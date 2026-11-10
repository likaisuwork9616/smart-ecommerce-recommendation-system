"""Inventory saved cold canonical roles and seal a temporal-guarded design only."""
import argparse
from collections import Counter
from datetime import datetime,timezone
from statistics import median
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json
from scripts import run_retailrocket_session_knn_diagnostics_v35 as parent
from scripts import run_retailrocket_session_knn_sources_v25 as old

BASE='reports/stage12/retailrocket_session_knn_v36_canonical_'
INVENTORY=BASE+'inventory_20261110.json';SPEC=BASE+'specification_20261110.json';SEAL=BASE+'seal_20261110.json'
METHOD='scripts/freeze_retailrocket_session_knn_canonical_v36.py'
TEST='tests/test_retailrocket_session_knn_canonical_v36.py'
SUITE='tests.test_retailrocket_session_knn_canonical_v36'
ROLES=('live_config_initial','source_config_initial','live_model_initial','source_model_initial',
    'live_config_after_load_prepare','live_model_after_load_prepare')
CASES={
 'authority':['four_initial_live_source_canonical_checks_retained','immutable_verified_source_bytes_only',
    'no_mutable_alias_or_new_live_baseline','mixed_policy_request_event_receipt_rejected'],
 'timing':['changed_before_initial_compare_rejected','persistent_init_mutation_rejected_before_borrow',
    'ABA_across_original_late_boundary_rejected','restore_before_late_boundary_no_continuous_detection_claim'],
 'typed_content':['bool_int_and_int_float_not_aliased','finite_float_hex_and_signed_zero_preserved',
    'list_tuple_map_sequence_and_complete_support_preserved','late_NaN_custom_and_unencodable_content_rejected_before_borrow'],
 'failure':['original_load_or_prepare_failure_poison','late_anchor_mismatch_clears_prepared_key_expected',
    'changed_sources_methods_owner_window_no_fallback','postborrow_live_config_model_mutation_rejected'],
 'unchanged_boundaries':['original15_create_and_postlock_full_checks','all_original_and_direct_method_identities_append_only',
    'one_cold_six_hits_fifteen_live_snapshot_checks','independent_publisher_rebuild_and_stopped_log_seal'],
 'accounting':['cold_six_canonical_calls_safe_path','all7_generic41_and_snapshot15_and_digest22_retained',
    'full_call_cold_and_final_guards_inside_entry','no_preload_crossworker_cache_or_claimed_saved_point392_seconds']}


