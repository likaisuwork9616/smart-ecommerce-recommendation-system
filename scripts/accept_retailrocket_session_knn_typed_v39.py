"""Sequential V39 differential, inherited safeguards and independent publication acceptance."""
import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import math
import json
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings, environment, check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts import freeze_retailrocket_session_knn_typed_v38 as design
from scripts import accept_retailrocket_session_knn_typed_core_v39 as core_accept
from scripts import accept_retailrocket_session_knn_snapshot_v30 as inherited
from scripts import retailrocket_session_knn_typed_publication_v39 as pub
from scripts import retailrocket_session_knn_entry_v34 as common
from scripts.retailrocket_session_knn_reuse_v27 import canonical

REPORT='reports/stage12/retailrocket_session_knn_v39_typed_acceptance_20261110.json'
SEAL='reports/stage12/retailrocket_session_knn_v39_typed_acceptance_seal_20261110.json'
METHOD='scripts/accept_retailrocket_session_knn_typed_v39.py'
C='tests.test_retailrocket_session_knn_typed_v39.'
A='tests.test_retailrocket_session_knn_typed_adapter_v39.'
P='tests.test_retailrocket_session_knn_typed_publication_v39.IntegratedTests.'
SUITES=('tests.test_retailrocket_session_knn_typed_v39',
        'tests.test_retailrocket_session_knn_typed_adapter_v39',
        'tests.test_retailrocket_session_knn_typed_publication_v39',
        'tests.test_retailrocket_session_knn_snapshot_v30',
        'tests.test_retailrocket_session_knn_entry_v34',*design.SUITES)
COUNT=A+'SchemeTests.test_15_live_snapshot_checks_and22_digests_retained'
SOURCE=P+'test_contract_preserves_original_scope_and_rejects_missing_direct_source'
PUB=P+'test_independent_original_canonical_authority_and_policy_are_exact'
BOUNDARY=A+'LateAuthorityTests.test_source_reference_build_and_late_order_stay_inside_original_cold_boundary'
CLEAN=A+'LateAuthorityTests.test_late_unsupported_utf8_and_cycle_errors_clear_all_reference_state'
MIX=A+'SchemeTests.test_policy_request_use_and_complete_receipt_cannot_mix'
SCOPE=dict(comparator_implemented=True,synthetic_integration_accepted=True,new_real_context_replays=0,
           new_real_query_runs=0,new_model_fits=0,full_validation_complete=False,reserved_test='locked',
           covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232)
OPERATIONS=dict(generic_canonical=39,full_typed_comparisons=2,reference_roots=2,
                live_snapshot_fingerprints=15,identity_key_digests=7,total_digests=22)


