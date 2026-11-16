"""Literal fake readers only. No wall/CPU clocks, real sleep or live metadata."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_clock_collector_v67 import (
    collect_capability, REAL_ORIGIN, FAKE_ORIGIN, DEADLINE_NS, SAMPLE_CAP)
from scripts.retailrocket_session_knn_clock_capability_v67 import evaluate_capability


SOURCE = 'a' * 64
EVIDENCE = []


class FakeMachine:
    def __init__(self):
        self.now = 0
        self.cpu_value = 0
        self.capture_step = 49_999_999
        self.cpu_step = 10_000
        self.bracket = 1
        self.in_capture = False
        self.capture_reads = 0
        self.capture_count = 0
        self.cpu_calls = 0
        self.sleep_calls = 0
        self.sleep_advance = 50_000_000
        self.events = []
        self.saved = []
        self.metadata_delay = 0
        self.evaluation_delay = 0
        self.persist_end = None
        self.persist_error = None
        self.metadata_error = None
        self.sleep_error = None
        self.cpu_error_at = None
        self.wall_error_at = None
        self.wall_calls = 0
        self.cancel_at_cpu = None
        self.cancel_after_evaluate = False
        self.evaluated = False
        self.thread_change_at = None
        self.meta = dict(environment=dict(python='literal-fake-python', os='literal-fake-os',
            process_id=19, thread_id=73, source_sha256=SOURCE), clocks={
            name: dict(api=api, available=True, implementation='literal-' + name,
                monotonic=True, adjustable=False, resolution_seconds='0.000000001')
            for name, api in (('wall', 'time.perf_counter_ns'), ('cpu', 'time.thread_time_ns'))})

    def metadata(self):
        self.events.append('M')
        self.now += self.metadata_delay
        if self.metadata_error:
            raise self.metadata_error
        return deepcopy(self.meta)

    def wall(self):
        self.events.append('W')
        self.wall_calls += 1
        if self.wall_calls == self.wall_error_at:
            raise OSError('wall failed')
        if self.in_capture:
            self.now += self.capture_step if self.capture_reads == 0 else self.bracket
            self.capture_reads += 1
        return self.now

    def cpu(self):
        self.events.append('C')
        self.cpu_calls += 1
        if self.cpu_calls == self.cpu_error_at:
            raise LookupError('original cpu failure')
        self.cpu_value += self.cpu_step
        return self.cpu_value

    def thread(self):
        self.events.append('T')
        self.in_capture = not self.in_capture
        if self.in_capture:
            self.capture_reads = 0
            self.capture_count += 1
        if self.thread_change_at == self.capture_count and not self.in_capture:
            return 74
        return 73

    def sleep(self, seconds):
        if seconds != 0.05:
            raise AssertionError('Only the planned 50 ms request is allowed')
        self.events.append('S')
        self.sleep_calls += 1
        self.now += self.sleep_advance
        if self.sleep_error:
            raise self.sleep_error

    def cancelled(self):
        return ((self.cancel_at_cpu is not None and self.cpu_calls >= self.cancel_at_cpu)
                or (self.cancel_after_evaluate and self.evaluated))

    def evaluate(self, record):
        self.events.append('E')
        self.now += self.evaluation_delay
        self.evaluated = True
        # Literal pass isolates collection/deadline gates from decision arithmetic.
        return {'status': 'clock_capability_passed', 'fixture_only': True}

    def persist(self, snapshot):
        self.events.append('P')
        self.saved.append(deepcopy(snapshot))
        if self.persist_end is not None:
            self.now = self.persist_end
        if self.persist_error:
            raise self.persist_error
        return dict(path='fake://raw.json', bytes=123, sha256='b' * 64)

    def collect(self, **overrides):
        kwargs = dict(origin=FAKE_ORIGIN, source_sha256=SOURCE, metadata=self.metadata,
            wall_clock=self.wall, cpu_clock=self.cpu, thread_identity=self.thread,
            sleep=self.sleep, cancelled=self.cancelled, persist=self.persist,
            evaluate=self.evaluate, sample_cap=11)
        kwargs.update(overrides)
        return collect_capability(**kwargs)


class CollectorTests(unittest.TestCase):
    def result(self, machine, **overrides):
        result = machine.collect(**overrides)
        EVIDENCE.append(dict(case=self.id().rsplit('.', 1)[-1], status=result['final']['status'],
            stamps=result['collection']['captured_stamps'], sleeps=machine.sleep_calls,
            stop_reasons=deepcopy(result['collection']['stop_reasons'])))
        return result

    def assert_no_calibration_after(self, machine, marker):
        tail = machine.events[machine.events.index(marker) + 1:]
        self.assertFalse(set(tail) & {'C', 'S', 'T'})

    def test_normal_three_read_order_and_all_slots(self):
        machine = FakeMachine()
        result = self.result(machine)
        self.assertEqual(result['final']['status'], 'clock_capability_passed')
        self.assertTrue(result['final']['completed'])
        self.assertFalse(result['final']['live_B_passed'])
        self.assertEqual([len(row['stamps']) for row in result['record']['rounds']], [11] * 3)
        self.assertEqual(machine.sleep_calls, 10)
        self.assertEqual(machine.cpu_calls, 53)
        for index, event in enumerate(machine.events):
            if event == 'C':
                self.assertEqual(machine.events[index - 2:index + 3], ['T', 'W', 'C', 'W', 'T'])
        self.assertEqual(machine.events[:2], ['W', 'M'])
        self.assert_no_calibration_after(machine, 'E')
        self.assertIsNone(machine.saved[0]['final'])
        self.assertNotIn('after_raw_persistence', [x['phase'] for x in machine.saved[0]['collection']['control_reads']])
        self.assertEqual(result['collection']['control_reads'][-1]['phase'], 'after_raw_persistence')

    def test_cap_and_wall_target_same_stamp_can_finish(self):
        machine = FakeMachine()
        result = self.result(machine)
        for row in result['record']['rounds']:
            self.assertEqual(row['stamps'][-1]['wall_before_ns'] - row['stamps'][0]['wall_before_ns'], 500_000_000)
            self.assertEqual(row['stop_reason'], 'wall_target')
        self.assertTrue(result['final']['completed'])

    def test_collected_canonical_record_passes_bound_pure_evaluator(self):
        machine = FakeMachine()
        result = self.result(machine, evaluate=lambda record: evaluate_capability(record,
            expected_origin=FAKE_ORIGIN, expected_source_sha256=SOURCE))
        self.assertEqual(result['decision']['status'], 'clock_capability_passed')
        self.assertTrue(result['final']['completed'])
        self.assertFalse(result['decision']['live_B_passed'])

    def test_cap_includes_initial_stamp_and_does_not_add_one(self):
        machine = FakeMachine()
        result = self.result(machine, sample_cap=10)
        self.assertEqual(machine.cpu_calls, 10)
        self.assertEqual(result['record']['rounds'][0]['stop_reason'], 'sample_cap')
        self.assertEqual(result['record']['rounds'][1:], [None, None])
        self.assertEqual(result['record']['sleeps'], [None] * 10)
        self.assertFalse(result['final']['completed'])

    def test_real_origin_rejects_reduced_cap_before_any_reader(self):
        machine = FakeMachine()
        with self.assertRaises(ValueError):
            machine.collect(origin=REAL_ORIGIN, sample_cap=11)
        self.assertEqual(machine.events, [])
        self.assertEqual(SAMPLE_CAP, 1_000_000)

    def test_foreign_provenance_and_source_rejected_before_reader(self):
        for kwargs in ({'origin': 'synthetic_fixture'}, {'source_sha256': 'invalid'},
                       {'sample_cap': True}, {'sample_cap': SAMPLE_CAP + 1}):
            with self.subTest(kwargs=kwargs):
                machine = FakeMachine()
                with self.assertRaises(ValueError):
                    machine.collect(**kwargs)
                self.assertEqual(machine.events, [])

    def test_persist_completion_before_same_and_after_deadline(self):
        for end, expected in ((DEADLINE_NS - 1, True), (DEADLINE_NS, True), (DEADLINE_NS + 1, False)):
            with self.subTest(end=end):
                machine = FakeMachine()
                machine.persist_end = end
                result = self.result(machine)
                self.assertEqual(result['final']['completed'], expected)
                self.assertEqual(result['final']['raw_persisted_within_deadline'], expected)
                self.assertEqual(result['final']['elapsed_wall_ns'], end)
                self.assertLess(result['record']['elapsed_wall_ns'], result['final']['elapsed_wall_ns'])

    def test_metadata_over_deadline_stops_before_cpu_or_sleep(self):
        machine = FakeMachine()
        machine.metadata_delay = DEADLINE_NS + 1
        result = self.result(machine)
        self.assertEqual(machine.cpu_calls, 0)
        self.assertEqual(machine.sleep_calls, 0)
        self.assertEqual(result['record']['rounds'], [None] * 3)
        self.assertEqual(len(machine.saved), 1)
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')

    def test_slow_evaluator_cannot_be_excluded_from_budget(self):
        machine = FakeMachine()
        machine.evaluation_delay = DEADLINE_NS
        result = self.result(machine)
        self.assertEqual(result['decision']['status'], 'clock_capability_passed')
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')
        self.assertFalse(result['final']['completed'])
        self.assertEqual(len(machine.saved), 1)

    def test_metadata_exception_remains_primary_when_persist_fails(self):
        machine = FakeMachine()
        machine.metadata_error = RuntimeError('metadata unavailable')
        machine.persist_error = OSError('disk unavailable')
        result = self.result(machine)
        self.assertEqual(result['collection']['primary_error']['type'], 'RuntimeError')
        self.assertEqual([x['type'] for x in result['collection']['errors']], ['RuntimeError', 'OSError'])
        self.assertIsNone(result['persistence'])
        self.assertEqual(machine.cpu_calls, 0)

    def test_cancel_stops_without_end_stamp_or_filling_pending_slots(self):
        machine = FakeMachine()
        machine.cancel_at_cpu = 5
        result = self.result(machine)
        self.assertEqual(machine.cpu_calls, 5)
        self.assertEqual(len(result['record']['rounds'][0]['stamps']), 5)
        self.assertEqual(result['record']['rounds'][1:], [None, None])
        self.assertFalse(result['record']['completed'])

    def test_cancel_after_evaluation_cannot_pass(self):
        machine = FakeMachine()
        machine.cancel_after_evaluate = True
        result = self.result(machine)
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')
        self.assertTrue(any(x['reason'] == 'cancelled' for x in result['collection']['stop_reasons']))

    def test_partial_cpu_exception_preserves_first_wall_and_original_error(self):
        machine = FakeMachine()
        machine.cpu_error_at = 1
        result = self.result(machine)
        failure = result['collection']['partial_captures'][0]
        self.assertEqual(failure['error_type'], 'LookupError')
        self.assertIsInstance(failure['raw_values'][0], int)
        self.assertEqual(failure['raw_values'][1:], [None, None])
        self.assertEqual(result['collection']['primary_error']['type'], 'LookupError')
        self.assertEqual(machine.cpu_calls, 1)
        self.assertEqual(result['record']['rounds'][0]['stamps'], [])

    def test_cpu_error_not_masked_by_final_wall_failure(self):
        machine = FakeMachine()
        machine.cpu_error_at = 1
        original_wall = machine.wall
        def wall():
            if machine.cpu_calls:
                raise OSError('subsequent control failure')
            return original_wall()
        result = self.result(machine, wall_clock=wall)
        self.assertEqual(result['collection']['primary_error']['type'], 'LookupError')
        self.assertIsNone(result['final']['ended_wall_ns'])
        self.assertIsNone(result['final']['elapsed_wall_ns'])
        self.assertFalse(result['final']['completed'])

    def test_partial_second_wall_failure_retains_cpu(self):
        machine = FakeMachine()
        original_wall = machine.wall
        def wall():
            if machine.in_capture and machine.capture_reads == 1:
                raise OSError('second wall failed')
            return original_wall()
        result = self.result(machine, wall_clock=wall)
        raw = result['collection']['partial_captures'][0]['raw_values']
        self.assertIsInstance(raw[0], int)
        self.assertIsInstance(raw[1], int)
        self.assertIsNone(raw[2])
        self.assertEqual(machine.cpu_calls, 1)

    def test_thread_change_is_rejected_and_keeps_failed_raw(self):
        machine = FakeMachine()
        machine.thread_change_at = 1
        result = self.result(machine)
        self.assertEqual(result['final']['status'], 'rejected_structure')
        self.assertTrue(all(value is not None for value in result['collection']['partial_captures'][0]['raw_values']))
        self.assertEqual(machine.cpu_calls, 1)

    def test_cpu_backwards_preserves_partial_raw_and_stops(self):
        machine = FakeMachine()
        original_cpu = machine.cpu
        def cpu():
            value = original_cpu()
            return value if machine.cpu_calls == 1 else 1
        result = self.result(machine, cpu_clock=cpu)
        self.assertEqual(machine.cpu_calls, 2)
        self.assertEqual(result['final']['status'], 'rejected_structure')
        self.assertEqual(result['collection']['partial_captures'][0]['raw_values'][1], 1)
        self.assertEqual(len(result['record']['rounds'][0]['stamps']), 1)

    def test_boolean_initial_control_is_rejected_before_metadata(self):
        machine = FakeMachine()
        result = self.result(machine, wall_clock=lambda: True)
        self.assertEqual(machine.cpu_calls, 0)
        self.assertNotIn('M', machine.events)
        self.assertEqual(result['final']['status'], 'rejected_structure')
        self.assertIs(result['collection']['control_reads'][0]['wall_ns'], True)

    def test_capture_wall_before_must_follow_the_previous_control(self):
        machine = FakeMachine()
        original_wall = machine.wall
        def wall():
            if not machine.in_capture and machine.cpu_calls == 1:
                machine.now += 1_000
            if machine.in_capture and machine.capture_reads == 0 and machine.cpu_calls:
                machine.capture_reads += 1
                return machine.now - 1
            return original_wall()
        result = self.result(machine, wall_clock=wall)
        self.assertEqual(machine.cpu_calls, 2)
        self.assertEqual(result['final']['status'], 'rejected_structure')
        self.assertEqual(len(result['record']['rounds'][0]['stamps']), 2)
        self.assertEqual(result['collection']['partial_captures'], [])
        self.assertTrue(any(x['reason'] == 'wall_moved_backwards' for x in result['collection']['stop_reasons']))

    def test_control_wall_backwards_stops_before_another_capture(self):
        machine = FakeMachine()
        original_wall = machine.wall
        def wall():
            if not machine.in_capture and machine.cpu_calls == 1:
                return machine.now - 1
            return original_wall()
        result = self.result(machine, wall_clock=wall)
        self.assertEqual(result['final']['status'], 'rejected_structure')
        self.assertEqual(machine.cpu_calls, 1)
        self.assertTrue(any(x['reason'] == 'wall_moved_backwards' for x in result['collection']['stop_reasons']))

    def test_later_bad_control_rejects_structure_without_hiding_primary_error(self):
        machine = FakeMachine()
        machine.metadata_error = RuntimeError('original metadata failure')
        original_wall = machine.wall
        def wall():
            if 'P' in machine.events:
                return False
            return original_wall()
        result = self.result(machine, wall_clock=wall)
        self.assertEqual(result['final']['status'], 'rejected_structure')
        self.assertEqual(result['collection']['primary_error']['type'], 'RuntimeError')
        self.assertIsNone(result['final']['ended_wall_ns'])

    def test_bracket_max_is_immediate_but_failed_stamp_is_retained(self):
        machine = FakeMachine()
        machine.bracket = 100_001
        result = self.result(machine)
        self.assertEqual(machine.cpu_calls, 1)
        self.assertEqual(len(result['record']['rounds'][0]['stamps']), 1)
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')

    def test_declared_resolution_stops_before_dense(self):
        machine = FakeMachine()
        machine.meta['clocks']['cpu']['resolution_seconds'] = '0.000100001'
        result = self.result(machine)
        self.assertEqual(result['final']['status'], 'cpu_resolution_insufficient')
        self.assertEqual(machine.cpu_calls, 0)

    def test_complete_round_positive_p95_stops_subsequent_rounds(self):
        machine = FakeMachine()
        machine.cpu_step = 100_001
        result = self.result(machine)
        self.assertEqual(machine.cpu_calls, 11)
        self.assertTrue(result['record']['rounds'][0]['completed'])
        self.assertEqual(result['record']['rounds'][1:], [None, None])
        self.assertEqual(result['final']['status'], 'cpu_resolution_insufficient')

    def test_partial_round_large_p95_is_not_early_insufficient(self):
        machine = FakeMachine()
        machine.cpu_step = 100_001
        result = self.result(machine, sample_cap=10)
        self.assertEqual(machine.cpu_calls, 10)
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')

    def test_too_few_positive_increments_does_not_borrow_next_round(self):
        machine = FakeMachine()
        machine.cpu_step = 0
        result = self.result(machine)
        self.assertEqual(machine.cpu_calls, 11)
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')
        self.assertEqual(result['record']['rounds'][1:], [None, None])

    def test_unavailable_clock_is_unconfirmed_without_cpu_reads(self):
        machine = FakeMachine()
        machine.meta['clocks']['cpu']['available'] = False
        machine.meta['clocks']['cpu']['resolution_seconds'] = None
        result = self.result(machine)
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')
        self.assertEqual(machine.cpu_calls, 0)

    def test_metadata_source_mismatch_is_rejected(self):
        machine = FakeMachine()
        machine.meta['environment']['source_sha256'] = 'c' * 64
        result = self.result(machine)
        self.assertEqual(result['final']['status'], 'rejected_structure')
        self.assertEqual(machine.cpu_calls, 0)

    def test_sleep_error_does_not_take_an_end_stamp(self):
        machine = FakeMachine()
        machine.sleep_error = RuntimeError('sleep interrupted')
        result = self.result(machine)
        self.assertEqual(machine.cpu_calls, 34)
        self.assertEqual(machine.sleep_calls, 1)
        self.assertIsNone(result['record']['sleeps'][0]['end'])
        self.assertEqual(result['record']['sleeps'][1:], [None] * 9)
        self.assertEqual(result['collection']['primary_error']['type'], 'RuntimeError')

    def test_short_sleep_preserves_both_endpoints_and_stops(self):
        machine = FakeMachine()
        original_sleep = machine.sleep
        def short_sleep(seconds):
            original_sleep(seconds)
            machine.capture_step = 1
            machine.now -= 50_000_000
        result = self.result(machine, sleep=short_sleep)
        self.assertEqual(machine.sleep_calls, 1)
        self.assertEqual(machine.cpu_calls, 35)
        self.assertTrue(result['record']['sleeps'][0]['completed'])
        self.assertEqual(result['record']['sleeps'][1:], [None] * 9)
        self.assertTrue(any(x['reason'] == 'sleep_wall_too_short' for x in result['collection']['stop_reasons']))

    def test_incomplete_persistence_never_passes(self):
        machine = FakeMachine()
        result = self.result(machine, persist=lambda snapshot: None)
        self.assertEqual(result['final']['status'], 'clock_capability_unconfirmed')
        self.assertFalse(result['final']['raw_persisted_within_deadline'])
        self.assertIsNone(result['persistence'])

    def test_evaluator_exception_is_preserved_and_raw_is_still_saved(self):
        machine = FakeMachine()
        def evaluate(record):
            raise ArithmeticError('analysis failed')
        result = self.result(machine, evaluate=evaluate)
        self.assertEqual(result['collection']['primary_error']['type'], 'ArithmeticError')
        self.assertEqual(len(machine.saved), 1)
        self.assertFalse(result['final']['completed'])


if __name__ == '__main__':
    unittest.main()
