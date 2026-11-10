"""One stopped V31 window's exact outer-log reconciliation; never replay queries."""
import argparse
from collections import Counter
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timedelta,timezone
import hashlib
from io import StringIO
import math
from pathlib import Path
from time import perf_counter
import unittest
from uuid import uuid4

import psutil
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,write,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from scripts import run_retailrocket_session_knn_compare_v31 as entry
from scripts import run_retailrocket_session_knn_compare_v28 as previous
from scripts import accept_retailrocket_session_knn_snapshot_v30 as s1

NAMESPACE='shop-mysql-runtime/verification/knn-v31-s1-362fcd2ee5da4ae4bf2f5fd5bb9e04c5'
BASE='reports/stage12/retailrocket_session_knn_v32_release_'
SPEC=BASE+'specification_20261110.json';ACCEPT=BASE+'acceptance_20261110.json';OUTPUT=BASE+'recovery_20261110.json'
SPEC_SHA='4dffec9fb8ca79d9f1f8878723ee704fc8e2c97cf725e1409111f927f8a7362c'
METHODS=('scripts/release_retailrocket_session_knn_v32.py','tests/test_retailrocket_session_knn_release_v32.py')
SUITES=('tests.test_retailrocket_session_knn_release_v32','tests.test_retailrocket_session_knn_compare_v31.ContractTests',
    'tests.test_retailrocket_session_knn_snapshot_v30')
EXPECTED_TAIL=("{'status': 'v29_C1_serialization_inventory_and_isolated_replay_complete', 'tests': 18, 'real_original48_runs': 0}\r\n"
    "{'specification': {'path': 'reports/stage12/retailrocket_session_knn_v29_serialization_specification_20261109.json', 'bytes': 338322, 'sha256': '221f63bbfa21078eedec62f9218dbb294443e4a03698e3a7bb19eb5923659cfd'}, 'new_candidate_required_cases': 32, 'inherited_case_count': 38, 'candidate_tests_run': 0, 'real_runs': 0, 'audit': True}\r\n").encode('ascii')
EXPECTED_FINAL_SHA='f735e41fb16c5418eb0e5a49e7ccf67e43d26f2a129e72ce17cd0cd59d800841'
EMPTY_SHA=hashlib.sha256(b'').hexdigest()


def validate_log(old_record,final_record,actual_bytes,expected_tail):
    if (type(expected_tail) is not bytes or type(actual_bytes) is not bytes
            or set(old_record)!={'path','bytes','sha256'} or set(final_record)!={'path','bytes','sha256'}
            or type(old_record['bytes']) is not int or type(final_record['bytes']) is not int
            or old_record['path']!=NAMESPACE+'/stdout_stderr.log'
            or expected_tail!=EXPECTED_TAIL or len(expected_tail)!=450 or hashlib.sha256(expected_tail).hexdigest()!=EXPECTED_FINAL_SHA
            or old_record!=dict(path=final_record['path'],bytes=0,sha256=EMPTY_SHA)
            or not old_record['path'].endswith('/stdout_stderr.log') or final_record['bytes']!=450
            or final_record['sha256']!=EXPECTED_FINAL_SHA or actual_bytes!=expected_tail):
        raise ValueError('Only the exact frozen stopped outer diagnostic log is reconcilable')
    return dict(original_descriptor=old_record,final_descriptor=final_record,original_prefix_bytes=0,
        original_prefix_sha256=EMPTY_SHA,append_bytes=450,append_sha256=EXPECTED_FINAL_SHA,
        reason='The pipeline flushed exactly the frozen parent audit diagnostics after the independent publisher sealed the still-open outer stdout. No query, payload, cost, source, model or method differs.')


def make_verifier(old_record,final_record,expected_tail,root=ROOT):
    def checked(records,watch=lambda:None):
        for record in records:
            if record['path']==old_record['path']:
                if record==old_record:
                    watch();validate_log(old_record,final_record,(Path(root)/record['path']).read_bytes(),expected_tail)
                elif record==final_record:verify_bindings([record],watch)
                else:raise ValueError('Unexpected outer-log descriptor')
            else:verify_bindings([record],watch)
    return checked


