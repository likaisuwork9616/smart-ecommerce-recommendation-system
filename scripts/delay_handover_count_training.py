"""A 102-column count-only cell alongside replay-only 101/104 references.

Only the numeric whitelist changes. The carrier-event history contract is
reused verbatim; duration quantiles are excluded before either fit or score.
"""
from __future__ import annotations

import hashlib
import warnings

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts import delay_handover_training as full
from scripts import delay_rank_focus as previous
from scripts.delay_budget_training import parameter_report
from scripts.delay_engineering_features import _number
from scripts.delay_handover_features import build_handover_order_features
from scripts.train_delay_model import positive_probability


BASELINE = full.BASELINE
FULL = full.NEW_CANDIDATE
NEW_CANDIDATE = 'xgboost_rank_handover_count_102_l2_100_topk_10'
NEW_CANDIDATES = (NEW_CANDIDATE,)
ALL_CANDIDATES = (BASELINE, FULL, NEW_CANDIDATE)
ADDED_FEATURES = ['seller_handover_count_90d']
FEATURE_SET = 'seller_handover_count_90d_backlog_geo_7_14d_approval'


def candidate_design(candidate):
    if candidate not in ALL_CANDIDATES:
        raise ValueError(f'Unknown handover count contrast candidate: {candidate}')
    if candidate != NEW_CANDIDATE:
        return full.candidate_design(candidate)
    return {
        **previous.candidate_design(BASELINE),
        'baseline_candidate': BASELINE,
        'feature_variant': 'handover_count_102',
        'feature_package': 'handover_count_102',
        'original_feature_count': 101,
        'feature_count': 102,
        'added_features': list(ADDED_FEATURES),
    }


def feature_names(candidate):
    candidate_design(candidate)
    if candidate != NEW_CANDIDATE:
        return full.feature_names(candidate)
    numeric, categorical = previous.feature_names(BASELINE)
    return numeric + list(ADDED_FEATURES), categorical


def prepare_input(frame, candidate):
    candidate_design(candidate)
    if candidate != NEW_CANDIDATE:
        return full.prepare_input(frame, candidate)
    numeric, categorical = feature_names(candidate)
    required = numeric + categorical
    if set(required).difference(frame.columns):
        raise ValueError('Missing required handover count model features')
    result = frame[required].copy()
    for name in numeric:
        result[name] = _number(result, name)
    for name in categorical:
        result[name] = result[name].astype(object).where(result[name].notna(), np.nan)
    return result


def feature_set(candidate):
    candidate_design(candidate)
    return FEATURE_SET if candidate == NEW_CANDIDATE else full.feature_set(candidate)


def make_candidate(candidate, seed=42, n_jobs=2):
    candidate_design(candidate)
    if candidate != NEW_CANDIDATE:
        return full.make_candidate(candidate, seed=seed, n_jobs=n_jobs)
    pipeline = previous.make_candidate(BASELINE, seed=seed, n_jobs=n_jobs)
    numeric, categorical = feature_names(candidate)
    prep = pipeline.named_steps['preprocessor']
    old = prep.transformers
    prep.set_params(transformers=[
        (old[0][0], old[0][1], numeric),
        (old[1][0], old[1][1], categorical),
    ])
    return pipeline


def build_count_order_features(tables, geolocation=None):
    """Reuse frozen raw histories, then retain only count-model inputs."""
    enriched = build_handover_order_features(tables, geolocation)
    numeric, categorical = feature_names(NEW_CANDIDATE)
    return enriched[['order_id', 'order_purchase_timestamp', 'prediction_time'] + numeric + categorical]


def fit_version(train, scoring, candidate, seed=42, n_jobs=2):
    """Fit only the new whitelist using supplied mature approval-day rows."""
    design = candidate_design(candidate)
    if candidate != NEW_CANDIDATE:
        raise ValueError('Reuse the existing 101/104-column artifacts; do not refit them')
    if train.empty or train.order_id.isna().any() or train.order_id.duplicated().any():
        raise ValueError('Require nonempty unique training order identities')
    training = train.copy()
    training['prediction_time'] = pd.to_datetime(training.prediction_time, errors='raise')
    if training.prediction_time.isna().any():
        raise ValueError('Training approval times must be present')
    training = training.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    day_sizes = training.groupby(training.prediction_time.dt.normalize(), sort=True).size().to_numpy(dtype=int)
    pipeline = make_candidate(candidate, seed, n_jobs)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(training, candidate), training.delayed, classifier__group=day_sizes)
    pipeline.set_params(classifier__n_jobs=1)
    with threadpool_limits(limits=1):
        values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid handover count ranking score')
    classifier = pipeline.named_steps['classifier']
    labels = training.groupby(training.prediction_time.dt.normalize(), sort=True).delayed.agg(['size', 'sum'])
    numeric, categorical = feature_names(candidate)
    return pipeline, values, {
        'classifier_parameters': parameter_report(classifier.get_params(deep=False)),
        'ranker_parameters': parameter_report(classifier.ranker_.get_params(deep=False)),
        'training_jobs': n_jobs,
        'prediction_jobs': 1,
        'training_design': 'deadline_wait0',
        'paired_model_family': design['family'],
        'paired_backbone_candidate': BASELINE,
        'paired_feature_variant': 'handover_count_102',
        'baseline_candidate': BASELINE,
        'baseline_feature_count': 101,
        'feature_count': len(numeric) + len(categorical),
        'added_numeric_features': list(ADDED_FEATURES),
        'changed_classifier_parameters': [],
        'reg_lambda': 100.,
        'pair_method': 'topk',
        'pair_focus_k': 10,
        'training_objective': design['training_objective'],
        'training_order': 'prediction_time ascending, then order_id ascending; stable sort',
        'training_order_sha256': hashlib.sha256('\n'.join(training.order_id.astype(str)).encode('utf-8')).hexdigest(),
        'daily_training_groups': day_sizes.tolist(),
        'daily_training_query_counts': {
            'queries': len(labels),
            'mixed_label_queries': int(((labels['sum'] > 0) & (labels['sum'] < labels['size'])).sum()),
            'all_on_time_queries': int(labels['sum'].eq(0).sum()),
            'all_delayed_queries': int(labels['sum'].eq(labels['size']).sum()),
        },
        'daily_training_group_semantics': 'mature supplied training rows grouped by approval calendar day',
        'ranker_objective': 'rank:ndcg / binary gain [0,1] / topk 10 pair generation; fixed training k, not a daily fraction; separate daily floor(10% * N) alert policy',
        'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score',
        'fit_warnings': sorted({f'{warning.category.__name__}: {warning.message}' for warning in caught}),
    }
