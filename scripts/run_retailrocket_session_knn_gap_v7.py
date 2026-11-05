"""Select and verify the pre-registered 34 new validation queries twice."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
import unittest
import uuid

import psutil

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, PRIMARY, PATHS, SPEC, read, write, describe, verify_bindings, environment, check_gates)
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_pair_v4 import verify_selected
from scripts.retailrocket_session_knn_sources_v4 import build_source_index
from scripts.retailrocket_session_knn_gap_v7 import (
    select_gap_roster, audit_gap_order, check_index, ledger_proof, summarize_gap_cost)
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload


MODULE = 'scripts.run_retailrocket_session_knn_gap_v7'
GAP_SPEC = 'reports/stage12/retailrocket_session_knn_v7_gap_sampling_specification_20261105.json'
ACCEPT = 'reports/stage12/retailrocket_session_knn_v7_gap_acceptance_20261105.json'
REPORT = 'reports/stage12/retailrocket_session_knn_v7_gap_cost_20261105.json'
METHODS = ('scripts/retailrocket_session_knn_gap_v7.py', 'scripts/run_retailrocket_session_knn_gap_v7.py',
           'tests/test_retailrocket_session_knn_gap_v7.py')
SUITES = ('tests.test_retailrocket_session_knn_gap_v7', 'tests.test_retailrocket_session_knn_detailed_cost_v6',
          'tests.test_retailrocket_session_knn_sources_v4')
PRIVATE = ROOT/'shop-mysql-runtime/verification'


def public_json(path, value, *, exclusive=False):
    """Publish completed bytes atomically. Reports from different runs cannot replace one another."""
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def acceptance():
    folder = PRIVATE/('v7-gap-acceptance-'+uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES)
    log = folder/'unittest.log'
    with log.open('x', encoding='utf-8') as stream:
        tested = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not tested.wasSuccessful() or tested.skipped:
        print(log.read_text(encoding='utf-8')[-10000:], file=sys.stderr)
        raise ValueError('V7 synthetic acceptance failed')
    result = {'status': 'v7_gap_tools_synthetic_accepted', 'tests_run': tested.testsRun,
              'failures': 0, 'errors': 0, 'skipped': 0, 'seconds': time.perf_counter()-started,
              'method_files': [describe(ROOT/name) for name in METHODS], 'environment': environment(),
              'specification': describe(ROOT/GAP_SPEC), 'suites': SUITES, 'log': describe(log),
              'actual_new_keys_selected': 0, 'actual_new_query_verifications': 0,
              'full_readback_started': False, 'reserved_test': 'locked', 'T_plan': None}
    public_json(ROOT/ACCEPT, result)
    print(json.dumps({k: result[k] for k in ('status','tests_run','seconds')}))


def _record(records, suffix):
    matches = [record for record in records if record['path'].endswith(suffix)]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous frozen input: '+suffix)
    return matches[0]


def _metadata_inputs(spec):
    inputs = spec['inputs']
    return {
        'history64': _record([r for r in inputs if 'knn-v3-cost-' in r['path']], '/frozen_probes.json')['path'],
        'history48': _record(inputs, '/joint/frozen_probes.json')['path'],
        'roster': _record(inputs, '/joint/joint_roster.jsonl')['path'],
        'v6_report': _record(inputs, '/retailrocket_session_knn_v6_refined_cost_20261103.json')['path']}


def _selection_inputs(metadata):
    spec = read(ROOT/GAP_SPEC)
    prior = read(ROOT/metadata['history64'])
    original = read(ROOT/metadata['history48'])
    if (len(prior['probes']), len(original['probes']), len(spec['quotas']),
            spec['selection']['planned_unique_queries'], spec['actual_inventory']['distinct_historical_keys']) != (
                64, 48, 17, 34, 110):
        raise ValueError('Only the frozen V7 34-query specification may be executed')
    return spec, prior, original


def _check_db(database):
    if any(Path(str(database)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('The sealed immutable database has an unexpected journal')


@contextmanager
def _phase(folder, name, watch):
    write(folder/(name+'_started.json'), {'phase': name, 'utc': datetime.now(timezone.utc).isoformat()})
    started = time.perf_counter()
    completed = False
    try:
        watch.force()
        yield
        watch.force()
        completed = True
    finally:
        write(folder/(name+'_receipt.json'), {'completed': completed, 'seconds': time.perf_counter()-started})


def _extract(folder, request, selection, database, watch):
    model_paths = {k: ROOT/v for k,v in PATHS.items()}
    config = read(ROOT/SPEC)['configuration']
    probes = selection['probes']
    index = build_source_index(folder/'source_index', ROOT/PRIMARY, model_paths, config, probes, watch)
    bound = {r['path']: r for r in request['sources']}
    check_index(index, probes, config['fixed_validation']['queries'], bound, ROOT)
    selected = folder/'raw_selected_inputs'
    selected.mkdir()
    paths = {'dataset': 'dataset/queries.csv', 'p0_rank': 'P0/ranked_queries.csv',
             'p0_metrics': 'P0/query_metrics.csv', 'p0_slices': 'P0/query_slices.csv',
             'c1': 'C1/queries.jsonl', 'd1': 'D1/queries.jsonl', 'k1': 'primary/queries.jsonl'}

    def copy(source, target, reference):
        watch()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        actual = describe(target, watch)
        if any(actual[k] != reference[k] for k in ('bytes','sha256')):
            raise ValueError('Selected frame or context copy changed')

    for name, relative in paths.items():
        sample = index['samples'][name]
        copy(folder/'source_index'/sample['path'], selected/relative, sample)
    for key, filename in (('dataset','catalog.csv'),('P0','item_counts.csv')):
        source = model_paths[key]/filename
        copy(source, selected/key/filename, bound[source.relative_to(ROOT).as_posix()])
    config['fixed_validation']['queries'] = len(probes)
    write(selected/'configuration.json', config)
    write(selected/'ordinals.json', [{'key': p['key'], 'original_ordinal': p['original_ordinal'],
                                      'subset_ordinal': i} for i,p in enumerate(probes)])
    local = [describe(p, watch) for p in sorted(selected.rglob('*')) if p.is_file()]
    local += [bound[database.relative_to(ROOT).as_posix()]]
    local += [describe(folder/p, watch) for p in ('frozen_probes.json','selection_seal.json',
                                                  'source_index/manifest.json','source_index/seal.json')]
    binding = {'sources': local, 'configuration': config, 'scope': 'v7_gap_34_engineering_only'}
    write(folder/'subset_binding.json', binding)
    return binding


def _observe(folder, request, binding, model, database, selection, spec, watch, repeat):
    output = folder/f'repeat_{repeat}'
    selected = folder/'raw_selected_inputs'
    probes = selection['probes']
    store = DetailedTimedStore.create(output/'verified_subset', binding, request['deadline_utc'],
        request['budget_seconds'], source_root=ROOT, expected_queries=len(probes),
        required_stages=('reconstruction','queries'))
    with store.writer():
        store.seal_stage('reconstruction', {'kind': 'reused_v5_reconstructed_model', 'fit_audit': model['fit_audit']})
        measured = verify_selected(selected/'primary', {k: selected/k for k in PATHS}, binding['configuration'],
                                   store, model, database, read(selected/'ordinals.json'), watch)
    detail = store.detailed_cost_summary(measured)
    proof = ledger_proof(store, probes)
    if proof['actual_committed_bytes'] != sum(r['frame_bytes'] for r in detail['rows']):
        raise ValueError('Observed frame bytes differ from the physical checkpoint')
    summary = summarize_gap_cost(measured, detail, selection, spec)
    write(output/'measurements.json', measured)
    write(output/'observations.json', {'detail': detail, 'append_events': store.append_events,
                                      'budget_events': store.budget_events})
    write(output/'proof.json', proof)
    write(output/'summary.json', summary)
    return proof


def _compare_repeat_frames(folder):
    def frames(repeat):
        store = folder/f'repeat_{repeat}'/'verified_subset'
        for manifest in sorted((store/'chunks').glob('*.json')):
            with (store/read(manifest)['payload']['path']).open('rb') as stream:
                yield from stream
    count = 0
    for left, right in zip(frames(0), frames(1), strict=True):
        if left != right:
            raise ValueError('Corresponding scientific frames in the two gap repeats differ')
        count += 1
    if count != 34:
        raise ValueError('Missing physical frames in repeat comparison')


def worker(folder):
    request = read(folder/'request.json')
    metadata = request['metadata']
    watch = ThrottledWatch(folder, request['deadline_utc'])
    try:
        with _phase(folder,'initial_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            check_gates()
            if metadata['environment'] != environment():
                raise ValueError('Frozen environment differs')
        spec, prior, original = _selection_inputs(metadata)
        with _phase(folder,'freeze_gap_selection',watch):
            roster = ROOT/metadata['roster']
            selected = select_gap_roster(roster, prior, original, spec, watch)
            write(folder/'frozen_probes.json', selected)
            audit_gap_order(roster, selected, prior, original, spec, watch)
            write(folder/'selection_seal.json', {'specification': describe(ROOT/GAP_SPEC),
                  'frozen_selection': describe(folder/'frozen_probes.json'), 'roster_sha256': selected['roster_sha256'],
                  'utc': datetime.now(timezone.utc).isoformat(), 'independent_order_checked': True})
        model_root = ROOT/metadata['independent_model_folder']
        database = model_root/'independent.sqlite'
        _check_db(database)
        with _phase(folder,'seven_source_extract',watch):
            binding = _extract(folder, request, selected, database, watch)
        model = read(model_root/'reconstruction.json')['receipt']
        proofs = []
        for repeat in range(2):
            with _phase(folder,f'gap_repeat_{repeat}',watch):
                proofs.append(_observe(folder, request, binding, model, database, selected, spec, watch, repeat))
                if repeat:
                    _same_payload(proofs[1], proofs[0])
                    _compare_repeat_frames(folder)
        with _phase(folder,'final_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            verify_bindings(binding['sources'],watch)
            _check_db(database)
            check_gates()
        write(folder/'measurement_result.json', {'completed_repeats': 2, 'unique_new_queries': 34,
              'independent_engineering_verifications': 68, 'formal_acceptance': False, 'T_plan': None})
    except BaseException as error:
        write(folder/'failure.json', {'error_type': type(error).__name__, 'full_readback_started': False,
                                     'reserved_test': 'locked', 'T_plan': None})
        raise


def _audit_repeat(folder, request, binding, selected, spec, repeat):
    run_root = folder/f'repeat_{repeat}'
    run = read(run_root/'verified_subset/run.json')
    if (run['deadline_utc'] != request['deadline_utc'] or run['budget_seconds'] != request['budget_seconds']
            or run['binding'] != binding):
        raise ValueError('Changed repeat deadline or subset binding')
    store = DetailedTimedStore.open(run_root/'verified_subset', binding, source_root=ROOT)
    measured = read(run_root/'measurements.json')
    observations = read(run_root/'observations.json')
    store.append_events = observations['append_events']
    store.budget_events = observations['budget_events']
    store.commit_events = measured['chunk_commits']
    detail = store.detailed_cost_summary(measured)
    proof = ledger_proof(store, selected['probes'])
    summary = summarize_gap_cost(measured, detail, selected, spec)
    if (detail != observations['detail'] or summary != read(run_root/'summary.json')
            or proof != read(run_root/'proof.json') or proof['actual_committed_bytes'] != sum(r['frame_bytes'] for r in detail['rows'])):
        raise ValueError('Post-exit subset proof or aggregate cost differs from raw evidence')
    return {'proof': proof, **summary}


def publish(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v7-gap-'):
        raise ValueError('V7 publication requires a private V7 namespace')
    existing = read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    if existing is not None and existing['namespace'] != folder.relative_to(ROOT).as_posix():
        raise FileExistsError('The public report belongs to a different sealed V7 namespace')
    completion = read(folder/'supervisor_completion.json')
    _normal_exit(completion)
    request = read(folder/'request.json')
    for identity in read(folder/'tracked_process_identities.json')['identities']:
        try:
            process = psutil.Process(identity['pid'])
            if process.is_running() and process.create_time() == identity['create_time']:
                raise ValueError('Tracked process remains live')
        except psutil.NoSuchProcess:
            pass
    phases = {p.name.removesuffix('_receipt.json'): read(p) for p in folder.glob('*_receipt.json')}
    expected = {'initial_frozen_source_hash','freeze_gap_selection','seven_source_extract',
                'gap_repeat_0','gap_repeat_1','final_frozen_source_hash'}
    if (set(phases) != expected or any(not p['completed'] for p in phases.values())
            or read(folder/'measurement_result.json')['independent_engineering_verifications'] != 68):
        raise ValueError('Incomplete bounded gap measurement')
    spec, prior, original = _selection_inputs(request['metadata'])
    roster = ROOT/request['metadata']['roster']
    selected = select_gap_roster(roster, prior, original, spec)
    seal = read(folder/'selection_seal.json')
    if (selected != read(folder/'frozen_probes.json') or seal['frozen_selection'] != describe(folder/'frozen_probes.json')
            or seal['specification'] != describe(ROOT/GAP_SPEC) or not seal['independent_order_checked']):
        raise ValueError('Frozen gap sample or source seal differs at publication')
    binding = read(folder/'subset_binding.json')
    verify_bindings(binding['sources'])
    indexed = read(folder/'source_index/manifest.json')
    check_index(indexed, selected['probes'], spec['actual_inventory']['population'],
                {r['path']: r for r in request['sources']}, ROOT)
    repeats = [_audit_repeat(folder, request, binding, selected, spec, i) for i in range(2)]
    _same_payload(repeats[1]['proof'],repeats[0]['proof'])
    _compare_repeat_frames(folder)
    baseline = read(ROOT/request['metadata']['v6_report'])
    grid = baseline['repeats'][0]['refinement_sensitivity']['policies']['neighbor_vote_grid']['cells']
    added = set(repeats[0]['cells'])
    if any(grid[c]['measured_queries'] != 0 or grid[c]['population_queries'] != repeats[0]['cells'][c]['population'] for c in added):
        raise ValueError('Measured cells do not agree with the previous coverage gap')
    missing = {c: b['population_queries'] for c,b in grid.items() if not b['measured_queries'] and c not in added}
    coverage = {'v6_plus_new_cells_with_sample': len(grid)-len(missing),
                'v6_plus_new_unrepresented_population': sum(missing.values()),
                'distinct_historically_verified_queries': spec['actual_inventory']['distinct_historical_keys']+len(selected['probes'])}
    if coverage != spec['conditional_after_all_34_verified']:
        raise ValueError('Observed coverage differs from the pre-registered expectation')
    audit = {'costs_and_ledger_recomputed': True, 'two_scientific_payloads_identical': True,
             'tracked_identities_stopped': True, 'historical_intersection_with_new_selection': 0}
    audit_path = folder/'post_exit_audit.json'
    if audit_path.exists():
        if read(audit_path) != audit:
            raise ValueError('Existing post-exit audit differs')
    else:
        write(audit_path, audit)
    created = existing['created_utc'] if existing is not None else datetime.now(timezone.utc).isoformat()
    report = {'status': 'v7_gap_34_measured_twice', 'created_utc': created,
              'namespace': folder.relative_to(ROOT).as_posix(), 'supervisor': completion, 'phases': phases,
              'environment': environment(), 'sources_bound': len(request['sources']), 'sources_reverified_before_after': True,
              'specification': seal['specification'], 'selection_sha256': seal['frozen_selection']['sha256'],
              'coverage': coverage, 'remaining_unrepresented_cells': missing, 'repeats': repeats,
              'scope': {'new_keys': 34, 'new_engineering_verifications': 68, 'original_48_reruns': 0,
                        'new_primary_fits': 0, 'new_primary_validation_runs': 0, 'new_primary_bootstrap': 0,
                        'full_readback_started': False, 'reserved_test': 'locked'},
              'T_plan': None, 'gates': check_gates(),
              'evidence': [describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]}
    if existing is None:
        public_json(ROOT/REPORT, report, exclusive=True)
    elif report != existing:
        raise ValueError('Re-audit differs from the previously published report')
    print(json.dumps({'report': REPORT, 'namespace': report['namespace'], 'supervisor': completion,
                      'coverage': coverage, 'proof': repeats[0]['proof']}))


def supervise():
    if (ROOT/REPORT).exists():
        raise FileExistsError('V7 gap report already exists; use --publish to audit its namespace')
    check_gates()
    accepted = read(ROOT/ACCEPT)
    if (accepted['status'] != 'v7_gap_tools_synthetic_accepted' or accepted['environment'] != environment()
            or {r['path'] for r in accepted['method_files']} != set(METHODS)
            or accepted['specification'] != describe(ROOT/GAP_SPEC)):
        raise ValueError('Accepted V7 methods/specification and environment are required')
    verify_bindings(accepted['method_files'])
    spec = read(ROOT/GAP_SPEC)
    metadata = _metadata_inputs(spec)
    v6_descriptor = _record(spec['inputs'], '/retailrocket_session_knn_v6_refined_cost_20261103.json')
    verify_bindings([v6_descriptor])
    parent = read(ROOT/metadata['v6_report'])
    if parent['status'] != 'v6_same_fixed_48_refined_cost_measured' or not parent['sources_reverified_before_after']:
        raise ValueError('Complete preserved V6 measurements are required')
    inherited = _record(parent['evidence'], '/request.json')
    exit_record = _record(parent['evidence'], '/supervisor_completion.json')
    verify_bindings([inherited, exit_record])
    _normal_exit(read(ROOT/exit_record['path']))
    prior_request = read(ROOT/inherited['path'])
    if prior_request['metadata']['environment'] != environment():
        raise ValueError('Incompatible frozen environment')
    records = {r['path']: r for r in prior_request['sources']}
    for record in [*spec['inputs'], inherited, exit_record, *accepted['method_files'], describe(ROOT/ACCEPT), describe(ROOT/GAP_SPEC)]:
        if record['path'] in records and records[record['path']] != record:
            raise ValueError('Inconsistent inherited source binding')
        records[record['path']] = record
    metadata.update(environment=environment(), independent_model_folder=prior_request['metadata']['independent_model_folder'],
                    queries=34, repeats=2, scope='frozen_new_34_only')
    folder = PRIVATE/('knn-v7-gap-'+uuid.uuid4().hex)
    print('V7 supervised window: '+folder.relative_to(ROOT).as_posix(), flush=True)
    receipt = run_window(folder,[sys.executable,'-B','-m',MODULE,'--worker',str(folder)],
                         [records[k] for k in sorted(records)],'joint_tail',metadata=metadata)
    _normal_exit(receipt)
    publish(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance', action='store_true')
    modes.add_argument('--measure', action='store_true')
    modes.add_argument('--publish', type=Path)
    modes.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.acceptance:
        acceptance()
    elif args.measure:
        supervise()
    elif args.publish:
        publish(args.publish)
    else:
        worker(args.worker)
