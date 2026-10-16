"""Four paired comparisons, difference-in-differences and complete-day accounting."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import diagnose_age_colsample as diagnosis
from tests.test_diagnose_age_intersections import fixture
from tests.test_delay_route_exchanges import cohort, selected_scores


def four_fixture():
    frame, scores, known = fixture()
    return frame, {'base08': scores[diagnosis.BASELINE], 'age08': scores[diagnosis.AGE],
        'base10': selected_scores(len(frame), [0, 8, 12, 13]),
        'age10': selected_scores(len(frame), [4, 6, 8, 13])}, known


def synthetic_row(tps):
    return ['overall', 'ALL', [400, 400, 0, 20],
        [[tp, 40-tp, 20-tp, 40, 0, 40, tp/20, tp/40] for tp in tps],
        [[0]*len(diagnosis.EXCHANGES) for _ in range(4)], [[0, 0, 0] for _ in range(4)]]


class AgeColsampleDiagnosisTests(unittest.TestCase):
    def test_frozen_contract_four_contrasts_and_stability(self):
        contract = diagnosis.diagnostic_contract()
        self.assertEqual(contract['seeds'], [11, 29, 42, 73, 101])
        self.assertEqual(len(contract['contrasts']), 4)
        self.assertEqual(contract['contrasts']['base_10_minus_08'], {'old': 'base08', 'new': 'base10'})
        self.assertIn('subsample0.8', ' '.join(contract['prohibitions']))
        self.assertEqual(diagnosis.previous.canonical_sha256(contract),
                         'ddc4ad65f53494edc4741d7b7dee08b19dbe3f03b824f13f0072bdccd40dbf2b')

    def test_difference_in_differences_is_paired_before_summary(self):
        old = [10, 12, 4, 5, 6]
        gap08, base_change, gap10 = [1, -1, 0, 2, -2], [2, -2, 1, 0, 3], [0, 2, -1, 1, -2]
        rows = {seed: synthetic_row([value, value+g08, value+change, value+change+g10])
                for seed, value, g08, change, g10 in zip(diagnosis.SEEDS, old, gap08, base_change, gap10, strict=True)}
        cross = diagnosis.summarize_group(rows)
        decoded = diagnosis.decode_group({'groups': [cross]}, cross_seed=True)
        did = decoded['did']['TP']
        self.assertEqual((did['mean'], did['minimum'], did['maximum'], did['span']), (0., -1., 3., 4.))
        self.assertEqual([did[name] for name in ('negative', 'zero', 'positive')], [3, 1, 1])
        self.assertEqual(decoded['paired']['base_10_minus_08']['TP']['minimum'], -2.)
        self.assertEqual(decoded['paired']['age_10_minus_08']['TP']['maximum'], 3.)

    def test_model_variation_and_gap_span_are_separate(self):
        rows = {seed: synthetic_row(values) for seed, values in zip(diagnosis.SEEDS,
            [[10, 11, 12, 12], [12, 11, 10, 12], [4, 4, 5, 4], [5, 7, 5, 6], [6, 4, 9, 7]], strict=True)}
        cross = {'groups': [diagnosis.summarize_group(rows)]}
        result = diagnosis.february_stability(cross)
        self.assertEqual(result['age_gap_span_change10_minus08']['TP'], 0.)
        self.assertEqual(result['by_version']['age08']['TP']['span'], 7.)
        self.assertEqual(result['by_version']['age10']['TP']['span'], 8.)
        self.assertIn('neither', result['interpretation'])

    def test_positive_mean_does_not_erase_negative_seed_count(self):
        rows = {seed: synthetic_row([5, 5, 5, 5+delta])
                for seed, delta in zip(diagnosis.SEEDS, [5, 5, -2, -1, 1], strict=True)}
        value = diagnosis.decode_group({'groups': [diagnosis.summarize_group(rows)]}, cross_seed=True)
        result = value['paired']['age_minus_base_at_10']['TP']
        self.assertGreater(result['mean'], 0)
        self.assertEqual(result['negative'], 2)
        self.assertEqual(result['span'], 7.)

    def test_undefined_rates_remain_null_in_paired_and_did(self):
        rows = {seed: synthetic_row([0]*4) for seed in diagnosis.SEEDS}
        for row in rows.values():
            row[2][3] = 0
            for version in row[3]:
                version[2] = 0
                version[6:] = [None, None]
        value = diagnosis.decode_group({'groups': [diagnosis.summarize_group(rows)]}, cross_seed=True)
        self.assertIsNone(value['did']['recall']['mean'])
        self.assertEqual(value['did']['recall']['undefined_seed_count'], 5)
        self.assertEqual(value['paired']['age_minus_base_at_10']['precision']['defined_seed_count'], 0)

    def test_nonfinite_summary_rejected(self):
        for value in (np.inf, -np.inf, np.nan):
            with self.subTest(value=value), self.assertRaises(ValueError):
                diagnosis.summary([1, value, None])

    def test_seed_and_denominator_changes_rejected(self):
        rows = {seed: synthetic_row([1, 2, 3, 4]) for seed in diagnosis.SEEDS}
        changed = deepcopy(rows)
        changed[29][2][3] += 1
        with self.assertRaises(ValueError):
            diagnosis.summarize_group(changed)
        with self.assertRaises(ValueError):
            diagnosis.summarize_group({42: rows[42]})

    def test_four_contrasts_use_their_own_old_alerts(self):
        frame, scores, known = four_fixture()
        phase, private = diagnosis.diagnose_phase(frame, scores, known)
        row = diagnosis.decode_group(phase)
        self.assertEqual(row['contrasts']['age_minus_base_at_08']['lost_delays'], 4)
        self.assertEqual(row['contrasts']['age_minus_base_at_10']['lost_delays'], 1)
        self.assertEqual(row['contrasts']['base_10_minus_08']['lost_delays'], 3)
        self.assertEqual(row['contrasts']['age_10_minus_08']['lost_delays'], 0)
        self.assertEqual(len(private['lost']['age_minus_base_at_10']['overall:ALL']), 1)
        self.assertNotEqual(private['lost']['age_minus_base_at_08']['overall:ALL'],
                            private['lost']['base_10_minus_08']['overall:ALL'])

    def test_unknown_high_score_competes_before_group_masks(self):
        frame, scores, known = four_fixture()
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[0, 'delayed'] = 'unknown-do-not-read'
        known[0] = False
        phase, private = diagnosis.diagnose_phase(frame, scores, known)
        row = diagnosis.decode_group(phase)
        self.assertEqual(row['models']['base08']['alerts'], 4)
        self.assertEqual(row['models']['base08']['known_alerts'], 3)
        self.assertEqual(row['models']['base08']['unknown_alerts'], 1)
        self.assertEqual(row['contrasts']['age_minus_base_at_08']['unknown_removed_alerts'], 1)
        self.assertNotIn(frame.order_id.iloc[0], private['lost']['age_minus_base_at_08']['overall:ALL'])

    def test_actual_routes_empty_focus_cells_and_five_110_bins_retained(self):
        frame, scores, known = four_fixture()
        frame['state_route'] = 'SP->SP'
        phase, private = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual([row[1] for row in phase['groups'] if row[0] == 'route'], ['SP->SC', 'SP->SP'])
        self.assertEqual(len([row for row in phase['groups'] if row[0] == 'cell']), 8)
        self.assertEqual([row[1] for row in phase['groups'] if row[0] == 'cell110_age'], list(diagnosis.AGE_BINS))
        self.assertEqual(diagnosis.decode_group(phase, 'route', 'SP->SC')['denominators']['full_batch_rows'], 0)
        self.assertIsNone(diagnosis.decode_group(phase, 'cell', '111')['models']['base10']['recall'])
        self.assertEqual(len(private['delayed']), 22)

    def test_exact_age_and_promise_boundaries_keep_original_groups(self):
        frame = cohort(10)
        frame['state_route'], frame['delayed'] = 'SP->RJ', 0
        frame['estimated_delivery_days'] = [21, 21.1, 30, 30.1, 25, 25, 25, 25, 25, 25]
        frame[diagnosis.intersections.FEATURE] = [24, 24.1, 72, 72.1, np.nan, 0, 168, 48, 169, 120]
        masks = {(kind, key): mask for kind, key, mask in diagnosis.group_masks(frame)}
        self.assertEqual(np.flatnonzero(masks['cell', '111']).tolist(), [1, 2, 7])
        self.assertFalse(masks['marginal', 'P'][0])
        self.assertTrue(masks['marginal', 'P'][1])
        self.assertEqual(int(masks['cell110_age', 'over24_to72h'].sum()), 0)
        self.assertEqual(int(masks['cell110_age', 'missing_or_empty'].sum()), 1)

    def test_daily_gross_survives_zero_monthly_route_change(self):
        frame = cohort(40)
        frame['prediction_time'] = pd.Timestamp('2017-07-01') + pd.to_timedelta(np.arange(40)//20, unit='D')
        frame['state_route'], frame['estimated_delivery_days'], frame[diagnosis.intersections.FEATURE], frame['delayed'] = 'SP->SP', 15., np.nan, 0
        frame.loc[[0, 20], 'state_route'] = 'SP->RJ'
        old, new = selected_scores(40, [0, 2, 21, 22]), selected_scores(40, [1, 2, 20, 22])
        phase, _ = diagnosis.diagnose_phase(frame, {'base08': old, 'age08': new, 'base10': old, 'age10': new}, np.ones(40, bool))
        row = diagnosis.decode_group(phase, 'route', 'SP->RJ')
        self.assertEqual(row['models']['base08']['alerts'], row['models']['age08']['alerts'])
        self.assertEqual(row['allocations']['age_minus_base_at_08'],
            {'within_group_exchanges': 0, 'cross_group_outgoing_slots': 1, 'cross_group_incoming_slots': 1})
        self.assertEqual(phase['daily_gross_totals'][0], [2, 2, 2, 0, 2, 0, 2])

    def test_public_output_omits_private_identities_and_rank_details(self):
        frame, scores, known = four_fixture()
        phase, _ = diagnosis.diagnose_phase(frame, scores, known)
        serialized = json.dumps(phase, allow_nan=False)
        self.assertNotIn(frame.order_id.iloc[0], serialized)
        self.assertNotIn('rank_capacity', serialized)
        self.assertNotIn('prediction_time', serialized)

    def test_incomplete_versions_duplicate_id_and_bad_scores_rejected(self):
        frame, scores, known = four_fixture()
        with self.assertRaises(ValueError):
            diagnosis.diagnose_phase(frame, {'base08': scores['base08']}, known)
        changed = frame.copy()
        changed.loc[1, 'order_id'] = changed.loc[0, 'order_id']
        with self.assertRaises(ValueError):
            diagnosis.diagnose_phase(changed, scores, known)
        for value in (np.nan, np.inf, 1.01, -.01):
            changed_scores = deepcopy(scores)
            changed_scores['age10'][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                diagnosis.diagnose_phase(frame, changed_scores, known)

    def test_frozen_reference_reproduces_all_counts_and_daily_flows(self):
        frame, scores, known = four_fixture()
        phase, _ = diagnosis.diagnose_phase(frame, scores, known)
        frozen = diagnosis.previous.diagnose_phase(frame,
            {diagnosis.BASELINE: scores['base08'], diagnosis.AGE: scores['age08']}, known)
        self.assertGreater(diagnosis.verify_frozen_phase(phase, frozen), 31)
        changed = deepcopy(frozen)
        changed['rpa_cells'][0]['lost_delays'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_frozen_phase(phase, changed)
        changed = deepcopy(frozen)
        changed['overall']['cross_route_slots'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_frozen_phase(phase, changed)

    def test_cross_seed_route_support_mismatch_rejected(self):
        frame, scores, known = four_fixture()
        phase, _ = diagnosis.diagnose_phase(frame, scores, known)
        phases = {seed: deepcopy(phase) for seed in diagnosis.SEEDS}
        phases[29]['groups'].pop(1)
        with self.assertRaises(ValueError):
            diagnosis.summarize_phases(phases)

    def test_compact_schema_and_readable_adapter(self):
        frame, scores, known = four_fixture()
        phase, _ = diagnosis.diagnose_phase(frame, scores, known)
        direct = diagnosis.decode_group(phase)
        cross = diagnosis.summarize_phases({seed: phase for seed in diagnosis.SEEDS})
        decoded = diagnosis.decode_group(cross, cross_seed=True)
        self.assertEqual(diagnosis.schema()['versions'], list(diagnosis.VERSIONS))
        self.assertEqual(decoded['models']['age10']['TP']['mean'], direct['models']['age10']['TP'])
        self.assertEqual(decoded['paired']['age_minus_base_at_10']['TP']['mean'],
                         direct['models']['age10']['TP'] - direct['models']['base10']['TP'])
        self.assertEqual(decoded['paired']['age_minus_base_at_10']['TP']['positive'], 5)

    def test_development_pool_sums_counts_and_recomputes_rates(self):
        frame, scores, known = four_fixture()
        phase, _ = diagnosis.diagnose_phase(frame, scores, known)
        keys = [f'{month}/{month}/evaluation' for month in ['2017-12', '2018-02', '2018-04']]
        source = {seed: {key: phase for key in keys} for seed in diagnosis.SEEDS}
        pooled = diagnosis.pool_development(source, keys)
        row = diagnosis.decode_group({'groups': [pooled['seed_groups']['42']]})
        self.assertEqual(row['denominators']['full_batch_rows'], 120)
        self.assertEqual(row['models']['age10']['TP'], 12)
        self.assertAlmostEqual(row['models']['age10']['recall'], 12/18)
        for invalid in (keys[:2], [keys[0]]*3, [*keys[:2], '2018-04/2017-12/validation']):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                diagnosis.pool_development(source, invalid)

    def test_main_contrasts_and_undefined_mutations_rejected(self):
        row = synthetic_row([2, 3, 4, 6])
        values = diagnosis.comparison_values(row)
        self.assertEqual(values['difference_in_differences']['true_positives'], 1)
        self.assertEqual(diagnosis.verify_comparisons(row, values), 30)
        changed = deepcopy(values)
        changed['base_10_minus_08']['true_positives'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_comparisons(row, changed)
        values.pop('difference_in_differences')
        with self.assertRaises(ValueError):
            diagnosis.verify_comparisons(row, values)

    def test_overlap_uses_own_contrast_sets_and_exports_only_aggregates(self):
        frame, scores, known = four_fixture()
        _, private = diagnosis.diagnose_phase(frame, scores, known)
        source = {diagnosis.TARGET_PHASE: {seed: deepcopy(private) for seed in diagnosis.SEEDS}}
        phases, focus, cross = diagnosis.identity_overlaps(source, {diagnosis.TARGET_PHASE: {}})
        old = phases[diagnosis.TARGET_PHASE]['age_minus_base_at_08']
        new = phases[diagnosis.TARGET_PHASE]['age_minus_base_at_10']
        self.assertEqual((old['union'], old['all_seed_intersection']), (4, 4))
        self.assertEqual((new['union'], new['all_seed_intersection']), (1, 1))
        self.assertEqual(len(focus['base_10_minus_08']), 22)
        self.assertEqual(len(old['pairwise']), 10)
        age_reference = phases[diagnosis.TARGET_PHASE]['age_10_minus_08']['definition']
        self.assertIn('own age08', age_reference)
        self.assertIn('own age10', age_reference)
        self.assertNotIn('reference101', age_reference)
        self.assertIn('own age08', focus['age_10_minus_08']['overall:ALL']['definition'])
        self.assertNotIn(frame.order_id.iloc[0], json.dumps([phases, focus, cross]))
        self.assertEqual(cross['42']['overall:ALL']['intersection'], 1)

    def test_empty_overlap_keeps_pairwise_jaccard_null(self):
        frame, scores, known = four_fixture()
        frame['delayed'] = 0
        _, private = diagnosis.diagnose_phase(frame, scores, known)
        _, focus, cross = diagnosis.identity_overlaps({diagnosis.TARGET_PHASE: {seed: private for seed in diagnosis.SEEDS}}, {diagnosis.TARGET_PHASE: {}})
        value = focus['base_10_minus_08']['route:SP->SC']
        self.assertIsNone(value['pairwise_jaccard']['mean'])
        self.assertEqual(value['pairwise_jaccard']['undefined_pair_count'], 10)
        self.assertIsNone(cross['42']['overall:ALL']['jaccard'])

    def test_missing_or_changed_delayed_identities_rejected(self):
        frame, scores, known = four_fixture()
        _, private = diagnosis.diagnose_phase(frame, scores, known)
        source = {diagnosis.TARGET_PHASE: {seed: deepcopy(private) for seed in diagnosis.SEEDS}}
        source[diagnosis.TARGET_PHASE][29]['delayed']['overall:ALL'] = set()
        with self.assertRaises(ValueError):
            diagnosis.identity_overlaps(source, {diagnosis.TARGET_PHASE: {}})

    def test_diagnosis_does_not_deserialize_models(self):
        frame, scores, known = four_fixture()
        with patch('joblib.load', side_effect=AssertionError('No model loads')):
            phase, _ = diagnosis.diagnose_phase(frame, scores, known)
            self.assertEqual(diagnosis.decode_group(phase)['models']['base10']['alerts'], 4)

    def test_unfinished_source_rejected_before_reading_dependencies(self):
        with patch('pathlib.Path.read_text', return_value=json.dumps({'status': 'running'})):
            with self.assertRaises(ValueError):
                diagnosis.build_report('unfinished.json')


if __name__ == '__main__':
    unittest.main()
