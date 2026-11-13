"""Describe query-time differences from the sealed V47/V48 records only."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from math import fsum, isclose, isfinite
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_phases_v49 as prior
from scripts.retailrocket_session_knn_query_distribution_v50 import query_parts, signed_distribution


ROOT, read, describe, verify_bindings = prior.ROOT, prior.read, prior.describe, prior.verify_bindings
BASE = 'reports/stage12/retailrocket_session_knn_v50_queries_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_queries_v50.py'
SUITES = ('tests.test_retailrocket_session_knn_query_distribution_v50',
          'tests.test_retailrocket_session_knn_queries_v50')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_query_distribution_v50.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
PRIOR_SHA = '98fc359a9af85e42a0dbffd1e8815a8fa12d430f723a4e44a46cc374486ff250'
SCOPE = dict(saved_windows=2, saved_entries=28, fixed_queries=48, formal_pairs_per_window=6,
    paired_query_observations_per_window=288, new_experiments=0, new_queries=0, new_decodes=0,
    new_fit=0, reserved_test='locked', population='Previously exposed fixed48 validation engineering records.')


def inputs():
    records = prior.input_descriptors()
    record = describe(ROOT / prior.REPORT)
    if record['sha256'] != PRIOR_SHA:
        raise ValueError('Expected the sealed V49 phase analysis')
    return [*records, record]


def close(actual, expected, name):
    if not isclose(actual, expected, rel_tol=0, abs_tol=1e-8):
        raise ValueError('Saved query costs do not reconcile: ' + name)


def extract_entry(measured, accounting, expected_identity=None):
    rows = measured['queries']
    if (len(rows) != 48 or measured['committed_prefix_rows'] != 0
            or measured['verified_subset_queries'] != 48):
        raise ValueError('Original fresh 48-query entry required')
    identity, queries = [], []
    for index, row in enumerate(rows):
        if (type(row['subset_ordinal']) is not int or row['subset_ordinal'] != index
                or type(row['original_ordinal']) is not int or row['original_ordinal'] < 0
                or type(row['key_sha256']) is not str or len(row['key_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in row['key_sha256'])
                or not isinstance(row['sql_workload'], dict)):
            raise ValueError('Query identity, position or logical workload is invalid')
        identity.append((row['original_ordinal'], row['key_sha256'], row['sql_workload']))
        queries.append(dict(position=index + 1, **query_parts(row)))
    if len({(item[0], item[1]) for item in identity}) != 48:
        raise ValueError('Unique fixed-query identities required')
    if expected_identity is not None and identity != expected_identity:
        raise ValueError('Fixed query identities, order or SQL workload changed')
    cost = accounting['costs']
    for field, source in (('verification_seconds', 'verification_seconds'),
                          ('append_excluding_commit_seconds', 'append_without_commit_seconds'),
                          ('rank_seconds', 'rank_seconds')):
        close(fsum(row[source] for row in rows), cost[field], field)
    query_commit = fsum(row['chunk_commit_seconds'] for row in rows)
    close(query_commit, accounting['query_nested_commit_seconds'], 'query commit')
    for event in measured['chunk_commits']:
        if event.get('completed') is not True or type(event['seconds']) not in (int, float) \
                or not isfinite(event['seconds']) or event['seconds'] < 0:
            raise ValueError('Completed nonnegative commit timer required')
    all_commit = fsum(event['seconds'] for event in measured['chunk_commits'])
    close(all_commit, cost['all_commit_seconds'], 'all commit')
    tail_commit = all_commit - query_commit
    if tail_commit < -1e-8:
        raise ValueError('Query commits exceed all commits')
    close(tail_commit, accounting['tail_commit_seconds'], 'tail commit')
    charged = fsum(row['query_charged_seconds'] for row in queries)
    close(charged + tail_commit, cost['primary_seconds'], 'primary')
    return dict(queries=queries, query_charged_seconds=charged, tail_commit_seconds=tail_commit,
                primary_seconds=cost['primary_seconds']), identity


def summarize_window(entries, schedule, primary_extras):
    if schedule != prior.v47.cold.SCHEDULE or set(entries) != {row['label'] for row in schedule}:
        raise ValueError('Original 14-entry schedule required')
    if len(primary_extras) != 6:
        raise ValueError('Six original primary differences required')
    for entry in entries.values():
        if [row['position'] for row in entry['queries']] != list(range(1, 49)):
            raise ValueError('All 48 fixed positions required in each entry')
        close(fsum(row['query_charged_seconds'] for row in entry['queries']), entry['query_charged_seconds'], 'entry queries')
        close(entry['query_charged_seconds'] + entry['tail_commit_seconds'], entry['primary_seconds'], 'entry primary')
    pairs, all_cells = [], []
    for number, order in enumerate(prior.v47.cold.ORDERS, 1):
        original, candidate = (entries[f'pair_{number}_{arm}'] for arm in ('R', 'C'))
        cells = []
        for left, right in zip(original['queries'], candidate['queries'], strict=True):
            if left['position'] != right['position']:
                raise ValueError('Matched fixed query positions required')
            delta = right['query_charged_seconds'] - left['query_charged_seconds']
            parts = {key: right['parts_seconds'][key] - value for key, value in left['parts_seconds'].items()}
            close(fsum(parts.values()), delta, 'paired query components')
            cells.append(dict(position=left['position'], extra_seconds=delta, parts_extra_seconds=parts))
        tail = candidate['tail_commit_seconds'] - original['tail_commit_seconds']
        primary = candidate['primary_seconds'] - original['primary_seconds']
        close(fsum(row['extra_seconds'] for row in cells) + tail, primary, 'paired primary')
        close(primary, primary_extras[number - 1], 'V49 paired primary')
        pairs.append(dict(pair=number, order=order, distribution=signed_distribution(row['extra_seconds'] for row in cells),
            parts_extra_seconds={key: fsum(row['parts_extra_seconds'][key] for row in cells) for key in cells[0]['parts_extra_seconds']},
            top_positive_positions=sorted((row for row in cells if row['extra_seconds'] > 0),
                key=lambda row: (-row['extra_seconds'], row['position']))[:5],
            tail_commit_extra_seconds=tail, primary_extra_seconds=primary,
            position_extras_seconds=[row['extra_seconds'] for row in cells]))
        all_cells.extend(cells)
    positions = []
    for position in range(1, 49):
        selected = [row for row in all_cells if row['position'] == position]
        if len(selected) != 6:
            raise ValueError('Six matched differences required for every fixed query')
        positions.append(dict(position=position, distribution=signed_distribution(row['extra_seconds'] for row in selected),
            parts_extra_seconds={key: fsum(row['parts_extra_seconds'][key] for row in selected)
                                 for key in selected[0]['parts_extra_seconds']}))
    pooled = signed_distribution(row['extra_seconds'] for row in all_cells)
    position_net = signed_distribution(row['distribution']['net_seconds'] for row in positions)
    close(pooled['net_seconds'], position_net['net_seconds'], 'pooled versus position net')
    return dict(pairs=pairs, pooled_query_differences=pooled,
        formal_tail_commit_extra_seconds=fsum(pair['tail_commit_extra_seconds'] for pair in pairs),
        formal_primary_extra_seconds=fsum(pair['primary_extra_seconds'] for pair in pairs),
        parts_extra_seconds={key: fsum(row['parts_extra_seconds'][key] for row in all_cells)
                             for key in all_cells[0]['parts_extra_seconds']},
        by_order={order: signed_distribution(delta for pair in pairs if pair['order'] == order
                                            for delta in pair['position_extras_seconds']) for order in ('CR', 'RC')},
        positions=positions, position_net_distribution=position_net,
        position_median_distribution=signed_distribution(row['distribution']['median'] for row in positions),
        positive_repeat_histogram={str(count): sum(row['distribution']['positive_count'] == count for row in positions)
                                   for count in range(7)},
        above_1ms_repeat_histogram={str(count): sum(row['distribution']['above_1ms'] == count for row in positions)
                                    for count in range(7)},
        top_net_positive_positions=sorted((row for row in positions if row['distribution']['net_seconds'] > 0),
            key=lambda row: (-row['distribution']['net_seconds'], row['position']))[:10],
        warmup_costs={arm: {key: entries['warm_' + arm][key] for key in
                           ('query_charged_seconds', 'tail_commit_seconds', 'primary_seconds')} for arm in ('R', 'C')})


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V50 tool acceptance already exists')
    methods, source_reports = [describe(ROOT / name) for name in METHODS], inputs()
    folder = prior.v48.PRIVATE / ('knn-v50-query-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = prior.suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline query distribution tests failed')
    verify_bindings([*methods, *source_reports])
    receipt = dict(status='v50_saved_query_distribution_tools_accepted', methods=methods, inputs=source_reports,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names, failures=0, errors=0, skipped=0,
        seconds=perf_counter() - start, log=describe(path), scope=SCOPE)
    prior.v48.public_json(ROOT / ACCEPTANCE, receipt, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=receipt['seconds'], new_experiments=0))
    return receipt


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v50_saved_query_distribution_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS] or value['inputs'] != inputs()
            or value['suites'] != list(SUITES) or value['scope'] != SCOPE
            or value['tests_run'] != len(set(value['passed_tests'])) or value['tests_run'] <= 0
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V50 methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    with redirect_stdout(StringIO()):
        phases = prior.build()
    if phases != read(ROOT / prior.REPORT):
        raise ValueError('Saved V49 phase analysis does not reproduce')
    windows, evidence, identity = {}, [], None
    for label, runner in (('V47', prior.v47), ('V48', prior.v48)):
        report = read(ROOT / runner.REPORT)
        index = {record['path']: record for record in report['closed_manifest']['window_evidence']}
        entries = {}
        for item in report['schedule']:
            name = item['label']
            measured, source = prior.sealed_json(ROOT / report['namespace'] / name / 'measured.json', index)
            entries[name], current_identity = extract_entry(measured, report['runs'][name]['accounting'], identity)
            if identity is None:
                identity = current_identity
            evidence.append(source)
        phase_pairs = phases['windows'][label]['comparison']['pairs']
        summary = summarize_window(entries, report['schedule'], [row['parts_extra_seconds']['primary'] for row in phase_pairs])
        close(summary['formal_primary_extra_seconds'],
              phases['windows'][label]['comparison']['formal']['parts_extra_seconds']['primary']['sum'], 'V49 window primary')
        windows[label] = dict(report=describe(ROOT / runner.REPORT), comparison=summary,
            entry_slower_pairs=phases['windows'][label]['comparison']['slower_pairs'], saved_entries_checked=14,
            matched_saved_rows=672, raw_query_identity_and_workload_equal=True)
    verify_bindings([*receipt['methods'], *receipt['inputs'], *evidence])
    return dict(status='v50_saved_fixed48_query_time_distribution_reconciled', acceptance=describe(ROOT / ACCEPTANCE),
        inputs=receipt['inputs'], methods=receipt['methods'], scope=SCOPE, windows=windows, measured_evidence=evidence,
        interpretation='Positive V46-minus-V39 means more time. 288 observations repeat the same 48 queries six times; '
          'they are not 288 independent queries. Positive-mass concentration excludes negative offsets from its denominator. '
          'Pooled-observation positive mass and positive mass after summing each position are distinct denominators. '
          'Positions are anonymous 1-based subset indexes; no original keys, hashes, ordinals or SQL rows are published. '
          'The 1 ms band is descriptive, not statistical significance. Tail commit is not allocated to a query. '
          'Timing records locate observed differences without proving decoder or host-load causality.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance', 'analysis', 'audit'):
        modes.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    with prior.v48.entry.exclusive():
        if args.acceptance:
            return accept()
        path = ROOT / REPORT
        if not args.audit and path.exists():
            raise FileExistsError('Immutable V50 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Query analysis differs from saved evidence')
        else:
            prior.v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, new_experiments=0,
            query_net_seconds={key: value['comparison']['pooled_query_differences']['net_seconds']
                               for key, value in result['windows'].items()}))


if __name__ == '__main__':
    main()
