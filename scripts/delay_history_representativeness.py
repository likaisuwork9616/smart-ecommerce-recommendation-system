"""Status-free, approval-time audit of completed and unfinished history.

Only caller-supplied, valid raw approvals enter the cohort. Final eligibility
is kept in separate retrospective counters; it never decides an as-of state.
All output fields are audit metadata and are not a model feature contract.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


CUTOFF = pd.Timestamp("2018-05-01")
DAY_NS = int(pd.Timedelta(days=1).value)
BASES = {"seller90": ("seller", 90), "route90": ("route", 90),
         "joint90": ("joint", 90), "route30": ("route", 30)}
COUNTERS = (
    "approved", "completed", "pending", "invalid_delivery",
    "pending_active", "pending_overdue", "pending_invalid_promise",
    "pending_missing_promise", "pending_negative_promise",
    "pending_no_carrier_event", "delivery_equal_query", "completed_legacy",
    "pending_legacy", "completed_legacy_excluded", "pending_legacy_excluded",
    "legacy_delivery_window", "legacy_delivery_old_approval",
    "completed_valid_promise", "pending_valid_promise",
    "completed_promise_days_sum", "pending_promise_days_sum",
)
AGE_BINS = {90: ((0, 7), (7, 14), (14, 30), (30, 60), (60, 90)),
            30: ((0, 7), (7, 14), (14, 30))}
_FIELDS = (
    "completed", "pending", "invalid_delivery", "pending_active",
    "pending_overdue", "pending_invalid_promise", "pending_no_carrier_event",
    "pending_missing_promise", "pending_negative_promise",
    "completed_legacy", "pending_legacy", "completed_valid_promise",
    "pending_valid_promise", "completed_promise_days_sum", "pending_promise_days_sum",
)
_FIELD = {name: i for i, name in enumerate(_FIELDS)}


def counter_names(window):
    return COUNTERS + tuple(f"{state}_age_{low}_{high}"
                            for state in ("completed", "pending")
                            for low, high in AGE_BINS[window])


def _times(values, name, *, required=False):
    try:
        result = pd.to_datetime(values, errors="coerce", format="mixed")
        if result.dt.tz is not None or (required and result.isna().any()):
            raise ValueError("Invalid timestamp")
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain timezone-naive timestamps") from error
    return result


def _ids(frame, name):
    if (frame.order_id.isna().any() or frame.order_id.duplicated().any()
            or not frame.order_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
        raise ValueError(f"{name} order IDs must be unique nonempty strings")


def _known(value):
    return value is not None and not pd.isna(value) and str(value).strip() != ""


def _keys(frame):
    sellers = [str(value) if _known(value) else None for value in frame.primary_seller_id]
    routes = [str(value) if _known(value) else None for value in frame.state_route]
    joints = [(seller, route) if seller is not None and route is not None else None
              for seller, route in zip(sellers, routes, strict=True)]
    return {"seller": sellers, "route": routes, "joint": joints}


class _Ledger:
    """Fenwick sums for the current observed state at each approval position."""

    def __init__(self, size):
        self.tree = np.zeros((size + 1, len(_FIELDS)), dtype=float)

    def update(self, position, delta):
        index = position + 1
        while index < len(self.tree):
            self.tree[index] += delta
            index += index & -index

    def prefix(self, stop):
        value = np.zeros(len(_FIELDS), dtype=float)
        while stop:
            value += self.tree[stop]
            stop -= stop & -stop
        return value

    def interval(self, lower, upper):
        return self.prefix(upper) - self.prefix(lower)


def _state_values(state, overdue, carrier, valid_promise, promise_days, legacy):
    result = np.zeros(len(_FIELDS), dtype=float)
    if state == 1:
        result[_FIELD["pending"]] = 1.
        result[_FIELD["pending_overdue" if overdue else "pending_active"
                      if valid_promise else "pending_invalid_promise"]] = 1.
        result[_FIELD["pending_no_carrier_event"]] = float(not carrier)
        result[_FIELD["pending_missing_promise"]] = float(not np.isfinite(promise_days))
        result[_FIELD["pending_negative_promise"]] = float(np.isfinite(promise_days) and promise_days < 0)
        result[_FIELD["pending_legacy"]] = float(legacy)
        result[_FIELD["pending_valid_promise"]] = float(valid_promise)
        result[_FIELD["pending_promise_days_sum"]] = promise_days if valid_promise else 0.
    elif state == 2:
        result[_FIELD["completed"]] = 1.
        result[_FIELD["completed_legacy"]] = float(legacy)
        result[_FIELD["completed_valid_promise"]] = float(valid_promise)
        result[_FIELD["completed_promise_days_sum"]] = promise_days if valid_promise else 0.
    elif state == 3:
        result[_FIELD["invalid_delivery"]] = 1.
    return result


def _group_outputs(approvals, deliveries, delivery_present, carriers, carrier_present,
                   deadlines, valid_promise, promise_days, legacy, query_times, windows):
    """One group sweep; route30 and route90 share the same observed-state ledger."""
    outputs = {window: np.zeros((len(query_times), len(counter_names(window))), dtype=float)
               for window in windows}
    used = {window: np.zeros(len(approvals), dtype=bool) for window in windows}
    if not len(approvals) or not len(query_times):
        return outputs, used
    ledger = _Ledger(len(approvals))
    state = np.zeros(len(approvals), dtype=np.int8)
    overdue = np.zeros(len(approvals), dtype=bool)
    carrier = np.zeros(len(approvals), dtype=bool)
    delivery_order = np.flatnonzero(delivery_present)
    delivery_order = delivery_order[np.argsort(deliveries[delivery_order], kind="stable")]
    carrier_order = np.flatnonzero(carrier_present)
    carrier_order = carrier_order[np.argsort(carriers[carrier_order], kind="stable")]
    deadline_order = np.flatnonzero(valid_promise)
    deadline_order = deadline_order[np.argsort(deadlines[deadline_order], kind="stable")]
    legacy_deliveries = np.sort(deliveries[legacy & delivery_present])
    query_order = np.argsort(query_times, kind="stable")
    sorted_queries = query_times[query_order]
    next_query = np.searchsorted(sorted_queries, approvals, side="right")
    exists = next_query < len(sorted_queries)
    for window in windows:
        selected = np.flatnonzero(exists)
        used[window][selected] = sorted_queries[next_query[selected]] <= approvals[selected] + window * DAY_NS
    approval_position = delivery_position = carrier_position = deadline_position = 0

    def values(position):
        return _state_values(state[position], overdue[position], carrier[position],
                             valid_promise[position], promise_days[position], legacy[position])

    for query_position in query_order:
        now = query_times[query_position]
        while approval_position < len(approvals) and approvals[approval_position] < now:
            position = approval_position
            if delivery_present[position] and deliveries[position] < now:
                state[position] = 2 if deliveries[position] >= approvals[position] else 3
            else:
                state[position] = 1
            overdue[position] = valid_promise[position] and deadlines[position] <= now
            carrier[position] = carrier_present[position] and carriers[position] < now
            ledger.update(position, values(position))
            approval_position += 1
        while delivery_position < len(delivery_order) and deliveries[delivery_order[delivery_position]] < now:
            position = delivery_order[delivery_position]
            if state[position] == 1:
                before = values(position)
                state[position] = 2 if deliveries[position] >= approvals[position] else 3
                ledger.update(position, values(position) - before)
            delivery_position += 1
        while carrier_position < len(carrier_order) and carriers[carrier_order[carrier_position]] < now:
            position = carrier_order[carrier_position]
            if state[position] == 1 and not carrier[position]:
                before = values(position)
                carrier[position] = True
                ledger.update(position, values(position) - before)
            carrier_position += 1
        while deadline_position < len(deadline_order) and deadlines[deadline_order[deadline_position]] <= now:
            position = deadline_order[deadline_position]
            if state[position] == 1 and not overdue[position]:
                before = values(position)
                overdue[position] = True
                ledger.update(position, values(position) - before)
            deadline_position += 1
        upper = int(np.searchsorted(approvals, now, side="left"))
        equal_left = np.searchsorted(deliveries[delivery_order], now, side="left")
        equal_right = np.searchsorted(deliveries[delivery_order], now, side="right")
        equal_approvals = approvals[delivery_order[equal_left:equal_right]]
        for window in windows:
            lower_time = now - window * DAY_NS
            lower = int(np.searchsorted(approvals, lower_time, side="left"))
            totals = ledger.interval(lower, upper)
            counts = dict(zip(_FIELDS, totals, strict=True))
            counts["approved"] = upper - lower
            counts["delivery_equal_query"] = int(np.count_nonzero((equal_approvals >= lower_time) & (equal_approvals < now)))
            counts["completed_legacy_excluded"] = counts["completed"] - counts["completed_legacy"]
            counts["pending_legacy_excluded"] = counts["pending"] - counts["pending_legacy"]
            counts["legacy_delivery_window"] = (np.searchsorted(legacy_deliveries, now, side="left")
                                                  - np.searchsorted(legacy_deliveries, lower_time, side="left"))
            counts["legacy_delivery_old_approval"] = counts["legacy_delivery_window"] - counts["completed_legacy"]
            for age_low, age_high in AGE_BINS[window]:
                age_left = int(np.searchsorted(approvals, now - age_high * DAY_NS,
                                              side="left" if age_high == window else "right"))
                age_right = int(np.searchsorted(approvals, now - age_low * DAY_NS,
                                               side="right" if age_low else "left"))
                age = ledger.interval(age_left, age_right)
                for label in ("completed", "pending"):
                    counts[f"{label}_age_{age_low}_{age_high}"] = age[_FIELD[label]]
            outputs[window][query_position] = [counts[name] for name in counter_names(window)]
    return outputs, used


def _validate(queries, history):
    query_required = {"order_id", "prediction_time", "primary_seller_id", "state_route"}
    history_required = query_required | {"purchase_time", "delivery_time", "carrier_time",
                                         "promise_time", "legacy_eligible"}
    for frame, required, name in ((queries, query_required, "Query"), (history, history_required, "History")):
        if required.difference(frame.columns):
            raise ValueError(f"Missing {name} columns: {sorted(required.difference(frame.columns))}")
        _ids(frame, name)
    query_times = _times(queries.prediction_time, "query prediction_time", required=True)
    approvals = _times(history.prediction_time, "history prediction_time", required=True)
    purchases = _times(history.purchase_time, "history purchase_time", required=True)
    if query_times.ge(CUTOFF).any() or approvals.ge(CUTOFF).any():
        raise ValueError("Query and history approvals must precede May 2018")
    if approvals.lt(purchases).any():
        raise ValueError("History purchase must not follow approval")
    optional = {name: _times(history[name], name) for name in ("delivery_time", "carrier_time", "promise_time")}
    if any(optional[name].ge(CUTOFF).any() for name in ("delivery_time", "carrier_time")):
        raise ValueError("Delivery and carrier events at or after cutoff must be masked")
    if not history.legacy_eligible.map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError("legacy_eligible must contain non-null booleans")
    if len(history):
        shared = queries.order_id.map(pd.Series(approvals.to_numpy(), index=history.order_id))
        selected = shared.notna().to_numpy()
        if (query_times.to_numpy()[selected] != shared.to_numpy()[selected]).any():
            raise ValueError("Shared order IDs must have identical approval timestamps")
    promise_valid = optional["promise_time"].notna() & optional["promise_time"].dt.normalize().ge(approvals.dt.normalize())
    valid_observed_delivery = optional["delivery_time"].isna() | optional["delivery_time"].ge(approvals)
    if (history.legacy_eligible & (~promise_valid | ~valid_observed_delivery)).any():
        raise ValueError("Legacy eligibility contradicts observed delivery or promise clocks")
    return query_times, approvals, optional, promise_valid


def build_representation(queries: pd.DataFrame, history: pd.DataFrame):
    """Append frozen-window audit counters while preserving original rows.

    ``history`` already contains only valid purchase<=approval records. Its
    delivery/carrier events at or after May 2018 must be masked by the caller.
    Delivery strictly before t establishes completion; equality remains pending.
    Invalid observed deliveries form a separate partition. A valid promise is
    present and no earlier than its approval calendar day. Overdue begins at
    midnight after that promise date. Any carrier<t ends the no-carrier proxy,
    even when that observed carrier contradicts approval. Unknown group keys
    remain NaN and are never pooled; known empty groups have zero counters.

    Legacy flags affect only legacy-named retrospective metadata. Promise sums
    use calendar promise days; age bins use elapsed query-minus-approval days
    in both completed and unfinished cohorts. No future duration is imputed.
    """
    query_dates, approvals, optional, valid_promise = _validate(queries, history)
    query_ns = query_dates.to_numpy(dtype="datetime64[ns]").view("int64")
    raw_ns = approvals.to_numpy(dtype="datetime64[ns]").view("int64")
    dates = {name: value.to_numpy(dtype="datetime64[ns]").view("int64") for name, value in optional.items()}
    deadlines = (optional["promise_time"].dt.normalize() + pd.Timedelta(days=1)).to_numpy(dtype="datetime64[ns]").view("int64")
    promise_days = (optional["promise_time"].dt.normalize() - approvals.dt.normalize()).dt.days.to_numpy(dtype=float)
    legacy = history.legacy_eligible.to_numpy(dtype=bool)
    delivery_present = optional["delivery_time"].notna().to_numpy()
    carrier_present = optional["carrier_time"].notna().to_numpy()
    promise_present = valid_promise.to_numpy()
    query_keys, raw_keys = _keys(queries), _keys(history)
    audit = {}
    quality = {"history_rows": len(history), "query_rows": len(queries), "bases": {},
               "scope": "Query-history occurrences overlap; distinct rows are counted separately per basis.",
               "legacy_flags_used_for_asof_state": False, "new_model_features": 0}
    for kind in ("seller", "route", "joint"):
        bases = [(basis, window) for basis, (group, window) in BASES.items() if group == kind]
        windows = [window for _, window in bases]
        arrays = {window: np.full((len(queries), len(counter_names(window))), np.nan) for window in windows}
        raw_groups, query_groups = {}, {}
        for position, key in enumerate(raw_keys[kind]):
            if key is not None:
                raw_groups.setdefault(key, []).append(position)
        for position, key in enumerate(query_keys[kind]):
            if key is not None:
                query_groups.setdefault(key, []).append(position)
        used_counts = {window: 0 for window in windows}
        for key, query_positions in query_groups.items():
            raw_positions = np.array(raw_groups.get(key, []), dtype=np.int64)
            raw_positions = raw_positions[np.argsort(raw_ns[raw_positions], kind="stable")]
            selected_queries = np.array(query_positions, dtype=np.int64)
            outputs, used = _group_outputs(
                raw_ns[raw_positions], dates["delivery_time"][raw_positions], delivery_present[raw_positions],
                dates["carrier_time"][raw_positions], carrier_present[raw_positions],
                deadlines[raw_positions], promise_present[raw_positions], promise_days[raw_positions],
                legacy[raw_positions], query_ns[selected_queries], windows)
            for window in windows:
                arrays[window][selected_queries] = outputs[window]
                used_counts[window] += int(used[window].sum())
        known = np.array([key is not None for key in query_keys[kind]], dtype=bool)
        for basis, window in bases:
            audit[f"audit_{basis}_key_known"] = known.astype(float)
            for column, values in zip(counter_names(window), arrays[window].T, strict=True):
                audit[f"audit_{basis}_{column}"] = values
            quality["bases"][basis] = {"window_days": window, "known_query_rows": int(known.sum()),
                "unknown_query_rows": int((~known).sum()), "distinct_history_rows_used": used_counts[window],
                "query_history_occurrences": int(np.nansum(arrays[window][:, 0]))}
    collisions = set(audit).intersection(queries.columns)
    if collisions:
        raise ValueError(f"Audit columns already exist: {sorted(collisions)}")
    audit_order = [f"audit_{basis}_{name}" for basis, (_, window) in BASES.items()
                   for name in ("key_known", *counter_names(window))]
    extra = pd.DataFrame(audit, index=queries.index)[audit_order]
    for basis, (_, window) in BASES.items():
        prefix = f"audit_{basis}_"
        known = extra[prefix + "key_known"].eq(1)
        counts = extra.loc[known]
        if not counts.empty:
            if (counts.drop(columns=[prefix + "key_known"], errors="ignore").filter(like=prefix).to_numpy() < 0).any():
                raise AssertionError("Audit counters must be nonnegative")
            np.testing.assert_array_equal(counts[prefix + "approved"], counts[[prefix + name for name in ("completed", "pending", "invalid_delivery")]].sum(axis=1))
            np.testing.assert_array_equal(counts[prefix + "pending"], counts[[prefix + name for name in ("pending_active", "pending_overdue", "pending_invalid_promise")]].sum(axis=1))
            np.testing.assert_array_equal(counts[prefix + "pending_invalid_promise"], counts[prefix + "pending_missing_promise"] + counts[prefix + "pending_negative_promise"])
            np.testing.assert_array_equal(counts[prefix + "legacy_delivery_window"], counts[prefix + "completed_legacy"] + counts[prefix + "legacy_delivery_old_approval"])
            for state in ("completed", "pending"):
                np.testing.assert_array_equal(counts[prefix + state], counts[[prefix + f"{state}_age_{low}_{high}" for low, high in AGE_BINS[window]]].sum(axis=1))
    return pd.concat([queries.copy(), extra], axis=1), quality
