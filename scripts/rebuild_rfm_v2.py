"""Rebuild missing RFM assets as v2; execute one frozen G2 candidate and verify."""
from __future__ import annotations

import argparse
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
from scripts import audit_rfm_feasibility as base
from scripts import freeze_rfm_dataset_spec as contract
from scripts import rfm_dataset_builder as builder
from scripts import rfm_dataset_artifacts as typed
from scripts import rfm_description as description
from scripts import rfm_rule_candidate as candidate
from scripts import rfm_rule_candidate_outputs as output
from scripts import rfm_rebuild_reference as reference

LEGACY = 'reports/stage6/rfm_rule_candidate_execution_specification.json'
EVALUATION = 'reports/stage6/rfm_evaluation_specification.json'
OLD_BUILD = 'reports/stage6/rfm_dataset_build.json'
OLD_G1 = 'reports/stage6/rfm_description.json'
SPEC = 'reports/stage6/rfm_rebuild_v2_specification.json'
REPORT = 'reports/stage6/rfm_rebuild_v2.json'
PRIVATE = '.runtime/stage6_rfm_rebuild_v2'
INPUT = PRIVATE + '/input_guard.json'
GUARD = PRIVATE + '/output_guard.json'
FAILURE = PRIVATE + '/failure.json'
RUN = PRIVATE + '/execution'
TEST_LOG = '.runtime/stage6_rfm_rebuild_v2_tests.log'
NEW_SOURCES = ('scripts/rebuild_rfm_v2.py', 'scripts/rfm_rebuild_reference.py',
               'tests/test_rebuild_rfm_v2.py')
MODULES = ('tests.test_rfm_dataset_builder', 'tests.test_rfm_dataset_artifacts',
           'tests.test_rfm_description', 'tests.test_rfm_rule_candidate',
           'tests.test_rfm_rule_candidate_outputs', 'tests.test_rebuild_rfm_v2')


def require(condition, message):
    if condition is not True:
        raise ValueError(message)


def policy():
    return {'version': 'rfm_rebuild_v2', 'purpose': 'new_execution_after_missing_private_v1_assets',
            'restores_original_private_evidence': False,
            'method': 'unchanged_original_dataset_G1_G2_rules',
            'legacy_namespace_strings': 'method_metadata_only_actual_artifacts_use_v2_namespace',
            'actual_private_namespace': PRIVATE, 'public_result': REPORT,
            'steps': ['raw_source_hash_check', 'new_dataset_build', 'independent_all_cell_reference',
                      'new_G1_description', 'historical_aggregate_comparison', 'one_G2_core_call',
                      'independent_G2_readback', 'external_output_guard'],
            'historical_comparison': {'nonfloats': 'exact_type_and_value',
                                      'floats': {'relative_tolerance': 1e-12, 'absolute_tolerance': 1e-12}},
            'failure': 'retain_partial_outputs_no_overwrite_or_automatic_retry',
            'G2_ineligible': 'completed_diagnostic_keep_rules_and_all_failure_reasons',
            'G3': 'not_executed', 'training': False, 'dashboard': False,
            'temporal_business_validation': 'pending_data',
            'stage4': {'daily_budget': 0.1, 'status': 'pending_data'},
            'stage5': {'status': 'pending_data'}}


def _snapshot(root):
    legacy = base.read_json(root / LEGACY)
    sources = legacy['sources']
    require(len(sources) == 57 and len({s['path'] for s in sources}) == 57,
            'Complete legacy 57-source set required')
    for source in sources:
        require(typed._same(base.descriptor(root / source['path'], root), source),
                'Legacy source bytes differ: ' + source['path'])
    extra = (LEGACY, *NEW_SOURCES)
    require(not set(extra) & {s['path'] for s in sources}, 'Duplicate v2 source')
    return [*sources, *[base.descriptor(root / path, root) for path in extra]]


def _fresh(root):
    for path in (SPEC, REPORT, PRIVATE, TEST_LOG):
        require(not (root / path).exists() and not (root / path).is_symlink(),
                'Existing v2 state cannot be overwritten: ' + path)


def _test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _test_ids(test)
        else:
            yield test.id()


