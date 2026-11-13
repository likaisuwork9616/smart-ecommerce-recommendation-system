"""Locate saved stage differences behind the fixed32/fixed33 reverse swings."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from math import isclose
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_peers_v52 as prior
from scripts.retailrocket_session_knn_peer_stages_v53 import compare_stage_pair, summarize_stage_pairs


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
timing, saved = prior.timing, prior.saved
BASE = 'reports/stage12/retailrocket_session_knn_v53_peer_stages_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_peer_stages_v53.py'
SUITES = ('tests.test_retailrocket_session_knn_peer_stages_v53',
          'tests.test_retailrocket_session_knn_peer_stage_analysis_v53')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_peer_stages_v53.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
PRIOR_SHA = '5d5025b021ed3ef965d463b123a6047dc6539ce309ac26e2bb3a01e8993f26f9'
POSITIONS = (32, 33)
SCOPE = dict(saved_windows=2, saved_entries=28, matched_saved_rows=1344,
    positions=list(POSITIONS), formal_pairs_per_window=6, selected_formal_query_rows=48,
    atomic_parts=11, grouped_parts=4, warmups_excluded=True, tail_commit_excluded=True,
    new_experiments=0, new_queries=0, new_decodes=0, new_fit=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    prior.accepted()
    sources = prior.inputs()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V52 workload-peer comparison')
    return [*sources, record]


def close(actual, expected, name):
    if not isclose(actual, expected, rel_tol=0, abs_tol=1e-8):
        raise ValueError('Stage analysis differs from V52: ' + name)


def stage_variation(pairs):
    """Describe each additive component, without adding component medians."""
    result = {}
    fields = ('sum', 'median', 'min', 'max', 'range', 'mad',
              'positive_count', 'negative_count', 'above_1ms', 'below_minus_1ms', 'within_1ms')
    for view, key in (('atomic', 'atomic_delta_seconds'), ('groups', 'group_delta_seconds')):
        result[view] = {}
        for stage in pairs[0]['positions']['32'][key]:
            values = {position: [row['positions'][str(position)][key][stage] for row in pairs]
                      for position in POSITIONS}
            summary = prior.summarize_peer_variation(values, 32, [33])
            result[view][stage] = {
                label: {field: source[field] for field in fields}
                for label, source in (('32', summary['target_summary']),
                    ('33', summary['peer_summaries'][0]['summary']),
                    ('gap_32_minus_33', summary['target_minus_peer_median_summary']))}
    return result


def analyze_entries(records, reference):
    checked = prior.prior.collect_entries(records)
    match = reference['matching']['targets']['32']
    if any(match[key] != [33] for key in ('primary_positions', 'expanded_positions')):
        raise ValueError('V52 must retain exactly fixed33 as both fixed32 peer sets')
    windows = {}
    for window in ('V47', 'V48'):
        entries = {row['label']: row for row in records if row['window'] == window}
        expected = reference['windows'][window]['32']['primary']
        if (expected != reference['windows'][window]['32']['expanded']
                or expected['target_position'] != 32
                or expected['pair_orders'] != list(saved.v47.cold.ORDERS)
                or [row['position'] for row in expected['peer_summaries']] != [33]):
            raise ValueError('Original V52 fixed32/fixed33 comparison required')
        peer = expected['peer_summaries'][0]
        pairs = []
        for number, order in enumerate(saved.v47.cold.ORDERS, 1):
            arms = [{position: timing.query_parts(entries[f'pair_{number}_{arm}']['measured']['queries'][position - 1])
                     for position in POSITIONS} for arm in ('R', 'C')]
            row = compare_stage_pair(*arms, pair=number, order=order)
            for position, series in ((32, expected['target_summary']), (33, peer['summary'])):
                close(row['positions'][str(position)]['total_delta_seconds'], series['values'][number - 1], 'query delta')
            close(row['gap_seconds'], expected['target_minus_peer_median_summary']['values'][number - 1], 'paired gap')
            pairs.append(row)
        summary = summarize_stage_pairs(pairs)
        if (len(summary['opposite_pair_numbers']) != peer['direction_vs_target']['opposite_sign_count']
                or sum(row['direction']['eligible'] for row in pairs) != peer['direction_vs_target']['eligible_count']):
            raise ValueError('Reverse-pair counts changed from V52')
        windows[window] = dict(**summary, stage_variation=stage_variation(pairs), v52_totals_reconciled=True)
    return dict(windows=windows, saved_entries_checked=checked['saved_entries_checked'],
        matched_saved_rows=checked['matched_saved_rows'], identity_order_and_workload_equal=True)


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V53 tool acceptance already exists')
    methods, sources = [describe(ROOT / name) for name in METHODS], inputs()
    folder = saved.v48.PRIVATE / ('knn-v53-peer-stage-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = saved.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline peer-stage tests failed')
    verify_bindings([*methods, *sources])
    value = dict(status='v53_saved_peer_stage_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names,
        failures=0, errors=0, skipped=0, seconds=perf_counter() - start,
        log=describe(path), scope=SCOPE)
    saved.v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v53_saved_peer_stage_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['suites'] != list(SUITES)
            or value['scope'] != SCOPE or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V53 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        reference = prior.build()
    if reference != read(ROOT / prior.REPORT):
        raise ValueError('Saved V52 peer analysis does not reproduce')
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
    summary = analyze_entries(records, reference)
    verify_bindings([*receipt['methods'], *receipt['inputs'], *evidence])
    return dict(status='v53_saved_fixed32_fixed33_stage_differences_reconciled',
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        scope=SCOPE, **summary, measured_evidence=evidence,
        interpretation='Each query delta is V46 minus V39; gap is delta32 minus delta33. '
          'Eleven atomic parts and four groups are alternative additive views, never added together. '
          'Reverse pairs require opposite query-delta signs and both absolute deltas strictly greater than 1 ms. '
          'Each reverse gap is aligned by its sign. Positive support and negative offsets are computed '
          'per pair and component before aggregation; shares use each view own gross positive support, not net. '
          'Aligned component support describes the gap, not necessarily opposite signs in that component. '
          'Remainders retain signed rounding differences; their names do not identify an observed activity. '
          'Full-six signed totals and post-hoc reverse subsets are separate. No sums of medians or MADs '
          'are treated as total costs. Warmups and tail commits are excluded. These are previously exposed, '
          'non-simultaneous wall-time records, not causal effects of decoder, CPU, I/O or host load.')


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
            raise FileExistsError('Immutable V53 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Stage analysis differs from saved evidence')
        else:
            saved.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
            reverse_pairs={name: row['opposite_pair_numbers'] for name, row in result['windows'].items()}))


if __name__ == '__main__':
    main()
