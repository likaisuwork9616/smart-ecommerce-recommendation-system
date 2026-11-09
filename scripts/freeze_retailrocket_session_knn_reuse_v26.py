"""Seal/audit candidate design only. No implementation, ranking or performance CLI."""
import argparse
from datetime import datetime, timezone

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings, environment, check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.retailrocket_session_knn_cost_window_v5 import LIMITS
from scripts.inventory_retailrocket_session_knn_reuse_v26 import BASE, COST, ANALYSIS, RELEASE, OUTPUT as INVENTORY, METHOD as INVENTORY_METHOD

SPEC=BASE+'v26_reuse_specification_20261109.json'
SEAL=BASE+'v26_reuse_seal_20261109.json'
METHOD='scripts/freeze_retailrocket_session_knn_reuse_v26.py'
PARSER_METHODS=('scripts/retailrocket_session_knn_readback.py','scripts/retailrocket_popularity_oracle.py')
CASES={
 'identity': ['same_size_changed_content','same_bytes_different_path','changed_size','changed_configuration',
    'changed_complete_support_or_model_receipt','changed_parser_or_prepare_method','different_window_or_process',
    'mtime_only_match_cannot_authorize_hit','source_changes_between_create_and_lock','changed_source_on_warm_hit'],
 'snapshot': ['parse_exact_sha_verified_buffer','bytes_change_during_buffer_acquisition','header_or_width_error',
    'duplicate_id_or_noncanonical_number','nonpositive_counts_or_support_mismatch','training_clock_violation',
    'map_or_tuple_mutation_rejected','caller_model_or_config_mutation_rejected','one_cold_build_six_hits',
    'second_sort_tuple_equivalence_including_ties'],
 'checkpoint': ['both_original_full_source_checks_each_run','forced_check_after_lock_before_cache_lookup',
    'writer_lock_failure','body_exception_cleanup','resume_rejects_previous_process_cache',
    'deadline_or_resource_stop','immutable_acceptance_and_existing_output'],
 'publication': ['new_interpreter_no_worker_snapshot','both_full_closure_checks_all_original_sources',
    'all14_original_store_opens_and_physical_frame_proofs','event_cost_load_or_payload_tamper',
    'publisher_failure_live_descendant_or_expiry_withholds_release'],
 'accounting': ['cold_build_key_checks_and_digests_inside_entry','hit_miss_bytes_rows_and_phase_counts',
    'same_fine_observers_for_both_arms','all14_retained_and_both_orders','no_hidden_cache_preload',
    'full_bytes_metrics_delta_hex_and_sql_workload_identical']}


