"""Pure numeric arm decomposition for anonymous positions 32 and 33.

This module receives four absolute timers only. It never loads saved records,
queries, models, SQL, experiment runners or another stage's implementation.
"""
from math import fsum, isclose, isfinite


ARMS = ('R', 'C')
POSITIONS = (32, 33)
TERM_ARMS = ('C', 'R')
TOLERANCE_SECONDS = 1e-8


def _finite(value, name, *, nonnegative=False):
    try:
        valid = type(value) in (int, float) and isfinite(value) and (not nonnegative or value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite ' + ('nonnegative ' if nonnegative else '') + 'numeric value required: ' + name)
    return value


def _sum(values, name):
    try:
        total = fsum(values)
    except OverflowError as error:
        raise ValueError('Finite aggregate required: ' + name) from error
    return _finite(total, name)


def compare_absolute_arms(timers):
    """Decompose delta32-delta33 into C's contrast minus R's contrast.

    ``timers`` must contain precisely R/C, each mapping integer positions 32/33
    to finite nonnegative seconds. Let c=C32-C33 and r=R32-R33. Raw arm terms
    are C=c and R=-r, whose sum is the same gap as (C32-R32)-(C33-R33).

    Nonzero gaps align both terms by the gap sign. Shares use gross positive
    aligned support P, never arm totals or the net gap. A zero gap preserves all
    raw timers and contrasts, but has no alignment direction or support shares.
    This is an arithmetic contrast decomposition, not a causal attribution.
    """
    if (type(timers) is not dict or set(timers) != set(ARMS)
            or any(type(arm) is not str for arm in timers)):
        raise ValueError('Exactly the R and C arm dictionaries are required')
    absolute = {}
    for arm in ARMS:
        values = timers[arm]
        if (type(values) is not dict or set(values) != set(POSITIONS)
                or any(type(position) is not int for position in values)):
            raise ValueError('Exactly integer positions 32 and 33 are required in each arm')
        absolute[arm] = {str(position): _finite(values[position], arm + str(position), nonnegative=True)
                         for position in POSITIONS}
    deltas = {str(position): _finite(absolute['C'][str(position)] - absolute['R'][str(position)], 'query C-minus-R')
              for position in POSITIONS}
    contrasts = {arm: _finite(absolute[arm]['32'] - absolute[arm]['33'], 'within-arm 32-minus-33') for arm in ARMS}
    gap = _finite(deltas['32'] - deltas['33'], 'query-delta gap')
    contrast_gap = _finite(contrasts['C'] - contrasts['R'], 'within-arm gap')
    raw_terms = dict(C=contrasts['C'], R=-contrasts['R'])
    residuals = []

    def reconcile(actual, expected, name):
        residual = _finite(abs(actual - expected), 'reconciliation residual')
        if not isclose(actual, expected, rel_tol=0, abs_tol=TOLERANCE_SECONDS):
            raise ValueError('Absolute-arm contrasts do not conserve ' + name)
        residuals.append(residual)

    reconcile(contrast_gap, gap, 'the two gap calculations')
    reconcile(_sum(raw_terms.values(), 'raw arm terms'), gap, 'raw C plus negative R')
    sign = 1 if gap > 0 else (-1 if gap < 0 else 0)
    components = {}
    for arm in TERM_ARMS:
        aligned = _finite(sign * raw_terms[arm], 'aligned arm contrast')
        components[arm] = dict(aligned_net=aligned, positive_support=max(aligned, 0), negative_offset=min(aligned, 0))
    positive = _sum((row['positive_support'] for row in components.values()), 'gross positive support')
    negative = _sum((row['negative_offset'] for row in components.values()), 'gross negative offsets')
    net = _sum((row['aligned_net'] for row in components.values()), 'aligned net')
    reconcile(_sum((positive, negative), 'positive plus negative'), net, 'aligned positive and negative terms')
    reconcile(net, abs(gap), 'the aligned absolute gap')
    for row in components.values():
        row['positive_share'] = row['positive_support'] / positive if positive else None
    largest = max(row['positive_support'] for row in components.values())
    leading = [arm for arm in TERM_ARMS if positive and components[arm]['positive_support'] == largest]
    return dict(absolute_seconds=absolute, query_delta_seconds=deltas,
        within_arm_gap_seconds=contrasts, raw_arm_terms_seconds=raw_terms, gap_seconds=gap,
        alignment=dict(defined=bool(sign), direction=sign, components=components,
            positive_seconds=positive, negative_seconds=negative, net_seconds=net, leading_support_arms=leading),
        max_reconciliation_residual_seconds=max(residuals))
