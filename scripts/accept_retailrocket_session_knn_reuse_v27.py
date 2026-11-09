"""C1 synthetic acceptance only. Real measurement requires a separately gated entry."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.freeze_retailrocket_session_knn_reuse_v26 import SPEC,SEAL,CASES
from scripts.retailrocket_session_knn_sources_v24 import summarize_events

SPEC_SHA='5d3bad04dcdead2d86201636f11194de00d18a3ddab57d6bf6607b7e27206f8d'
BASE='reports/stage12/retailrocket_session_knn_v27_reuse_'
REPORT=BASE+'acceptance_20261109.json'
PRIOR_DRAFT='shop-mysql-runtime/verification/knn-v27-c1-tests-941fa9ea44e84c94be9f5e850fde3a47/superseded_draft/acceptance_initial.json'
PRIVATE=ROOT/'shop-mysql-runtime/verification'
METHODS=('scripts/retailrocket_session_knn_reuse_v27.py','scripts/retailrocket_session_knn_reuse_audit_v27.py',
    'scripts/accept_retailrocket_session_knn_reuse_v27.py','tests/test_retailrocket_session_knn_reuse_v27.py',
    'tests/test_retailrocket_session_knn_reuse_acceptance_v27.py')
SUITES=('tests.test_retailrocket_session_knn_reuse_v27','tests.test_retailrocket_session_knn_reuse_acceptance_v27',
    'tests.test_retailrocket_session_knn_sources_v24','tests.test_retailrocket_session_knn_sources_v25',
    'tests.test_retailrocket_session_knn_detailed_cost_v6','tests.test_retailrocket_session_knn_priority_v23')
FOCUSED=SUITES[0]+'.ContextTests.';ADVERSARIAL=SUITES[1]+'.AdversarialTests.';INTEGRATED=SUITES[1]+'.IntegratedTests.'
COVERAGE={name:(FOCUSED if name in {
    'same_bytes_different_path','changed_configuration','changed_complete_support_or_model_receipt','different_window_or_process',
    'source_changes_between_create_and_lock','changed_source_on_warm_hit','map_or_tuple_mutation_rejected',
    'caller_model_or_config_mutation_rejected','one_cold_build_six_hits','forced_check_after_lock_before_cache_lookup'} else
    INTEGRATED if name in CASES['publication'] or name in CASES['accounting'][:-1] else ADVERSARIAL)+'test_'+name
    for values in CASES.values() for name in values}
COVERAGE['both_original_full_source_checks_each_run']=FOCUSED+'test_one_cold_build_six_hits'
COVERAGE['full_bytes_metrics_delta_hex_and_sql_workload_identical']=SUITES[0]+'.FullVerifierTests.test_full_bytes_metrics_delta_hex_and_sql_workload_identical'


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
    def addSuccess(self,test):self.passed.append(test.id());super().addSuccess(test)


def sealed_design():
    seal=read(ROOT/SEAL);verify_bindings([seal['specification'],*seal['evidence']])
    spec=read(ROOT/SPEC)
    if (describe(ROOT/SPEC)['sha256']!=SPEC_SHA or spec['scope']['authorized_real_runs']!=0
            or spec['synthetic_acceptance']['required_cases']!=CASES or spec['environment']!=environment()
            or spec['gates']!=check_gates()):raise ValueError('Original sealed C1-only design changed')
    return spec


def integration_evidence():
    from tests import test_retailrocket_session_knn_reuse_acceptance_v27 as harness
    folder=harness.IntegratedTests.folder;result=harness.release(folder)
    request=read(folder/'request.json');completion=read(folder/'supervisor_completion.json')
    _,pub=harness.supervisor.check_observation(folder/'publisher')
    events=read(folder/'publisher/events.json')
    evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]
    binding=read(ROOT/request['metadata']['cohort']['old_run'])['binding']['sources']
    return dict(namespace=folder.relative_to(ROOT).as_posix(),synthetic_only=True,retained_runs=14,
        queries_per_run=48,synthetic_saved_checks=672,independent_context_rebuilds=pub['phases']['publisher.independent_context']['calls'],
        worker_source_descriptors_per_boundary=len(request['sources']),publisher_source_descriptors=pub['source_descriptors']['completed_calls'],
        publisher_store_opens=pub['phases']['checkpoint.open']['calls'],binding_sources=len(binding),cache=result['cache'],
        supervisor=dict(exit_code=completion['exit_code'],stop_reason=completion['stop_reason'],
            tracked_processes=completion['tracked_processes'],tracked_processes_alive_after_cleanup=completion['tracked_processes_alive_after_cleanup']),
        all_phase_trees_recomputed=True,artificial_telemetry_padding_seconds_per_run=.45,
        interpretation='All inputs/models are artificial. Padding only ensures telemetry brackets. No real48 timing or speed claim.',evidence=evidence)


def acceptance():
    if (ROOT/REPORT).exists():raise FileExistsError('Immutable C1 acceptance already exists')
    spec=sealed_design();methods=[describe(ROOT/p) for p in METHODS]
    folder=PRIVATE/('knn-v27-c1-tests-'+uuid4().hex);folder.mkdir()
    suite=unittest.defaultTestLoader.loadTestsFromNames(SUITES);start=perf_counter()
    with (folder/'tests.log').open('x',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    if not result.wasSuccessful() or result.skipped:
        print((folder/'tests.log').read_text(encoding='utf-8')[-10000:])
        raise ValueError('C1 synthetic acceptance failed; preserve log and artifacts')
    if len(COVERAGE)!=38 or set(COVERAGE)!={x for values in CASES.values() for x in values}:
        raise ValueError('Every sealed case must map to a concrete test')
    missing={k:v for k,v in COVERAGE.items() if v not in result.passed}
    if missing:raise ValueError('Required cases did not pass: '+str(missing))
    integration=integration_evidence();verify_bindings(methods)
    if sealed_design()!=spec:raise ValueError('Sealed original methods changed during acceptance')
    report=dict(status='v27_C1_core_adapter_and_synthetic_publisher_accepted',created_utc=datetime.now(timezone.utc).isoformat(),
        specification=describe(ROOT/SPEC),seal=describe(ROOT/SEAL),methods=methods,log=describe(folder/'tests.log'),
        tests_run=result.testsRun,failures=0,errors=0,skipped=0,seconds=perf_counter()-start,suites=list(SUITES),
        required_cases=38,case_to_passed_test=COVERAGE,passed_test_ids=result.passed,integration=integration,
        environment=environment(),gates=check_gates(),
        scope=dict(real_runs=0,new_real_fit_validation_bootstrap=0,full_validation_complete=False,reserved_test='locked',
            covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232),
        pending_scope='No real C1 comparison is authorized/implemented by this acceptance CLI. A production supervised measurement/release entry needs its own activation specification and acceptance before real48.',
        superseded_unpublished_draft=describe(ROOT/PRIOR_DRAFT),
        superseded_method_snapshots=[describe(p) for p in sorted((ROOT/PRIOR_DRAFT).parent.glob('*.py'))],
        final_review='Added rejection of unbound cold dependencies and malformed unbounded byte descriptors. Original draft receipt/log/method snapshots are preserved privately.',
        measured_speedup=None,T_plan=None)
    public_json(ROOT/REPORT,report,exclusive=True)
    print(dict(report=REPORT,tests=result.testsRun,sealed_cases=38,synthetic_checks=672,real_runs=0,seconds=report['seconds']))


def audit():
    sealed_design();report=read(ROOT/REPORT)
    verify_bindings([report['specification'],report['seal'],*report['methods'],report['log'],*report['integration']['evidence'],
        report['superseded_unpublished_draft'],*report['superseded_method_snapshots']])
    if report['case_to_passed_test']!=COVERAGE or not set(COVERAGE.values())<=set(report['passed_test_ids']):
        raise ValueError('Required case coverage changed')
    if report['scope']['real_runs']!=0 or report['measured_speedup'] is not None:raise ValueError('Unexpected real execution claim')
    print(dict(status=report['status'],tests=report['tests_run'],sealed_cases=38,real_runs=0,audit=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance',action='store_true');mode.add_argument('--audit',action='store_true')
    if parser.parse_args().audit:audit()
    else:acceptance()