def coverage():
    rows={
        'authority':[(BOUNDARY,PUB),(C+'ReferenceTests.test_reference_is_tuple_only_nonserializable_and_factory_admitted',),
                     (BOUNDARY,P+'test_cold_pre_and_post_guards_inside_complete_entry'),
                     (A+'LateAuthorityTests.test_reference_replacement_before_late_rejects_without_fallback',MIX,
                      P+'test_raw_source_canonical_reference_and_policy_tamper_reach_semantic_rejection')],
        'scalar':[(C+'ScalarTests.test_exact_scalar_and_string_vectors',C+'ScalarTests.test_type_and_encoding_inequality_vectors'),
                  (C+'ScalarTests.test_exact_scalar_and_string_vectors',),
                  (C+'BoundaryTests.test_integer_limit_change_and_large_decimal_conversion',),
                  (C+'ScalarTests.test_exact_scalar_and_string_vectors',C+'ScalarTests.test_unsupported_subclasses_and_invalid_values_are_not_equal')],
        'containers':[(C+'GeneratedTests.test_reproducible_nested_equal_and_unequal_graphs',),
                      (C+'TraversalTests.test_proxy_protocol_exact_all_keyscan_sorted_then_getitem',),
                      (C+'GeneratedTests.test_reproducible_nested_equal_and_unequal_graphs',A+'InheritedContextTests.test_changed_complete_support_or_model_receipt'),
                      (C+'TraversalTests.test_shared_acyclic_aliases_are_each_fully_traversed',C+'TraversalTests.test_proxy_protocol_exact_all_keyscan_sorted_then_getitem')],
        'failure':[(C+'ScalarTests.test_unsupported_subclasses_and_invalid_values_are_not_equal',),
                   (C+'TraversalTests.test_ordinary_mismatch_never_skips_invalid_extra_live_tails',),
                   (C+'TraversalTests.test_active_ancestry_rejects_cycles_and_recovers_after_failure',C+'BoundaryTests.test_near_limit_worker_approval_and_public_deep_bytes_rejection',CLEAN),
                   (CLEAN,A+'InheritedAdversarialTests.test_body_exception_cleanup',
                    A+'LateAuthorityTests.test_second_reference_root_build_failure_clears_all_state_and_forbids_retry',
                    A+'LateAuthorityTests.test_original_load_or_prepare_failure_after_reference_build_clears_all_state')],
        'timing':[(A+'LateAuthorityTests.test_persistent_config_change_rejects_before_borrow_and_does_not_compare_model',
                   A+'LateAuthorityTests.test_persistent_model_change_rejects_after_complete_config_and_before_borrow'),
                  (A+'LateAuthorityTests.test_ABA_crossing_late_is_rejected_without_adopting_original_late_B',),
                  (A+'LateAuthorityTests.test_restore_before_late_and_after_late_restore_discrete_guard_boundaries',),
                  (A+'LateAuthorityTests.test_original_prepare_observer_exit_mutation_is_checked_before_borrow',
                   A+'LateAuthorityTests.test_no_new_watch_or_observer_clock_hook_inside_both_late_comparisons',
                   A+'LateAuthorityTests.test_caught_direct_comparator_reentry_via_proxy_read_rejects_outer_worker_before_borrow')],
        'preserved':[(SOURCE,A+'InheritedContextTests.test_different_window_or_process'),
                     (P+'test_every_create_and_post_lock_full_source_check',A+'InheritedContextTests.test_forced_check_after_lock_before_cache_lookup'),
                     (COUNT,A+'InheritedContextTests.test_caller_model_or_config_mutation_rejected'),
                     (PUB,P+'test_all_original_closure_identities_and14_publisher_opens',P+'test_final_log_manifest_covers_buffered_top_level_and_rejects_append_or_new_file')],
        'integration':[(MIX,P+'test_raw_summary_and_mixed_request_policy_rejected_independently'),
                       (PUB,P+'test_raw_late_order_counts_full_walk_and_original_time_boundary_tamper_rejected'),
                       (COUNT,P+'test_no_hidden_cache_preload'),
                       (A+'LateAuthorityTests.test_success_close_releases_both_references_and_expected_bytes',
                        A+'LateAuthorityTests.test_reference_release_in_seventh_finish_is_charged_without_gc',CLEAN)],
        'accounting':[(COUNT,BOUNDARY),(COUNT,),
                      (BOUNDARY,P+'test_cold_pre_and_post_guards_inside_complete_entry',
                       A+'LateAuthorityTests.test_reference_release_in_seventh_finish_is_charged_without_gc'),
                      (C+'GeneratedTests.test_reproducible_nested_equal_and_unequal_graphs',PUB)]}
    result={}
    for group,names in design.REQUIRED.items():
        if len(rows[group])!=len(names):raise ValueError('Exact frozen requirement rows required')
        for name,tests in zip(names,rows[group]):result['v38.'+group+'.'+name]=list(tests)
    if len(result)!=32:raise ValueError('Every V38 requirement must map to actual candidate tests')
    for name,tests in inherited.COVERAGE.items():
        replaced=[]
        for test in tests:
            prefix='tests.test_retailrocket_session_knn_snapshot_integration_v30.'
            if test.startswith(prefix):
                tail=test[len(prefix):]
                test=(P+tail[len('IntegratedTests.'):] if tail.startswith('IntegratedTests.') else A+tail)
            replaced.append(test)
        result['v30.'+name]=replaced
    # V36 source-anchor design is inherited. Only its two serialization-count
    # requirements are superseded by V38's complete four-plus-two design.
    v36rows={
        'authority':[(BOUNDARY,),(C+'ReferenceTests.test_reference_is_tuple_only_nonserializable_and_factory_admitted',),
                     (A+'LateAuthorityTests.test_ABA_crossing_late_is_rejected_without_adopting_original_late_B',),(MIX,PUB)],
        'timing':[(A+'InheritedContextTests.test_changed_configuration',),
                  (A+'LateAuthorityTests.test_persistent_config_change_rejects_before_borrow_and_does_not_compare_model',),
                  (A+'LateAuthorityTests.test_ABA_crossing_late_is_rejected_without_adopting_original_late_B',),
                  (A+'LateAuthorityTests.test_restore_before_late_and_after_late_restore_discrete_guard_boundaries',)],
        'typed_content':[(C+'ScalarTests.test_type_and_encoding_inequality_vectors',),
                         (C+'ScalarTests.test_exact_scalar_and_string_vectors',),
                         (C+'GeneratedTests.test_reproducible_nested_equal_and_unequal_graphs',),(CLEAN,)],
        'failure':[(A+'LateAuthorityTests.test_original_load_or_prepare_failure_after_reference_build_clears_all_state',
                    A+'InheritedAdversarialTests.test_body_exception_cleanup'),
                   (CLEAN,),(A+'InheritedContextTests.test_different_window_or_process',SOURCE),
                   (A+'InheritedContextTests.test_caller_model_or_config_mutation_rejected',)],
        'unchanged_boundaries':[(P+'test_every_create_and_post_lock_full_source_check',),(SOURCE,),
                                (COUNT,),(PUB,P+'test_final_log_manifest_covers_buffered_top_level_and_rejects_append_or_new_file')],
        'accounting':[(COUNT,),(COUNT,),(BOUNDARY,P+'test_cold_pre_and_post_guards_inside_complete_entry'),(P+'test_no_hidden_cache_preload',)]}
    for group,names in design.parent.prior.CASES.items():
        for name,tests in zip(names,v36rows[group]):result['v36.'+group+'.'+name]=list(tests)
    result.update({'v34.direct_methods':[SOURCE],
                   'v34.quiet_top_level_and_closed_streams':[P+'test_final_log_manifest_covers_buffered_top_level_and_rejects_append_or_new_file'],
                   'v34.exact_stopped_manifest_append_and_file_rejection':[P+'test_final_log_manifest_covers_buffered_top_level_and_rejects_append_or_new_file']})
    return result


