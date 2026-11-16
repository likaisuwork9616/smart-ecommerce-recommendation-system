"""Literal synthetic fresh48 entry/ledger acceptance, using injected clocks only.

The actual V39 policy -> V27 runner -> V22 entry and frozen pair/SQL code execute.
The supplied SyntheticPool deliberately tests that routing, not the production
typed decoder, source cache authority, a real load window, or clock overhead.
"""
import hashlib
import json
from pathlib import Path
import unittest
from uuid import uuid4

from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_reuse_v27 as reuse
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import retailrocket_session_knn_sql_v4 as sql
from scripts import retailrocket_session_knn_typed_adapter_v39 as typed
from scripts import retailrocket_session_knn_wall_cpu_adapter_v64 as adapter
from scripts.retailrocket_session_knn_wall_cpu_v63 import BoundaryRecorder
from tests import retailrocket_session_knn_wall_cpu_fixture_v64 as artificial


EVIDENCE = []
OUTPUT_FILES = ('measured.json', 'observations.json', 'profile.json', 'proof.json', 'entry.json')
PRIVATE = Path(__file__).resolve().parents[1]/'shop-mysql-runtime/verification'


class SharedFakeClock:
    """All original wall calls advance one common logical timeline by 10,000 ns.

    D's after-read is one ns beyond its before-read, without advancing that
    timeline. O, D and the frozen baseline therefore retain identical legacy
    values, including nested store/observer/entry timers. These are test values.
    """
    def __init__(self):
        self.value = 1_000_000
        self.legacy_calls = self.wall_calls = self.cpu_calls = self.thread_calls = 0

    def ns(self):
        self.value += 10_000
        self.legacy_calls += 1
        return self.value

    def seconds(self):
        return self.ns()/1e9

    def wall(self):
        half = self.wall_calls % 2
        self.wall_calls += 1
        return self.value+1 if half else self.ns()

    def cpu(self):
        self.cpu_calls += 1
        return self.value//2

    def thread(self):
        self.thread_calls += 1
        return 73


class CallerPool(artificial.SyntheticPool):
    """Caller-owned spy with actual load_context/prepare, not a typed decoder."""
    def __init__(self, trace):
        super().__init__(trace)
        self.borrow_arguments = []

    def load(self, paths, config, support, watch, **kwargs):
        self.borrow_arguments.append(dict(paths=paths, config=config, support=support,
                                          watch=watch, **kwargs))
        return super().load(paths, config, support, watch, **kwargs)


def original_factory(observer, pool, namespace, request, *, clock, pair_function):
    """Frozen V27 make_verifier code, independently bound without new adapter."""
    class SetupClock(observed._SetupClock):
        __call__ = artificial.clone(observed._SetupClock.__call__, perf_counter=clock.seconds)

    view = observed._ModuleView(observed, _SetupClock=SetupClock)
    sql_view = observed._ModuleView(pair.sql,
        predict=artificial.clone(sql.predict, perf_counter=clock.seconds))
    pair_view = observed._ModuleView(pair, sql=sql_view)
    factory = artificial.clone(reuse.make_verifier, observed=view, pair=pair_view,
        ORIGINALS=(pair_function, *reuse.ORIGINALS[1:]))
    return factory(observer, pool, namespace, request)


def session_for(mode, fixture, clock):
    if mode == 'baseline':
        return None
    if mode == 'O':
        return adapter.BoundarySession('O', fixture['cohort'], legacy_clock=clock.seconds)
    recorder = BoundaryRecorder(recording_id='synthetic-entry-v64', wall_clock=clock.wall,
        cpu_clock=clock.cpu, thread_identity=clock.thread)
    return adapter.BoundarySession('D', fixture['cohort'], recorder=recorder)


def expected_frames(fixture):
    return b''.join(checkpoint.encoded(dict(ordinal=ordinal, key=row['key'], payload=payload))
        for ordinal, (row, payload) in enumerate(zip(fixture['ordinals'], fixture['expected_payloads'])))


def entry_inputs(fixture):
    frames = expected_frames(fixture)
    probes = [dict(key=row['key'], **identity)
              for row, identity in zip(fixture['ordinals'], fixture['cohort'])]
    reference = dict(records=48, actual_committed_bytes=len(frames),
                     actual_committed_payload_sha256=hashlib.sha256(frames).hexdigest())
    return (fixture['root'], fixture['config'], fixture['binding'], fixture['model'],
            fixture['database'], probes, fixture['ordinals'], reference)


def request_for_entry():
    return dict(deadline_utc=2000.0, budget_seconds=900.0, metadata=dict(
        fingerprint_scheme=typed.s1.SCHEME, typed_reference_policy=typed.POLICY,
        typed_reference_scheme=typed.REFERENCE_SCHEME))


