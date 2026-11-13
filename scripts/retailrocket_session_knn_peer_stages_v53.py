"""Pure numeric stage contrasts for anonymous positions 32 and 33.

No raw record, runner, SQL, experiment or timer is loaded or executed. Atomic
and grouped views are alternatives; their contributions must never be added.
"""
from math import fsum, isclose, isfinite

from scripts.retailrocket_session_knn_query_distribution_v50 import RANK_STAGES


POSITIONS = (32, 33)
ORDERS = ('CR', 'RC', 'CR', 'RC', 'CR', 'RC')
ATOMIC_KEYS = (*RANK_STAGES, 'rank_other', 'verification_other', 'append', 'query_commit')
GROUP_KEYS = ('ranking', 'verification_other', 'append', 'query_commit')
REMAINDERS = {'rank_other', 'verification_other'}
TOLERANCE_SECONDS = 1e-8
MILLISECOND = .001


def _finite(value, name):
    try:
        valid = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite numeric value required: ' + name)
    return value


def _sum(values, name):
    try:
        value = fsum(values)
    except OverflowError as error:
        raise ValueError('Finite aggregate required: ' + name) from error
    return _finite(value, name)


def _close(values, expected, name):
    total = _sum(values, name)
    if not isclose(total, expected, rel_tol=0, abs_tol=TOLERANCE_SECONDS):
        raise ValueError('Stage components do not conserve ' + name)


def _identity(pair, order):
    if type(pair) is not int or not 1 <= pair <= 6:
        raise ValueError('Integer pair number from 1 through 6 required')
    if type(order) is not str or order != ORDERS[pair - 1]:
        raise ValueError('Original CR/RC pair order required')


def _atomic(values):
    if type(values) is not dict or set(values) != set(ATOMIC_KEYS):
        raise ValueError('Exactly the eleven original atomic stage keys are required')
    return {name: _finite(values[name], name) for name in ATOMIC_KEYS}


def _query(row):
    if type(row) is not dict:
        raise ValueError('A query_parts result dictionary is required')
    values = _atomic(row.get('parts_seconds'))
    for name, value in values.items():
        if value < (-TOLERANCE_SECONDS if name in REMAINDERS else 0):
            raise ValueError('Original stage is negative beyond permitted remainder roundoff: ' + name)
    total = _finite(row.get('query_charged_seconds'), 'query charged seconds')
    if total < 0:
        raise ValueError('Original query charged seconds must be nonnegative')
    _close(values.values(), total, 'original query charged seconds')
    return values, total


def _groups(values):
    return dict(ranking=_sum((values[name] for name in (*RANK_STAGES, 'rank_other')), 'ranking group'),
        **{name: values[name] for name in GROUP_KEYS[1:]})


def _direction(left, right):
    eligible = abs(left) > MILLISECOND and abs(right) > MILLISECOND
    opposite = eligible and (left > 0) != (right > 0)
    return dict(eligible=eligible, opposite_sign=opposite,
        label='opposite_sign' if opposite else ('same_sign' if eligible else 'within_1ms'),
        threshold_seconds=MILLISECOND)


def _aligned_view(rows, keys, expected):
    """Aggregate positive and negative contributions before cross-pair netting."""
    components = {}
    for name in keys:
        values = [row[name] for row in rows]
        components[name] = dict(aligned_net=_sum(values, 'aligned component'),
            positive_support=_sum((max(value, 0) for value in values), 'positive support'),
            negative_offset=_sum((min(value, 0) for value in values), 'negative offset'))
    positive = _sum((row['positive_support'] for row in components.values()), 'gross positive contributions')
    negative = _sum((row['negative_offset'] for row in components.values()), 'gross negative contributions')
    net = _sum((row['aligned_net'] for row in components.values()), 'aligned net')
    _close((positive, negative), expected, 'aligned positive plus negative contributions')
    _close((net,), expected, 'aligned total')
    for row in components.values():
        _close((row['positive_support'], row['negative_offset']), row['aligned_net'], 'aligned component')
        row['positive_share'] = row['positive_support'] / positive if positive else None
    ranked_positive = [dict(component=name, positive_support=row['positive_support'], positive_share=row['positive_share'])
        for name, row in sorted(components.items(), key=lambda item: (-item[1]['positive_support'], item[0]))
        if row['positive_support'] > 0]
    ranked_offsets = [dict(component=name, negative_offset=row['negative_offset'])
        for name, row in sorted(components.items(), key=lambda item: (item[1]['negative_offset'], item[0]))
        if row['negative_offset'] < 0]
    return dict(components=components, positive_seconds=positive, negative_seconds=negative, net_seconds=net,
        ranked_positive=ranked_positive, ranked_offsets=ranked_offsets,
        share_denominator='This view\'s gross positive support across individual pair/stage contributions; never net')