def methods():
    return common.source_inventory((METHOD,core_accept.METHOD,*pub.SEEDS),dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)


def expected():
    names=inherited.test_ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not names or len(names)!=len(set(names)):raise ValueError('Unique full candidate tests required')
    missing={case:[t for t in tests if t not in names] for case,tests in coverage().items() if any(t not in names for t in tests)}
    if missing:raise ValueError('Required candidate test mapping missing: '+str(missing))
    return names


def base():
    design.audit();core_accept.audit()
    plan,diagnostics=common.quiet_contract(pub.preserved_plan)
    return dict(specification=describe(ROOT/design.SPEC),seal=describe(ROOT/design.SEAL),
        core_acceptance=describe(ROOT/core_accept.REPORT),methods=methods(),suites=list(SUITES),
        case_to_passed_tests=coverage(),new_required_cases=32,inherited_v30_cases=70,inherited_v36_cases=24,v34_cases=3,
        count_supersessions=dict(
            v36_cold_six='V38 retains six complete observations as four canonical plus two typed comparisons.',
            v36_all7_generic41='V38 specifies generic39 plus typed2; snapshot15/digest22 remain.',
            v30_original_generic41='Applicable source/scientific/S1 cases run the new V39 pool; serialization accounting is replaced by V38.'),
        preserved_contract=dict(specification=describe(ROOT/design.parent.prior.SPEC),original_sources=2092,
            original_methods=168,original_binding=15,appended_source_count=len(plan['sources'])-2092,
            appended_method_count=len(plan['methods'])-168,actual_methods=plan['methods'],
            verification='All inherited real descriptors retained exactly by additive union. Synthetic closure/binding counts are separate; no real12GB source rehash or real context replay.'),
        environment=environment(),gates=check_gates(),scope=SCOPE,measured_speedup=None,T_plan=None)


def seal_value():
    return dict(status='v39_full_typed_acceptance_sealed',report=describe(ROOT/REPORT),
                specification=describe(ROOT/design.SPEC),core_acceptance=describe(ROOT/core_accept.REPORT))