def observations():
    report=read(ROOT/parent.REPORT);release=read(ROOT/parent.RELEASE)
    if release['report']!=describe(ROOT/parent.REPORT):raise ValueError('Original measured report seal differs')
    verify_bindings([release['report'],report['specification'],report['acceptance']])
    folder=ROOT/report['namespace'];request_record=[r for r in report['evidence'] if r['path']==report['namespace']+'/request.json']
    if len(request_record)!=1:raise ValueError('One sealed diagnostic request required')
    verify_bindings(request_record);request=read(folder/'request.json');plan=read(ROOT/parent.SPEC)['plan']
    if len(request['sources'])!=2092 or len(request['metadata']['context']['methods'])!=168 or len(plan['binding_sources'])!=15:
        raise ValueError('Expected the retained current source/method/binding identities')
    rows=[];evidence=[];retained=[];formal=[]
    for label in ('cold_warm','cold_1','cold_2','cold_3'):
        root=folder/label
        required=[(root/name).relative_to(ROOT).as_posix() for name in ('result.json','events.json','observation.json')]
        records=[r for r in report['evidence'] if r['path'] in required]
        if len(records)!=3:raise ValueError('Three original sealed cold files required')
        verify_bindings(records)
        events,summary=old.check_observation(root);result=read(root/'result.json')
        if result!=report['results']['cold'][label]['result']:raise ValueError('Original published cold result differs')
        if summary!=report['results']['cold'][label]['diagnostic']:raise ValueError('Saved canonical tree differs')
        selected=[e for e in events if e['phase'] in ('cold.canonical.compare','cold.canonical.expected')]
        if [e['metadata']['ordinal'] for e in selected]!=list(range(1,7)):raise ValueError('Six original cold canonical observations required')
        values=[]
        for ordinal,event in enumerate(selected,1):
            if event['phase']!=('cold.canonical.compare' if ordinal<=4 else 'cold.canonical.expected') or not event['completed']:
                raise ValueError('Cold canonical role/order differs')
            seconds=(event['end_ns']-event['start_ns'])/1e9;values.append(seconds)
            rows.append(dict(label=label,warmup=label=='cold_warm',ordinal=ordinal,role=ROLES[ordinal-1],seconds=seconds,
                encoded_bytes_captured=ordinal>=5,encoded_identity=(result['expected_config'] if ordinal==5 else result['expected_model']) if ordinal>=5 else None))
        retained.append(dict(config=result['expected_config'],model=result['expected_model']))
        if label!='cold_warm':formal.append(dict(label=label,initial_four_seconds=sum(values[:4]),late_two_seconds=sum(values[4:])))
        evidence.extend(describe(root/name) for name in ('result.json','events.json','observation.json'))
    if any(x!=retained[0] for x in retained):raise ValueError('Retained canonical identities changed across original cycles')
    return dict(inputs=[describe(ROOT/parent.REPORT),describe(ROOT/parent.RELEASE),*request_record],evidence=evidence,
        methods=[describe(ROOT/p) for p in ('scripts/retailrocket_session_knn_reuse_v27.py','scripts/retailrocket_session_knn_diagnostics_v35.py',
            'scripts/run_retailrocket_session_knn_diagnostics_v35.py')],observations=rows,formal_cycles=formal,
        formal_role_medians={role:median(x['seconds'] for x in rows if not x['warmup'] and x['role']==role) for role in ROLES},
        initial_four_seconds_median=median(x['initial_four_seconds'] for x in formal),late_two_seconds_median=median(x['late_two_seconds'] for x in formal),
        retained_canonical_identities=retained[0],retained_bytes=sum(x['bytes'] for x in retained[0].values()),
        source_contract=dict(request=request_record[0],sources=request['sources'],methods=request['metadata']['context']['methods'],
            original_sources=plan['original_sources'],original_methods=plan['original_methods'],binding=plan['binding_sources'],
            dependencies=request['metadata']['context']['dependencies']),
        limitation='First four canonical outputs were not captured separately in V35. Late byte identities are not relabelled as early measured bytes. Timings are instrumented replay observations, not a removable or guaranteed saving.')


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())


def ids(suite):
    return [name for test in suite for name in (ids(test) if isinstance(test,unittest.TestSuite) else [test.id()])]


def inventory():
    if (ROOT/INVENTORY).exists():raise FileExistsError('Immutable inventory exists; use --audit')
    value=observations();methods=[describe(ROOT/METHOD),describe(ROOT/TEST)]
    folder=PRIVATE/('knn-v36-counterexamples-'+uuid4().hex);folder.mkdir();start=perf_counter()
    expected=ids(unittest.defaultTestLoader.loadTestsFromName(SUITE))
    with (folder/'tests.log').open('x',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromName(SUITE))
    if not result.wasSuccessful() or result.skipped or Counter(result.passed)!=Counter(expected):raise ValueError('Original temporal counterexamples failed')
    verify_bindings(methods)
    public_json(ROOT/INVENTORY,dict(status='v36_saved_canonical_costs_and_original_guard_counterexamples_inventoried',
        created_utc=datetime.now(timezone.utc).isoformat(),analysis=value,methods=methods,
        counterexamples=dict(tests_run=result.testsRun,passed_test_ids=result.passed,failures=0,errors=0,skipped=0,
            log=describe(folder/'tests.log'),seconds=perf_counter()-start,
            interpretation='Original tiny C1 temporal guards only. No candidate implementation or acceptance; early-byte equality is an explicitly unsafe rule comparison.'),
        scope=dict(candidate_implemented=False,candidate_tests_run=0,new_real_context_replays=0,new_query_runs=0,
            full_validation_complete=False,reserved_test='locked'),measured_speedup=None,T_plan=None),exclusive=True)
    print(dict(inventory=INVENTORY,original_guard_tests=result.testsRun,candidate_tests_run=0,new_query_runs=0))


