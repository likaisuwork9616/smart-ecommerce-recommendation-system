"""Isolated V83 cases driven only by fake clocks, locks, and event records."""

from collections import deque
from dataclasses import replace
import unittest

from scripts import retailrocket_session_knn_lock_owner_v83 as owners
from scripts import retailrocket_session_knn_lock_trace_v83 as trace_tools


class _ScriptClock:
    def __init__(self, *, monotonic, utc=()):
        self.monotonic_values = deque(monotonic)
        self.utc_values = deque(utc)
        self.monotonic_calls = []
        self.utc_calls = []
        self.sleep_requests = []
        self.event_tick_ns = 0

    def monotonic(self):
        if not self.monotonic_values:
            raise AssertionError('Unexpected monotonic predicate read')
        value = self.monotonic_values.popleft()
        self.monotonic_calls.append(value)
        return value

    def utc(self):
        if not self.utc_values:
            raise AssertionError('UTC predicate must not be evaluated here')
        value = self.utc_values.popleft()
        self.utc_calls.append(value)
        return value

    def sleep(self, seconds):
        self.sleep_requests.append(seconds)

    def observe_ns(self):
        self.event_tick_ns += 10
        return self.event_tick_ns


class _ScriptLock:
    def __init__(self, outcomes, *, release_error=None):
        self.outcomes = deque(outcomes)
        self.operations = []
        self.held = False
        self.release_error = release_error

    def acquire(self):
        self.operations.append('acquire')
        if self.held or not self.outcomes:
            raise AssertionError('Unexpected lock acquire')
        outcome = self.outcomes.popleft()
        if outcome == 'busy':
            error = PermissionError(13, 'scheduled fake rejection')
            raise trace_tools.LockBusy('scheduled fake rejection') from error
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome != 'acquired':
            raise AssertionError('Unknown fake lock outcome')
        self.held = True

    def release(self):
        self.operations.append('release')
        if not self.held:
            raise AssertionError('Release without a grant')
        if self.release_error is not None:
            raise self.release_error
        self.held = False


