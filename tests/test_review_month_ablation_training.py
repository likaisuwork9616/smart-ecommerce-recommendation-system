"""Synthetic-only dispatcher tests; frozen real sources are never loaded here."""
from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning

from scripts import prepare_review_month_ablation as policy
from scripts import review_baseline_evaluation as evaluation
from scripts import review_baseline_pipeline as common
from scripts import review_month_ablation_training as training
from scripts import review_month_ablation_pairing as pairing
from tests.test_review_month_ablation_pairing import synthetic_control_fixture


def synthetic_training_bundle():
    bundle, report, inner, outer = synthetic_control_fixture()
    bundle.control_report, bundle.control_scores = report, {'inner_scores.csv': inner, 'outer_scores.csv': outer}
    refresh_synthetic_control(bundle)
    return bundle


def refresh_synthetic_control(bundle):
    """Build synthetic frozen-control report values without constructing a model."""
    for fold_report in bundle.control_report['results']['outer_folds']:
        fold = fold_report['outer_fold']
        for role, file, train_role in [('inner_validation', 'inner_scores.csv', 'inner_train_pool'),
                                       ('outer_evaluation', 'outer_scores.csv', 'outer_train_pool')]:
            truth = bundle.role_block(fold, role)
            scores = bundle.control_scores[file]
            prior = evaluation.constant_reference_probability(bundle.role_block(fold, train_role))
            for model, C in pairing._plans(role, fold_report['selection']['selected_C']):
                mask = pairing._select(scores, fold, role, model, C)
                for name in common.MEMBERSHIP_COLUMNS:
                    scores.loc[mask, name] = truth[name].to_numpy()
                if model == 'constant_reference':
                    scores.loc[mask, 'probability_low_1_2'] = prior
                p = pd.Series(scores.loc[mask, 'probability_low_1_2'].to_numpy(),
                              index=pd.Index(truth.order_id, name='order_id'))
                metrics = evaluation.evaluate_role(p, truth)
                if model == 'constant_reference':
                    fold_report['inner_reference' if role == 'inner_validation' else 'outer_reference'] = metrics
                elif model == 'logistic_selected':
                    fold_report['outer_selected'] = metrics
                else:
                    next(item for item in fold_report['inner_candidates'] if item['C'] == C)['evaluation'] = metrics
    bundle.control_report['results']['aggregate_selected'] = evaluation.macro_average_precision(
        [item['outer_selected'] for item in bundle.control_report['results']['outer_folds']])


def synthetic_specification():
    return {'execution_plan': policy.execution_plan()}


class SyntheticModel:
    """Deterministic orchestration double, with explicitly synthetic fit audit."""
    instances = []

    def __init__(self, C, *, context):
        self.C, self.context = C, context
        self.instances.append(self)

    def fit_orders(self, raw, block, *, outer_fold, role):
        self.raw, self.block, self.fold, self.role = raw.copy(deep=True), block.copy(deep=True), outer_fold, role
        return self

    def predict_orders(self, raw, query, *, outer_fold, role):
        if not query.loc[:, list(training.sources.FUTURE_QUERY_COLUMNS)].isna().all().all():
            raise AssertionError('Synthetic double observed future truth')
        good = self.C != .1
        values = [(.8 if good else .2) if order.endswith('-b') else
                  (.2 if good else .8) if order.endswith('-a') else .99 for order in query.order_id]
        return pd.Series(values, index=pd.Index(query.order_id, name='order_id'), dtype='float64')

    def audit_state(self):
        eligible = self.block.loc[self.block.role_label_usable, 'order_id']
        raw = self.raw.set_index('order_id').loc[eligible]
        waits = (raw.order_approved_at - raw.order_purchase_timestamp).dt.total_seconds().to_numpy() / 3600
        return {'state': 'FITTED', 'C': self.C, 'fit_context': (self.fold, self.role, common._plan(self.fold, self.role)[2]),
                'context_version': self.context.context_version,
                'eligible_order_ids': tuple(eligible), 'train_pool_order_ids': tuple(self.block.order_id),
                'output_columns': training.pipeline.OUTPUT_COLUMNS,
                'scaler_samples': len(eligible), 'scaler_mean': np.array([waits.mean()]),
                'scaler_variance': np.array([waits.var(ddof=0)]),
                'scaler_scale': np.array([waits.std(ddof=0) or 1.]), 'coefficient_values': np.zeros((1, 32)),
                'intercept_values': np.zeros(1), 'classes': np.array([0, 1])}


