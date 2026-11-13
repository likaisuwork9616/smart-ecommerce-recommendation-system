"""Compare saved timing variation for peers chosen by workload alone."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_workloads_v51 as prior
from scripts.retailrocket_session_knn_peer_matching_v52 import select_workload_peers
from scripts.retailrocket_session_knn_peer_variation_v52 import summarize_peer_variation


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
timing, saved = prior.prior, prior.saved
BASE = 'reports/stage12/retailrocket_session_knn_v52_peers_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_peers_v52.py'
SUITES = ('tests.test_retailrocket_session_knn_peer_matching_v52',
          'tests.test_retailrocket_session_knn_peer_variation_v52',
          'tests.test_retailrocket_session_knn_peers_v52')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_peer_matching_v52.py',
           'scripts/retailrocket_session_knn_peer_variation_v52.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
PRIOR_SHA = 'b02f274d0dc74813eee356403fcb5ad5a7245e16098e26e27d4045d401753545'
TARGETS = (32, 38)
SCOPE = dict(saved_windows=2, saved_entries=28, matched_saved_rows=1344, fixed_queries=48,
    target_positions=list(TARGETS), candidate_queries=46, formal_pairs_per_window=6,
    warmups_excluded_from_timing=True, workload_only_selection=True, new_experiments=0,
    new_queries=0, new_decodes=0, new_fit=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    prior.accepted()
    sources = prior.inputs()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V51 workload comparison')
    return [*sources, record]


def match_entries(records):
    checked = prior.collect_entries(records)
    # collect_entries has already required all 28 identity/workload vectors to
    # agree, including strict counter types in every saved entry.
    workloads = [row['sql_workload'] for row in records[0]['measured']['queries']]
    matches = select_workload_peers(workloads, TARGETS)
    return dict(matching=matches, saved_entries_checked=checked['saved_entries_checked'],
        matched_saved_rows=checked['matched_saved_rows'], unique_queries_counted=48,
        identity_order_and_workload_equal=True)


def compare_window(comparison, matching):
    pairs = comparison['pairs']
    if (len(pairs) != 6
            or [(row['pair'], row['order']) for row in pairs] != list(enumerate(saved.v47.cold.ORDERS, 1))
            or any(len(row['position_extras_seconds']) != 48 for row in pairs)):
        raise ValueError('Exactly six original CR/RC pairs of 48 differences required')
    values = {position: [row['position_extras_seconds'][position - 1] for row in pairs]
              for position in range(1, 49)}
    published = comparison['positions']
    if [row['position'] for row in published] != list(range(1, 49)):
        raise ValueError('Original 48 position summaries required')
    for position, row in enumerate(published, 1):
        if timing.signed_distribution(values[position]) != row['distribution']:
            raise ValueError('Saved six-pair differences do not reproduce V50 position summary')
    return {str(target): {
        name: summarize_peer_variation(values, target, matching['targets'][str(target)][field])
        for name, field in (('primary', 'primary_positions'), ('expanded', 'expanded_positions'))}
        for target in TARGETS}


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V52 tool acceptance already exists')
    methods, sources = [describe(ROOT / name) for name in METHODS], inputs()
    folder = saved.v48.PRIVATE / ('knn-v52-peer-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = saved.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline workload-peer tests failed')
    verify_bindings([*methods, *sources])
    value = dict(status='v52_saved_workload_peer_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names,
        failures=0, errors=0, skipped=0, seconds=perf_counter() - start,
        log=describe(path), scope=SCOPE)
    saved.v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v52_saved_workload_peer_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['suites'] != list(SUITES)
            or value['scope'] != SCOPE or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V52 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        workload_report = prior.build()
    if workload_report != read(ROOT / prior.REPORT):
        raise ValueError('Saved V51 workload report does not reproduce')
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
    matched = match_entries(records)
    timing_report = read(ROOT / timing.REPORT)
    windows = {name: compare_window(timing_report['windows'][name]['comparison'], matched['matching'])
               for name in ('V47', 'V48')}
    verify_bindings([*receipt['methods'], *receipt['inputs'], *evidence])
    return dict(status='v52_saved_workload_peers_and_variation_compared',
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        scope=SCOPE, **matched, windows=windows, measured_evidence=evidence,
        interpretation='Peers are selected from the other 46 positions using logical workload only, never timing. '
          'Primary 5/4 and expanded 3/2 symmetric-fold rules retain all matches. Nonmatching nearest positions '
          'are not relabeled as comparable. Timing is the saved V50 query charge: verification plus append '
          'excluding commit plus in-query commit; tail commit and warmups are excluded. Positive means V46 '
          'took longer. Peer median is computed within each of the six pairs before subtracting from the target. '
          'MAD is unscaled. The 1 ms band and workload bounds are descriptive, not significance tests. '
          'Six pairs repeat the same queries and peer sets may overlap. Fixed query order makes these different '
          'time positions, not simultaneous controls; subtraction does not remove host-load or other confounding. '
          'Bit width and catalog size are disclosed diagnostics, not matching criteria. There is no causal '
          'claim about the decoder, CPU, I/O or scheduling, and no generalization to unseen data. '
          'Targets and records were already exposed in V50/V51; freezing peer rules now does not make '
          'this a new confirmatory experiment.')


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
            raise FileExistsError('Immutable V52 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Peer comparison differs from saved evidence')
        else:
            saved.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
            peers={position: {key: row[key] for key in ('primary_positions', 'expanded_positions')}
                   for position, row in result['matching']['targets'].items()}))


if __name__ == '__main__':
    main()
