"""C1-S1 synthetic acceptance and sealed evidence audit; no real measurement entry."""
import argparse
from collections import Counter
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timezone
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json
from scripts import freeze_retailrocket_session_knn_serialization_v29 as design
from scripts import run_retailrocket_session_knn_compare_v28 as original
from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as adapter

BASE='reports/stage12/retailrocket_session_knn_v30_snapshot_'
REPORT=BASE+'acceptance_20261110.json'
SPEC_SHA='221f63bbfa21078eedec62f9218dbb294443e4a03698e3a7bb19eb5923659cfd'
METHODS=('scripts/retailrocket_session_knn_snapshot_v30.py','scripts/retailrocket_session_knn_snapshot_adapter_v30.py',
    'scripts/accept_retailrocket_session_knn_snapshot_v30.py','tests/test_retailrocket_session_knn_snapshot_v30.py',
    'tests/test_retailrocket_session_knn_snapshot_integration_v30.py')
SUITES=('tests.test_retailrocket_session_knn_snapshot_v30','tests.test_retailrocket_session_knn_snapshot_integration_v30',
    *original.SUITES,'tests.test_retailrocket_session_knn_serialization_v29')

# Every required case uses a newly executed S1 test; the frozen old suites are
# additional regressions rather than substitutes for exercising the new pool.
COVERAGE={'new.schema.exact_FrozenCatalog_mappingproxy_tuple_types': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_exact_FrozenCatalog_mappingproxy_tuple_types'],
 'new.schema.all_four_fields_present_and_field_order': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_all_four_fields_present_and_field_order'],
 'new.schema.canonical_ASCII_numeric_string_IDs': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_canonical_ASCII_numeric_string_IDs'],
 'new.schema.bool_float_int_not_aliased': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_bool_float_int_not_aliased'],
 'new.schema.nonnegative_counts_and_timestamps': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_nonnegative_counts_and_timestamps'],
 'new.schema.large_integers_not_float_rounded': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_large_integers_not_float_rounded'],
 'new.schema.map_insertion_order_equivalence': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_map_insertion_order_equivalence'],
 'new.schema.tuple_order_duplicates_and_empty_snapshot': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotSchemaTests.test_tuple_order_duplicates_and_empty_snapshot'],
 'new.mutation.changed_first_key_or_value': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_changed_first_key_or_value'],
 'new.mutation.changed_count_key_or_value': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_changed_count_key_or_value'],
 'new.mutation.changed_first_times_value_or_order': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_changed_first_times_value_or_order'],
 'new.mutation.changed_fallback_value_or_order': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_changed_fallback_value_or_order'],
 'new.mutation.scheme_prefix_and_event_version_mismatch': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_scheme_prefix_and_event_version_mismatch',
                                                           'tests.test_retailrocket_session_knn_snapshot_integration_v30.SchemeTests.test_scheme_prefix_and_event_version_mismatch',
                                                           'tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_publisher_semantically_rejects_mixed_schemes'],
 'new.mutation.cached_encoded_bytes_cannot_hide_live_mutation': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_cached_encoded_bytes_cannot_hide_live_mutation',
                                                                 'tests.test_retailrocket_session_knn_snapshot_integration_v30.SchemeTests.test_cached_encoded_bytes_cannot_hide_live_mutation'],
 'new.mutation.truncation_or_omitted_tail_rejected': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_truncation_or_omitted_tail_rejected'],
 'new.mutation.no_sorting_sequences_to_hide_tampering': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_no_sorting_sequences_to_hide_tampering'],
 'new.equivalence.cold_and_six_hits_complete_four_arm_payload_bytes': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.FullVerifierTests.test_cold_and_six_hits_complete_four_arm_payload_bytes'],
 'new.equivalence.Decimal_and_binary64_delta_hex_unchanged': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.FullVerifierTests.test_Decimal_and_binary64_delta_hex_unchanged'],
 'new.equivalence.SQL_workload_and_query_order_unchanged': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.FullVerifierTests.test_SQL_workload_and_query_order_unchanged'],
 'new.equivalence.caller_config_and_complete_support_mutation_rejected': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_changed_configuration',
                                                                          'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_changed_complete_support_or_model_receipt',
                                                                          'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_caller_model_or_config_mutation_rejected'],
 'new.equivalence.original_loader_schema_support_and_clock_rejections': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_header_or_width_error',
                                                                         'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_duplicate_id_or_noncanonical_number',
                                                                         'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_nonpositive_counts_or_support_mismatch',
                                                                         'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_training_clock_violation'],
 'new.equivalence.equal_fields_independent_worker_publisher_fingerprint': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_equal_fields_independent_worker_publisher_fingerprint',
                                                                           'tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_publisher_semantically_rejects_mixed_schemes'],
 'new.equivalence.15_live_snapshot_checks_and22_digests_retained': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.SchemeTests.test_15_live_snapshot_checks_and22_digests_retained'],
 'new.equivalence.identity_key_binding_and_model_canonical_unchanged': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.SchemeTests.test_identity_key_binding_and_model_canonical_unchanged',
                                                                        'tests.test_retailrocket_session_knn_snapshot_integration_v30.SchemeTests.test_15_live_snapshot_checks_and22_digests_retained',
                                                                        'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_accepted_environment_change_rejects',
                                                                        'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_eighth_run_and_incomplete_summary_reject'],
 'new.control.every_create_and_post_lock_full_source_check': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_every_create_and_post_lock_full_source_check'],
 'new.control.all_original_closure_identities_and14_publisher_opens': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_all_original_closure_identities_and14_publisher_opens'],
 'new.control.publisher_new_process_rebuild_no_worker_buffers': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_publisher_new_process_rebuild_no_worker_buffers'],
 'new.control.cold_pre_and_post_guards_inside_complete_entry': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_cold_pre_and_post_guards_inside_complete_entry'],
 'new.control.event_cost_load_cache_payload_tamper_rejects': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_event_cost_load_cache_payload_tamper_rejects'],
 'new.control.all14_pairs_cold_sum_and_adoption_thresholds_fixed': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_all14_pairs_cold_sum_and_adoption_thresholds_fixed'],
 'new.control.separate_validation_JSON_UTF8_SHA_release_timers': ['tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_separate_validation_JSON_UTF8_SHA_release_timers',
                                                                  'tests.test_retailrocket_session_knn_snapshot_integration_v30.SchemeTests.test_separate_validation_JSON_UTF8_SHA_release_timers',
                                                                  'tests.test_retailrocket_session_knn_snapshot_v30.SnapshotMutationTests.test_watch_failure_keeps_failed_observation'],
 'new.control.worker_failure_deadline_resources_existing_request_and_stopped_descendants': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_worker_failure_deadline_resources_existing_request_and_stopped_descendants',
                                                                                            'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_deadline_or_resource_stop',
                                                                                            'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_immutable_acceptance_and_existing_output'],
 'inherited.identity.same_size_changed_content': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_same_size_changed_content'],
 'inherited.identity.same_bytes_different_path': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_same_bytes_different_path',
                                                  'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_cold_dependency_cannot_substitute_an_unbound_same_content_path'],
 'inherited.identity.changed_size': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_changed_size'],
 'inherited.identity.changed_configuration': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_changed_configuration'],
 'inherited.identity.changed_complete_support_or_model_receipt': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_changed_complete_support_or_model_receipt'],
 'inherited.identity.changed_parser_or_prepare_method': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_changed_parser_or_prepare_method'],
 'inherited.identity.different_window_or_process': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_different_window_or_process'],
 'inherited.identity.mtime_only_match_cannot_authorize_hit': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_mtime_only_match_cannot_authorize_hit'],
 'inherited.identity.source_changes_between_create_and_lock': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_source_changes_between_create_and_lock'],
 'inherited.identity.changed_source_on_warm_hit': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_changed_source_on_warm_hit'],
 'inherited.snapshot.parse_exact_sha_verified_buffer': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_parse_exact_sha_verified_buffer'],
 'inherited.snapshot.bytes_change_during_buffer_acquisition': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_bytes_change_during_buffer_acquisition'],
 'inherited.snapshot.header_or_width_error': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_header_or_width_error'],
 'inherited.snapshot.duplicate_id_or_noncanonical_number': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_duplicate_id_or_noncanonical_number'],
 'inherited.snapshot.nonpositive_counts_or_support_mismatch': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_nonpositive_counts_or_support_mismatch'],
 'inherited.snapshot.training_clock_violation': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_training_clock_violation'],
 'inherited.snapshot.map_or_tuple_mutation_rejected': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_map_or_tuple_mutation_rejected'],
 'inherited.snapshot.caller_model_or_config_mutation_rejected': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_caller_model_or_config_mutation_rejected',
                                                                 'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_changed_configuration',
                                                                 'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_changed_complete_support_or_model_receipt'],
 'inherited.snapshot.one_cold_build_six_hits': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_one_cold_build_six_hits'],
 'inherited.snapshot.second_sort_tuple_equivalence_including_ties': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_second_sort_tuple_equivalence_including_ties'],
 'inherited.checkpoint.both_original_full_source_checks_each_run': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_every_create_and_post_lock_full_source_check',
                                                                    'tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_one_cold_build_six_hits'],
 'inherited.checkpoint.forced_check_after_lock_before_cache_lookup': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedContextTests.test_forced_check_after_lock_before_cache_lookup'],
 'inherited.checkpoint.writer_lock_failure': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_writer_lock_failure'],
 'inherited.checkpoint.body_exception_cleanup': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_body_exception_cleanup'],
 'inherited.checkpoint.resume_rejects_previous_process_cache': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_resume_rejects_previous_process_cache'],
 'inherited.checkpoint.deadline_or_resource_stop': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_deadline_or_resource_stop'],
 'inherited.checkpoint.immutable_acceptance_and_existing_output': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.InheritedAdversarialTests.test_immutable_acceptance_and_existing_output'],
 'inherited.publication.new_interpreter_no_worker_snapshot': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_publisher_new_process_rebuild_no_worker_buffers',
                                                              'tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_equal_fields_independent_worker_publisher_fingerprint'],
 'inherited.publication.both_full_closure_checks_all_original_sources': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_all_original_closure_identities_and14_publisher_opens'],
 'inherited.publication.all14_original_store_opens_and_physical_frame_proofs': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_all_original_closure_identities_and14_publisher_opens'],
 'inherited.publication.event_cost_load_or_payload_tamper': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_event_cost_load_cache_payload_tamper_rejects',
                                                             'tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_publisher_semantically_rejects_mixed_schemes'],
 'inherited.publication.publisher_failure_live_descendant_or_expiry_withholds_release': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_worker_failure_deadline_resources_existing_request_and_stopped_descendants',
                                                                                         'tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_event_cost_load_cache_payload_tamper_rejects'],
 'inherited.accounting.cold_build_key_checks_and_digests_inside_entry': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_cold_pre_and_post_guards_inside_complete_entry',
                                                                         'tests.test_retailrocket_session_knn_snapshot_integration_v30.SchemeTests.test_15_live_snapshot_checks_and22_digests_retained'],
 'inherited.accounting.hit_miss_bytes_rows_and_phase_counts': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_hit_miss_bytes_rows_and_phase_counts'],
 'inherited.accounting.same_fine_observers_for_both_arms': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_same_fine_observers_for_both_arms'],
 'inherited.accounting.no_hidden_cache_preload': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_no_hidden_cache_preload'],
 'inherited.accounting.all14_retained_and_both_orders': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_all14_pairs_cold_sum_and_adoption_thresholds_fixed'],
 'inherited.accounting.full_bytes_metrics_delta_hex_and_sql_workload_identical': ['tests.test_retailrocket_session_knn_snapshot_integration_v30.FullVerifierTests.test_cold_and_six_hits_complete_four_arm_payload_bytes',
                                                                                  'tests.test_retailrocket_session_knn_snapshot_integration_v30.FullVerifierTests.test_Decimal_and_binary64_delta_hex_unchanged',
                                                                                  'tests.test_retailrocket_session_knn_snapshot_integration_v30.FullVerifierTests.test_SQL_workload_and_query_order_unchanged',
                                                                                  'tests.test_retailrocket_session_knn_snapshot_integration_v30.IntegratedTests.test_all_original_closure_identities_and14_publisher_opens']}


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
    def addSuccess(self,test):self.passed.append(test.id());super().addSuccess(test)