def expected_diagnostic():
    captured=StringIO()
    with redirect_stdout(captured):entry.specification()
    result=captured.getvalue().replace('\n','\r\n').encode('ascii')
    if result!=EXPECTED_TAIL:raise ValueError('Diagnostics do not reproduce from frozen methods/specification')
    return result


def assert_stopped(folder,request):
    completion=read(folder/'supervisor_completion.json');entry.old._check_window(request,completion)
    if read(folder/'pipeline_done.json')!={'completed':True}:raise ValueError('Original pipeline is incomplete')
    exits={k:entry.old.child_exit(folder,request,k) for k in ('worker','publisher')}
    if exits['worker']['ended_utc']>exits['publisher']['started_utc']:raise ValueError('Original children overlap')
    for item in read(folder/'tracked_process_identities.json')['identities']:
        try:
            process=psutil.Process(item['pid'])
            if process.is_running() and process.create_time()==item['create_time']:raise ValueError('Original tracked identity still runs')
        except psutil.NoSuchProcess:pass
    return completion,exits


def audit_existing(folder,request,witness):
    folder=Path(folder).resolve()
    if folder!= (ROOT/NAMESPACE).resolve():raise ValueError('Only the sealed failed-publication window may recover')
    entry.core.require_scheme(request);assert_stopped(folder,request)
    expected=expected_diagnostic()
    captured=StringIO()
    with redirect_stdout(captured):meta=entry.contract(request)
    if captured.getvalue().replace('\n','\r\n').encode('ascii')!=expected:raise ValueError('Unexpected contract output')
    if witness!=validate_log(witness['original_descriptor'],witness['final_descriptor'],(folder/'stdout_stderr.log').read_bytes(),expected):
        raise ValueError('Reconciliation witness differs')
    checker=make_verifier(witness['original_descriptor'],witness['final_descriptor'],expected)
    audited=_clone(previous.audit_completed,verify_bindings=checker)(folder,request)
    result,completion,exits,pub,load=audited
    if result['status']!='v31_C1_S1_independent_real_audit_complete' or result['cache']['fingerprint_scheme']!=entry.core.SCHEME:
        raise ValueError('Unchanged independently published S1 result required')
    original=list(_physical_frames((ROOT/meta['cohort']['old_run']).parent))
    spec=entry.specification();reference=spec['original48_reference'];payload=b''.join(original)
    if len(original)!=48 or len(payload)!=reference['actual_committed_bytes'] or hashlib.sha256(payload).hexdigest()!=reference['actual_committed_payload_sha256']:
        raise ValueError('Original48 complete scientific reference differs')
    if len(result['runs'])!=14:raise ValueError('All14 completed runs are required')
    for label in result['runs']:
        if list(_physical_frames(folder/label/'verified_subset'))!=original:raise ValueError('Complete scientific frames differ')
    verify_bindings([witness['final_descriptor']]);assert_stopped(folder,request)
    return audited


def window_manifest(folder):
    return [describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]


def freeze():
    if (ROOT/SPEC).exists():raise FileExistsError('Immutable stopped-window recovery specification exists')
    folder=ROOT/NAMESPACE;request=read(folder/'request.json');assert_stopped(folder,request)
    tail=expected_diagnostic();result=read(folder/'audited_result.json')
    records=[x for x in result['evidence'] if x['path']==NAMESPACE+'/stdout_stderr.log']
    if len(records)!=1:raise ValueError('One original outer-log descriptor required')
    final=describe(folder/'stdout_stderr.log');witness=validate_log(records[0],final,(folder/'stdout_stderr.log').read_bytes(),tail)
    make_verifier(records[0],final,tail)(result['evidence'])
    verify_bindings(read(folder/'publisher_exit.json')['outputs'])
    public_json(ROOT/SPEC,dict(status='v32_single_stopped_window_publication_recovery_frozen',namespace=NAMESPACE,
        original_specification=describe(ROOT/entry.SPEC),original_acceptance=describe(ROOT/entry.ACCEPT),
        original_methods=read(ROOT/entry.ACCEPT)['methods'],window_evidence=window_manifest(folder),
        witness=witness,methods=list(METHODS),suites=list(SUITES),environment=environment(),gates=check_gates(),
        post_exit_budget_seconds=300,
        scope=dict(replayed_queries=0,new_real_runs=0,original_real_runs=14,original_engineering_checks=672,reserved_test='locked'),
        policy='Only this exact stopped window and exact 450-byte diagnostic append. All other evidence remains strict. Original files/methods/reports are never edited. Full source checks and independent post-exit validation precede publication; recovery cost is separate from original291.469s window.'),exclusive=True)
    print(dict(specification=describe(ROOT/SPEC),replayed_queries=0,real_runs=0))


