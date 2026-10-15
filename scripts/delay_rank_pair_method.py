"""Change only native LambdaRank pairing from topk to mean at fixed value 10.

The existing 101-column, L2=100, topk=10 versions are replay-only baselines.
The numerical pair parameter stays 10, but under mean it specifies sampled
pairs per row rather than a fixed top-position focus. Native normalization
settings are unchanged; their built-in behavior can depend on the method.
Neither method implements the separate daily floor(10% * N) alert policy.
"""
from __future__ import annotations

import hashlib
import numbers
import warnings

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts import delay_rank_focus as previous
from scripts.delay_budget_training import parameter_report
from scripts.train_delay_model import positive_probability


BASELINE = 'xgboost_rank_backlog_7_14d_l2_100_topk_10'
NEW_CANDIDATE = 'xgboost_rank_backlog_7_14d_l2_100_mean_10'
NEW_CANDIDATES = (NEW_CANDIDATE,)
ALL_CANDIDATES = (BASELINE, NEW_CANDIDATE)
_BASE_DESIGN = {
    key: value for key, value in previous.candidate_design(BASELINE).items()
    if key != 'pair_focus_k'
}
CANDIDATE_DESIGNS = {
    candidate: {
        **_BASE_DESIGN,
        'baseline_candidate': BASELINE,
        'pair_method': method,
        'num_pair_parameter': 10,
        'reg_lambda': 100,
    }
    for candidate, method in ((BASELINE, 'topk'), (NEW_CANDIDATE, 'mean'))
}


def candidate_design(candidate):
    if candidate not in CANDIDATE_DESIGNS:
        raise ValueError(f'Unknown ranking pair method candidate: {candidate}')
    design = CANDIDATE_DESIGNS[candidate].copy()
    value = design['num_pair_parameter']
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Integral)
            or value != 10):
        raise ValueError('The pair method contrast requires fixed integer num_pair_parameter=10')
    regularization = design['reg_lambda']
    if (isinstance(regularization, (bool, np.bool_))
            or not isinstance(regularization, numbers.Real)
            or not np.isfinite(regularization) or regularization != 100):
        raise ValueError('The pair method contrast requires fixed reg_lambda=100')
    expected_method = 'topk' if candidate == BASELINE else 'mean'
    if design['pair_method'] != expected_method or design['baseline_candidate'] != BASELINE:
        raise ValueError('Require the declared topk=10 baseline and mean=10 contrast')
    return design


def feature_names(candidate):
    candidate_design(candidate)
    return previous.feature_names(BASELINE)


def prepare_input(frame, candidate):
    candidate_design(candidate)
    return previous.prepare_input(frame, BASELINE)


def feature_set(candidate):
    candidate_design(candidate)
    return previous.feature_set(BASELINE)


def make_candidate(candidate, seed=42, n_jobs=2):
    """Reuse the complete topk=10 pipeline and set only the pair method."""
    design = candidate_design(candidate)
    pipeline = previous.make_candidate(BASELINE, seed=seed, n_jobs=n_jobs)
    return pipeline.set_params(classifier__lambdarank_pair_method=design['pair_method'])


def fit_version(train, scoring, candidate, seed=42, n_jobs=2):
    """Fit the mean cell on the identical supplied mature, sorted day queries."""
    design = candidate_design(candidate)
    if candidate not in NEW_CANDIDATES:
        raise ValueError('Reuse the existing topk=10 baseline artifact; do not refit it')
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
        raise ValueError('Invalid ranking pair method score')
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
        'baseline_candidate': BASELINE,
        'pair_method': design['pair_method'],
        'baseline_pair_method': 'topk',
        'pair_parameter_name': 'lambdarank_num_pair_per_sample',
        'num_pair_parameter': 10,
        'baseline_num_pair_parameter': 10,
        'pair_parameter_semantics': 'mean: sampled pairs per row; 10 is not a top-position cutoff or daily alert fraction',
        'normalization_semantics': 'native normalization settings unchanged; built-in normalization behavior depends on pair method',
        'reg_lambda': 100.,
        'changed_classifier_parameters': ['lambdarank_pair_method'],
        'training_objective': design['training_objective'],
        'training_order': 'prediction_time ascending, then order_id ascending; stable sort',
        'training_order_sha256': hashlib.sha256('\n'.join(training.order_id.astype(str)).encode('utf-8')).hexdigest(),
        'daily_training_groups': day_sizes.tolist(),
        'daily_training_query_counts': query_counts,
        'daily_training_group_semantics': 'mature supplied training rows grouped by approval calendar day',
        'ranker_objective': (
            'rank:ndcg / binary gain [0,1] / mean pair generation, numerical parameter 10 unchanged; '
            'separate daily floor(10% * N) alert policy'
        ),
        'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score',
        'fit_warnings': sorted({f'{warning.category.__name__}: {warning.message}' for warning in caught}),
    }
