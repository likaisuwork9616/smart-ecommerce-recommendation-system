"""New bounded engineering diagnostics using a verified read-only sealed model.

No full real readback, primary experiment, final selection or test entry exists.
The historical build allowance is retained; reuse is not a new build timing.
"""
import argparse
from contextlib import closing
import cProfile
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import pstats
import sqlite3
import subprocess
import sys
import time
import uuid

import psutil

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT,PRIMARY,PATHS,LIMITS,SPEC,read,write,describe,verify_bindings,environment,check_gates)
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch

PRIOR='shop-mysql-runtime/verification/retailrocket-knn-v2-probe-ede701de4fac422c86f86bc91828b759'
PRIOR_REPORT='reports/stage12/retailrocket_session_knn_v2_cost_probe_20261103.json'
ACCEPTANCE='reports/stage12/retailrocket_session_knn_v3_cost_entry_acceptance_20261103.json'


def assert_model_sealed():
    for suffix in ('-wal','-shm','-journal'):
        if (ROOT/PRIOR/('work/independent.sqlite'+suffix)).exists():
            raise ValueError('Prior model journal remains')


def validate_acceptance():
    acceptance=read(ROOT/ACCEPTANCE)
    if acceptance['status']!='v3_cost_diagnostic_entry_synthetic_accepted':
        raise ValueError('V3 synthetic acceptance is required')
    expected={p.relative_to(ROOT).as_posix() for parent in ('scripts','tests')
              for p in (ROOT/parent).glob('*knn*v3.py')}
    records=acceptance['method_files'];names=[r['path'] for r in records]
    if len(names)!=len(set(names)) or set(names)!=expected or not expected:
        raise ValueError('Incomplete or duplicate V3 method inventory')
    verify_bindings(records)


def source_bindings():
    prior=ROOT/PRIOR;cost=read(ROOT/PRIOR_REPORT)
    # Anchor provenance to the published prior report, not new hashes of an
    # arbitrarily selected local database.
    evidence={r['path']:r for r in cost['evidence']}
    for name in ('request.json','work/stages/reconstruction.json'):
        verify_bindings([evidence[PRIOR+'/'+name]])
    request=read(prior/'request.json');identity=read(prior/'work/run_identity.json')
    if describe(prior/'work/run.json')!={'path':PRIOR+'/work/run.json',
            'bytes':identity['bytes'],'sha256':identity['sha256']}:
        raise ValueError('Prior run identity changed')
    run=read(prior/'work/run.json');stage=read(prior/'work/stages/reconstruction.json')
    if (run['binding']['sources']!=request['sources'] or stage['run_sha256']!=identity['sha256']
            or request['environment']!=environment() or len(request['sources'])!=440):
        raise ValueError('Prior sealed model provenance mismatch')
    records={r['path']:r for r in request['sources']}
    for artifact in stage['artifacts']:
        record=dict(artifact,path=PRIOR+'/work/'+artifact['path']);records[record['path']]=record
    assert_model_sealed()
    for name in ('request.json','work/run.json','work/run_identity.json','work/stages/reconstruction.json'):
        r=describe(prior/name);records[r['path']]=r
    for parent in ('scripts','tests'):
        for path in sorted((ROOT/parent).glob('*knn*v3.py')):
            r=describe(path);records[r['path']]=r
    for name in (PRIOR_REPORT,ACCEPTANCE):
        r=describe(ROOT/name);records[r['path']]=r
    return [records[k] for k in sorted(records)]


