"""Assess coarse interval coverage in saved telemetry, without allocating load."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from math import isfinite
from statistics import median
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_entry_load_v59 as prior
from scripts.retailrocket_session_knn_entry_load_v59 import SCHEDULE, ORDERS
from scripts.retailrocket_session_knn_coarse_phases_v60 import extract_phases, PHASES
from scripts.retailrocket_session_knn_phase_coverage_v60 import analyze_interval


ROOT, read, describe, verify, write_new = prior.ROOT, prior.read, prior.describe, prior.verify, prior.write_new
BASE = 'reports/stage12/retailrocket_session_knn_v60_phase_coverage_'
ACCEPTANCE = BASE + 'acceptance_20261116.json'
REPORT = BASE + 'analysis_20261116.json'
PRIOR_SHA = '1adee63a5807d89b98dae167891183a873d892608a6f33584eab49cdab8e586a'
SUITES = ('tests.test_retailrocket_session_knn_phase_coverage_v60',
          'tests.test_retailrocket_session_knn_coarse_phases_v60',
          'tests.test_retailrocket_session_knn_phase_coverage_analysis_v60')
METHODS = ('scripts/analyze_retailrocket_session_knn_phase_coverage_v60.py',
           'scripts/retailrocket_session_knn_phase_coverage_v60.py',
           'scripts/retailrocket_session_knn_coarse_phases_v60.py',
           *(name.replace('.', '/') + '.py' for name in SUITES),
           'scripts/retailrocket_session_knn_phase_accounting_v49.py',
           'scripts/retailrocket_session_knn_sources_v24.py',
           'tests/test_retailrocket_session_knn_phase_accounting_v49.py')
SCOPE = dict(windows=['V47', 'V48'], formal_pairs=12, formal_entries=24,
    phases=list(PHASES), formal_phase_windows=168, warm_entries_separate=4,
    warm_phase_windows_separate=28, publisher_contexts_separate=2,
    original_raw_files_rechecked=120, minimum_contained_intervals=2,
    minimum_confirmed_interior_share=.5, new_experiments=0, new_queries=0,
    new_decodes=0, new_training=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    receipt = prior.accepted()
    report = describe(ROOT / prior.REPORT)
    if report['sha256'] != PRIOR_SHA:
        raise ValueError('Sealed V59 entry-load report required')
    records = [*receipt['inputs'], *receipt['methods'], describe(ROOT / prior.ACCEPTANCE), report]
    unique = {r['path']: r for r in records}
    verify(list(unique.values()))
    return list(unique.values())


def ns(value):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError('Finite nonnegative stored clock value required')
    converted = value * 1e9
    if not isfinite(converted):
        raise ValueError('Clock normalization overflows')
    return round(converted)


def normalize_records(records):
    return [dict(sequence=row['sequence'], start_ns=ns(row['monotonic_seconds']),
                 capture_ns=ns(row['collector_seconds'])) for row in records]


def analyze_entry(events, raw, source):
    extracted = extract_phases(events, source['accounting'], source.get('diagnostic'))
    records = normalize_records(raw['records'])
    return dict(root_duration_ns=extracted['root_duration_ns'],
        phases={phase['name']: dict(source_kind=phase['source_kind'],
            source_event_ids=phase['source_event_ids'],
            coverage=analyze_interval((phase['start_ns'], phase['end_ns']), records,
                                     origin_ns=extracted['root_start_ns']))
            for phase in extracted['phases']})


def distribution(values):
    good = [v for v in values if v is not None]
    return dict(count=len(values), valid=len(good), missing=len(values)-len(good),
        min=min(good) if good else None, median=median(good) if good else None,
        max=max(good) if good else None)


def summarize_window(entries):
    if set(entries) != {row['label'] for row in SCHEDULE}:
        raise ValueError('All fourteen original entries required')
    if any(tuple(entry['phases']) != PHASES for entry in entries.values()):
        raise ValueError('Exactly seven fixed phases per entry required')
    formal = {row['label']: entries[row['label']] for row in SCHEDULE[2:]}
    warm = {row['label']: entries[row['label']] for row in SCHEDULE[:2]}
    pairs = []
    for pair, order in enumerate(ORDERS, 1):
        decisions = {}
        for phase in PHASES:
            arms = {arm: formal[f'pair_{pair}_{arm}']['phases'][phase]['coverage'] for arm in ('R', 'C')}
            decisions[phase] = {arm: dict(eligible=value['screen']['eligible'],
                capture_hull_contained_count=value['capture_hull_contained_count'],
                capture_contained_interior_share=value['capture_contained_interior_share'])
                for arm, value in arms.items()}
            decisions[phase]['both_eligible'] = all(v['screen']['eligible'] for v in arms.values())
        pairs.append(dict(pair=pair, order=order, phases=decisions))
    summaries = {}
    for phase in PHASES:
        summaries[phase] = {}
        for arm in ('R', 'C'):
            rows = [formal[f'pair_{pair}_{arm}']['phases'][phase]['coverage'] for pair in range(1, 7)]
            summaries[phase][arm] = dict(phase_windows=6,
                eligible_count=sum(row['screen']['eligible'] for row in rows),
                no_contained_interval_count=sum(row['capture_hull_contained_count'] == 0 for row in rows),
                duration_ns=distribution([row['phase_duration_ns'] for row in rows]),
                contained_interval_count=distribution([row['capture_hull_contained_count'] for row in rows]),
                confirmed_interior_share=distribution([row['capture_contained_interior_share'] for row in rows]))
        summaries[phase]['both_eligible_pairs'] = [row['pair'] for row in pairs if row['phases'][phase]['both_eligible']]
    return dict(formal_entries=formal, pairs=pairs, formal_by_phase=summaries, warm_entries=warm)


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V60 acceptance exists')
    sources, methods = inputs(), [describe(ROOT / path) for path in METHODS]
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    names, log, started = prior.suite_ids(suite), StringIO(), perf_counter()
    with redirect_stdout(log), redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(log.getvalue())
        raise ValueError('V60 synthetic coverage tests failed')
    seconds = perf_counter() - started
    folder = ROOT / 'shop-mysql-runtime/verification' / ('v60-phase-coverage-acceptance-' + uuid4().hex)
    folder.mkdir()
    (folder / 'tests.log').write_text(log.getvalue(), encoding='utf-8')
    verify([*methods, *sources])
    value = dict(status='v60_coarse_coverage_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names, failures=0, errors=0,
        skipped=0, seconds=seconds, log=describe(folder / 'tests.log'), scope=SCOPE)
    write_new(ROOT / ACCEPTANCE, value)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=seconds, new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v60_coarse_coverage_tools_accepted'
            or value['methods'] != [describe(ROOT / path) for path in METHODS]
            or value['inputs'] != inputs() or value['scope'] != SCOPE
            or value['suites'] != list(SUITES) or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[k] != 0 for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V60 methods required')
    verify([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    previous = prior.build()
    if previous != read(ROOT / prior.REPORT):
        raise ValueError('V59 raw load/timer reconciliation changed')
    windows, selected_evidence = {}, []
    inventory = read(ROOT / prior.INVENTORY)
    for window, source in zip(SCOPE['windows'], inventory['sources'], strict=True):
        report = read(ROOT / source['path'])
        if report['schedule'] != SCHEDULE:
            raise ValueError('Original schedule required')
        reader = prior.SealedReader(ROOT, report['closed_manifest']['window_evidence'])
        entries = {}
        for item in SCHEDULE:
            label = item['label']
            base = report['namespace'] + '/' + label + '/'
            events, raw = (reader.read(base + name + '.json') for name in ('events', 'telemetry_records'))
            entries[label] = analyze_entry(events, raw, report['runs'][label])
        windows[window] = summarize_window(entries)
        windows[window]['publisher_context'] = previous['analysis']['windows'][window]['publisher']
        selected_evidence.extend(reader.checked.values())
    verify([*receipt['methods'], *receipt['inputs'], *selected_evidence])
    return dict(status='v60_saved_coarse_coverage_reconciled', scope=SCOPE,
        acceptance=describe(ROOT / ACCEPTANCE), methods=receipt['methods'], inputs=receipt['inputs'],
        windows=windows, selected_event_telemetry_files=selected_evidence,
        v59_raw_reconstruction_equal=True, rechecked_raw_files=len(previous['raw_evidence']),
        interpretation=[
            'Half-open nominal intervals; touching alone has no overlap. Each run is analyzed independently.',
            'Capture hull extends from first capture start through the next capture end. Hull-only overlaps are retained.',
            'Confirmed interior is the gap between first capture end and next capture start, not CPU or wait time.',
            'The prespecified screen needs at least two fully contained capture hulls and confirmed interiors covering at least half the phase.',
            'This is an operational temporal-coverage screen, not an accuracy, significance or causal threshold.',
            'Seven disjoint selected phases are not a complete additive entry partition. The post-setup envelope is not V49 primary.',
            'Nominal bracketing can be 100 percent while usable interval resolution is poor. Cross-boundary samples are never prorated.',
            'No resource values are allocated to phases, no query timestamps are reconstructed, and no new measurement is run.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance', 'analysis', 'audit'):
        modes.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    if args.acceptance:
        return accept()
    if not args.audit and (ROOT / REPORT).exists():
        raise FileExistsError('Immutable V60 report exists; use --audit')
    result = build()
    if args.audit:
        if result != read(ROOT / REPORT):
            raise ValueError('Saved coarse coverage does not reproduce')
    else:
        write_new(ROOT / REPORT, result)
    print(dict(report=REPORT, audit=args.audit, formal_phase_windows=168,
               rechecked_raw_files=result['rechecked_raw_files'], new_experiments=0))


if __name__ == '__main__':
    main()
