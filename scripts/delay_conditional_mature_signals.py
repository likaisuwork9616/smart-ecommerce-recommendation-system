"""Descriptive, fixed-stratum comparisons of approval-time mature signals.

The caller supplies one phase at a time and frozen miss identities. Nothing is
fit, ranked, coarsened or selected. Unknown query outcomes are never accessed.
Only aggregate counts and signal summaries are returned; identifiers are absent.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from scripts import delay_mature_signal_profiles as profiles
from scripts.delay_mature_history_audit import CANDIDATE_FEATURES


SEEDS = profiles.SEEDS
SUPPORT_BINS = profiles.SUPPORT_BINS
SUPPORT_MAPPING = profiles.SUPPORT_MAPPING
FOCUS_GROUPS = profiles.FOCUS_GROUPS
PROMISE_SCHEMES = ("promise_bin", "promise_days")
CANDIDATE_SUPPORTS = {
    CANDIDATE_FEATURES[0]: ("seller90",),
    CANDIDATE_FEATURES[1]: ("joint90",),
    CANDIDATE_FEATURES[2]: ("route30", "route90"),
}
RISK_SIGNS = {CANDIDATE_FEATURES[0]: -1., CANDIDATE_FEATURES[1]: 1., CANDIDATE_FEATURES[2]: 1.}
EPSILON = 1e-12
TIERS = ("finite_overlap", "cohort_adequate", "supported")
COHORT_NAMES = ("full_batch", "known", "unknown", "positive", "common20", "known_on_time", "other_delayed")


def _groups(frame):
    cells, original = profiles.intersections.group_masks(frame)
    groups = {name: original[name] for name in ("ALL", "R", "A", "RA")}
    groups.update({"R_not_A": original["R"] & ~original["A"],
                   "A_not_R": original["A"] & ~original["R"], "NOT_A": ~original["A"],
                   "SP->SC": frame.state_route.fillna("unknown").eq("SP->SC").to_numpy()})
    groups.update({f"cell:{cell}": cells == cell for cell in profiles.intersections.CELLS})
    return groups


def _prepare(frame, supports):
    if "prediction_time" not in frame:
        raise ValueError("Missing approval prediction_time")
    try:
        times = pd.to_datetime(frame["prediction_time"], errors="raise", format="mixed")
        if times.dt.tz is not None or times.isna().any():
            raise ValueError("invalid timestamps")
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError("Approval prediction_time must be complete timezone-naive timestamps") from error
    weeks = (times.dt.normalize() - pd.to_timedelta(times.dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")
    promise_bins = profiles.intersections.promise_bins(frame).to_numpy()
    days = profiles._numeric(frame["estimated_delivery_days"])
    if not np.equal(days, np.floor(days)).all():
        raise ValueError("Exact promise days must be finite nonnegative integers")
    routes = frame["state_route"].to_numpy(dtype=object)
    result = {}
    for scheme, promise in (("promise_bin", promise_bins), ("promise_days", days)):
        for candidate, names in CANDIDATE_SUPPORTS.items():
            arrays = [routes, promise, weeks.to_numpy(), *(supports[name][2] for name in names)]
            codes, keys = pd.factorize(pd.MultiIndex.from_arrays(arrays), sort=False)
            public_keys = [[None if pd.isna(value) else value for value in key] for key in keys.tolist()]
            local = np.logical_and.reduce([supports[name][1] & (supports[name][0] >= 20) for name in names])
            local_by_stratum = np.zeros(len(keys), dtype=bool)
            local_by_stratum[codes[local]] = True
            # The local support threshold is constant inside every fixed bin.
            if len(codes) and not np.array_equal(local_by_stratum[codes], local):
                raise AssertionError("Local-support threshold must be constant within a stratum")
            ordered = np.argsort(codes, kind="stable")
            boundaries = np.flatnonzero(np.diff(codes[ordered])) + 1
            positions = np.split(ordered, boundaries) if len(keys) else []
            result[scheme, candidate] = {"codes": codes, "keys": public_keys,
                                         "columns": ["state_route", scheme, "approval_week", *names],
                                         "local": local_by_stratum, "positions": positions}
    return result


def _aggregate(prepared, mask, values):
    codes, size = prepared["codes"], len(prepared["keys"])
    finite = mask & np.isfinite(values)
    count = np.bincount(codes[mask], minlength=size).astype(np.int64)
    n = np.bincount(codes[finite], minlength=size).astype(np.int64)
    sums = np.bincount(codes[finite], weights=values[finite], minlength=size)
    mean = np.divide(sums, n, out=np.full(size, np.nan), where=n > 0)
    return {"count": count, "n": n, "missing": count - n, "mean": mean}


def _ordering(prepared, miss_mask, control_mask, values, sign):
    size = len(prepared["keys"])
    pairs = np.zeros(size, dtype=np.int64)
    ties = np.zeros(size, dtype=np.int64)
    wins = np.zeros(size, dtype=np.int64)
    finite = np.isfinite(values)
    active = np.intersect1d(np.unique(prepared["codes"][miss_mask & finite]),
                            np.unique(prepared["codes"][control_mask & finite]))
    for code in active:
        positions = prepared["positions"][code]
        missed = values[positions[miss_mask[positions]]]
        controls = values[positions[control_mask[positions]]]
        missed, controls = sign * missed[np.isfinite(missed)], sign * controls[np.isfinite(controls)]
        if not len(missed) or not len(controls):
            continue
        controls.sort()
        below = np.searchsorted(controls, missed - EPSILON, side="left")
        above = np.searchsorted(controls, missed + EPSILON, side="right")
        pairs[code] = len(missed) * len(controls)
        ties[code] = int(np.sum(above - below))
        wins[code] = int(np.sum(below))
    probability = np.divide(wins + .5 * ties, pairs, out=np.full(size, np.nan), where=pairs > 0)
    return {"total_comparisons": pairs, "tie_pair_count": ties, "risk_win_pair_count": wins,
            "order_probability": probability}


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _effect(tier, missed, control, ordering, prepared, sign, *, include_weeks=True):
    count = int(tier.sum())
    common_n, control_n = int(missed["n"][tier].sum()), int(control["n"][tier].sum())
    result = {"strata_count": count,
              "week_count": len({prepared["keys"][i][2] for i in np.flatnonzero(tier)}),
              "common_n": common_n, "control_n": control_n,
              "common_weighted_mean": None, "standardized_control_mean": None,
              "native_difference": None, "risk_difference": None,
              "equal_stratum_native_difference": None, "equal_stratum_risk_difference": None,
              "order_probability": None, "equal_stratum_order_probability": None,
              "positive_strata": 0, "zero_strata": 0, "negative_strata": 0,
              "total_comparisons": int(ordering["total_comparisons"][tier].sum()),
              "tie_pair_count": int(ordering["tie_pair_count"][tier].sum()),
              "risk_win_pair_count": int(ordering["risk_win_pair_count"][tier].sum())}
    if count:
        weights = missed["n"][tier]
        left, right = missed["mean"][tier], control["mean"][tier]
        differences = left - right
        risk = sign * differences
        result.update({"common_weighted_mean": float(np.average(left, weights=weights)),
                       "standardized_control_mean": float(np.average(right, weights=weights)),
                       "native_difference": float(np.average(differences, weights=weights)),
                       "risk_difference": float(np.average(risk, weights=weights)),
                       "equal_stratum_native_difference": float(differences.mean()),
                       "equal_stratum_risk_difference": float(risk.mean()),
                       "order_probability": float(np.average(ordering["order_probability"][tier], weights=weights)),
                       "equal_stratum_order_probability": float(ordering["order_probability"][tier].mean()),
                       "positive_strata": int((risk > EPSILON).sum()),
                       "zero_strata": int((np.abs(risk) <= EPSILON).sum()),
                       "negative_strata": int((risk < -EPSILON).sum())})
    if include_weeks:
        result["by_week"] = []
        weeks = sorted({prepared["keys"][i][2] for i in np.flatnonzero(tier)})
        for week in weeks:
            week_mask = tier & np.array([key[2] == week for key in prepared["keys"]], dtype=bool)
            result["by_week"].append({"approval_week": week,
                                      **_effect(week_mask, missed, control, ordering, prepared, sign,
                                                include_weeks=False)})
    return result


def _comparison(prepared, missed, control, ordering, sign):
    nm, nc = missed["n"], control["n"]
    overlap = (nm >= 1) & (nc >= 1)
    adequate = (nm >= 3) & (nc >= 5)
    supported = adequate & prepared["local"]
    tiers = dict(zip(TIERS, (overlap, adequate, supported), strict=True))
    all_common, finite_common = int(missed["count"].sum()), int(nm.sum())
    uncovered = {"missing_signal": all_common - finite_common,
                 "no_control": int(nm[nc == 0].sum()),
                 "low_cohort": int(nm[(nc > 0) & ~adequate].sum()),
                 "low_local_support": int(nm[adequate & ~prepared["local"]].sum())}
    coverage = {"all_common": all_common, "finite_common": finite_common,
                **{name: int(nm[mask].sum()) for name, mask in tiers.items()}, "uncovered": uncovered,
                "finite_common_fraction_all_common": _ratio(finite_common, all_common),
                "common_below_three": int(nm[overlap & (nm < 3)].sum()),
                "control_below_five": int(nm[overlap & (nc < 5)].sum())}
    for name in TIERS:
        coverage[f"{name}_fraction_all_common"] = _ratio(coverage[name], all_common)
        coverage[f"{name}_fraction_finite_common"] = _ratio(coverage[name], finite_common)
    if sum(uncovered.values()) + coverage["supported"] != all_common:
        raise AssertionError("Mutually exclusive uncovered counts must reconcile with all common misses")
    miss_n, control_n = int(nm.sum()), int(nc.sum())
    miss_mean = float(np.average(missed["mean"][nm > 0], weights=nm[nm > 0])) if miss_n else None
    control_mean = float(np.average(control["mean"][nc > 0], weights=nc[nc > 0])) if control_n else None
    native = miss_mean - control_mean if miss_n and control_n else None
    return {"coverage": coverage,
            "unadjusted": {"common_n": miss_n, "control_n": control_n,
                           "common_mean": miss_mean, "control_mean": control_mean,
                           "native_difference": native, "risk_difference": sign * native if native is not None else None},
            "effects": {name: _effect(mask, missed, control, ordering, prepared, sign)
                        for name, mask in tiers.items()}}


def _public_number(value):
    if isinstance(value, (np.integer, int)):
        return int(value)
    return float(value) if np.isfinite(value) else None


def _strata(prepared, aggregates, orderings, sign):
    columns = list(prepared["columns"])
    for name in COHORT_NAMES:
        columns.extend(f"{name}_{field}" for field in ("n", "finite_n", "missing_n", "mean"))
    for name in ("known_on_time", "other_delayed"):
        columns.extend(f"{name}_{field}" for field in ("native_difference", "risk_difference", "finite_overlap",
                                                       "cohort_adequate", "supported", "total_comparisons",
                                                       "tie_pair_count", "risk_win_pair_count", "order_probability"))
    rows = []
    missed = aggregates["common20"]
    for code in np.flatnonzero(aggregates["full_batch"]["count"]):
        row = list(prepared["keys"][code])
        for name in COHORT_NAMES:
            aggregate = aggregates[name]
            row.extend(_public_number(aggregate[field][code]) for field in ("count", "n", "missing", "mean"))
        for name in ("known_on_time", "other_delayed"):
            control, ordering = aggregates[name], orderings[name]
            nm, nc = missed["n"][code], control["n"][code]
            overlap, adequate = bool(nm >= 1 and nc >= 1), bool(nm >= 3 and nc >= 5)
            difference = _public_number(missed["mean"][code] - control["mean"][code]) if overlap else None
            row.extend((difference, sign * difference if difference is not None else None,
                        overlap, adequate, adequate and bool(prepared["local"][code]),
                        int(ordering["total_comparisons"][code]), int(ordering["tie_pair_count"][code]),
                        int(ordering["risk_win_pair_count"][code]), _public_number(ordering["order_probability"][code])))
        rows.append(row)
    return {"columns": columns, "rows": rows}


def compare_phase(frame, known, common20, common4_by_seed, *, include_strata=True):
    """Compare frozen miss cohorts within prespecified approval-time strata.

    Input masks are complete, row-aligned booleans. Common20 is the identity
    intersection of the five fixed seed masks; all misses are known delayed.
    Strata use the entire state route, promise bin AND exact promise day (as
    separate fixed analyses), Monday 00:00 approval week, and each candidate's
    own local-support bin(s). No group is merged when overlap is inadequate.
    """
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Require a DataFrame of query signals")
    if not isinstance(include_strata, (bool, np.bool_)):
        raise ValueError("include_strata must be a boolean")
    missing = set(CANDIDATE_FEATURES).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing candidate signals: {sorted(missing)}")
    if (not isinstance(common4_by_seed, Mapping) or set(common4_by_seed) != set(SEEDS)
            or any(isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer))
                   for seed in common4_by_seed)):
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
    groups, supports = _groups(frame), profiles._support_arrays(frame, SUPPORT_MAPPING)
    prepared = _prepare(frame, supports)
    result = {"rows": len(frame), "candidate_features": list(CANDIDATE_FEATURES),
              "contract": {"promise_schemes": list(PROMISE_SCHEMES), "seeds": list(SEEDS),
                           "support_by_candidate": {name: list(values) for name, values in CANDIDATE_SUPPORTS.items()},
                           "support_bins": list(SUPPORT_BINS), "risk_signs": RISK_SIGNS.copy(),
                           "cohort_min_common": 3, "cohort_min_control": 5, "local_support_min": 20,
                           "epsilon": EPSILON, "week": "Monday 00:00; may cross months; caller never mixes phases",
                           "full_strata_included": bool(include_strata),
                           "primary_control": "known_on_time", "secondary_control": "other_delayed",
                           "weighting": "Finite common-miss n weights stratum differences and ordering probabilities; control means are standardized to the same weights.",
                           "ordering": "All within-stratum finite common/control pairs; risk wins plus half ties. Absolute pair differences <= epsilon are ties. Pairs are not independent samples.",
                           "interpretation": "Descriptive fixed overlapping groups; only eight R/P/A cells partition rows. No p values, confidence intervals, model selection or causal/gain claims. Zero-common strata and unknown keys remain visible."},
              "groups": {}}
    masks = {"full_batch": np.ones(len(frame), dtype=bool), "known": known, "unknown": ~known,
             "positive": positive, "common20": common20, "known_on_time": on_time,
             "other_delayed": positive & ~common20}
    signals = {candidate: profiles._numeric(frame[candidate]) for candidate in CANDIDATE_FEATURES}
    for group_name, group in groups.items():
        denominator = {f"{name}_rows": int((group & mask).sum()) for name, mask in masks.items()}
        denominator.update({"known_delay_rate": _ratio(denominator["positive_rows"], denominator["known_rows"]),
                            "common20_fraction_of_delays": _ratio(denominator["common20_rows"], denominator["positive_rows"]),
                            "common4_by_seed": {str(seed): int((group & mask).sum()) for seed, mask in seeds.items()}})
        row = {"denominators": denominator, "comparisons": {scheme: {} for scheme in PROMISE_SCHEMES}}
        if group_name in FOCUS_GROUPS:
            row["common4_by_seed"] = {str(seed): {scheme: {} for scheme in PROMISE_SCHEMES} for seed in SEEDS}
        for scheme in PROMISE_SCHEMES:
            for candidate, values in signals.items():
                setup, sign = prepared[scheme, candidate], RISK_SIGNS[candidate]
                aggregates = {name: _aggregate(setup, group & mask, values) for name, mask in masks.items()}
                ordering = {name: _ordering(setup, group & common20, group & masks[name], values, sign)
                            for name in ("known_on_time", "other_delayed")}
                comparison = {name: _comparison(setup, aggregates["common20"], aggregates[name], ordering[name], sign)
                              for name in ("known_on_time", "other_delayed")}
                if group_name in FOCUS_GROUPS:
                    if include_strata:
                        comparison["strata"] = _strata(setup, aggregates, ordering, sign)
                    for seed, seed_mask in seeds.items():
                        seed_aggregate = _aggregate(setup, group & seed_mask, values)
                        seed_order = _ordering(setup, group & seed_mask, group & on_time, values, sign)
                        row["common4_by_seed"][str(seed)][scheme][candidate] = _comparison(
                            setup, seed_aggregate, aggregates["known_on_time"], seed_order, sign)
                row["comparisons"][scheme][candidate] = comparison
        result["groups"][group_name] = row
    for name in masks:
        field = f"{name}_rows"
        if sum(result["groups"][f"cell:{cell}"]["denominators"][field]
               for cell in profiles.intersections.CELLS) != result["groups"]["ALL"]["denominators"][field]:
            raise AssertionError("Eight cell denominators must reconcile with ALL")
    return result
