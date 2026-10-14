"""Paired objectives preserve features, mature day groups and score ordering."""
import hashlib
import io
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone

from scripts import delay_backlog_training as previous
from scripts import delay_objective_training as training
from scripts.delay_calibration_policy import apply_alert_policy
from tests.test_delay_backlog_training import frame


class RecordingRanker:
    def __init__(self, **kwargs):
        self.parameters = kwargs

    def fit(self, X, y, **kwargs):
        self.training_values = X.copy()
        self.training_labels = np.asarray(y).copy()
        self.fit_parameters = kwargs.copy()
        return self

    def get_params(self, deep=False):
        return self.parameters.copy()

    def set_params(self, **kwargs):
        self.parameters.update(kwargs)
        return self

    def predict(self, X, **kwargs):
        self.predict_parameters = kwargs.copy()
        first = X[:, 0]
        return (first.toarray().ravel() if hasattr(first, 'toarray') else np.asarray(first).ravel()) * .000001


class MarginRanker(RecordingRanker):
    def __init__(self, margins):
        super().__init__()
        self.margins = np.asarray(margins, dtype=float)

    def predict(self, X, **kwargs):
        self.predict_parameters = kwargs.copy()
        return self.margins.copy()


class ObjectiveContractsTests(unittest.TestCase):
    def test_four_cells_keep_two_feature_contracts_and_core_tree_parameters(self):
        self.assertEqual(training.NEW_CANDIDATES, ('xgboost_rank_geo', 'xgboost_rank_backlog_7_14d'))
        self.assertEqual(len(training.ALL_CANDIDATES), 4)
        shared = ('n_estimators', 'learning_rate', 'max_depth', 'min_child_weight',
                  'subsample', 'colsample_bytree', 'reg_lambda', 'random_state', 'n_jobs', 'tree_method')
        for candidate in training.ALL_CANDIDATES:
            design = training.candidate_design(candidate)
            actual = training.make_candidate(candidate, seed=37, n_jobs=2)
            baseline = previous.make_candidate(design['backbone_candidate'], seed=37, n_jobs=2)
            expected_features = previous.feature_names(design['backbone_candidate'])
            self.assertEqual(training.feature_names(candidate), expected_features)
            self.assertEqual(sum(map(len, expected_features)), 101 if 'backlog' in candidate else 83)
            self.assertEqual(training.feature_set(candidate), previous.feature_set(design['backbone_candidate']))
            for left, right in zip(actual.named_steps['preprocessor'].transformers,
                                   baseline.named_steps['preprocessor'].transformers, strict=True):
                self.assertEqual(left[0], right[0])
                self.assertEqual(left[2], right[2])
                for (left_name, left_step), (right_name, right_step) in zip(left[1].steps, right[1].steps, strict=True):
                    self.assertEqual(left_name, right_name)
                    self.assertEqual(type(left_step), type(right_step))
                    self.assertEqual(left_step.get_params(deep=False), right_step.get_params(deep=False))
            actual_parameters = actual.named_steps['classifier'].get_params(deep=False)
            baseline_parameters = baseline.named_steps['classifier'].get_params(deep=False)
            self.assertEqual({key: actual_parameters[key] for key in shared},
                             {key: baseline_parameters[key] for key in shared})
            if candidate in training.NEW_CANDIDATES:
                self.assertEqual(actual_parameters['objective'], 'rank:ndcg')
                self.assertEqual(actual_parameters['eval_metric'], 'ndcg@20')
                self.assertEqual(actual_parameters['lambdarank_pair_method'], 'topk')
                self.assertEqual(actual_parameters['lambdarank_num_pair_per_sample'], 20)
                self.assertFalse(actual_parameters['ndcg_exp_gain'])
                self.assertNotIn('early_stopping_rounds', actual_parameters)
                self.assertEqual(clone(actual.named_steps['classifier']).get_params(), actual_parameters)
            else:
                self.assertEqual(actual_parameters['objective'], 'binary:logistic')
                self.assertEqual(actual_parameters['eval_metric'], 'logloss')
        with self.assertRaises(ValueError):
            training.make_candidate(training.NEW_CANDIDATES[0], n_jobs=0)
        with self.assertRaises(ValueError):
            training.candidate_design('unknown')

    def test_features_ignore_unknown_future_outcomes_and_extra_columns(self):
        value = frame('2017-09')
        broken = value.assign(delayed='future unknown', label_available_time='unknown',
                              training_outcome_known_time='unknown', future_actual_delivery_days=np.inf)
        for candidate in training.ALL_CANDIDATES:
            pd.testing.assert_frame_equal(training.prepare_input(value, candidate),
                                          training.prepare_input(broken, candidate))
            numeric, categorical = training.feature_names(candidate)
            self.assertEqual(training.prepare_input(broken, candidate).columns.tolist(), numeric + categorical)


