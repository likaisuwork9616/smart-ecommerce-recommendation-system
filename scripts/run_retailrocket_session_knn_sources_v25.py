"""One supervised original48 R/D window followed by an independent publisher."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import unittest
from uuid import uuid4

import psutil

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, write, describe, verify_bindings, environment, check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json, _check_db
from scripts.retailrocket_session_knn_checkpoint_v2 import _lock
from scripts.retailrocket_session_knn_cost_window_v5 import run_window, LIMITS
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_checks_v4 import clear_caches
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_sources_v24 import Observation, StoreFactory, run_fixed48, summarize_events
from scripts.retailrocket_session_knn_reinforcement_v18 import TelemetrySampler, summarize_telemetry
from scripts.run_retailrocket_session_knn_tail_v19 import _check_telemetry_span
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from scripts.run_retailrocket_session_knn_overlap_v22 import _check_window
from scripts.retailrocket_session_knn_priority_v23 import summarize_run

MODULE = 'scripts.run_retailrocket_session_knn_sources_v25'
BASE = 'reports/stage12/retailrocket_session_knn_v25_sources_'
SPEC = BASE+'specification_20261109.json'
SPEC_SHA = 'eafa94e7f5ff58cb6f3e6eb9f431bcf84da9553404a1bdbbf5a8d3f8191fdfa1'
ACCEPT = BASE+'acceptance_20261109.json'
REPORT = BASE+'cost_20261109.json'
RELEASE = BASE+'release_20261109.json'
METHODS = ('scripts/run_retailrocket_session_knn_sources_v25.py',
           'tests/test_retailrocket_session_knn_sources_v25.py')
SUITES = ('tests.test_retailrocket_session_knn_sources_v25',
          'tests.test_retailrocket_session_knn_sources_v24',
          'tests.test_retailrocket_session_knn_detailed_cost_v6',
          'tests.test_retailrocket_session_knn_priority_v23')
DONE = dict(runs=14, queries_per_run=48, checks=672, completed=True)


def specification():
    spec = read(ROOT/SPEC)
    if (describe(ROOT/SPEC)['sha256'] != SPEC_SHA
            or spec['status'] != 'v25_sources_integrated_measurement_specification_frozen'
            or spec['budget_seconds'] != 1800 or spec['limits'] != LIMITS
            or spec['scope']['authorized_real_runs'] != 14
            or spec['scope']['queries_per_run'] != 48):
        raise ValueError('Expected the sealed integrated original48 specification')
    verify_bindings(spec['evidence'])
    parent = read(ROOT/spec['parent_specification']['path'])
    if spec['schedule'] != parent['measurement_plan']['schedule'] or spec['cohort'] != parent['cohort']:
        raise ValueError('The original48 or RD/DR schedule changed')
    if spec['environment'] != environment() or spec['gates'] != check_gates():
        raise ValueError('Frozen environment or gates changed')
    return spec


@contextmanager
def exclusive():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE/'knn-v25-sources.guard').open('a+b') as guard:
        if guard.seek(0,2) == 0:
            guard.write(b'0');guard.flush()
        _lock(guard)
        yield


def acceptance():
    with exclusive():
        if (ROOT/ACCEPT).exists():
            raise FileExistsError('An immutable integrated acceptance already exists')
        spec = specification()
        methods = [describe(ROOT/name) for name in METHODS]
        folder = PRIVATE/('knn-v25-sources-tests-'+uuid4().hex)
        folder.mkdir()
        start = perf_counter()
        with (folder/'tests.log').open('x', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.testsRun or not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-9000:], file=sys.stderr)
            raise ValueError('Integrated worker/publisher synthetic acceptance failed')
        verify_bindings(methods)
        if specification() != spec:
            raise ValueError('Sources changed during integrated acceptance')
        report = dict(status='v25_sources_integrated_tools_synthetic_accepted',
            created_utc=datetime.now(timezone.utc).isoformat(), tests_run=result.testsRun,
            failures=0, errors=0, skipped=0, seconds=perf_counter()-start, suites=list(SUITES),
            methods=methods, log=describe(folder/'tests.log'), specification=describe(ROOT/SPEC),
            environment=environment(), gates=spec['gates'], real_rankings=0, real_windows=0)
        public_json(ROOT/ACCEPT, report, exclusive=True)
        print({'tests':result.testsRun, 'seconds':report['seconds'], 'real_windows':0})


def accepted(spec):
    report = read(ROOT/ACCEPT)
    if (report['status'] != 'v25_sources_integrated_tools_synthetic_accepted'
            or report['specification'] != describe(ROOT/SPEC) or report['suites'] != list(SUITES)
            or {x['path'] for x in report['methods']} != set(METHODS)
            or len(report['methods']) != len(METHODS) or report['tests_run'] <= 0
            or any(report[k] != 0 for k in ('failures','errors','skipped','real_rankings','real_windows'))
            or report['environment'] != environment() or report['gates'] != spec['gates']):
        raise ValueError('Unchanged integrated methods must pass acceptance')
    verify_bindings([*report['methods'],report['log']])
    return report


def source_contract():
    spec = specification(); tools = accepted(spec)
    records = {x['path']:x for x in spec['inherited_sources']}
    for x in [*spec['evidence'],*tools['methods'],tools['log'],describe(ROOT/SPEC),describe(ROOT/ACCEPT)]:
        if records.get(x['path'],x) != x:
            raise ValueError('Conflicting sealed source identity')
        records[x['path']] = x
    meta = dict(cohort=spec['cohort'],schedule=spec['schedule'],environment=environment(),
                specification=describe(ROOT/SPEC),acceptance=describe(ROOT/ACCEPT),gates=spec['gates'])
    for key in ('old_run','reference','probes'):
        if meta['cohort'][key] not in records:
            raise ValueError('Original cohort is outside the source closure')
    for x in read(ROOT/meta['cohort']['old_run'])['binding']['sources']:
        if records.get(x['path']) != x:
            raise ValueError('Original model/input binding is outside the closure')
    return [records[k] for k in sorted(records)], meta


def contract(request):
    _check_window(request)
    records, meta = source_contract()
    if request['sources'] != records or request['metadata'] != meta:
        raise ValueError('Request differs from accepted original48 sources/schedule')
    return meta


def folder_path(folder):
    folder = Path(folder).resolve()
    if folder.parent != PRIVATE.resolve() or not folder.name.startswith('knn-v25-sources-'):
        raise ValueError('Expected the one private integrated namespace')
    return folder


def inputs(request):
    c = request['metadata']['cohort']
    selected = ROOT/c['selected_root']; config = read(selected/'configuration.json')
    binding = read(ROOT/c['old_run'])['binding']; probes = read(ROOT/c['probes'])['probes']
    ordinals = read(selected/'ordinals.json')
    if (len(probes) != 48 or len(ordinals) != 48 or config['fixed_validation']['queries'] != 48
            or any(p['key'] != q['key'] or p['original_ordinal'] != q['original_ordinal']
                   or q['subset_ordinal'] != i for i,(p,q) in enumerate(zip(probes,ordinals)))):
        raise ValueError('Fixed48 identities/order differ')
    model_root = ROOT/c['model_root']; database = model_root/'independent.sqlite';_check_db(database)
    model = read(model_root/'reconstruction.json')['receipt']
    return selected,config,binding,model,database,probes,ordinals,read(ROOT/c['reference'])


def save_observation(root, observer):
    root.mkdir(parents=True,exist_ok=True)
    write(root/'events.json', observer.events)
    write(root/'observation.json', observer.summary())


def hash_phase(folder, request, name, watch):
    obs = Observation()
    try:
        with obs.span(name):
            obs.verify_bindings(request['sources'], watch)
            if check_gates() != request['metadata']['gates']:
                raise ValueError('Scientific gates changed')
    finally:
        save_observation(folder/name, obs)


def observed_run(folder, request, item, data, watch):
    label, mode = item['label'],item['mode']; root=folder/label
    root.mkdir(parents=True,exist_ok=True)
    obs = Observation() if mode == 'D' else None
    sampler=TelemetrySampler(interval_seconds=.2,process_name_prefix='ollama');sampler.start(0)
    span=dict(label=label,mode=mode,repeat_index=0,completed=False,
        start_monotonic_seconds=perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:
        run_fixed48(folder,request,label,data,observer=obs,source_root=ROOT,watch=watch)
        span['completed']=True
    finally:
        span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        try: sampler.stop()
        finally:
            write(root/'entry_span.json',span)
            write(root/'telemetry_records.json',dict(label=label,mode=mode,records=sampler.records))
            if obs is not None: save_observation(root,obs)


def load_summary(root,request,label,mode,previous=None):
    raw,span=read(root/'telemetry_records.json'),read(root/'entry_span.json')
    if any(x.get('label')!=label or x.get('mode')!=mode for x in (raw,span)):
        raise ValueError('Telemetry run identity changed')
    _check_telemetry_span(raw['records'],span,request,0)
    if previous is not None and raw['records'][0]['monotonic_seconds']<previous:
        raise ValueError('Sequential telemetry intervals overlap')
    summary=summarize_telemetry(raw['records'],0,interval_seconds=.2)
    end=raw['records'][-1]['monotonic_seconds']+raw['records'][-1]['collector_seconds']
    return summary,end


def worker(folder):
    folder=folder_path(folder);request=read(folder/'request.json');meta=contract(request)
    watch=ThrottledWatch(folder,request['deadline_utc'])
    try:
        hash_phase(folder,request,'worker_initial_hash',watch)
        data=inputs(request);clear_caches()
        for item in meta['schedule']:
            watch.force();write(folder/(item['label']+'_started.json'),item)
            observed_run(folder,request,item,data,watch)
            _check_db(data[4]);watch.force()
        hash_phase(folder,request,'worker_final_hash',watch)
        write(folder/'worker_done.json',DONE)
    except BaseException as error:
        write(folder/'worker_failure.json',dict(error_type=type(error).__name__,reserved_test='locked'))
        raise


def child_exit(folder,request,kind):
    value=read(folder/(kind+'_exit.json'))
    start,end=(datetime.fromisoformat(value[k]) for k in ('started_utc','ended_utc'))
    if (value['kind']!=kind or value['returncode']!=0 or not
            datetime.fromisoformat(request['created_utc'])<=start<=end<=datetime.fromisoformat(request['deadline_utc'])):
        raise ValueError('A normal child exit under the original deadline is required')
    try:
        p=psutil.Process(value['pid'])
        if value['create_time'] is not None and p.is_running() and p.create_time()==value['create_time']:
            raise ValueError('A completed child identity is still running')
    except psutil.NoSuchProcess: pass
    return value


def run_child(folder,request,kind,command=None):
    watch=ThrottledWatch(folder,request['deadline_utc']);watch.force()
    started=datetime.now(timezone.utc).isoformat();start=perf_counter()
    command=command or [sys.executable,'-B','-m',MODULE,'--'+kind,str(folder)]
    with (folder/(kind+'.log')).open('xb') as log:
        p=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try: created=psutil.Process(p.pid).create_time()
        except psutil.NoSuchProcess: created=None
        try:
            remaining=(datetime.fromisoformat(request['deadline_utc'])-datetime.now(timezone.utc)).total_seconds()
            code=p.wait(timeout=max(.001,remaining))
        except subprocess.TimeoutExpired:
            p.kill();p.wait();code=p.returncode
        value=dict(kind=kind,pid=p.pid,create_time=created,returncode=code,started_utc=started,
                   ended_utc=datetime.now(timezone.utc).isoformat(),seconds=perf_counter()-start)
        if kind=='publisher' and code==0:
            value['outputs']=[describe(folder/name) for name in (
                'audited_result.json','publisher/events.json','publisher/observation.json',
                'publisher/entry_span.json','publisher/telemetry_records.json')]
        write(folder/(kind+'_exit.json'),value)
    child_exit(folder,request,kind);watch.force()
    return value


def pipeline(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request)
    try:
        run_child(folder,request,'worker')
        run_child(folder,request,'publisher')
        write(folder/'pipeline_done.json',dict(completed=True))
    except BaseException as error:
        write(folder/'pipeline_failure.json',dict(error_type=type(error).__name__))
        raise


def check_observation(root):
    events=read(root/'events.json');summary=summarize_events(events)
    if summary!=read(root/'observation.json') or any(not x['completed'] for x in events):
        raise ValueError('Observation summary differs or contains failed operations')
    return events,summary


def check_diagnostic(root,binding,measured):
    events,summary=check_observation(root)
    descriptors=[x['metadata']['descriptor'] for x in events if x['phase']=='binding.descriptor']
    if descriptors!=binding['sources']*2:
        raise ValueError('D changed original create/post-lock descriptor count or identity')
    for phase in ('context.load_context','context.prepare_catalog','verifier.setup_envelope'):
        if summary['phases'][phase]['calls']!=1:
            raise ValueError('D changed original initialization calls')
    verify=next(x for x in events if x['phase']=='verifier.total')
    if verify['metadata']['original_setup_seconds']!=measured['setup_seconds']:
        raise ValueError('Original setup timing differs')
    return summary


def audit_result(folder,request,observer):
    meta=request['metadata'];child_exit(folder,request,'worker')
    if read(folder/'worker_done.json')!=DONE:
        raise ValueError('Worker did not complete all fourteen runs')
    watch=ThrottledWatch(folder,request['deadline_utc'])
    with observer.span('publisher.initial_hash'): observer.verify_bindings(request['sources'],watch)
    c=meta['cohort'];binding=read(ROOT/c['old_run'])['binding'];probes=read(ROOT/c['probes'])['probes']
    reference=read(ROOT/c['reference']);reference_frames=list(_physical_frames((ROOT/c['old_run']).parent))
    raw=b''.join(reference_frames)
    if len(reference_frames)!=48 or len(raw)!=reference['actual_committed_bytes'] or hashlib.sha256(raw).hexdigest()!=reference['actual_committed_payload_sha256']:
        raise ValueError('Original physical reference differs')
    for phase in ('worker_initial_hash','worker_final_hash'):
        e,s=check_observation(folder/phase)
        actual=[x['metadata']['descriptor'] for x in e if x['phase']=='closure.descriptor']
        if actual!=request['sources'] or s['source_descriptors']['completed_calls']!=len(request['sources']):
            raise ValueError('Incomplete worker source coverage')
    runs={};work=None;previous=None;factory=StoreFactory(observer)
    for item in meta['schedule']:
        watch.force();label,mode=item['label'],item['mode'];root=folder/label
        contract_run=read(root/'verified_subset/run.json')
        if (contract_run['binding']!=binding or contract_run['expected_queries']!=48
                or any(contract_run[k]!=request[k] for k in ('deadline_utc','budget_seconds'))):
            raise ValueError('Run binding, cohort or deadline changed')
        with observer.span('publisher.open_and_proof'):
            store=factory.open(root/'verified_subset',binding,source_root=ROOT)
            proof=observer.call('publisher.ledger_proof',ledger_proof,store,probes)
            if proof!=read(root/'proof.json') or any(proof[k]!=reference[k] for k in ('records','actual_committed_bytes','actual_committed_payload_sha256')):
                raise ValueError('Published ledger proof differs')
            if list(_physical_frames(root/'verified_subset'))!=reference_frames:
                raise ValueError('Complete scientific payload bytes differ')
        measured,obs,entry=(read(root/name) for name in ('measured.json','observations.json','entry.json'))
        if entry['label']!=label or entry['mode']!='baseline' or read(root/'profile.json'):
            raise ValueError('Original run identity or SQL profile changed')
        accounting=summarize_run(measured,obs,entry,probes)
        current=[q['sql_workload'] for q in measured['queries']]
        if work is not None and work!=current: raise ValueError('Logical workload changed')
        work=current
        load,previous=load_summary(root,request,label,mode,previous)
        diagnostic=check_diagnostic(root,binding,measured) if mode=='D' else None
        if mode=='R' and (root/'events.json').exists(): raise ValueError('Reference has fine observers')
        runs[label]=dict(mode=mode,accounting=accounting,load=load,diagnostic=diagnostic)
    with observer.span('publisher.final_hash'): observer.verify_bindings(request['sources'],watch)
    if check_gates()!=meta['gates']: raise ValueError('Scientific gates changed')
    watch.force()
    result=dict(status='v25_independent_audit_complete',schedule=meta['schedule'],runs=runs,
                reference=reference,sources_bound=len(request['sources']),worker_exit=describe(folder/'worker_exit.json'),
                sealed_worker_evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()
                    and p.relative_to(folder).parts[0] in ({x['label'] for x in meta['schedule']} |
                        {'worker_initial_hash','worker_final_hash','worker_done.json','request.json'})])
    observer.call('publisher.result_write',write,folder/'audited_result.json',result)
    watch.force()
    return result


def publisher(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request)
    (folder/'publisher').mkdir(parents=True,exist_ok=True)
    obs=Observation();sampler=TelemetrySampler(interval_seconds=.2,process_name_prefix='ollama');sampler.start(0)
    span=dict(label='publisher',mode='publisher',repeat_index=0,completed=False,
        start_monotonic_seconds=perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:
        obs.publisher(audit_result,folder,request,obs)
        span['completed']=True
    finally:
        span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        try: sampler.stop()
        finally:
            write(folder/'publisher/entry_span.json',span)
            write(folder/'publisher/telemetry_records.json',dict(label='publisher',mode='publisher',records=sampler.records))
            save_observation(folder/'publisher',obs)


def release(folder):
    folder=folder_path(folder);request=read(folder/'request.json');meta=contract(request)
    completion=read(folder/'supervisor_completion.json');_check_window(request,completion)
    if read(folder/'pipeline_done.json')!={'completed':True}:
        raise ValueError('Pipeline did not complete')
    exits={k:child_exit(folder,request,k) for k in ('worker','publisher')}
    if exits['worker']['ended_utc']>exits['publisher']['started_utc']:
        raise ValueError('Publisher overlapped the worker')
    result=read(folder/'audited_result.json');verify_bindings([result['worker_exit']])
    verify_bindings(exits['publisher']['outputs'])
    verify_bindings(result['sealed_worker_evidence'])
    events,pub=check_observation(folder/'publisher')
    load,_=load_summary(folder/'publisher',request,'publisher','publisher')
    expected=2*len(request['sources'])+14*len(read(ROOT/meta['cohort']['old_run'])['binding']['sources'])
    if pub['source_descriptors']['completed_calls']!=expected:
        raise ValueError('Independent publisher source calls differ')
    if [x['metadata']['descriptor'] for x in events if x['phase']=='closure.descriptor']!=request['sources']*2:
        raise ValueError('Independent publisher full source identities differ')
    for phase in ('worker_initial_hash','worker_final_hash'): check_observation(folder/phase)
    for item in meta['schedule']:
        root=folder/item['label']
        if item['mode']=='D': check_observation(root)
    evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]
    report=dict(status='v25_original48_source_setup_diagnostics_measured',created_utc=request['created_utc'],
        namespace=folder.relative_to(ROOT).as_posix(),specification=meta['specification'],acceptance=meta['acceptance'],
        schedule=meta['schedule'],supervisor=completion,results=result,
        worker_source_observations={p:read(folder/p/'observation.json') for p in ('worker_initial_hash','worker_final_hash')},
        publisher_observation=pub,publisher_load=load,
        process_wall_seconds={k:x['seconds'] for k,x in exits.items()},
        source_verification='Original sources checked before/after worker and twice in independent publisher within one monitored deadline.',
        scope=dict(real_runs=14,engineering_checks=672,new_keys=0,new_primary_fit_validation_bootstrap=0,
                   full_validation_complete=False,reserved_test='locked'),
        interpretation='R/D measures observer effects and changing machine context, not optimization. Publisher callback wall includes private audited-result output. '
            'Publisher process wall additionally includes interpreter startup, telemetry and observation receipts. Parent public serialization is separate. '
            'Logical descriptor bytes are not physical I/O or CPU wait. No Ollama GPU/token slowdown measurement.',
        gates=check_gates(),T_plan=None,evidence=evidence)
    if report['gates']!=meta['gates']: raise ValueError('Post-exit gates changed')
    existing=read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    if existing is not None:
        verify_bindings(existing['evidence'])
        if existing!=report: raise ValueError('Re-audit differs from immutable public report')
    else:
        start=perf_counter();public_json(ROOT/REPORT,report,exclusive=True)
        public_json(ROOT/RELEASE,dict(status='v25_public_report_released',report=describe(ROOT/REPORT),
            public_serialization_seconds=perf_counter()-start,deadline_utc=request['deadline_utc']),exclusive=True)
    print({'report':REPORT,'seconds':completion['seconds'],'checks':672,'publisher_seconds':exits['publisher']['seconds']})
    return report


def measure():
    with exclusive():
        if (ROOT/REPORT).exists(): raise FileExistsError('Use --release to re-audit the existing window')
        records,meta=source_contract()
        for p in PRIVATE.glob('knn-v25-sources-*/request.json'):
            raise FileExistsError('Inspect the existing window; do not silently retry: '+str(p.parent))
        folder=PRIVATE/('knn-v25-sources-'+uuid4().hex)
        print('V25 supervised namespace: '+folder.relative_to(ROOT).as_posix(),flush=True)
        run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],records,
                   'joint_tail',metadata=meta,budget_seconds=1800,limits=LIMITS)
        return release(folder)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance',action='store_true');mode.add_argument('--measure',action='store_true')
    for name in ('pipeline','worker','publisher','release'): mode.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.acceptance: acceptance()
    elif args.measure: measure()
    elif args.pipeline: pipeline(args.pipeline)
    elif args.worker: worker(args.worker)
    elif args.publisher: publisher(args.publisher)
    else:
        with exclusive(): release(args.release)
