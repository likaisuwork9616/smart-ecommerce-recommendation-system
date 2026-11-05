"""Bounded two-cell V8 measurement, using the unchanged V4 ranker and V6 store."""
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
from scripts.run_retailrocket_session_knn_gap_v7 import (
    PRIVATE, public_json, _phase, _check_db, _observe, _audit_repeat, _record)
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_sources_v4 import build_source_index
from scripts.retailrocket_session_knn_gap_v7 import check_index
from scripts.retailrocket_session_knn_gap_v8 import (
    CELLS, select_gap_roster, audit_gap_order, compare_frames, check_coverage, sample_workload)


MODULE = 'scripts.run_retailrocket_session_knn_gap_v8'
BASE = 'reports/stage12/retailrocket_session_knn_'
INVENTORY = BASE+'v8_gap_inventory_20261105.json'
SPEC = BASE+'v8_gap_sampling_specification_20261105.json'
ACCEPT = BASE+'v8_gap_acceptance_20261105.json'
REPORT = BASE+'v8_gap_cost_20261105.json'
PARENT = BASE+'v7_gap_cost_20261105.json'
METHODS = ('scripts/retailrocket_session_knn_gap_v8.py', 'scripts/run_retailrocket_session_knn_gap_v8.py',
           'tests/test_retailrocket_session_knn_gap_v8.py')
SUITES = ('tests.test_retailrocket_session_knn_gap_v8', 'tests.test_retailrocket_session_knn_gap_v7')


def preregistration():
    spec = read(ROOT/SPEC)
    inventory = read(ROOT/INVENTORY)
    if (spec['status'] != 'v8_target_two_specification_frozen'
            or spec['inventory'] != describe(ROOT/INVENTORY) or inventory['status'] != 'v8_gap_inventory_verified'
            or inventory['coverage_before']['distinct_historical_keys'] != 144):
        raise ValueError('Pinned 144-key inventory required')
    targets = {r['cell']:r for r in inventory['top_two_cells']}
    quotas = {r['cell']:r for r in spec['quotas']}
    if (set(quotas) != set(CELLS) or set(targets) != set(CELLS)
            or [r['cell'] for r in inventory['remaining_cells_ranked'][:2]] != [r['cell'] for r in inventory['top_two_cells']]
            or any(any(quotas[c][field] != targets[c][field]
                        for field in ('population','historical_exclusions','eligible')) for c in CELLS)):
        raise ValueError('Planned cells or capacity differ from bound inventory')
    return spec, inventory