def _position_delta(atomic, total):
    values = _atomic(atomic)
    total = _finite(total, 'position total delta')
    groups = _groups(values)
    _close(values.values(), total, 'position atomic delta')
    _close(groups.values(), total, 'position grouped delta')
    return dict(total_delta_seconds=total, atomic_delta_seconds=values, group_delta_seconds=groups)


def _pair_record(positions, pair, order):
    _identity(pair, order)
    left, right = (positions[str(position)] for position in POSITIONS)
    gap = _finite(left['total_delta_seconds'] - right['total_delta_seconds'], 'gap')
    atomic = {name: _finite(left['atomic_delta_seconds'][name] - right['atomic_delta_seconds'][name], 'atomic gap')
              for name in ATOMIC_KEYS}
    groups = {name: _finite(left['group_delta_seconds'][name] - right['group_delta_seconds'][name], 'grouped gap')
              for name in GROUP_KEYS}
    _close(atomic.values(), gap, 'atomic gap')
    _close(groups.values(), gap, 'grouped gap')
    sign = 1 if gap > 0 else (-1 if gap < 0 else 0)
    return dict(pair=pair, order=order, positions=positions, gap_seconds=gap,
        gap_atomic_seconds=atomic, gap_group_seconds=groups,
        direction=_direction(left['total_delta_seconds'], right['total_delta_seconds']),
        gap_alignment=dict(defined=bool(sign), direction=sign,
            atomic=_aligned_view([{name: sign * value for name, value in atomic.items()}], ATOMIC_KEYS, abs(gap)),
            groups=_aligned_view([{name: sign * value for name, value in groups.items()}], GROUP_KEYS, abs(gap))))


def compare_stage_pair(original, candidate, pair, order):
    """Compare two positions' C-minus-R charged query stages for one pair.

    Inputs map integer positions 32 and 33 to V50 query_parts results. Only the
    eleven charged atomic parts are used, excluding envelope bridges and tail
    commits. A zero gap has no alignment direction: its aligned views are zero,
    with defined=False, while the unaligned component contrasts remain intact.
    """
    _identity(pair, order)
    for arm in (original, candidate):
        if (type(arm) is not dict or set(arm) != set(POSITIONS)
                or any(type(position) is not int for position in arm)):
            raise ValueError('Exactly integer positions 32 and 33 are required in both arms')
    positions = {}
    for position in POSITIONS:
        before, before_total = _query(original[position])
        after, after_total = _query(candidate[position])
        atomic = {name: _finite(after[name] - before[name], 'atomic C-minus-R') for name in ATOMIC_KEYS}
        total = _finite(after_total - before_total, 'total C-minus-R')
        positions[str(position)] = _position_delta(atomic, total)
    return _pair_record(positions, pair, order)


