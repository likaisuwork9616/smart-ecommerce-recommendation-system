"""Describe one run against each position's own six-run timer reference.

Only the other 46 anonymous positions form the comparison cohort. Per-position
deviations are summarized as a distribution, never summed as elapsed time.
Callers must supply one arm and one stage at a time; this module reads no data.
"""
from fractions import Fraction
from math import isfinite

from scripts.retailrocket_session_knn_time_reference_v55 import locate_in_six


POSITIONS = tuple(range(1, 49))
TARGETS = (32, 33)
PAIRS = tuple(range(1, 7))
THRESHOLD_SECONDS = 0.001


def _direction(value, threshold=0):
    return 'above' if value > threshold else 'below' if value < -threshold else 'neutral'


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    # This helper receives exactly 46 finite signed deviations. Exact midpoint
    # arithmetic also handles two large same-sign or tiny subnormal values.
    median = float((Fraction(ordered[middle - 1]) + Fraction(ordered[middle])) / 2)
    if not isfinite(median):
        raise ValueError('Finite cohort median required')
    return median


def _counts(values, threshold):
    directions = tuple(_direction(value, threshold) for value in values)
    return {name: directions.count(name) for name in ('above', 'neutral', 'below')}


def _majority(counts):
    return next((direction for direction in ('above', 'below') if counts[direction] > 23), None)


def _comparison(delta, counts, majority, threshold):
    direction = _direction(delta, threshold)
    if direction == 'neutral':
        return dict(target_direction=direction, same_count=None, opposite_count=None,
                    neutral_count=counts['neutral'], same_fraction_of_46=None, matches_majority=None)
    opposite = 'below' if direction == 'above' else 'above'
    return dict(target_direction=direction, same_count=counts[direction],
                opposite_count=counts[opposite], neutral_count=counts['neutral'],
                same_fraction_of_46=counts[direction] / 46,
                matches_majority=direction == majority if majority is not None else None)


def analyze_same_run(timers_by_position, pair):
    """Compare pair 1..6 with independent six-value references at positions 1..48.

    Inputs must be exact dictionaries with integer keys and finite nonnegative
    numeric timer values, as required by V55. Zero-median ratios remain None.
    Raw direction uses zero; over-1ms direction uses strict +/-0.001 thresholds.
    A majority requires more than 23 of the 46 positions excluding 32 and 33.
    """
    if (type(timers_by_position) is not dict or set(timers_by_position) != set(POSITIONS)
            or any(type(position) is not int for position in timers_by_position)):
        raise ValueError('Exactly integer position keys 1 through 48 are required')
    if type(pair) is not int or pair not in PAIRS:
        raise ValueError('Pair must be an integer from 1 through 6')
    positions = {str(position): locate_in_six(timers_by_position[position], pair) for position in POSITIONS}
    others = [position for position in POSITIONS if position not in TARGETS]
    deltas = tuple(positions[str(position)]['delta_from_median_seconds'] for position in others)
    raw_counts = _counts(deltas, 0)
    threshold_counts = _counts(deltas, THRESHOLD_SECONDS)
    majorities = dict(raw=_majority(raw_counts), over_1ms=_majority(threshold_counts))
    cohort = dict(count=46,
                  delta_seconds=dict(min=min(deltas), median=_median(deltas), max=max(deltas)),
                  direction_counts=dict(above=raw_counts['above'], equal=raw_counts['neutral'], below=raw_counts['below']),
                  over_1ms_counts=dict(above=threshold_counts['above'], within=threshold_counts['neutral'], below=threshold_counts['below']),
                  unique_longest_count=sum(positions[str(position)]['rank_desc'] == dict(first=1, last=1) for position in others),
                  unique_shortest_count=sum(positions[str(position)]['rank_desc'] == dict(first=6, last=6) for position in others),
                  majority_direction=majorities)
    comparisons = {}
    for position in TARGETS:
        delta = positions[str(position)]['delta_from_median_seconds']
        comparisons[str(position)] = dict(delta_seconds=delta,
            raw=_comparison(delta, raw_counts, majorities['raw'], 0),
            over_1ms=_comparison(delta, threshold_counts, majorities['over_1ms'], THRESHOLD_SECONDS))
    return dict(pair=pair, positions=positions, other_positions=others,
                other46_summary=cohort, target_comparisons=comparisons)
