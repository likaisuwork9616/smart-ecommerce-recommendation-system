"""Private roster/aggregate persistence for a future read-only description run.

No core/statistics function is imported or called. Readback proves exact typed
persistence, not the statistical truth of an arbitrary supplied median or log
value. The guarded runner's one frozen core call and synthetic end-to-end
oracles provide that evidence; this module separately checks roster identity,
routing and known amount conservation against the loaded accepted ledger.
"""
from __future__ import annotations

from collections import Counter
import math
from pathlib import Path, PurePosixPath
import re
import uuid

from scripts import rfm_dataset_artifacts as typed
from scripts import freeze_rfm_dataset_spec as contract
from scripts import rfm_evaluation_contract as method

FILES = ('description.json', 'customer_roster.csv', 'order_roster.csv', 'manifest.json')
CUSTOMER_SCHEMA = [['customer_unique_id', 'nonempty_unique_string'],
                   ['activity_state', 'enum'], ['eligible_for_numeric_description', 'bool']]
ORDER_SCHEMA = [['order_id', 'nonempty_unique_string'], ['customer_unique_id', 'nonempty_string'],
                ['history_event_eligible', 'bool'], ['window_event_eligible', 'bool'],
                ['window_quarantine', 'bool']]
AXES = ('recency_seconds', 'frequency_orders', 'monetary_product_cents')
NULL_FIELDS = ('last_window_purchase_at', 'recency_seconds', 'recency_days',
               'frequency_orders', 'monetary_product_cents')
PERCENTAGES = ('0', '1', '5', '25', '50', '75', '95', '99', '100')
DESCRIPTION_KEYS = {
    'format_version', 'source_version', 'routing_counts', 'eligible_n', 'axes_and_units',
    'statistics_and_null_reasons', 'shape_and_tail_diagnostics', 'outlier_flags_not_removed',
    'population_and_money_conservation', 'gate_status', 'execution', 'limitations',
}
MONEY_KEYS = (
    'eligible_window_product_known_orders', 'eligible_window_product_unknown_orders',
    'eligible_window_product_cents_on_known_orders', 'published_customer_product_cents',
    'known_product_cents_masked_customer_subsets', 'known_product_orders_in_masked_customer_subsets',
    'unknown_product_orders_in_masked_customer_subsets', 'masked_customers', 'unmasked_customers',
    'inactive_complete_zero_customers', 'known_product_cents_equal_published_plus_masked_known',
    'unknown_product_amounts_are_zero_filled',
)
UNITS = {'recency_seconds': 'elapsed_seconds_display_days_div86400',
         'frequency_orders': 'distinct_window_eligible_order_count',
         'monetary_product_cents': 'nominal_BRL_product_gross_integer_cents'}
LIMITATIONS = [
    'Retrospective final snapshot; no original ingestion/revision or complete lifetime proof.',
    'M is product gross snapshot, not refunds, settlement, net revenue or future customer value.',
    'Only complete active customers enter numeric summaries; withheld R/F remain partial subsets.',
    'Descriptive output is not approval for cutpoints, customer partitions, models or business use.',
    'One snapshot cannot establish temporal stability.',
]


def _require(value, message):
    if value is not True:
        raise ValueError(message)


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys), 'Aggregate or metadata schema differs')


def _integer(value, *, nullable=False, signed=False):
    _require((nullable and value is None) or (type(value) is int and (signed or value >= 0)),
             'Expected an exact aggregate integer')


def _float(value, *, nullable=False):
    _require((nullable and value is None) or (type(value) is float and math.isfinite(value)),
             'Expected a finite aggregate binary64')


def _ratio(value):
    _keys(value, ('numerator', 'denominator', 'value', 'null_reason'))
    _integer(value['numerator'], nullable=True)
    _integer(value['denominator'])
    _float(value['value'], nullable=True)
    _require(value['null_reason'] in (None, 'empty_reference', 'zero_total_M'), 'Unexpected ratio reason')
    if value['denominator']:
        _require(value['numerator'] is not None and value['null_reason'] is None
                 and typed._same(value['value'], value['numerator'] / value['denominator']),
                 'Aggregate ratio differs')
    else:
        _require(value['numerator'] is None and value['value'] is None
                 and value['null_reason'] is not None, 'Undefined ratio must remain null')


