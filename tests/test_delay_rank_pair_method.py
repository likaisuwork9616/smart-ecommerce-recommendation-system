"""The mean contrast preserves 101 features, L2=100, value 10 and day groups."""
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_objective_training as objective
from scripts import delay_rank_focus as previous
from scripts import delay_rank_pair_method as training
from scripts.delay_calibration_policy import apply_alert_policy
from tests.test_delay_backlog_training import frame
from tests.test_delay_objective_training import RecordingRanker


class PairMethodContractTests(unittest.TestCase):
    def test_only_method_changes_and_numerical_ten_and_101_features_are_identical(self):
        self.assertEqual(training.BASELINE, 'xgboost_rank_backlog_7_14d_l2_100_topk_10')
        self.assertEqual(training.NEW_CANDIDATES, ('xgboost_rank_backlog_7_14d_l2_100_mean_10',))
        self.assertEqual(training.ALL_CANDIDATES, (training.BASELINE, training.NEW_CANDIDATE))
        baseline = previous.make_candidate(training.BASELINE, seed=37, n_jobs=2)
        expected = baseline.named_steps['classifier'].get_params(deep=False)
        for candidate in training.ALL_CANDIDATES:
            with self.subTest(candidate=candidate):
                design = training.candidate_design(candidate)
                self.assertNotIn('pair_focus_k', design)
                actual = training.make_candidate(candidate, seed=37, n_jobs=2)
                parameters = actual.named_steps['classifier'].get_params(deep=False)
                omitted = 'lambdarank_pair_method'
                self.assertEqual({k: v for k, v in parameters.items() if k != omitted},
                                 {k: v for k, v in expected.items() if k != omitted})
                self.assertEqual(parameters[omitted], design['pair_method'])
                self.assertEqual(parameters['lambdarank_num_pair_per_sample'], 10)
                self.assertEqual(parameters['reg_lambda'], 100.)
                self.assertEqual(parameters['eval_metric'], 'ndcg@20')
                self.assertEqual(parameters['objective'], 'rank:ndcg')
                self.assertEqual(parameters['n_estimators'], 400)
                self.assertFalse(parameters['ndcg_exp_gain'])
                self.assertEqual(training.feature_names(candidate), previous.feature_names(training.BASELINE))
                self.assertEqual(sum(map(len, training.feature_names(candidate))), 101)
                self.assertEqual(training.feature_set(candidate), previous.feature_set(training.BASELINE))
                for left, right in zip(actual.named_steps['preprocessor'].transformers,
                                       baseline.named_steps['preprocessor'].transformers, strict=True):
                    self.assertEqual((left[0], left[2]), (right[0], right[2]))
                    for (ln, ls), (rn, rs) in zip(left[1].steps, right[1].steps, strict=True):
                        self.assertEqual((ln, type(ls), ls.get_params(deep=False)),
                                         (rn, type(rs), rs.get_params(deep=False)))

    def test_future_outcomes_and_unlisted_columns_cannot_change_input(self):
        source = frame('2017-09')
        changed = source.assign(delayed='unknown', label_available_time='unknown',
                                training_outcome_known_time='unknown', future_delivery_days=np.inf)
        for candidate in training.ALL_CANDIDATES:
            pd.testing.assert_frame_equal(training.prepare_input(source, candidate),
                                          training.prepare_input(changed, candidate))
            numeric, categorical = training.feature_names(candidate)
            self.assertEqual(training.prepare_input(changed, candidate).columns.tolist(), numeric + categorical)

    def test_unknown_method_or_parameter_drift_and_invalid_jobs_are_rejected(self):
        for operation in (training.candidate_design, training.feature_names,
                          training.feature_set, training.make_candidate):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation('xgboost_rank_backlog_7_14d_l2_100_mean_20')
        with self.assertRaises(ValueError):
            training.prepare_input(frame('2017-09'), 'unknown')
        candidate = training.NEW_CANDIDATE
        original = training.CANDIDATE_DESIGNS[candidate]
        for value in (0, -1, .1, 10., np.nan, np.inf, True, '10', None, 20):
            with self.subTest(value=value), patch.dict(
                    training.CANDIDATE_DESIGNS, {candidate: {**original, 'num_pair_parameter': value}}):
                with self.assertRaises(ValueError):
                    training.make_candidate(candidate)
        for value in (1, 10, 0, np.nan, np.inf, True, '100', None):
            with self.subTest(l2=value), patch.dict(
                    training.CANDIDATE_DESIGNS, {candidate: {**original, 'reg_lambda': value}}):
                with self.assertRaises(ValueError):
                    training.make_candidate(candidate)
        for value in ('topk', 'unknown', None):
            with self.subTest(method=value), patch.dict(
                    training.CANDIDATE_DESIGNS, {candidate: {**original, 'pair_method': value}}):
                with self.assertRaises(ValueError):
                    training.make_candidate(candidate)
        with self.assertRaises(ValueError):
            training.make_candidate(candidate, n_jobs=0)


