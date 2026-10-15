"""Primary-seller handover history observed strictly before each approval.

The 90-day window is anchored on the carrier event, not approval or eventual
delivery. Event timestamps stand in for knowledge only under the existing
timely-ingestion assumption. No target, final status, shipping deadline or
future delivery duration is consumed. A delivery-before-carrier contradiction
rejects a past carrier event: that contradicting delivery is necessarily also
before the query, so this check does not require a future observation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.delay_backlog_features import (
    build_backlog_order_features, feature_columns as backlog_feature_columns,
)
from scripts.delay_engineering_features import _number
from scripts.delay_history_features import build_primary_sellers


WINDOW_DAYS = 90
MIN_QUANTILE_EVENTS = 5
ADDED_FEATURES = [
    'seller_handover_count_90d',
    'seller_handover_p50_hours_90d',
    'seller_handover_p90_hours_90d',
]
FEATURE_SET = 'seller_handover_90d_backlog_geo_7_14d_approval'
_RAW_TIMES = (
    'order_purchase_timestamp', 'order_approved_at',
    'order_delivered_carrier_date', 'order_delivered_customer_date',
)


def _timestamps(values, name):
    result = pd.to_datetime(values, errors='coerce', format='mixed')
    if result.dt.tz is not None:
        raise ValueError(f'{name} must be timezone-naive')
    return result


def _raw_events(tables):
    """Return valid static-primary-seller events and aggregate quality counts.

    Missing delivery is accepted. A delivered final status is not required.
    Raw timestamps are never repaired or clipped to zero elapsed hours.
    """
    required = {'order_id', *_RAW_TIMES}
    if required.difference(tables['orders'].columns):
        raise ValueError(f'Missing handover source columns: {sorted(required.difference(tables["orders"].columns))}')
    raw = tables['orders'][['order_id', *_RAW_TIMES]].copy()
    if raw.order_id.isna().any() or raw.order_id.duplicated().any():
        raise ValueError('Raw handover orders must have unique non-null order IDs')
    for name in _RAW_TIMES:
        raw[name] = _timestamps(raw[name], name)
    purchase, approval, carrier, delivery = [raw[name] for name in _RAW_TIMES]
    complete = purchase.notna() & approval.notna() & carrier.notna()
    approval_before_purchase = approval.notna() & purchase.notna() & approval.lt(purchase)
    carrier_before_approval = carrier.notna() & approval.notna() & carrier.lt(approval)
    delivery_before_carrier = delivery.notna() & carrier.notna() & delivery.lt(carrier)
    valid = complete & ~approval_before_purchase & ~carrier_before_approval & ~delivery_before_carrier
    primary = build_primary_sellers(tables['order_items']).set_index('order_id').primary_seller_id
    raw['primary_seller_id'] = raw.order_id.map(primary)
    events = raw.loc[valid, ['order_id', 'primary_seller_id']].copy()
    events['event_time'] = carrier.loc[valid]
    events['approval_to_carrier_hours'] = (carrier.loc[valid] - approval.loc[valid]).dt.total_seconds() / 3600
    events = events.sort_values(['event_time', 'order_id'], kind='stable').reset_index(drop=True)
    return events, primary, {
        'raw_orders': len(raw),
        'missing_purchase_approval_or_carrier': int((~complete).sum()),
        'approval_before_purchase': int(approval_before_purchase.sum()),
        'carrier_before_approval': int(carrier_before_approval.sum()),
        'delivery_before_carrier': int(delivery_before_carrier.sum()),
        'valid_handover_events': len(events),
        'valid_events_with_missing_delivery': int((valid & delivery.isna()).sum()),
        'valid_events_with_known_primary_seller': int(events.primary_seller_id.notna().sum()),
        'counts_may_overlap': True,
    }


def handover_event_diagnostics(tables):
    """Aggregate source quality only; never export order or seller identities."""
    return _raw_events(tables)[2]


def add_handover_features(frame, tables):
    """Append exactly three columns while preserving every supplied value.

    Each query uses primary seller from the established most-expensive-item
    lookup. Count all valid other-order events in [query-90d, query). Below
    five observations retain count but leave both quantiles missing. Unknown
    sellers never pool: count is zero and durations missing. Invalid/missing
    query time leaves all three features missing. Quantiles use NumPy's
    explicitly fixed linear interpolation. Current-order identity is excluded
    independently of its clock, including malformed externally supplied rows.
    """
    required = {'order_id', 'prediction_time'}
    if required.difference(frame.columns):
        raise ValueError(f'Missing handover query columns: {sorted(required.difference(frame.columns))}')
    if set(ADDED_FEATURES).intersection(frame.columns):
        raise ValueError('Handover feature columns already exist')
    if (frame.order_id.isna().any() or frame.order_id.duplicated().any()
            or not frame.order_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
        raise ValueError('Require unique nonempty string handover query order IDs')
    queries = _timestamps(frame.prediction_time, 'Query approval time')
    events, primary, _ = _raw_events(tables)
    sellers = frame.order_id.map(primary)
    groups = {}
    for key, group in events.loc[events.primary_seller_id.notna()].groupby('primary_seller_id', sort=False):
        groups[key] = (
            group.event_time.to_numpy(dtype='datetime64[ns]'),
            group.order_id.to_numpy(),
            group.approval_to_carrier_hours.to_numpy(dtype=float),
        )
    values = np.full((len(frame), 3), np.nan, dtype=float)
    values[queries.notna().to_numpy(), 0] = 0.
    span = np.timedelta64(WINDOW_DAYS, 'D')
    for position, (order_id, seller, query) in enumerate(zip(frame.order_id, sellers, queries, strict=True)):
        if pd.isna(query) or pd.isna(seller) or seller not in groups:
            continue
        times, identities, hours = groups[seller]
        timestamp = np.datetime64(query.to_datetime64(), 'ns')
        left = int(np.searchsorted(times, timestamp - span, side='left'))
        right = int(np.searchsorted(times, timestamp, side='left'))
        durations = hours[left:right][identities[left:right] != order_id]
        values[position, 0] = len(durations)
        if len(durations) >= MIN_QUANTILE_EVENTS:
            values[position, 1:] = np.quantile(durations, [.5, .9], method='linear')
    result = frame.copy()
    result[ADDED_FEATURES] = values
    return result[list(frame.columns) + ADDED_FEATURES]


def feature_columns():
    numeric, categorical = backlog_feature_columns('geo', '7_14d')
    return numeric + list(ADDED_FEATURES), categorical


def prepare_handover_input(frame):
    numeric, categorical = feature_columns()
    required = numeric + categorical
    if set(required).difference(frame.columns):
        raise ValueError('Missing required handover model features')
    result = frame[required].copy()
    for name in numeric:
        result[name] = _number(result, name)
    for name in categorical:
        result[name] = result[name].astype(object).where(result[name].notna(), np.nan)
    return result


def build_handover_order_features(tables, geolocation=None):
    """Pure raw-to-inference builder using the same approval-time history."""
    base = build_backlog_order_features(tables, 'geo', '7_14d', geolocation)
    enriched = add_handover_features(base, tables)
    numeric, categorical = feature_columns()
    return enriched[['order_id', 'order_purchase_timestamp', 'prediction_time'] + numeric + categorical]