def proposal(inventory,request):
    binding=read(ROOT/inventory['cohort']['old_run'])['binding']['sources']
    source_map={x['path']:x for x in request['sources']}
    semantics=[*inventory['methods'],*(source_map[p] for p in PARSER_METHODS)]
    verify_bindings(semantics)
    return dict(status='v26_repeated_cost_candidate_specification_frozen',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_inventory=describe(ROOT/INVENTORY),inventory_method=describe(ROOT/INVENTORY_METHOD),
        cohort=inventory['cohort'],original48_reference=read(ROOT/COST)['results']['reference'],
        inherited_sources=request['sources'],original_binding_sources=binding,environment=environment(),gates=check_gates(),
        source_identity=dict(record_fields=['path','bytes','sha256'],path_identity='Preserve every exact bound relative path; equal content at other paths is not interchangeable.',
            mandatory_boundaries=['worker full closure before runs','create full original binding check each run',
                'writer force=True full original binding check after OS lock and before snapshot lookup',
                'worker full closure after runs','independent publisher full closure before and after audit',
                'independent publisher original full binding check at each of14 store opens'],
            original_sources='All596 original closure identities remain. A future execution manifest adds candidate methods/specification/acceptance to the common closure; it never substitutes a smaller set.',
            unsupported_shortcuts=['path/size/mtime-only success','cross-process source-success receipts','content-hash-only path deduplication',
                'removal of create or forced post-lock checks','replacement of original publisher open checks by worker receipts']),
        candidates=[dict(id='C1_worker_context_snapshot',priority=1,implementation_status='not_implemented',
            change='Reuse an exact immutable counts/catalog/FrozenCatalog snapshot only within the one supervised worker. No SQL or per-query/control-stream change.',
            cache_scope=dict(max_entries=1,ownership='One namespace/request and one private pid/create_time identity. Never persist or pass the snapshot to publisher.',
                lifetime='Build inside first candidate warmup after original post-lock full check; retain through six candidate formal runs; discard on exit, failure or process restart.',
                expected_successful_candidate_runs=dict(cold_builds=1,hits=6),
                mismatch='Reject the window on any changed identity/config/model/support/method or unexpected miss; never silently re-key, fallback or retry.'),
            key=dict(source_records='Complete ordered original15 path/bytes/SHA records, plus configuration and reconstruction receipt descriptors.',
                inputs=inventory['initialization']['dependencies'],
                semantic_state='Complete typed configuration and model/support canonical identity, not fit_id alone. Compare live objects to frozen initial values on every borrow; charge this work.',
                methods=dict(original_semantics=semantics,additional='Bind candidate adapter, integrated acceptance methods and accepted interpreter/environment at future activation.'),
                request='Exact namespace/request fingerprint and process ownership; these private identities are excluded from public aggregates.'),
            build=['Read only counts and catalog into bounded immutable byte buffers; compute SHA256 and byte length over the exact buffers and match every expected path descriptor before parsing.',
                'Invoke the original independent CSV parser, positive_table, load_context validation and prepare_catalog semantics against those exact verified buffers. No primary production loader.',
                'Preserve UTF-8 and newline behavior, schema/width, duplicate ID, canonical numeric, positive count, full support and training clock rejection.',
                'Freeze copied maps with MappingProxyType and sequences with tuples; retain no mutable backing aliases. Freeze the complete initial config/model semantic state.',
                'Keep original per-run first_times sorting for C1 so it does not combine the separate C2 change; per-query control streams, fresh SQL connection/TEMP state and writer are never shared.'],
            borrow=['Original full binding create check and forced post-lock check must finish successfully before every lookup.',
                'Recompute/compare complete key and live semantic state; verify immutable snapshot content digest before use and after verifier return. Do not trust frozen dataclass alone.',
                'Do not reread/parse counts/catalog on a valid hit; report actual hit/miss, logical bytes, rows and every guard phase. Verification cost stays inside original setup/entry.',
                'Use the identical original verifier/ranker/arithmetic after context injection. Snapshot corruption, mutation or source/key mismatch rejects before publishing.'],
            timing='Cold bytes/digest/parser/support checks/prepare/copies and pre-use keys/digests stay in original setup and complete entry. Post-verifier snapshot checks stay inside complete entry and are recorded separately; expanded initialization is original setup plus that disjoint final guard. Preserve original setup/primary boundaries separately; no work can move into uncharged pre-warmup.'),
            dict(id='C2_reuse_prepared_first_times',priority=2,implementation_status='not_implemented',
                change='Replace only verify_selected first_times=sorted(catalog.values()) with the already prepared immutable first_times tuple.',
                independence='Fresh original load_context and prepare_catalog on all seven candidate runs; no C1 snapshot cache or source-check change.',
                invariants=['Same complete sorted timestamps, length, duplicate timestamps and bisect_left semantics.',
                    'No mutation of first_times; full payload/workload must equal the original verifier.'],
                timing='Charge original setup/entry. Sorting-only saving is unknown; measured setup-other includes many operations and is not a saving estimate.')],
        deferred=[dict(id='source_hash_reuse_or_path_dedup',decision='not_ready',
            reason='Same content or earlier hashes do not establish immutability between protection boundaries; no pinned immutable source/handle guarantee was accepted.',
            reopening_requires='A separate design with a proven non-mutation lifetime, path ownership and adversarial change/ABA tests. Present candidates preserve all source checks.')],
        synthetic_acceptance=dict(status='not_implemented_or_run',required_cases=CASES,required_case_count=sum(len(v) for v in CASES.values()),
            original_regressions=['V24 observer semantics','V25 supervised worker/publisher and real tiny subprocess deadline/cleanup',
                'V6 append/commit/budget invariants','V23 inclusive/exclusive conservation'],
            science='Use artificial complete four-arm fixtures and artificial48 ledger fixtures separately. Full saved scientific bytes, Decimal strings, binary64 delta_hex, order and logical SQL workload must match.',
            fail_closed='Any missing/failed/skipped case prevents real activation. Immutable accepted method/spec/log fingerprints must be committed first.'),
        future_comparison=dict(status='design_only_not_authorized',candidate_order=['C1_worker_context_snapshot','C2_reuse_prepared_first_times'],
            isolation='One candidate per new separately authorized window. No combined candidate, grid search, real retry or new sample selection.',
            population='Same original48 keys, original ordinals, immutable model and complete physical reference; all55 coverage remains historical.',
            schedule=[dict(label='warm_'+m,mode=m) for m in ('R','C')]+[
                dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')],
            reference='Original V4/V6 reconstruction/control/ranking/checkpoint behavior, rebuilding context every R. V25 historical R/D is not the new baseline.',
            observers='Same fine-observer depth on both arms plus sequential200ms target telemetry, including independent publisher. Count source/kernel/context/cache operations by arm.',
            caches='Candidate C1 cold only in warm_C, then six hits. R never sees candidate snapshot. Existing exact verifier caches follow the same initial reset policy on both arms; all14 runs are retained.',
            supervision=dict(budget_seconds=1800,limits=LIMITS,topology='Original single V5 deadline across worker then new-interpreter publisher; stopped descendants before release.'),
            publication='Preserve V25 independent source/physical payload/cost/event/load re-audit, all14 store opens, output sealing and post-exit release. Publisher never imports or trusts worker snapshot.',
            metrics=['complete entry including all cache work','setup build/hit/key/digest parts','original primary/append/commit boundaries',
                'sum all7 entries per arm including cold warmup','worker closure and whole process/window','publisher callback/process and parent release serialization',
                'peak sampled tree RSS, bounded snapshot bytes, telemetry gaps and Ollama context'],
            decision=dict(primary_metric='complete entry seconds; do not reuse the SQL primary-only adoption gate',
                entry_positive_pairs_at_least=5,total_formal_pairs=6,median_paired_entry_saving_percent_at_least=5,
                each_RC_CR_order_median_entry_saving_seconds='strictly_positive',
                all7_candidate_entry_seconds_including_cold='strictly_less_than_all7_reference',
                median_paired_primary_regression_percent_at_most=5,
                required='All scientific/source/safety/accounting tests pass and resource limits hold. Publish all pair values regardless of outcome; failure means not adopted.',
                interpretation='Frozen engineering screening criteria, not a statistical generalization guarantee or premeasured speedup.'),
            activation='Requires implemented candidate plus integrated synthetic acceptance and a fresh explicit real-execution authorization/specification. This V26 seal authorizes zero real runs.'),
        scope=dict(authorized_real_runs=0,new_model_fit=0,new_full_validation=0,new_bootstrap=0,reserved_test='locked',
            covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232),
        measured_speedup=None,T_plan=None)


def validate(spec,inventory,request):
    if spec['parent_inventory']!=describe(ROOT/INVENTORY) or spec['inherited_sources']!=request['sources']:
        raise ValueError('Sealed provenance changed')
    if spec['scope']['authorized_real_runs']!=0 or spec['measured_speedup'] is not None or spec['T_plan'] is not None:
        raise ValueError('Design must not claim measurement authority/results')
    candidates=spec['candidates']
    if [x['id'] for x in candidates]!=['C1_worker_context_snapshot','C2_reuse_prepared_first_times']:
        raise ValueError('Candidate scope changed')
    if candidates[0]['key']['inputs']!=inventory['initialization']['dependencies'] or candidates[0]['cache_scope']['max_entries']!=1:
        raise ValueError('Snapshot dependencies or bound changed')
    cases=spec['synthetic_acceptance']['required_cases'];flat=[x for v in cases.values() for x in v]
    if cases!=CASES or len(flat)!=len(set(flat)) or len(flat)!=spec['synthetic_acceptance']['required_case_count']:
        raise ValueError('Required synthetic cases changed')
    future=spec['future_comparison'];schedule=future['schedule']
    if len(schedule)!=14 or len({x['label'] for x in schedule})!=14 or future['supervision']['limits']!=LIMITS:
        raise ValueError('Future comparison design changed')
    if spec['environment']!=environment() or spec['gates']!=check_gates():raise ValueError('Frozen environment/gates changed')


def main(audit=False):
    inventory=read(ROOT/INVENTORY);report=read(ROOT/COST);folder=ROOT/report['namespace']
    verify_bindings([inventory['parent_report'],inventory['parent_analysis'],inventory['parent_release'],inventory['inventory_method'],*inventory['methods']])
    requests=[x for x in report['evidence'] if x['path']==(folder/'request.json').relative_to(ROOT).as_posix()]
    if len(requests)!=1:raise ValueError('Exactly one sealed source request is required')
    verify_bindings(requests)
    request=read(folder/'request.json')
    evidence=[describe(ROOT/p) for p in (INVENTORY,COST,ANALYSIS,RELEASE,METHOD,INVENTORY_METHOD)]+[
        describe(folder/'request.json'),*inventory['methods'],*(describe(ROOT/p) for p in PARSER_METHODS)]
    if audit:
        seal=read(ROOT/SEAL);verify_bindings([seal['specification'],*seal['evidence']]);spec=read(ROOT/SPEC)
        if seal['evidence']!=evidence:raise ValueError('Sealed design methods/evidence changed')
        validate(spec,inventory,request)
    else:
        if (ROOT/SPEC).exists() or (ROOT/SEAL).exists():raise FileExistsError('Immutable candidate seal already exists')
        spec=proposal(inventory,request);validate(spec,inventory,request)
        public_json(ROOT/SPEC,spec,exclusive=True)
        public_json(ROOT/SEAL,dict(status='v26_candidate_design_sealed_not_implemented',specification=describe(ROOT/SPEC),
            evidence=evidence,required_future_cases=spec['synthetic_acceptance']['required_case_count'],
            current_candidate_tests_run=0,current_real_runs=0,raw_source_rehash=False),exclusive=True)
    print(dict(specification=describe(ROOT/SPEC),required_future_cases=spec['synthetic_acceptance']['required_case_count'],real_runs=0,audit=audit))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--specification',action='store_true');mode.add_argument('--audit',action='store_true')
    main(parser.parse_args().audit)
