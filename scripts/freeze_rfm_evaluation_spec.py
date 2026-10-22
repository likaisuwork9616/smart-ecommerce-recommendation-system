"""Freeze Stage 6 evaluation methods using accepted metadata and byte hashes only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import audit_rfm_feasibility as base
from scripts import build_rfm_dataset as prior
from scripts import freeze_rfm_dataset_spec as dataset_contract
from scripts import rfm_dataset_artifacts as artifacts
from scripts import rfm_evaluation_contract as method

CODE = 'scripts/freeze_rfm_evaluation_spec.py'
TEST = 'tests/test_rfm_evaluation_spec.py'
METHOD = 'scripts/rfm_evaluation_contract.py'
SPEC = 'reports/stage6/rfm_evaluation_specification.json'
OUTPUT = 'reports/stage6/rfm_evaluation_contract_audit.json'
PRIVATE = '.runtime/stage6_rfm_evaluation_spec_v1'
GUARD = PRIVATE + '/input_guard.json'
ACCEPTANCE = 'reports/stage6/rfm_dataset_build_acceptance.json'
REFERENCE = '.runtime/stage6_rfm_builder_independent/reference_receipt.json'
COMPARISON = '.runtime/stage6_rfm_builder_independent/comparison_receipt.json'
PRIVATE_METADATA = (prior.GUARD, prior.PRIVATE + '/manifest.json', REFERENCE, COMPARISON)
same = artifacts._same


def _require(condition, message):
    if condition is not True:
        raise ValueError(message)


def _prior_source_guard(root):
    """Reconstruct the original 8/12/20 bindings without even parsing CSV headers."""
    event = base.descriptor(root / base.EVENT, root)
    _require(event['sha256'] == base.EVENT_SHA, 'Original event source inventory changed')
    event_sources = base.read_json(root / base.EVENT)['raw_sources']
    _require(len({item['path'] for item in event_sources}) == len(event_sources), 'Duplicate historical raw source')
    raw = {item['path']: item for item in event_sources}
    raw_actual = [base.descriptor(root / path, root) for path in base.FILES.values()]
    for actual in raw_actual:
        expected = {key: raw[actual['path']][key] for key in ('path', 'bytes', 'sha256')}
        _require(same(actual, expected), 'Original raw CSV bytes changed')
    inventory = base.read_json(root / base.SPEC)
    headers = inventory['source_headers']
    _require(type(headers) is dict and set(headers) == set(base.COLUMNS), 'Frozen source headers differ')
    for name, required in base.COLUMNS.items():
        header = headers[name]
        _require(type(header) is list and all(type(value) is str and value for value in header)
                 and len(header) == len(set(header)) and set(required) <= set(header),
                 'Frozen header evidence is malformed')
    expected_inventory = {
        'format_version': 1, 'policy': base.policy(), 'columns_read': base.COLUMNS,
        'source_headers': headers,
        'sources': [event, *raw_actual, *[base.descriptor(root / path, root)
                     for path in (base.CODE, base.TEST, 'sql/03_business_analysis.sql')]],
    }
    _require(same(inventory, expected_inventory), 'Complete eight-source inventory binding differs')
    inventory_report = base.read_json(root / base.OUTPUT)
    _require(same(inventory_report['specification'], base.descriptor(root / base.SPEC, root)),
             'Original inventory report binding differs')
    contract = base.read_json(root / dataset_contract.SPEC)
    expected_contract = {
        'format_version': 1, 'policy': dataset_contract.policy(),
        'planned_schemas': dataset_contract.schemas(), 'source_headers': headers,
        'columns_read': base.COLUMNS,
        'sources': [*inventory['sources'], *[base.descriptor(root / path, root)
                    for path in (base.SPEC, base.OUTPUT, dataset_contract.CODE, dataset_contract.TEST)]],
    }
    _require(same(contract, expected_contract), 'Complete twelve-source dataset contract differs')
    audit = base.read_json(root / dataset_contract.OUTPUT)
    _require(same(audit['specification'], base.descriptor(root / dataset_contract.SPEC, root))
             and same(audit['policy'], contract['policy']), 'Original contract audit binding differs')
    expected_build = {
        'format_version': 1, 'policy': prior.policy(),
        'dataset_contract': base.descriptor(root / dataset_contract.SPEC, root),
        'sources': [*contract['sources'], *[base.descriptor(root / path, root)
                    for path in (dataset_contract.SPEC, dataset_contract.OUTPUT, *prior.IMPLEMENTATION)]],
    }
    stored = base.read_json(root / prior.SPEC)
    _require(same(stored, expected_build), 'Complete twenty-source build binding differs')
    return stored


def _accepted_summary_checks(build, accepted, reference, independent, root):
    """Cross-check accepted aggregate denominators without reconstructing values."""
    result, readback = build['results'], build['acceptance']
    _require(type(readback) is dict and set(readback) == {*prior.ACCEPTANCE_FLAGS, 'rows', 'cells_compared'},
             'Prior readback schema differs')
    rows = readback['rows']
    _require(type(rows) is dict and set(rows) == set(artifacts.FILES[:2]), 'Prior accepted row keys differ')
    _require(all(type(value) is int and value >= 0 for value in rows.values()), 'Prior accepted row types differ')
    _require(type(readback['cells_compared']) is int and readback['cells_compared'] >= 0
             and readback['cells_compared'] == sum(rows.values()) * 16, 'Prior accepted row/cell counts differ')
    states = result['customer_states']
    expected_states = dataset_contract.policy()['activity_states']
    _require(type(states) is dict and set(states) == set(expected_states)
             and all(type(value) is int and value >= 0 for value in states.values()),
             'Prior customer state keys or numeric types differ')
    active = sum(states[key] for key in ('active_complete', 'active_money_unknown', 'active_with_quarantine'))
    inactive = states['inactive_complete'] + states['inactive_with_quarantine']
    masked = states['active_money_unknown'] + states['active_with_quarantine'] + states['inactive_with_quarantine']
    _require(sum(states.values()) == rows['customers.csv'], 'Customer state sum differs from accepted rows')
    # Pure JSON comparison against the already bound contract audit; this helper
    # does not read raw tables or inspect customer/order CSV values.
    prior._support_matches(result, root)
    conservation = result['customer_money_conservation']
    known = conservation['eligible_window_product_cents_on_known_orders']
    published = conservation['published_customer_product_cents']
    withheld = conservation['known_product_cents_masked_customer_subsets']
    _require(all(type(value) is int and value >= 0 for value in (known, published, withheld)),
             'Prior money conservation types differ')
    _require(known == published + withheld and conservation['known_product_cents_equal_published_plus_masked_known'] is True,
             'Prior money conservation equation differs')
    ref_money = reference['money_conservation']
    checks = {
        'public_build_version_policy_status': (
            same(build.get('format_version'), 1) and same(build.get('policy'), prior.policy())
            and build.get('status') == 'retrospective_RFM_dataset_built_readback_accepted_no_segmentation'),
        'accepted_readback_schema_types_counts': True,
        'accepted_state_types_sum': True,
        'accepted_population_denominators': (
            same(result['history']['customer_universe'], rows['customers.csv'])
            and same(result['history']['order_decisions_scope_rows'], rows['order_decisions.csv'])
            and same(result['source']['purchase_before_T_orders'], rows['order_decisions.csv'])
            and same(result['window']['active_customers'], active)
            and same(result['window']['zero_eligible_window_customers'], inactive)),
        'bound_original_contract_support': True,
        'accepted_money_mask_and_conservation': (
            same(conservation['masked_customers'], masked)
            and same(conservation['unmasked_customers'], rows['customers.csv'] - masked)
            and same(conservation['inactive_complete_zero_customers'], states['inactive_complete'])
            and conservation['unknown_product_amounts_are_zero_filled'] is False),
        'acceptance_version_status_permissions': (
            same(accepted.get('format_version'), 1)
            and accepted.get('status') == 'synthetic_real_readback_independent_same_ID_and_read_only_verification_passed'
            and same(accepted.get('scope'), {
                'dataset_correctness_only': True, 'model_fits': 0, 'segmentation': False, 'dashboard': False,
                'new_model_performance_conclusion': False, 'operational_as_of_accepted': False,
                'refund_net_money_supported': False})),
        'acceptance_prior_read_only_permissions': same(accepted.get('read_only_entry_verification'), {
            'passed': True, 'command': 'scripts/build_rfm_dataset.py --verify', 'source_binding_count': 20,
            'rebuilt': False, 'wrote_files': False}),
        'acceptance_stage4_stage5_unchanged': (
            same(accepted.get('stage4'), prior.policy()['stage4'])
            and same(accepted.get('stage5'), prior.policy()['stage5'])),
        'independent_reference_population_frequency_nulls': (
            same(reference['customer_rows'], rows['customers.csv'])
            and same(reference['order_rows'], rows['order_decisions.csv'])
            and same(reference['eligible_history_orders'], result['history']['event_eligible_orders'])
            and same(reference['eligible_window_orders'], result['window']['event_eligible_orders'])
            and same(reference['frequency_sum'], result['window']['event_eligible_orders'])
            and same(reference['null_recency_customers'], inactive)
            and same(reference['null_monetary_customers'], masked)),
        'independent_reference_states': same(reference['activity_state_counts'], {
            key: value for key, value in states.items() if value}),
        'independent_reference_money_conservation': (
            same(ref_money['all_eligible_window_product_cents'], known)
            and same(ref_money['known_customer_M_cents'], published)
            and same(ref_money['masked_customer_known_eligible_product_cents'], withheld)
            and ref_money['holds'] is True),
        'independent_reference_clock_and_quality_counts': (
            same(reference['history_clock_quarantine_orders'], result['history']['approval_conflict_orders'])
            and same(reference['window_clock_quarantine_orders'], result['window']['approval_conflict_orders'])
            and same(reference['window_all_quality_quarantine_orders'], result['window_quarantine']['orders'])
            and reference['raw_source_bytes_unchanged'] is True
            and reference['segmentation_training_dashboard'] is False),
        'independent_reference_source_rows': same(reference['source_rows'], {
            'orders': result['source']['orders'], 'customers': result['source']['customer_master_rows'],
            'order_items': result['source']['order_item_rows'], 'order_payments': result['source']['order_payment_rows']}),
    }
    datasets = independent['datasets']
    _require(type(datasets) is dict and set(datasets) == set(rows), 'Independent dataset keys differ')
    for name, count in rows.items():
        data = datasets[name]
        expected_binary64 = active if name == 'customers.csv' else 0
        _require(type(data) is dict and set(data) == {'rows', 'typed_cell_comparisons', 'nullable_cells', 'binary64_comparisons'}
                 and all(type(value) is int and value >= 0 for value in data.values()),
                 'Independent dataset metadata schema or types differ')
        _require(same(data['rows'], count) and same(data['typed_cell_comparisons'], count * 16)
                 and same(data['binary64_comparisons'], expected_binary64)
                 and data['nullable_cells'] <= count * 16, 'Independent per-file counts differ')
    checks['independent_per_file_rows_cells_binary64'] = True
    checks['independent_customer_null_cells'] = same(datasets['customers.csv']['nullable_cells'], 3 * inactive + masked)
    checks['independent_total_equals_per_file_cells'] = same(
        independent['total_cell_comparisons'], sum(data['typed_cell_comparisons'] for data in datasets.values()))
    return checks


def _chain(root):
    """Do not parse CSV values or replay prior builders/readback/statistics."""
    root = Path(root)
    build_spec = _prior_source_guard(root)
    _require(len(build_spec['sources']) == 20, 'Prior build must retain all twenty sources')
    guard = base.read_json(root / prior.GUARD)
    manifest = base.read_json(root / prior.PRIVATE / 'manifest.json')
    contract = base.read_json(root / dataset_contract.SPEC)
    build = base.read_json(root / prior.OUTPUT)
    accepted = base.read_json(root / ACCEPTANCE)
    reference = base.read_json(root / REFERENCE)
    independent = base.read_json(root / COMPARISON)
    private_bundle = artifacts.bundle_guard(root / prior.PRIVATE)
    readback = build['acceptance']
    checks = {
        **_accepted_summary_checks(build, accepted, reference, independent, root),
        'complete_twenty_original_sources': True,
        'private_guard_version': same(guard['format_version'], 1),
        'private_guard_build_specification': same(guard['build_specification'], base.descriptor(root / prior.SPEC, root)),
        'private_guard_dataset_contract': same(guard['dataset_contract'], build_spec['dataset_contract']),
        'private_guard_source_list': same(guard['source_bindings'], build_spec['sources']),
        'private_bundle_all_three_bytes': same(guard['private_bundle_guard'], private_bundle),
        'private_guard_prior_readback': same(guard['readback_acceptance'], readback),
        'manifest_seven_keys': set(manifest) == set(dataset_contract.schemas()['manifest.json']),
        'manifest_dataset_contract': same(manifest['specification_bytes_sha'], build_spec['dataset_contract']),
        'manifest_schema': same(manifest['schema'], contract['planned_schemas']),
        'manifest_sources': same(manifest['source_bindings'], build_spec['sources']),
        'manifest_private_csv_bytes': same(manifest['private_bytes_sha'], {name: private_bundle[name] for name in artifacts.FILES[:2]}),
        'manifest_rows': same(manifest['rows'], readback['rows']),
        'manifest_summary': same(manifest['population_and_state_counts'], build['results']),
        'manifest_prior_readback': same(manifest['readback_acceptance'], readback),
        'public_build_specification': same(build['specification'], base.descriptor(root / prior.SPEC, root)),
        'acceptance_build_report': same(accepted['build_report'], base.descriptor(root / prior.OUTPUT, root)),
        'acceptance_build_specification': same(accepted['specification'], base.descriptor(root / prior.SPEC, root)),
        'acceptance_real_bundle': same(accepted['real_private_bundle'], readback),
        'acceptance_independent_receipt': same(accepted['independent_acceptance'], independent),
        'independent_reference_customer_bytes': private_bundle['customers.csv']['sha256'] == reference['private_reference_sha']['customers.reference.csv'],
        'independent_reference_order_bytes': private_bundle['order_decisions.csv']['sha256'] == reference['private_reference_sha']['order_decisions.reference.csv'],
        'independent_prior_acceptance_passed': (
            independent['status'] == 'pass' and independent['production_code_imported'] is False
            and independent['reference_fingerprints_rechecked'] is True
            and independent['frozen_raw_source_fingerprints_rechecked'] is True),
        'independent_prior_cell_count': same(independent['total_cell_comparisons'], readback['cells_compared']),
        'prior_readback_passed': all(readback.get(key) is True for key in prior.ACCEPTANCE_FLAGS),
    }
    for key, passed in checks.items():
        _require(passed, 'Accepted dataset metadata chain differs: ' + key)
    _require(set(guard) == {'format_version', 'build_specification', 'dataset_contract',
                           'source_bindings', 'private_bundle_guard', 'readback_acceptance'},
             'Prior private output guard schema differs')
    private = {
        'metadata_files': [base.descriptor(root / path, root) for path in PRIVATE_METADATA],
        'private_bundle_guard': private_bundle,
    }
    return {'build_specification': build_spec, 'build_report': build,
            'checks': checks, 'private': private}


def _state(root):
    root = Path(root)
    chain = _chain(root)
    sources = [*chain['build_specification']['sources'], *[
        base.descriptor(root / path, root)
        for path in (prior.SPEC, prior.OUTPUT, ACCEPTANCE, 'requirements-lock.txt', METHOD, CODE, TEST)]]
    paths = [source['path'] for source in sources]
    _require(len(sources) == 27 and len(set(paths)) == 27,
             'Exactly twenty-seven complete distinct source bindings are required')
    spec = {'format_version': 1, 'policy': method.policy(),
            'planned_outputs': method.planned_outputs(), 'sources': sources}
    data = artifacts.json_bytes(spec)
    descriptor = {'path': SPEC, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    guard = {'format_version': 1, 'specification': descriptor,
             'source_bindings': sources, **chain['private']}
    return spec, guard, chain


def specification(root=ROOT):
    return _state(Path(root))[0]


def verify_sources(spec, root=ROOT):
    root = Path(root)
    proposed, guard, chain = _state(root)
    _require(same(spec, proposed) and same(base.read_json(root / SPEC), proposed),
             'Complete evaluation specification or source bytes differ')
    _require(same(base.descriptor(root / SPEC, root), guard['specification']),
             'Frozen evaluation specification bytes differ')
    _require(same(base.read_json(root / GUARD), guard)
             and (root / GUARD).read_bytes() == artifacts.json_bytes(guard),
             'Frozen private evaluation input guard differs')
    return chain


def _preflight_pair(root, spec, guard):
    paths = (root / SPEC, root / GUARD)
    _require(paths[0].exists() == paths[1].exists(), 'Partial frozen specification/guard must not be regenerated')
    if (root / PRIVATE).exists():
        _require((root / PRIVATE).is_dir() and {p.name for p in (root / PRIVATE).iterdir()} == {'input_guard.json'},
                 'Unexpected files in frozen evaluation control namespace')
    for path, payload in zip(paths, (spec, guard)):
        if path.exists():
            _require(path.read_bytes() == artifacts.json_bytes(payload), 'Refusing changed frozen specification or input guard')


def run(root=ROOT, *, specification_only=False, audit=False):
    root = Path(root)
    _require(sum((specification_only, audit)) == 1, 'Choose exactly one specification-only or audit action')
    if specification_only:
        spec, guard, _ = _state(root)
        _preflight_pair(root, spec, guard)
        after_spec, after_guard, _ = _state(root)
        _require(same(spec, after_spec) and same(guard, after_guard), 'Inputs changed during specification preflight')
        base.immutable_write(root / SPEC, spec)
        base.immutable_write(root / GUARD, guard)
        verify_sources(spec, root)
        return {'status': 'evaluation_methods_frozen_no_values_parsed_or_segmentation', 'output': SPEC}
    spec = base.read_json(root / SPEC)
    chain = verify_sources(spec, root)
    result = chain['build_report']['results']
    payload = {
        'format_version': 1, 'specification': base.descriptor(root / SPEC, root),
        'status': 'evaluation_contract_frozen_existing_dataset_bytes_verified_only',
        'metadata_checks': chain['checks'],
        'reused_accepted_population': {
            'source': prior.OUTPUT, 'customer_rows': chain['build_report']['acceptance']['rows']['customers.csv'],
            'order_decision_rows': chain['build_report']['acceptance']['rows']['order_decisions.csv'],
            'history_event_eligible_orders': result['history']['event_eligible_orders'],
            'window_event_eligible_orders': result['window']['event_eligible_orders'],
            'customer_states': result['customer_states'],
        },
        'execution': {'csv_values_parsed': False, 'csv_content_parsed': False, 'csv_header_parsed': False,
                      'new_descriptive_statistics_computed': False,
                      'cut_points_computed': False, 'scores_assigned': False, 'segments_assigned': False,
                      'model_fits': 0, 'dashboard': False, 'prior_readback_reexecuted': False,
                      'existing_dataset_rebuilt': False, 'new_model_performance_conclusion': False},
        'stage4': prior.policy()['stage4'], 'stage5': prior.policy()['stage5'],
    }
    final_chain = verify_sources(spec, root)
    _require(same(chain, final_chain), 'Inputs changed during metadata audit')
    base.immutable_write(root / OUTPUT, payload)
    verify_sources(spec, root)
    return {'status': payload['status'], 'output': OUTPUT, 'source_bindings': len(spec['sources'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--specification-only', action='store_true')
    actions.add_argument('--audit', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(run(**vars(args)), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
