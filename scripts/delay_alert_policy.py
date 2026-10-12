"""Choose a validation-only alert threshold subject to a minimum recall target."""

from __future__ import annotations

import numpy as np


def _numeric_vector(values, name: str) -> np.ndarray:
    try:
        array = np.asarray(values)
        if array.ndim != 1 or array.size == 0 or np.iscomplexobj(array):
            raise ValueError(f"{name} must be a nonempty one-dimensional numeric vector")
        array = array.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a nonempty one-dimensional numeric vector") from exc
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def choose_recall_threshold(y, scores, min_recall: float = 0.30) -> tuple[float, dict]:
    """Minimize validation alerts while achieving at least ``min_recall``.

    Only validation labels and validation scores belong in this function.
    Predictions use ``score >= threshold``. Equal-score observations are an
    indivisible group, so the requested recall can be exceeded when scores tie.
    The selected threshold is the highest observed score satisfying the target;
    no evaluation labels or scores are accepted or consulted.

    Validation recall does not guarantee recall on evaluation or future orders.
    Scores must be finite positive-class scores in [0, 1], and labels must contain
    both binary classes. Scores need not be calibrated probabilities.
    """
    labels = _numeric_vector(y, "y")
    values = _numeric_vector(scores, "scores")
    if len(labels) != len(values):
        raise ValueError("y and scores must have equal lengths")
    if not np.isin(labels, [0.0, 1.0]).all() or np.unique(labels).size != 2:
        raise ValueError("y must contain both binary classes 0 and 1")
    if ((values < 0.0) | (values > 1.0)).any():
        raise ValueError("scores must be in [0, 1]")
    try:
        recall_array = np.asarray(min_recall)
        if recall_array.ndim != 0 or np.iscomplexobj(recall_array):
            raise ValueError("min_recall must be a finite scalar in (0, 1]")
        target_recall = float(recall_array)
    except (TypeError, ValueError) as exc:
        raise ValueError("min_recall must be a finite scalar in (0, 1]") from exc
    if not np.isfinite(target_recall) or not 0.0 < target_recall <= 1.0:
        raise ValueError("min_recall must be a finite scalar in (0, 1]")

    # Work at the end of each score group. Evaluating positions within a tie
    # would invent an alert set that the threshold rule cannot reproduce.
    order = np.argsort(-values, kind="stable")
    ordered_scores = values[order]
    group_ends = np.r_[ordered_scores[:-1] != ordered_scores[1:], True]
    cumulative_tp = np.cumsum(labels[order])
    positive_rows = int(labels.sum())
    group_recall = cumulative_tp[group_ends] / positive_rows
    first_feasible = int(np.flatnonzero(group_recall >= target_recall)[0])
    threshold = float(ordered_scores[group_ends][first_feasible])

    alerted = values >= threshold
    true_positives = int(np.sum(alerted & (labels == 1)))
    false_positives = int(np.sum(alerted & (labels == 0)))
    alert_rows = int(alerted.sum())
    policy = {
        "data": "validation only",
        "objective": "minimize validation alert count subject to recall >= min_recall",
        "prediction_rule": "delay_score >= threshold",
        "selected_threshold": threshold,
        "min_recall": target_recall,
        "achieved_recall": true_positives / positive_rows,
        "predicted_positive_rows": alert_rows,
        "true_positive_rows": true_positives,
        "false_positive_rows": false_positives,
        "alert_rate": alert_rows / len(labels),
        "precision": true_positives / alert_rows,
        "candidate_thresholds": int(group_ends.sum()),
        "tie_policy": "highest feasible observed threshold; all equal scores receive the same prediction",
        "evaluation_recall_guarantee": False,
        "evaluation_note": "Validation recall does not guarantee recall on evaluation or future orders",
    }
    return threshold, policy
