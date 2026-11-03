"""Source-backed, scientifically UNACCEPTED ledger-layout engineering costs.

Stored four-arm recommendations are inputs, never independently ranked here.
Metric arithmetic is source self-consistency only.  Record encoding mirrors
the verified-ledger layout, but storage/protocol names deliberately differ.
This module never uses CheckpointStore, append_verified, scientific stage seals,
candidate/final acceptance, a production model, or original bootstrap files.

For a later diagnostic window, the caller must bind the preceding normal-exit
receipt and the expected engineering seal SHA.  Every phase has a new output
directory and an explicit current window; the old ledger remains immutable.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
from time import perf_counter, monotonic
import uuid

from scripts.retailrocket_session_knn_checkpoint_v2 import atomic_json, encoded
from scripts.retailrocket_session_knn_checks_v4 import terms
from scripts.retailrocket_session_knn_readback import FourFold, GROUPS, METRICS, scalar_count
from scripts.retailrocket_session_knn_oracle import exact
from scripts.retailrocket_popularity_oracle import read_rows, num, close
from scripts.retailrocket_directed_oracle import check_bootstrap
from scripts import retailrocket_session_knn_sources_v4 as source_frames


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = (ROOT / 'shop-mysql-runtime').resolve()
PROTOCOL = 'engineering_unaccepted_saved_outputs_ledger_cost_v5'
ARMS = ('P0', 'C1', 'D1', 'K1')
CONTRASTS = ('K1_minus_C1', 'K1_minus_P0', 'K1_minus_D1')
DIAGNOSTICS = ('history_size', 'unknown_seeds', 'eligible_neighbors', 'current_session_excluded',
               'selected_neighbor_count', 'boundary_ties_excluded', 'positive_candidates',
               'zero_fill_slots', 'fallback_reason')
EXPECTED_FIELDS = {'key', 'history', 'history_sha256', 'targets', 'candidate_count',
                   'reachable_targets', 'slices', 'predictions', 'terms', 'delta'}


class EngineeringIntegrityError(ValueError):
    pass


class _Budget:
    def __init__(self, deadline_utc, budget_seconds, watch):
        deadline = datetime.fromisoformat(deadline_utc.replace('Z', '+00:00'))
        if (deadline.tzinfo is None or isinstance(budget_seconds, bool)
                or not isinstance(budget_seconds, (float, int))
                or not math.isfinite(budget_seconds) or not 0 < budget_seconds <= 1800):
            raise ValueError('Explicit engineering window of at most 1800 seconds required')
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise TimeoutError('Engineering window already expired')
        self.stop = monotonic() + min(remaining, budget_seconds)
        self.watch = watch
        self.deadline_utc = deadline.isoformat()
        self.budget_seconds = budget_seconds

    def __call__(self):
        self.watch()
        if monotonic() >= self.stop:
            raise TimeoutError('Engineering ledger cost window expired')


def _read(path):
    def invalid(_):
        raise EngineeringIntegrityError('Nonfinite JSON constant')
    return json.loads(Path(path).read_bytes(), parse_constant=invalid)


def _private(path):
    path = Path(path).resolve()
    if not path.is_relative_to(PRIVATE) or path == PRIVATE:
        raise ValueError('Engineering artifacts must use a new Git-ignored project namespace')
    return path


def _inside(root, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise EngineeringIntegrityError('Unsafe engineering artifact path')
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise EngineeringIntegrityError('Engineering artifact escapes its root')
    return path


def _describe(root, path, watch):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Descriptor leaves root')
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            watch(); h.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise EngineeringIntegrityError('Input changed during byte hashing')
    return {'path': path.relative_to(root).as_posix(), 'bytes': after.st_size, 'sha256': h.hexdigest()}


def _identity(path, watch):
    return _describe(Path(path).resolve().parent, path, watch)


def _matches(actual, expected):
    if any(actual[key] != expected[key] for key in ('bytes', 'sha256')):
        raise EngineeringIntegrityError('Bound byte identity changed')


def _check(root, record, watch):
    path = _inside(root, record['path'])
    if _describe(root, path, watch) != record:
        raise EngineeringIntegrityError('Engineering artifact SHA differs')
    return path


def _copy(source, destination, watch):
    before = Path(source).stat()
    h = hashlib.sha256()
    with Path(source).open('rb') as incoming, Path(destination).open('xb') as outgoing:
        while block := incoming.read(1024 * 1024):
            watch(); outgoing.write(block); h.update(block)
        outgoing.flush(); os.fsync(outgoing.fileno())
    after = Path(source).stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise EngineeringIntegrityError('Input changed during engineering copy')
    return {'bytes': after.st_size, 'sha256': h.hexdigest()}


@contextmanager
def _phase(folder, name):
    folder = _private(folder)
    folder.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    status = {'kind': PROTOCOL, 'phase': name, 'scientific_acceptance': False}
    try:
        yield status
        status['completed'] = True
    except BaseException as error:
        status.update(completed=False, error_type=type(error).__name__)
        raise
    finally:
        status['seconds'] = perf_counter() - started
        atomic_json(folder / 'engineering_phase_receipt.json', status)


def _key(value):
    if (type(value) is not list or len(value) != 3 or type(value[0]) is not str
            or any(type(item) is not int or item < 0 for item in value[1:])):
        raise EngineeringIntegrityError('Invalid saved-output query key')
    num(value[0])
    return tuple(value)


def _shape_equal(actual, expected):
    try:
        exact(actual, expected)
    except ValueError as error:
        raise EngineeringIntegrityError('Source-derived workload shape differs from fixed configuration') from error


def _fixed_shapes(fixed, count, visitors, targets, reachable, complete, slices):
    observed = {'queries': count, 'visitors': visitors, 'target_occurrences': targets,
                'reachable_target_occurrences': reachable, 'all_targets_reachable_queries': complete,
                'new_visitor_queries': slices['visitor_history'].get('new', 0),
                'multi_item_current_queries': slices['current_basket'].get('multiple', 0),
                'multi_item_target_queries': slices['target_basket'].get('multiple', 0),
                'target_model_query_counts': {group: slices['target_model'].get(group, 0)
                                              for group in GROUPS['target_model']}}
    for name, value in observed.items():
        if name in fixed:
            _shape_equal(value, fixed[name])


def _payload(row):
    """Build the CP byte schema from unaccepted stored values; no K1 ranking."""
    if type(row) is not dict or set(row) != EXPECTED_FIELDS:
        raise EngineeringIntegrityError('Saved four-arm output schema differs')
    _key(row['key'])
    if (type(row['candidate_count']) is not int or row['candidate_count'] < 0
            or type(row['reachable_targets']) is not int
            or type(row['history']) is not list or type(row['targets']) is not list
            or not 0 <= row['reachable_targets'] <= len(row['targets'])):
        raise EngineeringIntegrityError('Invalid stored target/catalog/history shape')
    for item in [*row['history'], *row['targets']]:
        num(item)
    if (set(row['predictions']) != set(ARMS) or set(row['terms']) != set(ARMS)
            or set(row['delta']) != set(CONTRASTS) or set(row['slices']) != set(GROUPS)):
        raise EngineeringIntegrityError('Saved four-arm/slice schema differs')
    for family, group in row['slices'].items():
        if group not in GROUPS[family]:
            raise EngineeringIntegrityError('Unknown saved slice label')
    precise = {}
    for arm in ARMS:
        prediction = row['predictions'][arm]
        if type(prediction) is not dict or type(prediction.get('ids')) is not list:
            raise EngineeringIntegrityError('Invalid stored recommendation shape')
        for item in prediction['ids']:
            num(item)
        if (type(prediction.get('candidate_count')) is not int
                or prediction['candidate_count'] != row['candidate_count']):
            raise EngineeringIntegrityError('Stored candidate metadata is not self-consistent')
        # Frozen terms validates duplicates/empty targets/max10 first.  This
        # checks arithmetic of GIVEN ids, not the independent K1 rank formula.
        binary, accurate = terms(prediction['ids'], row['targets'])
        if any(type(row['terms'][arm][name]) is not float
               or not math.isfinite(row['terms'][arm][name])
               for name in ('dcg', 'idcg', *METRICS)):
            raise EngineeringIntegrityError('Stored metric fields must be finite binary64')
        close(row['terms'][arm], binary)
        precise[arm] = {name: str(value) for name, value in accurate.items()}
    calculated = {'K1_minus_' + arm: {
        name: row['terms']['K1'][name] - row['terms'][arm][name] for name in METRICS}
        for arm in ('C1', 'P0', 'D1')}
    exact(row['delta'], calculated)
    return {'expected': row, 'precise': precise,
            'delta_hex': {arm: {name: value.hex() for name, value in metrics.items()}
                          for arm, metrics in row['delta'].items()}}


class _EngineeringWriter:
    """A distinct source-only commit chain; never a verified CheckpointStore."""
    def __init__(self, root, contract_sha, watch, fault, chunk_queries, chunk_seconds):
        self.root, self.contract_sha = root, contract_sha
        self.watch, self.fault = watch, fault
        self.max_rows, self.max_seconds = chunk_queries, chunk_seconds
        self.stream = None; self.pending = 0; self.total = 0; self.chunks = []
        self.previous = None; self.lengths = []; self.previous_key = None

    def append_source_record(self, ordinal, key, payload):
        self.watch()
        normalized = _key(key)
        if ordinal != self.total + self.pending or self.previous_key is not None and normalized <= self.previous_key:
            raise EngineeringIntegrityError('Source-only ordinal/key order differs')
        data = encoded({'ordinal': ordinal, 'key': key, 'payload': payload})
        if self.stream is None:
            self.payload_name = 'engineering_payloads/' + uuid.uuid4().hex + '.jsonl'
            self.stream = _inside(self.root, self.payload_name).open('xb', buffering=0)
            self.first_key = list(key); self.started = monotonic()
        split = len(data) // 2
        self.stream.write(data[:split]); self.fault('payload_half_written')
        self.stream.write(data[split:])
        self.pending += 1; self.last_key = list(key); self.previous_key = normalized
        self.lengths.append(len(data))
        if self.pending >= self.max_rows or monotonic() - self.started >= self.max_seconds:
            self.flush()

    def flush(self):
        self.watch()
        if not self.pending:
            return
        self.stream.flush(); os.fsync(self.stream.fileno()); self.fault('after_payload_fsync')
        self.stream.close(); self.stream = None
        payload = _describe(self.root, _inside(self.root, self.payload_name), self.watch)
        number = len(self.chunks)
        manifest = {'protocol': PROTOCOL, 'scientific_acceptance': False,
                    'contract_sha256': self.contract_sha, 'chunk': number,
                    'previous_sha256': self.previous, 'first_ordinal': self.total,
                    'last_ordinal': self.total + self.pending - 1, 'count': self.pending,
                    'first_key': self.first_key, 'last_key': self.last_key, 'payload': payload}
        self.fault('before_manifest_commit'); self.watch()
        path = self.root / 'engineering_chunks' / f'{number:08d}.json'
        atomic_json(path, manifest)
        record = _describe(self.root, path, self.watch)
        self.chunks.append(record); self.previous = record['sha256']
        self.total += self.pending; self.pending = 0
        self.fault('after_manifest_commit')

    def close(self):
        if self.stream is not None:
            self.stream.close(); self.stream = None


def _pin_source_index(folder, expected_sha, primary, primary_identity, expected_queries, watch):
    if folder is None:
        return None
    if not expected_sha:
        raise ValueError('A frozen source-index seal identity is required')
    folder = Path(folder).resolve()
    seal = _read(folder / 'seal.json')['manifest']
    if seal['sha256'] != expected_sha or seal['path'] != 'manifest.json':
        raise EngineeringIntegrityError('Unexpected source-index seal')
    manifest = _read(_check(folder, seal, watch))
    if (manifest['kind'] != 'validation_source_position_index_only'
            or manifest['validation_queries'] != expected_queries):
        raise EngineeringIntegrityError('Wrong source-only key roster')
    record = manifest['sources']['k1']
    indexed = _inside(Path(manifest['source_root']).resolve(), record['path'])
    if indexed != Path(primary).resolve():
        raise EngineeringIntegrityError('Source index binds another primary file')
    _matches(primary_identity, record)
    _check(folder, manifest['index'], watch)
    return {'manifest_sha256': expected_sha, 'roster_sha256': manifest['roster_sha256'],
            'scope': 'source_bytes_and_key_roster_only', 'scientific_acceptance': False}


def _sample_references(records, watch):
    wanted = {}
    bindings = []
    for descriptor in records:
        path = Path(descriptor['path'])
        if not path.is_absolute():
            path = ROOT / path
        identity = _identity(path, watch); _matches(identity, descriptor)
        bindings.append({'bytes': identity['bytes'], 'sha256': identity['sha256']})
        consumed = hashlib.sha256(); consumed_bytes = 0
        with path.open('rb') as stream:
            for raw in stream:
                watch(); consumed.update(raw); consumed_bytes += len(raw)
                record = json.loads(raw)
                key = _key(record['key'])
                if key in wanted:
                    exact(wanted[key], record['payload'])
                else:
                    wanted[key] = record['payload']
        _matches({'bytes': consumed_bytes, 'sha256': consumed.hexdigest()}, identity)
    return wanted, bindings


def build_source_ledger(folder, primary, paths, config, watch=lambda: None, *,
                        deadline_utc, budget_seconds=1800, expected_primary=None,
                        source_index_folder=None, expected_manifest_sha256=None,
                        verified_sample_payloads=(), chunk_queries=64, chunk_seconds=120,
                        fault=lambda point: None):
    """Build a real-schema engineering proxy from unaccepted saved outputs.

    Parsing, given-recommendation metric self-consistency and byte/hash work are
    timed.  No history/model/support is loaded; K1 predictions are never made.
    Optional already-verified samples certify adapter fidelity at those keys
    only.  All other rows retain their scientifically unaccepted input status.
    """
    guard = _Budget(deadline_utc, budget_seconds, watch)
    if (type(chunk_queries) is not int or not 1 <= chunk_queries <= 64
            or isinstance(chunk_seconds, bool) or not 0 < chunk_seconds <= 120):
        raise ValueError('Invalid engineering chunk cadence')
    primary = Path(primary)
    source = primary / 'queries.jsonl' if primary.is_dir() else primary
    expected_queries = config['fixed_validation']['queries']
    if type(expected_queries) is not int or expected_queries < 1:
        raise ValueError('Positive fixed source roster required')
    with _phase(folder, 'build_source_backed_engineering_ledger') as status:
        root = _private(folder)
        for name in ('engineering_payloads', 'engineering_chunks', 'inputs'):
            (root / name).mkdir()
        original = _identity(source, guard)
        if expected_primary is not None:
            _matches(original, expected_primary)
        index = _pin_source_index(source_index_folder, expected_manifest_sha256,
                                  source, original, expected_queries, guard)
        catalog_source = Path(paths['dataset']) / 'catalog.csv'
        copied = _copy(catalog_source, root / 'inputs/catalog.csv', guard)
        atomic_json(root / 'inputs/configuration.json', config)
        sample_map, sample_bindings = _sample_references(verified_sample_payloads, guard)
        contract = {'protocol': PROTOCOL, 'kind': 'unaccepted_saved_outputs',
                    'scientific_acceptance': False, 'independent_K1_rank_checks': 0,
                    'source_path': str(source.resolve()), 'source_identity': original,
                    'source_index': index, 'expected_queries': expected_queries,
                    'deadline_utc_at_build': guard.deadline_utc,
                    'budget_seconds_at_build': budget_seconds,
                    'chunk_queries': chunk_queries, 'chunk_seconds': chunk_seconds,
                    'record_encoding': 'CP encoded ordinal/key/payload byte schema; engineering-only provenance',
                    'catalog': _describe(root, root / 'inputs/catalog.csv', guard),
                    'configuration': _describe(root, root / 'inputs/configuration.json', guard),
                    'known_verified_sample_bindings': sample_bindings}
        _matches(contract['catalog'], copied)
        atomic_json(root / 'engineering_contract.json', contract)
        contract_record = _describe(root, root / 'engineering_contract.json', guard)
        writer = _EngineeringWriter(root, contract_record['sha256'], guard, fault,
                                    chunk_queries, chunk_seconds)
        source_hash = hashlib.sha256(); roster = hashlib.sha256(); visitors = Counter()
        slices = {family: Counter() for family in GROUPS}; targets = reachable = complete = 0
        count = raw_bytes = reference_rows = 0; latest = None
        before = source.stat()
        try:
            with source.open('rb') as stream:
                for raw in source_frames._physical(stream, guard):
                    guard(); source_hash.update(raw); raw_bytes += len(raw)
                    row = json.loads(raw)
                    payload = _payload(row)
                    key = _key(row['key'])
                    if count >= expected_queries:
                        raise EngineeringIntegrityError('Extra saved source row')
                    if key in sample_map:
                        exact(payload, sample_map.pop(key)); reference_rows += 1
                    writer.append_source_record(count, list(key), payload)
                    roster.update(encoded(list(key))); visitors[key[0]] += 1
                    for family, group in row['slices'].items():
                        slices[family][group] += 1
                    targets += len(row['targets']); reachable += row['reachable_targets']
                    complete += row['reachable_targets'] == len(row['targets'])
                    latest = key[2] if latest is None else max(latest, key[2])
                    count += 1
            writer.flush()
        finally:
            writer.close()
        after = source.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise EngineeringIntegrityError('Primary source changed during transformation')
        _matches({'bytes': raw_bytes, 'sha256': source_hash.hexdigest()}, original)
        if count != expected_queries or sample_map:
            raise EngineeringIntegrityError('Incomplete source roster or missing verified-sample reference')
        if index is not None and roster.hexdigest() != index['roster_sha256']:
            raise EngineeringIntegrityError('Saved source keys differ from sealed source-only index')
        _fixed_shapes(config['fixed_validation'], count, len(visitors), targets, reachable, complete, slices)
        lengths = sorted(writer.lengths)
        summary = {'kind': PROTOCOL, 'input_status': 'unaccepted_saved_outputs',
                   'records': count, 'visitors': len(visitors), 'raw_primary_bytes': raw_bytes,
                   'engineering_record_bytes': sum(lengths), 'chunks': len(writer.chunks),
                   'record_min_bytes': lengths[0], 'record_max_bytes': lengths[-1],
                   'record_p50_bytes': lengths[(len(lengths) + 1) // 2 - 1],
                   'record_p99_bytes': lengths[(99 * len(lengths) + 99) // 100 - 1],
                   'visitor_query_count_histogram': dict(Counter(visitors.values())),
                   'slice_counts': {family: dict(values) for family, values in slices.items()},
                   'target_occurrences': targets, 'reachable_target_occurrences': reachable,
                   'all_targets_reachable_queries': complete, 'latest_query_time': latest,
                   'roster_sha256': roster.hexdigest(), 'metric_self_consistency_rows': count,
                   'known_verified_sample_payloads_matched': reference_rows,
                   'new_K1_predictions': 0, 'independent_K1_rank_checks': 0,
                   'full_scientific_acceptance': False, 'T_plan': None, 'reserved_test': 'locked'}
        atomic_json(root / 'engineering_summary.json', summary)
        guard(); fault('before_engineering_seal')
        seal = {'protocol': PROTOCOL, 'scientific_acceptance': False,
                'contract': contract_record,
                'summary': _describe(root, root / 'engineering_summary.json', guard),
                'chunks': writer.chunks,
                'note': 'Structural engineering seal; the external supervisor must separately attest normal exit.'}
        atomic_json(root / 'engineering_seal.json', seal)
        seal_record = _describe(root, root / 'engineering_seal.json', guard)
        guard()
        status['result'] = {'records': count, 'engineering_record_bytes': sum(lengths),
                            'chunks': len(writer.chunks), 'scientific_acceptance': False}
    return dict(summary, engineering_ledger_folder=str(root), engineering_seal_sha256=seal_record['sha256'],
                seconds=status['seconds'])


def _open_engineering(root, expected_seal_sha256, guard, rehash_source):
    root = _private(root)
    if not expected_seal_sha256:
        raise ValueError('A previously bound engineering seal SHA is required')
    seal_identity = _describe(root, root / 'engineering_seal.json', guard)
    if seal_identity['sha256'] != expected_seal_sha256:
        raise EngineeringIntegrityError('Engineering seal identity differs')
    seal = _read(root / 'engineering_seal.json')
    if seal['protocol'] != PROTOCOL or seal['scientific_acceptance'] is not False:
        raise EngineeringIntegrityError('Not a scientifically unaccepted engineering ledger')
    contract = _read(_check(root, seal['contract'], guard))
    summary = _read(_check(root, seal['summary'], guard))
    if contract['protocol'] != PROTOCOL or contract['scientific_acceptance'] is not False:
        raise EngineeringIntegrityError('Engineering contract kind differs')
    for name in ('catalog', 'configuration'):
        _check(root, contract[name], guard)
    if rehash_source:
        _matches(_identity(contract['source_path'], guard), contract['source_identity'])
    return root, seal, contract, summary


def _records(root, seal, contract, guard, state):
    manifests = sorted((root / 'engineering_chunks').iterdir())
    if len(manifests) != len(seal['chunks']):
        raise EngineeringIntegrityError('Engineering chunk inventory differs')
    ordinal = 0; previous = None; last_key = None; payload_paths = set(); roster = hashlib.sha256()
    bytes_checked = 0
    for number, (path, descriptor) in enumerate(zip(manifests, seal['chunks'])):
        guard()
        if path.name != f'{number:08d}.json' or path != _check(root, descriptor, guard):
            raise EngineeringIntegrityError('Engineering chunk order or identity differs')
        manifest = _read(path)
        if (manifest['protocol'] != PROTOCOL or manifest['scientific_acceptance'] is not False
                or manifest['contract_sha256'] != seal['contract']['sha256']
                or manifest['chunk'] != number or manifest['previous_sha256'] != previous
                or manifest['first_ordinal'] != ordinal):
            raise EngineeringIntegrityError('Engineering manifest chain differs')
        payload = manifest['payload']
        if payload['path'] in payload_paths:
            raise EngineeringIntegrityError('Repeated engineering payload')
        payload_paths.add(payload['path'])
        payload_path = _check(root, payload, guard); local_count = 0
        bytes_checked += payload['bytes']
        with payload_path.open('rb') as stream:
            for raw in stream:
                guard()
                if not raw.endswith(b'\n'):
                    raise EngineeringIntegrityError('Engineering record lacks final newline')
                record = json.loads(raw)
                key = _key(record['key'])
                if (set(record) != {'ordinal', 'key', 'payload'} or type(record['ordinal']) is not int
                        or record['ordinal'] != ordinal or last_key is not None and key <= last_key):
                    raise EngineeringIntegrityError('Engineering record boundary differs')
                if local_count == 0 and record['key'] != manifest['first_key']:
                    raise EngineeringIntegrityError('Engineering first key differs')
                exact(record['payload']['expected']['key'], record['key'])
                roster.update(encoded(record['key'])); last_key = key
                ordinal += 1; local_count += 1
                yield record
        if (not local_count or local_count != manifest['count']
                or ordinal - 1 != manifest['last_ordinal'] or list(last_key) != manifest['last_key']):
            raise EngineeringIntegrityError('Engineering final chunk boundary differs')
        previous = descriptor['sha256']
    if ordinal != contract['expected_queries']:
        raise EngineeringIntegrityError('Incomplete engineering source roster')
    state.update(records=ordinal, chunks=len(manifests), payload_bytes_hashed=bytes_checked,
                 roster_sha256=roster.hexdigest(), scientific_acceptance=False)


def recover_engineering_ledger(ledger_folder, out_folder, watch=lambda: None, *,
                               deadline_utc, budget_seconds=1800, expected_seal_sha256,
                               rehash_source=True):
    """Read-only byte/ordinal/key-chain recovery; no scientific row acceptance."""
    if _private(out_folder).is_relative_to(_private(ledger_folder)):
        raise ValueError('A read-only engineering ledger cannot contain new phase outputs')
    guard = _Budget(deadline_utc, budget_seconds, watch)
    with _phase(out_folder, 'recover_engineering_chain_only') as status:
        root, seal, contract, summary = _open_engineering(ledger_folder, expected_seal_sha256, guard, rehash_source)
        result = {}
        for _ in _records(root, seal, contract, guard, result):
            pass
        if result['roster_sha256'] != summary['roster_sha256']:
            raise EngineeringIntegrityError('Recovered engineering roster differs')
        result.update(kind=PROTOCOL, source_hash_included=bool(rehash_source),
                      source_hash_scope='original_queries_jsonl_if_enabled_plus_engineering_catalog_configuration_and_chain',
                      full_verified_real_ledger_recovered=False, reserved_test='locked', T_plan=None)
        guard()
        status['result'] = result
    return dict(result, seconds=status['seconds'])


def _catalog(root, contract, guard):
    config = _read(_inside(root, contract['configuration']['path']))
    catalog = {}
    for row in read_rows(_inside(root, contract['catalog']['path']), config['schemas']['catalog.csv']):
        guard(); item = row['itemid']; num(item); first = num(row['first_view_ms'])
        if item in catalog:
            raise EngineeringIntegrityError('Repeated engineering catalog item')
        catalog[item] = first
    return catalog


def global_engineering_replay(ledger_folder, out_folder, watch=lambda: None, *,
                              deadline_utc, budget_seconds=1800, expected_seal_sha256,
                              rehash_source=True):
    """Exercise full Fold/slice/diagnostic work; discard all effectiveness values."""
    if _private(out_folder).is_relative_to(_private(ledger_folder)):
        raise ValueError('A read-only engineering ledger cannot contain new phase outputs')
    guard = _Budget(deadline_utc, budget_seconds, watch)
    with _phase(out_folder, 'source_derived_global_cost_only') as status:
        root, seal, contract, summary = _open_engineering(ledger_folder, expected_seal_sha256, guard, rehash_source)
        catalog = _catalog(root, contract, guard)
        main = FourFold(catalog); conditional = FourFold(catalog)
        groups = {family: {group: FourFold(catalog) for group in names} for family, names in GROUPS.items()}
        diagnostics = {name: Counter() for name in DIAGNOSTICS}; cross = Counter()
        state = {}; checked = scalars = candidates = 0
        for record in _records(root, seal, contract, guard, state):
            expected = record['payload']['expected']; prediction = expected['predictions']; names = expected['slices']
            precise = {arm: {name: Decimal(value) for name, value in values.items()}
                       for arm, values in record['payload']['precise'].items()}
            delta = {arm: {name: float.fromhex(value) for name, value in values.items()}
                     for arm, values in record['payload']['delta_hex'].items()}
            exact(delta, expected['delta'])
            visitor, _, at = record['key']; targets = expected['targets']; reachable = expected['reachable_targets']
            query = {'v': visitor, 't': at, 'targets': targets}
            main.add(query, prediction, precise, delta, reachable)
            if reachable == len(targets):
                conditional.add(query, prediction, precise, delta, reachable)
            for family, group in names.items():
                groups[family][group].add(query, prediction, precise, delta, reachable)
            for name in diagnostics:
                value = prediction['K1'][name]
                diagnostics[name][(value or 'positive_evidence') if name == 'fallback_reason' else str(value)] += 1
            cross[encoded([prediction['K1']['fallback_reason'] is not None,
                           prediction['C1']['positive_candidates'] == 0,
                           prediction['D1']['positive_candidates'] == 0, names['target_model']])] += 1
            checked += 1; scalars += scalar_count(expected); candidates += expected['candidate_count']
        # Materialize all original-order Fold results, but expose only shapes.
        main_values = main.result(); conditional_values = conditional.result()
        slice_counts = {}
        for family, buckets in groups.items():
            slice_counts[family] = {}
            for group, fold in buckets.items():
                guard(); materialized = fold.result()
                slice_counts[family][group] = materialized['queries']
        observed = main_values['arms']['K1']
        if (observed['queries'] != summary['records'] or observed['visitors'] != summary['visitors']
                or state['roster_sha256'] != summary['roster_sha256']):
            raise EngineeringIntegrityError('Engineering global shape differs from its source ledger')
        config = _read(_inside(root, contract['configuration']['path']))
        _fixed_shapes(config['fixed_validation'], observed['queries'], observed['visitors'],
                      observed['target_occurrences'], observed['reachable_target_occurrences'],
                      observed['all_targets_reachable_queries'], slice_counts)
        for name in ('target_occurrences', 'reachable_target_occurrences', 'all_targets_reachable_queries'):
            _shape_equal(observed[name], summary[name])
        _shape_equal(slice_counts, {family: {group: values.get(group, 0) for group in GROUPS[family]}
                                   for family, values in summary['slice_counts'].items()})
        _shape_equal(conditional_values['queries'], summary['all_targets_reachable_queries'])
        if 'candidate_union_items' in config['fixed_validation']:
            _shape_equal(observed['candidate_union_items'], config['fixed_validation']['candidate_union_items'])
        result = {'kind': PROTOCOL, 'records': checked, 'visitors': observed['visitors'],
                  'catalog_union': observed['candidate_union_items'],
                  'conditional_queries': conditional_values['queries'], 'slice_counts': slice_counts,
                  'nested_scalars_processed': scalars, 'candidate_count_sum': candidates,
                  'diagnostic_families_processed': len(diagnostics), 'cross_tab_cells_processed': len(cross),
                  'all_four_arm_Fold_results_materialized_for_cost': True,
                  'effectiveness_values_returned_or_retained': False,
                  'input_status': 'unaccepted_saved_outputs', 'independent_K1_rank_checks': 0,
                  'full_scientific_acceptance': False, 'original_bootstrap_files_opened': False,
                  'source_hash_included': bool(rehash_source), 'T_plan': None, 'reserved_test': 'locked'}
        result['source_hash_scope'] = 'original_queries_jsonl_if_enabled_plus_engineering_catalog_configuration_and_chain'
        guard()
        status['result'] = result
    return dict(result, seconds=status['seconds'])


def engineering_draw_cost(ledger_folder, out_folder, watch=lambda: None, *,
                           deadline_utc, budget_seconds=1800, expected_seal_sha256,
                           rehash_source=True):
    """Generate/replay NEW 2000 engineering self-reference draws only."""
    if _private(out_folder).is_relative_to(_private(ledger_folder)):
        raise ValueError('A read-only engineering ledger cannot contain new phase outputs')
    import numpy as np
    guard = _Budget(deadline_utc, budget_seconds, watch)
    with _phase(out_folder, 'new_engineering_draw_self_reference_only') as status:
        root, seal, contract, _ = _open_engineering(ledger_folder, expected_seal_sha256, guard, rehash_source)
        state = {}; deltas = []
        for record in _records(root, seal, contract, guard, state):
            value = float.fromhex(record['payload']['delta_hex']['K1_minus_C1']['ndcg'])
            deltas.append((record['key'][0], value))
        grouped = defaultdict(list)
        for visitor, value in deltas:
            guard(); grouped[visitor].append(value)
        visitors = sorted(grouped, key=int)
        sizes = np.array([len(grouped[visitor]) for visitor in visitors], dtype=np.int64)
        sums = [math.fsum(grouped[visitor]) for visitor in visitors]
        random = np.random.Generator(np.random.PCG64(42))
        output = _private(out_folder)
        setup_started = perf_counter()
        with (output / 'new_engineering_reference.jsonl').open('x', encoding='utf-8') as reference, \
                (output / 'new_engineering_output.jsonl').open('x', encoding='utf-8') as values:
            for replicate in range(2000):
                guard(); before = random.bit_generator.state
                draw = random.integers(0, len(visitors), size=len(visitors), dtype=np.int64)
                weight = np.bincount(draw, minlength=len(visitors))
                denominator = int(np.dot(weight, sizes))
                delta = math.fsum(int(w) * total for w, total in zip(weight, sums)) / denominator
                identity = {'replicate': replicate, 'rng_before': before, 'rng_after': random.bit_generator.state,
                            'draw_sha256': hashlib.sha256(draw.astype('<i8', copy=False).tobytes()).hexdigest(),
                            'query_denominator': denominator}
                reference.write(json.dumps(identity, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
                values.write(json.dumps(dict(identity, delta=delta), ensure_ascii=False,
                                        separators=(',', ':'), allow_nan=False) + '\n')
        setup_seconds = perf_counter() - setup_started
        replay_started = perf_counter()
        replay = check_bootstrap(output / 'new_engineering_output.jsonl',
                                 output / 'new_engineering_reference.jsonl', deltas, guard)
        result = {'kind': PROTOCOL, 'engineering_self_reference_draws': replay['replicates'],
                  'visitors_per_draw': replay['visitors'], 'records': len(deltas),
                  'new_fixture_generation_seconds': setup_seconds,
                  'new_fixture_replay_seconds': perf_counter() - replay_started,
                  'input_status': 'unaccepted_saved_output_deltas',
                  'source_hash_included': bool(rehash_source),
                  'source_hash_scope': 'original_queries_jsonl_if_enabled_plus_engineering_catalog_configuration_and_chain',
                  'original_bootstrap_files_opened': False, 'original_draws_accepted': False,
                  'new_primary_bootstrap_generations': 0, 'effectiveness_values_published': False,
                  'new_engineering_draw_values_retained_private': True,
                  'full_scientific_acceptance': False, 'reserved_test': 'locked', 'T_plan': None}
        guard()
        status['result'] = result
    return dict(result, seconds=status['seconds'])


def run_ledger_cost(folder, primary, paths, config, watch=lambda: None, *, deadline_utc,
                    budget_seconds=1800, engineering_draws=2000, **build_options):
    """One caller-supervised window; phase APIs also support separately bound windows."""
    if engineering_draws not in (0, 2000) or type(engineering_draws) is not int:
        raise ValueError('Engineering draws must be explicitly 0 or 2000')
    guard = _Budget(deadline_utc, budget_seconds, watch); guard()
    folder = _private(folder); folder.mkdir(parents=True, exist_ok=False)
    common = {'deadline_utc': deadline_utc, 'budget_seconds': budget_seconds}
    built = build_source_ledger(folder / 'engineering_ledger', primary, paths, config, guard,
                                **common, **build_options)
    sealed = {'expected_seal_sha256': built['engineering_seal_sha256']}
    global_cost = global_engineering_replay(folder / 'engineering_ledger', folder / 'global_cost', guard,
                                            **common, **sealed)
    recovery = recover_engineering_ledger(folder / 'engineering_ledger', folder / 'recovery_cost', guard,
                                          **common, **sealed)
    draws = (engineering_draw_cost(folder / 'engineering_ledger', folder / 'draw_cost', guard,
                                    **common, **sealed) if engineering_draws else None)
    result = {'kind': PROTOCOL, 'build': built, 'global_cost': global_cost, 'recovery_cost': recovery,
              'engineering_draw_cost': draws, 'scientific_acceptance': False,
              'full_verified_real_ledger': False, 'new_K1_predictions': 0, 'new_primary_fits': 0,
              'original_bootstrap_files_opened': False, 'reserved_test': 'locked', 'T_plan': None,
              'remaining': ['independent_full_K1_rank_and_query_acceptance',
                            'true_full_verified_ledger_recovery', 'joint_independent_SQL_work_tail']}
    guard(); atomic_json(folder / 'engineering_cost_summary.json', result)
    return result
