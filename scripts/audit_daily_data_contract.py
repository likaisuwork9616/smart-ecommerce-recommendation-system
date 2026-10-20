"""Audit a frozen exported day roster; never infer production completeness."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'reports/stage4/daily_data_contract.json'
EVENT = 'reports/stage4/event_source_availability.json'
EVENT_SPEC = 'reports/stage4/event_source_availability_specification.json'
DAILY = 'reports/stage4/daily_delivery_acceptance.json'
DAILY_SPEC = 'reports/stage4/daily_delivery_acceptance_specification.json'
RAW = 'data/raw/olist/olist_orders_dataset.csv'
LEDGER = 'data/processed/olist_delay_age_colsample_scores.csv'
LOADER = 'scripts/load_olist_to_mysql.py'
CODE = 'scripts/audit_daily_data_contract.py'
PINNED_EVENT = 'fc5fdf4018a8b3d3202d8b7efb325904f215de78e4fe4871e48fe3e79ca29ee8'
PINNED_DAILY = '1a3fb55baf6688086d20f4e3ad9ccfd4f2b30a60ac253da23a447ccfb809afca'
ROSTER_COLUMNS = ['order_id', 'prediction_time', 'fold', 'model_version', 'role',
                  'candidate', 'seed', 'colsample_bytree']


def descriptor(path, root=ROOT):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Source must be an existing file inside the project')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest()}


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON constant')
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=invalid)


def verify_sources(items, root=ROOT):
    if len({item['path'] for item in items}) != len(items):
        raise ValueError('Duplicate source path')
    for item in items:
        if descriptor(Path(root) / item['path'], root) != {
                key: item[key] for key in ('path', 'bytes', 'sha256')}:
            raise ValueError('Bound source bytes changed: ' + item['path'])
    return len(items)


def immutable_write(path, payload):
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')
    path = Path(path)
    if path.exists() and path.read_bytes() != data:
        raise ValueError('Refusing to overwrite a different audit report')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)


def day_roster(raw, day):
    if raw['order_id'].isna().any() or raw['order_id'].duplicated().any():
        raise ValueError('Raw order IDs must be present and unique')
    parsed = {}
    quality = {}
    for name in ('order_purchase_timestamp', 'order_approved_at'):
        values = raw[name]
        parsed[name] = pd.to_datetime(values, format='%Y-%m-%d %H:%M:%S', errors='coerce')
        quality[name] = {'missing': int(values.isna().sum()),
                         'invalid_nonmissing': int((values.notna() & parsed[name].isna()).sum())}
    approval = parsed['order_approved_at']
    purchase = parsed['order_purchase_timestamp']
    quality['approval_before_purchase'] = int((approval < purchase).sum())
    quality['parseable_approval_before_2018_05_01'] = int((approval < pd.Timestamp('2018-05-01')).sum())
    start = pd.Timestamp(day)
    selected = raw.loc[(approval >= start) & (approval < start + pd.Timedelta(days=1))].copy()
    selected['prediction_time'] = approval.loc[selected.index]
    if selected.empty:
        raise ValueError('The previously selected day has no raw approvals')
    return selected, quality


def verify_roster_runs(roster, ledger, schema, selected):
    expected_ids = set(roster['order_id'])
    target = ledger.loc[(ledger['fold'] == '2018-02') &
                        (ledger['model_version'] == '2018-02') &
                        (ledger['role'] == 'evaluation')].copy()
    target['prediction_time'] = pd.to_datetime(target['prediction_time'],
                                               format='%Y-%m-%d %H:%M:%S', errors='raise')
    day = pd.Timestamp(selected['day'])
    target = target.loc[(target['prediction_time'] >= day) &
                        (target['prediction_time'] < day + pd.Timedelta(days=1))]
    expected_groups, runs = set(), []
    reference = None
    for version in schema['versions']:
        metadata = schema['version_source'][version]
        for seed in schema['seeds']:
            key = (metadata['candidate'], seed, metadata['colsample_bytree'])
            expected_groups.add(key)
            frame = target.loc[(target['candidate'] == key[0]) & (target['seed'] == key[1]) &
                               (target['colsample_bytree'] == key[2])]
            if frame['order_id'].isna().any() or frame['order_id'].duplicated().any():
                raise ValueError('Each frozen run needs unique nonmissing order IDs')
            actual_ids = set(frame['order_id'])
            if not actual_ids.issubset(expected_ids) or len(frame) != selected['full_day_rows']:
                raise ValueError('Frozen run differs from the accepted research day roster')
            current = frame.set_index('order_id')['prediction_time'].sort_index()
            source = roster.set_index('order_id').loc[current.index, 'prediction_time']
            if not current.equals(source):
                raise ValueError('Frozen approval times differ from the raw export')
            if reference is not None and actual_ids != reference:
                raise ValueError('Research rosters differ between frozen runs')
            reference = actual_ids
            runs.append({'version': version, 'seed': seed, 'research_rows': len(frame),
                         'raw_export_day_rows': len(roster),
                         'raw_export_rows_without_frozen_score': len(expected_ids - actual_ids)})
    actual_groups = set(target[['candidate', 'seed', 'colsample_bytree']].itertuples(index=False, name=None))
    if actual_groups != expected_groups or len(target) != len(runs) * selected['full_day_rows']:
        raise ValueError('Unexpected or missing frozen run metadata')
    missing = roster.loc[~roster['order_id'].isin(reference)]
    return runs, missing


def audit(root=ROOT):
    root = Path(root)
    if descriptor(root / EVENT, root)['sha256'] != PINNED_EVENT:
        raise ValueError('Previously inspected source audit changed')
    if descriptor(root / DAILY, root)['sha256'] != PINNED_DAILY:
        raise ValueError('Previously accepted frozen day report changed')
    event, event_spec = read_json(root / EVENT), read_json(root / EVENT_SPEC)
    daily, daily_spec = read_json(root / DAILY), read_json(root / DAILY_SPEC)
    if event['decision'] != 'pending_data_no_training' or daily['status'] != 'ok':
        raise ValueError('Unexpected prior audit decision')
    verify_sources([event['specification'], daily['specification']], root)
    if daily['selected_day'] != daily_spec['selected_day'] or daily['selected_day']['day'] != '2018-02-01':
        raise ValueError('Previously accepted day metadata changed')
    selected = daily['selected_day']
    raw_sources = event['raw_sources']
    expected_raw = {item['path'] for item in raw_sources}
    if len(expected_raw) != 9 or {p.relative_to(root).as_posix() for p in
                                 (root / 'data/raw/olist').glob('*.csv')} != expected_raw:
        raise ValueError('Raw CSV file set changed')
    sources = [{key: item[key] for key in ('path', 'bytes', 'sha256')} for item in raw_sources]
    ledger_source = next(item for item in daily_spec['sources'] if item['path'] == LEDGER)
    sources += [ledger_source] + [descriptor(root / path, root) for path in
                                  (EVENT, EVENT_SPEC, DAILY, DAILY_SPEC, LOADER, CODE)]
    verify_sources(sources, root)
    protected = {item['path']: item for item in event_spec['protected_sources']}
    if any(protected[item['path']] != item for item in sources if item['path'] in expected_raw):
        raise ValueError('Raw source manifests disagree')
    schemas = []
    for expected in raw_sources:
        with (root / expected['path']).open(encoding='utf-8-sig', newline='') as stream:
            rows = csv.reader(stream)
            columns, count = next(rows), sum(1 for _ in rows)
        if columns != expected['columns'] or count != expected['rows']:
            raise ValueError('Raw schema or row count changed')
        schemas.append({'path': expected['path'], 'columns': columns, 'rows': count,
                        'matches_prior_source_audit': True})
    raw = pd.read_csv(root / RAW, dtype=str)
    roster, quality = day_roster(raw, selected['day'])
    if len(roster) != selected['raw_day_approval_rows']:
        raise ValueError('Raw day denominator differs from prior acceptance')
    day_parts, total = [], 0
    for chunk in pd.read_csv(root / LEDGER, usecols=ROSTER_COLUMNS, chunksize=100000):
        total += len(chunk)
        day_parts.append(chunk.loc[chunk['prediction_time'].str.startswith(selected['day'])])
    if total != daily['verification']['ledger_total_rows_verified']:
        raise ValueError('Frozen ledger row count differs')
    runs, missing = verify_roster_runs(roster, pd.concat(day_parts, ignore_index=True),
                                      daily_spec['schema'], selected)
    if len(missing) != 3 or set(missing['order_status']) != {'canceled'}:
        raise ValueError('Raw versus research gap differs from prior acceptance')
    loader = (root / LOADER).read_text(encoding='utf-8')
    if 'pd.read_csv(file)' not in loader or 'if_exists="replace"' not in loader:
        raise ValueError('Reviewed loader behavior changed')
    database = event['database']
    if not database['orders_snapshot_comparison']['all_values_equal']:
        raise ValueError('Prior database evidence no longer describes the raw snapshot')
    verify_sources(sources, root)
    return {
        'format_version': 1, 'analysis': 'bounded_full_day_roster_ingestion_version_day_close_contract',
        'status': 'ok', 'decision': 'pending_data_no_training_no_production_acceptance',
        'scope': 'Current bounded raw schema and frozen ledger metadata review; prior DB/binlog/public evidence reused, not refreshed.',
        'contract_role': 'Proposed future minimum requirements in docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract; not confirmed business policy or an implemented live batch validator.',
        'choices_unconfirmed': ['business_timezone', 'ingestion_and_close_SLA',
                                'late_arrival_policy', 'reapproval_policy', 'day_reopen_policy'],
        'source_manifest': sources, 'raw_schemas': schemas,
        'raw_order_quality': quality,
        'clock': {'day': selected['day'], 'interval': '[2018-02-01 00:00:00,2018-02-02 00:00:00)',
                  'timestamp_representation': 'naive exported wall-clock; no timezone conversion',
                  'business_timezone_verified': False, 'historical_ingested_at_verified': False,
                  'file_hash_is_operational_version_or_asof_proof': False},
        'roster': {'raw_export_rows': len(raw), 'raw_export_day_rows': len(roster),
                   'accepted_research_day_rows': selected['full_day_rows'],
                   'raw_export_day_rows_without_frozen_scores_per_run': len(missing),
                   'excluded_final_canceled_rows_retrospective_only': len(missing),
                   'missing_approval_rows_assigned_to_any_day': False,
                   'purchase_date_used_to_impute_approval_day': False,
                   'runs': runs, 'coverage_scope': 'Export snapshot only; no original source-day reconciliation or closure proof.'},
        'contract_dimensions': {
            name: {'status': 'pending_data', 'production_gate_passed': False, 'reason': reason}
            for name, reason in {
                'full_daily_roster': 'Exported approvals lack upstream population scope and reconciliation; 242 research rows omit 3 of 245 exported day approvals.',
                'ingestion_asof_clock': 'No original available/ingested clock or verified business timezone in the inspected raw schemas.',
                'historical_source_and_promise_versions': 'Static exported values and artifact hashes lack effective-time and recorded-time version history.',
                'day_close_completion': 'No upstream scope/cursor, source watermark, close manifest or reconciliation proof.'}.items()},
        'existing_evidence': {'database_probe_reused': True, 'database_tables': database['table_count'],
                              'orders_snapshot_comparison': database['orders_snapshot_comparison'],
                              'loader': 'Reads exported CSV and replaces tables; no operational ingestion/version/day-close contract.',
                              'prior_binlog_snapshots': len(event['local_inventory']['prior_binlog_header_snapshots']),
                              'binlog_limit': 'Prior 2026 local import headers are not 2018 source observation times.',
                              'event_signal_status': 'pending_data',
                              'actual_event_capture_rates': 'not_identifiable_from_inspected_sources'},
        'fixed_research_policy': {'daily_fraction': 0.1, 'seeds': daily_spec['schema']['seeds'],
                                  'versions': daily_spec['schema']['versions'],
                                  'previous_research_daily_capacity': selected['daily_capacity'],
                                  'raw_245_capacity_not_accepted': True,
                                  'floor_245_div_10_equals_24_is_not_full_day_acceptance': True,
                                  'new_capacity_or_rank_or_alerts_computed': False},
        'verification': {'bound_files_checked_before_and_after': len(sources),
                         'raw_schemas_and_counts_verified': len(schemas), 'ledger_rows_counted': total,
                         'ledger_columns_parsed': ROSTER_COLUMNS, 'frozen_research_runs_verified': len(runs),
                         'frozen_research_roster_rows_verified': sum(run['research_rows'] for run in runs),
                         'ledger_score_outcome_alert_columns_parsed': 0, 'model_load_fit_predict_count': 0,
                         'new_performance_metrics': 0, 'new_model_selection': 0,
                         'original_holdout_scored': False, 'live_database_api_or_binlog_opened': False},
        'limitations': ['Full raw export does not establish all original approvals known at the decision time.',
                        'Final canceled status is retrospective and cannot justify an as-of exclusion.',
                        'CSV/file hashes prove artifact bytes, not original ingestion or effective version times.',
                        'No verified source watermark, terminal batch manifest, closure revision or late-arrival reconciliation.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.suffix != '.json':
        raise ValueError('Audit output must be a JSON file inside the project')
    report = audit()
    if output.relative_to(ROOT).as_posix() in {item['path'] for item in report['source_manifest']}:
        raise ValueError('Output cannot replace a bound input')
    verify_sources(report['source_manifest'])
    immutable_write(output, report)
    verify_sources(report['source_manifest'])
    print(json.dumps({'status': report['status'], 'decision': report['decision'],
                      'raw_day_rows': report['roster']['raw_export_day_rows'],
                      'research_day_rows': report['roster']['accepted_research_day_rows'],
                      'runs_verified': report['verification']['frozen_research_runs_verified']}))


if __name__ == '__main__':
    main()
