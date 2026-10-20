"""Verify the guarded review pipeline using synthetic unit tests only."""
from __future__ import annotations

import argparse
import importlib.metadata
import io
from pathlib import Path
import platform
import sys
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import freeze_review_dataset as dataset

CODE = 'scripts/verify_review_pipeline.py'
OUTPUT = 'reports/stage5/review_pipeline_verification.json'
LAST_RUN = '.runtime/stage5_review_pipeline_verification/last_run.json'
TEST_MODULE = 'tests.test_review_baseline_pipeline'
BASELINE_SPEC = 'reports/stage5/review_baseline_specification.json'
BASELINE_AUDIT = 'reports/stage5/review_baseline_contract_audit.json'
PARENT_SHAS = {
    BASELINE_SPEC: '202de6045b7dcee7b00c068670fff44b5cac813a838d3d5ad15d620e18e721aa',
    BASELINE_AUDIT: '204c8d2b09327848fe9367e75efae5b37093a39164ccdb4b69f34ef396e4c16a',
}
PUBLIC_INPUTS = (
    'requirements-lock.txt',
    'scripts/freeze_review_dataset.py',
    'scripts/audit_review_baseline_contract.py',
    'reports/stage5/review_dataset_specification.json',
    'reports/stage5/review_dataset_audit.json',
    BASELINE_SPEC,
    BASELINE_AUDIT,
    'scripts/review_baseline_pipeline.py',
    'tests/test_review_baseline_pipeline.py',
    CODE,
)


def public_contract(root=ROOT):
    """Verify only these ten public files; never follow embedded raw paths."""
    root = Path(root).resolve()
    sources = [dataset.descriptor(root / path, root) for path in PUBLIC_INPUTS]
    if len(sources) != 10 or len({source['path'] for source in sources}) != 10:
        raise ValueError('Expected exactly ten distinct public source bindings')
    by_path = {source['path']: source for source in sources}
    for path, expected in PARENT_SHAS.items():
        if by_path[path]['sha256'] != expected:
            raise ValueError('Frozen parent baseline contract changed: ' + path)
    specification = dataset.read_json(root / BASELINE_SPEC)
    audit = dataset.read_json(root / BASELINE_AUDIT)
    if audit['specification'] != by_path[BASELINE_SPEC]:
        raise ValueError('Parent audit does not bind the actual baseline specification')
    if specification['protocol'] != audit['protocol']:
        raise ValueError('Parent baseline protocol differs between public files')
    # The parent also pins these public ancestors. Do not hash or load its raw
    # source paths, private manifest, receipt, labels, or split-membership CSV.
    inherited = {source['path']: source for source in specification['sources']}
    for path in PUBLIC_INPUTS:
        if path in inherited and by_path[path] != {
                name: inherited[path][name] for name in ('path', 'bytes', 'sha256')}:
            raise ValueError('Public ancestor differs from the frozen parent: ' + path)
    expected_versions = specification['software_versions']
    actual = {'python': platform.python_version()}
    actual.update({name: importlib.metadata.version(name)
                   for name in ('numpy', 'pandas', 'scikit-learn')})
    if actual != expected_versions or audit['software_versions'] != expected_versions:
        raise ValueError('Runtime software differs from the frozen baseline versions')
    dataset.verify_sources(sources, root)
    return sources, actual


def test_ids(suite):
    """Enumerate the standard unittest suite before running or consuming it."""
    result = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            result.extend(test_ids(item))
        elif isinstance(item, unittest.TestCase):
            identity = item.id()
            if not identity.startswith(TEST_MODULE + '.'):
                raise ValueError('Unexpected test outside the designated synthetic module')
            result.append(identity)
        else:
            raise ValueError('Unexpected object in synthetic unittest suite')
    return result


def runtime_receipt_path(root=ROOT):
    root = Path(root).resolve()
    path = dataset.safe_output(root / LAST_RUN, '', root, private=True)
    if path.relative_to(root).as_posix() != LAST_RUN:
        raise ValueError('Execution receipt must not resolve to an aliased file')
    if path.exists() and not path.is_file():
        raise ValueError('Execution receipt path is not a regular file')
    return path


