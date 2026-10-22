"""Freeze G2 source, full-roster and output/readback wiring; CLI prepares only."""
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
from scripts import rfm_rule_candidate as core
from scripts import rfm_rule_candidate_sources as sources
from scripts import rfm_rule_candidate_outputs as outputs

base, typed, same = sources.base, sources.artifacts, sources.same
CODE = 'scripts/prepare_rfm_rule_candidate.py'
TEST = 'tests/test_prepare_rfm_rule_candidate.py'
SPEC = 'reports/stage6/rfm_rule_candidate_execution_specification.json'
PREFLIGHT = 'reports/stage6/rfm_rule_candidate_execution_preflight.json'
PRIVATE = '.runtime/stage6_rfm_rule_candidate_execution_v1'
INPUT_GUARD = PRIVATE + '/input_guard.json'
OUTPUT_GUARD = PRIVATE + '/output_guard.json'
FAILURE = PRIVATE + '/failure.json'
RECEIPT = '.runtime/stage6_rfm_rule_candidate_execution_unit.json'
DATASET = '.runtime/stage6_rfm_rule_candidate_v1'
PUBLIC = 'reports/stage6/rfm_rule_candidate.json'
MODULES = ['tests.test_rfm_rule_candidate_sources', 'tests.test_rfm_rule_candidate_outputs',
           'tests.test_prepare_rfm_rule_candidate']
IMPLEMENTATION = ('scripts/rfm_rule_candidate_sources.py', 'tests/test_rfm_rule_candidate_sources.py',
                  'scripts/rfm_rule_candidate_outputs.py', 'tests/test_rfm_rule_candidate_outputs.py', CODE, TEST)


def _require(value, message):
    if value is not True:
        raise ValueError(message)


def policy():
    return {
        'scope': 'G2_full_source_ID_output_readback_preparation_synthetic_only',
        'CLI': 'prepare_only_no_real_execution_or_path_override',
        'prior_G1': 'completed_description_source_bound_acceptance_and_full_private_public_readback_no_G1_core_replay',
        'prior_G2': 'accepted_synthetic_implementation_sources_guard_report_and_actual_test_log_unchanged',
        'independent_rosters': 'original_customer_order_projections_all_history_customers_all_preT_orders_window_orders_every_event_proof',
        'core': 'one_frozen_G2_call_only_after_complete_G0_G1_source_and_same_ID_checks',
        'assignments': 'all_complete_active_IDs_in_private_memory_and_roster_other_states_all_six_bins_ordinals_null',
        'output': 'four_private_files_staging_complete_typed_readback_public_aggregate_external_guard',
        'readback': 'every_roster_cell_and_aggregate_scalar_exact_types_nulls_float64_bits_independent_raw_RFM_cut_assignment_support_gate_check',
        'ineligible_candidate': 'complete_once_preserve_candidate_all_failures_not_a_technical_failure_no_recut_or_replay',
        'technical_failure': 'no_success_partial_or_failure_blocks_replay_no_resume_overwrite_rebuild_or_refreeze',
        'future_execute_callable': 'synthetic_tested_only_separate_real_execution_decision_required',
        'future_verify': 'full_sources_G1_same_ID_output_readback_without_G2_core_reexecution',
        'future_private_output': DATASET + '/', 'future_public_output': PUBLIC,
        'current_round': {'real_CSV_parsed': False, 'real_rosters_created': False,
                          'real_cutpoints_estimated': False, 'real_ordinals_or_tuples_assigned': False,
                          'future_outputs_created': False},
        'G3': 'not_implemented_not_executed_no_five_seed_subsampling_agreement_or_ARI',
        'clustering_models': False, 'model_fits': 0, 'dashboard': False,
        'stage4': sources.prior.policy()['stage4'], 'stage5': sources.prior.policy()['stage5'],
    }


def _specification(root, snapshot):
    bindings = [*snapshot['public_sources'], *[base.descriptor(root / path, root) for path in IMPLEMENTATION]]
    _require(len(bindings) == 57 and len({item['path'] for item in bindings}) == 57,
             'Exactly fifty-seven complete distinct execution sources required')
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
    _require(type(receipt) is dict and set(receipt) == {
        'modules', 'test_ids', 'tests_by_module', 'tests_run', 'errors', 'failures',
        'skipped', 'successful', 'elapsed_seconds', 'source_bindings'}, 'Execution receipt schema differs')
    ids, counts = receipt['test_ids'], receipt['tests_by_module']
    _require(same(receipt['modules'], MODULES) and type(ids) is list and bool(ids)
             and all(type(item) is str for item in ids) and ids == sorted(set(ids))
             and type(counts) is dict and set(counts) == set(MODULES)
             and all(type(counts[m]) is int and counts[m] > 0
                     and counts[m] == sum(identity.startswith(m + '.') for identity in ids) for m in MODULES)
             and type(receipt['tests_run']) is int and receipt['tests_run'] == sum(counts.values()) == len(ids)
             and all(type(receipt[k]) is int and receipt[k] == 0 for k in ('errors', 'failures', 'skipped'))
             and receipt['successful'] is True, 'All three exact synthetic suites must pass without skips')
    _require(type(receipt['elapsed_seconds']) is float and math.isfinite(receipt['elapsed_seconds'])
             and receipt['elapsed_seconds'] >= 0, 'Synthetic duration is invalid')
    _require(same(receipt['source_bindings'], bindings), 'Complete test receipt source bindings changed')
    return receipt


