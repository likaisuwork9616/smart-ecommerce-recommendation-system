"""Synthetic runner regressions; subprocesses, resource readings and data are fake."""
from contextlib import ExitStack, nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import run_retailrocket_session_knn_v2 as runner
from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_readback_v2 as core
from scripts import retailrocket_session_knn_cost_probe_v2 as probe


class FakeChild:
    pid = 321

    def __init__(self, rss=30):
        self.rss = rss
        self.killed = False

    def is_running(self):
        return not self.killed

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def kill(self):
        self.killed = True


class FakeProcess(FakeChild):
    def __init__(self, pid, rss, children=()):
        super().__init__(rss)
        self.pid = pid
        self.child_list = list(children)

    def children(self, recursive=True):
        return self.child_list

    def create_time(self):
        return 100.0+self.pid


class FakePopen:
    pid = 4321

    def __init__(self, cooperative=True, wait_error=None):
        self.cooperative = cooperative
        self.wait_error = wait_error
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is not None:
            return self.returncode
        if timeout is not None and timeout <= 2:
            if self.wait_error is not None:
                raise self.wait_error
            if not self.cooperative:
                raise subprocess.TimeoutExpired('synthetic worker', timeout)
        self.returncode = 0
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        root_patch = patch.object(runner, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.source = self.root/'input.txt'
        self.source.write_bytes(b'fixed synthetic input')
        self.gate = self.root/'gate.json'
        self.gate.write_text('{"test":"locked"}', encoding='utf-8')
        self.locked = self.root/runner.PREPARED/'locked_scope.json'
        self.put(self.locked, {'reference_gates': [runner.describe(self.gate)]})
        self.put(self.root/runner.SPEC, {'configuration': {'fixed_validation': {'queries': 1}}})
        self.records = [runner.describe(self.source)]
        self.put(self.root/runner.V2_ACCEPTANCE,
                 {'status': 'synthetic_equivalence_and_fault_recovery_accepted',
                  'method_files': self.records})

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def request(self, deadline=None):
        folder = self.root/'synthetic-worker'
        folder.mkdir()
        deadline = deadline or datetime.now(timezone.utc)+timedelta(minutes=5)
        self.put(folder/'request.json', {'deadline_utc': deadline.isoformat(), 'budget_seconds': 300,
                                       'sources': self.records, 'environment': {'synthetic': True}})
        return folder

    def worker_stubs(self, stack, folder, measured=None):
        store = SimpleNamespace(folder=folder/'work', writer=lambda: nullcontext())
        store.folder.mkdir()
        stack.enter_context(patch.object(checkpoint.CheckpointStore, 'create', return_value=store))

        original_connect = sqlite3.connect
        self.read_connections = []

        class TrackedConnection(sqlite3.Connection):
            closed = False

            def close(connection):
                connection.closed = True
                super().close()

        def tracked_connect(*args, **kwargs):
            connection = original_connect(*args, factory=TrackedConnection, **kwargs)
            self.read_connections.append(connection)
            self.addCleanup(connection.close)
            return connection

        stack.enter_context(patch.object(runner.sqlite3, 'connect', side_effect=tracked_connect))

        def build(primary, paths, config, supplied_store, watch):
            watch()
            original_connect(supplied_store.folder/'independent.sqlite').close()
            return {'support': {}, 'fit_audit': {'fit_id': 'synthetic-fit'}}

        model_mock = stack.enter_context(patch.object(core, 'prepare_model', side_effect=build))
        stack.enter_context(patch.object(core, 'load_context', return_value=({}, {})))

        def stratify(db, source, config, support, catalog, watch):
            watch()
            return {'total_queries': 1, 'complete': True}, [{'key': ['1', 0, 1]}]

        def measure(*args):
            self.assertTrue((folder/'frozen_probes.json').exists())
            args[-1]()
            if measured is not None:
                measured()
            return {'kind': 'engineering_cost_only', 'query_checkpoint_io_included': False}

        stack.enter_context(patch.object(probe, 'stratify', side_effect=stratify))
        stack.enter_context(patch.object(probe, 'measure_queries', side_effect=measure))
        return model_mock

    def test_multiphase_worker_preserves_each_immutable_phase_and_stays_no_go(self):
        folder = self.request()
        before = {path: path.read_bytes() for path in (self.source, self.gate, self.locked)}
        with ExitStack() as stack:
            self.worker_stubs(stack, folder)
            result = runner.worker(folder)
        phases = ['source_hash', 'build', 'stratify', 'queries', 'final_source_hash']
        self.assertEqual(set(result['phases_seconds']), set(phases))
        for position, name in enumerate(phases):
            saved = runner.read(folder/f'phase_{name}.json')
            self.assertEqual(saved['phase'], name)
            self.assertEqual(set(saved['phases_seconds']), set(phases[:position+1]))
            self.assertTrue(all(value >= 0 for value in saved['phases_seconds'].values()))
        self.assertFalse((folder/'phase.json').exists())
        self.assertEqual(result['decision'], 'do_not_start_full_readback')
        self.assertIn('full_shape_global_ledger_replay', result['missing_cost_evidence'])
        self.assertIn('full_shape_2000_draw_replay', result['missing_cost_evidence'])
        self.assertIn('full_resume_hash_ledger_and_tail', result['missing_cost_evidence'])
        self.assertFalse(result['full_readback_started'])
        self.assertEqual(result['reserved_test'], 'locked')
        self.assertEqual(result['primary_fits'], 0)
        self.assertEqual(runner.read(folder/'probe_result.json'), result)
        self.assertTrue(self.read_connections)
        self.assertTrue(all(connection.closed for connection in self.read_connections))
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(list(folder.rglob('*acceptance*')))

    def test_source_same_size_tamper_before_build_is_rejected(self):
        folder = self.request()
        self.source.write_bytes(b'other synthetic input')
        with ExitStack() as stack:
            model = self.worker_stubs(stack, folder)
            with self.assertRaisesRegex(ValueError, 'Frozen source identity changed'):
                runner.worker(folder)
            model.assert_not_called()
        self.assertTrue((folder/'phase_source_hash.json').exists())
        self.assertFalse((folder/'probe_result.json').exists())

    def test_source_same_size_tamper_during_measurement_fails_final_hash(self):
        folder = self.request()
        with ExitStack() as stack:
            self.worker_stubs(stack, folder, lambda: self.source.write_bytes(b'other synthetic input'))
            with self.assertRaisesRegex(ValueError, 'Frozen source identity changed'):
                runner.worker(folder)
        self.assertTrue((folder/'phase_final_source_hash.json').exists())
        self.assertFalse((folder/'probe_result.json').exists())
        self.assertTrue(all(connection.closed for connection in self.read_connections))

    def test_absolute_deadline_and_external_stop_prevent_build(self):
        for reason in ('deadline', 'stop_request'):
            with self.subTest(reason=reason):
                folder = self.root/reason
                folder.mkdir()
                deadline = datetime.now(timezone.utc)+timedelta(minutes=-1 if reason == 'deadline' else 5)
                self.put(folder/'request.json', {'deadline_utc': deadline.isoformat(), 'budget_seconds': 300,
                                               'sources': self.records, 'environment': {}})
                if reason == 'stop_request':
                    self.put(folder/'stop_request.json', {'reason': 'synthetic-stop'})
                with ExitStack() as stack:
                    model = self.worker_stubs(stack, folder)
                    with self.assertRaises(TimeoutError):
                        runner.worker(folder)
                    model.assert_not_called()
                self.assertFalse((folder/'probe_result.json').exists())

    def test_final_or_reserved_test_paths_are_never_allowed(self):
        for name in ('retailrocket_session_knn_final_v1', 'retailrocket_session_knn_paired_v1/final_refit',
                     'retailrocket_session_knn_paired_v1/reserved_test',
                     'retailrocket_session_knn_paired_v1/test_usage.jsonl'):
            with self.subTest(name=name):
                path = self.root/'shop-mysql-runtime'/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                with self.assertRaisesRegex(ValueError, 'Final/test scope changed'):
                    runner.check_gates()
                path.unlink()
        self.assertEqual(runner.check_gates()['reserved_test'], 'locked')

    def test_locked_reference_gate_same_size_change_rejected(self):
        self.gate.write_text('{"test":"opened"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Frozen source identity changed'):
            runner.check_gates()

    def test_synthetic_acceptance_and_exact_method_bindings_are_required_before_spawn(self):
        acceptance_path = self.root/runner.V2_ACCEPTANCE
        with patch.object(runner.subprocess, 'Popen') as popen:
            self.put(acceptance_path, {'status': 'incomplete', 'method_files': self.records})
            with self.assertRaisesRegex(ValueError, 'synthetic acceptance'):
                runner.supervised_probe()
            self.put(acceptance_path, {'status': 'synthetic_equivalence_and_fault_recovery_accepted',
                                       'method_files': self.records})
            self.source.write_bytes(b'other synthetic input')
            with self.assertRaisesRegex(ValueError, 'Frozen source identity changed'):
                runner.supervised_probe()
            popen.assert_not_called()

    def supervisor_stubs(self, stack, name, reason, cooperative=True, wait_error=None, monitor_error=None):
        process = FakePopen(cooperative, wait_error)
        child = FakeChild()
        worker = FakeProcess(process.pid, 100, [child])
        supervisor = FakeProcess(5432, 20)
        if monitor_error is not None:
            worker.memory_info = Mock(side_effect=monitor_error)
        limits = {'total_seconds': 10, 'rss_bytes': 1000, 'execution_bytes': 10**7,
                  'minimum_available_bytes': 1, 'minimum_free_bytes': 1}
        if reason == 'rss_limit':
            limits['rss_bytes'] = 100
        if reason == 'execution_disk_limit':
            limits['execution_bytes'] = 0
        elapsed = 11 if reason == 'deadline' else 1
        stack.enter_context(patch.object(runner, 'LIMITS', limits))
        stack.enter_context(patch.object(runner, 'expected_bindings', return_value=self.records))
        stack.enter_context(patch.object(runner, 'environment', return_value={'synthetic': True}))
        stack.enter_context(patch.object(runner.uuid, 'uuid4', return_value=SimpleNamespace(hex=name)))
        first_tick = True

        def monotonic():
            nonlocal first_tick
            if first_tick:
                first_tick = False
                return 100
            return 100+elapsed

        stack.enter_context(patch.object(runner.time, 'monotonic', side_effect=monotonic))
        stack.enter_context(patch.object(runner.time, 'sleep', side_effect=AssertionError('Unexpected monitoring loop')))
        popen = stack.enter_context(patch.object(runner.subprocess, 'Popen', return_value=process))
        stack.enter_context(patch.object(runner.psutil, 'Process', side_effect=lambda pid=None: worker if pid == process.pid else supervisor))
        stack.enter_context(patch.object(runner.psutil, 'boot_time', return_value=50))
        stack.enter_context(patch.object(runner.psutil, 'virtual_memory', return_value=SimpleNamespace(
            available=0 if reason == 'minimum_available_memory' else 1000)))
        stack.enter_context(patch.object(runner.psutil, 'disk_usage', return_value=SimpleNamespace(
            free=0 if reason == 'minimum_free_disk' else 1000)))
        folder = self.root/'shop-mysql-runtime/verification'/('retailrocket-knn-v2-probe-'+name)
        return process, child, popen, folder

    def test_each_external_resource_limit_writes_stop_and_exit_receipts(self):
        for reason in ('deadline', 'rss_limit', 'execution_disk_limit',
                       'minimum_available_memory', 'minimum_free_disk'):
            with self.subTest(reason=reason), ExitStack() as stack:
                process, child, popen, folder = self.supervisor_stubs(stack, reason, reason)
                result = runner.supervised_probe()
                self.assertEqual(result['stop_reason'], reason)
                self.assertEqual(runner.read(folder/'stop_request.json')['reason'], reason)
                self.assertEqual(runner.read(folder/'supervisor_completion.json'), result)
                self.assertEqual(result['exit_code'], 0)
                self.assertEqual(result['peak_sampled_tree_and_supervisor_rss_bytes'], 150)
                self.assertFalse(result['full_readback_started'])
                self.assertEqual(result['reserved_test'], 'locked')
                self.assertFalse(process.killed)
                self.assertFalse(child.killed)
                self.assertIn('--worker', popen.call_args.args[0])
                self.assertFalse(list(folder.rglob('*acceptance*')))

    def test_external_hard_deadline_kills_child_tree_and_records_observed_exit(self):
        with ExitStack() as stack:
            process, child, _, folder = self.supervisor_stubs(stack, 'hard-stop', 'deadline', cooperative=False)
            result = runner.supervised_probe()
        self.assertTrue(process.killed)
        self.assertTrue(child.killed)
        self.assertEqual(result['exit_code'], -9)
        self.assertEqual(result['stop_reason'], 'deadline')
        self.assertTrue((folder/'worker_identity.json').exists())
        self.assertIn('actual_exit_observed_utc', result)

    def test_wait_error_preserves_original_stop_and_still_records_exit(self):
        with ExitStack() as stack:
            process, child, _, folder = self.supervisor_stubs(
                stack, 'wait-failure', 'rss_limit', wait_error=OSError('synthetic wait failure'))
            with self.assertRaisesRegex(OSError, 'synthetic wait failure'):
                runner.supervised_probe()
        self.assertTrue(process.killed)
        self.assertTrue(child.killed)
        self.assertEqual(runner.read(folder/'stop_request.json')['reason'], 'rss_limit')
        receipt = runner.read(folder/'supervisor_completion.json')
        self.assertEqual(receipt['stop_reason'], 'rss_limit')
        self.assertEqual(receipt['exit_code'], -9)

    def test_monitor_error_stops_tree_and_receipt_identifies_interruption(self):
        with ExitStack() as stack:
            process, child, _, folder = self.supervisor_stubs(
                stack, 'monitor-failure', None, monitor_error=RuntimeError('synthetic monitor failure'))
            with self.assertRaisesRegex(RuntimeError, 'synthetic monitor failure'):
                runner.supervised_probe()
        self.assertTrue(process.killed)
        self.assertTrue(child.killed)
        self.assertEqual(runner.read(folder/'stop_request.json')['reason'], 'supervisor_exception_RuntimeError')
        receipt = runner.read(folder/'supervisor_completion.json')
        self.assertEqual(receipt['stop_reason'], 'supervisor_exception_RuntimeError')
        self.assertEqual(receipt['exit_code'], -9)


if __name__ == '__main__':
    unittest.main()
