"""Pure aggregate profiles of fixed, approval-time mature-history signals.

These profiles describe existing model misses. They never rank orders, choose
features, change alert capacity or read the outcome of an unknown query. Group
marginals overlap; only the eight fixed R/P/A cells form a partition.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from scripts import diagnose_age_intersections as intersections
from scripts.delay_mature_history_audit import CANDIDATE_FEATURES, RECOMPUTED_FEATURES


SEEDS = (11, 29, 42, 73, 101)
SIGNAL_FEATURES = tuple(RECOMPUTED_FEATURES + CANDIDATE_FEATURES)
SUPPORT_BINS = ("unknown_key", "0", "1-4", "5-19", "20-99", "100+")
SUPPORT_MAPPING = {
    "seller90": ("seller_completed_90d", "audit_seller_key_known"),
    "route90": ("route_completed_90d", "audit_route_key_known"),
    "joint90": ("audit_seller_route_completed_90d", "audit_seller_route_key_known"),
    "route30": ("audit_route_completed_30d", "audit_route_key_known"),
}
COHORTS = ("all_known", "known_on_time", "known_delayed", "common20", "other_delayed")
FOCUS_GROUPS = ("ALL", "R", "A", "RA", "SP->SC")


def _boolean(values, frame, name):
    """Reject truthy numbers, missing masks and silently misaligned Series."""
    if isinstance(values, pd.Series) and not values.index.equals(frame.index):
        raise ValueError(f"{name} Series index must match the ordered frame index")
    array = np.asarray(values)
    if array.ndim != 1 or len(array) != len(frame) or array.dtype.kind != "b":
        raise ValueError(f"{name} must be a row-aligned non-null boolean vector")
    return array.copy()


def _numeric(values):
    return pd.to_numeric(values, errors="coerce").to_numpy(dtype=float, na_value=np.nan)


def distribution(values):
    """Finite observations only; empty summaries remain JSON null, never NaN."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError("Distribution values must be one-dimensional")
    finite = array[np.isfinite(array)]
    result = {"rows": len(array), "finite": len(finite), "missing": len(array) - len(finite)}
    for name in ("mean", "p10", "p50", "p90", "min", "max"):
        result[name] = None
    if len(finite):
        result.update({"mean": float(np.mean(finite)), "min": float(np.min(finite)),
                       "max": float(np.max(finite))})
        result.update(dict(zip(("p10", "p50", "p90"),
                               map(float, np.quantile(finite, [.1, .5, .9], method="linear")),
                               strict=True)))
    return result


def _support_arrays(frame, support_mapping):
    if not isinstance(support_mapping, Mapping) or not support_mapping:
        raise ValueError("Require a nonempty named support mapping")
    result = {}
    for name, columns in support_mapping.items():
        if not isinstance(name, str) or not name or len(columns) != 2:
            raise ValueError("Support mapping requires a name and (count, key-known) columns")
        count_column, key_column = columns
        if count_column not in frame or key_column not in frame:
            raise ValueError(f"Missing support columns for {name}")
        counts = _numeric(frame[count_column])
        # Audit key flags are numeric 0/1 by contract, not nullable truthiness.
        keys = _numeric(frame[key_column])
        if not np.isfinite(keys).all() or not np.isin(keys, [0., 1.]).all():
            raise ValueError(f"{name} key-known flags must be complete binary values")
        known_keys = keys == 1.
        if (not np.isfinite(counts).all() or np.any(counts < 0)
                or not np.equal(counts, np.floor(counts)).all()):
            raise ValueError(f"{name} support counts must be finite nonnegative integers")
        if np.any((~known_keys) & (counts != 0)):
            raise ValueError(f"{name} unknown keys cannot have pooled history counts")
        bins = np.full(len(frame), "unknown_key", dtype=object)
        bins[known_keys & (counts == 0)] = "0"
        bins[known_keys & (counts >= 1) & (counts <= 4)] = "1-4"
        bins[known_keys & (counts >= 5) & (counts <= 19)] = "5-19"
        bins[known_keys & (counts >= 20) & (counts <= 99)] = "20-99"
        bins[known_keys & (counts >= 100)] = "100+"
        result[name] = (counts, known_keys, bins)
    return result


