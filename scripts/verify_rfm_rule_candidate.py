"""Verify the G2 implementation on synthetic data; no real candidate entry."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import prepare_rfm_description as prior

base, typed, same = prior.base, prior.typed, prior.same
SPEC = 'reports/stage6/rfm_rule_candidate_implementation_specification.json'
OUTPUT = 'reports/stage6/rfm_rule_candidate_verification.json'
PRIVATE = '.runtime/stage6_rfm_rule_candidate_implementation_v1'
GUARD = PRIVATE + '/input_guard.json'
LOG = PRIVATE + '/synthetic_tests.log'
ACCEPTANCE = 'reports/stage6/rfm_description_acceptance.json'
MODULES = ['tests.test_rfm_rule_candidate', 'tests.test_verify_rfm_rule_candidate']
IMPLEMENTATION = ('scripts/rfm_rule_candidate.py', 'tests/test_rfm_rule_candidate.py',
                  'scripts/verify_rfm_rule_candidate.py', 'tests/test_verify_rfm_rule_candidate.py')


def _require(value, message):
    if value is not True:
        raise ValueError(message)


def policy():
    return {
        'scope': 'G2_rule_candidate_implementation_synthetic_verification_only',
        'frozen_method': 'reports/stage6/rfm_evaluation_specification.json',
        'real_inputs': 'existing_source_metadata_and_binary_hashes_only_no_CSV_parsing',
        'G1': 'existing_completed_description_receipt_checked_without_reexecution',
        'synthetic_execution': 'two_actual_unittest_modules_no_skips_complete_source_bindings',
        'G2': 'exact_integer_quantiles_ties_intact_levels_support_and_full_same_ID_reproducibility',
        'G3': 'not_implemented_or_executed_no_five_seed_subsampling_or_ARI',
        'outputs': 'aggregate_specification_verification_and_private_guard_log_only',
        'CLI': 'verify_synthetic_only_no_real_dispatch_input_path_or_override',
        'repeat': 'verify_existing_source_bound_receipt_no_rerun_overwrite_or_refreeze',
        'stage4': prior.policy()['stage4'], 'stage5': prior.policy()['stage5'],
    }


def _prior_snapshot(root):
    """Check existing G0/G1 evidence using JSON metadata and binary hashes only."""
    state = prior.verify_prepared(root)
    _require(not (root / prior.FAILURE).exists(), 'Prior description execution failed')
    guard = base.read_json(root / prior.OUTPUT_GUARD)
    keys = {'format_version', 'specification', 'input_guard', 'private_bundle_guard',
            'public_report', 'readback_acceptance'}
    _require(type(guard) is dict and set(guard) == keys
             and same(guard['format_version'], 1)
             and (root / prior.OUTPUT_GUARD).read_bytes() == typed.json_bytes(guard)
             and same(guard['specification'], base.descriptor(root / prior.SPEC, root))
             and same(guard['input_guard'], base.descriptor(root / prior.INPUT_GUARD, root))
             and same(guard['public_report'], base.descriptor(root / prior.PUBLIC, root))
             and same(guard['private_bundle_guard'], prior.outputs.bundle_guard(root / prior.DATASET)),
             'Prior completed description output bytes or provenance differ')
    public = base.read_json(root / prior.PUBLIC)
    accepted = base.read_json(root / ACCEPTANCE)
    gates = {'G0': 'passed', 'G1': 'ready_for_aggregate_review', 'G2': 'not_executed',
             'G3': 'not_executed', 'temporal': 'pending_data'}
    _require(same(public['description']['gate_status'], gates)
             and same(public['readback_acceptance'], guard['readback_acceptance'])
             and same(accepted['gate_status'], gates)
             and same(accepted['readback_acceptance'], guard['readback_acceptance'])
             and accepted['decision'] == 'description_accepted_next_synthetic_rule_candidate_implementation_no_real_cuts_or_groups'
             and same(accepted['completed_verification']['core_calls'], 0)
             and accepted['completed_verification']['output_guard_valid'] is True
             and accepted['source_bindings_before_after_match'] is True,
             'Prior G1 acceptance metadata differs')
    bindings = [*state[0]['sources'], *[base.descriptor(root / path, root) for path in
                (prior.SPEC, prior.PREFLIGHT, prior.PUBLIC, ACCEPTANCE, *IMPLEMENTATION)]]
    _require(len(bindings) == 49 and len({item['path'] for item in bindings}) == 49,
             'Complete forty-nine source bindings required')
    return {'source_bindings': bindings,
            'private_provenance': {'prepared_input_guard': base.descriptor(root / prior.INPUT_GUARD, root),
                                   'completed_output_guard': base.descriptor(root / prior.OUTPUT_GUARD, root),
                                   'prepared_state': state[1], 'completed_guard': guard},
            'metadata_checks': state[2]['accepted_metadata_checks']}


def _expected_cases():
    # Independently specified synthetic oracles; never Olist results.
    return {
        'balanced_500': {'n': 500, 'G2': 'passed', 'levels': [5, 5, 5],
                         'bin_counts_each_axis': [100, 100, 100, 100, 100]},
        'constant_F_500': {'n': 500, 'G2': 'ineligible', 'F_levels': 1,
                           'F_cuts': [], 'F_bins': [500]},
        'support_99_per_bin': {'n': 495, 'G2': 'ineligible', 'support_floor': 100,
                               'bin_counts_each_axis': [99, 99, 99, 99, 99]},
        'small_joint_cells': {'n': 500, 'G2': 'passed', 'joint_cells': 125,
                               'each_cell_n': 4, 'unsupported_cells': 125},
    }


def _run_cases():
    from tests.test_rfm_rule_candidate import synthetic_dataset, balanced_dataset, evaluate
    cases = [balanced_dataset(),
             synthetic_dataset([(level, 1, level * 100) for level in range(1, 6) for _ in range(100)]),
             balanced_dataset(99),
             synthetic_dataset([(r, f, m * 100) for r in range(1, 6) for f in range(1, 6)
                                for m in range(5) for _ in range(4)])]
    results = [evaluate(case)['aggregate'] for case in cases]
    a, b, c, d = results
    axes = ('recency_seconds', 'frequency_orders', 'monetary_product_cents')
    counts = lambda report, axis: [item['n'] for item in report['axes'][axis]['bin_counts']]
    _require(all(counts(a, axis) == [100] * 5 for axis in axes)
             and all(counts(c, axis) == [99] * 5 for axis in axes)
             and all(cell['n'] == 4 for cell in d['neutral_joint_cell_counts'])
             and all(r['reproducibility']['same_ID_assignments_100pct'] is True for r in results),
             'Synthetic case independent counts or same-ID oracle failed')
    observed = {
        'balanced_500': {'n': a['reference_n'], 'G2': a['gate_status']['G2'],
                         'levels': [a['axes'][axis]['effective_levels'] for axis in axes],
                         'bin_counts_each_axis': counts(a, axes[0])},
        'constant_F_500': {'n': b['reference_n'], 'G2': b['gate_status']['G2'],
                           'F_levels': b['axes'][axes[1]]['effective_levels'],
                           'F_cuts': b['axes'][axes[1]]['cut_values'], 'F_bins': counts(b, axes[1])},
        'support_99_per_bin': {'n': c['reference_n'], 'G2': c['gate_status']['G2'],
                               'support_floor': c['support_floor'], 'bin_counts_each_axis': counts(c, axes[0])},
        'small_joint_cells': {'n': d['reference_n'], 'G2': d['gate_status']['G2'],
                               'joint_cells': d['observed_joint_cells_n'],
                               'each_cell_n': d['neutral_joint_cell_counts'][0]['n'],
                               'unsupported_cells': sum(cell['support_flag'] == 'insufficient_group_support'
                                                        for cell in d['neutral_joint_cell_counts'])},
    }
    _require(same(observed, _expected_cases()), 'Synthetic case oracle failed')
    return observed


def _test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _test_ids(item)
        else:
            yield item.id()


def _run_suites():
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    ids = sorted(_test_ids(suite))
    _require(bool(ids) and len(ids) == len(set(ids)), 'Unique actual test identities required')
    counts = {module: sum(identity.startswith(module + '.') for identity in ids) for module in MODULES}
    _require(all(count > 0 for count in counts.values()) and sum(counts.values()) == len(ids),
             'Both exact synthetic suites required')
    log = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    receipt = {'modules': MODULES, 'tests_by_module': counts, 'test_ids': ids,
               'tests_run': result.testsRun, 'errors': len(result.errors),
               'failures': len(result.failures), 'skipped': len(result.skipped),
               'successful': result.wasSuccessful(),
               'elapsed_seconds': float(round(time.perf_counter() - started, 6))}
    _validate_receipt(receipt)
    return receipt, log.getvalue()


def _validate_receipt(receipt):
    _require(type(receipt) is dict and set(receipt) == {'modules', 'tests_by_module', 'test_ids',
             'tests_run', 'errors', 'failures', 'skipped', 'successful', 'elapsed_seconds'},
             'Synthetic receipt schema differs')
    ids = receipt['test_ids']
    counts = receipt['tests_by_module']
    _require(same(receipt['modules'], MODULES) and type(ids) is list and bool(ids)
             and all(type(item) is str for item in ids) and ids == sorted(set(ids))
             and type(counts) is dict and set(counts) == set(MODULES)
             and all(type(counts[m]) is int and counts[m] > 0
                     and counts[m] == sum(i.startswith(m + '.') for i in ids) for m in MODULES)
             and type(receipt['tests_run']) is int
             and receipt['tests_run'] == sum(counts.values()) == len(ids)
             and all(type(receipt[k]) is int and receipt[k] == 0 for k in ('errors', 'failures', 'skipped'))
             and receipt['successful'] is True
             and type(receipt['elapsed_seconds']) is float
             and math.isfinite(receipt['elapsed_seconds']) and receipt['elapsed_seconds'] >= 0,
             'Synthetic suites failed or receipt counts, identities or types differ')


def _specification(snapshot):
    return {'format_version': 1, 'policy': policy(), 'sources': snapshot['source_bindings']}


def _report(snapshot, receipt):
    return {'format_version': 1,
            'status': 'G2_implementation_synthetic_verified_real_candidate_not_executed',
            'policy': policy(), 'source_count': len(snapshot['source_bindings']), 'unit_tests': receipt,
            'synthetic_cases': _expected_cases(),
            'prior_metadata': {'checks': snapshot['metadata_checks'], 'all_passed': True,
                               'completed_description_output_hashes_match': True,
                               'individual_readback_rerun': False},
            'execution': {'synthetic_candidate_tests_executed': True, 'real_CSV_parsed': False,
                          'real_cutpoints_estimated': False, 'real_ordinals_or_tuples_assigned': False,
                          'G3_executed': False, 'model_fits': 0, 'dashboard': False},
            'decision': 'synthetic_implementation_accepted_next_decide_real_G2_preparation_no_real_execution_authorized',
            'limitations': ['Synthetic verification is not a real-data G2 pass or model performance.',
                            'G1 acceptance bool is a caller precondition, not provenance or execution authorization.',
                            'G3 sensitivity, temporal stability and business applicability remain unassessed.']}


def _check_existing(root, snapshot):
    spec, report, guard = (base.read_json(root / path) for path in (SPEC, OUTPUT, GUARD))
    _require(same(spec, _specification(snapshot)) and same(guard['input_snapshot'], snapshot),
             'Frozen candidate sources or private provenance changed')
    _require(set(guard) == {'format_version', 'input_snapshot', 'specification', 'report', 'test_log'}
             and same(guard['format_version'], 1), 'Candidate guard schema differs')
    for key, path in (('specification', SPEC), ('report', OUTPUT), ('test_log', LOG)):
        _require(same(guard[key], base.descriptor(root / path, root)), 'Candidate output bytes changed')
    _require((root / SPEC).read_bytes() == typed.json_bytes(spec)
             and (root / OUTPUT).read_bytes() == typed.json_bytes(report)
             and (root / GUARD).read_bytes() == typed.json_bytes(guard), 'Canonical output bytes differ')
    _validate_receipt(report['unit_tests'])
    _require(same(report, _report(snapshot, report['unit_tests'])), 'Candidate report semantics differ')
    return {'status': report['status'], 'output': OUTPUT, 'source_bindings': len(spec['sources']),
            'tests_run': report['unit_tests']['tests_run'], 'existing_verified_without_test_rerun': True}


def run(root=ROOT, *, verify_synthetic=False):
    _require(verify_synthetic is True, 'Only synthetic verification is supported')
    root = Path(root)
    before = _prior_snapshot(root)
    paths = [root / path for path in (SPEC, OUTPUT, GUARD, LOG)]
    exists = [path.exists() for path in paths]
    _require(not any(exists) or all(exists), 'Partial candidate outputs must not be regenerated')
    if (root / PRIVATE).exists():
        _require((root / PRIVATE).is_dir()
                 and {p.name for p in (root / PRIVATE).iterdir()} == {'input_guard.json', 'synthetic_tests.log'},
                 'Unexpected candidate control files')
    if all(exists):
        result = _check_existing(root, before)
        _require(same(before, _prior_snapshot(root)), 'Sources changed during verification')
        return result
    receipt, log = _run_suites()
    _validate_receipt(receipt)
    _require(same(_run_cases(), _expected_cases()), 'Synthetic case verification differs')
    _require(same(before, _prior_snapshot(root)), 'Sources changed during synthetic verification')
    spec = _specification(before)
    report = _report(before, receipt)
    base.immutable_write(root / SPEC, spec)
    base.immutable_write(root / OUTPUT, report)
    (root / LOG).parent.mkdir(parents=True, exist_ok=True)
    with (root / LOG).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(log)
    guard = {'format_version': 1, 'input_snapshot': before,
             'specification': base.descriptor(root / SPEC, root),
             'report': base.descriptor(root / OUTPUT, root), 'test_log': base.descriptor(root / LOG, root)}
    base.immutable_write(root / GUARD, guard)
    _require(same(before, _prior_snapshot(root)), 'Sources changed during publication')
    result = _check_existing(root, before)
    result['existing_verified_without_test_rerun'] = False
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-synthetic', action='store_true', required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(**vars(args)), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