def prepare(root=ROOT):
    root = Path(root)
    _fresh(root)
    sources = _snapshot(root)
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    ids = sorted(_test_ids(suite))
    log = io.StringIO()
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    elapsed = time.perf_counter() - started
    require(typed._same(sources, _snapshot(root)), 'Sources changed during tests')
    path = root / TEST_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(log.getvalue())
    require(result.wasSuccessful() and not result.skipped and result.testsRun == len(ids),
            'Synthetic verification failed; keep its log and stop')
    tests = {'tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
             'skipped': len(result.skipped), 'elapsed_seconds': elapsed, 'test_ids': ids}
    spec = {'format_version': 1, 'policy': policy(), 'sources': sources, 'synthetic_verification': tests}
    base.immutable_write(root / SPEC, spec)
    base.immutable_write(root / INPUT, {'specification': base.descriptor(root / SPEC, root),
                                       'test_log': base.descriptor(path, root)})
    return {'status': 'v2_prepared_no_real_data_execution', 'tests_run': result.testsRun}


def _prepared(root):
    spec = base.read_json(root / SPEC)
    require(typed._same(spec['policy'], policy()) and typed._same(spec['sources'], _snapshot(root)),
            'Prepared v2 source or policy changed')
    guard = base.read_json(root / INPUT)
    expected = {'specification': base.descriptor(root / SPEC, root),
                'test_log': base.descriptor(root / TEST_LOG, root)}
    require(typed._same(guard, expected), 'Prepared v2 evidence changed')
    return spec


def compare_historical(actual, expected):
    """Comparison tolerance is frozen before execution; no rule tuning."""
    counts = {'scalar_values_compared': 0, 'float_values_compared': 0,
              'nonidentical_float_values_within_tolerance': 0, 'max_float_absolute_difference': 0.0}

    def visit(a, b):
        require(type(a) is type(b), 'Historical aggregate type differs')
        if isinstance(a, dict):
            require(set(a) == set(b), 'Historical aggregate keys differ')
            for key in a:
                visit(a[key], b[key])
        elif isinstance(a, list):
            require(len(a) == len(b), 'Historical aggregate length differs')
            for av, bv in zip(a, b):
                visit(av, bv)
        else:
            counts['scalar_values_compared'] += 1
            if type(a) is float:
                require(math.isfinite(a) and math.isfinite(b)
                        and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12),
                        'Historical floating aggregate differs beyond frozen tolerance')
                counts['float_values_compared'] += 1
                counts['nonidentical_float_values_within_tolerance'] += int(not typed._same(a, b))
                counts['max_float_absolute_difference'] = max(counts['max_float_absolute_difference'], abs(a - b))
            else:
                require(a == b, 'Historical aggregate value differs')
    visit(actual, expected)
    return {'accepted': True, **counts}


def _data(root, dataset):
    tables = base.read_tables(root)
    receipt, rosters = reference.verify_dataset(tables, dataset)
    return {'dataset': dataset, 'evaluation_spec': base.read_json(root / EVALUATION),
            **rosters, 'g1_accepted': True}, receipt


def _provenance(root, spec):
    return {'execution_specification': base.descriptor(root / SPEC, root), 'source_bindings': spec['sources']}


def _payload(root, dataset, g1, reference_receipt, candidate_report, spec, calls):
    comparisons = {'dataset_summary': compare_historical(dataset['summary'], base.read_json(root / OLD_BUILD)['results']),
                   'G1_description': compare_historical(g1, base.read_json(root / OLD_G1)['description'])}
    return {'format_version': 1, 'version': 'rfm_rebuild_v2', 'policy': policy(),
            'status': 'v2_rebuilt_G2_diagnostic_complete_readback_accepted',
            'specification': base.descriptor(root / SPEC, root),
            'recovery': {'original_private_assets_recovered': False, 'fresh_execution_not_original_receipts': True},
            'execution': calls, 'synthetic_verification': spec['synthetic_verification'],
            'dataset': {'summary': dataset['summary'], 'readback': typed._acceptance(dataset),
                        'independent_raw_source_validation': reference_receipt},
            'historical_aggregate_comparisons': comparisons,
            'G1': g1, 'G2': candidate_report}


