"""The pending-count ablation changes one input, never the training contract."""
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_unobserved_handover_training as training
from scripts import delay_objective_training as objective
from scripts import delay_rank_focus as previous
from scripts.predict_delay import predict_features
from tests.test_delay_handover_training import frame as original_frame
from tests.test_delay_objective_training import RecordingRanker


def frame(month, count=60):
    result = original_frame(month, count)
    result[training.ADDED_FEATURES[0]] = np.arange(len(result)) % 9
    return result


class UnobservedHandoverTrainingTests(unittest.TestCase):
    def test_only_whitelist_differs_from_frozen101_and_parameters_are_identical(self):
        self.assertEqual(training.ALL_CANDIDATES, (training.BASELINE, training.NEW_CANDIDATE))
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        old_numeric, old_categorical = previous.feature_names(training.BASELINE)
        self.assertEqual(numeric, old_numeric + list(training.ADDED_FEATURES))
        self.assertEqual(categorical, old_categorical)
        self.assertEqual((len(numeric), len(categorical)), (94, 8))
        self.assertEqual(list(training.ADDED_FEATURES), ['seller_unobserved_handover_pending_count_90d'])
        baseline = training.make_candidate(training.BASELINE, seed=37)
        candidate = training.make_candidate(training.NEW_CANDIDATE, seed=37)
        params = baseline.named_steps['classifier'].get_params(deep=False)
        self.assertEqual(candidate.named_steps['classifier'].get_params(deep=False), params)
        self.assertEqual((params['reg_lambda'], params['lambdarank_pair_method'],
                          params['lambdarank_num_pair_per_sample'], params['n_estimators']), (100., 'topk', 10, 400))
        for left, right in zip(candidate.named_steps['preprocessor'].transformers,
                               baseline.named_steps['preprocessor'].transformers, strict=True):
            for (ln, ls), (rn, rs) in zip(left[1].steps, right[1].steps, strict=True):
                self.assertEqual((ln, type(ls), ls.get_params(deep=False)),
                                 (rn, type(rs), rs.get_params(deep=False)))

    def test_inputs_exclude_completed_count_age_labels_status_and_future_events(self):
        data = frame('2017-09')
        excluded = ['seller_handover_count_90d', 'seller_handover_p50_hours_90d',
                    'seller_handover_p90_hours_90d', 'seller_unobserved_handover_pending_age_p90_hours_90d',
                    'delayed', 'label_available_time', 'order_status',
                    'order_delivered_carrier_date', 'order_delivered_customer_date']
        corrupted = data.assign(**{name: 'forbidden' for name in excluded})
        actual = training.prepare_input(data, training.NEW_CANDIDATE)
        pd.testing.assert_frame_equal(actual, training.prepare_input(corrupted, training.NEW_CANDIDATE))
        pd.testing.assert_frame_equal(actual, training.prepare_input(data.drop(columns=excluded, errors='ignore'), training.NEW_CANDIDATE))
        pd.testing.assert_frame_equal(training.prepare_input(data, training.BASELINE), previous.prepare_input(data, training.BASELINE))
        with self.assertRaisesRegex(ValueError, 'Missing required'):
            training.prepare_input(data.drop(columns=list(training.ADDED_FEATURES)), training.NEW_CANDIDATE)
        self.assertTrue(training.prepare_input(data.assign(**{training.ADDED_FEATURES[0]: np.inf}),
                                              training.NEW_CANDIDATE)[training.ADDED_FEATURES[0]].isna().all())

    def test_invalid_input_and_baseline_refit_are_rejected(self):
        for operation in (training.candidate_design, training.feature_names, training.feature_set, training.make_candidate):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation('unknown')
        with self.assertRaisesRegex(ValueError, 'Reuse the existing'):
            training.fit_version(None, None, training.BASELINE)
        with self.assertRaises(ValueError):
            training.make_candidate(training.NEW_CANDIDATE, n_jobs=0)
        data = frame('2017-09')
        for invalid in (data.iloc[:0], data.assign(order_id=None), data.assign(order_id='duplicate'),
                        data.assign(prediction_time=pd.NaT)):
            with self.assertRaises(ValueError):
                training.fit_version(invalid, data, training.NEW_CANDIDATE)

    def test_train_only_preprocessing_and_stable_mature_daily_groups(self):
        train = frame('2017-09').drop(index=[3, 7, 53]).sample(frac=1., random_state=19).reset_index(drop=True)
        train.loc[0, training.ADDED_FEATURES[0]] = np.nan
        scoring = frame('2018-02', 20)
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        scoring[numeric], scoring[categorical] = 999999., 'future_only'
        expected = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, _, info = training.fit_version(train, scoring, training.NEW_CANDIDATE)
        classifier = pipeline.named_steps['classifier']
        groups = expected.groupby(expected.prediction_time.dt.normalize(), sort=True).size().tolist()
        self.assertEqual(classifier.ranker_.fit_parameters, {'group': groups})
        self.assertEqual(info['daily_training_groups'], groups)
        np.testing.assert_array_equal(classifier.ranker_.training_labels, expected.delayed)
        prep = pipeline.named_steps['preprocessor']
        np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                   np.nanmedian(train[numeric].to_numpy(dtype=float), axis=0))
        for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
            self.assertNotIn('future_only', categories)
        self.assertEqual(info['training_order_sha256'], hashlib.sha256('\n'.join(expected.order_id).encode()).hexdigest())
        self.assertEqual(info['added_numeric_features'], list(training.ADDED_FEATURES))
        self.assertEqual(info['changed_classifier_parameters'], [])
        self.assertEqual((info['feature_count'], info['training_jobs'], info['prediction_jobs']), (102, 2, 1))

    def test_single_class_days_and_missing_counts_are_retained(self):
        train = frame('2017-09', 6)
        train['prediction_time'] = pd.to_datetime(['2017-09-01 01:00', '2017-09-01 02:00',
                                                  '2017-09-02 01:00', '2017-09-02 02:00',
                                                  '2017-09-03 01:00', '2017-09-03 02:00'])
        train['delayed'] = [0, 0, 1, 1, 0, 1]
        train[list(training.ADDED_FEATURES)] = np.nan
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, _, info = training.fit_version(train, frame('2018-02', 20), training.NEW_CANDIDATE)
        self.assertEqual(info['daily_training_groups'], [2, 2, 2])
        self.assertEqual(info['daily_training_query_counts'], {
            'queries': 3, 'mixed_label_queries': 1, 'all_on_time_queries': 1, 'all_delayed_queries': 1})
        self.assertTrue(np.isfinite(pipeline.named_steps['classifier'].ranker_.training_values.data).all())

    def test_real_fit_roundtrip_preserves_native_contract_and_complete_day_budget(self):
        train, scoring = frame('2017-09'), frame('2018-02', 20)
        factory = training.make_candidate
        def small(candidate, seed, n_jobs):
            return factory(candidate, seed, n_jobs).set_params(classifier__n_estimators=3)
        with patch.object(training, 'make_candidate', side_effect=small):
            pipeline, scores, info = training.fit_version(train, scoring, training.NEW_CANDIDATE, n_jobs=1)
        self.assertFalse(info['fit_warnings'])
        stream = io.BytesIO()
        joblib.dump(pipeline, stream)
        stream.seek(0)
        restored = joblib.load(stream)
        np.testing.assert_array_equal(scores, training.positive_probability(restored, training.prepare_input(scoring, training.NEW_CANDIDATE)))
        config = json.loads(restored.named_steps['classifier'].ranker_.get_booster().save_config())
        native = config['learner']['objective']['lambdarank_param']
        self.assertEqual((native['lambdarank_pair_method'], int(native['lambdarank_num_pair_per_sample'])), ('topk', 10))
        self.assertEqual(float(config['learner']['gradient_booster']['tree_train_param']['reg_lambda']), 100.)
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        artifact = {'format_version': 1, 'pipeline': restored, 'feature_names': numeric+categorical,
                    'numeric_features': numeric, 'categorical_features': categorical,
                    'threshold': 0., 'daily_alert_cap': .1}
        with self.assertRaises(ValueError):
            predict_features(artifact, scoring)
        predictions = predict_features(artifact, scoring, complete_daily_batches=True)
        self.assertEqual(int(predictions.predicted_delayed.sum()), 2)
        corrupted = scoring.assign(delayed='forbidden', seller_handover_count_90d='forbidden',
                                   seller_unobserved_handover_pending_age_p90_hours_90d='forbidden')
        pd.testing.assert_frame_equal(predictions, predict_features(artifact, corrupted, complete_daily_batches=True))


if __name__ == '__main__':
    unittest.main()
