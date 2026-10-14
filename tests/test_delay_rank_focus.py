"""Native top-k pair generation varies; L2, features and mature queries stay fixed."""
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_objective_training as objective
from scripts import delay_rank_regularization as previous
from scripts import delay_rank_focus as training
from scripts.delay_calibration_policy import apply_alert_policy
from tests.test_delay_backlog_training import frame
from tests.test_delay_objective_training import RecordingRanker


class FocusContractTests(unittest.TestCase):
    def test_declared_cells_change_only_pair_focus_in_existing_l2_100_pipeline(self):
        self.assertEqual(training.BASELINES, (
            'xgboost_rank_geo_l2_100', 'xgboost_rank_backlog_7_14d_l2_100'))
        self.assertEqual(training.FOCUS_VALUES, (10, 20, 40))
        self.assertEqual(training.NEW_CANDIDATES, (
            'xgboost_rank_geo_l2_100_topk_10', 'xgboost_rank_geo_l2_100_topk_40',
            'xgboost_rank_backlog_7_14d_l2_100_topk_10',
            'xgboost_rank_backlog_7_14d_l2_100_topk_40'))
        for candidate in training.ALL_CANDIDATES:
            with self.subTest(candidate=candidate):
                design = training.candidate_design(candidate)
                actual = training.make_candidate(candidate, seed=37, n_jobs=2)
                baseline = previous.make_candidate(design['baseline_candidate'], seed=37, n_jobs=2)
                a = actual.named_steps['classifier'].get_params(deep=False)
                b = baseline.named_steps['classifier'].get_params(deep=False)
                self.assertEqual(type(actual.named_steps['classifier']), type(baseline.named_steps['classifier']))
                name = 'lambdarank_num_pair_per_sample'
                self.assertEqual({k: v for k, v in a.items() if k != name},
                                 {k: v for k, v in b.items() if k != name})
                self.assertEqual(a[name], design['pair_focus_k'])
                self.assertEqual(b[name], 20)
                self.assertEqual(a['reg_lambda'], 100.)
                self.assertEqual(a['objective'], 'rank:ndcg')
                self.assertEqual(a['eval_metric'], 'ndcg@20')
                self.assertEqual(a['lambdarank_pair_method'], 'topk')
                self.assertFalse(a['ndcg_exp_gain'])
                self.assertEqual(a['n_estimators'], 400)
                self.assertEqual(a['min_child_weight'], 10.)
                self.assertEqual(a['random_state'], 37)
                self.assertEqual(training.feature_names(candidate), previous.feature_names(design['baseline_candidate']))
                self.assertEqual(sum(map(len, training.feature_names(candidate))),
                                 83 if design['feature_package'] == 'geo' else 101)
                self.assertEqual(training.feature_set(candidate), previous.feature_set(design['baseline_candidate']))
                for left, right in zip(actual.named_steps['preprocessor'].transformers,
                                       baseline.named_steps['preprocessor'].transformers, strict=True):
                    self.assertEqual(left[0], right[0])
                    self.assertEqual(left[2], right[2])
                    for (ln, ls), (rn, rs) in zip(left[1].steps, right[1].steps, strict=True):
                        self.assertEqual((ln, type(ls), ls.get_params(deep=False)),
                                         (rn, type(rs), rs.get_params(deep=False)))

    def test_future_outcomes_and_extra_columns_never_enter_preparation(self):
        value = frame('2017-09')
        broken = value.assign(delayed='unknown', label_available_time='unknown',
                              training_outcome_known_time='unknown', future_delivery_days=np.inf)
        for candidate in training.ALL_CANDIDATES:
            pd.testing.assert_frame_equal(training.prepare_input(value, candidate),
                                          training.prepare_input(broken, candidate))
            numeric, categorical = training.feature_names(candidate)
            self.assertEqual(training.prepare_input(broken, candidate).columns.tolist(), numeric + categorical)

    def test_unknown_candidates_invalid_k_fixed_l2_and_invalid_jobs_are_rejected(self):
        for operation in (training.candidate_design, training.feature_names, training.feature_set,
                          training.make_candidate):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation('xgboost_rank_geo_l2_100_topk_5')
        with self.assertRaises(ValueError):
            training.prepare_input(frame('2017-09'), 'unknown')
        candidate = training.NEW_CANDIDATES[0]
        original = training.CANDIDATE_DESIGNS[candidate]
        for value in (0, -1, .1, 10., np.nan, np.inf, -np.inf, True, '10', None, 30):
            with self.subTest(pair_focus_k=value), patch.dict(
                    training.CANDIDATE_DESIGNS, {candidate: {**original, 'pair_focus_k': value}}):
                with self.assertRaises(ValueError):
                    training.make_candidate(candidate)
        with patch.dict(training.CANDIDATE_DESIGNS, {candidate: {**original, 'reg_lambda': 10}}):
            with self.assertRaises(ValueError):
                training.make_candidate(candidate)
        with self.assertRaises(ValueError):
            training.make_candidate(candidate, n_jobs=0)