def audit_inventory():
    value=read(ROOT/INVENTORY);a=value['analysis'];verify_bindings([*value['methods'],value['counterexamples']['log'],*a['inputs'],*a['evidence'],*a['methods']])
    if a!=observations() or value['methods']!=[describe(ROOT/METHOD),describe(ROOT/TEST)]:raise ValueError('Inventory methods/evidence changed')
    counter=value['counterexamples'];expected=ids(unittest.defaultTestLoader.loadTestsFromName(SUITE))
    if (value['status']!='v36_saved_canonical_costs_and_original_guard_counterexamples_inventoried'
            or value['scope']!=dict(candidate_implemented=False,candidate_tests_run=0,new_real_context_replays=0,new_query_runs=0,
                full_validation_complete=False,reserved_test='locked')
            or value['measured_speedup'] is not None or value['T_plan'] is not None
            or counter['tests_run']!=len(counter['passed_test_ids']) or counter['tests_run']!=6
            or any(type(counter[k]) is not int or counter[k]!=0 for k in ('failures','errors','skipped'))
            or Counter(counter['passed_test_ids'])!=Counter(expected)):
        raise ValueError('Original guard counterexample coverage changed')
    return value


def design(inv):
    a=inv['analysis'];return dict(status='v36_cold_canonical_reuse_guarded_specification_frozen_not_implemented',
        inventory=describe(ROOT/INVENTORY),evidence=[*inv['methods'],inv['counterexamples']['log'],*a['inputs'],*a['evidence'],*a['methods']],
        candidate=dict(id='C1-S1-cold-canonical-source-anchor-v1',status='design_only_no_speedup_claim',
            admitted_scope='Retain canonical bytes from the exact verified parsed config/model as the fixed authority. Keep all four initial live/source canonical comparisons and both full live canonical checks at the original after-load/prepare boundary before borrow. Reject mismatch and poison; never refresh the authority from changed caller state.',
            order=['original identity/full source/post-lock checks','verified four buffers and source JSON parsing',
                'original ordered short-circuit live/source canonical comparisons for config then model',
                'retain immutable validated source bytes locally; no parsed-object mutable alias',
                'unchanged original load_context and prepare_catalog',
                'full canonical live config/model at original late boundary; compare to validated source bytes before any cache.use/borrow/query',
                'publish expected bytes only after all checks; unchanged snapshot/owner/key setup and pre-use guard',
                'unchanged every final live config/model canonical and complete snapshot check'],
            call_accounting=dict(cold_canonical=6,initial_live_source=4,late_live=2,all7_generic_canonical=41,
                all7_live_snapshot_fingerprints=15,all7_digests=22),
            rejection='Any mismatch or failure clears prepared/expected bytes/key/owner/active; no new mutable baseline, silent fallback or retry.',
            changed_rejection_semantics='Persistent initialization changes are rejected before borrow instead of potentially being absorbed into the old late baseline for that single borrow; the old next identity lookup may still reject. ABA crossing the late boundary must still reject. No claim to detect a transient restored before every existing discrete boundary.',
            byte_rules='Original typed canonical algorithm and complete bytes stay unchanged: bool/int, finite float hex and signed zero, list/tuple, map keys/order, all complete model/support/config fields. Source-file descriptors and S1 snapshot scheme are unchanged.',
            policy_binding='Future new method/spec/request/cache-use/receipt/publisher must bind the source-anchor policy; mixed policies reject.'),
        excluded_performance_branch=dict(cold_canonical_6_to_4='not_authorized_by_this_specification',
            reason='Blind early-byte retention loses the original late temporal observation. A→B at late capture then B→A before final passes the naive early-A rule but the original guard rejects.',
            prerequisites=['Separately specify and prove a closed immutable caller-ownership envelope covering all callees/watch/observer/aliases, without shifting or hiding work.',
                'Or separately specify an algorithm that performs a complete canonical-equivalent typed content comparison at the same late boundary. This is a new algorithm, not pure byte reuse.',
                'Pass the ABA/unsupported-type/failure and complete source/scientific equivalence matrix before permitting any fewer serializations.']),
        preserved=dict(current_sources=a['source_contract']['sources'],current_methods=a['source_contract']['methods'],
            original_sources=a['source_contract']['original_sources'],original_methods=a['source_contract']['original_methods'],
            original_binding=a['source_contract']['binding'],dependencies=a['source_contract']['dependencies'],
            identity='Original binding, complete request/namespace/process/environment/model/config key and exact direct methods; only append future method/spec/acceptance records.',
            integrity='Original create and post-lock source checks; every final live canonical check; 15 live snapshot fingerprints for one cold/six hits; independent publisher rebuild, source checks, scientific bytes/SQL/Decimal/hex and stopped full log manifest.'),
        acceptance=dict(status='future_candidate_not_implemented_or_tested',new_required_cases=CASES,new_required_case_count=24,
            inherited='All applicable C1-S1 70 required cases, V34 direct/log lifecycle, V35 exact-byte/watch/identity/lock regressions. Existing six temporal counterexamples are inventory evidence, not candidate acceptance.',
            gate='No candidate implementation is authorized by this design-only run. Any future implementation uses new files and must first pass concrete mapped tests and commit immutable acceptance before a separately frozen real comparison.'),
        cost_context=dict(late_two_observed_seconds=a['late_two_seconds_median'],retained_bytes=a['retained_bytes'],
            interpretation='The admitted safe path still performs six cold canonical calls. The observed late cost is not an achievable saving; no transfer of replay medians into original48 acceleration.'),
        scope=dict(new_candidate_implementation=False,new_candidate_tests=0,new_real_context_replays=0,new_query_runs=0,
            full_validation_complete=False,reserved_test='locked',covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232),
        environment=environment(),gates=check_gates(),measured_speedup=None,T_plan=None)