class FakeRetryTests(unittest.TestCase):
    def run_check(self, clock, backend, trace, steps=()):
        return trace_tools.run_fake_check(
            clock=clock,
            backend=backend,
            trace=trace,
            check_id='fake-check-1',
            request_deadline_utc=500.0,
            steps=steps,
        )

    def test_exact_second_short_circuits_poison_utc(self):
        clock = _ScriptClock(monotonic=(10, 11))
        backend = _ScriptLock(('busy',))
        trace = trace_tools.EventBuffer(capacity=32)

        with self.assertRaises(trace_tools.LockStopped) as caught:
            self.run_check(clock, backend, trace)

        decision = caught.exception.decision
        self.assertEqual(decision['reason'], 'lock_retry_monotonic_limit')
        self.assertEqual((decision['loop_start_mono'], decision['decision_mono'],
                          decision['elapsed_seconds']), (10, 11, 1))
        self.assertEqual(decision['request_deadline_utc'], 500.0)
        self.assertIs(decision['utc_evaluated'], False)
        self.assertIsNone(decision['utc_sample'])
        self.assertIsNone(decision['utc_predicate'])
        self.assertEqual(clock.utc_calls, [])
        self.assertEqual(clock.sleep_requests, [])
        self.assertEqual(backend.operations, ['acquire'])
        events = trace.snapshot()['events']
        self.assertEqual([event['event'] for event in events],
                         ['lock_loop_begin', 'lock_attempt_begin',
                          'lock_attempt_end', 'retry_decision'])
        self.assertEqual(events[-1]['decision'], decision)
        self.assertEqual(events[-2]['attempt_index'], events[-1]['attempt_index'])

    def test_original_utc_deadline_at_equality_before_one_second(self):
        clock = _ScriptClock(monotonic=(20, 20.25), utc=(500.0,))
        backend = _ScriptLock(('busy',))
        trace = trace_tools.EventBuffer(capacity=32)

        with self.assertRaises(trace_tools.LockStopped) as caught:
            self.run_check(clock, backend, trace)

        decision = caught.exception.decision
        self.assertEqual(decision['reason'], 'lock_retry_request_utc_deadline')
        self.assertEqual(decision['elapsed_seconds'], 0.25)
        self.assertIs(decision['utc_evaluated'], True)
        self.assertEqual(decision['utc_sample'], 500.0)
        self.assertIs(decision['utc_predicate'], True)
        self.assertEqual(clock.utc_calls, [500.0])
        self.assertEqual(clock.sleep_requests, [])
        self.assertEqual(backend.operations, ['acquire'])

    def test_retries_keep_the_original_monotonic_origin(self):
        clock = _ScriptClock(monotonic=(10, 10.25, 10.75, 11), utc=(498.0, 499.0))
        backend = _ScriptLock(('busy', 'busy', 'busy'))
        trace = trace_tools.EventBuffer(capacity=32)

        with self.assertRaises(trace_tools.LockStopped):
            self.run_check(clock, backend, trace)

        events = [e for e in trace.snapshot()['events'] if e['event'] == 'retry_decision']
        decisions = [e['decision'] for e in events]
        self.assertEqual([d['reason'] for d in decisions],
                         ['retry', 'retry', 'lock_retry_monotonic_limit'])
        self.assertEqual([d['loop_start_mono'] for d in decisions], [10, 10, 10])
        self.assertEqual([d['elapsed_seconds'] for d in decisions], [0.25, 0.75, 1])
        self.assertEqual([d['utc_evaluated'] for d in decisions], [True, True, False])
        self.assertEqual([d['utc_predicate'] for d in decisions], [False, False, None])
        self.assertEqual([d['requested_sleep_seconds'] for d in decisions[:2]],
                         [0.005, 0.005])
        indexes = [e['attempt_index'] for e in events]
        self.assertEqual(indexes, list(range(indexes[0], indexes[0] + 3)))
        self.assertEqual(clock.utc_calls, [498.0, 499.0])
        self.assertEqual(clock.sleep_requests, [0.005, 0.005])
        self.assertEqual(backend.operations, ['acquire', 'acquire', 'acquire'])

    def test_retry_then_acquire_preserves_write_and_unlock_order(self):
        clock = _ScriptClock(monotonic=(10, 10.25), utc=(499.0,))
        backend = _ScriptLock(('busy', 'acquired'))
        trace = trace_tools.EventBuffer(capacity=64)
        operations = ('write', 'flush', 'fsync', 'close_inner',
                      'replace_inner_to_outer', 'replace_outer_to_published')

        def run_step(name):
            self.assertTrue(backend.held)
            backend.operations.append(name)

        self.run_check(clock, backend, trace,
                       [(name, lambda name=name: run_step(name)) for name in operations])

        receipt = trace.snapshot()
        self.assertTrue(receipt['complete'])
        self.assertEqual(receipt['dropped_events'], 0)
        events = receipt['events']
        self.assertEqual(receipt['seen_events'], len(events))
        self.assertEqual({event['check_id'] for event in events}, {'fake-check-1'})
        self.assertEqual([event['result'] for event in events
                          if event['event'] == 'lock_attempt_end'], ['rejected', 'acquired'])
        self.assertEqual([event['decision']['reason'] for event in events
                          if event['event'] == 'retry_decision'], ['retry'])
        writes = [e for e in events if e['event'].startswith('state_write_')]
        self.assertEqual([(e['event'], e['operation']) for e in writes],
                         [(event, name) for name in operations
                          for event in ('state_write_begin', 'state_write_end')])
        unlocks = [e for e in events if e['event'].startswith('unlock_')]
        self.assertEqual([e['event'] for e in unlocks], ['unlock_begin', 'unlock_end'])
        hold_ids = {e['hold_id'] for e in [*writes, *unlocks]}
        self.assertEqual(len(hold_ids), 1)
        self.assertNotIn(None, hold_ids)
        self.assertEqual(clock.monotonic_calls, [10, 10.25])
        self.assertEqual(clock.utc_calls, [499.0])
        self.assertEqual(clock.sleep_requests, [0.005])
        self.assertEqual(backend.operations, ['acquire', 'acquire', *operations, 'release'])
        self.assertFalse(backend.held)

    def test_acquire_success_does_not_evaluate_retry_predicates(self):
        clock = _ScriptClock(monotonic=(10,))
        backend = _ScriptLock(('acquired',))
        trace = trace_tools.EventBuffer(capacity=32)

        self.run_check(clock, backend, trace)

        self.assertEqual(clock.monotonic_calls, [10])
        self.assertEqual(clock.utc_calls, [])
        self.assertEqual(clock.sleep_requests, [])
        self.assertEqual(backend.operations, ['acquire', 'release'])
        self.assertNotIn('retry_decision', [e['event'] for e in trace.snapshot()['events']])

    def test_unrelated_acquire_error_does_not_retry_or_release(self):
        clock = _ScriptClock(monotonic=(10,))
        error = OSError(5, 'scripted non-retry acquisition error')
        backend = _ScriptLock((error,))
        trace = trace_tools.EventBuffer(capacity=32)

        with self.assertRaises(OSError) as caught:
            self.run_check(clock, backend, trace)

        self.assertIs(caught.exception, error)
        events = trace.snapshot()['events']
        self.assertEqual([e['result'] for e in events if e['event'] == 'lock_attempt_end'],
                         ['failed'])
        self.assertEqual(backend.operations, ['acquire'])
        self.assertEqual(clock.monotonic_calls, [10])
        self.assertEqual(clock.utc_calls, [])

    def test_failed_write_is_recorded_before_unlock_and_skips_later_write(self):
        clock = _ScriptClock(monotonic=(10,))
        backend = _ScriptLock(('acquired',))
        trace = trace_tools.EventBuffer(capacity=32)
        error = OSError(5, 'scripted fsync failure')

        def fail_fsync():
            self.assertTrue(backend.held)
            backend.operations.append('fsync')
            raise error

        def unexpected_replace():
            self.fail('A failed fsync must not reach replace')

        with self.assertRaises(OSError) as caught:
            self.run_check(clock, backend, trace,
                           [('fsync', fail_fsync), ('replace_inner_to_outer', unexpected_replace)])

        self.assertIs(caught.exception, error)
        events = trace.snapshot()['events']
        self.assertEqual([e['event'] for e in events][-4:],
                         ['state_write_begin', 'state_write_end', 'unlock_begin', 'unlock_end'])
        self.assertEqual(events[-3]['operation'], 'fsync')
        self.assertEqual(events[-3]['result'], 'failed')
        self.assertEqual(events[-3]['hold_id'], events[-1]['hold_id'])
        self.assertEqual(backend.operations, ['acquire', 'fsync', 'release'])
        self.assertFalse(backend.held)

    def test_failed_unlock_is_not_saved_as_success(self):
        clock = _ScriptClock(monotonic=(10,))
        error = OSError(5, 'scripted release failure')
        backend = _ScriptLock(('acquired',), release_error=error)
        trace = trace_tools.EventBuffer(capacity=32)

        with self.assertRaises(OSError) as caught:
            self.run_check(clock, backend, trace)

        self.assertIs(caught.exception, error)
        events = trace.snapshot()['events']
        self.assertEqual([e['event'] for e in events][-2:], ['unlock_begin', 'unlock_end'])
        self.assertEqual(events[-2]['hold_id'], events[-1]['hold_id'])
        self.assertEqual(events[-1]['result'], 'failed')
        self.assertEqual(events[-1]['error']['errno'], 5)
        self.assertEqual(backend.operations, ['acquire', 'release'])

    def test_overflow_preserves_prefix_and_marks_missing_evidence(self):
        clock = _ScriptClock(monotonic=(10,))
        backend = _ScriptLock(('acquired',))
        trace = trace_tools.EventBuffer(capacity=2)

        self.run_check(clock, backend, trace)

        receipt = trace.snapshot()
        self.assertIs(receipt['complete'], False)
        self.assertEqual(len(receipt['events']), 2)
        self.assertGreater(receipt['dropped_events'], 0)
        self.assertEqual(receipt['seen_events'], len(receipt['events']) + receipt['dropped_events'])
        self.assertEqual([e['event'] for e in receipt['events']],
                         ['lock_loop_begin', 'lock_attempt_begin'])
        self.assertEqual(backend.operations, ['acquire', 'release'])


class FakeOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.scope = owners.Scope('a' * 64, 'fake-run', 'guard-object',
                                  'generation-1', 'fake-shared-clock', 'fake-boot')
        self.pipeline = owners.Actor('pipeline', 101, 'pipeline-instance', 'fake-boot')
        self.publisher = owners.Actor('publisher', 102, 'publisher-instance', 'fake-boot')
        self.outer = owners.Actor('outer', 103, 'outer-instance', 'fake-boot')
        self.publisher_hold = owners.Hold(self.publisher, self.scope, 'hold-publisher',
                                         owners.Bounds(4, 10), owners.Bounds(50, 54),
                                         continuous=True)
        self.attempt = owners.Attempt(self.pipeline, self.scope, 'fake-check-1', 1,
                                      owners.Bounds(20, 21), owners.Bounds(29, 30))

    def judge(self, attempt=None, holds=None, *, coverage=True, common_clock=True):
        return owners.classify_owner(
            self.attempt if attempt is None else attempt,
            [self.publisher_hold] if holds is None else holds,
            coverage_complete=coverage,
            common_clock_verified=common_clock,
        )

    def test_unique_strict_containment_confirms_holder_not_conflict(self):
        judged = self.judge()
        self.assertEqual(judged['status'], 'confirmed_holder_during_attempt')
        self.assertEqual(judged['owner']['role'], 'publisher')
        self.assertEqual(judged['owner']['pid'], 102)
        self.assertEqual(judged['owner']['creation_id'], 'publisher-instance')
        self.assertEqual(judged['owner']['boot_id'], 'fake-boot')
        self.assertEqual(judged['hold_id'], 'hold-publisher')
        self.assertEqual(judged['conflict'], 'unknown')

    def test_handoff_is_classified_per_retry(self):
        outer_hold = owners.Hold(self.outer, self.scope, 'hold-outer',
                                owners.Bounds(57, 60), owners.Bounds(110, 113),
                                continuous=True)
        retry = replace(self.attempt, attempt_index=2, begin=owners.Bounds(70, 71),
                        end=owners.Bounds(79, 80))
        comparisons = [self.judge(attempt, [outer_hold, self.publisher_hold])
                       for attempt in (self.attempt, retry)]
        self.assertEqual([answer['status'] for answer in comparisons],
                         ['confirmed_holder_during_attempt', 'confirmed_holder_during_attempt'])
        self.assertEqual([answer['owner']['role'] for answer in comparisons],
                         ['publisher', 'outer'])
        self.assertEqual([answer['hold_id'] for answer in comparisons],
                         ['hold-publisher', 'hold-outer'])

    def test_boundaries_crossing_and_error_expansion_stay_unknown(self):
        for name, begin, end in (
            ('equal_acquire_upper', owners.Bounds(10, 11), owners.Bounds(29, 30)),
            ('equal_release_lower', owners.Bounds(20, 21), owners.Bounds(49, 50)),
            ('cross_release', owners.Bounds(20, 21), owners.Bounds(55, 56)),
            ('begin_uncertainty_crosses_lower', owners.Bounds(9, 11), owners.Bounds(29, 30)),
        ):
            with self.subTest(name=name):
                result = self.judge(replace(self.attempt, begin=begin, end=end))
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['owner'])

    def test_missing_failed_call_or_unproved_hold_keeps_owner_unknown(self):
        for attempt in (replace(self.attempt, begin=None), replace(self.attempt, end=None)):
            with self.subTest(attempt=attempt):
                self.assertEqual(self.judge(attempt)['status'], 'unknown')
        for hold in (replace(self.publisher_hold, release_begin=None),
                     replace(self.publisher_hold, continuous=False)):
            with self.subTest(hold=hold):
                self.assertEqual(self.judge(holds=[hold])['status'], 'unknown')

    def test_interrupted_hold_is_bounded_by_the_last_proven_held_sample(self):
        interrupted = replace(self.publisher_hold, release_begin=None,
                              last_proven_held=owners.Bounds(40, 42))
        after_sample = replace(self.attempt, begin=owners.Bounds(38, 39),
                               end=owners.Bounds(44, 45))

        confirmed = self.judge(holds=[interrupted])
        unknown = self.judge(after_sample, [interrupted])

        self.assertEqual(confirmed['status'], 'confirmed_holder_during_attempt')
        self.assertEqual(confirmed['hold_id'], 'hold-publisher')
        self.assertEqual(unknown['status'], 'unknown')
        self.assertIsNone(unknown['owner'])

    def test_incomplete_coverage_or_unverified_clock_fails_closed(self):
        for coverage, common_clock in ((False, True), (True, False)):
            with self.subTest(coverage=coverage, common_clock=common_clock):
                result = self.judge(coverage=coverage, common_clock=common_clock)
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['owner'])

    def test_scope_and_launcher_identity_cannot_fill_the_role_record(self):
        wrong_scope = (
            replace(self.scope, clock_domain='unrelated-clock'),
            replace(self.scope, generation='replaced-object'),
            replace(self.scope, file_id='another-guard'),
        )
        holds = [replace(self.publisher_hold, scope=scope) for scope in wrong_scope]
        holds.append(replace(self.publisher_hold, actor=replace(self.publisher, kind='launcher')))
        for hold in holds:
            with self.subTest(hold=hold):
                result = self.judge(holds=[hold])
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['owner'])

    def test_overlapping_guaranteed_exclusive_holds_are_inconsistent(self):
        outer_hold = owners.Hold(self.outer, self.scope, 'hold-outer',
                                owners.Bounds(12, 15), owners.Bounds(45, 46),
                                continuous=True)

        result = self.judge(holds=[self.publisher_hold, outer_hold])

        self.assertEqual(result['status'], 'inconsistent')
        self.assertIsNone(result['owner'])

    def test_nonconflict_reason_does_not_change_historical_holder(self):
        judged = self.judge(replace(self.attempt, conflict='confirmed_nonconflict'))
        self.assertEqual(judged['status'], 'confirmed_holder_during_attempt')
        self.assertEqual(judged['owner']['role'], 'publisher')
        self.assertEqual(judged['conflict'], 'confirmed_nonconflict')
