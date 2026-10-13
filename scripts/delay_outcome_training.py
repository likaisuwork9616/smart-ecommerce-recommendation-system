"""Fixed candidate contrasts for fresher, causally available training labels."""
from __future__ import annotations

import warnings

import numpy as np
from threadpoolctl import threadpool_limits

from scripts.compare_waiting_strategies import make_candidate as make_legacy
from scripts.delay_budget_training import parameter_report
from scripts.delay_pending_training import ALL_CANDIDATES as ROUND2_CANDIDATES
from scripts.delay_pending_training import (
    make_candidate as make_pending, fit_version as fit_pending,
    feature_names as pending_feature_names, prepare_input as pending_input,
)
from scripts.train_delay_model import positive_probability

BASE_MODELS = ('logistic_static', 'random_forest_route', 'lightgbm_pending')
DESIGNS = ('delivery_wait0', 'deadline_wait0', 'deadline_wait30')
NEW_CANDIDATES = tuple(f'{base}__{design}' for design in DESIGNS for base in BASE_MODELS)
ALL_CANDIDATES = (*ROUND2_CANDIDATES, *NEW_CANDIDATES)
SELECTION_GROUPS = {'round2_candidates': ROUND2_CANDIDATES,
    **{design: tuple(c for c in NEW_CANDIDATES if c.endswith(design)) for design in DESIGNS},
    'all_candidates': ALL_CANDIDATES}


def candidate_design(candidate):
    if candidate not in NEW_CANDIDATES:
        raise ValueError(f'Unknown outcome-clock candidate: {candidate}')
    base, design = candidate.split('__')
    return base, ('delivery' if design.startswith('delivery') else 'deadline'), (30 if design.endswith('30') else 0)


def feature_names(candidate):
    base = candidate_design(candidate)[0] if candidate in NEW_CANDIDATES else candidate
    return pending_feature_names(base)


def prepare_input(frame, candidate):
    base = candidate_design(candidate)[0] if candidate in NEW_CANDIDATES else candidate
    return pending_input(frame, base)


def make_candidate(candidate, seed=42, n_jobs=4):
    base, _, _ = candidate_design(candidate)
    if n_jobs < 1:
        raise ValueError('Require positive n_jobs')
    return make_pending(base, seed, n_jobs) if base == 'lightgbm_pending' else make_legacy(base, seed, n_jobs)


def fit_version(train, scoring, candidate, seed=42, n_jobs=4):
    base, _, _ = candidate_design(candidate)
    if base == 'lightgbm_pending':
        return fit_pending(train, scoring, base, seed, n_jobs)
    pipeline = make_candidate(candidate, seed, n_jobs)
    with threadpool_limits(limits=n_jobs), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        pipeline.fit(prepare_input(train, candidate), train.delayed)
        if base.startswith('random_forest'):
            pipeline.set_params(classifier__n_jobs=1)
        values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid outcome-clock score')
    return pipeline, values, {'classifier_parameters': parameter_report(pipeline.named_steps['classifier'].get_params(deep=False)),
        'training_jobs': n_jobs, 'prediction_jobs': 1 if base.startswith('random_forest') else n_jobs,
        'fit_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught})}
