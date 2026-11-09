"""One accepted C1 original48 window: supervised worker, independent publisher, sealed release."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import sys
from time import perf_counter
import unittest
from uuid import uuid4
import psutil

from scripts import run_retailrocket_session_knn_sources_v25 as old
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,write,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json,_check_db
from scripts.retailrocket_session_knn_checkpoint_v2 import _lock
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_checks_v4 import clear_caches
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.retailrocket_session_knn_reuse_v27 import WorkerContext,run_fixed48
from scripts.retailrocket_session_knn_compare_v28 import context_contract,audit_saved_runs,decision
from scripts.retailrocket_session_knn_reinforcement_v18 import TelemetrySampler
from scripts.accept_retailrocket_session_knn_reuse_v27 import SUITES as CORE_SUITES

MODULE='scripts.run_retailrocket_session_knn_compare_v28'
BASE='reports/stage12/retailrocket_session_knn_v28_compare_'
SPEC=BASE+'specification_20261109.json';ACCEPT=BASE+'acceptance_20261109.json'
REPORT=BASE+'cost_20261109.json';RELEASE=BASE+'release_20261109.json'
SPEC_SHA='d20cb80317b2a1eef358a51f421ae671f2f1f5895112b6f6b912050c61549557'
METHODS=('scripts/run_retailrocket_session_knn_compare_v28.py','scripts/retailrocket_session_knn_compare_v28.py','tests/test_retailrocket_session_knn_compare_v28.py')
SUITES=('tests.test_retailrocket_session_knn_compare_v28',*CORE_SUITES)


def specification():
    spec=read(ROOT/SPEC)
    if (describe(ROOT/SPEC)['sha256']!=SPEC_SHA or spec['status']!='v28_C1_original48_real_entry_specification_frozen'
            or spec['activation']['authorized_real_runs']!=14 or spec['activation']['queries_per_run']!=48
            or spec['budget_seconds']!=1800 or spec['limits']!=LIMITS):raise ValueError('Expected the sealed real C1 activation')
    verify_bindings(spec['evidence'])
    parent=read(ROOT/spec['parent_specification']['path'])
    for a,b in (('cohort','cohort'),('inherited_sources','inherited_sources'),('original_binding_sources','original_binding_sources')):
        if spec[a]!=parent[b]:raise ValueError('Original source/cohort identities changed')
    if spec['schedule']!=parent['future_comparison']['schedule'] or spec['decision']!=parent['future_comparison']['decision']:
        raise ValueError('Original schedule/adoption gates changed')
    if spec['environment']!=environment() or spec['gates']!=check_gates():raise ValueError('Environment/scientific gates changed')
    return spec


@contextmanager
def exclusive():
    PRIVATE.mkdir(parents=True,exist_ok=True)
    with (PRIVATE/'knn-v28-c1.guard').open('a+b') as guard:
        if guard.seek(0,2)==0:guard.write(b'0');guard.flush()
        _lock(guard);yield


def acceptance():
    with exclusive():
        if (ROOT/ACCEPT).exists():raise FileExistsError('Immutable real-entry acceptance already exists')
        spec=specification();methods=[describe(ROOT/p) for p in METHODS]
        folder=PRIVATE/('knn-v28-c1-tests-'+uuid4().hex);folder.mkdir();start=perf_counter()
        with (folder/'tests.log').open('x',encoding='utf-8') as log:
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-10000:]);raise ValueError('V28 integration acceptance failed')
        verify_bindings(methods)
        if specification()!=spec:raise ValueError('Sealed sources changed during acceptance')
        from tests import test_retailrocket_session_knn_compare_v28 as fixture
        evidence=[describe(p) for p in sorted(fixture.IntegratedTests.folder.rglob('*')) if p.is_file()]
        report=dict(status='v28_C1_real_entry_synthetic_accepted',tests_run=result.testsRun,failures=0,errors=0,skipped=0,
            seconds=perf_counter()-start,suites=list(SUITES),methods=methods,log=describe(folder/'tests.log'),
            specification=describe(ROOT/SPEC),environment=environment(),gates=spec['gates'],synthetic_evidence=evidence,
            real_runs=0,created_utc=datetime.now(timezone.utc).isoformat())
        public_json(ROOT/ACCEPT,report,exclusive=True);print(dict(tests=result.testsRun,real_runs=0,seconds=report['seconds']))


def source_contract():
    spec=specification();accepted=read(ROOT/ACCEPT)
    if (accepted['status']!='v28_C1_real_entry_synthetic_accepted' or accepted['specification']!=describe(ROOT/SPEC)
            or accepted['suites']!=list(SUITES) or {x['path'] for x in accepted['methods']}!=set(METHODS)
            or any(accepted[k]!=0 for k in ('failures','errors','skipped','real_runs'))
            or accepted['tests_run']<=0 or accepted['environment']!=environment() or accepted['gates']!=spec['gates']):
        raise ValueError('Unchanged real entry must pass synthetic acceptance')
    verify_bindings([*accepted['methods'],accepted['log'],*accepted['synthetic_evidence']])
    records={}
    for x in [*spec['inherited_sources'],*spec['evidence'],*accepted['methods'],accepted['log'],
              *accepted['synthetic_evidence'],describe(ROOT/SPEC),describe(ROOT/ACCEPT)]:
        if records.get(x['path'],x)!=x:raise ValueError('Conflicting source identity')
        records[x['path']]=x
    core=read(ROOT/spec['parent_acceptance']['path'])
    methods={x['path']:x for x in [*spec['original_semantic_methods'],*core['methods'],*accepted['methods']]}
    dependencies=dict(zip(('counts','catalog','config','model'),spec['context_inputs']))
    meta=dict(cohort=spec['cohort'],schedule=spec['schedule'],context=dict(dependencies=dependencies,methods=[methods[k] for k in sorted(methods)]),
        environment=environment(),gates=spec['gates'],specification=describe(ROOT/SPEC),acceptance=describe(ROOT/ACCEPT))
    binding=read(ROOT/meta['cohort']['old_run'])['binding']
    if binding['sources']!=spec['original_binding_sources']:raise ValueError('Original15 binding changed')
    result=[records[k] for k in sorted(records)];context_contract(dict(sources=result,metadata=meta),binding)
    return result,meta


def contract(request):
    old._check_window(request);records,meta=source_contract()
    if request['sources']!=records or request['metadata']!=meta:raise ValueError('Real request differs from the accepted frozen contract')
    return meta


def folder_path(folder):
    folder=Path(folder).resolve()
    if folder.parent!=PRIVATE.resolve() or not folder.name.startswith('knn-v28-c1-'):raise ValueError('Expected original real-window namespace')
    return folder


def observed_run(folder,request,item,data,pool,watch):
    root=folder/item['label'];root.mkdir();obs=Observation();sampler=TelemetrySampler();sampler.start(0)
    span=dict(label=item['label'],mode=item['mode'],repeat_index=0,completed=False,
        start_monotonic_seconds=perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:
        run_fixed48(folder,request,item['label'],item['mode'],data,observer=obs,pool=pool,source_root=ROOT,watch=watch)
        span['completed']=True
    finally:
        span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        try:sampler.stop()
        finally:
            write(root/'entry_span.json',span);write(root/'telemetry_records.json',dict(label=item['label'],mode=item['mode'],records=sampler.records))
            old.save_observation(root,obs)


def run_worker(folder,request,data):
    watch=ThrottledWatch(folder,request['deadline_utc']);pool=None
    try:
        old.hash_phase(folder,request,'worker_initial_hash',watch)
        data=data() if callable(data) else data
        pool=WorkerContext(context_contract(request,data[2]),ROOT,ROOT);clear_caches()
        for item in request['metadata']['schedule']:
            watch.force();write(folder/(item['label']+'_started.json'),item)
            observed_run(folder,request,item,data,pool,watch);_check_db(data[4]);watch.force()
        write(folder/'cache_receipt.json',pool.completed_summary());pool.close()
        old.hash_phase(folder,request,'worker_final_hash',watch);write(folder/'worker_done.json',old.DONE)
    except BaseException as error:
        write(folder/'worker_failure.json',dict(error_type=type(error).__name__));raise
    finally:
        if pool is not None:pool.close()


def worker(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request)
    return run_worker(folder,request,lambda:old.inputs(request))


def run_publisher(folder,request):
    (folder/'publisher').mkdir();obs=Observation();sampler=TelemetrySampler();sampler.start(0)
    span=dict(label='publisher',mode='publisher',repeat_index=0,completed=False,
        start_monotonic_seconds=perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:
        obs.publisher(audit_saved_runs,folder,request,obs);span['completed']=True
    finally:
        span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        try:sampler.stop()
        finally:
            write(folder/'publisher/entry_span.json',span);write(folder/'publisher/telemetry_records.json',dict(label='publisher',mode='publisher',records=sampler.records))
            old.save_observation(folder/'publisher',obs)


def publisher(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request);run_publisher(folder,request)


def run_pipeline(folder,request,commands):
    try:
        for kind in ('worker','publisher'):old.run_child(folder,request,kind,commands[kind])
        write(folder/'pipeline_done.json',dict(completed=True))
    except BaseException as error:
        write(folder/'pipeline_failure.json',dict(error_type=type(error).__name__));raise


def pipeline(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request)
    run_pipeline(folder,request,{k:[sys.executable,'-B','-m',MODULE,'--'+k,str(folder)] for k in ('worker','publisher')})


def audit_completed(folder,request):
    completion=read(folder/'supervisor_completion.json');old._check_window(request,completion)
    if read(folder/'pipeline_done.json')!={'completed':True}:raise ValueError('Pipeline incomplete')
    exits={k:old.child_exit(folder,request,k) for k in ('worker','publisher')}
    if exits['worker']['ended_utc']>exits['publisher']['started_utc']:raise ValueError('Worker/publisher overlap')
    verify_bindings(exits['publisher']['outputs']);result=read(folder/'audited_result.json');verify_bindings(result['evidence'])
    events,pub=old.check_observation(folder/'publisher');load,_=old.load_summary(folder/'publisher',request,'publisher','publisher')
    binding=read(ROOT/request['metadata']['cohort']['old_run'])['binding']
    if pub['source_descriptors']['completed_calls']!=2*len(request['sources'])+14*len(binding['sources']):raise ValueError('Publisher source call coverage changed')
    if [x['metadata']['descriptor'] for x in events if x['phase']=='closure.descriptor']!=request['sources']*2:raise ValueError('Publisher full closure changed')
    for phase in ('worker_initial_hash','worker_final_hash'):old.check_observation(folder/phase)
    previous=None
    for item in request['metadata']['schedule']:
        root=folder/item['label'];old.check_diagnostic(root,binding,read(root/'measured.json'))
        _,previous=old.load_summary(root,request,item['label'],item['mode'],previous)
    if result['decision']!=decision(result['runs']) or result['cache']!=read(folder/'cache_receipt.json'):raise ValueError('Post-exit result differs')
    for identity in read(folder/'tracked_process_identities.json')['identities']:
        try:
            p=psutil.Process(identity['pid'])
            if p.is_running() and p.create_time()==identity['create_time']:raise ValueError('Tracked process is still alive')
        except psutil.NoSuchProcess:pass
    return result,completion,exits,pub,load


def release(folder):
    folder=folder_path(folder);request=read(folder/'request.json');meta=contract(request)
    result,completion,exits,pub,load=audit_completed(folder,request)
    report=dict(status='v28_C1_original48_real_comparison_measured',namespace=folder.relative_to(ROOT).as_posix(),
        specification=meta['specification'],acceptance=meta['acceptance'],schedule=meta['schedule'],supervisor=completion,
        results=result,decision=result['decision'],publisher_observation=pub,publisher_load=load,
        worker_source_observations={p:read(folder/p/'observation.json') for p in ('worker_initial_hash','worker_final_hash')},
        process_wall_seconds={k:v['seconds'] for k,v in exits.items()},gates=check_gates(),
        scope=dict(real_runs=14,engineering_checks=672,new_keys=0,new_real_fit_validation_bootstrap=0,
            full_validation_complete=False,reserved_test='locked'),T_plan=None,
        evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()],
        interpretation='Known-validation engineering comparison; all warmups retained in cold-inclusive sums. Not a population or reserved-test score. No Ollama token/GPU speed measurement.')
    if report['gates']!=meta['gates']:raise ValueError('Scientific gates changed after completion')
    if (ROOT/REPORT).exists():
        existing=read(ROOT/REPORT);verify_bindings(existing['evidence'])
        if existing!=report:raise ValueError('Immutable report differs from re-audit')
    else:
        start=perf_counter();public_json(ROOT/REPORT,report,exclusive=True)
        public_json(ROOT/RELEASE,dict(status='v28_C1_public_report_released',report=describe(ROOT/REPORT),
            public_serialization_seconds=perf_counter()-start,deadline_utc=request['deadline_utc']),exclusive=True)
    print(dict(report=REPORT,seconds=completion['seconds'],checks=672,adopted=report['decision']['adopted']))
    return report


def measure():
    with exclusive():
        if (ROOT/REPORT).exists():raise FileExistsError('Use --release for the completed window')
        for p in PRIVATE.glob('knn-v28-c1-*/request.json'):raise FileExistsError('Existing window forbids automatic retry: '+str(p.parent))
        sources,meta=source_contract();folder=PRIVATE/('knn-v28-c1-'+uuid4().hex)
        print('V28 supervised namespace: '+folder.relative_to(ROOT).as_posix(),flush=True)
        run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],sources,'joint_tail',metadata=meta,budget_seconds=1800,limits=LIMITS)
        return release(folder)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance',action='store_true');mode.add_argument('--measure',action='store_true')
    for name in ('pipeline','worker','publisher','release'):mode.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.acceptance:acceptance()
    elif args.measure:measure()
    elif args.pipeline:pipeline(args.pipeline)
    elif args.worker:worker(args.worker)
    elif args.publisher:publisher(args.publisher)
    else:
        with exclusive():release(args.release)
