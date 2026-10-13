"""Aggregate missed-delay diagnoses with a fixed complete-day 10% budget.

The caller supplies the outcome-availability mask. Unknown outcomes still
compete for the daily budget, but none of their labels enter a diagnostic.
Overlap comparisons describe existing models; their union is not a policy.
"""
from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations

import numpy as np
import pandas as pd

from scripts.delay_calibration_policy import apply_alert_policy
from scripts.diagnose_budget_misses import (
    GROUPINGS, MIN_GROUP_POSITIVES, MIN_GROUP_ROWS, PROMISE_BINS, RANK_BINS,
    _counts, _timestamps, analyze_segments, daily_rank_bins,
)


HISTORY_SUPPORT_BINS = ('0', '1-19', '20-99', '100+', 'unknown')
PROMISE_MARGIN_BINS = ('<=0', '(0,7]', '(7,14]', '14+', 'unknown')
SUPPORT_GROUPINGS = {
    'route_history_support': 'route_completed_90d_bin',
    'seller_history_support': 'seller_completed_90d_bin',
    'promise_margin': 'route_promise_margin_p90_days_bin',
}
REQUIRED_COLUMNS = {
    'order_id', 'prediction_time', 'label_available_time', 'delayed',
    'state_route', 'customer_state', 'estimated_delivery_days',
    'route_completed_90d', 'seller_completed_90d',
    'route_promise_margin_p90_days',
}


def _diagnostic_columns(known):
    """Create fixed, label-independent support intervals on known rows."""
    data = known.copy().reset_index(drop=True)
    for name in ('state_route', 'customer_state'):
        data[name] = data[name].astype(object).where(data[name].notna(), 'unknown')
    promise = pd.to_numeric(data.estimated_delivery_days, errors='raise')
    if not np.isfinite(promise).all() or (promise < 0).any():
        raise ValueError('Promise calendar days must be finite and nonnegative')
    data['promise_bin'] = pd.cut(promise, [-np.inf, 7, 14, 21, 30, np.inf],
                               labels=PROMISE_BINS, right=True).astype(object)
    for name in ('route_completed_90d', 'seller_completed_90d'):
        values = pd.to_numeric(data[name], errors='raise')
        finite = values.notna()
        if (not np.isfinite(values[finite]).all() or (values[finite] < 0).any()
                or not values[finite].eq(np.floor(values[finite])).all()):
            raise ValueError('Completed-history support must be nonnegative integer counts or missing')
        data[name + '_bin'] = np.select(
            [values.eq(0), values.between(1, 19), values.between(20, 99), values.ge(100)],
            HISTORY_SUPPORT_BINS[:-1], default='unknown')
    margin = pd.to_numeric(data.route_promise_margin_p90_days, errors='raise')
    if not np.isfinite(margin[margin.notna()]).all():
        raise ValueError('Promise margin must be finite or missing')
    data['route_promise_margin_p90_days_bin'] = np.select(
        [margin.le(0), margin.gt(0) & margin.le(7), margin.gt(7) & margin.le(14), margin.gt(14)],
        PROMISE_MARGIN_BINS[:-1], default='unknown')
    return data


def _known_diagnostics(data, predictions, rank_bins):
    # analyze_segments intentionally gets no scores: it must not re-rank the
    # known subset. Full-batch ranks are computed by analyze_month first.
    if len(data):
        report = analyze_segments(data, predictions)
    else:
        report = {
            'minimum_group_rows': MIN_GROUP_ROWS,
            'minimum_group_positive_rows': MIN_GROUP_POSITIVES,
            'aggregate': {'overall': _counts([], [], all_false_negatives=0),
                          'groups': {name: [] for name in GROUPINGS}},
            'by_month': {},
        }
    fn = report['aggregate']['overall']['false_negatives']
    for name, column in SUPPORT_GROUPINGS.items():
        rows = []
        for key, part in data.assign(_chosen=predictions).groupby(column, sort=True, dropna=False):
            row = {column: str(key)}
            row.update(_counts(part.delayed, part._chosen,
                               all_false_negatives=fn, scope_false_negatives=fn))
            rows.append(row)
        rows.sort(key=lambda row: (-row['false_negatives'], -row['positive_rows'], str(row)))
        report['aggregate']['groups'][name] = rows
    rank_rows = []
    labels = data.delayed.to_numpy()
    for name in RANK_BINS:
        positions = rank_bins == name
        row = {'daily_rank_bin': name}
        row.update(_counts(labels[positions], predictions[positions],
                           all_false_negatives=fn, scope_false_negatives=fn))
        rank_rows.append(row)
    report['aggregate']['daily_rank_bins'] = rank_rows
    # The API accepts exactly one month, so these aggregate additions also
    # describe its one month without any change of denominator.
    for scope in report['by_month'].values():
        for name in SUPPORT_GROUPINGS:
            scope['groups'][name] = report['aggregate']['groups'][name]
        scope['daily_rank_bins'] = rank_rows
    report['rank_notes'] = ('Ranks computed on the complete closed daily batch before filtering '
                            'to known outcomes; unknown outcomes compete for capacity.')
    report['support_bin_notes'] = {
        'history': 'Nonnegative completed-order counts: 0, 1-19, 20-99, 100+, missing.',
        'promise_margin': '<=0, (0,7], (7,14], >14 calendar days, missing.',
        'minimum_sample_met': 'At least 30 known rows and 5 known delayed rows.',
    }
    return report