def index_microbench(folder,watch,rows=50000):
    database=folder/'synthetic_index.sqlite';timings={}
    with closing(sqlite3.connect(database)) as db:
        db.execute('PRAGMA temp_store=MEMORY')
        db.set_progress_handler(lambda:(watch() or 0),10000)
        db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        start=time.perf_counter()
        for ordinal in range(rows):
            watch();db.execute('INSERT INTO m VALUES(?,?,?)',(str(ordinal//3),ordinal//3,str(ordinal%17000)))
        db.commit();timings['insert_and_commit']=time.perf_counter()-start
        sizes={'before_indexes':database.stat().st_size}
        for name in ('posting','k1_v2_posting'):
            start=time.perf_counter();db.execute('CREATE INDEX '+name+' ON m(i,v,s)');db.commit()
            timings[name]=time.perf_counter()-start;sizes[name]=database.stat().st_size
    return {'kind':'synthetic_index_microbenchmark','rows':rows,'seconds':timings,'database_bytes':sizes,
            'real_build_timing':False,'extrapolate_to_real_build':False}


def worker(folder):
    from scripts import retailrocket_session_knn_readback_v2 as core
    from scripts import retailrocket_session_knn_cost_probe_v2 as probe
    from scripts import retailrocket_session_knn_pair_probe_v3 as paired
    from scripts.retailrocket_session_knn_proxy_v3 import run_proxy
    request=read(folder/'request.json')
    watch=ThrottledWatch(folder,request['deadline_utc'])
    config=read(ROOT/SPEC)['configuration'];paths={k:ROOT/v for k,v in PATHS.items()}
    phases={};result={'kind':'bounded_engineering_diagnostic_only','full_readback_started':False,
                     'reserved_test':'locked','phases':phases,'T_plan':None}
    def timed(name,fn):
        write(folder/(name+'_started.json'),{'phase':name,'started_utc':datetime.now(timezone.utc).isoformat()})
        start=time.perf_counter();completed=False;error=None
        try:
            watch.force();value=fn();watch.force();completed=True
            return value
        except BaseException as exc:
            error=type(exc).__name__;raise
        finally:
            phases[name]={'seconds':time.perf_counter()-start,'completed':completed,'error_type':error}
            write(folder/(name+'_receipt.json'),dict(phases[name],phase=name))
    try:
        timed('source_and_sealed_model_hash',lambda:verify_bindings(request['sources'],watch));check_gates();assert_model_sealed()
        model=read(ROOT/PRIOR/'work/stages/reconstruction.json')['receipt']
        result['index_microbenchmark']=timed('synthetic_index_microbenchmark',lambda:index_microbench(folder,watch))
        counts,catalog=timed('load_context',lambda:core.load_context(paths,config,model['support'],watch))
        assert_model_sealed()
        with closing(sqlite3.connect('file:'+(ROOT/PRIOR/'work/independent.sqlite').as_posix()+'?mode=ro&immutable=1',uri=True)) as db:
            db.execute('PRAGMA temp_store=MEMORY')
            db.set_progress_handler(lambda:(watch() or 0),10000)
            profiler=cProfile.Profile()
            def stratify():
                try:return profiler.runcall(probe.stratify,db,paths['dataset'],config,model['support'],catalog,watch)
                finally:
                    profiler.dump_stats(str(folder/'stratify.prof'))
                    stats=pstats.Stats(profiler).stats
                    functions=[{'file':Path(key[0]).name,'line':key[1],'function':key[2],
                                'primitive_calls':value[0],'calls':value[1],
                                'self_seconds':value[2],'cumulative_seconds':value[3]}
                               for key,value in stats.items()]
                    write(folder/'stratify_profile.json',{'kind':'profiled_engineering_cost',
                        'timing_includes_profiler_overhead':True,
                        'top_self':sorted(functions,key=lambda r:r['self_seconds'],reverse=True)[:25]})
            population,probes=timed('full_stratification_profiled',stratify)
            write(folder/'frozen_probes.json',{'population':population,'probes':probes})
            result['population']=population
            ranking=timed('exact_rank_probes',lambda:probe.measure_queries(db,probes,model['support'],
                                      model['fit_audit']['fit_id'],counts,catalog,watch))
            write(folder/'rank_measurements.json',ranking);result['rank_measurements']=ranking
        extracted=timed('extract_selected_paired_sources',lambda:paired.extract_samples(
            folder,ROOT/PRIMARY,paths,config,probes,watch))
        write(folder/'extracted_source_summary.json',extracted)
        assert_model_sealed()
        paired_result=timed('selected_four_arm_and_checkpoint',lambda:paired.measure_paired(
            folder,extracted,ROOT/PRIOR/'work/independent.sqlite',model,
            request['deadline_utc'],request['budget_seconds'],watch))
        write(folder/'paired_measurements.json',paired_result);result['paired_measurements']=paired_result
        proxy_config=dict(config,deadline_utc=request['deadline_utc'],budget_seconds=request['budget_seconds'])
        result['synthetic_proxy']=timed('full_shape_synthetic_proxy',lambda:run_proxy(folder,proxy_config,watch))
        assert_model_sealed()
        timed('final_source_and_model_hash',lambda:verify_bindings(request['sources'],watch));check_gates();assert_model_sealed()
        result.update(decision='do_not_start_full_readback',historical_build_allowance_seconds=840.4063534999732,
            reused_model_build_timed_this_window=False,
            missing=['full_production_payload_shape_and_SQL_joint_tail_coverage',
                     'true_full_real_ledger_and_control_prefix_resume_with_tail_rework'],
            reason='Completed engineering components do not certify all full-readback cost dimensions.')
        write(folder/'diagnostic_result.json',result)
        return result
    except BaseException as error:
        write(folder/'failure.json',{'kind':'partial_engineering_diagnostic_preserved','error_type':type(error).__name__,
             'decision':'do_not_start_full_readback','reserved_test':'locked','T_plan':None})
        raise
    finally:
        write(folder/'watch_statistics.json',{'calls':watch.calls,'full_checks':watch.full_checks,
                                            'stop_checks':watch.stop_checks,'interval_seconds':.25})

def supervise():
    # Fresh unique namespace; expired V1 windows and its partial SQLite are unused.
    check_gates()
    validate_acceptance()
    folder=ROOT/'shop-mysql-runtime/verification'/('retailrocket-knn-v3-cost-'+uuid.uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False)
    started=datetime.now(timezone.utc);start=time.monotonic()
    request={'operation':'bounded_cost_diagnostic_v3','created_utc':started.isoformat(),
             'deadline_utc':(started+timedelta(seconds=LIMITS['total_seconds'])).isoformat(),
             'budget_seconds':LIMITS['total_seconds'],'environment':environment(),'limits':LIMITS,
             'sources':source_bindings(), 'prior_namespace':PRIOR, 'prior_source_count':440, 'synthetic_acceptance':ACCEPTANCE, 'authorization':'使用者要求先檢查建置、分層及監控成本，再補齊後續量測；獨立新30分鐘窗口，不啟動全量','selection_plan':'four_time_bands_x_four_posting_bands_extremes_v2',
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
            process=subprocess.Popen([sys.executable,'-B','-m','scripts.run_retailrocket_session_knn_cost_v3',
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
            receipt={'operation':'cost_diagnostic_v3_only','exit_code':exit_code,'stop_reason':stop_reason,
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
    group.add_argument('--diagnose',action='store_true')
    group.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    result=worker(args.worker) if args.worker else supervise()
    print(json.dumps({'worker_finished':True} if args.worker else result,ensure_ascii=False))


if __name__=='__main__':main()
