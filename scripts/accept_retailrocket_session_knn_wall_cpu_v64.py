"""Seal synthetic entry cases before execution; accept or audit saved evidence.

No production dataset, calibration, telemetry or benchmark command is provided.
Revisions and attempts are immutable; a correction requires another seal/push.
"""
import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'reports/stage12/retailrocket_session_knn_v64_wall_cpu_'
V63 = 'reports/stage12/retailrocket_session_knn_v63_wall_cpu_acceptance_20261116.json'
SUITES = (
    'tests.test_retailrocket_session_knn_wall_cpu_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_layout_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_summary_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_integration_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_sql_v64',
    'tests.test_retailrocket_session_knn_wall_cpu_adapter_v64',
    'tests.test_retailrocket_session_knn_wall_cpu_entry_v64')
METHODS = (
    'scripts/retailrocket_session_knn_wall_cpu_adapter_v64.py',
    'scripts/accept_retailrocket_session_knn_wall_cpu_v64.py',
    'tests/retailrocket_session_knn_wall_cpu_fixture_v64.py',
    *(name.replace('.', '/') + '.py' for name in SUITES if name.endswith('_v64')))
SCOPE = dict(stage='synthetic_entry_and_operation_equivalence',
    fake_boundary_clocks_only=True, actual_entry_code=True,
    synthetic_sql_and_checkpoint_io=True, original_fixed48_runs=0,
    actual_model_decodes=0, new_training=0, new_live_samples=0,
    real_calibration=False, artificial_overhead_benchmark=False, real_entry_overhead=False,
    actual_clock_resolution=None, actual_overhead=None,
    full_v62_A_passed=False, reserved_test='locked', adopt_v46=False,
    pending=['actual_V39_V46_worker_typed_reference_integration',
             'complete_B_D_decision_receipt_logic', 'V62_B_clock_capability',
             'V62_C_artificial_overhead', 'V62_D_real_entry_overhead'])


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
    with local_path(name).open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def names(revision):
    if type(revision) is not int or revision < 1:
        raise ValueError('Positive integer method revision required')
    suffix = f'r{revision}_20261116.json'
    return PREFIX + 'methods_' + suffix, PREFIX + 'acceptance_' + suffix


