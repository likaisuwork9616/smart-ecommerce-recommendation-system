"""Post-exit V31 analysis with one exact, originally bound ancestor attestation."""
import argparse
from collections import Counter
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timezone
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import analyze_retailrocket_session_knn_compare_v31 as old31
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json

METHOD='scripts/analyze_retailrocket_session_knn_compare_v33.py'
TEST='tests/test_retailrocket_session_knn_compare_v33.py'
METHODS=(METHOD,TEST)
SUITE='tests.test_retailrocket_session_knn_compare_v33'
ACCEPT='reports/stage12/retailrocket_session_knn_v33_analysis_acceptance_20261110.json'
OUTPUT=old31.OUTPUT
HELPER='scripts/retailrocket_session_knn_priority_v23.py'
ANCESTOR=dict(path='reports/stage12/retailrocket_session_knn_v23_priority_costs_20261109.json',bytes=102233,
    sha256='74fcccef7a1f048d3fc39eaaa2b1eb7e70d2282c84a1229645b5dbba16dfdf7f')
EXPECTED_HELPER=dict(path=HELPER,bytes=6126,sha256='4c0c365efe97504bc149b6576cc6ba54a49515e45d6d6106242308599672e09a')
DIRECT=tuple(p for p in old31.DEPENDENCIES if p!=HELPER)


def attest(request):
    sources={x['path']:x for x in request['sources']}
    if len(sources)!=len(request['sources']):raise ValueError('Duplicate original source path')
    if sources.get(ANCESTOR['path'])!=ANCESTOR or describe(ROOT/ANCESTOR['path'])!=ANCESTOR:
        raise ValueError('Exact original-window ancestor identity required')
    actual=describe(ROOT/HELPER)
    if actual!=EXPECTED_HELPER:raise ValueError('Expected unchanged priority helper required')
    ancestor=read(ROOT/ANCESTOR['path'])
    helpers=[x for x in ancestor['methods'] if x['path']==HELPER]
    if helpers!=[actual]:raise ValueError('Unique exact ancestor helper binding required')
    if HELPER in sources and sources[HELPER]!=actual:raise ValueError('Conflicting direct helper binding')
    return dict(kind='indirect_provenance',ancestor=ANCESTOR,helper=actual,
        original_direct_source=HELPER in sources,
        priority_runtime_direct_hash=False,priority_per_borrow_method=False,
        interpretation='Ancestor bytes were in the original request.sources; its unique methods binding identifies this helper. V33 is a post-exit analysis method, not an original-window method.')


def build():
    report=read(ROOT/old31.COST)
    request=read(ROOT/report['namespace']/'request.json')
    before=attest(request)
    result=_clone(old31.build,DEPENDENCIES=DIRECT,METHOD=METHOD)()
    after_request=read(ROOT/report['namespace']/'request.json')
    if after_request!=request or attest(after_request)!=before:raise ValueError('Ancestor attestation changed during analysis')
    result['dependencies']=[*result['dependencies'],before['helper']]
    result['source_attestation']=before
    result['frozen_analysis_status']=result['status']
    result['status']='v33_postexit_original48_S1_costs_frames_events_and_load_reconciled'
    result['analysis_stage']='postexit_only'
    result['new_query_verifications']=0
    result['new_real_runs']=0
    result['original_window_analysis_method']=describe(ROOT/old31.METHOD)
    return result


def test_ids(suite):
    return [name for test in suite for name in (test_ids(test) if isinstance(test,unittest.TestSuite) else [test.id()])]


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())


def acceptance():
    if (ROOT/ACCEPT).exists():raise FileExistsError('Immutable V33 acceptance exists')
    methods=[describe(ROOT/p) for p in METHODS]
    folder=PRIVATE/('knn-v33-analysis-acceptance-'+uuid4().hex);folder.mkdir();start=perf_counter()
    suite=unittest.defaultTestLoader.loadTestsFromName(SUITE);expected=test_ids(suite)
    with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    if not result.wasSuccessful() or result.skipped or Counter(result.passed)!=Counter(expected):
        raise ValueError('All V33 lightweight acceptance cases must pass')
    verify_bindings(methods)
    value=dict(status='v33_postexit_analysis_synthetic_accepted',created_utc=datetime.now(timezone.utc).isoformat(),
        methods=methods,log=describe(folder/'tests.log'),suite=SUITE,tests_run=result.testsRun,
        passed_test_ids=result.passed,failures=0,errors=0,skipped=0,new_real_runs=0,
        seconds=perf_counter()-start,analysis_stage='postexit_only')
    public_json(ROOT/ACCEPT,value,exclusive=True)
    print(dict(tests=result.testsRun,new_real_runs=0,acceptance=ACCEPT))
    return value


def accepted():
    value=read(ROOT/ACCEPT)
    expected=test_ids(unittest.defaultTestLoader.loadTestsFromName(SUITE))
    if (value['status']!='v33_postexit_analysis_synthetic_accepted' or value['methods']!=[describe(ROOT/p) for p in METHODS]
            or value['suite']!=SUITE or value['analysis_stage']!='postexit_only'
            or any(value[k]!=0 for k in ('failures','errors','skipped','new_real_runs'))
            or Counter(value['passed_test_ids'])!=Counter(expected) or value['tests_run']!=len(expected)):
        raise ValueError('Exact current V33 analysis methods must pass acceptance')
    verify_bindings([*value['methods'],value['log']])
    return value


def main(audit=False):
    approval=accepted()
    if audit:
        existing=read(ROOT/OUTPUT)
        verify_bindings([*existing['inputs'],existing['method'],*existing['dependencies'],*existing['saved_evidence']])
    elif (ROOT/OUTPUT).exists():raise FileExistsError('Immutable V31 analysis exists; use --audit')
    current=build()
    current['analysis_acceptance']=describe(ROOT/ACCEPT)
    if accepted()!=approval:raise ValueError('Acceptance changed during post-exit analysis')
    if audit:
        if existing!=current:raise ValueError('Immutable analysis differs from saved evidence')
    else:public_json(ROOT/OUTPUT,current,exclusive=True)
    print(dict(report=OUTPUT,audit=audit,checks=current['checks'],adopted=current['decision']['adopted'],analysis_stage=current['analysis_stage']))
    return current


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance',action='store_true');mode.add_argument('--analysis',action='store_true');mode.add_argument('--audit',action='store_true')
    args=parser.parse_args()
    acceptance() if args.acceptance else main(args.audit)
