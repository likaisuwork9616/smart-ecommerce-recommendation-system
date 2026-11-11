"""Execute and independently release the sealed C1-S1 / V39 comparison."""
from math import fsum
from pathlib import Path
from uuid import uuid4

from scripts import freeze_retailrocket_session_knn_compare_v41 as frozen
from scripts import retailrocket_session_knn_compare_v41 as comparison
from scripts import run_retailrocket_session_knn_compare_v40 as prior
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


ROOT, PRIVATE = prior.ROOT, prior.PRIVATE
read, write, describe, verify_bindings = prior.read, prior.write, prior.describe, prior.verify_bindings
entry, typed, common = prior.entry, prior.typed, prior.common
public_json, command, request_metadata = prior.public_json, prior.command, prior.request_metadata
ROLES = prior.ROLES
MODULE = 'scripts.run_retailrocket_session_knn_compare_v41'
SUITE = 'tests.test_retailrocket_session_knn_compare_v41'
SEEDS = (frozen.METHOD, MODULE.replace('.', '/') + '.py', SUITE.replace('.', '/') + '.py',
         'scripts/retailrocket_session_knn_compare_v41.py', 'scripts/accept_retailrocket_session_knn_compare_v41.py')
ACCEPTANCE = frozen.BASE + 'acceptance_20261111.json'
ACCEPTANCE_SEAL = frozen.BASE + 'acceptance_seal_20261111.json'
REPORT = frozen.BASE + 'result_20261111.json'
ACCEPTED = 'v41_direct_typed_comparison_entry_accepted'


