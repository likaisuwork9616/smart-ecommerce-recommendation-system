"""Fixed family parameters for geographic and workload feature ablations."""
import warnings

import numpy as np
from threadpoolctl import threadpool_limits

from scripts import delay_engineering_training as previous
from scripts.delay_ablation_features import VARIANT_FEATURES, FEATURE_SETS, prepare_ablation_input
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.delay_budget_training import parameter_report
from scripts.train_delay_model import positive_probability

FAMILIES = previous.FAMILIES
PREVIOUS_CANDIDATES = previous.SELECTION_GROUPS[previous.PRIMARY_SELECTION]
BASE_CANDIDATES = previous.BASE_CANDIDATES
FULL_CANDIDATES = previous.GEO_CANDIDATES
VARIANT_CANDIDATES = {variant: tuple(f'{family}_ablation_{variant}' for family in FAMILIES)
                      for variant in VARIANT_FEATURES}
NEW_CANDIDATES = tuple(c for values in VARIANT_CANDIDATES.values() for c in values)
ALL_CANDIDATES = (*PREVIOUS_CANDIDATES, *NEW_CANDIDATES)
PRIMARY_SELECTION = 'primary_without_dispatch'
SELECTION_GROUPS = {
    'previous_primary_candidates': PREVIOUS_CANDIDATES,
    'base60_same_training': BASE_CANDIDATES,
    'full83_same_training': FULL_CANDIDATES,
    **VARIANT_CANDIDATES,
    PRIMARY_SELECTION: ALL_CANDIDATES,
}


def candidate_design(candidate):
    if candidate not in NEW_CANDIDATES:
        raise ValueError(f'Unknown new ablation candidate: {candidate}')
    return tuple(candidate.split('_ablation_'))


def feature_names(candidate):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.feature_names(candidate)
    _, variant = candidate_design(candidate)
    return list(VARIANT_FEATURES[variant]), list(CATEGORICAL_FEATURES)


def prepare_input(frame, candidate):
    return (previous.prepare_input(frame, candidate) if candidate in PREVIOUS_CANDIDATES
            else prepare_ablation_input(frame, candidate_design(candidate)[1]))


def feature_set(candidate):
    return (previous.feature_set(candidate) if candidate in PREVIOUS_CANDIDATES
            else FEATURE_SETS[candidate_design(candidate)[1]])


def make_candidate(candidate, seed=42, n_jobs=4):
    if candidate in PREVIOUS_CANDIDATES:
        return previous.make_candidate(candidate, seed, n_jobs)
    family, _ = candidate_design(candidate)
    # Reuse the exact prior family constructor, including scaler/imputer/OHE.
    base = BASE_CANDIDATES[FAMILIES.index(family)]
    pipeline = previous.make_candidate(base, seed, n_jobs)
    numeric, categorical = feature_names(candidate)
    prep = pipeline.named_steps['preprocessor']
    old = prep.transformers
    prep.set_params(transformers=[(old[0][0], old[0][1], numeric), (old[1][0], old[1][1], categorical)])
    return pipeline


def fit_version(train, scoring, candidate, seed=42, n_jobs=4):
    family, variant = candidate_design(candidate)
    pipeline = make_candidate(candidate, seed, n_jobs)
    training = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(training, candidate), training.delayed)
        if family != 'logistic':
            pipeline.set_params(classifier__n_jobs=1)
        with threadpool_limits(limits=1):
            values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid ablation score')
    return pipeline, values, {'classifier_parameters': parameter_report(pipeline.named_steps['classifier'].get_params(deep=False)),
        'training_jobs': n_jobs, 'prediction_jobs': 1, 'paired_model_family': family,
        'paired_feature_variant': variant, 'training_design': 'deadline_wait0',
        'fit_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught})}
