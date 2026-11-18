"""Sealed V80 synthetic process/publication cases; never run before preparation seal."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from scripts import retailrocket_session_knn_bundle_v80 as bundle
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_full_worker_v75 as worker
from scripts import retailrocket_session_knn_pipeline_v80 as pipeline
from scripts import retailrocket_session_knn_role_observer_v80 as native


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


class FakeNativeBackend:
    """Window-local API double with distinct launcher, intermediate and role handles."""

    def __init__(self, *, exit_code=0, fail_api=None):
        self.root_pid, self.parent_pid, self.role_pid = 101, 102, 103
        self.borrowed = 41
        self.role_handle, self.parent_handle, self.self_handle = 42, 43, -1
        self.popen = SimpleNamespace(pid=self.root_pid)
        self.boot = 12345
        first = 116444736000000000 + (1 << 53)
        self.ticks = {self.root_pid: first, self.parent_pid: first + 4, self.role_pid: first + 8}
        self.handles = {self.borrowed: self.root_pid, self.role_handle: self.role_pid,
                        self.parent_handle: self.parent_pid, self.self_handle: self.role_pid, 44: self.root_pid}
        self.parents = {self.role_pid: self.parent_pid, self.parent_pid: self.root_pid}
        self.snapshots = []
        self.replacement_edges = None
        self.live_roles = set(self.handles)
        self.code = exit_code
        self.fail_api = fail_api
        self.events = []
        self.opened = []
        self.closed = []

    def _call(self, name, *args):
        self.events.append((name, *args))
        if self.fail_api == name:
            raise OSError('Synthetic API failure during ' + name)

    def borrow_launcher(self, popen):
        self._call('borrow_launcher', popen.pid)
        if popen is not self.popen:
            raise AssertionError('Observer must borrow the original Popen')
        return self.borrowed

    def current_handle(self):
        self._call('current_handle')
        return self.self_handle

    def open_process(self, pid, *, access, inherit):
        self._call('open_process', pid, access, inherit)
        handle = {self.role_pid: self.role_handle, self.parent_pid: self.parent_handle, self.root_pid: 44}[pid]
        self.opened.append(handle)
        return handle

    def process_id(self, handle):
        self._call('process_id', handle)
        return self.handles[handle]

    def creation_ticks(self, handle):
        self._call('creation_ticks', handle)
        return self.ticks[self.handles[handle]]

    def signal_state(self, handle):
        self._call('signal_state', handle)
        return handle not in self.live_roles

    def exit_code(self, handle):
        self._call('exit_code', handle)
        if handle != self.role_handle or handle in self.live_roles:
            raise AssertionError('Only query the held, signaled role handle')
        return self.code

    def close_handle(self, handle):
        self.closed.append(handle)
        self._call('close_handle', handle)

    def parent_snapshot(self):
        self._call('parent_snapshot')
        edges = self.replacement_edges if self.snapshots and self.replacement_edges is not None else self.parents
        snapshot = dict(edges)
        self.snapshots.append(snapshot)
        return snapshot

    def create_time(self, pid):
        self._call('create_time', pid)
        return float(self.ticks[pid] - 116444736000000000) / 10000000.0

    def identity(self, pid=None):
        pid = self.role_pid if pid is None else pid
        return dict(pid=pid, create_time=self.create_time(pid), boot_time=self.boot)

    def bind(self, **kwargs):
        return native.HeldRole(self.popen, boot_identity=lambda: self.boot, backend=self, **kwargs)

    def admit(self, held, *, identity=None, raw_creation=None):
        identity = self.identity() if identity is None else identity
        raw_creation = str(self.ticks[self.role_pid]) if raw_creation is None else raw_creation
        return held.admit(identity, raw_creation)


def _write(path, value):
    Path(path).write_bytes(cp.encoded(value))


def _admit(name):
    return bundle.admit(name,
        fixture_seal_sha256=os.environ['V80_FIXTURE_SEAL_SHA256'],
        method_seal_sha256=os.environ['V80_METHOD_SEAL_SHA256'])


def _role_path(folder, episode, role, filename):
    return folder / 'control' / 'episodes' / Path(episode).name / 'roles' / role / filename


def _role_descriptor(folder, episode, role, filename):
    return cp.descriptor(folder, _role_path(folder, episode, role, filename).relative_to(folder).as_posix())


class PipelineCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.small = _admit('F-small')
        cls.long = _admit('F-long')
        cls.work = ROOT / 'shop-mysql-runtime' / 'v80' / 'runs' / ('tests-' + uuid.uuid4().hex)
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

    def assert_watch_contract(self):
        class NoTruthValue:
            def __bool__(self):
                raise AssertionError('watch must discard the budget response without testing it')

        class SentinelValueError(ValueError):
            pass

        calls = []

        def check_budget(*args, **kwargs):
            calls.append((args, kwargs))
            return NoTruthValue()

        watch = pipeline._watch_adapter(check_budget)
        self.assertIsNone(watch())
        self.assertEqual(calls, [((), {})])
        sqlite_expression = (lambda: watch() or 0)()
        self.assertIs(type(sqlite_expression), int)
        self.assertEqual(sqlite_expression, 0)
        self.assertEqual(calls, [((), {}), ((), {})])
        for error in (cp.BudgetExceeded('synthetic budget'), SentinelValueError('synthetic sentinel')):
            exception_calls = []

            def failing_budget(*args, **kwargs):
                exception_calls.append((args, kwargs))
                raise error

            with self.assertRaises(type(error)) as caught:
                pipeline._watch_adapter(failing_budget)()
            self.assertIs(caught.exception, error)
            self.assertEqual(exception_calls, [((), {})])

    def assert_role_exit(self, folder, episode, role, code):
        receipt = pipeline._role_receipt(folder, episode, role)
        self.assertIs(type(receipt['exit_code']), int)
        self.assertEqual(receipt['exit_code'], code)
        self.assertEqual(receipt['identity'], cp.read(episode / (role + '_identity.json')))
        self.assertEqual(receipt['observation'], _role_descriptor(folder, episode, role, 'exit_observation.json'))
        self.assertIs(type(receipt['launcher']['exit_code']), int)
        self.assertIs(receipt['normal_observed'], code == 0)
        self.assertIsNone(receipt['stop_request'])
        self.assertFalse(_role_path(folder, episode, role, 'delivery_veto.json').exists())
        return receipt

    def assert_worker_fault(self, folder, episode, fault_point, occurrence):
        prefix = b'V80_WORKER_FAULT '
        marker_lines = [line for line in (episode / 'worker.log').read_bytes().splitlines(keepends=True)
                        if line.startswith(prefix)]
        self.assertEqual(len(marker_lines), 1)
        self.assertTrue(marker_lines[0].endswith(b'\n'))
        marker = json.loads(marker_lines[0][len(prefix):])
        receipt = self.assert_role_exit(folder, episode, 'worker', 9)
        self.assertEqual(cp.encoded(marker), cp.encoded(dict(
            schema='v80_worker_fault_marker', role='worker', episode=episode.name,
            request=cp.descriptor(folder, 'internal/request.json'), identity=receipt['identity'],
            ready=_role_descriptor(folder, episode, 'worker', 'ready.json'),
            ack=_role_descriptor(folder, episode, 'worker', 'ack.json'),
            fault_point=fault_point, occurrence=occurrence, planned_code=9)))
        self.assertFalse((episode / 'worker_failure.json').exists())
        self.assertIsNone(receipt.get('child_failure'))
        return receipt

    def test_A12_true_process_prefix_recovery(self):
        with self.subTest(case_id='A12.prefix_crash_recovery'):
            self.assert_watch_contract()
            folder = self.folder('A12-prefix')
            with self.assertRaises(pipeline._RoleChildError) as caught:
                pipeline.run_pipeline(self.long, folder,
                    scenario=dict(worker_fault='query_verified', worker_after=65), budget_seconds=120)
            episodes = list((folder / 'internal' / 'episodes').iterdir())
            self.assertEqual(len(episodes), 1)
            episode = episodes[0]
            self.assertEqual(cp.read(episode / 'scenario.json'),
                             dict(worker_fault='query_verified', worker_after=65))
            worker_exit = self.assert_worker_fault(folder, episode, 'query_verified', 65)
            outer_exit = self.assert_role_exit(folder, episode, 'pipeline', 1)
            self.assertEqual(caught.exception.role, 'pipeline')
            self.assertEqual(caught.exception.receipt, outer_exit)
            self.assertEqual(caught.exception.receipt_descriptor, cp.descriptor(
                folder, 'control/episodes/' + episode.name + '/pipeline_exit.json'))
            failure_path = (episode / 'pipeline_failure.json').relative_to(folder).as_posix()
            failure = cp.read(folder / failure_path)
            self.assertEqual(outer_exit['child_failure'], cp.descriptor(folder, failure_path))
            self.assertEqual(failure['failed_child_role'], 'worker')
            self.assertIs(type(failure['failed_child_exit_code']), int)
            self.assertEqual(failure['failed_child_exit_code'], 9)
            self.assertEqual(failure['failed_child_observation'], worker_exit['observation'])
            self.assertIs(failure['timeout_stop'], False)
            for receipt in (worker_exit, outer_exit):
                self.assertIn(receipt['identity'], receipt['tracked'])
                for identity in receipt['tracked']:
                    self.assertFalse(cp.Processes().is_alive(identity))
            run_dir = folder / 'internal' / 'cp'
            saved = pipeline._snapshot(run_dir)
            store = cp.CheckpointStore(run_dir, self.long['binding'])
            store._load()
            recovered = store.recover()
            self.assertEqual((recovered['records'], recovered['chunks']), (64, 1))
            prefix_manifest = cp.read(run_dir / 'chunks' / '00000000.json')
            self.assertEqual(prefix_manifest['run_sha256'], store.run_sha)
            self.assertEqual((prefix_manifest['chunk'], prefix_manifest['count'],
                              prefix_manifest['first_ordinal'], prefix_manifest['last_ordinal']), (0, 64, 0, 63))
            self.assertIsNone(prefix_manifest['previous_sha256'])
            prefix = [cp.descriptor(run_dir, 'chunks/00000000.json'), prefix_manifest['payload']]
            golden_path = Path(self.long['bundle_root']) / self.long['manifest']['golden_records']
            golden_prefix = b''.join(golden_path.read_bytes().splitlines(keepends=True)[:64])
            self.assertEqual((run_dir / prefix_manifest['payload']['path']).read_bytes(), golden_prefix)
            self.assertEqual(b''.join(cp.encoded(row) for row in store.iter_records()), golden_prefix)
            self.assertEqual(pipeline._snapshot(run_dir), saved)
            self.assertFalse((folder / 'final_seal.json').exists())
            request = (folder / 'internal' / 'request.json').read_bytes()
            first_budget = cp.read(run_dir / 'budget.json')
            evidence = folder / 'control' / 'case_evidence' / 'A12.prefix_crash_recovery'
            evidence.mkdir(parents=True)
            cp.atomic_json(evidence / 'pre_recovery.json', dict(
                watch_adapter_checked=True, original_episode=episode.name,
                request=cp.descriptor(folder, 'internal/request.json'),
                worker_observation=worker_exit['observation'], pipeline_observation=outer_exit['observation'],
                worker_fault_log=cp.descriptor(folder, (episode / 'worker.log').relative_to(folder).as_posix()),
                checkpoint_before_recovery=saved, validated_prefix=prefix,
                golden_prefix_sha256=hashlib.sha256(golden_prefix).hexdigest()))
            result = pipeline.run_pipeline(self.long, folder)
            self.assertEqual(result['queries'], 129)
            self.assertEqual(result['bootstrap_replicates'], 2000)
            self.assertEqual((folder / 'internal' / 'request.json').read_bytes(), request)
            for descriptor in prefix:
                self.assertEqual(cp.descriptor(run_dir, descriptor['path']), descriptor)
            resumed = folder / 'internal' / 'episodes' / result['publication_episode']
            self.assertNotEqual(resumed, episode)
            self.assertEqual(len(list((folder / 'internal' / 'episodes').iterdir())), 2)
            self.assertEqual(cp.descriptor(run_dir, 'run.json')['sha256'], store.run_sha)
            second_budget = cp.read(run_dir / 'budget.json')
            self.assertEqual(first_budget['run_sha256'], second_budget['run_sha256'])
            self.assertLessEqual(first_budget['consumed_seconds'], second_budget['consumed_seconds'])
            for role in ('worker', 'publisher', 'pipeline'):
                receipt = self.assert_role_exit(folder, resumed, role, 0)
                for identity in receipt['tracked']:
                    self.assertFalse(cp.Processes().is_alive(identity))
            self.assertEqual(pipeline.finalize_stopped(folder, expected=result), result)
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
                self.assert_native_role_guard(scenario)

    def assert_native_role_guard(self, scenario):
        if scenario == 'alive':
            backend = FakeNativeBackend()
            raw = str(backend.ticks[backend.role_pid])
            self.assertEqual(native.self_ready(backend.identity(), backend=backend), raw)
            with self._held_role(backend) as held:
                evidence = backend.admit(held)
                chain = [[backend.role_pid, backend.parent_pid], [backend.parent_pid, backend.root_pid]]
                self.assertEqual(evidence['ancestry']['fresh_chain_before'], chain)
                self.assertEqual(evidence['ancestry']['fresh_chain_after'], chain)
                self.assertEqual(len(backend.snapshots), 2)
                self.assertIsNot(backend.snapshots[0], backend.snapshots[1])
                self.assertIs(evidence['pre_ack_nonsignaled'], True)
                self.assertEqual(evidence['launcher_identity'], backend.identity(backend.root_pid))
                self.assertEqual(evidence['role_identity'], backend.identity())
                held.recheck_pre_ack()
                held.mark_acknowledged()
                self.assertIsNone(held.poll_exit())
                self.assertFalse(any(event[0] == 'exit_code' for event in backend.events))
                backend.live_roles.remove(backend.role_handle)
                observed = held.poll_exit()
                self.assertIs(type(observed), int)
                self.assertEqual(observed, 0)
            self.assertEqual([event for event in backend.events if event[0] == 'open_process'], [
                ('open_process', backend.role_pid, 0x00101000, False),
                ('open_process', backend.parent_pid, 0x00101000, False)])
            self.assertEqual([event for event in backend.events if event[0] == 'exit_code'],
                             [('exit_code', backend.role_handle)])
            backend = FakeNativeBackend()
            with self._held_role(backend) as held:
                backend.admit(held)
                backend.live_roles.remove(backend.role_handle)
                with self.assertRaises(native.RoleObservationError):
                    held.recheck_pre_ack()
                with self.assertRaises(native.RoleObservationError):
                    held.mark_acknowledged()
            backend = FakeNativeBackend()
            with self._held_role(backend) as held:
                identity = backend.identity(backend.root_pid)
                role = backend.admit(held, identity=identity, raw_creation=str(backend.ticks[backend.root_pid]))
                self.assertEqual(role['role_identity'], role['launcher_identity'])
                self.assertEqual(role['ancestry']['fresh_chain_before'], [])
                self.assertEqual(role['ancestry']['fresh_chain_after'], [])
            self.assertEqual(len(backend.opened), 1)
            return
        if scenario == 'nonzero':
            for code in (0, 1, 9, 259, True, 0.0, '0', -1, 2 ** 32):
                backend = FakeNativeBackend(exit_code=code)
                with self._held_role(backend) as held:
                    backend.admit(held)
                    held.recheck_pre_ack()
                    held.mark_acknowledged()
                    backend.live_roles.remove(backend.role_handle)
                    if type(code) is int and code in (0, 1, 9):
                        observed = held.poll_exit()
                        self.assertIs(type(observed), int)
                        self.assertEqual(observed, code)
                    else:
                        with self.assertRaises(native.RoleObservationError) as caught:
                            held.poll_exit()
                        if code == 259:
                            self.assertEqual(caught.exception.raw_exit_code, code)
            return
        if scenario == 'pid_reused':
            backend = FakeNativeBackend()
            ticks = backend.ticks[backend.role_pid]
            self.assertEqual(float(ticks - 116444736000000000), float(ticks + 1 - 116444736000000000))
            for raw in (str(ticks + 1), '0' + str(ticks), ticks, '+{}'.format(ticks)):
                backend = FakeNativeBackend()
                with self._held_role(backend) as held:
                    with self.assertRaises(native.RoleObservationError):
                        backend.admit(held, raw_creation=raw)
            backend = FakeNativeBackend()
            backend.replacement_edges = {backend.role_pid: backend.root_pid}
            with self._held_role(backend) as held:
                with self.assertRaises(native.RoleObservationError):
                    backend.admit(held)
            self.assertEqual(len(backend.snapshots), 2)
            backend = FakeNativeBackend()
            backend.handles[backend.borrowed] = backend.parent_pid
            with self.assertRaises(native.RoleObservationError):
                backend.bind()
            self.assertEqual(backend.opened, [])
            return
        if scenario == 'uncertain':
            for api in ('open_process', 'process_id', 'creation_ticks', 'signal_state', 'parent_snapshot', 'exit_code'):
                backend = FakeNativeBackend()
                with self._held_role(backend) as held:
                    if api == 'exit_code':
                        backend.admit(held)
                        held.recheck_pre_ack()
                        held.mark_acknowledged()
                        backend.live_roles.remove(backend.role_handle)
                        backend.fail_api = api
                        with self.assertRaises((native.RoleObservationError, OSError)):
                            held.poll_exit()
                    else:
                        backend.fail_api = api
                        with self.assertRaises((native.RoleObservationError, OSError)):
                            backend.admit(held)
            return
        if scenario == 'other_boot':
            backend = FakeNativeBackend()
            with self._held_role(backend) as held:
                identity = dict(backend.identity(), boot_time=backend.boot + 1)
                with self.assertRaises(native.RoleObservationError):
                    backend.admit(held, identity=identity)
            return
        backend = FakeNativeBackend()
        with self._held_role(backend) as held:
            backend.admit(held)
            backend.live_roles.remove(backend.role_handle)
            with self.assertRaises(native.RoleObservationError):
                held.poll_exit()  # A self-published ready or fault marker cannot authorize observation.
            self.assertFalse(any(event[0] == 'exit_code' for event in backend.events))

    @contextmanager
    def _held_role(self, backend):
        held = backend.bind()
        try:
            yield held
        finally:
            held.close()
            held.close()  # Cleanup attempts are idempotent even after a rejected admission.
            self.assertCountEqual(backend.closed, backend.opened)
            self.assertNotIn(backend.borrowed, backend.closed)
            self.assertNotIn(backend.self_handle, backend.closed)

    def test_A17_true_process_candidate_unknown_exit(self):
        with self.subTest(case_id='A17.candidate_unknown_exit'):
            folder = self.folder('A17-orphan')
            with self.assertRaises(pipeline._RoleChildError):
                pipeline.run_pipeline(self.small, folder,
                    scenario=dict(worker_fault='after_candidate_commit'), budget_seconds=120)
            run_dir = folder / 'internal' / 'cp'
            original = (run_dir / 'candidate.json').read_bytes()
            first, = (folder / 'internal' / 'episodes').iterdir()
            self.assert_role_exit(folder, first, 'worker', 9)
            self.assertFalse((run_dir / 'normal_worker_exit.json').exists())
            self.assertFalse((run_dir / 'acceptance.json').exists())
            # A fresh attempt must traverse P6 even though the orphan had all
            # stages. This expected crash proves global replay is actually hit.
            with self.assertRaises(pipeline._RoleChildError):
                pipeline.run_pipeline(self.small, folder,
                    scenario=dict(worker_fault='global_replay'))
            self.assertFalse((run_dir / 'candidate.json').exists())
            replays = [p.parent for p in (folder / 'internal' / 'episodes').glob('*/scenario.json')
                       if cp.read(p).get('worker_fault') == 'global_replay']
            self.assertEqual(len(replays), 1)
            self.assert_role_exit(folder, replays[0], 'worker', 9)
            pipeline.run_pipeline(self.small, folder)
            preserved = list((run_dir / 'recovery').glob('*.candidate.json'))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(preserved[0].read_bytes(), original)
            superseded = cp.read(preserved[0].with_name(preserved[0].name + '.superseded.json'))
            self.assertIsNone(superseded['historical_exit_code'])
            self.assertIsNone(superseded['historical_exit_cause'])
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
            first, = (folder / 'internal' / 'episodes').iterdir()
            first_worker = self.assert_role_exit(folder, first, 'worker', 0)
            first_supervisor = self.assert_role_exit(folder, first, 'pipeline', 1)
            normal_fields = json.loads(normal)
            self.assertEqual(normal_fields['worker_identity'], first_worker['identity'])
            self.assertEqual(normal_fields['supervisor_identity'], first_supervisor['identity'])
            self.assertEqual(json.loads(candidate)['worker_identity'], first_worker['identity'])
            workers = len(list((folder / 'internal' / 'episodes').glob('*/worker_exit.json')))
            result = pipeline.run_pipeline(self.small, folder)
            self.assertEqual((run_dir / 'normal_worker_exit.json').read_bytes(), normal)
            self.assertEqual((run_dir / 'candidate.json').read_bytes(), candidate)
            self.assertEqual(len(list((folder / 'internal' / 'episodes').glob('*/worker_exit.json'))), workers)
            self.assertEqual(self.assert_role_exit(folder, first, 'worker', 0), first_worker)
            self.assertIn(first_worker['observation'], result['external_role_evidence'])
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
            for role in ('pipeline', 'worker', 'publisher'):
                self.assert_role_exit(folder, episode, role, 0)
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
        control = target.parent / 'control'
        control.mkdir()
        shutil.copytree(source / 'control' / 'episodes', control / 'episodes')
        return target / 'cp'

    def assert_external_proof_refusal(self, source, mutation):
        cloned = self._copy_science(source)
        folder = cloned.parent.parent
        episode, = (cloned.parent / 'episodes').iterdir()
        if mutation == 'request':
            path = _role_path(folder, episode, 'worker', 'launch.json')
            value = cp.read(path)
            value['episode'] = 'e' * 32
            _write(path, value)
        elif mutation == 'request_deadline':
            path = _role_path(folder, episode, 'worker', 'ready.json')
            value = cp.read(path)
            value['nonce'] = '0' * 32
            _write(path, value)
        elif mutation == 'normal_boot':
            ack_path = _role_path(folder, episode, 'worker', 'ack.json')
            ack_path.unlink()
        else:
            receipt = episode / 'worker_exit.json'
            fields = cp.read(receipt)
            fields['identity'] = fields['launcher']['identity']
            if fields['identity'] == cp.read(episode / 'worker_identity.json'):
                # The board may launch the role directly. Use another observed role
                # so the negative still tests a different identity in that case.
                fields['identity'] = cp.read(episode / 'pipeline_identity.json')
            _write(receipt, fields)
        with self.assertRaises(cp.IntegrityError):
            pipeline.audit_saved(self.small, cloned, source_check=lambda: None)
        self.assertFalse((cloned.parent / 'publisher_proof.json').exists())

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
            episode, = (run_dir.parent / 'episodes').iterdir()
            for role in ('pipeline', 'worker', 'publisher'):
                self.assertIn(_role_descriptor(folder, episode, role, 'ack.json'), proof['role_evidence_prefix'])
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
                if mutation in ('request', 'request_deadline', 'normal_boot', 'observed_exit'):
                    self.assert_external_proof_refusal(folder, mutation)

    def test_A21_stopped_complete_manifest_and_buffered_logs(self):
        folder = self.folder('A21-stopped')
        result = pipeline.run_pipeline(self.small, folder)
        episode = folder / 'internal' / 'episodes' / result['publication_episode']
        with self.subTest(case_id='A21.closed_manifest'):
            self.assertIn(b'publication closed', (episode / 'pipeline.log').read_bytes())
            self.assertIn(b'proof closed', (episode / 'publisher.log').read_bytes())
            self.assertEqual(pipeline.finalize_stopped(folder, expected=result), result)
            self.assertNotIn('final_seal.json', {r['path'] for r in result['internal_evidence']})
            proof = cp.read(episode / 'publisher_proof.json')
            external = result['external_role_evidence']
            evidence_prefix = proof['role_evidence_prefix']
            for role in ('worker', 'publisher', 'pipeline'):
                for filename in ('launch.json', 'ready.json', 'ack.json', 'exit_observation.json'):
                    descriptor = _role_descriptor(folder, episode, role, filename)
                    self.assertIn(descriptor, external)
                    if filename == 'exit_observation.json' and role != 'worker':
                        self.assertNotIn(descriptor, evidence_prefix)
                    else:
                        self.assertIn(descriptor, evidence_prefix)
            for descriptor in evidence_prefix:
                self.assertEqual(cp.descriptor(folder, descriptor['path']), descriptor)
        for mutation in ('extra', 'append', 'missing', 'live'):
            with self.subTest(case_id='A21.' + mutation, mutation=mutation):
                path = episode / ('unexpected.json' if mutation == 'extra' else 'publisher.log')
                self.assert_stopped_evidence_refusal(folder, result, path, mutation, variant='internal')
                if mutation == 'live':
                    backend = FakeNativeBackend(fail_api='close_handle')
                    held = backend.bind()
                    backend.admit(held)
                    with self.assertRaises(OSError):
                        held.close()
                    held.close()
                    self.assertCountEqual(backend.closed, backend.opened)
                    self.assertNotIn(backend.borrowed, backend.closed)
                    continue
                external_name = 'unexpected.json' if mutation == 'extra' else 'ack.json'
                external_path = _role_path(folder, episode, 'worker', external_name)
                self.assert_stopped_evidence_refusal(folder, result, external_path, mutation, variant='external')
                if mutation == 'append':
                    self.assert_stopped_evidence_refusal(folder, result,
                        folder / 'control' / 'final_delivery_veto.json', 'extra', variant='late_veto',
                        case_id='A21.append')
        self.assertEqual(pipeline.finalize_stopped(folder, expected=result), result)

    def assert_stopped_evidence_refusal(self, folder, result, path, mutation, *, variant, case_id=None):
        old = path.read_bytes() if path.exists() else None
        try:
            if mutation == 'extra':
                path.write_bytes(b'{}')
            elif mutation == 'append':
                path.write_bytes(old + b'late append')
            elif mutation == 'missing':
                path.unlink()
            fake = None
            if mutation == 'live':
                fake = FakeProcesses()
                fake.is_alive = lambda identity: True
            with self.assertRaises((cp.IntegrityError, cp.WriterBusy)) as caught:
                pipeline.finalize_stopped(folder, expected=result, process_api=fake)
            evidence = folder / 'control' / 'case_evidence' / mutation / variant
            evidence.mkdir(parents=True)
            mutation_bytes = path.read_bytes() if path.exists() else None
            if mutation_bytes is not None:
                (evidence / 'mutated_bytes.bin').write_bytes(mutation_bytes)
            cp.atomic_json(evidence / 'rejection.json', dict(
                case_id=case_id or 'A21.' + mutation, error_type=type(caught.exception).__name__,
                original_sha256=None if old is None else hashlib.sha256(old).hexdigest(),
                mutated_sha256=None if mutation_bytes is None else hashlib.sha256(mutation_bytes).hexdigest(),
                missing=not path.exists(), restored_only_after_preserving_failure=True))
        finally:
            if old is None and path.exists():
                path.unlink()
            elif old is not None:
                path.write_bytes(old)

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
                episodes = tuple((folder / 'internal' / 'episodes').iterdir())
                if stage == 'P10':
                    disk_only = self._copy_science(folder).parent.parent
                    copied_before = pipeline._snapshot(disk_only / 'internal')
                    with patch.object(pipeline, '_launch_role', side_effect=AssertionError('no new role from disk-only receipt')):
                        with self.assertRaisesRegex(cp.IntegrityError, 'no live delivery ticket'):
                            pipeline.run_pipeline(self.small, disk_only)
                    self.assertEqual(pipeline._snapshot(disk_only / 'internal'), copied_before)
                    self.assertFalse((disk_only / 'final_seal.json').exists())
                result = pipeline.run_pipeline(self.small, folder)
                self.assertEqual(pipeline._snapshot(run_dir), original)
                self.assertEqual(len(list((folder / 'internal' / 'episodes').glob('*/worker_exit.json'))), worker_count)
                if stage == 'P10':
                    self.assertEqual(tuple((folder / 'internal' / 'episodes').iterdir()), episodes)
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
            self.assert_delivery_boundary()
            self.assert_missing_ack_blocks_dispatch()
        with self.subTest(case_id='A23.path_scope'):
            for value in (ROOT / 'shop-mysql-runtime' / 'v75' / 'fixtures' / 'bad',
                          ROOT / 'shop-mysql-runtime' / 'v80' / 'formal' / 'bad'):
                with self.assertRaises(cp.IntegrityError): pipeline._folder(value)
            folder = self.folder('A23-protocol-path')
            folder.mkdir()
            for episode, role in (('../' + '0' * 32, 'worker'), ('0' * 32, '../worker'),
                                  ('0' * 32, 'generic_synthetic')):
                with self.assertRaises(cp.IntegrityError):
                    pipeline._RoleFiles(folder, episode, role)
            target = folder / 'control' / 'episodes'
            target.mkdir(parents=True)
            for alias_name in ('is_symlink', 'is_junction'):
                with patch.object(type(target), alias_name, lambda path: path == target):
                    with self.assertRaises((bundle.SourceAuthorityError, cp.IntegrityError)):
                        pipeline._artifact(folder, target / 'relative_child.json')
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
                        base / 'child.log', base / 'child_exit.json', guard,
                        route='generic_synthetic', resource_check=resource)
                exited = cp.read(base / 'child_exit.json')
                self.assertGreaterEqual(len(calls), 2)
                self.assertIs(exited['normal_observed'], False)
                self.assertIsNotNone(exited['stop_request'])
                self.assertNotIn('observation', exited)
                self.assertFalse((base / 'control' / 'episodes').exists())
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
                                 base / 'worker_exit.json', guard, route='generic_synthetic')
            exited = cp.read(base / 'worker_exit.json')
            self.assertIs(exited['normal_observed'], False)
            self.assertEqual(exited['child_failure'], cp.descriptor(base, 'worker_failure.json'))
            self.assertNotIn('observation', exited)
            self.assertFalse((base / 'control' / 'episodes').exists())

    def assert_delivery_boundary(self):
        for boundary in ('receipt_write', 'guard_write', 'interrupted_before_ticket'):
            folder = self.folder('A23-' + boundary)
            files = pipeline._RoleFiles(folder, 'b' * 32, 'worker')
            files.internal.mkdir(parents=True)
            clock = FakeClock()
            backend = FakeNativeBackend()
            observer_identity = dict(backend.identity(backend.root_pid), pid=100)
            worker_identity = backend.identity()
            cp.atomic_json(files.internal / 'pipeline_identity.json', observer_identity)
            request = dict(created_utc=cp._iso(clock.now), deadline_utc=cp._iso(clock.now + 120),
                           budget_seconds=120, admission=self.small['admission'], binding=self.small['binding'])
            cp.atomic_json(folder / 'internal' / 'request.json', request)
            guard = pipeline.Deadline(request, folder / 'control' / 'budgets' / 'outer.json', clock=clock)
            clock.advance(119)
            fake_time = SimpleNamespace(monotonic=clock.monotonic, sleep=clock.advance)
            process_api = SimpleNamespace(identity=lambda: observer_identity,
                                         boot_identity=lambda: backend.boot, is_alive=lambda identity: False)
            backend.popen.returncode = None
            backend.popen.poll = lambda: backend.popen.returncode
            real_write = cp.atomic_json
            real_held_role = native.HeldRole
            timing_triggered = []

            def fake_popen(command, **options):
                launch = cp.read(files.external / 'launch.json')
                self.assertEqual(command, pipeline._command(files, launch['nonce']))
                self.assertEqual(float(options['env']['V80_ROLE_DEADLINE_MONOTONIC']), 120)
                self.assertFalse((files.external / 'ack.json').exists())
                cp.atomic_json(files.identity, worker_identity)
                cp.atomic_json(files.external / 'ready.json', dict(
                    schema='v80_role_ready', launch=_role_descriptor(folder, files.episode, 'worker', 'launch.json'),
                    nonce=launch['nonce'], identity=cp.descriptor(folder, files.identity.relative_to(folder).as_posix()),
                    pid=worker_identity['pid'], raw_creation=str(backend.ticks[backend.role_pid])))
                return backend.popen

            def write_with_delivery_fault(path, value):
                real_write(path, value)
                path = Path(path)
                if path == files.external / 'ack.json':
                    backend.live_roles.remove(backend.role_handle)
                    backend.popen.returncode = 0
                if path == files.receipt and boundary == 'interrupted_before_ticket':
                    timing_triggered.append(boundary)
                    raise RuntimeError('Synthetic interruption before delivery ticket')
                crossed_in_receipt = path == files.receipt and boundary == 'receipt_write'
                crossed_in_guard = path.parent == guard.path.parent and files.receipt.exists() and boundary == 'guard_write'
                if crossed_in_receipt or crossed_in_guard:
                    timing_triggered.append(boundary)
                    clock.advance(1)

            with ExitStack() as stack:
                stack.enter_context(patch.object(pipeline, 'time', fake_time))
                stack.enter_context(patch.object(pipeline, '_formal_limit', return_value=120))
                stack.enter_context(patch.object(pipeline.subprocess, 'Popen', side_effect=fake_popen))
                stack.enter_context(patch.object(native, 'HeldRole', side_effect=lambda process, **options: real_held_role(process, backend=backend, **options)))
                stack.enter_context(patch.object(cp, 'atomic_json', write_with_delivery_fault))
                if boundary == 'receipt_write':
                    expected_error = self.assertRaises(cp.BudgetExceeded)
                elif boundary == 'guard_write':
                    expected_error = self.assertRaisesRegex(cp.BudgetExceeded, 'after evidence delivery')
                else:
                    expected_error = self.assertRaisesRegex(RuntimeError, 'before delivery ticket')
                with expected_error:
                    pipeline._launch_role(files, guard, process_api=process_api)
            self.assertEqual(timing_triggered, [boundary])
            receipt = cp.read(files.receipt)
            self.assertIs(type(receipt['exit_code']), int)
            self.assertEqual(receipt['exit_code'], 0)
            self.assertIs(receipt['normal_observed'], True)
            veto_path = files.external / 'delivery_veto.json'
            veto = cp.read(veto_path)
            self.assertEqual(veto['receipt'], cp.descriptor(folder, files.receipt.relative_to(folder).as_posix()))
            self.assertEqual(veto['observation'], receipt['observation'])
            with self.assertRaisesRegex(cp.IntegrityError, 'vetoed'):
                pipeline._role_receipt(folder, files.episode, files.role)
            key = pipeline._ticket_key(files)
            self.assertNotIn(key, pipeline._TICKETS)
            binding = pipeline._ticket_binding(files)
            lookalike = pipeline._DeliveryTicket(key, os.getpid(), binding)
            for unauthorized in (None, receipt, lookalike):
                with self.assertRaisesRegex(cp.IntegrityError, 'no live delivery ticket'):
                    pipeline._require_ticket(unauthorized, key, binding)
            self.assertCountEqual(backend.opened, backend.closed)
            self.assertNotIn(backend.borrowed, backend.closed)

    def assert_missing_ack_blocks_dispatch(self):
        folder = self.folder('A23-missing-ack')
        files = pipeline._RoleFiles(folder, 'c' * 32, 'worker')
        files.internal.mkdir(parents=True)
        files.external.mkdir(parents=True)
        clock = FakeClock()
        backend = FakeNativeBackend()
        observer_identity = dict(backend.identity(backend.root_pid), pid=100)
        worker_identity = backend.identity()
        cp.atomic_json(files.internal / 'pipeline_identity.json', observer_identity)
        request = dict(created_utc=cp._iso(clock.now), deadline_utc=cp._iso(clock.now + 120),
                       budget_seconds=120, admission=self.small['admission'], binding=self.small['binding'])
        cp.atomic_json(folder / 'internal' / 'request.json', request)
        nonce = 'a' * 32
        cp.atomic_json(files.external / 'launch.json', pipeline._protocol_binding(files, request, nonce, observer_identity))
        guard = pipeline.Deadline(request, folder / 'control' / 'budgets' / 'worker.json', clock=clock)
        self_ready = native.self_ready
        fake_time = SimpleNamespace(sleep=clock.advance, monotonic=clock.monotonic)
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', pipeline._command(files, nonce)[3:]))
            stack.enter_context(patch.object(pipeline, '_formal_authority', return_value=None))
            stack.enter_context(patch.object(pipeline, '_request_deadline', return_value=guard))
            stack.enter_context(patch.object(pipeline, '_formal_limit', return_value=0.05))
            stack.enter_context(patch.object(pipeline, 'time', fake_time))
            stack.enter_context(patch.object(cp, 'Processes', return_value=SimpleNamespace(identity=lambda: worker_identity)))
            stack.enter_context(patch.object(native, 'self_ready', side_effect=lambda identity: self_ready(identity, backend=backend)))
            worker_body = stack.enter_context(patch.object(pipeline, '_worker', side_effect=AssertionError('work before ack')))
            with self.assertRaises(cp.BudgetExceeded):
                pipeline.main()
            worker_body.assert_not_called()
        self.assertTrue((files.external / 'ready.json').is_file())
        self.assertFalse((files.external / 'ack.json').exists())
        self.assertFalse((folder / 'internal' / 'cp').exists())

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