class EntryAcceptanceTests(unittest.TestCase):
    def setUp(self):
        # Retain private artificial SQLite/ledger evidence for later readback.
        self.root = PRIVATE/('v64-entry-fixture-'+uuid4().hex)
        self.root.mkdir(parents=True, exist_ok=False)
        self.fixture = artificial.build_fixture(self.root/'literal')
        self.counter = 0
        self.originals = [pair.verify_selected, sql.predict, reuse.make_verifier,
                          reuse.run_fixed48, reuse.entry._run, typed.run_fixed48,
                          observed._SetupClock.__call__]
        self.original_globals = [(function, dict(function.__globals__)) for function in self.originals]

    def assert_globals_unchanged(self):
        current = [pair.verify_selected, sql.predict, reuse.make_verifier,
                   reuse.run_fixed48, reuse.entry._run, typed.run_fixed48,
                   observed._SetupClock.__call__]
        for original, actual in zip(self.originals, current):
            self.assertIs(original, actual)
        for function, globals_before in self.original_globals:
            self.assertEqual(set(function.__globals__), set(globals_before))
            for name, value in globals_before.items():
                self.assertIs(function.__globals__[name], value, name)

    def new_state(self, mode, *, fail_point=None, fail_at=1, error=None):
        clock = SharedFakeClock()
        trace = artificial.Trace(fail_point, fail_at, error)
        observer = observed.Observation(clock=clock.ns)
        pool = CallerPool(trace)
        session = session_for(mode, self.fixture, clock)
        pair_function = artificial.clone(pair.verify_selected, sqlite3=trace.sqlite)
        return dict(mode=mode, clock=clock, trace=trace, observer=observer, pool=pool,
                    session=session, pair_function=pair_function, stores=[])

    def verifier(self, state, namespace):
        arguments = (state['observer'], state['pool'], namespace, request_for_entry())
        if state['mode'] == 'baseline':
            return original_factory(*arguments, clock=state['clock'], pair_function=state['pair_function'])
        return adapter.make_verifier(*arguments, session=state['session'],
                                     pair_function=state['pair_function'])

    def run_verifier(self, mode, *, fail_point=None, fail_at=1, error=None):
        state = self.new_state(mode, fail_point=fail_point, fail_at=fail_at, error=error)
        self.counter += 1
        store = artificial.create_store(self.fixture, f'verifier-{self.counter}', state['trace'],
                                        flush_clock=state['clock'].seconds)
        state['stores'].append(store)
        verify = self.verifier(state, 'literal-direct-verifier')
        fixture = self.fixture
        try:
            with store.writer():
                artificial.seal_reconstruction(store, fixture)
                state['result'] = verify(fixture['primary'], fixture['paths'], fixture['config'],
                    store, fixture['model'], fixture['database'], fixture['ordinals'],
                    state['trace'].watch, state['trace'].fault)
        except BaseException as caught:
            state['exception'] = caught
        state['payload'] = artificial.physical_payload_bytes(store)
        state['records'] = list(store.iter_records())
        state['summary'] = state['observer'].summary()
        return state

    def run_entry(self, mode):
        state = self.new_state(mode)
        clock, trace = state['clock'], state['trace']
        detailed_class = artificial.detailed_store_class(clock.seconds)

        class StoreFactory:
            def __init__(self, observer):
                state['factory_observer'] = observer

            def create(self, *args, **kwargs):
                store = detailed_class.create(*args, **kwargs, chunk_queries=8,
                    clock=artificial.FakeBudgetClock(), process_api=artificial.FakeProcesses(),
                    fault=trace.fault)
                state['stores'].append(store)
                return store

        entry_function = artificial.clone(reuse.entry._run, perf_counter=clock.seconds)
        if mode == 'baseline':
            def factory(observer, pool, namespace, request):
                return original_factory(observer, pool, namespace, request,
                    clock=clock, pair_function=state['pair_function'])
            entry_view = observed._ModuleView(reuse.entry, _run=entry_function)
            c1_runner = artificial.clone(reuse.run_fixed48, make_verifier=factory,
                                        entry=entry_view, StoreFactory=StoreFactory)
            runner = artificial.clone(typed.run_fixed48,
                                       c1=observed._ModuleView(reuse, run_fixed48=c1_runner))
        else:
            runner = adapter.bind_entry(session=state['session'], pair_function=state['pair_function'],
                                        entry_function=entry_function, store_factory=StoreFactory)
        folder = self.root/mode
        request = request_for_entry()
        state['return'] = runner(folder, request, 'synthetic', 'C', entry_inputs(self.fixture),
            observer=state['observer'], pool=state['pool'], source_root=self.fixture['root'],
            watch=trace.watch)
        state['files'] = {name: (folder/'synthetic'/name).read_bytes() for name in OUTPUT_FILES}
        state['decoded'] = {name: json.loads(value) for name, value in state['files'].items()}
        state['result'] = state['decoded']['measured.json']
        state['payload'] = artificial.physical_payload_bytes(state['stores'][0])
        state['records'] = list(state['stores'][0].iter_records())
        state['summary'] = state['observer'].summary()
        state['request'], state['folder'] = request, folder
        return state

    def assert_clean(self, state):
        self.assertEqual(state['observer'].stack, [])
        self.assertIsNone(state['pool'].active)
        for connection in state['trace'].connections:
            self.assertTrue(connection.closed)
        for store in state['stores']:
            self.assertIsNone(store._guard)
            self.assertIsNone(store._pending)
            self.assertEqual(store._pending_count, 0)
            self.assertEqual(checkpoint.read(store.folder/'writer_owner.json')['state'], 'released')
        self.assert_globals_unchanged()

    def assert_diagnostic(self, state, *, completed):
        mode, clock, session = state['mode'], state['clock'], state['session']
        if mode == 'baseline':
            self.assertIsNone(session)
            self.assertEqual((clock.wall_calls, clock.cpu_calls, clock.thread_calls), (0, 0, 0))
            return
        self.assertIs(session.report['completed'], completed)
        if mode == 'O':
            self.assertIsNone(session.recorder)
            self.assertIsNone(session._markers)
            self.assertIsNone(session._expected)
            self.assertIsNone(session.report['diagnostics'])
            self.assertEqual((clock.wall_calls, clock.cpu_calls, clock.thread_calls), (0, 0, 0))
            return
        diagnostic = session.report['diagnostics']
        boundaries = session.recorder.boundaries
        self.assertEqual(clock.wall_calls, 2*len(boundaries))
        self.assertEqual(clock.cpu_calls, len(boundaries))
        self.assertEqual(clock.thread_calls, 2*len(boundaries))
        for index, boundary in enumerate(boundaries):
            self.assertEqual(boundary.sequence, index)
            self.assertEqual(boundary.boundary_id, f'b{index}')
            self.assertEqual(boundary.wall_after_ns-boundary.wall_before_ns, 1)
            self.assertEqual(boundary.thread_cpu_ns, boundary.wall_before_ns//2)
            self.assertEqual(boundary.thread_id, 73)
        if completed:
            self.assertEqual(len(boundaries), 725)
            layout, analysis = diagnostic['layout'], diagnostic['analysis']
            self.assertEqual((layout['pair_marker_count'], layout['rank_marker_count']), (341, 384))
            self.assertEqual(layout['completed_query_count'], 48)
            self.assertEqual(len(analysis['spans']), 578)
            self.assertEqual(len(analysis['roots']), 50)
            self.assertIsNone(layout['expected_next'])
        else:
            self.assertEqual(diagnostic['layout']['status'], 'incomplete')
            self.assertEqual(diagnostic['layout']['spans'], [])
            self.assertIsNone(diagnostic['analysis'])

    def assert_same(self, baseline, other):
        self.assertEqual(other.get('result'), baseline.get('result'))
        self.assertEqual(other['payload'], baseline['payload'])
        self.assertEqual(other['records'], baseline['records'])
        self.assertEqual(other['trace'].events, baseline['trace'].events)
        self.assertEqual(other['observer'].events, baseline['observer'].events)
        self.assertEqual(other['summary'], baseline['summary'])
        self.assertEqual(other['clock'].legacy_calls, baseline['clock'].legacy_calls)
        self.assertEqual(other['clock'].value, baseline['clock'].value)

    def test_full_v39_v27_v22_entry_outputs_ledger_and_route(self):
        states = [self.run_entry(mode) for mode in ('baseline', 'O', 'D')]
        baseline = states[0]
        expected = expected_frames(self.fixture)
        for state in states:
            with self.subTest(mode=state['mode']):
                self.assert_same(baseline, state)
                self.assertEqual(state['files'], baseline['files'])
                self.assertIsNone(state['return'])
                self.assertEqual(set(state['files']), set(OUTPUT_FILES))
                self.assertEqual(state['payload'], expected)
                self.assertEqual(len(state['records']), 48)
                self.assertEqual([row['payload'] for row in state['records']], self.fixture['expected_payloads'])
                self.assertEqual([row['key'] for row in state['records']],
                                 [row['key'] for row in self.fixture['ordinals']])
                proof = state['decoded']['proof.json']
                self.assertEqual(proof, dict(records=48, actual_committed_bytes=len(expected),
                    actual_committed_payload_sha256=hashlib.sha256(expected).hexdigest(),
                    checkpoint_chain_checked=True))
                self.assertEqual(state['decoded']['profile.json'], [])
                self.assertEqual(state['decoded']['entry.json']['mode'], 'baseline')
                self.assertEqual(len(state['result']['queries']), 48)
                self.assertEqual(state['result']['verified_subset_queries'], 48)
                self.assertEqual(state['result']['committed_prefix_rows'], 0)
                self.assertEqual([row['records'] for row in state['result']['chunk_commits']], [8]*6)
                self.assertEqual(state['pool'].finishes, 1)
                self.assertEqual(state['pool'].invalidations, 0)
                self.assertFalse(state['pool'].poisoned)
                self.assertEqual(len(state['pool'].calls), 1)
                self.assertEqual(len(state['pool'].borrow_arguments), 1)
                borrow = state['pool'].borrow_arguments[0]
                self.assertIs(borrow['config'], self.fixture['config'])
                self.assertIs(borrow['model'], self.fixture['model'])
                self.assertIs(borrow['support'], self.fixture['model']['support'])
                self.assertIs(borrow['store'], state['stores'][0])
                self.assertIs(borrow['observer'], state['observer'])
                self.assertIs(borrow['request'], state['request'])
                self.assertEqual(borrow['namespace'], str(state['folder'].resolve()))
                self.assertIs(state['factory_observer'], state['observer'])
                self.assert_clean(state)
                self.assert_diagnostic(state, completed=True)
        diagnostic = states[-1]['session'].report['diagnostics']
        EVIDENCE.append(dict(case='complete_synthetic_v39_v27_v22_route', modes=['baseline', 'O', 'D'],
            boundary_count=725, span_count=len(diagnostic['analysis']['spans']), root_count=50,
            payload_rows=48, payload_bytes=len(expected), payload_sha256=hashlib.sha256(expected).hexdigest(),
            output_file_count=5, full_output_equal=True, physical_payload_equal=True, trace_equal=True,
            legacy_timing_values_equal=True, caller_pool_preserved=True, original_cpu_calls=0,
            diagnostic_cpu_calls=states[-1]['clock'].cpu_calls,
            typed_decoder_exercised=False, clock_values='injected_synthetic_only'))

    def test_direct_verifier_complete_result_matches_frozen_factory(self):
        states = [self.run_verifier(mode) for mode in ('baseline', 'O', 'D')]
        for state in states:
            with self.subTest(mode=state['mode']):
                self.assertNotIn('exception', state)
                self.assert_same(states[0], state)
                self.assertEqual(state['payload'], expected_frames(self.fixture))
                self.assertEqual([row['payload'] for row in state['records']], self.fixture['expected_payloads'])
                self.assert_clean(state)
                self.assert_diagnostic(state, completed=True)

    def test_failure_prefix_exception_identity_trace_and_cleanup_match(self):
        # Committed prefixes are protocol outcomes, independent of random run IDs.
        cases = (
            ('query_work', 1, 0), ('before_append', 1, 0), ('query_verified', 1, 0),
            ('query_verified', 9, 8), ('after_queries_sealed', 1, 48),
            ('payload_half_written', 1, 0), ('after_payload_fsync', 1, 0),
            ('before_manifest_commit', 1, 0), ('after_manifest_commit', 1, 8),
            ('pool_load', 1, 0), ('pool_prepare', 1, 0), ('pool_finish', 1, 48),
            ('execute_overlap', 1, 0), ('execute_votes', 1, 0),
            ('next_overlap', 2, 0), ('next_votes', 2, 0), ('watch', 1, 0))
        for point, occurrence, committed in cases:
            error = RuntimeError('synthetic exact exception: '+point)
            states = [self.run_verifier(mode, fail_point=point, fail_at=occurrence, error=error)
                      for mode in ('baseline', 'O', 'D')]
            for state in states:
                with self.subTest(point=point, occurrence=occurrence, mode=state['mode']):
                    self.assertIs(state.get('exception'), error)
                    self.assertNotIn('result', state)
                    self.assert_same(states[0], state)
                    self.assertEqual(len(state['records']), committed)
                    self.assertEqual([row['payload'] for row in state['records']],
                                     self.fixture['expected_payloads'][:committed])
                    self.assertTrue(state['pool'].poisoned)
                    self.assertEqual(state['pool'].invalidations, 1)
                    self.assert_clean(state)
                    self.assert_diagnostic(state, completed=False)
                    if state['session'] is not None:
                        self.assertEqual(state['session'].error_type, 'RuntimeError')
                        self.assertIsNone(state['session'].secondary_error_type)
        EVIDENCE.append(dict(case='verifier_fault_cleanup_matrix', cases=len(cases),
            modes=['baseline', 'O', 'D'], exact_exception_identity=True,
            committed_prefix_equal=True, trace_equal=True, cleanup_equal=True,
            incomplete_diagnostic_spans=0, typed_decoder_exercised=False))


if __name__ == '__main__':
    unittest.main()
