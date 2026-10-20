"""Synthetic-only training orchestration, metric arithmetic and output guards."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning

from scripts import review_baseline_evaluation as metrics
from scripts import review_baseline_pipeline as pipeline
from scripts import run_review_baseline as runner


def metric_block(labels=(1, 0, 1, 0, None)):
    states = ['no_visible_answer_at_cutoff' if value is None else
              'known_low_1_2' if value == 1 else 'known_other_3_5' for value in labels]
    return pd.DataFrame({'order_id': [f'synthetic-{i}' for i in range(len(labels))],
                         'role_label_usable': [value is not None for value in labels],
                         'label_state': states, 'y': pd.Series(labels, dtype='Int64')})


class SyntheticBundle:
    def __init__(self):
        rows = []
        for month in ('2017-06', '2017-09', '2017-11', '2017-12', '2018-02', '2018-04'):
            for suffix, wait in [('a', 0), ('b', 4), ('u', 1000)]:
                approval = pd.Timestamp(month + '-05 12:00:00')
                rows.append({'order_id': month + '-' + suffix,
                             'order_purchase_timestamp': approval - pd.Timedelta(hours=wait),
                             'order_approved_at': approval})
        self.raw_orders = pd.DataFrame(rows)
        self.context = pipeline.freeze_approval_roster(self.raw_orders, context_version='synthetic-training-v1')
        self.public_sources, self.private_sources = [], []
        self.summary = {'raw_order_rows': len(rows), 'cohort_order_rows': len(rows),
                        'scope': 'synthetic_metadata_only', 'historical_ingestion_verified': False}
        self.calls = 0
        self.blocks = {}
        for fold in runner.FOLDS:
            for role in ('inner_train_pool', 'inner_validation', 'outer_train_pool', 'outer_evaluation'):
                start, end, fit = pipeline._plan(fold, role)
                mask = self.raw_orders.order_approved_at.lt(end)
                if start is not None:
                    mask &= self.raw_orders.order_approved_at.ge(start)
                raw = self.raw_orders.loc[mask].sort_values(['order_approved_at', 'order_id'])
                cutoff = fit if role.endswith('train_pool') else pd.Timestamp(fold + '-01') if role == 'inner_validation' else pd.Timestamp('2018-07-01')
                records = []
                for row in raw.itertuples(index=False):
                    t, deadline = row.order_approved_at, row.order_approved_at + pd.Timedelta(days=60)
                    mature = deadline < cutoff
                    no_answer = row.order_id.endswith('-u')
                    y = pd.NA if no_answer or not mature else int(row.order_id.endswith('-b'))
                    first = pd.NaT if no_answer or t + pd.Timedelta(days=1) >= cutoff else t + pd.Timedelta(days=1)
                    state = ('immature_observation_window' if not mature else 'no_visible_answer_at_cutoff'
                             if no_answer else 'known_low_1_2' if y == 1 else 'known_other_3_5')
                    records.append({'outer_fold': fold, 'role': role, 'fit_at': fit, 'order_id': row.order_id,
                                    'prediction_time': t, 'window_deadline': deadline, 'observation_cutoff': cutoff,
                                    'horizon_complete': mature, 'label_state': state,
                                    'role_label_usable': not pd.isna(y), 'y': y, 'first_visible_answer_at': first})
                block = pd.DataFrame(records).loc[:, list(pipeline.MEMBERSHIP_COLUMNS)]
                block['y'] = block.y.astype('Int64')
                self.blocks[(fold, role)] = block

    def verify_stable(self):
        self.calls += 1
        return {'unchanged': True}

    def role_block(self, fold, role):
        return self.blocks[(fold, role)].copy(deep=True)

    def prediction_block(self, fold, role):
        block = self.role_block(fold, role)
        for name in ('window_deadline', 'observation_cutoff', 'horizon_complete', 'label_state',
                     'role_label_usable', 'y', 'first_visible_answer_at'):
            block[name] = pd.NA
        return block


def synthetic_spec():
    return {'execution_plan': runner.execution_plan(), 'method_reference': {'sha256': runner.PARENT_SHA}}


class ReviewBaselineEvaluationTest(unittest.TestCase):
    def test_hand_derived_metrics_and_unknown_exclusion(self):
        block = metric_block()
        p = pd.Series([.9, .8, .2, .1, 1.], index=block.order_id)
        result = metrics.evaluate_role(p, block)
        self.assertEqual(result['coverage']['full_orders'], 5)
        self.assertEqual(result['coverage']['known_labels'], 4)
        self.assertAlmostEqual(result['metrics']['average_precision'], 5/6)
        self.assertAlmostEqual(result['metrics']['roc_auc'], 3/4)
        self.assertAlmostEqual(result['metrics']['brier'], .325)
        self.assertAlmostEqual(result['metrics']['binary_log_loss'], -(np.log(.9)+np.log(.2))/2)
        self.assertEqual([result['metrics'][name] for name in ('TP', 'FP', 'TN', 'FN')], [1, 1, 1, 1])
        p.iloc[-1] = 0
        self.assertEqual(metrics.evaluate_role(p, block), result)

    def test_AP_tied_threshold_and_confusion_inclusive_point_five(self):
        block = metric_block((1, 0, 1, 0))
        result = metrics.evaluate_role(pd.Series(.5, index=block.order_id), block)['metrics']
        self.assertEqual(result['average_precision'], .5)
        self.assertEqual(result['roc_auc'], .5)
        self.assertEqual([result[name] for name in ('TP', 'FP', 'TN', 'FN')], [2, 2, 0, 0])

    def test_one_class_AP_ROC_null_but_binary_loss_and_brier_defined(self):
        block = metric_block((1, 1))
        result = metrics.evaluate_role(pd.Series([0., 1.], index=block.order_id), block)['metrics']
        self.assertIsNone(result['average_precision'])
        self.assertIsNone(result['roc_auc'])
        self.assertEqual(result['brier'], .5)
        self.assertTrue(np.isfinite(result['binary_log_loss']))
        self.assertEqual(result['recall'], .5)
        with self.assertRaises(ValueError):
            metrics.constant_reference_probability(block)

    def test_no_known_metrics_all_null_and_precision_recall_zero_denominators(self):
        block = metric_block((None, None))
        self.assertTrue(all(value is None for value in metrics.evaluate_role(pd.Series([0., 1.], index=block.order_id), block)['metrics'].values()))
        block = metric_block((0, 0))
        result = metrics.evaluate_role(pd.Series(0., index=block.order_id), block)['metrics']
        self.assertIsNone(result['precision'])
        self.assertIsNone(result['recall'])

    def test_unknown_nonfinite_or_missing_full_query_probability_rejected(self):
        block = metric_block()
        for p in [[.9, .8, .2, .1, np.nan], [.9, .8, .2, .1, -1], [.9, .8, .2, .1, 2]]:
            with self.assertRaises(ValueError):
                metrics.evaluate_role(pd.Series(p, index=block.order_id), block)
        with self.assertRaises(ValueError):
            metrics.evaluate_role(pd.Series([.1]*4, index=block.order_id.iloc[:4]), block)
        with self.assertRaises(ValueError):
            metrics.evaluate_role(pd.Series(.1, index=block.order_id.iloc[::-1]), block)

    def test_unknown_label_imputation_is_not_a_negative(self):
        block = metric_block()
        block.loc[4, 'y'] = 0
        with self.assertRaises(ValueError):
            metrics.label_support(block)

    def test_frozen_global_max_tie_tolerance_smallestC(self):
        evidence = metrics.select_candidate({.1: .8-5e-13, 1.: .8, 10.: .7})
        self.assertEqual(evidence['selected_C'], .1)
        self.assertEqual(evidence['candidates_within_tolerance'], [.1, 1.])
        self.assertFalse(evidence['reference_in_selection'])
        self.assertEqual(metrics.select_candidate({.1: .7, 1.: .8, 10.: .8})['selected_C'], 1.)

    def test_missing_nonfinite_bool_or_impossible_candidate_AP_stops(self):
        for scores in [{.1: .5, 1.: .6}, {.1: .5, 1.: np.nan, 10.: .6},
                       {.1: True, 1.: .6, 10.: .7}, {.1: -.1, 1.: .6, 10.: .7},
                       {.1: 1.1, 1.: .6, 10.: .7}]:
            with self.assertRaises(ValueError):
                metrics.select_candidate(scores)

    def test_macro_requires_all_three_valid_months(self):
        rows = [{'metrics': {'average_precision': value}} for value in [.2, .6, 1.]]
        self.assertAlmostEqual(metrics.macro_average_precision(rows)['macro_average_precision'], .6)
        rows[1]['metrics']['average_precision'] = None
        aggregate = metrics.macro_average_precision(rows)
        self.assertIsNone(aggregate['macro_average_precision'])
        self.assertEqual(aggregate['valid_folds'], 2)
        self.assertFalse(aggregate['pooled_average_precision_computed'])


class ReviewBaselineTrainingTest(unittest.TestCase):
    def test_complete_synthetic_twelve_fits_all_queries_and_references(self):
        bundle = SyntheticBundle()
        with patch.object(runner, 'GuardedReviewBaseline', wraps=runner.GuardedReviewBaseline) as factory:
            public, inner, outer, fits = runner.execute_training(bundle, synthetic_spec())
        self.assertEqual(factory.call_count, 12)
        self.assertEqual(public['execution']['estimator_fits_completed'], 12)
        self.assertEqual(public['execution']['reference_prior_computations'], 6)
        self.assertEqual(public['execution']['prediction_blocks_completed'], 18)
        self.assertEqual(public['execution']['score_rows_across_blocks'], 54)
        self.assertEqual(len(inner), 36)
        self.assertEqual(len(outer), 18)
        self.assertEqual(len(fits['fit_records']), 12)
        self.assertTrue(inner.loc[~inner.role_label_usable, 'y'].isna().all())
        self.assertTrue(outer.loc[~outer.role_label_usable, 'y'].isna().all())
        self.assertEqual(len(public['outer_folds']), 3)
        self.assertFalse(public['execution']['outer_labels_used_in_selection'])
        self.assertTrue(all(item['output_columns'] == 44 for item in public['fit_context_audits']))
        self.assertGreaterEqual(bundle.calls, 26)

    def test_outer_evaluation_result_changes_do_not_steer_any_selection(self):
        first, second = SyntheticBundle(), SyntheticBundle()
        for fold in runner.FOLDS:
            block = second.blocks[(fold, 'outer_evaluation')]
            known = block.role_label_usable
            block.loc[known, 'y'] = 1-block.loc[known, 'y']
            block.loc[known, 'label_state'] = ['known_low_1_2' if value == 1 else 'known_other_3_5' for value in block.loc[known, 'y']]
        one = runner.execute_training(first, synthetic_spec())[0]
        two = runner.execute_training(second, synthetic_spec())[0]
        self.assertEqual([item['selection'] for item in one['outer_folds']], [item['selection'] for item in two['outer_folds']])

    def test_candidate_failure_stops_no_fallback_records_context(self):
        bundle = SyntheticBundle()
        with patch.object(runner.GuardedReviewBaseline, 'fit_orders', side_effect=ConvergenceWarning('synthetic')) as fit:
            with self.assertRaises(runner.TrainingStopped) as stopped:
                runner.execute_training(bundle, synthetic_spec())
        self.assertEqual(fit.call_count, 1)
        self.assertEqual(stopped.exception.context['completed_estimator_fits'], 0)
        self.assertEqual(stopped.exception.context['outer_fold'], '2017-12')
        self.assertEqual(stopped.exception.context['C'], .1)
        self.assertEqual(stopped.exception.context['phase'], 'inner_fit')

    def test_full_source_verifier_callback_before_after_fit(self):
        bundle = SyntheticBundle()
        calls = []
        def guard():
            calls.append(1)
            if len(calls) == 3:
                raise ValueError('synthetic implementation-source drift after first fit')
        with self.assertRaises(runner.TrainingStopped) as stopped:
            runner.execute_training(bundle, synthetic_spec(), source_verifier=guard)
        self.assertEqual(stopped.exception.context['completed_estimator_fits'], 1)
        self.assertEqual(stopped.exception.context['C'], .1)
        self.assertEqual(len(calls), 3)

    def test_changed_execution_plan_rejected_before_any_fit(self):
        spec = synthetic_spec()
        spec['execution_plan']['C_candidates'] = [.1, 1.]
        with patch.object(runner, 'GuardedReviewBaseline') as factory:
            with self.assertRaises(runner.TrainingStopped):
                runner.execute_training(SyntheticBundle(), spec)
        factory.assert_not_called()

    def test_synthetic_ledger_exact_binary64_nullable_roundtrip(self):
        _, inner, outer, _ = runner.execute_training(SyntheticBundle(), synthetic_spec())
        for frame in (inner, outer):
            data = runner._csv_bytes(frame)
            checked = runner.verify_score_bytes(frame, data)
            self.assertTrue(checked['binary64_probabilities_exact'])
            self.assertEqual(checked['exact_cells_compared'], len(frame)*15)
            self.assertTrue(runner.read_score_csv(data).loc[~frame.role_label_usable, 'y'].isna().all())

    def test_existing_output_or_failure_receipt_refuses_retraining(self):
        runtime = runner.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            output = folder / 'report.json'
            private = folder / 'private'
            private.mkdir()
            (private / runner.FAILURE_NAME).write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                runner.ensure_outputs_absent(output, private)

    def test_unsafe_output_ancestor_and_control_collision_rejected_before_fit(self):
        runtime = runner.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            spec, guard = folder/'spec.json', folder/'guard.json'
            spec.write_text('{}', encoding='utf-8')
            guard.write_text('{}', encoding='utf-8')
            blocked = folder/'regular-file'
            blocked.write_text('file', encoding='utf-8')
            with self.assertRaises(ValueError):
                runner.preflight_execution_paths(SyntheticBundle(), {'public_sources': []}, spec, guard,
                                                folder/'report.json', blocked/'child')
            with self.assertRaises(ValueError):
                runner.preflight_execution_paths(SyntheticBundle(), {'public_sources': []}, spec, guard,
                                                guard, folder/'private')

    def test_failure_receipt_records_fold_phase_completed_fit_count_private(self):
        runtime = runner.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            error = runner.TrainingStopped({'outer_fold': '2017-12', 'role': 'inner_train_pool', 'C': .1,
                                            'phase': 'inner_prediction_and_evaluation', 'completed_estimator_fits': 1}, ValueError())
            receipt = runner.write_failure_receipt(error, folder, folder/'spec.json')
            self.assertEqual(receipt['execution_context']['completed_estimator_fits'], 1)
            self.assertFalse(receipt['automatic_retry'])
            self.assertTrue((folder/runner.FAILURE_NAME).is_file())

    def test_synthetic_spec_guard_and_full_bundle_publication_without_retraining(self):
        runtime = runner.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            bundle = SyntheticBundle()
            specfile, guardfile, reportfile = folder/'spec.json', folder/'guard.json', folder/'report.json'
            private = folder/'outputs'
            spec = runner.freeze_specification(bundle, specfile, guardfile)
            runner.preflight_execution_paths(bundle, spec, specfile, guardfile, reportfile, private)
            execution = runner.execute_training(bundle, spec)
            result = runner.publish(bundle, spec, specfile, guardfile, reportfile, private, execution)
            self.assertEqual(result['results']['execution']['estimator_fits_completed'], 12)
            self.assertEqual(result['source_roster_verification']['raw_order_rows'], 18)
            self.assertEqual(result['private_outputs']['inner_scores.csv']['rows'], 36)
            manifest = runner.files.read_json(private/'manifest.json')
            self.assertEqual(manifest['specification'], runner.files.descriptor(specfile))
            self.assertEqual(manifest['public_report'], runner.files.descriptor(reportfile))
            self.assertEqual(len(runner.files.read_json(private/'fit_audit.json')['fit_records']), 12)
            with self.assertRaises(ValueError):
                runner.ensure_outputs_absent(reportfile, private)

    def test_late_publication_verification_failure_removes_only_new_report(self):
        runtime = runner.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            bundle = SyntheticBundle()
            specfile, guardfile, reportfile = folder/'spec.json', folder/'guard.json', folder/'report.json'
            private = folder/'outputs'
            spec = runner.freeze_specification(bundle, specfile, guardfile)
            execution = runner.execute_training(bundle, spec)
            original = bundle.verify_stable
            def late_failure():
                if reportfile.exists():
                    raise ValueError('synthetic final post-publication guard failure')
                return original()
            bundle.verify_stable = late_failure
            with self.assertRaises(ValueError):
                runner.publish(bundle, spec, specfile, guardfile, reportfile, private, execution)
            self.assertFalse(reportfile.exists())
            self.assertTrue(specfile.exists())
            self.assertTrue(guardfile.exists())

    def test_output_alias_is_rejected_before_any_fit(self):
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(ValueError):
                runner.reject_output_aliases(runner.ROOT/'.runtime/dangling-output')


if __name__ == '__main__':
    unittest.main()
