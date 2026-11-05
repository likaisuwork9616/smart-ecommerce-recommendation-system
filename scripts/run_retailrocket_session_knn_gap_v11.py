"""V11 eight-query bounded cost window for two n4 cells and post-exit audit."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import sys
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, PATHS, read, write, describe, verify_bindings, environment, check_gates)
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json, _phase, _check_db, _record
from scripts.run_retailrocket_session_knn_gap_v9 import _completed, _extract
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_gap_v7 import check_index, ledger_proof
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_pair_v4 import verify_selected
from scripts.retailrocket_session_knn_gap_v11 import (
    CELLS, _quotas, audit_gap_order, check_coverage, compare_frames, sample_workload, select_gap_roster, summarize_gap_cost)


MODULE = 'scripts.run_retailrocket_session_knn_gap_v11'
BASE = 'reports/stage12/retailrocket_session_knn_'
INVENTORY = BASE+'v11_gap_inventory_20261105.json'
SPEC = BASE+'v11_gap_sampling_specification_20261105.json'
ACCEPT = BASE+'v11_gap_acceptance_20261105.json'
REPORT = BASE+'v11_gap_cost_20261105.json'
PARENT = BASE+'v10_gap_cost_20261105.json'
METHODS = ('scripts/retailrocket_session_knn_gap_v11.py', 'scripts/run_retailrocket_session_knn_gap_v11.py',
           'tests/test_retailrocket_session_knn_gap_v11.py')
SUITES = ('tests.test_retailrocket_session_knn_gap_v11','tests.test_retailrocket_session_knn_gap_v10')
HISTORY = ('history64','history48','history34','history8','history8_v9','history8_v10')
BEFORE = {'v6_plus_new_cells_with_sample':42,'v6_plus_new_unrepresented_population':1218,
          'distinct_historically_verified_queries':168}


def preregistration():
    spec, inv = read(ROOT/SPEC),read(ROOT/INVENTORY)
    if (spec['status'] != 'v11_target_two_specification_frozen' or spec['inventory'] != describe(ROOT/INVENTORY)
            or inv['status'] != 'v11_gap_inventory_verified' or inv['coverage_before']['distinct_historical_keys'] != 168):
        raise ValueError('Expected the bound V11 preregistration and inventory')
    quotas = _quotas(spec)
    if ([r['cell'] for r in inv['remaining_cells_ranked'][:2]] != list(CELLS)
            or [r['cell'] for r in inv['top_two_cells']] != list(CELLS)
            or any(quotas[r['cell']][k]!=r[k] for r in inv['top_two_cells']
                   for k in ('population','historical_exclusions','eligible'))):
        raise ValueError('Registered cells or capacity differ from the verified inventory')
    return spec,inv


def acceptance():
    spec,_ = preregistration()
    if (ROOT/ACCEPT).exists():
        raise FileExistsError(ROOT/ACCEPT)
    folder = PRIVATE/('knn-v11-gap-tests-'+uuid4().hex)
    folder.mkdir()
    start = perf_counter()
    log = folder/'tests.log'
    with log.open('x',encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not result.testsRun or not result.wasSuccessful() or result.skipped:
        print(log.read_text(encoding='utf-8')[-6000:],file=sys.stderr)
        raise ValueError(f'Synthetic acceptance failed: {log}')
    receipt = {'status':'v11_gap_tools_synthetic_accepted','created_utc':datetime.now(timezone.utc).isoformat(),
               'tests_run':result.testsRun,'seconds':perf_counter()-start,'failures':0,'errors':0,'skipped':0,
               'suites':list(SUITES),'environment':environment(),'method_files':[describe(ROOT/p) for p in METHODS],
               'specification':describe(ROOT/SPEC),'inventory':spec['inventory'],'log':describe(log),
               'actual_new_keys_selected':0,'actual_new_query_verifications':0,'reserved_test':'locked','T_plan':None}
    public_json(ROOT/ACCEPT,receipt,exclusive=True)
    print(f"V11 acceptance passed: {result.testsRun} tests in {receipt['seconds']:.3f} seconds")


def _selection_args(meta):
    spec,_ = preregistration()
    groups = [read(ROOT/meta[k]) for k in HISTORY]
    sets = [{p['key_sha256'] for p in g['probes']} for g in groups]
    if ([len(g['probes']) for g in groups]!=[64,48,34,8,8,8] or len(sets[0] & sets[1])!=2
            or any(sets[i] & set.union(*sets[:i]) for i in range(2,6)) or len(set.union(*sets))!=168):
        raise ValueError('Six historical cohorts do not match the fixed 168-key inventory')
    return ROOT/meta['roster'],*groups,spec


def _selection(args, watch=lambda:None):
    chosen = select_gap_roster(*args,watch=watch)
    audit_gap_order(args[0],chosen,*args[1:],watch=watch)
    return chosen


def _seal(folder,selection,spec):
    return {'selection':describe(folder/'frozen_probes.json'),'specification':describe(ROOT/SPEC),
            'inventory':spec['inventory'],'roster_sha256':selection['roster_sha256'],'full_sort_agrees':True}


def _repeat(folder, request, binding, selection, spec, i, *, model=None, database=None, watch=lambda:None):
    """Compute once under the writer; the supervisor reopens and recomputes from saved evidence."""
    run = folder/f'repeat_{i}'
    checkpoint = run/'verified_subset'
    if model is not None:
        subset = folder/'raw_selected_inputs'
        store = DetailedTimedStore.create(checkpoint,binding,request['deadline_utc'],request['budget_seconds'],
            source_root=ROOT,expected_queries=8,required_stages=('reconstruction','queries'))
        with store.writer():
            store.seal_stage('reconstruction',{'kind':'reused_v5_reconstructed_model','fit_audit':model['fit_audit']})
            measured = verify_selected(subset/'primary',{k:subset/k for k in PATHS},binding['configuration'],
                store,model,database,read(subset/'ordinals.json'),watch)
        write(run/'measurements.json',measured)
        events = {'append_events':store.append_events,'budget_events':store.budget_events}
    else:
        record = read(checkpoint/'run.json')
        if record['binding']!=binding or any(record[k]!=request[k] for k in ('deadline_utc','budget_seconds')):
            raise ValueError('Changed repeat binding or window deadline')
        measured = read(run/'measurements.json')
        events = read(run/'observations.json')
        store = DetailedTimedStore.open(checkpoint,binding,source_root=ROOT)
        store.commit_events = measured['chunk_commits']
        store.append_events = events['append_events']
        store.budget_events = events['budget_events']
    detail = store.detailed_cost_summary(measured)
    proof = ledger_proof(store,selection['probes'])
    if proof['actual_committed_bytes']!=sum(row['frame_bytes'] for row in detail['rows']):
        raise ValueError('Scientific ledger length differs from measured frames')
    predictions = [r['payload']['expected']['predictions']['K1'] for r in store.iter_records()]
    result = summarize_gap_cost(measured,detail,selection,spec)
    result.update(proof=proof,workload_by_cell=sample_workload(selection['probes'],measured,predictions))
    if model is None:
        if events['detail']!=detail or read(run/'proof.json')!=proof or read(run/'summary.json')!=result:
            raise ValueError('Post-exit raw evidence differs from published repeat')
    else:
        write(run/'observations.json',dict(events,detail=detail))
        write(run/'proof.json',proof)
        write(run/'summary.json',result)
    return result


def _compare(folder, repeats):
    _same_payload(repeats[0]['proof'],repeats[1]['proof'])
    compare_frames(folder,8)
    if repeats[0]['workload_by_cell']!=repeats[1]['workload_by_cell']:
        raise ValueError('Paired workloads or frontier counts differ')


def worker(folder):
    request = read(folder/'request.json')
    meta = request['metadata']
    watch = ThrottledWatch(folder,request['deadline_utc'])
    try:
        with _phase(folder,'initial_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            check_gates()
            if request['budget_seconds']!=1800 or meta['environment']!=environment():
                raise ValueError('Original engineering budget or environment changed')
        args = _selection_args(meta)
        spec = args[-1]
        with _phase(folder,'freeze_gap_selection',watch):
            selected = _selection(args,watch)
            write(folder/'frozen_probes.json',selected)
            write(folder/'selection_seal.json',dict(_seal(folder,selected,spec),utc=datetime.now(timezone.utc).isoformat()))
        model_root = ROOT/meta['independent_model_folder']
        db = model_root/'independent.sqlite'
        _check_db(db)
        with _phase(folder,'seven_source_extract',watch):
            transport = _extract(folder,request,selected,db,watch)
            binding = dict(transport,scope='v11_two_n4_cells_eight_engineering_only',
                           transport=describe(folder/'subset_binding.json'))
            write(folder/'v11_subset_binding.json',binding)
        model = read(model_root/'reconstruction.json')['receipt']
        repeats = []
        for i in range(2):
            with _phase(folder,f'gap_repeat_{i}',watch):
                repeats.append(_repeat(folder,request,binding,selected,spec,i,model=model,database=db,watch=watch))
                if i:
                    _compare(folder,repeats)
        with _phase(folder,'final_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            verify_bindings(binding['sources']+[binding['transport']],watch)
            _check_db(db)
            check_gates()
        write(folder/'done.json',{'repeats':2,'new_keys':8,'engineering_checks':16})
    except BaseException as exc:
        write(folder/'failure.json',{'error_type':type(exc).__name__,'reserved_test':'locked','full_readback_started':False})
        raise


def publish(folder):
    folder = folder.resolve()
    if folder.parent!=PRIVATE or not folder.name.startswith('knn-v11-gap-'):
        raise ValueError('V11 audit requires its own private namespace')
    namespace = folder.relative_to(ROOT).as_posix()
    existing = read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    if existing and existing['namespace']!=namespace:
        raise FileExistsError('A different V11 execution already published')
    completion,phases = _completed(folder)
    request = read(folder/'request.json')
    args = _selection_args(request['metadata'])
    selected,spec = _selection(args),args[-1]
    seal = read(folder/'selection_seal.json')
    if (selected!=read(folder/'frozen_probes.json') or not seal.get('utc')
            or any(seal.get(k)!=v for k,v in _seal(folder,selected,spec).items())):
        raise ValueError('Frozen V11 roster, specification or seal differs')
    binding = read(folder/'v11_subset_binding.json')
    verify_bindings(binding['sources']+[binding['transport']])
    check_index(read(folder/'source_index/manifest.json'),selected['probes'],args[2]['population']['total_queries'],
                {r['path']:r for r in request['sources']},ROOT)
    repeats = [_repeat(folder,request,binding,selected,spec,i) for i in range(2)]
    _compare(folder,repeats)
    parent = read(ROOT/PARENT)
    coverage,missing = check_coverage(parent['remaining_unrepresented_cells'],repeats[0]['cells'])
    if coverage!=spec['conditional_after_all_8_verified']:
        raise ValueError('Actual coverage differs from conditional pre-registration')
    audit = {'independent_selection_matches':True,'two_ledgers_byte_identical':True,
             'full_pool_top500_and_frontier_verified':True,'post_exit_costs_recomputed':True,
             'tracked_processes_stopped':True,'new_historical_overlap':0}
    if (folder/'post_exit_audit.json').exists():
        if read(folder/'post_exit_audit.json')!=audit:
            raise ValueError('Existing immutable audit differs')
    else:
        write(folder/'post_exit_audit.json',audit)
    report = {'status':'v11_gap_8_measured_twice','created_utc':existing['created_utc'] if existing else datetime.now(timezone.utc).isoformat(),
              'namespace':namespace,'environment':environment(),'supervisor':completion,'phases':phases,
              'sources_bound':len(request['sources']),'sources_reverified_before_after':True,
              'selection_sha256':seal['selection']['sha256'],'specification':seal['specification'],'inventory':seal['inventory'],
              'repeats':repeats,'coverage':coverage,'remaining_unrepresented_cells':missing,
              'scope':{'new_keys':8,'new_engineering_verifications':16,'new_primary_fits':0,
                       'new_primary_validation_runs':0,'new_primary_bootstrap':0,'SQL_candidate_runs':0,
                       'full_readback_started':False,'reserved_test':'locked'},
              'gates':check_gates(),'T_plan':None,'evidence':[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]}
    if existing is None:
        public_json(ROOT/REPORT,report,exclusive=True)
    elif existing!=report:
        raise ValueError('Re-audit differs from the previously published V11 report')
    print({'report':REPORT,'namespace':namespace,'seconds':completion['seconds'],'coverage':coverage,'proof':repeats[0]['proof']})


def supervise():
    if (ROOT/REPORT).exists():
        raise FileExistsError('Use --publish to re-audit the existing V11 result')
    check_gates()
    spec,inv = preregistration()
    accepted = read(ROOT/ACCEPT)
    if (accepted['status']!='v11_gap_tools_synthetic_accepted' or accepted['environment']!=environment()
            or {r['path'] for r in accepted['method_files']}!=set(METHODS)
            or accepted['inventory']!=spec['inventory'] or accepted['specification']!=describe(ROOT/SPEC)):
        raise ValueError('Current V11 methods, specification and environment require acceptance')
    verify_bindings(accepted['method_files'])
    parent_record = _record(inv['inputs'],'/'+Path(PARENT).name)
    verify_bindings([parent_record])
    parent = read(ROOT/PARENT)
    remaining = {r['cell']:r['population'] for r in inv['remaining_cells_ranked']}
    if (parent['status']!='v10_gap_8_measured_twice' or not parent['sources_reverified_before_after']
            or parent['coverage']!=BEFORE or parent['remaining_unrepresented_cells']!=remaining
            or len(remaining)!=13 or sum(remaining.values())!=1218):
        raise ValueError('Completed V10 remaining-cell inventory is required')
    anchors = [_record(parent['evidence'],'/'+name) for name in ('request.json','supervisor_completion.json','frozen_probes.json')]
    verify_bindings(anchors)
    _normal_exit(read(ROOT/anchors[1]['path']))
    prior = read(ROOT/anchors[0]['path'])
    meta = {k:prior['metadata'][k] for k in (*HISTORY[:-1],'roster','independent_model_folder','environment')}
    if meta['environment']!=environment():
        raise ValueError('Parent engineering environment differs')
    meta.update(history8_v10=anchors[2]['path'],queries=8,repeats=2)
    records = {r['path']:r for r in prior['sources']}
    for record in [*inv['inputs'],*anchors,*accepted['method_files'],spec['inventory'],describe(ROOT/SPEC),describe(ROOT/ACCEPT)]:
        if record['path'] in records and records[record['path']]!=record:
            raise ValueError('Inherited source definition changed')
        records[record['path']] = record
    folder = PRIVATE/('knn-v11-gap-'+uuid4().hex)
    print('V11 supervised window: '+folder.relative_to(ROOT).as_posix(),flush=True)
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
