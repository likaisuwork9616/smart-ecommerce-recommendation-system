"""Durable, source-bound checkpoints for a separate K1 readback protocol.

This module performs no fitting, ranking, bootstrap, or V1 mutation. A committed
chunk certifies only the caller's completed per-query checks. Final acceptance
requires a distinct supervisor, a normal worker exit, and all required seals.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import time
import uuid

import psutil


class IntegrityError(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class WriterBusy(RuntimeError):
    pass


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def _invalid_constant(value):
    raise IntegrityError('Nonfinite JSON constant')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=_invalid_constant)


def atomic_json(path, value):
    """Atomically publish a new JSON artifact; an existing target is immutable."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('xb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def _inside(root, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(p in ('', '.', '..') for p in name.split('/'))
            or PurePosixPath(name).is_absolute()):
        raise IntegrityError('Unsafe relative artifact path')
    root = Path(root).resolve()
    path = root / name
    if not path.resolve().is_relative_to(root):
        raise IntegrityError('Artifact leaves its bound root')
    return path


def descriptor(root, name):
    path = _inside(root, name)
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise IntegrityError('Artifact changed during identity check')
    return {'path': name, 'bytes': after.st_size, 'sha256': digest}


def bind_sources(source_root, relative_paths):
    names = list(relative_paths)
    if len(names) != len(set(names)):
        raise IntegrityError('Duplicate source binding')
    return [descriptor(source_root, name) for name in sorted(names)]


def verify_sources(source_root, records):
    names = [row['path'] for row in records]
    if len(names) != len(set(names)):
        raise IntegrityError('Duplicate source binding')
    for row in records:
        if descriptor(source_root, row['path']) != row:
            raise IntegrityError('Bound source identity differs: ' + row['path'])
    return len(records)


def _time(value):
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        result = float(value)
    else:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            raise ValueError('Deadline requires an explicit time zone')
        result = moment.timestamp()
    if not math.isfinite(result):
        raise ValueError('Nonfinite clock')
    return result


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class Clock:
    def utc(self):
        return time.time()

    def monotonic(self):
        return time.monotonic()


class Processes:
    @staticmethod
    def boot_identity():
        if os.name == 'nt':
            # psutil.boot_time() is derived from wall clock and uptime on
            # Windows and can differ between processes. Read the kernel's
            # exact 100 ns BootTime instead; never guess with a tolerance.
            import ctypes
            from ctypes import wintypes
            query = ctypes.WinDLL('ntdll').NtQuerySystemInformation
            query.argtypes = (wintypes.ULONG, ctypes.c_void_p,
                              wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))
            query.restype = ctypes.c_long
            information = ctypes.create_string_buffer(48)
            returned = wintypes.ULONG()
            status = query(3, information, len(information), ctypes.byref(returned))
            if status != 0 or returned.value != len(information):
                raise RuntimeError('Cannot establish native Windows boot identity')
            boot = int.from_bytes(information.raw[:8], 'little', signed=True)
            if boot <= 0:
                raise RuntimeError('Invalid native Windows BootTime')
            return boot
        return psutil.boot_time()

    def identity(self):
        process = psutil.Process()
        return {'pid': process.pid, 'create_time': process.create_time(),
                'boot_time': self.boot_identity()}

    def is_alive(self, identity):
        # AccessDenied and all other uncertain errors propagate: never steal.
        if identity['boot_time'] != self.boot_identity():
            return False
        try:
            process = psutil.Process(identity['pid'])
            return process.create_time() == identity['create_time'] and process.is_running()
        except psutil.NoSuchProcess:
            return False


def _lock(stream):
    stream.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        raise WriterBusy('Another writer holds the OS lock') from error


