"""C comparisons keep their feature, training and historical selection contracts."""
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from sklearn.exceptions import ConvergenceWarning

from scripts import delay_ablation_training as previous
from scripts import delay_budget_training as budget
from scripts import delay_regularization_training as training
from scripts.delay_ablation_features import GEOGRAPHIC_FEATURES, OTHER_FEATURES, VARIANT_FEATURES
from scripts.delay_dispatch_features import DISPATCH_NUMERIC_FEATURES
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.predict_delay import predict_features
from tests.test_delay_budget_training import decision_projection, month_frame
from tests.test_delay_engineering_training import ContractProbabilityPipeline, engineering_frame


class RegularizationTrainingTests(unittest.TestCase):
    def test_seven_values_only_change_c_with_a_common_iteration_ceiling(self):
        self.assertEqual(training.C_GRID, (.01, .03, .1, .3, 1., 3., 10.))
        self.assertEqual(training.NEW_CANDIDATES, (
            'logistic_load_regularization_c0p01', 'logistic_load_regularization_c0p03',
            'logistic_load_regularization_c0p1', 'logistic_load_regularization_c0p3',
            'logistic_load_regularization_c1', 'logistic_load_regularization_c3',
            'logistic_load_regularization_c10'))
        self.assertEqual((len(training.PREVIOUS_CANDIDATES), len(training.NEW_CANDIDATES),
                          len(training.ALL_CANDIDATES)), (43, 7, 50))
        self.assertEqual(len(set(training.ALL_CANDIDATES)), 50)
        self.assertFalse(any('dispatch' in name for name in training.ALL_CANDIDATES))
        expected = previous.make_candidate(training.REFERENCE_CANDIDATE, seed=37, n_jobs=2)
        parameters = expected.named_steps['classifier'].get_params(deep=False)
        for candidate, value in zip(training.NEW_CANDIDATES, training.C_GRID, strict=True):
            with self.subTest(candidate=candidate):
                pipeline = training.make_candidate(candidate, seed=37, n_jobs=2)
                self.assertEqual(training.candidate_c(candidate), value)
                actual = pipeline.named_steps['classifier'].get_params(deep=False)
                self.assertEqual(actual, {**parameters, 'C': value, 'max_iter': 10000})
                # lbfgs plus l1_ratio=0 is effective L2 in the pinned sklearn.
                self.assertEqual((actual['solver'], actual['l1_ratio']), ('lbfgs', 0.))
                numeric, categorical = training.feature_names(candidate)
                self.assertEqual(numeric, VARIANT_FEATURES['load_only'])
                self.assertEqual(categorical, list(CATEGORICAL_FEATURES))
                self.assertEqual(pipeline.named_steps['preprocessor'].transformers[0][2], numeric)
                self.assertEqual(pipeline.named_steps['preprocessor'].transformers[1][2], categorical)
                self.assertEqual(training.feature_set(candidate), 'ablation_load_only_approval')
        with self.assertRaises(ValueError):
            training.make_candidate(training.NEW_CANDIDATES[0], n_jobs=0)
        for name in ('logistic_load_regularization_c0p2', training.REFERENCE_CANDIDATE):
            with self.assertRaises(ValueError):
                training.candidate_c(name)
            with self.assertRaises(ValueError):
                training.fit_version(None, None, name)

    def test_old_candidates_are_delegated_and_cannot_be_refit(self):
        frame = engineering_frame('2017-09')
        for candidate in training.PREVIOUS_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertEqual(training.feature_names(candidate), previous.feature_names(candidate))
                self.assertEqual(training.feature_set(candidate), previous.feature_set(candidate))
                assert_frame_equal(training.prepare_input(frame, candidate), previous.prepare_input(frame, candidate))
                with self.assertRaises(ValueError):
                    training.fit_version(frame, frame, candidate)

    def test_65_column_whitelist_ignores_geography_other_dispatch_and_outcomes(self):
        frame = engineering_frame('2018-02')
        frame['customer_zip_prefix3'] = '001'
        candidate = training.NEW_CANDIDATES[0]
        actual = training.prepare_input(frame, candidate)
        self.assertEqual(len(actual.columns), 65)
        self.assertEqual(list(actual), sum(training.feature_names(candidate), []))
        self.assertTrue(actual.customer_zip_prefix3.eq('001').all())
        excluded = GEOGRAPHIC_FEATURES + OTHER_FEATURES + list(DISPATCH_NUMERIC_FEATURES) + [
            'order_id', 'delayed', 'label_available_time', 'prediction_time',
            'training_outcome_known_time', 'future_actual_delivery_days',
        ]
        self.assertFalse(set(excluded) & set(actual))
        changed = frame.copy(deep=True)
        for column in excluded:
            changed[column] = 'unavailable_at_prediction'
        for name in training.NEW_CANDIDATES:
            assert_frame_equal(actual, training.prepare_input(changed, name))
        with self.assertRaisesRegex(ValueError, 'Missing ablation'):
            training.prepare_input(frame.drop(columns=['seller_pending_vs_completed_30d']), candidate)
        with self.assertRaises(ValueError):
            training.prepare_input(frame, 'undeclared')

    def test_all_seven_fits_learn_only_from_sorted_training_and_report_real_convergence(self):
        train = engineering_frame('2017-09').iloc[::-1].copy()
        scoring = engineering_frame('2018-02', rows=20)
        train.iloc[0, train.columns.get_loc('item_count')] = np.nan
        numeric, categorical = training.feature_names(training.NEW_CANDIDATES[0])
        for column in numeric:
            scoring[column] = 1000000.
        for column in categorical:
            scoring[column] = 'future_only'
        expected_training = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
        for candidate in training.NEW_CANDIDATES:
            pipeline = training.make_candidate(candidate, n_jobs=2)
            with self.subTest(candidate=candidate), patch.object(training, 'make_candidate', return_value=pipeline), \
                    patch.object(pipeline, 'fit', wraps=pipeline.fit) as fitting, \
                    patch.object(training, 'threadpool_limits', wraps=training.threadpool_limits) as limits:
                result, values, report = training.fit_version(train, scoring, candidate, n_jobs=2)
            self.assertIs(result, pipeline)
            assert_frame_equal(fitting.call_args.args[0], training.prepare_input(expected_training, candidate))
            np.testing.assert_array_equal(fitting.call_args.args[1], expected_training.delayed)
            self.assertEqual([call.kwargs for call in limits.call_args_list], [{'limits': 2}, {'limits': 1}])
            prep = pipeline.named_steps['preprocessor']
            self.assertEqual(list(prep.feature_names_in_), numeric + categorical)
            np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                       np.nanmedian(train[numeric].to_numpy(dtype=float), axis=0))
            for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only', categories)
            classifier = pipeline.named_steps['classifier']
            self.assertEqual(report['n_iter'], classifier.n_iter_.tolist())
            self.assertEqual(report['n_iter_max'], int(classifier.n_iter_.max()))
            self.assertTrue(report['converged'])
            self.assertLess(report['n_iter_max'], report['max_iter'])
            self.assertEqual(report['coefficient_l2_norm'], float(np.linalg.norm(classifier.coef_)))
            self.assertEqual(report['intercept'], classifier.intercept_.tolist())
            self.assertEqual(report['regularization_c'], training.candidate_c(candidate))
            self.assertEqual((report['training_jobs'], report['prediction_jobs']), (2, 1))
            self.assertEqual((report['regularization'], report['training_design']), ('L2', 'deadline_wait0'))
            self.assertEqual(report['fit_warnings'], [])
            self.assertTrue(np.isfinite(values).all())
            changed = scoring.copy()
            changed['delayed'], changed['training_outcome_known_time'] = 'unknown', pd.Timestamp('2099-01-01')
            np.testing.assert_array_equal(values, training.positive_probability(pipeline, training.prepare_input(changed, candidate)))

    def test_nonconverged_or_warning_fits_are_rejected_before_scoring(self):
        frame = engineering_frame('2017-09')
        for iterations, emit_warning in ((10000, False), (9999, True)):
            classifier = SimpleNamespace(n_iter_=np.array([iterations]), max_iter=10000)
            pipeline = Mock()
            pipeline.named_steps = {'classifier': classifier}
            if emit_warning:
                pipeline.fit.side_effect = lambda *args: warnings.warn('optimizer failed', ConvergenceWarning)
            with self.subTest(iterations=iterations), patch.object(training, 'make_candidate', return_value=pipeline), \
                    patch.object(training, 'positive_probability') as predict:
                with self.assertRaisesRegex(ValueError, 'did not converge'):
                    training.fit_version(frame, frame, training.NEW_CANDIDATES[0], n_jobs=1)
                predict.assert_not_called()

    def test_invalid_probabilities_are_rejected(self):
        frame = engineering_frame('2017-09')
        for invalid in (np.full(len(frame), np.nan), np.full(len(frame), 1.01)):
            with patch.object(training, 'positive_probability', return_value=invalid):
                with self.assertRaisesRegex(ValueError, 'Invalid regularization score'):
                    training.fit_version(frame, frame, training.NEW_CANDIDATES[0], n_jobs=1)


