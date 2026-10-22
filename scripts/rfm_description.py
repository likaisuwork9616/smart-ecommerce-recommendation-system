"""Pure read-only RFM description for the frozen Stage 6 G0/G1 contract.

No file access, cutpoint estimation, customer scores, partitions or model fits.
The caller owns source-byte checks; this module checks typed rows, the complete
order/customer ledger and aggregate conservation before describing any values.
"""
from __future__ import annotations

from collections import Counter
import math

from scripts import freeze_rfm_dataset_spec as dataset_contract
from scripts import rfm_dataset_artifacts as artifacts
from scripts import rfm_evaluation_contract as method

AXES = ('recency_seconds', 'frequency_orders', 'monetary_product_cents')
PERCENTAGES = (0, 1, 5, 25, 50, 75, 95, 99, 100)
NULL_FIELDS = ('last_window_purchase_at', 'recency_seconds', 'recency_days',
               'frequency_orders', 'monetary_product_cents')
MONEY_KEYS = (
    'eligible_window_product_known_orders', 'eligible_window_product_unknown_orders',
    'eligible_window_product_cents_on_known_orders', 'published_customer_product_cents',
    'known_product_cents_masked_customer_subsets', 'known_product_orders_in_masked_customer_subsets',
    'unknown_product_orders_in_masked_customer_subsets', 'masked_customers', 'unmasked_customers',
    'inactive_complete_zero_customers', 'known_product_cents_equal_published_plus_masked_known',
    'unknown_product_amounts_are_zero_filled',
)


def _finite(value):
    if type(value) is not float or not math.isfinite(value):
        raise ValueError('Non-finite descriptive value')
    return value


