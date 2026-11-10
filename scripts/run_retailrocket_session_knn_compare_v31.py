"""One gated C1-S1 original48 window: sequential worker and independent publisher."""
import argparse
from collections import Counter
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timezone
import math
from pathlib import Path
import sys
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT,read,write,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts import run_retailrocket_session_knn_compare_v28 as previous
from scripts import freeze_retailrocket_session_knn_compare_v31 as frozen
from scripts import accept_retailrocket_session_knn_snapshot_v30 as accepted_s1
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as core

old=previous.old
MODULE='scripts.run_retailrocket_session_knn_compare_v31'
BASE=frozen.BASE;SPEC=frozen.SPEC;ACCEPT=BASE+'acceptance_20261110.json'
REPORT=BASE+'cost_20261110.json';RELEASE=BASE+'release_20261110.json'
SPEC_SHA='1473ae19a439372433ffe079d2fbf8d20811558322be6fe3d168b76476311a66'
METHODS=frozen.METHODS;SUITES=frozen.SUITES
exclusive=previous.exclusive
decision=core.decision


def specification():
    spec=read(ROOT/SPEC)
    if describe(ROOT/SPEC)['sha256']!=SPEC_SHA or spec!=frozen.audit():raise ValueError('Expected the sealed S1 real activation')
    return spec


def acceptance():
    with exclusive():
        if (ROOT/ACCEPT).exists():raise FileExistsError('Immutable S1 real-entry acceptance already exists')
        spec=specification();methods=[describe(ROOT/p) for p in METHODS]
        folder=PRIVATE/('knn-v31-s1-acceptance-'+uuid4().hex);folder.mkdir();start=perf_counter()
        with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
            result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=accepted_s1.Result).run(
                unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-15000:]);raise ValueError('New S1 entry acceptance failed')
        expected=accepted_s1.test_ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if Counter(result.passed)!=Counter(expected) or result.testsRun!=len(result.passed):
            raise ValueError('Every selected real-entry and inherited regression must succeed')
        accepted_s1.validate_coverage(result.passed)
        from tests import test_retailrocket_session_knn_compare_v31 as fixture
        integration=accepted_s1.integration_evidence(fixture.IntegratedTests.folder)
        verify_bindings(methods)
        if specification()!=spec:raise ValueError('Frozen activation changed during acceptance')
        report=dict(status='v31_C1_S1_real_entry_synthetic_accepted',created_utc=datetime.now(timezone.utc).isoformat(),
            tests_run=result.testsRun,failures=0,errors=0,skipped=0,seconds=perf_counter()-start,suites=list(SUITES),
            methods=methods,log=describe(folder/'tests.log'),specification=describe(ROOT/SPEC),
            core_acceptance=spec['parent_acceptance'],fingerprint_scheme=core.SCHEME,
            passed_test_ids=result.passed,parent_required_cases=70,parent_case_to_passed_tests=accepted_s1.COVERAGE,
            integration=integration,environment=environment(),gates=spec['gates'],real_runs=0,
            interpretation='Artificial new real-entry worker/publisher tests plus unchanged S1/new-old regressions. No real48 measurement yet.')
        public_json(ROOT/ACCEPT,report,exclusive=True)
        print(dict(tests=result.testsRun,real_runs=0,seconds=report['seconds']))


def accepted(spec):
    value=read(ROOT/ACCEPT)
    if (value['status']!='v31_C1_S1_real_entry_synthetic_accepted' or value['specification']!=describe(ROOT/SPEC)
            or value['core_acceptance']!=spec['parent_acceptance'] or value['fingerprint_scheme']!=core.SCHEME
            or value['methods']!=[describe(ROOT/p) for p in METHODS] or value['suites']!=list(SUITES)
            or value['parent_case_to_passed_tests']!=accepted_s1.COVERAGE or value['parent_required_cases']!=70
            or any(value[k]!=0 for k in ('failures','errors','skipped','real_runs'))
            or value['environment']!=environment() or value['gates']!=spec['gates']):raise ValueError('Unchanged S1 real entry must pass synthetic acceptance')
    expected=accepted_s1.test_ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if Counter(value['passed_test_ids'])!=Counter(expected) or value['tests_run']!=len(value['passed_test_ids']):
        raise ValueError('Acceptance lost a selected test success')
    accepted_s1.validate_coverage(value['passed_test_ids'])
    verify_bindings([*value['methods'],value['log'],*value['integration']['evidence']])
    return value


def source_contract():
    spec=specification();receipt=accepted(spec);parent=read(ROOT/spec['parent_acceptance']['path'])
    records={}
    for item in [*spec['inherited_sources'],*spec['evidence'],*receipt['methods'],receipt['log'],
                 *receipt['integration']['evidence'],describe(ROOT/SPEC),describe(ROOT/frozen.SEAL),describe(ROOT/ACCEPT)]:
        if records.get(item['path'],item)!=item:raise ValueError('Conflicting source identity')
        records[item['path']]=item
    methods={x['path']:x for x in [*spec['original_context_methods'],*parent['methods'],*receipt['methods']]}
    if any(methods.get(x['path'])!=x for x in spec['original_context_methods']):
        raise ValueError('Original per-borrow method scope changed')
    dependencies=dict(zip(('counts','catalog','config','model'),spec['context_inputs']))
    meta=dict(cohort=spec['cohort'],schedule=spec['schedule'],context=dict(dependencies=dependencies,methods=[methods[k] for k in sorted(methods)]),
        environment=environment(),gates=spec['gates'],fingerprint_scheme=core.SCHEME,
        core_specification=spec['parent_specification'],core_acceptance=spec['parent_acceptance'],
        specification=describe(ROOT/SPEC),acceptance=describe(ROOT/ACCEPT))
    binding=read(ROOT/meta['cohort']['old_run'])['binding']
    if binding['sources']!=spec['original_binding_sources']:raise ValueError('Original15 binding changed')
    result=[records[k] for k in sorted(records)];core.context_contract(dict(sources=result,metadata=meta),binding)
    return result,meta


