"""Strict private G2 candidate persistence and independent complete readback.

This module never imports or calls the G2 core.  The accepted source ledger is
used to independently verify reported integer cut ranks and every ID's bins,
ordinals, tuple, support counts and gate.  Output integrity is separate from
candidate eligibility: an ineligible candidate remains a complete diagnostic.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import uuid

from scripts import rfm_description as description
from scripts import rfm_description_outputs as prior

typed, contract = prior.typed, prior.contract
AXES = ('recency_seconds', 'frequency_orders', 'monetary_product_cents')
PREFIXES = ('r', 'f', 'm')
FILES = ('candidate.json', 'customer_roster.csv', 'order_roster.csv', 'manifest.json')
CUSTOMER_SCHEMA = [['customer_unique_id', 'nonempty_unique_string'], ['activity_state', 'enum'],
                   ['eligible_for_rule_candidate', 'bool'],
                   *[[p + '_numeric_bin', 'nullable_nonnegative_int64'] for p in PREFIXES],
                   *[[p + '_ordinal', 'nullable_nonnegative_int64'] for p in PREFIXES]]
ORDER_SCHEMA = [
    ['order_id', 'nonempty_unique_string'], ['customer_unique_id', 'nonempty_string'],
    ['purchase_at', 'timestamp_before_T'], ['approval_at', 'nullable_timestamp'],
    ['delivery_at', 'nullable_timestamp'], ['in_window', 'bool'],
    ['history_event_eligible', 'bool'], ['window_event_eligible', 'bool'],
    ['primary_exclusion_reason', 'enum'], ['window_quarantine', 'bool'],
    ['approval_missing_or_invalid', 'bool'],
]
LIMITATIONS = [
    'This pure function does not verify source-byte provenance or authorize real execution.',
    'Only complete active customers enter cutpoint estimation and assignment; legal M=0 is retained.',
    'Ordinals describe this marginal rule only; no total value score, business names or actions.',
    'Small joint cells are individually unsupported and are never automatically merged.',
    'G2 does not establish G3 method sensitivity, temporal stability or business applicability.',
]
AXIS_KEYS = ('n', 'percentages', 'quantile_ranks_1based', 'raw_cut_values', 'cut_values',
             'duplicate_cut_values_removed_n', 'maximum_cut_values_removed_n', 'effective_levels',
             'no_separation', 'bin_counts', 'failed_checks')
AGGREGATE_KEYS = ('format_version', 'candidate', 'reference_n', 'support_floor', 'routing_counts',
                  'axes_and_units', 'gate_status', 'execution', 'limitations', 'axes',
                  'neutral_joint_cell_counts', 'observed_joint_cells_n',
                  'joint_partition_degeneracy', 'failed_checks', 'reproducibility')
FAILURES = ('effective_levels_outside_2_to_5', 'empty_bin', 'insufficient_axis_bin_support')


def _require(value, message):
    if value is not True:
        raise ValueError(message)


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys), 'Candidate schema differs')


def _int(value, nullable=False):
    _require((nullable and value is None) or type(value) is int and value >= 0,
             'Exact nonnegative candidate integer required')


def _ints(value, length=None):
    _require(type(value) is list and (length is None or len(value) == length), 'Integer vector differs')
    for item in value:
        _int(item)


def _provenance(value):
    _keys(value, ('execution_specification', 'source_bindings'))
    prior._descriptor(value['execution_specification'])
    _require(value['execution_specification']['path'].startswith('reports/stage6/'),
             'Public Stage 6 execution specification required')
    sources = value['source_bindings']
    _require(type(sources) is list and bool(sources), 'Public source bindings required')
    for source in sources:
        prior._descriptor(source)
    _require(len({s['path'] for s in sources}) == len(sources), 'Duplicate source binding')


def _common(counts, n):
    return {
        'format_version': 1, 'candidate': 'frozen_marginal_P20_P40_P60_P80_rule',
        'reference_n': n, 'support_floor': max(100, (n + 199) // 200),
        'routing_counts': {'population_n': sum(counts.values()), 'by_state': counts,
                           'complete_active_n': n, 'excluded_from_candidate_n': sum(counts.values()) - n,
                           'same_ID_exhaustive_disjoint': True, 'independent_complete_roster_checked': True},
        'axes_and_units': {'recency_seconds': 'elapsed_seconds',
                           'frequency_orders': 'distinct_eligible_window_order_count',
                           'monetary_product_cents': 'nominal_BRL_product_gross_integer_cents'},
        'gate_status': {'G0': 'passed', 'G1': 'accepted_by_caller' if n else 'not_evaluable_empty_reference',
                        'G2': 'not_evaluable_empty_reference', 'G3': 'not_executed', 'temporal': 'pending_data'},
        'execution': {'source_RFM_modified': False, 'cutpoints_estimated': bool(n),
                      'ordinals_assigned_in_memory': bool(n), 'private_individual_files_written': False,
                      'clustering_models_executed': False, 'sensitivity_resampling_executed': False,
                      'model_fits': 0, 'dashboard': False},
        'limitations': LIMITATIONS,
    }


def _reproducibility(n):
    return ({'status': 'passed', 'variants': [
        {'name': name, 'reference_n': n, 'same_cutpoints_and_axis_summaries': True,
         'same_ID_assignments': True, 'same_value_ties_unsplit': True}
        for name in ('original', 'reversed', 'pcg64_seed42')], 'same_ID_assignments_100pct': True}
        if n else {'status': 'not_evaluated_empty_reference', 'variants': [],
                   'same_ID_assignments_100pct': None})


def _aggregate_shape(aggregate):
    """Whitelist every nested field before an aggregate may be public."""
    _keys(aggregate, AGGREGATE_KEYS)
    route = aggregate['routing_counts']
    _keys(route, ('population_n', 'by_state', 'complete_active_n', 'excluded_from_candidate_n',
                  'same_ID_exhaustive_disjoint', 'independent_complete_roster_checked'))
    _keys(route['by_state'], contract.policy()['activity_states'])
    for count in route['by_state'].values():
        _int(count)
    n = aggregate['reference_n']
    _int(n)
    _require(n == route['by_state']['active_complete'], 'Reference population differs')
    common = _common(route['by_state'], n)
    for key in common:
        if key != 'gate_status':
            _require(typed._same(aggregate[key], common[key]), 'Candidate fixed metadata or routing differs')
    _keys(aggregate['axes'], AXES)
    all_failures = []
    for axis in AXES:
        info = aggregate['axes'][axis]
        if not n:
            _require(info is None, 'Empty reference axes must remain null')
            continue
        _keys(info, AXIS_KEYS)
        for key in ('n', 'duplicate_cut_values_removed_n', 'maximum_cut_values_removed_n', 'effective_levels'):
            _int(info[key])
        _require(info['n'] == n and typed._same(info['percentages'], [20, 40, 60, 80])
                 and typed._same(info['quantile_ranks_1based'], [(n * p + 99) // 100 for p in (20, 40, 60, 80)]),
                 'Candidate quantile metadata differs')
        _ints(info['raw_cut_values'], 4)
        _ints(info['cut_values'])
        cuts, k = info['cut_values'], info['effective_levels']
        _require(cuts == sorted(set(cuts)) and info['raw_cut_values'] == sorted(info['raw_cut_values'])
                 and 1 <= k <= 5 and k == len(cuts) + 1
                 and type(info['no_separation']) is bool and info['no_separation'] is (k == 1),
                 'Candidate cuts or levels differ')
        _require(type(info['bin_counts']) is list and len(info['bin_counts']) == k, 'All candidate bins required')
        for b, row in enumerate(info['bin_counts'], 1):
            _keys(row, ('numeric_bin', 'ordinal', 'n', 'meets_support_floor', 'empty'))
            for key in ('numeric_bin', 'ordinal', 'n'):
                _int(row[key])
            _require(row['numeric_bin'] == b and row['ordinal'] == (k + 1 - b if axis == AXES[0] else b)
                     and type(row['meets_support_floor']) is bool
                     and row['meets_support_floor'] is (row['n'] >= aggregate['support_floor'])
                     and type(row['empty']) is bool and row['empty'] is (row['n'] == 0),
                     'Candidate bin support metadata differs')
        failures = ([FAILURES[0]] if k == 1 else [])
        if any(row['empty'] for row in info['bin_counts']):
            failures.append(FAILURES[1])
        if any(not row['meets_support_floor'] for row in info['bin_counts']):
            failures.append(FAILURES[2])
        _require(typed._same(info['failed_checks'], failures)
                 and sum(row['n'] for row in info['bin_counts']) == n, 'Axis gate metadata differs')
        all_failures.extend({'axis': axis, 'check': failure} for failure in failures)
    cells = aggregate['neutral_joint_cell_counts']
    _require(type(cells) is list, 'Joint cells must be a list')
    _require(bool(n) or not cells, 'Empty reference cannot contain joint cells')
    seen = []
    for cell in cells:
        _keys(cell, ('ordinals', 'n', 'support_flag'))
        _ints(cell['ordinals'], 3)
        _int(cell['n'])
        _require(cell['n'] > 0 and all(1 <= ordinal <= aggregate['axes'][axis]['effective_levels']
                 for axis, ordinal in zip(AXES, cell['ordinals']))
                 and cell['support_flag'] == ('insufficient_group_support' if cell['n'] < aggregate['support_floor'] else None),
                 'Joint cell support metadata differs')
        seen.append(tuple(cell['ordinals']))
    _int(aggregate['observed_joint_cells_n'])
    _require(seen == sorted(set(seen)) and len(cells) == aggregate['observed_joint_cells_n']
             and sum(cell['n'] for cell in cells) == n, 'Joint cell population differs')
    if n:
        common['gate_status']['G2'] = 'ineligible' if all_failures else 'passed'
        degenerate = len(cells) in (1, n)
        joint = {'degenerate': degenerate,
                 'reason': 'single_joint_group' if len(cells) == 1 else 'every_ID_singleton' if len(cells) == n else None,
                 'G3_not_evaluated': True}
    else:
        all_failures = [{'axis': None, 'check': 'empty_reference'}]
        joint = {'degenerate': None, 'reason': 'empty_reference'}
    _require(typed._same(aggregate['failed_checks'], all_failures)
             and typed._same(aggregate['gate_status'], common['gate_status'])
             and typed._same(aggregate['joint_partition_degeneracy'], joint)
             and typed._same(aggregate['reproducibility'], _reproducibility(n)),
             'Candidate eligibility, reproducibility or scope differs')


def _source_data(data):
    _require(type(data) is dict and data.get('g1_accepted') is True, 'Accepted G1 source evidence required')
    _require(type(data.get('g1_accepted')) is bool, 'G1 acceptance must be an exact bool')
    ordered = description._validate_and_order(data.get('dataset'), data.get('evaluation_spec'), data.get('customer_ids'))
    # The old strict G0 roster checker verifies all three independent ID lists.
    prior._rosters(data)
    return ordered


def _expected_result(data):
    """Independent rank/membership arithmetic; never call the candidate core."""
    dataset = _source_data(data)
    counts = {state: 0 for state in contract.policy()['activity_states']}
    counts.update(Counter(row['activity_state'] for row in dataset['customers']))
    rows = [row for row in dataset['customers'] if row['activity_state'] == 'active_complete']
    n = len(rows)
    aggregate = _common(counts, n)
    assignments = {row['customer_unique_id']: {'numeric_bins': {}, 'ordinals': {}, 'ordinal_tuple': []} for row in rows}
    axes = {}
    failures = []
    for axis in AXES:
        if not n:
            axes[axis] = None
            continue
        ordered = sorted(row[axis] for row in rows)
        ranks = [(n * p + 99) // 100 for p in (20, 40, 60, 80)]
        raw = [ordered[rank - 1] for rank in ranks]
        distinct = sorted(set(raw))
        cuts = [value for value in distinct if value < ordered[-1]]
        k = len(cuts) + 1
        bin_counts = Counter()
        for row in rows:
            b = 1 + sum(row[axis] > cut for cut in cuts)
            ordinal = k + 1 - b if axis == AXES[0] else b
            entry = assignments[row['customer_unique_id']]
            entry['numeric_bins'][axis], entry['ordinals'][axis] = b, ordinal
            entry['ordinal_tuple'].append(ordinal)
            bin_counts[b] += 1
        bins = [{'numeric_bin': b, 'ordinal': k + 1 - b if axis == AXES[0] else b,
                 'n': bin_counts[b], 'meets_support_floor': bin_counts[b] >= aggregate['support_floor'],
                 'empty': bin_counts[b] == 0} for b in range(1, k + 1)]
        failed = ([FAILURES[0]] if k == 1 else [])
        if any(row['empty'] for row in bins): failed.append(FAILURES[1])
        if any(not row['meets_support_floor'] for row in bins): failed.append(FAILURES[2])
        axes[axis] = {'n': n, 'percentages': [20, 40, 60, 80], 'quantile_ranks_1based': ranks,
                      'raw_cut_values': raw, 'cut_values': cuts,
                      'duplicate_cut_values_removed_n': 4 - len(distinct),
                      'maximum_cut_values_removed_n': len(distinct) - len(cuts),
                      'effective_levels': k, 'no_separation': k == 1,
                      'bin_counts': bins, 'failed_checks': failed}
        failures.extend({'axis': axis, 'check': check} for check in failed)
    cells = Counter(tuple(item['ordinal_tuple']) for item in assignments.values())
    aggregate.update(axes=axes, neutral_joint_cell_counts=[
        {'ordinals': list(cell), 'n': count,
         'support_flag': 'insufficient_group_support' if count < aggregate['support_floor'] else None}
        for cell, count in sorted(cells.items())], observed_joint_cells_n=len(cells),
        failed_checks=failures if n else [{'axis': None, 'check': 'empty_reference'}],
        reproducibility=_reproducibility(n),
        joint_partition_degeneracy=({'degenerate': len(cells) in (1, n),
            'reason': 'single_joint_group' if len(cells) == 1 else 'every_ID_singleton' if len(cells) == n else None,
            'G3_not_evaluated': True} if n else {'degenerate': None, 'reason': 'empty_reference'}))
    if n:
        aggregate['gate_status']['G2'] = 'ineligible' if failures else 'passed'
    return {'aggregate': aggregate, 'assignments_by_id': assignments}


def _rosters(data, result):
    expected = _expected_result(data)
    _keys(result, ('aggregate', 'assignments_by_id'))
    _aggregate_shape(result['aggregate'])
    _require(typed._same(result, expected), 'Candidate differs from independent source ranks, cuts or same-ID assignments')
    customers = []
    for row in data['dataset']['customers']:
        eligible = row['activity_state'] == 'active_complete'
        assignment = result['assignments_by_id'].get(row['customer_unique_id'])
        customer = {'customer_unique_id': row['customer_unique_id'], 'activity_state': row['activity_state'],
                    'eligible_for_rule_candidate': eligible}
        for kind in ('numeric_bin', 'ordinal'):
            key = 'numeric_bins' if kind == 'numeric_bin' else 'ordinals'
            for prefix, axis in zip(PREFIXES, AXES):
                customer[prefix + '_' + kind] = assignment[key][axis] if eligible else None
        customers.append(customer)
    orders = [{name: row[name] for name, _ in ORDER_SCHEMA} for row in data['dataset']['orders']]
    return customers, orders


def _acceptance(aggregate, customers, orders):
    return {'all_values_read_back': True, 'same_ID_rosters': True, 'strict_types_and_nulls': True,
            'float64_bitwise': True, 'independent_source_cutpoints_and_assignments': True,
            'rows': {'customer_roster.csv': len(customers), 'order_roster.csv': len(orders)},
            'roster_cells_compared': len(customers) * len(CUSTOMER_SCHEMA) + len(orders) * len(ORDER_SCHEMA),
            'assigned_active_customers': aggregate['reference_n'],
            'withheld_or_inactive_assignment_rows_null': len(customers) - aggregate['reference_n'],
            'aggregate_scalar_values_compared': prior._scalar_count(aggregate),
            'binary64_values_compared': prior._scalar_count(aggregate, float)}


def _schema():
    return {'customer_roster.csv': CUSTOMER_SCHEMA, 'order_roster.csv': ORDER_SCHEMA,
            'candidate.json': {'format_version': 1, 'top_level_keys': sorted(AGGREGATE_KEYS)},
            'manifest.json': ['format_version', 'provenance', 'schema', 'rows',
                              'private_bytes_sha', 'readback_acceptance']}


def bundle_guard(output):
    output = Path(output)
    _require(output.is_dir() and {path.name for path in output.iterdir()} == set(FILES), 'Exactly four G2 output files required')
    _require(not output.is_symlink() and not any((output / name).is_symlink() for name in FILES), 'Output symlinks rejected')
    return {name: typed._digest((output / name).read_bytes()) for name in FILES}


def read_outputs(output, provenance):
    """Restore canonical persistence and internal consistency only.

    The manifest preserves the writer's original independent-source receipt.
    This reader has no source RFM and cannot freshly establish that claim;
    ``verify_outputs`` must additionally compare all values with loaded sources.
    """
    _provenance(provenance)
    output = Path(output)
    before = bundle_guard(output)
    manifest = prior._read_json(output / 'manifest.json')
    _keys(manifest, _schema()['manifest.json'])
    _require(typed._same(manifest['format_version'], 1) and typed._same(manifest['provenance'], provenance)
             and typed._same(manifest['schema'], _schema())
             and typed._same(manifest['private_bytes_sha'], {name: before[name] for name in FILES[:3]}),
             'Manifest version, provenance, schema or private bytes differ')
    aggregate = prior._read_json(output / 'candidate.json')
    _aggregate_shape(aggregate)
    customers = typed._read_csv(output / 'customer_roster.csv', CUSTOMER_SCHEMA)
    orders = typed._read_csv(output / 'order_roster.csv', ORDER_SCHEMA)
    for rows, key in ((customers, 'customer_unique_id'), (orders, 'order_id')):
        ids = [row[key] for row in rows]
        _require(ids == sorted(set(ids)), 'Roster IDs must be complete, unique and canonical')
    assignments = {}
    states = {state: 0 for state in contract.policy()['activity_states']}
    for row in customers:
        _require(row['activity_state'] in states
                 and row['eligible_for_rule_candidate'] is (row['activity_state'] == 'active_complete'), 'Customer routing differs')
        states[row['activity_state']] += 1
        values = [row[p + '_' + kind] for kind in ('numeric_bin', 'ordinal') for p in PREFIXES]
        if not row['eligible_for_rule_candidate']:
            _require(all(value is None for value in values), 'Inactive or withheld assignments must be null')
            continue
        assignment = {'numeric_bins': {}, 'ordinals': {}, 'ordinal_tuple': []}
        for p, axis in zip(PREFIXES, AXES):
            b, ordinal = row[p + '_numeric_bin'], row[p + '_ordinal']
            k = aggregate['axes'][axis]['effective_levels']
            _require(type(b) is int and 1 <= b <= k
                     and type(ordinal) is int and ordinal == (k + 1 - b if axis == AXES[0] else b),
                     'Stored bin or ordinal direction differs')
            assignment['numeric_bins'][axis], assignment['ordinals'][axis] = b, ordinal
            assignment['ordinal_tuple'].append(ordinal)
        assignments[row['customer_unique_id']] = assignment
    _require(typed._same(states, aggregate['routing_counts']['by_state']), 'Stored routing counts differ')
    _require({row['customer_unique_id'] for row in orders if row['history_event_eligible']}
             == {row['customer_unique_id'] for row in customers}, 'Order/customer roster universe differs')
    for row in orders:
        _require(not row['window_event_eligible'] or row['history_event_eligible'], 'Window qualification differs')
        _require(not row['window_quarantine'] or not row['history_event_eligible'], 'Quarantine qualification differs')
    for axis in AXES:
        if aggregate['reference_n']:
            actual = Counter(entry['numeric_bins'][axis] for entry in assignments.values())
            _require([actual[b] for b in range(1, aggregate['axes'][axis]['effective_levels'] + 1)]
                     == [row['n'] for row in aggregate['axes'][axis]['bin_counts']], 'Stored per-axis counts differ')
    cells = Counter(tuple(entry['ordinal_tuple']) for entry in assignments.values())
    _require(cells == Counter({tuple(cell['ordinals']): cell['n'] for cell in aggregate['neutral_joint_cell_counts']}),
             'Stored joint cells differ')
    acceptance = _acceptance(aggregate, customers, orders)
    _require(typed._same(manifest['rows'], acceptance['rows'])
             and typed._same(manifest['readback_acceptance'], acceptance), 'Manifest acceptance differs')
    _require(typed._same(before, bundle_guard(output)), 'Output bytes changed during readback')
    return {'aggregate': aggregate, 'assignments_by_id': assignments,
            'customer_roster': customers, 'order_roster': orders, 'manifest': manifest}


def verify_outputs(output, data, result, provenance, expected_guard=None):
    _provenance(provenance)
    customers, orders = _rosters(data, result)
    before = bundle_guard(output)
    _require(expected_guard is None or typed._same(before, expected_guard), 'Frozen G2 output guard differs')
    restored = read_outputs(output, provenance)
    _require(typed._same(restored['aggregate'], result['aggregate'])
             and typed._same(restored['assignments_by_id'], result['assignments_by_id'])
             and typed._same(restored['customer_roster'], customers)
             and typed._same(restored['order_roster'], orders), 'Complete same-ID typed readback differs')
    _require(typed._same(before, bundle_guard(output)), 'Outputs changed during verification')
    return _acceptance(result['aggregate'], customers, orders)


def public_report(aggregate, provenance, acceptance):
    _aggregate_shape(aggregate)
    _provenance(provenance)
    _keys(acceptance, _acceptance(aggregate, [], []))
    for key in ('all_values_read_back', 'same_ID_rosters', 'strict_types_and_nulls',
                'float64_bitwise', 'independent_source_cutpoints_and_assignments'):
        _require(acceptance[key] is True, 'Readback acceptance required')
    _keys(acceptance['rows'], ('customer_roster.csv', 'order_roster.csv'))
    for value in acceptance['rows'].values(): _int(value)
    for key in ('roster_cells_compared', 'assigned_active_customers', 'withheld_or_inactive_assignment_rows_null',
                'aggregate_scalar_values_compared', 'binary64_values_compared'):
        _int(acceptance[key])
    population, orders = acceptance['rows']['customer_roster.csv'], acceptance['rows']['order_roster.csv']
    _require(population == aggregate['routing_counts']['population_n'] and orders >= population
             and acceptance['roster_cells_compared'] == population * 9 + orders * 11
             and acceptance['assigned_active_customers'] == aggregate['reference_n']
             and acceptance['withheld_or_inactive_assignment_rows_null'] == population - aggregate['reference_n']
             and acceptance['aggregate_scalar_values_compared'] == prior._scalar_count(aggregate)
             and acceptance['binary64_values_compared'] == prior._scalar_count(aggregate, float), 'Readback counts differ')
    return {'format_version': 1, 'specification': provenance['execution_specification'],
            'source_bindings': provenance['source_bindings'],
            'status': 'G2_candidate_diagnostic_completed_readback_accepted_G3_not_executed',
            'delivery': {'private_assignment_roster_written': True, 'private_bundle_files': 4,
                         'G2_core_reexecuted_for_readback': False},
            'aggregate': aggregate, 'readback_acceptance': acceptance}


def write_outputs(data, result, provenance, output):
    output = Path(output)
    _require(not output.exists() and not output.is_symlink(), 'Entire G2 output namespace must be absent')
    _provenance(provenance)
    customers, orders = _rosters(data, result)
    acceptance = _acceptance(result['aggregate'], customers, orders)
    payload = {'candidate.json': typed.json_bytes(result['aggregate']),
               'customer_roster.csv': typed._csv_bytes(customers, CUSTOMER_SCHEMA),
               'order_roster.csv': typed._csv_bytes(orders, ORDER_SCHEMA)}
    manifest = {'format_version': 1, 'provenance': provenance, 'schema': _schema(), 'rows': acceptance['rows'],
                'private_bytes_sha': {name: typed._digest(value) for name, value in payload.items()},
                'readback_acceptance': acceptance}
    payload['manifest.json'] = typed.json_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + '.staging-' + uuid.uuid4().hex)
    staging.mkdir()
    for name, value in payload.items():
        with (staging / name).open('xb') as stream:
            stream.write(value)
    verify_outputs(staging, data, result, provenance)
    staging.rename(output)
    private_guard = bundle_guard(output)
    accepted = verify_outputs(output, data, result, provenance, expected_guard=private_guard)
    return {'public_report': public_report(result['aggregate'], provenance, accepted),
            'readback_acceptance': accepted, 'private_guard': private_guard}
