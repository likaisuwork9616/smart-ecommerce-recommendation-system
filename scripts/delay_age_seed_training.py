"""Refit both frozen feature packages with five fixed paired random seeds.

No classifier setting besides random_state changes. Baseline101 and age102
use the same mature, sorted training rows and complete scoring-day cohorts.
"""
from __future__ import annotations

import hashlib
import numbers
import warnings

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts import delay_unobserved_handover_age_training as previous
from scripts.delay_budget_training import parameter_report
from scripts.train_delay_model import positive_probability

SEEDS = (11, 29, 42, 73, 101)
BASELINE, AGE = previous.ALL_CANDIDATES
MATCHED = (BASELINE, AGE)
ADDED_FEATURES = previous.ADDED_FEATURES
feature_names = previous.feature_names
feature_set = previous.feature_set
prepare_input = previous.prepare_input


def validate_seed(seed):
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, numbers.Integral) or seed not in SEEDS:
        raise ValueError('Require one of the five fixed paired seeds')
    return int(seed)


def make_candidate(candidate, seed, n_jobs=2):
    seed = validate_seed(seed)
    if candidate not in MATCHED:
        raise ValueError('Require frozen baseline101 or age102')
    return previous.make_candidate(candidate, seed=seed, n_jobs=n_jobs)


def training_layout(train):
    if train.empty or train.order_id.isna().any() or train.order_id.duplicated().any():
        raise ValueError('Require nonempty unique mature training identities')
    ordered = train.copy()
    ordered['prediction_time'] = pd.to_datetime(ordered.prediction_time, errors='raise')
    if ordered.prediction_time.isna().any() or not ordered.delayed.isin([0, 1]).all():
        raise ValueError('Require valid training approval times and binary outcomes')
    ordered = ordered.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    groups = ordered.groupby(ordered.prediction_time.dt.normalize(), sort=True).delayed.agg(['size', 'sum'])
    return ordered, {
        'training_order_sha256': hashlib.sha256('\n'.join(ordered.order_id.astype(str)).encode('utf-8')).hexdigest(),
        'training_labels_sha256': hashlib.sha256(ordered.delayed.to_numpy(dtype=np.int8).tobytes()).hexdigest(),
        'daily_training_groups': groups['size'].astype(int).tolist(),
        'daily_training_query_counts': {'queries': len(groups),
            'mixed_label_queries': int(((groups['sum'] > 0) & (groups['sum'] < groups['size'])).sum()),
            'all_on_time_queries': int(groups['sum'].eq(0).sum()),
            'all_delayed_queries': int(groups['sum'].eq(groups['size']).sum())},
    }


def fit_version(train, scoring, candidate, seed, n_jobs=2):
    """A fresh fit for either package, including seed42; no eval set is used."""
    seed = validate_seed(seed)
    if candidate not in MATCHED:
        raise ValueError('Require frozen baseline101 or age102')
    training, layout = training_layout(train)
    pipeline = make_candidate(candidate, seed, n_jobs=n_jobs)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(training, candidate), training.delayed,
                         classifier__group=np.asarray(layout['daily_training_groups'], dtype=int))
    pipeline.set_params(classifier__n_jobs=1)
    with threadpool_limits(limits=1):
        scores = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError('Invalid bounded uncalibrated margin scores')
    numeric, categorical = feature_names(candidate)
    classifier, preprocessor = pipeline.named_steps['classifier'], pipeline.named_steps['preprocessor']
    imputer = preprocessor.named_transformers_['numeric'].named_steps['imputer']
    indicator_features = [numeric[int(index)] for index in imputer.indicator_.features_]
    return pipeline, scores, {
        'seed': seed, 'candidate': candidate, 'training_design': 'deadline_wait0',
        'training_jobs': n_jobs, 'prediction_jobs': 1,
        'classifier_parameters': parameter_report(classifier.get_params(deep=False)),
        'ranker_parameters': parameter_report(classifier.ranker_.get_params(deep=False)),
        'feature_count': len(numeric) + len(categorical),
        'added_numeric_features': list(ADDED_FEATURES) if candidate == AGE else [],
        'transformed_feature_count': len(preprocessor.get_feature_names_out()),
        'numeric_missing_indicator_features': indicator_features,
        'age_missing_indicator_from_original_imputer': ADDED_FEATURES[0] in indicator_features,
        'manually_added_missingness_indicators': [],
        'reg_lambda': 100., 'pair_method': 'topk', 'pair_focus_k': 10,
        'changed_classifier_parameters_vs_original': ['random_state'] if seed != 42 else [],
        'training_order': 'prediction_time ascending, then order_id ascending; stable sort',
        **layout,
        'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score',
        'fit_warnings': sorted({f'{item.category.__name__}: {item.message}' for item in caught}),
    }
