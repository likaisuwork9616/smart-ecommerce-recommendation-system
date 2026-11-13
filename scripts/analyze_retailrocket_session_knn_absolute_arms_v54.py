"""Inspect absolute saved stage times for four preselected V48 cases."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from math import isclose
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_peer_stages_v53 as prior
from scripts.retailrocket_session_knn_absolute_arms_v54 import compare_absolute_arms


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
timing, saved = prior.timing, prior.saved
BASE = 'reports/stage12/retailrocket_session_knn_v54_absolute_arms_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_absolute_arms_v54.py'
SUITES = ('tests.test_retailrocket_session_knn_absolute_arms_v54',
          'tests.test_retailrocket_session_knn_absolute_arm_analysis_v54')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_absolute_arms_v54.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
PRIOR_SHA = '96487417d3d06775f5abdb27c4c8fbc0282eb80d31bcb702a9d9a6e4641d5e45'
CASES = ((2, 'sql_selected_votes_and_accumulation'),
         (3, 'sql_selected_votes_and_accumulation'),
         (4, 'sql_positive_overlaps'), (5, 'sql_positive_overlaps'))
SCOPE = dict(saved_windows_checked=2, saved_entries_checked=28, matched_saved_rows=1344,
    analysis_window='V48', positions=[32, 33], selected_absolute_timers=16,
    cases=[dict(pair=pair, stage=stage) for pair, stage in CASES],
    arms=dict(R='V39 original', C='V46 candidate'), new_experiments=0, new_queries=0,
    new_decodes=0, new_fit=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    prior.accepted()
    sources = prior.inputs()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V53 peer-stage analysis')
    return [*sources, record]


def close(actual, expected, name):
    if not isclose(actual, expected, rel_tol=0, abs_tol=1e-8):
        raise ValueError('Absolute stage times differ from V53: ' + name)


def analyze_entries(records, reference):
    # This inherited check validates both original schedules and every query's
    # identity, strict workload schema, timer nesting and primary accounting.
    checked = prior.prior.prior.collect_entries(records)
    pairs = reference['windows']['V48']['pairs']
    if (len(pairs) != 6 or [(row['pair'], row['order']) for row in pairs]
            != list(enumerate(saved.v47.cold.ORDERS, 1))):
        raise ValueError('Exactly the original six V48 pair references required')
    entries = {row['label']: row for row in records if row['window'] == 'V48'}
    cases = []
    for number, stage in CASES:
        timers = {}
        for arm in ('R', 'C'):
            rows = entries[f'pair_{number}_{arm}']['measured']['queries']
            timers[arm] = {position: timing.query_parts(rows[position - 1])['parts_seconds'][stage]
                           for position in (32, 33)}
        result = compare_absolute_arms(timers)
        expected = pairs[number - 1]
        for position in ('32', '33'):
            close(result['query_delta_seconds'][position],
                  expected['positions'][position]['atomic_delta_seconds'][stage], 'position ' + position)
        close(result['gap_seconds'], expected['gap_atomic_seconds'][stage], 'stage gap')
        cases.append(dict(window='V48', pair=number, order=expected['order'], stage=stage,
                          **result, v53_deltas_and_gap_reconciled=True))
    return dict(cases=cases, saved_entries_checked=checked['saved_entries_checked'],
        matched_saved_rows=checked['matched_saved_rows'], selected_absolute_timers=16,
        identity_order_and_workload_equal=True)


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V54 tool acceptance already exists')
    methods, sources = [describe(ROOT / name) for name in METHODS], inputs()
    folder = saved.v48.PRIVATE / ('knn-v54-absolute-arm-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = saved.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline absolute-arm tests failed')
    verify_bindings([*methods, *sources])
    value = dict(status='v54_saved_absolute_arm_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names,
        failures=0, errors=0, skipped=0, seconds=perf_counter() - start,
        log=describe(path), scope=SCOPE)
    saved.v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v54_saved_absolute_arm_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['suites'] != list(SUITES)
            or value['scope'] != SCOPE or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V54 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        reference = prior.build()
    if reference != read(ROOT / prior.REPORT):
        raise ValueError('Saved V53 stage analysis does not reproduce')
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
    result = analyze_entries(records, reference)
    verify_bindings([*receipt['methods'], *receipt['inputs'], *evidence])
    return dict(status='v54_saved_v48_absolute_stage_arms_reconciled',
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        scope=SCOPE, **result, measured_evidence=evidence,
        interpretation='Four preselected V48 cases are all retained, without filtering by stage direction or size. '
          'R means V39 original; C means V46 candidate. Absolute nonnegative stage durations are distinct from '
          'query C-minus-R deltas and within-arm position32-minus-position33 contrasts. Stage gap equals '
          '(C32-R32)-(C33-R33)=(C32-C33)-(R32-R33). Signed arm terms are C=(C32-C33), R=-(R32-R33). '
          'Alignment uses the stage gap sign. Each case has its own positive-support denominator; these shares '
          'are not fractions of total elapsed time and are not aggregated across cases. More arm support does '
          'not mean that arm is globally slower or its timer is an outlier. No temporal rise, fall or spike '
          'is inferred from four cells. These are previously exposed, non-simultaneous wall-time records; '
          'the arithmetic does not establish decoder, CPU, I/O, scheduler or host-load causality.')


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
            raise FileExistsError('Immutable V54 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Absolute-arm analysis differs from saved evidence')
        else:
            saved.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
            cases=[dict(pair=row['pair'], leading_support_arms=row['alignment']['leading_support_arms'])
                   for row in result['cases']]))


if __name__ == '__main__':
    main()
