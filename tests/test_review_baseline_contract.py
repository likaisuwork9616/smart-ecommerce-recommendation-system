"""No-fit tests for baseline policy, metadata availability and immutable guards."""
from copy import deepcopy
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import audit_review_baseline_contract as audit


def fixture():
    roster = pd.DataFrame({'order_id': ['low', 'other', 'unknown'],
                           'purchase_time': pd.to_datetime(['2017-08-01'] * 3),
                           'prediction_time': pd.to_datetime(['2017-08-02'] * 3)})
    frame = pd.DataFrame({'order_id': list(roster.order_id),
                          'prediction_time': roster.prediction_time,
                          'window_deadline': roster.prediction_time + pd.Timedelta(days=60),
                          'observation_cutoff': pd.Timestamp('2018-01-01'),
                          'horizon_complete': True,
                          'label_state': ['known_low_1_2', 'known_other_3_5', 'no_visible_answer_at_cutoff'],
                          'role_label_usable': [True, True, False],
                          'y': pd.Series([1, 0, pd.NA], dtype='Int64'),
                          'first_visible_answer_at': pd.to_datetime(['2017-08-03', '2017-08-03', None])})
    expected = {'orders': 3, 'mature_windows': 3, 'immature_windows': 0, 'usable_labels': 2,
                'unknown_or_ineligible_labels': 1, 'low_1_2': 1, 'other_3_5': 1,
                'exclusive_label_states': {state: int(frame.label_state.eq(state).sum()) for state in audit.dataset.STATES}}
    return roster, frame, expected


def checked(frame=None, roster=None, expected=None):
    r, f, e = fixture()
    return audit.block_metadata(f if frame is None else frame, r if roster is None else roster,
                                pd.Timestamp('2018-01-01'), e if expected is None else expected)


