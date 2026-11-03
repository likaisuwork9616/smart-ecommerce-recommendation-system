"""Cooperative worker checks and an isolated microbenchmark for the V3 cost probe."""
from datetime import datetime, timezone
import math
from pathlib import Path
import stat
import time


def _deadline_epoch(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError('Deadline requires an explicit time zone')
        value = value.timestamp()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Deadline must be a finite UTC epoch or an aware timestamp')
    return float(value)


class ThrottledWatch:
    """Check the supervisor's stop marker and UTC deadline on safe boundaries.

    The first call and force() always perform a full check. Regular calls only
    read the monotonic clock between checks. The external supervisor owns the
    hard cutoff even when a worker never reaches another safe boundary.
    """

    def __init__(self, folder, deadline_utc, interval_seconds=.25, clock=None):
        if (isinstance(interval_seconds, bool) or not math.isfinite(interval_seconds)
                or interval_seconds <= 0):
            raise ValueError('Check interval must be positive and finite')
        self._stop = Path(folder).absolute() / 'stop_request.json'
        self._deadline = _deadline_epoch(deadline_utc)
        self._interval = interval_seconds
        self._monotonic = time.monotonic if clock is None else clock.monotonic
        self._utc = time.time if clock is None else clock.utc
        self._last_monotonic = self._last_utc = self._next_check = -math.inf
        self._error = None
        self.calls = self.full_checks = self.stop_checks = 0

    def __call__(self):
        self._check(False)

    def force(self):
        self._check(True)

    def _check(self, forced):
        self.calls += 1
        if self._error is not None:
            raise self._error
        try:
            mono = self._monotonic()
            if not math.isfinite(mono) or mono < self._last_monotonic:
                raise RuntimeError('Monotonic clock invalid or moved backwards')
            self._last_monotonic = mono
            if not forced and mono < self._next_check:
                return
            self.full_checks += 1
            now = self._utc()
            if not math.isfinite(now) or now < self._last_utc:
                raise RuntimeError('UTC clock invalid or moved backwards')
            self._last_utc = now
            if now >= self._deadline:
                raise TimeoutError('Absolute probe deadline')
            self.stop_checks += 1
            # Path.exists() can hide filesystem errors. Only an absent marker
            # inside the existing run directory means "continue".
            try:
                self._stop.lstat()
            except FileNotFoundError:
                if not stat.S_ISDIR(self._stop.parent.stat().st_mode):
                    raise NotADirectoryError(self._stop.parent)
            else:
                raise TimeoutError('Supervisor stop requested')
            self._next_check = mono + self._interval
        except Exception as error:
            self._error = error
            raise


def bench_watch(folder, deadline, iterations=20000, repeats=3):
    """Measure V2-style checks, throttling, a clock-only loop and an empty loop.

    Each sample reports raw elapsed and process CPU seconds. Its counters cover
    the measured loop only. The existing folder and its missing stop marker are
    read-only inputs. This benchmark never opens research data or a model.
    """
    if type(iterations) is not int or iterations <= 0 or type(repeats) is not int or repeats <= 0:
        raise ValueError('Benchmark iterations and repeats must be positive integers')
    folder = Path(folder)
    deadline_dt = datetime.fromtimestamp(_deadline_epoch(deadline), timezone.utc)
    boundary = ThrottledWatch(folder, deadline)

    def old_watch():
        if datetime.now(timezone.utc) >= deadline_dt:
            raise TimeoutError('Absolute probe deadline')
        if (folder / 'stop_request.json').exists():
            raise TimeoutError('Supervisor stop requested')

    results = {name: [] for name in ('legacy', 'throttled', 'monotonic_only', 'empty_loop')}
    for _ in range(repeats):
        for name, samples in results.items():
            boundary.force()
            watch = ThrottledWatch(folder, deadline) if name == 'throttled' else None
            calls = full_checks = stop_checks = monotonic_checks = 0
            wall_start = time.perf_counter()
            cpu_start = time.process_time()
            if name == 'legacy':
                for _ in range(iterations):
                    old_watch()
                calls = full_checks = stop_checks = iterations
            elif name == 'throttled':
                for _ in range(iterations):
                    watch()
                calls = monotonic_checks = watch.calls
                full_checks = watch.full_checks
                stop_checks = watch.stop_checks
            elif name == 'monotonic_only':
                for _ in range(iterations):
                    time.monotonic()
                calls = monotonic_checks = iterations
            else:
                for _ in range(iterations):
                    pass
            cpu_seconds = time.process_time() - cpu_start
            wall_seconds = time.perf_counter() - wall_start
            boundary.force()
            samples.append({'wall_seconds': wall_seconds, 'cpu_seconds': cpu_seconds,
                            'calls': calls, 'full_checks': full_checks,
                            'stop_checks': stop_checks, 'monotonic_checks': monotonic_checks})
    return {'iterations': iterations, 'repeats': repeats, 'interval_seconds': .25,
            'results': results}
