"""Seal methods, run only V63 injected-clock tests, or audit the saved receipt.

There is intentionally no calibration, benchmark, model or real-entry command.
The unittest runner's elapsed time describes test execution, not clock overhead.
"""
import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'reports/stage12/retailrocket_session_knn_v63_wall_cpu_'
SEAL = PREFIX + 'methods_20261116.json'
ACCEPTANCE = PREFIX + 'acceptance_20261116.json'
SPEC = 'reports/stage12/retailrocket_session_knn_v62_wall_cpu_specification_20261116.json'
SUITES = ('tests.test_retailrocket_session_knn_wall_cpu_v63',
          'tests.test_retailrocket_session_knn_wall_cpu_layout_v63',
          'tests.test_retailrocket_session_knn_wall_cpu_summary_v63',
          'tests.test_retailrocket_session_knn_wall_cpu_integration_v63')
METHODS = ('scripts/retailrocket_session_knn_wall_cpu_v63.py',
           'scripts/retailrocket_session_knn_wall_cpu_layout_v63.py',
           'scripts/retailrocket_session_knn_wall_cpu_summary_v63.py',
           'scripts/accept_retailrocket_session_knn_wall_cpu_v63.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
SCOPE = dict(stage='minimal_boundary_and_fake_clock_acceptance_only',
    fake_clocks_only=True, actual_entry_adapter=False, full_v62_A_passed=False,
    real_calibration=False, artificial_workload_benchmark=False, real_entry_runs=False,
    new_experiments=0, new_queries=0, new_decodes=0, new_training=0, new_live_samples=0,
    actual_clock_resolution=None, actual_overhead=None, reserved_test='locked', adopt_v46=False,
    pending=['actual_entry_binding_and_setup_lifecycle', 'full_payload_and_checkpoint_equivalence',
             'SQL_lazy_fetch_watch_fault_equivalence', 'V39_V46_call_local_adapter_equivalence',
             'V62_B_clock_capability', 'V62_C_artificial_overhead', 'V62_D_real_entry_overhead'])


def local_path(name):
    path = (ROOT / name).resolve()
    path.relative_to(ROOT)
    return path


def read(name):
    return json.loads(local_path(name).read_bytes())


def describe(name):
    data = local_path(name).read_bytes()
    return dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def verify(records):
    for row in records:
        if row != describe(row['path']):
            raise ValueError('Sealed bytes or SHA256 changed: ' + row['path'])


def write_new(name, value):
    path = local_path(name)
    with path.open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def inputs():
    specification = read(SPEC)
    if specification['status'] != 'specification_only_not_implemented_or_measured':
        raise ValueError('The original V62 specification is required')
    records = [describe(SPEC), specification['spec_document'], *specification['source_bindings']]
    verify(records)
    return records


def declared_tests():
    """Static enumeration before execution; importing test modules is unnecessary."""
    names = []
    for module in SUITES:
        tree = ast.parse(local_path(module.replace('.', '/') + '.py').read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                        names.append(f'{module}.{node.name}.{method.name}')
    if not names or len(set(names)) != len(names):
        raise ValueError('Unique named fake-clock tests required')
    return sorted(names)


def freeze():
    value = dict(status='v63_minimal_methods_sealed_not_yet_tested',
        scope=SCOPE, inputs=inputs(), methods=[describe(name) for name in METHODS],
        suites=list(SUITES), declared_tests=declared_tests())
    write_new(SEAL, value)
    print(dict(seal=SEAL, declared_tests=len(value['declared_tests']), tests_run=0,
               real_calibration=False, new_experiments=0))


def sealed():
    value = read(SEAL)
    if (value['status'] != 'v63_minimal_methods_sealed_not_yet_tested'
            or value['scope'] != SCOPE or value['suites'] != list(SUITES)
            or value['methods'] != [describe(name) for name in METHODS]
            or value['inputs'] != inputs() or value['declared_tests'] != declared_tests()):
        raise ValueError('Only the unchanged sealed V63 method set may run')
    verify([*value['methods'], *value['inputs']])
    return value


def _test_ids(suite):
    if isinstance(suite, unittest.TestSuite):
        return [name for child in suite for name in _test_ids(child)]
    return [suite.id()]


def accept():
    if local_path(ACCEPTANCE).exists():
        raise FileExistsError('The V63 acceptance receipt is immutable')
    frozen = sealed()
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    names = sorted(_test_ids(suite))
    if names != frozen['declared_tests']:
        raise ValueError('Loaded tests differ from the sealed named cases')
    folder = ROOT / 'shop-mysql-runtime/verification' / ('v63-fake-clock-' + uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    log = StringIO()
    with redirect_stdout(log), redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    log_name = (folder / 'tests.log').relative_to(ROOT).as_posix()
    local_path(log_name).write_text(log.getvalue(), encoding='utf-8')
    success = result.wasSuccessful() and not result.skipped and result.testsRun == len(names)
    attempt = dict(status='passed' if success else 'failed', seal=describe(SEAL),
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), log=describe(log_name), scope=SCOPE)
    attempt_name = (folder / 'attempt.json').relative_to(ROOT).as_posix()
    write_new(attempt_name, attempt)
    if not success:
        print(log.getvalue())
        raise ValueError('Fake-clock acceptance failed; private attempt was preserved')
    sealed()  # Fail closed if any source changed while the suite was running.
    value = dict(status='v63_minimal_fake_clock_tests_passed_not_full_A',
        seal=describe(SEAL), methods=frozen['methods'], inputs=frozen['inputs'],
        suites=list(SUITES), passed_tests=names, tests_run=result.testsRun,
        failures=0, errors=0, skipped=0, log=describe(log_name), attempt=describe(attempt_name), scope=SCOPE)
    write_new(ACCEPTANCE, value)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, full_v62_A_passed=False,
               real_calibration=False, new_experiments=0))


def audit():
    frozen, value = sealed(), read(ACCEPTANCE)
    if (value['status'] != 'v63_minimal_fake_clock_tests_passed_not_full_A'
            or value['seal'] != describe(SEAL) or value['scope'] != SCOPE
            or value['methods'] != frozen['methods'] or value['inputs'] != frozen['inputs']
            or value['suites'] != list(SUITES) or value['passed_tests'] != frozen['declared_tests']
            or value['tests_run'] != len(frozen['declared_tests'])
            or any(type(value[key]) is not int or value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('The immutable fake-clock receipt differs from the sealed methods')
    verify([value['log'], value['attempt']])
    attempt = read(value['attempt']['path'])
    if (attempt['status'] != 'passed' or attempt['seal'] != value['seal']
            or attempt['scope'] != SCOPE or attempt['log'] != value['log']
            or any(attempt[key] != value[key] for key in ('tests_run', 'failures', 'errors', 'skipped'))):
        raise ValueError('The private attempt differs from the public receipt')
    print(dict(status='v63_saved_fake_clock_acceptance_audited', tests=value['tests_run'],
               tests_rerun=0, new_experiments=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true')
    group.add_argument('--acceptance', action='store_true')
    group.add_argument('--audit', action='store_true')
    arguments = parser.parse_args()
    if arguments.freeze:
        freeze()
    elif arguments.acceptance:
        accept()
    else:
        audit()


if __name__ == '__main__':
    main()