def sealed_design(full_sources=False):
    if describe(ROOT/design.SPEC)['sha256']!=SPEC_SHA:raise ValueError('Wrong frozen S1 specification')
    design.main(audit=True)
    spec=read(ROOT/design.SPEC)
    if (spec['candidate']['id']!='C1-S1-schema-snapshot-v1' or spec['candidate']['encoding']['scheme']!=codec.SCHEME
            or spec['acceptance']['new_required_cases']!=design.CASES or spec['acceptance']['new_required_case_count']!=32
            or len(spec['inherited_sources'])!=1261 or len(spec['original_binding_sources'])!=15
            or spec['scope']['authorized_real_runs']!=0 or spec['environment']!=environment() or spec['gates']!=check_gates()):
        raise ValueError('Frozen source/scientific/scheme gates changed')
    parent=read(ROOT/spec['parent_real_entry_specification']['path'])
    if (spec['original_binding_sources']!=parent['original_binding_sources']
            or spec['future_comparison']['schedule']!=parent['schedule'] or spec['future_comparison']['decision']!=parent['decision']):
        raise ValueError('Original binding, schedule or decision changed')
    identities={x['path']:x for x in spec['inherited_sources']}
    if len(identities)!=1261 or any(identities.get(x['path'])!=x for x in spec['original_binding_sources']):
        raise ValueError('Original15 binding must remain within the exact1261 source identities')
    expected={'new.'+group+'.'+name for group,values in spec['acceptance']['new_required_cases'].items() for name in values}
    expected|={'inherited.'+group+'.'+name for group,values in spec['acceptance']['inherited_required_cases'].items() for name in values}
    if len(expected)!=70 or set(COVERAGE)!=expected:raise ValueError('All32 new and38 inherited cases need concrete mappings')
    if full_sources:verify_bindings(spec['inherited_sources'])
    return spec


