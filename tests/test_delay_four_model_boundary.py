"""Synthetic evidence for frozen four-model ranking and daily exchanges."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import delay_four_model_boundary as diagnosis


FEATURE = diagnosis.colsample.intersections.FEATURE


def fixture(rows=40):
    frame = pd.DataFrame({
        'order_id': [f'private-boundary-order-{index:04d}' for index in range(rows)],
        'prediction_time': pd.Timestamp('2018-02-01') + pd.to_timedelta(np.arange(rows), unit='m'),
        'state_route': 'SP->SP', 'estimated_delivery_days': 15., FEATURE: np.nan,
        'delayed': np.zeros(rows, dtype=int),
    })
    return frame, {version: np.full(rows, .1) for version in diagnosis.VERSIONS}, np.ones(rows, bool)


def scores_for(rows, selected):
    values = np.full(rows, .1)
    values[selected] = .9
    return values


def group(public, kind='overall', key='ALL'):
    return diagnosis.decode_group(public, kind, key)


class FourModelBoundaryTests(unittest.TestCase):
    def test_ties_use_id_ascending_independently_of_frame_index(self):
        frame, scores, known = fixture(20)
        frame['order_id'] = frame.order_id.iloc[::-1].to_numpy()
        frame.index = np.arange(20) * 7 + 4
        frame['delayed'] = 1
        public, private = diagnosis.diagnose_phase(frame, scores, known)
        for version in diagnosis.VERSIONS:
            self.assertEqual(private['positions'][version].tolist(), list(range(20, 0, -1)))
            self.assertEqual(private['delayed']['overall:ALL'] - private['missed'][version]['overall:ALL'],
                             set(frame.order_id.iloc[-2:]))
        boundary = public['daily_boundaries'][0]['models']['base08']
        self.assertEqual(boundary['cutoff_score'], .1)
        self.assertEqual(boundary['cutoff_tie_rows'], 20)
        self.assertEqual(boundary['cutoff_tie_alerted_rows'], 2)
        self.assertEqual(boundary['cutoff_tie_unalerted_rows'], 18)
        self.assertTrue(boundary['cross_boundary_tie'])
        self.assertEqual(boundary['score_margin'], 0.)

    def test_unknown_outcome_competes_before_known_delay_masks(self):
        frame, scores, known = fixture(10)
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[0, 'delayed'] = 'future-label-must-not-be-read'
        frame.loc[1, 'delayed'] = 1
        known[0] = False
        public, private = diagnosis.diagnose_phase(frame, scores, known)
        row = group(public)
        self.assertEqual(row['models']['base08']['unknown_alerts'], 1)
        self.assertEqual(row['models']['base08']['TP'], 0)
        self.assertEqual(row['models']['base08']['FP'], 0)
        self.assertEqual(row['common_missed_delays'], 1)
        self.assertEqual(private['common_missed']['overall:ALL'], {frame.order_id.iloc[1]})
        self.assertEqual(public['boundary_totals']['base08']['unknown_alerts'], 1)
        scores['age08'] = scores_for(10, [1])
        changed, _ = diagnosis.diagnose_phase(frame, scores, known)
        exchange = group(changed)['contrasts']['age_minus_base_at_08']['exchanges']
        self.assertEqual(exchange['unknown_removed_alerts'], 1)
        self.assertEqual(exchange['recovered_delays'], 1)
        self.assertEqual(exchange['removed_on_time_alerts'], 0)

    def test_capacity_zero_is_a_separate_gap_bin_and_has_no_cutoff(self):
        frame, scores, known = fixture(9)
        frame['delayed'] = 1
        public, private = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual(private['capacity'].tolist(), [0] * 9)
        row = group(public)
        self.assertEqual(row['models']['age10']['FN'], 9)
        self.assertEqual(row['common_miss_gap']['age10']['bins'],
                         dict(zip(diagnosis.GAP_BINS, [9, 0, 0, 0, 0], strict=True)))
        boundary = public['daily_boundaries'][0]['models']['base10']
        self.assertIsNone(boundary['cutoff_score'])
        self.assertIsNone(boundary['score_margin'])
        self.assertFalse(boundary['cross_boundary_tie'])
        self.assertEqual(boundary['cutoff_tie_rows'], 0)
        self.assertEqual(public['boundary_totals']['base10']['capacity_zero_days'], 1)

    def test_catch_patterns_partition_all_delays_in_version_order(self):
        frame, scores, known = fixture(200)
        frame.loc[:15, 'delayed'] = 1
        for index, version in enumerate(diagnosis.VERSIONS):
            selected = [i for i in range(16) if i & (1 << (3 - index))] + list(range(16, 28))
            scores[version] = scores_for(200, selected)
        public, _ = diagnosis.diagnose_phase(frame, scores, known)
        row = group(public)
        self.assertEqual(row['catch_patterns'], dict.fromkeys(diagnosis.PATTERNS, 1))
        self.assertEqual(row['common_missed_delays'], 1)
        self.assertEqual(row['any_caught_delays'], 15)
        self.assertEqual(row['all_caught_delays'], 1)
        self.assertEqual([row['models'][version]['TP'] for version in diagnosis.VERSIONS], [8] * 4)

    def test_common_misses_differ_from_each_contrasts_own_newly_lost(self):
        frame, scores, known = fixture()
        frame.loc[[0, 1, 2, 4, 9], 'delayed'] = 1
        selected = ([0, 1, 2, 3], [2, 3, 4, 5], [0, 2, 6, 7], [2, 4, 6, 8])
        for version, choice in zip(diagnosis.VERSIONS, selected, strict=True):
            scores[version] = scores_for(40, choice)
        public, private = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual(private['common_missed']['overall:ALL'], {frame.order_id.iloc[9]})
        self.assertEqual(private['lost']['age_minus_base_at_08']['overall:ALL'], set(frame.order_id.iloc[[0, 1]]))
        self.assertEqual(private['lost']['age_minus_base_at_10']['overall:ALL'], {frame.order_id.iloc[0]})
        row = group(public)
        change = row['contrasts']['age_minus_base_at_08']
        self.assertEqual(change['lost_gap']['old']['bins']['inside_budget'], 2)
        self.assertEqual(change['lost_gap']['new']['bins']['one_to_three'], 2)
        self.assertEqual(change['recovered_gap']['old']['rows'], 1)
        self.assertEqual(change['recovered_gap']['new']['bins']['inside_budget'], 1)
        self.assertEqual(row['common_miss_gap']['base08']['rows'], 1)

    def test_daily_gross_route_transfers_survive_equal_monthly_totals(self):
        frame, scores, known = fixture()
        frame['prediction_time'] = pd.Timestamp('2018-02-01') + pd.to_timedelta(np.arange(40) // 20, unit='D')
        frame.loc[[0, 20], 'state_route'] = 'SP->RJ'
        old, new = scores_for(40, [0, 2, 21, 22]), scores_for(40, [1, 2, 20, 22])
        scores = {'base08': old, 'age08': new, 'base10': old, 'age10': new}
        public, _ = diagnosis.diagnose_phase(frame, scores, known)
        row = group(public, 'route', 'SP->RJ')
        self.assertEqual(row['models']['base08']['alerts'], row['models']['age08']['alerts'])
        self.assertEqual(row['contrasts']['age_minus_base_at_08']['allocations'],
                         dict(zip(diagnosis.colsample.ALLOCATIONS, [0, 1, 1], strict=True)))
        flow = public['daily_gross_totals']['age_minus_base_at_08']
        self.assertEqual(flow['within_route_exchanges'], 0)
        self.assertEqual(flow['cross_route_slots'], 2)
        daily = [diagnosis.decode_daily_exchange(row) for row in public['daily_exchanges']
                 if row[1:4] == ['route', 'SP->RJ', 'age_minus_base_at_08']]
        self.assertEqual([row['cross_group_outgoing_slots'] for row in daily], [1, 0])
        self.assertEqual([row['cross_group_incoming_slots'] for row in daily], [0, 1])

    def test_exact_age_boundaries_and_empty_focus_routes_are_preserved(self):
        frame, scores, known = fixture(10)
        frame['state_route'], frame['estimated_delivery_days'] = 'SP->RJ', 25.
        frame[FEATURE] = [24., 24.0001, 72., 72.0001, np.nan, 0., 168., 168.0001, 48., 120.]
        public, private = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual(group(public, 'marginal', 'A')['denominators']['full_batch_rows'], 3)
        self.assertEqual(group(public, 'cell', '111')['denominators']['full_batch_rows'], 3)
        finer = {row['key']: row['denominators']['full_batch_rows'] for row in public['groups']
                 if row['kind'] == 'cell110_age'}
        self.assertEqual(finer, {'missing_or_empty': 1, 'up_to_24h': 2, 'over24_to72h': 0,
                                'over72_to168h': 3, 'over168h': 1})
        self.assertEqual([row['key'] for row in public['groups'] if row['kind'] == 'route'],
                         ['SP->RJ', 'SP->SC', 'SP->SP'])
        self.assertEqual(group(public, 'route', 'SP->SC')['denominators']['full_batch_rows'], 0)
        self.assertEqual(private['common_missed']['route:SP->SP'], set())
        frame['state_route'] = 'XX->YY'
        empty, _ = diagnosis.diagnose_phase(frame, scores, known)
        self.assertEqual(group(empty, 'route', 'SP->RJ')['denominators']['full_batch_rows'], 0)

    def test_eight_cells_conserve_every_daily_outcome_and_changed_slot(self):
        frame, scores, known = fixture(80)
        frame['prediction_time'] = pd.Timestamp('2018-02-01') + pd.to_timedelta(np.arange(80) // 40, unit='D')
        frame['state_route'] = ['SP->RJ' if i & 4 else 'SP->SP' for i in range(80)]
        frame['estimated_delivery_days'] = [25. if i & 2 else 15. for i in range(80)]
        frame[FEATURE] = [48. if i & 1 else 0. for i in range(80)]
        frame['delayed'] = np.arange(80) % 3 == 0
        known[np.arange(80) % 7 == 0] = False
        rng = np.random.default_rng(42)
        scores = {version: rng.random(80) for version in diagnosis.VERSIONS}
        public, _ = diagnosis.diagnose_phase(frame, scores, known)
        cells = [row for row in public['groups'] if row['kind'] == 'cell']
        self.assertEqual(len(cells), 8)
        self.assertEqual([row['denominators']['full_batch_rows'] for row in cells], [10] * 8)
        ledger = [diagnosis.decode_daily_exchange(row) for row in public['daily_exchanges'] if row[1] == 'cell']
        for day in ('2018-02-01', '2018-02-02'):
            for contrast in diagnosis.CONTRASTS:
                rows = [row for row in ledger if row['day'] == day and row['contrast'] == contrast]
                self.assertEqual(len(rows), 8)
                for old_new in ('old_alerts', 'new_alerts'):
                    self.assertEqual(sum(row[old_new] for row in rows), 4)
                added = sum(row['added_alerts'] for row in rows)
                self.assertEqual(added, sum(row['dropped_alerts'] for row in rows))
                self.assertEqual(added, sum(row['within_group_exchanges'] + row['cross_group_incoming_slots'] for row in rows))
                self.assertEqual(sum(row['cross_group_outgoing_slots'] for row in rows),
                                 sum(row['cross_group_incoming_slots'] for row in rows))

    def test_fixed_gap_bins_include_edges_and_avoid_capacity_zero_contamination(self):
        result = diagnosis.gap_summary(np.ones(9, bool), np.array([1, 4, 5, 7, 8, 14, 15, 1, 25]),
                                      np.array([4, 4, 4, 4, 4, 4, 4, 0, 0]))
        self.assertEqual(result['bins'], dict(zip(diagnosis.GAP_BINS, [2, 2, 2, 2, 1], strict=True)))
        empty = diagnosis.gap_summary(np.zeros(9, bool), np.arange(1, 10), np.zeros(9, int))
        self.assertIsNone(empty['minimum'])
        self.assertIsNone(empty['median'])
        self.assertEqual(sum(empty['bins'].values()), 0)

    def test_compact_mode_has_identical_aggregate_results_and_private_cohorts(self):
        frame, scores, known = fixture()
        frame.loc[[0, 7], 'delayed'] = 1
        detailed, private = diagnosis.diagnose_phase(frame, scores, known)
        compact, compact_private = diagnosis.diagnose_phase(frame, scores, known, include_daily=False)
        self.assertNotIn('daily_boundaries', compact)
        self.assertNotIn('daily_exchanges', compact)
        self.assertEqual(compact, {key: value for key, value in detailed.items() if not key.startswith('daily_') or key == 'daily_gross_totals'})
        self.assertEqual(private['common_missed'], compact_private['common_missed'])
        self.assertEqual(private['lost'], compact_private['lost'])

    def test_public_json_exposes_no_order_id_or_row_aligned_identity_data(self):
        frame, scores, known = fixture()
        public, _ = diagnosis.diagnose_phase(frame, scores, known)
        serialized = json.dumps(public, allow_nan=False)
        self.assertNotIn('private-boundary-order-', serialized)
        self.assertNotIn('row_ids', serialized)
        self.assertNotIn('positions', serialized)
        self.assertEqual(diagnosis.schema()['daily_exchange_fields'], list(diagnosis.DAILY_EXCHANGE_FIELDS))

    def test_all_existing_group_counts_and_gross_flows_reproduce_previous_diagnostic(self):
        frame, scores, known = fixture(80)
        frame['prediction_time'] = pd.Timestamp('2018-02-01') + pd.to_timedelta(np.arange(80) // 20, unit='D')
        frame.loc[::3, 'delayed'] = 1
        frame.loc[::2, 'state_route'] = 'SP->RJ'
        frame.loc[::4, 'estimated_delivery_days'] = 25.
        frame.loc[::5, FEATURE] = 48.
        known[::7] = False
        rng = np.random.default_rng(11)
        scores = {version: rng.random(80) for version in diagnosis.VERSIONS}
        new, _ = diagnosis.diagnose_phase(frame, scores, known)
        old, _ = diagnosis.colsample.diagnose_phase(frame, scores, known)
        for old_row in old['groups']:
            previous = diagnosis.colsample.decode_group(old, old_row[0], old_row[1])
            current = group(new, old_row[0], old_row[1])
            self.assertEqual(current['denominators'], previous['denominators'])
            self.assertEqual(current['models'], previous['models'])
            for contrast in diagnosis.CONTRASTS:
                self.assertEqual(current['contrasts'][contrast]['exchanges'], previous['contrasts'][contrast])
                self.assertEqual(current['contrasts'][contrast]['allocations'], previous['allocations'][contrast])
        for contrast, flow in zip(diagnosis.CONTRASTS, old['daily_gross_totals'], strict=True):
            self.assertEqual(list(new['daily_gross_totals'][contrast].values()), flow)

    def test_no_fit_or_model_deserialization_is_called(self):
        frame, scores, known = fixture()
        with patch('pickle.load', side_effect=AssertionError('No model loading')), \
                patch('joblib.load', side_effect=AssertionError('No model loading')):
            diagnosis.diagnose_phase(frame, scores, known)

    def test_invalid_score_known_and_identity_vectors_are_rejected(self):
        frame, scores, known = fixture()
        for bad in (np.nan, np.inf, -.01, 1.01, 1j):
            modified = deepcopy(scores)
            modified['age10'] = modified['age10'].astype(complex if isinstance(bad, complex) else float)
            modified['age10'][0] = bad
            with self.subTest(score=bad), self.assertRaises(ValueError):
                diagnosis.diagnose_phase(frame, modified, known)
        for bad in (np.ones((40, 1)), np.ones(39), np.ones(40, bool)):
            with self.subTest(shape=np.asarray(bad).shape), self.assertRaises(ValueError):
                diagnosis.diagnose_phase(frame, {**scores, 'age10': bad}, known)
        for bad in (known.astype(int), known[:-1], known.reshape(-1, 1)):
            with self.subTest(known=bad.shape), self.assertRaises(ValueError):
                diagnosis.diagnose_phase(frame, scores, bad)
        for bad in (None, '', ' ', 17, frame.order_id.iloc[1]):
            changed = frame.copy()
            changed['order_id'] = changed.order_id.astype(object)
            changed.loc[0, 'order_id'] = bad
            with self.subTest(identity=bad), self.assertRaises(ValueError):
                diagnosis.diagnose_phase(changed, scores, known)
        changed = frame.copy()
        changed.loc[0, 'delayed'] = 2
        with self.assertRaises(ValueError):
            diagnosis.diagnose_phase(changed, scores, known)
        with self.assertRaises(ValueError):
            diagnosis.diagnose_phase(frame, {'base08': scores['base08']}, known)
        with self.assertRaises(ValueError):
            diagnosis.diagnose_phase(frame.iloc[:0], scores, known)

    def test_invalid_prediction_times_and_group_values_are_rejected(self):
        frame, scores, known = fixture()
        for value in (None, pd.NaT, 3, pd.Timestamp('2018-02-01', tz='UTC')):
            changed = frame.copy()
            changed['prediction_time'] = changed.prediction_time.astype(object)
            changed.loc[0, 'prediction_time'] = value
            with self.subTest(time=value), self.assertRaises(ValueError):
                diagnosis.diagnose_phase(changed, scores, known)
        changed = frame.copy()
        changed.loc[0, 'state_route'] = ' '
        with self.assertRaises(ValueError):
            diagnosis.diagnose_phase(changed, scores, known)
        for value in (-1., np.inf):
            changed = frame.copy()
            changed.loc[0, FEATURE] = value
            with self.subTest(age=value), self.assertRaises(ValueError):
                diagnosis.diagnose_phase(changed, scores, known)


if __name__ == '__main__':
    unittest.main()