class DailyXGBRankerTests(unittest.TestCase):
    def test_binary_gain_topk_fit_receives_only_mature_groups_without_eval_set(self):
        X, labels, groups = np.arange(12).reshape(6, 2), np.array([0, 1, 0, 0, 1, 0]), np.array([2, 4])
        with patch.object(training, 'XGBRanker', RecordingRanker):
            model = training.DailyXGBRankClassifier(n_estimators=3, n_jobs=2).fit(X, labels, group=groups)
        received = model.ranker_
        np.testing.assert_array_equal(received.training_values, X)
        np.testing.assert_array_equal(received.training_labels, labels)
        self.assertEqual(received.fit_parameters, {'group': [2, 4]})
        self.assertEqual(received.parameters, model.get_params(deep=False))
        self.assertFalse(received.parameters['ndcg_exp_gain'])
        self.assertNotIn('eval_set', received.parameters)
        self.assertNotIn('early_stopping_rounds', received.parameters)
        np.testing.assert_array_equal(model.daily_training_groups_, groups)
        np.testing.assert_array_equal(model.classes_, [0, 1])

    def test_invalid_labels_and_nonpositive_or_incomplete_groups_fail(self):
        invalid = (([0, 0], [2]), ([1, 1], [2]), ([0, 2], [2]),
                   ([0, 1], None), ([0, 1], [0, 2]), ([0, 1], [-1, 3]),
                   ([0, 1], [1]), ([0, 1], [1., 1.]), ([0, 1], [[1, 1]]),
                   ([[0], [1]], [2]))
        for labels, groups in invalid:
            with self.subTest(labels=labels, groups=groups), self.assertRaises(ValueError):
                training.DailyXGBRankClassifier().fit(np.zeros((2, 1)), labels, group=groups)
        with self.assertRaises(ValueError):
            training.DailyXGBRankClassifier().fit(np.zeros((3, 1)), [0, 1], group=[2])

    def test_margin_sigmoid_preserves_ties_complete_daily_top10_and_serializes(self):
        margins = np.array([3., 3., -2., 0., 1., -1., .5, 2., -3., 2.5,
                            -1., -1., 0., 2., 1., 3., 4., 5., 6., 7.])
        model = training.DailyXGBRankClassifier(n_jobs=1)
        model.ranker_, model.classes_ = MarginRanker(margins), np.array([0, 1])
        actual = model.predict_proba(np.zeros((20, 2)))
        self.assertEqual(model.ranker_.parameters['n_jobs'], 1)
        self.assertEqual(model.ranker_.predict_parameters, {'output_margin': True})
        np.testing.assert_allclose(actual[:, 1], 1 / (1 + np.exp(-margins)))
        self.assertEqual(actual[0, 1], actual[1, 1])
        self.assertTrue(((actual > 0) & (actual < 1)).all())
        batch = frame('2017-09', 20)
        # All twenty orders share one complete day; identical margins keep ID ties.
        expected = np.zeros(20, dtype=bool)
        expected[np.lexsort((batch.order_id.to_numpy(), -margins))[:2]] = True
        np.testing.assert_array_equal(apply_alert_policy(batch, actual[:, 1], 0., .1, raw_scores=actual[:, 1]), expected)
        stream = io.BytesIO()
        joblib.dump(model, stream)
        stream.seek(0)
        np.testing.assert_array_equal(joblib.load(stream).predict_proba(np.zeros((20, 2))), actual)

    def test_nonfinite_wrong_shape_and_saturation_fail_loudly(self):
        for margins in ([40., 50.], [-1000., -900.], [0., np.nan], [0., np.inf],
                        [[0.], [1.]], [0.]):
            model = training.DailyXGBRankClassifier(n_jobs=1)
            model.ranker_ = MarginRanker(margins)
            with self.subTest(margins=margins), self.assertRaises(ValueError):
                model.predict_proba(np.zeros((2, 1)))
        model.ranker_ = MarginRanker([40., 40.])
        with self.assertRaises(ValueError):
            model.predict_proba(np.zeros((2, 1)))


