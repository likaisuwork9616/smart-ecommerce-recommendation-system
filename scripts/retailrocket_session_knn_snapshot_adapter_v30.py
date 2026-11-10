"""C1-S1 adapters over frozen C1/entry bytecode; no real-measurement CLI."""
import hashlib
from pathlib import Path
from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_compare_v28 as old_audit
from scripts import run_retailrocket_session_knn_compare_v28 as entry
from scripts.retailrocket_session_knn_snapshot_v30 import SCHEME,fingerprint
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,write,describe,check_gates
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from scripts.run_retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.run_retailrocket_session_knn_sources_v25 import child_exit,load_summary,check_observation,check_diagnostic
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_sources_v24 import StoreFactory
from scripts.retailrocket_session_knn_priority_v23 import summarize_run
from scripts import retailrocket_session_knn_pair_v4 as pair

decision=old_audit.decision

def require_scheme(request):
    value=request.get('metadata',{}).get('fingerprint_scheme')
    if type(value) is not str or value!=SCHEME:
        raise ValueError('Exact C1-S1 request fingerprint scheme required')

def context_contract(request,binding):
    require_scheme(request)
    return old_audit.context_contract(request,binding)

class WorkerContext(c1.WorkerContext):
    def _identity(self,store,config,model,namespace,request,observer,watch):
        try:
            require_scheme(request)
            self._s1_request=request;self._s1_observer=observer;self._s1_watch=watch
            return super()._identity(store,config,model,namespace,request,observer,watch)
        except BaseException:
            self.invalidate();raise

    def _snapshot_digest(self):
        require_scheme(self._s1_request)
        return fingerprint(self.prepared,self._s1_observer,self._s1_watch)

    def load(self,paths,config,support,watch,*,model,store,namespace,request,observer):
        try:
            require_scheme(request);first=len(observer.events)
            result=super().load(paths,config,support,watch,model=model,store=store,namespace=namespace,request=request,observer=observer)
            uses=[event for event in observer.events[first:] if event['phase']=='cache.use']
            if len(uses)!=1 or uses[0]['metadata']!=self.calls[-1]:raise ValueError('Original cache use evidence differs')
            self.calls[-1]['fingerprint_scheme']=SCHEME
            uses[0]['metadata']['fingerprint_scheme']=SCHEME
            return result
        except BaseException:
            self.invalidate();raise

    def finish(self,observer,watch):
        try:
            require_scheme(self._s1_request)
            self._s1_observer=observer;self._s1_watch=watch
            return super().finish(observer,watch)
        except BaseException:
            self.invalidate();raise

    def completed_summary(self):
        result=super().completed_summary();require_scheme(self._s1_request)
        if any(row.get('fingerprint_scheme')!=SCHEME for row in result['call_observations']):
            raise ValueError('Mixed scheme in complete context receipt')
        return dict(result,fingerprint_scheme=SCHEME)

make_verifier=c1.make_verifier

def run_fixed48(folder,request,label,mode,data,*,observer,pool=None,source_root=ROOT,watch=lambda:None):
    try:
        require_scheme(request)
        return c1.run_fixed48(folder,request,label,mode,data,observer=observer,pool=pool,source_root=source_root,watch=watch)
    except BaseException:
        if pool is not None:pool.invalidate()
        raise

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
        expected_digest=fingerprint(prepared,observer,watch)
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
            expected_use=dict(fingerprint_scheme=SCHEME,cold=cold,hit=not cold,
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
            fingerprint_count=3 if cold else 2
            for name in ('snapshot.fingerprint','snapshot.validation','snapshot.json','snapshot.utf8','snapshot.sha256'):
                if phases.get(name,{}).get('calls')!=fingerprint_count:raise ValueError('Complete snapshot phase count changed')
            if phases.get('snapshot.release',{}).get('calls')!=2*fingerprint_count:raise ValueError('Snapshot release count changed')
            owners=[]
            for event in events:
                if event['phase'].startswith('snapshot.') and event['metadata'].get('scheme')!=SCHEME:
                    raise ValueError('Snapshot phase scheme changed')
                if event['phase']=='snapshot.fingerprint':
                    parent=event['parent'];ancestors=[]
                    while parent is not None:
                        ancestors.append(events[parent]['phase']);parent=events[parent]['parent']
                    owner=[name for name in ('cache.cold_build','cache.pre_use_digest','cache.final_guard') if name in ancestors]
                    if len(owner)!=1:raise ValueError('Live snapshot check left its original integrity boundary')
                    owners.extend(owner)
            if owners.count('cache.cold_build')!=int(cold) or owners.count('cache.pre_use_digest')!=1 or owners.count('cache.final_guard')!=1:
                raise ValueError('Cold/pre/post live checks changed')
            setup=next(e for e in events if e['phase']=='verifier.setup_envelope')
            finish=next(e for e in events if e['phase']=='cache.final_guard')
            if setup['end_ns']>finish['start_ns']:raise ValueError('Final guard overlaps original setup')
            uses.append(use)
        runs[label]=dict(mode=mode,accounting=accounting,diagnostic=diagnostic,load=load)
    receipt=read(folder/'cache_receipt.json')
    expected_receipt=dict(fingerprint_scheme=SCHEME,candidate_runs=7,cold_builds=1,hits=6,
        buffer_logical_bytes=sum(x['buffer_logical_bytes'] for x in uses),
        context_source_logical_bytes=sum(x['context_source_logical_bytes'] for x in uses),call_observations=uses)
    if receipt!=expected_receipt:raise ValueError('Worker cache receipt differs from raw audited events')
    with observer.span('publisher.final_hash'):observer.verify_bindings(request['sources'],watch)
    if check_gates()!=meta['gates']:raise ValueError('Scientific gates changed')
    result=dict(status='v30_C1_S1_independent_synthetic_audit_complete',runs=runs,reference=reference,cache=receipt,
        source_checks='Both full closure passes and all14 original store.open binding checks completed.',
        evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file() and p.name not in ('publisher.log',)])
    result['decision']=decision(runs)
    observer.call('publisher.result_write',write,folder/'audited_result.json',result)
    return result

# Each clone receives an invocation-local global dictionary. Frozen modules stay unchanged.
observed_run=_clone(entry.observed_run,run_fixed48=run_fixed48)
run_worker=_clone(entry.run_worker,WorkerContext=WorkerContext,observed_run=observed_run,context_contract=context_contract)
run_publisher=_clone(entry.run_publisher,audit_saved_runs=audit_saved_runs)
run_pipeline=entry.run_pipeline

def audit_completed(folder,request):
    require_scheme(request)
    return entry.audit_completed(folder,request)
