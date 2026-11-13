"""Compare recorded logical workload fields using pure in-memory arithmetic.

The schema below is copied from sql_v4.py's work.update declarations. No SQL,
runner, raw-data reader, model or experiment code is imported by this module.
"""
from statistics import median


COUNT_FIELDS = (
    'history_rows_inserted',
    'sql_overlap_groups_returned',
    'sql_overlap_membership_matches',
    'neighbor_pool_rows_hashed',
    'sql_selected_rows_inserted',
    'sql_vote_membership_rows_returned',
    'fraction_vote_additions',
    'fallback_catalog_rows_examined',
    'catalog_snapshot_rows_prepared',
    'causal_catalog_candidates',
    'positive_causal_candidates',
    'exact_vote_additions',
    'integer_vote_additions',
    'vote_scale_bits',
    'distinct_neighbor_similarities',
)
FLAG_FIELD = 'fraction_fallback'
SCHEMA = frozenset((*COUNT_FIELDS, FLAG_FIELD))
EXPECTED_COUNT = 48


def _stats(values):
    ordered = sorted(values)
    count = len(ordered)
    return dict(count=count, min=ordered[0], median=median(ordered),
        p90=ordered[(9 * count + 9) // 10 - 1], max=ordered[-1],
        sum=sum(ordered), unique_count=len(set(ordered)))


def _flag_stats(values):
    true_count = sum(value is True for value in values)
    return dict(count=len(values), true_count=true_count, false_count=len(values) - true_count)


def summarize_workloads(workloads, targets=(32, 38)):
    """Return summaries for 14 logical counts, one bit width and one Boolean.

    Ordinals are one-based positions in the supplied fixed48 order. Exactly two
    distinct target ordinals are required, leaving 46 comparison records.
    Descending ranks include all 48 records, with tied ranks represented by the
    first and last positions. ``vs_other46`` counts other-record values lower
    than, equal to or higher than the target value; its denominator is always 46.
    Ratios use the named median, returning None for a zero denominator.

    ``vote_scale_bits`` is a bit width, with zero used as a fallback sentinel.
    If any fallback flag is true, that field retains raw descriptive summaries
    but disables target ranks, size comparisons and median ratios.

    The result contains only the target ordinal/value pairs and aggregated
    statistics. Values are never summed across different workload fields.
    """
    if (type(targets) not in (tuple, list) or len(targets) != 2
            or any(type(value) is not int or not 1 <= value <= EXPECTED_COUNT for value in targets)
            or len(set(targets)) != 2):
        raise ValueError('Exactly two distinct integer target ordinals in 1..48 are required')
    targets = tuple(targets)
    try:
        workloads = list(workloads)
    except TypeError as error:
        raise ValueError('Exactly 48 workload dictionaries are required') from error
    if len(workloads) != EXPECTED_COUNT:
        raise ValueError('Exactly 48 workload dictionaries are required')
    for row in workloads:
        if type(row) is not dict or set(row) != SCHEMA:
            raise ValueError('Exact original 15-count and one-Boolean workload schema required')
        if any(type(row[name]) is not int or row[name] < 0 for name in COUNT_FIELDS):
            raise ValueError('Workload counters must be nonnegative integers, excluding Boolean values')
        if type(row[FLAG_FIELD]) is not bool:
            raise ValueError('fraction_fallback must be a Boolean value')
    other_indices = [index for index in range(EXPECTED_COUNT) if index + 1 not in targets]
    flags = [row[FLAG_FIELD] for row in workloads]
    has_fallback = any(flags)
    metrics = {}
    for name in COUNT_FIELDS:
        values = [row[name] for row in workloads]
        others = [values[index] for index in other_indices]
        all_stats, other_stats = _stats(values), _stats(others)
        bit_width = name == 'vote_scale_bits'
        unavailable = ('fraction_fallback is true in the fixed48 set; zero bit-width is a fallback sentinel, '
                       'so target ordering and median ratios are not interpreted as workload') if bit_width and has_fallback else None
        target_stats = {}
        for ordinal in targets:
            value = values[ordinal - 1]
            greater = sum(current > value for current in values)
            equal = sum(current == value for current in values)
            target_stats[str(ordinal)] = dict(ordinal=ordinal, value=value,
                rank_first=None if unavailable else 1 + greater, rank_last=None if unavailable else greater + equal,
                vs_other46=None if unavailable else dict(denominator=len(others), lower=sum(current < value for current in others),
                    equal=sum(current == value for current in others), higher=sum(current > value for current in others)),
                ratio_to_all_median=value / all_stats['median'] if all_stats['median'] and not unavailable else None,
                ratio_to_other_median=value / other_stats['median'] if other_stats['median'] and not unavailable else None,
                comparison_unavailable_reason=unavailable)
        metrics[name] = dict(quantity_kind='bit_width' if bit_width else 'logical_count',
            all48=all_stats, excluding_targets46=other_stats, targets=target_stats)
        if bit_width:
            metrics[name]['includes_fallback_sentinel'] = has_fallback
    return dict(count=EXPECTED_COUNT, target_ordinals=list(targets), other_count=len(other_indices),
        percentile_method='nearest_rank: one-based ceil(0.9*n), no interpolation',
        rank_method='Descending all48 ties: rank_first=1+strictly_greater; rank_last=strictly_greater+equal',
        comparison_direction='vs_other46 compares each other value with the target value; denominator excludes both targets',
        metrics=metrics,
        fraction_fallback=dict(all48=_flag_stats(flags),
            excluding_targets46=_flag_stats([flags[index] for index in other_indices]),
            targets={str(ordinal): flags[ordinal - 1] for ordinal in targets}),
        interpretation='Each logical count or bit-width field is summarized independently. No heterogeneous total workload, '
                       'physical I/O, elapsed-time cause or new execution is inferred.')
