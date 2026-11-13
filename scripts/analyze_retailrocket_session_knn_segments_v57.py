"""Describe fixed ordinal blocks and same-direction runs in saved V48 phases."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from math import isfinite
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_common_direction_v56 as prior
from scripts.retailrocket_session_knn_segments_v57 import analyze_segments, BLOCKS


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
saved = prior.saved
BASE = 'reports/stage12/retailrocket_session_knn_v57_segments_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_segments_v57.py'
SUITES = ('tests.test_retailrocket_session_knn_segments_v57',
          'tests.test_retailrocket_session_knn_segment_analysis_v57')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_segments_v57.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
PRIOR_SHA = '2bbdd00b82acf8d338c1a1f45206e479e02e9d729e543acf4fe56f232196e76e'
CASES, ORDERS = prior.CASES, prior.ORDERS
SCOPE = dict(saved_windows_checked=2, saved_entries_checked=28, matched_saved_rows=1344,
    analysis_window='V48', positions=list(range(1, 49)), target_positions=[32, 33],
    arms=dict(R='V39 original', C='V46 candidate'), reference_groups=192,
    reference_values_per_group=6, unique_reference_timers=1152, run_stage_panels=8,
    located_cells=384, other_cells=368, target_cells=16, threshold_seconds=.001,
    blocks=[dict(start=start, end=end) for start, end in BLOCKS],
    primary_view='other46', contextual_view='all48', block_summaries=96,
    cases=[dict(pair=pair, stage=stage) for pair, stage in CASES],
    new_experiments=0, new_queries=0, new_decodes=0, new_fit=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    prior.accepted()
    sources = prior.inputs()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V56 common-direction analysis')
    return [*sources, record]


def finite(value, name, nonnegative=False):
    try:
        valid = type(value) in (int, float) and isfinite(value) and (not nonnegative or value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Finite numeric V56 field required: ' + name)
    return value


def analyze_reference(reference):
    for name in ('saved_entries_checked', 'matched_saved_rows', 'reference_groups', 'unique_reference_timers',
                 'run_stage_panels', 'located_cells', 'other_cells', 'target_cells'):
        if type(reference[name]) is not int or reference[name] != SCOPE[name]:
            raise ValueError('Unchanged V56 scope required: ' + name)
    expected_cases = [('V48', pair, ORDERS[pair - 1], stage) for pair, stage in CASES]
    if [(row['window'], row['pair'], row['order'], row['stage']) for row in reference['cases']] != expected_cases:
        raise ValueError('Exactly the four original V56 cases are required')
    cases = []
    for original in reference['cases']:
        pair, arms = original['pair'], {}
        if set(original['arms']) != {'R', 'C'}:
            raise ValueError('Exactly the two original V56 arms are required')
        for arm in ('R', 'C'):
            source = original['arms'][arm]
            if (source['pair'] != pair or source['arm_run_position'] != ORDERS[pair - 1].index(arm) + 1
                    or set(source['positions']) != {str(position) for position in range(1, 49)}):
                raise ValueError('Original V56 pair, arm order and all 48 positions required')
            deltas = {}
            for position in range(1, 49):
                cell = source['positions'][str(position)]
                seconds = finite(cell['seconds'], 'absolute seconds', True)
                median = finite(cell['full_six']['median_seconds'], 'six median', True)
                delta = finite(cell['delta_from_median_seconds'], 'centered seconds')
                if cell['pair'] != pair or cell['full_six']['count'] != 6 or delta != seconds - median:
                    raise ValueError('V56 timer must reconcile to its own six-value median')
                deltas[position] = delta
            result = analyze_segments(deltas)
            others = result['views']['other46']
            old = source['other46_summary']
            if source['other_positions'] != [p for p in range(1, 49) if p not in (32, 33)] or old['count'] != 46:
                raise ValueError('Exactly the original other46 population is required')
            for mode, field, neutral in (('raw', 'direction_counts', 'equal'),
                                         ('over_1ms', 'over_1ms_counts', 'within')):
                counts = others['modes'][mode]['counts']
                expected = dict(above=old[field]['above'], neutral=old[field][neutral], below=old[field]['below'])
                if counts != expected:
                    raise ValueError('Segment totals differ from V56 direction counts')
                target_counts = dict.fromkeys(('above', 'neutral', 'below'), 0)
                for position in (32, 33):
                    row = result['positions'][position - 1]
                    target_counts[row[mode + '_direction']] += 1
                if result['views']['all48']['modes'][mode]['counts'] != {
                        direction: counts[direction] + target_counts[direction] for direction in counts}:
                    raise ValueError('All48 must equal other46 plus the two targets')
            for position in (32, 33):
                if source['target_comparisons'][str(position)]['delta_seconds'] != deltas[position]:
                    raise ValueError('V56 target deviations must remain unchanged')
            arms[arm] = dict(arm_run_position=source['arm_run_position'], **result)
        cases.append(dict(window='V48', pair=pair, order=original['order'], stage=original['stage'], arms=arms))
    return dict(cases=cases, saved_entries_checked=28, matched_saved_rows=1344,
        reference_groups=192, unique_reference_timers=1152, run_stage_panels=8, located_cells=384,
        other_cells=368, target_cells=16, block_summaries=96,
        v56_direction_counts_and_targets_equal=True, all48_equals_other46_plus_targets=True)


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V57 tool acceptance already exists')
    methods, sources = [describe(ROOT / name) for name in METHODS], inputs()
    folder = saved.v48.PRIVATE / ('knn-v57-segment-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = saved.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline segment-rule tests failed')
    verify_bindings([*methods, *sources])
    value = dict(status='v57_saved_segment_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names,
        failures=0, errors=0, skipped=0, seconds=perf_counter() - start,
        log=describe(path), scope=SCOPE)
    saved.v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v57_saved_segment_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['suites'] != list(SUITES)
            or value['scope'] != SCOPE or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V57 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        reference = prior.build()
    if reference != read(ROOT / prior.REPORT):
        raise ValueError('Saved V56 common-direction analysis does not reproduce')
    result = analyze_reference(reference)
    verify_bindings([*receipt['methods'], *receipt['inputs'], *reference['measured_evidence']])
    return dict(status='v57_saved_v48_ordinal_segments_reconciled',
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        scope=SCOPE, **result, measured_evidence=reference['measured_evidence'], v56_reproduced=True,
        interpretation='The six nonoverlapping ordinal blocks are fixed at1-8,9-16,17-24,25-32,33-40,41-48. '
          'Primary other46 excludes32/33 without closing their gaps; all48 is contextual. Each deviation '
          'retains its same-position/stage/arm six-value median from V56. Raw and strict plus/minus1ms '
          'modes are separate. Block density uses eligible block size; directional shares use the same '
          'panel/view/mode/direction total, with null shares for a zero denominator. Every maximal '
          'same-direction nonneutral run is retained; opposite signs, neutral values or excluded targets '
          'break a run, but fixed block boundaries do not. All tied longest runs and singletons remain. '
          'Blocks and run statistics are descriptions with no significance or outlier threshold, '
          'and no choice of boundaries or thresholds after viewing these segment results. Different '
          'queries and phases interleave in time; adjacent query ordinals do not establish simultaneous '
          'or sustained host load, or decoder, CPU, I/O or scheduler causality. No new experiment is run.')


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
            raise FileExistsError('Immutable V57 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Ordinal segments differ from saved evidence')
        else:
            saved.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
                   panels=result['run_stage_panels'], block_summaries=result['block_summaries']))


if __name__ == '__main__':
    main()
