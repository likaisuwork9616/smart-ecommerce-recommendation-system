"""Synthetic stored-score gates only; no model fit or metric calculation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import review_month_ablation_pairing as pairing
from scripts import review_month_ablation_pipeline as treatment_pipeline
from scripts import review_baseline_pipeline as control_pipeline
from tests.test_review_baseline_training import SyntheticBundle


def synthetic_control_fixture():
    bundle = SyntheticBundle()
    inner, outer, folds = [], [], []
    for fold in pairing.FOLDS:
        folds.append({'outer_fold': fold, 'selection': {'selected_C': .1},
                      'inner_candidates': [{'C': C} for C in pairing.CANDIDATES]})
        for role, train_role, target in [('inner_validation', 'inner_train_pool', inner),
                                         ('outer_evaluation', 'outer_train_pool', outer)]:
            truth = bundle.role_block(fold, role)
            train = bundle.role_block(fold, train_role)
            prior = float(train.loc[train.role_label_usable, 'y'].sum()) / int(train.role_label_usable.sum())
            plans = [('constant_reference', None)] + ([('logistic_candidate', C) for C in pairing.CANDIDATES]
                     if role == 'inner_validation' else [('logistic_selected', .1)])
            for model, C in plans:
                frame = truth.copy()
                frame['model'] = model
                frame['C'] = pd.Series(C, index=frame.index, dtype='Float64')
                frame['probability_low_1_2'] = prior if C is None else np.linspace(.1, .8, len(frame))
                frame['probability_low_1_2'] = frame.probability_low_1_2.astype('float64')
                target.append(frame.loc[:, pairing.SCORE_COLUMNS])
    inner, outer = pd.concat(inner, ignore_index=True), pd.concat(outer, ignore_index=True)
    report = {'results': {'outer_folds': folds, 'execution': {'score_rows_across_blocks': len(inner) + len(outer)}}}
    return bundle, report, inner, outer


class ReviewMonthAblationPairingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = synthetic_control_fixture()

    def setUp(self):
        self.bundle, self.report, self.inner, self.outer = deepcopy(self.fixture)

    def control(self, inner=None, outer=None, report=None):
        return pairing.validate_frozen_control(self.bundle, self.report if report is None else report,
                                               self.inner if inner is None else inner,
                                               self.outer if outer is None else outer)

    def pair(self, inner=None, outer=None, selected=None):
        return pairing.validate_treatment_pairing(self.bundle, self.report, self.inner, self.outer,
                                                  self.inner if inner is None else inner,
                                                  self.outer if outer is None else outer,
                                                  selected or dict.fromkeys(pairing.FOLDS, .1))

    def test_complete_18_blocks_include_unknown_without_metrics_or_fit(self):
        with (patch.object(pairing.labels, 'evaluate_role', side_effect=AssertionError('No metrics')),
              patch.object(pairing.labels, 'select_candidate', side_effect=AssertionError('No selection')),
              patch.object(control_pipeline.GuardedReviewBaseline, '__init__', side_effect=AssertionError('No model')),
              patch.object(treatment_pipeline.GuardedReviewMonthAblation, '__init__', side_effect=AssertionError('No model'))):
            result = self.control()
            paired = self.pair()
        self.assertEqual(result['score_blocks'], 18)
        self.assertEqual(result['score_rows'], len(self.inner) + len(self.outer))
        self.assertEqual(result['metadata_columns_compared'], 12)
        self.assertEqual(result['metrics_computed'], 0)
        self.assertEqual(result['candidate_selections'], 0)
        self.assertEqual(len(result['folds']), 6)
        self.assertTrue(all(item['unknown_or_ineligible_labels'] == 1 for item in result['folds']))
        self.assertEqual(paired['score_blocks'], 18)

    def test_gate_leaves_input_frames_and_report_unchanged(self):
        inner, outer, report = self.inner.copy(deep=True), self.outer.copy(deep=True), deepcopy(self.report)
        self.control()
        self.pair()
        pd.testing.assert_frame_equal(inner, self.inner)
        pd.testing.assert_frame_equal(outer, self.outer)
        self.assertEqual(report, self.report)

    def test_permuted_extra_or_missing_score_schema_rejected(self):
        for frame in [self.inner.iloc[:, ::-1], self.inner.assign(extra=1), self.inner.drop(columns='C')]:
            with self.subTest(columns=list(frame.columns)), self.assertRaises(ValueError):
                self.control(inner=frame)

    def test_empty_ledger_and_duplicate_row_index_rejected(self):
        changed = self.inner.copy()
        changed.index = [0] * len(changed)
        for frame in [self.inner.iloc[:0], changed]:
            with self.assertRaises(ValueError):
                self.control(inner=frame)

    def test_drop_duplicate_same_count_wrong_ID_rejected(self):
        wrong = self.inner.copy()
        wrong.loc[0, 'order_id'] = 'not-in-full-roster'
        for frame in [self.inner.iloc[1:], pd.concat([self.inner, self.inner.iloc[:1]], ignore_index=True), wrong]:
            with self.assertRaises(ValueError):
                self.control(inner=frame)

    def test_canonical_role_order_cannot_be_repaired_by_sorting(self):
        reversed_first = self.inner.copy()
        reversed_first.iloc[:3] = self.inner.iloc[:3].iloc[::-1].to_numpy()
        with self.assertRaises(ValueError):
            self.control(inner=reversed_first)

    def test_every_truth_metadata_change_rejected(self):
        for name in pairing.dataset.MEMBERSHIP_COLUMNS:
            changed = self.inner.copy()
            changed[name] = changed[name].astype(object)
            changed.loc[0, name] = 'wrong-metadata'
            with self.subTest(column=name), self.assertRaises(ValueError):
                self.control(inner=changed)

    def test_actual_boolean_masks_required_even_when_integer_equal(self):
        for name in ['horizon_complete', 'role_label_usable']:
            changed = self.inner.copy()
            changed[name] = changed[name].astype(object)
            changed.loc[0, name] = 1
            with self.subTest(column=name), self.assertRaises(ValueError):
                self.control(inner=changed)

    def test_unknown_label_cannot_be_imputed_or_filtered(self):
        unknown = self.inner.index[~self.inner.role_label_usable][0]
        changed = self.inner.copy()
        changed.loc[unknown, 'y'] = 0
        for frame in [changed, self.inner.loc[self.inner.role_label_usable]]:
            with self.assertRaises(ValueError):
                self.control(inner=frame)

    def test_unknown_probability_must_be_finite_and_bounded(self):
        unknown = self.inner.index[~self.inner.role_label_usable][0]
        for value in [np.nan, np.inf, -0.01, 1.01]:
            changed = self.inner.copy()
            changed.loc[unknown, 'probability_low_1_2'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.control(inner=changed)

    def test_probability_dtype_is_float64_and_no_coercion(self):
        for dtype in ['float32', 'object']:
            changed = self.inner.copy()
            changed['probability_low_1_2'] = changed.probability_low_1_2.astype(dtype)
            with self.assertRaises(ValueError):
                self.control(inner=changed)

    def test_unexpected_role_model_C_or_extra_block_rejected(self):
        for name, value in [('outer_fold', '2019-01'), ('role', 'outer_train_pool'),
                            ('model', 'surprise'), ('C', .5)]:
            changed = self.inner.copy()
            changed[name] = changed[name].astype(object)
            changed.loc[0, name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.control(inner=changed)
        extra = self.inner.iloc[:3].assign(model='extra_model')
        with self.assertRaises(ValueError):
            self.control(inner=pd.concat([self.inner, extra], ignore_index=True))

    def test_selected_control_C_must_match_pinned_report_not_reselect(self):
        changed = deepcopy(self.report)
        changed['results']['outer_folds'][0]['selection']['selected_C'] = 1.
        with self.assertRaises(ValueError):
            self.control(report=changed)

    def test_invalid_report_fold_and_candidate_rosters_rejected(self):
        for mutation in ['missing_fold', 'reverse_folds', 'duplicate_fold', 'missing_C', 'reverse_C', 'bool_C']:
            changed = deepcopy(self.report)
            folds = changed['results']['outer_folds']
            if mutation == 'missing_fold': folds.pop()
            elif mutation == 'reverse_folds': folds.reverse()
            elif mutation == 'duplicate_fold': folds[1] = deepcopy(folds[0])
            elif mutation == 'missing_C': folds[0]['inner_candidates'].pop()
            elif mutation == 'reverse_C': folds[0]['inner_candidates'].reverse()
            else: folds[0]['inner_candidates'][1]['C'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.control(report=changed)

    def test_invalid_selected_C_and_total_count_rejected(self):
        for value in [True, None, .5, '0.1', np.nan]:
            changed = deepcopy(self.report)
            changed['results']['outer_folds'][0]['selection']['selected_C'] = value
            with self.assertRaises(ValueError):
                self.control(report=changed)
        changed = deepcopy(self.report)
        changed['results']['execution']['score_rows_across_blocks'] += 1
        with self.assertRaises(ValueError):
            self.control(report=changed)

    def test_constant_probability_and_null_C_are_unchanged(self):
        for name, value in [('probability_low_1_2', .2), ('C', .1)]:
            changed = self.inner.copy()
            changed.loc[0, name] = value
            with self.assertRaises(ValueError):
                self.control(inner=changed)

    def test_truth_unknown_y_and_training_single_class_rejected(self):
        block = self.bundle.blocks[('2017-12', 'inner_validation')]
        block.loc[~block.role_label_usable, 'y'] = 0
        with self.assertRaises(ValueError):
            self.control()
        self.bundle, _, _, _ = deepcopy(self.fixture)
        train = self.bundle.blocks[('2017-12', 'inner_train_pool')]
        train.loc[train.role_label_usable, 'y'] = 0
        train.loc[train.role_label_usable, 'label_state'] = 'known_other_3_5'
        with self.assertRaises(ValueError):
            self.control()

    def test_future_treatment_selected_C_may_differ_from_control(self):
        changed = self.outer.copy()
        selections = dict(zip(pairing.FOLDS, [1., 10., .1]))
        for fold, C in selections.items():
            changed.loc[changed.outer_fold.eq(fold) & changed.model.eq('logistic_selected'), 'C'] = C
        selected = changed.model.eq('logistic_selected')
        changed.loc[selected, 'probability_low_1_2'] = .6
        result = self.pair(outer=changed, selected=selections)
        outer_pairs = [item for item in result['paired_blocks'] if item['model'] == 'logistic_selected']
        self.assertEqual([item['treatment_C'] for item in outer_pairs], [1., 10., .1])
        self.assertEqual([item['control_C'] for item in outer_pairs], [.1, .1, .1])
        self.assertFalse(result['treatment_selection_recomputed'])

    def test_future_pair_rejects_missing_unknown_reorder_and_same_count_wrong_ID(self):
        bad_id = self.outer.copy()
        bad_id.loc[0, 'order_id'] = 'different-ID'
        reorder = self.outer.copy()
        reorder.iloc[:3] = self.outer.iloc[:3].iloc[::-1].to_numpy()
        for frame in [self.outer.loc[self.outer.role_label_usable], reorder, bad_id]:
            with self.assertRaises(ValueError):
                self.pair(outer=frame)

    def test_future_pair_requires_complete_selected_fold_map(self):
        for selected in [{'2017-12': .1}, dict.fromkeys(pairing.FOLDS, 100.),
                         dict(dict.fromkeys(pairing.FOLDS, .1), extra=.1)]:
            with self.assertRaises(ValueError):
                self.pair(selected=selected)

    def test_future_pair_rejects_extra_missing_or_mismatched_treatment_C(self):
        for frame in [self.inner.iloc[3:], pd.concat([self.inner, self.inner.iloc[:3]], ignore_index=True)]:
            with self.assertRaises(ValueError):
                self.pair(inner=frame)
        changed = self.outer.copy()
        changed.loc[changed.model.eq('logistic_selected'), 'C'] = 1.
        with self.assertRaises(ValueError):
            self.pair(outer=changed)

    def test_direct_pair_uses_same_C_for_inner_candidate(self):
        truth = self.bundle.role_block('2017-12', 'inner_validation')
        a = self.inner.loc[self.inner.outer_fold.eq('2017-12') & self.inner.model.eq('logistic_candidate')
                           & self.inner.C.eq(.1)]
        b = self.inner.loc[self.inner.outer_fold.eq('2017-12') & self.inner.model.eq('logistic_candidate')
                           & self.inner.C.eq(1.)]
        with self.assertRaises(ValueError):
            pairing.validate_paired_block(a, b, truth, model='logistic_candidate', treatment_C=.1, control_C=1.)

    def test_direct_pair_rejects_wrong_query_model_or_bool_C(self):
        truth = self.bundle.role_block('2017-12', 'inner_validation')
        frame = self.inner.loc[self.inner.outer_fold.eq('2017-12') & self.inner.model.eq('logistic_candidate')
                               & self.inner.C.eq(1.)].copy()
        frame['C'] = frame.C.astype(object)
        frame.loc[:, 'C'] = True
        with self.assertRaises(ValueError):
            pairing.validate_score_block(frame, truth, 'logistic_candidate', 1.)
        with self.assertRaises(ValueError):
            pairing.validate_score_block(frame.assign(model='logistic_selected', C=1.), truth, 'logistic_selected', 1.)

    def test_control_report_metrics_are_never_read_or_recalculated(self):
        changed = deepcopy(self.report)
        for fold in changed['results']['outer_folds']:
            fold['outer_selected'] = {'metrics': 'unread-future-or-corrupt'}
            for item in fold['inner_candidates']:
                item['evaluation'] = {'metrics': 'unread'}
        with patch.object(pairing.labels, 'evaluate_role', side_effect=AssertionError('No metric computation')):
            self.assertEqual(self.control(), self.control(report=changed))

    def test_contract_keeps_null_pair_policy_and_requires_source_bound_caller(self):
        contract = pairing.pairing_contract()
        self.assertEqual(contract['score_columns'], pairing.SCORE_COLUMNS)
        self.assertEqual(contract['paired_metric_null_policy'], 'difference_null_if_either_arm_null_never_fill_zero')
        self.assertEqual(contract['paired_macro_support'], 'both_arms_all_three_months_valid_or_null')
        self.assertFalse(contract['selection_or_metrics_computed_by_this_gate'])
        self.assertIn('verified_immutable_source_bundle', contract['source_version_requirement'])


if __name__ == '__main__':
    unittest.main()
