"""Repeat the unchanged V47 cold protocol in an independently sealed window."""
from datetime import datetime
from math import fsum
from pathlib import Path
from statistics import median
from uuid import uuid4

from scripts import freeze_retailrocket_session_knn_cold_v48 as frozen
from scripts import run_retailrocket_session_knn_cold_v47 as previous
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


ROOT, PRIVATE = previous.ROOT, previous.PRIVATE
read, write, describe, verify_bindings = previous.read, previous.write, previous.describe, previous.verify_bindings
entry, typed, common, cold = previous.entry, previous.typed, previous.common, previous.cold
command, public_json, ROLES = previous.command, previous.public_json, previous.ROLES
MODULE = 'scripts.run_retailrocket_session_knn_cold_v48'
SUITE = 'tests.test_retailrocket_session_knn_cold_v48'
SEEDS = (frozen.METHOD, MODULE.replace('.', '/') + '.py', SUITE.replace('.', '/') + '.py',
         'scripts/accept_retailrocket_session_knn_cold_v48.py')
REPORT = frozen.BASE + 'result_20261113.json'
ACCEPTANCE = frozen.BASE + 'acceptance_20261113.json'
ACCEPTANCE_SEAL = frozen.BASE + 'acceptance_seal_20261113.json'
ACCEPTED = 'v48_second_cold_window_entry_accepted'


