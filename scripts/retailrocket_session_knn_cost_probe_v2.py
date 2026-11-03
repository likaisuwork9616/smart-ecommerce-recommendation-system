"""Target-blind, fixed-cell engineering probes for the independent SQL V2.

This module does not authorize or launch a real-data run.  The caller owns the
absolute deadline, SQL VM progress handler, source binding and all phase costs.
Probe timings are engineering observations, never validation effectiveness or
an acceptance result.  Full-population stratification is itself charged work.
"""
from bisect import bisect_left
import hashlib
import heapq
import json
from pathlib import Path
from time import perf_counter

from scripts.retailrocket_popularity_oracle import read_rows, num
from scripts import retailrocket_session_knn_sql_v2 as sql


POSTING_BANDS = ('0', '1-100', '101-1000', '>1000')
EXTREMES = ('posting_work', 'vote_memberships_upper', 'history_size', 'causal_candidates')
SELECTION_POLICY = 'four_equal_time_bands_x_four_posting_bands_extremes_then_key_sha256_v1'


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_dump(value).encode('utf-8')).hexdigest()


def _history(db, key, watch, expected_index=None):
    current = db.execute('SELECT k,role FROM h WHERE v=? AND s=? AND t=?', key).fetchone()
    if current is None or current[1] != 'validation':
        raise ValueError('Cost probe missing validation current basket')
    if expected_index is not None and current[0] != expected_index:
        raise ValueError('Cost probe basket index differs')
    history = set()
    for text, role in db.execute(
            'SELECT items,role FROM h WHERE v=? AND s=? AND t<=? ORDER BY t', key):
        watch()
        if role not in ('warmup', 'train', 'validation'):
            raise ValueError('Cost probe forbidden history role')
        items = json.loads(text)
        if type(items) is not list or not items or len(set(items)) != len(items):
            raise ValueError('Cost probe invalid independently reconstructed history')
        for item in items:
            num(item)
        history.update(items)
    return sorted(history, key=int)


def _work(db, history, current, support, watch):
    """Use complete positive SQL overlaps; upper bound is NOT chosen by score."""
    db.execute('DELETE FROM temp.k1_v2_probe_history')
    for item in history:
        watch()
        db.execute('INSERT INTO temp.k1_v2_probe_history VALUES(?)', (item,))
    posting = sum(support.get(item, 0) for item in history)
    largest = []
    visited = eligible = excluded = 0
    for visitor, start, overlap, size in db.execute(
            'SELECT membership.v,membership.s,COUNT(*),sizes.n '
            'FROM temp.k1_v2_probe_history AS query '
            'CROSS JOIN main.m AS membership INDEXED BY k1_v2_posting '
            'ON membership.i=query.i '
            'JOIN main.k1_v2_sizes AS sizes '
            'ON sizes.v=membership.v AND sizes.s=membership.s '
            'GROUP BY membership.v,membership.s'):
        watch()
        visited += overlap
        if (visitor, start) == current:
            excluded += 1
            continue
        if not 0 < overlap <= min(len(history), size):
            raise ValueError('Cost probe invalid independent session sizes')
        eligible += 1
        if len(largest) < 500:
            heapq.heappush(largest, size)
        elif size > largest[0]:
            heapq.heapreplace(largest, size)
    if posting != visited:
        raise ValueError('Cost probe support differs from full SQL overlaps')
    return {'posting_work': posting, 'vote_memberships_upper': sum(largest),
            'eligible_neighbors': eligible, 'current_session_excluded': excluded}


def _cell(time_band, posting):
    band = POSTING_BANDS[0 if posting == 0 else 1 if posting <= 100 else 2 if posting <= 1000 else 3]
    return f'time_{time_band}/posting_{band}', band


