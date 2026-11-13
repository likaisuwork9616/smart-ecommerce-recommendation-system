"""Artificial numeric fixtures only; no saved timer or experiment is loaded."""
from copy import deepcopy
from math import isfinite
import sys
import unittest

from scripts.retailrocket_session_knn_time_reference_v55 import locate_in_six, summarize_six


def time_fixture(values=(1, 2, 3, 4, 5, 6)):
    """Build a fresh artificial six-pair timer dictionary."""
    return dict(zip(range(1, 7), values))


class TimeReferenceTests(unittest.TestCase):
    def test_even_median_and_unscaled_mad_are_hand_calculated(self):
        self.assertEqual(summarize_six(time_fixture()), dict(count=6, min_seconds=1,
            median_seconds=3.5, max_seconds=6, mad_seconds=1.5, span_seconds=5))

    def test_other_five_uses_its_own_odd_median_and_mad(self):
        row = locate_in_six(time_fixture((1, 2, 3, 4, 8, 20)), 6)
        self.assertEqual(row['full_six']['median_seconds'], 3.5)
        self.assertEqual(row['full_six']['mad_seconds'], 2)
        self.assertEqual(row['other_five'], dict(count=5, min_seconds=1,
            median_seconds=3, max_seconds=8, mad_seconds=1, span_seconds=7))
        self.assertEqual(row['delta_from_median_seconds'], 16.5)
        self.assertEqual(row['delta_from_other_median_seconds'], 17)
        self.assertEqual(row['ratio_to_median'], 20 / 3.5)
        self.assertEqual(row['ratio_to_other_median'], 20 / 3)

    def test_descending_tied_ranks_and_counts_include_the_target(self):
        timers = time_fixture((2, 8, 8, 3, 8, 1))
        for pair in (2, 3, 5):
            with self.subTest(pair=pair):
                row = locate_in_six(timers, pair)
                self.assertEqual(row['rank_desc'], dict(first=1, last=3))
                self.assertEqual(row['counts'], dict(below=3, equal=3, above=0))
                self.assertEqual(row['other_five']['count'], 5)
                self.assertEqual(row['relation_to_other_range'], 'within')

    def test_nearby_values_do_not_become_approximate_ties(self):
        row = locate_in_six(time_fixture((1, 1 + 1e-12, 2, 3, 4, 5)), 1)
        self.assertEqual(row['rank_desc'], dict(first=6, last=6))
        self.assertEqual(row['counts'], dict(below=0, equal=1, above=5))

    def test_all_equal_positive_and_zero_timers(self):
        for value in (0, 7):
            with self.subTest(value=value):
                row = locate_in_six(time_fixture((value,) * 6), 3)
                self.assertEqual(row['rank_desc'], dict(first=1, last=6))
                self.assertEqual(row['counts'], dict(below=0, equal=6, above=0))
                for summary in (row['full_six'], row['other_five']):
                    self.assertEqual(summary['median_seconds'], value)
                    self.assertEqual(summary['mad_seconds'], 0)
                    self.assertEqual(summary['span_seconds'], 0)
                self.assertEqual(row['ratio_to_median'], 1 if value else None)
                self.assertEqual(row['ratio_to_other_median'], 1 if value else None)
                self.assertEqual(row['relation_to_other_range'], 'within')

    def test_minimum_maximum_and_interior_range_relations(self):
        for pair, relation, rank in ((1, 'below', 6), (6, 'above', 1), (3, 'within', 4)):
            with self.subTest(pair=pair):
                row = locate_in_six(time_fixture(), pair)
                self.assertEqual(row['relation_to_other_range'], relation)
                self.assertEqual(row['rank_desc'], dict(first=rank, last=rank))

    def test_equal_other_range_endpoints_are_within(self):
        timers = time_fixture((1, 1, 3, 5, 6, 6))
        for pair in (1, 6):
            with self.subTest(pair=pair):
                self.assertEqual(locate_in_six(timers, pair)['relation_to_other_range'], 'within')

    def test_zero_denominators_are_separate_for_six_and_five(self):
        row = locate_in_six(time_fixture((0, 0, 0, 2, 4, 6)), 6)
        self.assertEqual(row['full_six']['median_seconds'], 1)
        self.assertEqual(row['ratio_to_median'], 6)
        self.assertEqual(row['other_five']['median_seconds'], 0)
        self.assertIsNone(row['ratio_to_other_median'])
        zero = locate_in_six(time_fixture((0, 0, 0, 0, 0, 6)), 6)
        self.assertIsNone(zero['ratio_to_median'])
        self.assertIsNone(zero['ratio_to_other_median'])

    def test_large_finite_midpoints_do_not_overflow(self):
        largest = sys.float_info.max
        for timers in (time_fixture((largest,) * 6), time_fixture((0, 0, 0, largest, largest, largest))):
            with self.subTest(timers=timers):
                summary = summarize_six(timers)
                row = locate_in_six(timers, 6)
                for value in summary.values():
                    self.assertTrue(isfinite(value))
                self.assertTrue(isfinite(row['delta_from_median_seconds']))
                self.assertTrue(isfinite(row['ratio_to_median']))
        self.assertEqual(summarize_six(time_fixture((largest,) * 6))['median_seconds'], largest)
        self.assertEqual(summarize_six(time_fixture((0, 0, 0, largest, largest, largest)))['mad_seconds'], largest / 2)

    def test_tiny_midpoint_is_rounded_without_premature_underflow(self):
        tiny = float.fromhex('0x0.0000000000001p-1022')
        summary = summarize_six(time_fixture((0, 0, tiny, 2 * tiny, 3 * tiny, 4 * tiny)))
        self.assertEqual(summary['median_seconds'], 2 * tiny)

    def test_nonfinite_derived_ratio_is_rejected(self):
        timers = time_fixture((1e-308, 1e-308, 1e-308, 1e-308, 1e-308, 1e308))
        self.assertEqual(summarize_six(timers)['median_seconds'], 1e-308)
        with self.assertRaisesRegex(ValueError, 'Finite nonnegative numeric value required: ratio'):
            locate_in_six(timers, 6)

    def test_invalid_timer_schema_and_key_types_are_rejected(self):
        invalid = (None, [], {pair: pair for pair in range(1, 6)},
                   {pair: pair for pair in range(1, 8)},
                   {str(pair): pair for pair in range(1, 7)},
                   {1.0: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6},
                   {True: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6})
        for timers in invalid:
            with self.subTest(timers=timers):
                for operation in (summarize_six, lambda item: locate_in_six(item, 1)):
                    with self.assertRaises(ValueError):
                        operation(timers)

    def test_invalid_timer_values_are_rejected(self):
        for value in (True, False, -1, float('nan'), float('inf'), -float('inf'), '1', None, 10**1000):
            with self.subTest(value=value):
                timers = time_fixture()
                timers[4] = value
                for operation in (summarize_six, lambda item: locate_in_six(item, 1)):
                    with self.assertRaisesRegex(ValueError, 'Finite nonnegative numeric'):
                        operation(timers)

    def test_invalid_target_pairs_are_rejected(self):
        for pair in (True, False, 1.0, '1', None, 0, 7):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                locate_in_six(time_fixture(), pair)

    def test_input_and_dictionary_order_are_unchanged(self):
        timers = {6: 6, 3: 3, 2: 2, 5: 5, 1: 1, 4: 4}
        original = deepcopy(timers)
        original_keys = list(timers)
        self.assertEqual(summarize_six(timers), summarize_six(time_fixture()))
        self.assertEqual(locate_in_six(timers, 4), locate_in_six(time_fixture(), 4))
        self.assertEqual(timers, original)
        self.assertEqual(list(timers), original_keys)


if __name__ == '__main__':
    unittest.main()