def _validated_pair(row, expected_pair):
    if type(row) is not dict:
        raise ValueError('A paired stage result dictionary is required')
    _identity(row.get('pair'), row.get('order'))
    if row['pair'] != expected_pair:
        raise ValueError('Exactly six pairs in original order are required')
    supplied = row.get('positions')
    if type(supplied) is not dict or set(supplied) != {'32', '33'}:
        raise ValueError('Both anonymous position results are required')
    positions = {}
    for position in ('32', '33'):
        value = supplied[position]
        if type(value) is not dict:
            raise ValueError('A position result dictionary is required')
        positions[position] = _position_delta(value.get('atomic_delta_seconds'), value.get('total_delta_seconds'))
    expected = _pair_record(positions, row['pair'], row['order'])
    direction = row.get('direction')
    if (type(direction) is not dict or type(direction.get('eligible')) is not bool
            or type(direction.get('opposite_sign')) is not bool or row != expected):
        raise ValueError('Saved pair groups, direction, gap or contribution views differ from atomic values')
    return expected


def _signed_summary(pairs):
    positions = {}
    for position in ('32', '33'):
        atomic = {name: _sum((row['positions'][position]['atomic_delta_seconds'][name] for row in pairs),
                            'summed position component') for name in ATOMIC_KEYS}
        total = _sum((row['positions'][position]['total_delta_seconds'] for row in pairs), 'summed position total')
        positions[position] = _position_delta(atomic, total)
    gap = _sum((row['gap_seconds'] for row in pairs), 'summed signed gap')
    atomic = {name: _sum((row['gap_atomic_seconds'][name] for row in pairs), 'summed signed atomic gap') for name in ATOMIC_KEYS}
    groups = {name: _sum((row['gap_group_seconds'][name] for row in pairs), 'summed signed grouped gap') for name in GROUP_KEYS}
    _close(atomic.values(), gap, 'all-pair signed atomic gap')
    _close(groups.values(), gap, 'all-pair signed grouped gap')
    _close((positions['32']['total_delta_seconds'] - positions['33']['total_delta_seconds'],), gap, 'all-pair position gap')
    return dict(count=len(pairs), pair_numbers=[row['pair'] for row in pairs], positions=positions,
                gap_seconds=gap, gap_atomic_seconds=atomic, gap_group_seconds=groups)


def summarize_stage_pairs(pairs):
    """Keep all six signed contrasts and separately align opposite-sign pairs.

    The opposite subset requires both position deltas strictly beyond 1 ms.
    Each included pair is aligned by its own gap sign before taking per-stage
    positive support and negative offsets. Atomic and grouped gross-positive
    denominators are computed separately. Empty subsets retain zero totals and
    None shares. No stage medians or averages are calculated.
    """
    if type(pairs) not in (list, tuple) or len(pairs) != 6:
        raise ValueError('Exactly six pairs in original order are required')
    pairs = [_validated_pair(row, index) for index, row in enumerate(pairs, 1)]
    opposite = [row for row in pairs if row['direction']['opposite_sign']]
    aligned_total = _sum((abs(row['gap_seconds']) for row in opposite), 'opposite-pair absolute gaps')

    def aligned_rows(field, keys):
        return [{name: row['gap_alignment']['direction'] * row[field][name] for name in keys} for row in opposite]

    return dict(pairs=pairs, all_pairs=_signed_summary(pairs),
        opposite_pair_numbers=[row['pair'] for row in opposite],
        direction_counts=dict(eligible_count=sum(row['direction']['eligible'] for row in pairs),
            opposite_sign_count=len(opposite), same_sign_count=sum(row['direction']['label'] == 'same_sign' for row in pairs),
            within_1ms_count=sum(not row['direction']['eligible'] for row in pairs)),
        opposite_pairs=dict(count=len(opposite), pair_numbers=[row['pair'] for row in opposite],
            aligned_total_seconds=aligned_total,
            atomic=_aligned_view(aligned_rows('gap_atomic_seconds', ATOMIC_KEYS), ATOMIC_KEYS, aligned_total),
            groups=_aligned_view(aligned_rows('gap_group_seconds', GROUP_KEYS), GROUP_KEYS, aligned_total)),
        interpretation='All-pair sums remain signed. Opposite pairs are a post-hoc descriptive subset, '
            'aligned separately by each gap sign before positive and negative aggregation. '
            'Atomic and grouped views use independent gross-positive denominators and are not additive. '
            'Only charged query time is compared; no tail commit is assigned to either position.')
