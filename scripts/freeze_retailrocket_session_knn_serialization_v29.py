"""Seal a versioned full-snapshot fingerprint design; never implement or run a candidate."""
import argparse
from datetime import datetime,timezone
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.inventory_retailrocket_session_knn_serialization_v29 import OUTPUT as INVENTORY,audit as audit_inventory

BASE='reports/stage12/retailrocket_session_knn_v29_serialization_'
SPEC=BASE+'specification_20261109.json';SEAL=BASE+'seal_20261109.json'
METHOD='scripts/freeze_retailrocket_session_knn_serialization_v29.py'
V28='reports/stage12/retailrocket_session_knn_v28_compare_specification_20261109.json'
CASES={
 'schema':['exact_FrozenCatalog_mappingproxy_tuple_types','all_four_fields_present_and_field_order',
    'canonical_ASCII_numeric_string_IDs','bool_float_int_not_aliased','nonnegative_counts_and_timestamps',
    'large_integers_not_float_rounded','map_insertion_order_equivalence','tuple_order_duplicates_and_empty_snapshot'],
 'mutation':['changed_first_key_or_value','changed_count_key_or_value','changed_first_times_value_or_order',
    'changed_fallback_value_or_order','scheme_prefix_and_event_version_mismatch',
    'cached_encoded_bytes_cannot_hide_live_mutation','truncation_or_omitted_tail_rejected','no_sorting_sequences_to_hide_tampering'],
 'equivalence':['cold_and_six_hits_complete_four_arm_payload_bytes','Decimal_and_binary64_delta_hex_unchanged',
    'SQL_workload_and_query_order_unchanged','caller_config_and_complete_support_mutation_rejected',
    'original_loader_schema_support_and_clock_rejections','equal_fields_independent_worker_publisher_fingerprint',
    '15_live_snapshot_checks_and22_digests_retained','identity_key_binding_and_model_canonical_unchanged'],
 'control':['every_create_and_post_lock_full_source_check','all_original_closure_identities_and14_publisher_opens',
    'publisher_new_process_rebuild_no_worker_buffers','separate_validation_JSON_UTF8_SHA_release_timers',
    'cold_pre_and_post_guards_inside_complete_entry','event_cost_load_cache_payload_tamper_rejects',
    'worker_failure_deadline_resources_existing_request_and_stopped_descendants','all14_pairs_cold_sum_and_adoption_thresholds_fixed']}