def _descriptor(value):
    _keys(value, ('path', 'bytes', 'sha256'))
    path = value['path']
    _require(type(path) is str and bool(path) and '\\' not in path
             and not PurePosixPath(path).is_absolute() and ':' not in path
             and all(part not in ('', '.', '..') for part in path.split('/'))
             and not path.startswith(('.runtime/', 'models/', '.venv/'))
             and re.search(r'\b[0-9a-f]{32}\b', path) is None,
             'Provenance must contain public project paths only')
    _integer(value['bytes'])
    _require(type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None,
             'Expected a public source SHA256')


def _provenance(value):
    _keys(value, ('execution_specification', 'source_bindings'))
    _descriptor(value['execution_specification'])
    _require(value['execution_specification']['path'].startswith('reports/stage6/'),
             'Execution specification must be a public Stage 6 report')
    sources = value['source_bindings']
    _require(type(sources) is list and len(sources) == 41, 'Complete forty-one source bindings required')
    for source in sources:
        _descriptor(source)
    _require(len({s['path'] for s in sources}) == len(sources), 'Duplicate public source path')


def _description_shape(description):
    """Exact nested whitelist; numeric payloads cannot smuggle IDs or digests."""
    _keys(description, DESCRIPTION_KEYS)
    _require(typed._same(description['format_version'], 1), 'Description format differs')
    _require(typed._same(description['source_version'], {
        'evaluation_format_version': 1, 'input_namespace': method.policy()['input']['namespace'],
        'S_inclusive': str(contract.START), 'T_exclusive': str(contract.CUTOFF)}),
        'Description source version differs')
    states = contract.policy()['activity_states']
    route = description['routing_counts']
    _keys(route, ('population_n', 'by_state', 'complete_active_n', 'clean_inactive_n',
                  'withheld_n', 'null_counts_by_state', 'same_ID_exhaustive_disjoint',
                  'independent_roster_checked'))
    for key in ('population_n', 'complete_active_n', 'clean_inactive_n', 'withheld_n'):
        _integer(route[key])
    _keys(route['by_state'], states)
    _keys(route['null_counts_by_state'], states)
    for state in states:
        _integer(route['by_state'][state])
        _keys(route['null_counts_by_state'][state], NULL_FIELDS)
        for count in route['null_counts_by_state'][state].values():
            _integer(count)
    _require(route['same_ID_exhaustive_disjoint'] is True and route['independent_roster_checked'] is True,
             'Independent complete same-ID roster verification is required')
    _integer(description['eligible_n'])
    _require(typed._same(description['axes_and_units'], UNITS), 'RFM units differ')
    stats = description['statistics_and_null_reasons']
    _keys(stats, ('raw', 'log1p_views'))
    for scale in stats.values():
        _keys(scale, AXES)
    raw_fields = ('n', 'null_count', 'distinct_count', 'min', 'max', 'sum', 'mean_numerator',
                  'mean_denominator', 'arithmetic_mean', 'empirical_quantiles', 'IQR',
                  'Bowley_skewness', 'Bowley_numerator', 'Bowley_denominator', 'null_reason')
    for axis in AXES:
        raw, log = stats['raw'][axis], stats['log1p_views'][axis]
        _keys(raw, raw_fields)
        _integer(raw['n'])
        for key in raw_fields:
            if key in ('n', 'null_reason', 'empirical_quantiles', 'arithmetic_mean', 'Bowley_skewness'):
                continue
            _integer(raw[key], nullable=True, signed=key == 'Bowley_numerator')
        _float(raw['arithmetic_mean'], nullable=True)
        _float(raw['Bowley_skewness'], nullable=True)
        _require(raw['null_reason'] in (None, 'empty_reference', 'IQR_zero_Bowley_undefined'),
                 'Unexpected raw null reason')
        if raw['empirical_quantiles'] is not None:
            _keys(raw['empirical_quantiles'], PERCENTAGES)
            for value in raw['empirical_quantiles'].values():
                _integer(value)
        _keys(log, ('n', 'null_count', 'min', 'max', 'arithmetic_mean', 'empirical_quantiles', 'null_reason'))
        _integer(log['n'])
        _integer(log['null_count'], nullable=True)
        for key in ('min', 'max', 'arithmetic_mean'):
            _float(log[key], nullable=True)
        _require(log['null_reason'] in (None, 'empty_reference'), 'Unexpected log null reason')
        if log['empirical_quantiles'] is not None:
            _keys(log['empirical_quantiles'], PERCENTAGES)
            for value in log['empirical_quantiles'].values():
                _float(value)
    shape = description['shape_and_tail_diagnostics']
    _keys(shape, ('F_equals_1', 'M_equals_0', 'M_ge_Q99'))
    _ratio(shape['F_equals_1'])
    _ratio(shape['M_equals_0'])
    tail = shape['M_ge_Q99']
    _keys(tail, ('threshold_cents', 'includes_all_threshold_ties', 'count', 'fraction',
                 'total_M_cents', 'tail_M_cents', 'share_of_total_M'))
    _require(tail['includes_all_threshold_ties'] is True, 'Tail tie policy differs')
    for key in ('threshold_cents', 'count', 'total_M_cents', 'tail_M_cents'):
        _integer(tail[key], nullable=True)
    _ratio(tail['fraction'])
    _ratio(tail['share_of_total_M'])
    outliers = description['outlier_flags_not_removed']
    _keys(outliers, AXES)
    outlier_fields = ('n', 'flags_only', 'removed_n', 'lower_fence_numerator', 'upper_fence_numerator',
                      'fence_denominator', 'lower_flag_count', 'upper_flag_count', 'flag_count', 'null_reason')
    for value in outliers.values():
        _keys(value, outlier_fields)
        _integer(value['n'])
        _require(value['flags_only'] is True and typed._same(value['removed_n'], 0), 'Outlier policy differs')
        for key in outlier_fields:
            if key not in ('n', 'flags_only', 'removed_n', 'null_reason'):
                _integer(value[key], nullable=True, signed='numerator' in key)
        _require(value['null_reason'] in (None, 'empty_reference', 'IQR_zero_fences_degenerate'),
                 'Unexpected fence null reason')
    conservation = description['population_and_money_conservation']
    _keys(conservation, ('population_n', 'state_sum', 'frequency_sum_all_customers',
                         'window_event_eligible_orders', 'complete_active_product_cents', 'money'))
    for key in conservation:
        if key != 'money':
            _integer(conservation[key])
    _keys(conservation['money'], MONEY_KEYS)
    for key, value in conservation['money'].items():
        if key not in ('known_product_cents_equal_published_plus_masked_known', 'unknown_product_amounts_are_zero_filled'):
            _integer(value)
    _require(conservation['money']['known_product_cents_equal_published_plus_masked_known'] is True
             and conservation['money']['unknown_product_amounts_are_zero_filled'] is False,
             'Money masking policy differs')
    n = description['eligible_n']
    _require(typed._same(description['gate_status'], {
        'G0': 'passed', 'G1': 'ready_for_aggregate_review' if n else 'not_evaluable_empty_reference',
        'G2': 'not_executed', 'G3': 'not_executed', 'temporal': 'pending_data'}), 'Gate status differs')
    _require(typed._same(description['execution'], {
        'source_RFM_modified': False, 'cutpoints_estimated': False, 'scores_assigned': False,
        'segments_assigned': False, 'resampling_executed': False, 'model_fits': 0, 'dashboard': False}),
        'Description execution scope differs')
    _require(typed._same(description['limitations'], LIMITATIONS), 'Description limitations differ')


