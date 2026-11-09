"""C1 real-context binding, independent audit and predeclared entry decision."""
import hashlib
import math
from pathlib import Path
from statistics import median
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,write,describe,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from scripts.run_retailrocket_session_knn_sources_v25 import child_exit,load_summary,check_observation,check_diagnostic
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_sources_v24 import StoreFactory
from scripts.retailrocket_session_knn_priority_v23 import summarize_run
from scripts.retailrocket_session_knn_reuse_v27 import digest
from scripts import retailrocket_session_knn_pair_v4 as pair

def context_contract(request,binding):
    meta=request['metadata'];context=meta['context'];sources=request['sources']
    identities={x['path']:x for x in sources}
    if len(identities)!=len(sources):raise ValueError('Duplicate closure path')
    for x in [*binding['sources'],*context['dependencies'].values(),*context['methods']]:
        if identities.get(x['path'])!=x:raise ValueError('Exact context dependency/method outside closure')
    if set(context['dependencies'])!={'counts','catalog','config','model'}:raise ValueError('Four exact context dependencies required')
    return dict(binding=binding,sources=sources,dependencies=context['dependencies'],methods=context['methods'],environment=meta['environment'])

def decision(runs):
    labels={'warm_R','warm_C'}|{f'pair_{i}_{m}' for i in range(1,7) for m in ('R','C')}
    if set(runs)!=labels:raise ValueError('All14 retained runs required for a decision')
    costs={k:v['accounting']['costs'] for k,v in runs.items()}
    for value in costs.values():
        if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) or value[k]<=0 for k in ('entry_seconds','primary_seconds')):
            raise ValueError('Finite positive original entry/primary costs required')
    pairs=[]
    for i in range(1,7):
        r,c=(costs[f'pair_{i}_{m}'] for m in ('R','C'))
        pairs.append(dict(pair=i,order='RC' if i%2 else 'CR',R_entry_seconds=r['entry_seconds'],C_entry_seconds=c['entry_seconds'],
            entry_saving_seconds=r['entry_seconds']-c['entry_seconds'],entry_saving_percent=100*(r['entry_seconds']-c['entry_seconds'])/r['entry_seconds'],
            primary_regression_percent=100*(c['primary_seconds']-r['primary_seconds'])/r['primary_seconds']))
    order={o:median(p['entry_saving_seconds'] for p in pairs if p['order']==o) for o in ('RC','CR')}
    totals={m:math.fsum(v['entry_seconds'] for k,v in costs.items() if k.endswith('_'+m)) for m in ('R','C')}
    wins=sum(p['entry_saving_seconds']>0 for p in pairs);saving=median(p['entry_saving_percent'] for p in pairs)
    regression=median(p['primary_regression_percent'] for p in pairs)
    gates=dict(five_positive_pairs=wins>=5,median_entry_saving_at_least_five_percent=saving>=5,
        both_orders_positive=min(order.values())>0,cold_inclusive_seven_C_less_than_R=totals['C']<totals['R'],primary_regression_at_most_five_percent=regression<=5)
    return dict(pairs=pairs,faster_pairs=wins,median_entry_saving_percent=saving,order_median_saving_seconds=order,
        all7_entry_seconds=totals,median_primary_regression_percent=regression,gates=gates,adopted=all(gates.values()),
        interpretation='Engineering original48 screening only; all source/scientific/safety validation must already have passed. Historical V25 RD is not the reference.')

