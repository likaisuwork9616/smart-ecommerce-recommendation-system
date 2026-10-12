"""Guard the temporal split, training-only preprocessing and prediction contract."""
import unittest

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from scripts.delay_features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from scripts.predict_delay import predict_features
from scripts.train_delay_model import (
    choose_threshold, chronological_split, make_pipeline, prepare_features,
)


def small_dataset():
    count = 100
    approval = pd.date_range('2018-01-01', periods=10, freq='D').repeat(10) + pd.Timedelta(hours=10)
    frame = pd.DataFrame({
        'order_id': [f'order_{i:03}' for i in range(count)],
        'order_purchase_timestamp': approval - pd.Timedelta(hours=1),
        'prediction_time': approval,
        'label_available_time': approval + pd.Timedelta(days=1),
        'delayed': np.arange(count) % 2,
    })
    for column in NUMERIC_FEATURES:
        frame[column] = np.arange(count, dtype=float)
    for column in CATEGORICAL_FEATURES:
        frame[column] = 'SP'
    return frame


class DelayTrainingTests(unittest.TestCase):
    def test_splits_keep_whole_days_and_labels_known_at_next_boundary(self):
        complete, splits, report = chronological_split(small_dataset())
        self.assertEqual(report['validation_start'], '2018-01-07T00:00:00')
        self.assertEqual(report['test_start'], '2018-01-09T00:00:00')
        self.assertEqual(complete.groupby(complete.prediction_time.dt.date).dataset_split.nunique().max(), 1)
        self.assertEqual([len(splits[name]) for name in ['train', 'validation', 'test']], [50, 10, 20])
        self.assertLess(splits['train'].label_available_time.max(), splits['validation'].prediction_time.min().normalize())
        self.assertLess(splits['validation'].label_available_time.max(), splits['test'].prediction_time.min().normalize())
        ids = [set(splits[name].order_id) for name in ['train', 'validation', 'test']]
        self.assertFalse(ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])

    def test_preprocessing_is_fitted_on_training_and_handles_unknown_category(self):
        frame = small_dataset()
        train = frame.iloc[:50].copy()
        train.loc[0, NUMERIC_FEATURES[0]] = np.nan
        pipeline = make_pipeline(LogisticRegression(max_iter=1000), scale_numeric=True)
        pipeline.fit(prepare_features(train), train.delayed)
        imputer = pipeline.named_steps['preprocessor'].named_transformers_['numeric'].named_steps['imputer']
        self.assertEqual(imputer.statistics_[0], 25.0)
        before = imputer.statistics_.copy()
        future = frame.iloc[-2:].copy()
        future[NUMERIC_FEATURES] = 99999.0
        future[CATEGORICAL_FEATURES] = 'unseen_state'
        self.assertTrue(np.isfinite(pipeline.predict_proba(prepare_features(future))).all())
        np.testing.assert_array_equal(before, imputer.statistics_)

    def test_f1_threshold_uses_the_supplied_validation_labels(self):
        threshold, policy = choose_threshold([0, 1, 1, 0], [.1, .6, .8, .7])
        self.assertEqual(threshold, .6)
        self.assertEqual(policy['data'], 'validation only')

    def test_prediction_ignores_outcomes_and_rejects_missing_feature_columns(self):
        frame = small_dataset()
        pipeline = make_pipeline(LogisticRegression(max_iter=1000), scale_numeric=True)
        pipeline.fit(prepare_features(frame), frame.delayed)
        artifact = dict(format_version=1, pipeline=pipeline, threshold=.6,
                        selected_model='test_logistic', feature_names=NUMERIC_FEATURES + CATEGORICAL_FEATURES,
                        numeric_features=NUMERIC_FEATURES, categorical_features=CATEGORICAL_FEATURES)
        before = predict_features(artifact, frame)
        changed = frame.assign(delayed=1 - frame.delayed, label_available_time=pd.Timestamp('2099-01-01'))
        pd.testing.assert_frame_equal(before, predict_features(artifact, changed))
        self.assertTrue((before.predicted_delayed == (before.delay_score >= .6)).all())
        with self.assertRaisesRegex(ValueError, 'Missing required feature columns'):
            predict_features(artifact, frame.drop(columns=NUMERIC_FEATURES[0]))


if __name__ == '__main__':
    unittest.main()
