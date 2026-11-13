"""Compare fixed48 logical workload counters using sealed records only."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_queries_v50 as prior
from scripts.retailrocket_session_knn_workload_distribution_v51 import summarize_workloads


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
saved = prior.prior
BASE = 'reports/stage12/retailrocket_session_knn_v51_workloads_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_workloads_v51.py'
SUITES = ('tests.test_retailrocket_session_knn_workload_distribution_v51',
          'tests.test_retailrocket_session_knn_workloads_v51')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_workload_distribution_v51.py',
           *(name.replace('.', '/') + '.py' for name in SUITES),
           'scripts/retailrocket_session_knn_sql_v4.py')
PRIOR_SHA = '792336e520df35e832a153f42bedb1c1bc73f06218be59b50c8f895415d2fb1f'
TARGETS = (32, 38)
SCOPE = dict(saved_windows=2, saved_entries=28, matched_saved_rows=1344,
    unique_fixed_queries=48, target_positions=list(TARGETS), other_queries=46,
    repeated_workload_vectors_collapsed=True, new_experiments=0, new_queries=0,
    new_decodes=0, new_fit=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    prior.accepted()
    records = prior.inputs()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V50 query distribution')
    return [*records, record]


def collect_entries(records):
    """Validate all 28 saved entries, then count each fixed query only once."""
    expected = [(window, row['label']) for window in ('V47', 'V48')
                for row in saved.v47.cold.SCHEDULE]
    if [(row['window'], row['label']) for row in records] != expected:
        raise ValueError('Exactly the original two 14-entry schedules required')
    identity, comparison = None, None
    for record in records:
        _, current = prior.extract_entry(record['measured'], record['accounting'], identity)
        # Validate exact counter types in every entry: bool and int compare equal
        # in Python, so identity equality alone is not a sufficient schema check.
        summary = summarize_workloads([row[2] for row in current], TARGETS)
        if identity is None:
            identity, comparison = current, summary
        elif summary != comparison:
            raise ValueError('Repeated logical workload distributions differ')
    return dict(comparison=comparison, saved_entries_checked=len(records),
        matched_saved_rows=len(records) * 48, unique_queries_counted=48,
        identity_order_and_workload_equal=True,
        warmups_used_for_identity_check_only=True,
        windows={name: dict(entries_checked=14, saved_rows_checked=672)
                 for name in ('V47', 'V48')})


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V51 tool acceptance already exists')
    methods, sources = [describe(ROOT / name) for name in METHODS], inputs()
    folder = saved.v48.PRIVATE / ('knn-v51-workload-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = saved.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline workload analysis tests failed')
    verify_bindings([*methods, *sources])
    value = dict(status='v51_saved_workload_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names,
        failures=0, errors=0, skipped=0, seconds=perf_counter() - start,
        log=describe(path), scope=SCOPE)
    saved.v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun,
               seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v51_saved_workload_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['suites'] != list(SUITES)
            or value['scope'] != SCOPE or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V51 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        distribution = prior.build()
    if distribution != read(ROOT / prior.REPORT):
        raise ValueError('Saved V50 query distribution does not reproduce')
    records, evidence = [], []
    for window, runner in (('V47', saved.v47), ('V48', saved.v48)):
        report = read(ROOT / runner.REPORT)
        index = {row['path']: row for row in report['closed_manifest']['window_evidence']}
        for item in report['schedule']:
            label = item['label']
            measured, source = saved.sealed_json(ROOT / report['namespace'] / label / 'measured.json', index)
            records.append(dict(window=window, label=label, measured=measured,
                                accounting=report['runs'][label]['accounting']))
            evidence.append(source)
    comparison = collect_entries(records)
    verify_bindings([*receipt['methods'], *receipt['inputs'], *evidence])
    return dict(status='v51_saved_fixed48_logical_workload_compared',
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        scope=SCOPE, **comparison, measured_evidence=evidence,
        interpretation='The 28 entries contain the same 48 fixed query workload vectors; each vector is counted once. '
          'Positions are anonymous one-based subset indexes. Counter summaries and the two target values contain no '
          'original keys, hashes, ordinals, item IDs or SQL rows. Descending rank intervals preserve ties; comparisons '
          'to the other 46 exclude both targets. Counters are separate logical dimensions, never summed into one '
          'total workload. Larger counts do not prove CPU, physical I/O, scheduling wait or decoder causality. '
          'Catalog candidate counts and vote scale bits are quantities, not rows actually scanned or operation costs. '
          'Constant fields cannot distinguish the targets. There is no timing or workload threshold defining significance.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance', 'analysis', 'audit'):
        modes.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    with saved.v48.entry.exclusive():
        if args.acceptance:
            return accept()
        path = ROOT / REPORT
        if not args.audit and path.exists():
            raise FileExistsError('Immutable V51 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Workload analysis differs from saved evidence')
        else:
            saved.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
                   unique_queries=result['unique_queries_counted'],
                   saved_rows=result['matched_saved_rows']))


if __name__ == '__main__':
    main()
