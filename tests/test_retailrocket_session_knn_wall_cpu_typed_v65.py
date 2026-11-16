"""Real V39/V46 workers over new literal sources, never real model experiments."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import retailrocket_session_knn_wall_cpu_adapter_v64 as boundary
from tests import retailrocket_session_knn_wall_cpu_fixture_v64 as literal
from tests import test_retailrocket_session_knn_wall_cpu_entry_v64 as old_entry
from tests import retailrocket_session_knn_wall_cpu_typed_fixture_v65 as artificial


EVIDENCE = []
ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT/'shop-mysql-runtime/verification'
MODES = ('baseline', 'O', 'D')


class RealTypedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.root = PRIVATE/('v65-real-typed-' + uuid4().hex)
        self.fixture = artificial.build_fixture(self.root/'literal')
        self.counter = 0
        self.functions = (pair.verify_selected, boundary.sql.predict,
            artificial.reuse.WorkerContext.load, artificial.adapter.WorkerContext.load,
            artificial.adapter._Load.__init__, artificial.adapter._Load.buffer_root,
            artificial.cold.CandidateContext.load, artificial.cold.CandidateLoad.buffer_root,
            artificial.typed._decode, artificial.candidate.decode,
            artificial.typed._build_verified_reference, artificial.typed.compare_with_stats,
            observed._SetupClock.__call__, artificial.reuse.entry._run)
        self.namespaces = [(function, dict(function.__globals__)) for function in self.functions]
        self.profile_before = sys.getprofile()

    def assert_namespaces_unchanged(self):
        for function, before in self.namespaces:
            self.assertEqual(set(function.__globals__), set(before))
            for name, value in before.items():
                self.assertIs(function.__globals__[name], value, name)
        self.assertIs(sys.getprofile(), self.profile_before)

    def run_entry(self, decoder, mode, *, failure=None, error=None, mutate_final=False):
        self.counter += 1
        clock = artificial.FakeClock()
        trace = literal.Trace(fail_point=failure, error=error)
        observer = observed.Observation(clock=clock.ns)
        worker_type, load_type = artificial.worker_class(decoder, clock)
        pool = worker_type(self.fixture['contract'], self.fixture['root'], ROOT)
        expected_type = (artificial.adapter.WorkerContext if decoder == 'V39'
                         else artificial.cold.CandidateContext)
        self.assertIsInstance(pool, expected_type)
        self.assertIs(worker_type.load.__code__, expected_type.load.__code__)
        self.assertIs(load_type.__init__.__code__, artificial.adapter._Load.__init__.__code__)
        expected_buffer = (artificial.adapter._Load.buffer_root if decoder == 'V39'
                           else artificial.cold.CandidateLoad.buffer_root)
        self.assertIs(load_type.buffer_root, expected_buffer)
        # Candidate code uses exactly V47's factory clone with the sole decoder
        # substitution; all clocks are local to the test load instance.
        if decoder == 'V46':
            factory = load_type.buffer_root.__globals__['typed']._build_verified_reference
            self.assertIs(factory.__code__, artificial.typed._build_verified_reference.__code__)
            self.assertIs(factory.__globals__['_decode'], artificial.candidate.decode)
        session = old_entry.session_for(mode, self.fixture, clock)
        state = dict(decoder=decoder, mode=mode, clock=clock, trace=trace, observer=observer,
                     pool=pool, session=session, stores=[])
        store_type = artificial.store_class(clock)

        class Factory:
            def __init__(self, observer):
                self.observer = observer

            def create(self, *args, **kwargs):
                store = store_type.create(*args, **kwargs, observer=self.observer,
                    chunk_queries=8, clock=literal.FakeBudgetClock(),
                    process_api=literal.FakeProcesses(), fault=trace.fault)
                state['stores'].append(store)
                return store

        pair_function = literal.clone(pair.verify_selected, sqlite3=trace.sqlite)
        entry_function = literal.clone(artificial.reuse.entry._run, perf_counter=clock.seconds)
        if mode == 'baseline':
            def factory(observer, context, namespace, request):
                return old_entry.original_factory(observer, context, namespace, request,
                    clock=clock, pair_function=pair_function)
            c1_runner = literal.clone(artificial.reuse.run_fixed48,
                make_verifier=factory, StoreFactory=Factory,
                entry=observed._ModuleView(artificial.reuse.entry, _run=entry_function))
            runner = literal.clone(artificial.adapter.run_fixed48,
                c1=observed._ModuleView(artificial.reuse, run_fixed48=c1_runner))
        else:
            runner = boundary.bind_entry(session=session, pair_function=pair_function,
                entry_function=entry_function, store_factory=Factory)
        folder = self.root/f'{self.counter}-{decoder}-{mode}'
        state['folder'] = folder
        original_model = deepcopy(self.fixture['model'])
        changed = False
        if mutate_final:
            # Entry's native fault argument is untouched. A test-only watch hook
            # mutates unrelated live model content after genuine cold admission;
            # original final_guard must detect it after the scientific queries.
            original_watch = trace.watch
            def watch():
                nonlocal changed
                original_watch()
                if pool.active is not None and not changed:
                    self.fixture['model']['typed_fixture_values'].append('changed during borrow')
                    changed = True
        else:
            watch = trace.watch
        try:
            with artificial.typed_call_counts() as counts:
                state['call_counts'] = counts
                state['return'] = runner(folder, self.fixture['request'], 'synthetic', 'C',
                    old_entry.entry_inputs(self.fixture), observer=observer, pool=pool,
                    source_root=self.fixture['root'], watch=watch)
        except BaseException as caught:
            state['exception'] = caught
        finally:
            if mutate_final:
                self.fixture['model'].clear()
                self.fixture['model'].update(original_model)
        state['mutated'] = changed
        if state['stores']:
            store = state['stores'][0]
            state['payload'] = literal.physical_payload_bytes(store)
            state['records'] = list(store.iter_records())
            self.assertIsInstance(store, artificial.reuse.ReuseStore)
            self.assertTrue(store.created_here)
            self.assertEqual(store.full_checks,
                [dict(force=False, external=False), dict(force=True, external=False)])
        state['files'] = {name: (folder/'synthetic'/name).read_bytes()
            for name in old_entry.OUTPUT_FILES if (folder/'synthetic'/name).exists()}
        state['references'] = pool._typed_references
        state['use'] = deepcopy(pool.calls[0]) if pool.calls else None
        state['summary'] = observer.summary()
        state['profile_restored'] = sys.getprofile() is self.profile_before
        return state

    def assert_cleanup(self, state, *, success):
        pool = state['pool']
        self.assertEqual(state['observer'].stack, [])
        self.assertIsNone(pool.active)
        self.assertIs(pool.poisoned, not success)
        for store in state['stores']:
            self.assertIsNone(store._guard)
            self.assertIsNone(store._pending)
            self.assertEqual(store._pending_count, 0)
            self.assertEqual(literal.checkpoint.read(store.folder/'writer_owner.json')['state'], 'released')
        for connection in state['trace'].connections:
            self.assertTrue(connection.closed)
        if not success:
            self.assertIsNone(pool._typed_references)
            self.assertIsNone(pool._typed_authority)
            self.assertIsNone(pool.expected_config)
            self.assertIsNone(pool.expected_model)
        self.assertTrue(state['profile_restored'])
        self.assert_namespaces_unchanged()

    def assert_clock_shape(self, state, *, completed):
        session, clock = state['session'], state['clock']
        if state['mode'] == 'baseline':
            self.assertIsNone(session)
        else:
            self.assertIs(session.report['completed'], completed)
        if state['mode'] != 'D':
            self.assertEqual((clock.wall_calls, clock.cpu_calls, clock.thread_calls), (0, 0, 0))
            if session is not None:
                self.assertIsNone(session.report['diagnostics'])
            return
        diagnostic = session.report['diagnostics']
        count = len(session.recorder.boundaries)
        self.assertEqual((clock.wall_calls, clock.cpu_calls, clock.thread_calls),
                         (count*2, count, count*2))
        if completed:
            self.assertEqual(count, 725)
            self.assertEqual(len(diagnostic['analysis']['spans']), 578)
            self.assertEqual(len(diagnostic['analysis']['roots']), 50)
        else:
            self.assertEqual(diagnostic['layout']['status'], 'incomplete')
            self.assertIsNone(diagnostic['analysis'])

    def assert_real_references(self, state):
        pool, refs, use = state['pool'], state['references'], state['use']
        self.assertEqual(len(pool.calls), 1)
        self.assertTrue(use['cold'])
        self.assertFalse(use['hit'])
        artificial.adapter.strip_use(use)
        proof = use['typed_reference']
        self.assertEqual(proof['build']['roots'], 2)
        self.assertTrue(proof['build']['completed'])
        self.assertEqual([row['root'] for row in proof['checks']], ['config', 'model'])
        self.assertTrue(all(row['completed'] and row['equal'] for row in proof['checks']))
        self.assertEqual(state['clock'].passive_calls, 6)
        expected_counts = dict(V39_decode=0, V46_decode=0, verified_reference=2, late_compare=2)
        expected_counts[state['decoder']+'_decode'] = 2
        self.assertEqual(state['call_counts'], expected_counts)
        for root, reference in zip(('config', 'model'), refs):
            self.assertIs(type(reference), artificial.typed.Reference)
            source = artificial.typed.ORIGINAL_CANONICAL(self.fixture[root])
            self.assertEqual(reference.source_bytes, source)
            self.assertEqual(reference.source_length, len(source))
            self.assertEqual(reference.source_sha256, hashlib.sha256(source).hexdigest())
            self.assertEqual(proof['authority']['raw_sources'][root], self.fixture['contract']['dependencies'][root])
            self.assertEqual(proof['authority']['canonical'][root], reference.source_descriptor)
            self.assertEqual(proof['authority']['reference_statistics'][root], reference.statistics())
            self.assertEqual(reference.provenance['authority'], 'trusted_sealed_adapter_success_attestation')
            self.assertEqual(reference.provenance['source_role'], root)
        self.assertEqual(use, next(event['metadata'] for event in state['observer'].events
                                  if event['phase'] == 'cache.use'))

    def publish_artifacts(self, state):
        folder = state['folder']/'synthetic'
        paths = []
        for name, value in (('typed_use.json', state['use']), ('call_counts.json', state['call_counts']),
                            ('events.json', state['observer'].events),
                            ('boundary_report.json', None if state['session'] is None else state['session'].report)):
            path = folder/name
            path.write_bytes(literal.checkpoint.encoded(value))
        paths.extend(sorted(path for path in folder.rglob('*') if path.is_file()))
        return [artificial.describe(path) for path in paths]

    def test_real_workers_full_entry_outputs_ledger_references_and_decoders_match(self):
        states = [self.run_entry(decoder, mode) for decoder in ('V39', 'V46') for mode in MODES]
        expected = old_entry.expected_frames(self.fixture)
        first = states[0]
        artifacts = []
        for state in states:
            with self.subTest(decoder=state['decoder'], mode=state['mode']):
                self.assertNotIn('exception', state)
                self.assertIsNone(state['return'])
                self.assertEqual(set(state['files']), set(old_entry.OUTPUT_FILES))
                self.assertEqual(state['files'], first['files'])
                self.assertEqual(state['payload'], expected)
                self.assertEqual(len(state['records']), 48)
                self.assertEqual([row['payload'] for row in state['records']], self.fixture['expected_payloads'])
                self.assertEqual(state['trace'].events, first['trace'].events)
                self.assertEqual(state['observer'].events, first['observer'].events)
                self.assertEqual(state['summary'], first['summary'])
                self.assertEqual(state['clock'].value, first['clock'].value)
                self.assertEqual(state['clock'].legacy_calls, first['clock'].legacy_calls)
                self.assert_real_references(state)
                self.assert_cleanup(state, success=True)
                self.assert_clock_shape(state, completed=True)
                for reference, baseline in zip(state['references'], first['references']):
                    # Runtime provenance may legitimately include different outer
                    # wrapper frame depth. Compare full trees and exact sources.
                    self.assertEqual(reference.root, baseline.root)
                    self.assertEqual(reference.source_bytes, baseline.source_bytes)
                    self.assertEqual(reference.statistics(), baseline.statistics())
                artifacts.extend(self.publish_artifacts(state))
                state['pool'].close()
                self.assertIsNone(state['pool']._typed_references)
        source_artifacts = [artificial.describe(self.fixture['root']/row['path'])
                            for row in self.fixture['binding']['sources']]
        EVIDENCE.append(dict(case='real_typed_workers_full_entry', entries=len(states),
            decoders=['V39', 'V46'], modes=list(MODES), fresh_context_per_entry=True,
            full_output_file_count=5, full_outputs_equal=True, complete_payload_rows=48,
            physical_payload_bytes=len(expected), physical_payload_sha256=hashlib.sha256(expected).hexdigest(),
            complete_workloads_equal=True, sql_lazy_watch_fault_trace_equal=True,
            roots_per_entry=2, late_checks_per_entry=2, observed_decoder_calls_per_entry=2,
            canonical_sources_and_reference_trees_equal=True, typed_decoder_exercised=True,
            unicode_escape_metadata_in_both_roots=True,
            diagnostic_boundaries=725, diagnostic_spans=578, diagnostic_roots=50,
            fake_clock_only=True, profiler='test_only_call_count_not_timing',
            artifacts=[*source_artifacts, *artifacts]))

    def test_real_source_receipt_mismatch_rejects_before_reference_build(self):
        self.fixture['model']['typed_fixture_values'].append('not in sealed raw source')
        for decoder in ('V39', 'V46'):
            for mode in MODES:
                with self.subTest(decoder=decoder, mode=mode):
                    state = self.run_entry(decoder, mode)
                    self.assertIsInstance(state.get('exception'), ValueError)
                    self.assertIn('Live configuration/model differs', str(state['exception']))
                    self.assertEqual(state['call_counts'],
                        dict(V39_decode=0, V46_decode=0, verified_reference=0, late_compare=0))
                    self.assertEqual(state['records'], [])
                    self.assertEqual(state['files'], {})
                    self.assert_cleanup(state, success=False)
                    self.assert_clock_shape(state, completed=False)
        EVIDENCE.append(dict(case='real_typed_source_receipt_mismatch', entries=6,
            original_source_authority_rejection=True, reference_builds=0,
            decoder_calls=0, committed_rows=0, completed_entry_files=0))

    def test_checkpoint_fault_preserves_exception_and_invalidates_real_typed_authority(self):
        error = RuntimeError('synthetic V65 partial-payload fault')
        baseline_trace = None
        for decoder in ('V39', 'V46'):
            for mode in MODES:
                with self.subTest(decoder=decoder, mode=mode):
                    state = self.run_entry(decoder, mode, failure='payload_half_written', error=error)
                    self.assertIs(state.get('exception'), error)
                    self.assertEqual(state['records'], [])
                    self.assertEqual(state['files'], {})
                    self.assertEqual(state['call_counts']['verified_reference'], 2)
                    self.assertEqual(state['call_counts']['late_compare'], 2)
                    if baseline_trace is None:
                        baseline_trace = state['trace'].events
                    self.assertEqual(state['trace'].events, baseline_trace)
                    self.assert_cleanup(state, success=False)
                    self.assert_clock_shape(state, completed=False)
        EVIDENCE.append(dict(case='real_typed_checkpoint_fault', entries=6,
            exact_exception_identity=True, authority_invalidated=True, committed_rows=0,
            trace_equal=True, cleanup_equal=True, incomplete_spans=True))

    def test_real_final_guard_rejects_model_mutation_after_cold_admission(self):
        baseline_trace = None
        for decoder in ('V39', 'V46'):
            for mode in MODES:
                with self.subTest(decoder=decoder, mode=mode):
                    state = self.run_entry(decoder, mode, mutate_final=True)
                    self.assertTrue(state['mutated'])
                    self.assertIsInstance(state.get('exception'), ValueError)
                    self.assertIn('Snapshot/caller changed during verifier', str(state['exception']))
                    self.assertEqual(len(state['records']), 48)
                    self.assertEqual(state['payload'], old_entry.expected_frames(self.fixture))
                    self.assertEqual(state['files'], {})
                    self.assertEqual(state['call_counts']['verified_reference'], 2)
                    self.assertEqual(state['call_counts']['late_compare'], 2)
                    if baseline_trace is None:
                        baseline_trace = state['trace'].events
                    self.assertEqual(state['trace'].events, baseline_trace)
                    self.assert_cleanup(state, success=False)
                    self.assert_clock_shape(state, completed=False)
        EVIDENCE.append(dict(case='real_typed_final_guard_mutation', entries=6,
            live_source_mutation_rejected=True, authority_invalidated=True,
            committed_rows=48, completed_entry_files=0, incomplete_spans=True))


if __name__ == '__main__':
    unittest.main()
