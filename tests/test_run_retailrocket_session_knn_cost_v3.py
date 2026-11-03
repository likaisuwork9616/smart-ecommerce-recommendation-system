"""Exercise the V3 diagnostic entry on isolated inputs and fake worker processes."""
from contextlib import closing, ExitStack
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import run_retailrocket_session_knn_cost_v3 as runner
from scripts import run_retailrocket_session_knn_v2 as v2
from scripts import retailrocket_session_knn_cost_probe_v2 as probe
from scripts import retailrocket_session_knn_proxy_v3 as proxy
from scripts import retailrocket_session_knn_readback_v2 as core
from tests.test_run_retailrocket_session_knn_v2 import FakeChild, FakePopen, FakeProcess


class CostRunnerTests(unittest.TestCase):
    status = 'v3_cost_diagnostic_entry_synthetic_accepted'

    def setUp(self):
        project = runner.ROOT
        base = project / 'shop-mysql-runtime' / 'verification'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base, prefix='synthetic-v3-runner-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(v2, 'ROOT', self.root))
        self.stack.enter_context(patch.object(runner, 'ROOT', self.root))
        self.input = self.root / 'input.txt'
        self.input.write_bytes(b'synthetic source')
        self.put(self.root / v2.PREPARED / 'locked_scope.json',
                 {'reference_gates': [runner.describe(self.input)]})
        self.put(self.root / runner.SPEC, {'configuration': {'fixed_validation': {'queries': 1}}})
        self.acceptance = self.root / runner.ACCEPTANCE
        self.methods = []
        for namespace in ('scripts', 'tests'):
            for path in sorted((project / namespace).glob('*knn*v3.py')):
                method = self.root / namespace / path.name
                method.parent.mkdir(parents=True, exist_ok=True)
                method.write_bytes(b'# synthetic method\n')
                self.methods.append(runner.describe(method))
        self.put(self.acceptance, {'status': self.status, 'method_files': self.methods})
        self.prior = self.root / runner.PRIOR
        self.model = self.prior / 'work/independent.sqlite'
        self.model.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.model)) as db:
            db.execute('CREATE TABLE sealed(value INTEGER)')
            db.execute('INSERT INTO sealed VALUES(7)')
            db.commit()
        self.stage = self.prior / 'work/stages/reconstruction.json'
        self.put(self.stage, {'receipt': {'support': {}, 'fit_audit': {'fit_id': 'synthetic'}}})
        self.folder = self.root / 'worker'
        self.folder.mkdir()

    @staticmethod
    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def request(self, deadline=None):
        deadline = deadline or datetime.now(timezone.utc) + timedelta(minutes=5)
        self.put(self.folder / 'request.json', {'deadline_utc': deadline.isoformat(),
                 'budget_seconds': 300, 'environment': runner.environment(),
                 'sources': [runner.describe(path) for path in (self.input, self.model, self.stage)]})

    def historical_evidence(self):
        records = [runner.describe(self.input)]
        sources = self.root / 'old-sources'
        sources.mkdir()
        for ordinal in range(439):
            path = sources / f'{ordinal}.txt'
            path.write_bytes(b'x')
            records.append(runner.describe(path))
        environment = runner.environment()
        self.put(self.prior / 'request.json', {'sources': records, 'environment': environment})
        run = self.prior / 'work/run.json'
        self.put(run, {'binding': {'sources': records, 'environment': environment}})
        identity = dict(runner.describe(run), path='run.json')
        self.put(self.prior / 'work/run_identity.json', identity)
        stage = runner.read(self.stage)
        stage.update(run_sha256=identity['sha256'],
                     artifacts=[dict(runner.describe(self.model), path='independent.sqlite')])
        self.put(self.stage, stage)
        self.put(self.root / runner.PRIOR_REPORT, {'evidence': [runner.describe(self.prior / 'request.json'),
                                                               runner.describe(self.stage)]})

    def worker_stubs(self):
        paired = importlib.import_module('scripts.retailrocket_session_knn_pair_probe_v3')
        small_index = runner.index_microbench
        self.stack.enter_context(patch.object(runner, 'index_microbench',
                                              side_effect=lambda f, w: small_index(f, w, rows=12)))
        self.stack.enter_context(patch.object(core, 'load_context', return_value=({}, ['0'])))

        def stratify(db, source, config, support, catalog, watch):
            watch()
            self.assertEqual(db.execute('PRAGMA temp_store').fetchone(), (2,))
            self.assertEqual(db.execute('SELECT value FROM sealed').fetchone(), (7,))
            with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                db.execute('UPDATE sealed SET value=9')
            return {'complete': True, 'queries': 1}, [{'key': ['1', 0, 1]}]

        self.stack.enter_context(patch.object(probe, 'stratify', side_effect=stratify))
        self.stack.enter_context(patch.object(probe, 'measure_queries', return_value={'queries': 1}))
        self.stack.enter_context(patch.object(paired, 'extract_samples', return_value={'queries': 1}))
        self.stack.enter_context(patch.object(paired, 'measure_paired', return_value={'queries': 1}))
        return self.stack.enter_context(patch.object(proxy, 'run_proxy', return_value={
            'kind': 'synthetic_engineering_only', 'real_acceptance': False,
            'full_readback_started': False, 'T_plan': None}))

    def test_entry_requires_v3_status_and_matching_method_bytes(self):
        with patch.object(runner.subprocess, 'Popen') as popen:
            self.put(self.acceptance, {'status': 'v2-accepted', 'method_files': self.methods})
            with self.assertRaises(ValueError):
                runner.supervise()
            self.put(self.acceptance, {'status': self.status, 'method_files': self.methods})
            method = self.root / self.methods[0]['path']
            method.write_bytes(method.read_bytes().replace(b'method', b'change'))
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                runner.supervise()
            popen.assert_not_called()

    def test_entry_rejects_missing_or_duplicate_method_binding(self):
        with patch.object(runner.subprocess, 'Popen') as popen:
            for methods in ([], self.methods[1:], self.methods + [self.methods[0]]):
                with self.subTest(count=len(methods)):
                    self.put(self.acceptance, {'status': self.status, 'method_files': methods})
                    with self.assertRaises(ValueError):
                        runner.supervise()
            popen.assert_not_called()

    def test_sealed_model_descends_from_published_request_and_stage(self):
        self.historical_evidence()
        records = runner.source_bindings()
        self.assertIn(runner.describe(self.model), records)
        self.assertIn(runner.describe(self.input), records)
        runner.verify_bindings(records)
        # A freshly recomputed seal for different bytes cannot replace the
        # stage descriptor anchored in the published previous cost report.
        stage = runner.read(self.stage)
        stage['receipt']['fit_audit']['fit_id'] = 'substitution'
        self.put(self.stage, stage)
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            runner.source_bindings()

    def test_historical_run_identity_change_is_rejected(self):
        self.historical_evidence()
        path = self.prior / 'work/run.json'
        run = runner.read(path)
        run['binding']['sources'].pop()
        self.put(path, run)
        with self.assertRaisesRegex(ValueError, 'identity'):
            runner.source_bindings()

    def test_prior_database_wal_shm_or_rollback_journal_rejects_binding(self):
        self.historical_evidence()
        for suffix in ('-wal', '-shm', '-journal'):
            with self.subTest(suffix=suffix):
                marker = Path(str(self.model) + suffix)
                marker.write_bytes(b'synthetic sidecar')
                with self.assertRaisesRegex(ValueError, '(?i)journal'):
                    runner.source_bindings()
                marker.unlink()

    def test_success_preserves_all_phases_readonly_database_and_no_go(self):
        self.request()
        self.worker_stubs()
        original = self.model.read_bytes()
        result = runner.worker(self.folder)
        self.assertEqual(self.model.read_bytes(), original)
        self.assertFalse(result['full_readback_started'])
        self.assertFalse(result['reused_model_build_timed_this_window'])
        self.assertEqual(result['reserved_test'], 'locked')
        self.assertEqual(result['decision'], 'do_not_start_full_readback')
        self.assertIsNone(result['T_plan'])
        self.assertTrue(result['missing'])
        self.assertEqual(runner.read(self.folder / 'diagnostic_result.json'), result)
        required = {'source_and_sealed_model_hash', 'synthetic_index_microbenchmark', 'load_context',
                    'full_stratification_profiled', 'exact_rank_probes', 'extract_selected_paired_sources',
                    'selected_four_arm_and_checkpoint', 'full_shape_synthetic_proxy', 'final_source_and_model_hash'}
        self.assertTrue(required <= set(result['phases']))
        for phase, stats in result['phases'].items():
            self.assertEqual(runner.read(self.folder / f'{phase}_started.json')['phase'], phase)
            self.assertEqual(runner.read(self.folder / f'{phase}_receipt.json'), dict(stats, phase=phase))
            self.assertTrue(stats['completed'])
            self.assertIsNone(stats['error_type'])
        watch = runner.read(self.folder / 'watch_statistics.json')
        self.assertGreaterEqual(watch['calls'], watch['full_checks'])
        self.assertGreaterEqual(watch['stop_checks'], 2 * len(required))
        self.assertFalse(list(self.folder.rglob('*acceptance*')))

    def test_proxy_failure_keeps_completed_phases_and_partial_receipt(self):
        self.request()
        self.worker_stubs().side_effect = TimeoutError('synthetic proxy cutoff')
        with self.assertRaisesRegex(TimeoutError, 'proxy cutoff'):
            runner.worker(self.folder)
        paired = runner.read(self.folder / 'selected_four_arm_and_checkpoint_receipt.json')
        self.assertTrue(paired['completed'])
        self.assertTrue((self.folder / 'paired_measurements.json').exists())
        receipt = runner.read(self.folder / 'full_shape_synthetic_proxy_receipt.json')
        self.assertFalse(receipt['completed'])
        self.assertEqual(receipt['error_type'], 'TimeoutError')
        failure = runner.read(self.folder / 'failure.json')
        self.assertEqual(failure['decision'], 'do_not_start_full_readback')
        self.assertIsNone(failure['T_plan'])
        self.assertTrue((self.folder / 'watch_statistics.json').exists())
        self.assertFalse((self.folder / 'diagnostic_result.json').exists())
        self.assertFalse((self.folder / 'final_source_and_model_hash_started.json').exists())

    def test_changed_model_after_request_rejected_before_measurements(self):
        self.request()
        with self.model.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            runner.worker(self.folder)
        self.assertFalse(runner.read(self.folder / 'source_and_sealed_model_hash_receipt.json')['completed'])
        self.assertFalse((self.folder / 'synthetic_index_microbenchmark_started.json').exists())

    def test_sidecar_appearing_after_manifest_is_rejected_by_worker(self):
        self.request()
        self.worker_stubs()
        Path(str(self.model) + '-shm').write_bytes(b'synthetic sidecar')
        with self.assertRaisesRegex(ValueError, '(?i)journal'):
            runner.worker(self.folder)
        self.assertFalse((self.folder / 'full_stratification_profiled_started.json').exists())
        self.assertTrue((self.folder / 'failure.json').exists())

    def test_final_hash_catches_source_changed_after_initial_check(self):
        self.request()
        proxy_call = self.worker_stubs()

        def mutate(*args):
            self.input.write_bytes(b'synthetic change')
            return {'real_acceptance': False}

        proxy_call.side_effect = mutate
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            runner.worker(self.folder)
        self.assertTrue(runner.read(self.folder / 'full_shape_synthetic_proxy_receipt.json')['completed'])
        self.assertFalse(runner.read(self.folder / 'final_source_and_model_hash_receipt.json')['completed'])
        self.assertFalse((self.folder / 'diagnostic_result.json').exists())

    def test_expired_worker_deadline_records_stop_before_first_phase_body(self):
        self.request(deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
        with self.assertRaises(TimeoutError):
            runner.worker(self.folder)
        self.assertFalse(runner.read(self.folder / 'source_and_sealed_model_hash_receipt.json')['completed'])
        stats = runner.read(self.folder / 'watch_statistics.json')
        self.assertEqual((stats['calls'], stats['full_checks'], stats['stop_checks']), (1, 1, 0))

    def test_external_deadline_kills_uncooperative_worker_and_its_child(self):
        process = FakePopen(cooperative=False)
        child = FakeChild()
        worker = FakeProcess(process.pid, 10, [child])
        supervisor = FakeProcess(77, 10)
        limits = dict(runner.LIMITS, total_seconds=10)
        self.stack.enter_context(patch.object(runner, 'LIMITS', limits))
        self.stack.enter_context(patch.object(runner, 'source_bindings', return_value=[]))
        self.stack.enter_context(patch.object(runner.time, 'monotonic', side_effect=[100, 111, 111, 112]))
        self.stack.enter_context(patch.object(runner.psutil, 'Process',
            side_effect=lambda pid=None: worker if pid == process.pid else supervisor))
        self.stack.enter_context(patch.object(runner.uuid, 'uuid4', return_value=SimpleNamespace(hex='fixture')))
        self.stack.enter_context(patch.object(runner.subprocess, 'Popen', return_value=process))
        receipt = runner.supervise()
        self.assertTrue(process.killed and child.killed)
        self.assertEqual(receipt['exit_code'], -9)
        self.assertEqual(receipt['stop_reason'], 'deadline')
        self.assertTrue(receipt['actual_exit_observed_utc'])
        folder = self.root / receipt['namespace']
        self.assertEqual(runner.read(folder / 'stop_request.json')['reason'], 'deadline')
        self.assertEqual(runner.read(folder / 'supervisor_completion.json'), receipt)
        self.assertFalse(runner.read(folder / 'request.json')['full_readback_enabled'])
        self.assertFalse(list(folder.rglob('*acceptance*')))


if __name__ == '__main__':
    unittest.main()