def specification():
    value=read(ROOT/SPEC)
    if (describe(ROOT/SPEC)['sha256']!=SPEC_SHA or value['namespace']!=NAMESPACE
            or value['methods']!=list(METHODS) or value['suites']!=list(SUITES)
            or value['environment']!=environment() or value['gates']!=check_gates()):raise ValueError('Frozen single-window recovery changed')
    verify_bindings([value['original_specification'],value['original_acceptance'],*value['original_methods'],*value['window_evidence']])
    folder=ROOT/NAMESPACE;w=value['witness']
    if window_manifest(folder)!=value['window_evidence']:raise ValueError('Stopped window file set or content changed')
    if validate_log(w['original_descriptor'],w['final_descriptor'],(folder/'stdout_stderr.log').read_bytes(),expected_diagnostic())!=w:
        raise ValueError('Frozen log witness changed')
    return value


def acceptance():
    with entry.exclusive():
        if (ROOT/ACCEPT).exists():raise FileExistsError('Immutable recovery acceptance exists')
        spec=specification();methods=[describe(ROOT/p) for p in METHODS]
        folder=PRIVATE/('knn-v32-release-tests-'+uuid4().hex);folder.mkdir();start=perf_counter()
        with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
            result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=s1.Result).run(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        expected=s1.test_ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.wasSuccessful() or result.skipped or Counter(expected)!=Counter(result.passed):
            print((folder/'tests.log').read_text(encoding='utf-8')[-15000:]);raise ValueError('Recovery synthetic acceptance failed')
        verify_bindings(methods)
        if specification()!=spec:raise ValueError('Frozen stopped evidence changed during acceptance')
        public_json(ROOT/ACCEPT,dict(status='v32_exact_log_reconciliation_synthetic_accepted',specification=describe(ROOT/SPEC),
            methods=methods,suites=list(SUITES),tests_run=result.testsRun,passed_test_ids=result.passed,failures=0,errors=0,skipped=0,
            log=describe(folder/'tests.log'),seconds=perf_counter()-start,replayed_queries=0,new_real_runs=0),exclusive=True)
        print(dict(tests=result.testsRun,replayed_queries=0,new_real_runs=0))


def accepted():
    spec=specification();value=read(ROOT/ACCEPT)
    verify_bindings([value['specification'],*value['methods'],value['log']])
    if (value['status']!='v32_exact_log_reconciliation_synthetic_accepted' or value['specification']!=describe(ROOT/SPEC)
            or value['methods']!=[describe(ROOT/p) for p in METHODS] or value['suites']!=list(SUITES)
            or any(value[k]!=0 for k in ('failures','errors','skipped','replayed_queries','new_real_runs'))
            or value['tests_run']!=len(value['passed_test_ids'])
            or Counter(value['passed_test_ids'])!=Counter(s1.test_ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES)))):
        raise ValueError('Unchanged recovery must pass all selected tests')
    return spec,value


def report_for(folder,request,audited,recovery):
    result,completion,exits,pub,load=audited;meta=request['metadata']
    manifest=window_manifest(folder)
    if manifest!=read(ROOT/SPEC)['window_evidence']:raise ValueError('Only the frozen complete final window manifest may publish')
    return dict(status='v31_C1_S1_original48_real_comparison_measured',namespace=NAMESPACE,
        specification=meta['specification'],acceptance=meta['acceptance'],core_acceptance=meta['core_acceptance'],
        fingerprint_scheme=entry.core.SCHEME,schedule=meta['schedule'],supervisor=completion,results=result,decision=result['decision'],
        publisher_observation=pub,publisher_load=load,
        worker_source_observations={p:read(folder/p/'observation.json') for p in ('worker_initial_hash','worker_final_hash')},
        process_wall_seconds={k:v['seconds'] for k,v in exits.items()},gates=check_gates(),
        scope=dict(real_runs=14,engineering_checks=672,new_keys=0,new_real_fit_validation_bootstrap=0,full_validation_complete=False,reserved_test='locked'),T_plan=None,
        evidence=manifest,publication_recovery=recovery,
        interpretation='Known-validation original48 engineering comparison. Same single original window; no repeated queries. The sole final outer-log diagnostic append is reconciled by a separately accepted post-exit release. Original nested publisher evidence remains immutable; top-level evidence binds final stopped files. Recovery time is outside the original window. No population/test or Ollama token/GPU speed claim.')


