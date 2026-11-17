"""Synthetic-only full readback supervision and independent evidence publication.

No production profile, ranking implementation, calibration, or benchmark lives
here. Every process re-enters the sealed fixture registry. The outer caller is
the finalizer: it writes outside ``internal`` only after all internal writers
have stopped. Imported frozen modules are never patched.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

import psutil

from scripts import retailrocket_session_knn_checkpoint_v2 as cp


ROOT = Path(__file__).resolve().parents[1]
MODULE = 'scripts.retailrocket_session_knn_pipeline_v77'
REQUIRED_STAGES = ['reconstruction', 'queries', 'global', 'bootstrap']
SCENARIO_KEYS = {'worker_fault', 'worker_after', 'finalize_fault',
                 'publisher_fault', 'finalizer_fault'}
WORKER_FAULTS = {'database_build', 'database_row', 'query_work', 'query_verified',
                 'payload_half_written', 'after_payload_fsync',
                 'before_manifest_commit', 'after_manifest_commit',
                 'global_replay', 'bootstrap', 'bootstrap_draw',
                 'before_candidate', 'before_candidate_commit',
                 'after_candidate_commit'}
EPISODE_FILES = {
    'scenario.json', 'pipeline_identity.json', 'pipeline.log',
    'worker_identity.json', 'worker.log', 'worker_exit.json',
    'worker_sources.jsonl', 'supervisor_sources.jsonl',
    'publisher_identity.json', 'publisher.log', 'publisher_exit.json',
    'publisher_sources.jsonl', 'publisher_proof.json', 'pipeline_result.json',
    'worker_failure.json', 'publisher_failure.json', 'pipeline_failure.json',
}


def _same(left, right, message):
    if cp.encoded(left) != cp.encoded(right):
        raise cp.IntegrityError(message)


def _identity(value):
    if (type(value) is not dict or set(value) != {'pid', 'create_time', 'boot_time'}
            or type(value['pid']) is not int or value['pid'] <= 0
            or type(value['create_time']) not in (float, int)
            or not math.isfinite(value['create_time']) or value['create_time'] <= 0
            or type(value['boot_time']) not in (float, int)
            or not math.isfinite(value['boot_time']) or value['boot_time'] <= 0):
        raise cp.IntegrityError('Complete process identity required')
    return value


def _scope(admitted):
    binding = admitted['binding']
    n = binding.get('expected_queries')
    if (binding.get('profile') != 'synthetic_only' or type(n) is not int
            or not 0 < n <= 129 or type(binding.get('expected_visitors')) is not int
            or not 0 < binding['expected_visitors'] <= n
            or type(binding.get('bootstrap_replicates')) is not int
            or binding['bootstrap_replicates'] != 2000):
        raise cp.IntegrityError('Sealed synthetic counts required')
    return n


def _folder(folder):
    from scripts import retailrocket_session_knn_bundle_v77 as bundle
    path = Path(folder).absolute()
    try:
        name = path.relative_to(ROOT).as_posix()
    except ValueError as error:
        raise cp.IntegrityError('V77 output escaped repository') from error
    if not name.startswith('shop-mysql-runtime/v77/runs/'):
        raise cp.IntegrityError('V77 output must be below shop-mysql-runtime/v77/runs')
    return bundle.safe_path(ROOT, name)


def _scenario(value):
    value = {} if value is None else dict(value)
    if set(value) - SCENARIO_KEYS:
        raise ValueError('Undeclared synthetic fault scenario')
    if value.get('worker_fault') is not None and value['worker_fault'] not in WORKER_FAULTS:
        raise ValueError('Unknown worker fault point')
    after = value.get('worker_after', 1)
    if type(after) is not int or after < 1:
        raise ValueError('Positive exact fault occurrence required')
    if value.get('finalize_fault') not in (None, 'before_acceptance_commit'):
        raise ValueError('Unknown finalize fault point')
    if value.get('publisher_fault') not in (None, 'before_proof', 'after_proof'):
        raise ValueError('Unknown publisher fault point')
    if value.get('finalizer_fault') not in (None, 'before_final_commit'):
        raise ValueError('Unknown finalizer fault point')
    return value


class Deadline:
    """One absolute request budget including downtime; no timing-performance claim."""

    def __init__(self, request, state_path, *, clock=None):
        self.request = request
        self.path = Path(state_path)
        self.clock = clock or cp.Clock()
        self.base_utc = self.clock.utc()
        self.base_mono = self.clock.monotonic()
        self.started = cp._time(request['created_utc'])
        self.deadline = cp._time(request['deadline_utc'])
        self.budget = request['budget_seconds']
        if (type(self.budget) not in (float, int) or not math.isfinite(self.budget)
                or not 0 < self.budget <= 900 or self.deadline <= self.started):
            raise ValueError('Finite synthetic deadline at most 900 seconds required')

    @contextmanager
    def _state_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.parent / 'budget.guard'
        with lock_path.open('a+b') as stream:
            if stream.seek(0, 2) == 0:
                stream.write(b'0'); stream.flush()
            started = time.monotonic()
            while True:
                try:
                    cp._lock(stream)
                    break
                except cp.WriterBusy:
                    if time.monotonic() - started >= 1 or self.clock.utc() >= self.deadline:
                        raise cp.BudgetExceeded('Cumulative budget state lock unavailable')
                    time.sleep(0.005)
            try:
                yield
            finally:
                cp._unlock(stream)

    def check(self, resource_check=None):
        # Both readers and replacers use this same short OS lock. This also
        # avoids Windows rename/read sharing races between parent and child.
        with self._state_lock():
            return self._check_locked(resource_check)

    def _check_locked(self, resource_check):
        request_sha = hashlib.sha256(cp.encoded(self.request)).hexdigest()
        previous = [cp.read(path) for path in sorted(self.path.parent.glob('*.json'))]
        if any(row['request_sha256'] != request_sha for row in previous):
            raise cp.BudgetExceeded('Saved cumulative request identity changed')
        # Read all prior process states before reading the current clock. A new
        # PID/role must inherit the largest consumed budget and last observed
        # UTC. Temporary files are not published states and are never adopted.
        now, mono = self.clock.utc(), self.clock.monotonic()
        if previous and now < max(row['last_utc'] for row in previous):
            raise cp.BudgetExceeded('UTC moved backwards across a process boundary')
        elapsed = max(now - self.started,
                      self.base_utc - self.started + mono - self.base_mono,
                      max((row['consumed_seconds'] for row in previous), default=0))
        record = dict(request_sha256=request_sha, last_utc=now,
                      consumed_seconds=elapsed)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        cp.atomic_json(temporary, record)
        os.replace(temporary, self.path)
        if now >= self.deadline or elapsed >= self.budget:
            raise cp.BudgetExceeded('V77 absolute or cumulative deadline reached')
        if resource_check is not None:
            outcome = resource_check()
            if outcome is not None and outcome is not True:
                raise cp.BudgetExceeded('Synthetic resource guard rejected continuation')
        return min(self.deadline - now, self.budget - elapsed)


def _reenter(request):
    from scripts import retailrocket_session_knn_bundle_v77 as bundle
    admitted = bundle.admit(**request['admission'])
    _scope(admitted)
    _same(admitted['binding'], request['binding'], 'Saved request binding changed')
    return admitted


def _source_checker(admitted, path, labels):
    from scripts import retailrocket_session_knn_bundle_v77 as bundle
    counter = 0

    def check():
        nonlocal counter
        label = labels[min(counter, len(labels) - 1)]
        bundle.recheck(admitted)
        with Path(path).open('ab') as stream:
            stream.write(cp.encoded({'position': label, 'ordinal': counter,
                                     'verified': True}))
            stream.flush()
        counter += 1
    return check


def _snapshot(folder):
    folder = Path(folder)
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
        raise cp.IntegrityError('Evidence root is an alias')
    folder = folder.resolve()
    records = []
    for path in sorted(folder.rglob('*')):
        if (path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
                or not path.resolve().is_relative_to(folder)):
            raise cp.IntegrityError('Evidence alias escaped closed namespace')
        if path.is_file():
            records.append(cp.descriptor(folder, path.relative_to(folder).as_posix()))
    return records


def _assert_stopped(identities, process_api):
    for identity in identities:
        if process_api.is_alive(_identity(identity)):
            raise cp.WriterBusy('An internal writer is still alive')


def _raw_request(admitted, run_dir):
    request_path = Path(run_dir).parent / 'request.json'
    request = cp.read(request_path)
    _same(request['binding'], admitted['binding'], 'Publisher raw request differs')
    _same(request['admission'], admitted['admission'], 'Publisher admission differs')
    return request


def audit_saved(admitted, run_dir, *, source_check=None, watch=lambda: None):
    """P9: raw provenance proof, without ranking or numerical aggregate replay."""
    n = _scope(admitted)
    run_dir = Path(run_dir).resolve()
    if source_check is None:
        from scripts import retailrocket_session_knn_bundle_v77 as bundle
        source_check = lambda: bundle.recheck(admitted)
    source_check()  # H7, separate from admission and from H8.
    watch()
    request = _raw_request(admitted, run_dir)
    store = cp.CheckpointStore(run_dir, admitted['binding'])
    store._load()  # Read-only: do not acquire writer or call numerical worker.
    run = store.run
    if (request.get('profile') != 'synthetic_only'
            or request.get('deadline_utc') != run['deadline_utc']
            or cp.encoded(request.get('budget_seconds')) != cp.encoded(run['budget_seconds'])
            or cp._time(request['created_utc']) > cp._time(run['created_utc'])):
        raise cp.IntegrityError('Publisher request budget differs from immutable CP run')
    if (type(run['expected_queries']) is not int or run['expected_queries'] != n
            or run['required_stages'] != REQUIRED_STAGES):
        raise cp.IntegrityError('Publisher full query configuration differs')
    before = _snapshot(run_dir)
    roster, payloads = hashlib.sha256(), hashlib.sha256()
    visitors = set()
    count = 0
    for record in store.iter_records():
        watch()
        key = record['key']
        payload = record['payload']
        _same(payload['expected']['key'], key, 'Payload key differs from ledger')
        roster.update((json.dumps(key, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')) + '\n').encode('utf-8'))
        payloads.update(cp.encoded(payload))
        visitors.add(key[0])
        count += 1
    summary = dict(store._summary)
    if count != n or len(visitors) != admitted['binding']['expected_visitors']:
        raise cp.IntegrityError('Publisher full query/visitor roster differs')
    stages = []
    for name in REQUIRED_STAGES:
        if store.get_stage(name) is None:
            raise cp.IntegrityError('Publisher required stage missing')
        raw = cp.read(run_dir / 'stages' / (name + '.json'))
        if raw['run_sha256'] != store.run_sha:
            raise cp.IntegrityError('Publisher stage run differs')
        if name != 'reconstruction':
            _same(raw['ledger'], summary, 'Publisher stage ledger differs')
        stages.append(cp.descriptor(run_dir, 'stages/' + name + '.json'))
    query = store.get_stage('queries')
    if (type(query.get('queries')) is not int or query['queries'] != n
            or type(query.get('paired_streams_eof_checked')) is not bool
            or query['paired_streams_eof_checked'] is not True):
        raise cp.IntegrityError('Publisher query completion semantics differ')
    global_stage = store.get_stage('global')
    if (type(global_stage.get('queries')) is not int or global_stage['queries'] != n
            or global_stage.get('roster_sha256') != roster.hexdigest()):
        raise cp.IntegrityError('Publisher global roster differs')
    bootstrap = store.get_stage('bootstrap')
    if type(bootstrap.get('replicates')) is not int or bootstrap['replicates'] != 2000:
        raise cp.IntegrityError('Publisher original draw count differs')
    candidate = cp.read(run_dir / 'candidate.json')
    _same(candidate['run_sha256'], store.run_sha, 'Candidate run differs')
    _same(candidate['ledger'], summary, 'Candidate ledger differs')
    _same(candidate['stages'], stages, 'Candidate stages differ')
    _identity(candidate['worker_identity'])
    receipt = candidate['receipt']
    if (type(receipt.get('queries_checked')) is not int or receipt['queries_checked'] != n
            or type(receipt.get('bootstrap_replicates')) is not int
            or receipt['bootstrap_replicates'] != 2000
            or receipt.get('production_K1_helpers_imported') is not False
            or receipt.get('sampled_oracle') is not False):
        raise cp.IntegrityError('Candidate full receipt differs')
    aggregate = receipt['aggregate']
    _same(aggregate['roster_sha256'], roster.hexdigest(), 'Candidate aggregate roster differs')
    _same(aggregate['uncertainty'], bootstrap, 'Candidate draw receipt differs')
    _same(receipt['fit_audit'], store.get_stage('reconstruction')['fit_audit'],
          'Candidate reconstruction differs')
    for arm in ('P0', 'C1', 'D1', 'K1'):
        counts = aggregate['main']['arms'][arm]
        if (type(counts['queries']) is not int or counts['queries'] != n
                or type(counts['visitors']) is not int or counts['visitors'] != len(visitors)):
            raise cp.IntegrityError('Candidate aggregate counts differ')
    # Frozen comparison only; no Fold, predict, terms, or bootstrap execution.
    from scripts.retailrocket_session_knn_readback import close
    close(cp.read(Path(admitted['primary']) / 'aggregate.json'), aggregate)
    normal = cp.read(run_dir / 'normal_worker_exit.json')
    _same(normal['worker_identity'], candidate['worker_identity'], 'Normal exit worker differs')
    if type(normal['exit_code']) is not int or normal['exit_code'] != 0:
        raise cp.IntegrityError('Normal exit code differs')
    if _identity(normal['supervisor_identity']) == candidate['worker_identity']:
        raise cp.IntegrityError('Worker cannot certify own normal exit')
    if normal['supervisor_identity']['boot_time'] != candidate['worker_identity']['boot_time']:
        raise cp.IntegrityError('Original normal exit lacks same-boot independent observation')
    opened = cp.read(run_dir / 'sessions' / (candidate['worker_session'] + '.json'))
    if (opened['role'] != 'worker' or opened['state'] != 'active'
            or opened['token'] != candidate['worker_session']):
        raise cp.IntegrityError('Candidate worker session differs')
    _same(opened['identity'], candidate['worker_identity'], 'Worker session identity differs')
    observations = []
    for exit_path in sorted((run_dir.parent / 'episodes').glob('*/worker_exit.json')):
        observed = cp.read(exit_path)
        if observed['identity'] == candidate['worker_identity']:
            observations.append((exit_path.parent, observed))
    if len(observations) != 1:
        raise cp.IntegrityError('Exactly one raw worker exit observation required')
    original_episode, observed = observations[0]
    if (observed.get('normal_observed') is not True
            or type(observed.get('exit_code')) is not int or observed['exit_code'] != 0
            or observed.get('stop_request') is not None
            or observed['actual_exit_observed_utc'] > cp._time(normal['observed_utc'])):
        raise cp.IntegrityError('Raw normal worker exit observation differs')
    _same(cp.read(original_episode / 'pipeline_identity.json'), normal['supervisor_identity'],
          'Original observing supervisor identity differs')
    acceptance = cp.read(run_dir / 'acceptance.json')
    expected = dict(status='separate_v2_readback_complete', run_sha256=store.run_sha,
                    candidate=cp.descriptor(run_dir, 'candidate.json'), ledger=summary,
                    stages=stages,
                    normal_worker_exit=cp.descriptor(run_dir, 'normal_worker_exit.json'),
                    reserved_test='locked', primary_recomputed=False)
    _same(acceptance, expected, 'CP acceptance raw proof differs')
    watch()
    source_check()  # H8, after complete raw proof.
    _same(_snapshot(run_dir), before, 'Accepted science changed during publication')
    return dict(status='v77_synthetic_raw_publication_proof', synthetic=True,
                request=cp.descriptor(run_dir.parent, 'request.json'),
                binding_sha256=hashlib.sha256(cp.encoded(request['binding'])).hexdigest(),
                run_sha256=store.run_sha, queries=count, visitors=len(visitors),
                bootstrap_replicates=2000, roster_sha256=roster.hexdigest(),
                science_payload_sha256=payloads.hexdigest(), cp_evidence=before,
                source_positions=['H7', 'H8'], ranking_calls=0,
                global_numeric_replays=0, draw_numeric_replays=0,
                full_real_acceptance=False, real_T_plan=None)


def _request_deadline(request, folder, role, *, clock=None):
    return Deadline(request, folder / 'control' / 'budgets' /
                    (role + '-' + str(os.getpid()) + '.json'), clock=clock)


def _launch(command, log_path, receipt_path, guard, *, resource_check=None,
            process_api=None, watch_seconds=120):
    """Observe actual child exit; an exception cannot turn into normal-exit proof."""
    process_api = process_api or cp.Processes()
    remaining = guard.check(resource_check)
    # The suite carrier has the whole formal window; each work child also
    # inherits that window's remaining budget, in addition to its 120 s cap.
    formal_deadline = float(os.environ['V77_FORMAL_DEADLINE_MONOTONIC'])
    if not math.isfinite(formal_deadline):
        raise ValueError('Finite formal deadline required')
    formal_remaining = formal_deadline - time.monotonic()
    if formal_remaining <= 0:
        raise TimeoutError('Formal window expired before child launch')
    timeout = min(float(watch_seconds), remaining, 120.0, formal_remaining)
    started = guard.clock.utc()
    tracked = {}
    stop = None
    process = None
    identity = None
    with Path(log_path).open('ab', buffering=0) as log:
        try:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            p = psutil.Process(process.pid)
            identity = dict(pid=p.pid, create_time=p.create_time(),
                            boot_time=process_api.boot_identity())
            tracked[(identity['pid'], identity['create_time'])] = identity
            began = time.monotonic()
            while process.poll() is None:
                try:
                    if time.monotonic() >= formal_deadline:
                        raise TimeoutError('Formal window expired during child work')
                    guard.check(resource_check)
                    if time.monotonic() - began >= timeout:
                        raise cp.BudgetExceeded('Synthetic child watchdog reached')
                    try:
                        children = p.children(recursive=True)
                    except psutil.NoSuchProcess:
                        children = []
                    for child in children:
                        child_id = dict(pid=child.pid, create_time=child.create_time(),
                                        boot_time=identity['boot_time'])
                        tracked[(child_id['pid'], child_id['create_time'])] = child_id
                except BaseException as error:
                    stop = dict(requested_utc=guard.clock.utc(), reason=type(error).__name__)
                    raise
                time.sleep(0.02)
            code = process.wait()
            observed = guard.clock.utc()
        except BaseException:
            if process is not None:
                for item in reversed(list(tracked.values())):
                    if process_api.is_alive(item):
                        try:
                            psutil.Process(item['pid']).terminate()
                        except psutil.NoSuchProcess:
                            pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=3)
                code, observed = process.returncode, guard.clock.utc()
            else:
                code, observed = None, guard.clock.utc()
            if identity is not None:
                cp.atomic_json(receipt_path, dict(identity=identity, exit_code=code,
                    started_utc=started, actual_exit_observed_utc=observed,
                    stop_request=stop, tracked=list(tracked.values()), normal_observed=False))
            raise
    receipt = dict(identity=identity, exit_code=code, started_utc=started,
                   actual_exit_observed_utc=observed, stop_request=stop,
                   tracked=list(tracked.values()), normal_observed=code == 0)
    failure_path = Path(log_path).with_name(Path(log_path).stem + '_failure.json')
    failure = cp.read(failure_path) if failure_path.exists() else None
    if failure is not None:
        if (failure.get('role') != Path(log_path).stem
                or failure.get('episode') != Path(log_path).parent.name
                or type(failure.get('timeout_stop')) is not bool
                or type(failure.get('message')) is not str
                or failure.get('scientific_success') is not False):
            raise cp.IntegrityError('Malformed child failure evidence')
        receipt['child_failure'] = cp.descriptor(failure_path.parent, failure_path.name)
    cp.atomic_json(receipt_path, receipt)
    _assert_stopped(receipt['tracked'], process_api)
    if time.monotonic() >= formal_deadline:
        raise TimeoutError('Formal window expired before child receipt acceptance')
    guard.check(resource_check)
    if failure is not None and code == 0:
        raise cp.IntegrityError('Child success contradicts structured failure receipt')
    if code != 0:
        if failure is not None and failure.get('timeout_stop') is True:
            raise TimeoutError('Synthetic descendant deadline/watchdog failure: ' + failure['message'])
        raise RuntimeError('Synthetic child did not exit normally: ' + str(code))
    return receipt


def _worker(folder, episode):
    from scripts import retailrocket_session_knn_full_worker_v75 as worker
    internal = folder / 'internal'
    request = cp.read(internal / 'request.json')
    admitted = _reenter(request)
    scenario = _scenario(cp.read(episode / 'scenario.json'))
    process_api = cp.Processes()
    cp.atomic_json(episode / 'worker_identity.json', process_api.identity())
    count = 0

    def fault(point):
        nonlocal count
        if point == scenario.get('worker_fault'):
            count += 1
            if count == scenario.get('worker_after', 1):
                os._exit(9)
    checker = _source_checker(admitted, episode / 'worker_sources.jsonl', ['H1', 'H2', 'H3'])
    kwargs = dict(source_root=admitted['bundle_root'], external_source_verifier=checker,
                  fault=fault)
    run_dir = internal / 'cp'
    if run_dir.exists():
        store = worker.open_store(run_dir, admitted['binding'], **kwargs)
    else:
        store = worker.create_store(run_dir, admitted['binding'], request['deadline_utc'],
                                    request['budget_seconds'], **kwargs)
    with store.writer():
        worker.verify_full(admitted['primary'], admitted['paths'], admitted['config'], store,
                           watch=store.check_budget, fault=fault)


def _publisher(folder, episode):
    internal = folder / 'internal'
    request = cp.read(internal / 'request.json')
    admitted = _reenter(request)
    scenario = _scenario(cp.read(episode / 'scenario.json'))
    cp.atomic_json(episode / 'publisher_identity.json', cp.Processes().identity())
    guard = _request_deadline(request, folder, 'publisher')
    if scenario.get('publisher_fault') == 'before_proof':
        raise RuntimeError('Injected synthetic publisher fault before proof')
    proof = audit_saved(admitted, internal / 'cp', watch=guard.check,
                        source_check=_source_checker(admitted,
                            episode / 'publisher_sources.jsonl', ['H7', 'H8']))
    guard.check()
    cp.atomic_json(episode / 'publisher_proof.json', proof)
    if scenario.get('publisher_fault') == 'after_proof':
        raise RuntimeError('Injected synthetic publisher fault after proof')
    print('v77 publisher proof closed', flush=False)


def _pipeline(folder, episode):
    from scripts import retailrocket_session_knn_full_worker_v75 as worker
    internal = folder / 'internal'
    request = cp.read(internal / 'request.json')
    admitted = _reenter(request)
    scenario = _scenario(cp.read(episode / 'scenario.json'))
    cp.atomic_json(episode / 'pipeline_identity.json', cp.Processes().identity())
    guard = _request_deadline(request, folder, 'pipeline')
    run_dir = internal / 'cp'
    if not (run_dir / 'acceptance.json').exists():
        if (run_dir / 'normal_worker_exit.json').exists():
            normal = cp.read(run_dir / 'normal_worker_exit.json')
            identity, code = normal['worker_identity'], normal['exit_code']
        else:
            exited = _launch([sys.executable, '-B', '-m', MODULE, '--worker',
                              str(folder), '--episode', episode.name],
                             episode / 'worker.log', episode / 'worker_exit.json', guard)
            identity, code = exited['identity'], exited['exit_code']
            _same(cp.read(episode / 'worker_identity.json'), identity,
                  'Observed worker identity differs from child declaration')
        def fault(point):
            if point == scenario.get('finalize_fault'):
                raise RuntimeError('Injected finalize fault before acceptance')
        store = worker.open_store(run_dir, admitted['binding'],
                    source_root=admitted['bundle_root'], fault=fault,
                    external_source_verifier=_source_checker(admitted,
                        episode / 'supervisor_sources.jsonl', ['H4', 'H5', 'H6']))
        guard.check()
        store.finalize(cp.descriptor(run_dir, 'candidate.json')['sha256'], identity, code)
    guard.check()
    exited = _launch([sys.executable, '-B', '-m', MODULE, '--publisher',
                      str(folder), '--episode', episode.name],
                     episode / 'publisher.log', episode / 'publisher_exit.json', guard)
    _same(cp.read(episode / 'publisher_identity.json'), exited['identity'],
          'Observed publisher identity differs from child declaration')
    guard.check()
    cp.atomic_json(episode / 'pipeline_result.json', dict(
        status='v77_pipeline_completed_not_outer_acceptance',
        proof=cp.descriptor(episode, 'publisher_proof.json'),
        cp_acceptance=cp.descriptor(run_dir, 'acceptance.json')))
    print('v77 pipeline publication closed', flush=False)


def _completed_episode(folder):
    candidates = []
    for episode in sorted((folder / 'internal' / 'episodes').iterdir()):
        exit_path = folder / 'control' / 'episodes' / episode.name / 'pipeline_exit.json'
        if (episode / 'pipeline_result.json').exists() and exit_path.exists():
            receipt = cp.read(exit_path)
            if receipt.get('normal_observed') is True and receipt.get('exit_code') == 0:
                candidates.append(episode)
    if len(candidates) > 1:
        raise cp.IntegrityError('Multiple completed publication episodes')
    return candidates[0] if candidates else None


def finalize_stopped(folder, *, process_api=None, clock=None, expected=None,
                     fault=lambda point: None):
    """P10 external seal or readonly re-audit; never write inside internal/."""
    folder = _folder(folder)
    internal = folder / 'internal'
    process_api = process_api or cp.Processes()
    request = cp.read(internal / 'request.json')
    guard = _request_deadline(request, folder, 'finalizer', clock=clock)
    if expected is None:
        guard.check()
    episode = _completed_episode(folder)
    if episode is None:
        raise cp.IntegrityError('No observed complete publication episode')
    identities = []
    pipeline_exits = []
    for previous in sorted((internal / 'episodes').iterdir()):
        if not previous.is_dir() or previous.is_symlink():
            raise cp.IntegrityError('Invalid publication episode directory')
        if any(path.name not in EPISODE_FILES for path in previous.iterdir()):
            raise cp.IntegrityError('Undeclared internal evidence file')
        for name in ('pipeline_identity.json', 'worker_identity.json', 'publisher_identity.json'):
            path = previous / name
            if path.exists():
                identities.append(cp.read(path))
        exit_path = folder / 'control' / 'episodes' / previous.name / 'pipeline_exit.json'
        if not exit_path.exists():
            raise cp.IntegrityError('Missing independent pipeline exit observation')
        exited = cp.read(exit_path)
        identities.extend(exited['tracked'])
        pipeline_exits.append(cp.descriptor(folder, exit_path.relative_to(folder).as_posix()))
        if (previous / 'pipeline_identity.json').exists():
            _same(exited['identity'], cp.read(previous / 'pipeline_identity.json'),
                  'Outer observed pipeline identity differs')
        for name in ('worker_exit.json', 'publisher_exit.json'):
            if (previous / name).exists():
                identities.extend(cp.read(previous / name)['tracked'])
    _assert_stopped(identities, process_api)
    if {p.name for p in internal.iterdir()} != {'request.json', 'cp', 'episodes'}:
        raise cp.IntegrityError('Undeclared internal namespace entry')
    proof = cp.read(episode / 'publisher_proof.json')
    result = cp.read(episode / 'pipeline_result.json')
    _same(result['proof'], cp.descriptor(episode, 'publisher_proof.json'),
          'Publisher proof seal differs')
    _same(result['cp_acceptance'], cp.descriptor(internal / 'cp', 'acceptance.json'),
          'Accepted CP changed before stopped seal')
    _same(proof['request'], cp.descriptor(internal, 'request.json'), 'Proof request differs')
    _same(proof['cp_evidence'], _snapshot(internal / 'cp'), 'Accepted science changed after proof')
    publisher_exit = cp.read(episode / 'publisher_exit.json')
    if (publisher_exit.get('normal_observed') is not True
            or type(publisher_exit.get('exit_code')) is not int
            or publisher_exit['exit_code'] != 0):
        raise cp.IntegrityError('Publisher did not have an observed normal exit')
    before = _snapshot(internal)
    _assert_stopped(identities, process_api)
    _same(_snapshot(internal), before, 'Internal evidence changed while sealing')
    seal = dict(status='v77_synthetic_stopped_full_pipeline_accepted', synthetic=True,
                internal_evidence=before, pipeline_exit_evidence=pipeline_exits,
                publication_episode=episode.name,
                proof=cp.descriptor(internal, 'episodes/' + episode.name + '/publisher_proof.json'),
                queries=proof['queries'], visitors=proof['visitors'],
                bootstrap_replicates=proof['bootstrap_replicates'],
                cp_path=(internal / 'cp').relative_to(ROOT).as_posix(),
                full_real_acceptance=False, real_T_plan=None, reserved_test='locked')
    if expected is not None:
        _same(seal, expected, 'Post-seal evidence set or bytes changed')
        return seal
    guard.check()
    fault('before_final_commit')
    cp.atomic_json(folder / 'final_seal.json', seal)
    return seal


def run_pipeline(admitted, folder, *, scenario=None, clock=None, process_api=None,
                 resource_check=None, budget_seconds=120):
    """External supervisor entry. Re-entry preserves original deadline and evidence."""
    from scripts import retailrocket_session_knn_bundle_v77 as bundle
    admitted = bundle.admit(**admitted['admission'])
    _scope(admitted)
    folder = _folder(folder)
    scenario = _scenario(scenario)
    clock = clock or cp.Clock()
    if (folder / 'final_seal.json').exists():
        raise cp.IntegrityError('Completed synthetic pipeline is readonly')
    if not folder.exists():
        if type(budget_seconds) not in (int, float) or not 0 < budget_seconds <= 900:
            raise ValueError('Finite synthetic budget at most 900 seconds required')
        now = clock.utc()
        request = dict(profile='synthetic_only', admission=admitted['admission'],
                       binding=admitted['binding'], created_utc=cp._iso(now),
                       deadline_utc=cp._iso(now + budget_seconds), budget_seconds=budget_seconds)
        folder.mkdir(parents=True)
        (folder / 'internal' / 'episodes').mkdir(parents=True)
        (folder / 'control' / 'episodes').mkdir(parents=True)
        cp.atomic_json(folder / 'internal' / 'request.json', request)
    request = cp.read(folder / 'internal' / 'request.json')
    _same(request['admission'], admitted['admission'], 'Cannot rebind a synthetic run')
    _same(request['binding'], admitted['binding'], 'Cannot change run sources or method')
    guard = _request_deadline(request, folder, 'outer', clock=clock)
    guard.check(resource_check)
    if _completed_episode(folder) is None:
        episode = folder / 'internal' / 'episodes' / uuid.uuid4().hex
        episode.mkdir()
        external = folder / 'control' / 'episodes' / episode.name
        external.mkdir()
        cp.atomic_json(episode / 'scenario.json', scenario)
        _launch([sys.executable, '-B', '-m', MODULE, '--pipeline', str(folder),
                 '--episode', episode.name], episode / 'pipeline.log',
                external / 'pipeline_exit.json', guard,
                resource_check=resource_check, process_api=process_api)
    guard.check(resource_check)
    def fault(point):
        if point == scenario.get('finalizer_fault'):
            raise RuntimeError('Injected finalizer fault before external publication')
    return finalize_stopped(folder, process_api=process_api, clock=clock, fault=fault)


def account_intervals(intervals, *, outer_start, outer_end):
    """Account supplied synthetic intervals; never read clocks or infer CPU wait."""
    if outer_end < outer_start:
        raise ValueError('Outer interval reversed')
    indexed = {}
    for row in intervals:
        name = row['id']
        if name in indexed or row['end'] < row['start']:
            raise ValueError('Duplicate or reversed interval')
        indexed[name] = row
    exclusive = {}
    for name, row in indexed.items():
        ancestors = {name}
        parent = row.get('parent')
        while parent is not None:
            if parent not in indexed or parent in ancestors:
                raise ValueError('Missing or cyclic interval parent')
            ancestors.add(parent)
            parent = indexed[parent].get('parent')
        children = [r for r in indexed.values() if r.get('parent') == name]
        ordered = sorted(children, key=lambda r: r['start'])
        if any(r['start'] < row['start'] or r['end'] > row['end'] for r in children):
            raise ValueError('Child interval escaped parent')
        if any(a['end'] > b['start'] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Child intervals overlap; cannot sum twice')
        exclusive[name] = row['end'] - row['start'] - sum(r['end'] - r['start'] for r in children)
        if row.get('parent') is not None and row['parent'] not in indexed:
            raise ValueError('Missing interval parent')
    roots = [r for r in indexed.values() if r.get('parent') is None and r.get('view', 'worker') == 'worker']
    ordered = sorted(roots, key=lambda r: r['start'])
    if any(a['end'] > b['start'] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('Primary phase intervals overlap')
    phases = sum(r['end'] - r['start'] for r in roots)
    return dict(exclusive=exclusive, primary_phase_total=phases,
                outer_wall=outer_end - outer_start,
                signed_bridge=outer_end - outer_start - phases,
                waiting_cpu_attribution=None, synthetic_intervals_only=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Sealed V77 synthetic child process only')
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('worker', 'publisher', 'pipeline'):
        modes.add_argument('--' + name, type=Path)
    parser.add_argument('--episode', required=True)
    args = parser.parse_args()
    if len(args.episode) != 32 or any(c not in '0123456789abcdef' for c in args.episode):
        raise ValueError('Exact synthetic episode identifier required')
    mode = next(name for name in ('worker', 'publisher', 'pipeline') if getattr(args, name))
    folder = _folder(getattr(args, mode))
    episode = folder / 'internal' / 'episodes' / args.episode
    if not episode.is_dir() or episode.is_symlink():
        raise ValueError('Predeclared synthetic episode required')
    try:
        {'worker': _worker, 'publisher': _publisher, 'pipeline': _pipeline}[mode](folder, episode)
    except BaseException as error:
        timeout = isinstance(error, (TimeoutError, subprocess.TimeoutExpired, cp.BudgetExceeded))
        failure = dict(role=mode, episode=episode.name, error_type=type(error).__name__,
                       message=str(error), traceback=traceback.format_exc(),
                       timeout_stop=timeout, retry_allowed=False if timeout else None,
                       scientific_success=False)
        cp.atomic_json(episode / (mode + '_failure.json'), failure)
        raise


if __name__ == '__main__':
    main()
