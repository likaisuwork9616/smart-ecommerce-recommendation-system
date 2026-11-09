"""Artificial-only differential, source mutation, lock and publisher checks."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import count
from pathlib import Path
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch
from uuid import UUID

from scripts import retailrocket_session_knn_sources_v24 as source
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import run_retailrocket_session_knn_v2 as io
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from tests import test_retailrocket_session_knn_pair_v4 as pair_fixture
from tests import test_retailrocket_session_knn_validation as validation_fixture
from tests.test_retailrocket_session_knn_checkpoint_v2 import FakeClock, FakeProcesses


class SourceObserverTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.file = self.root/'source.txt'
        self.file.write_bytes(b'ABCD')
        self.binding = {'sources': cp.bind_sources(self.root, ['source.txt'])}
        self.originals = (cp.CheckpointStore._check_sources, cp.verify_sources, cp.descriptor,
                          pair.verify_selected, pair.core.load_context, pair.sql.prepare_catalog)

    def tearDown(self):
        self.assertEqual(self.originals, (cp.CheckpointStore._check_sources, cp.verify_sources, cp.descriptor,
                          pair.verify_selected, pair.core.load_context, pair.sql.prepare_catalog))

    def create(self, cls, name, **kwargs):
        return cls.create(self.root/name, self.binding, 1100., 90., source_root=self.root,
            expected_queries=2, required_stages=('reconstruction', 'queries'), chunk_queries=1,
            clock=FakeClock(), process_api=FakeProcesses(), **kwargs)

    def test_exact_source_descriptor_and_watch_trace_repeats_without_extra_reads(self):
        original_descriptor = cp.descriptor
        traces = []
        for observed in (False, True):
            trace = []
            def descriptor(*args):
                trace.append(args[1])
                return original_descriptor(*args)
            obs = source.Observation()
            with patch.object(cp, 'descriptor', descriptor):
                verify = obs.verify_sources if observed else cp.verify_sources
                self.assertEqual(verify(self.root, self.binding['sources']), 1)
                self.assertEqual(verify(self.root, self.binding['sources']), 1)
            traces.append(trace)
            if observed:
                result = obs.summary()['source_descriptors']
                self.assertEqual((result['attempted_calls'], result['completed_calls']), (2, 2))
                self.assertEqual((result['completed_logical_bytes'], result['unique_completed_logical_bytes']), (8, 4))
        self.assertEqual(traces[0], traces[1])
        with patch.object(io, 'ROOT', self.root):
            records = [io.describe(self.file)]
            traces = []
            for observed in (False, True):
                trace = []
                obs = source.Observation()
                verify = obs.verify_bindings if observed else io.verify_bindings
                verify(records, lambda: trace.append('original_watch'))
                traces.append(trace)
                if observed:
                    self.assertEqual(obs.summary()['source_descriptors']['completed_logical_bytes'], 4)
            self.assertEqual(traces, [['original_watch'], ['original_watch']])

    def test_same_length_mutation_missing_path_and_original_exceptions_retained(self):
        with patch.object(io, 'ROOT', self.root):
            records = [io.describe(self.file)]
            self.file.write_bytes(b'WXYZ')
            obs = source.Observation()
            errors = []
            for verify in (io.verify_bindings, obs.verify_bindings):
                with self.assertRaises(ValueError) as caught:
                    verify(records)
                errors.append(str(caught.exception))
            self.assertEqual(errors[0], errors[1])
            self.assertEqual(obs.summary()['phases']['closure.verify_bindings']['failed'], 1)
            self.assertEqual(obs.summary()['source_descriptors']['completed_logical_bytes'], 4)
            self.file.unlink()
            missing = source.Observation()
            with self.assertRaises(FileNotFoundError):
                missing.publisher(lambda: missing.verify_bindings(records))
            result = missing.summary()
            self.assertEqual(result['phases']['publisher.total']['failed'], 1)
            self.assertEqual(result['source_descriptors']['failed_calls'], 1)
            self.assertIsNone(result['source_descriptors']['failed_operation_byte_coverage'])

    def test_change_between_create_and_post_lock_force_recheck_still_rejects(self):
        errors = []
        for cls in (DetailedTimedStore, source.ObservedStore):
            self.file.write_bytes(b'ABCD')
            obs = source.Observation()
            store = self.create(cls, cls.__name__, **({'observer': obs} if cls is source.ObservedStore else {}))
            self.file.write_bytes(b'WXYZ')
            with self.assertRaises(cp.IntegrityError) as caught:
                with store.writer():
                    self.fail('The changed source must not enter the writer body')
            errors.append(str(caught.exception))
            self.assertIsNone(store._guard)
            if cls is source.ObservedStore:
                checks = [e for e in obs.events if e['phase'] == 'checkpoint.check_sources']
                self.assertEqual([e['metadata']['force'] for e in checks], [False, True])
                self.assertFalse(checks[-1]['completed'])
                self.assertEqual(obs.summary()['source_descriptors']['completed_calls'], 2)
        self.assertEqual(errors[0], errors[1])

    def test_original_cache_external_callback_and_force_behavior(self):
        obs = source.Observation()
        store = self.create(source.ObservedStore, 'cache', observer=obs)
        store._check_sources()
        self.assertEqual(obs.summary()['source_descriptors']['completed_calls'], 1)
        store._check_sources(force=True)
        self.assertEqual(obs.summary()['source_descriptors']['completed_calls'], 2)
        calls = []
        other = source.Observation()
        store = self.create(source.ObservedStore, 'external', observer=other,
                            external_source_verifier=lambda: calls.append('original_callback'))
        store._check_sources()
        store._check_sources(force=True)
        with store.writer():
            pass
        self.assertEqual(len(calls), 3)
        self.assertEqual(other.summary()['source_descriptors']['attempted_calls'], 0)

    def test_checkpoint_protocol_bytes_and_writer_fault_deadline_immutability(self):
        stores = []
        for cls in (DetailedTimedStore, source.ObservedStore):
            serial = count(1)
            obs = source.Observation()
            with patch.object(cp.uuid, 'uuid4', side_effect=lambda: UUID(int=next(serial))):
                store = self.create(cls, cls.__name__, **({'observer': obs} if cls is source.ObservedStore else {}))
                with store.writer():
                    store.seal_stage('reconstruction', {})
                    for i in range(2):
                        store.append_verified(i, ['1', 0, i], {'artificial': i})
                    store.flush_chunk()
                    store.seal_stage('queries', {'queries': 2, 'paired_streams_eof_checked': True})
                stores.append(store)
                if cls is source.ObservedStore:
                    self.assertEqual(obs.summary()['source_descriptors']['completed_calls'], 2)
        for name in ('chunks', 'payloads', 'stages'):
            self.assertEqual({p.name: p.read_bytes() for p in (stores[0].folder/name).iterdir()},
                             {p.name: p.read_bytes() for p in (stores[1].folder/name).iterdir()})
        for name in ('run.json', 'latest.json', 'budget.json'):
            self.assertEqual((stores[0].folder/name).read_bytes(), (stores[1].folder/name).read_bytes())
        for issue in ('lock', 'deadline', 'acceptance', 'body'):
            obs = source.Observation()
            store = self.create(source.ObservedStore, issue, observer=obs)
            if issue == 'deadline': store.clock.advance(100.)
            if issue == 'acceptance': (store.folder/'acceptance.json').write_text('{}')
            expected = {'lock': OSError, 'deadline': cp.BudgetExceeded,
                        'acceptance': cp.IntegrityError, 'body': RuntimeError}[issue]
            def body():
                with store.writer():
                    if issue == 'body': raise RuntimeError('artificial interruption')
            if issue == 'lock':
                with patch.object(cp, '_lock', side_effect=OSError('artificial lock failure')), self.assertRaises(expected): body()
            else:
                with self.assertRaises(expected): body()
            self.assertIsNone(store._guard)
            self.assertFalse(obs.stack)
            self.assertEqual(obs.summary()['phases']['checkpoint.writer_lifetime']['failed'], 1)

    def test_complete_four_arm_verifier_outputs_workload_and_setup_envelope_match(self):
        with patch.object(pair_fixture, 'make_fixture', side_effect=lambda **kw: validation_fixture.make_fixture(base=self.root, **kw)):
            root, paths, config, primary, _, database, model, ordinals, binding = pair_fixture.fixture(boundary=True)
        outputs, workloads = [], []
        for observed in (False, True):
            obs = source.Observation()
            cls = source.ObservedStore if observed else DetailedTimedStore
            store = cls.create(root/str(observed), binding,
                (datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat(), 180., source_root=root,
                expected_queries=len(ordinals), required_stages=('reconstruction', 'queries'), chunk_queries=1,
                **({'observer': obs} if observed else {}))
            with store.writer():
                store.seal_stage('reconstruction', {'fit_audit': model['fit_audit']})
                verify = source.make_verifier(obs) if observed else pair.verify_selected
                measured = verify(primary, paths, config, store, model, database, ordinals)
            outputs.append([cp.encoded(row) for row in store.iter_records()])
            workloads.append([q['sql_workload'] for q in measured['queries']])
            if observed:
                summary = obs.summary()
                self.assertEqual(summary['phases']['context.load_context']['calls'], 1)
                self.assertEqual(summary['phases']['context.prepare_catalog']['calls'], 1)
                self.assertEqual(summary['phases']['verifier.setup_envelope']['completed'], 1)
                event = next(e for e in obs.events if e['phase'] == 'verifier.total')
                self.assertEqual(event['metadata']['original_setup_seconds'], measured['setup_seconds'])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(workloads[0], workloads[1])

    def test_watch_failure_and_event_tampering_preserve_failed_evidence(self):
        obs = source.Observation()
        with patch.object(io, 'ROOT', self.root):
            records = [io.describe(self.file)]
            error = TimeoutError('original watch stopped')
            def watch(): raise error
            with self.assertRaises(TimeoutError) as caught:
                obs.verify_bindings(records, watch)
            self.assertIs(caught.exception, error)
        self.assertEqual(obs.summary()['source_descriptors']['failed_calls'], 1)
        obs = source.Observation(clock=iter([0, 10, 30, 40]).__next__)
        with obs.span('outer'):
            with obs.span('inner'):
                pass
        self.assertEqual(obs.summary()['root_wall_ns'], 40)
        self.assertEqual(sum(x['exclusive_wall_ns'] for x in obs.summary()['phases'].values()), 40)
        for change in ('outside', 'incomplete', 'parent', 'error', 'clock'):
            events = deepcopy(obs.events)
            if change == 'outside': events[1]['end_ns'] = 41
            elif change == 'incomplete': events[1]['end_ns'] = None
            elif change == 'parent': events[1]['parent'] = 1
            elif change == 'error': events[1]['completed'] = False
            else: events[1]['start_ns'] = -1
            with self.subTest(change=change), self.assertRaises(ValueError): source.summarize_events(events)
        overlap = deepcopy(obs.events)
        overlap.append(dict(overlap[1], id=2, start_ns=20, end_ns=35))
        with self.assertRaises(ValueError): source.summarize_events(overlap)

    def test_early_context_failure_closes_setup_and_keeps_original_exception(self):
        error = ValueError('artificial context parser failure')
        obs = source.Observation()
        with patch.object(pair.core, 'load_context', side_effect=error):
            for verify in (pair.verify_selected, source.make_verifier(obs)):
                with self.assertRaises(ValueError) as caught:
                    verify(None, dict.fromkeys(('dataset','P0','C1','D1')), {}, None,
                           {'fit_audit':{},'support':{}}, None, [])
                self.assertIs(caught.exception, error)
        self.assertFalse(obs.stack)
        self.assertEqual(obs.summary()['phases']['verifier.setup_envelope']['failed'], 1)
        self.assertEqual(obs.summary()['phases']['verifier.total']['failed'], 1)

    def test_writer_recovery_fault_keeps_original_failure_and_releases_lock(self):
        errors = []
        for cls in (DetailedTimedStore, source.ObservedStore):
            obs = source.Observation()
            store = self.create(cls, 'recovery_'+cls.__name__,
                                **({'observer':obs} if cls is source.ObservedStore else {}))
            with store.writer():
                store.seal_stage('reconstruction', {})
                store.append_verified(0, ['1',0,0], {'artificial':True})
            payload = next((store.folder/'payloads').glob('*.jsonl'))
            payload.write_bytes(payload.read_bytes()+b'broken tail\n')
            with self.assertRaises(cp.IntegrityError) as caught:
                with store.writer():
                    self.fail('Corrupted recovery must reject before the body')
            errors.append(str(caught.exception))
            self.assertIsNone(store._guard)
            self.assertTrue((store.folder/'integrity_failed.json').exists())
            if cls is source.ObservedStore:
                self.assertEqual(obs.summary()['phases']['checkpoint.writer_acquire']['failed'], 1)
        self.assertEqual(errors[0], errors[1])

    def test_sealed_acceptance_scope_cannot_authorize_real_runs_or_another_roster(self):
        from scripts import accept_retailrocket_session_knn_sources_v24 as gate
        spec = gate.specification()
        self.assertEqual(spec['scope']['actual_real_runs_authorized_this_round'], 0)
        for change in ('scope', 'size', 'schedule'):
            altered = deepcopy(spec)
            if change == 'scope': altered['scope']['actual_real_runs_authorized_this_round'] = 14
            elif change == 'size': altered['measurement_plan']['queries_per_run'] = 7
            else: altered['measurement_plan']['schedule'].reverse()
            with patch.object(gate, 'read', return_value=altered), self.assertRaises(ValueError):
                gate.specification()

    def test_synthetic48_run_and_independent_publisher_complete_bytes_and_faults(self):
        config = {'fixed_validation': {'queries': 48}}
        probes = [dict(key=['1', 0, i], original_ordinal=i,
                       key_sha256=hashlib.sha256(str(i).encode()).hexdigest()) for i in range(48)]
        ordinals = [dict(key=p['key'], original_ordinal=i, subset_ordinal=i) for i,p in enumerate(probes)]
        def verifier(primary, paths, configuration, store, model, database, selected, watch):
            rows = []
            for i,p in enumerate(probes):
                started = perf_counter()
                payload = {'expected': {'key': p['key'], 'artificial': i}}
                verify_seconds = perf_counter()-started
                started = perf_counter(); before = store.commit_seconds
                store.append_verified(i, p['key'], payload)
                elapsed = perf_counter()-started; commit = store.commit_seconds-before
                rows.append(dict(subset_ordinal=i, original_ordinal=i, key_sha256=p['key_sha256'],
                    verification_seconds=verify_seconds, rank_seconds=0.,
                    rank_stages_seconds={'sql_selected_votes_and_accumulation': 0.}, sql_workload={},
                    checkpoint_append_seconds=elapsed, chunk_commit_seconds=commit,
                    append_without_commit_seconds=elapsed-commit, seconds=verify_seconds+elapsed))
            store.flush_chunk(); store.seal_stage('queries', {'queries':48,'paired_streams_eof_checked':True})
            return dict(queries=rows, committed_prefix_rows=0, verified_subset_queries=48,
                setup_seconds=0., tail_flush_and_eof_seal_seconds=store.commit_seconds,
                prefix_replay_seconds=0., chunk_commits=list(store.commit_events))
        reference = None
        obs = source.Observation()
        for label, observer in (('R', None), ('D', obs)):
            if reference is None:
                # The original run compares its own immutable artificial ledger
                # fingerprint; this reference contains no real source identities.
                data = b''.join(cp.encoded({'ordinal':i,'key':p['key'],'payload':{'expected':{'key':p['key'],'artificial':i}}}) for i,p in enumerate(probes))
                reference = dict(records=48, actual_committed_bytes=len(data), actual_committed_payload_sha256=hashlib.sha256(data).hexdigest())
            inputs = (self.root, config, self.binding, {'fit_audit':{}}, self.root/'unused.sqlite', probes, ordinals, reference)
            request = dict(deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat(), budget_seconds=180.)
            with patch.object(pair, 'verify_selected', verifier), patch.object(source, 'make_verifier', return_value=verifier):
                source.run_fixed48(self.root/'runs', request, label, inputs, observer=observer, source_root=self.root)
        r = next((self.root/'runs/R/verified_subset/payloads').glob('*.jsonl')).read_bytes()
        d = next((self.root/'runs/D/verified_subset/payloads').glob('*.jsonl')).read_bytes()
        self.assertEqual(r, d)
        factory = source.StoreFactory(obs)
        with patch.object(io, 'ROOT', self.root):
            records = [io.describe(self.file)]
            def publish():
                obs.verify_bindings(records)
                store = factory.open(self.root/'runs/D/verified_subset', self.binding, source_root=self.root)
                proof = obs.call('publisher.ledger_proof', ledger_proof, store, probes)
                obs.call('publisher.output_write', io.write, self.root/'publication.json', proof)
                return proof
            self.assertEqual(obs.publisher(publish)['records'], 48)
            self.assertEqual(obs.summary()['phases']['run.output_write']['calls'], 5)
            self.assertEqual(obs.summary()['phases']['publisher.total']['completed'], 1)
            payload = next((self.root/'runs/D/verified_subset/payloads').glob('*.jsonl'))
            payload.write_bytes(payload.read_bytes()+b'{}\n')
            with self.assertRaises(cp.IntegrityError): obs.publisher(publish)
            self.assertEqual(obs.summary()['phases']['publisher.total']['failed'], 1)
        bad = list(inputs); bad[5] = probes[:-1]
        with self.assertRaises(ValueError): source.run_fixed48(self.root/'runs', request, 'bad', bad)


if __name__ == '__main__':
    unittest.main()
