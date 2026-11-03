"""Synthetic crash/recovery and identity tests; never opens real research data."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import psutil

from scripts import retailrocket_session_knn_checkpoint_v2 as cp


ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self):
        self.wall = 1000.0
        self.mono = 50.0

    def utc(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


class FakeProcesses:
    def __init__(self):
        self.current = {'pid': 123, 'create_time': 950.0, 'boot_time': 800.0}
        self.live = [deepcopy(self.current)]
        self.denied = False

    def identity(self):
        return deepcopy(self.current)

    def is_alive(self, identity):
        if self.denied:
            raise psutil.AccessDenied(identity['pid'])
        return identity in self.live

    def supervisor(self, reboot=False):
        self.live = []
        self.current = {'pid': 999, 'create_time': 1001.0,
                        'boot_time': 1000.0 if reboot else 800.0}
        self.live.append(deepcopy(self.current))


class CheckpointTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Native Windows boot identity')
    def test_native_boot_identity_is_stable_across_processes(self):
        current = cp.Processes().boot_identity()
        self.assertIs(type(current), int)
        script = ('from scripts.retailrocket_session_knn_checkpoint_v2 import Processes; '
                  'print(Processes().boot_identity())')
        for _ in range(3):
            value = subprocess.check_output([sys.executable, '-B', '-c', script],
                                            cwd=ROOT, text=True).strip()
            self.assertEqual(int(value), current)
        self.assertTrue(cp.Processes().is_alive(cp.Processes().identity()))

    @unittest.skipUnless(os.name == 'nt', 'Native Windows boot identity')
    def test_native_boot_identity_errors_fail_closed(self):
        with patch('ctypes.WinDLL') as native:
            native.return_value.NtQuerySystemInformation.return_value = -1
            with self.assertRaises(RuntimeError):
                cp.Processes().boot_identity()
        with patch('ctypes.WinDLL') as native:
            native.return_value.NtQuerySystemInformation.return_value = 0
            with self.assertRaises(RuntimeError):
                cp.Processes().boot_identity()

    def setUp(self):
        base = ROOT / 'shop-mysql-runtime/verification/retailrocket-session-knn-checkpoint-v2-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'input.txt').write_bytes(b'fixed synthetic input\n')
        self.binding = {'sources': cp.bind_sources(self.source, ['input.txt']),
                        'algorithm': 'synthetic-only'}
        self.clock, self.processes = FakeClock(), FakeProcesses()
        self.options = {'source_root': self.source, 'clock': self.clock, 'process_api': self.processes}

    def create(self, **kwargs):
        options = {'expected_queries': 7, 'chunk_queries': 2}
        options.update(kwargs)
        deadline = options.pop('deadline_utc', 1100.0)
        budget = options.pop('budget_seconds', 90.0)
        return cp.CheckpointStore.create(self.root / 'run', self.binding, deadline, budget,
                                         **self.options, **options)

    def reopen(self, **kwargs):
        options = dict(self.options, **kwargs)
        return cp.CheckpointStore.open(self.root / 'run', self.binding, **options)

    def record(self, store, ordinal):
        store.append_verified(ordinal, ['1', 0, ordinal],
                              {'precise': '0.123456789012345678901234567890',
                               'delta_hex': (ordinal / 10).hex()})

    def start(self, store):
        store.seal_stage('reconstruction', {'checked': True})

    def fill(self, store, count=7):
        self.start(store)
        for ordinal in range(count):
            self.record(store, ordinal)
        store.flush_chunk()

    def complete_worker(self, store):
        worker = self.processes.identity()
        with store.writer():
            self.fill(store)
            store.seal_stage('global', {'queries': 7})
            store.seal_stage('bootstrap', {'draws': 2000})
            candidate = store.write_candidate({'status': 'synthetic_verified'})
        return candidate, worker

    def write(self, path, value):
        path.write_bytes(cp.encoded(value))

    def test_roundtrip_seven_queries_cross_chunks_and_exact_values(self):
        store = self.create()
        with store.writer():
            self.fill(store)
        reopened = self.reopen()
        summary = reopened.recover()
        self.assertEqual((summary['records'], summary['chunks']), (7, 4))
        rows = list(reopened.iter_records())
        self.assertEqual([row['ordinal'] for row in rows], list(range(7)))
        self.assertEqual(rows[-1]['payload']['delta_hex'], (0.6).hex())
        self.assertEqual(rows[-1]['payload']['precise'], '0.123456789012345678901234567890')
        self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_deadline_requires_explicit_timezone_and_existing_run_rejected(self):
        with self.assertRaises(ValueError):
            self.create(deadline_utc='2030-01-01T00:00:00')

    def test_source_path_traversal_and_duplicate_rejected(self):
        for names in (['../input.txt'], ['/input.txt'], ['input.txt', 'input.txt'], ['x\\y']):
            with self.subTest(names=names), self.assertRaises(cp.IntegrityError):
                cp.bind_sources(self.source, names)

    def test_same_size_source_mutation_refuses_open(self):
        self.create()
        (self.source / 'input.txt').write_bytes(b'other synthetic input\n')
        with self.assertRaises(cp.IntegrityError):
            self.reopen()

    def test_binding_change_refuses_open(self):
        self.create()
        with self.assertRaises(cp.IntegrityError):
            cp.CheckpointStore.open(self.root / 'run', dict(self.binding, algorithm='changed'), **self.options)

    def test_external_source_verifier_is_explicit_and_invoked(self):
        calls = []
        opts = dict(self.options)
        opts.pop('source_root')
        store = cp.CheckpointStore.create(self.root / 'run', self.binding, 1100, 90,
            external_source_verifier=lambda: calls.append('checked'), **opts)
        with store.writer():
            pass
        self.assertGreaterEqual(len(calls), 2)

    def test_missing_source_verifier_refused(self):
        opts = dict(self.options)
        opts.pop('source_root')
        with self.assertRaises(ValueError):
            cp.CheckpointStore.create(self.root / 'run', self.binding, 1100, 90, **opts)

    def test_uncommitted_tail_preserved_and_recomputed(self):
        store = self.create()
        with store.writer():
            self.start(store)
            self.record(store, 0)
        self.assertEqual(store.recover()['records'], 0)
        orphan = list((store.folder / 'payloads').iterdir())
        with self.reopen().writer() as resumed:
            self.record(resumed, 0); self.record(resumed, 1)
        self.assertTrue(orphan[0].exists())
        self.assertEqual(self.reopen().recover()['records'], 2)

    def test_half_written_payload_is_not_a_commit(self):
        def fail(event):
            if event == 'payload_half_written':
                raise RuntimeError('synthetic abrupt stop')
        store = self.create(fault=fail)
        with self.assertRaises(RuntimeError), store.writer():
            self.start(store); self.record(store, 0)
        self.assertEqual(self.reopen().recover()['records'], 0)
        self.assertEqual(len(list((store.folder / 'payloads').iterdir())), 1)

    def test_flush_before_manifest_failure_keeps_tail_only(self):
        for event in ('after_payload_fsync', 'before_manifest_commit'):
            with self.subTest(event=event):
                folder = self.root / ('run_' + event)
                def fail(point):
                    if point == event:
                        raise RuntimeError('crash before commit')
                store = cp.CheckpointStore.create(folder, self.binding, 1100, 90,
                    expected_queries=7, max_chunk_rows=2, fault=fail, **self.options)
                with self.assertRaises(RuntimeError), store.writer():
                    self.start(store); self.record(store, 0); self.record(store, 1)
                reopened = cp.CheckpointStore.open(folder, self.binding, **self.options)
                self.assertEqual(reopened.recover()['records'], 0)

    def test_commit_before_latest_is_recovered(self):
        def fail(event):
            if event == 'after_manifest_commit':
                raise RuntimeError('crash after commit')
        store = self.create(fault=fail)
        with self.assertRaises(RuntimeError), store.writer():
            self.start(store); self.record(store, 0); self.record(store, 1)
        self.assertFalse((store.folder / 'latest.json').exists())
        self.assertEqual(self.reopen().recover()['records'], 2)

    def test_timed_checkpoint_only_at_safe_query_boundary(self):
        store = self.create(chunk_queries=64, chunk_seconds=2)
        with store.writer():
            self.start(store); self.record(store, 0)
            self.clock.advance(2)
            self.assertEqual(store.recover()['records'], 0)
            self.record(store, 1)
            self.assertEqual(store.recover()['records'], 2)
        self.assertEqual(store.recover()['records'], 2)

    def test_committed_payload_corruption_is_sticky_integrity_failure(self):
        store = self.create()
        with store.writer():
            self.fill(store)
        first = cp.read(store.folder / 'chunks/00000000.json')['payload']['path']
        path = store.folder / first
        data = path.read_bytes(); path.write_bytes(data.replace(b'0.123', b'0.923', 1))
        with self.assertRaises(cp.IntegrityError), self.reopen().writer():
            pass
        self.assertTrue((store.folder / 'integrity_failed.json').exists())
        with self.assertRaises(cp.IntegrityError):
            self.reopen()

    def test_chunk_gap_duplicate_reorder_and_prev_sha_refused(self):
        for failure in ('gap', 'duplicate', 'reorder', 'prev'):
            with self.subTest(failure=failure):
                folder = self.root / failure
                store = cp.CheckpointStore.create(folder, self.binding, 1100, 90,
                    expected_queries=7, chunk_queries=2, **self.options)
                with store.writer():
                    self.fill(store)
                one = folder / 'chunks/00000001.json'
                if failure == 'gap':
                    one.unlink()
                elif failure == 'duplicate':
                    (folder / 'chunks/copy.json').write_bytes(one.read_bytes())
                elif failure == 'reorder':
                    zero = folder / 'chunks/00000000.json'
                    old = zero.read_bytes(); zero.write_bytes(one.read_bytes()); one.write_bytes(old)
                else:
                    value = cp.read(one); value['previous_sha256'] = '0' * 64; self.write(one, value)
                with self.assertRaises(cp.IntegrityError):
                    store.recover()

    def test_missing_last_committed_chunk_detected_from_hint(self):
        store = self.create()
        with store.writer():
            self.fill(store)
        (store.folder / 'chunks/00000003.json').unlink()
        with self.assertRaises(cp.IntegrityError):
            store.recover()

    def test_stale_lower_latest_is_only_a_hint(self):
        store = self.create()
        with store.writer():
            self.start(store); self.record(store, 0); self.record(store, 1)
            earlier = (store.folder / 'latest.json').read_bytes()
            self.record(store, 2); self.record(store, 3)
        (store.folder / 'latest.json').write_bytes(earlier)
        self.assertEqual(self.reopen().recover()['records'], 4)

    def test_append_rejects_duplicate_key_gap_and_bool_ordinal(self):
        store = self.create()
        with store.writer():
            self.start(store); self.record(store, 0)
            for ordinal, key in ((2, ['1', 0, 1]), (1, ['1', 0, 0]), (True, ['1', 0, 1])):
                with self.subTest(ordinal=ordinal), self.assertRaises(cp.IntegrityError):
                    store.append_verified(ordinal, key, {})

    def test_os_lock_blocks_second_writer_in_same_process(self):
        store = self.create()
        second = self.reopen()
        with store.writer(), self.assertRaises(cp.WriterBusy), second.writer():
            pass

    def test_pid_reuse_is_not_the_same_writer_and_unknown_exit_preserved(self):
        store = self.create()
        with store.writer():
            pass
        owner = cp.read(store.folder / 'writer_owner.json')
        owner['state'] = 'active'; self.write(store.folder / 'writer_owner.json', owner)
        self.processes.current['create_time'] = 999.0
        self.processes.live = [deepcopy(self.processes.current)]
        with self.reopen().writer():
            pass
        audits = list((store.folder / 'recovery').glob('*.json'))
        self.assertEqual(len(audits), 1)
        self.assertIsNone(cp.read(audits[0])['historical_exit_cause'])

    def test_unknown_process_access_denied_is_fail_closed(self):
        store = self.create()
        with store.writer():
            pass
        owner = cp.read(store.folder / 'writer_owner.json')
        owner['state'] = 'active'; self.write(store.folder / 'writer_owner.json', owner)
        self.processes.denied = True
        with self.assertRaises(psutil.AccessDenied), self.reopen().writer():
            pass

    def test_live_recorded_writer_never_stolen(self):
        store = self.create()
        with store.writer():
            pass
        owner = cp.read(store.folder / 'writer_owner.json')
        owner['state'] = 'active'; self.write(store.folder / 'writer_owner.json', owner)
        with self.assertRaises(cp.WriterBusy), self.reopen().writer():
            pass

    def test_budget_is_cumulative_across_restart_and_downtime(self):
        store = self.create()
        with store.writer():
            self.clock.advance(40); store.check_budget(persist=True)
        self.clock.advance(45)
        self.assertEqual(self.reopen().check_budget()['consumed_seconds'], 85)
        self.clock.advance(6)
        with self.assertRaises(cp.BudgetExceeded), self.reopen().writer():
            pass
        self.assertTrue((store.folder / 'stop_requested.json').exists())

    def test_utc_rollback_and_absolute_deadline_refused(self):
        store = self.create()
        with store.writer():
            self.clock.advance(10); store.check_budget(persist=True)
            self.clock.wall -= 1
            with self.assertRaises(cp.BudgetExceeded):
                store.check_budget()
        self.clock.wall = 1100
        with self.assertRaises(cp.BudgetExceeded):
            self.reopen().check_budget()

    def test_submicrosecond_clock_roundtrip_does_not_invent_rollback(self):
        for index, value in enumerate((1000.0000004, 1000.0000006)):
            with self.subTest(clock=value):
                self.clock.wall = value
                folder = self.root / f'fractional-clock-{index}'
                store = cp.CheckpointStore.create(folder, self.binding, 1100, 90,
                                                  **self.options)
                with store.writer():
                    for _ in range(3):
                        store.check_budget(persist=True)
                budget = cp.read(folder / 'budget.json')
                self.assertEqual(budget['last_utc_epoch'], value)
                self.assertNotEqual(cp._time(budget['last_utc']), value)
                resumed = cp.CheckpointStore.open(folder, self.binding, **self.options)
                with resumed.writer():
                    resumed.check_budget(persist=True)
                    self.clock.wall -= 0.0000001
                    with self.assertRaises(cp.BudgetExceeded):
                        resumed.check_budget()

    def test_disk_full_before_manifest_cannot_publish_success(self):
        store = self.create()
        with store.writer():
            self.start(store); self.record(store, 0)
            with patch.object(cp.os, 'fsync', side_effect=OSError(28, 'synthetic disk full')):
                with self.assertRaises(OSError):
                    store.flush_chunk()
        self.assertEqual(self.reopen().recover()['records'], 0)
        self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_stage_artifact_sha_checked(self):
        store = self.create()
        with store.writer():
            artifact = store.folder / 'synthetic.sqlite'
            artifact.write_bytes(b'closed synthetic db')
            store.seal_stage('reconstruction', {'checked': True}, artifacts=['synthetic.sqlite'])
            self.assertTrue(store.get_stage('reconstruction')['checked'])
            artifact.write_bytes(b'broken synthetic db')
            with self.assertRaises(cp.IntegrityError):
                store.get_stage('reconstruction')

    def test_global_requires_complete_roster_and_bootstrap_requires_global(self):
        store = self.create()
        with store.writer():
            self.start(store); self.record(store, 0); store.flush_chunk()
            with self.assertRaises(cp.IntegrityError):
                store.seal_stage('global', {})
            with self.assertRaises(cp.IntegrityError):
                store.seal_stage('bootstrap', {})
            with self.assertRaises(cp.IntegrityError):
                store.write_candidate({})

    def test_candidate_is_not_acceptance_and_live_worker_blocks_finalization(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        self.assertFalse((store.folder / 'acceptance.json').exists())
        with self.assertRaises(cp.WriterBusy):
            store.finalize(candidate, worker, 0)

    def test_normal_exit_and_all_stages_allow_supervisor_acceptance(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        self.processes.supervisor()
        accepted = self.reopen().finalize(candidate, worker, 0)
        self.assertEqual(accepted['ledger']['records'], 7)
        self.assertEqual(accepted['reserved_test'], 'locked')
        self.assertFalse(accepted['primary_recomputed'])

    def test_nonzero_exit_and_reboot_unknown_exit_cannot_accept(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        self.processes.supervisor(reboot=True)
        with self.assertRaises(cp.IntegrityError):
            self.reopen().finalize(candidate, worker, 0)
        self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_nonzero_exit_rejected(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        self.processes.supervisor()
        with self.assertRaises(cp.IntegrityError):
            self.reopen().finalize(candidate, worker, 15)
        self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_candidate_or_stage_tamper_before_finalization_rejected(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        path = store.folder / 'stages/global.json'
        value = cp.read(path); value['receipt']['queries'] = 6; self.write(path, value)
        self.processes.supervisor()
        with self.assertRaises(cp.IntegrityError):
            self.reopen().finalize(candidate, worker, 0)

    def test_failure_before_acceptance_preserves_exit_and_can_finish_same_evidence(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        self.processes.supervisor()
        def fail(event):
            if event == 'before_acceptance_commit':
                raise RuntimeError('supervisor interrupted')
        with self.assertRaises(RuntimeError):
            self.reopen(fault=fail).finalize(candidate, worker, 0)
        self.assertTrue((store.folder / 'normal_worker_exit.json').exists())
        self.assertFalse((store.folder / 'acceptance.json').exists())
        self.reopen().finalize(candidate, worker, 0)
        self.assertTrue((store.folder / 'acceptance.json').exists())

    def test_orphan_candidate_is_preserved_before_complete_replay(self):
        store = self.create()
        old_sha, worker = self.complete_worker(store)
        original = (store.folder / 'candidate.json').read_bytes()
        self.processes.supervisor()
        resumed = self.reopen()
        with resumed.writer():
            receipt = resumed.supersede_candidate()
            self.assertIsNone(receipt['historical_exit_code'])
            self.assertIsNone(receipt['historical_exit_cause'])
            archive = resumed.folder / receipt['previous_candidate']['path']
            self.assertEqual(archive.read_bytes(), original)
            self.assertFalse((resumed.folder / 'normal_worker_exit.json').exists())
            self.assertFalse((resumed.folder / 'candidate.json').exists())
            new_sha = resumed.write_candidate({'complete_replay': True})
        self.assertNotEqual(new_sha, old_sha)
        self.assertNotEqual(cp.read(resumed.folder / 'candidate.json')['worker_identity'], worker)

    def test_live_candidate_worker_and_unknown_identity_cannot_be_superseded(self):
        store = self.create()
        self.complete_worker(store)
        with self.reopen().writer() as resumed:
            with self.assertRaises(cp.WriterBusy):
                resumed.supersede_candidate()
            self.processes.denied = True
            with self.assertRaises(psutil.AccessDenied):
                resumed.supersede_candidate()
        self.assertTrue((store.folder / 'candidate.json').exists())

    def test_orphan_candidate_tamper_refuses_supersede(self):
        store = self.create()
        self.complete_worker(store)
        candidate = cp.read(store.folder / 'candidate.json')
        candidate['ledger']['records'] -= 1
        self.write(store.folder / 'candidate.json', candidate)
        self.processes.supervisor()
        with self.assertRaises(cp.IntegrityError), self.reopen().writer() as resumed:
            resumed.supersede_candidate()
        self.assertTrue((store.folder / 'candidate.json').exists())

    def test_known_normal_exit_is_not_superseded(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        self.processes.supervisor()
        def fail(event):
            if event == 'before_acceptance_commit':
                raise RuntimeError('interrupted supervisor')
        with self.assertRaises(RuntimeError):
            self.reopen(fault=fail).finalize(candidate, worker, 0)
        with self.reopen().writer() as resumed:
            with self.assertRaises(cp.WriterBusy):
                resumed.supersede_candidate()
        self.reopen().finalize(candidate, worker, 0)

    def test_fault_after_candidate_commit_leaves_only_candidate(self):
        store = self.create()
        def fail(event):
            if event == 'after_candidate_commit':
                raise RuntimeError('worker interrupted after publishing candidate')
        store.fault = fail
        with self.assertRaises(RuntimeError):
            self.complete_worker(store)
        self.assertTrue((store.folder / 'candidate.json').exists())
        self.assertFalse((store.folder / 'normal_worker_exit.json').exists())
        self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_deadline_rechecked_after_expensive_completion_verification(self):
        store = self.create()
        with store.writer():
            self.fill(store)
            store.seal_stage('global', {'queries': 7})
            store.seal_stage('bootstrap', {'draws': 2})
            complete = store._complete_checks
            def delayed_completion():
                result = complete()
                self.clock.advance(100)
                return result
            with patch.object(store, '_complete_checks', side_effect=delayed_completion):
                with self.assertRaises(cp.BudgetExceeded):
                    store.write_candidate({})
        self.assertFalse((store.folder / 'candidate.json').exists())

    def test_recovery_rechecks_sealed_reconstruction_artifact(self):
        store = self.create()
        with store.writer():
            artifact = store.folder / 'synthetic.sqlite'
            artifact.write_bytes(b'closed database')
            store.seal_stage('reconstruction', {}, artifacts=['synthetic.sqlite'])
        artifact.write_bytes(b'mutated database')
        with self.assertRaises(cp.IntegrityError), self.reopen().writer():
            pass
        self.assertTrue((store.folder / 'integrity_failed.json').exists())

    def test_completed_run_refuses_new_writer(self):
        store = self.create()
        candidate, worker = self.complete_worker(store)
        self.processes.supervisor()
        self.reopen().finalize(candidate, worker, 0)
        with self.assertRaises(cp.IntegrityError), self.reopen().writer():
            pass
        self.assertFalse((store.folder / 'integrity_failed.json').exists())

    def test_reconstruction_artifact_is_not_rehashed_per_query(self):
        store = self.create()
        with store.writer():
            artifact = store.folder / 'synthetic.sqlite'
            artifact.write_bytes(b'closed database')
            store.seal_stage('reconstruction', {}, artifacts=['synthetic.sqlite'])
            original = cp.descriptor
            counted = []
            def observed(root, name):
                if name == 'synthetic.sqlite':
                    counted.append(name)
                return original(root, name)
            with patch.object(cp, 'descriptor', side_effect=observed):
                for ordinal in range(7):
                    self.record(store, ordinal)
            self.assertEqual(len(counted), 1)

    def test_atomic_json_does_not_overwrite(self):
        target = self.root / 'record.json'
        cp.atomic_json(target, {'one': 1})
        with self.assertRaises(FileExistsError):
            cp.atomic_json(target, {'two': 2})
        self.assertEqual(cp.read(target), {'one': 1})


if __name__ == '__main__':
    unittest.main()
