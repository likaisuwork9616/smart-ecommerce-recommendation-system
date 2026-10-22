"""Freeze read-only RFM execution wiring; CLI preparation never describes real data."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import rfm_description as core
from scripts import rfm_description_sources as sources
from scripts import rfm_description_outputs as outputs

base, typed, same = sources.base, sources.artifacts, sources.same
CODE = 'scripts/prepare_rfm_description.py'
TEST = 'tests/test_prepare_rfm_description.py'
SPEC = 'reports/stage6/rfm_description_execution_specification.json'
PREFLIGHT = 'reports/stage6/rfm_description_execution_preflight.json'
PRIVATE = '.runtime/stage6_rfm_description_execution_v1'
INPUT_GUARD = PRIVATE + '/input_guard.json'
OUTPUT_GUARD = PRIVATE + '/output_guard.json'
FAILURE = PRIVATE + '/failure.json'
RECEIPT = '.runtime/stage6_rfm_description_execution_unit.json'
DATASET = '.runtime/stage6_rfm_evaluation_v1'
PUBLIC = 'reports/stage6/rfm_description.json'
MODULES = ['tests.test_rfm_description_sources', 'tests.test_rfm_description_outputs',
           'tests.test_prepare_rfm_description']
IMPLEMENTATION = ('scripts/rfm_description_sources.py', 'tests/test_rfm_description_sources.py',
                  'scripts/rfm_description_outputs.py', 'tests/test_rfm_description_outputs.py', CODE, TEST)


def _require(value, message):
    if value is not True:
        raise ValueError(message)


def policy():
    return {
        'scope': 'freeze_complete_readonly_description_execution_synthetic_tests_only',
        'CLI': 'prepare_only_no_real_execution_or_path_override',
        'future_execute_callable': 'wired_and_tested_on_synthetic_inputs_not_called_on_real_data_this_round',
        'independent_roster': 'original_order_customer_event_projections_not_derived_bundle_roster',
        'roster_checks': 'all_history_customer_IDs_all_preT_order_IDs_window_order_IDs_and_every_order_mapping_clock_reason_flags',
        'core': 'one_frozen_describe_dataset_call_after_full_source_ID_guard_expected_customer_roster_required',
        'publication': 'private_four_file_staging_full_typed_readback_then_public_aggregate_then_external_output_guard',
        'readback': 'all_roster_rows_and_aggregate_values_exact_types_nulls_float64_bits_plus_population_money_conservation',
        'failure': 'stop_no_success_return_no_automatic_resume_overwrite_or_rebuild_private_failure_receipt',
        'future_private_output': DATASET + '/', 'future_public_output': PUBLIC,
        'future_verify': 'source_and_output_guards_then_readback_without_reexecuting_core',
        'current_round': {'real_CSV_parsed': False, 'real_roster_created': False,
                          'real_description_executed': False, 'real_description_outputs_created': False},
        'cutpoints': False, 'scores_or_groups': False, 'resampling': False, 'model_fits': 0, 'dashboard': False,
        'stage4': sources.prior.policy()['stage4'], 'stage5': sources.prior.policy()['stage5'],
    }


def _specification(root, snapshot):
    bindings = [*snapshot['public_sources'], *[base.descriptor(root / path, root) for path in IMPLEMENTATION]]
    _require(len(bindings) == 41 and len({item['path'] for item in bindings}) == 41,
             'Exactly forty-one complete distinct execution sources are required')
    return {'format_version': 1, 'policy': policy(), 'sources': bindings,
            'output_schema': outputs._schema(),
            'rosters': {'customer_roster.csv': outputs.CUSTOMER_SCHEMA,
                        'order_roster.csv': outputs.ORDER_SCHEMA}}


def specification(root=ROOT):
    root = Path(root)
    return _specification(root, sources.metadata_snapshot(root))


def source_bindings(root=ROOT):
    return specification(root)['sources']


def _unit_receipt(root, bindings):
    receipt = base.read_json(root / RECEIPT)
    keys = {'modules', 'tests_by_module', 'tests_run', 'errors', 'failures', 'skipped',
            'successful', 'elapsed_seconds', 'source_bindings'}
    _require(type(receipt) is dict and set(receipt) == keys, 'Execution test receipt schema differs')
    _require(same(receipt['modules'], MODULES) and type(receipt['tests_by_module']) is dict
             and set(receipt['tests_by_module']) == set(MODULES)
             and all(type(value) is int and value > 0 for value in receipt['tests_by_module'].values()),
             'All three exact synthetic suites with positive test counts are required')
    _require(type(receipt['tests_run']) is int
             and receipt['tests_run'] == sum(receipt['tests_by_module'].values())
             and all(type(receipt[key]) is int and receipt[key] == 0 for key in ('errors', 'failures', 'skipped'))
             and receipt['successful'] is True, 'Execution synthetic tests did not pass')
    _require(type(receipt['elapsed_seconds']) is float and math.isfinite(receipt['elapsed_seconds'])
             and receipt['elapsed_seconds'] >= 0, 'Synthetic duration is invalid')
    _require(same(receipt['source_bindings'], bindings), 'Test receipt complete source bindings changed')
    return receipt


def _state(root):
    snapshot = sources.metadata_snapshot(root)
    spec = _specification(root, snapshot)
    receipt = _unit_receipt(root, spec['sources'])
    data = typed.json_bytes(spec)
    descriptor = {'path': SPEC, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    guard = {'format_version': 1, 'specification': descriptor, 'input_snapshot': snapshot,
             'synthetic_test_receipt': base.descriptor(root / RECEIPT, root)}
    report = {'format_version': 1, 'specification': descriptor,
              'status': 'readonly_description_execution_prepared_synthetic_accepted_real_run_not_executed',
              'policy': policy(), 'source_count': len(spec['sources']),
              'unit_tests': {key: value for key, value in receipt.items() if key != 'source_bindings'},
              'accepted_metadata_checks': snapshot['metadata_checks'],
              'reused_accepted_rows': snapshot['accepted_rows'],
              'execution': {'source_loader_wired': True, 'independent_roster_wired': True,
                            'core_dispatch_wired': True, 'private_public_outputs_and_readback_wired': True,
                            'synthetic_only': True, 'real_CSV_parsed': False, 'real_roster_created': False,
                            'real_description_executed': False, 'future_outputs_created': False,
                            'cutpoints_estimated': False, 'scores_or_groups_created': False,
                            'resampling_executed': False, 'model_fits': 0, 'dashboard': False},
              'decision': 'prepared_only_next_decide_one_real_readonly_description_no_cutpoints_or_groups'}
    return spec, guard, report


def _execution_absent(root):
    _require(not any((root / path).exists() or (root / path).is_symlink()
                     for path in (DATASET, PUBLIC, OUTPUT_GUARD, FAILURE)),
             'Execution output or failure already exists; no automatic rerun or overwrite')


def _prepare_preflight(root, state):
    files = (SPEC, INPUT_GUARD, PREFLIGHT)
    exists = [(root / path).exists() for path in files]
    _require(not any(exists) or all(exists), 'Partial execution preparation must not be regenerated')
    if (root / PRIVATE).exists():
        _require((root / PRIVATE).is_dir()
                 and {path.name for path in (root / PRIVATE).iterdir()} == {'input_guard.json'},
                 'Unexpected execution control files')
    for path, payload in zip(files, state):
        if (root / path).exists():
            _require((root / path).read_bytes() == typed.json_bytes(payload), 'Frozen execution preparation bytes differ')


def verify_prepared(root=ROOT):
    root = Path(root)
    state = _state(root)
    for path, payload in zip((SPEC, INPUT_GUARD, PREFLIGHT), state):
        _require((root / path).read_bytes() == typed.json_bytes(payload), 'Prepared execution source or guard differs')
    return state


def prepare(root=ROOT):
    root = Path(root)
    _execution_absent(root)
    before = _state(root)
    _prepare_preflight(root, before)
    _require(same(before, _state(root)), 'Inputs changed during execution preparation')
    for path, payload in zip((SPEC, INPUT_GUARD, PREFLIGHT), before):
        base.immutable_write(root / path, payload)
    verify_prepared(root)
    return {'status': before[2]['status'], 'output': PREFLIGHT,
            'source_bindings': len(before[0]['sources']), 'tests_run': before[2]['unit_tests']['tests_run']}


def _provenance(root, spec):
    return {'execution_specification': base.descriptor(root / SPEC, root), 'source_bindings': spec['sources']}


def execute_prepared(root=ROOT):
    """Future execution, tested only on synthetic inputs in this preparation round.

    Intentionally not exposed by the CLI. The current user authorization permits
    preparation only; do not call this on the real workspace during this round.
    """
    root = Path(root)
    _execution_absent(root)
    state = verify_prepared(root)
    phase = 'load_independent_full_rosters'
    try:
        data = sources.read_inputs(root, state[1]['input_snapshot'])
        _require(same(state, verify_prepared(root)), 'Sources changed before description')
        phase = 'describe_frozen_dataset_once'
        description = core.describe_dataset(data['dataset'], data['evaluation_spec'],
                                            expected_customer_ids=data['customer_ids'])
        _require(same(state, verify_prepared(root)), 'Sources changed during description')
        phase = 'private_bundle_typed_readback'
        provenance = _provenance(root, state[0])
        result = outputs.write_outputs(data, description, provenance, root / DATASET)
        acceptance = outputs.verify_outputs(root / DATASET, data, description, provenance,
                                            expected_guard=result['private_guard'])
        _require(same(result['readback_acceptance'], acceptance)
                 and same(result['public_report'], outputs.public_report(description, provenance, acceptance)),
                 'Private/public output acceptance differs')
        _require(same(state, verify_prepared(root)), 'Sources changed during private output persistence')
        phase = 'public_aggregate_readback'
        base.immutable_write(root / PUBLIC, result['public_report'])
        _require((root / PUBLIC).read_bytes() == typed.json_bytes(result['public_report']),
                 'Public aggregate readback differs')
        guard = {'format_version': 1, 'specification': provenance['execution_specification'],
                 'input_guard': base.descriptor(root / INPUT_GUARD, root),
                 'private_bundle_guard': result['private_guard'],
                 'public_report': base.descriptor(root / PUBLIC, root), 'readback_acceptance': acceptance}
        _require(same(state, verify_prepared(root)), 'Sources changed before final output guard')
        _require(same(outputs.bundle_guard(root / DATASET), result['private_guard']), 'Private output changed before final guard')
        base.immutable_write(root / OUTPUT_GUARD, guard)
        _require((root / OUTPUT_GUARD).read_bytes() == typed.json_bytes(guard)
                 and same(guard['public_report'], base.descriptor(root / PUBLIC, root))
                 and same(guard['private_bundle_guard'], outputs.bundle_guard(root / DATASET))
                 and same(state, verify_prepared(root)), 'Final successful publication changed')
        return {'status': 'readonly_RFM_description_completed_readback_accepted', 'output': PUBLIC,
                'readback_acceptance': acceptance}
    except Exception as error:
        # Leave partial/staging evidence private and block replay; no success is
        # returned even if private or public publication had already begun.
        base.immutable_write(root / FAILURE, {'format_version': 1, 'status': 'failed_stop_no_success',
                                            'phase': phase, 'error_type': type(error).__name__})
        raise


def verify_completed(root=ROOT):
    """Future read-only source/output acceptance, with no new core statistics."""
    root = Path(root)
    _require(not (root / FAILURE).exists(), 'Failed execution is not accepted')
    state = verify_prepared(root)
    guard = base.read_json(root / OUTPUT_GUARD)
    _require((root / OUTPUT_GUARD).read_bytes() == typed.json_bytes(guard)
             and type(guard) is dict and set(guard) == {'format_version', 'specification', 'input_guard',
             'private_bundle_guard', 'public_report', 'readback_acceptance'}
             and same(guard['format_version'], 1)
             and same(guard['specification'], base.descriptor(root / SPEC, root))
             and same(guard['input_guard'], base.descriptor(root / INPUT_GUARD, root))
             and same(guard['public_report'], base.descriptor(root / PUBLIC, root))
             and same(guard['private_bundle_guard'], outputs.bundle_guard(root / DATASET)),
             'Final output provenance or bytes differ')
    data = sources.read_inputs(root, state[1]['input_snapshot'])
    provenance = _provenance(root, state[0])
    restored = outputs.read_outputs(root / DATASET, provenance)
    acceptance = outputs.verify_outputs(root / DATASET, data, restored['description'], provenance,
                                        expected_guard=guard['private_bundle_guard'])
    expected = outputs.public_report(restored['description'], provenance, acceptance)
    _require(same(guard['readback_acceptance'], acceptance)
             and (root / PUBLIC).read_bytes() == typed.json_bytes(expected), 'Public/private acceptance differs')
    _require(same(state, verify_prepared(root)), 'Sources changed during completed output verification')
    _require(same(guard['public_report'], base.descriptor(root / PUBLIC, root))
             and same(guard['private_bundle_guard'], outputs.bundle_guard(root / DATASET)),
             'Outputs changed during completed verification')
    return {'status': 'readonly_description_verified_without_core_reexecution', 'readback_acceptance': acceptance}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', required=True)
    parser.parse_args(argv)
    print(json.dumps(prepare(), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