class ReviewBaselineContractTest(unittest.TestCase):
    def test_primary_four_and_fixed_44_column_order(self):
        p = audit.protocol()
        self.assertEqual(p['features']['primary_order'], ['purchase_month', 'purchase_dayofweek', 'purchase_hour', 'approval_wait_hours'])
        self.assertEqual(sum(map(len, p['features']['categorical'].values())), 43)
        self.assertEqual(p['features']['output_columns'], 44)
        self.assertEqual(p['features']['output_order'][-1], 'scaled_approval_wait_hours')
        self.assertEqual(p['features']['primary_dtype'], 'float64')
        self.assertIsNone(p['features']['one_hot']['drop'])
        self.assertEqual(p['features']['one_hot']['handle_unknown'], 'error')

    def test_no_imputer_train_only_scaler_zero_variance_and_unknown_policy(self):
        p = audit.protocol()['preprocessing']
        self.assertIsNone(p['imputer'])
        self.assertEqual(p['eligible_fit_rows'], 'role_label_usable_train_only')
        self.assertEqual(p['numeric_scaler']['variance_ddof'], 0)
        self.assertEqual(p['numeric_scaler']['zero_std_scale'], 1)
        self.assertFalse(p['unknown_in_fit'])
        self.assertTrue(p['refit_per_C_and_outer_fit'])
        self.assertIn('stop_fold_keep_full_query', p['missing_nonfinite_or_invalid_X'])

    def test_future_constructor_and_selection_fixed_without_actual_selection(self):
        p = audit.protocol()
        self.assertEqual(p['main_model']['l1_ratio'], 0.0)
        self.assertEqual(p['main_model']['solver'], 'lbfgs')
        self.assertEqual(p['main_model']['penalty_argument'], 'omitted_deprecated')
        self.assertEqual(p['main_model']['n_jobs_argument'], 'omitted')
        self.assertEqual(p['selection']['C_candidates'], [0.1, 1.0, 10.0])
        self.assertEqual(p['selection']['tie_absolute_tolerance'], 1e-12)
        self.assertEqual(p['selection']['tie_break'], 'smallest_C_within_tolerance_of_max')
        self.assertIsNone(p['selection']['actual_selected_C'])
        self.assertFalse(p['selection']['outer_evaluation_used'])
        self.assertFalse(p['reference']['selection_candidate'])
        self.assertFalse(p['reference']['compute_this_run'])
        self.assertEqual(p['stop_rules']['any_candidate_failure_or_nonfinite_AP'], 'stop_fold_no_candidate_removal')

    def test_future_metrics_macro_ap_and_undefined_rules_are_policies_only(self):
        p = audit.protocol()
        e = p['future_evaluation']
        self.assertIn('all_three_months_valid_else_null', e['macro_primary'])
        self.assertFalse(e['pooled_AP'])
        self.assertFalse(e['independent_fold_confidence_interval'])
        self.assertEqual(e['no_known_rows'], 'all_metrics_null')
        self.assertIn('null_if', e['secondary_roc_auc'])
        self.assertEqual(e['primary_AP_undefined'], 'null_if_either_class_absent')
        self.assertIn('at_least_one_known_label_including_one_class', e['brier_and_log_loss_support'])
        self.assertEqual(e['log_loss_labels'], [0, 1])
        self.assertEqual(e['probability_target'], 'P(y=1)')
        self.assertIn('label_1_in_estimator.classes_', e['probability_column'])
        self.assertEqual(e['log_probability_clip'], [1e-15, 1-1e-15])
        self.assertTrue(all(count == 0 for count in p['this_run'].values()))
        for path in [Path(audit.__file__), Path(audit.dataset.__file__)]:
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name.startswith('sklearn') for alias in node.names))
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith('sklearn'))

    def test_installed_API_checked_as_AST_without_model_objects(self):
        checked = audit.local_api_contract()
        self.assertEqual(checked['verification']['classes_checked'], 3)
        self.assertEqual(checked['verification']['package_imports'], 0)
        self.assertEqual(checked['verification']['objects_instantiated'], 0)
        self.assertEqual(checked['classes']['LogisticRegression']['default_expressions']['penalty'], "'deprecated'")

    def test_constructor_parser_and_unsupported_API_fail_closed(self):
        signature = audit.constructor_signature("class Example:\n def __init__(self, *, x=1): pass\n", 'Example')
        self.assertEqual(signature['accepted_parameters'], ['x'])
        self.assertEqual(signature['default_expressions'], {'x': '1'})
        with self.assertRaises(ValueError):
            audit.validate_api_signatures({'LogisticRegression': signature})
        with self.assertRaises(ValueError):
            audit.constructor_signature('class Other: pass', 'Example')

    def test_source_ast_definitions_only_and_other_17_deferred(self):
        result = audit.ast_clock_contract()
        self.assertEqual(len(result['deferred_features']), 17)
        self.assertFalse(result['source_function_executed'])
        self.assertEqual(result['feature_values_computed'], 0)
        self.assertEqual(set(result['primary_expressions_AST_only']), set(audit.PRIMARY))

    def test_unknowns_retained_and_never_preprocessing_fit(self):
        summary = checked()
        self.assertEqual(summary['orders'], 3)
        self.assertEqual(summary['usable_labels'], 2)
        self.assertEqual(summary['unknown_or_ineligible_labels'], 1)
        self.assertEqual(summary['unknown_preprocessing_fit_rows'], 0)
        self.assertEqual(summary['source_clock_support_orders'], 3)

    def test_unknown_cannot_be_assigned_negative(self):
        _, frame, _ = fixture()
        frame.loc[2, 'y'] = 0
        with self.assertRaises(ValueError):
            checked(frame)

    def test_known_missing_label_and_class_state_mismatch_rejected(self):
        for replacement in [pd.NA, 0]:
            _, frame, _ = fixture()
            frame.loc[0, 'y'] = replacement
            with self.assertRaises(ValueError):
                checked(frame)

    def test_full_query_ids_and_canonical_order_cannot_drop_or_duplicate(self):
        _, frame, _ = fixture()
        for modified in [frame.iloc[:2], frame.iloc[::-1], pd.concat([frame, frame.iloc[:1]])]:
            with self.assertRaises(ValueError):
                checked(modified)

    def test_raw_approval_and_horizon_must_match(self):
        for name in ['prediction_time', 'window_deadline', 'observation_cutoff']:
            _, frame, _ = fixture()
            frame.loc[0, name] += pd.Timedelta(seconds=1)
            with self.assertRaises(ValueError):
                checked(frame)

    def test_equal_answer_cutoff_and_wrong_maturity_rejected(self):
        _, frame, _ = fixture()
        frame.loc[0, 'first_visible_answer_at'] = pd.Timestamp('2018-01-01')
        with self.assertRaises(ValueError):
            checked(frame)
        _, frame, _ = fixture()
        frame.loc[0, 'horizon_complete'] = False
        with self.assertRaises(ValueError):
            checked(frame)

    def test_fit_feature_clock_is_own_t_not_future_query_fit_clock(self):
        source = pd.DataFrame({'order_id': ['query'], 'order_purchase_timestamp': ['2018-04-02 00:00:00'],
                               'order_approved_at': ['2018-04-03 00:00:00']}, dtype='string')
        result = audit.raw_clock_roster(source)
        self.assertEqual(len(result), 1)
        self.assertGreater(result.prediction_time.iloc[0], pd.Timestamp('2018-04-01'))
        self.assertFalse(audit.protocol()['features']['query_clocks_before_model_fit_required'])

    def test_raw_only_two_clocks_and_ids_no_status_or_review_values(self):
        source = pd.DataFrame({'order_id': ['one', 'two', 'three'],
                               'order_purchase_timestamp': ['2018-01-01 00:00:00'] * 3,
                               'order_approved_at': ['2018-01-02 00:00:00', None, '2017-01-01 00:00:00']}, dtype='string')
        self.assertEqual(list(audit.raw_clock_roster(source).order_id), ['one'])
        source['order_status'] = 'delivered'
        with self.assertRaises(ValueError):
            audit.raw_clock_roster(source)

    def test_support_requires_both_classes_in_all_three_required_contexts(self):
        blocks = {name: {'both_classes_supported': True} for name in
                  ('inner_train_pool', 'inner_validation', 'outer_train_pool')}
        self.assertEqual(audit.support_decision(blocks), 'supported_for_future_offline_baseline_only')
        for name in blocks:
            changed = deepcopy(blocks)
            changed[name]['both_classes_supported'] = False
            self.assertEqual(audit.support_decision(changed), 'insufficient_support_stop_fold')

    def test_changed_protocol_and_source_version_rejected(self):
        with patch.object(audit, 'make_specification', return_value={'protocol': audit.protocol()}):
            changed = deepcopy(audit.protocol())
            changed['features']['primary_order'].append('review_score')
            with self.assertRaises(ValueError):
                audit.verify_contract({'protocol': changed}, 'unused', 'unused')

    def test_guard_spec_bytes_and_private_source_tamper_rejected(self):
        runtime = audit.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            source = folder / 'private.csv'
            source.write_bytes(b'original')
            descriptor = audit.dataset.descriptor(source)
            audit.dataset.verify_sources([descriptor])
            source.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                audit.dataset.verify_sources([descriptor])
            spec = {'protocol': audit.protocol()}
            specfile, guardfile = folder / 'spec.json', folder / 'guard.json'
            specfile.write_bytes(audit.dataset.json_bytes(spec))
            guardfile.write_bytes(audit.dataset.json_bytes({'specification': {'path': 'wrong'}}))
            with patch.object(audit, 'make_specification', return_value=spec):
                with self.assertRaises(ValueError):
                    audit.verify_contract(spec, specfile, guardfile)

    def test_spec_and_guard_all_preflight_before_any_write(self):
        runtime = audit.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            specfile, guardfile = folder / 'new_spec.json', folder / 'guard.json'
            guardfile.write_bytes(b'conflict')
            minimal = {'sources': [], 'protocol': audit.protocol()}
            with patch.object(audit, 'make_specification', return_value=minimal), patch.object(
                    audit, 'old_provenance', return_value=({}, {}, [], [])):
                with self.assertRaises(ValueError):
                    audit.freeze_specification(specfile, guardfile)
            self.assertFalse(specfile.exists())
            self.assertEqual(guardfile.read_bytes(), b'conflict')

    def test_outputs_outside_root_or_public_guard_rejected(self):
        with self.assertRaises(ValueError):
            audit.dataset.safe_output(audit.ROOT.parent / 'out.json', '../out.json')
        with self.assertRaises(ValueError):
            audit.dataset.safe_output(audit.ROOT / 'reports/guard.json', '', private=True)


if __name__ == '__main__':
    unittest.main()
