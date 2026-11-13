"""Artificial exact-caliper tests; no saved records or timed workloads are read."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_peer_matching_v52 import MATCH_FIELDS, select_workload_peers
from scripts.retailrocket_session_knn_workload_distribution_v51 import COUNT_FIELDS


def peer_fixture():
    """Return 48 new artificial records; both default targets have six values 100."""
    rows = [dict({name: 400 for name in COUNT_FIELDS}, fraction_fallback=False) for _ in range(48)]
    for row in rows:
        row['sql_selected_rows_inserted'] = 50
    for ordinal in (32, 38):
        set_match_values(rows, ordinal, 100)
    return rows


def set_match_values(rows, position, value):
    for name in MATCH_FIELDS:
        rows[position - 1][name] = value


def profile(result, position, target='32'):
    return next(row for row in result['targets'][target]['profiles'] if row['position'] == position)


class PeerMatchingTests(unittest.TestCase):
    def test_exact_primary_and_expanded_boundaries_use_symmetric_folds(self):
        rows = peer_fixture()
        for position in range(1, 6):
            set_match_values(rows, position, 100)
        for position, value in ((2, 125), (3, 150), (4, 80), (5, 79)):
            rows[position - 1][MATCH_FIELDS[0]] = value
        result = select_workload_peers(rows)
        target = result['targets']['32']
        self.assertEqual(target['primary_positions'], [1, 2, 4])
        self.assertEqual(target['expanded_positions'], [1, 2, 3, 4, 5])
        self.assertEqual(target['nearest_positions'], [1])
        self.assertEqual(profile(result, 2)['max_fold'], dict(numerator=5, denominator=4, value=1.25))
        self.assertEqual(profile(result, 4)['max_fold'], dict(numerator=5, denominator=4, value=1.25))
        self.assertEqual(profile(result, 3)['max_fold'], dict(numerator=3, denominator=2, value=1.5))
        self.assertEqual(target['candidates'], 46)
        self.assertEqual(target['eligible_count'], 46)

    def test_fraction_comparison_rejects_boundary_rounding_into_primary(self):
        rows = peer_fixture()
        for ordinal in (32, 38):
            rows[ordinal - 1][MATCH_FIELDS[0]] = 4 * 10**18
        for position, value in ((1, 5 * 10**18), (2, 5 * 10**18 + 1)):
            set_match_values(rows, position, 100)
            rows[position - 1][MATCH_FIELDS[0]] = value
        result = select_workload_peers(rows)
        self.assertEqual(result['targets']['32']['primary_positions'], [1])
        self.assertEqual(result['targets']['32']['expanded_positions'], [1, 2])
        self.assertFalse(profile(result, 2)['within_primary'])
        self.assertEqual(profile(result, 2)['max_fold']['value'], 1.25)
        self.assertEqual(profile(result, 2)['max_fold']['numerator'], 5 * 10**18 + 1)
        self.assertEqual(profile(result, 2)['max_fold']['denominator'], 4 * 10**18)

    def test_nearest_uses_maximum_fold_instead_of_sum_and_keeps_all_ties(self):
        rows = peer_fixture()
        set_match_values(rows, 1, 120)
        set_match_values(rows, 2, 100)
        rows[1][MATCH_FIELDS[0]] = 125
        set_match_values(rows, 3, 120)
        result = select_workload_peers(rows)
        self.assertEqual(result['targets']['32']['nearest_positions'], [1, 3])
        self.assertEqual(result['targets']['32']['nearest_max_fold'], dict(numerator=6, denominator=5, value=1.2))

    def test_no_caliper_peer_does_not_relax_threshold_and_keeps_nearest_ties(self):
        rows = peer_fixture()
        for position in (1, 2):
            set_match_values(rows, position, 200)
        set_match_values(rows, 3, 225)
        result = select_workload_peers(rows)['targets']['32']
        self.assertEqual(result['primary_positions'], [])
        self.assertEqual(result['expanded_positions'], [])
        self.assertEqual(result['nearest_positions'], [1, 2])
        self.assertEqual([row['position'] for row in result['profiles']], [1, 2])
        self.assertTrue(all(not row['within_primary'] and not row['within_expanded'] for row in result['profiles']))

    def test_both_targets_are_excluded_even_when_all_records_match_exactly(self):
        rows = peer_fixture()
        for position in range(1, 49):
            set_match_values(rows, position, 100)
        result = select_workload_peers(rows)
        expected = [position for position in range(1, 49) if position not in (32, 38)]
        for target in result['targets'].values():
            self.assertEqual(target['primary_positions'], expected)
            self.assertEqual(target['expanded_positions'], expected)
            self.assertEqual(target['nearest_positions'], expected)
            self.assertEqual(len(target['profiles']), 46)

    def test_zero_zero_is_one_but_one_sided_zero_excludes_matching_and_nearest(self):
        rows = peer_fixture()
        for ordinal in (32, 38):
            rows[ordinal - 1][MATCH_FIELDS[0]] = 0
        set_match_values(rows, 1, 100)
        rows[0][MATCH_FIELDS[0]] = 0
        result = select_workload_peers(rows)
        target = result['targets']['32']
        self.assertEqual(target['primary_positions'], [1])
        self.assertEqual(target['nearest_positions'], [1])
        self.assertEqual(target['condition_matched_count'], 46)
        self.assertEqual(target['eligible_count'], 1)
        self.assertEqual(target['one_sided_zero_count'], 45)
        self.assertEqual(profile(result, 1)['folds'][MATCH_FIELDS[0]], dict(numerator=1, denominator=1, value=1.0))

    def test_no_comparable_nearest_has_empty_sets_and_a_reason(self):
        rows = peer_fixture()
        for ordinal in (32, 38):
            rows[ordinal - 1][MATCH_FIELDS[0]] = 0
        target = select_workload_peers(rows)['targets']['32']
        self.assertEqual(target['eligible_count'], 0)
        self.assertEqual(target['one_sided_zero_count'], 46)
        self.assertEqual(target['nearest_positions'], [])
        self.assertIsNone(target['nearest_max_fold'])
        self.assertEqual(target['profiles'], [])
        self.assertIn('comparable', target['nearest_unavailable_reason'])

    def test_required_conditions_exclude_otherwise_exact_nearest_candidates(self):
        rows = peer_fixture()
        for position in (1, 2, 3):
            set_match_values(rows, position, 100)
        rows[0]['sql_selected_rows_inserted'] = 49
        rows[1]['fraction_fallback'] = True
        rows[1]['vote_scale_bits'] = 0
        result = select_workload_peers(rows)['targets']['32']
        self.assertEqual(result['primary_positions'], [3])
        self.assertEqual(result['nearest_positions'], [3])
        self.assertEqual(result['condition_matched_count'], 44)
        self.assertEqual(result['eligible_count'], 44)
        self.assertNotIn(1, [row['position'] for row in result['profiles']])
        self.assertNotIn(2, [row['position'] for row in result['profiles']])
        for position in range(1, 49):
            if position not in (32, 38):
                rows[position - 1]['sql_selected_rows_inserted'] = 49
        target = select_workload_peers(rows)['targets']['32']
        self.assertEqual(target['condition_matched_count'], 0)
        self.assertIsNone(target['nearest_max_fold'])
        self.assertIn('required equal conditions', target['nearest_unavailable_reason'])

    def test_diagnostic_fields_are_not_selection_filters(self):
        rows = peer_fixture()
        for position in (1, 2):
            set_match_values(rows, position, 100)
        rows[31]['vote_scale_bits'] = 100
        rows[31]['causal_catalog_candidates'] = 200
        rows[0]['vote_scale_bits'] = 1000
        rows[0]['causal_catalog_candidates'] = 1000
        rows[1]['vote_scale_bits'] = 0
        rows[1]['causal_catalog_candidates'] = 0
        result = select_workload_peers(rows)
        self.assertEqual(result['targets']['32']['primary_positions'], [1, 2])
        self.assertEqual(result['targets']['32']['nearest_positions'], [1, 2])
        first = profile(result, 1)['diagnostics']
        self.assertEqual(first['vote_scale_bits']['fold']['value'], 10)
        self.assertEqual(first['vote_scale_bits']['target_to_peer_ratio']['value'], .1)
        self.assertEqual(first['causal_catalog_candidates']['fold']['value'], 5)
        self.assertTrue(all(row['not_used_for_selection'] for row in first.values()))
        second = profile(result, 2)['diagnostics']
        self.assertIsNone(second['vote_scale_bits']['fold'])
        self.assertIsNone(second['causal_catalog_candidates']['target_to_peer_ratio'])

    def test_fallback_bit_width_diagnostics_are_unavailable_without_changing_peers(self):
        rows = peer_fixture()
        set_match_values(rows, 1, 100)
        for row in rows:
            row['fraction_fallback'] = True
            row['vote_scale_bits'] = 0
        result = select_workload_peers(rows)
        self.assertEqual(result['targets']['32']['primary_positions'], [1])
        diagnostic = profile(result, 1)['diagnostics']['vote_scale_bits']
        self.assertIsNone(diagnostic['fold'])
        self.assertIsNone(diagnostic['target_to_peer_ratio'])
        self.assertIn('sentinel', diagnostic['fold_unavailable_reason'])

    def test_profiles_are_exact_union_nested_thresholds_and_do_not_mutate_input(self):
        rows = peer_fixture()
        for position, value in ((1, 100), (2, 125), (3, 150), (4, 151)):
            set_match_values(rows, position, value)
        before = deepcopy(rows)
        result = select_workload_peers(iter(rows))
        self.assertEqual(rows, before)
        for target in result['targets'].values():
            primary, expanded, nearest = (set(target[key]) for key in
                                         ('primary_positions', 'expanded_positions', 'nearest_positions'))
            self.assertLessEqual(primary, expanded)
            self.assertEqual({row['position'] for row in target['profiles']}, primary | expanded | nearest)
            for row in target['profiles']:
                self.assertNotIn('key', row)
                self.assertEqual(set(row['folds']), set(MATCH_FIELDS))

    def test_invalid_schema_types_length_and_targets_use_v51_validation(self):
        for change in ('missing', 'extra_timing', 'counter_boolean', 'counter_float', 'counter_negative', 'flag_integer'):
            rows = peer_fixture()
            if change == 'missing':
                rows[0].pop(MATCH_FIELDS[0])
            elif change == 'extra_timing':
                rows[0]['seconds'] = .1
            elif change == 'flag_integer':
                rows[0]['fraction_fallback'] = 0
            else:
                rows[0][MATCH_FIELDS[0]] = {'counter_boolean': True, 'counter_float': 1.0, 'counter_negative': -1}[change]
            with self.subTest(change=change), self.assertRaises(ValueError):
                select_workload_peers(rows)
        for targets in ((32,), (32, 32), (0, 38), (32, 49), (True, 38), (32.0, 38)):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                select_workload_peers(peer_fixture(), targets)
        for rows in (None, peer_fixture()[:47]):
            with self.subTest(rows_type=type(rows).__name__), self.assertRaises(ValueError):
                select_workload_peers(rows)


if __name__ == '__main__':
    unittest.main()
