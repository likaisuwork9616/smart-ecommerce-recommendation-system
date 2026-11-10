"""Synthetic-only V39 worker and independent publisher over frozen scientific audit."""
import argparse
from copy import deepcopy
from pathlib import Path
import sys

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, write, describe, verify_bindings, environment
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE
from scripts import freeze_retailrocket_session_knn_typed_v38 as design
from scripts import retailrocket_session_knn_typed_v39 as typed
from scripts import retailrocket_session_knn_typed_adapter_v39 as adapter
from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as s1
from scripts import run_retailrocket_session_knn_compare_v28 as entry
from scripts import retailrocket_session_knn_entry_v34 as common
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch

MODULE = 'scripts.retailrocket_session_knn_typed_publication_v39'
SEEDS = ('scripts/retailrocket_session_knn_typed_v39.py',
         'scripts/retailrocket_session_knn_typed_adapter_v39.py',
         'scripts/retailrocket_session_knn_typed_publication_v39.py',
         'tests/test_retailrocket_session_knn_typed_v39.py',
         'tests/test_retailrocket_session_knn_typed_adapter_v39.py',
         'tests/test_retailrocket_session_knn_typed_publication_v39.py')


def preserved_plan():
    """Retain all real descriptors; this is not permission to execute a real window."""
    design.audit()
    inherited = read(ROOT/design.parent.prior.SPEC)['preserved']
    direct = common.source_inventory(SEEDS, dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    methods = common.merge_methods(inherited['current_methods'], direct)
    sources = common.merge_methods(inherited['current_sources'], methods)
    for key, expected in (('current_sources', 2092), ('current_methods', 168), ('original_sources', 1937),
                          ('original_methods', 26), ('original_binding', 15)):
        if len(inherited[key]) != expected: raise ValueError('Retained original contract count changed')
    return dict(sources=sources, methods=methods, direct=direct,
                original_sources=inherited['current_sources'], original_methods=inherited['current_methods'],
                original_binding=inherited['original_binding'])


def folder_path(folder):
    folder = Path(folder).resolve()
    if (folder.parent.parent != PRIVATE.resolve() or not folder.parent.name.startswith('knn-v39-synthetic-')
            or folder.name != 'window'):
        raise ValueError('Only the direct artificial V39 window is admitted')
    return folder


def _artificial_bundle(folder, request):
    folder=folder_path(folder); bundle=folder.parent; meta=request['metadata']
    def inside(name):
        if type(name) is not str or not (ROOT/name).resolve().is_relative_to(bundle):
            raise ValueError('Scientific input escaped the same artificial bundle')
    for name in meta['cohort'].values(): inside(name)
    inside(meta['synthetic_data']['path'])
    for record in meta['context']['dependencies'].values(): inside(record['path'])
    binding=read(ROOT/meta['cohort']['old_run'])['binding']
    for record in binding['sources']: inside(record['path'])
    data=read(ROOT/meta['synthetic_data']['path']); inside(data['database'])
    if data['contract']['binding']!=binding:
        raise ValueError('Artificial data/store bindings differ')


def contract(request, folder=None):
    entry.old._check_window(request)
    adapter.require_policy(request)
    meta = request['metadata']
    if meta.get('synthetic_acceptance_only') is not True or meta.get('environment') != environment():
        raise ValueError('Exact artificial-only environment required')
    if folder is not None: _artificial_bundle(folder,request)
    plan = preserved_plan()
    if meta.get('typed_specification') != describe(ROOT/design.SPEC):
        raise ValueError('Frozen typed policy specification differs')
    if meta['context']['methods'] != plan['methods'] or meta.get('direct_methods') != plan['direct']:
        raise ValueError('Additive original/direct methods differ')
    common.require_direct_sources(plan['methods'], request['sources'])
    binding = read(ROOT/meta['cohort']['old_run'])['binding']
    adapter.context_contract(request, binding)
    bound = {r['path']:r for r in request['sources']}
    if bound.get(meta['synthetic_data']['path']) != meta['synthetic_data']:
        raise ValueError('Artificial data descriptor outside closure')
    verify_bindings([meta['synthetic_data'], meta['typed_specification']])
    return meta


def quiet_role(folder, request, role):
    value, diagnostics = common.quiet_contract(contract, request, folder)
    record = dict(role=role, synthetic_only=True, policy=adapter.POLICY, diagnostics=diagnostics)
    path = folder/(role+'_contract.json')
    if path.exists():
        if read(path) != record: raise ValueError('Closed role contract changed')
    else: write(path, record)
    print(role+' contract verified')
    return value


def _integer(value):
    return type(value) is int and value >= 0


def _interval(value, lo, hi):
    return (type(value) is dict and _integer(value.get('start_ns')) and _integer(value.get('end_ns'))
            and lo <= value['start_ns'] <= value['end_ns'] <= hi)


def audit_typed_runs(folder, request, contract_value, observer):
    """Called only after the original publisher's complete initial source check."""
    adapter.require_policy(request)
    deps = contract_value['dependencies']
    watch=ThrottledWatch(folder,request['deadline_utc'])
    with observer.span('publisher.typed_authority'):
        config = c1.json.loads(c1.verified_buffer(ROOT, deps['config'],watch))
        model = c1.json.loads(c1.verified_buffer(ROOT, deps['model'],watch))['receipt']
        values = dict(config=config, model=model)
        encoded = {name:c1.canonical(value) for name,value in values.items()}
        refs = {name:typed.build_reference(data) for name,data in encoded.items()}
        authority = dict(raw_sources={name:deps[name] for name in ('config','model')},
                         canonical={name:refs[name].source_descriptor for name in refs},
                         reference_statistics={name:refs[name].statistics() for name in refs},
                         reference_scheme=typed.SCHEME, policy=adapter.POLICY)
        expected_stats={}
        for name in refs:
            equal,stats=typed.compare_with_stats(values[name],refs[name])
            if equal is not True: raise ValueError('Independent reference self-comparison failed')
            expected_stats[name]=stats
    uses = []; comparisons = 0
    for item in request['metadata']['schedule']:
        events = read(folder/item['label']/'events.json')
        cache = [event for event in events if event['phase']=='cache.use']
        if item['mode']=='R':
            if (cache or any(e['phase'].startswith(('typed.','reference.'))
                             or set(adapter.EXTRA_FIELDS).intersection(e['metadata']) for e in events)):
                raise ValueError('Reference arm borrowed typed context')
            continue
        if len(cache)!=1: raise ValueError('One typed cache use required')
        event = cache[0]; use = event['metadata']; adapter.strip_use(use)
        proof = use['typed_reference']; cold = not uses
        if set(proof)!={'authority','build','checks'} or proof['authority']!=authority:
            raise ValueError('Typed authority differs from independently rebuilt source')
        if cold:
            cold_event = next(e for e in events if e['phase']=='cache.cold_build')
            load = next(e for e in events if e['phase']=='cache.original_load_context')
            prepare = next(e for e in events if e['phase']=='cache.original_prepare_catalog')
            fingerprints = [e for e in events if e['phase']=='snapshot.fingerprint']
            if not fingerprints: raise ValueError('Cold full snapshot missing')
            build = proof['build']
            if (set(build)!={'start_ns','end_ns','roots','completed'} or build['roots']!=2
                    or build['completed'] is not True or not _interval(build,cold_event['start_ns'],load['start_ns'])):
                raise ValueError('Reference build left original charged cold boundary')
            checks = proof['checks']
            if type(checks) is not list or len(checks)!=2: raise ValueError('Two complete late checks required')
            previous = prepare['end_ns']; ceiling = fingerprints[0]['start_ns']
            for name,check in zip(('config','model'),checks):
                if (set(check)!={'root','start_ns','end_ns','completed','equal','statistics'}
                        or check['root']!=name or check['completed'] is not True or check['equal'] is not True
                        or check['statistics']!=expected_stats[name] or not _interval(check,previous,ceiling)):
                    raise ValueError('Original late complete typed order/content boundary changed')
                previous = check['end_ns']; comparisons += 1
            if not previous <= cold_event['end_ns'] <= event['start_ns']:
                raise ValueError('Typed guard left cold or moved after borrow')
        elif proof['build'] is not None or proof['checks']!=[]:
            raise ValueError('Hit unexpectedly rebuilt or reran cold typed check')
        uses.append(deepcopy(use))
    receipt = read(folder/'cache_receipt.json'); adapter.strip_summary(receipt)
    expected = dict(authority=authority, reference_builds=1, reference_roots=2,
                    late_comparisons=2, cold_calls=1, hit_calls=6)
    if (len(uses)!=7 or comparisons!=2 or receipt['typed_reference']!=expected
            or receipt['call_observations']!=uses):
        raise ValueError('Typed summary differs from full raw use evidence')
    return dict(policy=adapter.POLICY, reference_scheme=typed.SCHEME, authority=authority,
                independently_rebuilt_roots=2, cold_builds=1, late_comparisons=comparisons, hits=6,
                worker_reference_deserialized=False)


def audit_saved_runs(folder, request, observer):
    folder = Path(folder); _artificial_bundle(folder,request); proof = None
    def context(req, binding):
        nonlocal proof
        value = adapter.context_contract(req, binding)
        proof = audit_typed_runs(folder, req, value, observer)
        return value
    def legacy_read(path):
        path = Path(path); value = read(path)
        if path == folder/'cache_receipt.json': return adapter.strip_summary(value)
        if path.name=='events.json' and path.parent.parent==folder:
            value = deepcopy(value)
            for event in value:
                if event['phase']=='cache.use': event['metadata']=adapter.strip_use(event['metadata'])
        return value
    def result_write(path, value):
        if Path(path)!=folder/'audited_result.json': return write(path,value)
        if proof is None: raise ValueError('Independent typed authority was not checked')
        result = dict(value, status='v39_late_typed_independent_synthetic_audit_complete',
                      cache=read(folder/'cache_receipt.json'), typed_validation=proof,
                      evidence=common.publisher_evidence(folder))
        write(path,result)
    # Only the added typed fields are projected for the frozen old schema;
    # all raw typed fields were strictly verified above, and original source,
    # event trees, scientific frames, SQL and metrics remain independently read.
    original = _clone(s1.audit_saved_runs, context_contract=context, read=legacy_read, write=result_write)
    original(folder,request,observer)
    return read(folder/'audited_result.json')


observed_run = _clone(entry.observed_run, run_fixed48=adapter.run_fixed48)
run_worker = _clone(entry.run_worker, WorkerContext=adapter.WorkerContext,
                    observed_run=observed_run, context_contract=adapter.context_contract)
run_publisher = _clone(entry.run_publisher, audit_saved_runs=audit_saved_runs)
run_pipeline = entry.run_pipeline


def audit_completed(folder, request, expected_manifest=None):
    result, completion, exits, pub, load = entry.audit_completed(folder,request)
    adapter.require_policy(request)
    if result['status']!='v39_late_typed_independent_synthetic_audit_complete':
        raise ValueError('Independent typed publisher result required')
    proof = result['typed_validation']
    if (proof['policy']!=adapter.POLICY or proof['reference_scheme']!=typed.SCHEME
            or proof['late_comparisons']!=2 or proof['worker_reference_deserialized'] is not False
            or pub['phases']['publisher.typed_authority']['calls']!=1):
        raise ValueError('Independent typed authority proof differs')
    seal = common.closed_log_manifest(folder,request,completion,exits,expected=expected_manifest)
    return result,completion,exits,pub,load,seal


def child(folder, role):
    folder = folder_path(folder); request = read(folder/'request.json'); quiet_role(folder,request,role)
    if role=='pipeline':
        print('pipeline buffered diagnostic', file=sys.stderr)
        return run_pipeline(folder,request,{k:[sys.executable,'-B','-m',MODULE,'--'+k,str(folder)]
                                            for k in ('worker','publisher')})
    if role=='publisher': return run_publisher(folder,request)
    from tests.test_retailrocket_session_knn_reuse_acceptance_v27 import data_for
    return run_worker(folder,request,lambda:data_for(request)[1])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('pipeline','worker','publisher'): mode.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.pipeline: child(args.pipeline,'pipeline')
    elif args.worker: child(args.worker,'worker')
    else: child(args.publisher,'publisher')