def _support_summary(mask, values):
    counts, known_keys, bins = values
    result = {"rows": int(mask.sum()),
              "bins": {name: int((mask & (bins == name)).sum()) for name in SUPPORT_BINS},
              "known_key_count_distribution": distribution(counts[mask & known_keys])}
    if sum(result["bins"].values()) != result["rows"]:
        raise AssertionError("Support bins do not partition the cohort")
    return result


def _profile(mask, signals, supports):
    return {"rows": int(mask.sum()),
            "distributions": {name: distribution(values[mask]) for name, values in signals.items()},
            "support": {name: _support_summary(mask, values) for name, values in supports.items()}}


def _known_labels(frame, known):
    if "delayed" not in frame:
        raise ValueError("Missing query delayed labels")
    labels = np.full(len(frame), -1, dtype=np.int8)
    # The unknown part may contain future values of any type. It is not read.
    observed = frame["delayed"].iloc[np.flatnonzero(known)]
    if observed.isna().any() or not observed.isin([0, 1]).all():
        raise ValueError("Known query outcomes must be complete binary labels")
    labels[known] = observed.to_numpy(dtype=np.int8)
    return labels


def profile_phase(frame_with_signals, known, common20, common4_by_seed, *, support_mapping=None):
    """Return fixed group/cohort distributions without fitting or alert changes.

    ``known``, ``common20`` and every seed mask must be boolean vectors aligned
    with the supplied frame. A Series additionally needs the same ordered index.
    Seed keys are exactly the five integer seeds. ``common20`` must equal the
    identity-wise intersection of their five common-four-model miss masks, and
    every such miss must be an already-known delayed query.
    """
    frame = frame_with_signals
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Require a DataFrame of query signals")
    missing = set(SIGNAL_FEATURES).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing fixed signal columns: {sorted(missing)}")
    if (not isinstance(common4_by_seed, Mapping) or set(common4_by_seed) != set(SEEDS)
            or any(isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer))
                   for seed in common4_by_seed)):
        raise ValueError("Require exactly the five fixed integer seed keys")
    known = _boolean(known, frame, "known")
    common20 = _boolean(common20, frame, "common20")
    by_seed = {seed: _boolean(common4_by_seed[seed], frame, f"common4 seed {seed}") for seed in SEEDS}
    labels = _known_labels(frame, known)
    positive, on_time = known & (labels == 1), known & (labels == 0)
    if not np.array_equal(common20, np.logical_and.reduce(list(by_seed.values()))):
        raise ValueError("Common20 identity mask must equal the five-seed intersection")
    if any(np.any(mask & ~positive) for mask in (common20, *by_seed.values())):
        raise ValueError("Common miss masks may contain only known delayed queries")

    cells, original = intersections.group_masks(frame)
    groups = {name: original[name] for name in ("ALL", "R", "A", "RA")}
    groups.update({"R_not_A": original["R"] & ~original["A"],
                   "A_not_R": original["A"] & ~original["R"], "NOT_A": ~original["A"],
                   "SP->SC": frame.state_route.fillna("unknown").eq("SP->SC").to_numpy()})
    groups.update({f"cell:{cell}": cells == cell for cell in intersections.CELLS})
    if not np.equal(np.sum([groups[f"cell:{cell}"] for cell in intersections.CELLS], axis=0), 1).all():
        raise AssertionError("Eight fixed R/P/A cells do not partition the full phase")
    signals = {name: _numeric(frame[name]) for name in SIGNAL_FEATURES}
    supports = _support_arrays(frame, SUPPORT_MAPPING if support_mapping is None else support_mapping)
    cohort_masks = {"all_known": known, "known_on_time": on_time, "known_delayed": positive,
                    "common20": common20, "other_delayed": positive & ~common20}
    result = {"rows": len(frame), "signal_features": list(SIGNAL_FEATURES),
              "support_bins": list(SUPPORT_BINS),
              "interpretation": "Fixed overlapping marginals; only eight R/P/A cells partition rows. Unknown query outcomes are excluded before label access. Distributions are descriptive, not model gains.",
              "groups": {}}
    for name, mask in groups.items():
        full, observed, delayed, punctual, missed = [int((mask & condition).sum()) for condition in
            (original["ALL"], known, positive, on_time, common20)]
        denominator = {"full_batch_rows": full, "known_rows": observed, "unknown_rows": full - observed,
                       "positive_rows": delayed, "known_on_time_rows": punctual,
                       "common20_rows": missed, "other_delayed_rows": delayed - missed,
                       "known_delay_rate": delayed / observed if observed else None,
                       "common20_fraction_of_delays": missed / delayed if delayed else None,
                       "common4_by_seed": {str(seed): int((mask & by_seed[seed]).sum()) for seed in SEEDS}}
        if observed + denominator["unknown_rows"] != full or delayed + punctual != observed:
            raise AssertionError("Known/unknown or delayed/on-time cohorts do not partition")
        row = {"denominators": denominator,
               "cohorts": {cohort: _profile(mask & selected, signals, supports)
                           for cohort, selected in cohort_masks.items()}}
        if name in FOCUS_GROUPS:
            row["common4_by_seed"] = {str(seed): _profile(mask & by_seed[seed], signals, supports)
                                      for seed in SEEDS}
        if row["cohorts"]["common20"]["rows"] + row["cohorts"]["other_delayed"]["rows"] != delayed:
            raise AssertionError("Common20 and other-delay identities do not partition delays")
        result["groups"][name] = row
    for field in ("full_batch_rows", "known_rows", "unknown_rows", "positive_rows",
                  "known_on_time_rows", "common20_rows", "other_delayed_rows"):
        if sum(result["groups"][f"cell:{cell}"]["denominators"][field] for cell in intersections.CELLS) != result["groups"]["ALL"]["denominators"][field]:
            raise AssertionError("Cell count totals do not reconcile with ALL")
    return result