class ObjectiveTrainingTests(unittest.TestCase):
    def test_single_class_day_queries_are_retained_and_reported(self):
        train = frame('2017-09', 6)
        train['prediction_time'] = pd.to_datetime([
            '2017-09-01 01:00', '2017-09-01 02:00',
            '2017-09-02 01:00', '2017-09-02 02:00',
            '2017-09-03 01:00', '2017-09-03 02:00'])
        train['delayed'] = [0, 0, 1, 1, 0, 1]
        with patch.object(training, 'XGBRanker', RecordingRanker):
            pipeline, _, report = training.fit_version(train, frame('2018-02', 20), training.NEW_CANDIDATES[0])
        self.assertEqual(report['daily_training_groups'], [2, 2, 2])
        self.assertEqual(report['daily_training_query_counts'], {
            'queries': 3, 'mixed_label_queries': 1, 'all_on_time_queries': 1, 'all_delayed_queries': 1})
        np.testing.assert_array_equal(pipeline.named_steps['classifier'].ranker_.training_labels,
                                      np.array([0, 0, 1, 1, 0, 1]))

    def test_sorted_mature_day_groups_train_only_preprocessor_and_query_diagnostics(self):
        original = frame('2017-09', 120)
        # Purged training rows intentionally leave incomplete original-day groups.
        train = original.drop(index=[3, 7, 53]).sample(frac=1., random_state=19).reset_index(drop=True)
        scoring = frame('2018-02', 20)
        for candidate in training.NEW_CANDIDATES:
            numeric, categorical = training.feature_names(candidate)
            train.loc[0, numeric[0]] = np.nan
            scoring[numeric], scoring[categorical] = 999999., 'future_only'
            expected = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
            with self.subTest(candidate=candidate), patch.object(training, 'XGBRanker', RecordingRanker):
                pipeline, values, report = training.fit_version(train, scoring, candidate, n_jobs=2)
            model = pipeline.named_steps['classifier']
            expected_groups = expected.groupby(expected.prediction_time.dt.normalize(), sort=True).size().tolist()
            self.assertEqual(model.ranker_.fit_parameters, {'group': expected_groups})
            self.assertEqual(report['daily_training_groups'], expected_groups)
            self.assertEqual(sum(expected_groups), len(train))
            self.assertNotEqual(expected_groups, original.groupby(original.prediction_time.dt.normalize()).size().tolist())
            np.testing.assert_array_equal(model.ranker_.training_labels, expected.delayed)
            prep = pipeline.named_steps['preprocessor']
            transformed = prep.transform(training.prepare_input(expected, candidate))
            np.testing.assert_array_equal(model.ranker_.training_values.toarray() if hasattr(model.ranker_.training_values, 'toarray') else model.ranker_.training_values,
                                          transformed.toarray() if hasattr(transformed, 'toarray') else transformed)
            np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                       np.nanmedian(train[numeric].to_numpy(dtype=float), axis=0))
            self.assertEqual(prep.feature_names_in_.tolist(), numeric + categorical)
            for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only', categories)
            self.assertEqual(report['training_jobs'], 2)
            self.assertEqual(report['prediction_jobs'], 1)
            self.assertEqual(model.n_jobs, 1)
            self.assertEqual(report['training_order_sha256'], hashlib.sha256('\n'.join(expected.order_id).encode()).hexdigest())
            self.assertEqual(report['daily_training_query_counts'], {
                'queries': 3, 'mixed_label_queries': 3, 'all_on_time_queries': 0, 'all_delayed_queries': 0})
            self.assertIn('uncalibrated', report['score_semantics'])
            changed = scoring.assign(delayed='unknown', label_available_time='unknown', training_outcome_known_time='unknown')
            np.testing.assert_array_equal(values, training.positive_probability(pipeline, training.prepare_input(changed, candidate)))

    def test_real_small_fits_and_saved_reloads_repeat_exact_scores_for_all_four_cells(self):
        train, scoring = frame('2017-09'), frame('2018-02', 20)
        factory = training.make_candidate
        def small_candidate(candidate, seed, n_jobs):
            model = factory(candidate, seed, n_jobs)
            model.set_params(classifier__n_estimators=3)
            return model
        for candidate in training.ALL_CANDIDATES:
            with self.subTest(candidate=candidate), patch.object(training, 'make_candidate', side_effect=small_candidate):
                pipeline, values, report = training.fit_version(train, scoring, candidate, n_jobs=1)
            self.assertFalse(report['fit_warnings'])
            self.assertEqual(values.shape, (20,))
            stream = io.BytesIO()
            joblib.dump(pipeline, stream)
            stream.seek(0)
            restored = joblib.load(stream)
            np.testing.assert_array_equal(values, training.positive_probability(restored, training.prepare_input(scoring, candidate)))
            if candidate in training.NEW_CANDIDATES:
                prepared = restored.named_steps['preprocessor'].transform(training.prepare_input(scoring, candidate))
                margins = restored.named_steps['classifier'].predict_margin(prepared)
                order = np.argsort(margins, kind='stable')
                distinct = np.diff(margins[order]) > 0
                self.assertTrue((np.diff(values[order])[distinct] > 0).all())
                self.assertEqual(report['ranker_parameters']['n_jobs'], 1)
                self.assertEqual(sum(report['daily_training_groups']), len(train))
            else:
                self.assertIsNone(report['daily_training_groups'])

    def test_invalid_training_identities_or_approval_timestamps_fail_before_fit(self):
        original = frame('2017-09')
        invalid = [original.iloc[:0], original.assign(order_id='duplicate'),
                   original.assign(order_id=None), original.assign(prediction_time=pd.NaT)]
        for train in invalid:
            with self.subTest(rows=len(train)), self.assertRaises(ValueError):
                training.fit_version(train, original, training.NEW_CANDIDATES[0])


if __name__ == '__main__':
    unittest.main()
