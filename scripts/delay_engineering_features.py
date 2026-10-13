"""Approval-time geographic and deterministic interactions; dispatch sensitivity.

The 83-feature variant combines the existing 60 features with nine geographic
features and fourteen interactions. The 91-feature variant additionally uses
shipping deadlines, whose approval-time availability is an unverified assumption.
No statistics are fitted across orders by the interaction transform.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.delay_dispatch_features import DISPATCH_NUMERIC_FEATURES, add_dispatch_features
from scripts.delay_geo_features import GEO_NUMERIC_FEATURES, add_geo_features
from scripts.delay_pending_features import (
    NUMERIC_FEATURES as BASE_NUMERIC_FEATURES, CATEGORICAL_FEATURES,
    _build_pending_components,
)
from scripts.delay_features import load_olist_tables

GEO_FILENAME = 'olist_geolocation_dataset.csv'
INTERACTION_NUMERIC_FEATURES = [
    'geo_distance_per_promise_day', 'geo_promise_days_per_100km',
    'seller_pending_vs_completed_30d', 'route_pending_vs_completed_30d',
    'seller_overdue_pending_share_30d', 'route_overdue_pending_share_30d',
    'global_overdue_pending_share_30d', 'product_density_g_cm3',
    'freight_per_item', 'price_per_item', 'approval_weekday', 'approval_hour',
    'promise_weekday', 'geo_freight_per_km',
]
ENGINEERING_NUMERIC_FEATURES = list(BASE_NUMERIC_FEATURES) + GEO_NUMERIC_FEATURES + INTERACTION_NUMERIC_FEATURES
DISPATCH_ENGINEERING_NUMERIC_FEATURES = ENGINEERING_NUMERIC_FEATURES + DISPATCH_NUMERIC_FEATURES
FEATURE_SETS = {'base': 'pending_seller_route_budget_90d',
                'geo': 'geo_engineered_approval', 'dispatch': 'dispatch_geo_engineered_approval'}


def _number(frame, column):
    return pd.to_numeric(frame[column], errors='coerce').replace([np.inf, -np.inf], np.nan)


def _ratio(numerator, denominator):
    """Undefined/invalid nonnegative ratios stay missing, never become infinity."""
    return numerator.where(numerator.ge(0)) / denominator.where(denominator.gt(0))


def add_engineering_interactions(frame):
    if set(INTERACTION_NUMERIC_FEATURES).intersection(frame.columns):
        raise ValueError('Interaction columns already exist')
    result = frame.copy()
    distance, promise = _number(frame, 'geo_primary_distance_km'), _number(frame, 'estimated_delivery_days')
    result['geo_distance_per_promise_day'] = _ratio(distance, promise)
    result['geo_promise_days_per_100km'] = _ratio(promise, distance / 100)
    for group in ('seller', 'route'):
        completed = _number(frame, f'{group}_completed_90d')
        result[f'{group}_pending_vs_completed_30d'] = _ratio(
            _number(frame, f'{group}_pending_30d'), completed.where(completed.ge(0)) / 3 + 1)
    for group in ('seller', 'route', 'global'):
        result[f'{group}_overdue_pending_share_30d'] = _ratio(
            _number(frame, f'{group}_pending_overdue_30d'), _number(frame, f'{group}_pending_30d'))
    # Ratio of mean product weight to mean volume, not a measured parcel density.
    result['product_density_g_cm3'] = _ratio(_number(frame, 'product_weight_g_mean'), _number(frame, 'product_volume_cm3_mean'))
    result['freight_per_item'] = _ratio(_number(frame, 'total_freight_value'), _number(frame, 'item_count'))
    result['price_per_item'] = _ratio(_number(frame, 'total_price'), _number(frame, 'item_count'))
    approval = pd.to_datetime(frame['prediction_time'], errors='coerce')
    result['approval_weekday'], result['approval_hour'] = approval.dt.dayofweek, approval.dt.hour
    # Calendar offset reproduces the promise date used by the original features.
    valid_days = promise.where(promise.ge(0) & promise.eq(np.floor(promise)))
    promised = approval.dt.normalize() + pd.to_timedelta(valid_days, unit='D')
    result['promise_weekday'] = promised.dt.dayofweek
    result['geo_freight_per_km'] = _ratio(_number(frame, 'total_freight_value'), distance)
    result[INTERACTION_NUMERIC_FEATURES] = result[INTERACTION_NUMERIC_FEATURES].replace([np.inf, -np.inf], np.nan)
    return result


def build_engineering_order_features(tables, geolocation, *, include_dispatch=True):
    enriched, _ = _build_pending_components(tables)
    enriched = add_engineering_interactions(add_geo_features(enriched, tables, geolocation))
    if include_dispatch:
        enriched = add_dispatch_features(enriched, tables)
    numeric = DISPATCH_ENGINEERING_NUMERIC_FEATURES if include_dispatch else ENGINEERING_NUMERIC_FEATURES
    return enriched[['order_id', 'order_purchase_timestamp', 'prediction_time'] + numeric + list(CATEGORICAL_FEATURES)]


def build_engineering_delay_dataset(raw_dir):
    tables = load_olist_tables(Path(raw_dir))
    enriched, events = _build_pending_components(tables)
    geolocation = pd.read_csv(Path(raw_dir) / GEO_FILENAME)
    enriched = add_dispatch_features(add_engineering_interactions(add_geo_features(enriched, tables, geolocation)), tables)
    metadata = ['order_id', 'order_purchase_timestamp', 'prediction_time', 'label_available_time', 'delayed']
    return events[metadata].merge(enriched[['order_id'] + DISPATCH_ENGINEERING_NUMERIC_FEATURES + list(CATEGORICAL_FEATURES)],
                                  on='order_id', how='left', validate='one_to_one', sort=False)


def prepare_engineering_input(frame, variant):
    choices = {'base': list(BASE_NUMERIC_FEATURES), 'geo': ENGINEERING_NUMERIC_FEATURES,
               'dispatch': DISPATCH_ENGINEERING_NUMERIC_FEATURES}
    if variant not in choices:
        raise ValueError(f'Unknown feature variant: {variant}')
    numeric = choices[variant]
    names = numeric + list(CATEGORICAL_FEATURES)
    missing = set(names).difference(frame.columns)
    if missing:
        raise ValueError(f'Missing engineering feature columns: {sorted(missing)}')
    result = frame[names].copy()
    for column in numeric:
        result[column] = _number(result, column)
    for column in CATEGORICAL_FEATURES:
        result[column] = result[column].astype(object).where(result[column].notna(), np.nan)
    return result
