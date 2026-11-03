"""Synthetic worker-watch tests with no research inputs."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_monitor_v3 as monitor


class Clock:
    def __init__(self):
        self.mono = 10.0
        self.wall = 1000.0000006
        self.utc_reads = self.mono_reads = 0

    def monotonic(self):
        self.mono_reads += 1
        return self.mono

    def utc(self):
        self.utc_reads += 1
        return self.wall


class WatchTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'shop-mysql-runtime' / 'verification'
        root.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=root, prefix='knn-monitor-v3-')
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.stop = self.folder / 'stop_request.json'
        self.clock = Clock()
        self.watch = monitor.ThrottledWatch(self.folder, 1100, clock=self.clock)

    def test_first_call_checks_then_dense_calls_only_read_monotonic_clock(self):
        for _ in range(10000):
            self.watch()
        self.assertEqual(self.watch.calls, 10000)
        self.assertEqual(self.watch.full_checks, 1)
        self.assertEqual(self.watch.stop_checks, 1)
        self.assertEqual(self.clock.mono_reads, 10000)
        self.assertEqual(self.clock.utc_reads, 1)

    def test_next_interval_detects_stop_at_boundary(self):
        self.watch()
        self.stop.write_text('{}', encoding='utf-8')
        self.clock.mono = 10.249
        self.watch()
        self.clock.mono = 10.25
        with self.assertRaisesRegex(TimeoutError, 'Supervisor stop'):
            self.watch()
        self.assertEqual(self.watch.full_checks, 2)
        self.assertEqual(self.watch.stop_checks, 2)

    def test_force_bypasses_interval_and_stop_latches(self):
        self.watch()
        self.stop.write_text('{}', encoding='utf-8')
        with self.assertRaises(TimeoutError):
            self.watch.force()
        self.stop.unlink()
        with self.assertRaises(TimeoutError):
            self.watch()
        self.assertEqual(self.watch.calls, 3)
        self.assertEqual(self.watch.stop_checks, 2)

    def test_absolute_deadline_rejects_equality_before_stop_file_check(self):
        deadline = datetime.fromtimestamp(1100, timezone.utc).isoformat()
        watch = monitor.ThrottledWatch(self.folder, deadline, clock=self.clock)
        watch()
        self.clock.mono += .25
        self.clock.wall = 1100.0
        with self.assertRaisesRegex(TimeoutError, 'Absolute probe deadline'):
            watch()
        self.assertEqual((watch.full_checks, watch.stop_checks), (2, 1))

    def test_utc_rollback_uses_raw_values_even_below_one_microsecond(self):
        for value in (1000.0000004, 1000.0000006):
            with self.subTest(utc=value):
                self.clock.wall = value
                watch = monitor.ThrottledWatch(self.folder, 1100, clock=self.clock)
                watch()
                watch.force()
                self.clock.wall -= .0000001
                with self.assertRaisesRegex(RuntimeError, 'UTC clock'):
                    watch.force()

    def test_monotonic_rollback_on_fast_path_rejects(self):
        self.watch()
        self.clock.mono += .125
        self.watch()
        self.clock.mono -= .001
        with self.assertRaisesRegex(RuntimeError, 'Monotonic clock'):
            self.watch()
        self.assertEqual(self.watch.full_checks, 1)

    def test_unknown_stop_marker_status_fails_closed(self):
        with patch.object(Path, 'lstat', side_effect=PermissionError('cannot inspect marker')):
            with self.assertRaises(PermissionError):
                self.watch()
        with self.assertRaises(PermissionError):
            self.watch.force()

    def test_absent_run_directory_fails_closed(self):
        watch = monitor.ThrottledWatch(self.folder / 'missing', 1100, clock=self.clock)
        with self.assertRaises(FileNotFoundError):
            watch()

    def test_unusable_clock_and_unzoned_deadline_rejected(self):
        for deadline in ('2030-01-01T00:00:00', float('nan'), True):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                monitor.ThrottledWatch(self.folder, deadline)
        for interval in (0, -1, True, float('inf')):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                monitor.ThrottledWatch(self.folder, 1100, interval)
        for name in ('mono', 'wall'):
            with self.subTest(clock=name):
                clock = Clock()
                setattr(clock, name, float('nan'))
                watch = monitor.ThrottledWatch(self.folder, 1100, clock=clock)
                with self.assertRaises(RuntimeError):
                    watch()

    def test_benchmark_reports_measured_loop_counters_for_each_repeat(self):
        with patch.object(monitor.time, 'monotonic', return_value=50):
            result = monitor.bench_watch(self.folder, time.time() + 60, iterations=7, repeats=2)
        self.assertEqual((result['iterations'], result['repeats']), (7, 2))
        expected = {'legacy': (7, 7, 7, 0), 'throttled': (7, 1, 1, 7),
                    'monotonic_only': (7, 0, 0, 7), 'empty_loop': (0, 0, 0, 0)}
        self.assertEqual(set(result['results']), set(expected))
        for name, counts in expected.items():
            samples = result['results'][name]
            self.assertEqual(len(samples), 2)
            for row in samples:
                self.assertEqual(tuple(row[key] for key in ('calls', 'full_checks',
                                                            'stop_checks', 'monotonic_checks')), counts)
                self.assertGreaterEqual(row['cpu_seconds'], 0)
                self.assertGreaterEqual(row['wall_seconds'], 0)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_benchmark_refuses_stopped_run_and_invalid_counts(self):
        self.stop.write_bytes(b'preserve this marker')
        with self.assertRaises(TimeoutError):
            monitor.bench_watch(self.folder, time.time() + 60, iterations=1, repeats=1)
        self.assertEqual(self.stop.read_bytes(), b'preserve this marker')
        for iterations, repeats in ((0, 1), (1, 0), (True, 1)):
            with self.subTest(counts=(iterations, repeats)), self.assertRaises(ValueError):
                monitor.bench_watch(self.folder, time.time() + 60, iterations, repeats)


if __name__ == '__main__':
    unittest.main()
