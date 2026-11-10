"""Characterize the frozen canonical oracle and seal a late typed-comparator design."""
import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import math
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts import freeze_retailrocket_session_knn_ownership_v37 as parent

BASE = 'reports/stage12/retailrocket_session_knn_v38_typed_'
INVENTORY = BASE+'inventory_20261110.json'
SPEC = BASE+'specification_20261110.json'
SEAL = BASE+'seal_20261110.json'
METHOD = 'scripts/freeze_retailrocket_session_knn_typed_v38.py'
TEST = 'tests/test_retailrocket_session_knn_typed_contract_v38.py'
SUITE = 'tests.test_retailrocket_session_knn_typed_contract_v38'
SUITES = (SUITE, *parent.SUITES)
POLICY = 'C1-S1-cold-late-typed-source-anchor-v1'
INTERPRETATION = 'Original canonical oracle characterization plus original ownership/temporal tests only. No comparator implementation, candidate acceptance or performance measurement.'
SEMANTICS = {
    'scalar': 'Exact None/bool/int/finite-float/str types only. Integers use str(value); floats use finite float.hex(), including signed zero. Python equality is not typed canonical equality.',
    'sequence': 'Exact list and tuple have different tags. Every position, order and repetition is significant; all nested content is covered.',
    'mapping': 'Exact dict and MappingProxyType share the map tag. All keys must be exact str; keys sort by original Python str ordering; insertion order is immaterial. Values remain recursively typed. An exact proxy may wrap a custom mapping: preserve the original key-type scan then sorted-key scan then per-key lookup protocol; do not assume the backing is an exact dict.',
    'unicode': 'No Unicode normalization/case folding or lossy conversion. Original JSON ensure_ascii=False and final UTF-8 encoding reject lone surrogates; omitting output serialization must not widen this domain.',
    'failure': 'Reject nonfinite floats, nonstr keys, custom/subclass values and cyclic/over-depth/unencodable graphs. Shared acyclic aliases remain valid and every occurrence is traversed; cycle detection must use the active ancestry path, not a global visited set. Low-level resource exception classes/messages are not promised identical; no failure may return an equal result or permit borrowing.',
    'temporal': 'All four early live/source canonical checks stay. Late comparison is after the original load/prepare span exits and before expected state publication, snapshot/pre-use/cache.use/borrow/query. Config precedes model; all final live canonical checks remain.',
    'authority': 'Use the validated source canonical bytes, not the mutable caller or a newly captured late baseline. This adopts V36 stronger source-anchor rejection and is not equivalent to the old behavior that could absorb a persistent initialization mutation.',
    'ownership': 'No immutable ownership assumption is made for caller dict/list/support or callback aliases. Only the newly built source reference value must be recursively immutable and nonescaping.',
}
REQUIRED = {
    'authority': [
        'reference_only_from_source_bytes_of_successful_early_complete_comparisons',
        'reference_tree_exact_grammar_recursively_immutable_no_live_or_parsed_alias',
        'reference_build_decode_validation_and_lifetime_inside_charged_cold_scope',
        'reference_tamper_or_mixed_source_policy_rejected_without_fallback',
    ],
    'scalar': [
        'exact_types_none_bool_int_float_str_and_bool_int_int_float_separation',
        'finite_float_hex_subnormal_extremes_and_positive_negative_zero',
        'arbitrary_precision_integer_decimal_conversion_and_current_interpreter_limits',
        'unicode_exact_codepoints_no_normalization_and_utf8_rejection_domain',
    ],
    'containers': [
        'list_tuple_tag_order_lengths_and_duplicate_elements_all_covered',
        'dict_proxy_equivalence_sorted_exact_string_keyset_values_and_original_read_protocol',
        'every_nested_config_support_audit_and_unrelated_field_covered',
        'no_identity_len_digest_only_equality_or_shallow_mappingproxy_shortcut',
    ],
    'failure': [
        'unsupported_custom_subclass_nonstr_keys_and_nonfinite_rejected',
        'selected_root_fully_validated_even_after_an_earlier_value_mismatch',
        'active_path_cycles_rejected_shared_acyclic_aliases_allowed_depth_utf8_tail_fail_closed',
        'reference_build_load_prepare_compare_failure_poison_all_state_no_retry',
    ],
    'timing': [
        'persistent_config_and_model_init_mutations_rejected_at_original_late_before_borrow',
        'ABA_crossing_original_late_boundary_rejected_no_baseline_refresh',
        'restore_before_late_and_between_discrete_guards_no_continuous_detection_claim',
        'watch_and_observer_entry_exit_mutations_and_comparison_reentry_policy_explicit',
    ],
    'preserved': [
        'all_original_and_current_source_method_request_owner_key_checks_append_only',
        'original15_create_and_postlock_full_checks_and_original_load_prepare_semantics',
        'all_final_live_config_model_canonical_and_fifteen_live_snapshot_checks',
        'independent_publisher_rebuild_scientific_bytes_SQL_and_stopped_log_seal',
    ],
    'integration': [
        'new_policy_bound_in_methods_spec_request_events_receipt_publisher_mixed_rejected',
        'reference_descriptors_comparison_counts_and_completed_phases_independently_checked',
        'one_cold_six_hits_reference_reuse_only_in_one_worker_no_hit_guard_removed',
        'success_and_failure_cleanup_reference_retention_release_no_crossprocess_cache',
    ],
    'accounting': [
        'cold_four_canonical_plus_two_full_typed_checks_not_four_total_content_guards',
        'all7_generic39_typed2_snapshot15_digest22_expected_future_accounting_only',
        'reference_parse_freeze_full_walk_keysort_validation_release_and_observer_cost_in_entry',
        'differential_oracle_acceptance_before_separate_sequential_original48_fair_comparison',
    ],
}


