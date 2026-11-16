"""Seal, accept, collect at most one B, and audit immutable saved evidence.

Only --worker may read real B clocks. It requires the unique reservation and
claim created by --measure. No C/D, dataset, model or benchmark entry is present.
"""
import argparse
import ast
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'reports/stage12/retailrocket_session_knn_v67_clock_'
PLAN = 'reports/stage12/retailrocket_session_knn_v66_clock_calibration_plan_20261116.json'
PRIOR = 'reports/stage12/retailrocket_session_knn_v65_wall_cpu_acceptance_r1_20261116.json'
PRIVATE = 'shop-mysql-runtime/verification/'
RESERVATION = PRIVATE + 'v67-B-once-reservation.json'
RESULT = PREFIX + 'result_20261116.json'
MODULE = 'scripts.run_retailrocket_session_knn_clock_calibration_v67'
SUITES = (
    'tests.test_retailrocket_session_knn_wall_cpu_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_summary_v63',
    'tests.test_retailrocket_session_knn_wall_cpu_decision_v65.CapabilityDecisionTests',
    'tests.test_retailrocket_session_knn_clock_collector_v67',
    'tests.test_retailrocket_session_knn_clock_capability_v67',
    'tests.test_retailrocket_session_knn_clock_driver_v67',
)
METHODS = (
    'scripts/run_retailrocket_session_knn_clock_calibration_v67.py',
    'scripts/retailrocket_session_knn_clock_collector_v67.py',
    'scripts/retailrocket_session_knn_clock_capability_v67.py',
    'tests/test_retailrocket_session_knn_clock_collector_v67.py',
    'tests/test_retailrocket_session_knn_clock_capability_v67.py',
    'tests/test_retailrocket_session_knn_clock_driver_v67.py',
)
SCOPE = dict(user_confirmation_received=True, phase='B_only', maximum_live_attempts=1,
    deadline_ns=30_000_000_000, sample_cap=1_000_000, round_count=3,
    round_target_ns=500_000_000, sleep_trials=10, sleep_requested_ns=50_000_000,
    C_runs=0, D_runs=0, original_fixed48_runs=0, production_model_decodes=0,
    training_runs=0, new_live_load_samples=0, reserved_test='locked', adopt_v46=False,
    supervisor_timeout_seconds=30, retry_after_failure=False)


def local(name):
    path = (ROOT / name).resolve()
    path.relative_to(ROOT.resolve())
    return path


def private_folder(name):
    path = local(name)
    path.relative_to(local(PRIVATE))
    if path == local(PRIVATE):
        raise ValueError('A dedicated attempt folder is required')
    return path


def read(name):
    return json.loads(local(name).read_bytes())


