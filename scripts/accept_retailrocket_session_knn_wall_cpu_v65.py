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
PREFIX = 'reports/stage12/retailrocket_session_knn_v65_wall_cpu_'
PRIOR = 'reports/stage12/retailrocket_session_knn_v64_wall_cpu_acceptance_r1_20261116.json'
SPEC = 'reports/stage12/retailrocket_session_knn_v62_wall_cpu_specification_20261116.json'
SUITES = (
    'tests.test_retailrocket_session_knn_wall_cpu_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_layout_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_summary_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_integration_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_sql_v64',
    'tests.test_retailrocket_session_knn_wall_cpu_adapter_v64',
    'tests.test_retailrocket_session_knn_wall_cpu_entry_v64',
    'tests.test_retailrocket_session_knn_wall_cpu_typed_v65',
    'tests.test_retailrocket_session_knn_wall_cpu_decision_v65')
METHODS = tuple(sorted(path.relative_to(ROOT).as_posix()
    for directory in ('scripts', 'tests')
    for path in (ROOT / directory).glob('*retailrocket_session_knn_wall_cpu*v65.py')))
SCOPE = dict(stage='synthetic_typed_worker_and_complete_A16_acceptance',
    fake_boundary_clocks_only=True, actual_typed_worker_code=True,
    synthetic_sql_checkpoint_and_typed_decode=True, original_fixed48_runs=0,
    production_model_decodes=0, new_training=0, new_live_samples=0,
    real_calibration=False, artificial_overhead_benchmark=False, real_entry_overhead=False,
    actual_clock_resolution=None, actual_overhead=None,
    reserved_test='locked', adopt_v46=False,
    decision_evaluation='provided_records_only_not_measurement',
    pending_measurement=['V62_B_clock_capability', 'V62_C_artificial_overhead',
                         'V62_D_real_entry_overhead'])

# Exact named cases or whole sealed suites; every required A category is mapped.
CORE = 'tests.test_retailrocket_session_knn_wall_cpu_v63.'
LAYOUT = 'tests.test_retailrocket_session_knn_wall_cpu_layout_v63.'
INTEGRATION = 'tests.test_retailrocket_session_knn_wall_cpu_integration_v63.'
ENTRY = 'tests.test_retailrocket_session_knn_wall_cpu_entry_v64.'
GUARD = 'tests.test_retailrocket_session_knn_wall_cpu_adapter_v64.'
SQL = 'tests.test_retailrocket_session_knn_wall_cpu_sql_v64.'
COVERAGE_SELECTORS = {
    'read_order_and_body_once': (CORE+'BoundaryTests.test_read_order_and_legacy_return_keep_raw_integers',
        CORE+'BoundaryTests.test_no_buffer_write_or_validation_between_clock_reads',
        CORE+'BoundaryTests.test_successful_body_runs_once_and_preserves_return_identity'),
    'bracket_and_signed_residual': (CORE+'BoundaryTests.test_all_signed_formulas_with_unequal_brackets',),
    'integer_precision_and_zero_cpu': (CORE+'BoundaryTests.test_large_clock_origin_does_not_roundtrip_through_float',
        CORE+'BoundaryTests.test_zero_clock_advances_are_legal'),
    'negative_residual_and_clock_backwards': (CORE+'BoundaryTests.test_all_signed_formulas_with_unequal_brackets',
        CORE+'BoundaryTests.test_clock_backwards_and_overlap_fail_closed'),
    'missing_duplicate_order_types': (CORE+'BoundaryTests.test_bad_numeric_types_are_rejected_without_fake_zero',
        CORE+'SpanTreeTests.test_missing_duplicate_or_reordered_endpoints_rejected',
        GUARD+'BoundaryAdapterGuardTests.test_begin_rejects_count_bool_float_and_identity_type_aliases'),
    'thread_parent_overlap': (CORE+'BoundaryTests.test_thread_change_within_or_between_boundaries_is_rejected',
        CORE+'SpanTreeTests.test_wrong_parent_cycle_child_outside_and_sibling_overlap_rejected',
        CORE+'SpanTreeTests.test_mixed_recording_or_thread_registry_is_rejected'),
    'shared_boundaries_and_conservation': (CORE+'SpanTreeTests.test_shared_seven_segments_telescope_without_adding_parent_twice',
        LAYOUT+'LayoutTests.test_shared_rank_mark_ids_and_parent_layers_preserve_wrapper_gaps'),
    'fresh48_identity_and_counts': (LAYOUT+'LayoutTests.test_complete_counts_original_identity_and_setup_tail_scope',
        ENTRY+'EntryAcceptanceTests.test_full_v39_v27_v22_entry_outputs_ledger_and_route'),
    'setup_tail_wrapper_scope': (CORE+'SpanTreeTests.test_outer_wrapper_and_gaps_remain_unassigned_not_wait',
        INTEGRATION+'BoundaryLayoutIntegrationTests.test_all_725_fake_points_bind_578_spans_and_keep_wrapper_remainder'),
    'incomplete_skip_resume': (LAYOUT+'LayoutTests.test_partial_trace_must_be_prefix_not_skipped_or_resumed',
        GUARD+'BoundaryAdapterGuardTests.test_missing_tail_cannot_publish_complete_or_invent_boundaries'),
    'original_exception_cleanup': (CORE+'BoundaryTests.test_body_exception_and_cleanup_survive_secondary_timer_failure',
        ENTRY+'EntryAcceptanceTests.test_failure_prefix_exception_identity_trace_and_cleanup_match'),
    'off_mode_no_extra_probe': (CORE+'BoundaryTests.test_off_mode_runs_original_body_and_has_no_diagnostic_recorder',
        GUARD+'BoundaryAdapterGuardTests.test_original_mode_uses_only_legacy_clock_and_has_no_diagnostic_state',
        'tests.test_retailrocket_session_knn_wall_cpu_typed_v65'),
    'full_payload_workload_ledger_equivalence': (ENTRY+'EntryAcceptanceTests.test_full_v39_v27_v22_entry_outputs_ledger_and_route',
        'tests.test_retailrocket_session_knn_wall_cpu_typed_v65'),
    'sql_lazy_eof_watch_fault_equivalence': ('tests.test_retailrocket_session_knn_wall_cpu_sql_v64',
        ENTRY+'EntryAcceptanceTests.test_failure_prefix_exception_identity_trace_and_cleanup_match'),
    'call_local_namespace_and_decoder_isolation': (SQL+'SQLBoundaryAdapterTests.test_invocation_local_clone_keeps_code_and_independent_clock_namespaces',
        'tests.test_retailrocket_session_knn_wall_cpu_typed_v65'),
    'statistics_schedule_missing_failure_fixtures': ('tests.test_retailrocket_session_knn_wall_cpu_summary_v63',
        'tests.test_retailrocket_session_knn_wall_cpu_decision_v65')}



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
    prior = read(PRIOR)
    if prior['status'] != 'v64_synthetic_entry_tests_passed_not_full_A':
        raise ValueError('The accepted V64 entry and V63 core are required')
    prior_bindings = [*prior['inputs'], *prior['methods'], prior['seal']]
    verify(prior_bindings)
    paths = {PRIOR, *(row['path'] for row in prior_bindings), *source_closure()}
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


