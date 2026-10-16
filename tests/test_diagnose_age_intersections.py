"""Fixed overlap cells, complete-day ranks and daily gross alert accounting."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import diagnose_age_intersections as diagnosis
from tests.test_delay_route_exchanges import cohort, selected_scores
from tests.test_diagnose_unobserved_handover_age import fixture as preceding_fixture, ledger_data


def fixture():
    frame = cohort(40)
    bits = np.arange(40) % 8
    frame['state_route'] = np.where(bits >= 4, 'SP->RJ', 'SP->SP')
    frame['estimated_delivery_days'] = np.where((bits & 2) > 0, 25., 15.)
    frame[diagnosis.FEATURE] = np.where((bits & 1) > 0, 48., 120.)
    frame.loc[0, diagnosis.FEATURE] = np.nan
    frame['delayed'] = 0
    frame.loc[[0, 4, 6, 7, 8, 13], 'delayed'] = 1
    scores = {diagnosis.BASELINE: selected_scores(40, [0, 4, 6, 7]),
              diagnosis.NEW: selected_scores(40, [8, 9, 10, 11])}
    return frame, scores, np.ones(40, bool)


class AgeIntersectionTests(unittest.TestCase):
    def test_exact_promise_age_boundaries_and_three_bit_order(self):
        frame = cohort(8)
        frame['state_route'] = 'SP->RJ'
        frame['estimated_delivery_days'] = [21., 21.1, 30., 30.1, 25., 25., 25., 25.]
        frame[diagnosis.FEATURE] = [24., 24.1, 72., 72.1, np.nan, 0., 168., 48.]
        cells, groups = diagnosis.group_masks(frame)
        self.assertEqual(cells.tolist(), ['100', '111', '111', '100', '110', '110', '110', '111'])
        np.testing.assert_array_equal(groups['RPA'], groups['R'] & groups['P'] & groups['A'])

    def test_invalid_age_promise_and_route_rejected(self):
        frame, _, _ = fixture()
        for name, value in [(diagnosis.FEATURE, -1.), (diagnosis.FEATURE, np.inf),
                             ('estimated_delivery_days', np.nan), ('state_route', '')]:
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                diagnosis.group_masks(frame.assign(**{name: value}))

    def test_eight_cells_and_finer_age_partitions_include_empty_groups(self):
        frame, scores, known = fixture()
        result = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual([row['cell'] for row in result['cells']], list(diagnosis.CELLS))
        self.assertEqual([row['full_batch_rows'] for row in result['cells']], [5]*8)
        for cell in result['cells']:
            self.assertEqual([row['age_bin'] for row in cell['finer_age_bins']], list(diagnosis.previous.AGE_BINS))
            for field in diagnosis.COUNT_FIELDS:
                self.assertEqual(sum(row[field] for row in cell['finer_age_bins']), cell[field])
        self.assertEqual(sum(row['full_batch_rows'] for row in result['cells']), 40)

    def test_lost_intersections_are_not_the_sum_of_three_marginals(self):
        frame, scores, known = fixture()
        result = diagnosis.diagnose_phase(frame, scores, known)
        groups = result['marginals']
        self.assertEqual([groups[name]['lost_delays'] for name in ['R', 'P', 'A', 'RP', 'RA', 'PA', 'RPA']],
                         [3, 2, 1, 2, 1, 1, 1])
        self.assertEqual(result['lost_overlap']['lost_delays_union_R_P_A'], 3)
        self.assertEqual(result['lost_overlap']['lost_delays_sum_R_P_A'], 6)
        self.assertEqual(groups['ALL']['both_missed_delays'], 1)
        self.assertEqual(groups['ALL']['lost_delays'], 4)
        self.assertEqual(groups['ALL']['new_false_negatives'], 5)

    def test_unknown_high_score_keeps_slot_without_reading_its_label(self):
        frame, scores, known = fixture()
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[0, 'delayed'] = 'unknown-do-not-read'
        known[0] = False
        result = diagnosis.diagnose_phase(frame, scores, known)
        all_rows = result['marginals']['ALL']
        self.assertEqual((all_rows['old_alerts'], all_rows['old_known_alerts'], all_rows['old_unknown_alerts']), (4, 3, 1))
        self.assertEqual(all_rows['old_false_positives'], 0)
        self.assertEqual(all_rows['lost_delays'], 3)

    def test_no_delay_and_empty_cells_keep_none_rates_and_small_sample_flags(self):
        frame, scores, known = fixture()
        frame['state_route'], frame['estimated_delivery_days'], frame[diagnosis.FEATURE], frame['delayed'] = 'SP->SP', 15., np.nan, 0
        result = diagnosis.diagnose_phase(frame, scores, known)
        self.assertIsNone(result['marginals']['ALL']['old_recall'])
        self.assertIsNone(result['marginals']['ALL']['both_missed_fraction_of_delays'])
        empty = next(row for row in result['cells'] if row['cell'] == '111')
        self.assertEqual(empty['full_batch_rows'], 0)
        self.assertIsNone(empty['known_delay_rate'])
        self.assertTrue(empty['small_sample'])
        self.assertEqual(empty['rank_capacity']['lost_delays']['rows'], 0)

    def test_daily_gross_flows_do_not_collapse_to_monthly_net(self):
        frame = cohort(40)
        frame['prediction_time'] = pd.Timestamp('2017-07-01') + pd.to_timedelta(np.arange(40)//20, unit='D')
        frame['state_route'], frame['estimated_delivery_days'], frame[diagnosis.FEATURE], frame['delayed'] = 'SP->SP', 15., np.nan, 0
        frame.loc[[0, 20], 'state_route'] = 'SP->RJ'
        scores = {diagnosis.BASELINE: selected_scores(40, [0, 2, 21, 22]),
                  diagnosis.NEW: selected_scores(40, [1, 2, 20, 22])}
        result = diagnosis.diagnose_phase(frame, scores, np.ones(40, bool))
        self.assertEqual(len(result['allocations']['day_cells']), 2*8)
        self.assertEqual(result['allocations']['summary']['cross_cell_slots'], 2)
        cell = next(row for row in result['allocations']['cell_totals'] if row['cell'] == '100')
        self.assertEqual((cell['net_alerts'], cell['cross_cell_incoming_slots'], cell['cross_cell_outgoing_slots']), (0, 1, 1))

    def test_rank_and_capacity_gap_counts_match_existing_alerts(self):
        frame, scores, known = fixture()
        result = diagnosis.diagnose_phase(frame, scores, known)
        all_rows = result['marginals']['ALL']
        ranks = all_rows['rank_capacity']['known_delayed']
        self.assertEqual(ranks['old_relative_bins']['<=10%'], all_rows['old_true_positives'])
        self.assertEqual(ranks['new_relative_bins']['<=10%'], all_rows['new_true_positives'])
        lost = all_rows['rank_capacity']['lost_delays']
        self.assertEqual(lost['old_capacity_gap']['bins']['inside_budget'], all_rows['lost_delays'])
        self.assertEqual(lost['new_capacity_gap']['bins']['inside_budget'], 0)
        self.assertEqual(sum(lost['new_capacity_gap']['bins'].values()), all_rows['lost_delays'])
        self.assertGreater(lost['new_capacity_gap']['minimum'], 0)

    def test_focus_loss_days_account_for_whole_day_changes_and_known_unknown_outcomes(self):
        frame, scores, known = fixture()
        result = diagnosis.diagnose_phase(frame, scores, known)
        focus = result['focus_lost_days']
        self.assertEqual(focus['union_day_count'], 1)
        self.assertEqual(focus['by_cell_lost_days']['111']['lost_delays'], 1)
        day = focus['union_days'][0]
        for dimension, expected_count in [('cells', 8), ('routes', 2), ('promise_days', 5), ('age_bins', 5)]:
            rows = day['whole_day_changes'][dimension]
            self.assertEqual(len(rows), expected_count)
            self.assertEqual(sum(row['added'] for row in rows), 4)
            self.assertEqual(sum(row['dropped'] for row in rows), 4)
            for row in rows:
                self.assertEqual(list(row['outcomes']), list(diagnosis.OUTCOMES))
        # The full-day table retains the dropped delay outside R/P/A too.
        self.assertEqual(day['whole_day_counts']['lost_delays'], 4)
        self.assertEqual(sum(result['lost_overlap'][key] for key in ['lost_delays_union_R_P_A']), 3)

    def test_historical_cutoff_is_strict_and_unknown_answers_keep_rank_slots(self):
        frame, scores, known = preceding_fixture()
        ledger, expected = ledger_data(frame, scores, known)
        actual, aligned, _ = diagnosis.previous.verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', expected, '2017-07')
        self.assertFalse(actual[0])  # label_available_time equals cutoff
        result = diagnosis.diagnose_phase(frame, aligned, actual)
        self.assertEqual(result['marginals']['ALL']['old_unknown_alerts'], 1)

    def test_prior_marginals_are_recomputed_and_mutation_is_rejected(self):
        frame, scores, known = preceding_fixture()
        before = diagnosis.previous.diagnose_phase(frame, scores, known)
        actual = diagnosis.verify_preceding_marginals(frame, scores, known, before)
        self.assertEqual(actual['routes'], before['pending_age_features']['routes'])
        changed = deepcopy(before)
        changed['pending_age_features']['pending_age_bins'][0]['lost_delays'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_preceding_marginals(frame, scores, known, changed)

    def test_frozen_source_hash_guard_rejects_mutation(self):
        directory = diagnosis.ROOT / '.runtime/tmp'
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            path = Path(temporary) / 'source.json'
            path.write_text('{"fixed":10}', encoding='utf-8')
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(diagnosis.bound_json(path, expected), {'fixed': 10})
            path.write_text('{"fixed":11}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Frozen source SHA'):
                diagnosis.bound_json(path, expected)

    def test_no_model_deserialization_or_private_order_output(self):
        frame, scores, known = fixture()
        with patch('joblib.load', side_effect=AssertionError('Model loading is forbidden')):
            result = diagnosis.diagnose_phase(frame, scores, known)
        text = json.dumps(result, allow_nan=False)
        self.assertNotIn('private-order-', text)
        self.assertNotIn('order_id', result)


if __name__ == '__main__':
    unittest.main()