def _state(root):
    snapshot = sources.metadata_snapshot(root)
    spec = _specification(root, snapshot)
    receipt = _unit_receipt(root, spec['sources'])
    raw = typed.json_bytes(spec)
    descriptor = {'path': SPEC, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    guard = {'format_version': 1, 'specification': descriptor, 'input_snapshot': snapshot,
             'synthetic_test_receipt': base.descriptor(root / RECEIPT, root)}
    report = {'format_version': 1, 'specification': descriptor,
              'status': 'G2_execution_prepared_synthetic_accepted_real_candidate_not_executed',
              'policy': policy(), 'source_count': len(spec['sources']),
              'unit_tests': {key: value for key, value in receipt.items() if key != 'source_bindings'},
              'accepted_metadata_checks': snapshot['metadata_checks'],
              'reused_accepted_rows': snapshot['accepted_rows'],
              'execution': {'source_loader_wired': True, 'full_independent_rosters_wired': True,
                            'completed_G1_readback_wired': True, 'G2_single_core_dispatch_wired': True,
                            'private_public_outputs_readback_wired': True, 'synthetic_only': True,
                            **policy()['current_round'], 'G3_executed': False,
                            'clustering_models_executed': False, 'model_fits': 0, 'dashboard': False},
              'decision': 'prepared_only_next_decide_one_real_G2_run_no_execution_or_G3_authorization'}
    return spec, guard, report


def _execution_absent(root):
    paths = (DATASET, PUBLIC, OUTPUT_GUARD, FAILURE)
    _require(not any((root / path).exists() or (root / path).is_symlink() for path in paths),
             'Execution output or failure exists; no automatic rerun or overwrite')
    output = root / DATASET
    _require(not list(output.parent.glob(output.name + '.staging-*')),
             'Partial staging output blocks execution and preparation')


def _prepare_preflight(root, state):
    paths = (SPEC, INPUT_GUARD, PREFLIGHT)
    exists = [(root / path).exists() for path in paths]
    _require(not any((root / path).is_symlink() for path in paths)
             and not (root / PRIVATE).is_symlink(), 'Preparation symlinks rejected')
    _require(not any(exists) or all(exists), 'Partial preparation must not be regenerated')
    if (root / PRIVATE).exists():
        _require((root / PRIVATE).is_dir() and {p.name for p in (root / PRIVATE).iterdir()} == {'input_guard.json'},
                 'Unexpected preparation control files')
    for path, payload in zip(paths, state):
        if (root / path).exists():
            _require((root / path).read_bytes() == typed.json_bytes(payload), 'Frozen preparation bytes differ')


def verify_prepared(root=ROOT):
    root = Path(root)
    _require(not (root / PRIVATE).is_symlink(), 'Preparation control symlink rejected')
    state = _state(root)
    for path, payload in zip((SPEC, INPUT_GUARD, PREFLIGHT), state):
        _require(not (root / path).is_symlink()
                 and (root / path).read_bytes() == typed.json_bytes(payload), 'Prepared source or guard differs')
    return state


def prepare(root=ROOT):
    root = Path(root)
    _execution_absent(root)
    before = _state(root)
    _prepare_preflight(root, before)
    _require(same(before, _state(root)), 'Inputs changed during G2 preparation')
    for path, payload in zip((SPEC, INPUT_GUARD, PREFLIGHT), before):
        base.immutable_write(root / path, payload)
    verify_prepared(root)
    _execution_absent(root)
    return {'status': before[2]['status'], 'output': PREFLIGHT,
            'source_bindings': len(before[0]['sources']), 'tests_run': before[2]['unit_tests']['tests_run']}


def _provenance(root, spec):
    return {'execution_specification': base.descriptor(root / SPEC, root), 'source_bindings': spec['sources']}


def execute_prepared(root=ROOT):
    """Future operation: synthetic tests only in this preparation task.

    Not exposed by the CLI. Real execution requires a separate user decision;
    do not call this on the real workspace during the current preparation.
    """
    root = Path(root)
    _execution_absent(root)
    state = verify_prepared(root)
    phase = 'load_full_independent_rosters_and_completed_G1'
    try:
        data = sources.read_inputs(root, state[1]['input_snapshot'])
        _require(same(state, verify_prepared(root)), 'Sources changed before G2 candidate')
        phase = 'evaluate_frozen_G2_candidate_once'
        result = core.evaluate_rule_candidate(data['dataset'], data['evaluation_spec'],
                                              expected_customer_ids=data['customer_ids'],
                                              g1_accepted=data['g1_accepted'])
        _require(same(state, verify_prepared(root)), 'Sources changed during G2 candidate')
        phase = 'private_output_and_full_independent_readback'
        provenance = _provenance(root, state[0])
        written = outputs.write_outputs(data, result, provenance, root / DATASET)
        acceptance = outputs.verify_outputs(root / DATASET, data, result, provenance,
                                            expected_guard=written['private_guard'])
        _require(same(written['readback_acceptance'], acceptance)
                 and same(written['public_report'], outputs.public_report(result['aggregate'], provenance, acceptance)),
                 'Private/public candidate acceptance differs')
        _require(same(state, verify_prepared(root)), 'Sources changed during private publication')
        phase = 'public_aggregate_and_external_guard'
        base.immutable_write(root / PUBLIC, written['public_report'])
        _require((root / PUBLIC).read_bytes() == typed.json_bytes(written['public_report']), 'Public readback differs')
        guard = {'format_version': 1, 'specification': provenance['execution_specification'],
                 'input_guard': base.descriptor(root / INPUT_GUARD, root),
                 'private_bundle_guard': written['private_guard'],
                 'public_report': base.descriptor(root / PUBLIC, root), 'readback_acceptance': acceptance,
                 'candidate_gate': result['aggregate']['gate_status']['G2']}
        _require(same(state, verify_prepared(root))
                 and same(outputs.bundle_guard(root / DATASET), written['private_guard']),
                 'Sources or private output changed before final guard')
        base.immutable_write(root / OUTPUT_GUARD, guard)
        _require((root / OUTPUT_GUARD).read_bytes() == typed.json_bytes(guard)
                 and same(guard['public_report'], base.descriptor(root / PUBLIC, root))
                 and same(guard['private_bundle_guard'], outputs.bundle_guard(root / DATASET))
                 and same(state, verify_prepared(root)), 'Final G2 publication changed')
        return {'status': 'G2_candidate_completed_readback_accepted', 'output': PUBLIC,
                'candidate_gate': guard['candidate_gate'], 'readback_acceptance': acceptance}
    except Exception as error:
        base.immutable_write(root / FAILURE, {'format_version': 1, 'status': 'failed_stop_no_success',
                                            'phase': phase, 'error_type': type(error).__name__})
        raise


def verify_completed(root=ROOT):
    """Future full source/G1/ID/output readback without reexecuting the G2 core."""
    root = Path(root)
    _require(not (root / FAILURE).exists() and not (root / FAILURE).is_symlink(), 'Failed G2 execution not accepted')
    state = verify_prepared(root)
    guard = base.read_json(root / OUTPUT_GUARD)
    _require(not (root / OUTPUT_GUARD).is_symlink()
             and type(guard) is dict and set(guard) == {'format_version', 'specification', 'input_guard',
                 'private_bundle_guard', 'public_report', 'readback_acceptance', 'candidate_gate'}
             and same(guard['format_version'], 1)
             and (root / OUTPUT_GUARD).read_bytes() == typed.json_bytes(guard)
             and same(guard['specification'], base.descriptor(root / SPEC, root))
             and same(guard['input_guard'], base.descriptor(root / INPUT_GUARD, root))
             and same(guard['public_report'], base.descriptor(root / PUBLIC, root))
             and same(guard['private_bundle_guard'], outputs.bundle_guard(root / DATASET)),
             'Final candidate provenance or bytes differ')
    data = sources.read_inputs(root, state[1]['input_snapshot'])
    provenance = _provenance(root, state[0])
    restored = outputs.read_outputs(root / DATASET, provenance)
    result = {'aggregate': restored['aggregate'], 'assignments_by_id': restored['assignments_by_id']}
    acceptance = outputs.verify_outputs(root / DATASET, data, result, provenance,
                                        expected_guard=guard['private_bundle_guard'])
    expected = outputs.public_report(result['aggregate'], provenance, acceptance)
    _require(same(guard['readback_acceptance'], acceptance)
             and same(guard['candidate_gate'], result['aggregate']['gate_status']['G2'])
             and (root / PUBLIC).read_bytes() == typed.json_bytes(expected), 'Public/private G2 acceptance differs')
    _require(same(state, verify_prepared(root))
             and same(guard['public_report'], base.descriptor(root / PUBLIC, root))
             and same(guard['private_bundle_guard'], outputs.bundle_guard(root / DATASET)),
             'Sources or outputs changed during completed verification')
    return {'status': 'G2_candidate_verified_without_core_reexecution',
            'candidate_gate': guard['candidate_gate'], 'readback_acceptance': acceptance}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', required=True)
    parser.parse_args(argv)
    print(json.dumps(prepare(), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
