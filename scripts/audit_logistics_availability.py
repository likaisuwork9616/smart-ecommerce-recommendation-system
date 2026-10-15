"""Inventory Olist logistics clocks without fitting, scoring or reading holdout labels.

Only operational profiles of valid approvals before 2018-05-01 are published.
Carrier/customer events at or after that boundary are censored before profiling.
The nine complete files are fingerprinted and their schemas/row counts listed;
those file-level metadata are not outcome or model-performance measurements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from scripts.delay_backlog_features import feature_columns
from scripts.delay_dispatch_features import DISPATCH_NUMERIC_FEATURES
from scripts.logistics_event_availability import build_history_feasibility


DEFAULT_RAW_DIR = ROOT / "data/raw/olist"
DEFAULT_OUTPUT = ROOT / "reports/stage4/logistics_availability.json"
CUTOFF = pd.Timestamp("2018-05-01")
PROFILE_MONTHS = ("2017-07", "2017-09", "2017-12", "2018-02", "2018-04")
RAW_FILES = (
    "olist_customers_dataset.csv", "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv", "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv", "olist_orders_dataset.csv",
    "olist_products_dataset.csv", "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
)
EVENT_COLUMNS = (
    "order_purchase_timestamp", "order_approved_at",
    "order_delivered_carrier_date", "order_delivered_customer_date",
    "order_estimated_delivery_date",
)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count(mask) -> int:
    return int(mask.fillna(False).sum())


def _numeric_summary(values) -> dict:
    values = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return {"observations": 0, "minimum": None, "p25": None,
                "median": None, "p75": None, "p90": None, "maximum": None}
    return {"observations": len(values), "minimum": float(values.min()),
            "p25": float(values.quantile(.25)), "median": float(values.median()),
            "p75": float(values.quantile(.75)), "p90": float(values.quantile(.9)),
            "maximum": float(values.max())}


def restricted_population(orders: pd.DataFrame, cutoff=CUTOFF) -> tuple[pd.DataFrame, dict]:
    """Keep valid approval clocks, then censor future physical-event timestamps.

    No final status or eventual-delivery filter is applied. A missing carrier
    date means no carrier event observed by the boundary, not proof of no ship.
    """
    cutoff = pd.Timestamp(cutoff)
    if pd.isna(cutoff) or cutoff > CUTOFF or cutoff.tz is not None:
        raise ValueError("Inventory cutoff must be timezone-naive and no later than 2018-05-01")
    required = {"order_id", *EVENT_COLUMNS}
    if not required.issubset(orders):
        raise ValueError(f"Missing order columns: {sorted(required.difference(orders))}")
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError("Order IDs must be unique and non-null")
    # Intentionally do not retain order_status, reviews or any target column.
    frame = orders[["order_id", *EVENT_COLUMNS]].copy()
    for name in EVENT_COLUMNS:
        frame[name] = pd.to_datetime(frame[name], errors="coerce", format="mixed")
        if frame[name].dt.tz is not None:
            raise ValueError("Olist clocks must be timezone-naive")
    before = frame.order_approved_at.notna() & frame.order_approved_at.lt(cutoff)
    valid = (frame.order_purchase_timestamp.notna()
             & frame.order_approved_at.ge(frame.order_purchase_timestamp))
    scope = {
        "approved_before_cutoff": _count(before),
        "invalid_purchase_approval_clock_before_cutoff": _count(before & ~valid),
        "valid_approved_before_cutoff": _count(before & valid),
        "approval_cutoff_exclusive": cutoff.isoformat(),
        "physical_event_observation_cutoff_exclusive": cutoff.isoformat(),
        "final_status_filter": False,
        "eventual_delivery_filter": False,
        "target_or_performance_metrics_computed": False,
        "original_holdout_scored": False,
        "whole_file_metadata_exception": "Only headers, row counts, bytes and SHA256 cover complete raw files.",
    }
    frame = frame.loc[before & valid].copy().reset_index(drop=True)
    for name in ("order_delivered_carrier_date", "order_delivered_customer_date"):
        frame[name] = frame[name].where(frame[name].lt(cutoff))
    return frame, scope


def checkpoint_profile(frame: pd.DataFrame, *, approval_days=None, transit_days=None,
                       cutoff=CUTOFF) -> dict:
    """Describe observable checkpoint populations, not eventual eligible labels.

    Physical events must be strictly earlier than the decision. An event equal
    to the checkpoint is unknown as a feature, but delivery exactly at the
    checkpoint conservatively suppresses alerts. Carrier checkpoints are
    evaluated 1ns after the event so the strict clock observes the trigger.
    """
    approval = frame.order_approved_at
    carrier = frame.order_delivered_carrier_date
    delivery = frame.order_delivered_customer_date
    valid_carrier = carrier.notna() & carrier.ge(approval)
    if (approval_days is None) == (transit_days is None):
        raise ValueError("Choose exactly one checkpoint clock")
    if approval_days is not None:
        if approval_days not in (0, 1, 3, 7):
            raise ValueError("Approval checkpoints are 0, 1, 3 or 7 days")
        query = approval + pd.Timedelta(days=approval_days)
        clock = f"approval_plus_{approval_days}d"
        observable = query.lt(cutoff)
    else:
        if transit_days not in (0, 3):
            raise ValueError("Carrier checkpoints are 0 or 3 days")
        query = carrier + pd.Timedelta(days=transit_days) + pd.Timedelta(1, unit="ns")
        clock = f"valid_carrier_plus_{transit_days}d_plus_1ns"
        observable = valid_carrier & query.lt(cutoff)
    delivered = delivery.notna() & delivery.lt(query)
    delivered_equal = delivery.notna() & delivery.eq(query)
    carrier_seen = carrier.notna() & carrier.lt(query)
    valid_carrier_seen = valid_carrier & carrier_seen
    undelivered = observable & ~delivered & ~delivered_equal
    invalid_carrier_pending = undelivered & carrier_seen & ~valid_carrier
    eligible = undelivered & ~invalid_carrier_pending
    promise_end = frame.order_estimated_delivery_date.dt.normalize() + pd.Timedelta(days=1)
    already_overdue = eligible & promise_end.notna() & promise_end.le(query)
    advance_eligible = eligible & promise_end.notna() & query.lt(promise_end)
    return {
        "clock": clock,
        "observable_queries_before_cutoff": _count(observable),
        "excluded_no_valid_carrier_trigger_or_query_not_before_cutoff": _count(~observable),
        "customer_delivery_observed_before_query": _count(observable & delivered),
        "no_customer_delivery_observed_before_query": _count(observable & ~delivered),
        "customer_delivery_equal_query_conservative_suppression": _count(observable & delivered_equal),
        "no_customer_delivery_at_or_before_query": _count(undelivered),
        "eligible_for_reminder_proxy": _count(eligible),
        "already_overdue_pending_among_generic_eligible": _count(already_overdue),
        "missing_promise_among_generic_eligible": _count(eligible & promise_end.isna()),
        "eligible_for_advance_reminder_proxy": _count(advance_eligible),
        "undelivered_with_valid_carrier_event_before_query": _count(undelivered & valid_carrier_seen),
        "undelivered_without_carrier_event_before_query": _count(undelivered & ~carrier_seen),
        "undelivered_with_carrier_before_approval_anomaly": _count(invalid_carrier_pending),
        "undelivered_with_original_promise_already_expired": _count(undelivered & promise_end.le(query)),
        "undelivered_hours_remaining_until_original_promise_end": _numeric_summary(
            (promise_end.loc[undelivered] - query.loc[undelivered]).dt.total_seconds() / 3600),
        "eligibility_note": "Features observe event < t; delivery <= t and observed invalid carrier chronology suppress generic reminders. The two normal-state partitions sum to generic eligible; invalid-carrier rows are a separate exclusion. Advance reminders additionally require known promise and t < midnight after promised date; already-overdue orders are monitoring, not future-delay classification. Unknown cancellation times remain; this is not the current labeled delivered-only scoring cohort.",
    }


def operational_profile(frame: pd.DataFrame, items: pd.DataFrame, cutoff=CUTOFF) -> dict:
    approval = frame.order_approved_at
    carrier = frame.order_delivered_carrier_date
    delivery = frame.order_delivered_customer_date
    promise = frame.order_estimated_delivery_date
    known_carrier = carrier.notna()
    known_delivery = delivery.notna()
    valid_carrier = known_carrier & carrier.ge(approval)
    sequence = {
        "carrier_before_approval": _count(known_carrier & carrier.lt(approval)),
        "customer_delivery_before_approval": _count(known_delivery & delivery.lt(approval)),
        "customer_delivery_before_known_carrier": _count(known_carrier & known_delivery & delivery.lt(carrier)),
        "known_customer_delivery_without_carrier_observed_by_cutoff": _count(known_delivery & ~known_carrier),
        "carrier_equal_approval": _count(known_carrier & carrier.eq(approval)),
    }
    item_frame = items.loc[items.order_id.isin(frame.order_id)].copy()
    if item_frame.duplicated(["order_id", "order_item_id"]).any():
        raise ValueError("Item sequence must be unique per order")
    item_frame["shipping_limit_date"] = pd.to_datetime(item_frame.shipping_limit_date, errors="coerce", format="mixed")
    aggregated = item_frame.groupby("order_id", sort=False).agg(
        item_count=("order_item_id", "size"), seller_count=("seller_id", "nunique"),
        shipping_limit_count=("shipping_limit_date", "count"),
        shipping_limit_min=("shipping_limit_date", "min"),
        shipping_limit_max=("shipping_limit_date", "max"))
    joined = frame.set_index("order_id").join(aggregated)
    valid_limit = joined.shipping_limit_min.notna()
    item_approval = item_frame.order_id.map(frame.set_index("order_id").order_approved_at)
    schedule = {
        "item_rows": len(item_frame),
        "orders_with_items": _count(joined.item_count.notna()),
        "orders_without_items": _count(joined.item_count.isna()),
        "orders_with_multiple_items": _count(joined.item_count.gt(1)),
        "orders_with_multiple_sellers": _count(joined.seller_count.gt(1)),
        "items_with_valid_shipping_limit": _count(item_frame.shipping_limit_date.notna()),
        "items_with_shipping_limit_before_approval": _count(item_frame.shipping_limit_date.lt(item_approval)),
        "orders_with_at_least_one_valid_shipping_limit": _count(valid_limit),
        "orders_with_different_item_shipping_limits": _count(joined.shipping_limit_max.gt(joined.shipping_limit_min)),
        "orders_with_latest_shipping_limit_at_or_after_promise_end": _count(
            joined.shipping_limit_max.ge(joined.order_estimated_delivery_date.dt.normalize() + pd.Timedelta(days=1))),
        "known_order_carrier_at_or_after_latest_item_limit": _count(
            joined.order_delivered_carrier_date.notna()
            & joined.order_delivered_carrier_date.ge(joined.shipping_limit_max)),
        "latest_shipping_limit_hours_from_approval": _numeric_summary(
            (joined.shipping_limit_max - joined.order_approved_at).dt.total_seconds() / 3600),
        "assumption": "Exported item dispatch schedule is assumed available at approval only in the existing sensitivity branch; creation/revision/ingestion timestamps are absent.",
        "proxy_limit": "One order-level carrier timestamp cannot establish actual dispatch of every item or seller; carrier-vs-limit is descriptive, not a dispatch-lateness target.",
    }
    return {
        "orders": len(frame),
        "events_observed_strictly_before_inventory_cutoff": {
            "carrier": _count(known_carrier), "customer_delivery": _count(known_delivery),
            "original_promise_present": _count(promise.notna()),
        },
        "milestone_sequence_anomalies": sequence,
        "valid_observed_handover_events": _count(valid_carrier),
        "approval_to_valid_carrier_hours": _numeric_summary(
            (carrier.loc[valid_carrier] - approval.loc[valid_carrier]).dt.total_seconds() / 3600),
        "shipping_schedule_and_item_granularity": schedule,
        "approval_checkpoints": {str(days): checkpoint_profile(frame, approval_days=days, cutoff=cutoff)
                                 for days in (0, 1, 3, 7)},
        "handover_checkpoint": checkpoint_profile(frame, transit_days=0, cutoff=cutoff),
        "transit_checkpoint_carrier_plus_3d": checkpoint_profile(frame, transit_days=3, cutoff=cutoff),
    }


def _prediction_times() -> list[dict]:
    return [
        {"time": "approval", "current_task_comparable": True,
         "known": "Purchase/approval clocks, original promise and transaction attributes under static-export availability assumptions; strictly earlier historical carrier/delivery events.",
         "unknown": "This order's future carrier event, actual transit/delivery duration, final status and future reviews.",
         "new_signal_opportunity": "Historical carrier handover speed and approved-but-not-yet-handed-over backlog; preserve the existing approval-time cohort and daily cap."},
        {"time": "carrier_event_plus_1ns", "current_task_comparable": False,
         "known": "Recorded order-level carrier event; elapsed approval-to-carrier time and original promise remaining at this later decision.",
         "unknown": "Future customer delivery, actual parcel/item scans, carrier identity, final outcome.",
         "new_signal_opportunity": "Separate later-intervention task; excludes unhanded-over orders and needs a new cohort/budget definition."},
        {"time": "approval_plus_1_3_7_days", "current_task_comparable": False,
         "known": "Elapsed approval time; only carrier/customer events strictly earlier than checkpoint; original promise remaining.",
         "unknown": "Any later event; why a timestamp is missing; cancellation time; event ingestion delay.",
         "new_signal_opportunity": "Event-observed pending/handed-over state; one decision per order or repeat-alert policy must be defined first."},
        {"time": "carrier_plus_3_days_plus_1ns", "current_task_comparable": False,
         "known": "A valid earlier carrier event, elapsed transit proxy and whether customer delivery was observed before checkpoint.",
         "unknown": "Carrier/parcel scan positions and final delivery outcome.",
         "new_signal_opportunity": "Transit monitoring among handed-over yet unreceived orders; daily eligible-order cap cannot be compared directly with approval-batch 10%."},
    ]


def _signal_inventory() -> list[dict]:
    return [
        {"family": "historical_carrier_handover_speed", "in_current_101": False,
         "existing_code_branch": None, "approval_time_feasible": "conditional_on_event_observation_assumption",
         "safe_clock": "Other orders' valid carrier >= their approval, carrier strictly < current approval; rolling event-time window; no final-status/delivery filter; exclude current order.",
         "examples": ["seller/global/route handover count and approval-to-carrier hours over trailing 90 days"],
         "risk": "Completed-handover history omits still-unhanded-over orders; seller sparsity and anomalous clocks require missingness/count controls."},
        {"family": "not_yet_handed_over_workload", "in_current_101": False,
         "existing_code_branch": None, "approval_time_feasible": "conditional_on_event_observation_assumption",
         "safe_clock": "Other approvals < current approval; carrier missing or >= query; do not read final order_status; invalid carrier chronology must be flagged separately.",
         "examples": ["seller/global approved-but-no-carrier-observed count and age"],
         "risk": "Missing events and absent cancellation clocks can inflate queue; proxy does not establish physical possession."},
        {"family": "item_dispatch_schedule", "in_current_101": False,
         "existing_code_branch": "scripts/delay_dispatch_features.py (8 existing sensitivity features)",
         "approval_time_feasible": "unverified_schedule_availability_assumption",
         "safe_clock": "Use schedule values only if their creation/version is confirmed available at prediction time; never treat shipping_limit_date as actual dispatch.",
         "examples": DISPATCH_NUMERIC_FEATURES,
         "risk": "No schedule revision/creation timestamp; already evaluated as a sensitivity branch, not a new uncontaminated signal."},
        {"family": "this_order_handover_duration", "in_current_101": False,
         "existing_code_branch": None, "approval_time_feasible": False,
         "safe_clock": "Carrier event must already be observed strictly before a later decision; valid carrier >= approval.",
         "examples": ["approval-to-carrier elapsed hours", "promise hours remaining at carrier observation"],
         "risk": "Leaks future at approval; changing to handover time changes population and available intervention lead time."},
        {"family": "checkpoint_milestone_state", "in_current_101": False,
         "existing_code_branch": None, "approval_time_feasible": False,
         "safe_clock": "At predeclared checkpoint t, only event timestamps < t are observed; events exactly t remain unknown.",
         "examples": ["no carrier event observed by approval+3d", "carrier observed but no customer delivery observed by approval+7d"],
         "risk": "Requires repeated decision policy and event ingestion audit; final snapshot status is not historical as-of status."},
        {"family": "geography_workload_completed_delivery_history", "in_current_101": True,
         "existing_code_branch": "scripts/delay_backlog_features.py geo/7_14d",
         "approval_time_feasible": "existing_static_and_event_clock_assumptions",
         "safe_clock": "Existing physical-delivery history < approval; no future label history; backlog uses approval/promise and observed delivery clocks.",
         "examples": ["geographic distance", "route/seller recent completed delivery", "pending/overdue workload", "7/14-day overdue changes"],
         "risk": "Already present; renaming/recombining does not create a new external logistics observation."},
        {"family": "carrier_scans_location_service_weather_calendar", "in_current_101": False,
         "existing_code_branch": None, "approval_time_feasible": "not_available_in_nine_raw_tables",
         "safe_clock": "Requires new timestamped external data and joining/availability rules.",
         "examples": ["carrier identifier and service level", "parcel scan path", "tracking location", "weather", "public-holiday calendar"],
         "risk": "Cannot invent these from city/ZIP or a final delivery timestamp; day-of-week already exists."},
        {"family": "final_status_and_reviews", "in_current_101": False,
         "existing_code_branch": None, "approval_time_feasible": False,
         "safe_clock": "No historical status transition timestamps exist; reviews are downstream outcomes, not approval-time predictors.",
         "examples": ["final order_status", "review score/text", "actual customer delivery date as own-order input"],
         "risk": "Future information or target leakage; not proposed for the next training change."},
    ]


def build_report(raw_dir: Path) -> dict:
    raw_dir = Path(raw_dir)
    manifests = []
    tables = {}
    for filename in RAW_FILES:
        path = raw_dir / filename
        before = _hash(path)
        table = pd.read_csv(path, dtype=str)
        after = _hash(path)
        if before != after:
            raise ValueError(f"Raw file changed while reading: {filename}")
        manifests.append({"file": filename, "rows": len(table),
                          "columns": list(table.columns), "bytes": path.stat().st_size, "sha256": before})
        if filename in ("olist_orders_dataset.csv", "olist_order_items_dataset.csv",
                        "olist_sellers_dataset.csv", "olist_customers_dataset.csv"):
            tables[filename] = table
    population, scope = restricted_population(tables["olist_orders_dataset.csv"])
    items = tables["olist_order_items_dataset.csv"]
    profiles = {"all_pre_cutoff": operational_profile(population, items)}
    for month in PROFILE_MONTHS:
        start = pd.Timestamp(month + "-01")
        selected = population.order_approved_at.ge(start) & population.order_approved_at.lt(start + pd.offsets.MonthBegin(1))
        profiles[month] = operational_profile(population.loc[selected], items)
    history_feasibility = build_history_feasibility({
        "orders": tables["olist_orders_dataset.csv"],
        "items": tables["olist_order_items_dataset.csv"],
        "customers": tables["olist_customers_dataset.csv"],
        "sellers": tables["olist_sellers_dataset.csv"],
    })
    for manifest in manifests:
        if _hash(raw_dir / manifest["file"]) != manifest["sha256"]:
            raise ValueError(f"Raw file changed during inventory: {manifest['file']}")
    numeric, categorical = feature_columns("geo", "7_14d")
    if len(numeric) != 93 or len(categorical) != 8:
        raise AssertionError("Current 101-feature research contract changed")
    return {
        "format_version": 1,
        "analysis": "olist_logistics_signal_and_prediction_time_inventory",
        "work_type": "Data availability inventory only; no fit, prediction, selection or performance re-evaluation.",
        "new_training_fits": 0, "new_model_predictions": 0,
        "raw_sources": manifests,
        "audit_scope": scope,
        "event_clock_contract": {
            "known_event_rule": "physical event timestamp strictly < prediction_time",
            "equal_timestamp_rule": "Event exactly at t is unknown as an input; customer delivery <= t conservatively suppresses checkpoint alerts. Carrier-trigger decision occurs at carrier + 1ns.",
            "timezone": "Timezone-naive Olist export; geographic timezone/ingestion clocks are not provided.",
            "inventory_boundary": "2018-05-01T00:00:00 exclusive for all operational observations and queries.",
            "promise_end": "Midnight after original estimated delivery calendar date; a future contractual promise can be known before its date, subject to revision availability assumptions.",
            "advance_reminder_eligibility": "Require no delivery <= t, no observed invalid carrier chronology, known promise and t < promise-end midnight. Already-overdue pending is monitoring rather than prospective delay prediction.",
            "ingestion_limitation": "Recorded event time is not proof that production systems had ingested that event by the same instant.",
        },
        "existing_101_features": {"numeric_count": len(numeric), "categorical_count": len(categorical),
                                  "numeric": numeric, "categorical": categorical,
                                  "own_carrier_or_customer_delivery_inputs": False,
                                  "dispatch_schedule_features_included": False},
        "operational_profiles": profiles,
        "handover_history_feasibility": history_feasibility,
        "profile_period_interpretation": {
            "all_pre_cutoff": "Coverage of valid approved orders before May1, including unfinished/missing-item orders; no outcome label filter.",
            "2017-07_and_2017-09": "Previously inspected historical-validation approval months; this inventory computes operational counts only.",
            "2017-12_2018-02_and_2018-04": "Previously inspected development approval months; this inventory computes operational counts only.",
            "right_censoring": "Physical events and checkpoint queries are censored at May1; especially April completed-event duration summaries omit handovers not yet observed and do not prove faster service.",
            "comparability": "These all-approved operational populations differ from the existing eventually-delivered eligible prediction cohort; their denominators are not alert-performance denominators.",
        },
        "prediction_time_inventory": _prediction_times(),
        "candidate_signal_inventory": _signal_inventory(),
        "limitations": [
            "One order-level carrier/customer timestamp does not identify each parcel, carrier, item or seller's movement.",
            "No cancellation/status-transition/scan/ingestion or master-data revision history; missing observations cannot be equated with a verified physical state.",
            "Transaction/product/location/schedule fields come from a final static export; availability and versions at approval are assumptions, not proven ingestion logs.",
            "Event profile counts and checkpoint populations are operational coverage; they are neither late-order recall nor causal evidence of improvement.",
            "Pre-May approved orders and all operational event clocks/queries are bounded before May1; the original final holdout has not been scored or tuned against.",
            "Repeatedly inspected historical/development months cannot become a new untouched test merely by changing the prediction time.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.raw_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output), "orders_in_operational_scope": report["audit_scope"]["valid_approved_before_cutoff"],
                      "raw_files": len(report["raw_sources"]), "new_fits": 0, "new_predictions": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
