"""Train-only session cardinality/cost audit; never count item/pair models."""
from collections import Counter
import csv
import json
from pathlib import Path
import sqlite3

from scripts import retailrocket_popularity_io as oldio
from scripts import retailrocket_popularity as p


def train_sessions(path, header, start, end):
    """Clip before grouping decisions; no non-train membership is decoded."""
    previous = None
    key = None
    members = set()
    baskets = occurrences = 0
    for row in oldio.records(path, header):
        if row['role'] != 'train':
            continue
        v = p.item(row['visitorid'])
        s, t, index = (oldio.number(row[k]) for k in ('session_start_ms', 'query_ms', 'basket_index'))
        if not start <= t < end or s > t or index < 1:
            raise ValueError('Invalid train basket clock/index')
        order = (v, s, t)
        if previous is not None and order <= previous:
            raise ValueError('Unordered or duplicate train basket')
        previous = order
        current = (v, s)
        if key is not None and current != key:
            yield key, members, baskets, occurrences
            members = set()
            baskets = occurrences = 0
        key = current
        ids = oldio.array(row['items'])
        members.update(ids)
        baskets += 1
        occurrences += len(ids)
    if key is not None:
        yield key, members, baskets, occurrences


def summarize(rows):
    histogram = Counter()
    sessions = singleton = baskets = occurrences = supports = emissions = maximum = 0
    for n, b, o in rows:
        sessions += 1
        singleton += n == 1
        baskets += b
        occurrences += o
        supports += n
        emissions += n * (n - 1) // 2
        maximum = max(maximum, n)
        histogram[n] += 1
    return {'train_sessions': sessions, 'singleton_sessions': singleton, 'train_baskets': baskets,
            'basket_item_memberships': occurrences, 'distinct_session_item_memberships': supports,
            'exact_unordered_pair_emissions': emissions, 'maximum_session_items': maximum,
            'session_cardinality_histogram': {str(k): histogram[k] for k in sorted(histogram)},
            'unique_pairs_materialized': False, 'item_support_model_built': False,
            'pair_count_model_built': False, 'validation_or_test_items_decoded': False}


def audit(source, header, start, end, folder):
    """Write private cardinalities, independently reconcile SQL DISTINCT counts."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    ledger = folder / 'train_session_cardinalities.csv'
    with ledger.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['visitorid', 'session_start_ms', 'distinct_items', 'baskets', 'basket_memberships'])
        def rows():
            for (v, s), items, b, o in train_sessions(source, header, start, end):
                n = len(items)
                writer.writerow([v, s, n, b, o])
                yield n, b, o
        result = summarize(rows())
    db = sqlite3.connect(folder / 'independent_cost.sqlite')
    db.execute('PRAGMA temp_store=MEMORY')
    try:
        db.execute('CREATE TABLE membership(v TEXT,s INTEGER,i TEXT)')
        db.execute('CREATE TABLE basket(v TEXT,s INTEGER,t INTEGER,n INTEGER,PRIMARY KEY(v,s,t))')
        with Path(source).open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != header:
                raise ValueError('Cost oracle schema differs')
            batch = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Cost oracle CSV width')
                if row['role'] != 'train':
                    continue
                v, s, t = row['visitorid'], int(row['session_start_ms']), int(row['query_ms'])
                if not start <= t < end:
                    raise ValueError('Cost oracle train clock')
                ids = json.loads(row['items'])
                if not ids or len(ids) != len(set(ids)):
                    raise ValueError('Cost oracle membership')
                db.execute('INSERT INTO basket VALUES(?,?,?,?)', (v, s, t, len(ids)))
                batch.extend((v, s, i) for i in ids)
                if len(batch) >= 20000:
                    db.executemany('INSERT INTO membership VALUES(?,?,?)', batch)
                    batch.clear()
            db.executemany('INSERT INTO membership VALUES(?,?,?)', batch)
        db.execute('CREATE TABLE card AS SELECT v,s,COUNT(DISTINCT i) AS n FROM membership GROUP BY v,s')
        expected = []
        with ledger.open(encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                expected.append((row['visitorid'], int(row['session_start_ms']), int(row['distinct_items']),
                                 int(row['baskets']), int(row['basket_memberships'])))
        cursor = db.execute('SELECT c.v,c.s,c.n,COUNT(*),SUM(b.n) FROM card c JOIN basket b ON c.v=b.v AND c.s=b.s GROUP BY c.v,c.s ORDER BY c.v,c.s')
        checked = 0
        independent_rows = []
        for actual in cursor:
            if checked >= len(expected) or tuple(expected[checked]) != tuple(actual):
                raise ValueError('Independent train cardinality row differs')
            independent_rows.append(actual[2:])
            checked += 1
        if checked != len(expected) or summarize(independent_rows) != result:
            raise ValueError('Independent cost aggregate differs')
        result['independent_cardinality_rows_checked'] = checked
        result['independent_cardinality_cells_checked'] = checked * 5
        db.commit()
    finally:
        db.close()
    return result
