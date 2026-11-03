"""Bounded V2 readback engineering acceptance and cost probe; no primary fit.

The probe can never publish research acceptance. Full readback is deliberately
fail-closed until every cost dimension has evidence and a fresh execution window.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time
import uuid

import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]
PRIMARY='shop-mysql-runtime/retailrocket_session_knn_paired_v1'
PREPARED='shop-mysql-runtime/retailrocket_session_knn_validation_entry_v1'
AUDIT='shop-mysql-runtime/verification/retailrocket-session-knn-status-audit-20261030/evidence_manifest.json'
SPEC='reports/stage12/retailrocket_session_knn_v1_validation_entry_specification.json'
V2_CONTRACT='docs/contracts/retailrocket_session_knn_readback_v2.json'
V2_ACCEPTANCE='reports/stage12/retailrocket_session_knn_v2_synthetic_acceptance_20261103.json'
PATHS={'dataset':'shop-mysql-runtime/retailrocket_dataset_v1',
       'P0':'shop-mysql-runtime/retailrocket_popularity_v1/development',
       'C1':'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1',
       'D1':'shop-mysql-runtime/retailrocket_directed_paired_v1'}
ARTIFACTS=('aggregate.json','bootstrap.jsonl','fit_audit.json','postings.jsonl',
           'queries.jsonl','sessions.jsonl','train_sessions.jsonl')
LIMITS={'total_seconds':1800,'rss_bytes':8*1024**3,'execution_bytes':20*1024**3,
        'minimum_available_bytes':4*1024**3,'minimum_free_bytes':8*1024**3}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path,value):
    from scripts.retailrocket_session_knn_checkpoint_v2 import atomic_json
    atomic_json(Path(path),value)


def describe(path,watch=lambda:None):
    path=Path(path);h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):watch();h.update(block)
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':h.hexdigest()}


def verify_bindings(records,watch=lambda:None):
    for record in records:
        if describe(ROOT/record['path'],watch)!=record:
            raise ValueError('Frozen source identity changed: '+record['path'])


def environment():
    return {'python':platform.python_version(),'numpy':np.__version__,'psutil':psutil.__version__,
            'implementation':platform.python_implementation(),'byteorder':sys.byteorder}


def check_gates():
    locked=read(ROOT/PREPARED/'locked_scope.json')
    verify_bindings(locked['reference_gates'])
    for name in ('retailrocket_session_knn_final_v1','retailrocket_session_knn_paired_v1/final_refit',
                 'retailrocket_session_knn_paired_v1/reserved_test','retailrocket_session_knn_paired_v1/test_usage.jsonl'):
        if (ROOT/'shop-mysql-runtime'/name).exists():raise ValueError('Final/test scope changed')
    return {'reference_gates_verified':len(locked['reference_gates']),'reserved_test':'locked'}


def expected_bindings():
    guard=read(ROOT/PREPARED/'output_guard.json')
    records={r['path']:r for r in guard['sources']+guard['outputs']}
    audited={r['path']:r for r in read(ROOT/AUDIT)['verified_identities']}
    for name in ARTIFACTS:
        key=PRIMARY+'/'+name;records[key]=audited[key]
    for path in sorted((ROOT/'scripts').glob('*knn*v2.py')):
        record=describe(path);records[record['path']]=record
    for path in sorted((ROOT/'tests').glob('*knn*v2.py')):
        record=describe(path);records[record['path']]=record
    for key in (SPEC,AUDIT,V2_CONTRACT,V2_ACCEPTANCE,PREPARED+'/output_guard.json',PREPARED+'/locked_scope.json'):
        record=describe(ROOT/key);records[key]=record
    return [records[key] for key in sorted(records)]


def worker(folder):
    from scripts.retailrocket_session_knn_checkpoint_v2 import CheckpointStore
    from scripts import retailrocket_session_knn_readback_v2 as core
    from scripts import retailrocket_session_knn_cost_probe_v2 as probe
    request=read(folder/'request.json');deadline=datetime.fromisoformat(request['deadline_utc'])
    def watch():
        if datetime.now(timezone.utc)>=deadline:raise TimeoutError('Absolute probe deadline')
        if (folder/'stop_request.json').exists():raise TimeoutError('Supervisor stop requested')
    config=read(ROOT/SPEC)['configuration'];paths={k:ROOT/v for k,v in PATHS.items()}
    store=CheckpointStore.create(folder/'work',{'sources':request['sources'],'environment':request['environment']},
        request['deadline_utc'],request['budget_seconds'],expected_queries=config['fixed_validation']['queries'],source_root=ROOT)
    phase={};result={'kind':'engineering_cost_probe_only','reserved_test':'locked','primary_fits':0,
                    'full_readback_started':False,'phases_seconds':phase}
    def timed(name,fn):
        started=time.perf_counter()
        try:return fn()
        finally:
            phase[name]=time.perf_counter()-started
            write(folder/('phase_'+name+'.json'),{'phase':name,'phases_seconds':dict(phase)})
    with store.writer():
        timed('source_hash',lambda:verify_bindings(request['sources'],watch));check_gates()
        model=timed('build',lambda:core.prepare_model(ROOT/PRIMARY,paths,config,store,watch))
        counts,catalog=core.load_context(paths,config,model['support'],watch)
        with closing(sqlite3.connect('file:'+(store.folder/'independent.sqlite').as_posix()+'?mode=ro',uri=True)) as db:
            db.set_progress_handler(lambda:(watch() or 0),10000)
            population,probes=timed('stratify',lambda:probe.stratify(db,paths['dataset'],config,model['support'],catalog,watch))
            # Sealed before timing ranks; selection never reads targets or scores.
            write(folder/'frozen_probes.json',{'population':population,'probes':probes})
            measurements=timed('queries',lambda:probe.measure_queries(db,probes,model['support'],
                model['fit_audit']['fit_id'],counts,catalog,watch))
        result.update(population=population,probe_queries=len(probes),measurements=measurements)
        timed('final_source_hash',lambda:verify_bindings(request['sources'],watch));check_gates()
        # An incomplete engineering cost case must never unlock full validation.
        result.update(decision='do_not_start_full_readback',
            missing_cost_evidence=['paired_row_verification_and_checkpoint_io','full_shape_joint_tail_stress','full_shape_global_ledger_replay',
                                   'full_shape_2000_draw_replay','full_resume_hash_ledger_and_tail'],
            reason='Required phases and worst-work dimensions are not all bounded; no total-time claim.')
        write(folder/'probe_result.json',result)
    return result


def supervised_probe():
    # Fresh unique namespace; expired V1 windows and its partial SQLite are unused.
    check_gates()
    acceptance=read(ROOT/V2_ACCEPTANCE)
    if acceptance['status']!='synthetic_equivalence_and_fault_recovery_accepted':
        raise ValueError('V2 synthetic acceptance is required before real cost measurement')
    verify_bindings(acceptance['method_files'])
    folder=ROOT/'shop-mysql-runtime/verification'/('retailrocket-knn-v2-probe-'+uuid.uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False)
    started=datetime.now(timezone.utc);start=time.monotonic()
    request={'operation':'bounded_cost_probe_v2','created_utc':started.isoformat(),
             'deadline_utc':(started+timedelta(seconds=LIMITS['total_seconds'])).isoformat(),
             'budget_seconds':LIMITS['total_seconds'],'environment':environment(),'limits':LIMITS,
             'sources':expected_bindings(),'selection_plan':'four_time_bands_x_four_posting_bands_extremes_v2',
             'reserved_test':'locked','full_readback_enabled':False}
    write(folder/'request.json',request)
    peak_rss=peak_disk=0;stop_reason=None;process=None;exit_code=None
    def kill_tree():
        if process is None or process.poll() is not None:return
        try:
            children=psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:children=[]
        for child in children:
            try:child.kill()
            except psutil.NoSuchProcess:pass
        if process.poll() is None:process.kill()
    try:
        with (folder/'stdout_stderr.log').open('xb') as log:
            process=subprocess.Popen([sys.executable,'-B','-m','scripts.run_retailrocket_session_knn_v2',
                '--worker',str(folder)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            worker_process=psutil.Process(process.pid)
            write(folder/'worker_identity.json',{'pid':process.pid,'create_time':worker_process.create_time(),
                  'boot_time':psutil.boot_time(),'supervisor_pid':psutil.Process().pid,
                  'supervisor_create_time':psutil.Process().create_time()})
            while process.poll() is None:
                elapsed=time.monotonic()-start
                try:
                    members=[worker_process,*worker_process.children(recursive=True),psutil.Process()]
                    rss=sum(p.memory_info().rss for p in members if p.is_running())
                except psutil.NoSuchProcess:rss=0
                disk=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
                peak_rss=max(peak_rss,rss);peak_disk=max(peak_disk,disk)
                reason=('deadline' if elapsed>=LIMITS['total_seconds']-2 else
                    'rss_limit' if rss>LIMITS['rss_bytes'] else
                    'execution_disk_limit' if disk>LIMITS['execution_bytes'] else
                    'minimum_available_memory' if psutil.virtual_memory().available<LIMITS['minimum_available_bytes'] else
                    'minimum_free_disk' if psutil.disk_usage(str(folder)).free<LIMITS['minimum_free_bytes'] else None)
                if reason:
                    stop_reason=reason;write(folder/'stop_request.json',{'reason':reason,'requested_utc':datetime.now(timezone.utc).isoformat()})
                    # Give cooperative VM/row checks a short opportunity, then enforce externally.
                    try:process.wait(timeout=max(.001,min(2,LIMITS['total_seconds']-(time.monotonic()-start))))
                    except subprocess.TimeoutExpired:
                        kill_tree()
                    break
                time.sleep(.5)
            exit_code=process.wait(timeout=10)
    except BaseException as error:
        if stop_reason is None:stop_reason='supervisor_exception_'+type(error).__name__
        raise
    finally:
        try:
            if process is not None and process.poll() is None:
                if stop_reason is None:stop_reason='supervisor_interrupted'
                if not (folder/'stop_request.json').exists():
                    write(folder/'stop_request.json',{'reason':stop_reason,'requested_utc':datetime.now(timezone.utc).isoformat()})
                kill_tree();exit_code=process.wait(timeout=10)
        finally:
            receipt={'operation':'cost_probe_only','exit_code':exit_code,'stop_reason':stop_reason,
                     'actual_exit_observed_utc':datetime.now(timezone.utc).isoformat() if exit_code is not None else None,
                     'elapsed_seconds':time.monotonic()-start,'peak_sampled_tree_and_supervisor_rss_bytes':peak_rss,
                     'peak_sampled_execution_bytes':peak_disk,'reserved_test':'locked',
                     'full_readback_started':False,'namespace':folder.relative_to(ROOT).as_posix()}
            write(folder/'supervisor_completion.json',receipt)
    check_gates()
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--probe',action='store_true')
    group.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    print(json.dumps(worker(args.worker) if args.worker else supervised_probe(),ensure_ascii=False))


if __name__=='__main__':main()
