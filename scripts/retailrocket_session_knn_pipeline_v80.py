"""Synthetic-only full readback supervision and independent evidence publication.

No production profile, ranking implementation, calibration, or benchmark lives
here. Every process re-enters the sealed fixture registry. The outer caller is
the finalizer: it writes outside ``internal`` only after all internal writers
have stopped. Imported frozen modules are never patched.
"""
from contextlib import contextmanager
from dataclasses import dataclass
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
from scripts import retailrocket_session_knn_role_observer_v80 as observer


ROOT = Path(__file__).resolve().parents[1]
MODULE = 'scripts.retailrocket_session_knn_pipeline_v80'
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
ROLES = frozenset({'pipeline', 'worker', 'publisher'})
HANDSHAKE_FILES = ('launch.json', 'ready.json', 'ack.json')
FAULT_MARKER = 'V80_WORKER_FAULT '
_TICKETS = {}
_FINAL_VETO = 'control/final_delivery_veto.json'


@dataclass(frozen=True)
class _RoleFiles:
    folder: Path
    episode: str
    role: str

    def __post_init__(self):
        if (self.role not in ROLES or type(self.episode) is not str or len(self.episode) != 32
                or any(c not in '0123456789abcdef' for c in self.episode)):
            raise cp.IntegrityError('Unknown role or episode')

    @property
    def internal(self):
        return self.folder / 'internal' / 'episodes' / self.episode

    @property
    def external(self):
        return self.folder / 'control' / 'episodes' / self.episode / 'roles' / self.role

    @property
    def identity(self):
        return self.internal / (self.role + '_identity.json')

    @property
    def receipt(self):
        if self.role == 'pipeline':
            return self.external.parents[1] / 'pipeline_exit.json'
        return self.internal / (self.role + '_exit.json')

    @property
    def failure(self):
        return self.internal / (self.role + '_failure.json')


@dataclass(frozen=True, eq=False)
class _DeliveryTicket:
    key: tuple
    issuer_pid: int
    binding: bytes


class _RoleChildError(RuntimeError):
    def __init__(self, role, receipt, receipt_descriptor, ticket):
        super().__init__(f'Synthetic {role} role did not exit normally: {receipt["exit_code"]}')
        self.role = role
        self.receipt = receipt
        self.receipt_descriptor = receipt_descriptor
        self.ticket = ticket


def _relative(folder, path):
    return Path(path).relative_to(folder).as_posix()


def _artifact(folder, path):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
    try:
        return bundle.safe_path(folder, _relative(folder, path))
    except (OSError, ValueError) as error:
        raise cp.IntegrityError('Role artifact path is not canonical') from error


def _desc(folder, path):
    _artifact(folder, path)
    return cp.descriptor(folder, _relative(folder, path))


def _read(folder, path):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
    try:
        return bundle.read_json(_artifact(folder, path))
    except (OSError, ValueError) as error:
        raise cp.IntegrityError('Role or request record cannot be read: ' + Path(path).name) from error


def _sha(value):
    return hashlib.sha256(cp.encoded(value)).hexdigest()


def _record(value, keys, schema):
    if type(value) is not dict or set(value) != {'schema', *keys} or value['schema'] != schema:
        raise cp.IntegrityError(f'Invalid {schema} record')
    return value


def _command(files, nonce):
    return [sys.executable, '-B', '-m', MODULE, '--' + files.role, str(files.folder),
            '--episode', files.episode, '--nonce', nonce]


def _command_fingerprint(files, nonce):
    # The request is bound separately. An audit copy retains the same logical command.
    return _sha([MODULE, '-B', files.role, files.episode, nonce])


def _protocol_binding(files, request, nonce, observer_identity):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
    admission = request['admission']
    if type(nonce) is not str or len(nonce) != 32 or any(c not in '0123456789abcdef' for c in nonce):
        raise cp.IntegrityError('Invalid role launch nonce')
    method = cp.descriptor(ROOT, bundle.METHOD_SEAL)
    fixtures = cp.descriptor(ROOT, bundle.FIXTURE_SEAL)
    if (method['sha256'] != admission['method_seal_sha256']
            or fixtures['sha256'] != admission['fixture_seal_sha256']):
        raise cp.IntegrityError('Role launch seal anchors differ from request')
    return dict(schema='v80_role_launch', role=files.role, episode=files.episode,
                nonce=nonce, request=_desc(files.folder, files.folder / 'internal/request.json'),
                method_seal=method, fixture_seal=fixtures,
                command_fingerprint=_command_fingerprint(files, nonce),
                observer_identity=_native_identity(observer_identity))


def _load_launch(files):
    folder = files.folder
    request = _read(folder, folder / 'internal/request.json')
    launch = _record(_read(folder, files.external / 'launch.json'), {
        'role', 'episode', 'nonce', 'request', 'method_seal', 'fixture_seal',
        'command_fingerprint', 'observer_identity'}, 'v80_role_launch')
    expected = _protocol_binding(files, request, launch['nonce'], launch['observer_identity'])
    _same(launch, expected, 'Role launch binding differs')
    if files.role != 'pipeline':
        _same(launch['observer_identity'], _read(folder, files.internal / 'pipeline_identity.json'),
              'Role observer differs from owning pipeline')
    return launch


def _load_ready(files, launch):
    folder = files.folder
    role_identity = _native_identity(_read(folder, files.identity))
    ready = _record(_read(folder, files.external / 'ready.json'), {
        'launch', 'nonce', 'identity', 'pid', 'raw_creation'}, 'v80_role_ready')
    raw_creation = ready['raw_creation']
    expected = dict(schema='v80_role_ready', launch=_desc(folder, files.external / 'launch.json'),
                    nonce=launch['nonce'], identity=_desc(folder, files.identity),
                    pid=role_identity['pid'], raw_creation=raw_creation)
    _same(ready, expected, 'Role ready binding differs')
    if (role_identity['create_time'] != observer.normalize_creation(observer.parse_raw_creation(raw_creation))
            or role_identity['boot_time'] != launch['observer_identity']['boot_time']
            or role_identity == launch['observer_identity']):
        raise cp.IntegrityError('Ready role identity is inconsistent or self-observed')
    return ready, role_identity


