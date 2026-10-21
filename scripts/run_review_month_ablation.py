"""Bind the frozen ablation dispatcher; real training is an explicit later action."""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import freeze_review_dataset as files
from scripts import prepare_review_month_ablation as preparation
from scripts import review_baseline_sources as baseline_sources
from scripts import review_month_ablation_sources as sources
from scripts import run_review_baseline as control

SPEC = 'reports/stage5/review_month_ablation_dispatcher_specification.json'
REPORT = 'reports/stage5/review_month_ablation_dispatcher_verification.json'
PRIVATE = '.runtime/stage5_review_month_ablation_dispatcher_v1'
GUARD = PRIVATE + '/input_guard.json'
LAST_RUN = PRIVATE + '/synthetic_last_run.json'
CODE = ('scripts/run_review_month_ablation.py',
        'scripts/review_month_ablation_training.py',
        'scripts/review_month_ablation_artifacts.py',
        'tests/test_run_review_month_ablation.py',
        'tests/test_review_month_ablation_training.py',
        'tests/test_review_month_ablation_artifacts.py')
TEST_MODULES = tuple(path[:-3].replace('/', '.') for path in CODE if path.startswith('tests/'))
PARENTS = {
    preparation.SPEC: 'ae15389d470a28c29064f2fdee25310e5cc0d3ff5469502c038eee761d10c6e0',
    preparation.REPORT: '5e81ae9406b1500baf75ae85a1c79f8cc4917a037ce0986097654ad804cf736c',
}


def modules():
    from scripts import review_month_ablation_training as training
    from scripts import review_month_ablation_artifacts as artifacts
    return training, artifacts


