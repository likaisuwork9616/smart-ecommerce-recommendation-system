"""Real processes test exit, deadline and orphan cleanup of engineering windows."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import psutil

from scripts import retailrocket_session_knn_cost_window_v5 as window


class WindowTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1]/'shop-mysql-runtime/verification'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base, prefix='synthetic-v5-window-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = [{'path': 'synthetic-input', 'bytes': 1, 'sha256': 'fixture'}]
        self.limits = dict(window.LIMITS, minimum_available_bytes=1, minimum_free_bytes=1)

    def run_code(self, code, **kwargs):
        return window.run_window(self.root/'run', [sys.executable, '-B', '-c', code],
            self.source, 'rebuild', limits=self.limits, poll_seconds=.05, **kwargs)

    def test_normal_exit_saved_with_no_acceptance(self):
        receipt = self.run_code('print("synthetic")', budget_seconds=5)
        self.assertEqual(receipt['exit_code'], 0)
        self.assertIsNone(receipt['stop_reason'])
        self.assertEqual(receipt['tracked_processes_alive_after_cleanup'], 0)
        self.assertFalse(receipt['full_readback_started'])
        request = json.loads((self.root/'run/request.json').read_text(encoding='utf-8'))
        self.assertFalse(request['full_readback_enabled'])
        self.assertEqual(request['reserved_test'], 'locked')
        self.assertFalse(list((self.root/'run').rglob('*acceptance*')))

    def test_failure_exit_is_not_success(self):
        receipt = self.run_code('raise SystemExit(7)', budget_seconds=5)
        self.assertEqual(receipt['exit_code'], 7)
        self.assertEqual(receipt['tracked_processes_alive_after_cleanup'], 0)

    def test_deadline_kills_real_uncooperative_tree(self):
        code = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);time.sleep(60)'
        receipt = self.run_code(code, budget_seconds=2)
        self.assertEqual(receipt['stop_reason'], 'deadline')
        self.assertNotEqual(receipt['exit_code'], 0)
        self.assertGreaterEqual(receipt['tracked_processes'], 2)
        self.assertEqual(receipt['tracked_processes_alive_after_cleanup'], 0)
        self.assertLess(receipt['seconds'], 8)

    def test_parent_exit_still_cleans_observed_orphan(self):
        code = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);time.sleep(.5)'
        receipt = self.run_code(code, budget_seconds=5)
        self.assertEqual(receipt['exit_code'], 0)
        self.assertEqual(receipt['stop_reason'], 'worker_exit_with_live_descendants')
        self.assertGreaterEqual(receipt['tracked_processes'], 2)
        self.assertEqual(receipt['tracked_processes_alive_after_cleanup'], 0)

    def test_rejects_full_test_operations_and_invalid_budget_before_spawn(self):
        for operation, budget in [('full_readback', 10), ('test', 10), ('rebuild', 1801), ('rebuild', True)]:
            with self.subTest(operation=operation, budget=budget), self.assertRaises(ValueError):
                window.run_window(self.root/'run', [], self.source, operation, budget_seconds=budget)
        self.assertFalse((self.root/'run').exists())

    def test_rejects_duplicate_or_missing_sources(self):
        for records in ([], self.source*2):
            with self.assertRaises(ValueError):
                window.run_window(self.root/'run', [], records, 'rebuild')
        self.assertFalse((self.root/'run').exists())

    def test_identity_guard_ignores_reused_pid(self):
        process = psutil.Process()
        self.assertTrue(window._running(process, process.create_time()))
        self.assertFalse(window._running(process, process.create_time()+1))

    def test_namespace_is_never_reused(self):
        self.run_code('pass', budget_seconds=5)
        before = (self.root/'run/request.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_code('pass', budget_seconds=5)
        self.assertEqual(before, (self.root/'run/request.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