def freeze():
    if (ROOT/SPEC).exists() or (ROOT/SEAL).exists():raise FileExistsError('Immutable guarded design exists')
    inv=audit_inventory();value=dict(design(inv),created_utc=datetime.now(timezone.utc).isoformat())
    public_json(ROOT/SPEC,value,exclusive=True)
    public_json(ROOT/SEAL,dict(status='v36_guarded_canonical_design_sealed',specification=describe(ROOT/SPEC),
        inventory=describe(ROOT/INVENTORY),new_candidate_required_cases=24,new_candidate_tests=0,new_query_runs=0),exclusive=True)
    print(dict(specification=SPEC,new_required_cases=24,cold_canonical=6,unsafe_four_call_branch_authorized=False))


def audit():
    inv=audit_inventory()
    if (ROOT/SPEC).exists():
        seal=read(ROOT/SEAL);verify_bindings([seal['specification'],seal['inventory']]);value=read(ROOT/SPEC)
        if {k:v for k,v in value.items() if k!='created_utc'}!=design(inv):raise ValueError('Guarded design changed')
        if seal!=dict(status='v36_guarded_canonical_design_sealed',specification=describe(ROOT/SPEC),inventory=describe(ROOT/INVENTORY),
            new_candidate_required_cases=24,new_candidate_tests=0,new_query_runs=0):raise ValueError('Design seal changed')
    print(dict(audit=True,new_candidate_tests=0,new_query_runs=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('inventory','specification','audit'):mode.add_argument('--'+name,action='store_true')
    args=parser.parse_args()
    if args.inventory:inventory()
    elif args.specification:freeze()
    else:audit()