def source_roster():
    sources, metadata = prior.source_contract()
    direct = common.source_inventory(SEEDS, dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    methods = common.merge_methods(metadata['context']['methods'], direct)
    sources = common.merge_methods(sources, [describe(ROOT / prior.REPORT), *methods])
    return sources, methods


def acceptance_seal():
    return dict(status='v41_direct_typed_comparison_entry_acceptance_sealed', acceptance=describe(ROOT / ACCEPTANCE),
                specification=describe(ROOT / frozen.SPEC), real_runs=0)


accepted_entry = _clone(prior.accepted_entry, frozen=frozen, acceptance_seal=acceptance_seal,
                        ACCEPTANCE=ACCEPTANCE, ACCEPTANCE_SEAL=ACCEPTANCE_SEAL, ACCEPTED=ACCEPTED, SUITE=SUITE)
source_contract = _clone(prior.source_contract, frozen=frozen, source_roster=source_roster,
                         accepted_entry=accepted_entry, ACCEPTANCE=ACCEPTANCE, ACCEPTANCE_SEAL=ACCEPTANCE_SEAL)
def folder_path(folder):
    folder = Path(folder).resolve()
    suffix = folder.name.removeprefix(frozen.WINDOW_PREFIX)
    if (folder.parent != PRIVATE.resolve() or not folder.name.startswith(frozen.WINDOW_PREFIX)
            or len(suffix) != 32 or any(c not in '0123456789abcdef' for c in suffix)):
        raise ValueError('Direct V41 real namespace required')
    return folder


contract = _clone(prior.contract, folder_path=folder_path, source_contract=source_contract)
existing_windows = _clone(prior.existing_windows, frozen=frozen)


def run_role(folder, role, *, admit=contract, module=MODULE):
    folder = Path(folder).resolve()
    request = read(folder / 'request.json')
    _, diagnostics = common.quiet_contract(admit, folder, request)
    write(folder / (role + '_contract.json'), dict(role=role, request=describe(folder / 'request.json'),
        policy=typed.adapter.POLICY, diagnostics=diagnostics))
    print(role + ' contract verified')
    if role == 'pipeline':
        return entry.run_pipeline(folder, request, {name: command(module, name, folder) for name in ROLES[1:]})
    if role == 'worker':
        return comparison.run_worker(folder, request)
    return comparison.run_publisher(folder, request)


def _seconds(interval):
    return (interval['end_ns'] - interval['start_ns']) / 1e9


def _late_costs(saved, raw_original_late):
    if saved['original_late_checks'] != raw_original_late:
        raise ValueError('Original late timing evidence differs after exit')
    canonical = {row['root']: _seconds(row) for row in raw_original_late}
    typed_cold = saved['cache']['T']['call_observations'][0]['typed_reference']
    late = {row['root']: _seconds(row) for row in typed_cold['checks']}
    build = _seconds(typed_cold['build'])
    original = fsum(canonical.values())
    candidate = fsum([build, *late.values()])
    return dict(S_late_canonical_seconds=canonical, T_reference_build_seconds=build, T_late_typed_seconds=late,
        S_total_seconds=original, T_total_seconds=candidate, T_minus_S_seconds=candidate - original)


def completed_report(folder, request, *, expected_manifest=None):
    result, completion, exits, publisher, load = comparison.audit_completed(folder, request)
    seal = common.closed_log_manifest(folder, request, completion, exits, expected=expected_manifest)
    meta = request['metadata']
    proof = result['typed_validation']
    if (result['status'] != comparison.AUDITED or proof['policy'] != meta['typed_reference_policy']
            or proof['reference_scheme'] != meta['typed_reference_scheme'] or proof['late_comparisons'] != 2
            or proof['worker_reference_deserialized'] is not False
            or publisher['phases']['publisher.typed_authority']['calls'] != 1
            or publisher['phases']['publisher.open_and_proof']['calls'] != 14 or meta['gates'] != prior.check_gates()):
        raise ValueError('Incomplete independent comparison or scientific evidence')
    late = comparison.original_late_timing(folder, read(folder / 'cold_S/events.json'))
    snapshots = {arm: sum(run['diagnostic']['phases']['snapshot.fingerprint']['calls']
                         for run in result['runs'].values() if run['mode'] == arm) for arm in frozen.ARMS}
    cold_counts = {arm: {name: result['cache'][arm][name] for name in ('cold_builds', 'hits')}
                   for arm in frozen.ARMS}
    return dict(namespace=folder.relative_to(ROOT).as_posix(), schedule=meta['schedule'], arms=frozen.ARMS,
        comparison=result['decision'], cold_replaced_work=_late_costs(result, late), reference=result['reference'],
        typed_validation=proof, runs=result['runs'], supervisor=completion, publisher_observation=publisher,
        publisher_load=load, process_wall_seconds={key: value['seconds'] for key, value in exits.items()},
        worker_snapshots=snapshots, worker_contexts=cold_counts,
        sources=dict(descriptors=len(request['sources']), logical_bytes=sum(row['bytes'] for row in request['sources']),
                     methods=len(meta['context']['methods']), full_closure_passes=4, publisher_store_opens=14),
        gates=meta['gates'], engineering_checks=read(folder / 'worker_done.json')['checks']), seal


def release(*, audit_only):
    windows = existing_windows()
    if len(windows) != 1:
        raise ValueError('Exactly one saved direct-comparison window required')
    folder = folder_path(windows[0])
    path = ROOT / REPORT
    existing = read(path) if audit_only else None
    if not audit_only and path.exists():
        raise FileExistsError('Immutable comparison result already exists; use --audit')
    request = read(folder / 'request.json')
    metadata = contract(folder, request)
    report, manifest = completed_report(folder, request, expected_manifest=existing['closed_manifest'] if existing else None)
    report.update(status='v41_original48_C1_S1_and_V39_direct_cost_measured', specification=metadata['specification'],
        acceptance=metadata['acceptance'], closed_manifest=manifest, real_runs=14, scope=frozen.specification()['scope'],
        T_plan=None)
    if audit_only:
        if report != existing:
            raise ValueError('Public comparison differs from stopped evidence')
    else:
        public_json(path, report, exclusive=True)
    print(dict(report=REPORT, audit=audit_only, checks=report['engineering_checks'],
        cold_T_minus_S=report['comparison']['cold']['T_minus_S_seconds'],
        total_T_minus_S=report['comparison']['all7_T_minus_S_seconds'], seconds=report['supervisor']['seconds']))
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
        print('V41 supervised namespace: ' + folder.relative_to(ROOT).as_posix(), flush=True)
        completion = entry.run_window(folder, command(MODULE, 'pipeline', folder), sources, 'joint_tail',
            metadata=metadata, budget_seconds=spec['budget_seconds'], limits=spec['limits'])
        entry.old._check_window(read(folder / 'request.json'), completion)
        return release(audit_only=False)


main = _clone(prior.main, measure=measure, release=release, run_role=run_role)


if __name__ == '__main__':
    main()
