"""Describe other-query directions in eight preselected saved V48 run phases."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_time_reference_v55 as prior
from scripts.retailrocket_session_knn_common_direction_v56 import analyze_same_run


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
timing, saved = prior.timing, prior.saved
BASE = 'reports/stage12/retailrocket_session_knn_v56_common_direction_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_common_direction_v56.py'
SUITES = ('tests.test_retailrocket_session_knn_common_direction_v56',
          'tests.test_retailrocket_session_knn_common_direction_analysis_v56')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_common_direction_v56.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
PRIOR_SHA = 'b17987a602dd5ef20f603ef74a7d08b564a052d94162495c508fd2fdb03bb066'
CASES, STAGES, ORDERS = prior.CASES, prior.STAGES, prior.ORDERS
SCOPE = dict(saved_windows_checked=2, saved_entries_checked=28, matched_saved_rows=1344,
    analysis_window='V48', positions=list(range(1, 49)), target_positions=[32, 33],
    other_positions=[position for position in range(1, 49) if position not in (32, 33)],
    arms=dict(R='V39 original', C='V46 candidate'), reference_groups=192,
    reference_values_per_group=6, unique_reference_timers=1152, run_stage_panels=8,
    located_cells=384, other_cells=368, target_cells=16, threshold_seconds=.001,
    majority_rule='Strictly more than 23 of the other 46 in the same direction, separately for each mode.',
    cases=[dict(pair=pair, stage=stage) for pair, stage in CASES],
    new_experiments=0, new_queries=0, new_decodes=0, new_fit=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    prior.accepted()
    sources = prior.inputs()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V55 time-reference analysis')
    return [*sources, record]


def analyze_entries(records, reference):
    checked = prior.collect_entries(records)
    expected_cases = [('V48', pair, ORDERS[pair - 1], stage) for pair, stage in CASES]
    if [(row['window'], row['pair'], row['order'], row['stage']) for row in reference['cases']] != expected_cases:
        raise ValueError('Exactly the four fixed V55 cases in original order are required')
    entries = {row['label']: row for row in records if row['window'] == 'V48'}
    series, old_groups = {}, {}
    for stage in STAGES:
        for arm in ('R', 'C'):
            series[stage, arm] = {}
            for position in range(1, 49):
                values = {pair: timing.query_parts(entries[f'pair_{pair}_{arm}']['measured']['queries'][position - 1])
                          ['parts_seconds'][stage] for pair in range(1, 7)}
                series[stage, arm][position] = values
                if position in (32, 33):
                    old_groups[prior.group_key(stage, arm, position)] = dict(stage=stage, arm=arm, position=position,
                        observations=[dict(pair=pair, order=ORDERS[pair - 1],
                            arm_run_position=ORDERS[pair - 1].index(arm) + 1, seconds=value)
                            for pair, value in values.items()], summary=prior.summarize_six(values))
    if old_groups != reference['groups']:
        raise ValueError('All eight V55 reference groups must reproduce exactly')
    cases = []
    for (pair, stage), expected in zip(CASES, reference['cases']):
        arms, old_cells = {}, []
        for arm in ('R', 'C'):
            value = analyze_same_run(series[stage, arm], pair)
            arms[arm] = dict(arm_run_position=ORDERS[pair - 1].index(arm) + 1, **value)
            for position in (32, 33):
                old_cells.append(dict(arm=arm, position=position, group_key=prior.group_key(stage, arm, position),
                                      **value['positions'][str(position)]))
        if old_cells != expected['cells']:
            raise ValueError('All sixteen V55 target locations must reproduce exactly')
        cases.append(dict(window='V48', pair=pair, order=ORDERS[pair - 1], stage=stage,
                          arms=arms, v55_target_locations_equal=True))
    return dict(cases=cases, saved_entries_checked=checked['saved_entries_checked'],
        matched_saved_rows=checked['matched_saved_rows'], reference_groups=192,
        unique_reference_timers=1152, run_stage_panels=8, located_cells=384,
        other_cells=368, target_cells=16, v55_groups_and_locations_equal=True,
        identity_order_and_workload_equal=True)


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V56 tool acceptance already exists')
    methods, sources = [describe(ROOT / name) for name in METHODS], inputs()
    folder = saved.v48.PRIVATE / ('knn-v56-common-direction-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = saved.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline same-run direction tests failed')
    verify_bindings([*methods, *sources])
    value = dict(status='v56_saved_common_direction_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names,
        failures=0, errors=0, skipped=0, seconds=perf_counter() - start,
        log=describe(path), scope=SCOPE)
    saved.v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v56_saved_common_direction_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['suites'] != list(SUITES)
            or value['scope'] != SCOPE or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V56 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        reference = prior.build()
    if reference != read(ROOT / prior.REPORT):
        raise ValueError('Saved V55 time-reference analysis does not reproduce')
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
    return dict(status='v56_saved_v48_common_direction_reconciled',
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        scope=SCOPE, **result, measured_evidence=evidence,
        interpretation='Every query timer is centered on its own same-stage/arm/position six-pair median, '
          'including itself. Four fixed cases have two arms each; no stage, arm or window is pooled. '
          'Other-query summaries always exclude positions32/33, giving exactly46 equally weighted positions. '
          'Raw direction and strict plus/minus1ms descriptions are separate, including their target signs '
          'and strict-majority directions. One millisecond is a descriptive scale, not significance. '
          'Zero or within-threshold target direction leaves same/opposite counts and alignment undefined. '
          'Neutral-majority does not imply a directional majority. Differences are relative to historical '
          'medians, not paired C-minus-R effects or elapsed-time components. Same run does not mean '
          'simultaneous queries; fixed query order and shared baselines do not establish independence, '
          'host load, CPU, I/O or decoder causality. Other-five summaries remain overlapping descriptive '
          'references. No new experiment, query, decode or fit is run.')


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
            raise FileExistsError('Immutable V56 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Same-run directions differ from saved evidence')
        else:
            saved.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
                   run_stage_panels=result['run_stage_panels'], located_cells=result['located_cells']))


if __name__ == '__main__':
    main()
