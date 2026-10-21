"""Verify the three-feature ablation and frozen control with synthetic tests only."""
from __future__ import annotations

import argparse
from copy import deepcopy
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

CODE = 'scripts/verify_review_month_ablation_pipeline.py'
OUTPUT = 'reports/stage5/review_month_ablation_pipeline_verification.json'
LAST_RUN = '.runtime/stage5_review_month_ablation_pipeline/last_run.json'
SPEC = 'reports/stage5/review_month_ablation_specification.json'
AUDIT = 'reports/stage5/review_month_ablation_contract_audit.json'
BASELINE_SPEC = 'reports/stage5/review_baseline_specification.json'
PARENT_SHAS = {
    SPEC: '5ac404e3d66463a571d726f57f9af9d3774d30d7f3d90b4d4e86308f4c2ec9f1',
    AUDIT: '995ab67ebd04d1e677c49c53d663f207782086db51d6d6abe28b38c92c97e094',
}
TEST_MODULES = ('tests.test_review_baseline_pipeline',
                'tests.test_review_month_ablation_pipeline')
IMPLEMENTATION_INPUTS = ('scripts/review_month_ablation_pipeline.py',
                         'tests/test_review_month_ablation_pipeline.py', CODE)


def public_contract(root=ROOT):
    """Pin public ancestors without opening raw files, private guards or scores."""
    root = Path(root).resolve()
    sources = [dataset.descriptor(root / path, root) for path in PARENT_SHAS]
    for source in sources:
        if source['sha256'] != PARENT_SHAS[source['path']]:
            raise ValueError('Frozen month-ablation parent changed: ' + source['path'])
    specification = dataset.read_json(root / SPEC)
    audit = dataset.read_json(root / AUDIT)
    if (audit['specification'] != sources[0] or audit['protocol'] != specification['protocol']
            or audit['allowed_protocol_changes'] != specification['allowed_protocol_changes']):
        raise ValueError('Month-ablation parent binding or policy differs')
    ancestors = [source for source in specification['sources']
                 if source['path'].startswith(('scripts/', 'tests/', 'reports/'))
                 or source['path'] == 'requirements-lock.txt']
    if len(ancestors) != 30 or len(specification['sources']) != 39:
        raise ValueError('Frozen public ancestor roster changed')
    for source in ancestors:
        expected = {name: source[name] for name in ('path', 'bytes', 'sha256')}
        actual = dataset.descriptor(root / source['path'], root)
        if actual != expected:
            raise ValueError('Frozen public ancestor changed: ' + source['path'])
        sources.append(actual)
    baseline = dataset.read_json(root / BASELINE_SPEC)
    expected = deepcopy(baseline['protocol'])
    del expected['features']['categorical']['purchase_month']
    expected['features']['one_hot']['columns'] = 31
    expected['features']['output_columns'] = 32
    expected['features']['output_order'].remove('month_1_through_12')
    expected['features']['primary_order'].remove('purchase_month')
    if expected != specification['protocol']:
        raise ValueError('Policy differs beyond the frozen month removal')
    versions = {'python': platform.python_version()}
    versions.update({name: importlib.metadata.version(name)
                     for name in ('numpy', 'pandas', 'scikit-learn')})
    if versions != specification['software_versions_unchanged'] or versions != baseline['software_versions']:
        raise ValueError('Runtime software differs from the frozen versions')
    sources.extend(dataset.descriptor(root / path, root) for path in IMPLEMENTATION_INPUTS)
    if len(sources) != 35 or len({item['path'] for item in sources}) != 35:
        raise ValueError('Expected 35 distinct public source bindings')
    dataset.verify_sources(sources, root)
    return sources, versions


def test_ids(suite):
    result = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            result.extend(test_ids(item))
        elif isinstance(item, unittest.TestCase):
            identity = item.id()
            if not any(identity.startswith(module + '.') for module in TEST_MODULES):
                raise ValueError('Unexpected test outside the designated synthetic modules')
            result.append(identity)
        else:
            raise ValueError('Unexpected object in synthetic unittest suite')
    return result


def runtime_receipt_path(root=ROOT):
    root = Path(root).resolve()
    path = dataset.safe_output(root / LAST_RUN, '', root, private=True)
    if path.relative_to(root).as_posix() != LAST_RUN or (path.exists() and not path.is_file()):
        raise ValueError('Execution receipt must be an unaliased regular file')
    return path


