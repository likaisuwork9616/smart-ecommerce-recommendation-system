"""Synthetic labels plus deterministic reader values; no entry adapter execution."""
from copy import deepcopy
from dataclasses import replace
import unittest

from scripts.retailrocket_session_knn_wall_cpu_v63 import (
    BoundaryRecorder, BoundaryError, analyze_fresh48)
from tests.test_retailrocket_session_knn_wall_cpu_layout_v63 import fixture


def full_fixture():
    markers, cohort = fixture()
    wall_values = iter(value for i in range(725) for value in (2**70+i*100, 2**70+i*100+3))
    cpu_values = iter(2**70+i*130 for i in range(725))
    recorder = BoundaryRecorder(recording_id='synthetic-only', wall_clock=lambda: next(wall_values),
                                cpu_clock=lambda: next(cpu_values), thread_identity=lambda: 7)
    for marker in markers:
        recorder.capture(marker['boundary_id'])
    return recorder.boundaries, markers, cohort


class BoundaryLayoutIntegrationTests(unittest.TestCase):
    def test_all_725_fake_points_bind_578_spans_and_keep_wrapper_remainder(self):
        boundaries, markers, cohort = full_fixture()
        result = analyze_fresh48(boundaries, markers, cohort, completed=True)
        self.assertEqual(result['layout']['observed_marker_count'], 725)
        self.assertEqual(len(result['analysis']['spans']), 578)
        self.assertEqual(len(result['analysis']['roots']), 50)
        for ordinal in range(48):
            rank = result['analysis']['spans'][f'query:{ordinal}:rank']
            marks = result['analysis']['spans'][f'query:{ordinal}:rank_marks']
            self.assertEqual(marks['inclusive']['wall_ns'], 700)
            self.assertEqual(marks['inclusive']['thread_cpu_ns'], 910)
            self.assertEqual(set(marks['unassigned'].values()), {0})
            self.assertEqual(rank['unassigned'], dict(wall_ns=200, thread_cpu_ns=260,
                                                      wall_minus_thread_cpu_ns=-60))
        # 48 independent query roots (1400 each), setup (200), tail (100).
        self.assertEqual(result['analysis']['root_totals']['wall_ns'], 67_500)

    def test_same_ids_wrong_marker_order_rejected_even_for_unreferenced_setup_point(self):
        boundaries, markers, cohort = full_fixture()
        wrong = deepcopy(markers)
        wrong[1]['boundary_id'], wrong[2]['boundary_id'] = wrong[2]['boundary_id'], wrong[1]['boundary_id']
        with self.assertRaises(BoundaryError):
            analyze_fresh48(boundaries, wrong, cohort, completed=True)

    def test_partial_prefix_retains_raw_values_and_never_synthesizes_spans(self):
        boundaries, markers, cohort = full_fixture()
        for count in (0, 3, 19, 725):
            with self.subTest(count=count):
                result = analyze_fresh48(boundaries[:count], markers[:count], cohort, completed=False)
                self.assertEqual(result['layout']['status'], 'incomplete')
                self.assertIsNone(result['analysis'])
                self.assertEqual(result['layout']['spans'], [])
        corrupt = (replace(boundaries[0], thread_cpu_ns=True),)
        with self.assertRaises(BoundaryError):
            analyze_fresh48(corrupt, markers[:1], cohort, completed=False)

    def test_extra_clock_or_missing_clock_is_not_repaired_by_layout(self):
        boundaries, markers, cohort = full_fixture()
        last = boundaries[-1]
        extra = replace(last, boundary_id='extra', sequence=725,
                        wall_before_ns=last.wall_before_ns+100, wall_after_ns=last.wall_after_ns+100,
                        thread_cpu_ns=last.thread_cpu_ns+130)
        for records in (boundaries[:-1], boundaries[:-2], boundaries+(extra,)):
            with self.subTest(length=len(records)), self.assertRaises(BoundaryError):
                analyze_fresh48(records, markers, cohort, completed=True)


if __name__ == '__main__':
    unittest.main()