def verify_summaries(value):
    if canonical(value['operation_counts'])!=canonical(OPERATIONS):
        raise ValueError('Actual operation summary differs')
    original=read(ROOT/core_accept.REPORT)['differential']
    if canonical(value['differential'])!=canonical(original):
        raise ValueError('Executed differential vectors differ from the sealed same-suite core evidence')
    by_module=dict(Counter('.'.join(t.split('.')[:-2]) for t in value['passed_test_ids']))
    if canonical(value['tests_by_module'])!=canonical(by_module):
        raise ValueError('Per-module executed test counts differ')
    from tests import test_retailrocket_session_knn_typed_publication_v39 as fixture
    folder=pub.folder_path(ROOT/value['integration']['namespace'])
    rebuilt=fixture.integration_evidence(folder)
    if canonical(value['integration'])!=canonical(rebuilt):
        raise ValueError('Complete stopped integration evidence or metadata differs')


def acceptance():
    if (ROOT/REPORT).exists() or (ROOT/SEAL).exists():raise FileExistsError('Immutable full acceptance exists; use --audit')
    value=base();names=expected();folder=PRIVATE/('knn-v39-acceptance-'+uuid4().hex);folder.mkdir();start=perf_counter()
    from tests import test_retailrocket_session_knn_typed_v39 as core_fixture
    core_fixture.reset_evidence()
    with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=inherited.Result).run(
            unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not result.wasSuccessful() or result.skipped or Counter(result.passed)!=Counter(names):
        raise ValueError('Full differential/independent acceptance failed: '+str(folder/'tests.log'))
    if any(not set(tests).issubset(result.passed) for tests in coverage().values()):
        raise ValueError('A mapped requirement did not pass')
    from tests import test_retailrocket_session_knn_typed_adapter_v39 as context_fixture
    from tests import test_retailrocket_session_knn_typed_publication_v39 as publication_fixture
    integration=publication_fixture.integration_evidence();operations=context_fixture.SchemeTests.executed_counts
    if canonical(operations)!=canonical(OPERATIONS):
        raise ValueError('Actual one-cold/six-hit operation counts changed')
    verify_bindings(value['methods'])
    report=dict(value,status='v39_full_late_typed_differential_and_independent_publication_accepted',
        created_utc=datetime.now(timezone.utc).isoformat(),tests_run=result.testsRun,passed_test_ids=result.passed,
        tests_by_module=dict(Counter('.'.join(t.split('.')[:-2]) for t in result.passed)),
        failures=0,errors=0,skipped=0,seconds=perf_counter()-start,log=describe(folder/'tests.log'),
        differential=json.loads(json.dumps(core_fixture.differential_evidence(),ensure_ascii=False)),
        operation_counts=operations,integration=integration,
        pending='A separately frozen and accepted real comparison entry is still required. No adoption or speedup follows from artificial integration.')
    public_json(folder/'candidate_report.json',report,exclusive=True)
    verify_summaries(report)
    report['seconds']=perf_counter()-start
    public_json(ROOT/REPORT,report,exclusive=True)
    public_json(ROOT/SEAL,seal_value(),exclusive=True)
    print(dict(report=REPORT,tests=result.testsRun,new_requirements=32,mapped_requirements=len(coverage()),
               synthetic_checks=672,real_query_runs=0));return report


def audit():
    value=read(ROOT/REPORT);seal=read(ROOT/SEAL)
    if canonical(seal)!=canonical(seal_value()):raise ValueError('Acceptance report seal changed')
    verify_bindings([seal['report'],seal['specification'],seal['core_acceptance']])
    shape=base()
    if (value['status']!='v39_full_late_typed_differential_and_independent_publication_accepted'
            or any(canonical(value[k])!=canonical(v) for k,v in shape.items()) or Counter(value['passed_test_ids'])!=Counter(expected())
            or value['tests_run']!=len(value['passed_test_ids'])
            or any(type(value[k]) is not int or value[k]!=0 for k in ('failures','errors','skipped'))
            or type(value['seconds']) not in (int,float) or not math.isfinite(value['seconds']) or value['seconds']<0):
        raise ValueError('Full typed acceptance changed')
    verify_bindings([*value['methods'],value['log'],*value['integration']['evidence']])
    verify_summaries(value)
    if not value['integration']['independent_processes'] or value['integration']['supervisor']['live_after_cleanup']!=0:
        raise ValueError('Independent stopped publication evidence missing')
    print(dict(audit=True,tests=value['tests_run'],mapped_requirements=len(coverage()),real_query_runs=0))
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance','audit'):mode.add_argument('--'+name,action='store_true')
    args=parser.parse_args()
    if args.acceptance:acceptance()
    else:audit()