def _load_ack(files, launch, role_identity):
    folder = files.folder
    ack = _record(_read(folder, files.external / 'ack.json'), {
        'launch', 'ready', 'identity', 'nonce', 'observer_identity', 'launcher_identity',
        'role_identity', 'launcher_raw_creation', 'raw_creation', 'ancestry',
        'backend', 'access_mask', 'pre_ack_nonsignaled'}, 'v80_role_ack')
    ready, _ = _load_ready(files, launch)
    required = dict(launch=ready['launch'], ready=_desc(folder, files.external / 'ready.json'),
                    identity=ready['identity'], nonce=launch['nonce'],
                    observer_identity=launch['observer_identity'], role_identity=role_identity,
                    raw_creation=ready['raw_creation'], backend=observer.BACKEND,
                    access_mask=observer.ACCESS_MASK, pre_ack_nonsignaled=True)
    _same({key: ack[key] for key in required}, required, 'Acknowledged role binding differs')
    chain = ack['ancestry']
    if type(chain) is not dict or set(chain) != {'nodes', 'fresh_chain_before', 'fresh_chain_after'}:
        raise cp.IntegrityError('Malformed ancestry evidence')
    nodes = chain['nodes']
    if type(nodes) is not list or not nodes:
        raise cp.IntegrityError('Missing verified ancestry nodes')
    _same(nodes[0], dict(identity=role_identity, raw_creation=ready['raw_creation']), 'Role ancestry differs')
    _same(nodes[-1], dict(identity=ack['launcher_identity'], raw_creation=ack['launcher_raw_creation']),
          'Launcher ancestry differs')
    pids, ticks = [], []
    for node in nodes:
        if type(node) is not dict or set(node) != {'identity', 'raw_creation'}:
            raise cp.IntegrityError('Malformed ancestry node')
        identity = _native_identity(node['identity'])
        raw = observer.parse_raw_creation(node['raw_creation'])
        if (identity['boot_time'] != role_identity['boot_time']
                or identity['create_time'] != observer.normalize_creation(raw)):
            raise cp.IntegrityError('Ancestry identity differs from native timestamp')
        ticks.append(raw)
        pids.append(identity['pid'])
    edges = [[child, parent] for child, parent in zip(pids, pids[1:])]
    if len(pids) != len(set(pids)) or any(child < parent for child, parent in zip(ticks, ticks[1:])):
        raise cp.IntegrityError('Invalid ancestry order')
    _same(chain['fresh_chain_before'], edges, 'First observed parent chain differs')
    _same(chain['fresh_chain_after'], edges, 'Second observed parent chain differs')
    return ack


def _code(value):
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise cp.IntegrityError('Exit code must be an exact DWORD integer')
    return value


def _failure_descriptor(files):
    path = _artifact(files.folder, files.failure)
    if not path.exists():
        return None
    value = _read(files.folder, path)
    if (value.get('role') != files.role or value.get('episode') != files.episode
            or type(value.get('timeout_stop')) is not bool
            or type(value.get('message')) is not str or value.get('scientific_success') is not False):
        raise cp.IntegrityError('Malformed role failure evidence')
    return _desc(files.folder, path)


def _handshake_descriptors(files):
    return {name.removesuffix('.json'): _desc(files.folder, files.external / name)
            for name in HANDSHAKE_FILES}


def _project_exit(files, reported):
    return dict(schema='v80_role_exit', role=files.role, episode=files.episode,
                identity=reported['role_identity'], exit_code=reported['role_exit_code'],
                launcher=reported['launcher'], observation=_desc(files.folder, files.external / 'exit_observation.json'),
                started_utc=reported['started_utc'], actual_exit_observed_utc=reported['actual_exit_observed_utc'],
                stop_request=reported['stop_request'], tracked=reported['tracked'],
                child_failure=reported['child_failure'],
                normal_observed=(reported['state'] == 'observed' and reported['role_exit_code'] == 0
                                 and reported['launcher']['exit_code'] == 0
                                 and reported['stop_request'] is None and reported['child_failure'] is None))


def _role_receipt(folder, episode, role):
    folder = Path(folder)
    if isinstance(episode, Path):
        if episode.parent != folder / 'internal' / 'episodes':
            raise cp.IntegrityError('Episode path is outside this run')
        episode = episode.name
    files = _RoleFiles(folder, episode, role)
    if _artifact(files.folder, files.external / 'delivery_veto.json').exists():
        raise cp.IntegrityError('Role delivery was vetoed')
    launch = _load_launch(files)
    _, identity = _load_ready(files, launch)
    ack = _load_ack(files, launch, identity)
    value = _record(_read(files.folder, files.external / 'exit_observation.json'), {
        'role', 'episode', 'request', 'handshake', 'state', 'same_handle_signaled', 'query_succeeded',
        'role_identity', 'role_exit_code', 'launcher', 'started_utc', 'actual_exit_observed_utc',
        'stop_request', 'tracked', 'child_failure', 'diagnostic'}, 'v80_role_exit_observation')
    required = dict(role=role, episode=files.episode, request=launch['request'],
                    handshake=_handshake_descriptors(files), state='observed', role_identity=identity,
                    same_handle_signaled=True, query_succeeded=True, stop_request=None,
                    child_failure=_failure_descriptor(files), diagnostic=None)
    _same({key: value[key] for key in required}, required, 'Independent role exit unavailable or changed')
    _code(value['role_exit_code'])
    if value['role_exit_code'] == 259:
        raise cp.IntegrityError('STILL_ACTIVE sentinel is outside this exit contract')
    _same(value['launcher'], dict(identity=ack['launcher_identity'], exit_code=_code(value['launcher']['exit_code'])),
          'Launcher projection differs from held launch identity')
    tracked = [_native_identity(item) for item in value['tracked']]
    if (len({(item['pid'], item['create_time']) for item in tracked}) != len(tracked)
            or any(node['identity'] not in tracked for node in ack['ancestry']['nodes'])
            or any(item['boot_time'] != identity['boot_time'] for item in tracked)
            or cp._time(value['started_utc']) > cp._time(value['actual_exit_observed_utc'])):
        raise cp.IntegrityError('Role exit lacks complete tracked lineage or ordered timestamps')
    projected = _project_exit(files, value)
    _same(_read(files.folder, files.receipt), projected, 'Role receipt is not the independent observation projection')
    return projected