def _descriptor_bytes(name, data):
    return {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def binding_contract():
    training, artifacts = modules()
    return {
        'version': 'stage5_review_month_ablation_dispatcher_v1',
        'training_entry': 'scripts/run_review_month_ablation.py --train',
        'default_action': 'help_only_no_source_load_or_fit',
        'this_step': 'implementation_binding_and_synthetic_tests_only',
        'real_training_requires': 'separate_user_decision_and_explicit_train_action',
        'verification_required_before_fit': REPORT,
        'synthetic_fit_evidence': 'instrument_actual_sklearn_fit_count_and_fixed32_dimensions_minimum_one_complete_trial',
        'preflight': 'full_source_chain_complete_roles_frozen_control_empty_outputs_successful_bound_tests',
        'source_verification': 'captured_exact_sources_before_each_fit_after_prediction_before_after_publication',
        'stale_or_missing_verification': 'refuse_before_start_no_output_or_fit',
        'failure_after_start': 'stop_no_retry_write_private_failure_receipt_no_success_report',
        'historical_parent_status': 'preserved_not_rewritten_as_current_status',
        'dispatcher': training.dispatcher_contract(),
        'fit_audit': training.audit_contract(),
        'artifacts': artifacts.artifact_schema_contract(),
    }


def make_specification(bundle, root=ROOT):
    root = Path(root).resolve()
    for name, expected in PARENTS.items():
        if files.descriptor(root / name, root)['sha256'] != expected:
            raise ValueError('Frozen execution preparation changed')
    parent, parent_source, _ = preparation.verify_specification(bundle, root)
    public = baseline_sources.merge_sources(parent['public_sources'],
        [files.descriptor(root / name, root) for name in (*PARENTS, *CODE)])
    private = baseline_sources.merge_sources(bundle.private_sources,
        [files.descriptor(root / preparation.GUARD, root)])
    if {item['path'] for item in public} & {item['path'] for item in private}:
        raise ValueError('Public and private dispatcher bindings overlap')
    files.verify_sources(public + private, root)
    spec = {
        'format_version': 1, 'role': 'frozen_three_feature_dispatcher_and_artifact_binding',
        'execution_specification': parent_source,
        'preparation_verification': files.descriptor(root / preparation.REPORT, root),
        'execution_plan': parent['execution_plan'],
        'method_protocol_unchanged': parent['method_protocol_unchanged'],
        'same_ID_pairing_unchanged': parent['same_ID_pairing'],
        'output_contract_unchanged': parent['output_contract'],
        'binding_contract': binding_contract(), 'public_sources': public,
        'private_source_guard': {'path': GUARD, 'input_paths': [item['path'] for item in private],
                                 'private_digests_public': False},
        'software_versions': sources.method.baseline.software_versions(),
        'current_real_execution': {'feature_builds': 0, 'fits': 0, 'predictions': 0,
                                   'candidate_selections': 0, 'performance_metrics': 0},
        'actual_treatment_selected_C': None, 'stage4': parent['stage4'], 'dashboard': False,
    }
    return spec, private


def _guard(spec_source, private):
    return {'format_version': 1, 'specification': spec_source, 'private_sources': private,
            'scope': 'existing_local_snapshot_not_original_ingestion_or_version_availability_proof'}


def freeze(root=ROOT):
    """Read real source metadata only; freeze new code/test/schema bindings."""
    root = Path(root).resolve()
    with sources.forbid_model_execution():
        preparation.require_future_outputs_absent(root)
        bundle = sources.load_prepared_sources(root)
        spec, private = make_specification(bundle, root)
        data = files.json_bytes(spec)
        source = _descriptor_bytes(SPEC, data)
        if (root / REPORT).exists() and files.read_json(root / REPORT).get('specification') != source:
            raise ValueError('Existing verification belongs to another dispatcher')
        preparation._publish([
            (preparation._path(root, SPEC), data),
            (preparation._path(root, GUARD, True), files.json_bytes(_guard(source, private)))],
            spec['public_sources'] + private, root)
        return spec


def verify_binding(bundle, root=ROOT):
    root = Path(root).resolve()
    expected, private = make_specification(bundle, root)
    spec = files.read_json(preparation._path(root, SPEC))
    if spec != expected:
        raise ValueError('Dispatcher, tests, concrete schemas or source bindings changed')
    source = files.descriptor(root / SPEC, root)
    if files.read_json(preparation._path(root, GUARD, True)) != _guard(source, private):
        raise ValueError('Dispatcher input guard does not bind exact private sources')
    bound = spec['public_sources'] + private + [source, files.descriptor(root / GUARD, root)]
    files.verify_sources(bound, root)
    return spec, bound


def _suite():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(TEST_MODULES)
    if loader.errors:
        raise ValueError('Cannot import all designated synthetic tests')
    for name in TEST_MODULES:
        if Path(sys.modules[name].__file__).resolve() != ROOT / (name.replace('.', '/') + '.py'):
            raise ValueError('Unexpected synthetic test import origin')
    identities = []
    def visit(item):
        if isinstance(item, unittest.TestSuite):
            for child in item:
                visit(child)
        elif isinstance(item, unittest.TestCase) and any(item.id().startswith(n + '.') for n in TEST_MODULES):
            identities.append(item.id())
        else:
            raise ValueError('Unexpected test outside the bound synthetic suite')
    visit(suite)
    if not identities or len(set(identities)) != len(identities):
        raise ValueError('Distinct nonempty synthetic tests required')
    counts = {name: sum(x.startswith(name + '.') for x in identities) for name in TEST_MODULES}
    if not all(counts.values()):
        raise ValueError('Every bound test module needs coverage')
    return suite, sorted(identities), counts


def verify_test_report(spec, root=ROOT):
    """A stale, partial, skipped or unbound test report cannot authorize fitting."""
    root = Path(root).resolve()
    report = files.read_json(preparation._path(root, REPORT))
    _, identities, counts = _suite()
    tests = report.get('tests', {})
    synthetic = report.get('synthetic_execution', {})
    if (report.get('status') != 'passed_synthetic_month_ablation_dispatcher_verification'
            or report.get('specification') != files.descriptor(root / SPEC, root)
            or report.get('sources') != spec['public_sources']
            or report.get('software_versions') != spec['software_versions']
            or tests.get('modules') != list(TEST_MODULES)
            or tests.get('test_ids') != identities or tests.get('counts_by_module') != counts
            or tests.get('tests_run') != len(identities)
            or any(tests.get(key) != 0 for key in ('failures', 'errors', 'skips',
                                                  'expected_failures', 'unexpected_successes'))):
        raise ValueError('Successful complete synthetic verification for this exact binding is required')
    completed = synthetic.get('sklearn_fits_completed')
    attempted = synthetic.get('sklearn_fits_attempted')
    if (type(completed) is not int or completed < 12 or type(attempted) is not int
            or attempted < completed or synthetic.get('completed_fits_by_feature_count') != {'32': completed}):
        raise ValueError('Synthetic verification must include actual fixed32 estimator fits')
    return files.descriptor(root / REPORT, root)


def prepared(root=ROOT, *, require_tests=True):
    root = Path(root).resolve()
    with sources.forbid_model_execution():
        preparation.require_future_outputs_absent(root)
        bundle = sources.load_prepared_sources(root)
        spec, bound = verify_binding(bundle, root)
        if require_tests:
            bound.append(verify_test_report(spec, root))
        files.verify_sources(bound, root)
        references = {
            'execution_specification': spec['execution_specification'],
            'training_dispatcher_binding': files.descriptor(root / SPEC, root),
            'input_guard': files.descriptor(root / GUARD, root),
            'control_manifest': files.descriptor(root / (control.PRIVATE + '/manifest.json'), root),
        }
        if any(item not in bound for item in references.values()):
            raise ValueError('Every artifact reference must be part of the exact source bindings')
        modules()[1].preflight(root=root, bound_sources=bound)
    return bundle, spec, references, bound


def verify_synthetic(root=ROOT):
    """Parse real metadata before tests, but fit and score synthetic fixtures only."""
    root = Path(root).resolve()
    bundle, spec, _, bound = prepared(root, require_tests=False)
    stream = io.StringIO()
    started = time.perf_counter()
    receipt = {'status': 'failed', 'scope': 'synthetic_only', 'real_model_fits': 0}
    receipt_path = preparation._path(root, LAST_RUN, True)
    try:
        suite, identities, counts = _suite()
        from sklearn.linear_model import LogisticRegression
        original_fit = LogisticRegression.fit
        fit_evidence = {'sklearn_fits_attempted': 0, 'sklearn_fits_completed': 0,
                        'completed_fits_by_feature_count': {}}
        def observed_fit(model, X, y, *args, **kwargs):
            fit_evidence['sklearn_fits_attempted'] += 1
            result = original_fit(model, X, y, *args, **kwargs)
            fit_evidence['sklearn_fits_completed'] += 1
            dimension = str(X.shape[1])
            dimensions = fit_evidence['completed_fits_by_feature_count']
            dimensions[dimension] = dimensions.get(dimension, 0) + 1
            return result
        # Tests exercise the same entry point with synthetic adapters. Any accidental
        # attempt to invoke its actual Olist loader is stopped before feature building.
        with patch.object(sources, 'load_prepared_sources', side_effect=RuntimeError('Synthetic suite forbids real source loading')), \
                patch.object(LogisticRegression, 'fit', observed_fit):
            result = unittest.TextTestRunner(stream=stream, verbosity=2, buffer=True).run(suite)
        statistics = {'tests_run': result.testsRun, 'failures': len(result.failures),
                      'errors': len(result.errors), 'skips': len(result.skipped),
                      'expected_failures': len(result.expectedFailures),
                      'unexpected_successes': len(result.unexpectedSuccesses)}
        receipt['tests'] = statistics
        receipt['synthetic_execution'] = fit_evidence
        if result.testsRun != len(identities) or not result.wasSuccessful() or any(
                value for key, value in statistics.items() if key != 'tests_run'):
            raise ValueError('All bound synthetic tests must pass without skips')
        if (fit_evidence['sklearn_fits_completed'] < 12
                or fit_evidence['completed_fits_by_feature_count'] != {'32': fit_evidence['sklearn_fits_completed']}):
            raise ValueError('Verification requires actual fixed32 synthetic estimator fits')
        files.verify_sources(bound, root)
        report = {
            'format_version': 1, 'status': 'passed_synthetic_month_ablation_dispatcher_verification',
            'decision': 'formal_dispatcher_and_private_writer_bound_real_training_deferred',
            'specification': files.descriptor(root / SPEC, root),
            'sources': spec['public_sources'], 'software_versions': spec['software_versions'],
            'source_role_preflight': bundle.summary,
            'tests': {'modules': list(TEST_MODULES), 'counts_by_module': counts,
                      'test_ids': identities, **statistics},
            'synthetic_execution': fit_evidence,
            'scope': {'source_metadata_checked_before_tests': True, 'tests_use_synthetic_adapters_only': True,
                      'real_feature_builds': 0, 'real_model_fits': 0, 'real_predictions': 0,
                      'actual_treatment_selected_C': None, 'new_real_performance_conclusions': 0,
                      'four_feature_refits': 0, 'dashboard': False},
            'accepted_contract': spec['binding_contract'],
            'future_treatment_outputs': preparation.require_future_outputs_absent(root),
            'real_pair_acceptance': 'pending_not_trained',
            'limitations': ['Synthetic fits test execution and publication, not model performance.',
                            'Real three-feature training needs a separate decision.',
                            'Existing event clocks do not verify historical ingestion or score revisions.',
                            'Inspected development months are not an unseen final holdout.'],
            'stage4': spec['stage4'],
        }
        # The historical helper reports its own dispatcher status. Replace only this
        # new report's status; never mutate the frozen parent evidence.
        report['future_treatment_outputs']['training_dispatcher_bound'] = True
        preparation._publish([(preparation._path(root, REPORT), files.json_bytes(report))], bound, root)
        receipt['status'] = 'passed'
        receipt['report'] = files.descriptor(root / REPORT, root)
        return report
    finally:
        receipt['elapsed_seconds'] = round(time.perf_counter() - started, 6)
        receipt['unittest_log'] = stream.getvalue()
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_bytes(files.json_bytes(receipt))


def train(root=ROOT, *, emit=None):
    """Future explicit action. This implementation step never invokes it on real data."""
    root = Path(root).resolve()
    training, artifacts = modules()
    # A missing/stale binding or occupied namespace is a refusal before starting.
    # Do not add a receipt into someone else's existing run or an unverified version.
    bundle, spec, references, bound = prepared(root)
    def verify():
        bundle.verify_stable()
        files.verify_sources(bound, root)
    completed = 0
    try:
        execution = training.execute_training(bundle, spec, emit=emit, verify_sources=verify)
        completed = 12
        return artifacts.publish(execution, references, verify_sources=verify, bound_sources=bound, root=root)
    except Exception as error:
        context = error.context if isinstance(error, training.TrainingStopped) else {
            'phase': 'publication' if completed else 'training_entry', 'outer_fold': None,
            'role': None, 'C': None, 'completed_estimator_fits': completed}
        exception_type = error.cause_type if isinstance(error, training.TrainingStopped) else type(error).__name__
        artifacts.write_failure_receipt(context, exception_type, references, root=root)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--specification-only', action='store_true', help='bind sources/code/schemas without fitting')
    actions.add_argument('--verify-synthetic', action='store_true', help='run bound synthetic tests only')
    actions.add_argument('--check', action='store_true', help='read-only source and successful-test readiness gate')
    actions.add_argument('--train', action='store_true', help='explicit real training; requires a separate user decision')
    args = parser.parse_args(argv)
    if args.specification_only:
        result = freeze()
        print(result['role'])
    elif args.verify_synthetic:
        result = verify_synthetic()
        print(result['status'], 'tests=', result['tests']['tests_run'], 'real_fits=0')
    elif args.check:
        prepared()
        print('passed_dispatcher_readiness_no_training real_fits=0')
    elif args.train:
        result = train(emit=lambda item: print(__import__('json').dumps(item), flush=True))
        print(result['status'])
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