def _rosters(data):
    _require(type(data) is dict and 'dataset' in data, 'Loaded data are required')
    dataset = data['dataset']
    _require(type(dataset) is dict and set(dataset) == {'customers', 'orders', 'summary'}, 'Dataset shape differs')
    schemas = contract.schemas()
    typed._csv_bytes(dataset['customers'], schemas['customers.csv'])
    typed._csv_bytes(dataset['orders'], schemas['order_decisions.csv'])
    typed.validate_semantics(dataset, {'policy': contract.policy(), 'planned_schemas': schemas})
    customers, orders = dataset['customers'], dataset['orders']
    for key, actual in (('customer_ids', [r['customer_unique_id'] for r in customers]),
                        ('order_ids', [r['order_id'] for r in orders]),
                        ('window_order_ids', [r['order_id'] for r in orders if r['window_event_eligible']])):
        expected = data.get(key)
        _require(type(expected) is list and all(type(v) is str and bool(v) for v in expected)
                 and expected == sorted(set(expected)) and expected == actual,
                 'Independent complete roster differs')
    known = sum(r[k] for r in orders for k in ('product_cents', 'freight_cents', 'payment_cents') if r[k] is not None)
    _require(known <= typed.MAX, 'Accepted monetary subset violates int64 support')
    customer_rows = [{'customer_unique_id': r['customer_unique_id'], 'activity_state': r['activity_state'],
                      'eligible_for_numeric_description': r['activity_state'] == 'active_complete'} for r in customers]
    order_rows = [{name: r[name] for name, _ in ORDER_SCHEMA} for r in orders]
    return customer_rows, order_rows