def _watch_adapter(bound_check):
    def watch():
        bound_check()
        return None
    return watch


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


def _native_identity(value):
    try:
        return observer.require_identity(value)
    except observer.RoleObservationError as error:
        raise cp.IntegrityError('Invalid native Windows process identity') from error


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
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
    path = Path(folder).absolute()
    try:
        name = path.relative_to(ROOT).as_posix()
    except ValueError as error:
        raise cp.IntegrityError('V80 output escaped repository') from error
    if not name.startswith('shop-mysql-runtime/v80/runs/'):
        raise cp.IntegrityError('V80 output must be below shop-mysql-runtime/v80/runs')
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
            raise cp.BudgetExceeded('V80 absolute or cumulative deadline reached')
        if resource_check is not None:
            outcome = resource_check()
            if outcome is not None and outcome is not True:
                raise cp.BudgetExceeded('Synthetic resource guard rejected continuation')
        self.last_sample = (now, mono, elapsed)
        return min(self.deadline - now, self.budget - elapsed)


def _reenter(request):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
    admitted = bundle.admit(**request['admission'])
    _scope(admitted)
    _same(admitted['binding'], request['binding'], 'Saved request binding changed')
    return admitted


def _source_checker(admitted, path, labels):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
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


def _external_evidence(folder):
    if _artifact(folder, folder / _FINAL_VETO).exists():
        raise cp.IntegrityError('Final delivery was vetoed')
    path = folder / 'control' / 'episodes'
    if not _artifact(folder, path).is_dir():
        raise cp.IntegrityError('Missing external role evidence directory')
    return [dict(row, path='control/episodes/' + row['path']) for row in _snapshot(path)]


def _validate_episodes(folder, active_episode=None):
    internal = _artifact(folder, folder / 'internal' / 'episodes')
    external = _artifact(folder, folder / 'control' / 'episodes')
    known = {path.name for path in internal.iterdir()}
    if known != {path.name for path in external.iterdir()}:
        raise cp.IntegrityError('External episode set differs from internal evidence')
    identities = []
    for episode in sorted(known):
        internal_episode = _artifact(folder, internal / episode)
        external_episode = _artifact(folder, external / episode)
        contents = {path.name for path in internal_episode.iterdir()}
        if contents - EPISODE_FILES or any(not _artifact(folder, path).is_file()
                                          for path in internal_episode.iterdir()):
            raise cp.IntegrityError('Undeclared internal evidence file')
        active = episode == active_episode
        ext_names = {'roles'} if active else {'roles', 'pipeline_exit.json'}
        if {path.name for path in external_episode.iterdir()} != ext_names:
            raise cp.IntegrityError('Undeclared or missing external episode entry')
        roles = {'pipeline'} | {role for role in ('worker', 'publisher') if any(
            item.startswith(role + '_') or item == role + '.log' for item in contents)}
        if active and 'publisher' not in roles:
            raise cp.IntegrityError('Active publisher handshake is missing')
        if {path.name for path in (external_episode / 'roles').iterdir()} != roles:
            raise cp.IntegrityError('External role set differs from declared work')
        for role in sorted(roles):
            files = _RoleFiles(folder, episode, role)
            running = active and role in {'publisher', 'pipeline'}
            expected = set(HANDSHAKE_FILES) | (set() if running else {'exit_observation.json'})
            if {path.name for path in _artifact(folder, files.external).iterdir()} != expected:
                raise cp.IntegrityError('Role evidence missing, vetoed, or outside closed manifest')
            if running:
                launch = _load_launch(files)
                _, identity = _load_ready(files, launch)
                _load_ack(files, launch, identity)
            else:
                receipt = _role_receipt(folder, episode, role)
                identities.extend(receipt['tracked'])
    return identities


def _original_worker(folder, normal):
    matches = []
    for exit_path in sorted((folder / 'internal' / 'episodes').glob('*/worker_exit.json')):
        if _read(folder, exit_path)['identity'] == normal['worker_identity']:
            matches.append(exit_path.parent)
    if len(matches) != 1:
        raise cp.IntegrityError('Exactly one raw worker exit observation required')
    episode = matches[0]
    receipt = _role_receipt(folder, episode, 'worker')
    if (receipt['normal_observed'] is not True or _code(normal['exit_code']) != 0
            or receipt['actual_exit_observed_utc'] > cp._time(normal['observed_utc'])):
        raise cp.IntegrityError('Historical worker did not deliver a normal exit')
    _same(_read(folder, episode / 'pipeline_identity.json'), normal['supervisor_identity'],
          'Original observing supervisor identity differs')
    return receipt


