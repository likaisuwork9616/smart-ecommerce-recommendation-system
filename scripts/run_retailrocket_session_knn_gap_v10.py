"""Bounded V10 measurement of the remaining two capped 1111 validation cells."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, PATHS, read, write, describe, verify_bindings, environment, check_gates)
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json, _phase, _check_db, _record
from scripts.run_retailrocket_session_knn_gap_v9 import _completed, _extract as extract_source_frames
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_gap_v7 import check_index, ledger_proof
from scripts.retailrocket_session_knn_pair_v4 import verify_selected
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v10 import (
    CELLS, select_gap_roster, audit_gap_order, summarize_gap_cost, compare_frames, check_coverage, sample_workload)


MODULE = 'scripts.run_retailrocket_session_knn_gap_v10'
BASE = 'reports/stage12/retailrocket_session_knn_'
INVENTORY = BASE+'v10_gap_inventory_20261105.json'
SPEC = BASE+'v10_gap_sampling_specification_20261105.json'
ACCEPT = BASE+'v10_gap_acceptance_20261105.json'
REPORT = BASE+'v10_gap_cost_20261105.json'
PARENT = BASE+'v9_gap_cost_20261105.json'
METHODS = ('scripts/retailrocket_session_knn_gap_v10.py','scripts/run_retailrocket_session_knn_gap_v10.py',
           'tests/test_retailrocket_session_knn_gap_v10.py')
SUITES = ('tests.test_retailrocket_session_knn_gap_v10','tests.test_retailrocket_session_knn_gap_v9')
HISTORY_NAMES = ('history64','history48','history34','history8','history8_v9')


def preregistration():
    spec, inventory = read(ROOT/SPEC), read(ROOT/INVENTORY)
    if (spec['status'] != 'v10_target_two_specification_frozen' or spec['inventory'] != describe(ROOT/INVENTORY)
            or inventory['status'] != 'v10_gap_inventory_verified'
            or inventory['coverage_before']['distinct_historical_keys'] != 160):
        raise ValueError('V10 requires the registered specification and inventory')
    ranked = [row['cell'] for row in inventory['remaining_cells_ranked'][:2]]
    quotas = {q['cell']: q for q in spec['quotas']}
    if (ranked != list(CELLS) or [r['cell'] for r in inventory['top_two_cells']] != ranked
            or len(spec['quotas']) != 2 or set(quotas) != set(CELLS)
            or any(any(q[f] != quotas[q['cell']][f] for f in ('population','historical_exclusions','eligible'))
                   for q in inventory['top_two_cells'])):
        raise ValueError('Registered V10 cell ranking or counts differ')
    return spec, inventory


def acceptance():
    spec, _ = preregistration()
    if (ROOT/ACCEPT).exists():
        raise FileExistsError(ROOT/ACCEPT)
    folder = PRIVATE/('knn-v10-gap-tests-'+uuid4().hex)
    folder.mkdir()
    start = perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    log = folder/'tests.log'
    with log.open('x',encoding='utf-8') as stream:
        tested = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    if not tested.testsRun or not tested.wasSuccessful() or tested.skipped:
        print(log.read_text(encoding='utf-8')[-6000:],file=sys.stderr)
        raise ValueError(f'Synthetic acceptance failed: {log}')
    receipt = {'status':'v10_gap_tools_synthetic_accepted','created_utc':datetime.now(timezone.utc).isoformat(),
               'tests_run':tested.testsRun,'seconds':perf_counter()-start,'failures':0,'errors':0,'skipped':0,
               'suites':list(SUITES),'environment':environment(),'method_files':[describe(ROOT/p) for p in METHODS],
               'specification':describe(ROOT/SPEC),'inventory':spec['inventory'],'log':describe(log),
               'actual_new_keys_selected':0,'actual_new_query_verifications':0,'reserved_test':'locked','T_plan':None}
    public_json(ROOT/ACCEPT,receipt,exclusive=True)
    print(f"V10 acceptance passed: {tested.testsRun} tests in {receipt['seconds']:.3f} seconds")


def _selection_args(meta):
    spec, _ = preregistration()
    groups = [read(ROOT/meta[key]) for key in HISTORY_NAMES]
    sets = [{p['key_sha256'] for p in g['probes']} for g in groups]
    if ([len(g['probes']) for g in groups] != [64,48,34,8,8] or len(sets[0] & sets[1]) != 2
            or any(sets[i] & set.union(*sets[:i]) for i in range(2,len(sets)))
            or len(set.union(*sets)) != 160):
        raise ValueError('Five pinned historical samples differ')
    return ROOT/meta['roster'], *groups, spec


def _select_and_audit(args, watch=lambda: None):
    selection = select_gap_roster(*args, watch=watch)
    audit_gap_order(args[0], selection, *args[1:], watch=watch)
    return selection


def _bound_inputs(folder, request, selection, database, watch):
    # The frozen V9 helper creates and hashes seven exact frame files, the
    # context copies and an immutable transport receipt. Bind those same files
    # under V10's own checkpoint scope without editing the transport receipt.
    transport = extract_source_frames(folder, request, selection, database, watch)
    binding = dict(transport, scope='v10_two_capped_1111_cells_eight_engineering_only',
                   transport=describe(folder/'subset_binding.json'))
    write(folder/'v10_subset_binding.json',binding)
    return binding


def _summary(store, measured, selection, spec):
    detail = store.detailed_cost_summary(measured)
    proof = ledger_proof(store,selection['probes'])
    if proof['actual_committed_bytes'] != sum(row['frame_bytes'] for row in detail['rows']):
        raise ValueError('Committed V10 frame bytes differ from measured frames')
    predictions = [row['payload']['expected']['predictions']['K1'] for row in store.iter_records()]
    result = summarize_gap_cost(measured,detail,selection,spec)
    result.update(proof=proof,workload_by_cell=sample_workload(selection['probes'],measured,predictions))
    return detail,result


def _observe(folder, request, binding, selection, spec, model, database, watch, i):
    run = folder/f'repeat_{i}'
    subset = folder/'raw_selected_inputs'
    store = DetailedTimedStore.create(run/'verified_subset',binding,request['deadline_utc'],request['budget_seconds'],
        source_root=ROOT,expected_queries=8,required_stages=('reconstruction','queries'))
    with store.writer():
        store.seal_stage('reconstruction',{'kind':'reused_v5_reconstructed_model','fit_audit':model['fit_audit']})
        measured = verify_selected(subset/'primary',{k:subset/k for k in PATHS},binding['configuration'],
                                   store,model,database,read(subset/'ordinals.json'),watch)
    detail,result = _summary(store,measured,selection,spec)
    write(run/'measurements.json',measured)
    write(run/'observations.json',{'detail':detail,'append_events':store.append_events,'budget_events':store.budget_events})
    write(run/'proof.json',result['proof'])
    write(run/'summary.json',result)
    return result


def _audit_repeat(folder, request, binding, selection, spec, i):
    run = folder/f'repeat_{i}'
    record = read(run/'verified_subset/run.json')
    if record['binding'] != binding or any(record[k] != request[k] for k in ('deadline_utc','budget_seconds')):
        raise ValueError('Repeat checkpoint deadline or input binding changed')
    store = DetailedTimedStore.open(run/'verified_subset',binding,source_root=ROOT)
    measured = read(run/'measurements.json')
    observations = read(run/'observations.json')
    store.commit_events = measured['chunk_commits']
    store.append_events = observations['append_events']
    store.budget_events = observations['budget_events']
    detail,result = _summary(store,measured,selection,spec)
    if detail != observations['detail'] or result != read(run/'summary.json') or result['proof'] != read(run/'proof.json'):
        raise ValueError('Recomputed V10 cost, evidence or recorded bytes differ')
    return result


def worker(folder):
    request = read(folder/'request.json')
    meta = request['metadata']
    watch = ThrottledWatch(folder,request['deadline_utc'])
    try:
        with _phase(folder,'initial_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            check_gates()
            if request['budget_seconds'] != 1800 or meta['environment'] != environment():
                raise ValueError('Engineering environment or wall budget changed')
        args = _selection_args(meta)
        spec = args[-1]
        with _phase(folder,'freeze_gap_selection',watch):
            selection = _select_and_audit(args,watch)
            write(folder/'frozen_probes.json',selection)
            write(folder/'selection_seal.json',{'utc':datetime.now(timezone.utc).isoformat(),
                'selection':describe(folder/'frozen_probes.json'),'inventory':spec['inventory'],
                'specification':describe(ROOT/SPEC),'full_sort_agrees':True})
        model_root = ROOT/meta['independent_model_folder']
        database = model_root/'independent.sqlite'
        _check_db(database)
        with _phase(folder,'seven_source_extract',watch):
            binding = _bound_inputs(folder,request,selection,database,watch)
        model = read(model_root/'reconstruction.json')['receipt']
        repeats = []
        for i in range(2):
            with _phase(folder,f'gap_repeat_{i}',watch):
                repeats.append(_observe(folder,request,binding,selection,spec,model,database,watch,i))
                if i:
                    _same_payload(repeats[0]['proof'],repeats[1]['proof'])
                    compare_frames(folder,8)
        with _phase(folder,'final_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            verify_bindings(binding['sources']+[binding['transport']],watch)
            _check_db(database)
            check_gates()
        write(folder/'done.json',{'repeats':2,'new_keys':8,'engineering_checks':16})
    except BaseException as error:
        write(folder/'failure.json',{'error_type':type(error).__name__,'reserved_test':'locked','full_readback_started':False})
        raise


def publish(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v10-gap-'):
        raise ValueError('Expected a private V10 window')
    namespace = folder.relative_to(ROOT).as_posix()
    existing = read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    if existing and existing['namespace'] != namespace:
        raise FileExistsError('Another V10 namespace has already published')
    completion,phases = _completed(folder)
    request = read(folder/'request.json')
    args = _selection_args(request['metadata'])
    selection = _select_and_audit(args)
    spec = args[-1]
    seal = read(folder/'selection_seal.json')
    if (selection != read(folder/'frozen_probes.json') or seal['selection'] != describe(folder/'frozen_probes.json')
            or seal['inventory'] != spec['inventory'] or seal['specification'] != describe(ROOT/SPEC)
            or seal['full_sort_agrees'] is not True):
        raise ValueError('Frozen V10 roster or seal changed')
    binding = read(folder/'v10_subset_binding.json')
    verify_bindings(binding['sources']+[binding['transport']])
    index = read(folder/'source_index/manifest.json')
    check_index(index,selection['probes'],args[2]['population']['total_queries'],
                {rec['path']:rec for rec in request['sources']},ROOT)
    repeats = [_audit_repeat(folder,request,binding,selection,spec,i) for i in range(2)]
    _same_payload(repeats[0]['proof'],repeats[1]['proof'])
    compare_frames(folder,8)
    if repeats[0]['workload_by_cell'] != repeats[1]['workload_by_cell']:
        raise ValueError('Verified capped work differs between repeats')
    parent = read(ROOT/PARENT)
    coverage,missing = check_coverage(parent['remaining_unrepresented_cells'],repeats[0]['cells'])
    if coverage != spec['conditional_after_all_8_verified']:
        raise ValueError('Observed change in coverage differs from registered conditional result')
    audit = {'independent_selection_matches':True,'two_ledgers_byte_identical':True,
             'capped_work_and_frontier_verified':True,'post_exit_costs_recomputed':True,
             'tracked_processes_stopped':True,'new_historical_overlap':0}
    audit_path = folder/'post_exit_audit.json'
    if audit_path.exists():
        if read(audit_path) != audit:
            raise ValueError('Saved post-exit audit differs')
    else:
        write(audit_path,audit)
    report = {'status':'v10_gap_8_measured_twice','created_utc':existing['created_utc'] if existing else datetime.now(timezone.utc).isoformat(),
              'namespace':namespace,'supervisor':completion,'phases':phases,'environment':environment(),
              'sources_bound':len(request['sources']),'sources_reverified_before_after':True,'selection_sha256':seal['selection']['sha256'],
              'inventory':seal['inventory'],'specification':seal['specification'],'coverage':coverage,
              'remaining_unrepresented_cells':missing,'repeats':repeats,
              'scope':{'new_keys':8,'new_engineering_verifications':16,'new_primary_fits':0,'new_primary_validation_runs':0,
                       'new_primary_bootstrap':0,'SQL_candidate_runs':0,'full_readback_started':False,'reserved_test':'locked'},
              'gates':check_gates(),'T_plan':None,'evidence':[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]}
    if existing is None:
        public_json(ROOT/REPORT,report,exclusive=True)
    elif existing != report:
        raise ValueError('Re-audit differs from published V10 report')
    print({'report':REPORT,'namespace':namespace,'seconds':completion['seconds'],'coverage':coverage,'proof':repeats[0]['proof']})


def supervise():
    if (ROOT/REPORT).exists():
        raise FileExistsError('Re-audit the existing V10 namespace with --publish')
    check_gates()
    spec,inventory = preregistration()
    accepted = read(ROOT/ACCEPT)
    if (accepted['status'] != 'v10_gap_tools_synthetic_accepted' or accepted['environment'] != environment()
            or {r['path'] for r in accepted['method_files']} != set(METHODS) or accepted['inventory'] != spec['inventory']
            or accepted['specification'] != describe(ROOT/SPEC)):
        raise ValueError('Current V10 methods, environment and specification require acceptance')
    verify_bindings(accepted['method_files'])
    parent_record = _record(inventory['inputs'],'/'+Path(PARENT).name)
    verify_bindings([parent_record])
    parent = read(ROOT/PARENT)
    remaining = {r['cell']:r['population'] for r in inventory['remaining_cells_ranked']}
    if (parent['status'] != 'v9_gap_8_measured_twice' or not parent['sources_reverified_before_after']
            or parent['coverage'] != {'v6_plus_new_cells_with_sample':40,'v6_plus_new_unrepresented_population':2189,
                                      'distinct_historically_verified_queries':160}
            or parent['remaining_unrepresented_cells'] != remaining or len(remaining) != 15 or sum(remaining.values()) != 2189):
        raise ValueError('Expected completed V9 coverage and remaining cell inventory')
    anchors = [_record(parent['evidence'],'/'+n) for n in ('request.json','supervisor_completion.json','frozen_probes.json')]
    verify_bindings(anchors)
    _normal_exit(read(ROOT/anchors[1]['path']))
    previous = read(ROOT/anchors[0]['path'])
    meta = {k:previous['metadata'][k] for k in (*HISTORY_NAMES[:-1],'roster','independent_model_folder','environment')}
    if meta['environment'] != environment():
        raise ValueError('Frozen V9 environment differs')
    meta.update(history8_v9=anchors[2]['path'],queries=8,repeats=2)
    records = {r['path']:r for r in previous['sources']}
    for r in [*inventory['inputs'],*anchors,*accepted['method_files'],spec['inventory'],describe(ROOT/SPEC),describe(ROOT/ACCEPT)]:
        if r['path'] in records and records[r['path']] != r:
            raise ValueError('A pre-existing frozen input descriptor differs')
        records[r['path']] = r
    folder = PRIVATE/('knn-v10-gap-'+uuid4().hex)
    print('V10 supervised window: '+folder.relative_to(ROOT).as_posix(),flush=True)
    receipt = run_window(folder,[sys.executable,'-B','-m',MODULE,'--worker',str(folder)],
                         [records[k] for k in sorted(records)],'joint_tail',metadata=meta,budget_seconds=1800)
    _normal_exit(receipt)
    publish(folder)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance',action='store_true')
    modes.add_argument('--measure',action='store_true')
    modes.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    modes.add_argument('--publish',type=Path)
    args = parser.parse_args()
    if args.acceptance:
        acceptance()
    elif args.measure:
        supervise()
    elif args.worker:
        worker(args.worker)
    else:
        publish(args.publish)