def coverage(tests):
    required = read(SPEC)['acceptance_A_required_categories']
    if list(COVERAGE_SELECTORS) != required:
        raise ValueError('Every original V62 A category must be mapped in order')
    result = {}
    for category, selectors in COVERAGE_SELECTORS.items():
        selected = set()
        for selector in selectors:
            matches = {name for name in tests if name == selector or name.startswith(selector + '.')}
            if not matches:
                raise ValueError('Missing sealed case for A category: ' + category + ': ' + selector)
            selected.update(matches)
        result[category] = sorted(selected)
    return result


def artifact_records(evidence):
    records = {}
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'artifacts':
                    if type(child) is not list:
                        raise ValueError('Synthetic artifacts must be an explicit descriptor list')
                    for row in child:
                        if (type(row) is not dict or set(row) != {'path', 'bytes', 'sha256'}
                                or type(row['path']) is not str
                                or not row['path'].startswith('shop-mysql-runtime/verification/')
                                or type(row['bytes']) is not int or row['bytes'] < 0
                                or type(row['sha256']) is not str or len(row['sha256']) != 64
                                or any(c not in '0123456789abcdef' for c in row['sha256'])):
                            raise ValueError('Explicit private synthetic artifact descriptor required')
                        local_path(row['path']).relative_to((ROOT / 'shop-mysql-runtime/verification').resolve())
                        if row['path'] in records and records[row['path']] != row:
                            raise ValueError('Conflicting synthetic artifact descriptors')
                        records[row['path']] = dict(row)
                else:
                    visit(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                visit(child)
    visit(evidence)
    return [records[name] for name in sorted(records)]


def freeze(revision):
    seal, _ = names(revision)
    value = dict(status='v65_typed_and_decision_methods_sealed_not_yet_tested', revision=revision,
        scope=SCOPE, inputs=inputs(), methods=[describe(name) for name in METHODS],
        suites=list(SUITES), declared_tests=declared_tests(),
        acceptance_A_coverage=coverage(declared_tests()), full_v62_A_passed=False)
    write_new(seal, value)
    print(dict(seal=seal, declared_tests=len(value['declared_tests']), tests_run=0))


def sealed(revision):
    seal, _ = names(revision)
    value = read(seal)
    if (value['status'] != 'v65_typed_and_decision_methods_sealed_not_yet_tested'
            or type(value['revision']) is not int or value['revision'] != revision
            or value['scope'] != SCOPE or value['inputs'] != inputs()
            or value['methods'] != [describe(name) for name in METHODS]
            or value['suites'] != list(SUITES) or value['declared_tests'] != declared_tests()
            or value['acceptance_A_coverage'] != coverage(declared_tests())
            or value['full_v62_A_passed'] is not False):
        raise ValueError('Only the unchanged sealed V65 revision may execute')
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
    folder = ROOT / 'shop-mysql-runtime/verification' / ('v65-synthetic-' + uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    # Also reserve failed/crashed attempts: the same seal must not be retried.
    write_new(f'shop-mysql-runtime/verification/v65-wall-cpu-r{revision}-attempt.json',
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
                for name in SUITES if name.endswith('_v65')}
    artifacts, postflight_error = [], None
    try:
        artifacts = artifact_records(evidence)
        if success:
            if not artifacts or any(not rows for rows in evidence.values()):
                raise ValueError('Passing new suites must retain summaries and synthetic artifacts')
            verify(artifacts)
            sealed(revision)
    except Exception as error:
        postflight_error = dict(type=type(error).__name__, message=str(error))
        success = False
    attempt = dict(status='passed' if success else 'failed', revision=revision,
        seal=describe(seal), seal_commit=seal_commit, loaded_tests=loaded,
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), log=describe(log_name), evidence=evidence, artifacts=artifacts,
        postflight_error=postflight_error, scope=SCOPE)
    attempt_name = (folder / 'attempt.json').relative_to(ROOT).as_posix()
    write_new(attempt_name, attempt)
    if not success:
        print(log.getvalue())
        print(dict(private_attempt=attempt_name, postflight_error=postflight_error))
        raise ValueError('Synthetic acceptance failed; attempt preserved, correction requires a new seal')
    value = dict(status='v65_synthetic_full_A_tests_passed_not_live_B_C_D', revision=revision,
        seal=describe(seal), seal_commit=seal_commit, inputs=frozen['inputs'], methods=frozen['methods'],
        acceptance_A_coverage=frozen['acceptance_A_coverage'], full_v62_A_passed=True,
        suites=list(SUITES), passed_tests=loaded, tests_run=result.testsRun,
        failures=0, errors=0, skipped=0, evidence=evidence, artifacts=artifacts,
        log=describe(log_name), attempt=describe(attempt_name), scope=SCOPE)
    write_new(acceptance, value)
    print(dict(acceptance=acceptance, tests=result.testsRun, artifacts=len(artifacts),
               full_v62_A_passed=True, real_B_C_D_executed=False))


def audit(revision):
    seal, acceptance = names(revision)
    frozen, value = sealed(revision), read(acceptance)
    if (value['status'] != 'v65_synthetic_full_A_tests_passed_not_live_B_C_D'
            or type(value['revision']) is not int or value['revision'] != revision
            or value['scope'] != SCOPE or value['seal'] != describe(seal)
            or value['acceptance_A_coverage'] != frozen['acceptance_A_coverage']
            or value['full_v62_A_passed'] is not True
            or value['inputs'] != frozen['inputs'] or value['methods'] != frozen['methods']
            or value['suites'] != list(SUITES) or value['passed_tests'] != frozen['declared_tests']
            or type(value['tests_run']) is not int or value['tests_run'] != len(frozen['declared_tests'])
            or any(type(value[k]) is not int or value[k] != 0 for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('Acceptance differs from the immutable method revision')
    if value['artifacts'] != artifact_records(value['evidence']):
        raise ValueError('Synthetic artifact inventory differs from saved evidence')
    verify([value['log'], value['attempt'], *value['artifacts']])
    for row in [value['seal'], *value['methods']]:
        data = subprocess.check_output(['git', 'show', f"{value['seal_commit']}:{row['path']}"], cwd=ROOT)
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('The recorded seal commit differs from accepted source bytes')
    attempt = read(value['attempt']['path'])
    if (attempt['status'] != 'passed' or attempt['postflight_error'] is not None
            or attempt['loaded_tests'] != value['passed_tests']
            or any(attempt[k] != value[k] for k in ('revision', 'seal', 'seal_commit', 'tests_run',
                'failures', 'errors', 'skipped', 'log', 'evidence', 'artifacts', 'scope'))):
        raise ValueError('Private attempt differs from public acceptance')
    reservation = read(f'shop-mysql-runtime/verification/v65-wall-cpu-r{revision}-attempt.json')
    if reservation != dict(seal=value['seal'], seal_commit=value['seal_commit'],
                           folder=Path(value['attempt']['path']).parent.as_posix()):
        raise ValueError('The unique attempt reservation differs from the accepted run')
    log = local_path(value['log']['path']).read_text(encoding='utf-8')
    if sum(line.endswith(' ... ok') for line in log.splitlines()) != value['tests_run']:
        raise ValueError('Successful named test count differs from the preserved log')
    print(dict(status='v65_saved_synthetic_acceptance_audited', tests=value['tests_run'], tests_rerun=0))


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
