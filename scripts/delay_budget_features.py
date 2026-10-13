"""Approval-time seller and route context for ranking a fixed alert budget.

The feature set extends the existing route/promise contract without changing
the labeled cohort. Completed-history features only consume delivery events
in [approval - 90 days, approval). Seller identity and coarse postal prefixes
come from the order's known customer and primary seller; they are categories,
not geographic distances or outcome encodings.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.delay_features import add_delay_target, build_order_features, load_olist_tables
from scripts.delay_history_features import (
    HISTORY_NUMERIC_FEATURES,
    add_delivery_history,
    build_primary_sellers,
)
from scripts.delay_route_features import (
    CATEGORICAL_FEATURES as ROUTE_CATEGORICAL_FEATURES,
    NUMERIC_FEATURES as ROUTE_NUMERIC_FEATURES,
    add_route_promise_features,
)


ADDITIONAL_HISTORY_FEATURES = [
    name for name in HISTORY_NUMERIC_FEATURES if name not in ROUTE_NUMERIC_FEATURES
]
INTERACTION_NUMERIC_FEATURES = [
    "seller_promise_margin_days",
    "seller_promise_ratio",
    "seller_delay_rate_excess_global",
    "route_delay_rate_excess_global",
]
CONTEXT_CATEGORICAL_FEATURES = [
    "primary_seller_id", "customer_zip_prefix3", "primary_seller_zip_prefix3",
]
NUMERIC_FEATURES = (
    list(ROUTE_NUMERIC_FEATURES) + ADDITIONAL_HISTORY_FEATURES + INTERACTION_NUMERIC_FEATURES
)
CATEGORICAL_FEATURES = list(ROUTE_CATEGORICAL_FEATURES) + CONTEXT_CATEGORICAL_FEATURES
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
FEATURE_SET = "seller_route_budget_90d"


def _postal_prefix3(values: pd.Series) -> pd.Series:
    """Normalize a Brazilian five-digit postal prefix, retaining leading zeroes.

    Null, fractional, negative and values above 99999 remain missing. An
    absent ZIP column is also missing; it cannot invent an unknown ZIP group.
    """
    numeric = pd.to_numeric(values, errors="coerce")
    valid = np.isfinite(numeric) & numeric.between(0, 99999) & numeric.eq(np.floor(numeric))
    result = pd.Series(np.nan, index=values.index, dtype=object)
    result.loc[valid] = (numeric.loc[valid].astype("int64") // 100).map(lambda value: f"{value:03d}")
    return result


def _lookup_postal_prefix3(table: pd.DataFrame, key: str, column: str) -> pd.Series:
    values = table[column] if column in table else pd.Series(np.nan, index=table.index)
    return pd.Series(_postal_prefix3(values).to_numpy(), index=table[key], dtype=object)


def _add_budget_context(
    enriched: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    primary_sellers: pd.DataFrame,
) -> pd.DataFrame:
    output = enriched.copy()
    seller_lookup = primary_sellers.set_index("order_id")["primary_seller_id"]
    output["primary_seller_id"] = output["order_id"].map(seller_lookup)
    customer_lookup = tables["orders"].set_index("order_id")["customer_id"]
    customer_zip = _lookup_postal_prefix3(tables["customers"], "customer_id", "customer_zip_code_prefix")
    seller_zip = _lookup_postal_prefix3(tables["sellers"], "seller_id", "seller_zip_code_prefix")
    output["customer_zip_prefix3"] = output["order_id"].map(customer_lookup).map(customer_zip)
    output["primary_seller_zip_prefix3"] = output["primary_seller_id"].map(seller_zip)

    promise = pd.to_numeric(output["estimated_delivery_days"], errors="coerce")
    seller_days = pd.to_numeric(output["seller_delivery_days_90d"], errors="coerce")
    output["seller_promise_margin_days"] = promise - seller_days
    output["seller_promise_ratio"] = promise.div(seller_days.where(seller_days > 0))
    for prefix in ("seller", "route"):
        output[f"{prefix}_delay_rate_excess_global"] = (
            output[f"{prefix}_delay_rate_90d"] - output["global_delay_rate_90d"]
        )
    for name in NUMERIC_FEATURES:
        output[name] = pd.to_numeric(output[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
    for name in CATEGORICAL_FEATURES:
        output[name] = output[name].astype(object).where(output[name].notna(), np.nan)
    return output


def _build_budget_components(tables: dict[str, pd.DataFrame]):
    # Build the base and completed-event cohort once for both history methods.
    base = build_order_features(tables)
    events = add_delay_target(base, tables["orders"])
    primary_sellers = build_primary_sellers(tables["order_items"])
    enriched = add_route_promise_features(base, events)
    enriched = add_delivery_history(enriched, events, primary_sellers)
    enriched = _add_budget_context(enriched, tables, primary_sellers)
    return enriched, events


def build_budget_order_features(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build raw inference rows, including orders without known outcomes."""
    enriched, _ = _build_budget_components(tables)
    return enriched[["order_id", "order_purchase_timestamp", "prediction_time"] + FEATURES]


def build_budget_delay_dataset(raw_dir: Path) -> pd.DataFrame:
    """Keep exactly the existing eligible completed-order cohort and labels."""
    enriched, events = _build_budget_components(load_olist_tables(raw_dir))
    metadata = ["order_id", "order_purchase_timestamp", "prediction_time", "label_available_time", "delayed"]
    return events[metadata].merge(
        enriched[["order_id"] + FEATURES], on="order_id", how="left", validate="one_to_one", sort=False,
    )


def prepare_budget_input(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the explicit feature contract; imputation remains train-only."""
    if len(FEATURES) != len(set(FEATURES)):
        raise ValueError("Budget feature names must be unique")
    missing = set(FEATURES).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing budget feature columns: {sorted(missing)}")
    features = frame[FEATURES].copy()
    for name in NUMERIC_FEATURES:
        features[name] = pd.to_numeric(features[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
    for name in CATEGORICAL_FEATURES:
        features[name] = features[name].astype(object).where(features[name].notna(), np.nan)
    return features
