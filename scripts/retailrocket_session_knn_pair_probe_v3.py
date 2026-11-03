"""Private frozen-roster paired-row engineering measurements, never acceptance.

Extraction charges complete EOF scans of the original validation streams.
Only the already frozen subset is independently ranked and checked.  The V2
four-arm checks below are retained; no global/bootstrap or candidate is run.
"""
from bisect import bisect_left
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import sqlite3
from time import perf_counter

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback_v2 as core
from scripts import retailrocket_session_knn_sql_v2 as sql
from scripts.retailrocket_session_knn_readback import (
    rows, ids, read_rows, num, terms, close, GROUPS, METRICS, FIELDS, exact, dump)


def _read(path):
    return cp.read(Path(path))


def _write(path, value):
    cp.atomic_json(Path(path), value)


def _key_csv(row):
    visitor = row['visitorid']
    num(visitor)
    return visitor, num(row['session_start_ms']), num(row['query_ms'])


def _key_json(row):
    key = row.get('key')
    if (type(key) is not list or len(key) != 3 or type(key[0]) is not str
            or any(type(value) is not int or value < 0 for value in key[1:])):
        raise ValueError('Invalid paired JSON query key')
    num(key[0])
    return tuple(key)


def _describe(root, path, watch):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Sample input leaves its bound root')
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            watch()
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Input changed during sample identity check')
    return {'path': path.relative_to(root).as_posix(), 'bytes': after.st_size,
            'sha256': digest.hexdigest()}


def _copy(source, target, watch):
    source, target = Path(source), Path(target)
    before = source.stat()
    digest = hashlib.sha256()
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        while block := incoming.read(1024 * 1024):
            watch()
            outgoing.write(block)
            digest.update(block)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Source changed during sample copy')
    if target.stat().st_size != before.st_size:
        raise ValueError('Incomplete sample copy')
    return {'bytes': before.st_size, 'sha256': digest.hexdigest()}


