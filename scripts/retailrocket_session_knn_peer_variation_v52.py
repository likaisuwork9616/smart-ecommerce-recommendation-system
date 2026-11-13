"""Describe six paired C-minus-R query deltas using numbers supplied by callers.

No saved data, experiment, query engine or model is loaded here. Positive
differences mean the candidate took longer. MAD is the unscaled median absolute
deviation from the series median. Pair order is always CR, RC, CR, RC, CR, RC.
"""
from math import fsum, isfinite
from statistics import median


MILLISECOND = .001
ORDERS = ('CR', 'RC', 'CR', 'RC', 'CR', 'RC')


def _finite(value, name):
    try:
        valid = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite number required: ' + name)
    return value


def _position(value, name):
    if type(value) is not int or not 1 <= value <= 48:
        raise ValueError('Integer position from 1 through 48 required: ' + name)
    return value


def _describe(values):
    values = list(values)
    try:
        total = fsum(values)
        center = median(values)
        spread = max(values) - min(values)
        deviation = median([abs(value - center) for value in values])
    except OverflowError as error:
        raise ValueError('Finite aggregate required') from error
    for value in (total, center, spread, deviation):
        _finite(value, 'aggregate')
    return dict(values=values, count=len(values), sum=total, median=center,
        min=min(values), max=max(values), range=spread, mad=deviation,
        positive_count=sum(value > 0 for value in values),
        negative_count=sum(value < 0 for value in values),
        zero_count=sum(value == 0 for value in values),
        above_1ms=sum(value > MILLISECOND for value in values),
        below_minus_1ms=sum(value < -MILLISECOND for value in values),
        within_1ms=sum(-MILLISECOND <= value <= MILLISECOND for value in values))


def _summary(values):
    result = _describe(values)
    result['by_order'] = {
        order: _describe([value for value, pair_order in zip(values, ORDERS, strict=True) if pair_order == order])
        for order in ('CR', 'RC')}
    return result


def summarize_peer_variation(position_deltas, target, peers):
    """Summarize supplied positions without mutating or retaining input lists.

    ``position_deltas`` is a dict of integer positions 1..48 to six finite int
    or float seconds; each series may be a list or tuple. All supplied entries
    are validated, including unselected positions. ``peers`` is a list or tuple
    of unique positions present in that dict, excluding the target.

    Each peer's direction comparison counts only pairs where both absolute
    deltas exceed 1 ms. Exact +/-1 ms belongs to ``within_1ms``. Peer medians
    are computed separately within each pair before summarizing either that
    series or target-minus-peer-median. These summaries are None with no peers.
    Derived nonfinite aggregates are rejected as well as nonfinite inputs.
    """
    if type(position_deltas) is not dict:
        raise ValueError('A position-to-six-deltas dict is required')
    target = _position(target, 'target')
    if type(peers) not in (list, tuple):
        raise ValueError('A list or tuple of peer positions is required')
    selected = [_position(peer, 'peer') for peer in peers]
    if len(selected) != len(set(selected)) or target in selected:
        raise ValueError('Peer positions must be unique and exclude the target')
    data = {}
    for position, values in position_deltas.items():
        _position(position, 'key')
        if type(values) not in (list, tuple) or len(values) != len(ORDERS):
            raise ValueError('Exactly six deltas in a list or tuple are required')
        data[position] = [_finite(value, 'paired delta') for value in values]
    if target not in data or any(peer not in data for peer in selected):
        raise ValueError('Target and all peer positions must have supplied deltas')
    target_values = data[target]
    peer_summaries = []
    for peer in selected:
        values = data[peer]
        eligible = [(left, right) for left, right in zip(target_values, values, strict=True)
                    if abs(left) > MILLISECOND and abs(right) > MILLISECOND]
        same = sum((left > 0) == (right > 0) for left, right in eligible)
        peer_summaries.append(dict(position=peer, summary=_summary(values),
            direction_vs_target=dict(eligible_count=len(eligible), same_sign_count=same,
                opposite_sign_count=len(eligible) - same, ineligible_count=len(ORDERS) - len(eligible))))
    peer_median_summary = target_minus_peer_median_summary = None
    if selected:
        peer_medians = [_finite(median([data[peer][index] for peer in selected]), 'pair peer median')
                        for index in range(len(ORDERS))]
        relative = [_finite(left - right, 'target minus pair peer median')
                    for left, right in zip(target_values, peer_medians, strict=True)]
        peer_median_summary = _summary(peer_medians)
        target_minus_peer_median_summary = _summary(relative)
    return dict(target_position=target, pair_orders=list(ORDERS), threshold_seconds=MILLISECOND,
        target_summary=_summary(target_values), peer_summaries=peer_summaries,
        peer_median_summary=peer_median_summary,
        target_minus_peer_median_summary=target_minus_peer_median_summary)