def audit_saved(admitted, run_dir, *, source_check=None, watch=lambda: None, active_episode=None):
    """P9: raw provenance proof, without ranking or numerical aggregate replay."""
    n = _scope(admitted)
    supplied = Path(run_dir).absolute()
    folder = _folder(supplied.parent.parent)
    run_dir = _artifact(folder, supplied)
    if run_dir != folder / 'internal' / 'cp':
        raise cp.IntegrityError('Publisher requires the sealed synthetic CP namespace')
    role_prefix = _external_evidence(folder)
    if source_check is None:
        from scripts import retailrocket_session_knn_bundle_v80 as bundle
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
    _original_worker(folder, normal)
    _validate_episodes(folder, active_episode)
    watch()
    source_check()  # H8, after complete raw proof.
    _same(_snapshot(run_dir), before, 'Accepted science changed during publication')
    _same(_external_evidence(folder), role_prefix, 'Role evidence changed during publication')
    return dict(status='v80_synthetic_raw_publication_proof', synthetic=True,
                request=cp.descriptor(run_dir.parent, 'request.json'),
                binding_sha256=hashlib.sha256(cp.encoded(request['binding'])).hexdigest(),
                run_sha256=store.run_sha, queries=count, visitors=len(visitors),
                bootstrap_replicates=2000, roster_sha256=roster.hexdigest(),
                science_payload_sha256=payloads.hexdigest(), cp_evidence=before, role_evidence_prefix=role_prefix,
                source_positions=['H7', 'H8'], ranking_calls=0,
                global_numeric_replays=0, draw_numeric_replays=0,
                full_real_acceptance=False, real_T_plan=None)


def _request_deadline(request, folder, role, *, clock=None):
    return Deadline(request, folder / 'control' / 'budgets' /
                    (role + '-' + str(os.getpid()) + '.json'), clock=clock)


def _formal_limit():
    formal = float(os.environ['V80_FORMAL_DEADLINE_MONOTONIC'])
    inherited = float(os.environ.get('V80_ROLE_DEADLINE_MONOTONIC', formal))
    if not math.isfinite(formal) or not math.isfinite(inherited):
        raise ValueError('Finite formal and inherited work deadlines required')
    return min(formal, inherited)


def _formal_authority(admission):
    from scripts import run_retailrocket_session_knn_acceptance_v80 as formal
    request = formal._authoritative_request(formal.PRIVATE / 'window1', inherited=True)
    if any(admission.get(name) != request[name] for name in ('method_seal_sha256', 'fixture_seal_sha256')):
        raise cp.IntegrityError('Role admission does not bind the authorized formal window')


def _post_delivery(guard, monotonic_deadline, resource_check=None, *, monotonic=None):
    guard.check(resource_check)
    now, elapsed_clock = guard.clock.utc(), guard.clock.monotonic()
    current_mono = (time.monotonic if monotonic is None else monotonic)()
    prior_utc, prior_mono, prior_elapsed = guard.last_sample
    if (not all(map(math.isfinite, (now, elapsed_clock, current_mono, monotonic_deadline)))
            or now < prior_utc or elapsed_clock < prior_mono or now >= guard.deadline
            or current_mono >= monotonic_deadline
            or max(now - guard.started, prior_elapsed + elapsed_clock - prior_mono) >= guard.budget):
        raise cp.BudgetExceeded('Deadline reached after evidence delivery and budget persistence')


def _ticket_key(files):
    return (files.folder, files.episode, files.role)


def _mint_ticket(key, evidence):
    if key in _TICKETS:
        raise cp.IntegrityError('Role delivery ticket already issued')
    ticket = _DeliveryTicket(key, os.getpid(), evidence)
    _TICKETS[key] = ticket
    return ticket


def _require_ticket(ticket, key, evidence):
    if (_TICKETS.get(key) is not ticket or type(ticket) is not _DeliveryTicket
            or ticket.key != key or ticket.issuer_pid != os.getpid() or ticket.binding != evidence):
        raise cp.IntegrityError('Complete on-disk role receipt has no live delivery ticket')


def _ticket_binding(files):
    return cp.encoded(dict(receipt=_desc(files.folder, files.receipt),
                           observation=_desc(files.folder, files.external / 'exit_observation.json'),
                           handshake=_handshake_descriptors(files)))


def _save_veto(files, path, limit, error):
    folder = files.folder
    try:
        receipt = _artifact(folder, files.receipt)
        observation = _artifact(folder, files.external / 'exit_observation.json')
        final = _artifact(folder, folder / 'final_seal.json')
        _artifact(folder, path)
        cp.atomic_json(path, dict(schema='v80_delivery_veto', role=files.role, episode=files.episode,
                                  request=_desc(folder, folder / 'internal/request.json'),
                                  receipt=_desc(folder, receipt) if receipt.is_file() else None,
                                  observation=_desc(folder, observation) if observation.is_file() else None,
                                  final_seal=_desc(folder, final) if final.is_file() else None,
                                  phase='final_delivery' if path == folder / _FINAL_VETO
                                        else 'role_delivery', deadline_monotonic=limit,
                                  error_type=type(error).__name__, reason=str(error)))
    except Exception as veto_error:
        error.add_note(f'Could not save delivery veto: {veto_error}')


def _track_descendants(process, launcher, tracked, process_api):
    if not process_api.is_alive(launcher):
        return
    try:
        parent = psutil.Process(process.pid)
        if parent.create_time() != launcher['create_time']:
            raise cp.IntegrityError('Launcher changed during descendant tracking')
        for child in parent.children(recursive=True):
            try:
                identity = dict(pid=child.pid, create_time=child.create_time(), boot_time=launcher['boot_time'])
            except psutil.NoSuchProcess:
                continue
            tracked[(identity['pid'], identity['create_time'])] = identity
    except psutil.NoSuchProcess:
        return


def _stop_role(process, tracked, process_api):
    errors = []
    for identity in reversed(list(tracked.values())):
        try:
            if process_api.is_alive(identity):
                child = psutil.Process(identity['pid'])
                if child.create_time() == identity['create_time']:
                    child.terminate()
        except psutil.NoSuchProcess:
            continue
        except Exception as error:
            errors.append(error)
    if process is not None:
        try:
            if process.poll() is None:
                process.terminate()  # Popen owns the original launcher handle.
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except Exception as error:
            errors.append(error)
    try:
        _assert_stopped(tracked.values(), process_api)
    except Exception as error:
        errors.append(error)
    return errors


