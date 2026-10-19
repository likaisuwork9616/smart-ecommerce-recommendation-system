"""Pure complete-day diagnostics of four frozen score ledgers.

No model is loaded, fitted, or selected. Public objects contain aggregates only;
the separate private object must never be serialized into a public report.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts import diagnose_age_colsample as colsample
from scripts.delay_calibration_policy import _batch_dates
from scripts.diagnose_rank_batch_size import _known_labels

VERSIONS = colsample.VERSIONS
CONTRASTS = colsample.CONTRASTS
PATTERNS = tuple(f'{value:04b}' for value in range(16))
GAP_BINS = ('capacity_zero', 'inside_budget', 'one_to_three', 'four_to_ten', 'eleven_plus')
DAILY_EXCHANGE_FIELDS = ('old_alerts', 'new_alerts') + colsample.EXCHANGES + colsample.ALLOCATIONS
FLOW_FIELDS = ('complete_days', 'added_alerts', 'dropped_alerts', 'within_route_exchanges',
               'cross_route_slots', 'within_cell_exchanges', 'cross_cell_slots')


def schema():
    """Describe ordered fields, including the compact daily exchange ledger."""
    return {
        'format_version': 1, 'versions': list(VERSIONS),
        'contrasts': {name: {'old': old, 'new': new} for name, (old, new) in CONTRASTS.items()},
        'denominators': list(colsample.DENOMINATORS), 'model_metrics': list(colsample.METRICS),
        'exchange_metrics': list(colsample.EXCHANGES), 'allocation_metrics': list(colsample.ALLOCATIONS),
        'group_fields': ['kind', 'key', 'denominators', 'models', 'common_missed_delays',
                         'any_caught_delays', 'all_caught_delays', 'catch_patterns', 'common_miss_gap', 'contrasts'],
        'contrast_fields': ['exchanges', 'allocations', 'lost_gap', 'recovered_gap'],
        'catch_pattern_order': list(VERSIONS), 'catch_patterns': list(PATTERNS),
        'gap_bins': list(GAP_BINS),
        'gap_definition': 'One-based complete-day rank minus floor(full-day rows / 10); capacity_zero is separate regardless of distance.',
        'daily_exchange_row': ['day', 'kind', 'key', 'contrast', 'values'],
        'daily_exchange_fields': list(DAILY_EXCHANGE_FIELDS), 'flow_fields': list(FLOW_FIELDS),
        'privacy': 'Only the separate private return value contains order identities or row-aligned ranks.',
    }


def gap_summary(mask, positions, capacity):
    """Summarize a cohort's full-day distance from the fixed daily capacity.

    The zero-capacity bin takes precedence over all distance bins. Empty cohort
    summaries retain all bins and null extrema. Inputs are aligned row vectors.
    """
    mask, positions, capacity = np.asarray(mask), np.asarray(positions), np.asarray(capacity)
    if (mask.ndim != 1 or mask.dtype != bool or positions.shape != mask.shape
            or capacity.shape != mask.shape or positions.dtype.kind not in 'iu'
            or capacity.dtype.kind not in 'iu' or (positions < 1).any() or (capacity < 0).any()):
        raise ValueError('Require aligned boolean mask, positive integer ranks and nonnegative integer capacity')
    # Signed subtraction also preserves inside-budget distances for callers
    # supplying ordinary unsigned integer rank/capacity arrays.
    if (positions > np.iinfo(np.int64).max).any() or (capacity > np.iinfo(np.int64).max).any():
        raise ValueError('Rank and capacity must fit signed 64-bit integers')
    gaps = positions.astype(np.int64) - capacity.astype(np.int64)
    selected = gaps[mask]
    eligible = mask & (capacity > 0)
    bins = {
        'capacity_zero': int((mask & (capacity == 0)).sum()),
        'inside_budget': int((eligible & (gaps <= 0)).sum()),
        'one_to_three': int((eligible & (gaps >= 1) & (gaps <= 3)).sum()),
        'four_to_ten': int((eligible & (gaps >= 4) & (gaps <= 10)).sum()),
        'eleven_plus': int((eligible & (gaps >= 11)).sum()),
    }
    if sum(bins.values()) != int(mask.sum()):
        raise AssertionError('Rank-gap bins do not partition the cohort')
    return {'rows': int(mask.sum()), 'minimum': int(selected.min()) if len(selected) else None,
            'median': float(np.median(selected)) if len(selected) else None,
            'maximum': int(selected.max()) if len(selected) else None, 'bins': bins}


def decode_group(public, kind='overall', key='ALL'):
    return next(row for row in public['groups'] if row['kind'] == kind and row['key'] == key)


def decode_daily_exchange(row):
    day, kind, key, contrast, values = row
    return {'day': day, 'kind': kind, 'key': key, 'contrast': contrast,
            **dict(zip(DAILY_EXCHANGE_FIELDS, values, strict=True))}


def _ranking(values, ids, day_codes, day_sizes):
    order = np.lexsort((ids, -values, day_codes))
    ranks = np.empty(len(ids), dtype=int)
    ranks[order] = np.arange(len(ids)) - np.repeat(np.cumsum(day_sizes) - day_sizes, day_sizes) + 1
    return ranks


def _daily_counts(mask, day_codes, day_count):
    return np.bincount(day_codes[mask], minlength=day_count).astype(int)


def _boundaries(values, positions, day_indices, days, known, day_capacities):
    rows = []
    for index, indices in enumerate(day_indices):
        cap = int(day_capacities[index])
        local = values[indices]
        alerted = positions[indices] <= cap
        cutoff = float(local[positions[indices] == cap][0]) if cap else None
        tie = local == cutoff if cap else np.zeros(len(indices), bool)
        selected_tie, excluded_tie = int((tie & alerted).sum()), int((tie & ~alerted).sum())
        next_score = float(local[positions[indices] == cap + 1][0]) if cap < len(indices) else None
        rows.append({'day': str(days[index].date()), 'full_rows': len(indices), 'capacity': cap,
                     'known_alerts': int((known[indices] & alerted).sum()),
                     'unknown_alerts': int((~known[indices] & alerted).sum()),
                     'cutoff_score': cutoff, 'next_score': next_score,
                     'score_margin': cutoff - next_score if cap and next_score is not None else None,
                     'cutoff_tie_rows': int(tie.sum()), 'cutoff_tie_alerted_rows': selected_tie,
                     'cutoff_tie_unalerted_rows': excluded_tie,
                     'cross_boundary_tie': bool(selected_tie and excluded_tie)})
    return rows


def diagnose_phase(frame, scores, known, *, include_daily=True):
    """Return ``(public, private)`` for one seed and one original phase.

    All ranking precedes outcome and subgroup masks. Each complete day uses
    score DESC, order_id ASC and exactly floor(N / 10) slots. Unknown outcomes
    occupy slots but can never count as TP, FP, FN, recovered, or lost delays.
    Daily allocations are computed and checked even when detail is omitted.
    """
    required = {'order_id', 'prediction_time', 'delayed'}
    if not isinstance(frame, pd.DataFrame) or frame.empty or not required.issubset(frame):
        raise ValueError('Require a nonempty complete phase with order, time and outcome columns')
    if set(scores) != set(VERSIONS):
        raise ValueError('Require exactly the four fixed scoring versions')
    if not isinstance(include_daily, bool):
        raise ValueError('include_daily must be boolean')
    ids, dates = _batch_dates(frame, len(frame))
    known, labels = _known_labels(frame, known)
    day_codes, days = pd.factorize(dates, sort=True)
    day_sizes = np.bincount(day_codes)
    day_capacities = day_sizes // 10
    capacity = day_capacities[day_codes]
    day_count = len(days)
    # Group indices are built once, avoiding repeated full-frame scans per day.
    day_order = np.argsort(day_codes, kind='stable')
    day_indices = np.split(day_order, np.cumsum(day_sizes)[:-1])
    alerts, positions, boundaries, boundary_totals = {}, {}, {}, {}
    for version in VERSIONS:
        try:
            raw = np.asarray(scores[version])
            if np.iscomplexobj(raw) or raw.dtype.kind == 'b':
                raise ValueError
            values = np.asarray(raw, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError('Scores must be finite probability vectors') from exc
        if values.shape != (len(frame),) or not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError('Require finite bounded scores for every full-batch row')
        positions[version] = _ranking(values, ids, day_codes, day_sizes)
        alerts[version] = positions[version] <= capacity
        if not np.array_equal(_daily_counts(alerts[version], day_codes, day_count), day_capacities):
            raise AssertionError('Ranked daily alert counts do not equal capacity')
        boundaries[version] = _boundaries(values, positions[version], day_indices, days, known, day_capacities)
        boundary_totals[version] = {
            'complete_days': day_count, 'capacity': int(day_capacities.sum()),
            'known_alerts': int((known & alerts[version]).sum()),
            'unknown_alerts': int((~known & alerts[version]).sum()),
            'capacity_zero_days': int((day_capacities == 0).sum()),
            'cross_boundary_tie_days': sum(row['cross_boundary_tie'] for row in boundaries[version]),
            'cutoff_tie_rows': sum(row['cutoff_tie_rows'] for row in boundaries[version]),
            'cutoff_tie_unalerted_rows': sum(row['cutoff_tie_unalerted_rows'] for row in boundaries[version]),
        }
    masks = colsample.group_masks(frame)
    present_routes = {key for kind, key, _ in masks if kind == 'route'}
    for route in ('SP->RJ', 'SP->SC', 'SP->SP'):
        if route not in present_routes:
            masks.append(('route', route, np.zeros(len(frame), dtype=bool)))
    masks.sort(key=lambda row: (('overall', 'route', 'marginal', 'cell', 'cell110_age').index(row[0]),
                               row[1] if row[0] == 'route' else 0))
    positive = known & (labels == 1)
    bits = sum(alerts[version].astype(np.int8) * (1 << (3 - i)) for i, version in enumerate(VERSIONS))
    common_missed = positive & (bits == 0)
    private = {'row_ids': ids.copy(), 'positions': positions, 'capacity': capacity,
               'delayed': {}, 'missed': {version: {} for version in VERSIONS},
               'common_missed': {}, 'lost': {contrast: {} for contrast in CONTRASTS}}
    groups, daily_exchanges = [], []
    # Values indexed by group and contrast are retained only for conservation.
    partition_daily = {'route': {}, 'cell': {}}
    for kind, key, mask in masks:
        identity = f'{kind}:{key}'
        delayed = mask & positive
        denominators = dict(zip(colsample.DENOMINATORS,
            (int(mask.sum()), int((mask & known).sum()), int((mask & ~known).sum()), int(delayed.sum())), strict=True))
        models = {version: dict(zip(colsample.METRICS,
                   colsample.model_counts(mask, known, labels, alerts[version]), strict=True)) for version in VERSIONS}
        patterns = dict(zip(PATTERNS, np.bincount(bits[delayed], minlength=16).astype(int).tolist(), strict=True))
        row = {'kind': kind, 'key': key, 'denominators': denominators, 'models': models,
               'common_missed_delays': patterns['0000'],
               'any_caught_delays': int(delayed.sum()) - patterns['0000'],
               'all_caught_delays': patterns['1111'], 'catch_patterns': patterns,
               'common_miss_gap': {version: gap_summary(mask & common_missed, positions[version], capacity)
                                   for version in VERSIONS}, 'contrasts': {}}
        private['delayed'][identity] = set(ids[delayed])
        private['common_missed'][identity] = set(ids[mask & common_missed])
        for version in VERSIONS:
            private['missed'][version][identity] = set(ids[delayed & ~alerts[version]])
        for contrast, (old_version, new_version) in CONTRASTS.items():
            old, new = alerts[old_version], alerts[new_version]
            added, dropped = mask & ~old & new, mask & old & ~new
            lost, recovered = delayed & dropped, delayed & added
            exchange_values = colsample.exchange_counts(mask, known, labels, old, new)
            exchange = dict(zip(colsample.EXCHANGES, exchange_values, strict=True))
            if (exchange['added_alerts'] != exchange['recovered_delays'] + exchange['added_on_time_alerts'] + exchange['unknown_added_alerts']
                or exchange['dropped_alerts'] != exchange['lost_delays'] + exchange['removed_on_time_alerts'] + exchange['unknown_removed_alerts']
                or models[new_version]['TP'] - models[old_version]['TP'] != exchange['recovered_delays'] - exchange['lost_delays']):
                raise AssertionError('Paired delay and known/unknown exchanges do not reconcile')
            # Always count day first: two opposite route transfers on separate
            # days cannot cancel into a fictitious within-route exchange.
            daily_columns = [
                _daily_counts(mask & old, day_codes, day_count),
                _daily_counts(mask & new, day_codes, day_count),
                *[_daily_counts(cohort, day_codes, day_count) for cohort in
                  (recovered, lost, added, dropped, added & known & (labels == 0),
                   dropped & known & (labels == 0), added & ~known, dropped & ~known, mask & old & new)],
            ]
            added_days, dropped_days = daily_columns[4], daily_columns[5]
            allocations = [np.minimum(added_days, dropped_days), np.maximum(dropped_days - added_days, 0),
                           np.maximum(added_days - dropped_days, 0)]
            daily_values = np.column_stack(daily_columns + allocations)
            allocation = dict(zip(colsample.ALLOCATIONS, daily_values[:, -3:].sum(axis=0).astype(int).tolist(), strict=True))
            row['contrasts'][contrast] = {'exchanges': exchange, 'allocations': allocation,
                'lost_gap': {side: gap_summary(lost, positions[version], capacity)
                             for side, version in (('old', old_version), ('new', new_version))},
                'recovered_gap': {side: gap_summary(recovered, positions[version], capacity)
                                  for side, version in (('old', old_version), ('new', new_version))}}
            private['lost'][contrast][identity] = set(ids[lost])
            if kind in partition_daily:
                partition_daily[kind].setdefault(contrast, []).append(daily_values)
                if include_daily:
                    daily_exchanges.extend([str(day.date()), kind, key, contrast, values.tolist()]
                                           for day, values in zip(days, daily_values, strict=True))
        if sum(patterns.values()) != denominators['positive_rows']:
            raise AssertionError('Four-model catch patterns do not partition known delays')
        groups.append(row)
    overall = groups[0]
    flows = {}
    for contrast in CONTRASTS:
        partition_totals = {}
        for kind in ('route', 'cell'):
            total = np.sum(partition_daily[kind][contrast], axis=0)
            # The allocation columns are intentionally summed across groups;
            # every other daily count is an ordinary disjoint partition.
            if (not np.array_equal(total[:, 4], total[:, 5])
                    or not np.array_equal(total[:, 2] + total[:, 6] + total[:, 8], total[:, 4])
                    or not np.array_equal(total[:, 3] + total[:, 7] + total[:, 9], total[:, 5])
                    or not np.array_equal(total[:, 12], total[:, 13])
                    or not np.array_equal(total[:, 11] + total[:, 13], total[:, 4])):
                raise AssertionError('Daily route/cell changed-slot conservation failed')
            if not np.array_equal(total[:, 0], day_capacities) or not np.array_equal(total[:, 1], day_capacities):
                raise AssertionError('Daily partition alert counts do not equal capacity')
            partition_totals[kind] = total
        if not np.array_equal(partition_totals['route'][:, :11], partition_totals['cell'][:, :11]):
            raise AssertionError('Route and cell daily outcome exchanges disagree')
        route, cell = partition_totals['route'], partition_totals['cell']
        exchange = overall['contrasts'][contrast]['exchanges']
        flows[contrast] = dict(zip(FLOW_FIELDS, (day_count, exchange['added_alerts'], exchange['dropped_alerts'],
            int(route[:, 11].sum()), int(route[:, 13].sum()), int(cell[:, 11].sum()), int(cell[:, 13].sum())), strict=True))
    for kind in ('route', 'cell'):
        selected = [row for row in groups if row['kind'] == kind]
        for name in colsample.DENOMINATORS:
            if sum(row['denominators'][name] for row in selected) != overall['denominators'][name]:
                raise AssertionError('Route/cell denominators do not partition the phase')
        for version in VERSIONS:
            for name in colsample.METRICS[:6]:
                if sum(row['models'][version][name] for row in selected) != overall['models'][version][name]:
                    raise AssertionError('Route/cell outcome counts do not partition the phase')
    public = {'groups': groups, 'daily_gross_totals': flows, 'boundary_totals': boundary_totals}
    if include_daily:
        public['daily_boundaries'] = [
            {'day': str(day.date()), 'full_rows': int(day_sizes[i]), 'capacity': int(day_capacities[i]),
             'models': {version: {name: value for name, value in boundaries[version][i].items()
                                  if name not in ('day', 'full_rows', 'capacity')} for version in VERSIONS}}
            for i, day in enumerate(days)]
        public['daily_exchanges'] = daily_exchanges
    return public, private
