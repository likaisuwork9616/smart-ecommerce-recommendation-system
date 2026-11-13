"""Artificial paired-stage arithmetic only; no raw records or experiment calls."""
from copy import deepcopy
from math import fsum, inf, nextafter
import unittest

from scripts.retailrocket_session_knn_peer_stages_v53 import (
    ATOMIC_KEYS, GROUP_KEYS, ORDERS, compare_stage_pair, summarize_stage_pairs,
)


def query_parts_fixture(changes=None, *, baseline=10.0):
    """Return an artificial V50-shaped charged-parts result."""
    parts = dict.fromkeys(ATOMIC_KEYS, baseline)
    for name, change in (changes or {}).items():
        parts[name] += change
    total = fsum(parts.values())
    return dict(parts_seconds=parts, query_charged_seconds=total,
                query_envelope_seconds=total + .5, signed_timer_bridge=.5)


def stage_pair_fixture(delta32=None, delta33=None, *, pair=1):
    original = {position: query_parts_fixture() for position in (32, 33)}
    candidate = {32: query_parts_fixture(delta32), 33: query_parts_fixture(delta33)}
    return compare_stage_pair(original, candidate, pair, ORDERS[pair - 1])


def scalar_pair_fixture(delta32, delta33, *, pair=1):
    original, candidate = {}, {}
    for position, delta in ((32, delta32), (33, delta33)):
        original[position] = query_parts_fixture({'append': max(-delta, 0)}, baseline=0)
        candidate[position] = query_parts_fixture({'append': max(delta, 0)}, baseline=0)
    return compare_stage_pair(original, candidate, pair, ORDERS[pair - 1])