def compare_correlations(frame, baseline_numeric):
    """Describe candidate redundancy on the supplied unlabeled pre-May cohort.

    Exact duplication requires equal finite values, equal missingness and at
    least one finite observation. Spearman uses pairwise finite rows, average
    ranks for ties, and null for fewer than two pairs or a constant variable.
    No labels, route masks, scores or alerts are accessed.
    """
    names = list(baseline_numeric)
    if not names or len(names) != len(set(names)):
        raise ValueError("Require a nonempty unique baseline numeric feature list")
    missing = set(names + CANDIDATE_FEATURES).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing correlation columns: {sorted(missing)}")
    baseline = {name: _numeric(frame[name]) for name in names}
    result = {"rows": len(frame), "baseline_numeric_features": names, "candidate_features": list(CANDIDATE_FEATURES),
              "interpretation": "Pairwise descriptive redundancy only; correlation is not incremental predictive value or an independent test.",
              "by_candidate": {}}
    for candidate in CANDIDATE_FEATURES:
        values = _numeric(frame[candidate])
        finite = np.isfinite(values)
        duplicates, correlations = [], []
        for position, (name, comparison) in enumerate(baseline.items()):
            other_finite = np.isfinite(comparison)
            paired = finite & other_finite
            count = int(paired.sum())
            if finite.any() and np.array_equal(finite, other_finite) and np.array_equal(values[finite], comparison[finite]):
                duplicates.append({"feature": name, "paired_count": count})
            coefficient = None
            if count >= 2:
                left = pd.Series(values[paired]).rank(method="average").to_numpy(dtype=float)
                right = pd.Series(comparison[paired]).rank(method="average").to_numpy(dtype=float)
                if np.ptp(left) > 0 and np.ptp(right) > 0:
                    coefficient = float(np.corrcoef(left, right)[0, 1])
                    correlations.append((position, {"feature": name, "spearman": coefficient,
                                                    "abs_spearman": abs(coefficient), "paired_count": count}))
        correlations.sort(key=lambda entry: (-entry[1]["abs_spearman"], entry[0]))
        result["by_candidate"][candidate] = {"finite_rows": int(finite.sum()),
                                            "missing_rows": int((~finite).sum()),
                                            "exact_duplicates": duplicates,
                                            "top_abs_spearman": [entry[1] for entry in correlations[:3]]}
    return result
