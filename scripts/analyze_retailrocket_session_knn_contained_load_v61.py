"""Compare saved loads only on V60's fully contained adjacent sample pairs."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_phase_coverage_v60 as prior
from scripts.retailrocket_session_knn_entry_load_v59 import SCHEDULE
from scripts.retailrocket_session_knn_coarse_phases_v60 import PHASES
from scripts.retailrocket_session_knn_contained_load_v61 import (
    summarize_selected, flatten_metrics, METRIC_UNITS, DELTA_UNITS, POLICY)
from scripts.retailrocket_session_knn_contained_pairs_v61 import summarize_window


ROOT, read, describe, verify, write_new = prior.ROOT, prior.read, prior.describe, prior.verify, prior.write_new
BASE = 'reports/stage12/retailrocket_session_knn_v61_contained_load_'
ACCEPTANCE = BASE + 'acceptance_20261116.json'
REPORT = BASE + 'analysis_20261116.json'
PRIOR_SHA = '6be051d712a69e44bb217f324bf417d5806524128698a7029419cfe28bab452e'
SUITES = ('tests.test_retailrocket_session_knn_contained_load_v61',
          'tests.test_retailrocket_session_knn_contained_pairs_v61',
          'tests.test_retailrocket_session_knn_contained_load_analysis_v61')
METHODS = ('scripts/analyze_retailrocket_session_knn_contained_load_v61.py',
           'scripts/retailrocket_session_knn_contained_load_v61.py',
           'scripts/retailrocket_session_knn_contained_pairs_v61.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
SCOPE = dict(windows=['V47', 'V48'], formal_pairs=12, formal_entries=24,
    phases=list(PHASES), formal_phase_windows=168, phase_pair_comparisons=84,
    warm_entries_separate=4, warm_phase_windows_separate=28,
    publisher_contexts_separate=2, rechecked_raw_files=120, directly_read_telemetry_files=28,
    selection='Exactly V60 capture_hull_contained adjacent pairs; no bridging or proration.',
    new_experiments=0, new_queries=0, new_decodes=0, new_training=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def inputs():
    receipt = prior.accepted()
    report = describe(ROOT / prior.REPORT)
    if report['sha256'] != PRIOR_SHA:
        raise ValueError('Sealed V60 coverage report required')
    records = [*receipt['inputs'], *receipt['methods'], describe(ROOT / prior.ACCEPTANCE), report]
    unique = {row['path']: row for row in records}
    verify(list(unique.values()))
    return list(unique.values())


def analyze_entry(records, coverage_entry, entry_seconds):
    if tuple(coverage_entry['phases']) != PHASES:
        raise ValueError('All seven frozen coarse phases required')
    phases = {}
    for name, row in coverage_entry['phases'].items():
        summary = summarize_selected(records, row['coverage'])
        phases[name] = dict(source_kind=row['source_kind'], source_event_ids=deepcopy(row['source_event_ids']),
            coverage_screen=deepcopy(row['coverage']['screen']),
            summary=summary, metrics=flatten_metrics(summary))
    return dict(entry_seconds=entry_seconds, phases=phases)


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V61 acceptance exists')
    sources, methods = inputs(), [describe(ROOT / name) for name in METHODS]
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    names, log, started = prior.prior.suite_ids(suite), StringIO(), perf_counter()
    with redirect_stdout(log), redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(log.getvalue())
        raise ValueError('V61 synthetic contained-load tests failed')
    seconds = perf_counter() - started
    folder = ROOT / 'shop-mysql-runtime/verification' / ('v61-contained-load-acceptance-' + uuid4().hex)
    folder.mkdir()
    (folder / 'tests.log').write_text(log.getvalue(), encoding='utf-8')
    verify([*methods, *sources])
    value = dict(status='v61_contained_load_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names, failures=0, errors=0,
        skipped=0, seconds=seconds, log=describe(folder / 'tests.log'), scope=SCOPE)
    write_new(ROOT / ACCEPTANCE, value)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=seconds, new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v61_contained_load_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['scope'] != SCOPE
            or value['suites'] != list(SUITES) or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V61 methods required')
    verify([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    previous = prior.build()
    if previous != read(ROOT / prior.REPORT):
        raise ValueError('V60 coverage reconstruction changed')
    original = prior.prior
    inventory = read(ROOT / original.INVENTORY)
    windows, evidence = {}, []
    for window, descriptor in zip(SCOPE['windows'], inventory['sources'], strict=True):
        report = read(ROOT / descriptor['path'])
        if report['schedule'] != SCHEDULE:
            raise ValueError('All original scheduled entries required')
        reader = original.SealedReader(ROOT, report['closed_manifest']['window_evidence'])
        old = previous['windows'][window]
        coverage_entries = {**old['warm_entries'], **old['formal_entries']}
        entries = {}
        for item in SCHEDULE:
            label = item['label']
            raw = reader.read(report['namespace'] + '/' + label + '/telemetry_records.json')
            entries[label] = analyze_entry(raw['records'], coverage_entries[label],
                                          report['runs'][label]['accounting']['costs']['entry_seconds'])
        windows[window] = summarize_window(entries)
        windows[window]['publisher_context'] = deepcopy(old['publisher_context'])
        evidence.extend(reader.checked.values())
    if len(evidence) != SCOPE['directly_read_telemetry_files']:
        raise ValueError('Exactly twenty-eight selected telemetry sources required')
    verify([*receipt['methods'], *receipt['inputs'], *evidence])
    return dict(status='v61_saved_contained_load_reconciled', acceptance=describe(ROOT / ACCEPTANCE),
        scope=SCOPE, methods=receipt['methods'], inputs=receipt['inputs'],
        metric_units=METRIC_UNITS, delta_units=DELTA_UNITS, policy=deepcopy(POLICY), windows=windows,
        selected_telemetry_evidence=evidence, v60_reconstructed_equal=True,
        rechecked_raw_files=previous['rechecked_raw_files'],
        interpretation=[
            'Only original adjacent pairs with V60 capture_hull_contained=True are summarized; never bridge omitted pairs.',
            'CPU weighting uses stored capture-start differences, not phase duration or V60 confirmed interior.',
            'System CPU comes from the right sample. Process CPU requires stable identities and complete observations.',
            'Strict complete Ollama identity-set and scan requirements differ from the older partial-common-identity summary.',
            'Point gauges use the unique selected endpoints; shared endpoints are counted once.',
            'Disk deltas and process CPU increments describe only selected intervals; they are not full-phase costs.',
            'C-minus-R differences are descriptive, unadjusted, and use unequal sampled subsets when the intervals differ.',
            'No full-phase average, query32/33 attribution, CPU-versus-wait decomposition, causal claim or V46 adoption follows.',
            'Warm entries and publisher stay separate. No new experiment or live sampling is run.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance', 'analysis', 'audit'):
        modes.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    if args.acceptance:
        return accept()
    if not args.audit and (ROOT / REPORT).exists():
        raise FileExistsError('Immutable V61 report exists; use --audit')
    result = build()
    if args.audit:
        if result != read(ROOT / REPORT):
            raise ValueError('Saved contained-load result does not reproduce')
    else:
        write_new(ROOT / REPORT, result)
    print(dict(report=REPORT, audit=args.audit, formal_phase_windows=168,
               phase_pair_comparisons=84, rechecked_raw_files=result['rechecked_raw_files'], new_experiments=0))


if __name__ == '__main__':
    main()
