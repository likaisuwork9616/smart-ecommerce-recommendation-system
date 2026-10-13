"""Predeclared L2 strength comparison for the existing 65-column load variant.

The seven new candidates share preprocessing, deadline-clock zero-wait training,
and a 10,000-iteration ceiling. Only C, the inverse regularization strength,
differs. Older candidates are replayed rather than refit.
"""
from __future__ import annotations

import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

from scripts import delay_ablation_training as previous
from scripts.delay_ablation_features import FEATURE_SETS, VARIANT_FEATURES, prepare_ablation_input
from scripts.delay_budget_training import parameter_report
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.train_delay_model import positive_probability


C_GRID = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)
MAX_ITER = 10000
REFERENCE_CANDIDATE = 'logistic_ablation_load_only'
PREVIOUS_CANDIDATES = previous.ALL_CANDIDATES
NEW_CANDIDATES = tuple(
    f'logistic_load_regularization_c{format(value, "g").replace(".", "p")}'
    for value in C_GRID
)
ALL_CANDIDATES = (*PREVIOUS_CANDIDATES, *NEW_CANDIDATES)
PRIMARY_SELECTION = 'primary_without_dispatch'
SELECTION_GROUPS = {
    'previous_candidates': PREVIOUS_CANDIDATES,
    'logistic_load_regularization': NEW_CANDIDATES,
    PRIMARY_SELECTION: ALL_CANDIDATES,
}
_C_VALUES = dict(zip(NEW_CANDIDATES, C_GRID, strict=True))


def candidate_c(candidate):
    """Return the declared C, rejecting old or undeclared candidate names."""
    if candidate not in _C_VALUES:
        raise ValueError(f'Unknown new regularization candidate: {candidate}')
    return _C_VALUES[candidate]


def feature_names(candidate):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.feature_names(candidate)
    candidate_c(candidate)
    return list(VARIANT_FEATURES['load_only']), list(CATEGORICAL_FEATURES)


def prepare_input(frame, candidate):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.prepare_input(frame, candidate)
    candidate_c(candidate)
    return prepare_ablation_input(frame, 'load_only')


def feature_set(candidate):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.feature_set(candidate)
    candidate_c(candidate)
    return FEATURE_SETS['load_only']


def make_candidate(candidate, seed=42, n_jobs=4):
    """Keep the prior effective L2/lbfgs constructor and 65-column contract."""
    if n_jobs < 1:
        raise ValueError('Require positive n_jobs')
    if candidate in PREVIOUS_CANDIDATES:
        return previous.make_candidate(candidate, seed, n_jobs)
    value = candidate_c(candidate)
    pipeline = previous.make_candidate(REFERENCE_CANDIDATE, seed, n_jobs)
    # In sklearn 1.9 the existing default penalty='deprecated', l1_ratio=0
    # represents L2. Retaining those defaults avoids changing the reference
    # solver contract or introducing a deprecated explicit penalty argument.
    return pipeline.set_params(classifier__C=value, classifier__max_iter=MAX_ITER)


def fit_version(train, scoring, candidate, seed=42, n_jobs=4):
    """Refit a new C cell on training rows only; reject nonconverged fits."""
    value = candidate_c(candidate)
    training = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    pipeline = make_candidate(candidate, seed, n_jobs)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(training, candidate), training.delayed)
    classifier = pipeline.named_steps['classifier']
    iterations = np.asarray(classifier.n_iter_, dtype=int)
    n_iter_max = int(iterations.max())
    converged = bool(n_iter_max < classifier.max_iter)
    if not converged or any(issubclass(w.category, ConvergenceWarning) for w in caught):
        raise ValueError(f'Regularization candidate {candidate} did not converge: '
                         f'n_iter_max={n_iter_max}, max_iter={classifier.max_iter}')
    with threadpool_limits(limits=1):
        values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid regularization score')
    coefficients = np.asarray(classifier.coef_, dtype=float)
    intercept = np.asarray(classifier.intercept_, dtype=float)
    if not np.isfinite(coefficients).all() or not np.isfinite(intercept).all():
        raise ValueError('Nonfinite fitted regularization coefficients')
    return pipeline, values, {
        'classifier_parameters': parameter_report(classifier.get_params(deep=False)),
        'training_jobs': n_jobs, 'prediction_jobs': 1,
        'paired_model_family': 'logistic', 'paired_feature_variant': 'load_only',
        'training_design': 'deadline_wait0', 'regularization': 'L2',
        'regularization_c': value, 'max_iter': int(classifier.max_iter),
        'n_iter': iterations.tolist(), 'n_iter_max': n_iter_max, 'converged': converged,
        'coefficient_l2_norm': float(np.linalg.norm(coefficients)),
        'intercept': intercept.tolist(),
        'fit_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught}),
    }