def _validate_description(data, description):
    _description_shape(description)
    customer_roster, order_roster = _rosters(data)
    customers = data['dataset']['customers']
    states = contract.policy()['activity_states']
    counts = dict.fromkeys(states, 0)
    counts.update(Counter(r['activity_state'] for r in customers))
    complete = [r for r in customers if r['activity_state'] == 'active_complete']
    n = len(complete)
    expected_route = {
        'population_n': len(customers), 'by_state': counts, 'complete_active_n': n,
        'clean_inactive_n': counts['inactive_complete'],
        'withheld_n': sum(counts[s] for s in states if s not in ('active_complete', 'inactive_complete')),
        'null_counts_by_state': {s: {key: sum(r[key] is None for r in customers if r['activity_state'] == s)
                                   for key in NULL_FIELDS} for s in states},
        'same_ID_exhaustive_disjoint': True, 'independent_roster_checked': True,
    }
    _require(typed._same(description['routing_counts'], expected_route) and typed._same(description['eligible_n'], n),
             'Description routing differs from accepted customer roster')
    summary = data['dataset']['summary']
    total = sum(r['monetary_product_cents'] for r in complete)
    expected_money = {key: summary['customer_money_conservation'][key] for key in MONEY_KEYS}
    expected_conservation = {
        'population_n': len(customers), 'state_sum': sum(counts.values()),
        'frequency_sum_all_customers': sum(r['frequency_orders'] for r in customers),
        'window_event_eligible_orders': summary['window']['event_eligible_orders'],
        'complete_active_product_cents': total, 'money': expected_money,
    }
    _require(typed._same(description['population_and_money_conservation'], expected_conservation)
             and total == expected_money['published_customer_product_cents'],
             'Description monetary conservation differs')
    for axis in AXES:
        raw = description['statistics_and_null_reasons']['raw'][axis]
        log = description['statistics_and_null_reasons']['log1p_views'][axis]
        outlier = description['outlier_flags_not_removed'][axis]
        _require(raw['n'] == log['n'] == outlier['n'] == n, 'Description numeric denominator differs')
        if n:
            values = [r[axis] for r in complete]
            known_sum = sum(values)
            _require(raw['null_count'] == log['null_count'] == 0 and raw['distinct_count'] == len(set(values))
                     and raw['min'] == min(values) and raw['max'] == max(values)
                     and raw['sum'] == raw['mean_numerator'] == known_sum and raw['mean_denominator'] == n
                     and typed._same(raw['arithmetic_mean'], known_sum / n),
                     'Description known raw totals differ')
        else:
            _require(all(v is None for k, v in raw.items() if k not in ('n', 'null_reason'))
                     and raw['null_reason'] == 'empty_reference'
                     and all(v is None for k, v in log.items() if k not in ('n', 'null_reason'))
                     and log['null_reason'] == 'empty_reference', 'Empty description must stay null')
    return customer_roster, order_roster


