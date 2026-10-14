"""Describe existing model alert exchanges without fitting or selecting models.

Every eligible order competes in its complete closed daily batch before the
caller-supplied outcome-availability mask is used. Route allocation is an
accounting of daily alert counts, not a pairing of individual orders or a
claim that any feature caused an alert to move.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

import numpy as np
import pandas as pd

from scripts.delay_calibration_policy import apply_alert_policy
from scripts.diagnose_budget_misses import (
    MIN_GROUP_POSITIVES, MIN_GROUP_ROWS, RANK_BINS, _timestamps,
    daily_rank_bins,
)


REQUIRED_COLUMNS = {'order_id', 'prediction_time', 'state_route', 'delayed'}
COUNT_FIELDS = (
    'full_batch_rows', 'known_rows', 'unknown_rows', 'positive_rows',
    'old_alerts', 'new_alerts', 'old_known_alerts', 'new_known_alerts',
    'old_unknown_alerts', 'new_unknown_alerts', 'stable_alerts',
    'dropped_alerts', 'added_alerts', 'old_true_positives',
    'new_true_positives', 'old_false_positives', 'new_false_positives',
    'old_false_negatives', 'new_false_negatives', 'old_true_negatives',
    'new_true_negatives', 'recovered_delays', 'lost_delays',
    'added_on_time_alerts', 'removed_on_time_alerts',
    'unknown_added_alerts', 'unknown_removed_alerts', 'net_TP', 'net_FP',
    'net_unknown_alerts', 'net_alerts',
)
ALLOCATION_FIELDS = (
    'within_route_exchanges', 'cross_route_outgoing_slots',
    'cross_route_incoming_slots',
)


def _row_counts(positions, known, labels, old, new):
    known, labels, old, new = (value[positions] for value in (known, labels, old, new))
    positive, negative, unknown = known & (labels == 1), known & (labels == 0), ~known
    dropped, added = old & ~new, ~old & new
    old_tp, new_tp = int((old & positive).sum()), int((new & positive).sum())
    old_fp, new_fp = int((old & negative).sum()), int((new & negative).sum())
    positives, rows = int(positive.sum()), len(positions)
    old_known, new_known = int((old & known).sum()), int((new & known).sum())
    old_unknown, new_unknown = int((old & unknown).sum()), int((new & unknown).sum())
    result = {
        'full_batch_rows': rows, 'known_rows': int(known.sum()),
        'unknown_rows': int(unknown.sum()), 'positive_rows': positives,
        'old_alerts': int(old.sum()), 'new_alerts': int(new.sum()),
        'old_known_alerts': old_known, 'new_known_alerts': new_known,
        'old_unknown_alerts': old_unknown, 'new_unknown_alerts': new_unknown,
        'stable_alerts': int((old & new).sum()),
        'dropped_alerts': int(dropped.sum()), 'added_alerts': int(added.sum()),
        'old_true_positives': old_tp, 'new_true_positives': new_tp,
        'old_false_positives': old_fp, 'new_false_positives': new_fp,
        'old_false_negatives': positives - old_tp,
        'new_false_negatives': positives - new_tp,
        'old_true_negatives': int(negative.sum()) - old_fp,
        'new_true_negatives': int(negative.sum()) - new_fp,
        'recovered_delays': int((added & positive).sum()),
        'lost_delays': int((dropped & positive).sum()),
        'added_on_time_alerts': int((added & negative).sum()),
        'removed_on_time_alerts': int((dropped & negative).sum()),
        'unknown_added_alerts': int((added & unknown).sum()),
        'unknown_removed_alerts': int((dropped & unknown).sum()),
        'net_TP': new_tp - old_tp, 'net_FP': new_fp - old_fp,
        'net_unknown_alerts': new_unknown - old_unknown,
        'net_alerts': int(new.sum()) - int(old.sum()),
        'old_recall': old_tp / positives if positives else None,
        'new_recall': new_tp / positives if positives else None,
        'old_precision': old_tp / old_known if old_known else None,
        'new_precision': new_tp / new_known if new_known else None,
        'minimum_sample_met': int(known.sum()) >= MIN_GROUP_ROWS and positives >= MIN_GROUP_POSITIVES,
    }
    if (result['net_TP'] != result['recovered_delays'] - result['lost_delays']
            or result['net_FP'] != result['added_on_time_alerts'] - result['removed_on_time_alerts']
            or result['net_unknown_alerts'] != result['unknown_added_alerts'] - result['unknown_removed_alerts']
            or result['added_alerts'] != result['recovered_delays'] + result['added_on_time_alerts'] + result['unknown_added_alerts']
            or result['dropped_alerts'] != result['lost_delays'] + result['removed_on_time_alerts'] + result['unknown_removed_alerts']
            or result['net_alerts'] != result['net_TP'] + result['net_FP'] + result['net_unknown_alerts']
            or result['old_alerts'] != result['stable_alerts'] + result['dropped_alerts']
            or result['new_alerts'] != result['stable_alerts'] + result['added_alerts']):
        raise AssertionError('Alert and known/unknown outcome exchanges do not reconcile')
    return result


def _allocation(counts):
    dropped, added = counts['dropped_alerts'], counts['added_alerts']
    return {
        'within_route_exchanges': min(dropped, added),
        'cross_route_outgoing_slots': max(dropped - added, 0),
        'cross_route_incoming_slots': max(added - dropped, 0),
    }


def _rank_movements(known, labels, old, new, old_bins, new_bins):
    positive, negative, unknown = known & (labels == 1), known & (labels == 0), ~known
    dropped, added, stable, neither = old & ~new, ~old & new, old & new, ~old & ~new
    cohorts = (
        ('recovered_delays', positive & added), ('lost_delays', positive & dropped),
        ('stable_caught_delays', positive & stable), ('both_missed_delays', positive & neither),
        ('added_on_time_alerts', negative & added), ('removed_on_time_alerts', negative & dropped),
        ('stable_on_time_alerts', negative & stable), ('both_unalerted_on_time', negative & neither),
        ('unknown_added_alerts', unknown & added), ('unknown_removed_alerts', unknown & dropped),
        ('stable_unknown_alerts', unknown & stable), ('both_unalerted_unknown', unknown & neither),
    )
    rows = []
    for name, selected in cohorts:
        transitions = [
            {'old_rank_bin': before, 'new_rank_bin': after,
             'rows': int((selected & (old_bins == before) & (new_bins == after)).sum())}
            for before in RANK_BINS for after in RANK_BINS
        ]
        row = {
            'cohort': name, 'rows': int(selected.sum()),
            'old_rank_bins': {name: int((selected & (old_bins == name)).sum()) for name in RANK_BINS},
            'new_rank_bins': {name: int((selected & (new_bins == name)).sum()) for name in RANK_BINS},
            'rank_bin_transitions': transitions,
        }
        if (sum(item['rows'] for item in transitions) != row['rows']
                or sum(row['old_rank_bins'].values()) != row['rows']
                or sum(row['new_rank_bins'].values()) != row['rows']):
            raise AssertionError('Rank movement bins do not partition the cohort')
        rows.append(row)
    if sum(row['rows'] for row in rows) != len(known):
        raise AssertionError('Rank cohorts do not partition the complete batch')
    return {
        'bins': list(RANK_BINS), 'cohorts': rows,
        'rank_rule': 'One-based rank divided by complete daily batch size; score DESC, order_id ASC.',
        'notes': 'Full-batch ranks are computed before the known-outcome mask. Bins stay fixed at 10/20/50% even if cap differs from 10%.',
    }


def _assert_partition(rows, expected):
    for field in COUNT_FIELDS:
        if sum(row[field] for row in rows) != expected[field]:
            raise AssertionError(f'Partition does not reconcile field {field}')


def analyze_route_exchanges(frame, old_scores, new_scores, known_mask, cap=.1):
    """Aggregate positional before/after predictions of two existing models.

    The caller verifies complete scoring cohorts and supplies the historical
    outcome-availability mask. Unknown labels are never validated or counted
    as delayed/on-time outcomes. No private order IDs or individual scores are
    returned. All routes and dates are retained, including zero-change groups.

    Daily route changes split into within-route order replacement and residual
    cross-route slot counts. A residual incoming slot is not paired with any
    particular donor route, order, or outcome. Monthly gross outgoing/incoming
    totals sum daily movements; they are not the net monthly route difference.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty or not REQUIRED_COLUMNS.issubset(frame.columns):
        raise ValueError(f'Require a nonempty frame with {sorted(REQUIRED_COLUMNS)}')
    known = np.asarray(known_mask)
    if known.ndim != 1 or len(known) != len(frame) or known.dtype != np.dtype(bool):
        raise ValueError('known_mask must be an aligned one-dimensional boolean vector')
    source_labels = frame.delayed.to_numpy(dtype=object)[known]
    if not np.isin(source_labels, [0, 1]).all():
        raise ValueError('Known outcomes must be binary labels')
    labels = np.full(len(frame), -1, dtype=int)
    labels[known] = source_labels.astype(int)
    # The shared policy validates IDs, dates, cap, score values and alignment.
    old = apply_alert_policy(frame, old_scores, threshold=0, cap=cap)
    new = apply_alert_policy(frame, new_scores, threshold=0, cap=cap)
    if cap is None:
        raise ValueError('A finite daily cap is required for route allocation accounting')
    old_bins, new_bins = daily_rank_bins(frame, old_scores), daily_rank_bins(frame, new_scores)
    if float(cap) == .1 and (not np.array_equal(old, old_bins == '<=10%')
                            or not np.array_equal(new, new_bins == '<=10%')):
        raise AssertionError('Full-batch ranks do not match the shared 10% alert policy')
    times = _timestamps(frame.prediction_time)
    routes = frame.state_route.to_numpy(dtype=object).copy()
    for position, value in enumerate(routes):
        if pd.isna(value):
            routes[position] = 'unknown'
        elif not isinstance(value, str) or not value.strip():
            raise ValueError('state_route must contain nonempty strings or missing values')
    data = pd.DataFrame({'day': times.dt.strftime('%Y-%m-%d'),
                         'state_route': routes, 'position': np.arange(len(frame))})
    summary = _row_counts(np.arange(len(frame)), known, labels, old, new)
    route_days = []
    for (day, route), part in data.groupby(['day', 'state_route'], sort=True):
        row = {'day': day, 'state_route': route}
        row.update(_row_counts(part.position.to_numpy(), known, labels, old, new))
        row.update(_allocation(row))
        route_days.append(row)
    daily_lookup = {}
    route_lookup = {}
    for row in route_days:
        daily_lookup.setdefault(row['day'], []).append(row)
        route_lookup.setdefault(row['state_route'], []).append(row)
    days = []
    decimal_cap = Decimal(str(float(cap)))
    for day, part in data.groupby('day', sort=True):
        row = {'day': day}
        row.update(_row_counts(part.position.to_numpy(), known, labels, old, new))
        row['capacity'] = int((decimal_cap * len(part)).to_integral_value(rounding=ROUND_FLOOR))
        allocated = daily_lookup[day]
        row['within_route_exchanges'] = sum(item['within_route_exchanges'] for item in allocated)
        outgoing = sum(item['cross_route_outgoing_slots'] for item in allocated)
        incoming = sum(item['cross_route_incoming_slots'] for item in allocated)
        row['cross_route_slots'] = outgoing
        if (outgoing != incoming or row['old_alerts'] != row['capacity']
                or row['new_alerts'] != row['capacity']
                or row['dropped_alerts'] != row['added_alerts']
                or row['dropped_alerts'] != row['within_route_exchanges'] + outgoing):
            raise AssertionError('Complete-day route exchanges do not conserve capacity')
        _assert_partition(allocated, row)
        days.append(row)
    route_rows = []
    for route, part in data.groupby('state_route', sort=True):
        row = {'state_route': route}
        row.update(_row_counts(part.position.to_numpy(), known, labels, old, new))
        for field in ALLOCATION_FIELDS:
            row[field] = sum(item[field] for item in route_lookup[route])
        if (row['net_alerts'] != row['cross_route_incoming_slots'] - row['cross_route_outgoing_slots']
                or row['dropped_alerts'] != row['within_route_exchanges'] + row['cross_route_outgoing_slots']
                or row['added_alerts'] != row['within_route_exchanges'] + row['cross_route_incoming_slots']):
            raise AssertionError('Monthly route changes do not reconcile daily gross allocation')
        _assert_partition(route_lookup[route], row)
        route_rows.append(row)
    for rows in (route_rows, days, route_days):
        _assert_partition(rows, summary)
    allocation = {
        'within_route_exchanges': sum(row['within_route_exchanges'] for row in days),
        'cross_route_slots': sum(row['cross_route_slots'] for row in days),
        'changed_days': sum(row['dropped_alerts'] > 0 for row in days),
        'total_days': len(days), 'route_days': len(route_days), 'routes': len(route_rows),
        'capacity': sum(row['capacity'] for row in days),
        'monthly_net_recipient_slots': sum(max(row['net_alerts'], 0) for row in route_rows),
        'monthly_net_donor_slots': sum(max(-row['net_alerts'], 0) for row in route_rows),
    }
    if (summary['old_alerts'] != allocation['capacity']
            or summary['new_alerts'] != allocation['capacity']
            or summary['dropped_alerts'] != allocation['within_route_exchanges'] + allocation['cross_route_slots']
            or sum(row['cross_route_outgoing_slots'] for row in route_rows) != allocation['cross_route_slots']
            or sum(row['cross_route_incoming_slots'] for row in route_rows) != allocation['cross_route_slots']
            or allocation['monthly_net_recipient_slots'] != allocation['monthly_net_donor_slots']):
        raise AssertionError('Monthly capacity or allocation totals do not reconcile')
    return {
        'policy': {
            'daily_cap': float(cap), 'threshold': 0.0,
            'ranking': 'score DESC, raw score DESC (identical to score here), order_id ASC',
            'capacity_rule': 'floor(cap * complete daily batch rows); no carryover between days',
            'known_outcome_rule': 'Caller-supplied mask applied only after full-batch ranking',
            'minimum_group_known_rows': MIN_GROUP_ROWS,
            'minimum_group_delayed_rows': MIN_GROUP_POSITIVES,
            'allocation_rule': 'Within each day and route: within=min(dropped,added), outgoing=max(dropped-added,0), incoming=max(added-dropped,0). Sum outgoing equals sum incoming each day.',
            'interpretation': 'Aggregate daily count accounting only; no individual donor/recipient pairing and no causal feature attribution. Gross daily cross-route movements can cancel in monthly route net totals.',
        },
        'summary': summary, 'allocation_summary': allocation,
        'routes': route_rows, 'days': days, 'route_day_allocations': route_days,
        'rank_movements': _rank_movements(known, labels, old, new, old_bins, new_bins),
        'conservation': {
            'complete_daily_capacity': True, 'known_unknown_outcome_partition': True,
            'route_day_counts': True, 'route_totals': True, 'day_totals': True,
            'daily_cross_route_incoming_equals_outgoing': True,
            'gross_daily_allocation_matches_monthly_routes': True,
            'full_batch_rank_cohort_partition': True,
        },
    }
