"""Read-only local source/clock inventory; never builds or scores a second RFM."""
import argparse
import csv
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPORT = 'reports/stage6/rfm_temporal_data_inventory.json'
BASELINE = datetime(2018, 9, 1)
# Coverage probes, not selected validation dates or newly accepted snapshots.
PROBES = (datetime(2018, 10, 1), datetime(2018, 11, 1))
SEARCH = ('data', '.runtime/downloads', '.runtime/backups',
          '.runtime/data_handoffs', '.runtime/review_window_handoffs',
          '.runtime/rfm_temporal_handoffs')
META = ('.runtime/verification/olist-source-manifest.json',
        '.runtime/verification/full-setup.json')
PUBLIC = ('scripts/audit_rfm_temporal_data.py', 'tests/test_rfm_temporal_data.py',
          'reports/stage4/event_source_availability.json',
          'reports/stage5/review_validation_window_inventory.json',
          'reports/stage6/rfm_rebuild_v2.json',
          'reports/stage6/rfm_g3_v2_specification.json',
          'reports/stage6/rfm_g3_v2.json')
CLOCKS = ('order_purchase_timestamp', 'order_approved_at', 'order_delivered_customer_date')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def descriptor(root, name):
    path = root / name
    return {'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def clock(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def projected(path, fields):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not set(fields).issubset(reader.fieldnames or ()):
            raise ValueError('Required inventory columns absent')
        # Parse CSV framing, but retain/use only the requested metadata fields.
        return [{key: row[key] for key in fields} for row in reader]


def event_reason(row, cutoff):
    """Original event-only proxy at a probe cutoff; not a complete RFM guard."""
    purchase, approval, delivery = (clock(row[k]) for k in CLOCKS)
    if purchase is None:
        raise ValueError('Unlocatable purchase: cannot audit complete coverage')
    if purchase >= cutoff:
        return 'purchase_at_or_after_T'
    if row['order_status'] != 'delivered':
        return 'status_not_delivered'
    if delivery is None:
        return 'missing_or_invalid_delivery'
    if delivery < purchase:
        return 'delivery_before_purchase'
    if delivery >= cutoff:
        return 'delivery_at_or_after_T'
    if approval is not None and not purchase <= approval <= delivery:
        return 'approval_clock_conflict'
    return 'eligible_event_proxy'


def coverage(rows, lower, upper):
    new = [r for r in rows if lower <= clock(r[CLOCKS[0]]) < upper]
    old_deliveries = [r for r in rows if clock(r[CLOCKS[0]]) < lower
                      and (d := clock(r[CLOCKS[2]])) is not None and lower <= d < upper]
    reasons = Counter(event_reason(r, upper) for r in new)
    assert sum(reasons.values()) == len(new)
    return {'purchase_interval': [lower.isoformat(), upper.isoformat()],
            'purchase_rows': len(new),
            'final_snapshot_status_counts': dict(sorted(Counter(r['order_status'] for r in new).items())),
            'new_purchase_event_proxy_reasons': dict(sorted(reasons.items())),
            'eligible_new_purchase_event_proxy': reasons['eligible_event_proxy'],
            'earlier_purchase_delivery_events_in_interval': len(old_deliveries),
            'earlier_purchase_event_proxy_eligible_by_upper': sum(
                event_reason(r, upper) == 'eligible_event_proxy' for r in old_deliveries),
            'upstream_complete': None, 'accepted_for_temporal_validation': False}


def distinct_versions(copies):
    versions = {}
    for row in copies:
        versions.setdefault(row['table'], set()).add(row['sha256'])
    return {name: len(values) for name, values in sorted(versions.items())}


def inventory(root):
    expected = read_json(root / 'reports/stage4/event_source_availability.json')['raw_sources']
    sources, copies, headers = [], [], {}
    for entry in expected:
        desc = descriptor(root, entry['path'])
        if any(desc[k] != entry[k] for k in ('sha256', 'bytes')):
            raise ValueError('Raw source differs from accepted historical version')
        sources.append(desc)
        path = root / entry['path']
        with path.open(encoding='utf-8-sig', newline='') as stream:
            headers[path.name] = next(csv.reader(stream))
        copies.append({'container': 'data/raw/olist', 'table': path.name, 'sha256': desc['sha256']})
    names = set(headers)
    scope = []
    containers = []
    for rel in SEARCH:
        path = root / rel
        files = sorted(p for p in path.rglob('*') if p.is_file()) if path.exists() else []
        scope.append({'path': rel, 'exists': path.exists(),
                      'csv_count': sum(p.suffix.lower() == '.csv' for p in files),
                      'zip_count': sum(p.suffix.lower() == '.zip' for p in files)})
        for path in files:
            if path.name in names and path.parent != root / 'data/raw/olist':
                desc = descriptor(root, path.relative_to(root).as_posix())
                sources.append(desc)
                copies.append({'container': path.parent.relative_to(root).as_posix(),
                               'table': path.name, 'sha256': desc['sha256']})
            if path.suffix.lower() != '.zip':
                continue
            # Inspect only member names in unrelated archives (e.g. MySQL tools).
            with zipfile.ZipFile(path) as archive:
                members = [m for m in archive.infolist() if Path(m.filename).name in names]
                if not members:
                    continue
                relzip = path.relative_to(root).as_posix()
                sources.append(descriptor(root, relzip))
                for member in members:
                    with archive.open(member) as stream:
                        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                    copies.append({'container': relzip, 'table': Path(member.filename).name, 'sha256': sha})
                containers.append({'path': relzip, 'raw_table_members': len(members)})
    sources.extend(descriptor(root, p) for p in (*PUBLIC, *META))
    # Existing G3's 69 bound source files are byte checked, not re-executed.
    g3spec = read_json(root / 'reports/stage6/rfm_g3_v2_specification.json')
    for entry in g3spec['sources']:
        if descriptor(root, entry['path']) != entry:
            raise ValueError('Prior G3 source binding changed')
    data = root / 'data/raw/olist'
    orders = projected(data / 'olist_orders_dataset.csv', ('order_id', 'customer_id', 'order_status', *CLOCKS))
    customers = projected(data / 'olist_customers_dataset.csv', ('customer_id', 'customer_unique_id'))
    items = projected(data / 'olist_order_items_dataset.csv', ('order_id', 'order_item_id'))
    payments = projected(data / 'olist_order_payments_dataset.csv', ('order_id', 'payment_sequential'))
    order_ids = [r['order_id'] for r in orders]
    customer_ids = [r['customer_id'] for r in customers]
    if any(not v for v in order_ids + customer_ids) or len(set(order_ids)) != len(order_ids) or len(set(customer_ids)) != len(customer_ids):
        raise ValueError('Missing/duplicate order or customer primary key')
    if any(clock(r[CLOCKS[0]]) is None for r in orders):
        raise ValueError('Unlocatable purchase')
    if any(not r['customer_unique_id'] for r in customers):
        raise ValueError('Missing anonymous customer key')
    order_set, customer_set = set(order_ids), set(customer_ids)
    if any(r['customer_id'] not in customer_set for r in orders):
        raise ValueError('Unmapped order customer')
    joins = {}
    for label, detail, second_key in [('items', items, 'order_item_id'), ('payments', payments, 'payment_sequential')]:
        keys = [(r['order_id'], r[second_key]) for r in detail]
        ids = {r['order_id'] for r in detail}
        joins[label] = {'rows': len(detail), 'orders_missing_detail': len(order_set - ids),
                        'orphan_order_keys': len(ids - order_set),
                        'duplicate_composite_keys': len(keys) - len(set(keys))}
    clocks = {}
    for field in CLOCKS:
        vals = [clock(r[field]) for r in orders]
        valid = [v for v in vals if v is not None]
        clocks[field] = {'minimum': min(valid).isoformat() if valid else None,
                         'maximum': max(valid).isoformat() if valid else None,
                         'missing': sum(r[field] == '' for r in orders),
                         'invalid_nonblank': sum(bool(r[field]) and clock(r[field]) is None for r in orders)}
    month = Counter(clock(r[CLOCKS[0]]).strftime('%Y-%m') for r in orders)
    delivery_month = Counter(clock(r[CLOCKS[2]]).strftime('%Y-%m') for r in orders if clock(r[CLOCKS[2]]) is not None)
    months = sorted(set(month) | set(delivery_month))
    post = [r for r in orders if clock(r[CLOCKS[0]]) >= BASELINE]
    post_ids = {r['customer_id'] for r in post}
    post_customers = {r['customer_unique_id'] for r in customers if r['customer_id'] in post_ids}
    before_ids = {r['customer_id'] for r in orders if clock(r[CLOCKS[0]]) < BASELINE}
    before_customers = {r['customer_unique_id'] for r in customers if r['customer_id'] in before_ids}
    source_version_counts = distinct_versions(copies)
    if any(n != 1 for n in source_version_counts.values()):
        raise ValueError('A different raw version was found; inspect before drawing availability conclusions')
    # Check that no source was replaced while reading; metadata paths are private.
    for desc in sources:
        if descriptor(root, desc['path']) != desc:
            raise ValueError('Source changed during inventory')
    return {'format_version': 1, 'status': 'inventory_complete_temporal_validation_pending_data',
            'scope': {'baseline_cutoff': BASELINE.isoformat(), 'probes_not_selected_validation_cutoffs': [p.isoformat() for p in PROBES],
                      'search': scope, 'scope_limit': 'Selected project data/download/backup/handoff paths only; no external drive, cloud, live web or live DB audit.',
                      'raw_read_policy': 'All nine file hashes/headers; orders clocks/status/keys, customer keys, item/payment keys only. No review values or monetary values used.',
                      'audit_role': 'Availability inspection after prior research exposure, not a preregistered model experiment.'},
            'sources': [s for s in sources if s['path'] in PUBLIC or s['path'].startswith('data/raw/')],
            'local_evidence': {'source_manifest_version': read_json(root / META[0])['dataset_version'],
                               'local_import_receipt_available_not_live_DB_recheck': (root / META[1]).exists(),
                               'raw_copies': copies, 'archives': containers,
                               'distinct_versions_by_raw_table': source_version_counts,
                               'accepted_additional_as_of_snapshots': 0,
                               'as_of_evidence': 'No accepted historical ingestion/revision/completion bundle in inspected paths; a packaging/import date is not an original observation cutoff.'},
            'tables': {'orders': len(orders), 'customers': len(customers),
                       'anonymous_customer_keys': len({r['customer_unique_id'] for r in customers}),
                       'headers': headers, 'detail_key_quality': joins},
            'clocks': clocks,
            'monthly_event_counts': [{'month': m, 'purchase_rows': month[m], 'delivery_clock_rows': delivery_month[m],
                                      'upstream_complete': None} for m in months],
            'after_baseline': {'purchase_rows': len(post), 'anonymous_customer_keys': len(post_customers),
                               'keys_also_in_before_cutoff_purchase_rows': len(post_customers & before_customers),
                               'final_snapshot_status_counts': dict(sorted(Counter(r['order_status'] for r in post).items()))},
            'future_coverage_probes': [coverage(orders, BASELINE, p) for p in PROBES],
            'verification': {'prior_G3_bound_sources_byte_matched': len(g3spec['sources']),
                             'source_descriptors_rechecked_after_read': True,
                             'monthly_purchase_rows_reconciled': sum(month.values()) == len(orders),
                             'new_RFM_snapshots_built': 0, 'new_cutpoints_or_scores': 0,
                             'model_fits': 0, 'holdout_evaluations': 0},
            'limitations': ['Same final export can support retrospective event-proxy exploration only, not historical as-of knowledge or a new holdout.',
                            'Event maxima do not establish a completion watermark; absent events are not evidence of zero business activity.',
                            'Missing approval is nonblocking only under the original event-proxy rule; it is not an availability clock.',
                            'No amounts, refunds, settlement, entity-resolution revisions or business outcomes accepted this round.',
                            'The prior 25 small groups / 1791 customers retain insufficient-support status; no temporal group-size result was computed.',
                            'G3 agreement and ARI thresholds are same-snapshot sampling gates, not cross-time acceptance thresholds.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='recompute inventory and compare without writing')
    args = parser.parse_args()
    result = inventory(ROOT)
    target = ROOT / REPORT
    payload = encoded(result)
    if args.verify or target.exists():
        if target.read_bytes() != payload:
            raise ValueError('Saved inventory differs; preserve it and use a new revision for new evidence')
    else:
        with target.open('xb') as stream:
            stream.write(payload)
    print(json.dumps({'status': result['status'], 'report': REPORT,
                      'post_baseline': result['after_baseline'],
                      'probes': result['future_coverage_probes']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