def _scalar_count(value, wanted=None):
    if isinstance(value, dict):
        return sum(_scalar_count(v, wanted) for v in value.values())
    if isinstance(value, list):
        return sum(_scalar_count(v, wanted) for v in value)
    return int(wanted is None or type(value) is wanted)


def _acceptance(description, customers, orders):
    return {'all_values_read_back': True, 'same_ID_rosters': True, 'strict_types_and_nulls': True,
            'float64_bitwise': True, 'rows': {'customer_roster.csv': len(customers), 'order_roster.csv': len(orders)},
            'roster_cells_compared': len(customers) * 3 + len(orders) * 5,
            'aggregate_scalar_values_compared': _scalar_count(description),
            'binary64_values_compared': _scalar_count(description, float)}


def _schema():
    return {'customer_roster.csv': CUSTOMER_SCHEMA, 'order_roster.csv': ORDER_SCHEMA,
            'description.json': {'format_version': 1, 'top_level_keys': sorted(DESCRIPTION_KEYS)}}


def bundle_guard(output):
    output = Path(output)
    _require(output.is_dir() and {p.name for p in output.iterdir()} == set(FILES), 'Exactly four output files required')
    _require(not output.is_symlink() and not any((output / name).is_symlink() for name in FILES), 'Output symlinks rejected')
    return {name: typed._digest((output / name).read_bytes()) for name in FILES}


def _read_json(path):
    value = typed.base.read_json(path)
    _require(path.read_bytes() == typed.json_bytes(value), 'JSON must retain canonical bytes')
    return value


def read_outputs(output, provenance):
    _provenance(provenance)
    output = Path(output)
    before = bundle_guard(output)
    manifest = _read_json(output / 'manifest.json')
    _keys(manifest, ('format_version', 'provenance', 'schema', 'rows', 'private_bytes_sha',
                     'population_and_money_conservation', 'readback_acceptance'))
    _require(typed._same(manifest['format_version'], 1) and typed._same(manifest['provenance'], provenance)
             and typed._same(manifest['schema'], _schema()), 'Output version, provenance or schema differs')
    _require(typed._same(manifest['private_bytes_sha'], {name: before[name] for name in FILES[:3]}), 'Private bytes changed')
    description = _read_json(output / 'description.json')
    _description_shape(description)
    customers = typed._read_csv(output / 'customer_roster.csv', CUSTOMER_SCHEMA)
    orders = typed._read_csv(output / 'order_roster.csv', ORDER_SCHEMA)
    for rows, key in ((customers, 'customer_unique_id'), (orders, 'order_id')):
        ids = [r[key] for r in rows]
        _require(ids == sorted(set(ids)), 'Roster IDs are not unique canonical order')
    states = contract.policy()['activity_states']
    for row in customers:
        _require(row['activity_state'] in states and row['eligible_for_numeric_description'] is (row['activity_state'] == 'active_complete'),
                 'Customer roster eligibility differs')
    _require({r['customer_unique_id'] for r in orders if r['history_event_eligible']} == {r['customer_unique_id'] for r in customers},
             'History and customer roster universes differ')
    for row in orders:
        _require(not row['window_event_eligible'] or row['history_event_eligible'], 'Window roster eligibility differs')
        _require(not row['window_quarantine'] or not row['history_event_eligible'], 'Quarantine roster eligibility differs')
    receipt = _acceptance(description, customers, orders)
    _require(typed._same(manifest['rows'], receipt['rows'])
             and typed._same(manifest['readback_acceptance'], receipt)
             and typed._same(manifest['population_and_money_conservation'], description['population_and_money_conservation']),
             'Output manifest acceptance or conservation differs')
    _require(typed._same(before, bundle_guard(output)), 'Output bytes changed during readback')
    return {'description': description, 'customer_roster': customers, 'order_roster': orders, 'manifest': manifest}


