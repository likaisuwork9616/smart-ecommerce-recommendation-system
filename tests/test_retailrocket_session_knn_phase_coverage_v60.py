"""Synthetic interval coordinates only; no saved observations or live sampling."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_phase_coverage_v60 import analyze_interval


def samples(starts, capture=0):
    durations = [capture] * len(starts) if type(capture) is int else capture
    return [dict(sequence=index, start_ns=start, capture_ns=duration)
            for index, (start, duration) in enumerate(zip(starts, durations, strict=True))]


class PhaseCoverageTests(unittest.TestCase):
    def test_full_nominal_coverage_is_not_enough_without_two_contained_intervals(self):
        result = analyze_interval((10, 90), samples([0, 100]))
        self.assertEqual(result['nominal_overlap_union_ns'], 80)
        self.assertEqual(result['nominal_overlap_share'], 1)
        self.assertEqual(result['nominal_crossing_count'], 1)
        self.assertTrue(result['nominal_boundary_only'])
        self.assertFalse(result['screen']['eligible'])
        self.assertEqual(result['screen']['reason'], 'no_contained')

    def test_equal_boundaries_are_contained_and_touch_is_not_overlap(self):
        result = analyze_interval((20, 40), samples([0, 20, 30, 40, 60]))
        self.assertEqual([r['left_sequence'] for r in result['intervals']], [1, 2])
        self.assertEqual(result['nominal_overlap_count'], 2)
        self.assertEqual(result['capture_hull_contained_count'], 2)
        self.assertEqual(result['capture_contained_nominal_duration_ns'], 20)
        self.assertTrue(result['screen']['eligible'])

    def test_capture_hull_crossing_excludes_nominally_contained_interval(self):
        result = analyze_interval((10, 30), samples([0, 10, 20, 30, 40], 2))
        self.assertEqual(result['nominal_contained_count'], 2)
        self.assertEqual(result['capture_hull_contained_count'], 1)
        self.assertEqual(result['nominal_contained_capture_crossing_count'], 1)
        self.assertEqual(result['intervals'][-1]['classification'], 'nominal_contained_capture_crossing')
        self.assertEqual(result['capture_contained_nominal_share'], .5)
        self.assertEqual(result['capture_contained_interior_share'], .4)
        self.assertFalse(result['screen']['share_gate_passed'])
        self.assertFalse(result['screen']['count_gate_passed'])
        self.assertEqual(result['screen']['reason'], 'too_few')

    def test_capture_hull_only_overlap_is_retained_but_not_coverage(self):
        result = analyze_interval((10, 11), samples([0, 10, 20], [0, 2, 0]))
        self.assertEqual(result['capture_hull_only_count'], 1)
        self.assertEqual(result['capture_hull_only_intervals'][0]['left_sequence'], 0)
        self.assertEqual(result['capture_hull_only_intervals'][0]['nominal_overlap_ns'], 0)
        self.assertEqual(result['capture_hull_only_intervals'][0]['capture_hull_overlap_ns'], 1)
        self.assertEqual(result['capture_hull_only_intervals'][0]['classification'], 'capture_hull_only')
        self.assertEqual(result['nominal_overlap_count'], 1)
        self.assertEqual(result['nominal_overlap_union_ns'], 1)

    def test_count_and_half_share_gates_use_unrounded_integer_arithmetic(self):
        records = samples([0, 45, 70, 95, 200])
        result = analyze_interval((20, 120), records)
        self.assertEqual(result['capture_hull_contained_count'], 2)
        self.assertEqual(result['capture_contained_nominal_duration_ns'], 50)
        self.assertEqual(result['capture_contained_nominal_share'], .5)
        self.assertTrue(result['screen']['eligible'])
        below = analyze_interval((20, 121), records)
        self.assertTrue(below['screen']['count_gate_passed'])
        self.assertFalse(below['screen']['share_gate_passed'])
        self.assertEqual(below['screen']['reason'], 'low_share')

    def test_zero_duration_and_phase_outside_sampling_have_distinct_ratios(self):
        records = samples([10, 20, 30], 1)
        zero = analyze_interval((20, 20), records)
        self.assertEqual(zero['nominal_overlap_count'], 0)
        self.assertEqual(zero['capture_hull_only_count'], 0)
        self.assertIsNone(zero['nominal_overlap_share'])
        self.assertIsNone(zero['capture_contained_nominal_share'])
        self.assertIsNone(zero['capture_contained_interior_share'])
        self.assertEqual(zero['screen']['reason'], 'zero_duration')
        outside = analyze_interval((40, 50), records)
        self.assertEqual(outside['nominal_overlap_count'], 0)
        self.assertEqual(outside['nominal_overlap_share'], 0)
        self.assertFalse(outside['nominal_boundary_only'])

    def test_conservation_counts_durations_and_crossing_intervals(self):
        result = analyze_interval((5, 38), samples([0, 10, 20, 30, 40, 50], 2))
        self.assertEqual(result['nominal_overlap_count'], 4)
        self.assertEqual(result['nominal_contained_count'] + result['nominal_crossing_count'], 4)
        self.assertEqual(result['capture_hull_contained_count']
                         + result['nominal_contained_capture_crossing_count'],
                         result['nominal_contained_count'])
        self.assertEqual(sum(r['nominal_overlap_ns'] for r in result['intervals']), 33)
        self.assertEqual(result['nominal_contained_duration_ns'], 20)
        self.assertEqual(result['capture_contained_nominal_duration_ns'], 20)
        self.assertEqual(result['capture_contained_interior_duration_ns'], 16)
        self.assertEqual(result['max_nominal_overlap_interval_ns'], 10)
        self.assertFalse(result['screen']['eligible'])
        self.assertEqual(result['screen']['reason'], 'low_share')

    def test_interior_half_share_boundary_excludes_capture_elapsed(self):
        records = samples([0, 30, 55, 80, 200], 5)
        result = analyze_interval((20, 100), records)
        self.assertEqual(result['capture_hull_contained_count'], 2)
        self.assertEqual(result['capture_contained_nominal_duration_ns'], 50)
        self.assertEqual(result['capture_contained_interior_duration_ns'], 40)
        self.assertEqual(result['capture_contained_interior_share'], .5)
        self.assertTrue(result['screen']['eligible'])
        below = analyze_interval((20, 101), records)
        self.assertFalse(below['screen']['eligible'])
        self.assertEqual(below['screen']['reason'], 'low_share')

    def test_back_to_back_captures_have_no_confirmed_interior_duration(self):
        result = analyze_interval((0, 30), samples([0, 10, 20, 30], [10, 10, 10, 0]))
        self.assertEqual(result['capture_hull_contained_count'], 3)
        self.assertEqual(result['capture_contained_nominal_share'], 1)
        self.assertEqual(result['capture_contained_interior_share'], 0)
        self.assertFalse(result['screen']['eligible'])

    def test_irregular_gaps_and_partial_sampling_span_are_not_filled(self):
        result = analyze_interval((0, 100), samples([20, 25, 60, 80]))
        self.assertEqual(result['nominal_overlap_union_ns'], 60)
        self.assertEqual(result['nominal_overlap_share'], .6)
        self.assertEqual(result['max_nominal_overlap_interval_ns'], 35)
        self.assertEqual([r['nominal_duration_ns'] for r in result['intervals']], [5, 35, 20])
        self.assertEqual(result['capture_contained_nominal_duration_ns'], 60)

    def test_origin_translation_and_inputs_are_unchanged(self):
        records = samples([100, 110, 120, 130], 2)
        before = deepcopy(records)
        result = analyze_interval((105, 125), records, origin_ns=110)
        self.assertEqual(records, before)
        self.assertEqual(result['phase_start_offset_ns'], -5)
        self.assertEqual(result['phase_end_offset_ns'], 15)
        self.assertEqual(result['intervals'][0]['nominal_start_offset_ns'], -10)
        self.assertEqual(result['intervals'][0]['nominal_end_offset_ns'], 0)
        self.assertEqual(result['intervals'][0]['capture_hull_end_offset_ns'], 2)
        result['intervals'][0]['nominal_start_offset_ns'] = 999
        self.assertEqual(records, before)

    def test_duplicate_sequence_restart_and_resource_fields_are_rejected(self):
        for mutation in ('restart', 'skip', 'duplicate', 'reversed', 'capture_overlap', 'resource'):
            records = samples([0, 10, 20], 2)
            if mutation == 'restart': records[2]['sequence'] = 0
            elif mutation == 'skip': records[2]['sequence'] = 3
            elif mutation == 'duplicate': records[1]['start_ns'] = 0
            elif mutation == 'reversed': records[2]['start_ns'] = 5
            elif mutation == 'capture_overlap': records[1]['capture_ns'] = 11
            else: records[0]['system_cpu_percent'] = 99
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analyze_interval((0, 20), records)

    def test_nan_boolean_float_negative_and_bad_phase_shapes_are_rejected(self):
        for value in (True, 1.0, float('nan'), float('inf'), -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analyze_interval((value, 20), samples([0, 10, 20]))
            records = samples([0, 10, 20])
            records[1]['capture_ns'] = value
            with self.subTest(capture=value), self.assertRaises(ValueError):
                analyze_interval((0, 20), records)
        for phase in ((20, 10), (0,), (0, 10, 20), '0,20'):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                analyze_interval(phase, samples([0, 10, 20]))
        with self.assertRaises(ValueError): analyze_interval((0, 20), samples([0]))
        with self.assertRaises(ValueError): analyze_interval((0, 20), samples([0, 10]), origin_ns=False)


if __name__ == '__main__':
    unittest.main()
