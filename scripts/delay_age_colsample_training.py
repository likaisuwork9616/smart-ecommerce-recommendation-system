"""Fresh paired rankers with only colsample_bytree changed from .8 to1."""
from __future__ import annotations

import hashlib
import json
import warnings

import numpy as np
from threadpoolctl import threadpool_limits

from scripts import delay_age_seed_training as previous
from scripts.delay_budget_training import parameter_report
from scripts.train_delay_model import positive_probability

SEEDS, MATCHED = previous.SEEDS, previous.MATCHED
BASELINE, AGE = MATCHED
ADDED_FEATURES = previous.ADDED_FEATURES
COLSAMPLES = (.8, 1.)
feature_names = previous.feature_names
feature_set = previous.feature_set
prepare_input = previous.prepare_input
training_layout = previous.training_layout
validate_seed = previous.validate_seed


def _json_value(value):
    if isinstance(value, type):
        return value.__module__ + '.' + value.__qualname__
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [_json_value(item) for item in value]
    return parameter_report(value)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def preprocessing_specification(pipeline):
    prep = pipeline.named_steps['preprocessor']
    return {'remainder': prep.remainder, 'sparse_threshold': prep.sparse_threshold,
            'transformers': [{'name': name, 'columns': list(columns),
                'steps': [{'name': step_name, 'class': type(step).__module__ + '.' + type(step).__qualname__,
                           'parameters': _json_value(step.get_params(deep=False))}
                          for step_name, step in transformer.steps]}
                         for name, transformer, columns in prep.transformers]}


def make_candidate(candidate, seed, n_jobs=2):
    pipeline = previous.make_candidate(candidate, seed, n_jobs)
    if pipeline.named_steps['classifier'].colsample_bytree != .8:
        raise ValueError('Require the frozen .8 feature-subsampling reference')
    return pipeline.set_params(classifier__colsample_bytree=1.)


def verify_preprocessing(pipeline, train, candidate):
    """Verify learned statistics from unchanged train-only deterministic rules."""
    numeric, categorical = feature_names(candidate)
    prep = pipeline.named_steps['preprocessor']
    numeric_imputer = prep.named_transformers_['numeric'].named_steps['imputer']
    categorical_pipeline = prep.named_transformers_['categorical']
    categorical_imputer = categorical_pipeline.named_steps['imputer']
    onehot = categorical_pipeline.named_steps['onehot']
    prepared = prepare_input(train, candidate)
    values = prepared[numeric].to_numpy(dtype=float)
    expected_medians = [float(np.nanmedian(values[:, i])) if not np.isnan(values[:, i]).all() else 0.
                        for i in range(len(numeric))]
    np.testing.assert_array_equal(numeric_imputer.statistics_, expected_medians)
    np.testing.assert_array_equal(numeric_imputer.indicator_.features_, np.flatnonzero(np.isnan(values).any(axis=0)))
    expected_modes, expected_categories = [], []
    for name in categorical:
        observed = prepared[name].dropna()
        mode = observed.mode().iloc[0] if not observed.empty else 0
        imputed = prepared[name].fillna(mode).to_numpy()
        expected_modes.append(mode)
        expected_categories.append(np.unique(imputed).tolist())
    np.testing.assert_array_equal(categorical_imputer.statistics_, expected_modes)
    for found, expected in zip(onehot.categories_, expected_categories, strict=True):
        np.testing.assert_array_equal(found, expected)
    state = {'numeric_medians': expected_medians, 'numeric_indicator_indices': numeric_imputer.indicator_.features_.tolist(),
             'categorical_modes': expected_modes, 'onehot_categories': expected_categories,
             'transformed_feature_names': prep.get_feature_names_out().tolist()}
    return {'train_only_preprocessing_verified': True, 'preprocessing_state_sha256': canonical_sha256(state),
            'preprocessing_specification_sha256': canonical_sha256(preprocessing_specification(pipeline))}


def fit_version(train, scoring, candidate, seed, n_jobs=2):
    seed = validate_seed(seed)
    ordered, layout = training_layout(train)
    pipeline = make_candidate(candidate, seed, n_jobs)
    reference = previous.make_candidate(candidate, seed, n_jobs)
    if preprocessing_specification(pipeline) != preprocessing_specification(reference):
        raise ValueError('Only column subsampling may change; preprocessing rules changed')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(ordered, candidate), ordered.delayed,
                         classifier__group=np.asarray(layout['daily_training_groups'], dtype=int))
    pipeline.set_params(classifier__n_jobs=1)
    with threadpool_limits(limits=1):
        scores = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError('Invalid bounded uncalibrated ranking scores')
    numeric, categorical = feature_names(candidate)
    classifier, prep = pipeline.named_steps['classifier'], pipeline.named_steps['preprocessor']
    indicators = [numeric[int(i)] for i in prep.named_transformers_['numeric'].named_steps['imputer'].indicator_.features_]
    return pipeline, scores, {'seed': seed, 'candidate': candidate, 'colsample_bytree': 1.,
        'source_colsample_bytree': .8, 'changed_classifier_parameters_vs_source': ['colsample_bytree'],
        'training_design': 'deadline_wait0', 'training_jobs': n_jobs, 'prediction_jobs': 1,
        'classifier_parameters': parameter_report(classifier.get_params(deep=False)),
        'ranker_parameters': parameter_report(classifier.ranker_.get_params(deep=False)),
        'feature_count': len(numeric) + len(categorical),
        'added_numeric_features': list(ADDED_FEATURES) if candidate == AGE else [],
        'transformed_feature_count': len(prep.get_feature_names_out()),
        'numeric_missing_indicator_features': indicators,
        'age_missing_indicator_from_original_imputer': ADDED_FEATURES[0] in indicators,
        'manually_added_missingness_indicators': [], 'reg_lambda': 100., 'pair_method': 'topk', 'pair_focus_k': 10,
        'training_order': 'prediction_time ascending, then order_id ascending; stable sort', **layout,
        **verify_preprocessing(pipeline, ordered, candidate),
        'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score',
        'fit_warnings': sorted({f'{item.category.__name__}: {item.message}' for item in caught})}