class ReviewMonthAblationTrainingTest(unittest.TestCase):
    def setUp(self):
        self.bundle = synthetic_training_bundle()
        SyntheticModel.instances = []

    def run_synthetic_double(self, bundle=None, **kwargs):
        with patch.object(training, 'GuardedReviewMonthAblation', SyntheticModel):
            return training.execute_training(bundle or self.bundle, synthetic_specification(), **kwargs)

    def assert_stopped(self, expected_fits, action, phase=None):
        with self.assertRaises(training.TrainingStopped) as caught:
            action()
        self.assertEqual(caught.exception.context['completed_estimator_fits'], expected_fits)
        if phase is not None:
            self.assertEqual(caught.exception.context['phase'], phase)
        return caught.exception

    def test_actual_synthetic_twelve_fresh_fits_fixed32_no_control_model(self):
        actual = training.GuardedReviewMonthAblation
        instances = []

        def factory(*args, **kwargs):
            model = actual(*args, **kwargs)
            instances.append(model)
            return model

        with (patch.object(training, 'GuardedReviewMonthAblation', side_effect=factory),
              patch.object(common.GuardedReviewBaseline, '__init__', side_effect=AssertionError('No control fit')),
              patch.object(training.evaluation, 'select_candidate', wraps=evaluation.select_candidate) as selector):
            result, inner, outer, audit, paired = training.execute_training(self.bundle, synthetic_specification())
        self.assertEqual(len(instances), 12)
        self.assertEqual(len({id(model) for model in instances}), 12)
        self.assertEqual(selector.call_count, 3)
        self.assertEqual(result['execution']['estimator_fits_completed'], 12)
        self.assertEqual(result['execution']['inner_candidates_evaluated'], 9)
        self.assertEqual(result['execution']['outer_refits_completed'], 3)
        self.assertEqual(result['execution']['control_fits'], 0)
        self.assertEqual([len(inner), len(outer)], [36, 18])
        self.assertEqual(paired['score_blocks'], 18)
        self.assertEqual([item['fit_sequence'] for item in audit['fit_records']], list(range(1, 13)))
        self.assertTrue(all(len(item['output_columns']) == 32 for item in audit['fit_records']))
        self.assertTrue(all(len(item['coefficient_values'][0]) == 32 for item in audit['fit_records']))
        self.assertEqual(tuple(audit), training.FIT_AUDIT_KEYS)
        self.assertTrue(all(tuple(item) == training.FIT_RECORD_KEYS for item in audit['fit_records']))
        self.assertGreaterEqual(self.bundle.calls, 27)

    def test_independent_inner_AP_selects_C1_while_control_remains_C_point1(self):
        result, inner, outer, audit, paired = self.run_synthetic_double()
        self.assertEqual([item['selection']['selected_C'] for item in result['outer_folds']], [1.] * 3)
        self.assertEqual([item['selection']['selected_C'] for item in self.bundle.control_report['results']['outer_folds']], [.1] * 3)
        self.assertEqual([item['C'] for item in audit['fit_records']], [.1, 1., 10., 1.] * 3)
        selected = [item for item in paired['paired_blocks'] if item['model'] == 'logistic_selected']
        self.assertTrue(all(item['treatment_C'] == 1 and item['control_C'] == .1 for item in selected))
        self.assertEqual(paired['independent_treatment_selection']['selection_calls'], 3)
        self.assertFalse(paired['independent_treatment_selection']['control_C_used'])
        self.assertEqual(len(SyntheticModel.instances), 12)

    def test_all_unknown_queries_scored_and_train_unknowns_excluded_before_scaling(self):
        result, inner, outer, audit, paired = self.run_synthetic_double()
        for frame in (inner, outer):
            unknown = frame.loc[~frame.role_label_usable]
            self.assertTrue(unknown.y.isna().all())
            self.assertTrue(np.isfinite(unknown.probability_low_1_2).all())
            self.assertGreater(len(unknown), 0)
        self.assertTrue(all(not any(order.endswith('-u') for order in item['eligible_order_ids']) for item in audit['fit_records']))
        self.assertTrue(all(item['scaler_mean'] == [2.] and item['scaler_variance'] == [4.] for item in audit['fit_records']))
        self.assertTrue(all(item['scaler_samples'] == item['eligible_orders'] for item in audit['fit_records']))
        self.assertTrue(paired['constant_reference_equality'])

    def test_existing_truth_control_scores_and_report_are_never_mutated(self):
        before = deepcopy(self.bundle)
        self.run_synthetic_double()
        pd.testing.assert_frame_equal(self.bundle.raw_orders, before.raw_orders)
        for key, value in before.blocks.items():
            pd.testing.assert_frame_equal(self.bundle.blocks[key], value)
        for key, value in before.control_scores.items():
            pd.testing.assert_frame_equal(self.bundle.control_scores[key], value)
        self.assertEqual(self.bundle.control_report, before.control_report)

    def test_outer_outcomes_cannot_change_treatment_selection(self):
        original = self.run_synthetic_double()[0]
        changed = deepcopy(self.bundle)
        for fold in training.FOLDS:
            truth = changed.blocks[(fold, 'outer_evaluation')]
            usable = truth.role_label_usable
            truth.loc[usable, 'y'] = 1 - truth.loc[usable, 'y']
            truth.loc[usable, 'label_state'] = truth.loc[usable, 'y'].map({1: 'known_low_1_2', 0: 'known_other_3_5'})
        refresh_synthetic_control(changed)
        altered = self.run_synthetic_double(changed)[0]
        self.assertEqual([item['selection'] for item in original['outer_folds']],
                         [item['selection'] for item in altered['outer_folds']])
        self.assertNotEqual(original['aggregate_selected'], altered['aggregate_selected'])

    def test_unknown_probability_does_not_enter_metrics_or_selection(self):
        original = self.run_synthetic_double()[0]
        original_predict = SyntheticModel.predict_orders

        def changed(model, raw, query, **kwargs):
            p = original_predict(model, raw, query, **kwargs)
            p.loc[p.index.str.endswith('-u')] = 0
            return p

        with patch.object(SyntheticModel, 'predict_orders', changed):
            altered = self.run_synthetic_double()[0]
        self.assertEqual(original, altered)

    def test_malformed_last_training_context_stops_before_any_model(self):
        block = self.bundle.blocks[(training.FOLDS[-1], 'outer_train_pool')]
        block.loc[block.role_label_usable, 'first_visible_answer_at'] = block.fit_at.iloc[0]
        error = self.assert_stopped(0, self.run_synthetic_double, 'all_roles_preflight')
        self.assertEqual(error.context['outer_fold'], training.FOLDS[-1])
        self.assertEqual(len(SyntheticModel.instances), 0)

    def test_missing_last_query_ID_stops_before_any_model(self):
        self.bundle.blocks[(training.FOLDS[-1], 'outer_evaluation')] = self.bundle.blocks[(training.FOLDS[-1], 'outer_evaluation')].iloc[:-1]
        self.assert_stopped(0, self.run_synthetic_double, 'all_roles_preflight')
        self.assertEqual(len(SyntheticModel.instances), 0)

    def test_last_inner_validation_one_class_stops_before_any_model(self):
        block = self.bundle.blocks[(training.FOLDS[-1], 'inner_validation')]
        usable = block.role_label_usable
        block.loc[usable, 'y'] = 1
        block.loc[usable, 'label_state'] = 'known_low_1_2'
        self.assert_stopped(0, self.run_synthetic_double, 'all_roles_preflight')
        self.assertEqual(len(SyntheticModel.instances), 0)

    def test_all_seven_future_truth_columns_must_be_cleared_before_any_model(self):
        original = self.bundle.prediction_block
        for name in training.sources.FUTURE_QUERY_COLUMNS:
            def leaked(fold, role, field=name):
                query = original(fold, role)
                query[field] = self.bundle.role_block(fold, role)[field]
                return query
            with self.subTest(field=name), patch.object(self.bundle, 'prediction_block', side_effect=leaked):
                self.assert_stopped(0, self.run_synthetic_double, 'all_roles_preflight')
        self.assertEqual(len(SyntheticModel.instances), 0)

    def test_control_row_permutation_or_loss_stops_before_any_model(self):
        original = self.bundle.control_scores['inner_scores.csv']
        for changed in [original.iloc[1:].copy(), original.iloc[::-1].reset_index(drop=True)]:
            self.bundle.control_scores['inner_scores.csv'] = changed
            self.assert_stopped(0, self.run_synthetic_double, 'frozen_control_preflight')
        self.assertEqual(len(SyntheticModel.instances), 0)

    def test_changed_execution_policy_stops_before_any_model(self):
        spec = synthetic_specification()
        spec['execution_plan']['C_candidates'] = [.1, 1.]
        with patch.object(training, 'GuardedReviewMonthAblation', SyntheticModel):
            self.assert_stopped(0, lambda: training.execute_training(self.bundle, spec), 'execution_specification_validation')
        self.assertEqual(len(SyntheticModel.instances), 0)

    def test_source_changes_before_second_fit_stop_without_retry(self):
        calls = 0

        def verify():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise ValueError('Synthetic bound source changed')

        error = self.assert_stopped(1, lambda: self.run_synthetic_double(verify_sources=verify), 'source_before_fit')
        self.assertEqual(error.context['C'], 1.)
        self.assertEqual(len(SyntheticModel.instances), 1)

    def test_source_changes_after_prediction_count_completed_fit(self):
        calls = 0

        def verify():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise ValueError('Synthetic source drift')

        self.assert_stopped(1, lambda: self.run_synthetic_double(verify_sources=verify), 'source_after_prediction')
        self.assertEqual(len(SyntheticModel.instances), 1)

    def test_candidate_fit_failure_does_not_drop_candidate_or_retry(self):
        original = SyntheticModel.fit_orders

        def failed(model, *args, **kwargs):
            if model.C == 1:
                raise ConvergenceWarning('Synthetic nonconvergence')
            return original(model, *args, **kwargs)

        with patch.object(SyntheticModel, 'fit_orders', failed):
            error = self.assert_stopped(1, self.run_synthetic_double, 'fit')
        self.assertEqual(error.cause_type, 'ConvergenceWarning')
        self.assertEqual(len(SyntheticModel.instances), 2)

    def test_first_outer_fit_failure_stops_later_folds(self):
        original = SyntheticModel.fit_orders

        def failed(model, *args, **kwargs):
            if kwargs['role'] == 'outer_train_pool':
                raise ValueError('Synthetic outer failure')
            return original(model, *args, **kwargs)

        with patch.object(SyntheticModel, 'fit_orders', failed):
            error = self.assert_stopped(3, self.run_synthetic_double, 'fit')
        self.assertEqual(error.context['outer_fold'], training.FOLDS[0])
        self.assertEqual(len(SyntheticModel.instances), 4)

    def test_prediction_failure_counts_fit_and_stops_before_next_candidate(self):
        with patch.object(SyntheticModel, 'predict_orders', side_effect=ValueError('Synthetic prediction failure')):
            self.assert_stopped(1, self.run_synthetic_double, 'prediction')
        self.assertEqual(len(SyntheticModel.instances), 1)

    def test_nonfinite_unknown_prediction_stops_without_silently_dropping_row(self):
        original = SyntheticModel.predict_orders

        def invalid(model, *args, **kwargs):
            probabilities = original(model, *args, **kwargs)
            probabilities.iloc[-1] = np.nan
            return probabilities

        with patch.object(SyntheticModel, 'predict_orders', invalid):
            self.assert_stopped(1, self.run_synthetic_double, 'evaluation_and_fit_audit')
        self.assertEqual(len(SyntheticModel.instances), 1)

    def test_missing_or_reordered_prediction_stops_at_first_fit(self):
        original = SyntheticModel.predict_orders
        for reverse in (False, True):
            def invalid(model, *args, **kwargs):
                result = original(model, *args, **kwargs)
                return result.iloc[::-1] if reverse else result.iloc[:-1]
            with patch.object(SyntheticModel, 'predict_orders', invalid):
                self.assert_stopped(1, self.run_synthetic_double, 'evaluation_and_fit_audit')

    def test_false_diagnostics_32_columns_scaler_roster_or_fit_context_stop(self):
        original = SyntheticModel.audit_state
        changes = [('output_columns', tuple(range(32))), ('scaler_mean', np.array([99.])),
                   ('scaler_samples', 123), ('eligible_order_ids', ('wrong-id',)),
                   ('coefficient_values', np.zeros((1, 44))), ('fit_context', ('2018-04', 'outer_train_pool', pd.Timestamp('2018-04-01')))]
        for key, value in changes:
            def invalid(model, field=key, replacement=value):
                state = original(model)
                state[field] = replacement
                return state
            with self.subTest(field=key), patch.object(SyntheticModel, 'audit_state', invalid):
                self.assert_stopped(1, self.run_synthetic_double, 'evaluation_and_fit_audit')

    def test_reused_model_instance_rejected_before_second_fit(self):
        model = SyntheticModel(.1, context=self.bundle.context)
        with patch.object(training, 'GuardedReviewMonthAblation', return_value=model):
            self.assert_stopped(1, lambda: training.execute_training(self.bundle, synthetic_specification()), 'model_construction')

    def test_final_pairing_failure_retains_all12_fit_count_without_success(self):
        with patch.object(training.pairing, 'validate_treatment_pairing', side_effect=ValueError('Synthetic same-ID failure')):
            self.assert_stopped(12, self.run_synthetic_double, 'complete_same_id_pairing')
        self.assertEqual(len(SyntheticModel.instances), 12)

    def test_actual_final_ledger_ID_corruption_is_rejected(self):
        original = training._ledger

        def corrupt(block, p, model, C):
            result = original(block, p, model, C)
            if model == 'logistic_selected':
                result.loc[result.index[-1], 'order_id'] = 'synthetic-wrong-id'
            return result

        with patch.object(training, '_ledger', side_effect=corrupt):
            self.assert_stopped(12, self.run_synthetic_double, 'complete_same_id_pairing')

    def test_private_acceptance_binds_exact_score_and_fit_audit_payload_bytes(self):
        public, inner, outer, audit, paired = self.run_synthetic_double()
        payloads = {'inner_scores.csv': training._csv_bytes(inner),
                    'outer_scores.csv': training._csv_bytes(outer),
                    'fit_audit.json': training.files.json_bytes(audit)}
        expected = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    for name, data in payloads.items()}
        self.assertEqual(paired['accepted_treatment_file_digests'], expected)
        public_bytes = training.files.json_bytes(public)
        self.assertEqual(paired['accepted_public_results_digest'],
                         {'bytes': len(public_bytes), 'sha256': hashlib.sha256(public_bytes).hexdigest()})
        inner.loc[0, 'order_id'] = 'synthetic-tampered-after-acceptance'
        self.assertNotEqual(hashlib.sha256(training._csv_bytes(inner)).hexdigest(),
                            expected['inner_scores.csv']['sha256'])
        audit['fit_records'][0]['coefficient_values'][0][0] = .123
        self.assertNotEqual(hashlib.sha256(training.files.json_bytes(audit)).hexdigest(),
                            expected['fit_audit.json']['sha256'])
        public['outer_folds'][0]['outer_selected']['metrics']['brier'] = .987654321
        self.assertNotEqual(hashlib.sha256(training.files.json_bytes(public)).hexdigest(),
                            paired['accepted_public_results_digest']['sha256'])

    def test_final_source_failure_retains12_and_no_success(self):
        calls = 0

        def verify():
            nonlocal calls
            calls += 1
            if calls == 27:
                raise ValueError('Synthetic final source drift')

        self.assert_stopped(12, lambda: self.run_synthetic_double(verify_sources=verify), 'final_source_verification')

    def test_null_deltas_remain_null_not_zero(self):
        left = dict.fromkeys(training.METRIC_NAMES, .2)
        right = dict.fromkeys(training.METRIC_NAMES, .1)
        left['precision'] = None
        right['recall'] = None
        delta = training.metric_difference(left, right)
        self.assertIsNone(delta['precision'])
        self.assertIsNone(delta['recall'])
        self.assertAlmostEqual(delta['average_precision'], .1)
        for bad in (float('nan'), True, '0.2'):
            left['brier'] = bad
            with self.assertRaises(ValueError):
                training.metric_difference(left, right)

    def test_one_class_outer_kept_macro_null_no_fold_dropped(self):
        block = self.bundle.blocks[(training.FOLDS[-1], 'outer_evaluation')]
        known = block.role_label_usable
        block.loc[known, 'y'] = 1
        block.loc[known, 'label_state'] = 'known_low_1_2'
        refresh_synthetic_control(self.bundle)
        result, _, _, audit, _ = self.run_synthetic_double()
        self.assertEqual(len(audit['fit_records']), 12)
        self.assertEqual(len(result['outer_folds']), 3)
        self.assertIsNone(result['aggregate_selected']['macro_average_precision'])
        macro = result['paired_comparison']['macro_average_precision']
        self.assertIsNone(macro['treatment_minus_control'])
        self.assertEqual(macro['control_valid_folds'], 2)

    def test_no_known_outer_labels_kept_fullquery_and_null_metrics(self):
        block = self.bundle.blocks[(training.FOLDS[-1], 'outer_evaluation')]
        block['y'] = pd.Series(pd.NA, index=block.index, dtype='Int64')
        block['role_label_usable'] = False
        block['label_state'] = 'no_visible_answer_at_cutoff'
        block['first_visible_answer_at'] = pd.Series(pd.NaT, index=block.index,
                                                    dtype=block.first_visible_answer_at.dtype)
        refresh_synthetic_control(self.bundle)
        result, _, outer, _, _ = self.run_synthetic_double()
        self.assertTrue(all(value is None for value in result['outer_folds'][-1]['outer_selected']['metrics'].values()))
        self.assertEqual(len(outer), 18)
        self.assertIsNone(result['paired_comparison']['macro_average_precision']['treatment_minus_control'])

    def test_control_metrics_are_read_without_recompute_or_reselection(self):
        original = training.evaluation.evaluate_role
        calls = []

        def counted(probabilities, block):
            calls.append((len(probabilities), block.role.iloc[0]))
            return original(probabilities, block)

        with (patch.object(training.evaluation, 'evaluate_role', side_effect=counted),
              patch.object(training.evaluation, 'select_candidate', wraps=evaluation.select_candidate) as selected):
            result = self.run_synthetic_double()[0]
        self.assertEqual(len(calls), 18)
        self.assertEqual(selected.call_count, 3)
        self.assertEqual(result['execution']['control_metrics_recomputed'], 0)
        self.assertEqual(result['execution']['control_candidate_selections'], 0)

    def test_frozen_control_metric_coverage_schema_and_nonfinite_fail_prefit(self):
        for mutate in [lambda value: value['coverage'].update(full_orders=999),
                       lambda value: value['metrics'].update(average_precision=float('nan')),
                       lambda value: value['metrics'].update(unexpected=0)]:
            bundle = synthetic_training_bundle()
            mutate(bundle.control_report['results']['outer_folds'][-1]['outer_selected'])
            self.assert_stopped(0, lambda: self.run_synthetic_double(bundle), 'frozen_control_preflight')
        self.assertEqual(len(SyntheticModel.instances), 0)

    def test_frozen_control_constant_metric_mismatch_fails_without_success(self):
        self.bundle.control_report['results']['outer_folds'][0]['outer_reference']['metrics']['brier'] += .01
        self.assert_stopped(12, self.run_synthetic_double, 'paired_metric_comparison')

    def test_failed_progress_callback_stops_and_does_not_retry(self):
        def fail(_):
            raise OSError('Synthetic callback failure')
        self.assert_stopped(1, lambda: self.run_synthetic_double(emit=fail), 'evaluation_and_fit_audit')
        self.assertEqual(len(SyntheticModel.instances), 1)


if __name__ == '__main__':
    unittest.main()