def recover():
    with entry.exclusive():
        if (ROOT/entry.REPORT).exists() or (ROOT/entry.RELEASE).exists() or (ROOT/OUTPUT).exists():raise FileExistsError('Use --audit for an already recovered publication')
        spec,receipt=accepted();folder=ROOT/NAMESPACE;request=read(folder/'request.json');assert_stopped(folder,request)
        root=PRIVATE/('knn-v32-release-recovery-'+uuid4().hex);root.mkdir()
        started_utc=datetime.now(timezone.utc);deadline=(started_utc+timedelta(seconds=300)).isoformat()
        watch=ThrottledWatch(root,deadline);start=perf_counter()
        before=perf_counter();verify_bindings(request['sources'],watch);initial=perf_counter()-before
        before=perf_counter();audited=audit_existing(folder,request,spec['witness']);audit_seconds=perf_counter()-before
        before=perf_counter();verify_bindings(request['sources'],watch);final=perf_counter()-before
        verify_bindings([*spec['window_evidence'],*receipt['methods'],describe(ROOT/SPEC),describe(ROOT/ACCEPT)])
        if window_manifest(folder)!=spec['window_evidence']:raise ValueError('Stopped window changed during recovery')
        watch.force()
        raw=dict(status='v32_stopped_window_reaudited_without_query_replay',original_namespace=NAMESPACE,
            started_utc=started_utc.isoformat(),deadline_utc=deadline,post_exit_budget_seconds=300,
            original_supervised_window_seconds=audited[1]['seconds'],original_closure_sources=len(request['sources']),context_methods=len(request['metadata']['context']['methods']),
            original_source_hashes=dict(initial_seconds=initial,final_seconds=final,passes=2),post_exit_audit_seconds=audit_seconds,
            post_exit_total_seconds=perf_counter()-start,frames_checked=672,replayed_queries=0,new_real_runs=0,
            witness=spec['witness'],original_audited_result=describe(folder/'audited_result.json'),
            methods=receipt['methods'],specification=describe(ROOT/SPEC),acceptance=describe(ROOT/ACCEPT))
        write(root/'audit.json',raw)
        recovery=dict(status='v32_exact_stopped_log_reconciled',specification=describe(ROOT/SPEC),acceptance=describe(ROOT/ACCEPT),
            audit=describe(root/'audit.json'),witness=spec['witness'],replayed_queries=0,new_real_runs=0,
            post_exit_total_seconds=raw['post_exit_total_seconds'])
        report=report_for(folder,request,audited,recovery);verify_bindings(spec['window_evidence']);watch.force()
        tick=perf_counter();public_json(ROOT/entry.REPORT,report,exclusive=True)
        if window_manifest(folder)!=spec['window_evidence']:raise ValueError('Stopped window changed before release seal')
        public_json(ROOT/entry.RELEASE,dict(status='v31_C1_S1_public_report_released',report=describe(ROOT/entry.REPORT),
            public_serialization_seconds=perf_counter()-tick,deadline_utc=request['deadline_utc'],publication_recovery=describe(ROOT/ACCEPT)),exclusive=True)
        public_json(ROOT/OUTPUT,dict(status='v32_original_window_publication_recovered',report=describe(ROOT/entry.REPORT),
            release=describe(ROOT/entry.RELEASE),recovery=recovery,replayed_queries=0,new_real_runs=0),exclusive=True)
        print(dict(report=entry.REPORT,window_seconds=audited[1]['seconds'],recovery_seconds=raw['post_exit_total_seconds'],replayed_queries=0,adopted=report['decision']['adopted']))


