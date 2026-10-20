"""Audit bounded event-source evidence without fitting or replaying any model.

The specification freezes this round's source snapshot and future acceptance
contract. It is not a model preregistration written before source inspection.
Private evidence is read as already executed; no database or API is contacted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = pd.Timestamp('2018-05-01')
ANALYSIS = 'bounded_cancellation_closure_promise_version_source_availability'
CODE = 'scripts/audit_event_source_availability.py'
SPECIFICATION = ROOT / 'reports/stage4/event_source_availability_specification.json'
OUTPUT = ROOT / 'reports/stage4/event_source_availability.json'
PRIOR = 'reports/stage4/completed_history_representativeness_audit.json'
EVIDENCE = {
    'review': '.runtime/event_source_independent_review.json',
    'inventory': '.runtime/event_sources_independent_inventory.json',
    'json_metadata': '.runtime/event_sources_independent_json_metadata.json',
    'database': '.runtime/event_source_database_probe.json',
    'public': '.runtime/event_source_public/public_source_findings.json',
}
RAW_NAMES = (
    'olist_customers_dataset.csv', 'olist_geolocation_dataset.csv',
    'olist_order_items_dataset.csv', 'olist_order_payments_dataset.csv',
    'olist_order_reviews_dataset.csv', 'olist_orders_dataset.csv',
    'olist_products_dataset.csv', 'olist_sellers_dataset.csv',
    'product_category_name_translation.csv',
)
ORDER_COLUMNS = (
    'order_id', 'customer_id', 'order_status', 'order_purchase_timestamp',
    'order_approved_at', 'order_delivered_carrier_date',
    'order_delivered_customer_date', 'order_estimated_delivery_date',
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path):
    def invalid_constant(value):
        raise ValueError(f'Non-finite JSON constant: {value}')
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=_unique_pairs, parse_constant=invalid_constant)


def immutable_json(path, value):
    """Preserve existing bytes; accept only a semantically identical rerun."""
    path = Path(path)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False) + '\n'
    if path.exists():
        if read_json(path) != value:
            raise ValueError(f'Refusing to overwrite different JSON: {path.name}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(encoded)


def descriptor(path, root=ROOT):
    path = Path(path)
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
            'sha256': sha256(path)}


def acceptance_contract():
    return {
        'decision_rule': 'No accepted additional as-of event/version source means pending_data_no_training. Absence within inspected sources is not global non-existence.',
        'query_clock': 't is the current query approval time, not each historical order own approval. Cancellation may follow historical approval and still precede t.',
        'event_rule': 'Require stable order identity, event type/semantics, occurred_at<t AND observed_at<t. Closure here means cancellation or another non-delivery transition that exits the risk set; existing delivery completion timestamps remain a different known event. Source received time and project persisted/ingested time must be distinguished and independently explained.',
        'promise_rule': 'Require promised value, version identity, effective/valid time, observed/system time, supersession/correction/retraction history. Select only observed_at<t versions effective_at<=t and valid under what was known at t.',
        'boundaries': 'Verify timezone, daylight-saving conversions, clock precision and same-t ties. Events equal to t are not known; promise effective_at=t may apply only when observed_at<t.',
        'ordering': 'Report missing/invalid timestamps, duplicates/conflicts, event order, observed-before-occurred anomalies, late-arrival/backfill delays and immutable revision policy. A promise may be observed before its future effective time.',
        'joins': 'Verify same anonymized order_id or an authorized mapping, key uniqueness, one-to-many version cardinality, orphan events, conflicting versions and overlapping validity intervals. Seller-only linkage is insufficient.',
        'scope': 'Verify each query month and required historical lookback, including route/promise/approval-week/support coverage. Do not import future events or rescore original holdout.',
        'coverage': 'Separate raw valid approval denominator, joined orders, known true-event register, timestamp-valid events, and as-of covered query/history windows. Missing true-event or revision denominator means actual capture rate unknown, not 0%.',
        'snapshot_alternative': 'Immutable complete snapshots require captured_at, available_at<t, cadence and completeness proof. They can establish known status as of a snapshot under a separately accepted contract, not exact cancellation occurrence time.',
        'prohibited_substitutes': ['Final exported status or final single promise value',
            'CSV mtime or later local database import/binlog time as original observed_at',
            'Review dates or shipping deadlines as cancellation/promise revisions',
            'A seller marketing closed-deal as an order closure',
            'API indexed examples as acquired authorized historical same-ID data'],
        'protected_experiment': {'daily_alert_fraction': 0.1, 'seeds': [11, 29, 42, 73, 101],
            'four_frozen_models_unchanged': True, 'new_fit': 0, 'new_replay': 0,
            'new_selection': 0, 'original_holdout_scored': False},
    }


def make_specification(root=ROOT):
    root = Path(root)
    names = [f'data/raw/olist/{name}' for name in RAW_NAMES] + [PRIOR, *EVIDENCE.values()]
    return {'format_version': 1, 'analysis': ANALYSIS,
        'specification_role': 'This round source snapshot and future acceptance contract; source inspection already performed. Not a model preregistration.',
        'cutoff_exclusive': CUTOFF.isoformat(), 'contract': acceptance_contract(),
        'protected_sources': [descriptor(root / name, root) for name in names],
        'analysis_code': [descriptor(root / CODE, root)],
        'excluded_live_inputs': 'Live database/binlog files are not bound or reopened. Already executed read-only probe and old-binlog aggregates are bound as private evidence JSON.'}


def verify_sources(specification, root=ROOT):
    if specification['analysis'] != ANALYSIS or specification['contract'] != acceptance_contract():
        raise ValueError('Analysis or acceptance contract changed; re-accept source snapshot')
    entries = specification['protected_sources'] + specification['analysis_code']
    for item in entries:
        if descriptor(Path(root) / item['path'], Path(root)) != item:
            raise ValueError(f'Changed protected source: {item["path"]}')
    return len(entries)


def _naive_dates(values):
    parsed = pd.to_datetime(values, errors='coerce', format='mixed')
    if not pd.api.types.is_datetime64_any_dtype(parsed.dtype) or parsed.dt.tz is not None:
        raise ValueError('Require existing timezone-naive Olist clocks; new timezone semantics need acceptance')
    return parsed


def orders_profile(orders):
    """Only ID metadata uses all rows; status and promise profiles use pre-cutoff approvals."""
    if tuple(orders.columns) != ORDER_COLUMNS:
        raise ValueError('Orders schema changed; require exact original eight columns and source re-acceptance')
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError('Orders join keys must be unique and non-null')
    approval = _naive_dates(orders.order_approved_at)
    purchase = _naive_dates(orders.order_purchase_timestamp)
    before = approval.notna() & approval.lt(CUTOFF)
    missing_purchase = before & purchase.isna()
    reversed_clock = before & purchase.notna() & purchase.gt(approval)
    eligible = before & ~missing_purchase & ~reversed_clock
    frame = orders.loc[eligible].copy()
    dates = {name: _naive_dates(frame[name]) for name in ORDER_COLUMNS[3:]}
    ap = dates['order_approved_at']
    promise = dates['order_estimated_delivery_date']

    def summarize(indexes):
        selected = frame.loc[indexes]
        prom = promise.loc[indexes]
        appr = ap.loc[indexes]
        return {'eligible_orders': len(selected), 'promise_present': int(prom.notna().sum()),
            'promise_missing_or_invalid': int(prom.isna().sum()),
            'negative_promise_days': int(prom.lt(appr.dt.normalize()).sum()),
            'final_canceled': int(selected.order_status.eq('canceled').sum()),
            'final_unavailable': int(selected.order_status.eq('unavailable').sum())}

    monthly = {str(month): summarize(indexes) for month, indexes in
               ap.groupby(ap.dt.strftime('%Y-%m')).groups.items()}
    statuses = {str(key): int(value) for key, value in frame.order_status.value_counts(dropna=False).items()}
    return {
        'whole_orders_join_metadata': {'rows': len(orders), 'unique_order_ids': int(orders.order_id.nunique()),
            'missing_order_ids': 0, 'duplicated_order_ids': 0},
        'approval_population': {'approval_before_cutoff': int(before.sum()),
            'missing_purchase_before_cutoff': int(missing_purchase.sum()),
            'reversed_purchase_approval_before_cutoff': int(reversed_clock.sum()),
            'eligible_orders': len(frame),
            'earliest_approval': None if frame.empty else ap.min().isoformat(),
            'latest_approval': None if frame.empty else ap.max().isoformat(),
            'promise_present': int(promise.notna().sum()),
            'promise_missing': int(promise.isna().sum()),
            'negative_promise_days': int(promise.lt(ap.dt.normalize()).sum()),
            'promise_without_non_midnight_time': int(promise.eq(promise.dt.normalize()).sum()),
            'carrier_event_before_cutoff': int(dates['order_delivered_carrier_date'].lt(CUTOFF).sum()),
            'delivery_event_before_cutoff': int(dates['order_delivered_customer_date'].lt(CUTOFF).sum()),
            'delivery_before_approval': int(dates['order_delivered_customer_date'].lt(ap).sum()),
            'final_status_counts': statuses,
            'final_canceled_or_unavailable': int(frame.order_status.isin(['canceled', 'unavailable']).sum())},
        'eligible_timestamp_parse_failures': {name: int((frame[name].notna() & parsed.isna()).sum())
                                             for name, parsed in dates.items()},
        'by_approval_month': monthly,
        'availability': {
            'schema_verifiable_cancellation_or_non_delivery_closure_clock_columns': [],
            'schema_verifiable_observed_clock_columns': [],
            'schema_verifiable_promise_version_columns': [],
            'existing_delivery_completion_column': 'order_delivered_customer_date',
            'existing_delivery_completion_ingestion_clock_available': False,
            'orders_with_provable_cancellation_known_before_query_t': 0,
            'orders_with_provable_non_delivery_closure_known_before_query_t': 0,
            'orders_with_verifiable_promise_version_as_of_query_t': 0,
            'actual_cancellation_event_capture_rate': None,
            'actual_non_delivery_closure_event_capture_rate': None,
            'actual_promise_revision_capture_rate': None,
            'meaning': 'Zero verifiable new cancellation/non-delivery-exit clocks or promise versions, not zero actual events. Existing delivery completion timestamps are present but lack ingestion times. A non-null single exported promise is not proof of its approval-time version.'},
        'scope': 'Final statuses are retrospective descriptors only, never an as-of event or feature. No final status filter. Invalid approval timestamps cannot enter a pre-cutoff cohort; no outcome/performance aggregates after cutoff.',
    }


def _check_independent_profile(profile, independent):
    for section in ('whole_orders_join_metadata', 'approval_population'):
        if profile[section] != independent[section]:
            raise ValueError(f'Independent raw review disagrees: {section}')
    for month, actual in profile['by_approval_month'].items():
        expected = independent['by_approval_month'][month]
        for key in ('eligible_orders', 'promise_present', 'negative_promise_days', 'final_canceled', 'final_unavailable'):
            if actual[key] != expected[key]:
                raise ValueError(f'Independent raw review disagrees: {month}/{key}')
    if set(profile['by_approval_month']) != set(independent['by_approval_month']):
        raise ValueError('Independent raw review month range differs')


def sanitized_inventory(inventory, metadata, raw_tables):
    known = {item['path'].split('/')[-1]: item for item in raw_tables}
    for item in inventory['raw_olist_tables']:
        actual = known[item['path'].split('/')[-1]]
        if (item['columns'], item['row_count'], item['sha256']) != (actual['columns'], actual['rows'], actual['sha256']):
            raise ValueError('Independent raw inventory disagrees')
    members = []
    for member in inventory['olist_zip_members']:
        original = known[member['name']]
        if member['sha256'] != original['sha256'] or member['bytes'] != original['bytes']:
            raise ValueError('Archive member is not the same raw source')
        members.append({key: member[key] for key in ('name', 'bytes', 'sha256')})
    if set(known) != {member['name'] for member in members}:
        raise ValueError('Archive/raw source membership differs')
    candidates = inventory['data_like_candidates']
    count = lambda prefix, suffix: sum(item['path'].startswith(prefix) and item['path'].endswith(suffix) for item in candidates)
    binlog_keys = ('bytes', 'sha256', 'event_count', 'event_type_counts', 'zero_timestamp_event_count',
                   'event_timestamp_min_utc', 'event_timestamp_max_utc', 'table_map_event_counts', 'row_event_counts')
    return {'files_inspected_at_inventory_snapshot': inventory['safe_walk_files'],
        'csv_files': inventory['extensions']['.csv'], 'zip_files': inventory['extensions']['.zip'],
        'processed_csv': count('data/processed/', '.csv'), 'runtime_csv': count('.runtime/', '.csv'),
        'permission_denied_directory_count': len(inventory['permission_denied_directories']),
        'explicitly_skipped_root_count': len(inventory['explicit_skipped_roots']),
        'permission_scope': 'Denied and explicitly skipped directories were not read; do not count them as source coverage. No inaccessible path names are published.',
        'raw_retailrocket_file_count': inventory['raw_retailrocket_file_count'],
        'sample_file_count': inventory['sample_file_count'],
        'olist_zip_sha256': inventory['olist_zip_sha256'], 'olist_zip_members_exactly_match_raw': members,
        'prior_binlog_header_snapshots': [dict(snapshot_number=n, **{key: item[key] for key in binlog_keys})
            for n, item in enumerate(inventory['binlogs'], 1)],
        'binlog_interpretation': 'Only prior file/header evidence is bound, not live files. These 2026 local import events are not 2016-2018 original order observed_at; table row-event counts are not source-event or order counts. No SQL or row payload is published.',
        'json_metadata_inventory': {'existing_json_count': metadata['existing_json_count'],
            'existing_json_bytes': metadata['existing_json_bytes'],
            'potential_event_source_key_matches': sum(bool(item['potential_event_source_keys']) for item in metadata['entries']),
            'meaning': 'Top-level key screening is a bounded metadata check, not proof that every value has been exhaustively excluded as event evidence.',
            'safe_connection_count': len(metadata['dbeaver_safe_connections'])}}


def sanitized_database(database, raw_tables):
    if database['status'] != 'ok' or database['errors']:
        raise ValueError('Require completed successful read-only database probe evidence')
    comparison = database['orders_snapshot_comparison']
    raw_orders = next(item for item in raw_tables if item['path'].endswith('/olist_orders_dataset.csv'))
    if not comparison['all_values_equal'] or comparison['raw_sha256'] != raw_orders['sha256']:
        raise ValueError('Database orders snapshot does not match raw orders')
    if comparison['values_compared'] != comparison['rows'] * comparison['columns']:
        raise ValueError('Database cell comparison denominator differs')
    tables = [{'name': item['name'], 'kind': item['kind'], 'rows': item['rows'],
               'columns': [column['name'] for column in item['columns']]} for item in database['tables']]
    expected = {item['path'].split('/')[-1].removeprefix('olist_').removesuffix('.csv').removesuffix('_dataset'):
                (item['rows'], item['columns']) for item in raw_tables}
    actual = {item['name']: (item['rows'], item['columns']) for item in tables}
    if len(tables) != len(actual) or actual != expected:
        raise ValueError('Database table schema or row counts differ from the raw snapshot')
    return {'probe_status': 'ok', 'table_count': len(tables), 'tables': tables,
        'metadata_visible_counts': {key: item['visible_count'] for key, item in database['metadata_checks'].items()},
        'orders_snapshot_comparison': comparison,
        'interpretation': 'Configured project database visible metadata only; orders is the identical final eight-column CSV snapshot. Zero visible metadata objects does not prove inaccessible schemas/accounts have no data. Local creation/import timestamps are not original source observation times.',
        'service_or_network_restarted_by_this_script': False}


def sanitized_public(public):
    if public['new_accepted_event_sources'] != 0 or public['decision'] != 'pending_data_no_training':
        raise ValueError('New public source requires an updated acceptance audit')
    return {key: value for key, value in public.items() if key != 'public_sources'} | {
        'public_sources': [{key: value for key, value in item.items() if key != 'artifacts'}
                           for item in public['public_sources']]}


def build_report(specification, root=ROOT, specification_path=SPECIFICATION):
    root = Path(root)
    checked = verify_sources(specification, root)
    evidence = {key: read_json(root / value) for key, value in EVIDENCE.items()}
    prior = read_json(root / PRIOR)
    if prior['status'] != 'ok':
        raise ValueError('Require completed preceding representation audit')
    raw_tables = []
    orders = None
    for name in RAW_NAMES:
        path = root / 'data/raw/olist' / name
        frame = pd.read_csv(path)
        raw_tables.append(dict(descriptor(path, root), rows=len(frame), columns=list(frame.columns)))
        if name == 'olist_orders_dataset.csv':
            orders = frame
    profile = orders_profile(orders)
    _check_independent_profile(profile, evidence['review'])
    report = {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'specification': descriptor(Path(specification_path), root),
        'source_snapshot_role': specification['specification_role'],
        'cutoff_exclusive': CUTOFF.isoformat(), 'contract': acceptance_contract(),
        'raw_sources': raw_tables, 'orders': profile,
        'local_inventory': sanitized_inventory(evidence['inventory'], evidence['json_metadata'], raw_tables),
        'database': sanitized_database(evidence['database'], raw_tables),
        'official_public_sources': sanitized_public(evidence['public']),
        'decision': 'pending_data_no_training',
        'verification': {'protected_source_and_code_hashes_checked_before_and_after': checked,
            'independent_raw_review_matched': True, 'raw_tables_read': len(raw_tables),
            'new_fit': 0, 'new_model_deserialization': 0, 'new_score_replay': 0,
            'new_model_selection': 0, 'new_alerts': 0, 'original_holdout_scored': False},
        'limitations': ['Bounded inspected local/public sources only; no global non-existence claim.',
            'No actual original ingestion, cancellation/closure or promise revision source was accepted; actual capture rates remain unknown.',
            'Private evidence JSON represents this executed inventory snapshot; live services/files are not queried or refreshed on rerun.',
            'No training or new prediction experiment; existing historical validation/development recall and untouched holdout status are unchanged.']}
    verify_sources(specification, root)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    args = parser.parse_args()
    specification = make_specification()
    immutable_json(SPECIFICATION, specification)
    if args.specification_only:
        print(json.dumps({'status': 'ok', 'specification': descriptor(SPECIFICATION)}, ensure_ascii=False))
        return
    report = build_report(read_json(SPECIFICATION))
    immutable_json(OUTPUT, report)
    print(json.dumps({'status': 'ok', 'decision': report['decision'], 'output': descriptor(OUTPUT),
                      'verification': report['verification']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