class StagePairTests(unittest.TestCase):
    def test_atomic_and_grouped_views_conserve_without_double_counting_ranking(self):
        row = stage_pair_fixture({'sql_positive_overlaps': 3, 'sql_selected_votes_and_accumulation': -2, 'append': .5},
                                 {'sql_positive_overlaps': -1, 'sql_selected_votes_and_accumulation': 1, 'append': -1})
        self.assertEqual(row['positions']['32']['total_delta_seconds'], 1.5)
        self.assertEqual(row['positions']['33']['total_delta_seconds'], -1)
        self.assertEqual(row['gap_seconds'], 2.5)
        self.assertEqual(row['gap_atomic_seconds']['sql_positive_overlaps'], 4)
        self.assertEqual(row['gap_atomic_seconds']['sql_selected_votes_and_accumulation'], -3)
        self.assertEqual(row['gap_group_seconds']['ranking'], 1)
        self.assertEqual(fsum(row['gap_atomic_seconds'].values()), 2.5)
        self.assertEqual(fsum(row['gap_group_seconds'].values()), 2.5)
        self.assertNotIn('ranking', row['gap_atomic_seconds'])
        self.assertEqual(set(row['gap_group_seconds']), set(GROUP_KEYS))
        atomic, groups = row['gap_alignment']['atomic'], row['gap_alignment']['groups']
        self.assertEqual((atomic['positive_seconds'], atomic['negative_seconds'], atomic['net_seconds']), (5.5, -3, 2.5))
        self.assertEqual((groups['positive_seconds'], groups['negative_seconds'], groups['net_seconds']), (2.5, 0, 2.5))
        self.assertAlmostEqual(atomic['components']['sql_positive_overlaps']['positive_share'], 4 / 5.5)
        self.assertEqual(groups['components']['ranking']['positive_share'], .4)

    def test_negative_gap_is_aligned_using_its_own_sign(self):
        row = stage_pair_fixture({'sql_positive_overlaps': -3, 'append': 1}, {'sql_positive_overlaps': 1})
        self.assertEqual(row['gap_seconds'], -3)
        self.assertEqual(row['gap_alignment']['direction'], -1)
        self.assertTrue(row['direction']['opposite_sign'])
        atomic = row['gap_alignment']['atomic']
        self.assertEqual(atomic['components']['sql_positive_overlaps']['aligned_net'], 4)
        self.assertEqual(atomic['components']['append']['aligned_net'], -1)
        self.assertEqual((atomic['positive_seconds'], atomic['negative_seconds'], atomic['net_seconds']), (4, -1, 3))

    def test_direction_uses_unrounded_deltas_and_strict_one_millisecond_boundaries(self):
        above = nextafter(.001, inf)
        cases = ((.001, -.002, 'within_1ms'), (-.001, .002, 'within_1ms'),
                 (0, .003, 'within_1ms'), (.002, .003, 'same_sign'), (-.002, -.003, 'same_sign'),
                 (above, -above, 'opposite_sign'), (-above, above, 'opposite_sign'))
        for left, right, label in cases:
            with self.subTest(left=left, right=right):
                row = scalar_pair_fixture(left, right)
                self.assertEqual(row['direction']['label'], label)
                self.assertEqual(row['direction']['opposite_sign'], label == 'opposite_sign')

    def test_zero_gap_retains_raw_offsets_but_has_no_alignment_direction(self):
        row = stage_pair_fixture({'sql_positive_overlaps': 1, 'append': -1})
        self.assertEqual(row['gap_seconds'], 0)
        self.assertEqual(row['gap_atomic_seconds']['sql_positive_overlaps'], 1)
        self.assertEqual(row['gap_atomic_seconds']['append'], -1)
        self.assertFalse(row['gap_alignment']['defined'])
        self.assertEqual(row['gap_alignment']['direction'], 0)
        for view in ('atomic', 'groups'):
            result = row['gap_alignment'][view]
            self.assertEqual(result['positive_seconds'], 0)
            self.assertTrue(all(value['positive_share'] is None for value in result['components'].values()))

    def test_original_inputs_are_unchanged_and_tail_or_envelope_fields_are_excluded(self):
        original = {position: query_parts_fixture() for position in (32, 33)}
        candidate = deepcopy(original)
        before = deepcopy((original, candidate))
        expected = compare_stage_pair(original, candidate, 1, 'CR')
        self.assertEqual((original, candidate), before)
        candidate[32]['tail_commit_seconds'] = 1000
        candidate[32]['query_envelope_seconds'] += 1000
        candidate[32]['signed_timer_bridge'] += 1000
        self.assertEqual(compare_stage_pair(original, candidate, 1, 'CR'), expected)

    def test_tiny_signed_remainders_are_preserved_without_clamping(self):
        original = {position: query_parts_fixture(baseline=0) for position in (32, 33)}
        candidate = deepcopy(original)
        candidate[32]['parts_seconds'].update(rank_other=-1e-9, append=1)
        candidate[32]['query_charged_seconds'] = 1 - 1e-9
        row = compare_stage_pair(original, candidate, 1, 'CR')
        self.assertEqual(row['positions']['32']['atomic_delta_seconds']['rank_other'], -1e-9)
        self.assertEqual(row['positions']['32']['group_delta_seconds']['ranking'], -1e-9)

    def test_invalid_position_pair_order_part_schema_and_conservation_are_rejected(self):
        original = {position: query_parts_fixture() for position in (32, 33)}
        candidate = deepcopy(original)
        for bad in ({32: original[32]}, {'32': original[32], '33': original[33]},
                    {32.0: original[32], 33: original[33]}, {32: original[32], 33: original[33], 38: original[32]}):
            with self.subTest(positions=list(bad)), self.assertRaisesRegex(ValueError, 'Exactly integer positions'):
                compare_stage_pair(bad, candidate, 1, 'CR')
        for pair, order in ((True, 'CR'), (1.0, 'CR'), (0, 'CR'), (7, 'CR'), (1, 'RC'), (2, 'CR'), (1, 'cr')):
            with self.subTest(pair=pair, order=order), self.assertRaises(ValueError):
                compare_stage_pair(original, candidate, pair, order)
        for change in ('missing', 'extra', 'charged'):
            changed = deepcopy(candidate)
            if change == 'missing':
                changed[32]['parts_seconds'].pop('append')
            elif change == 'extra':
                changed[32]['parts_seconds']['ranking'] = 1
            else:
                changed[32]['query_charged_seconds'] += .01
            with self.subTest(change=change), self.assertRaises(ValueError):
                compare_stage_pair(original, changed, 1, 'CR')

    def test_invalid_numeric_values_and_material_negative_original_stages_are_rejected(self):
        original = {position: query_parts_fixture() for position in (32, 33)}
        for value in (True, '1', float('nan'), float('inf'), -1):
            candidate = deepcopy(original)
            candidate[32]['parts_seconds']['append'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                compare_stage_pair(original, candidate, 1, 'CR')
        candidate = deepcopy(original)
        candidate[32]['parts_seconds']['rank_other'] = -.1
        with self.assertRaisesRegex(ValueError, 'negative beyond'):
            compare_stage_pair(original, candidate, 1, 'CR')
        with self.assertRaisesRegex(ValueError, 'Finite numeric'):
            scalar_pair_fixture(1e308, -1e308)


class StageSummaryTests(unittest.TestCase):
    def test_alignment_precedes_positive_aggregation_and_does_not_use_netted_denominator(self):
        pairs = [stage_pair_fixture(pair=index) for index in range(1, 7)]
        pairs[0] = stage_pair_fixture({'sql_positive_overlaps': 3, 'sql_selected_votes_and_accumulation': -2, 'append': .5},
                                     {'sql_positive_overlaps': -1, 'sql_selected_votes_and_accumulation': 1, 'append': -1}, pair=1)
        pairs[1] = stage_pair_fixture({'sql_positive_overlaps': 1, 'sql_selected_votes_and_accumulation': -3},
                                     {'sql_positive_overlaps': -1, 'sql_selected_votes_and_accumulation': 1, 'append': 1}, pair=2)
        before = deepcopy(pairs)
        result = summarize_stage_pairs(pairs)
        self.assertEqual(pairs, before)
        self.assertEqual(result['opposite_pair_numbers'], [1, 2])
        self.assertEqual(result['all_pairs']['gap_seconds'], -.5)
        subset = result['opposite_pairs']
        self.assertEqual(subset['aligned_total_seconds'], 5.5)
        atomic = subset['atomic']
        self.assertEqual((atomic['positive_seconds'], atomic['negative_seconds'], atomic['net_seconds']), (10.5, -5, 5.5))
        first = atomic['components']['sql_positive_overlaps']
        self.assertEqual((first['aligned_net'], first['positive_support'], first['negative_offset']), (2, 4, -2))
        self.assertAlmostEqual(first['positive_share'], 4 / 10.5)
        self.assertNotEqual(first['positive_share'], 2 / 5.5)
        groups = subset['groups']
        self.assertEqual(groups['positive_seconds'], 5.5)
        self.assertEqual(groups['negative_seconds'], 0)
        self.assertEqual(fsum(result['all_pairs']['gap_atomic_seconds'].values()), -.5)
        self.assertEqual(fsum(result['all_pairs']['gap_group_seconds'].values()), -.5)

    def test_empty_opposite_subset_has_zero_counts_totals_and_none_shares(self):
        pairs = [scalar_pair_fixture(.002, .003, pair=index) for index in range(1, 7)]
        result = summarize_stage_pairs(pairs)
        self.assertEqual(result['opposite_pair_numbers'], [])
        self.assertEqual(result['direction_counts'], dict(eligible_count=6, opposite_sign_count=0, same_sign_count=6, within_1ms_count=0))
        subset = result['opposite_pairs']
        self.assertEqual((subset['count'], subset['pair_numbers'], subset['aligned_total_seconds']), (0, [], 0))
        for view in ('atomic', 'groups'):
            self.assertEqual(subset[view]['positive_seconds'], 0)
            self.assertEqual(subset[view]['negative_seconds'], 0)
            self.assertTrue(all(row['positive_share'] is None for row in subset[view]['components'].values()))
        self.assertEqual(len(result['pairs']), 6)
        self.assertEqual(result['all_pairs']['count'], 6)

    def test_six_pair_order_and_all_saved_derived_views_are_revalidated(self):
        pairs = [scalar_pair_fixture(.002, -.003, pair=index) for index in range(1, 7)]
        for supplied in (pairs[:5], pairs + [pairs[-1]], [pairs[1], pairs[0], *pairs[2:]]):
            with self.subTest(length=len(supplied)), self.assertRaises(ValueError):
                summarize_stage_pairs(supplied)
        for change in ('group', 'gap', 'classification', 'classification_type', 'alignment'):
            supplied = deepcopy(pairs)
            if change == 'group':
                supplied[0]['positions']['32']['group_delta_seconds']['ranking'] += .1
            elif change == 'gap':
                supplied[0]['gap_seconds'] += .1
            elif change == 'classification':
                supplied[0]['direction']['opposite_sign'] = False
            elif change == 'classification_type':
                supplied[0]['direction']['eligible'] = 1
            else:
                supplied[0]['gap_alignment']['atomic']['positive_seconds'] += .1
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'differ from atomic'):
                summarize_stage_pairs(supplied)


if __name__ == '__main__':
    unittest.main()
