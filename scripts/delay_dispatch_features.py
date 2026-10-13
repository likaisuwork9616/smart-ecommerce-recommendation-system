"""Item dispatch deadlines and promised-delivery slack at approval.

``shipping_limit_date`` is a contractual dispatch deadline, not an observed
carrier or delivery event. The Olist export has no deadline-change or item
ingestion timestamp. Using the exported value at approval therefore requires
an as-of availability assumption; this feature family must be evaluated as a
separate sensitivity experiment rather than asserted to be deployable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


DISPATCH_NUMERIC_FEATURES = [
    "dispatch_limit_min_hours_from_approval",
    "dispatch_limit_max_hours_from_approval",
    "dispatch_limit_mean_hours_from_approval",
    "dispatch_limit_spread_hours",
    "promise_after_latest_dispatch_days",
    "past_deadline_item_ratio",
    "missing_limit_item_ratio",
    "primary_item_dispatch_limit_hours",
]


def _naive_timestamps(values: pd.Series, name: str) -> pd.Series:
    """Coerce invalid timestamps while rejecting timezone-aware input."""
    try:
        result = pd.to_datetime(values, errors="coerce", format="mixed")
    except ValueError as error:
        raise ValueError(f"{name} must contain timezone-naive timestamps") from error
    if result.dt.tz is not None:
        raise ValueError(f"{name} must contain timezone-naive timestamps")
    return result


def add_dispatch_features(
    features: pd.DataFrame, tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Return a copy with eight deadline features, preserving query row order.

    Queries use ``prediction_time`` as approval. Deadlines are aggregated over
    all order items; invalid/missing deadlines do not participate in min, max,
    mean, spread or past-deadline ratios. The past ratio uses valid deadlines
    as its denominator and is strictly ``deadline < approval``. Missingness
    uses all items as its denominator. With items but no valid deadline, only
    missingness is 1; with no items, all eight values remain missing.

    Promised-delivery slack ends at midnight after the estimated calendar
    date, and subtracts the latest item deadline in fractional days. The
    representative item's deadline follows the existing primary-item rule:
    highest price, then lowest item sequence, with missing prices last.
    Actual carrier/delivery timestamps and final order status are never read.
    """
    required_queries = {"order_id", "prediction_time"}
    required_orders = {"order_id", "order_estimated_delivery_date"}
    required_items = {"order_id", "order_item_id", "price"}
    for frame, required, name in (
        (features, required_queries, "dispatch queries"),
        (tables["orders"], required_orders, "dispatch orders"),
        (tables["order_items"], required_items, "dispatch items"),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Missing {name} columns: {sorted(missing)}")
    if features.order_id.isna().any() or features.order_id.duplicated().any():
        raise ValueError("Dispatch query order IDs must be unique and non-null")
    orders = tables["orders"]
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError("Dispatch source order IDs must be unique and non-null")
    items = tables["order_items"].copy()
    if items[["order_id", "order_item_id"]].isna().any(axis=None):
        raise ValueError("Dispatch item order IDs and item sequences must be non-null")
    if items.duplicated(["order_id", "order_item_id"]).any():
        raise ValueError("Dispatch item sequences must be unique within each order")
    overlap = set(DISPATCH_NUMERIC_FEATURES).intersection(features.columns)
    if overlap:
        raise ValueError(f"Dispatch features already exist: {sorted(overlap)}")

    approvals = _naive_timestamps(features.prediction_time, "Query approval timestamps")
    promises = _naive_timestamps(
        orders.order_estimated_delivery_date, "Estimated delivery timestamps",
    )
    deadline_values = (
        items.shipping_limit_date if "shipping_limit_date" in items
        else pd.Series(pd.NaT, index=items.index)
    )
    items["deadline"] = _naive_timestamps(deadline_values, "Dispatch limit timestamps")
    output = features.copy()
    if items.empty or features.empty:
        output[DISPATCH_NUMERIC_FEATURES] = np.nan
        return output

    summary = items.groupby("order_id", sort=False).agg(
        item_count=("order_item_id", "size"),
        valid_count=("deadline", "count"),
        deadline_min=("deadline", "min"),
        deadline_max=("deadline", "max"),
        deadline_mean=("deadline", "mean"),
    )
    approval_lookup = pd.Series(approvals.to_numpy(), index=features.order_id)
    item_approvals = items.order_id.map(approval_lookup)
    past = items.deadline.lt(item_approvals)
    past_count = past.groupby(items.order_id, sort=False).sum()
    summary["past_ratio"] = past_count.div(summary.valid_count.where(summary.valid_count > 0))
    summary["missing_ratio"] = 1. - summary.valid_count.div(summary.item_count)
    primary = (
        items.sort_values(
            ["order_id", "price", "order_item_id"], ascending=[True, False, True],
            na_position="last", kind="stable",
        )
        .drop_duplicates("order_id")
        .set_index("order_id").deadline
    )
    query_min = features.order_id.map(summary.deadline_min)
    query_max = features.order_id.map(summary.deadline_max)
    query_mean = features.order_id.map(summary.deadline_mean)
    promise_lookup = pd.Series(promises.to_numpy(), index=orders.order_id)
    promised_end = features.order_id.map(promise_lookup).dt.normalize() + pd.Timedelta(days=1)
    values = pd.DataFrame(index=features.index)
    for statistic, deadlines in (("min", query_min), ("max", query_max), ("mean", query_mean)):
        values[f"dispatch_limit_{statistic}_hours_from_approval"] = (
            deadlines - approvals
        ).dt.total_seconds() / 3600.
    values["dispatch_limit_spread_hours"] = (query_max - query_min).dt.total_seconds() / 3600.
    values["promise_after_latest_dispatch_days"] = (
        promised_end - query_max
    ).dt.total_seconds() / 86400.
    values["past_deadline_item_ratio"] = (
        features.order_id.map(summary.past_ratio).where(approvals.notna())
    )
    values["missing_limit_item_ratio"] = features.order_id.map(summary.missing_ratio)
    values["primary_item_dispatch_limit_hours"] = (
        features.order_id.map(primary) - approvals
    ).dt.total_seconds() / 3600.
    output[DISPATCH_NUMERIC_FEATURES] = (
        values[DISPATCH_NUMERIC_FEATURES].astype(float).replace([np.inf, -np.inf], np.nan).to_numpy()
    )
    return output