def verify(root=ROOT, output=None):
    """Exercise both implementations on fixtures; never execute a training CLI."""
    root = Path(root).resolve()
    output_path = dataset.safe_output(output or root / OUTPUT, OUTPUT, root)
    receipt_path = runtime_receipt_path(root)
    if output_path == receipt_path:
        raise ValueError('Public report and private receipt collide')
    started = time.perf_counter()
    stream = io.StringIO()
    receipt = {'format_version': 1, 'status': 'failed', 'test_modules': list(TEST_MODULES),
               'test_ids': [], 'unittest_log': '', 'report_written': False}
    try:
        sources, versions = public_contract(root)
        source_paths = {(root / source['path']).resolve() for source in sources}
        if output_path in source_paths or receipt_path in source_paths:
            raise ValueError('Verification output collides with a public input')
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromNames(TEST_MODULES)
        if loader.errors:
            stream.write('\n'.join(loader.errors))
            raise ValueError('Could not load the designated synthetic unittest modules')
        for module in TEST_MODULES:
            if Path(sys.modules[module].__file__).resolve() != root / (module.replace('.', '/') + '.py'):
                raise ValueError('Loaded synthetic tests from an unexpected file')
        identities = sorted(test_ids(suite))
        receipt['test_ids'] = identities
        if not identities or len(set(identities)) != len(identities):
            raise ValueError('Synthetic suite must contain distinct nonempty tests')
        by_module = {module: sum(identity.startswith(module + '.') for identity in identities)
                     for module in TEST_MODULES}
        if not all(by_module.values()):
            raise ValueError('Both control and treatment must have synthetic coverage')
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
            raise ValueError('Every synthetic test must run with no failure, error or skip')
        dataset.verify_sources(sources, root)
        report = {
            'format_version': 1,
            'status': 'passed_synthetic_month_ablation_pipeline_verification',
            'decision': 'three_feature_implementation_verified_real_training_deferred',
            'sources': sources, 'software_versions': versions,
            'tests': {'modules': list(TEST_MODULES), 'counts_by_module': by_module,
                      **counts, 'test_ids': identities},
            'implementation': {
                'primary_order': ['purchase_dayofweek', 'purchase_hour', 'approval_wait_hours'],
                'one_hot_columns': 31, 'output_columns': 32,
                'control_output_columns': 44,
                'shared_guard_module': 'scripts/review_baseline_pipeline.py',
                'frozen_control_code_unchanged': True,
                'historical_specification_status_fields_unchanged': True,
            },
            'scope': {
                'fixtures': 'synthetic_only_designated_unittest_modules',
                'synthetic_execution': 'both_arms_feature_build_preprocessor_fit_logistic_fit_transform_predict',
                'parent_audits_executed': 0,
                'embedded_raw_or_private_source_bindings_revalidated': False,
                'real_data_rows_processed': 0, 'real_feature_values_built': 0,
                'real_model_fits': 0, 'real_predictions': 0, 'frozen_score_rows_parsed': 0,
                'model_performance_metrics': 0, 'actual_C_selection': 0, 'dashboard': 0,
            },
            'verification': {'public_bound_sources_before_after': len(sources),
                             'frozen_parent_public_contracts_verified': True,
                             'only_five_frozen_protocol_changes': True,
                             'all_discovered_tests_executed': True,
                             'strict_json_exact_readback': True,
                             'elapsed_time_and_unittest_log_public': False},
            'next_step': 'bind_new_execution_sources_and_private_output_version_before_deciding_real_training',
            'protected_stage4': {'status': 'pending_data', 'daily_alert_fraction': 0.1,
                                 'seeds': [11, 29, 42, 73, 101], 'modified': False},
            'limitations': [
                'Synthetic fits verify implementation, not model performance or ingestion/version availability.',
                'Existing H60 and role files were not rebuilt or revalidated against private data in this run.',
                'Future treatment must select C independently by the original inner AP policy.',
                'Future control uses its frozen scores without refitting or reselecting.',
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
        receipt_path.write_bytes(dataset.json_bytes(receipt))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=OUTPUT)
    args = parser.parse_args(argv)
    report = verify(output=ROOT / args.output)
    print(__import__('json').dumps({'status': report['status'], 'tests_run': report['tests']['tests_run'],
                                   'public_source_bindings': len(report['sources']), 'real_model_fits': 0}))


if __name__ == '__main__':
    main()