def source_roster():
    sources, metadata = previous.source_contract()
    direct = common.source_inventory(SEEDS, dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    methods = common.merge_methods(metadata['context']['methods'], direct)
    return common.merge_methods(sources, [*frozen.specification()['predecessors'], *methods]), methods


def acceptance_seal():
    return dict(status='v48_second_cold_window_acceptance_sealed', acceptance=describe(ROOT / ACCEPTANCE),
                specification=describe(ROOT / frozen.SPEC), real_runs=0)


def folder_path(folder):
    folder = Path(folder).resolve()
    suffix = folder.name.removeprefix(frozen.WINDOW_PREFIX)
    if (folder.parent != PRIVATE.resolve() or not folder.name.startswith(frozen.WINDOW_PREFIX)
            or len(suffix) != 32 or any(c not in '0123456789abcdef' for c in suffix)):
        raise ValueError('Direct V48 cold namespace required')
    return folder


request_metadata = _clone(previous.request_metadata, frozen=frozen)
accepted_entry = _clone(previous.accepted_entry, frozen=frozen, acceptance_seal=acceptance_seal,
                        ACCEPTANCE=ACCEPTANCE, ACCEPTANCE_SEAL=ACCEPTANCE_SEAL, ACCEPTED=ACCEPTED, SUITE=SUITE)
source_contract = _clone(previous.source_contract, frozen=frozen, source_roster=source_roster,
                         accepted_entry=accepted_entry, request_metadata=request_metadata,
                         ACCEPTANCE=ACCEPTANCE, ACCEPTANCE_SEAL=ACCEPTANCE_SEAL)
contract = _clone(previous.contract, folder_path=folder_path, source_contract=source_contract)
existing_windows = _clone(previous.existing_windows, frozen=frozen)
completed_report = previous.completed_report


def run_role(folder, name, *, admit=contract, module=MODULE):
    return previous.run_role(folder, name, admit=admit, module=module)


def compare_windows(baseline, current):
    for key in ('schedule', 'arms', 'authority', 'reference'):
        if baseline[key] != current[key]:
            raise ValueError('Repeat window changed ' + key)
    for result in (baseline, current):
        if result['comparison'] != cold.comparison(result['runs']):
            raise ValueError('Window summary differs from signed pairs')
    windows = {}
    for label, result in (('V47', baseline), ('V48', current)):
        comparison = result['comparison']
        pairs = comparison['pairs']
        metrics = {}
        for key in cold.METRICS:
            deltas = [pair['saving_seconds'][key] for pair in pairs]
            metrics[key] = dict(comparison['medians'][key], slower_pairs=sum(x < 0 for x in deltas),
                tied_pairs=sum(x == 0 for x in deltas), min_saving_seconds=min(deltas), max_saving_seconds=max(deltas),
                min_saving_percent=min(pair['saving_percent'][key] for pair in pairs),
                formal_total_seconds={arm: fsum(pair[name][key] for pair in pairs)
                                      for arm, name in (('R', 'original'), ('C', 'candidate'))},
                formal_total_saving_seconds=fsum(deltas),
                including_warmup_total_seconds={arm: fsum([comparison['warmups'][arm][key],
                    *(pair[name][key] for pair in pairs)]) for arm, name in (('R', 'original'), ('C', 'candidate'))})
        formal_loads = [run['load'] for name, run in result['runs'].items() if name.startswith('pair_')]
        windows[label] = dict(metrics=metrics, entry_regressions=[dict(pair=pair['pair'], order=pair['order'],
            saving_seconds=pair['saving_seconds']['entry'], saving_percent=pair['saving_percent']['entry'])
            for pair in pairs if pair['saving_seconds']['entry'] < 0],
            load=dict(median_entry_system_cpu_percent=median(row['system_cpu_percent']['mean'] for row in formal_loads),
                minimum_available_memory_bytes=min(row['available_memory_bytes']['min'] for row in formal_loads),
                interpretation='Existing whole-system observations include the benchmark; descriptive, not causal.'))
    return dict(baseline=frozen.specification()['repeat']['baseline'], windows=windows,
        entry_slowdown_reproduced=bool(windows['V47']['entry_regressions'] and windows['V48']['entry_regressions']),
        scope='Two exposed fixed48 validation engineering windows; no new fit or reserved test.',
        adoption='Assessment only; production defaults are unchanged.')


def release(*, audit_only):
    windows = existing_windows()
    if len(windows) != 1:
        raise ValueError('Exactly one saved second cold window required')
    folder = folder_path(windows[0])
    path = ROOT / REPORT
    existing = read(path) if audit_only else None
    if not audit_only and path.exists():
        raise FileExistsError('Immutable V48 comparison result already exists; use --audit')
    request = read(folder / 'request.json')
    metadata = contract(folder, request)
    report, manifest = completed_report(folder, request, expected_manifest=existing['closed_manifest'] if existing else None)
    spec = frozen.specification()
    baseline = read(ROOT / previous.REPORT)
    if report['authority']['canonical'] != spec['canonical']:
        raise ValueError('Repeat authority differs from original model')
    if datetime.fromisoformat(request['created_utc']) <= datetime.fromisoformat(
            baseline['supervisor']['actual_exit_observed_utc']):
        raise ValueError('Second window must start after the sealed first window exits')
    report.update(status='v48_second_V39_V46_cold_window_measured', specification=metadata['specification'],
        acceptance=metadata['acceptance'], closed_manifest=manifest, real_runs=14, scope=spec['scope'], T_plan=None,
        repeat_comparison=compare_windows(baseline, report))
    if audit_only:
        if report != existing:
            raise ValueError('Public repeat comparison differs from stopped evidence')
    else:
        public_json(path, report, exclusive=True)
    print(dict(report=REPORT, audit=audit_only, checks=report['engineering_checks'],
               medians=report['comparison']['medians'], seconds=report['supervisor']['seconds'],
               slowdown_reproduced=report['repeat_comparison']['entry_slowdown_reproduced']))
    return report


def measure():
    with entry.exclusive():
        if (ROOT / REPORT).exists() or existing_windows():
            raise FileExistsError('Existing real request or result forbids another measurement')
        sources, metadata = source_contract()
        spec = frozen.specification()
        frozen.verify_original_reference(spec)
        verify_bindings([*spec['dependencies'].values(), *spec['original_binding']])
        for record in sources:
            if (ROOT / record['path']).stat().st_size != record['bytes']:
                raise ValueError('Sealed source size differs: ' + record['path'])
        folder = PRIVATE / (frozen.WINDOW_PREFIX + uuid4().hex)
        print('V48 supervised namespace: ' + folder.relative_to(ROOT).as_posix(), flush=True)
        completion = entry.run_window(folder, command(MODULE, 'pipeline', folder), sources, 'joint_tail',
            metadata=metadata, budget_seconds=spec['budget_seconds'], limits=spec['limits'])
        entry.old._check_window(read(folder / 'request.json'), completion)
        return release(audit_only=False)


main = _clone(previous.main, measure=measure, release=release, run_role=run_role)


if __name__ == '__main__':
    main()
