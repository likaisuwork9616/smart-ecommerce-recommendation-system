"""Run one readback stage in an isolated worker under a shared UTC cutoff."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = (ROOT / 'shop-mysql-runtime/verification').resolve()
LIMITS = ROOT / 'docs/contracts/retailrocket_session_knn_validation_entry_v1.json'
STAGES = ('sources_before', 'cohort', 'predictions', 'sql_witness', 'dense', 'aggregate', 'sources_after')


def used_bytes(folder):
    total = 0
    for file in folder.rglob('*'):
        if file.is_file():
            try:
                total += file.stat().st_size
            except FileNotFoundError:  # A SQLite temporary journal may have closed.
                continue
    return total


def command(stage, out, deadline):
    prefix = [sys.executable, '-B', '-u', '-m']
    options = ['--out', str(out)]
    if stage in ('sources_before', 'cohort', 'sources_after'):
        return prefix + ['scripts.verify_k1_cohort_v1', stage] + options
    if stage in ('predictions', 'sql_witness', 'dense'):
        options += ['--deadline-utc', deadline.isoformat()]
    return prefix + ['scripts.verify_k1_' + stage + '_v1'] + options


def run(stage, out, deadline):
    out = out.resolve()
    if PRIVATE not in out.parents:
        raise ValueError('Choose a new run directory inside shop-mysql-runtime/verification')
    out.mkdir(parents=True, exist_ok=True)
    limits = json.loads(LIMITS.read_bytes())['limits']
    started = datetime.now(timezone.utc)
    available_seconds = (deadline - started).total_seconds()
    if available_seconds <= 5:
        raise TimeoutError('Insufficient remaining time for a worker and cleanup')
    stop = time.monotonic() + available_seconds - 5
    with (out / (stage + '.started')).open('x') as marker:
        marker.write(started.isoformat())
    peak_rss = peak_disk = samples = 0
    owned = []
    proc = None
    status = 'incomplete'
    try:
        if (stage != 'sources_before' and not (out / 'k1_sources_before.json').is_file()):
            raise RuntimeError('Validate and bind sources before reading development rows')
        proc = subprocess.Popen(command(stage, out, deadline), cwd=ROOT)
        root_process = psutil.Process(proc.pid)
        while proc.poll() is None:
            if time.monotonic() >= stop or datetime.now(timezone.utc) >= deadline:
                raise TimeoutError('Stage deadline reached')
            try:
                owned = [root_process, *root_process.children(recursive=True)]
                rss = sum(p.memory_info().rss for p in owned)
            except psutil.NoSuchProcess:
                continue
            peak_rss = max(peak_rss, rss)
            if samples % 10 == 0:
                peak_disk = max(peak_disk, used_bytes(out))
            if (rss > limits['maximum_process_RSS_bytes'] or peak_disk > limits['maximum_execution_disk_bytes']
                    or shutil.disk_usage(out).free < limits['minimum_free_disk_bytes']
                    or psutil.virtual_memory().available < limits['minimum_available_memory_bytes']):
                raise RuntimeError('Readback resource limit reached')
            samples += 1
            time.sleep(limits['monitor_interval_seconds'])
        if proc.returncode:
            raise RuntimeError(f'{stage} exited with code {proc.returncode}')
        if not (out / ('k1_' + stage + '.json')).is_file():
            raise ValueError('Worker finished without a receipt')
        status = 'passed'
    finally:
        if proc is not None and proc.poll() is None:
            for process in reversed(owned):
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=4)
        receipt = dict(stage=stage, status=status, started_utc=started.isoformat(),
                       ended_utc=datetime.now(timezone.utc).isoformat(), deadline_utc=deadline.isoformat(),
                       samples=samples, sampled_peak_tree_rss_bytes=peak_rss,
                       sampled_peak_run_disk_bytes=max(peak_disk, used_bytes(out)))
        with (out / ('resource_' + stage + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2)
        print(stage, status, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=STAGES)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--deadline-utc', type=datetime.fromisoformat, required=True)
    args = parser.parse_args()
    if args.deadline_utc.tzinfo is None:
        parser.error('deadline must include a timezone')
    run(args.stage, args.out, args.deadline_utc)
