"""Accept and re-audit the V40 entry on an artificial 48-record window."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import run_retailrocket_session_knn_compare_v40 as run
from tests import test_retailrocket_session_knn_compare_v40 as fixture
from scripts.accept_retailrocket_session_knn_snapshot_v30 import Result, test_ids


def coverage():
    contract = run.SUITE + '.ContractTests.'
    integrated = run.SUITE + '.IntegrationTests.'
    cases = (
        (contract + 'test_real_roster_preserves_all_parents_and_exact_schedule',
         contract + 'test_real_contract_rejects_changed_policy_sources_cohort_and_schedule'),
        (contract + 'test_measure_requires_acceptance_and_refuses_existing_request',),
        (integrated + 'test_production_loader_and_sequential_stopped_independent_roles',),
        (integrated + 'test_production_loader_and_sequential_stopped_independent_roles',
         integrated + 'test_publisher_rejects_raw_typed_policy_tampering'),
        (integrated + 'test_role_diagnostics_are_closed_and_final_log_tampering_fails',
         integrated + 'test_publication_and_read_only_audit_share_completed_checks'),
        (contract + 'test_real_namespace_rejects_artificial_and_legacy',
         contract + 'test_failed_worker_prevents_publisher', integrated + 'test_publisher_rejects_raw_typed_policy_tampering'),
    )
    return dict(zip(run.frozen.REQUIREMENTS, map(list, cases), strict=True))


def audit():
    run.frozen.specification()
    _, methods = run.source_roster()
    value, manifest = run.accepted_entry(methods)
    if (value['coverage'] != coverage()
            or sorted(value['passed_tests']) != sorted(test_ids(unittest.defaultTestLoader.loadTestsFromName(run.SUITE)))):
        raise ValueError('Acceptance suite or mapped coverage changed')
    run.verify_bindings([value['manifest'], value['log']])
    folder = run.ROOT / value['integration']['namespace']
    if not folder.parent.name.startswith(fixture.PREFIX):
        raise ValueError('An artificial acceptance window is required')
    rebuilt, _ = fixture.window_evidence(folder, manifest)
    if rebuilt != value['integration']:
        raise ValueError('Rebuilt artificial acceptance differs')
    return value


def acceptance():
    paths = (run.ROOT / run.ACCEPTANCE, run.ROOT / run.ACCEPTANCE_SEAL)
    if any(path.exists() for path in paths):
        raise FileExistsError('Immutable entry acceptance already exists; use --audit')
    spec = run.frozen.specification()
    _, methods = run.source_roster()
    folder = run.PRIVATE / ('knn-v40-entry-acceptance-' + uuid4().hex)
    folder.mkdir()
    start = perf_counter()
    log_path = folder / 'tests.log'
    with log_path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromName(run.SUITE)
        expected = sorted(test_ids(suite))
        result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Result).run(suite)
    if not result.wasSuccessful() or result.skipped or sorted(result.passed) != expected:
        print(log_path.read_text(encoding='utf-8')[-14000:])
        raise ValueError('V40 entry acceptance failed: ' + str(log_path))
    if any(not set(names).issubset(result.passed) for names in coverage().values()):
        raise ValueError('An entry requirement lacks a passing test')
    run.verify_bindings(methods)
    if spec != run.frozen.specification():
        raise ValueError('Frozen comparison changed during acceptance')
    summary, manifest = fixture.window_evidence(fixture.IntegrationTests.folder, fixture.IntegrationTests.manifest)
    manifest_path = folder / 'closed_manifest.json'
    run.write(manifest_path, manifest)
    value = dict(status=run.ACCEPTED, specification=run.describe(run.ROOT / run.frozen.SPEC), methods=methods,
        suite=run.SUITE, coverage=coverage(), tests_run=result.testsRun, passed_tests=result.passed,
        failures=0, errors=0, skipped=0, real_runs=0, seconds=perf_counter() - start,
        log=run.describe(log_path), manifest=run.describe(manifest_path), integration=summary)
    run.public_json(paths[0], value, exclusive=True)
    run.public_json(paths[1], run.acceptance_seal(), exclusive=True)
    return audit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance', action='store_true')
    mode.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with run.entry.exclusive():
        value = audit() if args.audit else acceptance()
    print(dict(audit=args.audit, tests=value['tests_run'], requirements=len(value['coverage']),
               integration=value['integration'], real_runs=0, seconds=value['seconds']))
