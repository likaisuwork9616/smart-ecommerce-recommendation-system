"""V9 fixed eight-query supervised validation cost window and post-exit audit."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
from time import perf_counter
import unittest
from uuid import uuid4

import psutil

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, PRIMARY, PATHS, SPEC as MODEL_SPEC, read, write, describe, verify_bindings, environment, check_gates)
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json, _phase, _check_db, _record
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_sources_v4 import build_source_index
from scripts.retailrocket_session_knn_gap_v7 import check_index, ledger_proof
from scripts.retailrocket_session_knn_pair_v4 import verify_selected
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v9 import (
    CELLS, select_gap_roster, audit_gap_order, summarize_gap_cost, compare_frames, check_coverage, sample_workload)


MODULE = 'scripts.run_retailrocket_session_knn_gap_v9'
BASE = 'reports/stage12/retailrocket_session_knn_'
INVENTORY = BASE+'v9_gap_inventory_20261105.json'
SPEC = BASE+'v9_gap_sampling_specification_20261105.json'
ACCEPT = BASE+'v9_gap_acceptance_20261105.json'
REPORT = BASE+'v9_gap_cost_20261105.json'
PARENT = BASE+'v8_gap_cost_20261105.json'
METHODS = ('scripts/retailrocket_session_knn_gap_v9.py','scripts/run_retailrocket_session_knn_gap_v9.py',
           'tests/test_retailrocket_session_knn_gap_v9.py')
SUITES = ('tests.test_retailrocket_session_knn_gap_v9','tests.test_retailrocket_session_knn_gap_v8',
          'tests.test_retailrocket_session_knn_gap_v7')


def preregistration():
    spec, inv = read(ROOT/SPEC),read(ROOT/INVENTORY)
    if (spec['status'] != 'v9_target_two_specification_frozen' or spec['inventory'] != describe(ROOT/INVENTORY)
            or inv['status'] != 'v9_gap_inventory_verified'
            or inv['coverage_before']['distinct_historical_keys'] != 152):
        raise ValueError('Pinned V9 inventory/spec required')
    ranked = [r['cell'] for r in inv['remaining_cells_ranked'][:2]]
    quotas = {r['cell']:r for r in spec['quotas']}
    if (ranked != list(CELLS) or [r['cell'] for r in inv['top_two_cells']] != ranked or len(spec['quotas']) != 2
            or set(quotas) != set(CELLS)
            or any(any(quotas[r['cell']][f] != r[f] for f in ('population','historical_exclusions','eligible'))
                   for r in inv['top_two_cells'])):
        raise ValueError('Cells or quotas differ from registered inventory')
    return spec,inv


def acceptance():
    preregistration()
    if (ROOT/ACCEPT).exists():
        raise FileExistsError(ROOT/ACCEPT)
    folder = PRIVATE/('knn-v9-gap-tests-'+uuid4().hex)
    folder.mkdir()
    log = folder/'tests.log'
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    start = perf_counter()
    with log.open('x',encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    if not result.testsRun or not result.wasSuccessful() or result.skipped:
        print(log.read_text(encoding='utf-8')[-6000:],file=sys.stderr)
        raise ValueError(f'V9 synthetic acceptance failed: {log}')
    value = {'status':'v9_gap_tools_synthetic_accepted','created_utc':datetime.now(timezone.utc).isoformat(),
             'tests_run':result.testsRun,'seconds':perf_counter()-start,'failures':0,'errors':0,'skipped':0,
             'suites':list(SUITES),'environment':environment(),'method_files':[describe(ROOT/p) for p in METHODS],
             'log':describe(log),'specification':describe(ROOT/SPEC),'inventory':describe(ROOT/INVENTORY),
             'actual_new_keys_selected':0,'actual_new_query_verifications':0,'reserved_test':'locked','T_plan':None}
    public_json(ROOT/ACCEPT,value,exclusive=True)
    print(f"V9 acceptance passed: {result.testsRun} tests in {value['seconds']:.3f} seconds")


def _selection_args(meta):
    spec,_ = preregistration()
    groups = [read(ROOT/meta[key]) for key in ('history64','history48','history34','history8')]
    a,b,c,d = ({r['key_sha256'] for r in g['probes']} for g in groups)
    if ([len(g['probes']) for g in groups] != [64,48,34,8] or len(a & b) != 2
            or c & (a|b) or d & (a|b|c) or len(a|b|c|d) != 152):
        raise ValueError('Four frozen cohorts differ')
    return ROOT/meta['roster'],*groups,spec


def _freeze(folder, meta, watch):
    args = _selection_args(meta)
    selection = select_gap_roster(*args,watch=watch)
    audit_gap_order(args[0],selection,*args[1:],watch=watch)
    write(folder/'frozen_probes.json',selection)
    write(folder/'selection_seal.json',{'utc':datetime.now(timezone.utc).isoformat(),
        'selection':describe(folder/'frozen_probes.json'),'inventory':describe(ROOT/INVENTORY),
        'specification':describe(ROOT/SPEC),'full_sort_agrees':True})
    return selection,args[-1]


def _extract(folder, request, selection, database, watch):
    config = read(ROOT/MODEL_SPEC)['configuration']
    paths = {k:ROOT/v for k,v in PATHS.items()}
    probes = selection['probes']
    index_root = folder/'source_index'
    index = build_source_index(index_root,ROOT/PRIMARY,paths,config,probes,watch)
    bound = {r['path']:r for r in request['sources']}
    check_index(index,probes,config['fixed_validation']['queries'],bound,ROOT)
    subset = folder/'raw_selected_inputs'
    frames = {'dataset':'dataset/queries.csv','p0_rank':'P0/ranked_queries.csv',
              'p0_metrics':'P0/query_metrics.csv','p0_slices':'P0/query_slices.csv',
              'c1':'C1/queries.jsonl','d1':'D1/queries.jsonl','k1':'primary/queries.jsonl'}
    copies = [(index_root/index['samples'][key]['path'],subset/name,index['samples'][key]) for key,name in frames.items()]
    for key,name in (('dataset','catalog.csv'),('P0','item_counts.csv')):
        source = paths[key]/name
        copies.append((source,subset/key/name,bound[source.relative_to(ROOT).as_posix()]))
    for source,target,ref in copies:
        watch()
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        copied = describe(target,watch)
        if any(copied[k] != ref[k] for k in ('bytes','sha256')):
            raise ValueError('Selected raw source bytes differ')
    config['fixed_validation']['queries'] = len(probes)
    write(subset/'configuration.json',config)
    write(subset/'ordinals.json',[{'key':r['key'],'original_ordinal':r['original_ordinal'],'subset_ordinal':i}
                                  for i,r in enumerate(probes)])
    records = [describe(p,watch) for p in sorted(subset.rglob('*')) if p.is_file()]
    records.append(bound[database.relative_to(ROOT).as_posix()])
    records += [describe(folder/name,watch) for name in ('frozen_probes.json','selection_seal.json',
                'source_index/manifest.json','source_index/seal.json')]
    binding = {'sources':records,'configuration':config,'scope':'v9_capped_and_uncapped_engineering_subset_only'}
    write(folder/'subset_binding.json',binding)
    return binding


def _summarize(store, measured, selection, spec):
    detail = store.detailed_cost_summary(measured)
    probes = selection['probes']
    proof = ledger_proof(store,probes)
    if proof['actual_committed_bytes'] != sum(r['frame_bytes'] for r in detail['rows']):
        raise ValueError('Physical ledger size differs from observed frames')
    predictions = [r['payload']['expected']['predictions']['K1'] for r in store.iter_records()]
    result = summarize_gap_cost(measured,detail,selection,spec)
    result.update(proof=proof,workload_by_cell=sample_workload(probes,measured,predictions))
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
    detail,result = _summarize(store,measured,selection,spec)
    write(run/'measurements.json',measured)
    write(run/'observations.json',{'detail':detail,'append_events':store.append_events,'budget_events':store.budget_events})
    write(run/'proof.json',result['proof'])
    write(run/'summary.json',result)
    return result


def _audit_repeat(folder, request, binding, selection, spec, i):
    folder = folder/f'repeat_{i}'
    run = read(folder/'verified_subset/run.json')
    if run['binding'] != binding or any(run[k] != request[k] for k in ('deadline_utc','budget_seconds')):
        raise ValueError('Changed checkpoint deadline or subset binding')
    store = DetailedTimedStore.open(folder/'verified_subset',binding,source_root=ROOT)
    measured = read(folder/'measurements.json')
    observations = read(folder/'observations.json')
    store.commit_events = measured['chunk_commits']
    store.append_events = observations['append_events']
    store.budget_events = observations['budget_events']
    detail,result = _summarize(store,measured,selection,spec)
    if detail != observations['detail'] or result != read(folder/'summary.json') or result['proof'] != read(folder/'proof.json'):
        raise ValueError('Saved repeat differs from independent evidence')
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
                raise ValueError('Environment or wall budget changed')
        with _phase(folder,'freeze_gap_selection',watch):
            selection,spec = _freeze(folder,meta,watch)
        model_root = ROOT/meta['independent_model_folder']
        database = model_root/'independent.sqlite'
        _check_db(database)
        with _phase(folder,'seven_source_extract',watch):
            binding = _extract(folder,request,selection,database,watch)
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
            verify_bindings(binding['sources'],watch)
            _check_db(database)
            check_gates()
        write(folder/'done.json',{'repeats':2,'new_keys':8,'engineering_checks':16})
    except BaseException as error:
        write(folder/'failure.json',{'error_type':type(error).__name__,'reserved_test':'locked','full_readback_started':False})
        raise


def _completed(folder):
    completion = read(folder/'supervisor_completion.json')
    _normal_exit(completion)
    for identity in read(folder/'tracked_process_identities.json')['identities']:
        try:
            p = psutil.Process(identity['pid'])
            if p.is_running() and p.create_time() == identity['create_time']:
                raise ValueError('A recorded worker is still alive')
        except psutil.NoSuchProcess:
            pass
    phases = {p.name.removesuffix('_receipt.json'):read(p) for p in folder.glob('*_receipt.json')}
    required = {'initial_frozen_source_hash','freeze_gap_selection','seven_source_extract',
                'gap_repeat_0','gap_repeat_1','final_frozen_source_hash'}
    if (set(phases) != required or any(not r['completed'] for r in phases.values())
            or read(folder/'done.json') != {'repeats':2,'new_keys':8,'engineering_checks':16}):
        raise ValueError('Incomplete V9 window')
    return completion,phases


def publish(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v9-gap-'):
        raise ValueError('Expected a private V9 namespace')
    namespace = folder.relative_to(ROOT).as_posix()
    existing = read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    if existing and existing['namespace'] != namespace:
        raise FileExistsError('A different V9 run already published')
    completion,phases = _completed(folder)
    request = read(folder/'request.json')
    args = _selection_args(request['metadata'])
    selection = select_gap_roster(*args)
    audit_gap_order(args[0],selection,*args[1:])
    seal = read(folder/'selection_seal.json')
    if (selection != read(folder/'frozen_probes.json') or seal['selection'] != describe(folder/'frozen_probes.json')
            or seal['specification'] != describe(ROOT/SPEC) or seal['inventory'] != describe(ROOT/INVENTORY)
            or not seal['full_sort_agrees']):
        raise ValueError('Frozen sample differs at publication')
    binding = read(folder/'subset_binding.json')
    verify_bindings(binding['sources'])
    index = read(folder/'source_index/manifest.json')
    check_index(index,selection['probes'],args[2]['population']['total_queries'],
                {r['path']:r for r in request['sources']},ROOT)
    repeats = [_audit_repeat(folder,request,binding,selection,args[-1],i) for i in range(2)]
    _same_payload(repeats[0]['proof'],repeats[1]['proof'])
    compare_frames(folder,8)
    if repeats[0]['workload_by_cell'] != repeats[1]['workload_by_cell']:
        raise ValueError('Logical work differs between repeats')
    parent = read(ROOT/PARENT)
    coverage,missing = check_coverage(parent['remaining_unrepresented_cells'],repeats[0]['cells'])
    if coverage != args[-1]['conditional_after_all_8_verified']:
        raise ValueError('Observed coverage differs from pre-registration')
    audit = {'selection_full_sort_agrees':True,'physical_frames_identical':True,
             'cap_and_boundary_verified_against_original':True,'recomputed_repeat_costs':True,
             'tracked_workers_stopped':True,'new_historical_overlap':0}
    audit_path = folder/'post_exit_audit.json'
    if audit_path.exists():
        if read(audit_path) != audit:
            raise ValueError('Saved publication audit changed')
    else:
        write(audit_path,audit)
    report = {'status':'v9_gap_8_measured_twice','created_utc':existing['created_utc'] if existing else datetime.now(timezone.utc).isoformat(),
              'namespace':namespace,'supervisor':completion,'phases':phases,'environment':environment(),
              'sources_bound':len(request['sources']),'sources_reverified_before_after':True,
              'inventory':seal['inventory'],'specification':seal['specification'],'selection_sha256':seal['selection']['sha256'],
              'coverage':coverage,'remaining_unrepresented_cells':missing,'repeats':repeats,'scope':{
                 'new_keys':8,'new_engineering_verifications':16,'new_primary_fits':0,'new_primary_validation_runs':0,
                 'new_primary_bootstrap':0,'SQL_candidate_runs':0,'full_readback_started':False,'reserved_test':'locked'},
              'gates':check_gates(),'T_plan':None,'evidence':[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]}
    if existing is None:
        public_json(ROOT/REPORT,report,exclusive=True)
    elif existing != report:
        raise ValueError('Read-only re-audit differs from existing report')
    print({'report':REPORT,'namespace':namespace,'seconds':completion['seconds'],'coverage':coverage,'proof':repeats[0]['proof']})


def supervise():
    if (ROOT/REPORT).exists():
        raise FileExistsError('V9 report exists; use --publish to re-audit')
    check_gates()
    spec,inv = preregistration()
    accepted = read(ROOT/ACCEPT)
    if (accepted['status'] != 'v9_gap_tools_synthetic_accepted' or accepted['environment'] != environment()
            or {r['path'] for r in accepted['method_files']} != set(METHODS)
            or accepted['inventory'] != spec['inventory'] or accepted['specification'] != describe(ROOT/SPEC)):
        raise ValueError('V9 methods, inventory and specification must pass acceptance')
    verify_bindings(accepted['method_files'])
    parent_record = _record(inv['inputs'],'/'+Path(PARENT).name)
    verify_bindings([parent_record])
    parent = read(ROOT/PARENT)
    remaining = {r['cell']:r['population'] for r in inv['remaining_cells_ranked']}
    if (parent['status'] != 'v8_gap_8_measured_twice' or not parent['sources_reverified_before_after']
            or parent['coverage'] != {'v6_plus_new_cells_with_sample':38,'v6_plus_new_unrepresented_population':5615,
                                      'distinct_historically_verified_queries':152}
            or parent['remaining_unrepresented_cells'] != remaining or len(remaining) != 17 or sum(remaining.values()) != 5615):
        raise ValueError('Completed V8 reference and remaining coverage required')
    anchors = [_record(parent['evidence'],'/'+name) for name in ('request.json','supervisor_completion.json','frozen_probes.json')]
    verify_bindings(anchors)
    _normal_exit(read(ROOT/anchors[1]['path']))
    prior = read(ROOT/anchors[0]['path'])
    meta = {k:prior['metadata'][k] for k in ('history64','history48','history34','roster','independent_model_folder','environment')}
    if meta['environment'] != environment():
        raise ValueError('Reference environment differs')
    meta.update(history8=anchors[2]['path'],queries=8,repeats=2)
    records = {r['path']:r for r in prior['sources']}
    for r in [*inv['inputs'],*anchors,*accepted['method_files'],spec['inventory'],describe(ROOT/SPEC),describe(ROOT/ACCEPT)]:
        if r['path'] in records and records[r['path']] != r:
            raise ValueError('Inherited input binding changed')
        records[r['path']] = r
    folder = PRIVATE/('knn-v9-gap-'+uuid4().hex)
    print('V9 supervised window: '+folder.relative_to(ROOT).as_posix(),flush=True)
    receipt = run_window(folder,[sys.executable,'-B','-m',MODULE,'--worker',str(folder)],
                         [records[k] for k in sorted(records)],'joint_tail',metadata=meta,budget_seconds=1800)
    _normal_exit(receipt)
    publish(folder)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance',action='store_true')
    modes.add_argument('--measure',action='store_true')
    modes.add_argument('--publish',type=Path)
    modes.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.acceptance:
        acceptance()
    elif args.measure:
        supervise()
    elif args.publish:
        publish(args.publish)
    else:
        worker(args.worker)
