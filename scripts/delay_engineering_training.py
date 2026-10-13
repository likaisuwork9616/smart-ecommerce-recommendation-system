"""Paired feature-family comparisons with a fixed fresh training design.

All twelve family/variant cells share deadline-clock, zero-wait monthly
training. The existing LightGBM/pending version is reused for the base cell;
the other eleven cells are newly fit. The primary historical selector excludes
dispatch deadlines because the export cannot establish their as-of history.
"""
from __future__ import annotations

import warnings

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits
from xgboost import XGBClassifier

from scripts import delay_budget_training as budget
from scripts import delay_outcome_training as outcome
from scripts import delay_pending_training as pending
from scripts.compare_waiting_strategies import make_candidate as make_legacy
from scripts.delay_engineering_features import (
    CATEGORICAL_FEATURES, DISPATCH_ENGINEERING_NUMERIC_FEATURES,
    ENGINEERING_NUMERIC_FEATURES, FEATURE_SETS, prepare_engineering_input,
)
from scripts.delay_pending_features import NUMERIC_FEATURES as BASE_NUMERIC_FEATURES
from scripts.train_delay_model import make_pipeline, positive_probability


FAMILIES = ('logistic', 'random_forest', 'lightgbm', 'xgboost')
VARIANTS = ('base', 'geo', 'dispatch')
REUSED_BASE_LIGHTGBM = 'lightgbm_pending__deadline_wait0'
PREVIOUS_CANDIDATES = outcome.ALL_CANDIDATES
BASE_CANDIDATES = tuple(
    REUSED_BASE_LIGHTGBM if family == 'lightgbm' else f'{family}_engineering_base'
    for family in FAMILIES
)
GEO_CANDIDATES = tuple(f'{family}_engineering_geo' for family in FAMILIES)
DISPATCH_CANDIDATES = tuple(f'{family}_engineering_dispatch' for family in FAMILIES)
NEW_CANDIDATES = tuple(candidate for candidate in BASE_CANDIDATES if candidate != REUSED_BASE_LIGHTGBM) + GEO_CANDIDATES + DISPATCH_CANDIDATES
ALL_CANDIDATES = (*PREVIOUS_CANDIDATES, *NEW_CANDIDATES)
PRIMARY_SELECTION = 'primary_without_dispatch'
SELECTION_GROUPS = {
    'prior_candidates': PREVIOUS_CANDIDATES,
    'base60_same_training': BASE_CANDIDATES,
    'geo_engineering_only': GEO_CANDIDATES,
    'dispatch_sensitivity_only': DISPATCH_CANDIDATES,
    PRIMARY_SELECTION: tuple(c for c in ALL_CANDIDATES if c not in DISPATCH_CANDIDATES),
    'all_including_dispatch': ALL_CANDIDATES,
}


def candidate_family_variant(candidate):
    """Return one of the twelve paired cells, rejecting unrelated old models."""
    if candidate == REUSED_BASE_LIGHTGBM:
        return 'lightgbm', 'base'
    if candidate not in NEW_CANDIDATES:
        raise ValueError(f'Candidate is not part of the paired feature contrast: {candidate}')
    family, variant = candidate.split('_engineering_')
    return family, variant


def feature_names(candidate):
    if candidate not in NEW_CANDIDATES:
        return outcome.feature_names(candidate)
    _, variant = candidate_family_variant(candidate)
    numeric = {'base': BASE_NUMERIC_FEATURES, 'geo': ENGINEERING_NUMERIC_FEATURES,
               'dispatch': DISPATCH_ENGINEERING_NUMERIC_FEATURES}[variant]
    return list(numeric), list(CATEGORICAL_FEATURES)


def prepare_input(frame, candidate):
    if candidate not in NEW_CANDIDATES:
        return outcome.prepare_input(frame, candidate)
    return prepare_engineering_input(frame, variant=candidate_family_variant(candidate)[1])


def feature_set(candidate):
    if candidate in NEW_CANDIDATES:
        variant = candidate_family_variant(candidate)[1]
        return FEATURE_SETS[variant]
    if candidate not in PREVIOUS_CANDIDATES:
        raise ValueError(f'Unknown engineering candidate: {candidate}')
    base = outcome.candidate_design(candidate)[0] if candidate in outcome.NEW_CANDIDATES else candidate
    if base.endswith('_pending'):
        return 'pending_seller_route_budget_90d'
    if base.endswith('_route'):
        return 'route_promise_90d'
    if base.endswith('_static'):
        return 'approval_static'
    return 'seller_route_budget_90d'


def make_candidate(candidate, seed=42, n_jobs=4):
    """Fixed family parameters, identical across each family's three variants."""
    if n_jobs < 1:
        raise ValueError('Require positive n_jobs')
    if candidate in PREVIOUS_CANDIDATES:
        if candidate in outcome.NEW_CANDIDATES:
            return outcome.make_candidate(candidate, seed, n_jobs)
        if candidate in pending.NEW_CANDIDATES:
            return pending.make_candidate(candidate, seed, n_jobs)
        if candidate in budget.NEW_CANDIDATES:
            return budget.make_candidate(candidate, seed, n_jobs)
        return make_legacy(candidate, seed, n_jobs)
    family, _ = candidate_family_variant(candidate)
    if family == 'logistic':
        classifier = LogisticRegression(class_weight='balanced', max_iter=2000, random_state=seed)
    elif family == 'random_forest':
        classifier = RandomForestClassifier(n_estimators=200, max_depth=14, min_samples_leaf=8,
            class_weight='balanced_subsample', random_state=seed, n_jobs=n_jobs)
    elif family == 'lightgbm':
        classifier = LGBMClassifier(n_estimators=400, learning_rate=.05, num_leaves=31,
            min_child_samples=60, subsample=.8, subsample_freq=1, colsample_bytree=.8,
            reg_lambda=10., random_state=seed, n_jobs=n_jobs, verbosity=-1,
            deterministic=True, force_col_wise=True)
    else:
        classifier = XGBClassifier(n_estimators=400, learning_rate=.05, max_depth=4,
            min_child_weight=10., subsample=.8, colsample_bytree=.8, reg_lambda=10.,
            objective='binary:logistic', eval_metric='logloss', tree_method='hist',
            random_state=seed, n_jobs=n_jobs)
    pipeline = make_pipeline(classifier, scale_numeric=family == 'logistic')
    numeric, categorical = feature_names(candidate)
    preprocessor = pipeline.named_steps['preprocessor']
    old = preprocessor.transformers
    preprocessor.set_params(transformers=[(old[0][0], old[0][1], numeric), (old[1][0], old[1][1], categorical)])
    return pipeline


def fit_version(train, scoring, candidate, seed=42, n_jobs=4):
    """Fit only new cells; training labels/features alone enter the pipeline."""
    if candidate not in NEW_CANDIDATES:
        raise ValueError('Only the eleven new engineering cells may be refit')
    family, variant = candidate_family_variant(candidate)
    training = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    pipeline = make_candidate(candidate, seed, n_jobs)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(training, candidate), training.delayed)
        if family != 'logistic':
            pipeline.set_params(classifier__n_jobs=1)
        with threadpool_limits(limits=1):
            values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid feature engineering scores')
    return pipeline, values, {
        'classifier_parameters': budget.parameter_report(pipeline.named_steps['classifier'].get_params(deep=False)),
        'training_jobs': n_jobs, 'prediction_jobs': 1,
        'paired_model_family': family, 'paired_feature_variant': variant,
        'training_design': 'deadline_wait0',
        'fit_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught}),
    }
