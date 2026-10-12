"""Point-in-time delivery history, using only completed outcomes known at approval.

Windows are based on delivery-event time: [prediction_time - 90 days,
prediction_time). These statistics describe recently completed eligible orders,
not all pending orders; slow unfinished and cancelled orders are absent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.delay_features import (
    CATEGORICAL_FEATURES,
    FEATURES as BASE_FEATURES,
    NUMERIC_FEATURES as BASE_NUMERIC_FEATURES,
    add_delay_target,
    build_order_features,
    load_olist_tables,
)


HISTORY_WINDOW_DAYS = 90
HISTORY_PRIOR_RATE = 0.05
HISTORY_PRIOR_STRENGTH = 20.0
HISTORY_NUMERIC_FEATURES = [
    "global_completed_90d", "global_delay_rate_90d", "global_delivery_days_90d",
    "seller_completed_90d", "seller_delay_rate_90d", "seller_delivery_days_90d",
    "route_completed_90d", "route_delay_rate_90d", "route_delivery_days_90d",
    "route_promise_margin_days",
]
NUMERIC_FEATURES = list(BASE_NUMERIC_FEATURES) + HISTORY_NUMERIC_FEATURES
FEATURES = list(BASE_FEATURES) + HISTORY_NUMERIC_FEATURES


def build_primary_sellers(order_items: pd.DataFrame) -> pd.DataFrame:
    """Internal order-to-seller lookup, matching v1 highest-price/item-sequence ties."""
    columns = ["order_id", "order_item_id", "price", "seller_id"]
    missing = set(columns).difference(order_items.columns)
    if missing:
        raise ValueError(f"Missing item columns: {sorted(missing)}")
    if order_items.duplicated(["order_id", "order_item_id"]).any():
        raise ValueError("Order item sequences must be unique within each order")
    return (
        order_items[columns]
        .sort_values(["order_id", "price", "order_item_id"], ascending=[True, False, True], na_position="last")
        .drop_duplicates("order_id")[["order_id", "seller_id"]]
        .rename(columns={"seller_id": "primary_seller_id"})
        .reset_index(drop=True)
    )


def _timestamps(values, name, *, allow_missing=False):
    result = pd.to_datetime(values, errors="coerce")
    if result.dt.tz is not None:
        raise ValueError(f"{name} must be timezone-naive")
    if not allow_missing and result.isna().any():
        raise ValueError(f"{name} must contain valid non-null timestamps")
    return result


def _positions_by_key(keys):
    result = {}
    for position, key in enumerate(keys):
        if key is not None:
            result.setdefault(key, []).append(position)
    return result


def _window_sums(event_times, delayed, durations, query_times, window_ns):
    """Sorted delivery-event prefixes allow two binary searches per prediction."""
    lower = np.searchsorted(event_times, query_times - window_ns, side="left")
    upper = np.searchsorted(event_times, query_times, side="left")
    delay_prefix = np.concatenate(([0.0], np.cumsum(delayed, dtype=float)))
    duration_prefix = np.concatenate(([0.0], np.cumsum(durations, dtype=float)))
    return (
        (upper - lower).astype(float),
        delay_prefix[upper] - delay_prefix[lower],
        duration_prefix[upper] - duration_prefix[lower],
    )


def _group_window_sums(event_keys, query_keys, event_times, delayed, durations, query_times, window_ns):
    counts = np.zeros(len(query_times), dtype=float)
    delay_sums = np.zeros(len(query_times), dtype=float)
    duration_sums = np.zeros(len(query_times), dtype=float)
    event_groups = _positions_by_key(event_keys)
    for key, query_positions in _positions_by_key(query_keys).items():
        if key not in event_groups:
            continue
        event_positions = np.asarray(event_groups[key], dtype=int)
        query_positions = np.asarray(query_positions, dtype=int)
        values = _window_sums(
            event_times[event_positions], delayed[event_positions], durations[event_positions],
            query_times[query_positions], window_ns,
        )
        counts[query_positions], delay_sums[query_positions], duration_sums[query_positions] = values
    return counts, delay_sums, duration_sums


def _route_keys(frame):
    return [
        None if pd.isna(customer) or pd.isna(seller) else (str(customer), str(seller))
        for customer, seller in zip(frame["customer_state"], frame["primary_seller_state"])
    ]


def add_delivery_history(
    features: pd.DataFrame,
    events: pd.DataFrame,
    primary_sellers: pd.DataFrame,
    *,
    window_days=HISTORY_WINDOW_DAYS,
    prior_rate=HISTORY_PRIOR_RATE,
    prior_strength=HISTORY_PRIOR_STRENGTH,
) -> pd.DataFrame:
    """Enrich predictions without consuming their own or future outcome labels.

    ``events`` has one eligible completed order per row, with order_id,
    prediction_time, label_available_time, delayed, customer_state and
    primary_seller_state. ``primary_sellers`` maps historical and current
    order_id to primary_seller_id. Missing seller/route keys do not pool into
    an artificial unknown group. Query row order and index are preserved.

    Rates use 20 pseudo observations by default. Global rates shrink to the
    fixed 0.05 prior; seller/route rates shrink to that query's global rate.
    Durations are fractional days since approval and fall back only to the
    same query's global completed-history mean. Missing approval timestamps
    yield missing history features, rather than pretending to have a history.
    """
    required_features = {"order_id", "prediction_time", "estimated_delivery_days",
                         "customer_state", "primary_seller_state"}
    required_events = {"order_id", "prediction_time", "label_available_time", "delayed",
                       "customer_state", "primary_seller_state"}
    for frame, required, name in (
        (features, required_features, "features"),
        (events, required_events, "events"),
        (primary_sellers, {"order_id", "primary_seller_id"}, "primary_sellers"),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Missing {name} columns: {sorted(missing)}")
        if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
            raise ValueError(f"{name} must have one row per non-null order_id")
    if window_days <= 0 or prior_strength <= 0 or not 0 <= prior_rate <= 1:
        raise ValueError("Require positive window/prior strength and a prior rate in [0, 1]")
    if not events["delayed"].isin([0, 1]).all():
        raise ValueError("Historical delayed labels must be binary")

    output = features.copy()
    query_dates = _timestamps(features["prediction_time"], "prediction_time", allow_missing=True)
    valid_queries = query_dates.notna().to_numpy()
    event_frame = events.copy()
    event_frame["label_available_time"] = _timestamps(event_frame["label_available_time"], "label_available_time")
    event_frame["prediction_time"] = _timestamps(event_frame["prediction_time"], "historical prediction_time")
    if (event_frame["label_available_time"] < event_frame["prediction_time"]).any():
        raise ValueError("Historical delivery must not precede its approval")
    # Stable tie ordering makes cumulative floating-point sums independent of input order.
    event_frame = event_frame.sort_values(["label_available_time", "order_id"], kind="stable").reset_index(drop=True)
    durations = (
        (event_frame["label_available_time"] - event_frame["prediction_time"]).dt.total_seconds() / 86400
    ).to_numpy(dtype=float)
    event_times = event_frame["label_available_time"].to_numpy(dtype="datetime64[ns]").view("int64")
    query_times = query_dates.to_numpy(dtype="datetime64[ns]").view("int64").copy()
    # NaT is never queried. A harmless placeholder avoids integer underflow in lower bounds.
    query_times[~valid_queries] = 0
    delayed = event_frame["delayed"].to_numpy(dtype=float)
    window_ns = int(pd.Timedelta(days=window_days).value)
    counts, delay_sums, duration_sums = _window_sums(event_times, delayed, durations, query_times, window_ns)
    global_rate = (delay_sums + prior_strength * prior_rate) / (counts + prior_strength)
    global_duration = np.divide(duration_sums, counts, out=np.full(len(output), np.nan), where=counts > 0)
    output["global_completed_90d"] = counts
    output["global_delay_rate_90d"] = global_rate
    output["global_delivery_days_90d"] = global_duration

    seller_lookup = primary_sellers.set_index("order_id")["primary_seller_id"]

    def seller_keys(frame):
        return [None if pd.isna(value) else str(value) for value in frame["order_id"].map(seller_lookup)]

    for prefix, event_keys, query_keys in (
        ("seller", seller_keys(event_frame), seller_keys(features)),
        ("route", _route_keys(event_frame), _route_keys(features)),
    ):
        group_counts, group_delays, group_durations = _group_window_sums(
            event_keys, query_keys, event_times, delayed, durations, query_times, window_ns,
        )
        output[f"{prefix}_completed_90d"] = group_counts
        output[f"{prefix}_delay_rate_90d"] = (
            group_delays + prior_strength * global_rate
        ) / (group_counts + prior_strength)
        output[f"{prefix}_delivery_days_90d"] = np.divide(
            group_durations, group_counts, out=global_duration.copy(), where=group_counts > 0,
        )
    output["route_promise_margin_days"] = (
        pd.to_numeric(features["estimated_delivery_days"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        - output["route_delivery_days_90d"].to_numpy()
    )
    output.loc[~valid_queries, HISTORY_NUMERIC_FEATURES] = np.nan
    return output


def _build_history_components(tables):
    base = build_order_features(tables)
    events = add_delay_target(base, tables["orders"])
    primary_sellers = build_primary_sellers(tables["order_items"])
    enriched = add_delivery_history(base, events, primary_sellers)
    return enriched, events


def build_history_order_features(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build approval-time features for raw inference; internal IDs never enter X."""
    enriched, _ = _build_history_components(tables)
    return enriched


def build_history_delay_dataset(raw_dir: Path) -> pd.DataFrame:
    """Use exactly the v1 labeled cohort, adding point-in-time numeric history."""
    tables = load_olist_tables(raw_dir)
    enriched, events = _build_history_components(tables)
    return events.merge(
        enriched[["order_id"] + HISTORY_NUMERIC_FEATURES],
        on="order_id", how="left", validate="one_to_one", sort=False,
    )
