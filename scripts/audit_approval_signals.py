"""Describe two approval-time, unobserved-handover workload proxies.

This is an availability audit, never a model feature/training/prediction CLI.
All scores and outcomes come from the frozen 101/102/104 development ledger.
Only aggregate distributions are published; optional per-order proxy values
must stay under the ignored .runtime directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_history_features import build_primary_sellers

CUTOFF = pd.Timestamp('2018-05-01')
ANALYSIS = 'approval_time_unobserved_handover_signal_inventory'
SIGNALS = ('seller_unobserved_handover_pending_count_90d',
           'seller_unobserved_handover_pending_age_p90_hours_90d')
COUNT_BINS = ('missing_seller', 'zero', 'one_to_four', 'five_to_nineteen', 'twenty_plus')
AGE_BINS = ('missing_seller', 'empty', 'up_to_24h', 'over24_to72h', 'over72_to168h', 'over168h')
COHORTS = ('common_missed_delayed', 'other_known_delayed', 'known_ontime', 'unknown_outcome')
CANDIDATES = ('xgboost_rank_backlog_7_14d_l2_100_topk_10',
              'xgboost_rank_handover_count_102_l2_100_topk_10',
              'xgboost_rank_handover_104_l2_100_topk_10')
TIME_COLUMNS = ('order_purchase_timestamp', 'order_approved_at',
                'order_delivered_carrier_date', 'order_delivered_customer_date')
SOURCE_SHA256 = '57077703b7160c84eca8ab517f2f3325d105ea481bfa5c657f057fbbd0a3f9b3'
DIAGNOSTIC_SHA256 = '35f15584b6843318872e561531dc870e392c0cfec19cbf66f7c9e98c32b35121'
CONTRACT_SHA256 = '064891915530d167e24791fafdf39576eaa3605aa294c55f7757ab526e2da1d9'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def _timestamps(values, name):
    values = pd.to_datetime(values, errors='coerce', format='mixed')
    if values.dt.tz is not None:
        raise ValueError(f'{name} must be timezone-naive')
    return values


def contract():
    """Prespecified before any full-population or outcome-group calculation."""
    return {
        'prediction_time': 'approval', 'query_cutoff_exclusive': CUTOFF.isoformat(),
        'signals': list(SIGNALS), 'window_days': 90,
        'primary_seller': 'Highest item price, then lowest item sequence; unchanged static-export lookup.',
        'history': 'Valid purchase <= approval, other order identity, approval in [t-90d,t).',
        'observed_event': 'Carrier/customer event strictly < t. Event equal to t is unknown.',
        'pending': 'No carrier event observed before t AND no customer-delivery event observed before t.',
        'observed_anomalies': 'Observed carrier before approval, delivery before approval, delivery before observed carrier, and delivery observed without observed carrier are quarantined from pending. Future carrier/delivery timestamps never exclude a row.',
        'zero_and_missing': 'Known seller with no pending orders: count=0, age p90 missing. Unknown seller: both missing; unknown sellers are never pooled.',
        'age_quantile': 'Linear p90 of (t - historical approval) hours among pending; minimum 1 pending order, fixed diagnostic rule, not the 104-column handover min-5 rule.',
        'count_bins': dict(zip(COUNT_BINS, ('seller missing', 'count == 0', '1 <= count <= 4', '5 <= count <= 19', 'count >= 20'), strict=True)),
        'age_bins': dict(zip(AGE_BINS, ('seller missing', 'count == 0', '0 <= age <= 24', '24 < age <= 72', '72 < age <= 168', 'age > 168'), strict=True)),
        'cohorts': {COHORTS[0]: 'Known delayed and no alert from any of the three fixed models.',
                    COHORTS[1]: 'Known delayed and alerted by at least one fixed model.',
                    COHORTS[2]: 'Known on-time.', COHORTS[3]: 'Outcome unavailable at the original historical cutoff.'},
        'ranking': 'Original full closed daily batch floor(0.1*N), unknown outcomes compete before cohort masks; no cohort reranking.',
        'no_threshold_search': True, 'no_model_input_change': True,
        'interpretation': 'Prespecified descriptive bins test coverage, not model gain or causal mechanism. Repeated validation months have different cutoffs and cannot be summed as independent months.',
    }


def pending_signals(queries, orders, items):
    """Return only ID, query time and two diagnostic proxies, without targets.

    Future delivery-before-carrier contradictions cannot affect the output.
    A delivery already observed before t excludes the order even when the
    missing/unobserved carrier is anomalous; no final status is consulted.
    """
    required = {'order_id', 'prediction_time'}
    if not required.issubset(queries):
        raise ValueError('Missing query IDs or times')
    if queries.order_id.isna().any() or queries.order_id.duplicated().any():
        raise ValueError('Query IDs must be unique and non-null')
    if not {'order_id', *TIME_COLUMNS}.issubset(orders):
        raise ValueError('Missing raw order clocks')
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError('Raw IDs must be unique and non-null')
    times = _timestamps(queries.prediction_time, 'prediction_time')
    if times.isna().any() or times.ge(CUTOFF).any():
        raise ValueError('Queries require valid approval times before May 2018')
    raw = orders[['order_id', *TIME_COLUMNS]].copy()
    for name in TIME_COLUMNS:
        raw[name] = _timestamps(raw[name], name)
    # Scope first; future physical-event values are then censored before use.
    raw = raw.loc[raw.order_approved_at.lt(CUTOFF)
                  & raw.order_purchase_timestamp.notna()
                  & raw.order_approved_at.ge(raw.order_purchase_timestamp)].copy()
    for name in TIME_COLUMNS[2:]:
        raw[name] = raw[name].where(raw[name].lt(CUTOFF))
    lookup = build_primary_sellers(items).set_index('order_id').primary_seller_id
    raw['seller'] = raw.order_id.map(lookup)
    query_sellers = queries.order_id.map(lookup)
    groups = {seller: group.sort_values(['order_approved_at', 'order_id'], kind='stable')
              for seller, group in raw.loc[raw.seller.notna()].groupby('seller', sort=False)}
    output = np.full((len(queries), 2), np.nan)
    quality = {'query_history_occurrences': 0, 'carrier_before_approval_observed': 0,
               'delivery_before_approval_observed': 0, 'delivery_before_carrier_both_observed': 0,
               'delivery_without_carrier_observed': 0}
    for seller in query_sellers.dropna().unique():
        positions = np.flatnonzero(query_sellers.eq(seller).to_numpy())
        group = groups.get(seller)
        if group is None:
            output[positions, 0] = 0
            continue
        approvals = group.order_approved_at.to_numpy(dtype='datetime64[ns]')
        carriers = group.order_delivered_carrier_date.to_numpy(dtype='datetime64[ns]')
        deliveries = group.order_delivered_customer_date.to_numpy(dtype='datetime64[ns]')
        ids = group.order_id.to_numpy()
        for position in positions:
            now = times.iloc[position].to_datetime64()
            lower = np.searchsorted(approvals, now - np.timedelta64(90, 'D'), side='left')
            upper = np.searchsorted(approvals, now, side='left')
            keep = ids[lower:upper] != queries.order_id.iloc[position]
            a, c, d = approvals[lower:upper][keep], carriers[lower:upper][keep], deliveries[lower:upper][keep]
            carrier_seen, delivery_seen = c < now, d < now
            pending = ~carrier_seen & ~delivery_seen
            output[position, 0] = pending.sum()
            if pending.any():
                hours = (now - a[pending]) / np.timedelta64(1, 'h')
                output[position, 1] = np.quantile(hours, .9, method='linear')
            quality['query_history_occurrences'] += len(a)
            quality['carrier_before_approval_observed'] += int((carrier_seen & (c < a)).sum())
            quality['delivery_before_approval_observed'] += int((delivery_seen & (d < a)).sum())
            quality['delivery_before_carrier_both_observed'] += int((carrier_seen & delivery_seen & (d < c)).sum())
            quality['delivery_without_carrier_observed'] += int((delivery_seen & ~carrier_seen).sum())
    result = queries[['order_id', 'prediction_time']].copy()
    result['prediction_time'] = times
    result[list(SIGNALS)] = output
    quality.update({'queries': len(queries), 'missing_seller_queries': int(query_sellers.isna().sum()),
                    'scope': 'Overlapping historical order occurrences across queries, not unique raw orders. Anomaly categories overlap.',
                    'valid_approved_raw_orders_before_cutoff': len(raw)})
    return result, quality


def signal_bins(values):
    count = pd.to_numeric(values[SIGNALS[0]], errors='raise').to_numpy(dtype=float)
    age = pd.to_numeric(values[SIGNALS[1]], errors='raise').to_numpy(dtype=float)
    if np.any(np.isinf(count)) or np.any(np.isinf(age)) or np.any(count[np.isfinite(count)] < 0) or np.any(count[np.isfinite(count)] % 1):
        raise ValueError('Pending counts require nonnegative integers or missing')
    if np.any(np.isfinite(age) != (count > 0)) or np.any(age[np.isfinite(age)] < 0) or np.any(age[np.isfinite(age)] > 90 * 24):
        raise ValueError('Pending age missingness or 90-day bounds are invalid')
    count_bin = np.select([np.isnan(count), count == 0, count < 5, count < 20], COUNT_BINS[:-1], default=COUNT_BINS[-1])
    age_bin = np.select([np.isnan(count), count == 0, age <= 24, age <= 72, age <= 168], AGE_BINS[:-1], default=AGE_BINS[-1])
    return count_bin, age_bin


def summarize(values, mask):
    count_bin, age_bin = signal_bins(values)
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != (len(values),):
        raise ValueError('Invalid cohort mask')
    n = int(mask.sum())
    result = {'orders': n, 'count_observed': int((mask & values[SIGNALS[0]].notna().to_numpy()).sum()),
              'age_observed': int((mask & values[SIGNALS[1]].notna().to_numpy()).sum()),
              'count_bins': {b: int((mask & (count_bin == b)).sum()) for b in COUNT_BINS},
              'age_bins': {b: int((mask & (age_bin == b)).sum()) for b in AGE_BINS}}
    for bins in ('count_bins', 'age_bins'):
        if sum(result[bins].values()) != n:
            raise AssertionError('Fixed signal bins must partition each cohort')
    for signal in SIGNALS:
        data = values.loc[mask, signal].dropna()
        result[signal] = {'median': None if data.empty else float(data.median()),
                          'p90': None if data.empty else float(data.quantile(.9))}
    return result


def phase_profile(frame, ledger, values, *, role='evaluation', cutoff=None):
    """Retain complete-day ranks and separate four exhaustive outcome cohorts."""
    if set(ledger.candidate) != set(CANDIDATES) or len(ledger) != 3 * len(frame):
        raise ValueError('Require three complete fixed score cohorts')
    if role not in ('validation', 'evaluation'):
        raise ValueError('Unknown scoring role')
    if role == 'validation':
        if cutoff is None or 'label_available_time' not in frame:
            raise ValueError('Historical phases require original delivery-observation clocks')
        expected_known = pd.to_datetime(frame.label_available_time, errors='raise').lt(pd.Timestamp(cutoff)).to_numpy()
    else:
        expected_known = np.ones(len(frame), bool)
    alerts, known, labels = [], None, None
    for candidate in CANDIDATES:
        part = ledger.loc[ledger.candidate.eq(candidate)]
        if part.order_id.duplicated().any() or set(part.order_id) != set(frame.order_id):
            raise ValueError('Ledger and full batch identities differ')
        part = part.set_index('order_id').loc[frame.order_id]
        observed = part.outcome_for_metrics.notna().to_numpy()
        if not np.array_equal(observed, expected_known):
            raise ValueError('Frozen historical outcome availability changed')
        if part.known_at_selection.dtype != bool:
            raise ValueError('Selection availability flags must be boolean')
        expected_flags = expected_known if role == 'validation' else np.zeros(len(frame), bool)
        if not np.array_equal(part.known_at_selection.to_numpy(), expected_flags):
            raise ValueError('Frozen selection availability flags changed')
        outcomes = part.outcome_for_metrics.to_numpy(dtype=float)
        if not np.isin(outcomes[observed], [0, 1]).all():
            raise ValueError('Known labels must be binary')
        if known is None:
            known, labels = observed, outcomes
        elif not np.array_equal(known, observed) or not np.array_equal(labels[known], outcomes[known]):
            raise ValueError('Models changed known outcome availability')
        actual = apply_alert_policy(frame, part.delay_score.to_numpy(dtype=float), 0., .1,
                                    raw_scores=part.delay_score.to_numpy(dtype=float))
        np.testing.assert_array_equal(actual, part.predicted_delayed.to_numpy())
        np.testing.assert_array_equal(pd.to_datetime(part.prediction_time).to_numpy(), frame.prediction_time.to_numpy())
        alerts.append(actual)
    missed = known & (labels == 1) & ~np.any(alerts, axis=0)
    masks = (missed, known & (labels == 1) & ~missed, known & (labels == 0), ~known)
    if not np.all(np.sum(np.asarray(masks), axis=0) == 1):
        raise AssertionError('Signal cohorts must partition every full batch')
    return {'full_batch': summarize(values, np.ones(len(frame), bool)),
            'cohorts': {name: summarize(values, mask) for name, mask in zip(COHORTS, masks, strict=True)}}


def availability_inventory():
    return [
        {'signal': 'Transaction, geography, completed delivery, undelivered and overdue workload, route/promise 7/14-day changes',
         'available_at_approval': 'conditional', 'available_later': True, 'unavailable': False,
         'coverage': 'Already included in all three 101/102/104 models; not new.',
         'assumption': 'Static export attributes and historical event < t ingestion assumptions.'},
        {'signal': 'Primary seller 90-day completed handover event count and elapsed p50/p90',
         'available_at_approval': 'conditional', 'available_later': True, 'unavailable': False,
         'coverage': 'Count already in102/104; p50/p90 already in104. Old logistics inventory predates those branches.',
         'assumption': 'Other orders carrier < t; order-level handover proxy; min5 events for104 quantiles.'},
        {'signal': list(SIGNALS), 'available_at_approval': 'conditional', 'available_later': True, 'unavailable': False,
         'coverage': 'Not in101/102/104; calculated here only as diagnostic descriptors.',
         'assumption': 'Absence of an observed carrier is not verified physical non-dispatch; static primary seller, timely ingestion and missing cancellation clocks remain limitations.'},
        {'signal': 'Item shipping_limit_date schedule and promise-after-dispatch schedule',
         'available_at_approval': 'unverified', 'available_later': 'unverified', 'unavailable': False,
         'coverage': 'Existing8-feature dispatch sensitivity branch; not a new untested signal.',
         'assumption': 'No creation/revision history proves approval-time schedule version; not an actual handover event.'},
        {'signal': 'Own future carrier/customer-delivery timestamp, elapsed actual handover/transit duration',
         'available_at_approval': False, 'available_later': 'after event observation only', 'unavailable': False,
         'coverage': 'Excluded as own-order approval predictors; later checkpoints change population/budget.',
         'assumption': 'Never import future event or duration into approval model.'},
        {'signal': 'Final status, reviews, cancellation/status-transition times',
         'available_at_approval': False, 'available_later': 'final status/reviews only; transition timestamps absent', 'unavailable': 'historical transitions',
         'coverage': 'Snapshot final status and downstream reviews cannot reconstruct as-of state.',
         'assumption': 'Approved cancelled orders may remain in unobserved-event queue.'},
        {'signal': 'Carrier ID/service, parcel scans/position, ingestion timestamps, weather and holiday source',
         'available_at_approval': False, 'available_later': False, 'unavailable': True,
         'coverage': 'Not supplied by nine raw tables; weekday already exists.',
         'assumption': 'Needs actual external/versioned sources; cannot invent from ZIP or final timestamps.'},
    ]


def build_report(source_path, diagnostic_path, raw_dir, cache_output=None):
    source_path, diagnostic_path, raw_dir = Path(source_path), Path(diagnostic_path), Path(raw_dir)
    verify_fixed_sources(source_path, diagnostic_path)
    # The pre-run snapshot was saved by Windows Path.write_text (CRLF).
    # Reconstruct those exact bytes explicitly so verification is portable.
    contract_text = (json.dumps(contract(), ensure_ascii=False, indent=2) + '\n').replace('\n', '\r\n')
    if hashlib.sha256(contract_text.encode('utf-8')).hexdigest() != CONTRACT_SHA256:
        raise ValueError('Prespecified signal contract changed')
    source = json.loads(source_path.read_text(encoding='utf-8'))
    diagnostic = json.loads(diagnostic_path.read_text(encoding='utf-8'))
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    files = {source_path: sha256(source_path), diagnostic_path: sha256(diagnostic_path),
             feature_path: source['feature_dataset']['sha256'], score_path: source['score_export']['sha256'],
             ROOT / 'reports/stage4/logistics_availability.json': sha256(ROOT / 'reports/stage4/logistics_availability.json')}
    for row in source['source_files']:
        files[raw_dir / row['filename']] = row['sha256']
    if diagnostic.get('source_report') != {'path': relative(source_path), 'sha256': files[source_path]}:
        raise ValueError('Require diagnostic provenance for the frozen source')
    def verify():
        for path, expected in files.items():
            if sha256(path) != expected:
                raise ValueError(f'Frozen source changed: {relative(path)}')
    verify()
    features = pd.read_csv(feature_path, float_precision='round_trip')
    features.prediction_time = pd.to_datetime(features.prediction_time, errors='raise')
    if len(features) != 70844 or len(features.columns) != 137 or features.prediction_time.ge(CUTOFF).any():
        raise ValueError('Require frozen137-column pre-May feature cache')
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    if len(ledger) != 192168 or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any():
        raise ValueError('Require unchanged192168-row ledger')
    orders = pd.read_csv(raw_dir / 'olist_orders_dataset.csv', dtype=str)
    items = pd.read_csv(raw_dir / 'olist_order_items_dataset.csv', dtype={'order_id': str, 'seller_id': str})
    values, quality = pending_signals(features[['order_id', 'prediction_time']], orders, items)
    signal_bins(values)
    phases = {}
    scored_rows = 0
    for fold in source['folds']:
        for month, role in [*((r['month'], 'validation') for r in fold['schedule']['validation_months']), (fold['name'], 'evaluation')]:
            key = f'{fold["name"]}/{month}/{role}'
            selected = features.prediction_time.dt.strftime('%Y-%m').eq(month)
            frame = features.loc[selected].reset_index(drop=True)
            local = values.loc[selected].reset_index(drop=True)
            part = ledger.loc[ledger.fold.eq(fold['name']) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            profile = phase_profile(frame, part, local, role=role, cutoff=fold['schedule']['evaluation_start'])
            expected = diagnostic['phases'][key]
            if profile['full_batch']['orders'] != expected['context'][CANDIDATES[0]]['full_batch']['scored_rows']:
                raise ValueError('Frozen diagnostic phase population changed')
            phases[key] = {'fold': fold['name'], 'month': month,
                           'role': 'historical_validation' if role == 'validation' else 'development_retest',
                           'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                           **profile}
            scored_rows += len(part)
    if len(phases) != 12 or scored_rows != len(ledger):
        raise ValueError('Expected exactly12 complete original phases')
    if cache_output is not None:
        cache_output = Path(cache_output).resolve()
        if not cache_output.is_relative_to((ROOT / '.runtime').resolve()) or cache_output.suffix.lower() != '.csv':
            raise ValueError('Per-order diagnostics must be an ignored .runtime CSV')
        cache_output.parent.mkdir(parents=True, exist_ok=True)
        values.to_csv(cache_output, index=False)
    verify()
    return {'format_version': 1, 'analysis': ANALYSIS, 'status': 'ok',
            'source_report': {'path': relative(source_path), 'sha256': files[source_path]},
            'source_diagnostic': {'path': relative(diagnostic_path), 'sha256': files[diagnostic_path]},
            'source_features': source['feature_dataset'], 'source_scores': source['score_export'],
            'source_hashes': [{'path': relative(p), 'sha256': h} for p, h in files.items()],
            'contract_provenance': {'path': '.runtime/verification/approval-signal-prespecified.json',
                                    'sha256': CONTRACT_SHA256, 'captured_before_full_population_profile': True,
                                    'exact_contract_reconstructed_and_verified': True, 'no_search': True},
            'contract': contract(), 'availability_matrix': availability_inventory(),
            'raw_schema': {'orders': {'file': 'olist_orders_dataset.csv', 'used_columns': ['order_id', *TIME_COLUMNS]},
                           'items': {'file': 'olist_order_items_dataset.csv', 'used_columns': ['order_id', 'order_item_id', 'price', 'seller_id']},
                           'unused_fields': ['order_status', 'shipping_limit_date', 'reviews', 'targets']},
            'query_quality': quality, 'full_feature_population': summarize(values, np.ones(len(values), bool)),
            'phases': phases,
            'verification': {'phases': 12, 'ledger_rows': scored_rows, 'new_fits': 0,
                             'new_model_predictions': 0, 'models_loaded': 0, 'new_selection': False,
                             'original_holdout_not_read_as_query_or_rescored': True,
                             'frozen_sources_checked_before_and_after': True,
                             'diagnostic_proxies_added_to_model_inputs': False},
            'limitations': ['These are unobserved-event proxies, not verified physical queues or parcel-level seller handovers.',
                            'No cancellation, event ingestion or static attribute revision timestamps are available.',
                            'Two diagnostic columns are outside all three fixed model input whitelists; no recall gain is measured.',
                            'Outcome-conditioned descriptive distributions do not establish predictive gain or feature causality.',
                            'All phases are reused historical validation/development; repeated months with different cutoffs overlap.',
                            'All operational queries and observed event clocks are strictly before2018-05-01; original holdout is unchanged.']}


def verify_fixed_sources(source, diagnostic):
    if sha256(source) != SOURCE_SHA256 or sha256(diagnostic) != DIAGNOSTIC_SHA256:
        raise ValueError('Require the exact frozen101/102/104 experiment and diagnostic source hashes')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/handover_count.json')
    parser.add_argument('--source-diagnostic', type=Path, default=ROOT / 'reports/stage4/handover_count_diagnostics.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/approval_signal_inventory.json')
    parser.add_argument('--cache-output', type=Path)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.suffix.lower() != '.json' or output in (args.source_report.resolve(), args.source_diagnostic.resolve()):
        parser.error('Require a separate aggregate JSON report')
    if output.exists() and json.loads(output.read_text(encoding='utf-8')).get('analysis') != ANALYSIS:
        parser.error('Refusing to overwrite another report')
    report = build_report(args.source_report, args.source_diagnostic, args.data_dir, args.cache_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'report': relative(output), 'phases': len(report['phases']), 'new_fits': 0, 'new_predictions': 0}), flush=True)
    return report


if __name__ == '__main__':
    main()
