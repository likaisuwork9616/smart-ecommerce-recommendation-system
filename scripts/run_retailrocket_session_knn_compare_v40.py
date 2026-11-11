"""Run one sealed original48 comparison, then publish stopped evidence."""
import argparse
from pathlib import Path
import sys
from uuid import uuid4

from scripts import freeze_retailrocket_session_knn_compare_v40 as frozen
from scripts import retailrocket_session_knn_entry_v34 as common
from scripts import retailrocket_session_knn_typed_publication_v39 as typed
from scripts import run_retailrocket_session_knn_compare_v28 as entry
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts.run_retailrocket_session_knn_v2 import ROOT, check_gates, describe, read, verify_bindings, write


MODULE = 'scripts.run_retailrocket_session_knn_compare_v40'
ACCEPTANCE = frozen.BASE + 'acceptance_20261111.json'
ACCEPTANCE_SEAL = frozen.BASE + 'acceptance_seal_20261111.json'
REPORT = frozen.BASE + 'result_20261111.json'
ACCEPTED = 'v40_original48_comparison_entry_accepted'
AUDITED = 'v40_late_typed_independent_audit_complete'
ROLES = ('pipeline', 'worker', 'publisher')
SUITE = 'tests.test_retailrocket_session_knn_compare_v40'
SEEDS = (frozen.METHOD, 'scripts/run_retailrocket_session_knn_compare_v40.py',
         'scripts/accept_retailrocket_session_knn_compare_v40.py', SUITE.replace('.', '/') + '.py')


