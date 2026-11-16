"""Deterministic injected clocks only; never calibrate or call a real entry."""
from dataclasses import FrozenInstanceError, replace
import unittest

from scripts.retailrocket_session_knn_wall_cpu_v63 import (
    Boundary, BoundaryError, BoundaryRecorder, CallRecord, Span, analyze_spans, invoke, span_values)


def recording(walls, cpus, threads=None, *, recording_id='fake'):
    wall_values, cpu_values = iter(walls), iter(cpus)
    identities = iter(threads) if threads is not None else None
    calls = []

    def wall():
        calls.append('wall')
        value = next(wall_values)
        if isinstance(value, BaseException):
            raise value
        return value

    def cpu():
        calls.append('cpu')
        value = next(cpu_values)
        if isinstance(value, BaseException):
            raise value
        return value

    def thread():
        calls.append('thread')
        return next(identities) if identities is not None else 7

    return BoundaryRecorder(recording_id=recording_id, wall_clock=wall,
                            cpu_clock=cpu, thread_identity=thread), calls


def registry(count=8):
    return tuple(Boundary('fake', f'b{i}', i, 7, i*10, i*15, i*10+1) for i in range(count))


class BoundaryTests(unittest.TestCase):
    def test_read_order_and_legacy_return_keep_raw_integers(self):
        recorder, calls = recording([1_000_000_003, 1_000_000_008], [200])
        result = recorder.tap('start')
        self.assertEqual(calls, ['thread', 'wall', 'cpu', 'wall', 'thread'])
        self.assertEqual(result, 1_000_000_003 / 1e9)
        self.assertEqual(recorder.boundaries[0].wall_before_ns, 1_000_000_003)
        self.assertIs(type(recorder.boundaries[0].thread_cpu_ns), int)
        with self.assertRaises(FrozenInstanceError):
            recorder.boundaries[0].thread_cpu_ns = 0

    def test_no_buffer_write_or_validation_between_clock_reads(self):
        observations = []
        walls = iter([False, 3])
        def wall():
            observations.append(('wall', len(recorder.boundaries)))
            return next(walls)
        def cpu():
            observations.append(('cpu', len(recorder.boundaries)))
            return 1
        recorder = BoundaryRecorder(recording_id='fake', wall_clock=wall, cpu_clock=cpu,
                                    thread_identity=lambda: 7)
        with self.assertRaises(BoundaryError):
            recorder.capture('invalid')
        self.assertEqual(observations, [('wall', 0), ('cpu', 0), ('wall', 0)])
        self.assertEqual(recorder.failures[0].raw_values, (False, 1, 3))

    def test_all_signed_formulas_with_unequal_brackets(self):
        recorder, _ = recording([10, 12, 20, 23], [2, 25])
        a, b = recorder.capture('a'), recorder.capture('b')
        self.assertEqual(span_values(a, b), dict(wall_ns=10, thread_cpu_ns=23,
            wall_minus_thread_cpu_ns=-13, start_bracket_ns=2, end_bracket_ns=3,
            wall_inner_ns=8, wall_outer_ns=13, residual_inner_ns=-15, residual_outer_ns=-10))

    def test_large_clock_origin_does_not_roundtrip_through_float(self):
        origin = 2**100
        recorder, _ = recording([origin, origin+1, origin+7, origin+9], [origin, origin+11])
        a, b = recorder.capture('a'), recorder.capture('b')
        value = span_values(a, b)
        self.assertEqual((value['wall_ns'], value['thread_cpu_ns'], value['wall_minus_thread_cpu_ns']), (7, 11, -4))
        shifted = span_values(replace(a, wall_before_ns=0, wall_after_ns=1, thread_cpu_ns=0),
                              replace(b, wall_before_ns=7, wall_after_ns=9, thread_cpu_ns=11))
        self.assertEqual(value, shifted)

    def test_zero_clock_advances_are_legal(self):
        recorder, _ = recording([0, 0, 0, 0], [0, 0])
        value = span_values(recorder.capture('a'), recorder.capture('b'))
        self.assertEqual(set(value.values()), {0})

    def test_bad_numeric_types_are_rejected_without_fake_zero(self):
        for value in (True, False, 1.0, float('nan'), float('inf'), None, '1'):
            for position in ('wall', 'cpu', 'thread'):
                with self.subTest(position=position, value=repr(value)):
                    recorder, _ = recording([value, 2] if position == 'wall' else [1, 2],
                        [value] if position == 'cpu' else [1],
                        [value, value] if position == 'thread' else None)
                    with self.assertRaises(BoundaryError):
                        recorder.capture('a')
                    self.assertEqual(recorder.boundaries, ())
                    self.assertTrue(recorder.failed)

    def test_clock_backwards_and_overlap_fail_closed(self):
        fixtures = [([2, 1], [0]), ([1, 3, 2, 4], [0, 1]), ([1, 2, 3, 4], [2, 1])]
        for walls, cpus in fixtures:
            recorder, calls = recording(walls, cpus)
            with self.subTest(walls=walls), self.assertRaises(BoundaryError):
                recorder.capture('a')
                recorder.capture('b')
            count = len(calls)
            with self.assertRaises(BoundaryError):
                recorder.capture('later')
            self.assertEqual(len(calls), count)

    def test_thread_change_within_or_between_boundaries_is_rejected(self):
        for threads in ([7, 8], [7, 7, 8, 8]):
            recorder, _ = recording([1, 2, 3, 4], [0, 1], threads)
            with self.subTest(threads=threads), self.assertRaises(BoundaryError):
                recorder.capture('a')
                recorder.capture('b')

    def test_duplicate_boundary_rejects_without_reading_more_clocks(self):
        recorder, calls = recording([1, 2], [0])
        recorder.capture('a')
        count = len(calls)
        with self.assertRaises(BoundaryError):
            recorder.capture('a')
        self.assertEqual(len(calls), count)
        self.assertEqual(len(recorder.boundaries), 1)

    def test_clock_failure_retains_partial_raw_values(self):
        error = RuntimeError('synthetic CPU failure')
        recorder, calls = recording([1, 2], [error])
        with self.assertRaises(RuntimeError) as caught:
            recorder.capture('a')
        self.assertIs(caught.exception, error)
        self.assertEqual(calls, ['thread', 'wall', 'cpu'])
        self.assertEqual(recorder.failures[0].raw_values, (1, None, None))

    def test_successful_body_runs_once_and_preserves_return_identity(self):
        recorder, _ = recording([1, 2, 10, 11], [0, 3])
        result, trace = object(), []
        def body():
            trace.append('body')
            return result
        self.assertIs(invoke('D', body, recorder=recorder, span_id='call', phase='work'), result)
        self.assertEqual(trace, ['body'])
        self.assertTrue(recorder.calls[0].completed)
        value = analyze_spans(recorder.boundaries, [recorder.calls[0].as_span()])
        self.assertEqual(value['root_totals']['wall_ns'], 9)

    def test_start_failure_never_runs_body(self):
        recorder, _ = recording([RuntimeError('start')], [])
        trace = []
        with self.assertRaises(RuntimeError):
            recorder.call('call', 'work', lambda: trace.append('body'))
        self.assertEqual(trace, [])
        self.assertFalse(recorder.calls[0].completed)
        self.assertIsNone(recorder.calls[0].start)

    def test_end_failure_does_not_publish_success(self):
        recorder, _ = recording([1, 2, RuntimeError('end')], [0])
        trace = []
        with self.assertRaises(RuntimeError):
            recorder.call('call', 'work', lambda: trace.append('body'))
        self.assertEqual(trace, ['body'])
        self.assertFalse(recorder.calls[0].completed)
        with self.assertRaises(BoundaryError):
            recorder.calls[0].as_span()

    def test_body_exception_and_cleanup_survive_secondary_timer_failure(self):
        recorder, _ = recording([1, 2, RuntimeError('secondary clock')], [0])
        original, trace = LookupError('original fault'), []
        def body():
            try:
                trace.append('body')
                raise original
            finally:
                trace.append('cleanup')
        with self.assertRaises(LookupError) as caught:
            recorder.call('call', 'work', body)
        self.assertIs(caught.exception, original)
        self.assertEqual(trace, ['body', 'cleanup'])
        event = recorder.calls[0]
        self.assertFalse(event.completed)
        self.assertEqual((event.body_error_type, event.timer_error_type), ('LookupError', 'RuntimeError'))
        self.assertIsNone(event.end)

    def test_body_failure_with_valid_end_still_stays_incomplete(self):
        recorder, _ = recording([1, 2, 5, 6], [0, 1])
        def body():
            raise KeyboardInterrupt('synthetic fault')
        with self.assertRaises(KeyboardInterrupt):
            recorder.call('call', 'work', body)
        self.assertIsNotNone(recorder.calls[0].end)
        self.assertFalse(recorder.calls[0].completed)
        self.assertTrue(recorder.failed)

    def test_off_mode_runs_original_body_and_has_no_diagnostic_recorder(self):
        result, trace = object(), []
        self.assertIs(invoke('O', lambda: (trace.append('body'), result)[1]), result)
        self.assertEqual(trace, ['body'])
        recorder, calls = recording([], [])
        with self.assertRaises(BoundaryError):
            invoke('O', lambda: trace.append('unexpected'), recorder=recorder)
        self.assertEqual(calls, [])
        self.assertEqual(recorder.boundaries, ())
        self.assertEqual(recorder.calls, ())

    def test_explicit_dependencies_and_mode_are_required(self):
        with self.assertRaises(TypeError):
            BoundaryRecorder(recording_id='fake')
        for mode in ('D', 'unknown', None):
            with self.subTest(mode=mode), self.assertRaises(BoundaryError):
                invoke(mode, lambda: self.fail('body should not run'))

    def test_forged_completion_flags_and_error_records_cannot_become_spans(self):
        for flag, body_error, timer_error in ((1, None, None), (True, 'Fault', None),
                                             (True, None, 'ClockFault'), (False, None, None)):
            event = CallRecord('x', 'work', None, 'start', 'end', flag, body_error, timer_error)
            with self.subTest(event=event), self.assertRaises(BoundaryError):
                event.as_span()