def audit_saved_runs(folder,request,observer):
    """No snapshot parameter or worker object. Real activation still needs its own entry gate."""
    folder=Path(folder);meta=request['metadata'];cohort=meta['cohort']
    child_exit(folder,request,'worker')
    schedule=meta['schedule']
    expected=[dict(label='warm_'+m,mode=m) for m in ('R','C')]+[
        dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')]
    if schedule!=expected or read(folder/'worker_done.json')!=dict(runs=14,queries_per_run=48,checks=672,completed=True):
        raise ValueError('Complete retained balanced C1 schedule required')
    watch=ThrottledWatch(folder,request['deadline_utc'])
    with observer.span('publisher.initial_hash'):observer.verify_bindings(request['sources'],watch)
    binding=read(ROOT/cohort['old_run'])['binding'];probes=read(ROOT/cohort['probes'])['probes'];reference=read(ROOT/cohort['reference'])
    frames=list(_physical_frames((ROOT/cohort['old_run']).parent));payload=b''.join(frames)
    if len(frames)!=48 or len(payload)!=reference['actual_committed_bytes'] or hashlib.sha256(payload).hexdigest()!=reference['actual_committed_payload_sha256']:
        raise ValueError('Original physical reference differs')
    for phase in ('worker_initial_hash','worker_final_hash'):
        events,summary=check_observation(folder/phase)
        if [e['metadata']['descriptor'] for e in events if e['phase']=='closure.descriptor']!=request['sources']:
            raise ValueError('Worker full source coverage differs')
    # Rebuild independently from bound raw sources, never deserialize a worker context.
    contract=context_contract(request,binding)
    selected=ROOT/cohort['selected_root'];config=read(selected/'configuration.json')
    model=read(ROOT/contract['dependencies']['model']['path'])['receipt']
    paths={k:selected/k for k in ('dataset','P0','C1','D1')}
    with observer.span('publisher.independent_context'):
        counts,catalog=pair.core.load_context(paths,config,model['support'],watch)
        prepared=pair.sql.prepare_catalog(catalog,counts,watch)
        expected_digest=digest(dict(first=prepared.first,counts=prepared.counts,first_times=prepared.first_times,fallback=prepared.fallback))
    runs={};previous=None;workload=None;uses=[];factory=StoreFactory(observer)
    method_bytes=sum(x['bytes'] for x in contract['methods'])
    for item in schedule:
        watch.force();label,mode=item['label'],item['mode'];root=folder/label
        run=read(root/'verified_subset/run.json')
        if (run['binding']!=binding or run['expected_queries']!=48 or any(run[k]!=request[k] for k in ('budget_seconds','deadline_utc'))):
            raise ValueError('Run identity changed')
        with observer.span('publisher.open_and_proof'):
            store=factory.open(root/'verified_subset',binding,source_root=ROOT)
            proof=observer.call('publisher.ledger_proof',ledger_proof,store,probes)
            if proof!=read(root/'proof.json') or list(_physical_frames(root/'verified_subset'))!=frames:
                raise ValueError('Complete scientific payload/proof differs')
        measured,raw,entry=(read(root/p) for p in ('measured.json','observations.json','entry.json'))
        if entry['label']!=label or entry['mode']!='baseline' or read(root/'profile.json'):
            raise ValueError('Original entry/method identity changed')
        accounting=summarize_run(measured,raw,entry,probes)
        current=[x['sql_workload'] for x in measured['queries']]
        if workload is not None and current!=workload:raise ValueError('SQL logical workload changed')
        workload=current
        load,previous=load_summary(root,request,label,mode,previous)
        diagnostic=check_diagnostic(root,binding,measured);events=read(root/'events.json')
        cache=[e['metadata'] for e in events if e['phase']=='cache.use']
        if mode=='R' and (cache or any(e['phase'].startswith('cache.') for e in events)):
            raise ValueError('Reference borrowed candidate cache')
        if mode=='C':
            if len(cache)!=1:raise ValueError('Exactly one candidate context borrow required')
            use=cache[0];cold=not uses
            expected_use=dict(cold=cold,hit=not cold,
                buffer_logical_bytes=sum(v['bytes'] for v in contract['dependencies'].values()) if cold else 0,
                context_source_logical_bytes=sum(contract['dependencies'][n]['bytes'] for n in ('counts','catalog')) if cold else 0,
                method_logical_bytes=method_bytes,method_verifications=len(contract['methods']),snapshot_digest=expected_digest,
                catalog_rows=len(prepared.first),count_rows=len(prepared.counts))
            if use!=expected_use:raise ValueError('Cache use differs from independently rebuilt context')
            phases=diagnostic['phases']
            for name in ('cache.identity','cache.pre_use_digest','cache.final_guard','cache.use'):
                if phases.get(name,{}).get('calls')!=1:raise ValueError('Cache guard count differs')
            for name in ('cache.cold_build','cache.original_load_context','cache.original_prepare_catalog'):
                if phases.get(name,{}).get('calls',0)!=int(cold):raise ValueError('Cache build count differs')
            setup=next(e for e in events if e['phase']=='verifier.setup_envelope')
            finish=next(e for e in events if e['phase']=='cache.final_guard')
            if setup['end_ns']>finish['start_ns']:raise ValueError('Final guard overlaps original setup')
            uses.append(use)
        runs[label]=dict(mode=mode,accounting=accounting,diagnostic=diagnostic,load=load)
    receipt=read(folder/'cache_receipt.json')
    expected_receipt=dict(candidate_runs=7,cold_builds=1,hits=6,
        buffer_logical_bytes=sum(x['buffer_logical_bytes'] for x in uses),
        context_source_logical_bytes=sum(x['context_source_logical_bytes'] for x in uses),call_observations=uses)
    if receipt!=expected_receipt:raise ValueError('Worker cache receipt differs from raw audited events')
    with observer.span('publisher.final_hash'):observer.verify_bindings(request['sources'],watch)
    if check_gates()!=meta['gates']:raise ValueError('Scientific gates changed')
    result=dict(status='v28_C1_independent_real_audit_complete',runs=runs,reference=reference,cache=receipt,
        source_checks='Both full closure passes and all14 original store.open binding checks completed.',
        evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file() and p.name not in ('publisher.log',)])
    result['decision']=decision(runs)
    observer.call('publisher.result_write',write,folder/'audited_result.json',result)
    return result
