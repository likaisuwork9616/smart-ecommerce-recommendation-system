"""Accept generic stopped-log and direct-source entry contracts; no real query CLI."""
import argparse
from collections import Counter
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timezone
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import retailrocket_session_knn_entry_v34 as common
from scripts import run_retailrocket_session_knn_compare_v31 as original
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json

REPORT='reports/stage12/retailrocket_session_knn_v34_entry_acceptance_20261110.json'
METHODS=('scripts/retailrocket_session_knn_entry_v34.py','scripts/accept_retailrocket_session_knn_entry_v34.py',
    'tests/test_retailrocket_session_knn_entry_v34.py')
SUITES=('tests.test_retailrocket_session_knn_entry_v34','tests.test_retailrocket_session_knn_compare_v31.ContractTests',
    'tests.test_retailrocket_session_knn_compare_v33')
SCOPE=dict(real_query_runs=0,new_real_fit_validation_bootstrap=0,full_validation_complete=False,reserved_test='locked')


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())


def ids(suite):
    return [name for test in suite for name in (ids(test) if isinstance(test,unittest.TestSuite) else [test.id()])]


def source_audit():
    cost=read(ROOT/original.REPORT);release=read(ROOT/original.RELEASE);verify_bindings([release['report']])
    if release['report']!=describe(ROOT/original.REPORT):raise ValueError('Expected the original sealed real report')
    path=cost['namespace']+'/request.json';record=[x for x in cost['evidence'] if x['path']==path]
    if len(record)!=1:raise ValueError('One sealed original request required')
    verify_bindings(record);request=read(ROOT/path)
    if len(request['sources'])!=1937 or len(request['metadata']['context']['methods'])!=26:
        raise ValueError('Original1937 sources and26 methods must be retained')
    common.quiet_contract(original.contract,request)
    direct=common.source_inventory((*METHODS,'scripts/run_retailrocket_session_knn_compare_v31.py',
        'scripts/analyze_retailrocket_session_knn_compare_v31.py'),dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    original_sources={x['path']:x for x in request['sources']}
    merged=common.merge_methods(request['sources'],direct)
    methods=common.merge_methods(request['metadata']['context']['methods'],direct)
    common.require_direct_sources(methods,merged)
    if any({x['path']:x for x in merged}.get(k)!=v for k,v in original_sources.items()):
        raise ValueError('Original source descriptor replaced')
    return dict(parent_report=describe(ROOT/original.REPORT),original_request=record[0],
        original_sources=len(request['sources']),original_methods=len(request['metadata']['context']['methods']),
        direct_project_sources=direct,added_direct_sources=[x for x in direct if x['path'] not in original_sources],
        merged_sources=len(merged),merged_methods=len(methods),dynamic_target_seeds=list(common.DYNAMIC_TARGET_SEEDS),
        priority_direct=True,old_descriptors_unchanged=True,
        interpretation='Static on-disk import closure plus explicit dynamic targets. No claim that old indirect helpers were directly hashed in the historical window; new contracts must bind and verify them directly.')


def acceptance():
    with original.exclusive():
        if (ROOT/REPORT).exists():raise FileExistsError('Immutable common-entry acceptance exists')
        methods=[describe(ROOT/p) for p in METHODS];sources=source_audit()
        folder=PRIVATE/('knn-v34-tests-'+uuid4().hex);folder.mkdir();start=perf_counter()
        expected=ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
            result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.wasSuccessful() or result.skipped or Counter(expected)!=Counter(result.passed):
            print((folder/'tests.log').read_text(encoding='utf-8')[-14000:]);raise ValueError('Common-entry acceptance failed')
        from tests import test_retailrocket_session_knn_entry_v34 as fixture
        window=fixture.IntegratedTests.folder;request=read(window/'request.json');completion=read(window/'supervisor_completion.json')
        exits={k:original.old.child_exit(window,request,k) for k in ('worker','publisher')}
        seal=common.closed_log_manifest(window,request,completion,exits,expected=fixture.IntegratedTests.seal)
        verify_bindings(methods)
        if source_audit()!=sources:raise ValueError('Direct-source closure changed during acceptance')
        report=dict(status='v34_common_entry_logs_and_direct_sources_synthetic_accepted',created_utc=datetime.now(timezone.utc).isoformat(),
            methods=methods,tests_run=result.testsRun,passed_test_ids=result.passed,suites=list(SUITES),failures=0,errors=0,skipped=0,
            log=describe(folder/'tests.log'),seconds=perf_counter()-start,source_audit=sources,
            integration=dict(namespace=window.relative_to(ROOT).as_posix(),final_seal=seal,
                top_level_contract_exercised=True,buffered_outer_and_publisher_logs_nonempty=True,queries=0),
            environment=environment(),gates=check_gates(),scope=dict(SCOPE),T_plan=None)
        public_json(ROOT/REPORT,report,exclusive=True)
        print(dict(tests=result.testsRun,direct_sources=len(sources['direct_project_sources']),added_direct_sources=len(sources['added_direct_sources']),real_query_runs=0))


def audit():
    report=read(ROOT/REPORT)
    if (report['status']!='v34_common_entry_logs_and_direct_sources_synthetic_accepted'
            or report['methods']!=[describe(ROOT/p) for p in METHODS] or report['suites']!=list(SUITES)
            or any(report[k]!=0 for k in ('failures','errors','skipped'))
            or Counter(report['passed_test_ids'])!=Counter(ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES)))
            or report['tests_run']!=len(report['passed_test_ids']) or report['source_audit']!=source_audit()
            or report['environment']!=environment() or report['gates']!=check_gates()):raise ValueError('Common-entry acceptance changed')
    verify_bindings([*report['methods'],report['log']])
    folder=ROOT/report['integration']['namespace'];request=read(folder/'request.json');completion=read(folder/'supervisor_completion.json')
    common.closed_log_manifest(folder,request,completion,{k:original.old.child_exit(folder,request,k) for k in ('worker','publisher')},expected=report['integration']['final_seal'])
    if (report['scope']!=SCOPE or report['T_plan'] is not None or report['integration']['queries']!=0
            or report['integration']['top_level_contract_exercised'] is not True
            or report['integration']['buffered_outer_and_publisher_logs_nonempty'] is not True):
        raise ValueError('No real query scope or untested lifecycle claim is allowed')
    print(dict(tests=report['tests_run'],real_query_runs=0,audit=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance',action='store_true');mode.add_argument('--audit',action='store_true')
    audit() if parser.parse_args().audit else acceptance()