class SpanTreeTests(unittest.TestCase):
    def test_empty_or_lazy_plan_cannot_publish_empty_success(self):
        for spans in ([], (), iter(())):
            with self.subTest(spans=spans), self.assertRaises(BoundaryError):
                analyze_spans(registry(), spans)
        with self.assertRaises(BoundaryError):
            analyze_spans(iter(registry()), [Span('root', 'root', None, 'b0', 'b7')])

    def test_shared_seven_segments_telescope_without_adding_parent_twice(self):
        boundaries = registry()
        plan = [Span('rank_marks', 'rank_marks', None, 'b0', 'b7')]
        plan += [Span(f'part{i}', 'part', 'rank_marks', f'b{i}', f'b{i+1}') for i in range(7)]
        result = analyze_spans(boundaries, plan)
        parent = result['spans']['rank_marks']
        self.assertEqual(parent['children_sum'], dict(wall_ns=70, thread_cpu_ns=105, wall_minus_thread_cpu_ns=-35))
        self.assertEqual(set(parent['unassigned'].values()), {0})
        self.assertEqual(result['root_totals'], parent['children_sum'])

    def test_outer_wrapper_and_gaps_remain_unassigned_not_wait(self):
        boundaries = registry(10)
        plan = [Span('outer', 'outer', None, 'b0', 'b9'),
                Span('inner', 'inner', 'outer', 'b1', 'b8')]
        result = analyze_spans(boundaries, plan)
        self.assertEqual(result['spans']['outer']['unassigned'],
                         dict(wall_ns=20, thread_cpu_ns=30, wall_minus_thread_cpu_ns=-10))
        self.assertNotIn('waiting', repr(result))

    def test_nested_measured_calls_have_correct_parent_without_clock_defaults(self):
        recorder, _ = recording([1, 2, 3, 4, 5, 6, 7, 8], [0, 1, 2, 3])
        result = recorder.call('outer', 'outer', lambda:
            recorder.call('inner', 'inner', lambda: 42, parent='outer'))
        self.assertEqual(result, 42)
        values = analyze_spans(recorder.boundaries, [row.as_span() for row in recorder.calls])
        self.assertEqual(values['roots'], ['outer'])
        self.assertEqual(values['spans']['outer']['unassigned']['wall_ns'], 4)

    def test_missing_duplicate_or_reordered_endpoints_rejected(self):
        points = registry()
        plans = [[Span('x', 'work', None, 'missing', 'b7')],
                 [Span('x', 'work', None, 'b7', 'b0')],
                 [Span('x', 'work', None, 'b1', 'b1')],
                 [Span('x', 'work', None, 'b0', 'b7')]*2]
        for plan in plans:
            with self.subTest(plan=plan), self.assertRaises(BoundaryError):
                analyze_spans(points, plan)
        for bad in (points[:-1]+(points[-2],), tuple(reversed(points)), points[1:]):
            with self.subTest(registry=bad), self.assertRaises(BoundaryError):
                analyze_spans(bad, [Span('x', 'work', None, 'b0', 'b7')])

    def test_wrong_parent_cycle_child_outside_and_sibling_overlap_rejected(self):
        points = registry()
        cases = [
            [Span('x', 'x', 'missing', 'b0', 'b7')],
            [Span('x', 'x', 'y', 'b0', 'b7'), Span('y', 'y', 'x', 'b0', 'b7')],
            [Span('x', 'x', None, 'b1', 'b6'), Span('y', 'y', 'x', 'b0', 'b5')],
            [Span('x', 'x', None, 'b0', 'b7'), Span('a', 'a', 'x', 'b1', 'b4'), Span('b', 'b', 'x', 'b3', 'b5')],
            [Span('x', 'x', None, 'b0', 'b7'), Span('y', 'y', None, 'b1', 'b6')]]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(BoundaryError):
                analyze_spans(points, case)

    def test_mixed_recording_or_thread_registry_is_rejected(self):
        points = registry()
        for replacement in (replace(points[-1], recording_id='other'), replace(points[-1], thread_id=8)):
            with self.subTest(replacement=replacement), self.assertRaises(BoundaryError):
                analyze_spans(points[:-1]+(replacement,), [Span('x', 'x', None, 'b0', 'b7')])

    def test_original_registry_and_plan_are_not_mutated(self):
        points = registry()
        spans = [Span('root', 'root', None, 'b0', 'b7'), Span('child', 'child', 'root', 'b1', 'b6')]
        before = (tuple(points), tuple(spans))
        first = analyze_spans(points, spans)
        first['spans']['root']['direct_children'].clear()
        self.assertEqual((tuple(points), tuple(spans)), before)
        self.assertEqual(analyze_spans(points, spans)['spans']['root']['direct_children'], ['child'])


if __name__ == '__main__':
    unittest.main()
