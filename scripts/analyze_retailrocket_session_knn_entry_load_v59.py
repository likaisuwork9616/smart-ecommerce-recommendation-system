"""Compare whole-entry load in sealed V47/V48 records without running workloads."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import hashlib
from io import StringIO
import json
from pathlib import Path
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.retailrocket_session_knn_entry_load_v59 import analyze_load_reports
from scripts.retailrocket_session_knn_reinforcement_v18 import summarize_telemetry


ROOT = Path(__file__).resolve().parents[1]
BASE = 'reports/stage12/retailrocket_session_knn_v59_entry_load_'
ACCEPTANCE = BASE + 'acceptance_20261116.json'
REPORT = BASE + 'analysis_20261116.json'
INVENTORY = 'reports/stage12/retailrocket_session_knn_v58_evidence_inventory_20261116.json'
INVENTORY_SHA = '2af4bb27f73ffdd4ee9beb2efba72a6f1d8c48bf999f0fd14a74fa408f2a6486'
SUITES = ('tests.test_retailrocket_session_knn_entry_load_v59',
          'tests.test_retailrocket_session_knn_entry_load_analysis_v59')
METHODS = ('scripts/analyze_retailrocket_session_knn_entry_load_v59.py',
           'scripts/retailrocket_session_knn_entry_load_v59.py',
           *(name.replace('.', '/') + '.py' for name in SUITES))
SCOPE = dict(windows=['V47', 'V48'], formal_pairs_per_window=6, formal_entries=24,
    warm_entries_separate=4, publishers_separate=2, expected_raw_files=120,
    expected_telemetry_summaries=30, new_experiments=0, new_queries=0, new_decodes=0,
    new_training=0, reserved_test='locked',
    population='Previously exposed fixed48 validation engineering records only.')


def describe(path):
    path = Path(path)
    raw = path.read_bytes()
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest())


def read(path):
    return json.loads(Path(path).read_bytes())


def verify(records):
    for record in records:
        if describe(ROOT / record['path']) != record:
            raise ValueError('Saved source changed: ' + record['path'])


def inputs():
    inventory = describe(ROOT / INVENTORY)
    if inventory['sha256'] != INVENTORY_SHA:
        raise ValueError('The sealed V58 inventory is required')
    value = read(ROOT / INVENTORY)
    records = [inventory, *value['sources'], *value['methods']]
    verify(records)
    return records


class SealedReader:
    def __init__(self, root, records):
        self.root = Path(root).resolve()
        self.index = {r['path']: r for r in records}
        if len(self.index) != len(records):
            raise ValueError('Duplicate manifest paths')
        self.checked = {}

    def read(self, name):
        path = (self.root / name).resolve()
        path.relative_to(self.root)
        record = self.index[name]
        raw = path.read_bytes()
        if (len(raw), hashlib.sha256(raw).hexdigest()) != (record['bytes'], record['sha256']):
            raise ValueError('Manifest bytes/SHA differ: ' + name)
        self.checked[name] = record
        return json.loads(raw)


def check_observation(raw, span, events, expected_load, label, mode, request):
    if any(value.get('label') != label or value.get('mode') != mode for value in (raw, span)):
        raise ValueError('Telemetry label/arm differs')
    if span.get('completed') is not True or span.get('repeat_index') != 0:
        raise ValueError('Completed original observation required')
    records = raw['records']
    rebuilt = summarize_telemetry(records, 0, .2)
    if rebuilt != expected_load:
        raise ValueError('Saved load does not reproduce from raw telemetry')
    lower, upper = (datetime.fromisoformat(request[k]) for k in ('created_utc', 'deadline_utc'))
    start, end = (datetime.fromisoformat(span[k]) for k in ('start_utc', 'end_utc'))
    if (lower.utcoffset() is None or upper.utcoffset() is None
            or not lower <= start <= end <= upper
            or not datetime.fromisoformat(records[0]['observed_utc']) <= start <= end
            <= datetime.fromisoformat(records[-1]['observed_utc'])
            or any(not lower <= datetime.fromisoformat(row['observed_utc']) <= upper for row in records)):
        raise ValueError('Observation outside original UTC window')
    roots = [e for e in events if e['phase'] == ('publisher.total' if label == 'publisher' else 'run.total')]
    if len(roots) != 1 or roots[0]['completed'] is not True:
        raise ValueError('One completed outer wall event required')
    event = roots[0]
    if not (records[0]['monotonic_seconds'] + records[0]['collector_seconds']
            <= span['start_monotonic_seconds'] <= event['start_ns'] / 1e9
            <= event['end_ns'] / 1e9 <= span['end_monotonic_seconds']
            <= records[-1]['monotonic_seconds']):
        raise ValueError('Raw telemetry must bracket the saved entry and event')
    return dict(summary_reproduced=True, bracketing_passed=True,
                span_seconds=span['end_monotonic_seconds'] - span['start_monotonic_seconds'],
                event_seconds=(event['end_ns'] - event['start_ns']) / 1e9,
                samples=len(records))


def load_window(report):
    reader = SealedReader(ROOT, report['closed_manifest']['window_evidence'])
    base = report['namespace']
    request = reader.read(base + '/request.json')
    bound = {r['path']: r for r in request['sources']}
    for method in read(ROOT / INVENTORY)['methods']:
        if bound.get(method['path']) != method:
            raise ValueError('Historical collector/entry source binding differs')
    checks, previous = {}, None
    for item in [*report['schedule'], dict(label='publisher', mode='publisher')]:
        label, mode = item['label'], item['mode']
        raw, span, events = (reader.read(base + '/' + label + '/' + name + '.json')
                             for name in ('telemetry_records', 'entry_span', 'events'))
        expected = report['publisher_load'] if label == 'publisher' else report['runs'][label]['load']
        checks[label] = check_observation(raw, span, events, expected, label, mode, request)
        if previous is not None and raw['records'][0]['monotonic_seconds'] < previous:
            raise ValueError('Sequential observation windows overlap')
        last = raw['records'][-1]
        previous = last['monotonic_seconds'] + last['collector_seconds']
        if label != 'publisher':
            entry = reader.read(base + '/' + label + '/entry.json')
            if (entry['label'] != label or entry['mode'] != 'baseline'
                    or entry['seconds'] != report['runs'][label]['accounting']['costs']['entry_seconds']):
                raise ValueError('Saved full-entry timer differs from original entry.json')
    return checks, list(reader.checked.values())


def write_new(path, value):
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(payload)


def suite_ids(suite):
    return [name for test in suite for name in (suite_ids(test) if isinstance(test, unittest.TestSuite) else [test.id()])]


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable acceptance already exists')
    sources = inputs()
    methods = [describe(ROOT / name) for name in METHODS]
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    names, log, started = suite_ids(suite), StringIO(), perf_counter()
    with redirect_stdout(log), redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(log.getvalue())
        raise ValueError('Saved entry-load analysis tests failed')
    seconds = perf_counter() - started
    folder = ROOT / 'shop-mysql-runtime/verification' / ('v59-entry-load-acceptance-' + uuid4().hex)
    folder.mkdir()
    (folder / 'tests.log').write_text(log.getvalue(), encoding='utf-8')
    verify([*methods, *sources])
    value = dict(status='v59_saved_entry_load_tools_accepted', methods=methods, inputs=sources,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names, failures=0, errors=0,
        skipped=0, seconds=seconds, log=describe(folder / 'tests.log'), scope=SCOPE)
    write_new(ROOT / ACCEPTANCE, value)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=seconds, new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v59_saved_entry_load_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != inputs() or value['scope'] != SCOPE
            or value['suites'] != list(SUITES) or value['tests_run'] <= 0
            or value['tests_run'] != len(set(value['passed_tests']))
            or any(value[k] != 0 for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('Unchanged accepted V59 methods required')
    verify([value['log'], *value['methods'], *value['inputs']])
    return value


def build():
    receipt = accepted()
    inventory = read(ROOT / INVENTORY)
    reports = {window: read(ROOT / source['path']) for window, source in
               zip(SCOPE['windows'], inventory['sources'], strict=True)}
    result = analyze_load_reports(reports)
    checks, evidence = {}, []
    for window, report in reports.items():
        checks[window], records = load_window(report)
        evidence.extend(records)
    if len(evidence) != SCOPE['expected_raw_files']:
        raise ValueError('Expected 120 targeted raw evidence files')
    verify([*receipt['methods'], *receipt['inputs'], *evidence])
    return dict(status='v59_saved_whole_entry_load_reconciled', acceptance=describe(ROOT / ACCEPTANCE),
        methods=receipt['methods'], inputs=receipt['inputs'], scope=SCOPE, analysis=result,
        observation_checks=checks, raw_evidence=evidence,
        interpretation='All six formal pairs in each window; warm entries and publisher stay separate. '
        'C-minus-R means greater candidate value, not necessarily worse load. CPU means describe '
        'the bracketing sample window, not exact entry boundaries; process CPU includes sampler work. '
        'No per-query interpolation, wall-minus-process-CPU wait estimate, collector subtraction, '
        'load adjustment, significance, correlation or causal attribution. No workload rerun or live sampling. '
        'Targeted raw load/timer verification only; prior output/workload audits are not rerun.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance', 'analysis', 'audit'):
        modes.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    if args.acceptance:
        return accept()
    if not args.audit and (ROOT / REPORT).exists():
        raise FileExistsError('Immutable analysis exists; use --audit')
    result = build()
    if args.audit:
        if read(ROOT / REPORT) != result:
            raise ValueError('Saved whole-entry load analysis does not reproduce')
    else:
        write_new(ROOT / REPORT, result)
    print(dict(report=REPORT, audit=args.audit, raw_files=len(result['raw_evidence']),
               formal_pairs=12, new_experiments=0))


if __name__ == '__main__':
    main()
