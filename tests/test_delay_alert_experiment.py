"""Check selection isolation and inference's expanded feature contract."""
import copy
import unittest

import numpy as np
import pandas as pd

from scripts.delay_history_features import HISTORY_NUMERIC_FEATURES
from scripts.improve_delay_alerts import (
    CANDIDATES, feature_names, make_candidate, prepare_input, run_experiment, select_candidate,
)
from scripts.predict_delay import build_inference_features, predict_features


class AlertExperimentTests(unittest.TestCase):
    def test_selection_uses_validation_alerts_even_when_evaluation_prefers_another_model(self):
        results = {}
        for index, name in enumerate(CANDIDATES):
            results[name] = {
                'validation': {'balanced': {
                    'predicted_positive_rows': 100 + index,
                    'confusion_matrix': [[100, 70 + index], [70, 30]],
                    'average_precision': .2,
                }},
                'evaluation': {'balanced': {'precision': index / 10}},
            }
        selected = select_candidate(results)
        self.assertEqual(selected, 'random_forest_static')
        changed = copy.deepcopy(results)
        for value in changed.values():
            value['evaluation'] = {'completely_different_outcomes': True}
        self.assertEqual(select_candidate(changed), selected)

    def test_history_pipeline_learns_history_imputation_only_from_training(self):
        frame = pd.DataFrame({name: np.arange(100, dtype=float) for name in feature_names(False)[0]})
        frame[feature_names(False)[1][-4:]] = 'SP'
        frame['delayed'] = np.arange(100) % 2
        frame['label_available_time'] = pd.Timestamp('2018-01-01')
        for index, name in enumerate(HISTORY_NUMERIC_FEATURES):
            frame[name] = np.arange(len(frame), dtype=float) + index * 10
        training = frame.iloc[:50].copy()
        training.loc[0, HISTORY_NUMERIC_FEATURES[0]] = np.nan
        pipeline = make_candidate('logistic_history', seed=42, n_jobs=1)
        pipeline.fit(prepare_input(training, True), training.delayed)
        imputer = pipeline.named_steps['preprocessor'].named_transformers_['numeric'].named_steps['imputer']
        self.assertEqual(imputer.statistics_.shape, (27,))
        self.assertEqual(imputer.statistics_[17], 25.0)
        before = imputer.statistics_.copy()
        numeric, names = feature_names(True)
        artifact = dict(format_version=1, pipeline=pipeline, threshold=.5,
                        feature_names=names, numeric_features=numeric,
                        categorical_features=names[-4:])
        future = frame.iloc[-3:].copy()
        future[HISTORY_NUMERIC_FEATURES] = 99999.0
        predictions = predict_features(artifact, future)
        self.assertTrue(np.isfinite(predictions.delay_score).all())
        np.testing.assert_array_equal(before, imputer.statistics_)
        changed = future.assign(delayed=1 - future.delayed, label_available_time=pd.Timestamp('2099-01-01'))
        pd.testing.assert_frame_equal(predictions, predict_features(artifact, changed))

    def test_unknown_raw_feature_versions_fail_instead_of_silently_using_static_features(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported feature set'):
            build_inference_features({'feature_set': 'unknown_future_version'}, {})

    def test_saved_forest_scoring_is_repeatable_at_the_selected_boundary(self):
        frame = pd.DataFrame({name: np.arange(60, dtype=float) for name in feature_names(True)[0]})
        frame[feature_names(True)[1][-4:]] = 'SP'
        frame['delayed'] = np.arange(60) % 2
        splits = dict(train=frame.iloc[:30], validation=frame.iloc[30:46], evaluation=frame.iloc[46:])
        result, pipelines = run_experiment(splits, min_recall=.3, seed=42, n_jobs=2)
        pipeline = pipelines['random_forest_static']
        self.assertEqual(pipeline.named_steps['classifier'].n_jobs, 1)
        values = prepare_input(splits['validation'], False)
        threshold = result['models']['random_forest_static']['thresholds']['balanced']
        first = pipeline.predict_proba(values)[:, 1]
        for _ in range(4):
            repeated = pipeline.predict_proba(values)[:, 1]
            np.testing.assert_array_equal(first, repeated)
            np.testing.assert_array_equal(first >= threshold, repeated >= threshold)


if __name__ == '__main__':
    unittest.main()
