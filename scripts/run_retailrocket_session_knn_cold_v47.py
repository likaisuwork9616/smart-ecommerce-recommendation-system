"""Activate and release a sealed fixed48 V39 / V46 cold comparison."""
from pathlib import Path
from uuid import uuid4

from scripts import freeze_retailrocket_session_knn_cold_v47 as frozen
from scripts import retailrocket_session_knn_cold_v47 as cold
from scripts import run_retailrocket_session_knn_compare_v41 as prior
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


ROOT, PRIVATE = prior.ROOT, prior.PRIVATE
read, write, describe, verify_bindings = prior.read, prior.write, prior.describe, prior.verify_bindings
entry, typed, common = prior.entry, prior.typed, prior.common
command, public_json, ROLES = prior.command, prior.public_json, prior.ROLES
MODULE = 'scripts.run_retailrocket_session_knn_cold_v47'
SUITE = 'tests.test_retailrocket_session_knn_cold_v47'
SEEDS = (frozen.METHOD, MODULE.replace('.', '/') + '.py', SUITE.replace('.', '/') + '.py',
         'scripts/retailrocket_session_knn_cold_v47.py', 'scripts/accept_retailrocket_session_knn_cold_v47.py')
REPORT = frozen.BASE + 'result_20261112.json'
ACCEPTANCE = frozen.BASE + 'acceptance_20261112.json'
ACCEPTANCE_SEAL = frozen.BASE + 'acceptance_seal_20261112.json'
ACCEPTED = 'v47_fresh_context_entry_accepted'


def source_roster():
    sources, metadata = prior.source_contract()
    direct = common.source_inventory(SEEDS, dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    methods = common.merge_methods(metadata['context']['methods'], direct)
    evidence = frozen.specification()['predecessors']
    return common.merge_methods(sources, [*evidence, *methods]), methods


def acceptance_seal():
    return dict(status='v47_fresh_context_acceptance_sealed', acceptance=describe(ROOT / ACCEPTANCE),
                specification=describe(ROOT / frozen.SPEC), real_runs=0)


def folder_path(folder):
    folder = Path(folder).resolve()
    suffix = folder.name.removeprefix(frozen.WINDOW_PREFIX)
    if (folder.parent != PRIVATE.resolve() or not folder.name.startswith(frozen.WINDOW_PREFIX)
            or len(suffix) != 32 or any(c not in '0123456789abcdef' for c in suffix)):
        raise ValueError('Direct V47 cold namespace required')
    return folder


request_metadata = _clone(prior.request_metadata, frozen=frozen)
accepted_entry = _clone(prior.prior.accepted_entry, frozen=frozen, acceptance_seal=acceptance_seal,
                        ACCEPTANCE=ACCEPTANCE, ACCEPTANCE_SEAL=ACCEPTANCE_SEAL, ACCEPTED=ACCEPTED, SUITE=SUITE)
source_contract = _clone(prior.prior.source_contract, frozen=frozen, source_roster=source_roster,
                         accepted_entry=accepted_entry, request_metadata=request_metadata,
                         ACCEPTANCE=ACCEPTANCE, ACCEPTANCE_SEAL=ACCEPTANCE_SEAL)
contract = _clone(prior.prior.contract, folder_path=folder_path, source_contract=source_contract)
existing_windows = _clone(prior.existing_windows, frozen=frozen)
role = _clone(prior.run_role, comparison=cold)


def run_role(folder, name, *, admit=contract, module=MODULE):
    return role(folder, name, admit=admit, module=module)


def completed_report(folder, request, *, expected_manifest=None):
    result, completion, exits, publisher, load = cold.audit_completed(folder, request)
    seal = common.closed_log_manifest(folder, request, completion, exits, expected=expected_manifest)
    if (result['status'] != cold.AUDITED or publisher['phases']['publisher.typed_authority']['calls'] != 1
            or publisher['phases']['publisher.open_and_proof']['calls'] != 14):
        raise ValueError('Missing independent cold comparison evidence')
    for label, run in result['runs'].items():
        use = result['cache'][label]['use']
        build = use['typed_reference']['build']
        if (use['cold'] is not True or use['hit'] is not False
                or run['reference_build_seconds'] != (build['end_ns'] - build['start_ns']) / 1e9):
            raise ValueError('Saved cold build differs from raw receipt')
    last = request['metadata']['schedule'][-1]['label']
    last_end = cold.prior._phase(read(folder / last / 'events.json'), 'run.total')['end_ns']
    cold.attach_decode_times(result['runs'], read(folder / 'decode_receipt.json'), last_end)
    if result['decision'] != cold.comparison(result['runs']):
        raise ValueError('Saved decode replays differ from publication')
    return dict(namespace=folder.relative_to(ROOT).as_posix(), schedule=request['metadata']['schedule'], arms=cold.ARMS,
        comparison=result['decision'], authority=result['authority'], reference=result['reference'], runs=result['runs'],
        supervisor=completion, publisher_observation=publisher, publisher_load=load,
        process_wall_seconds={key: value['seconds'] for key, value in exits.items()},
        sources=dict(descriptors=len(request['sources']), methods=len(request['metadata']['context']['methods']),
                     publisher_store_opens=14, full_closure_passes=4),
        engineering_checks=read(folder / 'worker_done.json')['checks']), seal


def release(*, audit_only):
    windows = existing_windows()
    if len(windows) != 1:
        raise ValueError('Exactly one saved real cold window required')
    folder = folder_path(windows[0])
    path = ROOT / REPORT
    existing = read(path) if audit_only else None
    if not audit_only and path.exists():
        raise FileExistsError('Immutable V47 comparison result already exists; use --audit')
    request = read(folder / 'request.json')
    metadata = contract(folder, request)
    report, manifest = completed_report(folder, request, expected_manifest=existing['closed_manifest'] if existing else None)
    spec = frozen.specification()
    if report['authority']['canonical'] != spec['canonical']:
        raise ValueError('Cold authority differs from the original V41/V46 sources')
    report.update(status='v47_fresh_V39_V46_cost_measured', specification=metadata['specification'],
        acceptance=metadata['acceptance'], closed_manifest=manifest, real_runs=14, scope=spec['scope'], T_plan=None)
    if audit_only:
        if report != existing:
            raise ValueError('Public comparison differs from stopped evidence')
    else:
        public_json(path, report, exclusive=True)
    print(dict(report=REPORT, audit=audit_only, checks=report['engineering_checks'],
               medians=report['comparison']['medians'], seconds=report['supervisor']['seconds']))
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
        print('V47 supervised namespace: ' + folder.relative_to(ROOT).as_posix(), flush=True)
        completion = entry.run_window(folder, command(MODULE, 'pipeline', folder), sources, 'joint_tail',
            metadata=metadata, budget_seconds=spec['budget_seconds'], limits=spec['limits'])
        entry.old._check_window(read(folder / 'request.json'), completion)
        return release(audit_only=False)


main = _clone(prior.main, measure=measure, release=release, run_role=run_role)


if __name__ == '__main__':
    main()
