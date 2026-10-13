"""Approval-time route/promised-delivery features from strictly past outcomes.

The rolling window covers delivery timestamps in [approval - 90 days, approval).
Delivery durations use normalized calendar dates, matching the existing promised
days feature and target; these are not the fractional-day history means.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.delay_features import (
    CATEGORICAL_FEATURES as BASE_CATEGORICAL_FEATURES,
    FEATURES as BASE_FEATURES,
    NUMERIC_FEATURES as BASE_NUMERIC_FEATURES,
    add_delay_target,
    build_order_features,
    load_olist_tables,
)


ROUTE_NUMERIC_FEATURES = [
    "global_completed_90d",
    "route_completed_90d",
    "global_delivery_p90_calendar_days_90d",
    "route_delivery_p50_calendar_days_90d",
    "route_delivery_p90_calendar_days_90d",
    "route_promise_margin_p90_days",
    "route_promise_ratio_p90",
    "route_promise_cdf_90d",
]
ROUTE_CATEGORICAL_FEATURES = ["state_route"]
NUMERIC_FEATURES = list(BASE_NUMERIC_FEATURES) + ROUTE_NUMERIC_FEATURES
CATEGORICAL_FEATURES = list(BASE_CATEGORICAL_FEATURES) + ROUTE_CATEGORICAL_FEATURES
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


class _RollingDistribution:
    """Fenwick frequencies provide exact order statistics without re-sorting.

    Coordinates are integer calendar durations. A coordinate list may include
    future events, but only active past-event frequencies affect any statistic.
    """

    def __init__(self, coordinates):
        self.coordinates = coordinates
        self.tree = [0] * (len(coordinates) + 1)
        self.count = 0

    def update(self, coordinate_position, delta):
        self.count += delta
        position = coordinate_position + 1
        while position < len(self.tree):
            self.tree[position] += delta
            position += position & -position

    def _kth(self, rank):
        """Return the coordinate at zero-based rank in the active multiset."""
        position = 0
        bit = 1 << (len(self.coordinates).bit_length() - 1)
        while bit:
            candidate = position + bit
            if candidate < len(self.tree) and self.tree[candidate] <= rank:
                rank -= self.tree[candidate]
                position = candidate
            bit >>= 1
        return float(self.coordinates[position])

    def quantile(self, probability):
        if not self.count:
            return np.nan
        rank = (self.count - 1) * probability
        lower = int(np.floor(rank))
        upper = int(np.ceil(rank))
        value = self._kth(lower)
        # Matches np.quantile(method='linear'), including interpolated values.
        return value + (self._kth(upper) - value) * (rank - lower)

    def count_at_or_below(self, value):
        position = int(np.searchsorted(self.coordinates, value, side="right"))
        count = 0
        while position:
            count += self.tree[position]
            position -= position & -position
        return count


def _timestamps(values, name, *, allow_missing=False):
    result = pd.to_datetime(values, errors="coerce")
    if result.dt.tz is not None:
        raise ValueError(f"{name} must be timezone-naive")
    if not allow_missing and result.isna().any():
        raise ValueError(f"{name} must contain valid non-null timestamps")
    return result


def _route_keys(frame):
    # Unknown endpoints do not pool into an artificial unknown route.
    return [
        None if pd.isna(seller) or pd.isna(customer) else (str(seller), str(customer))
        for seller, customer in zip(frame["primary_seller_state"], frame["customer_state"])
    ]


def add_route_promise_features(
    features: pd.DataFrame,
    events: pd.DataFrame,
    *,
    window_days=90,
    prior_strength=20,
) -> pd.DataFrame:
    """Add exact rolling quantiles and promised-day CDF for seller -> customer.

    ``events`` contains one eligible delivered order per row, with its approval
    and delivery/label-availability timestamp. Only completed events strictly
    before each query's approval enter that query's rolling distribution. No
    delayed label, order ID or current outcome is used as a model feature.

    Route quantiles fall back to the same query's global quantiles when the
    route has no completed history. CDF = (route durations <= current promise
    + prior_strength * global CDF) / (route count + prior_strength). A completely
    empty global history produces missing quantiles/CDF, while zero counts
    remain meaningful. Missing approvals produce missing numeric features.
    Query row order and index are preserved, and input frames are not modified.
    """
    required = {"order_id", "prediction_time", "customer_state", "primary_seller_state"}
    for frame, columns, name in (
        (features, required | {"estimated_delivery_days"}, "features"),
        (events, required | {"label_available_time"}, "events"),
    ):
        missing = columns.difference(frame.columns)
        if missing:
            raise ValueError(f"Missing {name} columns: {sorted(missing)}")
        if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
            raise ValueError(f"{name} must have one row per non-null order_id")
    if not np.isfinite(window_days) or window_days <= 0:
        raise ValueError("window_days must be finite and positive")
    if not np.isfinite(prior_strength) or prior_strength <= 0:
        raise ValueError("prior_strength must be finite and positive")

    output = features.copy()
    query_dates = _timestamps(features["prediction_time"], "prediction_time", allow_missing=True)
    event_frame = events.copy()
    event_frame["prediction_time"] = _timestamps(event_frame["prediction_time"], "historical prediction_time")
    event_frame["label_available_time"] = _timestamps(event_frame["label_available_time"], "label_available_time")
    if (event_frame["label_available_time"] < event_frame["prediction_time"]).any():
        raise ValueError("Historical delivery must not precede its approval")
    event_frame = event_frame.sort_values(["label_available_time", "order_id"], kind="stable").reset_index(drop=True)
    durations = (
        event_frame["label_available_time"].dt.normalize()
        - event_frame["prediction_time"].dt.normalize()
    ).dt.days.to_numpy(dtype=np.int64)
    coordinates = np.unique(durations)
    duration_positions = np.searchsorted(coordinates, durations)
    event_times = event_frame["label_available_time"].to_numpy(dtype="datetime64[ns]").view("int64")
    query_times = query_dates.to_numpy(dtype="datetime64[ns]").view("int64")
    valid_positions = np.flatnonzero(query_dates.notna().to_numpy())
    query_order = valid_positions[np.argsort(query_times[valid_positions], kind="stable")]
    event_routes = _route_keys(event_frame)
    query_routes = _route_keys(features)
    promises = pd.to_numeric(features["estimated_delivery_days"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    window_ns = int(pd.Timedelta(days=window_days).value)

    result = np.full((len(features), len(ROUTE_NUMERIC_FEATURES)), np.nan, dtype=float)
    global_distribution = _RollingDistribution(coordinates)
    route_distributions = {}
    add_position = 0
    remove_position = 0

    def update(event_position, delta):
        duration_position = int(duration_positions[event_position])
        global_distribution.update(duration_position, delta)
        route = event_routes[event_position]
        if route is not None:
            if route not in route_distributions:
                route_distributions[route] = _RollingDistribution(coordinates)
            route_distributions[route].update(duration_position, delta)

    for query_position in query_order:
        query_time = query_times[query_position]
        while add_position < len(event_times) and event_times[add_position] < query_time:
            update(add_position, 1)
            add_position += 1
        lower_bound = query_time - window_ns
        while remove_position < add_position and event_times[remove_position] < lower_bound:
            update(remove_position, -1)
            remove_position += 1

        route = route_distributions.get(query_routes[query_position])
        route_count = route.count if route is not None else 0
        global_p90 = global_distribution.quantile(.9)
        if route_count:
            route_p50 = route.quantile(.5)
            route_p90 = route.quantile(.9)
        else:
            route_p50 = global_distribution.quantile(.5)
            route_p90 = global_p90
        promise = promises[query_position]
        finite_promise = np.isfinite(promise)
        margin = promise - route_p90 if finite_promise else np.nan
        ratio = promise / route_p90 if finite_promise and route_p90 > 0 else np.nan
        cdf = np.nan
        if finite_promise and global_distribution.count:
            global_cdf = global_distribution.count_at_or_below(promise) / global_distribution.count
            route_at_or_below = route.count_at_or_below(promise) if route_count else 0
            cdf = (route_at_or_below + prior_strength * global_cdf) / (route_count + prior_strength)
        result[query_position] = (
            global_distribution.count, route_count, global_p90, route_p50,
            route_p90, margin, ratio, cdf,
        )

    output[ROUTE_NUMERIC_FEATURES] = result
    output["state_route"] = pd.Series(
        [np.nan if route is None else f"{route[0]}->{route[1]}" for route in query_routes],
        index=output.index, dtype=object,
    )
    return output


def _build_route_components(tables):
    base = build_order_features(tables)
    events = add_delay_target(base, tables["orders"])
    return add_route_promise_features(base, events), events


def build_route_order_features(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build raw inference features; historical outcomes become usable on delivery."""
    enriched, _ = _build_route_components(tables)
    return enriched


def build_route_delay_dataset(raw_dir: Path) -> pd.DataFrame:
    """Keep exactly the original labeled cohort and add the route/promise columns."""
    tables = load_olist_tables(raw_dir)
    enriched, events = _build_route_components(tables)
    return events.merge(
        enriched[["order_id"] + ROUTE_NUMERIC_FEATURES + ROUTE_CATEGORICAL_FEATURES],
        on="order_id", how="left", validate="one_to_one", sort=False,
    )
