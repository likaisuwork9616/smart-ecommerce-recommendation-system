"""Pure numeric accounting for already recorded fixed48 query timers.

No model, query engine, worker, experiment runner or V49 implementation is
imported here. Positive signed differences mean the candidate took longer.
"""
from math import fsum, isclose, isfinite
from statistics import median


TOLERANCE_SECONDS = 1e-8
MILLISECOND = .001
RANK_STAGES = (
    'history_and_temp_setup', 'sql_positive_overlaps', 'neighbor_pool_sha',
    'exact_neighbor_selection', 'sql_selected_votes_and_accumulation',
    'top_ten_and_zero_fill', 'prediction_output',
)
QUERY_TIMERS = (
    'verification_seconds', 'rank_seconds', 'checkpoint_append_seconds',
    'append_without_commit_seconds', 'chunk_commit_seconds', 'seconds',
)


def _finite(value, name, *, nonnegative=False):
    try:
        valid = type(value) in (int, float) and isfinite(value) and (not nonnegative or value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite ' + ('nonnegative ' if nonnegative else '') + 'number required: ' + name)
    return value


def _sum(values, name):
    try:
        total = fsum(values)
    except OverflowError as error:
        raise ValueError('Finite aggregate required: ' + name) from error
    return _finite(total, name)


def signed_distribution(values):
    """Describe signed changes, with concentration relative to gross positives.

    ``negative_seconds`` keeps its negative sign. Threshold counts include both
    exact +/-1 ms boundaries in ``within_1ms``. Percentiles use the nearest rank
    rule (one-based ceil(p*n)), without interpolation. An empty sequence is not
    a distribution. With no positive values, concentration shares and coverage
    counts are None, while positive top-k sums remain zero.
    """
    values = list(values)
    if not values:
        raise ValueError('A nonempty sequence is required')
    for value in values:
        _finite(value, 'signed observation')
    ordered = sorted(values)
    positives = sorted((value for value in values if value > 0), reverse=True)
    negatives = [value for value in values if value < 0]
    positive = _sum(positives, 'gross positive')
    negative = _sum(negatives, 'gross negative')
    count = len(values)
    result = dict(count=count, net_seconds=_sum(values, 'net'), positive_seconds=positive,
        negative_seconds=negative, positive_count=len(positives), negative_count=len(negatives),
        zero_count=sum(value == 0 for value in values), median=median(ordered), min=ordered[0], max=ordered[-1],
        above_1ms=sum(value > MILLISECOND for value in values),
        below_minus_1ms=sum(value < -MILLISECOND for value in values),
        within_1ms=sum(-MILLISECOND <= value <= MILLISECOND for value in values),
        p10=ordered[(count + 9) // 10 - 1], p90=ordered[(9 * count + 9) // 10 - 1],
        percentile_method='nearest_rank: one-based ceil(p*n), no interpolation',
        concentration_denominator='positive_seconds (gross positive sum, never net_seconds)')
    for size in (1, 5, 10):
        total = _sum(positives[:size], 'positive top-' + str(size))
        result['positive_top' + str(size) + '_seconds'] = total
        result['positive_top' + str(size) + '_share'] = total / positive if positive > 0 else None
    for percent in (50, 80):
        target = positive * (percent / 100)
        result['n_for_' + str(percent) + 'pct_positive'] = (
            next(index for index in range(1, len(positives) + 1) if fsum(positives[:index]) >= target)
            if positive > 0 else None)
    return result


def query_parts(row):
    """Partition one saved query's charged time, without allocating tail commits.

    Original timers must be finite and nonnegative. Nested boundaries allow at
    most 1e-8 seconds of numerical discrepancy. Derived rank/verification
    remainders retain such tiny signed differences so the decomposition remains
    additive. ``signed_timer_bridge`` is envelope minus charged query time;
    it is kept outside ``parts_seconds`` and may likewise be slightly negative.
    """
    timers = {name: _finite(row[name], name, nonnegative=True) for name in QUERY_TIMERS}
    stages = row['rank_stages_seconds']
    if type(stages) is not dict or set(stages) != set(RANK_STAGES):
        raise ValueError('Exactly the original seven rank stages are required')
    parts = {name: _finite(stages[name], name, nonnegative=True) for name in RANK_STAGES}
    rank_total = _sum(parts.values(), 'rank stages')
    rank, verification = timers['rank_seconds'], timers['verification_seconds']
    append, commit = timers['append_without_commit_seconds'], timers['chunk_commit_seconds']
    append_parts = _sum((append, commit), 'append and in-query commit')
    if not isclose(timers['checkpoint_append_seconds'], append_parts,
                   rel_tol=0, abs_tol=TOLERANCE_SECONDS):
        raise ValueError('Checkpoint append does not equal append plus in-query commit')
    if rank_total > rank + TOLERANCE_SECONDS or rank > verification + TOLERANCE_SECONDS:
        raise ValueError('Rank stages exceed their enclosing rank or verification timer')
    enclosing = _sum((verification, timers['checkpoint_append_seconds']), 'verification and checkpoint append')
    if enclosing > timers['seconds'] + TOLERANCE_SECONDS:
        raise ValueError('Query charged intervals exceed the query envelope')
    charged = _sum((verification, append, commit), 'query charged')
    if charged > timers['seconds'] + TOLERANCE_SECONDS:
        raise ValueError('Query charged intervals exceed the query envelope')
    parts.update(rank_other=rank - rank_total, verification_other=verification - rank,
                 append=append, query_commit=commit)
    residual = abs(_sum(parts.values(), 'query parts') - charged)
    if residual > TOLERANCE_SECONDS:
        raise ValueError('Query parts do not conserve the charged timer')
    return dict(query_charged_seconds=charged, parts_seconds=parts,
        query_envelope_seconds=timers['seconds'], signed_timer_bridge=timers['seconds'] - charged,
        max_reconciliation_residual_seconds=residual)