def _release_role(files, nonce):
    launch = _load_launch(files)
    if launch['nonce'] != nonce:
        raise cp.IntegrityError('Role arguments do not bind the declared launch')
    request = _read(files.folder, files.folder / 'internal/request.json')
    guard = _request_deadline(request, files.folder, files.role)
    limit = _formal_limit()
    _post_delivery(guard, limit)
    identity = cp.Processes().identity()
    raw_creation = observer.self_ready(identity)
    cp.atomic_json(_artifact(files.folder, files.identity), identity)
    ready = dict(schema='v80_role_ready', launch=_desc(files.folder, files.external / 'launch.json'),
                 nonce=nonce, identity=_desc(files.folder, files.identity),
                 pid=identity['pid'], raw_creation=raw_creation)
    cp.atomic_json(_artifact(files.folder, files.external / 'ready.json'), ready)
    path = _artifact(files.folder, files.external / 'ack.json')
    while not path.exists():
        _post_delivery(guard, limit)
        time.sleep(0.02)
    _load_ack(files, launch, identity)
    handshake = _handshake_descriptors(files)
    _post_delivery(guard, limit)
    return handshake


def _diagnostic(error):
    return dict(error_type=type(error).__name__, reason=str(error),
                api=getattr(error, 'api', None), winerror=getattr(error, 'winerror', None),
                raw_os_exit_code=getattr(error, 'raw_exit_code', None))


def _launch_role(files, guard, *, resource_check=None, process_api=None):
    """Supervise one declared role and return its live delivery authority."""
    process_api = cp.Processes() if process_api is None else process_api
    started = guard.clock.utc()
    limit = min(_formal_limit(), time.monotonic() + 120.0)

    def check():
        _post_delivery(guard, limit, resource_check)

    check()
    folder = files.folder
    nonce = uuid.uuid4().hex
    launch = _protocol_binding(files, guard.request, nonce, process_api.identity())
    directory = _artifact(folder, files.external)
    directory.mkdir(parents=True, exist_ok=False)
    cp.atomic_json(directory / 'launch.json', launch)
    tracked = {}

    def track(identity):
        tracked[(identity['pid'], identity['create_time'])] = identity

    process = held = identity = launcher = role_code = observed_utc = launcher_code = None
    handshake = None
    observation_path = directory / 'exit_observation.json'
    log_path = _artifact(folder, files.internal / (files.role + '.log'))
    env = dict(os.environ, V80_ROLE_DEADLINE_MONOTONIC=str(limit))
    try:
        check()
        with log_path.open('xb', buffering=0) as log:
            process = subprocess.Popen(_command(files, nonce), cwd=ROOT, env=env,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            held = observer.HeldRole(process, boot_identity=process_api.boot_identity, track=track)
            launcher = held.launcher_identity
            ready_path = _artifact(folder, directory / 'ready.json')
            while not ready_path.exists():
                check()
                _track_descendants(process, launcher, tracked, process_api)
                if process.poll() is not None:
                    raise cp.IntegrityError('Original launcher exited before role ready')
                time.sleep(0.02)
            ready, identity = _load_ready(files, launch)
            native = held.admit(identity, ready['raw_creation'], check=check)
            ack = dict(schema='v80_role_ack', **native, nonce=nonce, launch=ready['launch'],
                       ready=_desc(folder, ready_path), identity=ready['identity'],
                       observer_identity=launch['observer_identity'])
            held.recheck_pre_ack(check=check)
            cp.atomic_json(directory / 'ack.json', ack)
            held.mark_acknowledged()
            handshake = _handshake_descriptors(files)
            while True:
                check()
                _track_descendants(process, launcher, tracked, process_api)
                launcher_code = process.poll()
                if role_code is None:
                    role_code = held.poll_exit()
                    if role_code is not None:
                        observed_utc = guard.clock.utc()
                if role_code is not None and launcher_code is not None:
                    break
                if launcher_code is not None:
                    raise cp.IntegrityError('Launcher exited before observing role signal')
                time.sleep(0.02)
        _code(launcher_code)
        held.close()
        # Those two exact native objects have already signaled. Retaining the
        # Popen owner can keep a stopped process visible to PID enumeration.
        _assert_stopped((item for item in tracked.values() if item not in (launcher, identity)), process_api)
        failure = _failure_descriptor(files)
        record = dict(schema='v80_role_exit_observation', role=files.role, episode=files.episode,
                      request=launch['request'], handshake=handshake, state='observed',
                      same_handle_signaled=True, query_succeeded=True, role_identity=identity,
                      role_exit_code=_code(role_code), launcher=dict(identity=launcher, exit_code=launcher_code),
                      started_utc=started, actual_exit_observed_utc=observed_utc, stop_request=None,
                      tracked=list(tracked.values()), child_failure=failure, diagnostic=None)
        cp.atomic_json(observation_path, record)
        projection = _project_exit(files, record)
        cp.atomic_json(_artifact(folder, files.receipt), projection)
        receipt = _role_receipt(folder, files.episode, files.role)
        receipt_descriptor = _desc(folder, files.receipt)
        binding = _ticket_binding(files)
        if failure is not None and _read(folder, files.failure)['timeout_stop']:
            raise TimeoutError('Synthetic descendant deadline/watchdog failure')
        if role_code == 0 and not receipt['normal_observed']:
            raise cp.IntegrityError('Role code 0 contradicts launcher or failure evidence')
        check()  # Includes receipt readback, close, and the guard's own state write.
        ticket = _mint_ticket(_ticket_key(files), binding)
    except BaseException as error:
        stop = dict(requested_utc=guard.clock.utc(), reason=type(error).__name__)
        for cleanup_error in _stop_role(process, tracked, process_api):
            error.add_note(f'Observed process cleanup failure: {cleanup_error}')
        if held is not None:
            try:
                held.close()
            except Exception as close_error:
                error.add_note(f'Role handle cleanup failure: {close_error}')
        if process is not None and process.returncode is not None:
            launcher_code = process.returncode
        if not observation_path.exists():
            try:
                diagnosis = _diagnostic(error)
                independent = role_code is not None and handshake is not None
                cp.atomic_json(observation_path, dict(
                    schema='v80_role_exit_observation', role=files.role, episode=files.episode,
                    request=launch['request'], handshake=handshake, state='unconfirmed',
                    same_handle_signaled=(independent or diagnosis['api'] == 'GetExitCodeProcess'),
                    query_succeeded=(independent or diagnosis['raw_os_exit_code'] == 259),
                    role_identity=identity, role_exit_code=role_code if independent else None,
                    launcher=dict(identity=launcher, exit_code=launcher_code),
                    started_utc=started, actual_exit_observed_utc=observed_utc, stop_request=stop,
                    tracked=list(tracked.values()), child_failure=_failure_descriptor(files), diagnostic=diagnosis))
            except Exception as save_error:
                error.add_note(f'Could not save unconfirmed role evidence: {save_error}')
        _save_veto(files, directory / 'delivery_veto.json', limit, error)
        raise
    if role_code != 0:
        raise _RoleChildError(files.role, receipt, receipt_descriptor, ticket)
    return ticket


def _launch(command, log_path, receipt_path, guard, *, route, resource_check=None,
            process_api=None, watch_seconds=120):
    """Preserve launcher-only observations for explicitly generic synthetic commands."""
    if route != 'generic_synthetic' or len(command) != 4 or command[:3] != [sys.executable, '-B', '-c']:
        raise cp.IntegrityError('Explicit generic synthetic command required')
    process_api = process_api or cp.Processes()
    remaining = guard.check(resource_check)
    # The suite carrier has the whole formal window; each work child also
    # inherits that window's remaining budget, in addition to its 120 s cap.
    began = time.monotonic()
    formal_deadline = _formal_limit()
    formal_remaining = formal_deadline - began
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
    _post_delivery(guard, min(formal_deadline, began + timeout), resource_check)
    if failure is not None and code == 0:
        raise cp.IntegrityError('Child success contradicts structured failure receipt')
    if code != 0:
        if failure is not None and failure.get('timeout_stop') is True:
            raise TimeoutError('Synthetic descendant deadline/watchdog failure: ' + failure['message'])
        raise RuntimeError('Synthetic child did not exit normally: ' + str(code))
    return receipt


def _worker(folder, episode, handshake):
    from scripts import retailrocket_session_knn_full_worker_v75 as worker
    internal = folder / 'internal'
    request = cp.read(internal / 'request.json')
    admitted = _reenter(request)
    scenario = _scenario(cp.read(episode / 'scenario.json'))
    identity = _read(folder, episode / 'worker_identity.json')
    request_descriptor = _desc(folder, internal / 'request.json')
    count = 0

    def fault(point):
        nonlocal count
        if point == scenario.get('worker_fault'):
            count += 1
            if count == scenario.get('worker_after', 1):
                marker = dict(schema='v80_worker_fault_marker', role='worker', episode=episode.name,
                              request=request_descriptor, identity=identity, ready=handshake['ready'],
                              ack=handshake['ack'], fault_point=point, occurrence=count, planned_code=9)
                sys.stdout.write(FAULT_MARKER + cp.encoded(marker).decode('utf-8'))
                sys.stdout.flush()
                os.fsync(sys.stdout.fileno())
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
                           watch=_watch_adapter(store.check_budget), fault=fault)