def verify(root=ROOT, output=None):
    """Run only the named synthetic tests and publish deterministic aggregates."""
    root = Path(root).resolve()
    output_path = dataset.safe_output(output or root / OUTPUT, OUTPUT, root)
    receipt_path = runtime_receipt_path(root)
    if output_path == receipt_path:
        raise ValueError('Public verification and private execution receipt collide')
    source_paths = {(root / path).resolve() for path in PUBLIC_INPUTS}
    if output_path in source_paths or receipt_path in source_paths:
        raise ValueError('Verification output collides with a public input')
    started = time.perf_counter()
    stream = io.StringIO()
    receipt = {'format_version': 1, 'status': 'failed', 'test_module': TEST_MODULE,
               'test_ids': [], 'unittest_log': '', 'report_written': False}
    try:
        sources, versions = public_contract(root)
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromName(TEST_MODULE)
        if loader.errors:
            stream.write('\n'.join(loader.errors))
            raise ValueError('Could not load the designated synthetic unittest module')
        module_path = Path(sys.modules[TEST_MODULE].__file__).resolve()
        if module_path != root / 'tests/test_review_baseline_pipeline.py':
            raise ValueError('Loaded synthetic tests from an unexpected file')
        identities = sorted(test_ids(suite))
        receipt['test_ids'] = identities
        if not identities or len(set(identities)) != len(identities):
            raise ValueError('Synthetic test suite must contain distinct nonempty tests')
        tests_started = time.perf_counter()
        result = unittest.TextTestRunner(stream=stream, verbosity=2, buffer=True).run(suite)
        receipt['test_elapsed_seconds'] = round(time.perf_counter() - tests_started, 6)
        counts = {'tests_run': result.testsRun, 'failures': len(result.failures),
                  'errors': len(result.errors), 'skips': len(result.skipped),
                  'expected_failures': len(result.expectedFailures),
                  'unexpected_successes': len(result.unexpectedSuccesses)}
        receipt['unittest_counts'] = counts
        if (result.testsRun != len(identities) or not result.wasSuccessful()
                or any(counts[name] for name in counts if name != 'tests_run')):
            raise ValueError('Synthetic suite must run every test with no failure, error, or skip')
        dataset.verify_sources(sources, root)
        report = {
            'format_version': 1,
            'status': 'passed_synthetic_pipeline_contract_verification',
            'decision': 'implementation_synthetic_checks_passed_real_data_training_not_run',
            'sources': sources,
            'software_versions': versions,
            'tests': {'module': TEST_MODULE, **counts, 'test_ids': identities},
            'scope': {
                'fixtures': 'synthetic_only_designated_unittest_module',
                'synthetic_execution': 'feature_build_scaler_and_logistic_fits_probability_calls_exercised_by_contract_tests',
                'parent_audits_executed': 0,
                'embedded_raw_or_private_source_bindings_revalidated': False,
                'real_data_rows_processed': 0, 'real_feature_values_built': 0,
                'real_model_fits': 0, 'real_predictions': 0,
                'model_performance_metrics': 0, 'actual_C_selection': 0,
                'dashboard': 0,
            },
            'verification': {'public_bound_sources_before_after': len(sources),
                             'frozen_parent_public_contracts_verified': True,
                             'all_discovered_tests_executed': True,
                             'strict_json_exact_readback': True,
                             'elapsed_time_and_unittest_log_public': False},
            'protected_stage4': {'status': 'pending_data', 'daily_alert_fraction': 0.1,
                                 'seeds': [11, 29, 42, 73, 101], 'modified': False},
            'limitations': [
                'Synthetic tests do not measure model performance or prove real ingestion/version availability.',
                'The frozen H60 dataset and baseline policy are public ancestors, not re-executed data audits.',
                'No real-data builder, fit, prediction, model selection, or Dashboard run is performed here.',
                'Previously inspected development months remain development data, not an unseen final test.',
            ],
        }
        data = dataset.json_bytes(report)
        dataset.immutable_preflight(output_path, data)
        dataset.verify_sources(sources, root)
        dataset.immutable_write(output_path, data)
        if output_path.read_bytes() != data or dataset.read_json(output_path) != report:
            raise ValueError('Verification report did not round-trip exactly')
        dataset.verify_sources(sources, root)
        receipt.update({'status': 'passed', 'report_written': True,
                        'report': dataset.descriptor(output_path, root),
                        'public_source_bindings_verified': len(sources)})
        return report
    except Exception:
        receipt['failure_traceback'] = traceback.format_exc()
        raise
    finally:
        receipt['elapsed_seconds'] = round(time.perf_counter() - started, 6)
        receipt['unittest_log'] = stream.getvalue()
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        # This private execution-state receipt intentionally records the latest
        # run, while the public report remains immutable and timing independent.
        receipt_path.write_bytes(dataset.json_bytes(receipt))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=OUTPUT)
    args = parser.parse_args(argv)
    report = verify(output=ROOT / args.output)
    receipt = dataset.read_json(runtime_receipt_path())
    print(__import__('json').dumps({'status': report['status'],
                                   'tests_run': report['tests']['tests_run'],
                                   'public_source_bindings': len(report['sources']),
                                   'elapsed_seconds': receipt['elapsed_seconds'],
                                   'real_model_fits': 0}))


if __name__ == '__main__':
    main()
