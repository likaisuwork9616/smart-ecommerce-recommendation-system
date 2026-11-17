"""Sealed V75 synthetic process/publication cases; never run before preparation seal."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

from scripts import retailrocket_session_knn_bundle_v75 as bundle
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_full_worker_v75 as worker
from scripts import retailrocket_session_knn_pipeline_v75 as pipeline


ROOT = Path(__file__).resolve().parents[1]
CASE_IDS = ('A12.prefix_crash_recovery', 'A16.alive', 'A16.nonzero', 'A16.pid_reused', 'A16.uncertain', 'A16.other_boot', 'A16.self_exit', 'A17.candidate_unknown_exit', 'A18.normal_exit_reentry', 'A19.normal_positions', 'A19.H1', 'A19.H2', 'A19.H3', 'A19.H4', 'A19.H5', 'A19.H6', 'A19.H7', 'A19.H8', 'A20.no_numeric_replay', 'A20.request', 'A20.request_deadline', 'A20.normal_boot', 'A20.observed_exit', 'A20.candidate_count', 'A20.query_stage', 'A20.payload_key', 'A20.global_roster', 'A20.aggregate_count', 'A20.cp_summary', 'A21.closed_manifest', 'A21.extra', 'A21.append', 'A21.missing', 'A21.live', 'A22.P9', 'A22.P10', 'A23.absolute', 'A23.downtime', 'A23.rollback', 'A23.rss', 'A23.disk', 'A23.temp', 'A23.monitor', 'A23.delivery', 'A23.path_scope', 'A23.resource_process', 'A23.monitor_process', 'A23.descendant_timeout', 'A24.intervals')


class FakeClock:
    def __init__(self, now=1700000000.0):
        self.now = now
        self.mono = 0.0

    def utc(self):
        return self.now

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.now += seconds
        self.mono += seconds


class FakeProcesses:
    def __init__(self, pid=101, created=1.0, boot=1.0, alive=(), uncertain=False):
        self.value = dict(pid=pid, create_time=created, boot_time=boot)
        self.alive = list(alive)
        self.uncertain = uncertain

    def identity(self):
        return dict(self.value)

    def is_alive(self, identity):
        if self.uncertain:
            raise PermissionError('Synthetic inaccessible process identity')
        return identity in self.alive


def _write(path, value):
    Path(path).write_bytes(cp.encoded(value))


def _admit(name):
    return bundle.admit(name,
        fixture_seal_sha256=os.environ['V75_FIXTURE_SEAL_SHA256'],
        method_seal_sha256=os.environ['V75_METHOD_SEAL_SHA256'])


class PipelineCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.small = _admit('F-small')
        cls.long = _admit('F-long')
        cls.work = ROOT / 'shop-mysql-runtime' / 'v75' / 'runs' / ('tests-' + uuid.uuid4().hex)
        cls.work.mkdir(parents=True)

    def folder(self, name):
        return self.work / (name + '-' + uuid.uuid4().hex)

    def assert_golden(self, folder, admitted):
        run_dir = folder / 'internal' / 'cp'
        store = cp.CheckpointStore(run_dir, admitted['binding'])
        store._load()
        actual = b''.join(cp.encoded(row) for row in store.iter_records())
        expected = (Path(admitted['bundle_root']) / admitted['manifest']['golden_records']).read_bytes()
        self.assertEqual(actual, expected)

    def make_candidate(self, name, *, fail_source_at=None):
        base = self.folder(name)
        base.mkdir()
        source = base / 'source.txt'
        source.write_bytes(b'a')
        binding = dict(profile='synthetic_only', fixture_id='guard-unit',
            expected_queries=2, expected_visitors=1, bootstrap_replicates=2000,
            configuration=dict(synthetic_acceptance_only=True,
                               fixed_validation=dict(queries=2, visitors=1)),
            sources=[cp.descriptor(base, 'source.txt')])
        clock = FakeClock()
        worker_process = FakeProcesses()
        seen = []
        self.last_source_events = seen
        self.last_source_base = base

        def check_sources():
            seen.append(len(seen) + 1)
            if len(seen) == fail_source_at:
                source.write_bytes(b'b')
            cp.verify_sources(base, binding['sources'])

        store = worker.create_store(base / 'cp', binding, clock.now + 120, 120,
            source_root=base, clock=clock, process_api=worker_process,
            external_source_verifier=check_sources)
        with store.writer():
            store.seal_stage('reconstruction', {'artificial_guard_unit': True})
            for i in range(2):
                store.append_verified(i, ['1', 1, i + 2], {'artificial_guard_unit': i})
            store.flush_chunk()
            store.seal_stage('queries', dict(queries=2, paired_streams_eof_checked=True))
            store.seal_stage('global', dict(queries=2))
            store.seal_stage('bootstrap', dict(replicates=2000))
            store.write_candidate({'artificial_guard_unit': True})
        return base, binding, clock, worker_process.identity(), check_sources, seen

    def test_A12_true_process_prefix_recovery(self):
        with self.subTest(case_id='A12.prefix_crash_recovery'):
            folder = self.folder('A12-prefix')
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline(self.long, folder,
                    scenario=dict(worker_fault='query_verified', worker_after=65), budget_seconds=120)
            run_dir = folder / 'internal' / 'cp'
            store = cp.CheckpointStore(run_dir, self.long['binding'])
            store._load()
            self.assertEqual(store.recover()['records'], 64)
            prefix = [cp.descriptor(run_dir, 'chunks/00000000.json')]
            prefix.append(cp.read(run_dir / 'chunks' / '00000000.json')['payload'])
            self.assertFalse((folder / 'final_seal.json').exists())
            request = (folder / 'internal' / 'request.json').read_bytes()
            result = pipeline.run_pipeline(self.long, folder)
            self.assertEqual(result['queries'], 129)
            self.assertEqual((folder / 'internal' / 'request.json').read_bytes(), request)
            for descriptor in prefix:
                self.assertEqual(cp.descriptor(run_dir, descriptor['path']), descriptor)
            self.assert_golden(folder, self.long)

    def test_A16_exit_and_identity_refusals(self):
        for scenario in ('alive', 'nonzero', 'pid_reused', 'uncertain', 'other_boot', 'self_exit'):
            with self.subTest(case_id='A16.' + scenario, scenario=scenario):
                base, binding, clock, identity, check, seen = self.make_candidate('A16-' + scenario)
                observer = FakeProcesses(pid=202)
                supplied, code = dict(identity), 0
                if scenario == 'alive':
                    observer.alive.append(identity)
                elif scenario == 'nonzero':
                    code = 9
                elif scenario == 'pid_reused':
                    supplied['create_time'] = 2.0
                elif scenario == 'uncertain':
                    observer.uncertain = True
                elif scenario == 'other_boot':
                    observer.value['boot_time'] = 2.0
                else:
                    observer.value = dict(identity)
                store = worker.open_store(base / 'cp', binding, clock=clock,
                    process_api=observer, external_source_verifier=check)
                original = (base / 'cp' / 'candidate.json').read_bytes()
                with self.assertRaises((cp.IntegrityError, cp.WriterBusy, PermissionError)):
                    store.finalize(cp.descriptor(base / 'cp', 'candidate.json')['sha256'], supplied, code)
                self.assertFalse((base / 'cp' / 'acceptance.json').exists())
                self.assertEqual((base / 'cp' / 'candidate.json').read_bytes(), original)

    def test_A17_true_process_candidate_unknown_exit(self):
        with self.subTest(case_id='A17.candidate_unknown_exit'):
            folder = self.folder('A17-orphan')
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline(self.small, folder,
                    scenario=dict(worker_fault='after_candidate_commit'), budget_seconds=120)
            run_dir = folder / 'internal' / 'cp'
            original = (run_dir / 'candidate.json').read_bytes()
            self.assertFalse((run_dir / 'normal_worker_exit.json').exists())
            self.assertFalse((run_dir / 'acceptance.json').exists())
            # A fresh attempt must traverse P6 even though the orphan had all
            # stages. This expected crash proves global replay is actually hit.
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline(self.small, folder,
                    scenario=dict(worker_fault='global_replay'))
            self.assertFalse((run_dir / 'candidate.json').exists())
            replays = [p.parent for p in (folder / 'internal' / 'episodes').glob('*/scenario.json')
                       if cp.read(p).get('worker_fault') == 'global_replay']
            self.assertEqual(len(replays), 1)
            self.assertEqual(cp.read(replays[0] / 'worker_exit.json')['exit_code'], 9)
            pipeline.run_pipeline(self.small, folder)
            preserved = list((run_dir / 'recovery').glob('*.candidate.json'))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(preserved[0].read_bytes(), original)
            self.assertNotEqual((run_dir / 'candidate.json').read_bytes(), original)
            self.assert_golden(folder, self.small)

    def test_A18_recorded_normal_exit_finalize_reentry(self):
        with self.subTest(case_id='A18.normal_exit_reentry'):
            folder = self.folder('A18-finalize')
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline(self.small, folder,
                    scenario=dict(finalize_fault='before_acceptance_commit'), budget_seconds=120)
            run_dir = folder / 'internal' / 'cp'
            normal = (run_dir / 'normal_worker_exit.json').read_bytes()
            candidate = (run_dir / 'candidate.json').read_bytes()
            self.assertFalse((run_dir / 'acceptance.json').exists())
            workers = len(list((folder / 'internal' / 'episodes').glob('*/worker_exit.json')))
            pipeline.run_pipeline(self.small, folder)
            self.assertEqual((run_dir / 'normal_worker_exit.json').read_bytes(), normal)
            self.assertEqual((run_dir / 'candidate.json').read_bytes(), candidate)
            self.assertEqual(len(list((folder / 'internal' / 'episodes').glob('*/worker_exit.json'))), workers)
            self.assertFalse(list((run_dir / 'recovery').glob('*.candidate.json')))
            self.assert_golden(folder, self.small)

    def test_A19_source_positions_and_same_size_changes(self):
        folder = self.folder('A19-normal')
        result = pipeline.run_pipeline(self.small, folder)
        episode = folder / 'internal' / 'episodes' / result['publication_episode']
        trace = []
        for name in ('worker_sources.jsonl', 'supervisor_sources.jsonl', 'publisher_sources.jsonl'):
            trace.extend(json.loads(line)['position'] for line in (episode / name).read_text().splitlines())
        with self.subTest(case_id='A19.normal_positions'):
            self.assertEqual(trace, ['H' + str(i) for i in range(1, 9)])
        for point in range(1, 7):
            with self.subTest(case_id='A19.H' + str(point), source_position='H' + str(point)):
                seen = []
                if point <= 3:
                    with self.assertRaises(cp.IntegrityError):
                        self.make_candidate('A19-source', fail_source_at=point)
                    self.assertEqual(self.last_source_events[-1], point)
                    self.assertFalse((self.last_source_base / 'cp' / 'candidate.json').exists())
                    self.assertFalse((self.last_source_base / 'cp' / 'acceptance.json').exists())
                else:
                    base, binding, clock, identity, check, seen = self.make_candidate(
                        'A19-source', fail_source_at=point)
                    with self.assertRaises(cp.IntegrityError):
                        store = worker.open_store(base / 'cp', binding, clock=clock,
                            process_api=FakeProcesses(pid=202), external_source_verifier=check)
                        store.finalize(cp.descriptor(base / 'cp', 'candidate.json')['sha256'], identity, 0)
                    self.assertEqual(seen[-1], point)
                    self.assertFalse((base / 'cp' / 'acceptance.json').exists())
        for point in (1, 2):
            with self.subTest(case_id='A19.H' + str(point + 6), source_position='H' + str(point + 6)):
                sentinel = self.folder('A19-sentinel')
                sentinel.mkdir(); (sentinel / 'source').write_bytes(b'a')
                binding = [cp.descriptor(sentinel, 'source')]
                seen = []
                def check():
                    seen.append(len(seen) + 1)
                    if len(seen) == point:
                        (sentinel / 'source').write_bytes(b'b')
                    cp.verify_sources(sentinel, binding)
                with self.assertRaises(cp.IntegrityError):
                    pipeline.audit_saved(self.small, folder / 'internal' / 'cp', source_check=check)
                self.assertEqual(seen[-1], point)
                self.assertEqual(pipeline.finalize_stopped(folder, expected=result), result)

    def _copy_science(self, source):
        target = self.folder('A20-tamper') / 'internal'
        target.mkdir(parents=True)
        shutil.copytree(source / 'internal' / 'cp', target / 'cp')
        shutil.copytree(source / 'internal' / 'episodes', target / 'episodes')
        shutil.copy2(source / 'internal' / 'request.json', target / 'request.json')
        return target / 'cp'

    def _refresh_receipts(self, run_dir):
        """Unit mutations remain internally hash-consistent to reach new raw guards."""
        candidate = cp.read(run_dir / 'candidate.json')
        summary = dict(candidate['ledger'])
        previous = None
        for path in sorted((run_dir / 'chunks').glob('*.json')):
            chunk = cp.read(path)
            chunk['previous_sha256'] = previous
            chunk['payload'] = cp.descriptor(run_dir, chunk['payload']['path'])
            _write(path, chunk)
            previous = cp.descriptor(run_dir, path.relative_to(run_dir).as_posix())['sha256']
        summary['last_manifest_sha256'] = previous
        latest = cp.read(run_dir / 'latest.json')
        latest.update(summary); _write(run_dir / 'latest.json', latest)
        for name in ('queries', 'global', 'bootstrap'):
            path = run_dir / 'stages' / (name + '.json')
            value = cp.read(path); value['ledger'] = summary; _write(path, value)
        stages = [cp.descriptor(run_dir, 'stages/' + n + '.json') for n in pipeline.REQUIRED_STAGES]
        candidate['ledger'], candidate['stages'] = summary, stages
        _write(run_dir / 'candidate.json', candidate)
        accepted = cp.read(run_dir / 'acceptance.json')
        accepted.update(ledger=summary, stages=stages, candidate=cp.descriptor(run_dir, 'candidate.json'),
                        normal_worker_exit=cp.descriptor(run_dir, 'normal_worker_exit.json'))
        _write(run_dir / 'acceptance.json', accepted)

    def test_A20_publisher_raw_proof_and_no_numeric_replay(self):
        folder = self.folder('A20-normal')
        pipeline.run_pipeline(self.small, folder)
        run_dir = folder / 'internal' / 'cp'
        with patch('scripts.retailrocket_session_knn_sql_v4.predict', side_effect=AssertionError('ranking forbidden')), \
             patch('scripts.retailrocket_session_knn_readback_v2.replay_global', side_effect=AssertionError('global forbidden')), \
             patch('scripts.retailrocket_session_knn_readback_v2.check_bootstrap', side_effect=AssertionError('draw forbidden')):
            proof = pipeline.audit_saved(self.small, run_dir, source_check=lambda: None)
        with self.subTest(case_id='A20.no_numeric_replay'):
            self.assertEqual((proof['ranking_calls'], proof['global_numeric_replays'], proof['draw_numeric_replays']), (0, 0, 0))
        for mutation, message in (
                ('request', 'raw request'), ('request_deadline', 'request budget'),
                ('normal_boot', 'same-boot'), ('observed_exit', 'Raw normal worker exit'),
                ('candidate_count', 'full receipt'),
                ('query_stage', 'query completion'), ('payload_key', 'Payload key'),
                ('global_roster', 'global roster'), ('aggregate_count', 'aggregate counts'),
                ('cp_summary', 'CP acceptance')):
            with self.subTest(case_id='A20.' + mutation, mutation=mutation):
                cloned = self._copy_science(folder)
                if mutation == 'request':
                    path = cloned.parent / 'request.json'; value = cp.read(path)
                    value['binding']['expected_queries'] += 1; _write(path, value)
                elif mutation == 'request_deadline':
                    path = cloned.parent / 'request.json'; value = cp.read(path)
                    value['deadline_utc'] = cp._iso(cp._time(value['deadline_utc']) + 1)
                    _write(path, value)
                elif mutation == 'normal_boot':
                    path = cloned / 'normal_worker_exit.json'; value = cp.read(path)
                    value['supervisor_identity']['boot_time'] += 1; _write(path, value)
                    self._refresh_receipts(cloned)
                elif mutation == 'observed_exit':
                    path = next((cloned.parent / 'episodes').glob('*/worker_exit.json'))
                    value = cp.read(path); value['normal_observed'] = False; _write(path, value)
                elif mutation == 'candidate_count':
                    path = cloned / 'candidate.json'; value = cp.read(path)
                    value['receipt']['queries_checked'] += 1; _write(path, value)
                    self._refresh_receipts(cloned)
                elif mutation == 'query_stage':
                    path = cloned / 'stages' / 'queries.json'; value = cp.read(path)
                    value['receipt']['paired_streams_eof_checked'] = 1; _write(path, value)
                    self._refresh_receipts(cloned)
                elif mutation == 'payload_key':
                    chunk = cp.read(next((cloned / 'chunks').glob('*.json')))
                    path = cloned / chunk['payload']['path']
                    rows = [json.loads(line) for line in path.read_text().splitlines()]
                    rows[0]['payload']['expected']['key'][2] += 1
                    path.write_bytes(b''.join(cp.encoded(row) for row in rows))
                    self._refresh_receipts(cloned)
                elif mutation == 'global_roster':
                    path = cloned / 'stages' / 'global.json'; value = cp.read(path)
                    value['receipt']['roster_sha256'] = '0' * 64; _write(path, value)
                    self._refresh_receipts(cloned)
                elif mutation == 'aggregate_count':
                    path = cloned / 'candidate.json'; value = cp.read(path)
                    value['receipt']['aggregate']['main']['arms']['K1']['queries'] += 1
                    _write(path, value); self._refresh_receipts(cloned)
                else:
                    path = cloned / 'acceptance.json'; value = cp.read(path)
                    value['ledger']['records'] += 1; _write(path, value)
                old_chain = cp.CheckpointStore(cloned, self.small['binding']); old_chain._load()
                self.assertEqual(len(list(old_chain.iter_records())), self.small['binding']['expected_queries'])
                with self.assertRaisesRegex(cp.IntegrityError, message):
                    pipeline.audit_saved(self.small, cloned, source_check=lambda: None)
                self.assertFalse((cloned.parent / 'publisher_proof.json').exists())

    def test_A21_stopped_complete_manifest_and_buffered_logs(self):
        folder = self.folder('A21-stopped')
        result = pipeline.run_pipeline(self.small, folder)
        episode = folder / 'internal' / 'episodes' / result['publication_episode']
        with self.subTest(case_id='A21.closed_manifest'):
            self.assertIn(b'publication closed', (episode / 'pipeline.log').read_bytes())
            self.assertIn(b'proof closed', (episode / 'publisher.log').read_bytes())
            self.assertEqual(pipeline.finalize_stopped(folder, expected=result), result)
            self.assertNotIn('final_seal.json', {r['path'] for r in result['internal_evidence']})
        for mutation in ('extra', 'append', 'missing', 'live'):
            with self.subTest(case_id='A21.' + mutation, mutation=mutation):
                path = episode / ('unexpected.json' if mutation == 'extra' else 'publisher.log')
                old = path.read_bytes() if path.exists() else None
                try:
                    if mutation == 'extra': path.write_bytes(b'{}')
                    elif mutation == 'append': path.write_bytes(old + b'late append')
                    elif mutation == 'missing': path.unlink()
                    fake = None
                    if mutation == 'live':
                        fake = FakeProcesses()
                        fake.is_alive = lambda identity: True
                    with self.assertRaises((cp.IntegrityError, cp.WriterBusy)) as caught:
                        pipeline.finalize_stopped(folder, expected=result, process_api=fake)
                    evidence = folder / 'control' / 'case_evidence' / mutation
                    evidence.mkdir(parents=True)
                    mutation_bytes = path.read_bytes() if path.exists() else None
                    if mutation_bytes is not None:
                        (evidence / 'mutated_bytes.bin').write_bytes(mutation_bytes)
                    cp.atomic_json(evidence / 'rejection.json', dict(
                        case_id='A21.' + mutation, error_type=type(caught.exception).__name__,
                        original_sha256=None if old is None else hashlib.sha256(old).hexdigest(),
                        mutated_sha256=None if mutation_bytes is None else hashlib.sha256(mutation_bytes).hexdigest(),
                        missing=not path.exists(), restored_only_after_preserving_failure=True))
                finally:
                    if old is None and path.exists(): path.unlink()
                    elif old is not None: path.write_bytes(old)
        self.assertEqual(pipeline.finalize_stopped(folder, expected=result), result)

    def test_A22_publication_only_recovery_and_completed_readonly(self):
        for stage, scenario in (
                ('P9', dict(publisher_fault='before_proof')),
                ('P10', dict(finalizer_fault='before_final_commit'))):
            with self.subTest(case_id='A22.' + stage, stage=stage):
                folder = self.folder('A22-' + stage)
                with self.assertRaises(RuntimeError):
                    pipeline.run_pipeline(self.small, folder, scenario=scenario)
                run_dir = folder / 'internal' / 'cp'
                self.assertTrue((run_dir / 'acceptance.json').exists())
                original = pipeline._snapshot(run_dir)
                worker_count = len(list((folder / 'internal' / 'episodes').glob('*/worker_exit.json')))
                self.assertFalse((folder / 'final_seal.json').exists())
                result = pipeline.run_pipeline(self.small, folder)
                self.assertEqual(pipeline._snapshot(run_dir), original)
                self.assertEqual(len(list((folder / 'internal' / 'episodes').glob('*/worker_exit.json'))), worker_count)
                with self.assertRaisesRegex(cp.IntegrityError, 'readonly'):
                    pipeline.run_pipeline(self.small, folder)
                self.assertEqual(pipeline.finalize_stopped(folder, expected=result), result)

    def test_A23_fake_deadline_resource_and_cross_process_budget(self):
        for fault in ('absolute', 'downtime', 'rollback', 'rss', 'disk', 'temp', 'monitor'):
            with self.subTest(case_id='A23.' + fault, fault=fault):
                base = self.folder('A23-' + fault); base.mkdir()
                clock = FakeClock()
                request = dict(created_utc=cp._iso(clock.now), deadline_utc=cp._iso(clock.now + 120), budget_seconds=120)
                guard = pipeline.Deadline(request, base / 'first-pid.json', clock=clock)
                guard.check(); clock.advance(10); guard.check()
                later = pipeline.Deadline(request, base / 'second-pid.json', clock=clock)
                resource = None
                if fault == 'absolute': clock.advance(110)
                elif fault == 'downtime': clock.advance(120)
                elif fault == 'rollback': clock.now -= 1
                elif fault == 'monitor':
                    def resource(): raise RuntimeError('Synthetic monitor unavailable')
                else:
                    resource = lambda: False
                with self.assertRaises((cp.BudgetExceeded, RuntimeError)):
                    later.check(resource)
                self.assertFalse((base / 'final_seal.json').exists())
        with self.subTest(case_id='A23.delivery'):
            base = self.folder('A23-delivery'); base.mkdir()
            clock = FakeClock(); request = dict(created_utc=cp._iso(clock.now), deadline_utc=cp._iso(clock.now + 120), budget_seconds=120)
            pipeline.Deadline(request, base / 'worker.json', clock=clock).check()
            clock.advance(110)
            self.assertEqual(pipeline.Deadline(request, base / 'publisher.json', clock=clock).check(), 10)
            clock.advance(10)
            with self.assertRaises(cp.BudgetExceeded):
                pipeline.Deadline(request, base / 'finalizer.json', clock=clock).check()
        with self.subTest(case_id='A23.path_scope'):
            for value in (ROOT / 'shop-mysql-runtime' / 'v75' / 'fixtures' / 'bad',
                          ROOT / 'shop-mysql-runtime' / 'v75' / 'formal' / 'bad'):
                with self.assertRaises(cp.IntegrityError): pipeline._folder(value)
        for cause in ('resource_process', 'monitor_process'):
            with self.subTest(case_id='A23.' + cause):
                base = self.folder('A23-' + cause); base.mkdir()
                real_clock = cp.Clock(); now = real_clock.utc()
                request = dict(created_utc=cp._iso(now), deadline_utc=cp._iso(now + 20), budget_seconds=20)
                guard = pipeline.Deadline(request, base / 'budget' / 'outer.json', clock=real_clock)
                calls = []
                def resource():
                    calls.append(len(calls) + 1)
                    if len(calls) == 1:
                        return True
                    if cause == 'monitor_process':
                        raise RuntimeError('Synthetic process monitor failed')
                    return False
                with self.assertRaises((cp.BudgetExceeded, RuntimeError)):
                    pipeline._launch([sys.executable, '-B', '-c', 'import time; time.sleep(30)'],
                        base / 'child.log', base / 'child_exit.json', guard, resource_check=resource)
                exited = cp.read(base / 'child_exit.json')
                self.assertGreaterEqual(len(calls), 2)
                self.assertIs(exited['normal_observed'], False)
                self.assertIsNotNone(exited['stop_request'])
                self.assertLessEqual(exited['stop_request']['requested_utc'], exited['actual_exit_observed_utc'])
                for identity in exited['tracked']:
                    self.assertFalse(cp.Processes().is_alive(identity))
                self.assertFalse((base / 'final_seal.json').exists())

        with self.subTest(case_id='A23.descendant_timeout'):
            base = self.folder('A23-child-timeout'); base.mkdir()
            clock = cp.Clock(); now = clock.utc()
            request = dict(created_utc=cp._iso(now), deadline_utc=cp._iso(now + 20), budget_seconds=20)
            guard = pipeline.Deadline(request, base / 'budget' / 'outer.json', clock=clock)
            failure = dict(role='worker', episode=base.name, error_type='BudgetExceeded',
                           message='Synthetic injected descendant deadline', traceback='synthetic case',
                           timeout_stop=True, retry_allowed=False, scientific_success=False)
            code = ('from pathlib import Path; import sys; '
                    + 'Path(' + repr(str(base / 'worker_failure.json')) + ').write_bytes('
                    + repr(cp.encoded(failure)) + '); sys.exit(1)')
            with self.assertRaisesRegex(TimeoutError, 'descendant deadline'):
                pipeline._launch([sys.executable, '-B', '-c', code], base / 'worker.log',
                                 base / 'worker_exit.json', guard)
            exited = cp.read(base / 'worker_exit.json')
            self.assertIs(exited['normal_observed'], False)
            self.assertEqual(exited['child_failure'], cp.descriptor(base, 'worker_failure.json'))

    def test_A24_synthetic_exclusive_accounting_and_signed_bridge(self):
        with self.subTest(case_id='A24.intervals'):
            intervals = [
                dict(id='P4', start=0, end=10),
                dict(id='verify', start=0, end=6, parent='P4'),
                dict(id='rank', start=1, end=5, parent='verify'),
                dict(id='append', start=6, end=10, parent='P4'),
                dict(id='commit', start=8, end=10, parent='append'),
                dict(id='P5', start=10, end=12),
                dict(id='tail', start=10, end=12, parent='P5'),
                dict(id='P6', start=12, end=20),
                dict(id='fold', start=12, end=16, parent='P6'),
                dict(id='draw', start=16, end=19, parent='P6'),
                dict(id='H3', start=20, end=21),
                dict(id='supervisor_overlap', start=0, end=21, view='observer'),
                dict(id='recovery_episode', start=21, end=24),
            ]
            result = pipeline.account_intervals(intervals, outer_start=0, outer_end=23)
            self.assertEqual(result['primary_phase_total'], 24)
            self.assertEqual(result['signed_bridge'], -1)
            self.assertEqual(result['exclusive']['verify'], 2)
            self.assertEqual(result['exclusive']['append'], 2)
            self.assertIsNone(result['waiting_cpu_attribution'])
            primary_exclusive = sum(value for key, value in result['exclusive'].items() if key != 'supervisor_overlap')
            self.assertEqual(primary_exclusive, 24)
            with self.assertRaises(ValueError):
                pipeline.account_intervals([dict(id='x', start=0, end=3), dict(id='y', start=1, end=4)], outer_start=0, outer_end=4)
            with self.assertRaises(ValueError):
                pipeline.account_intervals([dict(id='x', start=0, end=3, parent='y'), dict(id='y', start=0, end=3, parent='x')], outer_start=0, outer_end=3)


if __name__ == '__main__':
    unittest.main()
