"""Diagnose mature outcome signals available strictly before approval.

This module never trains a model or changes a model feature list. Callers supply
the existing legacy eligible-completed event cohort. Every rolling window uses
delivery/label-availability time, with an inclusive lower and exclusive upper
bound. Pending and cancelled orders are absent from this cohort by construction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.delay_budget_features import INTERACTION_NUMERIC_FEATURES
from scripts.delay_history_features import (
    HISTORY_NUMERIC_FEATURES,
    _group_window_sums,
    _window_sums,
    add_delivery_history,
)
from scripts.delay_route_features import (
    ROUTE_NUMERIC_FEATURES,
    _RollingDistribution,
    add_route_promise_features,
)


PRIOR_STRENGTH = 20.0
PRIOR_RATE = 0.05
RECOMPUTED_FEATURES = list(dict.fromkeys(
    HISTORY_NUMERIC_FEATURES + ROUTE_NUMERIC_FEATURES + INTERACTION_NUMERIC_FEATURES
))
CANDIDATE_FEATURES = [
    "seller_promise_cdf_90d",
    "seller_route_delay_rate_90d",
    "route_recent30_delay_rate_excess90d",
]
AUDIT_ONLY_FEATURES = [
    "audit_seller_key_known", "audit_route_key_known", "audit_seller_route_key_known",
    "audit_global_delay_count_90d", "audit_global_delay_rate_raw_90d",
    "audit_global_delay_prior_fraction_90d", "audit_global_promise_count_le_90d",
    "audit_global_promise_cdf_90d",
    "audit_seller_delay_count_90d", "audit_seller_delay_rate_raw_90d",
    "audit_seller_delay_prior_fraction_90d", "audit_seller_promise_count_le_90d",
    "audit_seller_promise_cdf_raw_90d", "audit_seller_promise_prior_fraction_90d",
    "audit_route_delay_count_90d", "audit_route_delay_rate_raw_90d",
    "audit_route_delay_prior_fraction_90d", "audit_route_promise_count_le_90d",
    "audit_route_promise_cdf_raw_90d", "audit_route_promise_prior_fraction_90d",
    "audit_seller_route_completed_90d", "audit_seller_route_delay_count_90d",
    "audit_seller_route_delay_rate_raw_90d", "audit_seller_route_delay_prior_fraction_90d",
    "audit_global_completed_30d", "audit_global_delay_count_30d",
    "audit_global_delay_rate_raw_30d", "audit_global_delay_rate_30d",
    "audit_global_delay_prior_fraction_30d", "audit_route_completed_30d",
    "audit_route_delay_count_30d", "audit_route_delay_rate_raw_30d",
    "audit_route_recent30_delay_rate_30d", "audit_route_recent30_prior_fraction",
]
SIGNAL_FEATURES = RECOMPUTED_FEATURES + CANDIDATE_FEATURES + AUDIT_ONLY_FEATURES


def _valid_timestamps(values, name):
    try:
        result = pd.to_datetime(values, errors="coerce")
        timezone = result.dt.tz
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain valid timezone-naive timestamps") from error
    if timezone is not None or result.isna().any():
        raise ValueError(f"{name} must contain valid non-null timezone-naive timestamps")
    return result


def _validate(queries, events, primary_sellers):
    common = {"order_id", "prediction_time", "customer_state", "primary_seller_state"}
    for frame, required, name in (
        (queries, common | {"estimated_delivery_days"}, "queries"),
        (events, common | {"label_available_time", "delayed"}, "events"),
        (primary_sellers, {"order_id", "primary_seller_id"}, "primary_sellers"),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Missing {name} columns: {sorted(missing)}")
        if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
            raise ValueError(f"{name} must have one row per non-null order_id")
    query_dates = _valid_timestamps(queries["prediction_time"], "query prediction_time")
    event_approvals = _valid_timestamps(events["prediction_time"], "event prediction_time")
    event_deliveries = _valid_timestamps(events["label_available_time"], "label_available_time")
    if (event_deliveries < event_approvals).any():
        raise ValueError("Historical delivery must not precede its approval")
    if not events["delayed"].isin([0, 1]).all():
        raise ValueError("Historical delayed labels must be binary")
    # Same-ID events cannot become artificial prior outcomes by moving queries
    # to a later approval. Together with delivery >= approval and delivery < t,
    # this guarantees self-exclusion in the unchanged legacy builders.
    if len(events):
        event_lookup = pd.Series(event_approvals.to_numpy(), index=events["order_id"])
        shared_dates = queries["order_id"].map(event_lookup)
        shared = shared_dates.notna().to_numpy()
        if (query_dates.to_numpy()[shared] != shared_dates.to_numpy()[shared]).any():
            raise ValueError("Queries and events sharing order_id must have identical prediction_time")
    return query_dates, event_approvals, event_deliveries


def _known(value):
    return value is not None and not pd.isna(value) and str(value).strip() != ""


def _seller_keys(frame, lookup):
    return [str(value) if _known(value) else None for value in frame["order_id"].map(lookup)]


def _route_keys(frame):
    return [
        (str(seller), str(customer)) if _known(seller) and _known(customer) else None
        for seller, customer in zip(frame["primary_seller_state"], frame["customer_state"])
    ]


def _joint_keys(sellers, routes):
    return [None if seller is None or route is None else (seller, *route)
            for seller, route in zip(sellers, routes)]


def _raw_rate(numerators, counts):
    return np.divide(numerators, counts, out=np.full(len(counts), np.nan), where=counts > 0)


def _global_promise_counts(event_times, durations, query_times, promises):
    """Only active [t-90d,t) frequencies affect CDF, including its denominator."""
    coordinates = np.unique(durations)
    distribution = _RollingDistribution(coordinates)
    positions = np.searchsorted(coordinates, durations)
    values = np.full(len(query_times), np.nan)
    left = right = 0
    window = pd.Timedelta(days=90).value
    for query_position in np.argsort(query_times, kind="stable"):
        time = query_times[query_position]
        while right < len(event_times) and event_times[right] < time:
            distribution.update(int(positions[right]), 1)
            right += 1
        while left < right and event_times[left] < time - window:
            distribution.update(int(positions[left]), -1)
            left += 1
        if np.isfinite(promises[query_position]):
            values[query_position] = distribution.count_at_or_below(promises[query_position])
    return values


def _group_promise_counts(event_keys, query_keys, event_times, durations, query_times, promises):
    """Binary-search sorted time arrays, then inspect only the active group slice."""
    groups = {}
    for position, key in enumerate(event_keys):
        if key is not None:
            groups.setdefault(key, []).append(position)
    groups = {
        key: (event_times[positions], durations[positions])
        for key, positions in groups.items()
    }
    values = np.zeros(len(query_times), dtype=float)
    window = pd.Timedelta(days=90).value
    for position, key in enumerate(query_keys):
        if not np.isfinite(promises[position]):
            values[position] = np.nan
            continue
        group_values = groups.get(key)
        if group_values is None:
            continue
        times, group_durations = group_values
        lower, upper = np.searchsorted(times, [query_times[position] - window, query_times[position]], side="left")
        values[position] = np.count_nonzero(group_durations[lower:upper] <= promises[position])
    return values


def build_signals(queries: pd.DataFrame, events: pd.DataFrame,
                  primary_sellers: pd.DataFrame) -> pd.DataFrame:
    """Return original query rows, 20 recomputed legacy values and audit columns.

    Inputs follow the existing completed-history contract. Queries must have
    their actual approval timestamp, a calendar-day estimated_delivery_days,
    and unique non-null order IDs. The legacy cohort is supplied by the caller;
    this function does not redefine event eligibility. Query outcome columns
    are never read. All inputs remain unchanged and query index/order survive.

    Candidate priors each have strength 20. Seller CDF shrinks to the same
    query's global 90-day calendar-duration CDF; seller x route delay rate
    shrinks to its existing route 90-day rate. Recent route delay shrinks to
    global 30-day rate, itself shrunk to .05, and subtracts route 90-day rate.
    Unknown candidate keys produce NaN/support zero. Known but empty keys can
    use the stated prior, with support zero and prior fraction one. A global
    CDF without any observations remains NaN. Audit columns are not model X.
    """
    if not np.isfinite(PRIOR_STRENGTH) or PRIOR_STRENGTH <= 0:
        raise ValueError("PRIOR_STRENGTH must be finite and positive")
    if not np.isfinite(PRIOR_RATE) or not 0 <= PRIOR_RATE <= 1:
        raise ValueError("PRIOR_RATE must be finite and in [0, 1]")
    query_dates, event_approvals, event_deliveries = _validate(queries, events, primary_sellers)
    # Use the existing implementations for a direct feature-cache audit.
    output = add_route_promise_features(queries, events, window_days=90, prior_strength=PRIOR_STRENGTH)
    output = add_delivery_history(output, events, primary_sellers, window_days=90,
                                  prior_rate=PRIOR_RATE, prior_strength=PRIOR_STRENGTH)
    promise = pd.to_numeric(queries["estimated_delivery_days"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    seller_days = output["seller_delivery_days_90d"].to_numpy(dtype=float)
    output["seller_promise_margin_days"] = promise - seller_days
    output["seller_promise_ratio"] = np.divide(
        promise, seller_days, out=np.full(len(output), np.nan), where=seller_days > 0,
    )
    for prefix in ("seller", "route"):
        output[f"{prefix}_delay_rate_excess_global"] = (
            output[f"{prefix}_delay_rate_90d"] - output["global_delay_rate_90d"]
        )
    output[RECOMPUTED_FEATURES] = output[RECOMPUTED_FEATURES].replace([np.inf, -np.inf], np.nan)

    sorted_events = events.copy()
    sorted_events["prediction_time"] = event_approvals
    sorted_events["label_available_time"] = event_deliveries
    sorted_events = sorted_events.sort_values(["label_available_time", "order_id"], kind="stable").reset_index(drop=True)
    event_times = sorted_events["label_available_time"].to_numpy(dtype="datetime64[ns]").view("int64")
    query_times = query_dates.to_numpy(dtype="datetime64[ns]").view("int64")
    durations = (sorted_events["label_available_time"].dt.normalize()
                 - sorted_events["prediction_time"].dt.normalize()).dt.days.to_numpy(dtype=np.int64)
    delayed = sorted_events["delayed"].to_numpy(dtype=float)
    lookup = primary_sellers.set_index("order_id")["primary_seller_id"]
    event_sellers, query_sellers = _seller_keys(sorted_events, lookup), _seller_keys(queries, lookup)
    event_routes, query_routes = _route_keys(sorted_events), _route_keys(queries)
    event_joints = _joint_keys(event_sellers, event_routes)
    query_joints = _joint_keys(query_sellers, query_routes)
    seller_known = np.array([key is not None for key in query_sellers])
    route_known = np.array([key is not None for key in query_routes])
    joint_known = np.array([key is not None for key in query_joints])
    audit = {
        "audit_seller_key_known": seller_known.astype(float),
        "audit_route_key_known": route_known.astype(float),
        "audit_seller_route_key_known": joint_known.astype(float),
    }
    window90 = pd.Timedelta(days=90).value
    window30 = pd.Timedelta(days=30).value
    global_count, global_delayed, _ = _window_sums(event_times, delayed, durations, query_times, window90)
    global_cdf_count = _global_promise_counts(event_times, durations, query_times, promise)
    global_cdf = _raw_rate(global_cdf_count, global_count)
    audit.update({
        "audit_global_delay_count_90d": global_delayed,
        "audit_global_delay_rate_raw_90d": _raw_rate(global_delayed, global_count),
        "audit_global_delay_prior_fraction_90d": PRIOR_STRENGTH / (global_count + PRIOR_STRENGTH),
        "audit_global_promise_count_le_90d": global_cdf_count,
        "audit_global_promise_cdf_90d": global_cdf,
    })
    for prefix, event_keys, query_keys in (
        ("seller", event_sellers, query_sellers), ("route", event_routes, query_routes),
    ):
        counts, positives, _ = _group_window_sums(
            event_keys, query_keys, event_times, delayed, durations, query_times, window90,
        )
        cdf_counts = _group_promise_counts(event_keys, query_keys, event_times, durations, query_times, promise)
        audit.update({
            f"audit_{prefix}_delay_count_90d": positives,
            f"audit_{prefix}_delay_rate_raw_90d": _raw_rate(positives, counts),
            f"audit_{prefix}_delay_prior_fraction_90d": PRIOR_STRENGTH / (counts + PRIOR_STRENGTH),
            f"audit_{prefix}_promise_count_le_90d": cdf_counts,
            f"audit_{prefix}_promise_cdf_raw_90d": _raw_rate(cdf_counts, counts),
            f"audit_{prefix}_promise_prior_fraction_90d": PRIOR_STRENGTH / (counts + PRIOR_STRENGTH),
        })
        if prefix == "seller":
            candidate = (cdf_counts + PRIOR_STRENGTH * global_cdf) / (counts + PRIOR_STRENGTH)
            candidate[~seller_known] = np.nan
            output["seller_promise_cdf_90d"] = candidate

    joint_count, joint_delayed, _ = _group_window_sums(
        event_joints, query_joints, event_times, delayed, durations, query_times, window90,
    )
    route_rate90 = output["route_delay_rate_90d"].to_numpy(dtype=float)
    joint_rate = (joint_delayed + PRIOR_STRENGTH * route_rate90) / (joint_count + PRIOR_STRENGTH)
    joint_rate[~joint_known] = np.nan
    output["seller_route_delay_rate_90d"] = joint_rate
    audit.update({
        "audit_seller_route_completed_90d": joint_count,
        "audit_seller_route_delay_count_90d": joint_delayed,
        "audit_seller_route_delay_rate_raw_90d": _raw_rate(joint_delayed, joint_count),
        "audit_seller_route_delay_prior_fraction_90d": PRIOR_STRENGTH / (joint_count + PRIOR_STRENGTH),
    })
    global_count30, global_delayed30, _ = _window_sums(event_times, delayed, durations, query_times, window30)
    global_rate30 = (global_delayed30 + PRIOR_STRENGTH * PRIOR_RATE) / (global_count30 + PRIOR_STRENGTH)
    route_count30, route_delayed30, _ = _group_window_sums(
        event_routes, query_routes, event_times, delayed, durations, query_times, window30,
    )
    route_rate30 = (route_delayed30 + PRIOR_STRENGTH * global_rate30) / (route_count30 + PRIOR_STRENGTH)
    route_rate30[~route_known] = np.nan
    output["route_recent30_delay_rate_excess90d"] = route_rate30 - route_rate90
    audit.update({
        "audit_global_completed_30d": global_count30,
        "audit_global_delay_count_30d": global_delayed30,
        "audit_global_delay_rate_raw_30d": _raw_rate(global_delayed30, global_count30),
        "audit_global_delay_rate_30d": global_rate30,
        "audit_global_delay_prior_fraction_30d": PRIOR_STRENGTH / (global_count30 + PRIOR_STRENGTH),
        "audit_route_completed_30d": route_count30,
        "audit_route_delay_count_30d": route_delayed30,
        "audit_route_delay_rate_raw_30d": _raw_rate(route_delayed30, route_count30),
        "audit_route_recent30_delay_rate_30d": route_rate30,
        "audit_route_recent30_prior_fraction": PRIOR_STRENGTH / (route_count30 + PRIOR_STRENGTH),
    })
    for name in AUDIT_ONLY_FEATURES:
        output[name] = audit[name]
    return output