def design(inventory,parent,request,binding):
    return dict(status='v29_C1_S1_schema_snapshot_design_frozen',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_inventory=describe(ROOT/INVENTORY),parent_real_entry_specification=describe(ROOT/V28),
        inherited_sources=request['sources'],original_binding_sources=binding['sources'],cohort=parent['cohort'],
        original_context_inputs=parent['context_inputs'],original_semantic_methods=parent['original_semantic_methods'],
        original_real_decision=read(ROOT/inventory['inputs'][0]['path'])['decision'],
        diagnosis=dict(original_guard_seconds_median=inventory['formal_original_guard_sum_seconds']['median'],
            original_C1_not_adopted=True,code_flow_counts=inventory['code_flow_counts'],
            replay_is_separate=True,observed_candidate_gain=None),
        candidate=dict(id='C1-S1-schema-snapshot-v1',priority=1,status='not_implemented',
            change='Only replace the general typed-tree snapshot fingerprint with a complete, versioned schema-specific representation. Keep C1 identity/config/model/binding algorithms and source checks.',
            fields=['first','counts','first_times','fallback'],
            schema=dict(snapshot='Exact accepted FrozenCatalog class',first='Exact MappingProxyType: canonical ASCII numeric str IDs to nonnegative type(x) is int timestamps',
                counts='Exact MappingProxyType: canonical ASCII numeric str IDs to nonnegative type(x) is int counts',
                first_times='Exact tuple of type(x) is int timestamps, preserving every element, duplicate and position',
                fallback='Exact tuple of canonical ASCII numeric str IDs, preserving every position',
                validation='Perform full live schema/value validation before each fingerprint. Bool is not int. Do not omit zeros, tails or unknown invalid values. Retain original loader/prepare checks.'),
            encoding=dict(scheme='K1-C1-S1-SNAPSHOT-v1',domain_prefix_utf8='K1-C1-S1-SNAPSHOT-v1\n',
                structure='[["first", sorted complete [ID,timestamp] rows by string ID], ["counts", sorted complete [ID,count] rows by string ID], ["first_times", original tuple as JSON array], ["fallback", original tuple as JSON array]]',
                JSON='ensure_ascii=False; separators=(comma,colon); allow_nan=False; UTF-8; no whitespace or newline after JSON.',
                values='Keep IDs as strings and all integers exact decimal integers. Mapping order is canonicalized, sequences are never reordered or deduplicated.',
                fingerprint='SHA256(domain_prefix_utf8 bytes + complete encoded JSON bytes). Full SHA256 retained; no approximate/sampled identity.',
                version='Snapshot preimage format changes, so old C1 snapshot SHA is not expected to match. Old source-file path/bytes/SHA descriptors remain identical. Bind scheme in method/spec/request and cache.use events; reject mixed schemes.'),
            lifetime_and_checks='Original one cold build and six hits in one worker, one snapshot; cold expected fingerprint plus each of7 pre-use and7 post-use fingerprints:15 complete live fingerprints. No cached byte string can replace live verification.',
            retained_canonical=dict(all7_binding=14,all7_config=10,all7_model=10,all7_identity_key=7,
                all7_generic_canonical=41,all7_specialized_snapshot_encodings=15,all7_digest_calls=22,
                interpretation='Function dispatch changes only for snapshot encoding; no integrity boundary is removed.'),
            state='Keep mapping/tuple ownership and no mutable backing aliases; fail on any unexpected miss, changed caller/config/model/process/window/source/method or snapshot mutation. No silent fallback/retry.',
            publication='Separate accepted publisher reads the original model/counts/catalog and rebuilds context; independently validates schema and computes the same versioned fingerprint. It never receives a worker snapshot, encoded buffer or successful-check token.',
            accounting='Charge full schema validation, allocation/copy, JSON, UTF8, SHA and release at each original pre/post boundary. Keep cold setup, final guard and complete entry separately; both arms same observer depth. Do not hide work in preload.'),
        preserved=dict(source_identity='Every1261 V28 closure descriptor and every15 original binding record remain exact; add new scheme/entry/method/acceptance records only.',
            full_sources='Original create and post-OS-lock force=True full source check for every run, worker/publisher before/after full closure, all14 original publisher open/proof checks.',
            science='Original48 identities/order/model/control streams, full payload/Decimal/delta bits and SQL unchanged; C2 sorting change is not combined.',
            old_methods='V27/V28 files, reports, fingerprints and rejected C1 decision remain immutable. New pool/fingerprint/publisher adapters use new files.'),
        deferred=[dict(id='identity_key_component_rewrite',status='not_combined',reason='Original identity median0.416s is smaller than snapshot checks; request/closure duplication needs a separate full-field and mutable-state proof.'),
            dict(id='source_hash_cache_or_fewer_snapshot_checks',status='not_authorized',reason='This candidate changes representation only and preserves all full source and live pre/post integrity boundaries.')],
        acceptance=dict(status='not_implemented_or_run',new_required_cases=CASES,new_required_case_count=sum(len(x) for x in CASES.values()),
            inherited_required_cases=read(ROOT/parent['parent_specification']['path'])['synthetic_acceptance']['required_cases'],
            regressions='V27 73-case and V28 real-entry eight-case regression, plus V29 diagnostic byte/count tests. Do not relabel diagnostic18 as candidate acceptance.',
            gate='Every new/inherited required case maps to a successful concrete test; no failure/error/skip. Commit immutable new methods/spec/log fingerprints before any separate real activation.'),
        future_comparison=dict(status='design_only_not_authorized',candidate='C1-S1 only',schedule=parent['schedule'],decision=parent['decision'],
            supervision=dict(budget_seconds=parent['budget_seconds'],limits=parent['limits'],topology=parent['execution']['topology']),
            reference='Fresh original V4/V6 R in the same window, rebuilding each time; previous rejected C1/V28 timings or replay medians are not a new baseline.',
            cold='R/C warmups plus six RC/CR pairs,14 fresh stores. One C cold plus six hits; all7 per-arm sums include cold. No preloaded snapshot or chosen faster retry.',
            output='Report all pair values, guard component times, all7 sums, worker/publisher/window/public serialization, source coverage and telemetry gaps. Recompute full scientific bytes and stopped identities before release.',
            interpretation='No measured acceleration or direct conversion of replay phase percentages into original C1 savings. Full known-validation engineering only; reserved test stays locked.'),
        scope=dict(authorized_real_runs=0,candidate_implementation=False,candidate_tests_run=0,
            new_real_fit_validation_bootstrap=0,full_validation_complete=False,reserved_test='locked',
            covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232),measured_speedup=None,T_plan=None)