def _quantiles(sorted_values):
    """Select exact observed values using the preregistered integer ranks."""
    n = len(sorted_values)
    if not n:
        return None
    return {str(p): sorted_values[0 if p == 0 else (n * p + 99) // 100 - 1]
            for p in PERCENTAGES}


def _raw_statistics(values):
    n = len(values)
    keys = ('null_count', 'distinct_count', 'min', 'max', 'sum', 'mean_numerator',
            'mean_denominator', 'arithmetic_mean', 'empirical_quantiles', 'IQR',
            'Bowley_skewness', 'Bowley_numerator', 'Bowley_denominator')
    if not n:
        return {'n': 0, **dict.fromkeys(keys), 'null_reason': 'empty_reference'}
    sorted_values = sorted(values)
    quantiles = _quantiles(sorted_values)
    total = sum(values)
    iqr = quantiles['75'] - quantiles['25']
    bowley_numerator = quantiles['75'] + quantiles['25'] - 2 * quantiles['50']
    return {
        'n': n, 'null_count': 0, 'distinct_count': len(set(values)),
        'min': sorted_values[0], 'max': sorted_values[-1], 'sum': total,
        'mean_numerator': total, 'mean_denominator': n,
        'arithmetic_mean': _finite(total / n), 'empirical_quantiles': quantiles,
        'IQR': iqr, 'Bowley_skewness': _finite(bowley_numerator / iqr) if iqr else None,
        'Bowley_numerator': bowley_numerator if iqr else None,
        'Bowley_denominator': iqr if iqr else None,
        'null_reason': 'IQR_zero_Bowley_undefined' if not iqr else None,
    }


def _outlier_summary(values, statistics):
    result = {'n': len(values), 'flags_only': True, 'removed_n': 0,
              'lower_fence_numerator': None, 'upper_fence_numerator': None,
              'fence_denominator': None, 'lower_flag_count': None,
              'upper_flag_count': None, 'flag_count': None, 'null_reason': None}
    if not values:
        result['null_reason'] = 'empty_reference'
        return result
    iqr = statistics['IQR']
    if iqr == 0:
        result['null_reason'] = 'IQR_zero_fences_degenerate'
        return result
    q = statistics['empirical_quantiles']
    lower, upper = 2 * q['25'] - 3 * iqr, 2 * q['75'] + 3 * iqr
    lower_count = sum(2 * value < lower for value in values)
    upper_count = sum(2 * value > upper for value in values)
    result.update(lower_fence_numerator=lower, upper_fence_numerator=upper,
                  fence_denominator=2, lower_flag_count=lower_count,
                  upper_flag_count=upper_count, flag_count=lower_count + upper_count)
    return result


def _log_statistics(values, axis):
    keys = ('null_count', 'min', 'max', 'arithmetic_mean', 'empirical_quantiles')
    if not values:
        return {'n': 0, **dict.fromkeys(keys), 'null_reason': 'empty_reference'}
    divisor = 86400 if axis == 'recency_seconds' else 100 if axis == 'monetary_product_cents' else 1
    transformed = sorted(_finite(math.log1p(value / divisor)) for value in values)
    return {
        'n': len(values), 'null_count': 0, 'min': transformed[0], 'max': transformed[-1],
        'arithmetic_mean': _finite(math.fsum(transformed) / len(values)),
        'empirical_quantiles': _quantiles(transformed), 'null_reason': None,
    }


def _ratio(numerator, denominator, empty_reason='empty_reference'):
    return {'numerator': numerator if denominator else None, 'denominator': denominator,
            'value': _finite(numerator / denominator) if denominator else None,
            'null_reason': None if denominator else empty_reason}


def _validate_and_order(dataset, evaluation_spec, expected_customer_ids):
    if (type(evaluation_spec) is not dict or not artifacts._same(evaluation_spec.get('format_version'), 1)
            or not artifacts._same(evaluation_spec.get('policy'), method.policy())
            or not artifacts._same(evaluation_spec.get('planned_outputs'), method.planned_outputs())):
        raise ValueError('Frozen evaluation policy or planned outputs differ')
    if type(dataset) is not dict or set(dataset) != {'customers', 'orders', 'summary'}:
        raise ValueError('Exactly the customer/order/summary dataset is required')
    if type(dataset['customers']) is not list or type(dataset['orders']) is not list or type(dataset['summary']) is not dict:
        raise ValueError('Dataset tables or summary have incorrect types')
    schemas = dataset_contract.schemas()
    # Strict schema/type validation without file access. The original serializer
    # only writes an in-memory StringIO; no CSV file or input row is changed.
    artifacts._csv_bytes(dataset['customers'], schemas['customers.csv'])
    artifacts._csv_bytes(dataset['orders'], schemas['order_decisions.csv'])
    ordered = {
        'customers': sorted(dataset['customers'], key=lambda row: row['customer_unique_id']),
        'orders': sorted(dataset['orders'], key=lambda row: row['order_id']),
        'summary': dataset['summary'],
    }
    if expected_customer_ids is not None:
        if type(expected_customer_ids) not in (list, tuple, set, frozenset):
            raise ValueError('Expected customer IDs must be a finite explicit collection')
        expected = list(expected_customer_ids)
        if (any(type(value) is not str or not value or value != value.strip() for value in expected)
                or len(expected) != len(set(expected))
                or sorted(expected) != [row['customer_unique_id'] for row in ordered['customers']]):
            raise ValueError('Customer IDs differ from the complete expected roster')
    artifacts.validate_semantics(ordered, {
        'policy': dataset_contract.policy(), 'planned_schemas': schemas})
    states = ordered['summary']['customer_states']
    expected_states = dataset_contract.policy()['activity_states']
    if (type(states) is not dict or set(states) != set(expected_states)
            or any(type(value) is not int or value < 0 for value in states.values())):
        raise ValueError('Customer state summary schema or types differ')
    for row in ordered['customers']:
        if row['frequency_orders']:
            if not 0 < row['recency_seconds'] <= 365 * 86400:
                raise ValueError('Active recency is outside the frozen domain')
        if row['activity_state'] == 'active_complete':
            if (row['frequency_orders'] < 1 or row['monetary_product_cents'] is None
                    or row['monetary_product_cents'] < 0):
                raise ValueError('Complete active RFM has invalid domain values')
    # Necessary subset of the original all-source checked-int64 support guard.
    known_money = sum(row[key] for row in ordered['orders']
                      for key in ('product_cents', 'freight_cents', 'payment_cents')
                      if row[key] is not None)
    if known_money > artifacts.MAX:
        raise ValueError('Known pre-T monetary subset violates the frozen int64 support bound')
    return ordered


def describe_dataset(dataset, evaluation_spec, *, expected_customer_ids=None):
    """Validate complete same-ID routing and return aggregate G0/G1 summaries.

    The optional independently supplied roster detects a consistently removed
    customer even if the caller also replaced the order ledger and summary.
    A production caller must additionally enforce the frozen source/bundle bytes.
    This module never opens files and never returns IDs or individual RFM rows.
    """
    data = _validate_and_order(dataset, evaluation_spec, expected_customer_ids)
    customers = data['customers']
    states = dataset_contract.policy()['activity_states']
    state_counts = Counter({state: 0 for state in states})
    state_counts.update(row['activity_state'] for row in customers)
    complete = [row for row in customers if row['activity_state'] == 'active_complete']
    values = {axis: [row[axis] for row in complete] for axis in AXES}
    raw = {axis: _raw_statistics(values[axis]) for axis in AXES}
    outliers = {axis: _outlier_summary(values[axis], raw[axis]) for axis in AXES}
    log_views = {axis: _log_statistics(values[axis], axis) for axis in AXES}
    null_counts = {
        state: {key: sum(row[key] is None for row in customers if row['activity_state'] == state)
                for key in NULL_FIELDS} for state in states}
    n = len(complete)
    m_values = values['monetary_product_cents']
    q99 = raw['monetary_product_cents']['empirical_quantiles']['99'] if n else None
    tail = [value for value in m_values if value >= q99] if n else []
    m_total = sum(m_values)
    money = {key: data['summary']['customer_money_conservation'][key] for key in MONEY_KEYS}
    if money['published_customer_product_cents'] != m_total:
        # Clean inactive rows contribute exactly zero; no withheld partial money
        # may leak into the sole complete-active numeric cohort.
        raise ValueError('Complete-active M sum differs from unmasked customer money')
    return {
        'format_version': 1,
        'source_version': {'evaluation_format_version': evaluation_spec['format_version'],
                           'input_namespace': method.policy()['input']['namespace'],
                           'S_inclusive': str(dataset_contract.START),
                           'T_exclusive': str(dataset_contract.CUTOFF)},
        'routing_counts': {
            'population_n': len(customers), 'by_state': dict(state_counts),
            'complete_active_n': n, 'clean_inactive_n': state_counts['inactive_complete'],
            'withheld_n': sum(state_counts[s] for s in states if s not in ('active_complete', 'inactive_complete')),
            'null_counts_by_state': null_counts,
            'same_ID_exhaustive_disjoint': True,
            'independent_roster_checked': expected_customer_ids is not None,
        },
        'eligible_n': n,
        'axes_and_units': {'recency_seconds': 'elapsed_seconds_display_days_div86400',
                           'frequency_orders': 'distinct_window_eligible_order_count',
                           'monetary_product_cents': 'nominal_BRL_product_gross_integer_cents'},
        'statistics_and_null_reasons': {'raw': raw, 'log1p_views': log_views},
        'shape_and_tail_diagnostics': {
            'F_equals_1': _ratio(sum(value == 1 for value in values['frequency_orders']), n),
            'M_equals_0': _ratio(sum(value == 0 for value in m_values), n),
            'M_ge_Q99': {'threshold_cents': q99, 'includes_all_threshold_ties': True,
                          'count': len(tail) if n else None,
                          'fraction': _ratio(len(tail), n),
                          'total_M_cents': m_total if n else None,
                          'tail_M_cents': sum(tail) if n else None,
                          'share_of_total_M': _ratio(sum(tail), m_total, 'zero_total_M' if n else 'empty_reference')},
        },
        'outlier_flags_not_removed': outliers,
        'population_and_money_conservation': {
            'population_n': len(customers), 'state_sum': sum(state_counts.values()),
            'frequency_sum_all_customers': sum(row['frequency_orders'] for row in customers),
            'window_event_eligible_orders': data['summary']['window']['event_eligible_orders'],
            'complete_active_product_cents': m_total, 'money': money,
        },
        'gate_status': {'G0': 'passed', 'G1': 'ready_for_aggregate_review' if n else 'not_evaluable_empty_reference',
                        'G2': 'not_executed', 'G3': 'not_executed', 'temporal': 'pending_data'},
        'execution': {'source_RFM_modified': False, 'cutpoints_estimated': False,
                      'scores_assigned': False, 'segments_assigned': False,
                      'resampling_executed': False, 'model_fits': 0, 'dashboard': False},
        'limitations': [
            'Retrospective final snapshot; no original ingestion/revision or complete lifetime proof.',
            'M is product gross snapshot, not refunds, settlement, net revenue or future customer value.',
            'Only complete active customers enter numeric summaries; withheld R/F remain partial subsets.',
            'Descriptive output is not approval for cutpoints, customer partitions, models or business use.',
            'One snapshot cannot establish temporal stability.',
        ],
    }