def verify_outputs(output, data, description, provenance, expected_guard=None):
    _provenance(provenance)
    customers, orders = _validate_description(data, description)
    before = bundle_guard(output)
    _require(expected_guard is None or typed._same(before, expected_guard), 'Frozen private output guard differs')
    restored = read_outputs(output, provenance)
    _require(typed._same(restored['description'], description)
             and typed._same(restored['customer_roster'], customers)
             and typed._same(restored['order_roster'], orders), 'Complete typed output readback differs')
    _require(typed._same(before, bundle_guard(output)), 'Output bytes changed during verification')
    return _acceptance(description, customers, orders)


def public_report(description, provenance, acceptance):
    _description_shape(description)
    _provenance(provenance)
    _keys(acceptance, ('all_values_read_back', 'same_ID_rosters', 'strict_types_and_nulls',
                       'float64_bitwise', 'rows', 'roster_cells_compared',
                       'aggregate_scalar_values_compared', 'binary64_values_compared'))
    for key in ('all_values_read_back', 'same_ID_rosters', 'strict_types_and_nulls', 'float64_bitwise'):
        _require(acceptance[key] is True, 'Readback acceptance did not pass')
    _keys(acceptance['rows'], ('customer_roster.csv', 'order_roster.csv'))
    for value in acceptance['rows'].values():
        _integer(value)
    for key in ('roster_cells_compared', 'aggregate_scalar_values_compared', 'binary64_values_compared'):
        _integer(acceptance[key])
    n, orders = acceptance['rows']['customer_roster.csv'], acceptance['rows']['order_roster.csv']
    _require(n == description['routing_counts']['population_n']
             and orders >= n and orders >= description['population_and_money_conservation']['window_event_eligible_orders']
             and acceptance['roster_cells_compared'] == n * 3 + orders * 5
             and acceptance['aggregate_scalar_values_compared'] == _scalar_count(description)
             and acceptance['binary64_values_compared'] == _scalar_count(description, float),
             'Readback acceptance counts differ')
    return {'format_version': 1, 'specification': provenance['execution_specification'],
            'source_bindings': provenance['source_bindings'],
            'status': 'readonly_RFM_description_readback_accepted_no_cutpoints_or_groups',
            'description': description, 'readback_acceptance': acceptance}


def write_outputs(data, description, provenance, output):
    output = Path(output)
    _require(not output.exists() and not output.is_symlink(), 'Entire output namespace must be absent')
    _provenance(provenance)
    customers, orders = _validate_description(data, description)
    acceptance = _acceptance(description, customers, orders)
    payload = {'description.json': typed.json_bytes(description),
               'customer_roster.csv': typed._csv_bytes(customers, CUSTOMER_SCHEMA),
               'order_roster.csv': typed._csv_bytes(orders, ORDER_SCHEMA)}
    manifest = {'format_version': 1, 'provenance': provenance, 'schema': _schema(), 'rows': acceptance['rows'],
                'private_bytes_sha': {name: typed._digest(value) for name, value in payload.items()},
                'population_and_money_conservation': description['population_and_money_conservation'],
                'readback_acceptance': acceptance}
    payload['manifest.json'] = typed.json_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + '.staging-' + uuid.uuid4().hex)
    staging.mkdir()
    # Failed stages remain private; publication only occurs after full readback.
    for name, value in payload.items():
        with (staging / name).open('xb') as stream:
            stream.write(value)
    verify_outputs(staging, data, description, provenance)
    staging.rename(output)
    private_guard = bundle_guard(output)
    accepted = verify_outputs(output, data, description, provenance, expected_guard=private_guard)
    return {'public_report': public_report(description, provenance, accepted),
            'readback_acceptance': accepted, 'private_guard': private_guard}
