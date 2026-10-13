"""Historical score calibration and a hard cap for complete daily batches.

Calibration fits and policy selection must use separate historical cohorts.
This module does not make that split: callers are responsible for supplying
only labels known at the declared decision time. Daily budgets require the
complete batch, including orders whose labels are still unknown. They are a
retrospective batch policy, not an online per-order alert guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from scripts.delay_alert_policy import _numeric_vector


CALIBRATION_METHODS = ('raw', 'sigmoid', 'isotonic')
LOGIT_CLIP = 1e-6


@dataclass
class ScoreCalibrator:
    """Picklable fitted transformation; none of its fields contain order IDs."""

    method: str
    estimator: Any = None
    constant_probability: float | None = None
    fit_rows: int = 0
    fit_positive_rows: int = 0
    fit_notes: str = ''

    def to_report(self) -> dict:
        """Return JSON-safe fitted parameters and any monotonicity fallback."""
        report = {
            'method': self.method, 'fit_rows': self.fit_rows,
            'fit_positive_rows': self.fit_positive_rows,
            'fit_positive_rate': self.fit_positive_rows / self.fit_rows if self.fit_rows else None,
            'fit_notes': self.fit_notes,
            'constant_probability': self.constant_probability,
            'monotonicity_fallback_applied': self.constant_probability is not None,
        }
        if self.method == 'sigmoid' and self.estimator is not None:
            report['parameters'] = {
                'input_transform': 'logit(raw score)', 'logit_clip': LOGIT_CLIP,
                'C': 1e6, 'class_weight': None, 'solver': 'lbfgs', 'max_iter': 2000,
                'tol': 1e-10, 'slope': float(self.estimator.coef_[0, 0]),
                'intercept': float(self.estimator.intercept_[0]),
            }
        elif self.method == 'isotonic' and self.estimator is not None:
            report['parameters'] = {
                'increasing': True, 'out_of_bounds': 'clip',
                'knots': int(len(self.estimator.X_thresholds_)),
                'raw_score_min': float(self.estimator.X_thresholds_[0]),
                'raw_score_max': float(self.estimator.X_thresholds_[-1]),
                'probability_min': float(self.estimator.y_thresholds_[0]),
                'probability_max': float(self.estimator.y_thresholds_[-1]),
            }
        else:
            report['parameters'] = {}
        return report


def _probabilities(values, name='scores'):
    values = _numeric_vector(values, name)
    if ((values < 0) | (values > 1)).any():
        raise ValueError(f'{name} must be in [0, 1]')
    return values


def _labels(values, *, require_both=False):
    labels = _numeric_vector(values, 'y')
    if not np.isin(labels, [0, 1]).all():
        raise ValueError('y must contain only binary labels 0 and 1')
    if require_both and np.unique(labels).size != 2:
        raise ValueError('y must contain both binary classes 0 and 1')
    return labels


def _scalar(value, name, *, include_zero):
    try:
        array = np.asarray(value)
        if array.ndim != 0 or np.iscomplexobj(array) or isinstance(value, (bool, np.bool_)):
            raise ValueError
        result = float(array)
    except (TypeError, ValueError) as exc:
        interval = '[0, 1]' if include_zero else '(0, 1]'
        raise ValueError(f'{name} must be a finite scalar in {interval}') from exc
    lower_valid = result >= 0 if include_zero else result > 0
    if not np.isfinite(result) or not lower_valid or result > 1:
        interval = '[0, 1]' if include_zero else '(0, 1]'
        raise ValueError(f'{name} must be a finite scalar in {interval}')
    return result


def _logits(values):
    clipped = np.clip(values, LOGIT_CLIP, 1 - LOGIT_CLIP)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def fit_calibrator(y, scores, method: str) -> ScoreCalibrator:
    """Fit an unweighted monotone transform on calibration labels only.

    ``raw`` is the identity. ``sigmoid`` is logistic regression on the logit of
    the clipped original score (C=1e6, no class weights). A nonpositive fitted
    slope falls back to calibration prevalence, preventing rank inversion.
    ``isotonic`` is increasing isotonic regression with clipped extrapolation.
    Report held-out calibration metrics; fitted-cohort metrics are descriptive.
    """
    if method not in CALIBRATION_METHODS:
        raise ValueError(f'method must be one of {CALIBRATION_METHODS}')
    labels = _labels(y, require_both=True)
    values = _probabilities(scores)
    if len(labels) != len(values):
        raise ValueError('y and scores must have equal lengths')
    result = ScoreCalibrator(method=method, fit_rows=len(labels),
                             fit_positive_rows=int(labels.sum()))
    if method == 'raw':
        result.fit_notes = 'Identity transformation; labels validated but no parameters fitted.'
    elif method == 'sigmoid':
        estimator = LogisticRegression(C=1e6, solver='lbfgs', max_iter=2000,
                                       tol=1e-10, class_weight=None)
        estimator.fit(_logits(values), labels.astype(int))
        result.estimator = estimator
        if float(estimator.coef_[0, 0]) <= 0:
            result.constant_probability = float(labels.mean())
            result.fit_notes = ('Nonpositive fitted sigmoid slope; use calibration prevalence '
                                'as a constant to prevent rank inversion.')
        else:
            result.fit_notes = ('Unweighted sigmoid on logit(raw score), clip=1e-6, C=1e6; '
                                'positive fitted slope.')
    else:
        result.estimator = IsotonicRegression(increasing=True, out_of_bounds='clip')
        result.estimator.fit(values, labels)
        result.fit_notes = 'Unweighted increasing isotonic regression; extrapolation clipped.'
    return result


def transform_scores(calibrator: ScoreCalibrator, scores) -> np.ndarray:
    """Transform finite [0, 1] scores without inspecting outcome labels."""
    values = _probabilities(scores)
    if not isinstance(calibrator, ScoreCalibrator) or calibrator.method not in CALIBRATION_METHODS:
        raise ValueError('calibrator must be a fitted ScoreCalibrator')
    if calibrator.method == 'raw':
        result = values.copy()
    elif calibrator.constant_probability is not None:
        probability = _scalar(calibrator.constant_probability, 'constant_probability', include_zero=True)
        result = np.full(len(values), probability)
    elif calibrator.estimator is None:
        raise ValueError('calibrator is missing its fitted estimator')
    elif calibrator.method == 'sigmoid':
        if float(calibrator.estimator.coef_[0, 0]) <= 0:
            raise ValueError('sigmoid calibrator must have a positive fitted slope')
        result = calibrator.estimator.predict_proba(_logits(values))[:, 1]
    else:
        result = calibrator.estimator.predict(values)
    return _probabilities(result, 'calibrated scores')


def _batch_dates(frame, rows):
    if not isinstance(frame, pd.DataFrame) or not {'order_id', 'prediction_time'}.issubset(frame.columns):
        raise ValueError('frame must be a DataFrame with order_id and prediction_time')
    if len(frame) != rows:
        raise ValueError('frame and scores must have equal lengths')
    ids = frame['order_id'].to_numpy(dtype=object)
    if any(not isinstance(value, str) or not value.strip() for value in ids):
        raise ValueError('order_id must contain nonempty strings')
    if len(set(ids)) != len(ids):
        raise ValueError('order_id must be unique within the complete batch')
    stamps = []
    for value in frame['prediction_time']:
        try:
            if isinstance(value, (bool, int, float, np.number)):
                raise ValueError
            stamp = pd.Timestamp(value)
            if pd.isna(stamp) or stamp.tzinfo is not None:
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError('prediction_time must contain valid timezone-naive timestamps') from exc
        stamps.append(stamp.normalize())
    return ids, pd.DatetimeIndex(stamps)


def _budget_membership(frame, values, cap, raw_scores):
    ids, dates = _batch_dates(frame, len(values))
    raw = values if raw_scores is None else _probabilities(raw_scores, 'raw_scores')
    if len(raw) != len(values):
        raise ValueError('raw_scores and scores must have equal lengths')
    fraction = None if cap is None else _scalar(cap, 'cap', include_zero=True)
    counts = pd.Series(dates).value_counts().sort_index()
    decimal_cap = Decimal(str(fraction)) if fraction is not None else None
    capacities = {
        day: int((decimal_cap * int(size)).to_integral_value(rounding=ROUND_FLOOR))
        if decimal_cap is not None else int(size)
        for day, size in counts.items()
    }
    membership = np.ones(len(values), dtype=bool)
    if fraction is not None:
        ranked = pd.DataFrame({'day': dates, 'score': values, 'raw': raw,
                               'id': ids, 'position': np.arange(len(values))})
        ranked = ranked.sort_values(['day', 'score', 'raw', 'id'],
                                    ascending=[True, False, False, True], kind='stable')
        ranks = ranked.groupby('day', sort=False).cumcount().to_numpy()
        limits = ranked['day'].map(capacities).to_numpy()
        membership[:] = False
        membership[ranked.loc[ranks < limits, 'position'].to_numpy()] = True
    daily = [{'day': day.date().isoformat(), 'batch_rows': int(size),
              'capacity_rows': capacities[day]} for day, size in counts.items()]
    return membership, fraction, daily


def apply_alert_policy(frame, scores, threshold, cap=None, raw_scores=None) -> np.ndarray:
    """Threshold scores within the deterministic top-K of each complete day.

    K = floor(cap * full daily batch size), including unknown-label orders.
    Ranking uses calibrated score descending, raw score descending, then
    order_id ascending. Raw-score tie breaking preserves isotonic plateaus.
    The returned boolean vector uses input row order, independent of its index.
    A missing cap leaves the ordinary ``score >= threshold`` rule unchanged.
    """
    values = _probabilities(scores)
    selected_threshold = _scalar(threshold, 'threshold', include_zero=True)
    membership, _, _ = _budget_membership(frame, values, cap, raw_scores)
    return membership & (values >= selected_threshold)


def _known_labels(y, rows, known_mask):
    source = np.asarray(y, dtype=object)
    if source.ndim != 1 or len(source) != rows:
        raise ValueError('y and scores must be one-dimensional with equal lengths')
    if known_mask is None:
        known = np.ones(rows, dtype=bool)
    else:
        known = np.asarray(known_mask)
        if known.ndim != 1 or len(known) != rows or known.dtype.kind != 'b':
            raise ValueError('known_mask must be a boolean vector matching scores')
    labels = np.zeros(rows, dtype=float)
    labels[known] = _labels(source[known], require_both=True)
    return labels, known


def choose_budget_threshold(frame, y, scores, cap=None, min_recall=.30,
                            raw_scores=None, known_mask=None) -> tuple[float, dict]:
    """Minimize full-batch alerts subject to recall on known validation labels.

    Supply every order in the daily cohort, including immature-label orders,
    and mark labels known at decision time with ``known_mask``. Unknown labels
    are never parsed or used, but their scores still compete for daily capacity.
    This also keeps budget denominators independent of label availability.

    Threshold ties are indivisible after deterministic budget ranking. If the
    recall floor is infeasible, threshold zero gives the maximum recall under
    the cap, and ``feasible`` is false. No future recall guarantee is implied.
    """
    values = _probabilities(scores)
    target = _scalar(min_recall, 'min_recall', include_zero=False)
    labels, known = _known_labels(y, len(values), known_mask)
    membership, fraction, daily = _budget_membership(frame, values, cap, raw_scores)
    positives = int(labels[known].sum())
    max_tp = int(((labels == 1) & known & membership).sum())
    max_recall = max_tp / positives
    feasible = max_recall >= target
    candidates = values[membership]
    if feasible:
        positions = np.flatnonzero(membership)
        order = np.argsort(-values[positions], kind='stable')
        positions = positions[order]
        ordered_values = values[positions]
        group_ends = np.r_[ordered_values[:-1] != ordered_values[1:], True]
        cumulative_tp = np.cumsum((labels[positions] == 1) & known[positions])
        first = int(np.flatnonzero(cumulative_tp[group_ends] / positives >= target)[0])
        threshold = float(ordered_values[group_ends][first])
    else:
        threshold = 0.0
    predicted = membership & (values >= threshold)
    known_predicted = predicted & known
    tp = int((known_predicted & (labels == 1)).sum())
    fp = int((known_predicted & (labels == 0)).sum())
    fn = positives - tp
    tn = int(known.sum()) - positives - fp
    alerts = int(predicted.sum())
    known_alerts = int(known_predicted.sum())
    policy = {
        'data': 'historical validation; only known_mask=True labels enter metrics or selection',
        'objective': 'minimize full-batch alerts subject to known-label recall >= min_recall and daily cap',
        'fallback': 'threshold zero maximizes recall within the cap when recall floor is infeasible',
        'prediction_rule': 'score >= threshold AND deterministic daily top-K membership',
        'selected_threshold': threshold, 'min_recall': target, 'feasible': feasible,
        'achieved_recall': tp / positives, 'max_achievable_recall': max_recall,
        'rows': len(values), 'full_batch_rows': len(values), 'known_rows': int(known.sum()),
        'known_positive_rows': positives, 'unknown_rows': int((~known).sum()),
        'predicted_positive_rows': alerts, 'known_predicted_positive_rows': known_alerts,
        'unknown_predicted_positive_rows': alerts - known_alerts,
        'true_positive_rows': tp, 'false_positive_rows': fp,
        'false_negative_rows': fn, 'true_negative_rows': tn,
        'confusion_matrix': [[tn, fp], [fn, tp]],
        'alert_rate': alerts / len(values), 'known_alert_rate': known_alerts / int(known.sum()),
        'precision': tp / known_alerts if known_alerts else 0.0,
        'cap': fraction, 'daily_capacity_rows': int(membership.sum()), 'daily_capacity': daily,
        'candidate_thresholds': int(np.unique(candidates).size),
        'tie_policy': 'rank calibrated score DESC, raw score DESC, order_id ASC; threshold score ties indivisible',
        'capacity_rule': 'floor(cap * full daily cohort rows); unknown-label orders retain capacity and compete',
        'batch_semantics': ('Requires complete calendar-day batches in the eligible completed cohort; '
                            'not an online per-order or all-approved-order guarantee.'),
        'evaluation_recall_guarantee': False,
    }
    return threshold, policy


def probability_metrics(y, probabilities) -> dict:
    """Brier, log loss and ten fixed-width reliability bins, allowing one class.

    Bins are [lower, upper), with the final bin including probability one.
    Empty bins remain present with null means and gaps. ECE is the weighted
    absolute probability-versus-frequency gap; report it with bin counts.
    """
    labels = _labels(y)
    values = _probabilities(probabilities, 'probabilities')
    if len(labels) != len(values):
        raise ValueError('y and probabilities must have equal lengths')
    epsilon = np.finfo(float).eps
    clipped = np.clip(values, epsilon, 1 - epsilon)
    loss = -np.mean(labels * np.log(clipped) + (1 - labels) * np.log1p(-clipped))
    assignments = np.minimum((values * 10).astype(int), 9)
    bins, ece = [], 0.0
    for index in range(10):
        mask = assignments == index
        rows = int(mask.sum())
        mean_probability = float(values[mask].mean()) if rows else None
        observed_rate = float(labels[mask].mean()) if rows else None
        gap = abs(mean_probability - observed_rate) if rows else None
        if rows:
            ece += rows / len(values) * gap
        bins.append({'bin': index, 'lower_bound': index / 10, 'upper_bound': (index + 1) / 10,
                     'upper_inclusive': index == 9, 'rows': rows,
                     'mean_probability': mean_probability,
                     'observed_positive_rate': observed_rate, 'absolute_gap': gap})
    return {'rows': len(values), 'positive_rows': int(labels.sum()),
            'positive_rate': float(labels.mean()),
            'brier_score': float(np.mean((values - labels) ** 2)), 'log_loss': float(loss),
            'log_loss_clip_epsilon': float(epsilon),
            'expected_calibration_error': float(ece), 'reliability_bins': bins}