def _publisher(folder, episode, _handshake):
    internal = folder / 'internal'
    request = cp.read(internal / 'request.json')
    admitted = _reenter(request)
    scenario = _scenario(cp.read(episode / 'scenario.json'))
    guard = _request_deadline(request, folder, 'publisher')
    if scenario.get('publisher_fault') == 'before_proof':
        raise RuntimeError('Injected synthetic publisher fault before proof')
    proof = audit_saved(admitted, internal / 'cp', watch=guard.check, active_episode=episode.name,
                        source_check=_source_checker(admitted,
                            episode / 'publisher_sources.jsonl', ['H7', 'H8']))
    guard.check()
    cp.atomic_json(episode / 'publisher_proof.json', proof)
    if scenario.get('publisher_fault') == 'after_proof':
        raise RuntimeError('Injected synthetic publisher fault after proof')
    print('v80 publisher proof closed', flush=False)


def _delivered(files, ticket):
    receipt = _role_receipt(files.folder, files.episode, files.role)
    _require_ticket(ticket, _ticket_key(files), _ticket_binding(files))
    if receipt['normal_observed'] is not True:
        raise cp.IntegrityError('Role did not deliver a normal exit')
    return receipt


def _pipeline(folder, episode, _handshake):
    from scripts import retailrocket_session_knn_full_worker_v75 as worker
    internal = folder / 'internal'
    request = cp.read(internal / 'request.json')
    admitted = _reenter(request)
    scenario = _scenario(cp.read(episode / 'scenario.json'))
    guard = _request_deadline(request, folder, 'pipeline')
    run_dir = internal / 'cp'
    if not (run_dir / 'acceptance.json').exists():
        if (run_dir / 'normal_worker_exit.json').exists():
            normal = cp.read(run_dir / 'normal_worker_exit.json')
            exited = _original_worker(folder, normal)
        else:
            files = _RoleFiles(folder, episode.name, 'worker')
            exited = _delivered(files, _launch_role(files, guard))
        def fault(point):
            if point == scenario.get('finalize_fault'):
                raise RuntimeError('Injected finalize fault before acceptance')
        store = worker.open_store(run_dir, admitted['binding'],
                    source_root=admitted['bundle_root'], fault=fault,
                    external_source_verifier=_source_checker(admitted,
                        episode / 'supervisor_sources.jsonl', ['H4', 'H5', 'H6']))
        guard.check()
        store.finalize(cp.descriptor(run_dir, 'candidate.json')['sha256'], exited['identity'], exited['exit_code'])
    guard.check()
    files = _RoleFiles(folder, episode.name, 'publisher')
    _delivered(files, _launch_role(files, guard))
    guard.check()
    cp.atomic_json(episode / 'pipeline_result.json', dict(
        status='v80_pipeline_completed_not_outer_acceptance',
        proof=cp.descriptor(episode, 'publisher_proof.json'),
        cp_acceptance=cp.descriptor(run_dir, 'acceptance.json')))
    print('v80 pipeline publication closed', flush=False)


