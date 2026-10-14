"""Change only native LambdaRank top-k pair generation at fixed L2=100.

The existing k=20 versions are replay-only baselines. Fixed k is the number
of top positions used to generate training pairs, not the deployed daily
10% alert budget. ndcg@20 remains an unused evaluation configuration: no
evaluation set, early stopping, external weights or continuation is fitted.
"""
from __future__ import annotations

import hashlib
import numbers
import warnings

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts import delay_rank_regularization as previous
from scripts.delay_budget_training import parameter_report
from scripts.train_delay_model import positive_probability


BASELINES = ('xgboost_rank_geo_l2_100', 'xgboost_rank_backlog_7_14d_l2_100')
FOCUS_VALUES = (10, 20, 40)
NEW_CANDIDATES = tuple(
    f'{baseline}_topk_{value}'
    for baseline in BASELINES for value in FOCUS_VALUES if value != 20
)
ALL_CANDIDATES = (*BASELINES, *NEW_CANDIDATES)
CANDIDATE_DESIGNS = {
    candidate: {
        **previous.candidate_design(baseline),
        'baseline_candidate': baseline,
        'pair_focus_k': value,
        'reg_lambda': 100,
        'feature_package': previous.candidate_design(baseline)['feature_package'],
    }
    for baseline in BASELINES
    for candidate, value in (
        (baseline, 20),
        *((f'{baseline}_topk_{value}', value) for value in FOCUS_VALUES if value != 20),
    )
}


def candidate_design(candidate):
    if candidate not in CANDIDATE_DESIGNS:
        raise ValueError(f'Unknown ranking pair focus candidate: {candidate}')
    design = CANDIDATE_DESIGNS[candidate].copy()
    value = design['pair_focus_k']
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Integral)
            or value not in FOCUS_VALUES):
        raise ValueError('Ranking pair_focus_k must be one of the predeclared integers 10, 20, 40')
    if design['reg_lambda'] != 100:
        raise ValueError('The ranking pair focus contrast requires fixed reg_lambda=100')
    return design


def feature_names(candidate):
    return previous.feature_names(candidate_design(candidate)['baseline_candidate'])


def prepare_input(frame, candidate):
    return previous.prepare_input(frame, candidate_design(candidate)['baseline_candidate'])


def feature_set(candidate):
    return previous.feature_set(candidate_design(candidate)['baseline_candidate'])


def make_candidate(candidate, seed=42, n_jobs=2):
    """Keep the original L2=100 pipeline; change only the native top-k value."""
    design = candidate_design(candidate)
    pipeline = previous.make_candidate(design['baseline_candidate'], seed=seed, n_jobs=n_jobs)
    return pipeline.set_params(classifier__lambdarank_num_pair_per_sample=int(design['pair_focus_k']))


def fit_version(train, scoring, candidate, seed=42, n_jobs=2):
    """Fit a new fixed-k cell on the same sorted supplied mature day queries."""
    design = candidate_design(candidate)
    if candidate not in NEW_CANDIDATES:
        raise ValueError('Reuse the existing topk=20 baseline artifact; do not refit it')
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
        raise ValueError('Invalid ranking pair focus score')
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
        'pair_focus_parameter': 'lambdarank_num_pair_per_sample',
        'pair_focus_k': int(design['pair_focus_k']),
        'baseline_pair_focus_k': 20,
        'reg_lambda': 100.,
        'changed_classifier_parameters': ['lambdarank_num_pair_per_sample'],
        'training_objective': design['training_objective'],
        'training_order': 'prediction_time ascending, then order_id ascending; stable sort',
        'training_order_sha256': hashlib.sha256('\n'.join(training.order_id.astype(str)).encode('utf-8')).hexdigest(),
        'daily_training_groups': day_sizes.tolist(),
        'daily_training_query_counts': query_counts,
        'daily_training_group_semantics': 'mature supplied training rows grouped by approval calendar day',
        'ranker_objective': (
            f'rank:ndcg / binary gain [0,1] / topk {design["pair_focus_k"]} pair generation; '
            'fixed training k, not a daily fraction; separate daily floor(10% * N) alert policy'
        ),
        'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score',
        'fit_warnings': sorted({f'{warning.category.__name__}: {warning.message}' for warning in caught}),
    }
