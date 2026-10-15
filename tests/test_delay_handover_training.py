"""Only three numeric columns change; native ranking and inference stay fixed."""
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_handover_training as training
from scripts import delay_rank_focus as previous
from scripts import delay_objective_training as objective
from scripts.delay_handover_features import ADDED_FEATURES, FEATURE_SET
from scripts.predict_delay import predict_features
from tests.test_delay_backlog_training import frame as backlog_frame
from tests.test_delay_objective_training import RecordingRanker


def frame(month, rows=120):
    result = backlog_frame(month, rows)
    for index, name in enumerate(ADDED_FEATURES):
        result[name] = np.arange(rows, dtype=float)*.5+index
    return result


class HandoverTrainingTests(unittest.TestCase):
    def test_exact_three_column_change_preserves_all_classifier_and_preprocessor_settings(self):
        self.assertEqual(training.ALL_CANDIDATES, (training.BASELINE, training.NEW_CANDIDATE))
        self.assertEqual(training.NEW_CANDIDATES, (training.NEW_CANDIDATE,))
        baseline = previous.make_candidate(training.BASELINE, seed=37, n_jobs=2)
        actual = training.make_candidate(training.NEW_CANDIDATE, seed=37, n_jobs=2)
        self.assertEqual(actual.named_steps['classifier'].get_params(deep=False),
                         baseline.named_steps['classifier'].get_params(deep=False))
        params = actual.named_steps['classifier'].get_params(deep=False)
        self.assertEqual(params['reg_lambda'], 100.)
        self.assertEqual(params['lambdarank_pair_method'], 'topk')
        self.assertEqual(params['lambdarank_num_pair_per_sample'], 10)
        self.assertEqual(params['eval_metric'], 'ndcg@20')
        self.assertEqual(params['n_estimators'], 400)
        old_num, old_cat = previous.feature_names(training.BASELINE)
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        self.assertEqual(numeric, old_num+ADDED_FEATURES)
        self.assertEqual(categorical, old_cat)
        self.assertEqual((len(numeric), len(categorical)), (96, 8))
        self.assertEqual(training.feature_set(training.NEW_CANDIDATE), FEATURE_SET)
        self.assertEqual(training.feature_set(training.BASELINE), previous.feature_set(training.BASELINE))
        for left, right in zip(actual.named_steps['preprocessor'].transformers,
                               baseline.named_steps['preprocessor'].transformers, strict=True):
            self.assertEqual(left[0], right[0])
            for (ln, ls), (rn, rs) in zip(left[1].steps, right[1].steps, strict=True):
                self.assertEqual((ln, type(ls), ls.get_params(deep=False)),
                                 (rn, type(rs), rs.get_params(deep=False)))

    def test_whitelist_ignores_targets_status_future_events_and_extra_features(self):
        data = frame('2017-09')
        changed = data.assign(delayed='unavailable', label_available_time='unavailable',
                              order_delivered_carrier_date='2099-01-01', order_status='canceled',
                              future_feature=np.inf)
        for candidate in training.ALL_CANDIDATES:
            pd.testing.assert_frame_equal(training.prepare_input(data, candidate),
                                          training.prepare_input(changed, candidate))
        prepared = training.prepare_input(data.assign(**{ADDED_FEATURES[0]: np.inf}), training.NEW_CANDIDATE)
        self.assertTrue(prepared[ADDED_FEATURES[0]].isna().all())
        with self.assertRaises(ValueError):
            training.prepare_input(data.drop(columns=ADDED_FEATURES[:1]), training.NEW_CANDIDATE)

    def test_unknown_candidate_invalid_jobs_and_baseline_refit_fail(self):
        for operation in (training.candidate_design, training.feature_names, training.feature_set,
                          training.make_candidate):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation('unknown')
        with self.assertRaises(ValueError):
            training.prepare_input(frame('2017-09'), 'unknown')
        with self.assertRaises(ValueError):
            training.make_candidate(training.NEW_CANDIDATE, n_jobs=0)
        with self.assertRaisesRegex(ValueError, 'Reuse the existing'):
            training.fit_version(None, None, training.BASELINE)
        data = frame('2017-09')
        for invalid in (data.iloc[:0], data.assign(order_id=None), data.assign(order_id='duplicate'),
                        data.assign(prediction_time=pd.NaT)):
            with self.assertRaises(ValueError):
                training.fit_version(invalid, data, training.NEW_CANDIDATE)

    def test_train_only_imputation_sorted_mature_day_queries_and_no_evaluation_set(self):
        train = frame('2017-09').drop(index=[3, 7, 53]).sample(frac=1., random_state=19).reset_index(drop=True)
        train.loc[0, ADDED_FEATURES[0]] = np.nan
        scoring = frame('2018-02', 20)
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        scoring[numeric], scoring[categorical] = 999999., 'future_only'
        expected = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, scores, info = training.fit_version(train, scoring, training.NEW_CANDIDATE)
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
        self.assertEqual(info['changed_classifier_parameters'], [])
        self.assertEqual(info['added_numeric_features'], ADDED_FEATURES)
        self.assertEqual(info['feature_count'], 104)
        self.assertEqual(info['training_order_sha256'], hashlib.sha256('\n'.join(expected.order_id).encode()).hexdigest())
        self.assertEqual(info['daily_training_query_counts'], {
            'queries': 3, 'mixed_label_queries': 3, 'all_on_time_queries': 0, 'all_delayed_queries': 0})
        self.assertEqual((info['training_jobs'], info['prediction_jobs']), (2, 1))
        changed = scoring.assign(delayed='unknown', label_available_time='unknown')
        np.testing.assert_array_equal(scores, training.positive_probability(pipeline, training.prepare_input(changed, training.NEW_CANDIDATE)))

    def test_single_class_queries_are_retained_and_all_missing_history_is_train_imputed(self):
        train = frame('2017-09', 6)
        train['prediction_time'] = pd.to_datetime([
            '2017-09-01 01:00', '2017-09-01 02:00', '2017-09-02 01:00',
            '2017-09-02 02:00', '2017-09-03 01:00', '2017-09-03 02:00'])
        train['delayed'] = [0, 0, 1, 1, 0, 1]
        train[ADDED_FEATURES[1:]] = np.nan
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, _, info = training.fit_version(train, frame('2018-02', 20), training.NEW_CANDIDATE)
        self.assertEqual(info['daily_training_groups'], [2, 2, 2])
        self.assertEqual(info['daily_training_query_counts'], {
            'queries': 3, 'mixed_label_queries': 1, 'all_on_time_queries': 1, 'all_delayed_queries': 1})
        prep = pipeline.named_steps['preprocessor']
        self.assertEqual(prep.feature_names_in_.tolist(), sum(training.feature_names(training.NEW_CANDIDATE), []))
        self.assertTrue(np.isfinite(pipeline.named_steps['classifier'].ranker_.training_values.data).all())

    def test_small_real_fit_serializes_native_parameters_and_enforces_complete_daily_budget(self):
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
        classifier = restored.named_steps['classifier']
        config = json.loads(classifier.ranker_.get_booster().save_config())
        native = config['learner']['objective']['lambdarank_param']
        self.assertEqual(native['lambdarank_pair_method'], 'topk')
        self.assertEqual(int(native['lambdarank_num_pair_per_sample']), 10)
        self.assertEqual(float(config['learner']['gradient_booster']['tree_train_param']['reg_lambda']), 100.)
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        artifact = {'format_version': 1, 'pipeline': restored, 'feature_names': numeric+categorical,
                    'numeric_features': numeric, 'categorical_features': categorical,
                    'threshold': 0., 'daily_alert_cap': .1}
        with self.assertRaises(ValueError):
            predict_features(artifact, scoring)
        actual = predict_features(artifact, scoring, complete_daily_batches=True)
        self.assertEqual(int(actual.predicted_delayed.sum()), 2)
        X = restored.named_steps['preprocessor'].transform(training.prepare_input(scoring, training.NEW_CANDIDATE))
        margins = classifier.predict_margin(X)
        expected = np.zeros(len(scoring), dtype=bool)
        expected[np.lexsort((scoring.order_id.to_numpy(), -margins))[:2]] = True
        np.testing.assert_array_equal(actual.predicted_delayed.to_numpy(dtype=bool), expected)


if __name__ == '__main__':
    unittest.main()
