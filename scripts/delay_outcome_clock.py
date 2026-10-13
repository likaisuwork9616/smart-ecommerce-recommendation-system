"""Training-only maturity from delivery or the end of the promised calendar day.

For the unchanged eventually-delivered cohort, a late result is knowable at
the next midnight after the promise; an on-time result is knowable on delivery.
The minimum of these two timestamps expresses both cases without consulting
the target. Actual delivery metadata remains unchanged for physical-delivery
history features and historical validation maturity. This does not establish
eventual-delivery eligibility for every originally approved order.
"""

from __future__ import annotations

from numbers import Integral

import numpy as np
import pandas as pd

from scripts.delay_multimonth_validation import _partition_report, _require_both_classes
from scripts.delay_rolling_validation import _order_fingerprint, split_rolling_month
from scripts.delay_waiting_split import _validated_frame


TRAINING_OUTCOME_COLUMN = "training_outcome_known_time"


def _timestamps(values, name):
    result = pd.to_datetime(values, errors="raise", format="mixed")
    if result.isna().any() or result.dt.tz is not None:
        raise ValueError(f"{name} must contain valid non-null timezone-naive timestamps")
    return result


def add_training_outcome_clock(dataset: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Attach the training clock after matching source identities and timelines.

    ``orders`` is the unchanged raw orders table from the existing six-file
    source manifest. Every supplied cohort row must match its raw purchase,
    approval, actual delivery and calendar-delay target. All input columns,
    their values, external index and row order are preserved.
    """
    dataset_required = {"order_id", "order_purchase_timestamp", "prediction_time", "label_available_time", "delayed"}
    raw_required = {"order_id", "order_purchase_timestamp", "order_approved_at", "order_delivered_customer_date",
                    "order_estimated_delivery_date", "order_status"}
    for frame, required, name in ((dataset, dataset_required, "dataset"), (orders, raw_required, "raw orders")):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Missing {name} columns: {sorted(missing)}")
        if frame.order_id.isna().any() or frame.order_id.duplicated().any():
            raise ValueError(f"{name} must have unique non-null order IDs")
    if dataset.empty or not dataset.delayed.isin([0, 1]).all():
        raise ValueError("Require a nonempty binary-labeled eligible cohort")
    raw = orders.set_index("order_id")
    if not dataset.order_id.isin(raw.index).all():
        raise ValueError("Cohort order IDs must all exist in raw orders")
    raw = raw.loc[dataset.order_id].reset_index()
    for name in ("order_purchase_timestamp", "order_approved_at", "order_delivered_customer_date", "order_estimated_delivery_date"):
        raw[name] = _timestamps(raw[name], f"raw {name}")
    actual_columns = (("order_purchase_timestamp", "order_purchase_timestamp"),
                      ("prediction_time", "order_approved_at"),
                      ("label_available_time", "order_delivered_customer_date"))
    for cached, source in actual_columns:
        values = _timestamps(dataset[cached], cached)
        if not np.array_equal(values.to_numpy(), raw[source].to_numpy()):
            raise ValueError(f"Cohort {cached} differs from raw {source}")
    valid = raw.order_status.eq("delivered")
    valid &= raw.order_approved_at.ge(raw.order_purchase_timestamp)
    valid &= raw.order_delivered_customer_date.ge(raw.order_approved_at)
    valid &= raw.order_estimated_delivery_date.dt.normalize().ge(raw.order_approved_at.dt.normalize())
    if not valid.all():
        raise ValueError("Cohort rows must retain the existing valid eventually-delivered population")
    expected_target = (raw.order_delivered_customer_date.dt.normalize() > raw.order_estimated_delivery_date.dt.normalize()).astype(int)
    if not np.array_equal(dataset.delayed.to_numpy(), expected_target.to_numpy()):
        raise ValueError("Cohort calendar-delay labels differ from raw source")
    deadline = raw.order_estimated_delivery_date.dt.normalize() + pd.Timedelta(days=1)
    known = np.minimum(raw.order_delivered_customer_date.to_numpy(dtype="datetime64[ns]"),
                       deadline.to_numpy(dtype="datetime64[ns]"))
    if TRAINING_OUTCOME_COLUMN in dataset:
        existing = _timestamps(dataset[TRAINING_OUTCOME_COLUMN], TRAINING_OUTCOME_COLUMN)
        if not np.array_equal(existing.to_numpy(dtype="datetime64[ns]"), known):
            raise ValueError("Existing training outcome clock differs from raw-derived minimum")
    output = dataset.copy()
    output[TRAINING_OUTCOME_COLUMN] = known
    return output


def split_outcome_training_month(
    dataset: pd.DataFrame, month_start, wait_days=0, clock="deadline", score_end=None,
):
    """Change only training approval wait and outcome maturity for a monthly fit.

    Historical validation must continue using its original actual-delivery
    cutoff. The scoring cohort is exactly the original rolling month's cohort,
    with no outcome-maturity filter. Use the attached raw-verified training
    clock; never replace actual ``label_available_time`` in feature builders.
    """
    if isinstance(wait_days, bool) or not isinstance(wait_days, Integral) or wait_days not in (0, 30):
        raise ValueError("wait_days must be either 0 or 30")
    if clock not in ("deadline", "delivery"):
        raise ValueError("clock must be deadline or delivery")
    if TRAINING_OUTCOME_COLUMN not in dataset:
        raise ValueError("Attach the raw-verified training outcome clock before splitting")
    baseline_splits, baseline_report = split_rolling_month(dataset, month_start, score_end)
    frame = _validated_frame(dataset)
    frame[TRAINING_OUTCOME_COLUMN] = _timestamps(frame[TRAINING_OUTCOME_COLUMN], TRAINING_OUTCOME_COLUMN)
    if ((frame[TRAINING_OUTCOME_COLUMN] < frame.prediction_time)
            | (frame[TRAINING_OUTCOME_COLUMN] > frame.label_available_time)).any():
        raise ValueError("Training outcome time must be at or after approval and no later than actual delivery")
    start = pd.Timestamp(baseline_report["model_fit_time"])
    train_end = start - pd.Timedelta(days=int(wait_days))
    before = frame.loc[frame.prediction_time < train_end]
    selected_clock = TRAINING_OUTCOME_COLUMN if clock == "deadline" else "label_available_time"
    train = before.loc[before[selected_clock] < start].copy()
    _require_both_classes(train, "train")
    same_wait_delivery = before.loc[before.label_available_time < start]
    early_only = train.loc[train.label_available_time >= start]
    if not early_only.delayed.eq(1).all():
        raise ValueError("Only delayed outcomes can become known before their delivery")
    baseline_train = baseline_splits["train"]
    if not baseline_train.order_id.isin(train.order_id).all():
        raise ValueError("The more recent training design must retain baseline mature training rows")
    train_report = _partition_report(before, train, start)
    train_report.update({
        "order_id_fingerprint": _order_fingerprint(train),
        "training_label_clock": selected_clock,
        "training_outcome_known_time_max": train[TRAINING_OUTCOME_COLUMN].max().isoformat(),
        "selected_training_clock_max": train[selected_clock].max().isoformat(),
        "actual_delivery_time_max": train.label_available_time.max().isoformat(),
        "actual_delivery_labels_known_at_fit_rows": int((train.label_available_time < start).sum()),
        "outcomes_known_before_delivery_rows": len(early_only),
        "outcomes_known_before_delivery_positive_rows": int(early_only.delayed.sum()),
    })
    report = dict(baseline_report)
    report.update({
        "method": "monthly_refit_with_training_only_outcome_clock_and_approval_wait",
        "wait_days": int(wait_days), "training_clock": clock,
        "training_label_clock": selected_clock, "train_prediction_end": train_end.isoformat(),
        "training_source_cutoff": (
            "Training approvals are strictly before model fit minus the configured wait; "
            "the selected training outcome clock must be strictly before model fit. "
            "Actual delivery timestamps are never rewritten."
        ),
        "training_outcome_clock_formula": "min(actual delivery timestamp, estimated delivery calendar date + 1 day at midnight)",
        "actual_delivery_metadata_preserved": True,
        "validation_maturity_clock_unchanged": "label_available_time (actual delivery), strictly before selection time",
        "clock_limitations": (
            "Unchanged eventually-delivered eligible cohort; does not establish eventual delivery for raw pending orders. "
            "No event-ingestion timestamps or promise-revision history; assumes delivery records and original promise are timely available."
        ),
        "train_wait": {"start": train_end.isoformat(), "end": start.isoformat(), "days": int(wait_days),
            "prediction_rows_not_assigned": int(((frame.prediction_time >= train_end) & (frame.prediction_time < start)).sum())},
        "baseline_60day_delivery_training": baseline_report["partitions"]["train"],
        "same_wait_delivery_training": {"rows": len(same_wait_delivery), "positive_rows": int(same_wait_delivery.delayed.sum()),
            "order_id_fingerprint": _order_fingerprint(same_wait_delivery)},
        "added_vs_baseline_60day_delivery": {"rows": len(train)-len(baseline_train),
            "positive_rows": int(train.delayed.sum()-baseline_train.delayed.sum())},
        "partitions": {"train": train_report, "scoring": baseline_report["partitions"]["scoring"]},
    })
    return {"train": train, "scoring": baseline_splits["scoring"]}, report
