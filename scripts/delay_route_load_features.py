"""Approval-only route/promise workload changes and fixed cross interactions.

All arrival counts use raw orders with valid purchase/approval timestamps and
approval >= purchase, including cancelled and unfinished orders. Windows are
left-closed/right-open and never read delivery, final status or target labels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.delay_ablation_features import VARIANT_FEATURES, build_ablation_order_features
from scripts.delay_engineering_features import (
    CATEGORICAL_FEATURES, ENGINEERING_NUMERIC_FEATURES,
    _number, build_engineering_order_features,
)
from scripts.delay_history_features import build_primary_sellers


TREND_NUMERIC_FEATURES = [
    'route_approvals_7d', 'route_approvals_previous_7d',
    'route_approvals_14d', 'route_approvals_previous_14d',
    'route_approval_log_growth_7d', 'route_approval_log_growth_14d',
    'route_approval_share_change_7d',
    'route_promise_approvals_7d', 'route_promise_approvals_previous_7d',
    'route_promise_approvals_14d', 'route_promise_approvals_previous_14d',
    'route_promise_approval_log_growth_7d', 'route_promise_approval_log_growth_14d',
]
CROSS_NUMERIC_FEATURES = [
    'promise_x_route_growth_7d', 'promise_x_lane_growth_7d',
    'margin_x_route_growth_7d', 'promise_x_route_overdue_share_30d',
]
CROSS_CATEGORICAL_FEATURES = ['state_route_promise_bin', 'state_route_promise_growth_bin']
ADDED_FEATURES = TREND_NUMERIC_FEATURES + CROSS_NUMERIC_FEATURES + CROSS_CATEGORICAL_FEATURES
PROMISE_BINS = ('0-7', '8-14', '15-21', '22-30', '31+')
GROWTH_THRESHOLD = float(np.log(1.25))
DAY_NS = int(pd.Timedelta(days=1).value)


def _timestamps(values, name):
    result = pd.to_datetime(values, errors='coerce', format='mixed')
    if result.dt.tz is not None:
        raise ValueError(f'{name} must be timezone-naive')
    return result


def promise_bins(values):
    """The predeclared calendar-day bins; invalid/noninteger values stay missing."""
    number = pd.to_numeric(values, errors='coerce').replace([np.inf, -np.inf], np.nan)
    valid = number.ge(0) & number.eq(np.floor(number))
    result = pd.Series(np.nan, index=values.index, dtype=object)
    masks = (number.between(0, 7), number.between(8, 14), number.between(15, 21),
             number.between(22, 30), number.ge(31))
    for label, mask in zip(PROMISE_BINS, masks, strict=True):
        result.loc[valid & mask] = label
    return result


def _route_keys(frame):
    return [None if pd.isna(seller) or pd.isna(customer) else (str(seller), str(customer))
            for seller, customer in zip(frame.primary_seller_state, frame.customer_state)]


def _lane_keys(routes, bins):
    return [None if route is None or pd.isna(bin_name) else (*route, str(bin_name))
            for route, bin_name in zip(routes, bins, strict=True)]


def _raw_approved_population(tables):
    """Build an approval-only ledger without even requiring delivery/status fields."""
    names = ['order_id', 'customer_id', 'order_purchase_timestamp',
             'order_approved_at', 'order_estimated_delivery_date']
    missing = set(names).difference(tables['orders'].columns)
    if missing:
        raise ValueError(f'Missing raw approval columns: {sorted(missing)}')
    raw = tables['orders'][names].copy()
    if raw.order_id.isna().any() or raw.order_id.duplicated().any():
        raise ValueError('Raw order IDs must be unique and non-null')
    for column in names[2:]:
        raw[column] = _timestamps(raw[column], column)
    valid = raw.order_purchase_timestamp.notna() & raw.order_approved_at.notna()
    valid &= raw.order_approved_at.ge(raw.order_purchase_timestamp)
    raw = raw.loc[valid].copy()
    primary = build_primary_sellers(tables['order_items']).set_index('order_id').primary_seller_id
    for table_name, key in (('customers', 'customer_id'), ('sellers', 'seller_id')):
        if tables[table_name][key].isna().any() or tables[table_name][key].duplicated().any():
            raise ValueError(f'{table_name}.{key} must be unique and non-null')
    customer_states = tables['customers'].set_index('customer_id').customer_state
    seller_states = tables['sellers'].set_index('seller_id').seller_state
    raw['primary_seller_state'] = raw.order_id.map(primary).map(seller_states)
    raw['customer_state'] = raw.customer_id.map(customer_states)
    raw['promise_days'] = (raw.order_estimated_delivery_date.dt.normalize()
                           - raw.order_approved_at.dt.normalize()).dt.total_seconds() / 86400
    return raw.sort_values(['order_approved_at', 'order_id'], kind='stable').reset_index(drop=True)


def _window_counts(event_times, query_times):
    """Columns are recent 7, previous 7, recent 14 and previous 14 days."""
    boundaries = [np.searchsorted(event_times, query_times - days * DAY_NS, side='left')
                  for days in (0, 7, 14, 28)]
    upper, week, fortnight, previous_fortnight = boundaries
    return np.column_stack((upper-week, week-fortnight, upper-fortnight,
                            fortnight-previous_fortnight)).astype(float)


def _group_counts(event_times, event_keys, query_times, query_keys, valid_queries):
    output = np.full((len(query_times), 4), np.nan)
    event_groups, query_groups = {}, {}
    for position, key in enumerate(event_keys):
        if key is not None:
            event_groups.setdefault(key, []).append(position)
    for position, key in enumerate(query_keys):
        if key is not None and valid_queries[position]:
            query_groups.setdefault(key, []).append(position)
    for key, positions in query_groups.items():
        event_positions = event_groups.get(key, [])
        output[positions] = _window_counts(event_times[event_positions], query_times[positions])
    return output


def add_route_load_features(frame, tables):
    """Append fixed features while preserving every original value, row and index.

    Known routes without earlier approvals have zero counts/log growth; missing
    route keys are never pooled and remain missing. Invalid promised days still
    count toward a raw route, but cannot count toward a route/promise lane.
    """
    required = {'order_id', 'prediction_time', 'primary_seller_state', 'customer_state',
                'state_route', 'estimated_delivery_days', 'route_promise_margin_p90_days',
                'route_overdue_pending_share_30d'}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f'Missing route/load query columns: {sorted(missing)}')
    if set(ADDED_FEATURES).intersection(frame.columns):
        raise ValueError('Route/load feature columns already exist')
    if frame.order_id.isna().any() or frame.order_id.duplicated().any():
        raise ValueError('Query order IDs must be unique and non-null')
    timestamps = _timestamps(frame.prediction_time, 'prediction_time')
    valid_queries = timestamps.notna().to_numpy()
    query_times = timestamps.to_numpy(dtype='datetime64[ns]').view('int64')
    raw = _raw_approved_population(tables)
    event_times = raw.order_approved_at.to_numpy(dtype='datetime64[ns]').view('int64')
    routes, raw_routes = _route_keys(frame), _route_keys(raw)
    bins, raw_bins = promise_bins(frame.estimated_delivery_days), promise_bins(raw.promise_days)
    route_counts = _group_counts(event_times, raw_routes, query_times, routes, valid_queries)
    lane_counts = _group_counts(event_times, _lane_keys(raw_routes, raw_bins), query_times,
                                _lane_keys(routes, bins), valid_queries)
    global_counts = np.full((len(frame), 4), np.nan)
    global_counts[valid_queries] = _window_counts(event_times, query_times[valid_queries])
    output = frame.copy()
    output[TREND_NUMERIC_FEATURES[:4]] = route_counts
    output[TREND_NUMERIC_FEATURES[7:11]] = lane_counts
    with np.errstate(invalid='ignore', divide='ignore'):
        route_growth = np.log((route_counts[:, [0, 2]] + 1) / (route_counts[:, [1, 3]] + 1))
        lane_growth = np.log((lane_counts[:, [0, 2]] + 1) / (lane_counts[:, [1, 3]] + 1))
        share = np.divide(route_counts[:, :2], global_counts[:, :2],
                          out=np.full((len(frame), 2), np.nan), where=global_counts[:, :2] > 0)
    output[TREND_NUMERIC_FEATURES[4:6]] = route_growth
    output['route_approval_share_change_7d'] = share[:, 0] - share[:, 1]
    output[TREND_NUMERIC_FEATURES[11:13]] = lane_growth
    promise = _number(frame, 'estimated_delivery_days')
    promise = promise.where(promise.ge(0) & promise.eq(np.floor(promise))).to_numpy(dtype=float) / 30
    output['promise_x_route_growth_7d'] = promise * route_growth[:, 0]
    output['promise_x_lane_growth_7d'] = promise * lane_growth[:, 0]
    output['margin_x_route_growth_7d'] = _number(frame, 'route_promise_margin_p90_days').to_numpy(dtype=float) / 30 * route_growth[:, 0]
    output['promise_x_route_overdue_share_30d'] = promise * _number(frame, 'route_overdue_pending_share_30d').to_numpy(dtype=float)
    route_promise, route_growth_bin = [], []
    for route, original_route, bin_name, growth in zip(routes, frame.state_route, bins, lane_growth[:, 0], strict=True):
        if route is None or pd.isna(original_route) or pd.isna(bin_name):
            route_promise.append(np.nan)
            route_growth_bin.append(np.nan)
            continue
        lane = f'{original_route}|{bin_name}'
        route_promise.append(lane)
        if not np.isfinite(growth):
            route_growth_bin.append(np.nan)
        else:
            direction = 'decrease' if growth < -GROWTH_THRESHOLD else 'increase' if growth > GROWTH_THRESHOLD else 'stable'
            route_growth_bin.append(f'{lane}|{direction}')
    output[CROSS_CATEGORICAL_FEATURES[0]] = np.asarray(route_promise, dtype=object)
    output[CROSS_CATEGORICAL_FEATURES[1]] = np.asarray(route_growth_bin, dtype=object)
    return output[list(frame.columns) + ADDED_FEATURES]


def feature_columns(backbone, variant):
    """Return numeric/categorical whitelists for the four frozen contracts."""
    if backbone not in ('load', 'geo'):
        raise ValueError(f'Unknown route/load backbone: {backbone}')
    if variant not in ('trend', 'cross'):
        raise ValueError(f'Unknown route/load variant: {variant}')
    numeric = list(VARIANT_FEATURES['load_only'] if backbone == 'load' else ENGINEERING_NUMERIC_FEATURES)
    numeric += TREND_NUMERIC_FEATURES
    categorical = list(CATEGORICAL_FEATURES)
    if variant == 'cross':
        numeric += CROSS_NUMERIC_FEATURES
        categorical += CROSS_CATEGORICAL_FEATURES
    return numeric, categorical


def prepare_route_load_input(frame, backbone, variant):
    numeric, categorical = feature_columns(backbone, variant)
    missing = set(numeric + categorical).difference(frame.columns)
    if missing:
        raise ValueError(f'Missing route/load feature columns: {sorted(missing)}')
    output = frame[numeric + categorical].copy()
    for column in numeric:
        output[column] = _number(output, column)
    for column in categorical:
        output[column] = output[column].astype(object).where(output[column].notna(), np.nan)
    return output


def build_route_load_order_features(tables, backbone, variant, geolocation=None):
    numeric, categorical = feature_columns(backbone, variant)
    if backbone == 'load':
        frame = build_ablation_order_features(tables, 'load_only')
    else:
        if geolocation is None:
            raise ValueError('Route/load geographic inference requires the static geolocation reference table')
        frame = build_engineering_order_features(tables, geolocation, include_dispatch=False)
    enriched = add_route_load_features(frame, tables)
    return enriched[['order_id', 'order_purchase_timestamp', 'prediction_time'] + numeric + categorical]
