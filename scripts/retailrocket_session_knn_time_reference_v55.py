"""Pure numeric six-timer reference summaries; no saved records are loaded.

Ranks and equality use exact numeric comparisons within the same six values.
MAD is the unscaled median of absolute deviations from that sample's median.
These descriptive summaries define no significance or outlier threshold.
"""
from fractions import Fraction
from math import isfinite


PAIRS = tuple(range(1, 7))


def _finite(value, name, *, nonnegative=False):
    try:
        valid = type(value) in (int, float) and isfinite(value) and (not nonnegative or value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite ' + ('nonnegative ' if nonnegative else '') + 'numeric value required: ' + name)
    return value


def _validate_timers(timers):
    if (type(timers) is not dict or set(timers) != set(PAIRS)
            or any(type(pair) is not int for pair in timers)):
        raise ValueError('Exactly integer pair keys 1 through 6 are required')
    return tuple(_finite(timers[pair], 'pair ' + str(pair), nonnegative=True) for pair in PAIRS)


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return _finite(ordered[middle], 'median', nonnegative=True)
    # Exact midpoint arithmetic avoids overflowing two large finite timers and
    # avoids underflow from halving each tiny timer before adding them.
    midpoint = (Fraction(ordered[middle - 1]) + Fraction(ordered[middle])) / 2
    try:
        result = float(midpoint)
    except OverflowError as error:
        raise ValueError('Finite numeric median required') from error
    return _finite(result, 'median', nonnegative=True)


def _summary(values):
    center = _median(values)
    deviations = tuple(_finite(abs(value - center), 'absolute deviation', nonnegative=True) for value in values)
    minimum, maximum = min(values), max(values)
    return dict(count=len(values), min_seconds=minimum, median_seconds=center,
                max_seconds=maximum, mad_seconds=_median(deviations),
                span_seconds=_finite(maximum - minimum, 'span', nonnegative=True))


def _ratio(numerator, denominator, name):
    if denominator == 0:
        return None
    try:
        result = numerator / denominator
    except OverflowError as error:
        raise ValueError('Finite numeric ratio required: ' + name) from error
    return _finite(result, name, nonnegative=True)


def summarize_six(timers):
    """Summarize precisely six finite nonnegative timers keyed by int 1..6."""
    return _summary(_validate_timers(timers))


def locate_in_six(timers, target_pair):
    """Locate a timer in its six-value sample and a separate other-five sample.

    Descending rank 1 is the slowest timer. Counts include the target itself;
    ties require exact equality. Other-five range endpoints count as within.
    Ratios use each sample's own median and are None when that median is zero.
    """
    values = _validate_timers(timers)
    if type(target_pair) is not int or target_pair not in PAIRS:
        raise ValueError('Target pair must be an integer from 1 through 6')
    target = values[target_pair - 1]
    other_values = tuple(value for pair, value in zip(PAIRS, values) if pair != target_pair)
    full, other = _summary(values), _summary(other_values)
    below = sum(value < target for value in values)
    equal = sum(value == target for value in values)
    above = sum(value > target for value in values)
    relation = ('below' if target < other['min_seconds'] else
                'above' if target > other['max_seconds'] else 'within')
    return dict(pair=target_pair, seconds=target,
                rank_desc=dict(first=1 + above, last=above + equal),
                counts=dict(below=below, equal=equal, above=above),
                full_six=full,
                delta_from_median_seconds=_finite(target - full['median_seconds'], 'delta from six median'),
                ratio_to_median=_ratio(target, full['median_seconds'], 'ratio to six median'),
                other_five=other,
                delta_from_other_median_seconds=_finite(target - other['median_seconds'], 'delta from other median'),
                ratio_to_other_median=_ratio(target, other['median_seconds'], 'ratio to other median'),
                relation_to_other_range=relation)