def audit():
    spec,receipt=accepted();published=read(ROOT/entry.REPORT);proof=read(ROOT/OUTPUT)
    verify_bindings([proof['report'],proof['release'],published['publication_recovery']['audit'],*published['evidence']])
    raw=read(ROOT/published['publication_recovery']['audit']['path'])
    expected_recovery=dict(status='v32_exact_stopped_log_reconciled',specification=describe(ROOT/SPEC),acceptance=describe(ROOT/ACCEPT),
        audit=published['publication_recovery']['audit'],witness=spec['witness'],replayed_queries=0,new_real_runs=0,
        post_exit_total_seconds=raw['post_exit_total_seconds'])
    request=read(ROOT/NAMESPACE/'request.json')
    started=datetime.fromisoformat(raw['started_utc']);deadline=datetime.fromisoformat(raw['deadline_utc'])
    original_exit=datetime.fromisoformat(read(ROOT/NAMESPACE/'supervisor_completion.json')['actual_exit_observed_utc'])
    if (started.utcoffset() is None or deadline.utcoffset() is None or started<original_exit
            or started>datetime.now(timezone.utc) or (deadline-started).total_seconds()!=300):
        raise ValueError('Recovery chronology must follow the original stopped window')
    times=[raw['original_source_hashes']['initial_seconds'],raw['original_source_hashes']['final_seconds'],raw['post_exit_audit_seconds'],raw['post_exit_total_seconds']]
    if (proof['status']!='v32_original_window_publication_recovered' or proof['report']!=describe(ROOT/entry.REPORT)
            or proof['release']!=describe(ROOT/entry.RELEASE) or proof['replayed_queries']!=0 or proof['new_real_runs']!=0
            or proof['recovery']!=expected_recovery or published['publication_recovery']!=expected_recovery
            or raw['status']!='v32_stopped_window_reaudited_without_query_replay' or raw['original_namespace']!=NAMESPACE
            or raw['witness']!=spec['witness'] or raw['replayed_queries']!=0 or raw['new_real_runs']!=0
            or raw['frames_checked']!=672 or raw['original_closure_sources']!=len(request['sources'])
            or raw['context_methods']!=26 or raw['original_source_hashes']['passes']!=2
            or raw['original_supervised_window_seconds']!=read(ROOT/NAMESPACE/'supervisor_completion.json')['seconds']
            or raw['original_audited_result']!=describe(ROOT/NAMESPACE/'audited_result.json')
            or raw['methods']!=receipt['methods'] or raw['specification']!=describe(ROOT/SPEC) or raw['acceptance']!=describe(ROOT/ACCEPT)
            or any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in times)
            or raw['post_exit_total_seconds']+1e-8<math.fsum(times[:3]) or raw['post_exit_total_seconds']>300
            or raw['post_exit_budget_seconds']!=300
            or (datetime.fromisoformat(raw['deadline_utc'])-datetime.fromisoformat(raw['started_utc'])).total_seconds()!=300):
        raise ValueError('Recovery proof differs from the sealed stopped window')
    for obj in (proof,raw,published['publication_recovery']):
        if any(type(obj[k]) is not int or obj[k]!=0 for k in ('replayed_queries','new_real_runs')):
            raise ValueError('Recovery must retain exact zero replay counters')
    release=read(ROOT/entry.RELEASE);seconds=release['public_serialization_seconds']
    if (release['status']!='v31_C1_S1_public_report_released' or release['report']!=describe(ROOT/entry.REPORT)
            or release['deadline_utc']!=request['deadline_utc'] or release['publication_recovery']!=describe(ROOT/ACCEPT)
            or type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0):raise ValueError('Recovered release seal differs')
    folder=ROOT/NAMESPACE;audited=audit_existing(folder,request,spec['witness'])
    if published!=report_for(folder,request,audited,published['publication_recovery']):raise ValueError('Re-audited recovered report differs')
    print(dict(status=proof['status'],replayed_queries=0,checks=672,audit=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('specification','acceptance','recover','audit'):mode.add_argument('--'+name,action='store_true')
    args=parser.parse_args()
    if args.specification:freeze()
    elif args.acceptance:acceptance()
    elif args.recover:recover()
    else:
        with entry.exclusive():audit()