def validate_coverage(passed):
    for name,tests in COVERAGE.items():
        if not tests or len(tests)!=len(set(tests)) or any(not t.startswith(SUITES[:2]) for t in tests):
            raise ValueError('Required cases must exercise new S1 tests: '+name)
        if not set(tests)<=set(passed):raise ValueError('Required case did not pass: '+name)


def test_ids(suite):
    result=[]
    for test in suite:
        result.extend(test_ids(test) if isinstance(test,unittest.TestSuite) else [test.id()])
    return result


def validate_results(passed,count,by_module):
    expected=test_ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    # V29 intentionally imports the old ContextTests again: compare multisets.
    if (Counter(passed)!=Counter(expected) or count!=len(passed)
            or by_module!=dict(Counter('.'.join(t.split('.')[:-2]) for t in passed))):
        raise ValueError('Every selected new and old test must have actually succeeded')
    validate_coverage(passed)


def scope():
    return dict(real_runs=0,new_real_fit_validation_bootstrap=0,full_validation_complete=False,reserved_test='locked',
        covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232)


def operation_counts():
    return dict(generic_canonical=41,live_snapshot_fingerprints=15,identity_key_digests=7,total_digests=22,
        interpretation='Counted by new S1 SchemeTests on one cold plus six hits, not a real48 timing result.')


