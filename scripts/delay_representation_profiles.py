"""Fixed-condition summaries of approval-cohort representation audit counters.

Audit ratios describe the observed history, never a model probability or gain.
The existing conditional arithmetic is reused without altering its thresholds,
weights, ties, support clocks or frozen miss identities.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from scripts import delay_conditional_mature_signals as old
from scripts import delay_history_representativeness as core
from scripts import delay_mature_signal_profiles as profiles


SEEDS = old.SEEDS
FOCUS_GROUPS = old.FOCUS_GROUPS
BASES = tuple(core.BASES)
COMPARISON_BASES = ("seller90", "joint90", "route90")
METRICS = ("pending_share", "overdue_pending_share")
SCHEMES = ("promise_bin", "promise_days", "promise_days_weekday")
SUPPORT_BY_BASIS = {"seller90": ("seller90",), "joint90": ("joint90",),
                    "route90": ("route30", "route90")}
_CANDIDATE = dict(zip(COMPARISON_BASES, old.CANDIDATE_FEATURES, strict=True))
_NUMERATOR = {"pending_share": "pending", "overdue_pending_share": "pending_overdue"}
EPSILON = old.EPSILON
COHORTS = ("all_known", "unknown", "common20", "known_on_time", "other_delayed")


def query_metric(audit, basis, metric):
    """Return an unsmoothed query ratio; unknown/empty history remains missing."""
    if basis not in BASES or metric not in METRICS:
        raise ValueError("Unknown representation basis or metric")
    prefix = f"audit_{basis}_"
    numerator = profiles._numeric(audit[prefix + _NUMERATOR[metric]])
    denominator = profiles._numeric(audit[prefix + "approved"])
    keys = profiles._numeric(audit[prefix + "key_known"])
    return np.divide(numerator, denominator, out=np.full(len(audit), np.nan),
                     where=(keys == 1) & np.isfinite(numerator) & (denominator > 0))


def derive_metrics(audit):
    """Six outcome-free ratios for the three prespecified comparison bases."""
    return {f"{basis}_{metric}": query_metric(audit, basis, metric)
            for basis in COMPARISON_BASES for metric in METRICS}


def _audit_arrays(frame, audit):
    if not isinstance(audit, pd.DataFrame) or not audit.index.equals(frame.index) or len(audit) != len(frame):
        raise ValueError("Audit frame must have the same ordered query index")
    for name in ("order_id", "prediction_time"):
        if name not in frame or name not in audit:
            raise ValueError("Query/audit identity and approval clocks are required")
    if (frame.order_id.isna().any() or frame.order_id.duplicated().any()
            or not frame.order_id.equals(audit.order_id)):
        raise ValueError("Audit query identities/order must equal the unique frame identities")
    clocks = [pd.to_datetime(values.prediction_time, errors="raise", format="mixed") for values in (frame, audit)]
    if not clocks[0].equals(clocks[1]):
        raise ValueError("Audit query approval clocks must equal the frame clocks")
    arrays = {}
    for basis, (_, window) in core.BASES.items():
        prefix = f"audit_{basis}_"
        names = ("key_known", *core.counter_names(window))
        if any(prefix + name not in audit for name in names):
            raise ValueError(f"Missing representation audit columns for {basis}")
        values = {name: profiles._numeric(audit[prefix + name]) for name in names}
        key = values.pop("key_known")
        if not np.isfinite(key).all() or not np.isin(key, [0., 1.]).all():
            raise ValueError("Audit key-known flags must be complete binary values")
        known = key == 1
        for name, data in values.items():
            if (not np.isfinite(data[known]).all() or (data[known] < 0).any()
                    or not np.equal(data[known], np.floor(data[known])).all()
                    or not np.isnan(data[~known]).all()):
                raise ValueError("Audit counters must be nonnegative integer values for known keys and NaN for unknown keys")
        def same(left, right):
            if not np.array_equal(left[known], right[known]):
                raise ValueError(f"Audit counter conservation failed for {basis}")
        same(values["approved"], values["completed"] + values["pending"] + values["invalid_delivery"])
        same(values["pending"], values["pending_active"] + values["pending_overdue"] + values["pending_invalid_promise"])
        same(values["pending_invalid_promise"], values["pending_missing_promise"] + values["pending_negative_promise"])
        same(values["completed"], values["completed_legacy"] + values["completed_legacy_excluded"])
        same(values["pending"], values["pending_legacy"] + values["pending_legacy_excluded"])
        same(values["legacy_delivery_window"], values["completed_legacy"] + values["legacy_delivery_old_approval"])
        for state in ("completed", "pending"):
            same(values[state], sum(values[f"{state}_age_{low}_{high}"] for low, high in core.AGE_BINS[window]))
            if (values[f"{state}_valid_promise"][known] > values[state][known]).any():
                raise ValueError("Valid-promise count cannot exceed its state count")
        if (values["delivery_equal_query"][known] > values["pending"][known]).any():
            raise ValueError("Delivery-equality boundary must be a subset of pending")
        arrays[basis] = {"known": known, "counters": values,
                         "metrics": {metric: query_metric(audit, basis, metric) for metric in METRICS}}
    return arrays


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _mean(values, mask):
    selected = values[mask & np.isfinite(values)]
    return {"finite_rows": len(selected), "missing_rows": int(mask.sum()) - len(selected),
            "mean": float(selected.mean()) if len(selected) else None}


def _profile(mask, basis, values):
    known, counts = values["known"], values["counters"]
    selected = mask & known
    totals = {name: int(data[selected].sum()) for name, data in counts.items()}
    output = {"rows": int(mask.sum()), "known_key_rows": int(selected.sum()),
              "unknown_key_rows": int((mask & ~known).sum()),
              "known_zero_approval_rows": int((selected & (counts["approved"] == 0)).sum()),
              "positive_approval_rows": int((selected & (counts["approved"] > 0)).sum()),
              "counter_sums": totals,
              "query_ratios": {name: _mean(data, mask) for name, data in values["metrics"].items()},
              "pooled_occurrence_ratios": {
                  "pending_share": _ratio(totals["pending"], totals["approved"]),
                  "overdue_pending_share": _ratio(totals["pending_overdue"], totals["approved"]),
                  "overdue_among_valid_promise_pending": _ratio(totals["pending_overdue"], totals["pending_valid_promise"])},
              "age_composition": {}, "valid_promise_days": {}}
    window = core.BASES[basis][1]
    for state in ("completed", "pending"):
        bins = {}
        for low, high in core.AGE_BINS[window]:
            name = f"{state}_age_{low}_{high}"
            query_share = np.divide(counts[name], counts[state], out=np.full(len(mask), np.nan),
                                    where=known & (counts[state] > 0))
            bins[f"{low}_{high}"] = {"occurrences": totals[name],
                                      "pooled_occurrence_share": _ratio(totals[name], totals[state]),
                                      "query_share": _mean(query_share, mask)}
        output["age_composition"][state] = bins
        n, total = counts[f"{state}_valid_promise"], counts[f"{state}_promise_days_sum"]
        query_mean = np.divide(total, n, out=np.full(len(mask), np.nan), where=known & (n > 0))
        output["valid_promise_days"][state] = {
            "valid_promise_occurrences": totals[f"{state}_valid_promise"],
            "pooled_occurrence_mean": _ratio(totals[f"{state}_promise_days_sum"], totals[f"{state}_valid_promise"]),
            "query_mean": _mean(query_mean, mask)}
    return output


def _with_weekday(setup, weekdays):
    keys = [setup["keys"][code] + [int(day)] for code, day in zip(setup["codes"], weekdays, strict=True)]
    columns = setup["columns"] + ["approval_weekday"]
    arrays = [[key[i] for key in keys] for i in range(len(columns))]
    codes, unique = pd.factorize(pd.MultiIndex.from_arrays(arrays), sort=False)
    public = [[None if pd.isna(value) else value for value in key] for key in unique.tolist()]
    local = np.zeros(len(unique), dtype=bool)
    local[codes[setup["local"][setup["codes"]]]] = True
    ordered = np.argsort(codes, kind="stable")
    boundaries = np.flatnonzero(np.diff(codes[ordered])) + 1
    positions = np.split(ordered, boundaries) if len(unique) else []
    return {"codes": codes, "keys": public, "columns": columns, "local": local, "positions": positions}


def _compact_strata(setup, aggregates, orderings):
    columns = setup["columns"] + ["full_batch_n"]
    for name in ("common20", "known_on_time", "other_delayed"):
        columns += [f"{name}_{field}" for field in ("n", "finite_n", "mean")]
    for name in ("known_on_time", "other_delayed"):
        columns += [f"{name}_{field}" for field in ("native_difference", "finite_overlap", "cohort_adequate", "supported", "order_probability")]
    rows, missed = [], aggregates["common20"]
    for code in np.flatnonzero(aggregates["full_batch"]["count"]):
        row = setup["keys"][code] + [int(aggregates["full_batch"]["count"][code])]
        for name in ("common20", "known_on_time", "other_delayed"):
            value = aggregates[name]
            row += [int(value["count"][code]), int(value["n"][code]), old._public_number(value["mean"][code])]
        for name in ("known_on_time", "other_delayed"):
            control = aggregates[name]
            nm, nc = missed["n"][code], control["n"][code]
            overlap, adequate = bool(nm >= 1 and nc >= 1), bool(nm >= 3 and nc >= 5)
            difference = old._public_number(missed["mean"][code] - control["mean"][code]) if overlap else None
            row += [difference, overlap, adequate, adequate and bool(setup["local"][code]),
                    old._public_number(orderings[name]["order_probability"][code])]
        rows.append(row)
    return {"columns": columns, "rows": rows}


def compare_phase(frame, audit_aligned, known, common20, common4_by_seed, *, include_strata=False):
    """Summarize fixed query cohorts and compare audit ratios in fixed strata."""
    if not isinstance(frame, pd.DataFrame) or not isinstance(include_strata, (bool, np.bool_)):
        raise ValueError("Require a query DataFrame and boolean include_strata")
    if (not isinstance(common4_by_seed, Mapping) or set(common4_by_seed) != set(SEEDS)
            or any(isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer)) for seed in common4_by_seed)):
        raise ValueError("Require exactly the five fixed integer seed keys")
    known = profiles._boolean(known, frame, "known")
    common20 = profiles._boolean(common20, frame, "common20")
    seeds = {seed: profiles._boolean(common4_by_seed[seed], frame, f"common4 seed {seed}") for seed in SEEDS}
    labels = profiles._known_labels(frame, known)
    positive, on_time = known & (labels == 1), known & (labels == 0)
    if not np.array_equal(common20, np.logical_and.reduce(list(seeds.values()))):
        raise ValueError("Common20 identity mask must equal the five-seed intersection")
    if any(np.any(mask & ~positive) for mask in (common20, *seeds.values())):
        raise ValueError("Common miss masks may contain only known delayed queries")
    arrays = _audit_arrays(frame, audit_aligned)
    groups = old._groups(frame)
    supports = profiles._support_arrays(frame, old.SUPPORT_MAPPING)
    if any(not np.array_equal(arrays[basis]["known"], supports[basis][1]) for basis in BASES):
        raise ValueError("Audit group key-known flags must equal the original mature-support flags")
    prepared = old._prepare(frame, supports)
    weekdays = pd.to_datetime(frame.prediction_time, errors="raise", format="mixed").dt.dayofweek.to_numpy()
    setups = {}
    for basis, candidate in _CANDIDATE.items():
        for scheme in SCHEMES[:2]:
            setups[scheme, basis] = prepared[scheme, candidate]
        setups[SCHEMES[2], basis] = _with_weekday(prepared["promise_days", candidate], weekdays)
    masks = {"full_batch": np.ones(len(frame), dtype=bool), "known": known, "unknown": ~known,
             "positive": positive, "common20": common20, "known_on_time": on_time,
             "other_delayed": positive & ~common20}
    cohorts = {"all_known": known, "unknown": ~known, "common20": common20,
               "known_on_time": on_time, "other_delayed": positive & ~common20}
    result = {"rows": len(frame), "contract": {
        "bases": list(BASES), "comparison_bases": list(COMPARISON_BASES), "metrics": list(METRICS),
        "schemes": list(SCHEMES), "seeds": list(SEEDS),
        "support_by_basis": {basis: list(values) for basis, values in SUPPORT_BY_BASIS.items()},
        "cohort_min_common": 3, "cohort_min_control": 5, "local_support_min": 20, "epsilon": EPSILON,
        "risk_sign": 1, "full_strata_included": bool(include_strata),
        "condition_scope": "Conditions fix current query route/promise/approval week/support; they do not equate historical orders' own promise or elapsed ages.",
        "ratios": "Unsmoothed pending/approved and overdue-pending/approved within one approval cohort. Unknown keys and approved=0 are missing; query means and pooled occurrence ratios are distinct.",
        "weighting": "Finite common-miss n weights differences and order probabilities; control means standardized to those weights. Equal-stratum sensitivity is also retained.",
        "clock": "Support bins retain original delivery-event counts, not new approval-cohort counts. Week Monday00:00, weekday Mon0..Sun6; strict event clocks and history state defined by upstream audit.",
        "interpretation": "Audit associations only; +1 orientation is a prespecified hypothesis, not model risk. Overlapping windows, groups, reused controls and seeds are not independent samples. No training or automatic selection."},
        "groups": {}}
    for name, group in groups.items():
        denominator = {f"{field}_rows": int((group & mask).sum()) for field, mask in masks.items()}
        denominator.update({"known_delay_rate": _ratio(denominator["positive_rows"], denominator["known_rows"]),
                            "common20_fraction_of_delays": _ratio(denominator["common20_rows"], denominator["positive_rows"]),
                            "common4_by_seed": {str(seed): int((group & mask).sum()) for seed, mask in seeds.items()}})
        row = {"denominators": denominator,
               "cohorts": {cohort: {basis: _profile(group & mask, basis, values) for basis, values in arrays.items()}
                           for cohort, mask in cohorts.items()},
               "comparisons": {scheme: {} for scheme in SCHEMES}}
        if name in FOCUS_GROUPS:
            row["common4_by_seed"] = {str(seed): {
                "profile": {basis: _profile(group & mask, basis, values) for basis, values in arrays.items()},
                "comparisons": {scheme: {} for scheme in SCHEMES}} for seed, mask in seeds.items()}
        for scheme in SCHEMES:
            for basis in COMPARISON_BASES:
                setup = setups[scheme, basis]
                row["comparisons"][scheme][basis] = {}
                if name in FOCUS_GROUPS:
                    for seed in SEEDS:
                        row["common4_by_seed"][str(seed)]["comparisons"][scheme][basis] = {}
                for metric, values in arrays[basis]["metrics"].items():
                    aggregates = {cohort: old._aggregate(setup, group & masks[cohort], values)
                                  for cohort in ("full_batch", "common20", "known_on_time", "other_delayed")}
                    orderings = {control: old._ordering(setup, group & common20, group & masks[control], values, 1.)
                                 for control in ("known_on_time", "other_delayed")}
                    comparison = {control: old._comparison(setup, aggregates["common20"], aggregates[control], orderings[control], 1.)
                                  for control in orderings}
                    if name in FOCUS_GROUPS:
                        if include_strata:
                            comparison["strata"] = _compact_strata(setup, aggregates, orderings)
                        for seed, mask in seeds.items():
                            missed = old._aggregate(setup, group & mask, values)
                            order = old._ordering(setup, group & mask, group & on_time, values, 1.)
                            row["common4_by_seed"][str(seed)]["comparisons"][scheme][basis][metric] = old._comparison(
                                setup, missed, aggregates["known_on_time"], order, 1.)
                    row["comparisons"][scheme][basis][metric] = comparison
        result["groups"][name] = row
    for name in masks:
        field = f"{name}_rows"
        if sum(result["groups"][f"cell:{cell}"]["denominators"][field] for cell in profiles.intersections.CELLS) != result["groups"]["ALL"]["denominators"][field]:
            raise AssertionError("Eight fixed cells must reconcile with all query denominators")
    return result


def _direction(value):
    return None if value is None else 1 if value > EPSILON else -1 if value < -EPSILON else 0


def _phase_screen(group, basis, metric):
    effects = {scheme: group["comparisons"][scheme][basis][metric]["known_on_time"]["effects"]["supported"] for scheme in SCHEMES}
    sufficient = all(row["common_n"] >= 20 and row["week_count"] >= 3 for row in effects.values())
    signs = [_direction(value) for row in effects.values()
             for value in (row["risk_difference"], row["order_probability"] - .5 if row["order_probability"] is not None else None)]
    aligned = signs[0] in (-1, 1) and all(sign == signs[0] for sign in signs)
    seed_directions = {}
    for seed in SEEDS:
        values = []
        for scheme in SCHEMES:
            row = group["common4_by_seed"][str(seed)]["comparisons"][scheme][basis][metric]["effects"]["supported"]
            values += [_direction(row["risk_difference"]), _direction(row["order_probability"] - .5) if row["order_probability"] is not None else None]
        seed_directions[str(seed)] = values
    seed_aligned = aligned and all(all(sign == signs[0] for sign in values) for values in seed_directions.values())
    return {"data_sufficient_all_three_schemes": sufficient, "all_three_scheme_directions_aligned": aligned,
            "all_five_seed_directions_aligned": seed_aligned, "direction": signs[0] if aligned else None,
            "work_screen_passed": bool(sufficient and aligned and seed_aligned),
            "supported_by_scheme": {scheme: {field: row[field] for field in
                ("common_n", "control_n", "strata_count", "week_count", "risk_difference", "order_probability")} for scheme, row in effects.items()},
            "seed_directions": seed_directions}


def representation_screen(phases, metadata):
    """Report predeclared descriptive consistency flags on three disjoint months."""
    keys = [key for key, plan in metadata.items() if plan["ledger_role"] == "evaluation"]
    if len(keys) != 3 or len({metadata[key]["month"] for key in keys}) != 3:
        raise ValueError("Require three distinct inspected development months")
    results = {}
    for basis in COMPARISON_BASES:
        results[basis] = {}
        for metric in METRICS:
            results[basis][metric] = {}
            for group in FOCUS_GROUPS:
                monthly = {key: _phase_screen(phases[key]["groups"][group], basis, metric) for key in keys}
                by_sign = {str(sign): [key for key, row in monthly.items() if row["work_screen_passed"] and row["direction"] == sign] for sign in (-1, 1)}
                results[basis][metric][group] = {"development_phases": monthly,
                    "passing_months_by_direction": by_sign,
                    "work_screen_at_least_two_months": any(len(values) >= 2 for values in by_sign.values())}
    return {"by_basis": results, "automatic_training_selection": False,
            "interpretation": "Exploratory representation-association consistency only. A flag does not validate a new signal, significance, causality, incremental prediction, deployment or feature selection."}
