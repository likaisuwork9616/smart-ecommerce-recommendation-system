"""Read the pinned official Retailrocket ZIP; write aggregate intake evidence only.

No recommendation samples, labels, fits or evaluation scores are created.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import re
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/retailrocket'
PRIVATE = ROOT / 'shop-mysql-runtime/retailrocket_intake_v1'
REPORT = ROOT / 'reports/stage8/retailrocket_source_audit_v1.json'
HEADERS = {
    'events.csv': ['timestamp', 'visitorid', 'event', 'itemid', 'transactionid'],
    'category_tree.csv': ['categoryid', 'parentid'],
    'item_properties_part1.csv': ['timestamp', 'itemid', 'property', 'value'],
    'item_properties_part2.csv': ['timestamp', 'itemid', 'property', 'value'],
}
ID = re.compile(r'^(0|[1-9][0-9]*)$', re.ASCII)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while b := f.read(1024*1024):
            h.update(b)
    return h.hexdigest()


def descriptor(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds')


def scalar(db, query):
    return db.execute(query).fetchone()[0]


def rows(archive, name):
    with archive.open(name) as binary:
        reader = csv.reader(io.TextIOWrapper(binary, encoding='utf-8', newline=''))
        if next(reader) != HEADERS[name]:
            raise ValueError('unexpected header: '+name)
        for i, row in enumerate(reader, 2):
            if len(row) != len(HEADERS[name]):
                raise ValueError(f'field count: {name}:{i}')
            yield i, row


def run():
    started = time.monotonic()
    if PRIVATE.exists() or REPORT.exists():
        raise FileExistsError('intake output already exists; use --verify, never overwrite')
    PRIVATE.mkdir(parents=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    source = json.loads((RAW/'source_manifest.json').read_text(encoding='utf-8'))
    meta = json.loads((RAW/'metadata.json').read_text(encoding='utf-8'))
    package = RAW/'ecommerce-dataset-v2.zip'
    expected = source['requests']['official_zip']
    assert package.stat().st_size == expected['bytes'] and sha(package) == expected['sha256']
    assert meta['ownerRef'] == 'retailrocket' and meta['currentVersionNumber'] == 2
    assert meta['licenseName'] == 'CC BY-NC-SA 4.0'
    dbpath = PRIVATE/'inventory.sqlite'
    db = sqlite3.connect(dbpath)
    db.executescript('''PRAGMA temp_store=MEMORY; PRAGMA journal_mode=OFF;
        CREATE TABLE events(rowno INTEGER PRIMARY KEY,t INTEGER,v TEXT,e TEXT,i TEXT,x TEXT);
        CREATE TABLE properties(part TEXT,rowno INTEGER,t INTEGER,i TEXT,p TEXT,value TEXT);
        CREATE TABLE categories(c TEXT,p TEXT);
    ''')
    report = {'schema_version': 1, 'status': 'source_audit_completed_contract_not_yet_frozen',
              'checked_date_asia_taipei': '2026-10-28',
              'official_source': {'dataset_id': 1031, 'owner': meta['ownerRef'], 'creator': meta['creatorName'],
                                  'version': 2, 'license': meta['licenseName'],
                                  'url': 'https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset',
                                  'license_url': 'https://creativecommons.org/licenses/by-nc-sa/4.0/'},
              'scope': {'models_trained': 0, 'recommendation_samples_built': 0, 'test_scores_computed': 0},
              'limitations': ['event time is not historical ingestion or availability time',
                              'visitorid is an anonymous source key, not a verified person',
                              'no impression/exposure/propensity log, price/currency/order outcome evidence',
                              'raw file order does not resolve simultaneous event order',
                              'generic hashed properties are scanned structurally, not audited as model features']}
    members = []
    event_counts = collections.Counter()
    missing = collections.Counter()
    invalid = collections.Counter()
    backward = 0
    previous = None
    with zipfile.ZipFile(package) as z:
        assert len(z.namelist()) == 4 and set(z.namelist()) == set(HEADERS)
        # A complete read of every member checks the ZIP CRC as well as its SHA.
        for name in HEADERS:
            h = hashlib.sha256()
            with z.open(name) as f:
                while b := f.read(1024*1024):
                    h.update(b)
            m = z.getinfo(name)
            members.append({'name': name, 'bytes': m.file_size, 'sha256': h.hexdigest(), 'crc32': f'{m.CRC:08x}'})
        batch = []
        for rowno, r in rows(z, 'events.csv'):
            for col, value in zip(HEADERS['events.csv'], r):
                if value == '':
                    missing[col] += 1
            t, v, e, i, x = r
            if not ID.fullmatch(t) or not ID.fullmatch(v) or not ID.fullmatch(i) or (x and not ID.fullmatch(x)):
                invalid['identifier_or_timestamp'] += 1
                continue
            if e not in ('view','addtocart','transaction'):
                invalid['event_type'] += 1
                continue
            ti = int(t)
            if previous is not None and ti < previous:
                backward += 1
            previous = ti
            event_counts[e] += 1
            batch.append((rowno, ti, v, e, i, x))
            if len(batch) == 20000:
                db.executemany('INSERT INTO events VALUES(?,?,?,?,?,?)', batch)
                batch.clear()
        db.executemany('INSERT INTO events VALUES(?,?,?,?,?,?)', batch)
        db.commit()
        print('events parsed', flush=True)
        props = {'parts': {}, 'critical_values': {}, 'invalid': {}, 'all_items': None}
        items = set()
        critical = collections.Counter()
        propnames = collections.Counter()
        invalid_p = collections.Counter()
        for name in ('item_properties_part1.csv', 'item_properties_part2.csv'):
            count = 0
            low = None
            high = None
            batch = []
            for rowno, r in rows(z, name):
                count += 1
                t, i, p, value = r
                if not ID.fullmatch(t) or not ID.fullmatch(i) or not p or not value:
                    invalid_p['invalid_or_missing_field'] += 1
                    continue
                ti = int(t)
                low = ti if low is None else min(low,ti)
                high = ti if high is None else max(high,ti)
                items.add(i)
                propnames[p] += 1
                if p in ('available','categoryid'):
                    if p == 'available':
                        critical[value] += 1
                    batch.append((name, rowno, ti, i, p, value))
                if len(batch) >= 20000:
                    db.executemany('INSERT INTO properties VALUES(?,?,?,?,?,?)', batch)
                    batch.clear()
            db.executemany('INSERT INTO properties VALUES(?,?,?,?,?,?)', batch)
            db.commit()
            props['parts'][name] = {'rows': count, 'min_ms': low, 'max_ms': high, 'min_utc': utc(low), 'max_utc': utc(high)}
            print(name+' parsed', flush=True)
        props.update(all_items=len(items), property_names=len(propnames), critical_values=dict(critical), invalid=dict(invalid_p),
                     critical_rows={p:propnames[p] for p in ('available','categoryid')})
        cats = []
        for _, (c,p) in rows(z,'category_tree.csv'):
            if not ID.fullmatch(c) or (p and not ID.fullmatch(p)):
                raise ValueError('invalid category key')
            cats.append((c,p))
        db.executemany('INSERT INTO categories VALUES(?,?)',cats)
    db.executescript('''CREATE INDEX event_natural ON events(t,v,e,i,x);
        CREATE INDEX event_visitor_clock ON events(v,t,i);
        CREATE INDEX event_transaction ON events(x,v,t);
        CREATE INDEX property_key ON properties(i,p,t,value);
    ''')
    db.commit()
    n = scalar(db,'SELECT COUNT(*) FROM events')
    lo, hi = db.execute('SELECT MIN(t),MAX(t) FROM events').fetchone()
    report['events'] = {
        'rows': n, 'event_counts': dict(event_counts), 'missing': dict(missing), 'invalid': dict(invalid),
        'visitors': scalar(db,'SELECT COUNT(DISTINCT v) FROM events'), 'items': scalar(db,'SELECT COUNT(DISTINCT i) FROM events'),
        'min_ms':lo,'max_ms':hi,'min_utc':utc(lo),'max_utc':utc(hi),
        'raw_timestamp_backward_steps': backward,
        'exact_duplicate_excess': scalar(db,'SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM events GROUP BY t,v,e,i,x HAVING COUNT(*)>1)'),
        'four_field_duplicate_excess': scalar(db,'SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM events GROUP BY t,v,e,i HAVING COUNT(*)>1)'),
        'four_field_groups_with_distinct_transactionid':scalar(db,'SELECT COUNT(*) FROM (SELECT t,v,e,i FROM events GROUP BY t,v,e,i HAVING COUNT(DISTINCT x)>1)'),
        'visitor_timestamp_groups_multiple_items':scalar(db,'SELECT COUNT(*) FROM (SELECT v,t FROM events GROUP BY v,t HAVING COUNT(DISTINCT i)>1)'),
        'transaction_missing_id':scalar(db,"SELECT COUNT(*) FROM events WHERE e='transaction' AND x=''"),
        'non_transaction_with_id':scalar(db,"SELECT COUNT(*) FROM events WHERE e!='transaction' AND x!=''"),
        'transaction_ids':scalar(db,"SELECT COUNT(DISTINCT x) FROM events WHERE e='transaction' AND x!=''"),
        'transaction_ids_multiple_visitors':scalar(db,"SELECT COUNT(*) FROM (SELECT x FROM events WHERE e='transaction' AND x!='' GROUP BY x HAVING COUNT(DISTINCT v)>1)"),
        'transaction_ids_multiple_timestamps':scalar(db,"SELECT COUNT(*) FROM (SELECT x FROM events WHERE e='transaction' AND x!='' GROUP BY x HAVING COUNT(DISTINCT t)>1)"),
        'by_utc_day':[{'day':d,'event':e,'rows':c} for d,e,c in db.execute("SELECT date(t/1000,'unixepoch'),e,COUNT(*) FROM events GROUP BY 1,2 ORDER BY 1,2")],
        'by_utc_month':[{'month':d,'event':e,'rows':c} for d,e,c in db.execute("SELECT strftime('%Y-%m',t/1000,'unixepoch'),e,COUNT(*) FROM events GROUP BY 1,2 ORDER BY 1,2")],
    }
    props['critical_exact_duplicate_excess'] = scalar(db,'SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM properties GROUP BY i,p,t,value HAVING COUNT(*)>1)')
    props['critical_same_timestamp_conflict_keys'] = scalar(db,'SELECT COUNT(*) FROM (SELECT i,p,t FROM properties GROUP BY i,p,t HAVING COUNT(DISTINCT value)>1)')
    props['critical_category_values_not_in_tree'] = scalar(db,"SELECT COUNT(DISTINCT value) FROM properties WHERE p='categoryid' AND value NOT IN(SELECT c FROM categories)")
    props['critical_items'] = scalar(db,'SELECT COUNT(DISTINCT i) FROM properties')
    props['event_items_missing_any_properties'] = len({r[0] for r in db.execute('SELECT DISTINCT i FROM events')}-items)
    report['properties'] = props
    report['category_tree'] = {'rows':len(cats), 'unique_children':len({c for c,p in cats}), 'roots':sum(not p for c,p in cats),
        'parents_not_in_children':len({p for c,p in cats if p}-{c for c,p in cats}),
        'self_links':sum(c==p for c,p in cats)}
    db.close()
    report['files'] = members
    report['source_descriptors'] = [descriptor(p) for p in (package,RAW/'metadata.response',RAW/'file_list.response',RAW/'source_page.response',RAW/'license.response',RAW/'source_manifest.json',ROOT/'scripts/audit_retailrocket_source.py')]
    report['private_inventory'] = descriptor(dbpath)
    report['verification'] = {'all_four_members_crc_and_sha256_readback':True,'all_csv_rows_scanned':True,
                              'event_count_reconciles':n==sum(event_counts.values()),'elapsed_seconds':round(time.monotonic()-started,3)}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    guard = {'report':descriptor(REPORT), 'sources':report['source_descriptors'], 'inventory':report['private_inventory']}
    (PRIVATE/'output_guard.json').write_text(json.dumps(guard,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','verification')},ensure_ascii=False,indent=2))


def verify():
    guard = json.loads((PRIVATE/'output_guard.json').read_text(encoding='utf-8'))
    files = [guard['report'],guard['inventory'],*guard['sources']]
    for record in files:
        path = (ROOT/record['path']).resolve()
        if not path.is_relative_to(ROOT) or descriptor(path) != record:
            raise ValueError('source bytes changed: '+record['path'])
    print(json.dumps({'status':'source_audit_bytes_verified','files':len(files),'new_models':0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',action='store_true')
    args = parser.parse_args()
    verify() if args.verify else run()