class FocusFittingTests(unittest.TestCase):
    def test_baseline_twenty_cannot_be_refit_and_invalid_training_fails_early(self):
        original = frame('2017-09')
        for baseline in training.BASELINES:
            with self.assertRaisesRegex(ValueError, 'Reuse the existing'):
                training.fit_version(original, original, baseline)
        invalid = [original.iloc[:0], original.assign(order_id='duplicate'),
                   original.assign(order_id=None), original.assign(prediction_time=pd.NaT)]
        for data in invalid:
            with self.subTest(rows=len(data)), self.assertRaises(ValueError):
                training.fit_version(data, original, training.NEW_CANDIDATES[0])

    def test_sorted_mature_queries_train_only_preprocessing_and_no_eval_set(self):
        original = frame('2017-09', 120)
        train = original.drop(index=[3, 7, 53]).sample(frac=1., random_state=19).reset_index(drop=True)
        scoring = frame('2018-02', 20)
        for candidate in training.NEW_CANDIDATES:
            numeric, categorical = training.feature_names(candidate)
            modified = train.copy()
            modified.loc[0, numeric[0]] = np.nan
            future = scoring.copy()
            future[numeric], future[categorical] = 999999., 'future_only'
            expected = modified.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
            with self.subTest(candidate=candidate), patch.object(objective, 'XGBRanker', RecordingRanker):
                pipeline, scores, report = training.fit_version(modified, future, candidate, n_jobs=2)
            classifier = pipeline.named_steps['classifier']
            expected_groups = expected.groupby(expected.prediction_time.dt.normalize(), sort=True).size().tolist()
            self.assertEqual(classifier.ranker_.fit_parameters, {'group': expected_groups})
            self.assertEqual(report['daily_training_groups'], expected_groups)
            self.assertEqual(sum(expected_groups), len(train))
            self.assertNotEqual(expected_groups, original.groupby(original.prediction_time.dt.normalize()).size().tolist())
            np.testing.assert_array_equal(classifier.ranker_.training_labels, expected.delayed)
            prep = pipeline.named_steps['preprocessor']
            actual_x = classifier.ranker_.training_values
            expected_x = prep.transform(training.prepare_input(expected, candidate))
            np.testing.assert_array_equal(actual_x.toarray() if hasattr(actual_x, 'toarray') else actual_x,
                                          expected_x.toarray() if hasattr(expected_x, 'toarray') else expected_x)
            np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                       np.nanmedian(modified[numeric].to_numpy(dtype=float), axis=0))
            self.assertEqual(prep.feature_names_in_.tolist(), numeric + categorical)
            for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only', categories)
            self.assertEqual(report['training_order_sha256'], hashlib.sha256('\n'.join(expected.order_id).encode()).hexdigest())
            self.assertEqual(report['training_jobs'], 2)
            self.assertEqual(report['prediction_jobs'], 1)
            self.assertEqual(classifier.n_jobs, 1)
            self.assertEqual(report['changed_classifier_parameters'], ['lambdarank_num_pair_per_sample'])
            self.assertEqual(report['pair_focus_k'], training.candidate_design(candidate)['pair_focus_k'])
            self.assertEqual(classifier.ranker_.parameters['lambdarank_num_pair_per_sample'], report['pair_focus_k'])
            self.assertEqual(classifier.ranker_.parameters['eval_metric'], 'ndcg@20')
            self.assertEqual(classifier.ranker_.parameters['reg_lambda'], 100.)
            self.assertEqual(report['baseline_pair_focus_k'], 20)
            self.assertEqual(report['daily_training_query_counts'], {
                'queries': 3, 'mixed_label_queries': 3, 'all_on_time_queries': 0, 'all_delayed_queries': 0})
            self.assertIn('fixed training k, not a daily fraction', report['ranker_objective'])
            self.assertIn('strictly monotone uncalibrated', report['score_semantics'])
            changed = future.assign(delayed='unknown', label_available_time='unknown', training_outcome_known_time='unknown')
            np.testing.assert_array_equal(scores, training.positive_probability(pipeline, training.prepare_input(changed, candidate)))

    def test_single_class_queries_are_retained_without_new_weights(self):
        train = frame('2017-09', 6)
        train['prediction_time'] = pd.to_datetime([
            '2017-09-01 01:00', '2017-09-01 02:00',
            '2017-09-02 01:00', '2017-09-02 02:00',
            '2017-09-03 01:00', '2017-09-03 02:00'])
        train['delayed'] = [0, 0, 1, 1, 0, 1]
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, _, report = training.fit_version(train, frame('2018-02', 20), training.NEW_CANDIDATES[-1])
        self.assertEqual(report['daily_training_groups'], [2, 2, 2])
        self.assertEqual(report['daily_training_query_counts'], {
            'queries': 3, 'mixed_label_queries': 1, 'all_on_time_queries': 1, 'all_delayed_queries': 1})
        self.assertEqual(pipeline.named_steps['classifier'].ranker_.fit_parameters, {'group': [2, 2, 2]})

    def test_four_real_small_fits_serialize_and_native_topk_is_effective(self):
        train, scoring = frame('2017-09'), frame('2018-02', 20)
        factory = training.make_candidate
        def small_candidate(candidate, seed, n_jobs):
            return factory(candidate, seed, n_jobs).set_params(classifier__n_estimators=3)
        for candidate in training.NEW_CANDIDATES:
            with self.subTest(candidate=candidate), patch.object(training, 'make_candidate', side_effect=small_candidate):
                pipeline, scores, report = training.fit_version(train, scoring, candidate, n_jobs=1)
            self.assertFalse(report['fit_warnings'])
            self.assertEqual(scores.shape, (20,))
            stream = io.BytesIO()
            joblib.dump(pipeline, stream)
            stream.seek(0)
            restored = joblib.load(stream)
            np.testing.assert_array_equal(scores, training.positive_probability(restored, training.prepare_input(scoring, candidate)))
            X = restored.named_steps['preprocessor'].transform(training.prepare_input(scoring, candidate))
            classifier = restored.named_steps['classifier']
            config = json.loads(classifier.ranker_.get_booster().save_config())
            params = config['learner']['objective']['lambdarank_param']
            self.assertEqual(int(params['lambdarank_num_pair_per_sample']), report['pair_focus_k'])
            self.assertEqual(params['lambdarank_pair_method'], 'topk')
            self.assertEqual(config['learner']['objective']['name'], 'rank:ndcg')
            self.assertEqual([metric['name'] for metric in config['learner']['metrics']], ['ndcg@20'])
            self.assertEqual(float(config['learner']['gradient_booster']['tree_train_param']['reg_lambda']), 100.)
            margins = classifier.predict_margin(X)
            order = np.argsort(margins, kind='stable')
            distinct = np.diff(margins[order]) > 0
            self.assertTrue((np.diff(scores[order])[distinct] > 0).all())
            self.assertEqual(report['ranker_parameters']['n_jobs'], 1)
            expected_alerts = np.zeros(20, dtype=bool)
            expected_alerts[np.lexsort((scoring.order_id.to_numpy(), -margins))[:2]] = True
            np.testing.assert_array_equal(
                apply_alert_policy(scoring, scores, 0., .1, raw_scores=scores), expected_alerts)


if __name__ == '__main__':
    unittest.main()
