"""One approval-time waiting-age p90 feature, without a pending-count input.

The primary seller's other orders enter the 90-day cohort on approval. Only
carrier or customer-delivery events observed strictly before the query remove
them. The remaining approval-to-query hours form a linear p90 with minimum
one observation. Missing event ingestion and cancellation clocks limit this
to an unobserved-event proxy, not a verified physical queue.
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

from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.delay_history_features import build_primary_sellers

WINDOW_DAYS = 90
MIN_PENDING_OBSERVATIONS = 1
QUANTILE = .9
QUANTILE_METHOD = 'linear'
CUTOFF = pd.Timestamp('2018-05-01')
ADDED_FEATURES = ('seller_unobserved_handover_pending_age_p90_hours_90d',)
SOURCE_FEATURE_SHA256 = 'fe558084eaa0989a5dbad0c4e9ad9a474f3af7466c91cfaf202dc71d505618d7'
TIME_COLUMNS = ('order_purchase_timestamp', 'order_approved_at',
                'order_delivered_carrier_date', 'order_delivered_customer_date')
CATEGORICAL_CACHE_COLUMNS = (*CATEGORICAL_FEATURES, 'state_route_promise_bin', 'state_route_promise_growth_bin',
                             'state_route', 'primary_seller_id', 'customer_zip_prefix3', 'primary_seller_zip_prefix3')


def feature_contract():
    """Prespecified age-only feature; no threshold or quantile search."""
    return {
        'prediction_time': 'approval', 'query_cutoff_exclusive': CUTOFF.isoformat(),
        'added_features': list(ADDED_FEATURES), 'window_days': WINDOW_DAYS,
        'primary_seller': 'Highest item price, then lowest item sequence; unchanged static-export lookup.',
        'history': 'Valid purchase <= approval, other order identity, approval in [t-90d,t).',
        'observed_event': 'Carrier/customer event strictly < t. Event equal to t is unknown.',
        'pending': 'No carrier event observed before t AND no customer-delivery event observed before t.',
        'age_quantile': 'Linear p90 of (t - historical approval) hours among pending; minimum 1 pending order, not the completed-handover min-5 rule.',
        'quantile': QUANTILE, 'quantile_method': QUANTILE_METHOD,
        'minimum_pending_observations': MIN_PENDING_OBSERVATIONS,
        'future_data': 'Future physical-event timestamps and final status never exclude an order.',
        'observed_anomalies': 'Any already-observed carrier or delivery excludes the order, including contradictions and delivery without carrier.',
        'missing': 'Known seller with no pending orders: age missing. Unknown seller: age missing; unknown sellers are never pooled. Quality distinguishes these groups, but no pending-count input or hand-made missingness feature is added.',
        'assumptions': 'Static primary seller and event-time-as-knowledge; ingestion, cancellation and attribute-revision clocks unavailable.',
        'excluded_added_features': ['pending_count', 'completed_handover_event_count', 'completed_handover_quantiles', 'targets', 'final_status'],
    }


def _timestamps(values, name):
    converted = pd.to_datetime(values, errors='coerce', format='mixed')
    if converted.dt.tz is not None:
        raise ValueError(f'{name} must be timezone-naive')
    return converted


def _require_ids(frame, label):
    if 'order_id' not in frame:
        raise ValueError(f'Missing {label} order IDs')
    if (frame.order_id.isna().any() or frame.order_id.duplicated().any()
            or not frame.order_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
        raise ValueError(f'{label} IDs must be unique nonempty strings')


def _calculate(queries, orders, items):
    """Compute only age p90, independently of the earlier audit and count CLI."""
    _require_ids(queries, 'Query')
    _require_ids(orders, 'Raw')
    if 'prediction_time' not in queries:
        raise ValueError('Missing query prediction times')
    if not set(TIME_COLUMNS).issubset(orders):
        raise ValueError('Missing raw order clocks')
    times = _timestamps(queries.prediction_time, 'prediction_time')
    if times.isna().any() or times.ge(CUTOFF).any():
        raise ValueError('Queries require valid approval times before May 2018')

    raw = orders[['order_id', *TIME_COLUMNS]].copy()
    for column in TIME_COLUMNS:
        raw[column] = _timestamps(raw[column], column)
    valid = (raw.order_purchase_timestamp.notna() & raw.order_approved_at.notna()
             & raw.order_approved_at.ge(raw.order_purchase_timestamp)
             & raw.order_approved_at.lt(CUTOFF))
    history = raw.loc[valid].copy()
    primary = build_primary_sellers(items).set_index('order_id').primary_seller_id
    history['seller'] = history.order_id.map(primary)
    sellers = queries.order_id.map(primary)
    for column in TIME_COLUMNS[2:]:
        history[column] = history[column].where(history[column].lt(CUTOFF))
    groups = {}
    for seller, group in history.loc[history.seller.notna()].groupby('seller', sort=False):
        group = group.sort_values(['order_approved_at', 'order_id'], kind='stable')
        groups[seller] = (group.order_approved_at.to_numpy(dtype='datetime64[ns]'),
                          group.order_delivered_carrier_date.to_numpy(dtype='datetime64[ns]'),
                          group.order_delivered_customer_date.to_numpy(dtype='datetime64[ns]'),
                          group.order_id.to_numpy())
    ages = np.full(len(queries), np.nan, dtype=float)
    history_occurrences = pending_occurrences = known_empty = 0
    for position, (order_id, seller, timestamp) in enumerate(zip(queries.order_id, sellers, times, strict=True)):
        if pd.isna(seller):
            continue
        if seller not in groups:
            known_empty += 1
            continue
        approvals, carriers, deliveries, identities = groups[seller]
        now = timestamp.to_datetime64()
        left = np.searchsorted(approvals, now - np.timedelta64(WINDOW_DAYS, 'D'), side='left')
        right = np.searchsorted(approvals, now, side='left')
        other = identities[left:right] != order_id
        unobserved = ~(carriers[left:right] < now) & ~(deliveries[left:right] < now)
        selected = other & unobserved
        history_occurrences += int(np.count_nonzero(other))
        pending_occurrences += int(np.count_nonzero(selected))
        if selected.any():
            hours = (now - approvals[left:right][selected]) / np.timedelta64(1, 'h')
            ages[position] = np.quantile(hours, QUANTILE, method=QUANTILE_METHOD)
        else:
            known_empty += 1
    observed = ages[np.isfinite(ages)]
    if np.isinf(ages).any() or (observed <= 0).any() or (observed > WINDOW_DAYS * 24).any():
        raise AssertionError('Pending age must lie in (0, 90 days] or be missing')
    result = queries[['order_id', 'prediction_time']].copy()
    result['prediction_time'] = times
    result[ADDED_FEATURES[0]] = ages
    quality = {
        'queries': len(queries), 'raw_orders': len(orders),
        'valid_approved_raw_orders_before_cutoff': len(history),
        'valid_history_orders_with_missing_seller': int(history.seller.isna().sum()),
        'query_history_occurrences': history_occurrences,
        'pending_history_occurrences': pending_occurrences,
        'missing_seller_queries': int(sellers.isna().sum()),
        'known_seller_without_pending_queries': known_empty,
        'age_observed_queries': int(np.isfinite(ages).sum()),
        'age_missing_queries': int(np.isnan(ages).sum()),
        'age_min_hours': None if not len(observed) else float(observed.min()),
        'age_median_hours': None if not len(observed) else float(np.median(observed)),
        'age_population_p90_hours': None if not len(observed) else float(np.quantile(observed, .9, method='linear')),
        'age_max_hours': None if not len(observed) else float(observed.max()),
        'scope': 'Age summaries describe per-query seller pending-age p90 values, not pooled history durations; historical occurrences overlap between queries.',
        'pending_count_exported_as_feature': False,
    }
    if quality['age_missing_queries'] != quality['missing_seller_queries'] + known_empty:
        raise AssertionError('Unknown seller and empty known history must partition missing ages')
    return result, quality


def pending_age_p90(queries, orders, items):
    """Return ID, normalized query time and exactly one age-p90 column."""
    return _calculate(queries, orders, items)[0]


def add_unobserved_handover_age(dataset, orders, items):
    """Append only age p90 while preserving every original value and index."""
    if not {'order_id', 'prediction_time'}.issubset(dataset):
        raise ValueError('Missing query IDs or prediction times')
    if set(ADDED_FEATURES).intersection(dataset.columns):
        raise ValueError('Unobserved-handover age feature already exists')
    values, quality = _calculate(dataset[['order_id', 'prediction_time']], orders, items)
    augmented = dataset.copy()
    augmented[ADDED_FEATURES[0]] = values[ADDED_FEATURES[0]].to_numpy()
    return augmented, quality


def read_feature_cache(path):
    """Preserve categorical ZIP prefixes and round-trip numeric precision."""
    return pd.read_csv(path, float_precision='round_trip',
                       dtype={column: object for column in CATEGORICAL_CACHE_COLUMNS})


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT / 'data/processed/olist_delay_handover_features.csv')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/olist_delay_unobserved_handover_age_features.csv')
    parser.add_argument('--quality-output', type=Path, default=ROOT / '.runtime/verification/unobserved-handover-age-feature-quality.json')
    args = parser.parse_args(argv)
    source, output, quality_path = args.dataset.resolve(), args.output.resolve(), args.quality_output.resolve()
    if (not output.is_relative_to((ROOT / 'data/processed').resolve()) or output == source
            or output.suffix.lower() != '.csv'):
        parser.error('Feature cache must be a separate ignored data/processed CSV')
    if not quality_path.is_relative_to((ROOT / '.runtime').resolve()) or quality_path.suffix.lower() != '.json':
        parser.error('Quality metadata must stay in an ignored .runtime JSON')
    if _sha256(source) != SOURCE_FEATURE_SHA256:
        raise ValueError('Require the exact original 137-column cache, not the pending-count cache')
    dataset = read_feature_cache(source)
    if dataset.shape != (70844, 137):
        raise ValueError('Require the frozen 70,844-row, 137-column development dataset')
    paths = [source, args.data_dir / 'olist_orders_dataset.csv', args.data_dir / 'olist_order_items_dataset.csv']
    sources = [{'path': p.resolve().relative_to(ROOT).as_posix(), 'sha256': _sha256(p)} for p in paths]
    orders = pd.read_csv(paths[1], dtype=str)
    items = pd.read_csv(paths[2], dtype={'order_id': str, 'seller_id': str})
    result, quality = add_unobserved_handover_age(dataset, orders, items)
    pd.testing.assert_frame_equal(result[list(dataset.columns)], dataset, check_exact=True)
    if result.shape != (70844, 138):
        raise AssertionError('Only one new age feature may be appended')
    for info, path in zip(sources, paths, strict=True):
        if _sha256(path) != info['sha256']:
            raise ValueError('Source changed while building the age feature')
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    restored = read_feature_cache(output)
    pd.testing.assert_frame_equal(restored[list(dataset.columns)], dataset, check_exact=True)
    pd.testing.assert_series_equal(restored[ADDED_FEATURES[0]], result[ADDED_FEATURES[0]], check_exact=True)
    metadata = {'status': 'ok', 'contract': feature_contract(), 'quality': quality, 'source_hashes': sources,
                'output': {'path': output.relative_to(ROOT).as_posix(), 'sha256': _sha256(output),
                           'rows': len(result), 'columns': len(result.columns)},
                'verification': {'original_137_columns_preserved': True,
                                 'csv_round_trip_preserved_original_values': True,
                                 'added_features': list(ADDED_FEATURES),
                                 'pending_count_added': False, 'completed_handover_features_added': False}}
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'cache': metadata['output'], 'quality': quality}, ensure_ascii=False), flush=True)
    return metadata


if __name__ == '__main__':
    main()
