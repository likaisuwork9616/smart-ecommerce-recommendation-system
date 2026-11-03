"""Externally bound engineering windows; no scientific acceptance or full CLI."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import time

import psutil

from scripts.retailrocket_session_knn_checkpoint_v2 import atomic_json


OPERATIONS = ('joint_tail', 'rebuild', 'ledger_coverage')
LIMITS = {'rss_bytes': 8*2**30, 'execution_bytes': 20*2**30,
          'minimum_available_bytes': 4*2**30, 'minimum_free_bytes': 8*2**30}


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _running(process, created):
    try:
        return process.is_running() and process.create_time() == created
    except psutil.NoSuchProcess:
        return False


def _discover(worker, known):
    """Retain identities even if a descendant later outlives its parent."""
    try:
        members = [worker, *worker.children(recursive=True)]
    except psutil.NoSuchProcess:
        members = [worker]
    for process in members:
        try:
            created = process.create_time()
            known[(process.pid, created)] = process
        except psutil.NoSuchProcess:
            pass


def _alive(known):
    return [process for (_, created), process in known.items() if _running(process, created)]


def _cleanup(known):
    """Kill tracked descendants even after the top-level worker has exited."""
    members = _alive(known)
    for process in reversed(members):
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    if members:
        psutil.wait_procs(members, timeout=3)
    return len(_alive(known))


def run_window(folder, command, sources, operation, *, metadata=None,
               budget_seconds=1800, limits=None, poll_seconds=.5):
    """Create one new, non-resumable supervised cost namespace.

    The caller must bind approved inputs/methods and check gates in its worker.
    Initial/final source hashing is measured by that worker inside this window.
    Source integrity is not inferred from a zero process exit. No automatic
    retry, extension, scientific acceptance, final/test operation is available.
    """
    if operation not in OPERATIONS:
        raise ValueError('Unsupported engineering operation')
    if type(budget_seconds) not in (int, float) or not 2 <= budget_seconds <= 1800:
        raise ValueError('Each engineering window must be at most 1800 seconds')
    if not sources or len({r['path'] for r in sources}) != len(sources):
        raise ValueError('A unique nonempty frozen source inventory is required')
    if not .05 <= poll_seconds <= 1:
        raise ValueError('Invalid monitor interval')
    settings = dict(LIMITS if limits is None else limits)
    if set(settings) != set(LIMITS) or any(type(v) is not int or v <= 0 for v in settings.values()):
        raise ValueError('Invalid resource limits')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    now = datetime.now(timezone.utc)
    request = {'kind': 'bounded_engineering_cost_v5', 'operation': operation,
               'created_utc': now.isoformat(),
               'deadline_utc': (now+timedelta(seconds=budget_seconds)).isoformat(),
               'budget_seconds': budget_seconds, 'limits': settings,
               'sources': sources, 'metadata': metadata or {},
               'full_readback_enabled': False, 'reserved_test': 'locked', 'T_plan': None}
    atomic_json(folder/'request.json', request)
    known = {}; process = None; code = None; reason = None
    peak_rss = peak_disk = 0; live_after_cleanup = 0; supervisor_error = None
    try:
        with (folder/'stdout_stderr.log').open('xb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            worker = psutil.Process(process.pid)
            _discover(worker, known)
            atomic_json(folder/'worker_identity.json', {'pid': process.pid,
                'create_time': worker.create_time(), 'supervisor_pid': psutil.Process().pid})
            while process.poll() is None:
                _discover(worker, known)
                members = _alive(known)+[psutil.Process()]
                rss = 0
                for member in members:
                    try:
                        rss += member.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                disk = 0
                for path in folder.rglob('*'):
                    try:
                        if path.is_file():
                            disk += path.stat().st_size
                    except FileNotFoundError:
                        pass
                peak_rss = max(peak_rss, rss); peak_disk = max(peak_disk, disk)
                elapsed = time.monotonic()-start
                grace = min(2, budget_seconds/4)
                reason = ('deadline' if elapsed >= budget_seconds-grace else
                    'rss_limit' if rss > settings['rss_bytes'] else
                    'execution_disk_limit' if disk > settings['execution_bytes'] else
                    'minimum_available_memory' if psutil.virtual_memory().available < settings['minimum_available_bytes'] else
                    'minimum_free_disk' if psutil.disk_usage(str(folder)).free < settings['minimum_free_bytes'] else None)
                if reason:
                    atomic_json(folder/'stop_request.json', {'reason': reason, 'utc': _utc()})
                    try:
                        process.wait(timeout=max(.001, min(grace, budget_seconds-elapsed)))
                    except subprocess.TimeoutExpired:
                        _cleanup(known)
                        if process.poll() is None:
                            process.kill()
                    break
                time.sleep(poll_seconds)
            code = process.wait(timeout=5)
            # Record a final discovery when possible. The tracked map survives
            # top-worker exit, unlike children() on a vanished parent alone.
            _discover(worker, known)
            if _alive(known) and reason is None:
                reason = 'worker_exit_with_live_descendants'
    except BaseException as error:
        supervisor_error = type(error).__name__
        reason = reason or 'supervisor_exception_'+supervisor_error
        raise
    finally:
        try:
            live_after_cleanup = _cleanup(known)
            if process is not None:
                if process.poll() is None:
                    process.kill()
                code = process.wait(timeout=5)
            if live_after_cleanup:
                reason = reason or 'tracked_process_cleanup_incomplete'
        finally:
            atomic_json(folder/'tracked_process_identities.json', {
                'identities': [{'pid': pid, 'create_time': created} for pid, created in known],
                'live_after_cleanup': live_after_cleanup,
                'coverage': 'Identities observed at monitor samples, not an OS job-object guarantee.'})
            receipt = {'kind': 'engineering_cost_v5_exit_observation', 'operation': operation,
                'exit_code': code, 'stop_reason': reason, 'supervisor_error': supervisor_error,
                'actual_exit_observed_utc': _utc() if code is not None else None,
                'seconds': time.monotonic()-start, 'peak_sampled_tree_and_supervisor_rss_bytes': peak_rss,
                'peak_sampled_execution_bytes': peak_disk, 'tracked_processes': len(known),
                'tracked_processes_alive_after_cleanup': live_after_cleanup,
                'full_readback_started': False, 'reserved_test': 'locked', 'T_plan': None}
            atomic_json(folder/'supervisor_completion.json', receipt)
    return receipt