class RegularizationSelectionTests(unittest.TestCase):
    def test_three_historical_selectors_and_53_summary_rows_ignore_development_changes(self):
        validation = [month_frame(month) for month in ('2017-09', '2017-10', '2017-11')]
        evaluation = month_frame('2018-02')
        weak = np.tile(np.linspace(.01, .99, 50), 2)
        strong = weak.copy()
        strong[np.arange(100) % 50 < 4] = 1.
        winner = training.NEW_CANDIDATES[3]
        historical = [{name: strong if name == winner else weak for name in training.ALL_CANDIDATES}
                      for _ in validation]
        development = {name: weak for name in training.ALL_CANDIDATES}

        def decide(frame, scores):
            return budget.decide_ranking_fold(validation, historical, frame, scores, '2018-02-01',
                candidate_order=training.ALL_CANDIDATES, selection_groups=training.SELECTION_GROUPS)

        before = decide(evaluation, development)
        self.assertEqual(len(before['models']), 50)
        self.assertEqual(len(before['selected_models']), 3)
        self.assertEqual(before['selected_models']['logistic_load_regularization'], winner)
        self.assertEqual(before['selected_models'][training.PRIMARY_SELECTION], winner)
        self.assertIn(before['selected_models']['previous_candidates'], training.PREVIOUS_CANDIDATES)
        changed = evaluation.copy()
        changed['delayed'] = 1 - changed.delayed
        changed['label_available_time'] = pd.Timestamp('2099-01-01')
        after = decide(changed, {name: 1 - values for name, values in development.items()})
        self.assertEqual(decision_projection(before), decision_projection(after))
        self.assertEqual(len(budget.summarize([{'name': '2018-02', 'experiment': before}],
            candidate_order=training.ALL_CANDIDATES, selection_groups=training.SELECTION_GROUPS)), 53)

    def test_saved_regularization_artifacts_require_complete_daily_batches(self):
        frame = engineering_frame('2018-02', rows=100)
        frame['item_count'] = np.tile(np.linspace(.01, .99, 50), 2)
        for candidate in training.NEW_CANDIDATES:
            numeric, categorical = training.feature_names(candidate)
            pipeline = ContractProbabilityPipeline()
            artifact = {'format_version': 1, 'pipeline': pipeline, 'feature_set': training.feature_set(candidate),
                'feature_names': numeric + categorical, 'numeric_features': numeric,
                'categorical_features': categorical, 'threshold': 0., 'daily_alert_cap': .10}
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                predict_features(artifact, frame)
            result = predict_features(artifact, frame, complete_daily_batches=True)
            self.assertEqual(int(result.predicted_delayed.sum()), 10)
            self.assertEqual(pipeline.received_columns, numeric + categorical)


if __name__ == '__main__':
    unittest.main()
