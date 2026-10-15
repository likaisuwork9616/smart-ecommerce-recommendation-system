"""One new 104-column cell; existing 101-column topk10 is replay-only.

Only the numeric feature whitelist changes. All classifier parameters,
train-only imputers, categories, mature approval-day queries and bounded
uncalibrated margin score semantics match the frozen L2=100 topk10 baseline.
"""
from __future__ import annotations

import hashlib
import warnings

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts import delay_rank_focus as previous
from scripts.delay_budget_training import parameter_report
from scripts.delay_handover_features import (
    ADDED_FEATURES, FEATURE_SET, feature_columns, prepare_handover_input,
)
from scripts.train_delay_model import positive_probability


BASELINE = 'xgboost_rank_backlog_7_14d_l2_100_topk_10'
NEW_CANDIDATE = 'xgboost_rank_handover_104_l2_100_topk_10'
NEW_CANDIDATES = (NEW_CANDIDATE,)
ALL_CANDIDATES = (BASELINE, NEW_CANDIDATE)


def candidate_design(candidate):
    if candidate not in ALL_CANDIDATES:
        raise ValueError(f'Unknown handover contrast candidate: {candidate}')
    return {
        **previous.candidate_design(BASELINE),
        'baseline_candidate': BASELINE,
        'feature_variant': 'handover_104' if candidate == NEW_CANDIDATE else 'backlog_7_14d',
        'feature_package': 'handover_104' if candidate == NEW_CANDIDATE else 'backlog_7_14d',
        'original_feature_count': 101,
        'feature_count': 104 if candidate == NEW_CANDIDATE else 101,
        'added_features': list(ADDED_FEATURES) if candidate == NEW_CANDIDATE else [],
    }


def feature_names(candidate):
    candidate_design(candidate)
    return feature_columns() if candidate == NEW_CANDIDATE else previous.feature_names(BASELINE)


def prepare_input(frame, candidate):
    candidate_design(candidate)
    return prepare_handover_input(frame) if candidate == NEW_CANDIDATE else previous.prepare_input(frame, BASELINE)


def feature_set(candidate):
    candidate_design(candidate)
    return FEATURE_SET if candidate == NEW_CANDIDATE else previous.feature_set(BASELINE)


def make_candidate(candidate, seed=42, n_jobs=2):
    candidate_design(candidate)
    pipeline = previous.make_candidate(BASELINE, seed=seed, n_jobs=n_jobs)
    if candidate == NEW_CANDIDATE:
        numeric, categorical = feature_names(candidate)
        prep = pipeline.named_steps['preprocessor']
        old = prep.transformers
        prep.set_params(transformers=[
            (old[0][0], old[0][1], numeric),
            (old[1][0], old[1][1], categorical),
        ])
    return pipeline


def fit_version(train, scoring, candidate, seed=42, n_jobs=2):
    """Fit the new whitelist once; the caller supplies already mature rows."""
    design = candidate_design(candidate)
    if candidate != NEW_CANDIDATE:
        raise ValueError('Reuse the existing 101-column topk10 baseline artifact; do not refit it')
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
        raise ValueError('Invalid handover ranking score')
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
        'paired_feature_variant': 'handover_104',
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