def acceptance():
    preregistration()
    if (ROOT/ACCEPT).exists():
        raise FileExistsError(ROOT/ACCEPT)
    folder = PRIVATE/('knn-v8-gap-tests-'+uuid4().hex)
    folder.mkdir()
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    log = folder/'tests.log'
    start = perf_counter()
    with log.open('x',encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    if not result.testsRun or not result.wasSuccessful() or result.skipped:
        raise ValueError(f'V8 acceptance failed: {log}')
    receipt = {'status':'v8_gap_tools_synthetic_accepted','created_utc':datetime.now(timezone.utc).isoformat(),
               'tests_run':result.testsRun,'seconds':perf_counter()-start,'failures':0,'errors':0,'skipped':0,
               'suites':list(SUITES),'environment':environment(),'method_files':[describe(ROOT/p) for p in METHODS],
               'specification':describe(ROOT/SPEC),'inventory':describe(ROOT/INVENTORY),'log':describe(log),
               'actual_new_keys_selected':0,'actual_new_query_verifications':0,'reserved_test':'locked','T_plan':None}
    public_json(ROOT/ACCEPT,receipt,exclusive=True)
    print(f"V8 synthetic acceptance passed: {result.testsRun} tests, {receipt['seconds']:.3f} seconds")


def _selection_args(metadata):
    spec, _ = preregistration()
    groups = tuple(read(ROOT/metadata[key]) for key in ('history64','history48','history34'))
    a,b,c = ({p['key_sha256'] for p in g['probes']} for g in groups)
    if ([len(g['probes']) for g in groups] != [64,48,34] or len(a & b) != 2
            or c & (a | b) or len(a | b | c) != 144):
        raise ValueError('Frozen three historical samples differ')
    return (ROOT/metadata['roster'], *groups, spec)


def _extract(folder, request, selection, database, watch):
    """Build a fresh seven-source index; bind exact raw frames and model under V8 scope."""
    paths = {k:ROOT/v for k,v in PATHS.items()}
    cfg = read(ROOT/MODEL_SPEC)['configuration']
    probes = selection['probes']
    index = build_source_index(folder/'source_index', ROOT/PRIMARY, paths, cfg, probes, watch)
    bound = {r['path']:r for r in request['sources']}
    check_index(index,probes,cfg['fixed_validation']['queries'],bound,ROOT)
    selected = folder/'raw_selected_inputs'
    copies = []
    for key,name in (('dataset','dataset/queries.csv'),('p0_rank','P0/ranked_queries.csv'),
                     ('p0_metrics','P0/query_metrics.csv'),('p0_slices','P0/query_slices.csv'),
                     ('c1','C1/queries.jsonl'),('d1','D1/queries.jsonl'),('k1','primary/queries.jsonl')):
        ref = index['samples'][key]
        copies.append((folder/'source_index'/ref['path'],selected/name,ref))
    for key,name in (('dataset','catalog.csv'),('P0','item_counts.csv')):
        source = paths[key]/name
        copies.append((source,selected/key/name,bound[source.relative_to(ROOT).as_posix()]))
    for source,destination,reference in copies:
        watch()
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        record = describe(destination,watch)
        if any(record[k] != reference[k] for k in ('bytes','sha256')):
            raise ValueError('Seven-source extracted frame/context identity changed')
    cfg['fixed_validation']['queries'] = len(probes)
    write(selected/'configuration.json',cfg)
    write(selected/'ordinals.json',[{'key':p['key'],'original_ordinal':p['original_ordinal'],'subset_ordinal':i}
                                    for i,p in enumerate(probes)])
    records = [describe(p,watch) for p in sorted(selected.rglob('*')) if p.is_file()]
    records.append(bound[database.relative_to(ROOT).as_posix()])
    records.extend(describe(folder/name,watch) for name in
                   ('frozen_probes.json','selection_seal.json','source_index/manifest.json','source_index/seal.json'))
    binding = {'sources':records,'configuration':cfg,'scope':'v8_two_gap_cells_eight_engineering_only'}
    write(folder/'subset_binding.json',binding)
    return binding


def worker(folder):
    request = read(folder/'request.json')
    meta = request['metadata']
    watch = ThrottledWatch(folder,request['deadline_utc'])
    try:
        with _phase(folder,'initial_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            check_gates()
            if request['budget_seconds'] != 1800 or meta['environment'] != environment():
                raise ValueError('Frozen deadline or environment differs')
        args = _selection_args(meta)
        with _phase(folder,'freeze_gap_selection',watch):
            selection = select_gap_roster(*args,watch=watch)
            audit_gap_order(args[0],selection,*args[1:],watch=watch)
            write(folder/'frozen_probes.json',selection)
            write(folder/'selection_seal.json',{'utc':datetime.now(timezone.utc).isoformat(),
                'selection':describe(folder/'frozen_probes.json'),'specification':describe(ROOT/SPEC),
                'inventory':describe(ROOT/INVENTORY),'full_sort_agrees':True})
        model_root = ROOT/meta['independent_model_folder']
        database = model_root/'independent.sqlite'
        _check_db(database)
        with _phase(folder,'seven_source_extract',watch):
            binding = _extract(folder,request,selection,database,watch)
        model = read(model_root/'reconstruction.json')['receipt']
        proofs = []
        for i in range(2):
            with _phase(folder,f'gap_repeat_{i}',watch):
                proofs.append(_observe(folder,request,binding,model,database,selection,args[-1],watch,i))
                sample_workload(selection['probes'],read(folder/f'repeat_{i}'/'measurements.json'))
                if i:
                    _same_payload(*proofs)
                    compare_frames(folder,8)
        with _phase(folder,'final_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch)
            verify_bindings(binding['sources'],watch)
            _check_db(database)
            check_gates()
        write(folder/'done.json',{'repeats':2,'new_keys':8,'engineering_checks':16})
    except BaseException as error:
        write(folder/'failure.json',{'error_type':type(error).__name__,'full_readback_started':False,'reserved_test':'locked'})
        raise


def publish(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v8-gap-'):
        raise ValueError('Expected private V8 window')
    existing = read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    namespace = folder.relative_to(ROOT).as_posix()
    if existing and existing['namespace'] != namespace:
        raise FileExistsError('A different V8 window has already published')
    completion = read(folder/'supervisor_completion.json')
    _normal_exit(completion)
    for ident in read(folder/'tracked_process_identities.json')['identities']:
        try:
            p = psutil.Process(ident['pid'])
            if p.is_running() and p.create_time() == ident['create_time']:
                raise ValueError('Tracked worker is still running')
        except psutil.NoSuchProcess:
            pass
    phases = {p.name.removesuffix('_receipt.json'):read(p) for p in folder.glob('*_receipt.json')}
    expected = {'initial_frozen_source_hash','freeze_gap_selection','seven_source_extract',
                'gap_repeat_0','gap_repeat_1','final_frozen_source_hash'}
    if (phases.keys() != expected or any(not r['completed'] for r in phases.values())
            or read(folder/'done.json') != {'repeats':2,'new_keys':8,'engineering_checks':16}):
        raise ValueError('Incomplete V8 phase evidence')
    request = read(folder/'request.json')
    args = _selection_args(request['metadata'])
    selected = select_gap_roster(*args)
    audit_gap_order(args[0],selected,*args[1:])
    seal = read(folder/'selection_seal.json')
    if (selected != read(folder/'frozen_probes.json') or seal['selection'] != describe(folder/'frozen_probes.json')
            or seal['specification'] != describe(ROOT/SPEC) or seal['inventory'] != describe(ROOT/INVENTORY)
            or not seal['full_sort_agrees']):
        raise ValueError('Selection, inventory or specification changed')
    binding = read(folder/'subset_binding.json')
    verify_bindings(binding['sources'])
    check_index(read(folder/'source_index/manifest.json'), selected['probes'], args[2]['population']['total_queries'],
                {r['path']:r for r in request['sources']},ROOT)
    repeats = []
    for i in range(2):
        summary = _audit_repeat(folder,request,binding,selected,args[-1],i)
        summary['workload_by_cell'] = sample_workload(selected['probes'],read(folder/f'repeat_{i}'/'measurements.json'))
        repeats.append(summary)
    _same_payload(repeats[0]['proof'],repeats[1]['proof'])
    compare_frames(folder,8)
    if repeats[0]['workload_by_cell'] != repeats[1]['workload_by_cell']:
        raise ValueError('Paired repeats differ in actual structural work')
    parent = read(ROOT/PARENT)
    coverage, missing = check_coverage(parent['remaining_unrepresented_cells'],repeats[0]['cells'])
    if coverage != args[-1]['conditional_after_all_8_verified']:
        raise ValueError('Observed coverage differs from registered result')
    audit = {'selection_full_sort_agrees':True,'two_ledgers_byte_identical':True,'post_exit_costs_recomputed':True,
             'tracked_identities_stopped':True,'historical_overlap':0}
    audit_path = folder/'post_exit_audit.json'
    if audit_path.exists():
        if read(audit_path) != audit:
            raise ValueError('Prior immutable audit differs')
    else:
        write(audit_path,audit)
    report = {'status':'v8_gap_8_measured_twice','created_utc':existing['created_utc'] if existing else datetime.now(timezone.utc).isoformat(),
              'namespace':namespace,'supervisor':completion,'environment':environment(),'phases':phases,
              'sources_bound':len(request['sources']),'sources_reverified_before_after':True,
              'specification':seal['specification'],'inventory':seal['inventory'],'selection_sha256':seal['selection']['sha256'],
              'coverage':coverage,'remaining_unrepresented_cells':missing,'repeats':repeats,
              'scope':{'new_keys':8,'new_engineering_verifications':16,'new_primary_fits':0,
                       'new_primary_validation_runs':0,'new_primary_bootstrap':0,'SQL_candidate_runs':0,
                       'full_readback_started':False,'reserved_test':'locked'},'T_plan':None,'gates':check_gates(),
              'evidence':[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]}
    if existing is None:
        public_json(ROOT/REPORT,report,exclusive=True)
    elif report != existing:
        raise ValueError('Re-audit differs from published V8 report')
    print({'report':REPORT,'namespace':namespace,'seconds':completion['seconds'],'coverage':coverage,'proof':repeats[0]['proof']})


def supervise():
    if (ROOT/REPORT).exists():
        raise FileExistsError('Audit published V8 results with --publish instead')
    check_gates()
    spec, inventory = preregistration()
    accepted = read(ROOT/ACCEPT)
    if (accepted['status'] != 'v8_gap_tools_synthetic_accepted' or accepted['environment'] != environment()
            or {r['path'] for r in accepted['method_files']} != set(METHODS)
            or accepted['inventory'] != spec['inventory'] or accepted['specification'] != describe(ROOT/SPEC)):
        raise ValueError('Current V8 method files, specification and environment must pass acceptance')
    verify_bindings(accepted['method_files'])
    parent_record = _record(inventory['inputs'],'/'+Path(PARENT).name)
    verify_bindings([parent_record])
    parent = read(ROOT/PARENT)
    remaining = {r['cell']:r['population'] for r in inventory['remaining_cells_ranked']}
    if (parent['status'] != 'v7_gap_34_measured_twice' or not parent['sources_reverified_before_after']
            or parent['coverage'] != {'v6_plus_new_cells_with_sample':36,'v6_plus_new_unrepresented_population':43948,
                                      'distinct_historically_verified_queries':144}
            or parent['remaining_unrepresented_cells'] != remaining or len(remaining) != 19 or sum(remaining.values()) != 43948):
        raise ValueError('The completed V7 gap window is required')
    anchors = [_record(parent['evidence'],'/'+name) for name in ('request.json','supervisor_completion.json','frozen_probes.json')]
    verify_bindings(anchors)
    inherited = read(ROOT/anchors[0]['path'])
    _normal_exit(read(ROOT/anchors[1]['path']))
    old = inherited['metadata']
    if old['environment'] != environment():
        raise ValueError('V7 environment differs')
    records = {r['path']:r for r in inherited['sources']}
    for r in [*inventory['inputs'], *anchors, *accepted['method_files'], describe(ROOT/ACCEPT),
              describe(ROOT/SPEC), spec['inventory']]:
        if r['path'] in records and records[r['path']] != r:
            raise ValueError('Changed inherited frozen source')
        records[r['path']] = r
    meta = {k:old[k] for k in ('history64','history48','roster','independent_model_folder','environment')}
    meta.update(history34=anchors[2]['path'],queries=8,repeats=2)
    folder = PRIVATE/('knn-v8-gap-'+uuid4().hex)
    print('V8 supervised window: '+folder.relative_to(ROOT).as_posix(),flush=True)
    receipt = run_window(folder,[sys.executable,'-B','-m',MODULE,'--worker',str(folder)],
                         [records[k] for k in sorted(records)],'joint_tail',metadata=meta,budget_seconds=1800)
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
