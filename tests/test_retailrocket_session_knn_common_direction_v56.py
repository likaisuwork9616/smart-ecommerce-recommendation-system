"""Hand-calculated 48-by-6 numeric cases only; no raw records are loaded."""
from copy import deepcopy
import sys
import unittest

from scripts.retailrocket_session_knn_common_direction_v56 import analyze_same_run


OTHER_POSITIONS = tuple(position for position in range(1, 49) if position not in (32, 33))


def same_run_fixture(deltas=None, pair=1):
    """Make artificial timers whose chosen pair has each requested deviation."""
    deltas = {} if deltas is None else deltas
    timers = {}
    for position in range(1, 49):
        delta = deltas.get(position, 0)
        baseline = -delta if delta < 0 else 0
        timers[position] = {index: baseline for index in range(1, 7)}
        timers[position][pair] = 0 if delta < 0 else delta
    return timers


def cohort_fixture(values, target32=0, target33=0, pair=1):
    """Map exactly 46 artificial deviations to the non-target positions."""
    if len(values) != 46:
        raise ValueError('Artificial cohort must contain 46 values')
    return same_run_fixture(dict(zip(OTHER_POSITIONS, values)) | {32: target32, 33: target33}, pair)


class CommonDirectionTests(unittest.TestCase):
    def test_full_locate_results_keep_six_and_other_five_distinct(self):
        timers = same_run_fixture()
        timers[17] = {1: 10, 2: 9, 3: 8, 4: 7, 5: 6, 6: 5}
        row = analyze_same_run(timers, 2)
        located = row['positions']['17']
        self.assertEqual(len(row['positions']), 48)
        self.assertEqual(located['pair'], 2)
        self.assertEqual(located['seconds'], 9)
        self.assertEqual(located['rank_desc'], dict(first=2, last=2))
        self.assertEqual(located['counts'], dict(below=4, equal=1, above=1))
        self.assertEqual(located['full_six'], dict(count=6, min_seconds=5, median_seconds=7.5,
            max_seconds=10, mad_seconds=1.5, span_seconds=5))
        self.assertEqual(located['other_five'], dict(count=5, min_seconds=5, median_seconds=7,
            max_seconds=10, mad_seconds=1, span_seconds=5))
        self.assertEqual(located['delta_from_median_seconds'], 1.5)
        self.assertEqual(located['delta_from_other_median_seconds'], 2)
        self.assertEqual(located['ratio_to_median'], 9 / 7.5)
        self.assertEqual(located['ratio_to_other_median'], 9 / 7)
        self.assertEqual(located['relation_to_other_range'], 'within')

    def test_each_position_uses_its_own_median_not_a_cross_position_median(self):
        timers = {position: {pair: position * 1000 for pair in range(1, 7)} for position in range(1, 49)}
        for position in range(1, 49):
            timers[position][4] += 1 if position % 2 else -1
        row = analyze_same_run(timers, 4)
        for position in range(1, 49):
            self.assertEqual(row['positions'][str(position)]['full_six']['median_seconds'], position * 1000)
        self.assertEqual(row['other46_summary']['delta_seconds'], dict(min=-1, median=0, max=1))
        self.assertEqual(row['other46_summary']['direction_counts'], dict(above=23, equal=0, below=23))
        self.assertNotIn('sum', row['other46_summary']['delta_seconds'])

    def test_hand_calculated_majority_and_opposite_targets(self):
        row = analyze_same_run(cohort_fixture([.002] * 24 + [-.003] * 10 + [0] * 12, .004, -.004), 1)
        summary = row['other46_summary']
        self.assertEqual(summary['count'], 46)
        self.assertEqual(summary['delta_seconds'], dict(min=-.003, median=.002, max=.002))
        self.assertEqual(summary['direction_counts'], dict(above=24, equal=12, below=10))
        self.assertEqual(summary['over_1ms_counts'], dict(above=24, within=12, below=10))
        self.assertEqual(summary['majority_direction'], dict(raw='above', over_1ms='above'))
        self.assertEqual((summary['unique_longest_count'], summary['unique_shortest_count']), (24, 10))
        for mode in ('raw', 'over_1ms'):
            self.assertEqual(row['target_comparisons']['32'][mode], dict(target_direction='above', same_count=24,
                opposite_count=10, neutral_count=12, same_fraction_of_46=24 / 46, matches_majority=True))
            self.assertEqual(row['target_comparisons']['33'][mode], dict(target_direction='below', same_count=10,
                opposite_count=24, neutral_count=12, same_fraction_of_46=10 / 46, matches_majority=False))

    def test_exact_plus_and_minus_one_ms_are_within_and_target_neutral(self):
        row = analyze_same_run(cohort_fixture([.002] * 11 + [-.002] * 10 + [.001] * 12 + [-.001] * 13, .001, -.001), 1)
        summary = row['other46_summary']
        self.assertEqual(summary['direction_counts'], dict(above=23, equal=0, below=23))
        self.assertEqual(summary['over_1ms_counts'], dict(above=11, within=25, below=10))
        self.assertEqual(summary['majority_direction'], dict(raw=None, over_1ms=None))
        for target in ('32', '33'):
            comparison = row['target_comparisons'][target]
            self.assertEqual(comparison['raw']['same_fraction_of_46'], .5)
            self.assertIsNone(comparison['raw']['matches_majority'])
            self.assertEqual(comparison['over_1ms'], dict(target_direction='neutral', same_count=None,
                opposite_count=None, neutral_count=25, same_fraction_of_46=None, matches_majority=None))

    def test_all_zero_is_neutral_and_zero_median_ratios_stay_none(self):
        row = analyze_same_run(same_run_fixture(), 1)
        summary = row['other46_summary']
        self.assertEqual(summary['delta_seconds'], dict(min=0, median=0, max=0))
        self.assertEqual(summary['direction_counts'], dict(above=0, equal=46, below=0))
        self.assertEqual(summary['over_1ms_counts'], dict(above=0, within=46, below=0))
        self.assertEqual((summary['unique_longest_count'], summary['unique_shortest_count']), (0, 0))
        for located in row['positions'].values():
            self.assertIsNone(located['ratio_to_median'])
            self.assertIsNone(located['ratio_to_other_median'])
        for comparison in row['target_comparisons'].values():
            for mode in ('raw', 'over_1ms'):
                self.assertEqual(comparison[mode]['neutral_count'], 46)
                self.assertIsNone(comparison[mode]['same_count'])

    def test_targets_are_excluded_and_majority_requires_twenty_four(self):
        for positive_count, majority in ((23, None), (24, 'above')):
            with self.subTest(positive_count=positive_count):
                row = analyze_same_run(cohort_fixture([.002] * positive_count + [0] * (46 - positive_count), .003, .003), 1)
                self.assertEqual(row['other_positions'], list(OTHER_POSITIONS))
                self.assertEqual(len(row['other_positions']), 46)
                self.assertEqual(row['other46_summary']['majority_direction'], dict(raw=majority, over_1ms=majority))
                self.assertEqual(row['target_comparisons']['32']['raw']['same_count'], positive_count)
                self.assertEqual(row['target_comparisons']['33']['raw']['same_fraction_of_46'], positive_count / 46)

    def test_below_majority_and_raw_majority_can_differ_from_threshold_mode(self):
        row = analyze_same_run(cohort_fixture([-.0005] * 24 + [.002] * 22, -.0005, .002), 1)
        self.assertEqual(row['other46_summary']['majority_direction'], dict(raw='below', over_1ms=None))
        self.assertTrue(row['target_comparisons']['32']['raw']['matches_majority'])
        self.assertIsNone(row['target_comparisons']['32']['over_1ms']['same_fraction_of_46'])
        self.assertFalse(row['target_comparisons']['33']['raw']['matches_majority'])
        self.assertIsNone(row['target_comparisons']['33']['over_1ms']['matches_majority'])

    def test_no_majority_despite_nonzero_targets(self):
        row = analyze_same_run(cohort_fixture([.002] * 20 + [-.002] * 20 + [0] * 6, .003, -.003), 1)
        self.assertEqual(row['other46_summary']['majority_direction'], dict(raw=None, over_1ms=None))
        for comparison in row['target_comparisons'].values():
            self.assertIsNone(comparison['raw']['matches_majority'])
            self.assertEqual(comparison['raw']['same_count'], 20)

    def test_tied_extremes_do_not_count_as_unique_longest_or_shortest(self):
        timers = same_run_fixture({1: 3, 2: -3, 32: 3, 33: -3})
        timers[3] = {1: 3, 2: 3, 3: 0, 4: 0, 5: 0, 6: 0}
        timers[4] = {1: 0, 2: 0, 3: 3, 4: 3, 5: 3, 6: 3}
        row = analyze_same_run(timers, 1)
        self.assertEqual(row['positions']['3']['rank_desc'], dict(first=1, last=2))
        self.assertEqual(row['positions']['4']['rank_desc'], dict(first=5, last=6))
        self.assertEqual(row['other46_summary']['unique_longest_count'], 1)
        self.assertEqual(row['other46_summary']['unique_shortest_count'], 1)

    def test_requested_pair_can_be_any_of_six(self):
        for pair in range(1, 7):
            with self.subTest(pair=pair):
                row = analyze_same_run(cohort_fixture([.002] * 46, .003, -.003, pair), pair)
                self.assertEqual(row['pair'], pair)
                self.assertEqual(row['other46_summary']['direction_counts']['above'], 46)
                self.assertEqual(row['target_comparisons']['33']['delta_seconds'], -.003)

    def test_large_signed_deviation_midpoint_stays_finite(self):
        largest = sys.float_info.max
        for values, expected in (([largest] * 46, largest), ([-largest] * 46, -largest),
                                 ([-largest] * 23 + [largest] * 23, 0)):
            with self.subTest(expected=expected):
                row = analyze_same_run(cohort_fixture(values), 1)
                self.assertEqual(row['other46_summary']['delta_seconds']['median'], expected)

    def test_invalid_outer_schema_and_position_types_are_rejected(self):
        valid = same_run_fixture()
        invalid = (None, [], {position: valid[position] for position in range(1, 48)},
                   valid | {49: valid[1]}, {str(position): row for position, row in valid.items()},
                   {1.0 if position == 1 else position: row for position, row in valid.items()},
                   {True if position == 1 else position: row for position, row in valid.items()})
        for timers in invalid:
            with self.subTest(kind=type(timers)), self.assertRaises(ValueError):
                analyze_same_run(timers, 1)

    def test_invalid_nested_timer_schema_and_values_are_rejected(self):
        invalid_rows = (None, {}, {pair: 0 for pair in range(1, 6)}, {pair: 0 for pair in range(1, 8)},
                        {1.0: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0},
                        {True: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0})
        for nested in invalid_rows:
            timers = same_run_fixture()
            timers[48] = nested
            with self.subTest(nested=nested), self.assertRaises(ValueError):
                analyze_same_run(timers, 1)
        for value in (True, False, -1, float('nan'), float('inf'), '1', None, 10**1000):
            timers = same_run_fixture()
            timers[48][6] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                analyze_same_run(timers, 1)

    def test_invalid_pair_types_and_range_are_rejected(self):
        for pair in (True, False, 1.0, '1', None, 0, 7):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                analyze_same_run(same_run_fixture(), pair)

    def test_nested_inputs_and_order_are_unchanged(self):
        timers = dict(reversed(list(same_run_fixture({1: .002, 32: -.002}, pair=4).items())))
        before, order = deepcopy(timers), list(timers)
        row = analyze_same_run(timers, 4)
        self.assertEqual(timers, before)
        self.assertEqual(list(timers), order)
        row['positions']['1']['full_six']['median_seconds'] = 100
        self.assertEqual(timers, before)


if __name__ == '__main__':
    unittest.main()