def validate(spec,inventory,parent,request):
    if (spec['parent_inventory']!=describe(ROOT/INVENTORY) or spec['inherited_sources']!=request['sources']
            or len(spec['inherited_sources'])!=1261 or len(spec['original_binding_sources'])!=15):raise ValueError('Original identity scope changed')
    if spec['candidate']['fields']!=['first','counts','first_times','fallback'] or spec['candidate']['status']!='not_implemented':raise ValueError('Candidate scope changed')
    if spec['acceptance']['new_required_cases']!=CASES or spec['acceptance']['new_required_case_count']!=32:raise ValueError('Candidate cases changed')
    if spec['future_comparison']['schedule']!=parent['schedule'] or spec['future_comparison']['decision']!=parent['decision']:raise ValueError('Fair comparison gates changed')
    if spec['scope']['authorized_real_runs'] or spec['scope']['candidate_tests_run'] or spec['measured_speedup'] is not None:raise ValueError('Unexpected execution/acceleration claim')
    if spec['environment']!=environment() or spec['gates']!=check_gates():raise ValueError('Environment/scientific gates changed')


def main(audit=False):
    audit_inventory();inventory=read(ROOT/INVENTORY);parent=read(ROOT/V28);real=read(ROOT/inventory['inputs'][0]['path'])
    request_path=ROOT/real['namespace']/'request.json';record=[x for x in real['evidence'] if x['path']==request_path.relative_to(ROOT).as_posix()]
    if len(record)!=1:raise ValueError('One sealed real request required')
    verify_bindings(record);request=read(request_path);identities={x['path']:x for x in request['sources']}
    old=request['metadata']['cohort']['old_run'];verify_bindings([identities[old]]);binding=read(ROOT/old)['binding']
    verify_bindings([parent['parent_specification']])
    evidence=[describe(ROOT/INVENTORY),describe(ROOT/V28),describe(ROOT/METHOD),*inventory['methods'],inventory['original_method'],
        inventory['tests']['log'],inventory['replay']['raw_rows'],inventory['replay']['plan_receipt'],*inventory['inputs'],*record,identities[old],parent['parent_specification']]
    if audit:
        receipt=read(ROOT/SEAL);verify_bindings([receipt['specification'],*receipt['evidence']]);spec=read(ROOT/SPEC)
        if receipt['evidence']!=evidence:raise ValueError('Sealed design methods changed')
        validate(spec,inventory,parent,request)
    else:
        if (ROOT/SPEC).exists() or (ROOT/SEAL).exists():raise FileExistsError('Immutable design already sealed')
        spec=design(inventory,parent,request,binding);spec.update(environment=environment(),gates=check_gates())
        validate(spec,inventory,parent,request);public_json(ROOT/SPEC,spec,exclusive=True)
        public_json(ROOT/SEAL,dict(status='v29_schema_snapshot_design_sealed_not_implemented',specification=describe(ROOT/SPEC),evidence=evidence,
            new_candidate_required_cases=32,inherited_case_count=38,candidate_tests_run=0,real_runs=0),exclusive=True)
    print(dict(specification=describe(ROOT/SPEC),new_candidate_required_cases=32,inherited_case_count=38,candidate_tests_run=0,real_runs=0,audit=audit))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--specification',action='store_true');mode.add_argument('--audit',action='store_true')
    main(parser.parse_args().audit)
