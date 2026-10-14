"""Daily-ranking contrasts that change only XGBoost L2 regularization.

The two lambda=10 ranking baselines are existing artifacts and must be
replayed, not refit. New lambda=1/100 cells reuse their feature contracts,
preprocessing, mature day queries and strictly monotone score interface.
"""
from __future__ import annotations

import hashlib
import numbers
import warnings

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts import delay_objective_training as previous
from scripts.delay_budget_training import parameter_report
from scripts.train_delay_model import positive_probability


BASELINES = previous.NEW_CANDIDATES
L2_VALUES = (1, 10, 100)
NEW_CANDIDATES = tuple(
    f'{baseline}_l2_{value}'
    for baseline in BASELINES for value in L2_VALUES if value != 10
)
ALL_CANDIDATES = (*BASELINES, *NEW_CANDIDATES)
CANDIDATE_DESIGNS = {
    candidate: {
        **previous.candidate_design(baseline),
        'baseline_candidate': baseline,
        'reg_lambda': value,
        'feature_package': previous.candidate_design(baseline)['feature_variant'],
    }
    for baseline in BASELINES
    for candidate, value in (
        (baseline, 10),
        *((f'{baseline}_l2_{value}', value) for value in L2_VALUES if value != 10),
    )
}


def candidate_design(candidate):
    if candidate not in CANDIDATE_DESIGNS:
        raise ValueError(f'Unknown ranking regularization candidate: {candidate}')
    design = CANDIDATE_DESIGNS[candidate].copy()
    value = design['reg_lambda']
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real)
            or not np.isfinite(value) or value not in L2_VALUES):
        raise ValueError('Ranking reg_lambda must be one of the predeclared positive values 1, 10, 100')
    return design


def feature_names(candidate):
    return previous.feature_names(candidate_design(candidate)['baseline_candidate'])


def prepare_input(frame, candidate):
    return previous.prepare_input(frame, candidate_design(candidate)['baseline_candidate'])


def feature_set(candidate):
    return previous.feature_set(candidate_design(candidate)['baseline_candidate'])


def make_candidate(candidate, seed=42, n_jobs=2):
    """Reuse the complete prior pipeline and set only classifier.reg_lambda."""
    design = candidate_design(candidate)
    pipeline = previous.make_candidate(design['baseline_candidate'], seed=seed, n_jobs=n_jobs)
    return pipeline.set_params(classifier__reg_lambda=float(design['reg_lambda']))


def fit_version(train, scoring, candidate, seed=42, n_jobs=2):
    """Fit a new L2 cell once on the same sorted supplied mature training rows.

    This intentionally mirrors the original objective experiment's fitting
    procedure without changing that frozen experiment or fitting its baselines.
    The caller supplies already mature rows; validation outcomes never enter fit.
    """
    design = candidate_design(candidate)
    if candidate not in NEW_CANDIDATES:
        raise ValueError('Reuse the existing reg_lambda=10 baseline artifact; do not refit it')
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
        raise ValueError('Invalid ranking regularization score')
    classifier = pipeline.named_steps['classifier']
    daily_labels = training.groupby(training.prediction_time.dt.normalize(), sort=True).delayed.agg(['size', 'sum'])
    query_counts = {
        'queries': len(daily_labels),
        'mixed_label_queries': int(((daily_labels['sum'] > 0) & (daily_labels['sum'] < daily_labels['size'])).sum()),
        'all_on_time_queries': int(daily_labels['sum'].eq(0).sum()),
        'all_delayed_queries': int(daily_labels['sum'].eq(daily_labels['size']).sum()),
    }
    return pipeline, values, {
        'classifier_parameters': parameter_report(classifier.get_params(deep=False)),
        'ranker_parameters': parameter_report(classifier.ranker_.get_params(deep=False)),
        'training_jobs': n_jobs,
        'prediction_jobs': 1,
        'training_design': 'deadline_wait0',
        'paired_model_family': design['family'],
        'paired_backbone_candidate': design['backbone_candidate'],
        'paired_feature_variant': design['feature_variant'],
        'baseline_candidate': design['baseline_candidate'],
        'regularization_parameter': 'reg_lambda',
        'reg_lambda': float(design['reg_lambda']),
        'baseline_reg_lambda': 10.,
        'changed_classifier_parameters': ['reg_lambda'],
        'training_objective': design['training_objective'],
        'training_order': 'prediction_time ascending, then order_id ascending; stable sort',
        'training_order_sha256': hashlib.sha256('\n'.join(training.order_id.astype(str)).encode('utf-8')).hexdigest(),
        'daily_training_groups': day_sizes.tolist(),
        'daily_training_query_counts': query_counts,
        'daily_training_group_semantics': 'mature supplied training rows grouped by approval calendar day',
        'ranker_objective': 'rank:ndcg / binary gain [0,1] / topk 20 pair generation; separate daily floor(10% * N) alert policy',
        'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score',
        'fit_warnings': sorted({f'{warning.category.__name__}: {warning.message}' for warning in caught}),
    }
