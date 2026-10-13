"""Approval-time pending workload, including orders without delivery labels.

The raw population has a valid purchase and approval timestamp with approval
at or after purchase. Final order status is never consulted. Missing promised
dates still contribute workload counts but cannot establish overdue status.
Cancellation timestamps are unavailable, so approved cancelled orders can
remain pending in the 30/90-day windows until a delivery is recorded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.delay_budget_features import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES as BASE_NUMERIC_FEATURES,
    _build_budget_components,
)
from scripts.delay_features import load_olist_tables
from scripts.delay_history_features import build_primary_sellers


PENDING_NUMERIC_FEATURES = [
    f"{group}_{statistic}"
    for group in ("global", "seller", "route")
    for statistic in (
        "pending_30d", "pending_90d", "pending_mean_age_30d",
        "pending_overdue_30d", "pending_overdue_90d",
    )
]
NUMERIC_FEATURES = list(BASE_NUMERIC_FEATURES) + PENDING_NUMERIC_FEATURES
FEATURES = NUMERIC_FEATURES + list(CATEGORICAL_FEATURES)
FEATURE_SET = "pending_seller_route_budget_90d"
DAY_NS = int(pd.Timedelta(days=1).value)


class _PendingLedger:
    """Fenwick prefix counts, approval-day sums and overdue counts."""

    def __init__(self, approval_times, origin):
        self.approval_times = np.asarray(approval_times, dtype=np.int64)
        self.approval_days = (self.approval_times - origin) / DAY_NS
        self.count = np.zeros(len(self.approval_times) + 1, dtype=float)
        self.day_sum = np.zeros(len(self.approval_times) + 1, dtype=float)
        self.overdue = np.zeros(len(self.approval_times) + 1, dtype=float)
        self.totals = np.zeros(3, dtype=float)

    def update(self, position, count, overdue):
        day_sum = count * self.approval_days[position]
        self.totals += (count, day_sum, overdue)
        index = position + 1
        while index < len(self.count):
            self.count[index] += count
            self.day_sum[index] += day_sum
            self.overdue[index] += overdue
            index += index & -index

    def window(self, lower_time):
        # All active approvals precede the current query; totals are its upper
        # prefix. The lower prefix excludes only approvals strictly < lower.
        index = int(np.searchsorted(self.approval_times, lower_time, side="left"))
        count = day_sum = overdue = 0.
        while index:
            count += self.count[index]
            day_sum += self.day_sum[index]
            overdue += self.overdue[index]
            index -= index & -index
        return self.totals - (count, day_sum, overdue)


def _keys(frame):
    sellers = [None if pd.isna(value) else str(value) for value in frame["primary_seller_id"]]
    routes = [
        None if pd.isna(seller) or pd.isna(customer) else (str(seller), str(customer))
        for seller, customer in zip(frame["primary_seller_state"], frame["customer_state"])
    ]
    return sellers, routes


def _group_ledgers(keys, approval_times, origin):
    positions = {}
    for position, key in enumerate(keys):
        if key is not None:
            positions.setdefault(key, []).append(position)
    ledgers, addresses = {}, [None] * len(keys)
    for key, global_positions in positions.items():
        ledger = _PendingLedger(approval_times[global_positions], origin)
        ledgers[key] = ledger
        for local_position, global_position in enumerate(global_positions):
            addresses[global_position] = (ledger, local_position)
    return ledgers, addresses


def _raw_approved_population(tables):
    required_orders = ["order_id", "customer_id", "order_purchase_timestamp", "order_approved_at",
                       "order_delivered_customer_date", "order_estimated_delivery_date"]
    orders = tables["orders"][required_orders].copy()
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError("Raw orders must have unique non-null order IDs")
    for name in required_orders[2:]:
        orders[name] = pd.to_datetime(orders[name], errors="coerce", format="mixed")
        if orders[name].dt.tz is not None:
            raise ValueError(f"{name} must be timezone-naive")
    valid = orders[["order_purchase_timestamp", "order_approved_at"]].notna().all(axis=1)
    valid &= orders.order_approved_at.ge(orders.order_purchase_timestamp)
    orders = orders.loc[valid].copy()
    primary_sellers = build_primary_sellers(tables["order_items"]).set_index("order_id").primary_seller_id
    customer_states = tables["customers"].set_index("customer_id").customer_state
    seller_states = tables["sellers"].set_index("seller_id").seller_state
    orders["primary_seller_id"] = orders.order_id.map(primary_sellers)
    orders["customer_state"] = orders.customer_id.map(customer_states)
    orders["primary_seller_state"] = orders.primary_seller_id.map(seller_states)
    return orders.sort_values(["order_approved_at", "order_id"], kind="stable").reset_index(drop=True)


def add_pending_features(features: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Add workload from strictly earlier approvals and delivery information.

    Pending at t means delivered time is missing or >= t. Delivery exactly t
    remains unknown under the existing strict history convention. Windows
    include approval t-window and exclude approval t. Overdue starts at the
    midnight after the promised calendar date. Missing seller/route keys are
    not pooled: their group counts are zero and mean age is missing.
    """
    required = {"order_id", "prediction_time", "primary_seller_id", "primary_seller_state", "customer_state"}
    if not required.issubset(features.columns):
        raise ValueError(f"Missing pending query features: {sorted(required.difference(features.columns))}")
    if features.order_id.isna().any() or features.order_id.duplicated().any():
        raise ValueError("Pending query order IDs must be unique and non-null")
    queries = pd.to_datetime(features.prediction_time, errors="coerce", format="mixed")
    if queries.dt.tz is not None:
        raise ValueError("Query approval timestamps must be timezone-naive")
    raw = _raw_approved_population(tables)
    result = np.full((len(features), len(PENDING_NUMERIC_FEATURES)), np.nan)
    if raw.empty:
        valid = queries.notna().to_numpy()
        for start in (0, 5, 10):
            result[valid, start:start+5] = (0., 0., np.nan, 0., 0.)
        output = features.copy()
        output[PENDING_NUMERIC_FEATURES] = result
        return output
    approval_times = raw.order_approved_at.to_numpy(dtype="datetime64[ns]").view("int64")
    delivery_times = raw.order_delivered_customer_date.to_numpy(dtype="datetime64[ns]").view("int64")
    delivery_present = raw.order_delivered_customer_date.notna().to_numpy()
    deadlines = (raw.order_estimated_delivery_date.dt.normalize() + pd.Timedelta(days=1)).to_numpy(dtype="datetime64[ns]").view("int64")
    deadline_present = raw.order_estimated_delivery_date.notna().to_numpy()
    origin = int(raw.order_approved_at.min().normalize().value)
    global_ledger = _PendingLedger(approval_times, origin)
    seller_keys, route_keys = _keys(raw)
    seller_ledgers, seller_addresses = _group_ledgers(seller_keys, approval_times, origin)
    route_ledgers, route_addresses = _group_ledgers(route_keys, approval_times, origin)
    query_sellers, query_routes = _keys(features)
    delivery_order = np.flatnonzero(delivery_present)
    delivery_order = delivery_order[np.argsort(delivery_times[delivery_order], kind="stable")]
    deadline_order = np.flatnonzero(deadline_present)
    deadline_order = deadline_order[np.argsort(deadlines[deadline_order], kind="stable")]
    query_times = queries.to_numpy(dtype="datetime64[ns]").view("int64")
    query_order = np.flatnonzero(queries.notna().to_numpy())
    query_order = query_order[np.argsort(query_times[query_order], kind="stable")]
    active = np.zeros(len(raw), dtype=bool)
    overdue = np.zeros(len(raw), dtype=bool)
    approval_position = delivery_position = deadline_position = 0

    def update(position, count_delta, overdue_delta):
        global_ledger.update(position, count_delta, overdue_delta)
        for addresses in (seller_addresses, route_addresses):
            address = addresses[position]
            if address is not None:
                ledger, local_position = address
                ledger.update(local_position, count_delta, overdue_delta)

    for query_position in query_order:
        now = query_times[query_position]
        while approval_position < len(raw) and approval_times[approval_position] < now:
            position = approval_position
            if not delivery_present[position] or delivery_times[position] >= now:
                active[position] = True
                overdue[position] = deadline_present[position] and deadlines[position] <= now
                update(position, 1., float(overdue[position]))
            approval_position += 1
        while delivery_position < len(delivery_order) and delivery_times[delivery_order[delivery_position]] < now:
            position = delivery_order[delivery_position]
            if active[position]:
                update(position, -1., -float(overdue[position]))
                active[position] = False
                overdue[position] = False
            delivery_position += 1
        while deadline_position < len(deadline_order) and deadlines[deadline_order[deadline_position]] <= now:
            position = deadline_order[deadline_position]
            if active[position] and not overdue[position]:
                update(position, 0., 1.)
                overdue[position] = True
            deadline_position += 1
        ledgers = (global_ledger, seller_ledgers.get(query_sellers[query_position]), route_ledgers.get(query_routes[query_position]))
        now_days = (now - origin) / DAY_NS
        for group_position, ledger in enumerate(ledgers):
            if ledger is None:
                values = (0., 0., np.nan, 0., 0.)
            else:
                count30, approval_sum30, overdue30 = ledger.window(now - 30 * DAY_NS)
                count90, _, overdue90 = ledger.window(now - 90 * DAY_NS)
                mean_age = now_days - approval_sum30 / count30 if count30 else np.nan
                values = (count30, count90, mean_age, overdue30, overdue90)
            start = group_position * 5
            result[query_position, start:start+5] = values
    output = features.copy()
    output[PENDING_NUMERIC_FEATURES] = result
    return output


def _build_pending_components(tables):
    enriched, events = _build_budget_components(tables)
    return add_pending_features(enriched, tables), events


def build_pending_order_features(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build all inference rows with the 60-feature approval-time contract."""
    enriched, _ = _build_pending_components(tables)
    return enriched[["order_id", "order_purchase_timestamp", "prediction_time"] + FEATURES]


def build_pending_delay_dataset(raw_dir: Path) -> pd.DataFrame:
    """Use the unchanged eligible labeled cohort, with raw pending context."""
    enriched, events = _build_pending_components(load_olist_tables(raw_dir))
    metadata = ["order_id", "order_purchase_timestamp", "prediction_time", "label_available_time", "delayed"]
    return events[metadata].merge(enriched[["order_id"] + FEATURES], on="order_id", how="left", validate="one_to_one", sort=False)


def prepare_pending_input(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the 60-feature contract; learned imputation remains train-only."""
    missing = set(FEATURES).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing pending feature columns: {sorted(missing)}")
    features = frame[FEATURES].copy()
    for name in NUMERIC_FEATURES:
        features[name] = pd.to_numeric(features[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
    for name in CATEGORICAL_FEATURES:
        features[name] = features[name].astype(object).where(features[name].notna(), np.nan)
    return features
