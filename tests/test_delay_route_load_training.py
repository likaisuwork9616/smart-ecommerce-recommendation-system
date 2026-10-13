"""Fixed route/load cells preserve parameters and historical-only model choice."""
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from sklearn.exceptions import ConvergenceWarning

from scripts import delay_budget_training as budget
from scripts import delay_regularization_training as previous
from scripts import delay_route_load_training as training
from scripts.delay_route_load_features import ADDED_FEATURES, CROSS_CATEGORICAL_FEATURES
from scripts.predict_delay import build_inference_features, predict_features
from scripts.train_route_load_interactions import paired_comparisons, verify_prior_score_part
from tests.test_delay_budget_training import decision_projection, month_frame
from tests.test_delay_engineering_training import ContractProbabilityPipeline, engineering_frame


def route_load_frame(month, rows=120):
    frame = engineering_frame(month, rows)
    added = {name: np.arange(rows, dtype=float) + index if name not in CROSS_CATEGORICAL_FEATURES else np.where(np.arange(rows) % 2, 'SP->RJ|22-30|growing', 'SP->SP|15-21|stable')
             for index, name in enumerate(ADDED_FEATURES)}
    return pd.concat([frame, pd.DataFrame(added, index=frame.index)], axis=1)


class RouteLoadTrainingTests(unittest.TestCase):
    def test_six_cells_change_only_features_of_the_declared_backbone(self):
        self.assertEqual(training.NEW_CANDIDATES, ('logistic_c1_route_load_trend', 'logistic_c1_route_load_cross',
            'logistic_c0p01_route_load_trend', 'logistic_c0p01_route_load_cross',
            'xgboost_route_load_trend', 'xgboost_route_load_cross'))
        self.assertEqual((len(training.PREVIOUS_CANDIDATES), len(training.ALL_CANDIDATES)), (50, 56))
        self.assertEqual(len(set(training.ALL_CANDIDATES)), 56)
        for candidate, expected_count in zip(training.NEW_CANDIDATES, (78, 84, 78, 84, 96, 102), strict=True):
            design = training.candidate_design(candidate)
            baseline = previous.make_candidate(design['backbone_candidate'], seed=37, n_jobs=2)
            actual = training.make_candidate(candidate, seed=37, n_jobs=2)
            with self.subTest(candidate=candidate):
                self.assertEqual(actual.named_steps['classifier'].get_params(deep=False), baseline.named_steps['classifier'].get_params(deep=False))
                numeric, categorical = training.feature_names(candidate)
                self.assertEqual(len(numeric + categorical), expected_count)
                self.assertEqual(len(set(numeric + categorical)), expected_count)
                prep = actual.named_steps['preprocessor']
                self.assertEqual(prep.transformers[0][2], numeric)
                self.assertEqual(prep.transformers[1][2], categorical)
                for index in range(2):
                    actual_steps = prep.transformers[index][1].named_steps
                    expected_steps = baseline.named_steps['preprocessor'].transformers[index][1].named_steps
                    self.assertEqual(list(actual_steps), list(expected_steps))
                    for step in actual_steps:
                        self.assertIs(type(actual_steps[step]), type(expected_steps[step]))
                        self.assertEqual(actual_steps[step].get_params(deep=False), expected_steps[step].get_params(deep=False))
                self.assertIn(training.feature_set(candidate), training.FEATURE_SET_DESIGNS)
                self.assertEqual(design['backbone'] == 'geo', training.feature_set(candidate) in training.GEOGRAPHIC_FEATURE_SETS)
                if design['family'] == 'logistic':
                    self.assertEqual(actual.named_steps['classifier'].max_iter, 10000)
        for name in ('undeclared', training.PREVIOUS_CANDIDATES[0]):
            with self.assertRaises(ValueError):
                training.candidate_design(name)
            with self.assertRaises(ValueError):
                training.fit_version(None, None, name)
        with self.assertRaises(ValueError):
            training.make_candidate(training.NEW_CANDIDATES[0], n_jobs=0)

    def test_previous_candidates_are_delegated_without_new_features(self):
        frame = route_load_frame('2017-09')
        for candidate in training.PREVIOUS_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertEqual(training.feature_names(candidate), previous.feature_names(candidate))
                self.assertEqual(training.feature_set(candidate), previous.feature_set(candidate))
                assert_frame_equal(training.prepare_input(frame, candidate), previous.prepare_input(frame, candidate))

    def test_train_only_preprocessing_sorted_fits_and_recorded_convergence(self):
        train, scoring = route_load_frame('2017-09').iloc[::-1].copy(), route_load_frame('2018-02', 20)
        train.iloc[0, train.columns.get_loc('item_count')] = np.nan
        factory = training.make_candidate
        expected_train = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
        for candidate in training.NEW_CANDIDATES:
            numeric, categorical = training.feature_names(candidate)
            future = scoring.copy()
            future[numeric] = 1000000.
            future[categorical] = 'future_only'
            pipeline = factory(candidate, n_jobs=2)
            if training.candidate_design(candidate)['family'] == 'xgboost':
                pipeline.set_params(classifier__n_estimators=3)
            with self.subTest(candidate=candidate), patch.object(training, 'make_candidate', return_value=pipeline), \
                    patch.object(pipeline, 'fit', wraps=pipeline.fit) as fitting, \
                    patch.object(training, 'threadpool_limits', wraps=training.threadpool_limits) as limits:
                fitted, values, report = training.fit_version(train, future, candidate, n_jobs=2)
            assert_frame_equal(fitting.call_args.args[0], training.prepare_input(expected_train, candidate))
            np.testing.assert_array_equal(fitting.call_args.args[1], expected_train.delayed)
            self.assertEqual([call.kwargs for call in limits.call_args_list], [{'limits': 2}, {'limits': 1}])
            prep = fitted.named_steps['preprocessor']
            self.assertEqual(list(prep.feature_names_in_), numeric + categorical)
            np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_, np.nanmedian(train[numeric].to_numpy(dtype=float), axis=0))
            for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only', categories)
            changed = future.copy()
            for name in ('delayed', 'label_available_time', 'training_outcome_known_time', 'future_actual_delivery_days'):
                changed[name] = 'unavailable'
            np.testing.assert_array_equal(values, training.positive_probability(fitted, training.prepare_input(changed, candidate)))
            self.assertEqual((report['training_jobs'], report['prediction_jobs']), (2, 1))
            self.assertEqual(report['training_design'], 'deadline_wait0')
            self.assertEqual(report['paired_backbone_candidate'], training.candidate_design(candidate)['backbone_candidate'])
            if report['paired_model_family'] == 'logistic':
                self.assertTrue(report['converged'])
                self.assertEqual(report['n_iter'], fitted.named_steps['classifier'].n_iter_.tolist())
                self.assertLess(report['n_iter_max'], report['max_iter'])
                self.assertEqual(report['coefficient_l2_norm'], float(np.linalg.norm(fitted.named_steps['classifier'].coef_)))

    def test_nonconverged_logistic_rejected_before_prediction(self):
        frame = route_load_frame('2017-09')
        for iterations, emits_warning in ((10000, False), (9999, True)):
            classifier = SimpleNamespace(n_iter_=np.array([iterations]), max_iter=10000)
            pipeline = Mock()
            pipeline.named_steps = {'classifier': classifier}
            if emits_warning:
                pipeline.fit.side_effect = lambda *args: warnings.warn('failed', ConvergenceWarning)
            with patch.object(training, 'make_candidate', return_value=pipeline), patch.object(training, 'positive_probability') as predict:
                with self.assertRaisesRegex(ValueError, 'did not converge'):
                    training.fit_version(frame, frame, training.NEW_CANDIDATES[0], n_jobs=1)
                predict.assert_not_called()

    def test_invalid_scores_rejected(self):
        frame = route_load_frame('2017-09')
        for values in (np.full(len(frame), np.nan), np.full(len(frame), -0.01)):
            with patch.object(training, 'positive_probability', return_value=values):
                with self.assertRaisesRegex(ValueError, 'Invalid route/load score'):
                    training.fit_version(frame, frame, training.NEW_CANDIDATES[0], n_jobs=1)

    def test_feature_set_inference_dispatch_and_capped_contract(self):
        frame = route_load_frame('2018-02', 100)
        frame['item_count'] = np.tile(np.linspace(.01, .99, 50), 2)
        tables, geo = object(), object()
        for candidate in training.NEW_CANDIDATES:
            feature_set = training.feature_set(candidate)
            backbone, variant = training.FEATURE_SET_DESIGNS[feature_set]
            with patch('scripts.delay_route_load_features.build_route_load_order_features', return_value=frame) as build:
                self.assertIs(build_inference_features({'feature_set': feature_set}, tables, geo), frame)
                build.assert_called_once_with(tables, backbone, variant, geo)
            numeric, categorical = training.feature_names(candidate)
            pipeline = ContractProbabilityPipeline()
            artifact = {'format_version': 1, 'pipeline': pipeline, 'feature_set': feature_set,
                'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
                'threshold': 0., 'daily_alert_cap': .1}
            with self.assertRaises(ValueError):
                predict_features(artifact, frame)
            result = predict_features(artifact, frame, complete_daily_batches=True)
            self.assertEqual(int(result.predicted_delayed.sum()), 10)
            self.assertEqual(pipeline.received_columns, numeric + categorical)
        with self.assertRaisesRegex(ValueError, 'Unsupported feature set'):
            build_inference_features({'feature_set': 'route_load_unknown'}, {})


