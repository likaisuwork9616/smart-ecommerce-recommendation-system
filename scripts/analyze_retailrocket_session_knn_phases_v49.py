"""Explain saved V47/V48 entry costs without executing an experiment."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
from io import StringIO
import json
from math import fsum, isclose, isfinite
from statistics import median
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import run_retailrocket_session_knn_cold_v47 as v47
from scripts import run_retailrocket_session_knn_cold_v48 as v48
from scripts.retailrocket_session_knn_phase_accounting_v49 import partition


ROOT, read, describe, verify_bindings = v48.ROOT, v48.read, v48.describe, v48.verify_bindings
BASE = 'reports/stage12/retailrocket_session_knn_v49_phases_'
ACCEPTANCE = BASE + 'acceptance_20261113.json'
REPORT = BASE + 'analysis_20261113.json'
METHOD = 'scripts/analyze_retailrocket_session_knn_phases_v49.py'
SUITES = ('tests.test_retailrocket_session_knn_phase_accounting_v49',
          'tests.test_retailrocket_session_knn_phases_v49')
METHODS = (METHOD, 'scripts/retailrocket_session_knn_phase_accounting_v49.py',
           *(suite.replace('.', '/') + '.py' for suite in SUITES),
           'scripts/retailrocket_session_knn_sources_v24.py')
INPUTS = ((v47.REPORT, '3ff9aa0eceb8e2ae79c02549953aad91f95fe8a3a3c9d5785a095b5d02a84ecd'),
          (v48.REPORT, 'f2e8349eea6261e144b6b23a93aa1999e65cc972625ae25a58e0b212b5d00b94'))
SCOPE = dict(saved_windows=2, saved_entries=28, saved_formal_pairs=12,
             new_experiments=0, new_queries=0, new_decodes=0, new_fit=0, reserved_test='locked',
             population='Previously exposed fixed48 validation engineering records only.')


def input_descriptors():
    records = [describe(ROOT / name) for name, _ in INPUTS]
    if any(record['sha256'] != expected for record, (_, expected) in zip(records, INPUTS, strict=True)):
        raise ValueError('Expected unchanged V47 and V48 reports')
    return records


def distribution(values):
    values = list(values)
    if not values or any(type(x) not in (int, float) or not isfinite(x) for x in values):
        raise ValueError('Finite nonempty observations required')
    return dict(sum=fsum(values), median=median(values), min=min(values), max=max(values))


def summarize_pairs(runs, schedule):
    if schedule != v47.cold.SCHEDULE or set(runs) != {item['label'] for item in schedule}:
        raise ValueError('All 14 entries in the original schedule are required')
    keys = tuple(runs['warm_R']['parts_seconds'])
    if any(set(row['parts_seconds']) != set(keys) for row in runs.values()):
        raise ValueError('Entry partition keys differ')
    pairs = []
    for index, order in enumerate(v47.cold.ORDERS, 1):
        original, candidate = (runs[f'pair_{index}_{arm}'] for arm in ('R', 'C'))
        extra = {key: candidate['parts_seconds'][key] - original['parts_seconds'][key] for key in keys}
        entry_extra = candidate['entry_seconds'] - original['entry_seconds']
        if not isclose(fsum(extra.values()), entry_extra, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError('Paired components do not conserve full entry difference')
        snapshots = {role: {key: candidate['snapshot_parts_seconds'][role][key]
            - original['snapshot_parts_seconds'][role][key]
            for key in original['snapshot_parts_seconds'][role]} for role in original['snapshot_parts_seconds']}
        details = {group: {key: candidate[group][key] - original[group][key] for key in original[group]}
                   for group in ('primary_parts_seconds', 'rank_parts_seconds')}
        pairs.append(dict(pair=index, order=order, entry_extra_seconds=entry_extra,
            nonreference_extra_seconds=entry_extra - extra['reference_build'],
            parts_extra_seconds=extra, snapshot_extra_seconds=snapshots, **details,
            largest_positive_nonreference_parts=[dict(part=key, extra_seconds=value)
                for key, value in sorted(extra.items(), key=lambda item: (-item[1], item[0]))
                if value > 0 and key not in ('reference_build', 'signed_entry_bridge')]))

    def aggregate(selected):
        return dict(pairs=[row['pair'] for row in selected],
            entry_extra_seconds=distribution(row['entry_extra_seconds'] for row in selected),
            nonreference_extra_seconds=distribution(row['nonreference_extra_seconds'] for row in selected),
            parts_extra_seconds={key: distribution(row['parts_extra_seconds'][key] for row in selected) for key in keys},
            snapshot_extra_seconds={role: {key: distribution(row['snapshot_extra_seconds'][role][key] for row in selected)
                for key in selected[0]['snapshot_extra_seconds'][role]} for role in selected[0]['snapshot_extra_seconds']},
            **{group: {key: distribution(row[group][key] for row in selected) for key in selected[0][group]}
               for group in ('primary_parts_seconds', 'rank_parts_seconds')})

    regressions = [row for row in pairs if row['entry_extra_seconds'] > 0]
    return dict(pairs=pairs, formal=aggregate(pairs),
        slower_pairs=[row['pair'] for row in regressions],
        slower_pairs_only=aggregate(regressions) if regressions else None,
        warmups={arm: runs['warm_' + arm] for arm in ('R', 'C')},
        interpretation='Positive C-minus-R means V46 took longer. Formal sums conserve; component medians need not sum. '
                       'Warmups are excluded. Slower-pair subsets are post-hoc descriptions, not independent samples. '
                       'Snapshot, primary and rank details are nested views; do not add them to the main parts.')


def suite_ids(suite):
    return [name for item in suite for name in (suite_ids(item) if isinstance(item, unittest.TestSuite) else [item.id()])]


def accept():
    if (ROOT / ACCEPTANCE).exists():
        raise FileExistsError('Immutable V49 tool acceptance already exists')
    methods, inputs = [describe(ROOT / name) for name in METHODS], input_descriptors()
    folder = v48.PRIVATE / ('knn-v49-analysis-tests-' + uuid4().hex)
    folder.mkdir()
    path = folder / 'tests.log'
    start = perf_counter()
    with path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        names = suite_ids(suite)
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not names:
        print(path.read_text(encoding='utf-8'))
        raise ValueError('Offline accounting tool tests failed')
    verify_bindings([*methods, *inputs])
    value = dict(status='v49_offline_accounting_tools_accepted', methods=methods, inputs=inputs,
        suites=list(SUITES), tests_run=result.testsRun, passed_tests=names, failures=0, errors=0, skipped=0,
        seconds=perf_counter() - start, log=describe(path), scope=SCOPE)
    v48.public_json(ROOT / ACCEPTANCE, value, exclusive=True)
    print(dict(acceptance=ACCEPTANCE, tests=result.testsRun, seconds=value['seconds'], new_experiments=0))
    return value


def accepted():
    value = read(ROOT / ACCEPTANCE)
    if (value['status'] != 'v49_offline_accounting_tools_accepted'
            or value['methods'] != [describe(ROOT / name) for name in METHODS]
            or value['inputs'] != input_descriptors() or value['suites'] != list(SUITES)
            or value['tests_run'] != len(value['passed_tests']) or value['tests_run'] <= 0
            or any(value[key] != 0 for key in ('failures', 'errors', 'skipped')) or value['scope'] != SCOPE):
        raise ValueError('Unchanged accepted offline methods required')
    verify_bindings([value['log'], *value['methods'], *value['inputs']])
    return value


def sealed_json(path, index):
    relative = path.relative_to(ROOT).as_posix()
    expected = index.get(relative)
    if expected is None:
        raise ValueError('Saved event file is outside the stopped evidence manifest')
    data = path.read_bytes()
    if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError('Saved event bytes differ from stopped evidence')
    return json.loads(data), expected


def build():
    tools = accepted()
    windows, evidence = {}, []
    baseline = None
    for label, runner in (('V47', v47), ('V48', v48)):
        # release(audit_only=True) only rechecks stopped records; it never calls a worker or decoder.
        before = runner.existing_windows()
        with redirect_stdout(StringIO()):
            report = runner.release(audit_only=True)
        if runner.existing_windows() != before:
            raise ValueError('Offline analysis must not create an execution window')
        if baseline is None:
            baseline = report
        elif any(report[key] != baseline[key] for key in ('authority', 'reference', 'schedule', 'arms')):
            raise ValueError('The two saved windows differ in source or protocol')
        index = {row['path']: row for row in report['closed_manifest']['window_evidence']}
        runs = {}
        for item in report['schedule']:
            name = item['label']
            events, source = sealed_json(ROOT / report['namespace'] / name / 'events.json', index)
            saved = report['runs'][name]
            row = partition(events, saved['accounting'], saved['diagnostic'])
            if not isclose(row['parts_seconds']['reference_build'], saved['reference_build_seconds'],
                           rel_tol=0, abs_tol=1e-9):
                raise ValueError('Passive reference build differs from published cost')
            runs[name] = row
            evidence.append(source)
        summary = summarize_pairs(runs, report['schedule'])
        original_saving = fsum(pair['saving_seconds']['entry'] for pair in report['comparison']['pairs'])
        if not isclose(summary['formal']['entry_extra_seconds']['sum'], -original_saving, rel_tol=0, abs_tol=1e-8):
            raise ValueError('Analysis changed the saved formal comparison')
        windows[label] = dict(report=describe(ROOT / runner.REPORT), runs=runs, comparison=summary,
            stopped_audit_passed=True, saved_checks=report['engineering_checks'],
            saved_tracked_processes=report['supervisor']['tracked_processes'],
            saved_alive_after_cleanup=report['supervisor']['tracked_processes_alive_after_cleanup'])
    verify_bindings([*tools['methods'], *tools['inputs'], *evidence])
    return dict(status='v49_saved_cold_entry_phases_reconciled', acceptance=describe(ROOT / ACCEPTANCE),
        methods=tools['methods'], inputs=tools['inputs'], scope=SCOPE, windows=windows,
        raw_event_evidence=evidence, event_trees=28,
        interpretation='Saved wall intervals locate observed differences; they do not establish CPU wait, '
                       'physical I/O, external-load causality or a causal effect of the decoder on other stages.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance', 'analysis', 'audit'):
        modes.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    with v48.entry.exclusive():
        if args.acceptance:
            return accept()
        path = ROOT / REPORT
        if not args.audit and path.exists():
            raise FileExistsError('Immutable V49 analysis exists; use --audit')
        result = build()
        if args.audit:
            if result != read(path):
                raise ValueError('Saved analysis differs from stopped evidence')
        else:
            v48.public_json(path, result, exclusive=True)
        print(dict(report=REPORT, audit=args.audit, event_trees=result['event_trees'], new_experiments=0,
            window_extras={key: value['comparison']['formal']['entry_extra_seconds']['sum']
                           for key, value in result['windows'].items()}))


if __name__ == '__main__':
    main()