def original_source_verification(spec):
    return dict(closure_identities=1261,binding_identities=15,
        closure_logical_bytes=sum(x['bytes'] for x in spec['inherited_sources']),
        all_exact_descriptors_verified_before_and_after=True,source_identity_scheme_unchanged=True)


def integration_evidence(folder):
    request=read(folder/'request.json')
    if request['metadata'].get('synthetic_acceptance_only') is not True:raise ValueError('Artificial-only namespace required')
    result,completion,exits,pub,load=adapter.audit_completed(folder,request)
    binding=read(ROOT/request['metadata']['cohort']['old_run'])['binding']['sources']
    count=sum(row['diagnostic']['phases'].get('snapshot.fingerprint',{}).get('calls',0) for row in result['runs'].values())
    if (len(result['runs'])!=14 or count!=15 or result['cache']['hits']!=6 or result['cache']['cold_builds']!=1
            or result['cache']['fingerprint_scheme']!=codec.SCHEME
            or pub['phases']['checkpoint.open']['calls']!=14
            or pub['phases']['publisher.independent_context']['calls']!=1
            or pub['phases']['snapshot.fingerprint']['calls']!=1):raise ValueError('Incomplete S1 synthetic window')
    if exits['worker']['pid']==exits['publisher']['pid'] or exits['worker']['ended_utc']>exits['publisher']['started_utc']:
        raise ValueError('Independent publisher must start after the worker exit')
    return dict(namespace=folder.relative_to(ROOT).as_posix(),synthetic_only=True,retained_runs=14,queries_per_run=48,
        synthetic_saved_checks=672,fingerprint_scheme=codec.SCHEME,live_worker_fingerprints=count,
        independent_publisher_fingerprints=1,independent_context_rebuilds=1,publisher_store_opens=14,
        worker_source_descriptors_per_boundary=len(request['sources']),
        publisher_source_descriptors=pub['source_descriptors']['completed_calls'],binding_sources=len(binding),
        cache=result['cache'],all_phase_trees_recomputed=True,raw_load_recomputed=True,
        supervisor=dict(exit_code=completion['exit_code'],stop_reason=completion['stop_reason'],
            tracked_processes=completion['tracked_processes'],tracked_processes_alive_after_cleanup=completion['tracked_processes_alive_after_cleanup']),
        interpretation='Artificial inputs and models only. Synthetic closure counts are separate from the frozen real1261/15 identities. No real48 timing or speed claim.',
        evidence=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()])