def _paired_counts(labels, a, b):
    positive, negative = labels == 1, labels == 0
    recovered = int((positive & ~a & b).sum())
    lost = int((positive & a & ~b).sum())
    added = int((negative & ~a & b).sum())
    removed = int((negative & a & ~b).sum())
    return {
        'rows': len(labels), 'positive_rows': int(positive.sum()),
        'recovered_delays': recovered, 'lost_delays': lost,
        'added_on_time_alerts': added, 'removed_on_time_alerts': removed,
        'net_TP': recovered - lost, 'net_FP': added - removed,
        'minimum_sample_met': len(labels) >= MIN_GROUP_ROWS and int(positive.sum()) >= MIN_GROUP_POSITIVES,
    }


def _pairwise(data, predictions, full_predictions, known):
    result = []
    labels = data.delayed.to_numpy()
    for model_a, model_b in combinations(predictions, 2):
        a, b = predictions[model_a], predictions[model_b]
        groups = {}
        for name, column in (('state_route', 'state_route'), ('promise_days', 'promise_bin')):
            rows = []
            for key, positions in data.groupby(column, sort=True, dropna=False).indices.items():
                row = {column: str(key)}
                row.update(_paired_counts(labels[positions], a[positions], b[positions]))
                rows.append(row)
            rows.sort(key=lambda row: (-row['recovered_delays'], -row['lost_delays'], str(row)))
            groups[name] = rows
        unknown_a, unknown_b = full_predictions[model_a][~known], full_predictions[model_b][~known]
        added = int((~unknown_a & unknown_b).sum())
        removed = int((unknown_a & ~unknown_b).sum())
        result.append({
            'model_a': model_a, 'model_b': model_b, 'direction': 'model_a -> model_b',
            'known_outcome': {'overall': _paired_counts(labels, a, b), 'groups': groups},
            'unknown_outcome_alerts': {'rows': int((~known).sum()),
                                       'added_alerts': added, 'removed_alerts': removed,
                                       'net_alerts': added - removed},
        })
    return result


def _delayed_overlap(data, predictions):
    delayed = data.delayed.to_numpy() == 1
    names = list(predictions)
    matrix = np.column_stack([predictions[name][delayed] for name in names])
    patterns, counts = np.unique(matrix, axis=0, return_counts=True)
    rows = [{'alerted_models': [name for name, selected in zip(names, pattern, strict=True) if selected],
             'delayed_rows': int(count)} for pattern, count in zip(patterns, counts, strict=True)]
    pairs = []
    for model_a, model_b in combinations(names, 2):
        a, b = predictions[model_a][delayed], predictions[model_b][delayed]
        pairs.append({'model_a': model_a, 'model_b': model_b,
                      'both_missed': int((~a & ~b).sum()), 'both_caught': int((a & b).sum()),
                      'only_a_caught': int((a & ~b).sum()), 'only_b_caught': int((~a & b).sum())})
    return {'model_order': names, 'delayed_rows': int(delayed.sum()),
            'all_models_miss': int((~matrix.any(axis=1)).sum()),
            'any_model_caught': int(matrix.any(axis=1).sum()),
            'all_models_caught': int(matrix.all(axis=1).sum()),
            'alert_pattern_counts': rows, 'pairwise': pairs,
            'interpretation': 'Descriptive overlap only; no union policy is selected or evaluated.'}


def analyze_month(frame, scores_by_candidate, known_mask):
    """Diagnose existing model scores using complete-day positional inputs.

    ``frame`` must contain one complete calendar month. The caller verifies
    completeness and determines which outcomes were known at its cutoff.
    Scores and the boolean mask align by row position, regardless of index.
    Outcomes outside the mask are never inspected, even for validation.
    """
    if (not isinstance(frame, pd.DataFrame) or frame.empty
            or not REQUIRED_COLUMNS.issubset(frame.columns)):
        raise ValueError(f'Require a nonempty monthly frame with {sorted(REQUIRED_COLUMNS)}')
    known = np.asarray(known_mask)
    if known.ndim != 1 or len(known) != len(frame) or known.dtype != np.dtype(bool):
        raise ValueError('known_mask must be an aligned one-dimensional boolean vector')
    if not isinstance(scores_by_candidate, Mapping) or len(scores_by_candidate) < 2:
        raise ValueError('Require scores for at least two candidates')
    if any(not isinstance(name, str) or not name.strip() for name in scores_by_candidate):
        raise ValueError('Candidate names must be nonempty strings')
    times = _timestamps(frame.prediction_time)
    if times.dt.to_period('M').nunique() != 1:
        raise ValueError('Expected exactly one calendar month')
    labels = frame.delayed.to_numpy()[known]
    if not np.isin(labels, [0, 1]).all():
        raise ValueError('Known outcomes must be binary labels')
    data = _diagnostic_columns(frame.iloc[np.flatnonzero(known)])
    full_predictions, predictions, models = {}, {}, {}
    for name, scores in scores_by_candidate.items():
        chosen = apply_alert_policy(frame, scores, threshold=0, cap=.1)
        bins = daily_rank_bins(frame, scores)
        if not np.array_equal(chosen, bins == '<=10%'):
            raise AssertionError('Diagnostic rank bins differ from daily alert policy')
        full_predictions[name] = chosen
        predictions[name] = chosen[known]
        models[name] = {
            'known_outcome_diagnostics': _known_diagnostics(data, chosen[known], bins[known]),
            'unknown_outcome_alerts': {'rows': int((~known).sum()), 'alerts': int(chosen[~known].sum())},
        }
    counts = times.dt.normalize().value_counts()
    return {
        'complete_batch': {'rows': len(frame), 'known_rows': int(known.sum()),
                           'unknown_rows': int((~known).sum()),
                           'capacity': sum(int(size) // 10 for size in counts),
                           'total_days': len(counts)},
        'models': models,
        'pairwise_comparisons': _pairwise(data, predictions, full_predictions, known),
        'delayed_overlap': _delayed_overlap(data, predictions),
    }
