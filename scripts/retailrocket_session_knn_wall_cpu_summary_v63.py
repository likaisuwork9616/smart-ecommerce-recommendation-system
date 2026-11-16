"""Pure provided-record statistics for V62; no clocks, files or calibration.

Ratios and gate decisions use exact fractions of integer durations. Display
medians also retain their exact rational form; no rounded display value is used
to decide whether a budget passed.
"""
from copy import deepcopy
from fractions import Fraction
from math import isfinite


ORDERS = ('OD', 'DO') * 4
SCHEDULE = (('warm_O', 'O'), ('warm_D', 'D')) + tuple(
    (f'pair_{pair}_{mode}', mode)
    for pair, order in enumerate(ORDERS, 1) for mode in order)
MEDIAN_LIMIT = Fraction(2, 100)
MAXIMUM_LIMIT = Fraction(5, 100)


def _fraction(value):
    if type(value) is int or type(value) is Fraction:
        return Fraction(value)
    if type(value) is float and isfinite(value):
        return Fraction(value)
    raise ValueError('Finite numeric value required; bool is not a number')


def _median(values):
    ordered = sorted(_fraction(value) for value in values)
    middle = len(ordered) // 2
    return (ordered[middle] if len(ordered) % 2 else
            (ordered[middle - 1] + ordered[middle]) / 2)


def _display(value):
    rational = _fraction(value)
    if rational.denominator == 1:
        return rational.numerator
    try:
        result = float(rational)
    except OverflowError as error:
        raise ValueError('Derived display value exceeds finite float range') from error
    if not isfinite(result):
        raise ValueError('Derived display value must remain finite')
    return result


def nearest_rank(values, p):
    """Return the original value at ceil(p*n), using a 1-based rank.

    Float p is interpreted by its decimal spelling (for example, 0.95), so a
    binary representation just above a rank boundary does not advance a rank.
    Nulls are not silently discarded here; distribution handles missing values.
    """
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError('A nonempty ordered collection is required')
    for value in values:
        _fraction(value)
    probability = _fraction(p)
    if type(p) is float:
        probability = Fraction(str(p))
    if not 0 < probability <= 1:
        raise ValueError('Percentile must satisfy 0 < p <= 1')
    product = probability * len(values)
    rank = (product.numerator + product.denominator - 1) // product.denominator
    return sorted(values)[rank - 1]


def distribution(values):
    """Keep the missing denominator and an exact median alongside its display."""
    if not isinstance(values, (list, tuple)):
        raise ValueError('A list or tuple of values is required')
    available = [value for value in values if value is not None]
    for value in available:
        _fraction(value)
    if not available:
        return dict(count=len(values), valid=0, missing=len(values), min=None,
                    median=None, median_exact=None, max=None, p95=None)
    middle = _median(available)
    return dict(count=len(values), valid=len(available), missing=len(values)-len(available),
                min=_display(min(available)), median=_display(middle),
                median_exact=dict(numerator=middle.numerator, denominator=middle.denominator),
                max=_display(max(available)), p95=_display(nearest_rank(available, .95)))


def _reason(row):
    if not row['completed']:
        return 'incomplete'
    if row['wall_ns'] is None:
        return 'missing_wall'
    if row['mode'] == 'O' and row['wall_ns'] == 0:
        return 'zero_original_duration'
    return None


def summarize_overhead(rows):
    """Summarize exactly two warmups and eight original/diagnostic pairs.

    Rows must have label, mode, wall_ns and completed. A missing wall or an
    incomplete row stays in its original pair and prevents acceptance. Missing,
    extra, duplicate or out-of-order rows are structural errors, not a reason
    to repair the schedule. This function does not collect measurements or
    attest to the origin of supplied records.
    """
    if not isinstance(rows, (list, tuple)) or len(rows) != len(SCHEDULE):
        raise ValueError('Exactly eighteen rows in the fixed schedule are required')
    for row, (label, mode) in zip(rows, SCHEDULE, strict=True):
        if (not isinstance(row, dict)
                or set(row) != {'label', 'mode', 'wall_ns', 'completed'}
                or row['label'] != label or row['mode'] != mode
                or type(row['completed']) is not bool):
            raise ValueError('Fixed labels, modes, fields and completion flags are required')
        wall = row['wall_ns']
        if wall is not None and (type(wall) is not int or wall < 0):
            raise ValueError('Wall duration must be a nonnegative integer or null')

    warm = [dict(**deepcopy(row), unavailable_reason=_reason(row)) for row in rows[:2]]
    pairs, ratios, deltas, signed_ratios = [], [], [], []
    for pair, order in enumerate(ORDERS, 1):
        by_mode = {row['mode']: row for row in rows[2 + (pair-1)*2:4 + (pair-1)*2]}
        original, diagnostic = by_mode['O'], by_mode['D']
        reasons = {mode: _reason(by_mode[mode]) for mode in ('O', 'D')}
        if any(reason is not None for reason in reasons.values()):
            delta = signed = ratio = None
        else:
            delta = diagnostic['wall_ns'] - original['wall_ns']
            signed = Fraction(delta, original['wall_ns'])
            ratio = abs(signed)
        deltas.append(delta)
        signed_ratios.append(signed)
        ratios.append(ratio)
        pairs.append(dict(pair=pair, order=order,
            O=deepcopy(original), D=deepcopy(diagnostic), unavailable_reasons=reasons,
            delta_D_minus_O_ns=delta,
            signed_relative_delta=None if signed is None else _display(signed),
            absolute_relative_delta=None if ratio is None else _display(ratio),
            absolute_relative_exact=None if ratio is None else dict(
                numerator=ratio.numerator, denominator=ratio.denominator)))

    available = [value for value in ratios if value is not None]
    failures = []
    if any(row['unavailable_reason'] is not None for row in warm):
        failures.append('warmup_unavailable')
    if len(available) != len(ORDERS):
        failures.append('formal_pair_unavailable')
    median_ok = bool(available) and _median(available) <= MEDIAN_LIMIT
    maximum_ok = bool(available) and max(available) <= MAXIMUM_LIMIT
    if not median_ok:
        failures.append('median_absolute_relative_budget')
    if not maximum_ok:
        failures.append('maximum_absolute_relative_budget')
    return dict(status='perturbation_budget_passed' if not failures else 'perturbation_not_accepted',
        failure_reasons=failures, warmups=warm, pairs=pairs,
        signed_delta_ns=distribution(deltas), signed_relative_delta=distribution(signed_ratios),
        absolute_relative_delta=distribution(ratios),
        by_order={order: dict(
            signed_delta_ns=distribution([deltas[i] for i, item in enumerate(ORDERS) if item == order]),
            absolute_relative_delta=distribution([ratios[i] for i, item in enumerate(ORDERS) if item == order]))
            for order in ('OD', 'DO')},
        gate=dict(expected_pairs=8, valid_pairs=len(available), missing_pairs=8-len(available),
            median_limit=.02, maximum_limit=.05, median_passed=median_ok, maximum_passed=maximum_ok,
            all_pairs_required=True, all_warmups_required=True,
            gate_arithmetic='exact_fraction_of_integer_wall_ns',
            measurement_executed_by_this_function=False, evaluation='provided_records_only'))
