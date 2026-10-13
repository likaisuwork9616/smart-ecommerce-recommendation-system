"""Guard decision isolation and the route experiment's inference contract."""
import copy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.compare_waiting_strategies import (
    CANDIDATES, feature_names, make_candidate, prepare_input, run_experiment, select_candidate,
)
from scripts.delay_features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from scripts.delay_route_features import ROUTE_CATEGORICAL_FEATURES, ROUTE_NUMERIC_FEATURES
from scripts.predict_delay import build_inference_features, predict_features


def feature_frame(rows=96):
    numeric, categorical = feature_names('logistic_route')
    frame = pd.DataFrame({name: np.arange(rows, dtype=float) % (11 + index)
                          for index, name in enumerate(numeric)})
    for name in categorical:
        frame[name] = np.where(np.arange(rows) % 3, 'SP', 'RJ')
    frame['order_id'] = [f'order-{i}' for i in range(rows)]
    frame['delayed'] = np.arange(rows) % 2
    frame['label_available_time'] = pd.Timestamp('2018-01-01')
    return frame


class WaitingExperimentTests(unittest.TestCase):
    def test_feature_contract_and_whitelist_drop_labels_and_other_history(self):
        frame = feature_frame()
        frame['future_delivery_delay'] = 999.0
        frame['seller_delay_rate_90d'] = .7
        for candidate in CANDIDATES:
            numeric, categorical = feature_names(candidate)
            expected_numeric = NUMERIC_FEATURES + (ROUTE_NUMERIC_FEATURES if candidate.endswith('_route') else [])
            expected_categorical = CATEGORICAL_FEATURES + (ROUTE_CATEGORICAL_FEATURES if candidate.endswith('_route') else [])
            self.assertEqual(numeric, expected_numeric)
            self.assertEqual(categorical, expected_categorical)
            self.assertEqual(list(prepare_input(frame, candidate)), numeric + categorical)
            self.assertFalse({'delayed', 'label_available_time', 'order_id', 'future_delivery_delay',
                              'seller_delay_rate_90d'}.intersection(numeric + categorical))
            self.assertEqual(len(set(numeric + categorical)), len(numeric + categorical))

    def test_route_imputation_is_learned_from_train_only_and_inference_ignores_outcomes(self):
        frame = feature_frame()
        column = ROUTE_NUMERIC_FEATURES[0]
        frame[column] = np.arange(len(frame), dtype=float)
        train = frame.iloc[:40].copy()
        train.loc[0, column] = np.nan
        pipeline = make_candidate('logistic_route', seed=42, n_jobs=1)
        pipeline.fit(prepare_input(train, 'logistic_route'), train.delayed)
        numeric, categorical = feature_names('logistic_route')
        imputer = pipeline.named_steps['preprocessor'].named_transformers_['numeric'].named_steps['imputer']
        self.assertEqual(imputer.statistics_.shape, (25,))
        self.assertEqual(imputer.statistics_[numeric.index(column)], 20.0)
        before = imputer.statistics_.copy()
        artifact = dict(format_version=1, feature_set='route_promise_90d', pipeline=pipeline,
                        threshold=.5, feature_names=numeric + categorical,
                        numeric_features=numeric, categorical_features=categorical)
        future = frame.iloc[60:].copy()
        future[ROUTE_NUMERIC_FEATURES] = 100000.0
        first = predict_features(artifact, future)
        changed = future.assign(delayed=1 - future.delayed,
                                label_available_time=pd.Timestamp('2099-01-01'))
        pd.testing.assert_frame_equal(first, predict_features(artifact, changed))
        np.testing.assert_array_equal(before, imputer.statistics_)
        self.assertTrue(np.isfinite(first.delay_score).all())

    def test_model_choice_uses_validation_and_stable_tie_break(self):
        results = {name: {'validation': {
            'predicted_positive_rows': 30,
            'confusion_matrix': [[100, 21], [20, 9]],
            'average_precision': .5,
        }} for name in CANDIDATES}
        self.assertEqual(select_candidate(results), CANDIDATES[0])
        results['logistic_route']['validation']['predicted_positive_rows'] = 29
        results['random_forest_static']['evaluation'] = {'precision': 1.0}
        results['logistic_route']['evaluation'] = {'precision': 0.0}
        self.assertEqual(select_candidate(results), 'logistic_route')
        changed = copy.deepcopy(results)
        for value in changed.values():
            value['evaluation'] = {'entirely_changed_eval': True}
        self.assertEqual(select_candidate(changed), 'logistic_route')

    def test_changing_evaluation_outcomes_preserves_fit_threshold_selection_and_scores(self):
        frame = feature_frame()
        splits = {'train': frame.iloc[:40].copy(), 'validation': frame.iloc[40:68].copy(),
                  'evaluation': frame.iloc[68:].copy()}
        changed = {name: part.copy() for name, part in splits.items()}
        changed['evaluation']['delayed'] = 1 - changed['evaluation']['delayed']
        changed['evaluation']['label_available_time'] = pd.Timestamp('2099-01-01')
        result, pipelines, scores = run_experiment(splits, min_recall=.30, seed=42, n_jobs=2)
        altered, _, altered_scores = run_experiment(changed, min_recall=.30, seed=42, n_jobs=2)
        self.assertEqual(result['selected_model'], altered['selected_model'])
        for candidate in CANDIDATES:
            self.assertEqual(result['models'][candidate]['threshold'], altered['models'][candidate]['threshold'])
            self.assertEqual(result['models'][candidate]['validation'], altered['models'][candidate]['validation'])
            self.assertGreaterEqual(result['models'][candidate]['validation']['recall'], .30)
            np.testing.assert_array_equal(scores[candidate], altered_scores[candidate])
            numeric, categorical = feature_names(candidate)
            artifact = dict(format_version=1, pipeline=pipelines[candidate],
                            threshold=result['models'][candidate]['threshold'],
                            feature_names=numeric + categorical, numeric_features=numeric,
                            categorical_features=categorical)
            inference = predict_features(artifact, splits['evaluation'])
            np.testing.assert_array_equal(scores[candidate], inference.delay_score)
            if candidate.startswith('random_forest'):
                self.assertEqual(pipelines[candidate].named_steps['classifier'].n_jobs, 1)
                repeated = predict_features(artifact, splits['validation'])
                pd.testing.assert_frame_equal(repeated, predict_features(artifact, splits['validation']))

    def test_raw_route_artifact_dispatches_to_route_builder(self):
        expected = pd.DataFrame({'order_id': ['query'], 'state_route': ['SP>RJ']})
        tables = {'sentinel': object()}
        with patch('scripts.delay_route_features.build_route_order_features', return_value=expected) as builder:
            result = build_inference_features({'feature_set': 'route_promise_90d'}, tables)
        builder.assert_called_once_with(tables)
        pd.testing.assert_frame_equal(result, expected)


if __name__ == '__main__':
    unittest.main()