class RouteLoadSelectionTests(unittest.TestCase):
    def test_selectors_ignore_development_and_paired_tables_cover_all_declared_cells(self):
        validation = [month_frame(month) for month in ('2017-09', '2017-10', '2017-11')]
        evaluation = month_frame('2018-02')
        weak = np.tile(np.linspace(.01, .99, 50), 2)
        strong = weak.copy()
        strong[np.arange(100) % 50 < 4] = 1.
        winner = training.NEW_CANDIDATES[3]
        historical = [{name: strong if name == winner else weak for name in training.ALL_CANDIDATES} for _ in validation]
        development = {name: weak for name in training.ALL_CANDIDATES}
        def decide(frame, scores):
            return budget.decide_ranking_fold(validation, historical, frame, scores, '2018-02-01',
                candidate_order=training.ALL_CANDIDATES, selection_groups=training.SELECTION_GROUPS)
        before = decide(evaluation, development)
        changed = evaluation.copy()
        changed['delayed'], changed['label_available_time'] = 1 - changed.delayed, pd.Timestamp('2099-01-01')
        after = decide(changed, {name: 1-values for name, values in development.items()})
        self.assertEqual(decision_projection(before), decision_projection(after))
        self.assertEqual(before['selected_models']['new_route_load'], winner)
        self.assertEqual(before['selected_models'][training.PRIMARY_SELECTION], winner)
        self.assertIn(before['selected_models']['previous_candidates'], training.PREVIOUS_CANDIDATES)
        folds = [{'name': '2018-02', 'experiment': before}]
        summary = budget.summarize(folds, candidate_order=training.ALL_CANDIDATES, selection_groups=training.SELECTION_GROUPS)
        self.assertEqual(len(summary), 59)
        comparisons = paired_comparisons(folds, summary)
        self.assertEqual(len(comparisons), 3)
        for comparison in comparisons:
            self.assertEqual(set(comparison['candidates']), {'baseline', 'trend', 'cross'})
            for label, candidate in comparison['candidates'].items():
                self.assertEqual(comparison['by_fold']['2018-02'][label]['validation_by_month'], before['models'][candidate]['validation_by_month'])

    def test_frozen_score_phase_checks_cohort_maturity_labels_and_decisions(self):
        frame = month_frame('2017-09', 20)
        frame['fold'], frame['role'], frame['candidate'], frame['model_version'] = '2017-12', 'validation', 'base', '2017-09'
        frame['known_at_selection'] = np.arange(20) < 15
        frame['outcome_for_metrics'] = np.where(frame.known_at_selection, frame.delayed, np.nan)
        frame['delay_score'], frame['predicted_delayed'] = np.linspace(0, 1, 20), np.arange(20) >= 18
        verify_prior_score_part(frame.iloc[::-1].copy(), frame)
        for column, value in (('prediction_time', pd.Timestamp('2099-01-01')), ('fold', 'wrong'),
                ('known_at_selection', False), ('predicted_delayed', True), ('outcome_for_metrics', 0.0), ('delay_score', 0.9)):
            changed = frame.copy()
            changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                verify_prior_score_part(changed, frame)
        with self.assertRaises(ValueError):
            verify_prior_score_part(frame.iloc[:-1], frame)
        with self.assertRaises(ValueError):
            verify_prior_score_part(pd.concat([frame, frame.iloc[:1]]), frame)


if __name__ == '__main__':
    unittest.main()