class PairMethodFittingTests(unittest.TestCase):
    def test_existing_baseline_is_replay_only_and_invalid_training_fails_early(self):
        original = frame('2017-09')
        with self.assertRaisesRegex(ValueError, 'Reuse the existing topk=10'):
            training.fit_version(original, original, training.BASELINE)
        for invalid in (original.iloc[:0], original.assign(order_id='duplicate'),
                        original.assign(order_id=None), original.assign(prediction_time=pd.NaT)):
            with self.subTest(rows=len(invalid)), self.assertRaises(ValueError):
                training.fit_version(invalid, original, training.NEW_CANDIDATE)

    def test_sorted_mature_queries_and_train_only_preprocessing_match_topk_contract(self):
        original = frame('2017-09', 120)
        train = original.drop(index=[3, 7, 53]).sample(frac=1., random_state=19).reset_index(drop=True)
        scoring = frame('2018-02', 20)
        numeric, categorical = training.feature_names(training.NEW_CANDIDATE)
        train.loc[0, numeric[0]] = np.nan
        scoring[numeric], scoring[categorical] = 999999., 'future_only'
        expected = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, scores, report = training.fit_version(train, scoring, training.NEW_CANDIDATE)
        classifier = pipeline.named_steps['classifier']
        expected_groups = expected.groupby(expected.prediction_time.dt.normalize(), sort=True).size().tolist()
        self.assertEqual(classifier.ranker_.fit_parameters, {'group': expected_groups})
        self.assertEqual(report['daily_training_groups'], expected_groups)
        self.assertEqual(sum(expected_groups), len(train))
        np.testing.assert_array_equal(classifier.ranker_.training_labels, expected.delayed)
        prep = pipeline.named_steps['preprocessor']
        actual_x = classifier.ranker_.training_values
        expected_x = prep.transform(training.prepare_input(expected, training.NEW_CANDIDATE))
        np.testing.assert_array_equal(actual_x.toarray() if hasattr(actual_x, 'toarray') else actual_x,
                                      expected_x.toarray() if hasattr(expected_x, 'toarray') else expected_x)
        np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                  np.nanmedian(train[numeric].to_numpy(dtype=float), axis=0))
        self.assertEqual(prep.feature_names_in_.tolist(), numeric + categorical)
        for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
            self.assertNotIn('future_only', categories)
        self.assertEqual(report['training_order_sha256'], hashlib.sha256('\n'.join(expected.order_id).encode()).hexdigest())
        self.assertEqual(report['training_jobs'], 2)
        self.assertEqual(report['prediction_jobs'], 1)
        self.assertEqual(classifier.n_jobs, 1)
        self.assertEqual(report['changed_classifier_parameters'], ['lambdarank_pair_method'])
        self.assertEqual(report['pair_method'], 'mean')
        self.assertEqual(report['baseline_pair_method'], 'topk')
        self.assertEqual(report['num_pair_parameter'], 10)
        self.assertEqual(report['baseline_num_pair_parameter'], 10)
        self.assertNotIn('pair_focus_k', report)
        self.assertEqual(classifier.ranker_.parameters['lambdarank_pair_method'], 'mean')
        self.assertEqual(classifier.ranker_.parameters['lambdarank_num_pair_per_sample'], 10)
        self.assertEqual(classifier.ranker_.parameters['eval_metric'], 'ndcg@20')
        self.assertEqual(classifier.ranker_.parameters['reg_lambda'], 100.)
        self.assertEqual(report['daily_training_query_counts'], {
            'queries': 3, 'mixed_label_queries': 3, 'all_on_time_queries': 0, 'all_delayed_queries': 0})
        self.assertIn('sampled pairs per row', report['pair_parameter_semantics'])
        self.assertIn('built-in normalization behavior depends on pair method', report['normalization_semantics'])
        self.assertIn('strictly monotone uncalibrated', report['score_semantics'])
        changed = scoring.assign(delayed='unknown', label_available_time='unknown', training_outcome_known_time='unknown')
        np.testing.assert_array_equal(scores, training.positive_probability(
            pipeline, training.prepare_input(changed, training.NEW_CANDIDATE)))

    def test_single_class_day_queries_are_retained_without_weights(self):
        train = frame('2017-09', 6)
        train['prediction_time'] = pd.to_datetime([
            '2017-09-01 01:00', '2017-09-01 02:00', '2017-09-02 01:00',
            '2017-09-02 02:00', '2017-09-03 01:00', '2017-09-03 02:00'])
        train['delayed'] = [0, 0, 1, 1, 0, 1]
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, _, report = training.fit_version(train, frame('2018-02', 20), training.NEW_CANDIDATE)
        self.assertEqual(report['daily_training_groups'], [2, 2, 2])
        self.assertEqual(report['daily_training_query_counts'], {
            'queries': 3, 'mixed_label_queries': 1, 'all_on_time_queries': 1, 'all_delayed_queries': 1})
        self.assertEqual(pipeline.named_steps['classifier'].ranker_.fit_parameters, {'group': [2, 2, 2]})

    def test_real_small_fit_serializes_mean_and_keeps_native_normalization_parameters(self):
        train, scoring = frame('2017-09'), frame('2018-02', 20)
        factory = training.make_candidate
        def small_candidate(candidate, seed, n_jobs):
            return factory(candidate, seed, n_jobs).set_params(classifier__n_estimators=3)
        with patch.object(training, 'make_candidate', side_effect=small_candidate):
            pipeline, scores, report = training.fit_version(train, scoring, training.NEW_CANDIDATE, n_jobs=1)
        self.assertFalse(report['fit_warnings'])
        self.assertEqual(scores.shape, (20,))
        stream = io.BytesIO()
        joblib.dump(pipeline, stream)
        stream.seek(0)
        restored = joblib.load(stream)
        np.testing.assert_array_equal(scores, training.positive_probability(
            restored, training.prepare_input(scoring, training.NEW_CANDIDATE)))
        classifier = restored.named_steps['classifier']
        config = json.loads(classifier.ranker_.get_booster().save_config())
        params = config['learner']['objective']['lambdarank_param']
        self.assertEqual(int(params['lambdarank_num_pair_per_sample']), 10)
        self.assertEqual(params['lambdarank_pair_method'], 'mean')
        self.assertEqual(config['learner']['objective']['name'], 'rank:ndcg')
        self.assertEqual([metric['name'] for metric in config['learner']['metrics']], ['ndcg@20'])
        self.assertEqual(float(config['learner']['gradient_booster']['tree_train_param']['reg_lambda']), 100.)
        # A tiny fixture-only reference checks effective native defaults, never a research baseline refit.
        baseline = factory(training.BASELINE, n_jobs=1).set_params(classifier__n_estimators=3)
        ordered = train.sort_values(['prediction_time', 'order_id'], kind='stable')
        sizes = ordered.groupby(ordered.prediction_time.dt.normalize(), sort=True).size().to_numpy(dtype=int)
        baseline.fit(training.prepare_input(ordered, training.BASELINE), ordered.delayed, classifier__group=sizes)
        reference = json.loads(baseline.named_steps['classifier'].ranker_.get_booster().save_config())
        baseline_params = reference['learner']['objective']['lambdarank_param']
        self.assertEqual(baseline_params['lambdarank_pair_method'], 'topk')
        self.assertEqual({k: v for k, v in params.items() if k != 'lambdarank_pair_method'},
                         {k: v for k, v in baseline_params.items() if k != 'lambdarank_pair_method'})
        X = restored.named_steps['preprocessor'].transform(training.prepare_input(scoring, training.NEW_CANDIDATE))
        margins = classifier.predict_margin(X)
        order = np.argsort(margins, kind='stable')
        distinct = np.diff(margins[order]) > 0
        self.assertTrue((np.diff(scores[order])[distinct] > 0).all())
        expected_alerts = np.zeros(20, dtype=bool)
        expected_alerts[np.lexsort((scoring.order_id.to_numpy(), -margins))[:2]] = True
        np.testing.assert_array_equal(apply_alert_policy(scoring, scores, 0., .1, raw_scores=scores), expected_alerts)


if __name__ == '__main__':
    unittest.main()