def contract(request):
    old._check_window(request);core.require_scheme(request);records,meta=source_contract()
    if request['sources']!=records or request['metadata']!=meta:raise ValueError('Real request differs from the accepted S1 activation')
    return meta


def folder_path(folder):
    folder=Path(folder).resolve()
    if folder.parent!=PRIVATE.resolve() or not folder.name.startswith('knn-v31-s1-'):
        raise ValueError('Expected a direct S1 real-window namespace')
    return folder


def _real_result_write(path,value):
    if Path(path).name=='audited_result.json':
        if value['status']!='v30_C1_S1_independent_synthetic_audit_complete':raise ValueError('Unexpected S1 audit implementation')
        # Executed inside the original publisher.result_write span. Only the
        # activation label changes; every frozen audit check remains intact.
        value['status']='v31_C1_S1_independent_real_audit_complete'
    return write(path,value)


audit_saved_runs=_clone(core.audit_saved_runs,write=_real_result_write)
run_worker=core.run_worker
run_publisher=_clone(core.run_publisher,audit_saved_runs=audit_saved_runs)
run_pipeline=core.run_pipeline


def worker(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request)
    return run_worker(folder,request,lambda:old.inputs(request))


def publisher(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request)
    return run_publisher(folder,request)


def pipeline(folder):
    folder=folder_path(folder);request=read(folder/'request.json');contract(request)
    return run_pipeline(folder,request,{k:[sys.executable,'-B','-m',MODULE,'--'+k,str(folder)] for k in ('worker','publisher')})


def audit_completed(folder,request):
    result,completion,exits,pub,load=core.audit_completed(folder,request)
    if (result['status']!='v31_C1_S1_independent_real_audit_complete'
            or result['cache']['fingerprint_scheme']!=core.SCHEME):raise ValueError('Wrong independently published S1 result')
    return result,completion,exits,pub,load


def release(folder):
    folder=folder_path(folder);request=read(folder/'request.json');meta=contract(request)
    result,completion,exits,pub,load=audit_completed(folder,request)
    report=dict(status='v31_C1_S1_original48_real_comparison_measured',namespace=folder.relative_to(ROOT).as_posix(),
        specification=meta['specification'],acceptance=meta['acceptance'],core_acceptance=meta['core_acceptance'],
        fingerprint_scheme=core.SCHEME,schedule=meta['schedule'],supervisor=completion,results=result,decision=result['decision'],
        publisher_observation=pub,publisher_load=load,
        worker_source_observations={p:read(folder/p/'observation.json') for p in ('worker_initial_hash','worker_final_hash')},
        process_wall_seconds={k:v['seconds'] for k,v in exits.items()},gates=check_gates(),
        scope=dict(real_runs=14,engineering_checks=672,new_keys=0,new_real_fit_validation_bootstrap=0,
            full_validation_complete=False,reserved_test='locked'),T_plan=None,
        evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()],
        interpretation='Known-validation engineering comparison of fresh R and C1-S1 in the same window. All warmups retained in cold-inclusive sums. Not a population or reserved-test score. No Ollama token/GPU speed measurement.')
    if report['gates']!=meta['gates']:raise ValueError('Scientific gates changed after completion')
    if (ROOT/REPORT).exists():
        existing=read(ROOT/REPORT);verify_bindings(existing['evidence'])
        if existing!=report:raise ValueError('Immutable report differs from re-audit')
        receipt=read(ROOT/RELEASE);verify_bindings([receipt['report']])
        seconds=receipt['public_serialization_seconds']
        if (receipt['report']!=describe(ROOT/REPORT) or receipt['status']!='v31_C1_S1_public_report_released'
                or receipt['deadline_utc']!=request['deadline_utc'] or type(seconds) not in (int,float)
                or not math.isfinite(seconds) or seconds<0):raise ValueError('Public report release seal differs')
    else:
        start=perf_counter();public_json(ROOT/REPORT,report,exclusive=True)
        public_json(ROOT/RELEASE,dict(status='v31_C1_S1_public_report_released',report=describe(ROOT/REPORT),
            public_serialization_seconds=perf_counter()-start,deadline_utc=request['deadline_utc']),exclusive=True)
    print(dict(report=REPORT,seconds=completion['seconds'],checks=672,adopted=report['decision']['adopted']))
    return report


def measure():
    with exclusive():
        if (ROOT/REPORT).exists():raise FileExistsError('Use --release for the completed S1 window')
        for p in PRIVATE.glob('knn-v31-s1-*/request.json'):raise FileExistsError('Existing window forbids automatic retry: '+str(p.parent))
        sources,meta=source_contract();folder=PRIVATE/('knn-v31-s1-'+uuid4().hex)
        print('V31 supervised namespace: '+folder.relative_to(ROOT).as_posix(),flush=True)
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