def run(root=ROOT):
    root = Path(root)
    spec = _prepared(root)
    require({p.name for p in (root / PRIVATE).iterdir()} == {'input_guard.json'}
            and not (root / REPORT).exists(), 'Existing or partial v2 execution blocks replay')
    (root / RUN).mkdir()  # Atomic reservation: even an interrupted run cannot be silently replayed.
    calls = {'dataset_builder_calls': 0, 'G1_core_calls': 0, 'G2_core_calls': 0,
             'model_fits': 0, 'G3_executed': False}
    try:
        frozen = base.read_json(root / contract.SPEC)
        dataset = builder.build_dataset(base.read_tables(root), frozen)
        calls['dataset_builder_calls'] += 1
        data, receipt = _data(root, dataset)
        compare_historical(dataset['summary'], base.read_json(root / OLD_BUILD)['results'])
        _prepared(root)
        typed.write_bundle(dataset, frozen, spec['sources'], root / RUN / 'dataset')
        restored = typed.read_bundle(root / RUN / 'dataset', frozen, spec['sources'])
        require(typed._same(restored, dataset), 'Complete dataset readback differs')
        g1 = description.describe_dataset(restored, data['evaluation_spec'], expected_customer_ids=data['customer_ids'])
        calls['G1_core_calls'] += 1
        compare_historical(g1, base.read_json(root / OLD_G1)['description'])
        base.immutable_write(root / RUN / 'description.json', g1)
        require(typed._same(base.read_json(root / RUN / 'description.json'), g1), 'G1 readback differs')
        require(g1['gate_status']['G1'] == 'ready_for_aggregate_review', 'G1 is not evaluable')
        _prepared(root)
        result = candidate.evaluate_rule_candidate(restored, data['evaluation_spec'],
                    expected_customer_ids=data['customer_ids'], g1_accepted=True)
        calls['G2_core_calls'] += 1
        written = output.write_outputs(data, result, _provenance(root, spec), root / RUN / 'candidate')
        payload = _payload(root, restored, g1, receipt, written['public_report'], spec, calls)
        _prepared(root)
        base.immutable_write(root / REPORT, payload)
        guard = {'specification': base.descriptor(root / SPEC, root),
                 'input_guard': base.descriptor(root / INPUT, root),
                 'dataset': typed.bundle_guard(root / RUN / 'dataset'),
                 'description': base.descriptor(root / RUN / 'description.json', root),
                 'candidate': written['private_guard'], 'report': base.descriptor(root / REPORT, root)}
        base.immutable_write(root / GUARD, guard)
        return verify(root)
    except Exception as exc:
        base.immutable_write(root / FAILURE, {'status': 'technical_failure_no_replay',
                                             'exception_type': type(exc).__name__, 'execution': calls})
        raise


def verify(root=ROOT):
    """Full read-only verification; never rebuild or call the G1/G2 cores."""
    root = Path(root)
    spec = _prepared(root)
    require(not (root / FAILURE).exists(), 'Technical failure blocks acceptance')
    guard_version = base.descriptor(root / GUARD, root)
    guard = base.read_json(root / GUARD)
    expected = {'specification': base.descriptor(root / SPEC, root),
                'input_guard': base.descriptor(root / INPUT, root),
                'dataset': typed.bundle_guard(root / RUN / 'dataset'),
                'description': base.descriptor(root / RUN / 'description.json', root),
                'candidate': output.bundle_guard(root / RUN / 'candidate'),
                'report': base.descriptor(root / REPORT, root)}
    require(typed._same(guard, expected), 'External v2 output guard differs')
    frozen = base.read_json(root / contract.SPEC)
    dataset = typed.read_bundle(root / RUN / 'dataset', frozen, spec['sources'])
    data, receipt = _data(root, dataset)
    g1 = base.read_json(root / RUN / 'description.json')
    provenance = _provenance(root, spec)
    result = output.read_outputs(root / RUN / 'candidate', provenance)
    result = {k: result[k] for k in ('aggregate', 'assignments_by_id')}
    accepted = output.verify_outputs(root / RUN / 'candidate', data, result, provenance,
                                     expected_guard=guard['candidate'])
    candidate_report = output.public_report(result['aggregate'], provenance, accepted)
    calls = {'dataset_builder_calls': 1, 'G1_core_calls': 1, 'G2_core_calls': 1,
             'model_fits': 0, 'G3_executed': False}
    expected_payload = _payload(root, dataset, g1, receipt, candidate_report, spec, calls)
    require((root / REPORT).read_bytes() == typed.json_bytes(expected_payload), 'Public v2 report differs')
    _prepared(root)
    require(typed._same(guard, {'specification': base.descriptor(root / SPEC, root),
                'input_guard': base.descriptor(root / INPUT, root),
                'dataset': typed.bundle_guard(root / RUN / 'dataset'),
                'description': base.descriptor(root / RUN / 'description.json', root),
                'candidate': output.bundle_guard(root / RUN / 'candidate'),
                'report': base.descriptor(root / REPORT, root)}), 'Outputs changed during verification')
    require(typed._same(guard_version, base.descriptor(root / GUARD, root))
            and not (root / FAILURE).exists(), 'Completion guard changed during verification')
    return {'status': 'v2_verified_without_core_reexecution',
            'G2': result['aggregate']['gate_status']['G2'], 'customers': len(dataset['customers']),
            'orders': len(dataset['orders']), 'report': REPORT}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--prepare', action='store_true')
    actions.add_argument('--run', action='store_true')
    actions.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    result = prepare() if args.prepare else run() if args.run else verify()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
