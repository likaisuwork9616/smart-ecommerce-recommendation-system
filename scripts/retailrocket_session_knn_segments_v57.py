"""Pure numeric fixed-position blocks and adjacent direction runs.

Signed deviations are descriptive values, never summed as elapsed time. Runs
use original position adjacency; neutral and excluded positions break a run,
while eight-position block boundaries do not. No records are loaded here.
"""
from fractions import Fraction
from math import isfinite


BLOCKS = ((1, 8), (9, 16), (17, 24), (25, 32), (33, 40), (41, 48))
TARGETS = (32, 33)
POSITIONS = tuple(range(1, 49))
DIRECTIONS = ('above', 'neutral', 'below')
MODES = {'raw': 0, 'over_1ms': 0.001}
SYMBOLS = {'above': '+', 'neutral': '0', 'below': '-'}


def _finite(value):
    try:
        valid = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite signed numeric deviations required')
    return value


def _direction(value, threshold):
    return 'above' if value > threshold else 'below' if value < -threshold else 'neutral'


def _summary(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else float(
        (Fraction(ordered[middle - 1]) + Fraction(ordered[middle])) / 2)
    return dict(min=ordered[0], median=_finite(median), max=ordered[-1])


def _counts(directions):
    return {direction: directions.count(direction) for direction in DIRECTIONS}


def _runs(directions):
    runs = []
    for position, direction in enumerate(directions, start=1):
        if direction not in ('above', 'below'):
            continue
        if runs and runs[-1]['direction'] == direction and runs[-1]['end'] == position - 1:
            runs[-1]['end'] = position
            runs[-1]['length'] += 1
        else:
            runs.append(dict(direction=direction, start=position, end=position, length=1))
    longest = {}
    for direction in ('above', 'below'):
        matching = [run for run in runs if run['direction'] == direction]
        length = max((run['length'] for run in matching), default=0)
        longest[direction] = dict(length=length, segments=[
            {key: run[key] for key in ('start', 'end', 'length')}
            for run in matching if run['length'] == length])
    return runs, longest


def _view(values, excluded):
    eligible = [position for position in POSITIONS if position not in excluded]
    modes = {}
    for mode, threshold in MODES.items():
        directions = [_direction(values[position], threshold) if position not in excluded else 'excluded'
                      for position in POSITIONS]
        runs, longest = _runs(directions)
        modes[mode] = dict(counts=_counts(directions),
                           sequence=''.join(SYMBOLS.get(direction, 'x') for direction in directions),
                           runs=runs, longest=longest)
    blocks = []
    for start, end in BLOCKS:
        selected = [position for position in eligible if start <= position <= end]
        block_modes = {}
        for mode, threshold in MODES.items():
            counts = _counts([_direction(values[position], threshold) for position in selected])
            total = modes[mode]['counts']
            block_modes[mode] = dict(counts=counts,
                densities={direction: counts[direction] / len(selected) for direction in DIRECTIONS},
                shares={direction: counts[direction] / total[direction] if total[direction] else None
                        for direction in DIRECTIONS})
        blocks.append(dict(start=start, end=end, count=len(selected),
                           delta_seconds=_summary([values[position] for position in selected]), modes=block_modes))
    return dict(count=len(eligible), excluded_positions=list(excluded), blocks=blocks, modes=modes)


def analyze_segments(deltas):
    """Analyze exactly 48 finite signed deviations keyed by integer positions.

    Block densities use eligible block size (8, or 7 around an excluded target).
    Direction shares use the same view/mode's full direction count; an absent
    direction gives None shares. +/-1ms endpoints are neutral in over_1ms mode.
    """
    if (type(deltas) is not dict or set(deltas) != set(POSITIONS)
            or any(type(position) is not int for position in deltas)):
        raise ValueError('Exactly integer position keys 1 through 48 are required')
    values = {position: _finite(deltas[position]) for position in POSITIONS}
    positions = [dict(position=position, delta_seconds=values[position],
                      raw_direction=_direction(values[position], MODES['raw']),
                      over_1ms_direction=_direction(values[position], MODES['over_1ms']),
                      is_target=position in TARGETS) for position in POSITIONS]
    return dict(positions=positions, views=dict(all48=_view(values, ()), other46=_view(values, TARGETS)))
