"""Disjoint feature groups for a 2x2 geographic/workload ablation.

G = nine postal features + three distance ratios; L = five workload ratios.
The remaining six cost/density/calendar interactions (O) are absent from new
variants. Existing full83 provides the conditional O increment over G+L.
"""
import numpy as np

from scripts.delay_engineering_features import (
    BASE_NUMERIC_FEATURES, CATEGORICAL_FEATURES, INTERACTION_NUMERIC_FEATURES, ENGINEERING_NUMERIC_FEATURES,
    build_engineering_order_features, _number, _ratio,
)
from scripts.delay_geo_features import GEO_NUMERIC_FEATURES
from scripts.delay_pending_features import build_pending_order_features

GEOGRAPHIC_FEATURES = list(GEO_NUMERIC_FEATURES) + [
    'geo_distance_per_promise_day', 'geo_promise_days_per_100km', 'geo_freight_per_km',
]
WORKLOAD_FEATURES = [
    'seller_pending_vs_completed_30d', 'route_pending_vs_completed_30d',
    'seller_overdue_pending_share_30d', 'route_overdue_pending_share_30d',
    'global_overdue_pending_share_30d',
]
OTHER_FEATURES = [name for name in INTERACTION_NUMERIC_FEATURES
                  if name not in GEOGRAPHIC_FEATURES + WORKLOAD_FEATURES]
VARIANT_FEATURES = {
    'geo_only': list(BASE_NUMERIC_FEATURES) + GEOGRAPHIC_FEATURES,
    'load_only': list(BASE_NUMERIC_FEATURES) + WORKLOAD_FEATURES,
    'geo_load': list(BASE_NUMERIC_FEATURES) + GEOGRAPHIC_FEATURES + WORKLOAD_FEATURES,
}
# Keep the relative ordering of every surviving full83 column unchanged.
VARIANT_FEATURES = {variant: [name for name in ENGINEERING_NUMERIC_FEATURES if name in names]
                    for variant, names in VARIANT_FEATURES.items()}
FEATURE_SETS = {variant: f'ablation_{variant}_approval' for variant in VARIANT_FEATURES}
FEATURE_SET_VARIANTS = {name: variant for variant, name in FEATURE_SETS.items()}
GEOGRAPHIC_FEATURE_SETS = {FEATURE_SETS['geo_only'], FEATURE_SETS['geo_load']}


def add_workload_interactions(frame):
    """The same five existing ratios, without requiring geographic columns."""
    if set(WORKLOAD_FEATURES).intersection(frame.columns):
        raise ValueError('Workload interaction columns already exist')
    result = frame.copy()
    for group in ('seller', 'route'):
        completed = _number(frame, f'{group}_completed_90d')
        result[f'{group}_pending_vs_completed_30d'] = _ratio(
            _number(frame, f'{group}_pending_30d'), completed.where(completed.ge(0)) / 3 + 1)
    for group in ('seller', 'route', 'global'):
        result[f'{group}_overdue_pending_share_30d'] = _ratio(
            _number(frame, f'{group}_pending_overdue_30d'), _number(frame, f'{group}_pending_30d'))
    return result


def prepare_ablation_input(frame, variant):
    if variant not in VARIANT_FEATURES:
        raise ValueError(f'Unknown ablation variant: {variant}')
    numeric = VARIANT_FEATURES[variant]
    names = numeric + list(CATEGORICAL_FEATURES)
    missing = set(names).difference(frame.columns)
    if missing:
        raise ValueError(f'Missing ablation feature columns: {sorted(missing)}')
    result = frame[names].copy()
    for column in numeric:
        result[column] = _number(result, column)
    for column in CATEGORICAL_FEATURES:
        result[column] = result[column].astype(object).where(result[column].notna(), np.nan)
    return result


def build_ablation_order_features(tables, variant, geolocation=None):
    if variant not in VARIANT_FEATURES:
        raise ValueError(f'Unknown ablation variant: {variant}')
    if variant == 'load_only':
        enriched = add_workload_interactions(build_pending_order_features(tables))
    else:
        if geolocation is None:
            raise ValueError('Geographic ablation inference requires the static geolocation reference table')
        enriched = build_engineering_order_features(tables, geolocation, include_dispatch=False)
    return enriched[['order_id', 'order_purchase_timestamp', 'prediction_time']
                    + VARIANT_FEATURES[variant] + list(CATEGORICAL_FEATURES)]