def source_closure():
    """Hash static repository imports without importing or running their code."""
    pending = list(METHODS) + [name.replace('.', '/') + '.py' for name in SUITES]
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse(local_path(name).read_text(encoding='utf-8-sig'))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
                modules.update(node.module + '.' + alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        for module in modules:
            if module.split('.')[0] not in ('scripts', 'tests'):
                continue
            target = module.replace('.', '/') + '.py'
            if local_path(target).is_file():
                pending.append(target)
    for package in ('scripts/__init__.py', 'tests/__init__.py'):
        if local_path(package).is_file():
            seen.add(package)
    return sorted(seen.difference(METHODS))


def inputs():
    prior = read(V63)
    if prior['status'] != 'v63_minimal_fake_clock_tests_passed_not_full_A':
        raise ValueError('The accepted V63 core is required')
    prior_bindings = [*prior['inputs'], *prior['methods'], prior['seal']]
    verify(prior_bindings)
    paths = {V63, *(row['path'] for row in prior_bindings), *source_closure()}
    return [describe(path) for path in sorted(paths)]


def declared_tests():
    tests = []
    for module in SUITES:
        tree = ast.parse(local_path(module.replace('.', '/') + '.py').read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                        tests.append(f'{module}.{node.name}.{method.name}')
    if not tests or len(tests) != len(set(tests)):
        raise ValueError('Unique named synthetic tests required')
    return sorted(tests)


def freeze(revision):
    seal, _ = names(revision)
    value = dict(status='v64_synthetic_methods_sealed_not_yet_tested', revision=revision,
        scope=SCOPE, inputs=inputs(), methods=[describe(name) for name in METHODS],
        suites=list(SUITES), declared_tests=declared_tests())
    write_new(seal, value)
    print(dict(seal=seal, declared_tests=len(value['declared_tests']), tests_run=0))


def sealed(revision):
    seal, _ = names(revision)
    value = read(seal)
    if (value['status'] != 'v64_synthetic_methods_sealed_not_yet_tested'
            or type(value['revision']) is not int or value['revision'] != revision
            or value['scope'] != SCOPE or value['inputs'] != inputs()
            or value['methods'] != [describe(name) for name in METHODS]
            or value['suites'] != list(SUITES) or value['declared_tests'] != declared_tests()):
        raise ValueError('Only the unchanged sealed V64 revision may execute')
    return value


def published(seal, frozen):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT)
    head = git('rev-parse', 'HEAD').decode().strip()
    if (git('branch', '--show-current').decode().strip() != 'main'
            or git('rev-parse', 'refs/remotes/origin/main').decode().strip() != head):
        raise ValueError('Seal commit must be on main and match the pushed tracking ref')
    for row in [describe(seal), *frozen['methods']]:
        data = git('show', f"HEAD:{row['path']}")
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Methods must be committed before acceptance: ' + row['path'])
    return head


def test_ids(suite):
    if isinstance(suite, unittest.TestSuite):
        return [name for child in suite for name in test_ids(child)]
    return [suite.id()]


def accept(revision):
    seal, acceptance = names(revision)
    if local_path(acceptance).exists():
        raise FileExistsError('Acceptance receipts cannot be overwritten')
    frozen = sealed(revision)
    seal_commit = published(seal, frozen)
    folder = ROOT / 'shop-mysql-runtime/verification' / ('v64-synthetic-' + uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    # Also reserve failed/crashed attempts: the same seal must not be retried.
    write_new(f'shop-mysql-runtime/verification/v64-wall-cpu-r{revision}-attempt.json',
        dict(seal=describe(seal), seal_commit=seal_commit, folder=folder.relative_to(ROOT).as_posix()))
    log = StringIO()
    with redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        loaded = sorted(test_ids(suite))
        if loaded != frozen['declared_tests']:
            result = unittest.TestResult()
            result.errors.append(('sealed_test_manifest', 'Loaded cases differ; no test body executed'))
            print('Loaded cases differ from the sealed manifest; tests_run=0')
            print(loaded)
        else:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    log_name = (folder / 'tests.log').relative_to(ROOT).as_posix()
    local_path(log_name).write_text(log.getvalue(), encoding='utf-8')
    success = (loaded == frozen['declared_tests'] and result.wasSuccessful()
               and not result.skipped and result.testsRun == len(loaded))
    evidence = {name: getattr(sys.modules.get(name), 'EVIDENCE', [])
                for name in SUITES if name.endswith('_v64')}
    attempt = dict(status='passed' if success else 'failed', revision=revision,
        seal=describe(seal), seal_commit=seal_commit, loaded_tests=loaded,
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), log=describe(log_name), evidence=evidence, scope=SCOPE)
    attempt_name = (folder / 'attempt.json').relative_to(ROOT).as_posix()
    write_new(attempt_name, attempt)
    if not success:
        print(log.getvalue())
        print(dict(private_attempt=attempt_name))
        raise ValueError('Synthetic acceptance failed; attempt preserved, correction requires a new seal')
    sealed(revision)
    value = dict(status='v64_synthetic_entry_tests_passed_not_full_A', revision=revision,
        seal=describe(seal), seal_commit=seal_commit, inputs=frozen['inputs'], methods=frozen['methods'],
        suites=list(SUITES), passed_tests=loaded, tests_run=result.testsRun,
        failures=0, errors=0, skipped=0, evidence=evidence,
        log=describe(log_name), attempt=describe(attempt_name), scope=SCOPE)
    write_new(acceptance, value)
    print(dict(acceptance=acceptance, tests=result.testsRun, evidence=evidence, scope=SCOPE))


def audit(revision):
    seal, acceptance = names(revision)
    frozen, value = sealed(revision), read(acceptance)
    if (value['status'] != 'v64_synthetic_entry_tests_passed_not_full_A'
            or type(value['revision']) is not int or value['revision'] != revision
            or value['scope'] != SCOPE or value['seal'] != describe(seal)
            or value['inputs'] != frozen['inputs'] or value['methods'] != frozen['methods']
            or value['suites'] != list(SUITES) or value['passed_tests'] != frozen['declared_tests']
            or type(value['tests_run']) is not int or value['tests_run'] != len(frozen['declared_tests'])
            or any(type(value[k]) is not int or value[k] != 0 for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('Acceptance differs from the immutable method revision')
    verify([value['log'], value['attempt']])
    for row in [value['seal'], *value['methods']]:
        data = subprocess.check_output(['git', 'show', f"{value['seal_commit']}:{row['path']}"], cwd=ROOT)
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('The recorded seal commit differs from accepted source bytes')
    attempt = read(value['attempt']['path'])
    if (attempt['status'] != 'passed' or attempt['loaded_tests'] != value['passed_tests']
            or any(attempt[k] != value[k] for k in ('revision', 'seal', 'seal_commit', 'tests_run',
                'failures', 'errors', 'skipped', 'log', 'evidence', 'scope'))):
        raise ValueError('Private attempt differs from public acceptance')
    log = local_path(value['log']['path']).read_text(encoding='utf-8')
    if sum(line.endswith(' ... ok') for line in log.splitlines()) != value['tests_run']:
        raise ValueError('Successful named test count differs from the preserved log')
    print(dict(status='v64_saved_synthetic_acceptance_audited', tests=value['tests_run'], tests_rerun=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true')
    group.add_argument('--acceptance', action='store_true')
    group.add_argument('--audit', action='store_true')
    parser.add_argument('--revision', type=int, default=1)
    arguments = parser.parse_args()
    action = freeze if arguments.freeze else accept if arguments.acceptance else audit
    action(arguments.revision)


if __name__ == '__main__':
    main()
