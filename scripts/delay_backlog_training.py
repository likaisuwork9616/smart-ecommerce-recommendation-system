"""Fixed backbone comparisons for 7/14-day overdue backlog changes."""
from __future__ import annotations

import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

from scripts import delay_route_load_training as previous
from scripts.delay_budget_training import parameter_report
from scripts.delay_backlog_features import feature_columns, prepare_backlog_input, FEATURE_SET_DESIGNS, GEOGRAPHIC_FEATURE_SETS
from scripts.train_delay_model import positive_probability


BACKBONES = {
    'logistic_c1': ('logistic_load_regularization_c1', 'load'),
    'logistic_c0p01': ('logistic_load_regularization_c0p01', 'load'),
    'xgboost': ('xgboost_engineering_geo', 'geo'),
}
VARIANTS = ('7d', '14d', '7_14d')
CANDIDATE_DESIGNS = {
    f'{name}_backlog_{variant}': {'backbone_candidate': candidate, 'backbone': backbone,
                                  'variant': variant, 'family': name.split('_')[0]}
    for name, (candidate, backbone) in BACKBONES.items() for variant in VARIANTS
}
PREVIOUS_CANDIDATES = previous.ALL_CANDIDATES
NEW_CANDIDATES = tuple(CANDIDATE_DESIGNS)
ALL_CANDIDATES = (*PREVIOUS_CANDIDATES, *NEW_CANDIDATES)
PRIMARY_SELECTION = 'primary_without_dispatch'
SELECTION_GROUPS = {
    'previous_candidates': PREVIOUS_CANDIDATES,
    'new_backlog': NEW_CANDIDATES,
    PRIMARY_SELECTION: ALL_CANDIDATES,
}



def candidate_design(candidate):
    if candidate not in CANDIDATE_DESIGNS:
        raise ValueError(f'Unknown new backlog candidate: {candidate}')
    return CANDIDATE_DESIGNS[candidate].copy()


def feature_names(candidate):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.feature_names(candidate)
    design = candidate_design(candidate)
    return feature_columns(design['backbone'], design['variant'])


def prepare_input(frame, candidate):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.prepare_input(frame, candidate)
    design = candidate_design(candidate)
    return prepare_backlog_input(frame, design['backbone'], design['variant'])


def feature_set(candidate):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.feature_set(candidate)
    design = candidate_design(candidate)
    return f'backlog_{design["backbone"]}_{design["variant"]}_approval'


def make_candidate(candidate, seed=42, n_jobs=4):
    """Change only the declared feature columns, preserving the backbone pipeline."""
    if n_jobs < 1:
        raise ValueError('Require positive n_jobs')
    if candidate in PREVIOUS_CANDIDATES:
        return previous.make_candidate(candidate, seed, n_jobs)
    design = candidate_design(candidate)
    pipeline = previous.make_candidate(design['backbone_candidate'], seed, n_jobs)
    numeric, categorical = feature_names(candidate)
    prep = pipeline.named_steps['preprocessor']
    old = prep.transformers
    prep.set_params(transformers=[(old[0][0], old[0][1], numeric),
                                  (old[1][0], old[1][1], categorical)])
    return pipeline


def fit_version(train, scoring, candidate, seed=42, n_jobs=4):
    """Fit a new cell on sorted training rows and reject unconverged Logistic fits."""
    design = candidate_design(candidate)
    training = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    pipeline = make_candidate(candidate, seed, n_jobs)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(training, candidate), training.delayed)
    classifier = pipeline.named_steps['classifier']
    diagnostics = {}
    if design['family'] == 'logistic':
        iterations = np.asarray(classifier.n_iter_, dtype=int)
        n_iter_max = int(iterations.max())
        if n_iter_max >= classifier.max_iter or any(issubclass(w.category, ConvergenceWarning) for w in caught):
            raise ValueError(f'Backlog candidate {candidate} did not converge: '
                             f'n_iter_max={n_iter_max}, max_iter={classifier.max_iter}')
        coefficients, intercept = np.asarray(classifier.coef_), np.asarray(classifier.intercept_)
        if not np.isfinite(coefficients).all() or not np.isfinite(intercept).all():
            raise ValueError('Nonfinite fitted backlog coefficients')
        diagnostics = {'regularization': 'L2', 'regularization_c': float(classifier.C),
            'max_iter': int(classifier.max_iter), 'n_iter': iterations.tolist(),
            'n_iter_max': n_iter_max, 'converged': True,
            'coefficient_l2_norm': float(np.linalg.norm(coefficients)), 'intercept': intercept.tolist()}
    else:
        pipeline.set_params(classifier__n_jobs=1)
    with threadpool_limits(limits=1):
        values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid backlog score')
    return pipeline, values, {
        'classifier_parameters': parameter_report(classifier.get_params(deep=False)),
        'training_jobs': n_jobs, 'prediction_jobs': 1, **diagnostics,
        'paired_model_family': design['family'], 'paired_feature_variant': design['variant'],
        'paired_backbone_candidate': design['backbone_candidate'], 'training_design': 'deadline_wait0',
        'fit_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught}),
    }