def describe(name):
    data = local(name).read_bytes()
    return dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def write_new(name, value):
    """Exclusive immutable JSON, including flush/fsync and descriptor cost."""
    data = (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    with local(name).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def verify(rows):
    for row in rows:
        if row != describe(row['path']):
            raise ValueError('Source/evidence changed: ' + row['path'])


def names(revision):
    if type(revision) is not int or revision < 1:
        raise ValueError('Positive revision required')
    suffix = f'r{revision}_20261116.json'
    return PREFIX + 'methods_' + suffix, PREFIX + 'acceptance_' + suffix


def suite_path(selector):
    parts = selector.split('.')
    return '/'.join(parts[:2]) + '.py'


def declared_tests():
    cases = []
    for selector in SUITES:
        module = '.'.join(selector.split('.')[:2])
        selected_class = selector.split('.')[2] if len(selector.split('.')) == 3 else None
        tree = ast.parse(local(suite_path(selector)).read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and selected_class in (None, node.name):
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                        cases.append(f'{module}.{node.name}.{method.name}')
    if not cases or len(cases) != len(set(cases)):
        raise ValueError('Unique declared tests required')
    return sorted(cases)


def bindings():
    plan, prior = read(PLAN), read(PRIOR)
    if prior['status'] != 'v65_synthetic_full_A_tests_passed_not_live_B_C_D':
        raise ValueError('V65 full synthetic A required')
    rows = [plan['plan_document'], *plan['source_bindings'],
            *prior['inputs'], *prior['methods'], prior['seal']]
    verify(rows)
    pending = list(METHODS) + [suite_path(x) for x in SUITES]
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse(local(name).read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module] + [node.module + '.' + alias.name for alias in node.names]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                target = module.replace('.', '/') + '.py'
                if module.split('.')[0] in ('scripts', 'tests') and local(target).is_file():
                    pending.append(target)
    paths = {PLAN, PRIOR, *(row['path'] for row in rows), *seen}
    for name in ('scripts/__init__.py', 'tests/__init__.py'):
        if local(name).is_file():
            paths.add(name)
    return [describe(name) for name in sorted(paths.difference(METHODS))]


def seal_value(revision):
    return dict(status='v67_methods_sealed_not_yet_tested', revision=revision,
        scope=SCOPE, inputs=bindings(), methods=[describe(x) for x in METHODS],
        suites=list(SUITES), declared_tests=declared_tests())


def freeze(revision):
    value = seal_value(revision)
    write_new(names(revision)[0], value)
    print(dict(seal=names(revision)[0], declared_cases=len(value['declared_tests']), tests_run=0))


def sealed(revision):
    value = read(names(revision)[0])
    if value != seal_value(revision):
        raise ValueError('Methods differ from the immutable seal')
    return value


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def committed(rows, commit, *, historical_text=False):
    for row in rows:
        data = git('show', f"{commit}:{row['path']}")
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            # Old Windows text sources were sealed as CRLF but stored by Git as
            # LF. Permit only that exact relation for historical inputs; the
            # local original bytes must still match their old immutable seal.
            if historical_text and Path(row['path']).suffix in ('.md', '.py'):
                original = local(row['path']).read_bytes()
                if (len(original) == row['bytes'] and hashlib.sha256(original).hexdigest() == row['sha256']
                        and original.replace(b'\r\n', b'\n') == data):
                    continue
            raise ValueError('Committed bytes differ: ' + row['path'])


def published(rows, historical_inputs=()):
    head = git('rev-parse', 'HEAD').decode().strip()
    if (git('branch', '--show-current').decode().strip() != 'main' or
            git('rev-parse', 'refs/remotes/origin/main').decode().strip() != head):
        raise ValueError('Current main must match the pushed tracking ref')
    committed(rows, head)
    committed(historical_inputs, head, historical_text=True)
    return head


def test_ids(suite):
    if isinstance(suite, unittest.TestSuite):
        return [case for child in suite for case in test_ids(child)]
    return [suite.id()]


def accept(revision):
    seal, acceptance = names(revision)
    frozen = sealed(revision)
    commit = published([describe(seal), *frozen['methods']], frozen['inputs'])
    if local(acceptance).exists():
        raise FileExistsError('Acceptance cannot be overwritten')
    folder = PRIVATE + 'v67-fake-' + uuid4().hex
    local(folder).mkdir(parents=True, exist_ok=False)
    reservation = PRIVATE + f'v67-fake-r{revision}-reservation.json'
    write_new(reservation, dict(seal=describe(seal), commit=commit, folder=folder))
    log = StringIO()
    with redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        loaded = sorted(test_ids(suite))
        if loaded != frozen['declared_tests']:
            result = unittest.TestResult()
            result.errors.append(('manifest', 'Loaded cases differ; no bodies executed'))
            print(loaded)
        else:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    log_name = folder + '/tests.log'
    with local(log_name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(log.getvalue())
    success = (loaded == frozen['declared_tests'] and result.wasSuccessful()
               and not result.skipped and result.testsRun == len(loaded))
    postflight_error = None
    try:
        sealed(revision)
    except Exception as error:
        success, postflight_error = False, str(error)
    attempt = dict(status='passed' if success else 'failed', revision=revision,
        seal=describe(seal), seal_commit=commit, scope=SCOPE, loaded_tests=loaded,
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), log=describe(log_name), postflight_error=postflight_error,
        reservation=describe(reservation), live_B_attempts=0)
    attempt_row = write_new(folder + '/attempt.json', attempt)
    value = dict(attempt, attempt=attempt_row, inputs=frozen['inputs'], methods=frozen['methods'])
    write_new(acceptance, value)
    print(dict(acceptance=acceptance, status=attempt['status'], tests_run=result.testsRun,
               failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped)))
    if not success:
        print(log.getvalue())
        raise ValueError('Fake acceptance failed; preserve attempt and reseal before another fake suite')


def audit_acceptance(revision):
    seal, acceptance = names(revision)
    frozen, value = sealed(revision), read(acceptance)
    if (value['status'] != 'passed' or value['revision'] != revision or value['scope'] != SCOPE or
            value['seal'] != describe(seal) or value['methods'] != frozen['methods'] or
            value['inputs'] != frozen['inputs'] or value['loaded_tests'] != frozen['declared_tests'] or
            value['tests_run'] != len(frozen['declared_tests']) or value['postflight_error'] is not None or
            any(value[x] != 0 for x in ('failures', 'errors', 'skipped', 'live_B_attempts'))):
        raise ValueError('Successful sealed fake acceptance required')
    verify([value['log'], value['attempt'], value['reservation']])
    attempt = read(value['attempt']['path'])
    if any(attempt[key] != value[key] for key in attempt):
        raise ValueError('Public/private acceptance differs')
    reservation = read(value['reservation']['path'])
    if reservation != dict(seal=value['seal'], commit=value['seal_commit'],
                           folder=Path(value['attempt']['path']).parent.as_posix()):
        raise ValueError('Fake reservation differs')
    committed([value['seal'], *value['methods']], value['seal_commit'])
    committed(value['inputs'], value['seal_commit'], historical_text=True)
    log = local(value['log']['path']).read_text(encoding='utf-8')
    if sum(line.endswith(' ... ok') for line in log.splitlines()) != value['tests_run']:
        raise ValueError('Named successful log count differs')
    return value


def reserve_live(revision, folder, commit):
    private_folder(folder)
    seal, acceptance = names(revision)
    return write_new(RESERVATION, dict(revision=revision, folder=folder, seal=describe(seal),
        acceptance=describe(acceptance), published_commit=commit, scope=SCOPE))


def claim_worker(folder, revision):
    private_folder(folder)
    reservation = read(RESERVATION)
    if (reservation['folder'] != folder or reservation['revision'] != revision or
            reservation['scope'] != SCOPE or reservation['seal'] != describe(names(revision)[0]) or
            reservation['acceptance'] != describe(names(revision)[1])):
        raise ValueError('Worker does not match the unique B reservation')
    return write_new(folder + '/worker_claim.json', dict(reservation=describe(RESERVATION)))


def worker(folder, revision):
    # All source/fake verification and the exclusive claim precede live APIs.
    audit_acceptance(revision)
    reservation = read(RESERVATION)
    committed([reservation['seal'], reservation['acceptance']], reservation['published_commit'])
    claim_worker(folder, revision)
    from scripts.retailrocket_session_knn_clock_collector_v67 import collect_capability, REAL_ORIGIN
    from scripts.retailrocket_session_knn_clock_capability_v67 import evaluate_capability, validate_real_readers
    import platform
    import threading
    import time
    source = describe(names(revision)[0])['sha256']
    wall, cpu, identity = time.perf_counter_ns, time.thread_time_ns, threading.get_ident
    validate_real_readers(wall_clock=wall, cpu_clock=cpu, thread_identity=identity)
    captured_metadata = {}

    def metadata():
        clocks = {}
        for name, api, key in (('wall', 'time.perf_counter_ns', 'perf_counter'),
                               ('cpu', 'time.thread_time_ns', 'thread_time')):
            try:
                info = time.get_clock_info(key)
                clocks[name] = dict(api=api, available=True, implementation=info.implementation,
                    monotonic=info.monotonic, adjustable=info.adjustable,
                    resolution_seconds=str(info.resolution))
            except Exception:
                clocks[name] = dict(api=api, available=False, implementation='unavailable',
                    monotonic=False, adjustable=False, resolution_seconds=None)
        value = dict(environment=dict(python=sys.version, os=platform.platform(),
            process_id=os.getpid(), thread_id=identity(), source_sha256=source), clocks=clocks)
        captured_metadata.update(deepcopy(value))
        return value

    def evaluate(record):
        return evaluate_capability(record, expected_origin=REAL_ORIGIN, expected_source_sha256=source,
            expected_environment=captured_metadata.get('environment'),
            expected_clocks=captured_metadata.get('clocks'))

    envelope = collect_capability(origin=REAL_ORIGIN, source_sha256=source,
        metadata=metadata, wall_clock=wall, cpu_clock=cpu, thread_identity=identity,
        sleep=time.sleep, cancelled=lambda: False,
        persist=lambda snapshot: write_new(folder + '/raw.json', snapshot), evaluate=evaluate)
    # This publication is after B. The persisted raw is provisional; final contains
    # the final control read proving whether evaluation + raw fsync met the budget.
    write_new(folder + '/outcome.json', dict(envelope=envelope, source_sha256=source,
        readers=dict(wall='time.perf_counter_ns', cpu='time.thread_time_ns',
                     thread='threading.get_ident', identity_checked=True),
        publication_scope='after_B_not_part_of_success_window'))


def run_child(command, log_path, *, popen=subprocess.Popen):
    """Wait at most 30 seconds after Popen returns; never retry a failed child.

    This supervisor includes child setup/publication and may stop B early.
    Collector final is independently required to meet the whole-B 30s budget.
    """
    result = dict(timeout=False, returncode=None, launch_error=None)
    with log_path.open('xb') as log:
        try:
            process = popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as error:
            result['launch_error'] = dict(type=type(error).__name__, message=str(error))
            return result
        try:
            process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            result['timeout'] = True
            process.kill()  # Only this owned child; never another user's process.
            process.communicate()
        result['returncode'] = process.returncode
    return result


def summarize(folder, supervision):
    """Saved records only: no clock, sleep or collection is invoked here."""
    artifacts = [describe(RESERVATION)]
    for name in ('worker_claim.json', 'raw.json', 'outcome.json', 'worker.log'):
        path = folder + '/' + name
        if local(path).is_file():
            artifacts.append(describe(path))
    complete_envelope = local(folder + '/outcome.json').is_file()
    public_supervision = dict(supervision)
    if public_supervision['launch_error'] is not None:
        public_supervision['launch_error'] = {'type': public_supervision['launch_error']['type']}
    result = dict(status='clock_capability_unconfirmed', live_B_passed=False,
        completed=False, elapsed_wall_ns=None, raw_missing=not local(folder + '/raw.json').is_file(),
        outcome_missing=not complete_envelope, supervision=public_supervision, artifacts=artifacts,
        failure_reasons=[], decision_summary=None, collection_summary=None, final=None)
    if supervision['timeout'] or supervision['launch_error'] or supervision['returncode'] != 0:
        result['failure_reasons'].append('supervisor_incomplete_no_retry')
    if not complete_envelope:
        result['failure_reasons'].append('missing_final_envelope_no_success_attestation')
        return result
    if read(folder + '/worker_claim.json') != dict(reservation=describe(RESERVATION)):
        raise ValueError('Completed envelope requires the matching exclusive worker claim')
    from scripts.retailrocket_session_knn_clock_capability_v67 import evaluate_capability
    saved = read(folder + '/outcome.json')
    envelope = saved['envelope']
    reservation = read(RESERVATION)
    if saved['source_sha256'] != reservation['seal']['sha256'] or saved['readers'] != dict(
            wall='time.perf_counter_ns', cpu='time.thread_time_ns', thread='threading.get_ident',
            identity_checked=True):
        raise ValueError('Live reader/source provenance differs')
    metadata = envelope['collection']['metadata_raw'] or {}
    decision = evaluate_capability(envelope['record'], expected_origin='real_clock_capability_v67',
        expected_source_sha256=saved['source_sha256'], expected_environment=metadata.get('environment'),
        expected_clocks=metadata.get('clocks'))
    if decision != envelope['decision']:
        raise ValueError('Saved pure decision differs on readonly recomputation')
    if envelope['persistence'] is not None:
        verify([envelope['persistence']])
        if envelope['persistence']['path'] != folder + '/raw.json':
            raise ValueError('Raw path differs')
        raw = read(folder + '/raw.json')
        if (raw['record'] != envelope['record'] or raw['decision'] != envelope['decision'] or
                raw['final'] is not None or raw['snapshot_status'] != 'provisional_before_raw_persistence'):
            raise ValueError('Raw provisional snapshot differs')
        # Only post-persistence controls/errors may be added to the envelope.
        before, after = raw['collection'], envelope['collection']
        for key in before:
            if key in ('control_reads', 'errors', 'stop_reasons'):
                if after[key][:len(before[key])] != before[key]:
                    raise ValueError('Raw prefix changed: ' + key)
            elif key != 'primary_error' and before[key] != after[key]:
                raise ValueError('Raw collection changed: ' + key)
    final = envelope['final']
    controls = envelope['collection']['control_reads']
    previous = None
    for control in controls:
        if control['error_type'] is not None:
            continue  # Keep rejected raw values; they cannot be valid deadline evidence.
        point = control['wall_ns']
        if type(point) is not int or point < 0 or (previous is not None and point < previous):
            raise ValueError('Valid control clocks must be exact nonnegative monotonic integers')
        previous = point
    canonical_end = envelope['record']['ended_wall_ns']
    expected_end = None if not controls or controls[-1]['error_type'] is not None else controls[-1]['wall_ns']
    if (not controls or controls[-1]['phase'] != 'after_raw_persistence' or
            expected_end != final['ended_wall_ns']):
        raise ValueError('Final deadline control evidence differs')
    start, end = envelope['record']['started_wall_ns'], final['ended_wall_ns']
    if end is not None and canonical_end is not None and end < canonical_end:
        raise ValueError('Final persistence control precedes canonical collection end')
    elapsed = end - start if start is not None and end is not None else None
    within = envelope['persistence'] is not None and elapsed is not None and 0 <= elapsed <= 30_000_000_000
    if final['elapsed_wall_ns'] != elapsed or final['raw_persisted_within_deadline'] != within:
        raise ValueError('Whole-gate elapsed/deadline differs')
    stops = envelope['collection']['stop_reasons']
    expected_status = stops[0]['status'] if stops else decision['status']
    if any(item['status'] == 'rejected_structure' for item in stops):
        expected_status = 'rejected_structure'
    if not within and expected_status != 'rejected_structure':
        expected_status = 'clock_capability_unconfirmed'
    passed = expected_status == 'clock_capability_passed' and within and not stops
    expected_final = dict(status=expected_status, completed=passed, ended_wall_ns=end,
        elapsed_wall_ns=elapsed, raw_persisted_within_deadline=within, deadline_ns=30_000_000_000,
        live_B_passed=passed, authorized_next_gate=False)
    if final != expected_final:
        raise ValueError('Final classification differs from stops/decision/deadline')
    if final['live_B_passed'] and (not within or not final['completed'] or
            decision['status'] != 'clock_capability_passed' or envelope['collection']['stop_reasons'] or
            not envelope['record']['completed']):
        raise ValueError('Incomplete collection cannot attest a B pass')
    # Raw integer stamps and machine identities remain private.
    result.update(status=final['status'], live_B_passed=final['live_B_passed'],
        completed=final['completed'], elapsed_wall_ns=elapsed,
        final={key: value for key, value in final.items() if key != 'ended_wall_ns'},
        decision_summary={key: value for key, value in decision.items() if key not in ('raw', 'records')},
        collection_summary={key: envelope['collection'][key] for key in (
            'stop_reasons', 'captured_stamps', 'requested_sleeps')})
    result['collection_summary']['errors'] = [
        {key: row[key] for key in ('phase', 'type')} for row in envelope['collection']['errors']]
    primary = envelope['collection']['primary_error']
    result['collection_summary']['primary_error'] = (
        None if primary is None else {key: primary[key] for key in ('phase', 'type')})
    result['failure_reasons'].extend(envelope['collection']['stop_reasons'])
    if result['failure_reasons'] and (supervision['timeout'] or supervision['launch_error'] or supervision['returncode'] != 0):
        result.update(status='clock_capability_unconfirmed', live_B_passed=False, completed=False)
    return result


def measure(revision):
    frozen = sealed(revision)
    audit_acceptance(revision)
    seal, acceptance = names(revision)
    commit = published([describe(seal), describe(acceptance), *frozen['methods']], frozen['inputs'])
    if local(RESULT).exists() or local(RESERVATION).exists():
        raise FileExistsError('V67 permits at most one live B attempt, including failed attempts')
    folder = PRIVATE + 'v67-B-' + uuid4().hex
    local(folder).mkdir(parents=True, exist_ok=False)
    reserve_live(revision, folder, commit)
    supervision = run_child([sys.executable, '-B', '-m', MODULE, '--worker', folder,
                            '--revision', str(revision)], local(folder + '/worker.log'))
    write_new(folder + '/supervision.json', supervision)
    try:
        summary = summarize(folder, supervision)
    except Exception as error:
        summary = dict(status='clock_capability_unconfirmed', live_B_passed=False,
            completed=False, audit_error=dict(type=type(error).__name__, message=str(error)))
    value = dict(schema='v67_single_B_result', revision=revision, scope=SCOPE,
        live_attempts_reserved=1, reservation=describe(RESERVATION), seal=describe(seal),
        acceptance=describe(acceptance), published_commit=commit, folder=folder,
        supervision=describe(folder + '/supervision.json'), summary=summary)
    write_new(RESULT, value)
    print(json.dumps(dict(result=RESULT, status=summary['status'],
                         live_B_passed=summary['live_B_passed']), ensure_ascii=False))


def audit_measure(revision):
    audit_acceptance(revision)
    value = read(RESULT)
    if value['revision'] != revision or value['scope'] != SCOPE or value['live_attempts_reserved'] != 1:
        raise ValueError('B result scope differs')
    verify([value['reservation'], value['seal'], value['acceptance'], value['supervision']])
    reservation = read(RESERVATION)
    if reservation != dict(revision=revision, folder=value['folder'], seal=value['seal'],
            acceptance=value['acceptance'], published_commit=value['published_commit'], scope=SCOPE):
        raise ValueError('Live reservation/result differs')
    committed([value['seal'], value['acceptance']], value['published_commit'])
    claim_path = value['folder'] + '/worker_claim.json'
    if local(claim_path).exists() and read(claim_path) != dict(reservation=value['reservation']):
        raise ValueError('Worker claim differs')
    summary = summarize(value['folder'], read(value['supervision']['path']))
    if summary != value['summary']:
        raise ValueError('Saved B result differs from readonly audit')
    print(dict(status='v67_saved_B_audited', B_status=summary['status'], live_attempts=1, reruns=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('freeze', 'acceptance', 'audit-acceptance', 'measure', 'audit-measure'):
        group.add_argument('--' + name, action='store_true')
    group.add_argument('--worker', help=argparse.SUPPRESS)
    parser.add_argument('--revision', type=int, default=1)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.revision)
    elif args.freeze:
        freeze(args.revision)
    elif args.acceptance:
        accept(args.revision)
    elif args.audit_acceptance:
        result = audit_acceptance(args.revision)
        print(dict(status='v67_fake_acceptance_audited', tests=result['tests_run'], reruns=0))
    elif args.measure:
        measure(args.revision)
    else:
        audit_measure(args.revision)


if __name__ == '__main__':
    main()