def acceptance():
    with original.exclusive():
        if (ROOT/REPORT).exists():raise FileExistsError('Immutable S1 acceptance already exists')
        spec=sealed_design(full_sources=True);methods=[describe(ROOT/p) for p in METHODS]
        folder=PRIVATE/('knn-v30-s1-tests-'+uuid4().hex);folder.mkdir();start=perf_counter()
        suite=unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
            result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
        if not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-14000:]);raise ValueError('S1 synthetic acceptance failed; preserve all evidence')
        by_module=dict(Counter('.'.join(t.split('.')[:-2]) for t in result.passed))
        validate_results(result.passed,result.testsRun,by_module)
        from tests import test_retailrocket_session_knn_snapshot_integration_v30 as harness
        integration=integration_evidence(harness.IntegratedTests.folder)
        verify_bindings(methods)
        if sealed_design(full_sources=True)!=spec:raise ValueError('Frozen identities changed during acceptance')
        report=dict(status='v30_C1_S1_core_and_independent_publisher_synthetic_accepted',created_utc=datetime.now(timezone.utc).isoformat(),
            specification=describe(ROOT/design.SPEC),seal=describe(ROOT/design.SEAL),methods=methods,log=describe(folder/'tests.log'),
            tests_run=result.testsRun,failures=0,errors=0,skipped=0,seconds=perf_counter()-start,suites=list(SUITES),
            tests_by_module=by_module,
            required_cases=70,new_required_cases=32,inherited_required_cases=38,case_to_passed_tests=COVERAGE,
            passed_test_ids=result.passed,integration=integration,environment=environment(),gates=check_gates(),
            original_source_verification=original_source_verification(spec),operation_counts=operation_counts(),scope=scope(),
            pending_scope='A separately frozen and accepted real comparison entry is still required. This CLI only accepts artificial cases and audits their saved evidence.',
            measured_speedup=None,T_plan=None)
        public_json(ROOT/REPORT,report,exclusive=True)
        print(dict(report=REPORT,tests=result.testsRun,required_cases=70,synthetic_checks=672,real_runs=0,seconds=report['seconds']))


def audit():
    spec=sealed_design(full_sources=True);report=read(ROOT/REPORT)
    verify_bindings([report['specification'],report['seal'],*report['methods'],report['log'],*report['integration']['evidence']])
    if (report['status']!='v30_C1_S1_core_and_independent_publisher_synthetic_accepted'
            or report['suites']!=list(SUITES) or report['methods']!=[describe(ROOT/p) for p in METHODS]
            or report['specification']!=describe(ROOT/design.SPEC) or report['seal']!=describe(ROOT/design.SEAL)
            or report['case_to_passed_tests']!=COVERAGE or report['required_cases']!=70
            or report['new_required_cases']!=32 or report['inherited_required_cases']!=38
            or any(report[k]!=0 for k in ('failures','errors','skipped'))
            or report['scope']!=scope() or report['operation_counts']!=operation_counts()
            or report['original_source_verification']!=original_source_verification(spec)
            or report['measured_speedup'] is not None or report['T_plan'] is not None
            or report['environment']!=environment() or report['gates']!=spec['gates']):raise ValueError('S1 acceptance changed')
    validate_results(report['passed_test_ids'],report['tests_run'],report['tests_by_module'])
    if report['integration']!=integration_evidence(ROOT/report['integration']['namespace']):raise ValueError('Re-audited S1 evidence differs')
    print(dict(status=report['status'],tests=report['tests_run'],required_cases=70,real_runs=0,audit=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance',action='store_true');mode.add_argument('--audit',action='store_true')
    if parser.parse_args().audit:audit()
    else:acceptance()
