"""Locate four saved V48 cases within same-stage/arm/position six-pair times."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_absolute_arms_v54 as prior
from scripts.analyze_retailrocket_session_knn_workloads_v51 import collect_entries
from scripts.retailrocket_session_knn_time_reference_v55 import summarize_six, locate_in_six


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
timing, saved = prior.timing, prior.saved
BASE = 'reports/stage12/retailrocket_session_knn_v55_time_reference_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_time_reference_v55.py'
SUITES = ('tests.test_retailrocket_session_knn_time_reference_v55',
          'tests.test_retailrocket_session_knn_time_reference_analysis_v55')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_time_reference_v55.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
PRIOR_SHA = 'f3fe11a70612a2107b91981e8f2212390cfce85001d495d5f3d52a1d1b38359f'
CASES = prior.CASES
STAGES = tuple(dict.fromkeys(stage for _, stage in CASES))
ORDERS = saved.v47.cold.ORDERS
SCOPE = dict(saved_windows_checked=2, saved_entries_checked=28, matched_saved_rows=1344,
    analysis_window='V48', positions=[32, 33], arms=dict(R='V39 original', C='V46 candidate'),
    reference_groups=8, reference_values_per_group=6, unique_reference_timers=48,
    target_cases=4, target_absolute_timers=16,
    cases=[dict(pair=pair, stage=stage) for pair, stage in CASES],
    new_experiments=0, new_queries=0, new_decodes=0, new_fit=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    prior.accepted()
    sources = prior.inputs()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V54 absolute-arm analysis')
    return [*sources, record]


def group_key(stage, arm, position):
    return f'{stage}/{arm}/{position}'


def analyze_entries(records, reference):
    checked = collect_entries(records)
    expected_cases = [('V48', pair, ORDERS[pair - 1], stage) for pair, stage in CASES]
    if [(row['window'], row['pair'], row['order'], row['stage']) for row in reference['cases']] != expected_cases:
        raise ValueError('Exactly the four fixed V54 cases in original order are required')
    entries = {row['label']: row for row in records if row['window'] == 'V48'}
    groups, series = {}, {}
    for stage in STAGES:
        for arm in ('R', 'C'):
            for position in (32, 33):
                key = group_key(stage, arm, position)
                values = {pair: timing.query_parts(entries[f'pair_{pair}_{arm}']['measured']['queries'][position - 1])
                          ['parts_seconds'][stage] for pair in range(1, 7)}
                series[key] = values
                groups[key] = dict(stage=stage, arm=arm, position=position,
                    observations=[dict(pair=pair, order=ORDERS[pair - 1],
                        arm_run_position=ORDERS[pair - 1].index(arm) + 1, seconds=value)
                        for pair, value in values.items()], summary=summarize_six(values))
    cases = []
    for (pair, stage), expected in zip(CASES, reference['cases']):
        cells = []
        for arm in ('R', 'C'):
            for position in (32, 33):
                key = group_key(stage, arm, position)
                value = locate_in_six(series[key], pair)
                original = expected['absolute_seconds'][arm][str(position)]
                if type(original) not in (int, float) or value['seconds'] != original:
                    raise ValueError('Absolute target timer differs from V54')
                cells.append(dict(arm=arm, position=position, group_key=key, **value))
        cases.append(dict(window='V48', pair=pair, order=ORDERS[pair - 1], stage=stage,
                          cells=cells, v54_absolute_timers_equal=True))
    return dict(groups=groups, cases=cases, saved_entries_checked=checked['saved_entries_checked'],
        matched_saved_rows=checked['matched_saved_rows'], unique_reference_timers=48,
        target_absolute_timers=16, identity_order_and_workload_equal=True)


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V55 tool acceptance already exists')
    methods, sources = [describe(ROOT / name) for name in METHODS], inputs()
    folder = saved.v48.PRIVATE / ('knn-v55-time-reference-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = saved.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline six-time reference tests failed')
    verify_bindings([*methods, *sources])
    value = dict(status='v55_saved_time_reference_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names,
        failures=0, errors=0, skipped=0, seconds=perf_counter() - start,
        log=describe(path), scope=SCOPE)
    saved.v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v55_saved_time_reference_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['suites'] != list(SUITES)
            or value['scope'] != SCOPE or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V55 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        reference = prior.build()
    if reference != read(ROOT / prior.REPORT):
        raise ValueError('Saved V54 absolute-arm analysis does not reproduce')
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
    return dict(status='v55_saved_v48_time_reference_reconciled',
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        scope=SCOPE, **result, measured_evidence=evidence,
        interpretation='All four V54 cases and all sixteen cells are retained. Each reference group fixes '
          'V48, stage, arm and query position and uses all six original formal pairs, including the target. '
          'Rank 1 is longest; exact ties retain the first and last occupied ranks. MAD is unscaled. '
          'Other-five summaries exclude only the current target pair, retaining any other V54 target in '
          'the same group. Above the other-five maximum is equivalent to being the unique six-value '
          'maximum, not independent evidence or an outlier criterion. Zero median ratios are null. '
          'Original pair order and arm run position are descriptive metadata, not load adjustment. '
          'No groups, arms, query positions or windows are pooled. Six non-independent exposed '
          'wall-time observations do not establish abnormality, significance, decoder causality, '
          'CPU, I/O, scheduler or host-load causes; no new experiment is run.')


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
            raise FileExistsError('Immutable V55 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Six-time reference differs from saved evidence')
        else:
            saved.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
                   groups=len(result['groups']), target_absolute_timers=result['target_absolute_timers']))


if __name__ == '__main__':
    main()