def inherited():
    parent.audit()
    inv = read(ROOT/parent.INVENTORY)
    return dict(records=[describe(ROOT/p) for p in (parent.INVENTORY, parent.SPEC, parent.SEAL,
                                                   parent.prior.SPEC, parent.prior.SEAL)],
                source_audit=inv['source_audit'], preserved_counts=inv['inherited']['counts'],
                limitation='Re-audit sealed local code/event/test evidence; no new full 12GB source closure hash, real context or query replay.')


def scope():
    return parent.scope()


def expected_tests():
    names = parent.prior.ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if len(names) != len(set(names)) or len([x for x in names if x.startswith(SUITE+'.')]) < 18:
        raise ValueError('Canonical oracle coverage missing or duplicated')
    inherited_names = [x for x in names if not x.startswith(SUITE+'.')]
    if Counter(inherited_names) != Counter(parent.expected_tests()):
        raise ValueError('All original ownership/temporal tests must be rerun together')
    return names


def inventory():
    if (ROOT/INVENTORY).exists(): raise FileExistsError('Immutable typed inventory exists; use --audit')
    base = inherited(); methods = [describe(ROOT/p) for p in (METHOD, TEST)]
    expected = expected_tests(); folder = PRIVATE/('knn-v38-oracle-'+uuid4().hex); folder.mkdir()
    started = perf_counter()
    with (folder/'tests.log').open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=parent.prior.Result).run(
            unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not result.wasSuccessful() or result.skipped or Counter(result.passed) != Counter(expected):
        raise ValueError('Original oracle characterization failed: '+str(folder/'tests.log'))
    verify_bindings(methods)
    public_json(ROOT/INVENTORY, dict(status='v38_original_typed_oracle_and_late_contract_inventoried',
        created_utc=datetime.now(timezone.utc).isoformat(), inherited=base, methods=methods, semantics=SEMANTICS,
        verification=dict(suites=list(SUITES), tests_run=result.testsRun, passed_test_ids=result.passed,
                          failures=0, errors=0, skipped=0, seconds=perf_counter()-started,
                          log=describe(folder/'tests.log'), interpretation=INTERPRETATION),
        scope=scope(), measured_speedup=None, T_plan=None), exclusive=True)
    print(dict(inventory=INVENTORY, original_tests=result.testsRun, comparator_implemented=False, new_query_runs=0))


def audit_inventory():
    value = read(ROOT/INVENTORY); tests = value['verification']
    verify_bindings(value['methods']+[tests['log']])
    if (value['status'] != 'v38_original_typed_oracle_and_late_contract_inventoried'
            or value['inherited'] != inherited() or value['methods'] != [describe(ROOT/p) for p in (METHOD, TEST)]
            or value['semantics'] != SEMANTICS or value['scope'] != scope()
            or value['measured_speedup'] is not None or value['T_plan'] is not None
            or tests['suites'] != list(SUITES) or tests['interpretation'] != INTERPRETATION
            or Counter(tests['passed_test_ids']) != Counter(expected_tests())
            or tests['tests_run'] != len(tests['passed_test_ids'])
            or any(type(tests[k]) is not int or tests[k] != 0 for k in ('failures', 'errors', 'skipped'))
            or type(tests['seconds']) not in (int, float) or not math.isfinite(tests['seconds']) or tests['seconds'] < 0):
        raise ValueError('Typed inventory changed')
    return value


def design(inv):
    return dict(status='v38_full_late_typed_comparator_specification_frozen_not_implemented',
        inventory=describe(ROOT/INVENTORY), inherited=inv['inherited'], methods=inv['methods'],
        verification_log=inv['verification']['log'],
        candidate=dict(id=POLICY, status='design_only_not_accepted',
            semantic_target='For a stable live graph in the original canonical domain, compare_full(live, frozen_reference) is true exactly when original canonical(live) equals the validated source canonical bytes. Original-or-stronger rejection timing is required; arbitrary concurrent mutation detection is not claimed.',
            baseline='V36 validated source anchor. Persistent initialization changes are rejected before borrow, rather than adopted into the old late baseline. This deliberate strengthening must be reported separately from encoding equivalence.',
            reference='After all four successful original early live/source canonical comparisons, retain the config/model source canonical bytes. Decode these exact bytes, validate the original typed JSON grammar, and build a new tuple-only recursive token tree containing exact immutable str/bool leaves. No live/source dict/list alias survives in the reference. Decode/grammar/freeze/retention costs are charged.',
            reference_validation='Require exact tag/arity and JSON list shapes; none has arity1, others arity2. bool payload is exact bool; int payload is a str whose int/str roundtrip is canonical under current interpreter limits; float payload is a finite fromhex value whose hex roundtrip is exact including signed zero; str and map keys are exact UTF8-encodable str. Sequence children validate recursively; map pairs have arity2 with strictly sorted unique keys. Reject malformed/duplicate/out-of-order reference tokens; bind original source-byte length/SHA and reference scheme in evidence. These are checks of the supplied authority, not a new source serialization.',
            authority_bindings=dict(raw_configuration=read(ROOT/parent.prior.SPEC)['preserved']['dependencies']['config'],
                raw_reconstruction=read(ROOT/parent.prior.SPEC)['preserved']['dependencies']['model'],
                model_selector='receipt', canonical_algorithm=describe(ROOT/'scripts/retailrocket_session_knn_reuse_v27.py'),
                reference_scheme='K1-C1-LATE-TYPED-REFERENCE-v1',
                future_evidence='Separately bind each original raw JSON descriptor and each successful early source typed-canonical byte length/SHA (config call2/model call4), plus canonical algorithm identity and reference scheme. Do not relabel raw JSON bytes or V35 late bytes as newly observed early bytes.'),
            grammar=dict(none=['none'], boolean=['bool', 'exact bool'], integer=['int', 'str(int)'],
                floating=['float', 'finite float.hex()'], string=['str', 'exact Unicode str'],
                sequence=['list or tuple tag', 'tuple of child tokens'],
                mapping=['map', 'tuple of sorted (exact str key, child token) pairs']),
            traversal='Walk every live node of the selected config/model root using original exact type dispatch, original sorted str map keys, scalar conversion and complete sequence order. Validate all live children including extra map entries/sequence elements after any value/shape/length mismatch; no zip truncation or boolean short-circuit may skip a live tail. A hard unsupported/unencodable/cycle error may immediately raise and poison; full traversal on ordinary inequality is not a demand to continue after an error. Accumulate equality without Python container equality, digest/identity-only shortcuts, rebuilding the whole typed tree or emitting JSON/UTF8 canonical output. Detect cycles only on active ancestry, and traverse repeated acyclic aliases for each occurrence without memoized equality.',
            domain_validation='Preserve finite float checks, arbitrary int conversion limits, exact string/key types, no Unicode normalization and strict UTF8 encodability including lone-surrogate rejection. Cycle/depth/resource failures reject and poison; low-level exception text/class is not the scientific contract. Any newly rejected oracle-valid boundary case blocks candidate acceptance until explicitly resolved.',
            mapping_protocol='Use the original all(type(k) is str for k in live), then sorted(live), then live[k] in that sorted order. Do not add len(live), items(), equality or other custom-backing protocol calls. Existing proxy-backed data hooks are not new instrumentation hooks; their mutation/reentry behavior needs explicit differential acceptance, and exact proxy type alone proves neither stable backing nor readonly capability. Dynamic protocol behavior remains an admission gate until the required equivalence tests pass.',
            timing=['unchanged complete identity/source/method/post-lock checks',
                'unchanged verified four buffers and config/model source parsing',
                'original four ordered short-circuit live/source canonical calls; retain source bytes only after equality',
                'build and validate immutable source reference inside cold scope before original initialization',
                'unchanged original load_context and prepare_catalog, including observer span exit',
                'at original late boundary complete config typed validation/comparison, reject/poison if mismatch',
                'then complete model typed validation/comparison, reject/poison if mismatch',
                'only on success publish source expected bytes/owner/key and perform unchanged snapshot/pre-use/borrow',
                'every original final live config/model canonical and complete snapshot validation unchanged'],
            callback_policy='No new watch/span/observer-clock/user callback from original prepare-span exit through both late checks and successful expected-byte publication, including no hook at comparator entry or between config/model. Keep all existing hooks/watch calls elsewhere. Use bound passive timers/local primitive metadata and attach evidence after checks without inserting a callback before the old observation point. Reentry during comparison rejects before state publication. Cooperative sampling requires a separate mutation/reentry and timing specification.',
            failure='Any reference build, original initialization or late comparison failure poisons and clears prepared/reference/expected bytes/key/owner/active. Never refresh authority from live caller, fall back to four calls without content checking, reuse after failure or move checks after borrow/query.',
            equality_scope='Type/encoding equivalence is specified for stable graphs. Existing callback mutation scenarios remain admitted and must be checked at the same late point. A mutation restored before all existing discrete guards may pass; no continuous or adversarial heap isolation guarantee.'),
        call_accounting=dict(status='proposed_only_current_runtime_unchanged', current_cold_canonical=6,
            proposed_cold_canonical=4, proposed_cold_full_typed_comparisons=2,
            proposed_all7_generic_canonical=39, proposed_all7_full_typed_comparisons=2,
            all7_live_snapshot_fingerprints=15, all7_digests=22,
            qualification='Six complete cold content observations remain: four canonical plus two typed checks. Canonical count reduction does not establish a speedup; reference decode/freeze/keysort/domain validation are new work.'),
        acceptance=dict(status='future_candidate_not_implemented_or_tested', required_cases=REQUIRED, required_case_count=32,
            oracle='Differential checks against unchanged original canonical for accepted/equal/different/rejected values, including generated nested graphs and explicit limits. Characterization tests alone are not comparator acceptance.',
            inherited='V36 source-anchor temporal/failure requirements, original C1-S1 applicable acceptance, V34 direct/log lifecycle and independent publication. Original methods/results remain immutable.',
            gate='Implement in new files, map every new/inherited requirement to passed tests, seal independent synthetic integration evidence and policy identities before a separately frozen original48 sequential comparison.'),
        publisher_contract='A new independent publisher re-reads verified raw config/model and uses original canonical to rebuild source-byte identities and immutable reference authority; never trust a serialized worker reference. Verify policy, source byte length/SHA, exactly one cold reference build with two roots, two successful complete late checks only on cold and zero on hits, ordered passive timing evidence and full success/failure phase counts in request/events/receipt. Preserve every original source/store/scientific reconstruction and stopped-log audit.',
        preserved='All current 2092 sources/168 methods plus original1937/26 and binding15 are retained via the exact inherited specification. Complete identity key, create/post-lock checks, original SQL/scientific bytes, all final live checks, snapshot checks and independent publisher/stopped-log validation remain unchanged.',
        scope=scope(), measured_speedup=None, T_plan=None)


def seal_value():
    return dict(status='v38_full_late_typed_design_sealed', inventory=describe(ROOT/INVENTORY),
                specification=describe(ROOT/SPEC), policy=POLICY, future_required_cases=32,
                candidate_implemented=False, candidate_tests_run=0, new_query_runs=0)


def freeze():
    if (ROOT/SPEC).exists() or (ROOT/SEAL).exists(): raise FileExistsError('Immutable typed design exists')
    inv = audit_inventory(); value = dict(design(inv), created_utc=datetime.now(timezone.utc).isoformat())
    if sum(len(x) for x in REQUIRED.values()) != 32: raise ValueError('Expected 32 required future cases')
    public_json(ROOT/SPEC, value, exclusive=True); public_json(ROOT/SEAL, seal_value(), exclusive=True)
    print(dict(specification=SPEC, future_required_cases=32, candidate_tests_run=0, new_query_runs=0))


def audit():
    inv = audit_inventory()
    if (ROOT/SPEC).exists():
        value = read(ROOT/SPEC); seal = read(ROOT/SEAL)
        verify_bindings([seal['inventory'], seal['specification']])
        if {k:v for k,v in value.items() if k != 'created_utc'} != design(inv) or seal != seal_value():
            raise ValueError('Typed specification/seal changed')
    elif (ROOT/SEAL).exists(): raise ValueError('Orphan typed seal')
    print(dict(audit=True, original_tests=inv['verification']['tests_run'], candidate_implemented=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('inventory', 'specification', 'audit'): mode.add_argument('--'+name, action='store_true')
    args = parser.parse_args()
    if args.inventory: inventory()
    elif args.specification: freeze()
    else: audit()
