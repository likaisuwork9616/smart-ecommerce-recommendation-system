"""Rebuild K1 train membership with frozen SQL and rerank prespecified August rows."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from scripts import retailrocket_session_knn_sql_v2 as sql
from scripts.retailrocket_session_knn_readback import exact, reconstruct
from scripts.retailrocket_session_knn_readback_v2 import load_context
from scripts.verify_k1_aggregate_v1 import ROOT, STAGE12, write_result


def ordinals(count):
    if type(count) is not int or count < 1:
        raise ValueError('Expected a nonempty fixed validation roster')
    return sorted({i * (count - 1) // 32 for i in range(33)})


def sha(path, watch):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            watch()
            digest.update(block)
    return digest.hexdigest()


def check_predictions(db, primary, config, model, catalog, query_digest, watch):
    count = config['fixed_validation']['queries']
    selected = set(ordinals(count))
    query_hash = hashlib.sha256()
    evidence = hashlib.sha256()
    scanned = checked = 0
    lo, hi = config['validation_window_ms']
    with (primary / 'queries.jsonl').open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            query_hash.update(line)
            scanned += 1
            if ordinal not in selected:
                continue
            row = json.loads(line)
            visitor, start, now = row['key']
            if not start <= now or not lo <= now < hi:
                raise ValueError('Selected query outside development window')
            current = db.execute('SELECT role FROM h WHERE v=? AND s=? AND t=?', (visitor, start, now)).fetchone()
            if current != ('validation',):
                raise ValueError('Selected current basket missing from SQL reconstruction')
            history = set()
            for items, in db.execute('SELECT items FROM h WHERE v=? AND s=? AND t<=? ORDER BY t',
                                     (visitor, start, now)):
                history.update(json.loads(items))
            history = sorted(history, key=int)
            exact(history, row['history'])
            prediction = sql.predict(db, model['support'], model['fit_audit']['fit_id'], catalog.counts,
                                     catalog, now, history, (visitor, start), watch)
            exact(row['predictions']['K1'], prediction)
            # A commitment to the ordered selected keys and full verified predictions.
            payload = json.dumps([ordinal, row['key'], prediction], sort_keys=True, separators=(',', ':'), allow_nan=False)
            evidence.update((payload + '\n').encode('utf-8'))
            checked += 1
    exact(scanned, count)
    exact(checked, len(selected))
    exact(query_hash.hexdigest(), query_digest)
    return {'queries_scanned': scanned, 'queries_sha256': query_hash.hexdigest(),
            'queries_sql_checked': checked, 'ordinals_zero_based': sorted(selected),
            'verified_predictions_sha256': evidence.hexdigest()}


def verify(primary, paths, config, scratch, expected_query_digest, watch=lambda: None):
    # A fresh workspace makes the former partial oracle and any interrupted
    # local reconstruction ineligible as inputs to this witness.
    scratch.mkdir(exist_ok=False)
    database = scratch / 'independent.sqlite'
    with database.open('xb'):
        pass
    started = time.monotonic()
    with closing(sqlite3.connect(database)) as db:
        db.execute('PRAGMA temp_store = MEMORY')
        db.execute('PRAGMA synchronous = FULL')
        db.set_progress_handler(lambda: watch() or 0, 10000)
        sessions, support, audit = reconstruct(db, primary, paths['dataset'], paths['C1'], config, watch)
        del sessions
        index = sql.build_index(db, watch)
        exact(index, {'train_sessions': audit['train_sessions'],
                      'session_item_memberships': audit['distinct_session_item_memberships']})
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Independent SQLite database integrity check failed')
    built = time.monotonic()
    counts, raw_catalog = load_context(paths, config, support, watch)
    catalog = sql.prepare_catalog(raw_catalog, counts, watch)
    del raw_catalog, counts
    model = {'support': support, 'fit_audit': audit}
    uri = database.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute('PRAGMA temp_store = MEMORY')
        db.set_progress_handler(lambda: watch() or 0, 10000)
        result = check_predictions(db, primary, config, model, catalog, expected_query_digest, watch)
    if set(scratch.iterdir()) != {database}:
        raise ValueError('Unexpected SQLite sidecar or scratch artifact')
    result.update(status='passed', stage='independent_sql_training_and_fixed_query_witness',
                  sqlite_version=sqlite3.sqlite_version, fit_audit=audit, index_counts=index,
                  database_bytes=database.stat().st_size, database_sha256=sha(database, watch),
                  rebuild_seconds=round(built - started, 3), elapsed_seconds=round(time.monotonic() - started, 3),
                  test_ranked_queries=0)
    watch()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='Run directory containing the source-before receipt')
    parser.add_argument('--deadline-utc', required=True, type=datetime.fromisoformat)
    args = parser.parse_args()
    if args.deadline_utc.tzinfo is None:
        parser.error('deadline-utc requires an explicit UTC offset')
    stop = time.monotonic() + (args.deadline_utc - datetime.now(timezone.utc)).total_seconds()

    def watch():
        if time.monotonic() >= stop:
            raise TimeoutError('SQL witness reached the run deadline')

    watch()
    out = args.out.resolve(strict=True)
    receipt = out / 'k1_sql_witness.json'
    if receipt.exists():
        raise FileExistsError(receipt)
    stage = ROOT / STAGE12
    runtime = ROOT / 'shop-mysql-runtime'
    primary = runtime / 'retailrocket_session_knn_paired_v1'
    paths = {'dataset': runtime / 'retailrocket_dataset_v1',
             'P0': runtime / 'retailrocket_popularity_v1' / 'development',
             'C1': runtime / 'retailrocket_cooccurrence_paired_v1'}
    if any(out.is_relative_to(folder) for folder in (primary, *paths.values())):
        raise ValueError('The witness cannot write inside an immutable source directory')
    gate_data = (out / 'k1_sources_before.json').read_bytes()
    before = json.loads(gate_data)
    exact(before['status'], 'passed')
    spec = (stage / 'retailrocket_session_knn_v1_validation_entry_specification.json').read_bytes()
    exact(hashlib.sha256(spec).hexdigest(), before['entry_spec_sha256'])
    result = verify(primary, paths, json.loads(spec)['configuration'], out / 'sql_witness',
                    before['primary_sha256']['queries.jsonl'], watch)
    exact((out / 'k1_sources_before.json').read_bytes() == gate_data, True)
    result['source_gate_sha256'] = hashlib.sha256(gate_data).hexdigest()
    result['engine_sha256'] = sha(Path(__file__), watch)
    watch()
    write_result(receipt, result)
    print('SQL witness passed', result['queries_sql_checked'], 'fixed predictions', result['elapsed_seconds'], flush=True)


if __name__ == '__main__':
    main()