def _unlock(stream):
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class CheckpointStore:
    def __init__(self, folder, binding, *, source_root=None, clock=None,
                 process_api=None, fault=None, external_source_verifier=None):
        self.folder = Path(folder).resolve()
        self.binding = json.loads(encoded(binding))
        self.source_root = None if source_root is None else Path(source_root).resolve()
        self.clock = clock or Clock()
        self.processes = process_api or Processes()
        self.fault = fault or (lambda event: None)
        self.external_source_verifier = external_source_verifier
        self._guard = self._pending = None
        self._pending_count = 0
        self._sources_checked = False
        self._reconstruction_checked = False
        self._summary = None
        self._token = self._identity = self._role = None
        self._budget_write_at = -math.inf

    @classmethod
    def create(cls, folder, binding, deadline_utc, budget_seconds, *,
               expected_queries=None, required_stages=('reconstruction', 'global', 'bootstrap'),
               max_chunk_rows=64, max_chunk_seconds=120, chunk_queries=None, chunk_seconds=None, **kwargs):
        store = cls(folder, binding, **kwargs)
        if chunk_queries is not None:
            max_chunk_rows = chunk_queries
        if chunk_seconds is not None:
            max_chunk_seconds = chunk_seconds
        now = store.clock.utc()
        deadline = _time(deadline_utc)
        if (deadline <= now or isinstance(budget_seconds, bool)
                or not math.isfinite(budget_seconds) or budget_seconds <= 0):
            raise ValueError('Invalid or expired run budget')
        if (type(max_chunk_rows) is not int or max_chunk_rows < 1
                or not math.isfinite(max_chunk_seconds) or max_chunk_seconds <= 0
                or expected_queries is not None and (type(expected_queries) is not int or expected_queries < 0)):
            raise ValueError('Invalid chunk or expected-query setting')
        if len(required_stages) != len(set(required_stages)):
            raise ValueError('Duplicate required stage')
        for name in required_stages:
            store._stage_name(name)
        store._check_sources()
        store.folder.mkdir(parents=True, exist_ok=False)
        for name in ('chunks', 'payloads', 'pending', 'stages', 'sessions', 'recovery'):
            (store.folder / name).mkdir()
        run = {'protocol': 'retailrocket_session_knn_checkpoint_v2', 'run_id': uuid.uuid4().hex,
               'binding': store.binding, 'created_utc': _iso(now), 'deadline_utc': _iso(deadline),
               'budget_seconds': budget_seconds, 'budget_kind': 'total_wall_time_including_downtime',
               'expected_queries': expected_queries, 'required_stages': list(required_stages),
               'max_chunk_rows': max_chunk_rows, 'max_chunk_seconds': max_chunk_seconds}
        store._atomic('run.json', run)
        run_identity = descriptor(store.folder, 'run.json')
        store._atomic('run_identity.json', run_identity)
        store.run, store.run_sha = run, run_identity['sha256']
        store._atomic('budget.json', {'run_sha256': store.run_sha, 'consumed_seconds': 0.0,
                                    'last_utc': _iso(now), 'last_utc_epoch': now})
        store._load()
        return store

    @classmethod
    def open(cls, folder, binding, **kwargs):
        store = cls(folder, binding, **kwargs)
        store._load()
        store._check_sources()
        return store

    def _load(self):
        identity = read(self.folder / 'run_identity.json')
        if identity != descriptor(self.folder, 'run.json'):
            raise IntegrityError('Run contract identity changed')
        self.run = read(self.folder / 'run.json')
        self.run_sha = identity['sha256']
        if self.run['binding'] != self.binding:
            raise IntegrityError('Expected source/configuration binding differs')
        if (self.folder / 'integrity_failed.json').exists():
            raise IntegrityError('This namespace has a recorded integrity failure')
        self._base_utc, self._base_mono = self.clock.utc(), self.clock.monotonic()

    def _check_sources(self, force=False):
        if self._sources_checked and not force:
            return
        records = self.binding.get('sources', [])
        if self.external_source_verifier is not None:
            self.external_source_verifier()
            self._sources_checked = True
            return
        if records and self.source_root is None:
            raise ValueError('source_root required for source descriptors')
        if records:
            verify_sources(self.source_root, records)
        self._sources_checked = True

    def _atomic(self, name, value, replace=False):
        target = _inside(self.folder, name)
        if target.exists() and not replace:
            raise FileExistsError(name)
        temporary = self.folder / 'pending' / (uuid.uuid4().hex + '.json.tmp')
        with temporary.open('xb') as stream:
            stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
        # Only the OS-lock owner mutates existing runs. New runs are exclusively
        # mkdir-claimed. Rename atomicity is not a claim of power-loss durability.
        os.replace(temporary, target)

    def _require_writer(self):
        if self._guard is None:
            raise WriterBusy('Operation requires the exclusive writer context')
        if (self.folder / 'acceptance.json').exists():
            raise IntegrityError('Completed acceptance is immutable')

    @contextmanager
    def writer(self, role='worker'):
        if self._guard is not None:
            raise WriterBusy('Writer context already active')
        guard = (self.folder / 'writer.guard').open('a+b')
        try:
            if guard.seek(0, 2) == 0:
                guard.write(b'0'); guard.flush(); os.fsync(guard.fileno())
            _lock(guard)
        except BaseException:
            guard.close()
            raise
        self._guard = guard
        error = None
        entered = False
        try:
            self._load()
            self._reconstruction_checked = False
            if (self.folder / 'acceptance.json').exists():
                raise IntegrityError('Completed acceptance is immutable')
            self._check_sources(force=True)
            owner_path = self.folder / 'writer_owner.json'
            owner = read(owner_path) if owner_path.exists() else None
            if owner and owner['state'] == 'active':
                if self.processes.is_alive(owner['identity']):
                    raise WriterBusy('Recorded writer identity is still alive')
                self._atomic('recovery/' + uuid.uuid4().hex + '.json', {
                    'previous_owner': owner, 'observed_utc': _iso(self.clock.utc()),
                    'historical_exit_code': None, 'historical_exit_cause': None,
                    'status': 'previous_identity_not_running_exit_unrecorded'})
            self._identity = self.processes.identity()
            self._token = uuid.uuid4().hex
            self._role = role
            self.check_budget(persist=True)
            self.recover()
            opened = {'token': self._token, 'identity': self._identity, 'role': role,
                      'state': 'active', 'opened_utc': _iso(self.clock.utc())}
            self._atomic('sessions/' + self._token + '.json', opened)
            self._atomic('writer_owner.json', opened, replace=owner_path.exists())
            entered = True
            yield self
        except BaseException as caught:
            error = type(caught).__name__
            if isinstance(caught, IntegrityError):
                self._fail(caught)
            raise
        finally:
            if self._pending is not None:
                self._pending.close()
                self._pending = None
            self._pending_count = 0
            try:
                if entered:
                    released = {'token': self._token, 'identity': self._identity, 'role': role,
                                'state': 'released', 'released_utc': _iso(self.clock.utc()),
                                'exception': error, 'note': 'Writer release, not a process-exit receipt.'}
                    self._atomic('sessions/' + self._token + '.released.json', released)
                    self._atomic('writer_owner.json', released, replace=True)
            finally:
                _unlock(guard); guard.close(); self._guard = None

    def check_budget(self, persist=False):
        budget = read(self.folder / 'budget.json')
        now, mono = self.clock.utc(), self.clock.monotonic()
        # ISO formatting rounds to microseconds. Compare the original epoch
        # float, whose JSON round-trip is exact, so equal clock reads stay equal.
        if budget['run_sha256'] != self.run_sha or now < _time(budget['last_utc_epoch']):
            raise BudgetExceeded('Budget identity changed or UTC moved backwards')
        elapsed = max(budget['consumed_seconds'], now - _time(self.run['created_utc']),
                      self._base_utc - _time(self.run['created_utc']) + mono - self._base_mono)
        expired = now >= _time(self.run['deadline_utc']) or elapsed >= self.run['budget_seconds']
        if self._guard is not None and (persist or expired or mono - self._budget_write_at >= 1.0):
            self._atomic('budget.json', {'run_sha256': self.run_sha, 'consumed_seconds': elapsed,
                                       'last_utc': _iso(now), 'last_utc_epoch': now}, replace=True)
            self._budget_write_at = mono
        if expired:
            if self._guard is not None and not (self.folder / 'stop_requested.json').exists():
                self._atomic('stop_requested.json', {'utc': _iso(now), 'reason': 'deadline_or_total_wall_budget',
                                                    'consumed_seconds': elapsed})
            raise BudgetExceeded('Absolute deadline or cumulative wall budget reached')
        return {'consumed_seconds': elapsed,
                'remaining_seconds': min(self.run['budget_seconds'] - elapsed, _time(self.run['deadline_utc']) - now)}

    @staticmethod
    def _key(key):
        if (type(key) is not list or len(key) != 3 or type(key[0]) is not str
                or not key[0].isdigit() or str(int(key[0])) != key[0]
                or any(type(value) is not int or value < 0 for value in key[1:])):
            raise IntegrityError('Invalid query key')
        return tuple(key)

    def _fail(self, error):
        if (self._guard is not None and not (self.folder / 'integrity_failed.json').exists()
                and not (self.folder / 'acceptance.json').exists()):
            self._atomic('integrity_failed.json', {'status': 'integrity_failed',
                        'utc': _iso(self.clock.utc()), 'error_type': type(error).__name__})

    def iter_records(self):
        """Validate and stream committed records; orphan payloads never count."""
        try:
            if (self.folder / 'integrity_failed.json').exists():
                raise IntegrityError('Recorded integrity failure')
            files = sorted((self.folder / 'chunks').iterdir())
            total, previous_key, previous_sha, payloads = 0, None, None, set()
            for number, path in enumerate(files):
                if path.name != f'{number:08d}.json' or not path.is_file():
                    raise IntegrityError('Committed chunk gap, duplicate or unexpected name')
                manifest = read(path)
                if (manifest['run_sha256'] != self.run_sha or manifest['chunk'] != number
                        or manifest['previous_sha256'] != previous_sha or manifest['first_ordinal'] != total):
                    raise IntegrityError('Committed manifest chain differs')
                payload = manifest['payload']
                if not re.fullmatch(r'payloads/[0-9a-f]{32}\.jsonl', payload['path']) or payload['path'] in payloads:
                    raise IntegrityError('Duplicate or invalid committed payload')
                payloads.add(payload['path'])
                if descriptor(self.folder, payload['path']) != payload:
                    raise IntegrityError('Committed payload SHA differs')
                local_count = 0
                with _inside(self.folder, payload['path']).open('rb') as stream:
                    for line in stream:
                        if not line.endswith(b'\n'):
                            raise IntegrityError('Committed payload lacks final newline')
                        record = json.loads(line, parse_constant=_invalid_constant)
                        if set(record) != {'ordinal', 'key', 'payload'} or type(record['ordinal']) is not int or record['ordinal'] != total:
                            raise IntegrityError('Ledger ordinal differs')
                        key = self._key(record['key'])
                        if previous_key is not None and key <= previous_key:
                            raise IntegrityError('Ledger key order/uniqueness differs')
                        if local_count == 0 and record['key'] != manifest['first_key']:
                            raise IntegrityError('First chunk key differs')
                        previous_key = key; total += 1; local_count += 1
                        yield record
                if (local_count < 1 or local_count != manifest['count'] or total - 1 != manifest['last_ordinal']
                        or list(previous_key) != manifest['last_key']):
                    raise IntegrityError('Chunk count or final boundary differs')
                previous_sha = descriptor(self.folder, 'chunks/' + path.name)['sha256']
            latest = self.folder / 'latest.json'
            if latest.exists():
                hint = read(latest)
                if hint['run_sha256'] != self.run_sha or type(hint['chunks']) is not int or hint['chunks'] > len(files):
                    raise IntegrityError('Latest hint reports missing committed chunks')
                if hint['chunks'] == len(files) and (hint['records'] != total or hint['last_manifest_sha256'] != previous_sha):
                    raise IntegrityError('Latest hint contradicts committed chain')
            self._summary = {'records': total, 'chunks': len(files),
                             'last_key': None if previous_key is None else list(previous_key),
                             'last_manifest_sha256': previous_sha}
        except (ValueError, KeyError, TypeError, OSError) as error:
            self._fail(error)
            if isinstance(error, IntegrityError):
                raise
            raise IntegrityError('Unreadable or invalid committed checkpoint') from error

    def recover(self):
        for _ in self.iter_records():
            pass
        # Recovery validates sealed prerequisites as well as the query chain.
        # This is phase-level work, never repeated for every appended query.
        for name in self.run['required_stages']:
            if self.get_stage(name) is not None and name in ('global', 'bootstrap'):
                value = read(self.folder / 'stages' / (name + '.json'))
                if value['ledger'] != self._summary:
                    raise IntegrityError('Recovered stage has a different query chain')
        return dict(self._summary)

    def append_verified(self, ordinal, key, payload):
        self._require_writer(); self.check_budget()
        if 'reconstruction' in self.run['required_stages'] and not self._reconstruction_checked:
            if self.get_stage('reconstruction') is None:
                raise IntegrityError('Independent reconstruction must be sealed before queries')
            self._reconstruction_checked = True
        if (self.folder / 'candidate.json').exists() or (self.folder / 'stages/global.json').exists():
            raise IntegrityError('Query stage already sealed')
        expected = self._summary['records'] + self._pending_count
        normalized = self._key(key)
        prior = self._last_pending_key if self._pending_count else self._summary['last_key']
        if type(ordinal) is not int or ordinal != expected or prior is not None and normalized <= tuple(prior):
            raise IntegrityError('Noncontiguous ordinal or unordered query')
        data = encoded({'ordinal': ordinal, 'key': key, 'payload': payload})
        if self._pending is None:
            self._pending_name = 'payloads/' + uuid.uuid4().hex + '.jsonl'
            self._pending = _inside(self.folder, self._pending_name).open('xb', buffering=0)
            self._pending_first = list(key)
            self._chunk_started = self.clock.monotonic()
        split = len(data) // 2
        self._pending.write(data[:split]); self.fault('payload_half_written')
        self._pending.write(data[split:])
        self._pending_count += 1; self._last_pending_key = list(key)
        if (self._pending_count >= self.run['max_chunk_rows']
                or self.clock.monotonic() - self._chunk_started >= self.run['max_chunk_seconds']):
            self.flush_chunk()

    def flush_chunk(self):
        self._require_writer(); self.check_budget(persist=True)
        if not self._pending_count:
            return None
        self._pending.flush(); os.fsync(self._pending.fileno())
        self.fault('after_payload_fsync')
        self._pending.close(); self._pending = None
        number = self._summary['chunks']
        manifest = {'run_sha256': self.run_sha, 'chunk': number,
                    'previous_sha256': self._summary['last_manifest_sha256'],
                    'first_ordinal': self._summary['records'],
                    'last_ordinal': self._summary['records'] + self._pending_count - 1,
                    'count': self._pending_count, 'first_key': self._pending_first,
                    'last_key': self._last_pending_key,
                    'payload': descriptor(self.folder, self._pending_name)}
        self.fault('before_manifest_commit')
        name = f'chunks/{number:08d}.json'
        self.check_budget(persist=True)
        self._atomic(name, manifest)
        self._summary = {'records': manifest['last_ordinal'] + 1, 'chunks': number + 1,
                         'last_key': manifest['last_key'],
                         'last_manifest_sha256': descriptor(self.folder, name)['sha256']}
        self._pending_count = 0
        self.fault('after_manifest_commit')
        self._atomic('latest.json', dict(self._summary, run_sha256=self.run_sha), replace=True)
        return manifest

    @staticmethod
    def _stage_name(name):
        if not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9_]*', name):
            raise ValueError('Invalid stage name')

    def seal_stage(self, name, receipt, artifacts=()):
        self._require_writer(); self.check_budget(persist=True); self._stage_name(name)
        if self._pending_count:
            raise IntegrityError('Cannot seal a stage with an uncommitted tail')
        if (self.folder / 'candidate.json').exists():
            raise IntegrityError('Completion candidate already written')
        summary = self.recover()
        if name in ('global', 'bootstrap') and summary['records'] != self.run['expected_queries']:
            raise IntegrityError('Global stage requires the complete query roster')
        if name == 'bootstrap' and self.get_stage('global') is None:
            raise IntegrityError('Bootstrap requires the global seal')
        names = list(artifacts)
        if len(names) != len(set(names)):
            raise IntegrityError('Duplicate stage artifact')
        value = {'run_sha256': self.run_sha, 'ledger': summary, 'receipt': receipt,
                 'artifacts': [descriptor(self.folder, item) for item in names]}
        self.check_budget(persist=True)
        self._atomic('stages/' + name + '.json', value)
        return value

    def get_stage(self, name):
        self._stage_name(name)
        path = self.folder / 'stages' / (name + '.json')
        if not path.exists():
            return None
        value = read(path)
        if value['run_sha256'] != self.run_sha:
            raise IntegrityError('Stage belongs to another run')
        verify_sources(self.folder, value['artifacts'])
        return value['receipt']

    def _complete_checks(self):
        summary = self.recover()
        if self._pending_count or self.run['expected_queries'] is None or summary['records'] != self.run['expected_queries']:
            raise IntegrityError('Complete expected query count required')
        stages = []
        for name in self.run['required_stages']:
            if self.get_stage(name) is None:
                raise IntegrityError('Required stage not sealed: ' + name)
            stage = read(self.folder / 'stages' / (name + '.json'))
            if name in ('global', 'bootstrap') and stage['ledger'] != summary:
                raise IntegrityError('Global/bootstrap seal has a different query chain')
            stages.append(descriptor(self.folder, 'stages/' + name + '.json'))
        self._check_sources(force=True)
        return summary, stages

    def write_candidate(self, receipt):
        self._require_writer(); self.check_budget(persist=True)
        if self._role != 'worker':
            raise IntegrityError('Only the worker can write its completion candidate')
        self.flush_chunk()
        summary, stages = self._complete_checks()
        self.check_budget(persist=True)
        self.fault('before_candidate_commit')
        self._atomic('candidate.json', {'run_sha256': self.run_sha, 'worker_identity': self._identity,
                     'worker_session': self._token, 'ledger': summary, 'stages': stages,
                     'receipt': receipt, 'created_utc': _iso(self.clock.utc()),
                     'status': 'worker_candidate_not_final_acceptance'})
        self.fault('after_candidate_commit')
        return descriptor(self.folder, 'candidate.json')['sha256']

    def supersede_candidate(self):
        """Preserve an orphan candidate before a new worker repeats completion.

        This does not certify the previous process's exit, nor authorize skipping
        any replay. A recorded normal exit must instead re-enter finalization.
        """
        self._require_writer(); self.check_budget(persist=True)
        if self._role != 'worker':
            raise IntegrityError('Only a new worker can supersede an orphan candidate')
        path = self.folder / 'candidate.json'
        if not path.exists():
            return None
        if (self.folder / 'normal_worker_exit.json').exists():
            raise WriterBusy('Recorded normal exit requires supervisor finalization')
        candidate_record = descriptor(self.folder, 'candidate.json')
        candidate = read(path)
        if self.processes.is_alive(candidate['worker_identity']):
            raise WriterBusy('Candidate worker is still alive')
        summary, stages = self._complete_checks()
        if (candidate['run_sha256'] != self.run_sha or candidate['ledger'] != summary
                or candidate['stages'] != stages):
            raise IntegrityError('Orphan candidate does not bind the verified run')
        name = 'recovery/' + uuid.uuid4().hex + '.candidate.json'
        receipt = {'status': 'candidate_superseded_for_complete_replay',
                   'previous_candidate': dict(candidate_record, path=name),
                   'previous_worker_identity': candidate['worker_identity'],
                   'historical_exit_code': None, 'historical_exit_cause': None,
                   'new_worker_identity': self._identity, 'observed_utc': _iso(self.clock.utc())}
        # The rename preserves the exact candidate bytes. A crash after rename
        # still leaves the old evidence and allows complete replay on re-entry.
        self.check_budget(persist=True)
        os.replace(path, self.folder / name)
        self._atomic(name + '.superseded.json', receipt)
        return receipt

    def finalize(self, candidate_sha, worker_identity, exit_code):
        """Supervisor calls only after observing this worker's normal exit."""
        with self.writer(role='supervisor'):
            self.check_budget(persist=True)
            if type(exit_code) is not int or exit_code != 0:
                raise IntegrityError('A documented normal worker exit is required')
            if self.processes.is_alive(worker_identity):
                raise WriterBusy('Worker still alive; supervisor cannot finalize')
            candidate_record = descriptor(self.folder, 'candidate.json')
            if candidate_record['sha256'] != candidate_sha:
                raise IntegrityError('Candidate identity differs')
            candidate = read(self.folder / 'candidate.json')
            summary, stages = self._complete_checks()
            if (candidate['run_sha256'] != self.run_sha or candidate['worker_identity'] != worker_identity
                    or candidate['ledger'] != summary or candidate['stages'] != stages):
                raise IntegrityError('Candidate does not bind the complete verified run')
            exit_path = self.folder / 'normal_worker_exit.json'
            if exit_path.exists():
                previous_exit = read(exit_path)
                if previous_exit['worker_identity'] != worker_identity or previous_exit['exit_code'] != 0:
                    raise IntegrityError('Existing normal-exit evidence differs')
            else:
                if self._identity == worker_identity or self._identity['boot_time'] != worker_identity['boot_time']:
                    raise IntegrityError('No same-boot independent supervisor exit observation')
                exit_receipt = {'worker_identity': worker_identity, 'exit_code': exit_code,
                                'supervisor_identity': self._identity, 'observed_utc': _iso(self.clock.utc())}
                self._atomic('normal_worker_exit.json', exit_receipt)
            self.check_budget(persist=True); self.fault('before_acceptance_commit')
            result = {'status': 'separate_v2_readback_complete', 'run_sha256': self.run_sha,
                      'candidate': candidate_record, 'ledger': summary, 'stages': stages,
                      'normal_worker_exit': descriptor(self.folder, 'normal_worker_exit.json'),
                      'reserved_test': 'locked', 'primary_recomputed': False}
            self._atomic('acceptance.json', result)
            return result