def source_roster():
    inherited = read(ROOT / frozen.inherited.SPEC)['preserved']
    accepted = read(ROOT / frozen.accepted.REPORT)['preserved_contract']['actual_methods']
    direct = common.source_inventory(SEEDS, dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    methods = common.merge_methods(accepted, direct)
    return common.merge_methods(inherited['current_sources'], methods), methods


def acceptance_seal():
    return dict(status='v40_original48_entry_acceptance_sealed', acceptance=describe(ROOT / ACCEPTANCE),
                specification=describe(ROOT / frozen.SPEC), real_runs=0)


def accepted_entry(methods):
    value = read(ROOT / ACCEPTANCE)
    if (read(ROOT / ACCEPTANCE_SEAL) != acceptance_seal() or value['status'] != ACCEPTED
            or value['specification'] != describe(ROOT / frozen.SPEC) or value['methods'] != methods
            or value['suite'] != SUITE or set(value['coverage']) != set(frozen.REQUIREMENTS)
            or value['tests_run'] != len(set(value['passed_tests'])) or not value['passed_tests']
            or any(not tests or not set(tests).issubset(value['passed_tests']) for tests in value['coverage'].values())
            or any(type(value[k]) is not int or value[k] != 0 for k in ('failures', 'errors', 'skipped', 'real_runs'))):
        raise ValueError('Unchanged entry and its sealed artificial acceptance are required')
    manifest = read(ROOT / value['manifest']['path'])
    if (manifest['status'] != 'v34_stopped_logs_and_complete_window_sealed'
            or value['integration']['engineering_checks'] != 672):
        raise ValueError('Complete artificial stopped-window acceptance required')
    return value, manifest


def request_metadata(spec, methods, cohort, dependencies):
    keys = ('schedule', 'environment', 'gates', 'fingerprint_scheme', 'typed_reference_policy', 'typed_reference_scheme')
    return dict({key: spec[key] for key in keys}, cohort=cohort,
                context=dict(dependencies=dependencies, methods=methods), specification=describe(ROOT / frozen.SPEC))


def source_contract():
    spec = frozen.specification()
    sources, methods = source_roster()
    accepted, manifest = accepted_entry(methods)
    evidence = [describe(ROOT / path) for path in (frozen.SPEC, frozen.SEAL, ACCEPTANCE, ACCEPTANCE_SEAL)]
    evidence.extend((accepted['log'], accepted['manifest']))
    evidence.extend(manifest['window_evidence'])
    sources = common.merge_methods(sources, evidence)
    metadata = request_metadata(spec, methods, spec['cohort'], spec['dependencies'])
    metadata['acceptance'] = describe(ROOT / ACCEPTANCE)
    binding = read(ROOT / spec['cohort']['old_run'])['binding']
    if binding['sources'] != spec['original_binding']:
        raise ValueError('Original 15 binding descriptors changed')
    typed.adapter.context_contract(dict(sources=sources, metadata=metadata), binding)
    return sources, metadata


def contract(folder, request):
    folder_path(folder)
    entry.old._check_window(request)
    typed.adapter.require_policy(request)
    sources, metadata = source_contract()
    if request['sources'] != sources or request['metadata'] != metadata:
        raise ValueError('Real request differs from the sealed source, cohort or schedule contract')
    common.require_direct_sources(metadata['context']['methods'], sources)
    return metadata


def folder_path(folder):
    folder = Path(folder).resolve()
    suffix = folder.name.removeprefix(frozen.WINDOW_PREFIX)
    if (folder.parent != PRIVATE.resolve() or not folder.name.startswith(frozen.WINDOW_PREFIX)
            or len(suffix) != 32 or any(c not in '0123456789abcdef' for c in suffix)):
        raise ValueError('Direct V40 real namespace required')
    return folder


def _saved_publisher_request(folder, request):
    # The role has already checked the exact contract. Bind the raw audit to
    # that role's immutable request before projecting any original schema fields.
    if (read(folder / 'request.json') != request
            or read(folder / 'publisher_contract.json')['request'] != describe(folder / 'request.json')):
        raise ValueError('Publisher request differs from the admitted request')


def _write_audit_result(path, value):
    if Path(path).name == 'audited_result.json':
        if value['status'] != 'v39_late_typed_independent_synthetic_audit_complete':
            raise ValueError('Unexpected typed publisher result')
        value = dict(value, status=AUDITED)
    write(path, value)


# Keep the verified V39 source rebuild and raw checks. Only the outer request
# admission and publication label depend on the comparison entry.
audit_saved_runs = _clone(typed.audit_saved_runs, _artificial_bundle=_saved_publisher_request, write=_write_audit_result)
run_publisher = _clone(entry.run_publisher, audit_saved_runs=audit_saved_runs)


def command(module, role, folder):
    return [sys.executable, '-B', '-m', module, '--' + role, str(folder)]


def run_role(folder, role, *, admit=contract, module=MODULE):
    folder = Path(folder).resolve()
    request = read(folder / 'request.json')
    _, diagnostics = common.quiet_contract(admit, folder, request)
    write(folder / (role + '_contract.json'), dict(role=role, request=describe(folder / 'request.json'),
        policy=typed.adapter.POLICY, diagnostics=diagnostics))
    print(role + ' contract verified')
    if role == 'pipeline':
        commands = {kind: command(module, kind, folder) for kind in ROLES[1:]}
        return entry.run_pipeline(folder, request, commands)
    if role == 'worker':
        return typed.run_worker(folder, request, lambda: entry.old.inputs(request))
    return run_publisher(folder, request)


def completed_report(folder, request, *, expected_manifest=None):
    result, completion, exits, publisher, load = entry.audit_completed(folder, request)
    seal = common.closed_log_manifest(folder, request, completion, exits, expected=expected_manifest)
    meta = request['metadata']
    proof = result['typed_validation']
    if (result['status'] != AUDITED or proof['policy'] != meta['typed_reference_policy']
            or proof['reference_scheme'] != meta['typed_reference_scheme'] or proof['late_comparisons'] != 2
            or proof['worker_reference_deserialized'] is not False
            or publisher['phases']['publisher.typed_authority']['calls'] != 1
            or publisher['phases']['publisher.open_and_proof']['calls'] != 14 or meta['gates'] != check_gates()):
        raise ValueError('Incomplete independent typed, scientific or gate evidence')
    cache = result['cache']
    cold = cache['call_observations'][0]['typed_reference']
    report = dict(namespace=folder.relative_to(ROOT).as_posix(), schedule=meta['schedule'],
        decision=result['decision'], reference=result['reference'], typed_validation=proof,
        cold_passive_seconds={name: (timing['end_ns'] - timing['start_ns']) / 1e9 for name, timing in
            [('reference_build', cold['build']), *((row['root'], row) for row in cold['checks'])]},
        runs=result['runs'], supervisor=completion, publisher_observation=publisher, publisher_load=load,
        process_wall_seconds={k: v['seconds'] for k, v in exits.items()},
        sources=dict(descriptors=len(request['sources']), logical_bytes=sum(row['bytes'] for row in request['sources']),
                     methods=len(meta['context']['methods']), full_closure_passes=4, publisher_store_opens=14),
        gates=meta['gates'], engineering_checks=read(folder / 'worker_done.json')['checks'])
    return report, seal


def existing_windows():
    return sorted(path.parent for path in PRIVATE.glob(frozen.WINDOW_PREFIX + '*/request.json'))


def release(*, audit_only):
    windows = existing_windows()
    if len(windows) != 1:
        raise ValueError('Exactly one saved real window required')
    folder = folder_path(windows[0])
    path = ROOT / REPORT
    prior = read(path) if audit_only else None
    if not audit_only and path.exists():
        raise FileExistsError('Immutable result already exists; use --audit')
    request = read(folder / 'request.json')
    metadata = contract(folder, request)
    report, manifest = completed_report(folder, request, expected_manifest=prior['closed_manifest'] if prior else None)
    report.update(status='v40_original48_real_comparison_measured', specification=metadata['specification'],
        acceptance=metadata['acceptance'], closed_manifest=manifest, real_runs=14,
        scope=frozen.specification()['scope'], T_plan=None)
    if audit_only:
        if prior != report:
            raise ValueError('Public result differs from stopped evidence')
    else:
        public_json(path, report, exclusive=True)
    print(dict(report=REPORT, audit=audit_only, checks=report['engineering_checks'],
               adopted=report['decision']['adopted'], seconds=report['supervisor']['seconds']))
    return report


def measure():
    with entry.exclusive():
        if (ROOT / REPORT).exists() or existing_windows():
            raise FileExistsError('Existing real request or result forbids another measurement')
        sources, metadata = source_contract()
        # Verify the small sealed inputs before opening the one real slot. The
        # supervised worker/publisher still independently hash every source.
        spec = frozen.specification()
        frozen.verify_original_reference(spec)
        verify_bindings([*spec['dependencies'].values(), *spec['original_binding']])
        for record in sources:
            if (ROOT / record['path']).stat().st_size != record['bytes']:
                raise ValueError('Sealed source size differs: ' + record['path'])
        folder = PRIVATE / (frozen.WINDOW_PREFIX + uuid4().hex)
        print('V40 supervised namespace: ' + folder.relative_to(ROOT).as_posix(), flush=True)
        completion = entry.run_window(folder, command(MODULE, 'pipeline', folder), sources, 'joint_tail',
            metadata=metadata, budget_seconds=spec['budget_seconds'], limits=spec['limits'])
        entry.old._check_window(read(folder / 'request.json'), completion)
        return release(audit_only=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('measure', 'release', 'audit'):
        mode.add_argument('--' + name, action='store_true')
    for role in ROLES:
        mode.add_argument('--' + role, type=Path)
    args = parser.parse_args()
    if args.measure:
        measure()
    elif args.release or args.audit:
        with entry.exclusive():
            release(audit_only=args.audit)
    else:
        for role in ROLES:
            folder = getattr(args, role)
            if folder is not None:
                run_role(folder, role)
                break


if __name__ == '__main__':
    main()