def _sealed_episode(folder):
    candidates = []
    for episode in sorted((folder / 'internal' / 'episodes').iterdir()):
        result_path = _artifact(folder, episode / 'pipeline_result.json')
        if result_path.exists():
            receipt = _role_receipt(folder, episode, 'pipeline')
            if receipt['normal_observed'] is True:
                candidates.append(episode)
    if len(candidates) > 1:
        raise cp.IntegrityError('Multiple completed publication episodes')
    return candidates[0] if candidates else None


def _completed_episode(folder):
    episode = _sealed_episode(folder)
    if episode is not None:
        files = _RoleFiles(folder, episode.name, 'pipeline')
        _delivered(files, _TICKETS.get(_ticket_key(files)))
    return episode


def _final_binding(folder, episode):
    return cp.encoded(dict(seal=_desc(folder, folder / 'final_seal.json'),
                           pipeline=_desc(folder, _RoleFiles(folder, episode, 'pipeline').receipt)))


def _capture_formal_deliveries():
    """Snapshot runs actually delivered by the suite carrier's live outer."""
    receipts = []
    for key, ticket in sorted(_TICKETS.items()):
        folder, episode, role = key
        if role == 'final':
            _require_ticket(ticket, key, _final_binding(folder, episode))
            receipts.append(dict(run=folder.relative_to(ROOT).as_posix(),
                                 final_seal=_desc(folder, folder / 'final_seal.json')))
    _check_formal_deliveries(receipts)
    return receipts


def _check_formal_deliveries(receipts):
    """File-only post-suite check of successful runs, including any late veto."""
    if type(receipts) is not list or not receipts:
        raise cp.IntegrityError('Completed suite has no delivered run evidence')
    seen = set()
    for row in receipts:
        if (type(row) is not dict or set(row) != {'run', 'final_seal'}
                or type(row['run']) is not str or row['run'] in seen):
            raise cp.IntegrityError('Invalid completed run evidence roster')
        seen.add(row['run'])
        folder = _folder(ROOT / row['run'])
        if folder.relative_to(ROOT).as_posix() != row['run']:
            raise cp.IntegrityError('Completed run path is not canonical')
        path = folder / 'final_seal.json'
        _same(_desc(folder, path), row['final_seal'], 'Completed run seal changed')
        seal = _read(folder, path)
        _same(_external_evidence(folder), seal['external_role_evidence'],
              'Completed run external evidence changed or was vetoed')
        _validate_episodes(folder)  # read closed namespaces, never mint a ticket
        _same(_snapshot(folder / 'internal'), seal['internal_evidence'],
              'Completed run internal evidence changed')
        _same(_desc(folder, path), row['final_seal'], 'Completed run seal changed during recheck')


def _check_publisher_prefix(folder, episode, proof, external):
    publisher = _RoleFiles(folder, episode.name, 'publisher')
    pipeline = _RoleFiles(folder, episode.name, 'pipeline')
    suffix = {_relative(folder, pipeline.receipt),
              _relative(folder, pipeline.external / 'exit_observation.json'),
              _relative(folder, publisher.external / 'exit_observation.json')}
    _same([row for row in external if row['path'] not in suffix], proof['role_evidence_prefix'],
          'Publisher role evidence prefix changed before final seal')


