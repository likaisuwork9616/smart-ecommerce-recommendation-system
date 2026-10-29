"""Two train-only cost passes; bounded single-session sets, no global K1 index."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sqlite3

from scripts import retailrocket_session_knn as k
from scripts import retailrocket_popularity_io as io

HEADER = ['visitorid','session_start_ms','baskets','basket_memberships','distinct_items','membership_sha256']


def summary():
    return dict(train_sessions=0,train_baskets=0,basket_item_memberships=0,distinct_session_item_memberships=0,
                singleton_sessions=0,maximum_session_items=0,maximum_session_baskets=0)


def add(result,baskets,occurrences,members):
    result['train_sessions'] += 1; result['train_baskets'] += baskets
    result['basket_item_memberships'] += occurrences; result['distinct_session_item_memberships'] += members
    result['singleton_sessions'] += members==1
    result['maximum_session_items'] = max(result['maximum_session_items'],members)
    result['maximum_session_baskets'] = max(result['maximum_session_baskets'],baskets)


def audit(source, header, start, end, support_path, lineage_path, folder, watch=lambda:None):
    folder = Path(folder); folder.mkdir(parents=True,exist_ok=False)
    result = summary(); roles = Counter(); decoded = 0; hist = Counter()
    def baskets():
        nonlocal decoded
        for row in io.records(Path(source),header):
            watch(); roles[row['role']] += 1
            if row['role'] != 'train':
                continue  # No nontrain item JSON decode (including malformed sentinel fixtures).
            decoded += 1
            yield k.Basket(row['visitorid'],io.number(row['session_start_ms']),io.number(row['query_ms']),
                           'train',io.number(row['basket_index']),io.array(row['items']))
    ledger = folder/'train_session_costs.csv'
    with ledger.open('x',encoding='utf-8',newline='') as output,Path(lineage_path).open(encoding='utf-8') as reference:
        writer = csv.writer(output,lineterminator='\n'); writer.writerow(HEADER)
        for row in k.train_sets(baskets(),start,end,watch):
            original_line = reference.readline()
            if not original_line or json.loads(original_line) != row:
                raise ValueError('Full train session lineage differs from frozen C1')
            members = len(row['items']); hist[members] += 1
            digest = hashlib.sha256(k.encoded(row['items']).encode()).hexdigest()
            writer.writerow([*row['key'],row['baskets'],row['basket_memberships'],members,digest])
            add(result,row['baskets'],row['basket_memberships'],members)
        if reference.readline():
            raise ValueError('Extra C1 train lineage')
    result['session_size_histogram'] = {str(n):hist[n] for n in sorted(hist)}
    # Existing accepted train support provides posting lengths; no new global support fit.
    previous_item = -1; support_items = support_sum = max_posting = 0
    for r in io.records(Path(support_path),['itemid','support']):
        watch(); item = io.number(r['itemid']); n = io.number(r['support'])
        if item <= previous_item or n < 1:
            raise ValueError('Invalid frozen support order/value')
        previous_item = item; support_items += 1; support_sum += n; max_posting = max(max_posting,n)
    if support_sum != result['distinct_session_item_memberships']:
        raise ValueError('Membership total differs from frozen C1 sum S_i')
    independent = independent_cost(source,header,start,end,ledger,watch)
    for key in (*summary().keys(),'session_size_histogram'):
        if independent[key] != result[key]:
            raise ValueError('Independent cost aggregate differs: '+key)
    if independent['role_metadata_counts'] != dict(roles) or independent['train_item_arrays_decoded'] != decoded:
        raise ValueError('Independent role/decode counts differ')
    result.update(positive_support_items=support_items,maximum_posting_size=max_posting,
        frozen_C1_support_memberships=support_sum,independent_rows_checked=independent['rows_checked'],
        independent_cells_checked=independent['rows_checked']*len(HEADER),independent_raw_cost_passes=2,
        train_item_arrays_decoded_per_pass=decoded,role_metadata_counts_per_pass=dict(roles),
        validation_test_item_arrays_decoded=0,global_K1_index_built=False,new_item_support_fitted=False,
        complete_C1_train_lineage_checked=True,maximum_independent_SQL_session_members=independent['maximum_SQL_members'],
        interpretation='M is exact membership count; posting maxima come from accepted C1 support, not a new K1 fit. No query-cost/RSS/runtime guarantee.')
    with (folder/'cost.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
    return result


def independent_cost(source,header,start,end,ledger,watch=lambda:None):
    """Separate CSV/parser plus per-session SQL DISTINCT, no production set iterator."""
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE m(i TEXT PRIMARY KEY)')
    db.execute('CREATE TEMP TABLE basket(i TEXT PRIMARY KEY)')
    db.set_progress_handler(lambda:(watch() or 0),4096)
    total = summary(); hist = Counter(); roles = Counter(); decoded = checked = max_sql = 0
    key = previous = last_index = None; n = occurrences = 0
    def canonical(value):
        if type(value) is not str or not value.isascii() or not value.isdecimal() or str(int(value)) != value:
            raise ValueError('Independent noncanonical integer')
        return int(value)
    try:
        with Path(source).open(encoding='utf-8',newline='') as source_stream,Path(ledger).open(encoding='utf-8',newline='') as output:
            rows = csv.DictReader(source_stream); readback = csv.reader(output)
            if rows.fieldnames != header or next(readback) != HEADER:
                raise ValueError('Independent cost schema')
            def finish():
                nonlocal checked,max_sql
                members = sorted((r[0] for r in db.execute('SELECT i FROM m')),key=int)
                digest = hashlib.sha256(json.dumps(members,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                expected = [key[0],str(key[1]),str(n),str(occurrences),str(len(members)),digest]
                if next(readback,None) != expected:
                    raise ValueError('Independent per-session cost/hash mismatch')
                checked += 1; max_sql = max(max_sql,len(members)); hist[len(members)] += 1
                total['train_sessions'] += 1
                total['train_baskets'] += n
                total['basket_item_memberships'] += occurrences
                total['distinct_session_item_memberships'] += len(members)
                total['singleton_sessions'] += int(len(members)==1)
                total['maximum_session_items'] = max(total['maximum_session_items'],len(members))
                total['maximum_session_baskets'] = max(total['maximum_session_baskets'],n)
                db.execute('DELETE FROM m')
            for row in rows:
                watch()
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Independent CSV width')
                roles[row['role']] += 1
                if row['role'] != 'train':
                    continue
                v = row['visitorid']; canonical(v)
                s,t,index = (canonical(row[name]) for name in ('session_start_ms','query_ms','basket_index'))
                if not start <= t < end or s > t or index < 1:
                    raise ValueError('Independent train clock/index')
                if previous is not None and (v,s,t) <= previous:
                    raise ValueError('Independent source duplicate/order')
                previous = (v,s,t)
                if key is not None and (v,s) != key:
                    finish(); n = occurrences = 0; last_index = None
                key = (v,s)
                if last_index is not None and index <= last_index:
                    raise ValueError('Independent source index order')
                last_index = index
                ids = json.loads(row['items']); decoded += 1
                if not isinstance(ids,list) or not ids:
                    raise ValueError('Independent empty/non-list train items')
                for i in ids: canonical(i)
                # Duplicate detection via a separate per-basket SQL temporary relation.
                db.execute('DELETE FROM basket')
                db.executemany('INSERT INTO basket VALUES(?)',[(i,) for i in ids])
                db.execute('INSERT OR IGNORE INTO m SELECT i FROM basket')
                n += 1; occurrences += len(ids)
            if key is not None: finish()
            if next(readback,None) is not None:
                raise ValueError('Extra cost ledger row')
        total.update(session_size_histogram={str(n):hist[n] for n in sorted(hist)},rows_checked=checked,
                     role_metadata_counts=dict(roles),train_item_arrays_decoded=decoded,maximum_SQL_members=max_sql)
        return total
    finally:
        db.close()
