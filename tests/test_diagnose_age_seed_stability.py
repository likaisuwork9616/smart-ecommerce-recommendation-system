"""Paired seed summaries, complete-day accounting and private overlap sets."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import diagnose_age_seed_stability as diagnosis
from tests.test_diagnose_age_intersections import fixture
from tests.test_diagnose_unobserved_handover_age import fixture as ledger_fixture, ledger_data
from tests.test_delay_route_exchanges import cohort, selected_scores


def summary_row(old_tp, new_tp):
    row = {'full_batch_rows': 400, 'known_rows': 400, 'unknown_rows': 0, 'positive_rows': 20,
           'recovered_delays': max(new_tp - old_tp, 0), 'lost_delays': max(old_tp - new_tp, 0),
           'added_alerts': abs(new_tp - old_tp), 'dropped_alerts': abs(new_tp - old_tp)}
    for side, tp in [('old', old_tp), ('new', new_tp)]:
        row.update({f'{side}_true_positives': tp, f'{side}_false_positives': 40 - tp,
                    f'{side}_false_negatives': 20 - tp, f'{side}_alerts': 40,
                    f'{side}_recall': tp / 20, f'{side}_precision': tp / 40})
    return row


class AgeSeedDiagnosisTests(unittest.TestCase):
    def test_pre_fit_contract_exact_seeds_groups_and_hash(self):
        contract = diagnosis.diagnostic_contract()
        self.assertEqual(contract['seeds'], [11, 29, 42, 73, 101])
        self.assertEqual(contract['cells'], [f'{n:03b}' for n in range(8)])
        self.assertEqual(contract['groups']['P'], '21 < estimated_delivery_days <= 30')
        self.assertEqual(diagnosis.canonical_sha256(contract),
                         '43644959e7ad4ba23b7d76bf1d9934e6a41db33d1f64ddd84bb65a55d7699294')

    def test_paired_delta_extrema_are_not_subtracted_marginal_extrema(self):
        old = [10, 12, 4, 5, 6]
        changes = [1, -1, 0, 2, -2]
        rows = {seed: summary_row(value, value + change)
                for seed, value, change in zip(diagnosis.SEEDS, old, changes, strict=True)}
        result = diagnosis.summarize_group(rows)
        tp = result['paired_delta']['TP']
        self.assertEqual((tp['mean'], tp['minimum'], tp['maximum']), (0., -2., 2.))
        self.assertEqual(tp['directions'], {'negative': 2, 'zero': 1, 'positive': 2, 'undefined': 0})
        self.assertEqual(result['denominators']['positive_rows'], 20)
        self.assertEqual(list(tp['by_seed']), ['11', '29', '42', '73', '101'])
        self.assertEqual(result['paired_delta']['alerts']['directions']['zero'], 5)

    def test_group_denominator_or_seed_omissions_rejected(self):
        rows = {seed: summary_row(4, 5) for seed in diagnosis.SEEDS}
        changed = deepcopy(rows)
        changed[29]['positive_rows'] += 1
        with self.assertRaises(ValueError):
            diagnosis.summarize_group(changed)
        with self.assertRaises(ValueError):
            diagnosis.summarize_group({42: rows[42]})

    def test_undefined_precision_and_empty_recall_are_not_zero(self):
        rows = {seed: summary_row(0, 0) for seed in diagnosis.SEEDS}
        for row in rows.values():
            row['positive_rows'] = 0
            row['old_recall'] = row['new_recall'] = None
            row['old_precision'] = None
        result = diagnosis.summarize_group(rows)
        recall = result['paired_delta']['recall']
        self.assertIsNone(recall['mean'])
        self.assertEqual(recall['directions']['undefined'], 5)
        precision = result['paired_delta']['precision']
        self.assertIsNone(precision['minimum'])
        self.assertEqual(precision['defined_seed_count'], 0)

    def test_nonfinite_summary_values_rejected(self):
        for value in [np.inf, -np.inf, np.nan]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                diagnosis.numeric_summary([0., value, None])

    def test_identity_overlap_tracks_multiplicity_and_all_ten_seed_pairs(self):
        a, b, c, d = 'private-alpha', 'private-beta', 'private-gamma', 'private-delta'
        sets = {11: {a, b}, 29: {b, c}, 42: {b}, 73: set(), 101: {b, d}}
        result = diagnosis.overlap_summary(sets, {a, b, c, d, 'never-lost'})
        self.assertEqual(result['union'], 4)
        self.assertEqual(result['all_seed_intersection'], 0)
        self.assertEqual(result['multiplicity'], {'1': 3, '2': 0, '3': 0, '4': 1, '5': 0})
        self.assertEqual(result['never_newly_lost_by_any_seed'], 1)
        self.assertEqual(len(result['pairwise']), 10)
        pair = next(row for row in result['pairwise'] if row['left_seed'] == 11 and row['right_seed'] == 29)
        self.assertAlmostEqual(pair['jaccard'], 1 / 3)
        self.assertEqual((pair['intersection'], pair['union']), (1, 3))
        self.assertNotIn('private-', json.dumps(result))

    def test_equal_lost_counts_do_not_imply_same_lost_identities(self):
        shared = {seed: {'same'} for seed in diagnosis.SEEDS}
        distinct = {seed: {str(seed)} for seed in diagnosis.SEEDS}
        one = diagnosis.overlap_summary(shared, {'same'})
        two = diagnosis.overlap_summary(distinct, set(map(str, diagnosis.SEEDS)))
        self.assertEqual(list(one['by_seed'].values()), list(two['by_seed'].values()))
        self.assertEqual((one['union'], one['all_seed_intersection']), (1, 1))
        self.assertEqual((two['union'], two['all_seed_intersection']), (5, 0))

    def test_empty_pairwise_union_keeps_jaccard_undefined(self):
        result = diagnosis.overlap_summary({seed: set() for seed in diagnosis.SEEDS}, {'delay'})
        self.assertEqual(result['union'], 0)
        self.assertTrue(all(row['jaccard'] is None for row in result['pairwise']))
        self.assertEqual(result['pairwise_jaccard']['undefined_pair_count'], 10)
        self.assertIsNone(result['pairwise_jaccard']['mean'])

    def test_overlap_unknown_identity_and_missing_seed_rejected(self):
        sets = {seed: set() for seed in diagnosis.SEEDS}
        sets[42] = {'not-known-delayed'}
        with self.assertRaises(ValueError):
            diagnosis.overlap_summary(sets, set())
        with self.assertRaises(ValueError):
            diagnosis.overlap_summary({42: set()}, set())

    def test_complete_day_slots_precede_known_masks_and_rpa_slices(self):
        frame, scores, known = fixture()
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[0, 'delayed'] = 'unknown-not-readable'
        known[0] = False
        result = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual((result['overall']['old_alerts'], result['overall']['old_unknown_alerts']), (4, 1))
        self.assertEqual((result['overall']['lost_delays'], result['overall']['recovered_delays']), (3, 1))
        self.assertEqual(len(result['rpa_cells']), 8)
        self.assertEqual(sum(row['old_alerts'] for row in result['rpa_cells']), 4)
        self.assertNotIn('private-order-', json.dumps(result, allow_nan=False))

    def test_phase_publishes_actual_routes_empty_cells_and_five_110_age_bins(self):
        frame, scores, known = fixture()
        frame['state_route'] = 'SP->SP'
        result = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual([row['state_route'] for row in result['routes']], ['SP->SP'])
        empty = next(row for row in result['rpa_cells'] if row['cell'] == '111')
        self.assertEqual(empty['full_batch_rows'], 0)
        self.assertIsNone(empty['new_recall'])
        self.assertEqual(empty['lost_rank_capacity']['rows'], 0)
        self.assertEqual([row['age_bin'] for row in result['cell110_age_bins']], list(diagnosis.AGE_BINS))
        self.assertTrue(all(row['full_batch_rows'] == 0 for row in result['cell110_age_bins']))

    def test_daily_gross_cross_route_and_cell_flows_survive_zero_monthly_net(self):
        frame = cohort(40)
        frame['prediction_time'] = pd.Timestamp('2017-07-01') + pd.to_timedelta(np.arange(40) // 20, unit='D')
        frame['state_route'], frame['estimated_delivery_days'], frame[diagnosis.FEATURE], frame['delayed'] = 'SP->SP', 15., np.nan, 0
        frame.loc[[0, 20], 'state_route'] = 'SP->RJ'
        scores = {diagnosis.BASELINE: selected_scores(40, [0, 2, 21, 22]),
                  diagnosis.AGE: selected_scores(40, [1, 2, 20, 22])}
        result = diagnosis.diagnose_phase(frame, scores, np.ones(40, bool))
        self.assertEqual(len(result['days']), 2)
        self.assertEqual(result['overall']['cross_route_slots'], 2)
        self.assertEqual(result['overall']['cross_cell_slots'], 2)
        route = next(row for row in result['routes'] if row['state_route'] == 'SP->RJ')
        self.assertEqual((route['net_alerts'], route['cross_route_incoming_slots'], route['cross_route_outgoing_slots']), (0, 1, 1))

    def test_cross_seed_route_support_mismatch_rejected(self):
        frame, scores, known = fixture()
        result = diagnosis.diagnose_phase(frame, scores, known)
        phases = {seed: deepcopy(result) for seed in diagnosis.SEEDS}
        phases[29]['routes'].pop()
        with self.assertRaises(ValueError):
            diagnosis.summarize_phases(phases)

    def test_development_pool_only_three_disjoint_evaluation_phase_keys(self):
        frame, scores, known = fixture()
        result = diagnosis.diagnose_phase(frame, scores, known)
        keys = [f'{month}/{month}/evaluation' for month in ['2017-12', '2018-02', '2018-04']]
        phases = {seed: {key: deepcopy(result) for key in keys} for seed in diagnosis.SEEDS}
        pool = diagnosis.development_pool(phases, keys)
        self.assertEqual(pool['cross_seed']['overall']['denominators']['full_batch_rows'], 120)
        self.assertEqual(pool['cross_seed']['overall']['paired_delta']['TP']['directions']['negative'], 5)
        for invalid in [keys[:2], [keys[0]] * 3, [*keys[:2], '2018-04/2017-12/validation']]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                diagnosis.development_pool(phases, invalid)

    def test_seed42_prior_intersections_count_and_lost_rank_mutations_rejected(self):
        frame, scores, known = fixture()
        before = diagnosis.intersections.diagnose_phase(frame, scores, known, include_focus_days=False)
        actual = diagnosis.diagnose_phase(frame, scores, known)
        self.assertGreater(diagnosis.verify_seed42_reference(actual, before), 0)
        changed = deepcopy(before)
        changed['cells'][0]['lost_delays'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_seed42_reference(actual, changed)
        changed = deepcopy(before)
        changed['marginals']['ALL']['rank_capacity']['lost_delays']['new_capacity_gap']['median'] = 999.
        with self.assertRaises(ValueError):
            diagnosis.verify_seed42_reference(actual, changed)

    def ledger(self, *, evaluation=False):
        frame, scores, known = ledger_fixture()
        role = 'evaluation' if evaluation else 'validation'
        if evaluation:
            known = np.ones(len(frame), bool)
        ledger, model_records = ledger_data(frame, scores, known, role=role)
        ledger['seed'], ledger['fold'] = 42, '2017-12'
        expected = {candidate: (record['validation_by_month']['2017-07'] if not evaluation else
                               {'known_outcome_metrics': record['development_evaluation'], 'full_batch': record['evaluation_batch']})
                    for candidate, record in model_records.items()}
        metadata = {'fold': '2017-12', 'month': '2017-07', 'ledger_role': role,
                    'historical_outcome_cutoff': None if evaluation else '2017-12-01'}
        return frame, ledger, metadata, expected, known

    def test_historical_clock_equality_remains_unknown_and_competes(self):
        frame, ledger, metadata, expected, known = self.ledger()
        actual, scores, _ = diagnosis.verify_phase_ledger(frame, ledger, metadata, 42, expected)
        np.testing.assert_array_equal(actual, known)
        self.assertFalse(actual[0])
        self.assertEqual(diagnosis.diagnose_phase(frame, scores, actual)['overall']['old_unknown_alerts'], 1)

    def test_seed_candidate_duplicate_and_availability_mutations_rejected(self):
        frame, ledger, metadata, expected, _ = self.ledger()
        changed = ledger.copy()
        changed.loc[0, 'seed'] = 11
        with self.assertRaises(ValueError):
            diagnosis.verify_phase_ledger(frame, changed, metadata, 42, expected)
        changed = ledger.copy()
        changed.loc[1, 'order_id'] = changed.loc[0, 'order_id']
        with self.assertRaises(ValueError):
            diagnosis.verify_phase_ledger(frame, changed, metadata, 42, expected)
        changed = ledger.copy()
        changed.loc[0, 'known_at_selection'] = True
        with self.assertRaises(AssertionError):
            diagnosis.verify_phase_ledger(frame, changed, metadata, 42, expected)

    def test_evaluation_flags_and_report_budget_mutations_rejected(self):
        frame, ledger, metadata, expected, _ = self.ledger(evaluation=True)
        diagnosis.verify_phase_ledger(frame, ledger, metadata, 42, expected)
        changed = ledger.copy()
        changed.loc[0, 'known_at_selection'] = True
        with self.assertRaises(AssertionError):
            diagnosis.verify_phase_ledger(frame, changed, metadata, 42, expected)
        changed_expected = deepcopy(expected)
        changed_expected[diagnosis.AGE]['full_batch']['capacity'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_phase_ledger(frame, ledger, metadata, 42, changed_expected)

    def test_diagnosis_never_deserializes_models(self):
        frame, scores, known = fixture()
        with patch('joblib.load', side_effect=AssertionError('No model loading allowed')):
            result = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual(result['overall']['full_batch_rows'], 40)

    def test_source_that_omits_prespecified_seeds_is_rejected_before_file_access(self):
        source = {'status': 'ok', 'seeds': [42], 'matched_candidate_order': list(diagnosis.CANDIDATES),
                  'diagnostic_contract': diagnosis.diagnostic_contract(),
                  'diagnostic_contract_sha256': diagnosis.canonical_sha256(diagnosis.diagnostic_contract())}
        with patch('pathlib.Path.read_text', return_value=json.dumps(source)), self.assertRaises(ValueError):
            diagnosis.build_report('not-read.json', 'not-read')

    def test_immutable_report_recheck_preserves_bytes_and_rejects_changed_result(self):
        payload = {'analysis': diagnosis.ANALYSIS, 'paired_delta': -3}
        with patch('pathlib.Path.exists', return_value=True), \
                patch('pathlib.Path.read_text', return_value=json.dumps(payload)), \
                patch('pathlib.Path.write_text') as writer:
            self.assertFalse(diagnosis.fixed_json('frozen.json', payload))
            writer.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
                diagnosis.fixed_json('frozen.json', {**payload, 'paired_delta': 3})
            writer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