def stratify(db, source, config, support, catalog, watch=lambda: None):
    """Scan the complete validation roster and return population and <=64 probes.

    Role is checked before any item/key/target decoding; no target field or
    existing prediction file is accessed.  Probes retain metadata and hashes,
    with history independently rebuilt again when measured.  Each cell chooses
    the maximum of four frozen costs (ties by smallest key SHA), then fills to
    at most four distinct keys by smallest SHA.  No random or prefix sampling.
    """
    lo, hi = config['validation_window_ms']
    if type(lo) is not int or type(hi) is not int or hi <= lo:
        raise ValueError('Cost probe invalid validation window')
    expected = config.get('fixed_validation', {}).get('queries', 166897)
    if type(expected) is not int or expected < 0:
        raise ValueError('Cost probe invalid fixed population')
    watch()
    first_times = sorted(catalog.values())
    db.execute('CREATE TEMP TABLE IF NOT EXISTS k1_v2_probe_history '
               '(i TEXT PRIMARY KEY) WITHOUT ROWID')
    cells = {f'time_{time}/posting_{band}': {'count': 0, 'maxima': {}, 'hashes': []}
             for time in range(4) for band in POSTING_BANDS}
    total = 0
    previous = None
    for raw in read_rows(Path(source)/'queries.csv', config['schemas']['queries.csv']):
        watch()
        if raw['role'] != 'validation':
            continue
        visitor = raw['visitorid']
        num(visitor)
        start, at, index = (num(raw[field]) for field in ('session_start_ms', 'query_ms', 'basket_index'))
        key = (visitor, start, at)
        if not lo <= at < hi or start > at:
            raise ValueError('Cost probe query outside validation window')
        if previous is not None and key <= previous:
            raise ValueError('Cost probe duplicate or unordered validation key')
        previous = key
        history = _history(db, key, watch, index)
        work = _work(db, history, (visitor, start), support, watch)
        time_band = 4*(at-lo)//(hi-lo)
        cell, posting_band = _cell(time_band, work['posting_work'])
        row = dict(work, key=list(key), key_sha256=_sha(list(key)),
                   history_sha256=_sha(history), history_size=len(history),
                   causal_candidates=bisect_left(first_times, at),
                   time_band=time_band, posting_band=posting_band, cell=cell)
        bucket = cells[cell]
        bucket['count'] += 1
        total += 1
        for field in EXTREMES:
            old = bucket['maxima'].get(field)
            if old is None or (-row[field], row['key_sha256']) < (-old[field], old['key_sha256']):
                bucket['maxima'][field] = row
        bucket['hashes'].append(row)
        bucket['hashes'].sort(key=lambda r: r['key_sha256'])
        del bucket['hashes'][4:]
    if total != expected:
        raise ValueError(f'Cost probe incomplete validation population: {total} != {expected}')
    population = {'selection_policy': SELECTION_POLICY, 'total_queries': total,
                  'expected_queries': expected, 'complete': True,
                  'validation_window_ms': [lo, hi], 'cells': {},
                  'targets_accessed': False, 'main_predictions_accessed': False}
    probes = []
    for cell, bucket in cells.items():
        chosen = {}
        for field in EXTREMES:
            row = bucket['maxima'].get(field)
            if row is not None:
                selected = chosen.setdefault(row['key_sha256'], dict(row, selection_reasons=[]))
                selected['selection_reasons'].append('maximum_'+field)
        for row in bucket['hashes']:
            if len(chosen) == min(4, bucket['count']):
                break
            if row['key_sha256'] not in chosen:
                chosen[row['key_sha256']] = dict(row, selection_reasons=['key_sha256_fill'])
        population['cells'][cell] = {'count': bucket['count'], 'selected_count': len(chosen),
                                    'maxima': {field: row[field] for field, row in bucket['maxima'].items()}}
        probes.extend(sorted(chosen.values(), key=lambda r: r['key_sha256']))
    watch()
    return population, probes


def measure_queries(db, probes, support, fit_id, counts, catalog, watch=lambda: None):
    """Measure only frozen probes; return engineering costs, never scores.

    History reconstruction and exact prediction are timed together.  Catalog
    preparation is separately measured once.  Checkpoint I/O, full-scale
    stress, global replay, bootstrap, source rehash and resume remain separate
    required phases: this result must not imply any of them cost zero.
    """
    begin = perf_counter()
    prepared = sql.prepare_catalog(catalog, counts, watch)
    preparation_seconds = perf_counter()-begin
    rows = []
    cells = {}
    seen = set()
    for probe in probes:
        watch()
        key = tuple(probe['key'])
        if key in seen or _sha(list(key)) != probe['key_sha256']:
            raise ValueError('Cost probe duplicate or changed frozen key')
        seen.add(key)
        start = perf_counter()
        history = _history(db, key, watch)
        if len(history) != probe['history_size'] or _sha(history) != probe['history_sha256']:
            raise ValueError('Cost probe history changed after selection')
        if prepared.size(key[2]) != probe['causal_candidates']:
            raise ValueError('Cost probe causal catalog changed after selection')
        work = {}
        prediction = sql.predict(db, support, fit_id, prepared.counts, prepared,
                                 key[2], history, key[:2], watch, workload=work)
        elapsed = perf_counter()-start
        if prediction['raw_posting_visits'] != probe['posting_work']:
            raise ValueError('Cost probe posting work changed after selection')
        if prediction['vote_memberships'] > probe['vote_memberships_upper']:
            raise ValueError('Cost probe selected votes exceed frozen upper bound')
        row = {'key': list(key), 'key_sha256': probe['key_sha256'], 'cell': probe['cell'],
               'seconds': elapsed, 'workload': work}
        rows.append(row)
        cell = cells.setdefault(probe['cell'], {'count': 0, 'max_seconds': 0.0})
        cell['count'] += 1
        cell['max_seconds'] = max(cell['max_seconds'], elapsed)
    return {'kind': 'engineering_cost_only', 'queries': rows, 'cells': cells,
            'catalog_prepare_seconds': preparation_seconds,
            'query_checkpoint_io_included': False, 'formal_acceptance': False,
            'main_predictions_accessed': False, 'targets_accessed': False,
            'required_separate_costs': ['checkpoint_io', 'source_hash', 'build', 'stratify',
                                        'full_scale_stress', 'global', 'bootstrap', 'finalize', 'resume']}