def finalize_stopped(folder, *, process_api=None, clock=None, expected=None,
                     resource_check=None, fault=lambda point: None):
    """Seal stopped evidence, or audit it without re-authorizing delivery."""
    folder = _folder(folder)
    internal = folder / 'internal'
    process_api = process_api or cp.Processes()
    external = _external_evidence(folder)
    identities = _validate_episodes(folder)
    if expected is None:
        episode = _completed_episode(folder)
        request = _read(folder, internal / 'request.json')
        guard = _request_deadline(request, folder, 'finalizer', clock=clock)
        limit = _formal_limit()
        _post_delivery(guard, limit, resource_check)
    else:
        episode = _sealed_episode(folder)
    if episode is None:
        raise cp.IntegrityError('No independently observed complete publication episode')
    _assert_stopped(identities, process_api)
    if {p.name for p in internal.iterdir()} != {'request.json', 'cp', 'episodes'}:
        raise cp.IntegrityError('Undeclared internal namespace entry')
    proof = _read(folder, episode / 'publisher_proof.json')
    result = _read(folder, episode / 'pipeline_result.json')
    _same(result['proof'], cp.descriptor(episode, 'publisher_proof.json'), 'Publisher proof seal differs')
    _same(result['cp_acceptance'], cp.descriptor(internal / 'cp', 'acceptance.json'),
          'Accepted CP changed before stopped seal')
    _same(proof['request'], cp.descriptor(internal, 'request.json'), 'Proof request differs')
    _same(proof['cp_evidence'], _snapshot(internal / 'cp'), 'Accepted science changed after proof')
    publisher_exit = _role_receipt(folder, episode, 'publisher')
    if publisher_exit['normal_observed'] is not True:
        raise cp.IntegrityError('Publisher did not have an independently observed normal exit')
    _check_publisher_prefix(folder, episode, proof, external)
    before = _snapshot(internal)
    _assert_stopped(identities, process_api)
    _same(_snapshot(internal), before, 'Internal evidence changed while sealing')
    _same(_external_evidence(folder), external, 'External evidence changed while sealing')
    pipeline_exits = [row for row in external if row['path'].endswith('/pipeline_exit.json')]
    seal = dict(status='v80_synthetic_stopped_full_pipeline_evidence', synthetic=True,
                internal_evidence=before, pipeline_exit_evidence=pipeline_exits,
                external_role_evidence=external, publication_episode=episode.name,
                proof=cp.descriptor(internal, 'episodes/' + episode.name + '/publisher_proof.json'),
                queries=proof['queries'], visitors=proof['visitors'],
                bootstrap_replicates=proof['bootstrap_replicates'],
                cp_path=(internal / 'cp').relative_to(ROOT).as_posix(),
                full_real_acceptance=False, real_T_plan=None, reserved_test='locked')
    path = _artifact(folder, folder / 'final_seal.json')
    key = (folder, episode.name, 'final')
    if expected is not None:
        _same(seal, expected, 'Post-seal evidence set or bytes changed')
        _same(_read(folder, path), seal, 'Saved final seal changed')
        ticket = _TICKETS.get(key)
        if ticket is None:
            return dict(status='v80_readonly_evidence_verified_delivery_unknown', evidence=seal)
        _require_ticket(ticket, key, _final_binding(folder, episode.name))
        return seal
    _post_delivery(guard, limit, resource_check)
    fault('before_final_commit')
    try:
        cp.atomic_json(path, seal)
        _same(_read(folder, path), seal, 'Final seal readback differs')
        _same(_external_evidence(folder), external, 'External evidence changed during final delivery')
        _same(_snapshot(internal), before, 'Internal evidence changed during final delivery')
        binding = _final_binding(folder, episode.name)
        _post_delivery(guard, limit, resource_check)
        _mint_ticket(key, binding)
    except BaseException as error:
        _save_veto(_RoleFiles(folder, episode.name, 'pipeline'), folder / _FINAL_VETO, limit, error)
        raise
    return seal


def run_pipeline(admitted, folder, *, scenario=None, clock=None, process_api=None,
                 resource_check=None, budget_seconds=120):
    """Start or continue a source-bound synthetic run under the inherited formal deadline."""
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
    limit = _formal_limit()
    _formal_authority(admitted['admission'])
    admitted = bundle.admit(**admitted['admission'])
    _scope(admitted)
    folder = _folder(folder)
    scenario = _scenario(scenario)
    clock = clock or cp.Clock()
    if _artifact(folder, folder / 'final_seal.json').exists():
        raise cp.IntegrityError('Existing synthetic seal is readonly')
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
    request = _read(folder, folder / 'internal' / 'request.json')
    _same(request['admission'], admitted['admission'], 'Cannot rebind a synthetic run')
    _same(request['binding'], admitted['binding'], 'Cannot change run sources or method')
    guard = _request_deadline(request, folder, 'outer', clock=clock)
    _post_delivery(guard, limit, resource_check)
    _external_evidence(folder)
    _assert_stopped(_validate_episodes(folder), process_api or cp.Processes())
    if _completed_episode(folder) is None:
        episode = folder / 'internal' / 'episodes' / uuid.uuid4().hex
        episode.mkdir()
        cp.atomic_json(episode / 'scenario.json', scenario)
        _launch_role(_RoleFiles(folder, episode.name, 'pipeline'), guard,
                     resource_check=resource_check, process_api=process_api)
    _post_delivery(guard, limit, resource_check)

    def fault(point):
        if point == scenario.get('finalizer_fault'):
            raise RuntimeError('Injected finalizer fault before external publication')

    return finalize_stopped(folder, process_api=process_api, clock=clock,
                            resource_check=resource_check, fault=fault)


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
    parser = argparse.ArgumentParser(description='Sealed V80 synthetic child process only')
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('worker', 'publisher', 'pipeline'):
        modes.add_argument('--' + name, type=Path)
    parser.add_argument('--episode', required=True)
    parser.add_argument('--nonce', required=True)
    args = parser.parse_args()
    if len(args.episode) != 32 or any(c not in '0123456789abcdef' for c in args.episode):
        raise ValueError('Exact synthetic episode identifier required')
    mode = next(name for name in ('worker', 'publisher', 'pipeline') if getattr(args, name))
    folder = _folder(getattr(args, mode))
    episode = folder / 'internal' / 'episodes' / args.episode
    if not episode.is_dir() or episode.is_symlink():
        raise ValueError('Predeclared synthetic episode required')
    try:
        files = _RoleFiles(folder, episode.name, mode)
        request = _read(folder, folder / 'internal/request.json')
        _formal_authority(request['admission'])
        handshake = _release_role(files, args.nonce)
        {'worker': _worker, 'publisher': _publisher, 'pipeline': _pipeline}[mode](folder, episode, handshake)
    except BaseException as error:
        timeout = isinstance(error, (TimeoutError, subprocess.TimeoutExpired, cp.BudgetExceeded))
        failure = dict(role=mode, episode=episode.name, error_type=type(error).__name__,
                       message=str(error), traceback=traceback.format_exc(),
                       timeout_stop=timeout, retry_allowed=False if timeout else None,
                       scientific_success=False)
        if isinstance(error, _RoleChildError):
            failure.update(failed_child_role=error.role, failed_child_exit_code=error.receipt['exit_code'],
                           failed_child_observation=error.receipt['observation'],
                           failed_child_receipt=error.receipt_descriptor)
        cp.atomic_json(episode / (mode + '_failure.json'), failure)
        raise


if __name__ == '__main__':
    main()