def extract_samples(folder, primary, paths, config, probes, watch=lambda: None):
    """Extract frozen selected ordinals after full EOF/key/count checks.

    ``folder/frozen_probes.json`` must already contain the exact probes supplied
    by the target-blind selector.  All products, including keys and selected
    scores, stay under the private ``folder/paired_samples`` directory.
    """
    started = perf_counter()
    folder, primary = Path(folder).resolve(), Path(primary)
    paths = {key: Path(value) for key, value in paths.items()}
    frozen_path = folder / 'frozen_probes.json'
    if not frozen_path.is_file():
        raise ValueError('Frozen probe roster is required before paired extraction')
    frozen_identity = _describe(folder, frozen_path, watch)
    frozen = _read(frozen_path)
    exact(frozen['probes'], probes)
    if not 0 < len(probes) <= 64:
        raise ValueError('Paired probe requires 1..64 frozen keys')
    requested = [_key_json(row) for row in probes]
    if len(requested) != len(set(requested)):
        raise ValueError('Duplicate frozen paired probe key')
    requested = set(requested)
    expected = config['fixed_validation']['queries']
    if type(expected) is not int or expected < len(requested):
        raise ValueError('Invalid original validation population')
    root = folder / 'paired_samples'
    root.mkdir(exist_ok=False)
    target_paths = {key: root / key for key in ('dataset', 'P0', 'C1', 'D1')}
    target_primary = root / 'primary'
    for path in [*target_paths.values(), target_primary]:
        path.mkdir()
    scans = {}
    selected = {}
    headers = config['schemas']['queries.csv']
    count = 0
    previous = None
    with (target_paths['dataset'] / 'queries.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        for row in read_rows(paths['dataset'] / 'queries.csv', headers):
            watch()
            # A non-validation target string is never JSON-decoded.
            if row['role'] != 'validation':
                continue
            key = _key_csv(row)
            if previous is not None and key <= previous:
                raise ValueError('Original validation query order/uniqueness differs')
            previous = key
            if key in requested:
                selected[count] = key
                writer.writerow(row)
            count += 1
    if count != expected or set(selected.values()) != requested:
        raise ValueError('Missing frozen key or incomplete original validation query EOF')
    scans['dataset/queries.csv'] = count

    for name in ('ranked_queries.csv', 'query_metrics.csv', 'query_slices.csv'):
        count = 0
        previous = None
        with (target_paths['P0'] / name).open('x', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS[name])
            writer.writeheader()
            for row in read_rows(paths['P0'] / name, FIELDS[name]):
                watch()
                key = _key_csv(row)
                if row['role'] != 'validation' or previous is not None and key <= previous:
                    raise ValueError('P0 original paired role/order differs')
                previous = key
                if count in selected:
                    exact(list(key), list(selected[count]))
                    writer.writerow(row)
                count += 1
        if count != expected:
            raise ValueError('P0 original paired stream EOF count differs: ' + name)
        scans['P0/' + name] = count

    for arm, incoming, outgoing in (
            ('C1', paths['C1'] / 'queries.jsonl', target_paths['C1'] / 'queries.jsonl'),
            ('D1', paths['D1'] / 'queries.jsonl', target_paths['D1'] / 'queries.jsonl'),
            ('K1', primary / 'queries.jsonl', target_primary / 'queries.jsonl')):
        count = 0
        previous = None
        with outgoing.open('x', encoding='utf-8', newline='\n') as stream:
            for row in rows(incoming, watch):
                key = _key_json(row)
                if previous is not None and key <= previous:
                    raise ValueError('Original paired JSON order/uniqueness differs: ' + arm)
                previous = key
                if count in selected:
                    exact(list(key), list(selected[count]))
                    stream.write(dump(row) + '\n')
                count += 1
        if count != expected:
            raise ValueError('Original paired JSON EOF count differs: ' + arm)
        scans[arm + '/queries.jsonl'] = count

    _copy(paths['P0'] / 'item_counts.csv', target_paths['P0'] / 'item_counts.csv', watch)
    _copy(paths['dataset'] / 'catalog.csv', target_paths['dataset'] / 'catalog.csv', watch)
    copied_roster = _copy(frozen_path, root / 'frozen_probes.json', watch)
    exact(copied_roster, {key: frozen_identity[key] for key in ('bytes', 'sha256')})
    exact(_read(root / 'frozen_probes.json'), frozen)
    subset_config = json.loads(dump(config))
    subset_config['fixed_validation']['queries'] = len(selected)
    subset_config['engineering_subset'] = {
        'original_validation_queries': expected,
        'original_ordinals': list(selected), 'formal_acceptance': False}
    _write(root / 'configuration.json', subset_config)
    ordinals = [{'subset_ordinal': ordinal, 'original_ordinal': source_ordinal,
                 'key': list(key)}
                for ordinal, (source_ordinal, key) in enumerate(selected.items())]
    _write(root / 'ordinals.json', ordinals)
    sources = [_describe(root, path, watch) for path in sorted(root.rglob('*')) if path.is_file()]
    manifest = {'kind': 'frozen_subset_extraction_only', 'formal_acceptance': False,
                'original_validation_queries': expected, 'selected_queries': len(selected),
                'scan_counts': scans, 'ordinals': ordinals, 'sources': sources,
                'selection_changed': False}
    _write(root / 'extraction_manifest.json', manifest)
    watch()
    return {'sample_root': str(root), 'sample_primary': str(target_primary),
            'paths': {key: str(value) for key, value in target_paths.items()},
            'config': subset_config, 'ordinals': ordinals, 'scan_counts': scans,
            'source_paths': [row['path'] for row in sources] + ['extraction_manifest.json'],
            'selected_queries': len(selected), 'original_validation_queries': expected,
            'elapsed_seconds': perf_counter() - started, 'formal_acceptance': False}


def _verify_selected(primary, paths, config, store, model, database, ordinals, watch):
    """The V2 four-arm per-query checks, timed separately from setup/tail."""
    setup_started = perf_counter()
    source, p0, c1, d1 = (paths[key] for key in ('dataset', 'P0', 'C1', 'D1'))
    audit, support = model['fit_audit'], model['support']
    counts, catalog = core.load_context(paths, config, support, watch)
    prepared = sql.prepare_catalog(catalog, counts, watch)
    first_times = sorted(catalog.values())
    if any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Copied model has an unexpected SQLite journal')
    db = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA temp_store=MEMORY')
    db.set_progress_handler(lambda: (watch() or 0), 10000)
    observations = []
    try:
        controls = [iter(read_rows(p0 / name, FIELDS[name]))
                    for name in ('ranked_queries.csv', 'query_metrics.csv', 'query_slices.csv')]
        controls += [iter(rows(c1 / 'queries.jsonl', watch)), iter(rows(d1 / 'queries.jsonl', watch))]
        outputs = iter(rows(primary / 'queries.jsonl', watch))
        previous = None
        if store.recover()['records']:
            raise ValueError('Engineering paired measurements require a fresh ledger')
        ordinal = -1
        lo, hi = config['validation_window_ms']
        setup_seconds = perf_counter() - setup_started
        for raw in read_rows(source / 'queries.csv', config['schemas']['queries.csv']):
            query_started = perf_counter()
            watch()
            if raw['role'] != 'validation':
                raise ValueError('Subset contains a forbidden query role')
            ordinal += 1
            v = raw['visitorid']; num(v)
            s, t, nt, index = (num(raw[field]) for field in
                               ('session_start_ms', 'query_ms', 'next_view_ms', 'basket_index'))
            key = (v, s, t)
            if ordinal >= len(ordinals):
                raise ValueError('Extra subset query outside frozen ordinals')
            exact(ordinals[ordinal]['key'], list(key))
            if previous is not None and key <= previous:
                raise ValueError('Oracle duplicate/unordered query')
            previous = key
            if not lo <= t < nt < hi or s > t or nt - t > 1800000 or t + 1800000 > hi:
                raise ValueError('Oracle validation clock/horizon')
            for field, value in [('status', 'labelled'), ('next_role', 'validation'),
                                 ('next_in_session', '1'), ('mature', '1'), ('cross_role', '0')]:
                if raw[field] != value:
                    raise ValueError('Oracle query label state')
            current = db.execute('SELECT k,n FROM h WHERE v=? AND s=? AND t=?', key).fetchone()
            if current is None or current[0] != index:
                raise ValueError('Oracle missing current basket')
            history = set()
            for (text,) in db.execute('SELECT items FROM h WHERE v=? AND s=? AND t<=? ORDER BY t', key):
                watch(); history.update(json.loads(text))
            history = sorted(history, key=int); targets = ids(raw['target_items'])
            successor = db.execute(
                'SELECT t,k,role,items FROM h WHERE v=? AND s=? AND t>? ORDER BY t LIMIT 1', key).fetchone()
            if successor is None or successor[:3] != (nt, index + 1, 'validation'):
                raise ValueError('Oracle next-basket identity')
            exact(sorted(targets, key=int), sorted(json.loads(successor[3]), key=int))
            reachable = sum(item in catalog and catalog[item] < t for item in targets)
            candidate = bisect_left(first_times, t)
            if (len(targets) != num(raw['target_count']) or reachable != num(raw['reachable_target_count'])
                    or candidate != num(raw['candidate_count'])
                    or raw['all_targets_reachable'] != str(int(reachable == len(targets)))):
                raise ValueError('Oracle full query denominators')
            values = [next(stream, None) for stream in controls]; actual = next(outputs, None)
            if any(value is None for value in values) or actual is None:
                raise ValueError('Oracle missing paired row')
            rank, metric, slices, one, three = values
            for row in (rank, metric, slices):
                if _key_csv(row) != key or row['role'] != 'validation':
                    raise ValueError('Oracle original P0 key/role')
            if rank['fit_id'] != config['control_fit_ids']['P0']:
                raise ValueError('Oracle P0 fit')
            p0ids = json.loads(rank['top10_items'])
            exact(json.loads(rank['top10_scores']), [counts.get(item, 0) for item in p0ids])
            p0pred = {'ids': p0ids, 'candidate_count': num(rank['candidate_count'])}
            p0terms = {metric_name: float(metric[metric_name]) for metric_name in ('dcg', 'idcg', *METRICS)}
            p0terms.update(target_count=num(metric['target_count']), hits=num(metric['hits']),
                           first_hit_rank=num(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
            if num(metric['reachable_target_count']) != reachable or metric['all_targets_reachable'] != raw['all_targets_reachable']:
                raise ValueError('Oracle P0 target denominator')
            train = num(raw['train_view_events']); known = sum(item in support for item in targets)
            activity = '0' if not train else '1' if train == 1 else '2-5' if train <= 5 else '6+'
            if raw['visitor_seen_before_fit'] not in ('0', '1') or raw['train_activity_slice'] != activity:
                raise ValueError('Oracle visitor/activity state')
            names = {'visitor_history': 'seen' if raw['visitor_seen_before_fit'] == '1' else 'new',
                     'current_basket': 'multiple' if current[1] > 1 else 'single',
                     'target_basket': 'multiple' if len(targets) > 1 else 'single',
                     'train_activity': activity,
                     'target_model': 'all_positive' if known == len(targets) else 'all_zero' if not known else 'mixed'}
            identity = {'key': list(key), 'history': history,
                        'history_sha256': hashlib.sha256(dump(history).encode()).hexdigest(),
                        'targets': targets, 'candidate_count': candidate,
                        'reachable_targets': reachable, 'slices': names}
            for reference in (one, three):
                for field, value in identity.items():
                    exact(reference[field], value)
                exact(reference['predictions']['P0'], p0pred); exact(reference['terms']['P0'], p0terms)
            exact({field: slices[field] for field in GROUPS}, names)
            exact(one['predictions']['C1'], three['predictions']['C1'])
            exact(one['terms']['C1'], three['terms']['C1'])
            for arm in ('C1', 'D1'):
                if three['predictions'][arm]['fit_id'] != config['control_fit_ids'][arm]:
                    raise ValueError('Oracle control fit')
            workload = {}
            predictions = dict(three['predictions'], K1=sql.predict(
                db, support, audit['fit_id'], prepared.counts, prepared, t, history, (v, s),
                watch, workload=workload))
            binary = {}; precise = {}
            for arm in ('P0', 'C1', 'D1', 'K1'):
                prediction = predictions[arm]
                if (prediction['candidate_count'] != candidate or len(prediction['ids']) != min(10, candidate)
                        or any(item not in catalog or catalog[item] >= t for item in prediction['ids'])):
                    raise ValueError('Oracle complete causal control/K1 list')
                independently, precise[arm] = terms(prediction['ids'], targets)
                if any(type(actual['terms'][arm][metric_name]) is not float
                       or not math.isfinite(actual['terms'][arm][metric_name])
                       for metric_name in ('dcg', 'idcg', *METRICS)):
                    raise ValueError('Oracle expected finite binary64 metric fields')
                close(actual['terms'][arm], independently)
                binary[arm] = actual['terms'][arm] if arm == 'K1' else three['terms'][arm]
                if arm != 'K1':
                    exact(actual['terms'][arm], binary[arm])
            delta = {'K1_minus_' + arm: {name: binary['K1'][name] - binary[arm][name] for name in METRICS}
                     for arm in ('C1', 'P0', 'D1')}
            expected = dict(identity, predictions=predictions, terms=binary, delta=delta)
            exact(actual, expected)
            if predictions['K1']['fallback_reason'] is not None:
                exact(predictions['K1']['ids'], predictions['P0']['ids'])
            payload = {'expected': expected,
                       'precise': {arm: {name: str(value) for name, value in metrics.items()}
                                   for arm, metrics in precise.items()},
                       'delta_hex': {arm: {name: value.hex() for name, value in metrics.items()}
                                     for arm, metrics in delta.items()}}
            verified_seconds = perf_counter() - query_started
            append_started = perf_counter()
            store.append_verified(ordinal, list(key), payload)
            append_seconds = perf_counter() - append_started
            observations.append({'subset_ordinal': ordinal,
                'original_ordinal': ordinals[ordinal]['original_ordinal'],
                'key_sha256': hashlib.sha256(dump(list(key)).encode()).hexdigest(),
                'verification_seconds': verified_seconds, 'checkpoint_append_seconds': append_seconds,
                'seconds': perf_counter() - query_started, 'sql_workload': workload})
        tail_started = perf_counter()
        if any(next(stream, None) is not None for stream in [*controls, outputs]):
            raise ValueError('Oracle extra paired row')
        if ordinal + 1 != config['fixed_validation']['queries'] or ordinal + 1 != len(ordinals):
            raise ValueError('Incomplete frozen subset query coverage')
        store.flush_chunk()
        store.seal_stage('queries', {'engineering_subset_only': True, 'queries': ordinal + 1,
                                    'paired_streams_eof_checked': True})
        return {'setup_seconds': setup_seconds, 'queries': observations,
                'tail_flush_and_eof_seal_seconds': perf_counter() - tail_started,
                'verified_subset_queries': ordinal + 1}
    finally:
        for stream in [*locals().get('controls', []), locals().get('outputs')]:
            if stream is not None and hasattr(stream, 'close'):
                stream.close()
        db.close()


def measure_paired(folder, extracted, model_database, model, deadline_utc,
                   budget_seconds, watch=lambda: None):
    """Time complete selected pairing and real private checkpoint I/O only."""
    started = perf_counter()
    folder, root = Path(folder).resolve(), Path(extracted['sample_root']).resolve()
    if not root.is_relative_to(folder):
        raise ValueError('Sample root leaves the diagnostic namespace')
    deadline = datetime.fromisoformat(deadline_utc.replace('Z', '+00:00'))
    if deadline.tzinfo is None:
        raise ValueError('Explicit paired measurement deadline timezone required')
    def checked_watch():
        watch()
        if datetime.now(timezone.utc) >= deadline:
            raise TimeoutError('Paired measurement deadline reached')
    checked_watch()
    config = _read(root / 'configuration.json')
    exact(config, extracted['config'])
    ordinals = _read(root / 'ordinals.json')
    exact(ordinals, extracted['ordinals'])
    manifest = _read(root / 'extraction_manifest.json')
    exact(manifest['sources'], [_describe(root, root / row['path'], checked_watch)
                               for row in manifest['sources']])
    exact(_read(folder / 'frozen_probes.json'), _read(root / 'frozen_probes.json'))
    exact(str(Path(extracted['sample_primary']).resolve()), str(root / 'primary'))
    exact({key: str(Path(value).resolve()) for key, value in extracted['paths'].items()},
          {key: str(root / key) for key in ('dataset', 'P0', 'C1', 'D1')})
    source_input_names = [row['path'] for row in manifest['sources']] + ['extraction_manifest.json']
    exact(extracted['source_paths'], source_input_names)
    exact(ordinals, manifest['ordinals'])
    measurement = root / 'measurement'
    measurement.mkdir(exist_ok=False)
    database = measurement / 'model.sqlite'
    original = Path(model_database)
    if any(Path(str(original) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Unsealed source database journal exists')
    copy_started = perf_counter()
    copied = _copy(original, database, checked_watch)
    original_identity = _describe(original.parent, original, checked_watch)
    exact(copied, {key: original_identity[key] for key in ('bytes', 'sha256')})
    if any(Path(str(original) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Source database journal appeared during copy')
    copy_seconds = perf_counter() - copy_started
    _write(measurement / 'model_receipt.json', {'model': model,
        'sealed_source_database': dict(original_identity, source_directory=str(original.parent.resolve()))})
    source_names = source_input_names + ['measurement/model.sqlite', 'measurement/model_receipt.json']
    binding_started = perf_counter()
    records = [_describe(root, root / name, checked_watch) for name in sorted(source_names)]
    exact(next(row for row in records if row['path'] == 'measurement/model.sqlite'),
          dict(copied, path='measurement/model.sqlite'))
    binding_seconds = perf_counter() - binding_started
    binding = {'sources': records, 'configuration': config,
               'scope': 'frozen_subset_paired_engineering_only', 'environment': {'python': platform.python_version()}}
    store_started = perf_counter()
    store = cp.CheckpointStore.create(measurement / 'checkpoint', binding, deadline_utc,
        budget_seconds, source_root=root, expected_queries=len(ordinals),
        required_stages=('reconstruction', 'queries'))
    store_creation_seconds = perf_counter() - store_started
    primary = Path(extracted['sample_primary'])
    paths = {key: Path(value) for key, value in extracted['paths'].items()}
    with store.writer():
        checked_watch()
        store.seal_stage('reconstruction', {'kind': 'sealed_model_diagnostic_reuse',
            'fit_audit': model['fit_audit'], 'bound_database': 'measurement/model.sqlite',
            'new_model_reconstruction': False})
        measured = _verify_selected(primary, paths, config, store, model, database, ordinals, checked_watch)
        final_hash_started = perf_counter()
        exact(records, [_describe(root, root / row['path'], checked_watch) for row in records])
        final_hash_seconds = perf_counter() - final_hash_started
        summary = store.recover()
    if any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Copied model SQLite journal appeared during measurement')
    checked_watch()
    if (store.folder / 'candidate.json').exists() or (store.folder / 'acceptance.json').exists():
        raise ValueError('Engineering paired measurement cannot publish research acceptance')
    result = {'kind': 'frozen_subset_paired_engineering_cost_only', 'formal_acceptance': False,
              'full_validation_accepted': False, 'global_or_bootstrap_executed': False,
              'reserved_test': 'locked', 'new_primary_fits': 0, 'new_primary_bootstrap_generations': 0,
              'selected_queries': len(ordinals), 'original_validation_queries': extracted['original_validation_queries'],
              'database_copy_seconds': copy_seconds, 'database_copy_bytes': copied['bytes'],
              'binding_hash_seconds': binding_seconds, 'checkpoint_create_seconds': store_creation_seconds,
              'final_subset_and_database_hash_seconds': final_hash_seconds,
              'whole_phase_seconds': perf_counter() - started, **measured,
              'whole_phase_timer_note': 'Includes copy/source identity, setup, pairing, checkpoint and final input hashes; extraction and final receipt publication are separate.',
              'checkpoint_records': summary['records'], 'checkpoint_chunks': summary['chunks'],
              'checkpoint_folder': str(store.folder), 'source_files_bound': len(records),
              'temp_store': 'MEMORY', 'main_database_open_mode': 'ro',
              'candidate_written': False, 'acceptance_written': False}
    _write(measurement / 'paired_measurement.json', result)
    return result
