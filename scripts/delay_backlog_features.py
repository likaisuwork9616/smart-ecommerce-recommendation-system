"""As-of changes in overdue undelivered orders within a rolling 90-day cohort.

An order contributes at snapshot s when approval is in [s-90d,s), its
original promise expires by s, and delivery is missing or >=s. Final status
and target labels are never read. Cancellation timestamps are unavailable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.delay_ablation_features import VARIANT_FEATURES, build_ablation_order_features
from scripts.delay_engineering_features import CATEGORICAL_FEATURES, ENGINEERING_NUMERIC_FEATURES, _number, build_engineering_order_features
from scripts.delay_pending_features import _raw_approved_population

GROUPS = ('global', 'seller', 'route')
LAGS = (7, 14)
DAY_NS = int(pd.Timedelta(days=1).value)
WINDOW_NS = 90 * DAY_NS
LAG_FEATURES = {lag: [f'{group}_overdue_pending_{statistic}_{lag}d'
                      for group in GROUPS for statistic in ('lag', 'change', 'log_growth')]
                for lag in LAGS}
ADDED_FEATURES = [name for lag in LAGS for name in LAG_FEATURES[lag]]
VARIANTS = {'7d': (7,), '14d': (14,), '7_14d': (7, 14)}
FEATURE_SET_DESIGNS = {f'backlog_{backbone}_{variant}_approval': (backbone, variant)
                       for backbone in ('load', 'geo') for variant in VARIANTS}
GEOGRAPHIC_FEATURE_SETS = {name for name, (backbone, _) in FEATURE_SET_DESIGNS.items() if backbone == 'geo'}


def _keys(frame, group):
    if group == 'global':
        return ['global'] * len(frame)
    if group == 'seller':
        return [None if pd.isna(v) else str(v) for v in frame.primary_seller_id]
    return [None if pd.isna(s) or pd.isna(c) else (str(s), str(c))
            for s, c in zip(frame.primary_seller_state, frame.customer_state, strict=True)]


def overdue_snapshots(frame, tables):
    """Return counts at t, t-7d and t-14d using independent active intervals.

    Interval start=max(approval+1ns,promise calendar midnight+1day), end=
    min(delivery,approval+90days), both inclusive. Counting starts <=s minus
    ends <s preserves strict approval/delivery and the inclusive age boundary.
    Unknown group keys are missing, never a pooled group or fabricated zero.
    """
    required = {'order_id', 'prediction_time', 'primary_seller_id', 'primary_seller_state', 'customer_state'}
    if not required.issubset(frame):
        raise ValueError(f'Missing backlog query columns: {sorted(required.difference(frame))}')
    if (frame.order_id.isna().any() or frame.order_id.duplicated().any()
            or not frame.order_id.map(lambda v: isinstance(v, str) and bool(v.strip())).all()):
        raise ValueError('Require unique nonempty string query order IDs')
    times = pd.to_datetime(frame.prediction_time, errors='coerce', format='mixed')
    if times.dt.tz is not None:
        raise ValueError('Backlog timestamps must be timezone-naive')
    snapshots = [times - pd.Timedelta(days=lag) for lag in (0, 7, 14)]
    valid = times.notna().to_numpy()
    raw = _raw_approved_population(tables)
    approval = raw.order_approved_at.to_numpy(dtype='datetime64[ns]').view('int64')
    delivery = raw.order_delivered_customer_date.to_numpy(dtype='datetime64[ns]').view('int64')
    deadline = (raw.order_estimated_delivery_date.dt.normalize() + pd.Timedelta(days=1)).to_numpy(dtype='datetime64[ns]').view('int64')
    limit = np.iinfo(np.int64).max
    start = np.maximum(np.minimum(approval, limit - 1) + 1, deadline)
    end = np.minimum(np.minimum(approval, limit - WINDOW_NS) + WINDOW_NS,
                     np.where(raw.order_delivered_customer_date.notna(), delivery, limit))
    eligible = raw.order_estimated_delivery_date.notna().to_numpy() & (start <= end)
    output = {}
    for group in GROUPS:
        event_groups, query_groups = {}, {}
        for i, key in enumerate(_keys(raw, group)):
            if key is not None and eligible[i]:
                event_groups.setdefault(key, []).append(i)
        for i, key in enumerate(_keys(frame, group)):
            if key is not None and valid[i]:
                query_groups.setdefault(key, []).append(i)
        counts = np.full((len(frame), 3), np.nan)
        for key, positions in query_groups.items():
            events = event_groups.get(key, [])
            starts, ends = np.sort(start[events]), np.sort(end[events])
            for j, stamps in enumerate(snapshots):
                query = stamps.iloc[positions].to_numpy(dtype='datetime64[ns]').view('int64')
                counts[positions, j] = np.searchsorted(starts, query, side='right') - np.searchsorted(ends, query, side='left')
        if np.any(counts[np.isfinite(counts)] < 0):
            raise AssertionError('Overdue interval counts cannot be negative')
        output[group] = counts
    return output


def add_backlog_features(frame, tables):
    if set(ADDED_FEATURES).intersection(frame):
        raise ValueError('Backlog feature columns already exist')
    snapshots = overdue_snapshots(frame, tables)
    result = frame.copy()
    for lag_index, lag in enumerate(LAGS, start=1):
        for group in GROUPS:
            now, old = snapshots[group][:, 0], snapshots[group][:, lag_index]
            # Check an unchanged existing count when the caller supplies one.
            current_name = f'{group}_pending_overdue_90d'
            if current_name in frame:
                actual = _number(frame, current_name).to_numpy(dtype=float)
                valid = np.isfinite(now)
                if not np.array_equal(actual[valid], now[valid]):
                    raise ValueError('Current backlog differs from the frozen pending contract')
            result[f'{group}_overdue_pending_lag_{lag}d'] = old
            result[f'{group}_overdue_pending_change_{lag}d'] = now - old
            result[f'{group}_overdue_pending_log_growth_{lag}d'] = np.log1p(now) - np.log1p(old)
    return result[list(frame.columns) + ADDED_FEATURES]


def feature_columns(backbone, variant):
    if backbone not in ('load', 'geo') or variant not in VARIANTS:
        raise ValueError('Unknown backlog backbone or lag variant')
    numeric = list(VARIANT_FEATURES['load_only'] if backbone == 'load' else ENGINEERING_NUMERIC_FEATURES)
    numeric += [name for lag in VARIANTS[variant] for name in LAG_FEATURES[lag]]
    return numeric, list(CATEGORICAL_FEATURES)


def prepare_backlog_input(frame, backbone, variant):
    numeric, categorical = feature_columns(backbone, variant)
    if not set(numeric + categorical).issubset(frame):
        raise ValueError('Missing required backlog model features')
    output = frame[numeric + categorical].copy()
    for name in numeric:
        output[name] = _number(output, name)
    for name in categorical:
        output[name] = output[name].astype(object).where(output[name].notna(), np.nan)
    return output


def build_backlog_order_features(tables, backbone, variant, geolocation=None):
    numeric, categorical = feature_columns(backbone, variant)
    if backbone == 'load':
        frame = build_ablation_order_features(tables, 'load_only')
    else:
        if geolocation is None:
            raise ValueError('Geographic backlog inference requires geolocation')
        frame = build_engineering_order_features(tables, geolocation, include_dispatch=False)
    enriched = add_backlog_features(frame, tables)
    return enriched[['order_id', 'order_purchase_timestamp', 'prediction_time'] + numeric + categorical]
