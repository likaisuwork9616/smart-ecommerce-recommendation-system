"""Metadata-only D1 protocol checks; no recommendation or real-row computation."""
import json


def validate(policy, parent, p0, pa, c1, ca, inventory, c1_policy):
    checks = []

    def require(name, condition):
        if not condition:
            raise ValueError('D1 specification mismatch: ' + name)
        checks.append(name)

    def equal(name, actual, expected):
        # JSON encoding distinguishes bool from int and rejects nonfinite floats.
        require(name, json.dumps(actual, sort_keys=True, allow_nan=False) ==
                json.dumps(expected, sort_keys=True, allow_nan=False))

    def fixed(section, expected):
        for key, value in expected.items():
            equal(section + '.' + key, policy[section][key], value)

    def file_of(report, suffix):
        matches = [x for x in report['files'] if x['path'].endswith('/' + suffix)]
        require('unique_' + suffix + '_' + report['status'], len(matches) == 1)
        return matches[0]

    try:
        equal('protocol_id', policy['protocol_id'], 'retailrocket_directed_paired_v1')
        equal('version', policy['version'], 1)
        equal('status', policy['status'], 'frozen_before_D1_implementation_after_P0_and_C1_validation_observed')
        equal('parent_data_contract', policy['parent_data_contract'], 'docs/contracts/retailrocket_recommendation_v1.json')
        equal('parent_metric_protocol', policy['parent_metric_protocol'], 'docs/contracts/retailrocket_popularity_execution_v1.json')
        equal('parent_C1_protocol', policy['parent_C1_protocol'], 'docs/contracts/retailrocket_cooccurrence_paired_v1.json')
        equal('inventory_path', policy['candidate_inventory'], 'reports/stage11/retailrocket_stage11_candidate_inventory_v1.json')
        equal('research_question', policy['research_question'], 'With the same session-binary unit, S_i, causal history, full candidates and denominators, how does restricting arbitrary unordered session cooccurrence to directed adjacent-basket association change next-basket validation NDCG?')
        equal('interpretation', policy['interpretation'], 'Joint change of direction and adjacency; does not isolate either effect. Custom D1 association score, not standard first-order Markov or a probability; no claim that it solves cold items.')
        expected_scope = {'specification_only': True, 'D1_implemented': False, 'real_D1_fits': 0,
            'new_P0_fits': 0, 'new_C1_fits': 0, 'new_ranked_queries': 0, 'new_paired_metrics': 0,
            'new_bootstrap_replicates': 0, 'real_data_CSV_rows_parsed': 0,
            'real_data_JSONL_rows_parsed': 0, 'train_cost_scan_executed': False, 'reserved_test_enabled': False}
        equal('zero_research_scope', policy['scope_this_round'], expected_scope)
        fixed('comparison', {'challenger': 'D1_binary_session_directed_adjacent_association', 'challenger_count': 1,
            'primary_control': 'C1', 'secondary_control': 'P0', 'hyperparameter_search': False,
            'deterministic': True, 'model_seeds': None, 'parent_stochastic_seeds_if_future_method_changes': [11, 29, 42, 73, 101],
            'D1_primary_fit_limit': 1, 'independent_count_audits': 1, 'reference_refits_or_rerankings': 0,
            'fit_roles': ['train'], 'fit_start_inclusive_utc': '2015-05-04T00:00:00Z',
            'fit_end_exclusive_utc': '2015-08-01T00:00:00Z', 'evaluation_roles': ['validation'],
            'statistics_update_during_evaluation': False, 'training_ranking': False, 'final_refit': False, 'test_ranking': False})
        equal('parent_train_window', parent['time_roles']['train'],
              [policy['comparison']['fit_start_inclusive_utc'], policy['comparison']['fit_end_exclusive_utc']])
        equal('parent_future_stochastic_seeds', parent['evaluation']['stochastic_seeds'],
              policy['comparison']['parent_stochastic_seeds_if_future_method_changes'])
        equal('P0_accepted', p0['status'], 'development_fit_and_full_validation_independently_accepted')
        equal('P0_acceptance', pa['status'], 'all_validation_output_cells_and_aggregates_independently_accepted')
        equal('C1_accepted', c1['status'], 'C1_paired_validation_and_bootstrap_independently_accepted')
        equal('C1_acceptance', ca['status'], 'complete_C1_model_lineage_queries_nested_values_and_bootstrap_accepted')
        equal('P0_aggregate_reused', c1['validation']['arms']['P0'], p0['validation'])
        for name, report, acceptance in [('P0', p0, pa), ('C1', c1, ca)]:
            equal(name + '_acceptance_scope', acceptance['scope'], report['scope'])
            equal(name + '_test_state', report['scope']['reserved_test_state'], 'locked')
            equal(name + '_test_ranked', report['scope']['reserved_test_ranked_queries'], 0)
            equal(name + '_final_refits', report['scope']['final_refits'], 0)
            equal(name + '_training_ranked', report['scope']['training_ranked_queries'], 0)
        equal('C1_reference_refits', c1['scope']['P0_refits_or_rerankings'], 0)
        fixed('reference_identity', {'P0_guard': 'shop-mysql-runtime/retailrocket_popularity_v1/development/output_guard.json',
            'C1_guard': 'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/output_guard.json',
            'release_receipt': 'reports/stage10/retailrocket_c1_p0_v1_research_release.json',
            'release_guard': 'shop-mysql-runtime/retailrocket_c1_p0_release_v1/output_guard.json',
            'P0_fit_id': p0['fit_audit']['fit_id'], 'C1_fit_id': c1['fit_audit']['fit_id'],
            'P0_item_counts': file_of(p0, 'item_counts.csv'), 'P0_ranked_queries': file_of(p0, 'ranked_queries.csv'),
            'P0_query_metrics': file_of(p0, 'query_metrics.csv'), 'C1_support': file_of(c1, 'support.csv'),
            'C1_pairs': file_of(c1, 'pairs.csv'), 'C1_queries': file_of(c1, 'queries.jsonl'),
            'C1_bootstrap': file_of(c1, 'bootstrap.jsonl'),
            'reuse': 'Read accepted reference bytes; never refit, rerank, regenerate or edit P0/C1 outputs; C1 pairs are an audit upper bound, not a tunable D1 blend.'})
        fixed('fit', {'source': 'shop-mysql-runtime/retailrocket_dataset_v1/baskets.csv',
            'session_key': ['visitorid', 'session_start_ms'], 'both_endpoint_roles': ['train'],
            'original_index_difference': 1, 'strictly_later_timestamp': True, 'maximum_gap_ms': 1800000,
            'same_session_required': True, 'both_endpoints_inside_fit_window': True, 'bridge_after_filtering': False,
            'within_basket_order': False, 'labelled_query_filter': False, 'include_unlabelled_train_baskets': True,
            'future_session_end_or_total_length_used': False, 'repeat_within_session_counted_again': False,
            'self_edges': False, 'minimum_directed_support': 1, 'row_sum_normalization': False,
            'smoothing': None, 'decay': None, 'blend_weight': None, 'neighbor_top_L': None,
            'session_cap': None, 'history_cap': None, 'pruning_or_sampling': False,
            'boundary': 'Take original adjacent baskets only when both endpoints are train and within cutoff; never connect warmup to train, train to validation, or across a removed/missing index. A session crossing cutoff is retained only through eligible train endpoints; no end-based session deletion.',
            'shared_support': 'Use byte-identical C1 S_i: count of train session item sets containing i, including singleton-only and no-transition items; no primary support refit. Independent oracle reconstructs S_i only to audit equality.',
            'directed_count': 'D_ij = number of train sessions with at least one original adjacent eligible basket pair (A,B) where i in A, j in B and i != j. Count each ordered (i,j) at most once per session; reverse direction is separate.',
            'cross_basket_product': 'Every A x B pair except i=j is eligible; no averaging by basket size and no invented order within either unordered same-ms basket.'})
        equal('parent_session_gap', policy['fit']['maximum_gap_ms'], parent['primary_task']['session_gap_ms'])
        equal('fit_invariants', policy['fit']['invariants'], [
            'S_i positive keys exactly equal frozen C1 support and P0 positive keys; do not replace by D1 outgoing keys',
            'For each stored edge: i != j and integer 0 < D_ij <= C1_C_ij <= min(S_i,S_j)',
            'D_ij and D_ji need not match; their sum may exceed C1_C_ij',
            'sum_(i,j) D_ij equals sum_s number of distinct directed edges in eligible train session s',
            'sum D <= 2 * sum C1_C; distinct global D edges <= 2 * distinct global C1 pairs; these are count bounds, not raw scan-work or runtime bounds',
            'Singleton/no-transition sessions add zero D edges but remain in shared S_i; no-transition keys must not disappear'])
        fixed('history', {'set': 'Distinct union of same-session baskets through query_ms and basket_index inclusive, including current basket; identical to stored C1 query history',
            'current_basket_included': True, 'visitor_lifetime_history': False, 'cross_role_past_context': True,
            'multiplicity': 'Each distinct seed once; no last-N cap, recency weight or last-basket-only substitution',
            'unknown_seed': 'Keep trace; S_i absent gives exact zero, never divide by zero or drop query',
            'missing_or_empty_current_join': 'Stop; accepted current basket is nonempty, so this is not a fallback condition',
            'forbidden': ['targets', 'next_view_ms', 'future_baskets', 'session_end_or_total_length', 'cart_or_transaction',
                          'test_values', 'known_reference_hits', 'diagnostic_seen_or_activity_flags']})
        fixed('ranking', {'K': 10, 'catalog': 'All accepted catalog IDs with first_view_ms < query_ms; same complete causal catalog as C1/P0',
            'score': 'sum(D_ij / S_i for distinct i in H(q) if i != j and S_i > 0); absent directed edge contributes zero',
            'arithmetic': 'exact reduced rational; no floating tie tolerance',
            'order': ['directed_rational_score_descending', 'frozen_P0_count_descending', 'numeric_itemid_ascending'],
            'previously_seen_removed': False,
            'full_fallback': 'If every causal candidate has zero D1 score, exactly reuse P0 full-catalog order',
            'partial_fallback': 'Fill zero-score slots by full frozen P0-count/numeric-ID order over all causal candidates, excluding already chosen IDs; not a truncated P0 top10 append',
            'unknown_candidate': 'Retain every candidate. Missing D1 edges contribute zero; independently look up the frozen P0 count and use zero only if that P0 key is absent. A candidate without D1 incoming/outgoing evidence can still have positive P0 count, which must remain unchanged for tie/fill.',
            'short_catalog': 'Return min(10, candidate_count) unique IDs; no padding',
            'empty_catalog': 'Empty rank; keep nonempty-target query with zero retrieval metrics',
            'negative_sampling': False, 'target_injection': False, 'availability_filter': False, 'property_features': False,
            'exact_optimization': 'All directed outgoing neighbors for all history seeds plus proven full zero-score complement; no top-L/ANN/sample/candidate cap'})
        equal('ranking_bounds', policy['ranking']['audit_bounds'], [
            'D1 candidate scores <= C1 scores mathematically at the same H and S; this does not order retrieval metrics',
            'D1 positive candidate set is a subset of C1 positive set; supported-seed count using S is identical',
            'Every C1 no-positive-evidence query must also fully fall back in D1; the converse need not hold'])
        fixed('evaluation', {'roster': 'queries.csv exact validation role; three-way complete key and stored order equality with C1 queries.jsonl and P0 outputs',
            'key': ['visitorid', 'session_start_ms', 'query_ms'], 'missing_extra_duplicate_policy': 'Stop; never inner-join away a query',
            'primary_estimand': 'mean_q(NDCG_D1(q)-NDCG_C1(q)) over all 166897 validation queries',
            'secondary_comparison': 'D1-P0 differences are descriptive only; preserve original C1-P0 report as historical reference',
            'metrics': 'Unchanged P0 v1 full-target NDCG/Recall/HitRate/MRR, visitor-macro NDCG and common-union coverage; full target includes unreachable items',
            'conditional': 'Same 161211 all-targets-reachable queries, separate descriptive denominator; never substitute for main',
            'performance_pass_threshold': None, 'float_absolute_tolerance': 1e-12, 'float_relative_tolerance': 1e-12,
            'nonfinite': 'forbidden; explicit null plus reason for undefined groups', 'counts_keys_history_rational_ranks': 'exact',
            'source_exposure': 'P0 and C1 validation, diagnostics and intervals were observed before D1 selection; future D1 is a new exposed-development comparison, not a pristine holdout.'})
        equal('fixed_validation_parent', policy['fixed_validation'], c1_policy['fixed_validation'])
        v = p0['validation']; expected = {k: v[k] for k in ('queries', 'visitors', 'target_occurrences',
            'reachable_target_occurrences', 'all_targets_reachable_queries', 'candidate_union_items', 'support_floor_queries')}
        expected.update(new_visitor_queries=v['slices']['visitor_history']['new']['queries'],
            multi_item_current_queries=v['slices']['current_basket']['multiple']['queries'],
            multi_item_target_queries=v['slices']['target_basket']['multiple']['queries'],
            target_model_query_counts={k: x['queries'] for k, x in v['slices']['target_model'].items()})
        for key, value in expected.items(): equal('fixed_validation_reference.' + key, policy['fixed_validation'][key], value)
        equal('required_full_queries', expected['queries'], 166897)
        equal('required_full_visitors', expected['visitors'], 62235)
        equal('C1_full_queries', c1['scope']['validation_queries'], expected['queries'])
        fixed('uncertainty', {'primary_only': 'D1-C1 query-macro NDCG difference',
            'method': 'paired visitor-cluster percentile bootstrap', 'replicates': 2000, 'seed': 42,
            'numpy_version': '2.5.4', 'bit_generator': 'PCG64',
            'cluster_order': 'ascending numeric visitorid, exactly 62235 visitors',
            'draw': 'rng.integers(0,V,size=V,dtype=np.int64), V=62235, Generator(PCG64(42)), replicate order 0..1999',
            'reference_value': 'Round-trip binary64 C1 NDCG from accepted C1 query JSONL; copy original P0 values for descriptive D1-P0',
            'reduction': 'Per-query D1 binary64 minus copied C1 binary64; main math.fsum in accepted query order. Per-visitor d_v=math.fsum in within-visitor query order; each replicate math.fsum(w_v*d_v in numeric visitor order)/sum(w_v*n_v) with exact integer denominator. Do not average visitor means.',
            'confidence_level': 0.95, 'quantiles': [0.025, 0.975], 'quantile_method': 'linear',
            'audit_reuse': 'Verify each draw SHA (little-endian signed int64), RNG before/after and sampled query denominator against accepted C1 bootstrap; compute NEW D1-C1 deltas and interval in D1 namespace only. Never copy C1-P0 deltas/interval as D1 results.',
            'D1_P0_interval': False, 'secondary_or_slice_intervals': False, 'p_values': False,
            'multiple_comparison_policy': 'One prespecified primary contrast only. No simultaneous two-control superiority claim or new family-wise inference. All secondary differences descriptive.',
            'interpretation': 'Conditional exposed-development resampling only; report unfavorable or cross-zero interval unchanged, no automatic model selection/test unlock.'})
        equal('old_bootstrap_replicates', c1['validation']['uncertainty']['replicates'], 2000)
        equal('old_bootstrap_visitors', c1['validation']['uncertainty']['visitors'], 62235)
        for key in ('replicates', 'seed', 'numpy_version', 'bit_generator', 'confidence_level', 'quantiles', 'quantile_method'):
            equal('same_draw_recipe.' + key, policy['uncertainty'][key], c1_policy['uncertainty'][key])
        fixed('slices_and_diagnostics', {'shared_membership': 'Exact inherited C1/P0 visitor seen/new, current/target one/multiple, original train activity 0/1/2-5/6+, and target support based on shared frozen C1 S_i/P0 positive keys',
            'support_floor_queries': 1669, 'visitor_counts_separate': True,
            'small_groups': {'current_multiple': 56, 'target_multiple': 53, 'mixed_target_support': 3},
            'small_group_rule': 'descriptive_only; no removal/merge/tuning or slice CI; original train/test and Olist/UCI restrictions retained',
            'cold_reference': '11943 all-zero shared-support target queries had zero C1/P0 NDCG, Recall, HitRate and MRR; coverage is not asserted zero. This is not a prediction of D1 performance, and does not mean all targets are unreachable or never seen.',
            'D1_metrics_known': False})
        equal('distinct_outgoing_incoming_diagnostics', policy['slices_and_diagnostics']['D1_extra_diagnostics'], [
            'shared-S supported seeds (must match C1)',
            'history seeds with at least one D1 outgoing edge; not a replacement support definition',
            'incoming-edge target coverage: all/mixed/none, complete denominator, descriptive only',
            'positive causal candidate count 0 / 1-9 / at_least_10 and zero-fill slots',
            'mutually exclusive reason: positive_evidence; else no_shared_supported_seed; else no_outgoing_seed; else no_positive_causal_neighbor',
            'C1 full-fallback implies D1 full-fallback; report extra D1 fallback without dropping queries'])
        equal('support_floor_formula', policy['slices_and_diagnostics']['support_floor_queries'], max(50, (expected['queries'] + 99) // 100))
        fixed('resources_and_next_entry', {'this_round_scan': False,
            'train_only_preflight': 'Before real D1 fit, independently count original adjacent train basket pairs, raw cross-products excluding diagonal, repeated directed emissions and per-session unique edge totals/maxima; temporary per-session sets only, no global D1 table. Role metadata may be scanned for filtering; decode item arrays only for train baskets, never validation/test item arrays or targets; no validation/test ranking.',
            'counts_to_reconcile': 'raw=sum_adj(|A|*|B|-|A intersection B|); unique=sum_s|E_s|; sum fitted D_ij=unique. Raw can exceed 2*sum C1_C due to repeats; no raw/runtime promise from bound.',
            'limits': {'maximum_process_RSS_bytes': 8*1024**3, 'maximum_execution_disk_bytes': 20*1024**3,
                       'minimum_free_disk_bytes': 8*1024**3, 'minimum_available_memory_bytes': 4*1024**3,
                       'maximum_elapsed_seconds': 21600, 'monitor_interval_seconds': 0.5},
            'on_exceed': 'Stop and preserve started/failure/partial evidence; no sampling, truncation, relaxed denominator or silent retry',
            'entry_gate': 'Implement D1, three-arm adapter, bootstrap and independent synthetic oracle first; then train-only cost audit and separately frozen real-validation entry. This spec does not implement or launch that entry.'})
        fixed('reserved_test', {'state': 'locked', 'enabled_this_round': False, 'D1_test_authorized': False,
            'reuse_P0_or_C1_gate': False, 'future_final_selection_refit_test_protocol_required': True,
            'create_test_output_or_usage_journal': False, 'logical_tests_consumed_this_round': 0,
            'rule': 'Preserve P0 eight technical/identity/explicit-scope gates and C1 final-choice restriction; favorable development result or this specification cannot open test. No final-refit/test command this round.'})
        fixed('planned_acceptance', {'private_execution_root': 'shop-mysql-runtime/retailrocket_directed_paired_v1/',
            'D1_implemented': False, 'reentry': 'Complete verify-only; partial evidence preserved and replay/overwrite refused',
            'independent_oracle': 'Separate SQL/relational original adjacent basket join and DISTINCT(session,i,j), independent shared S reconstruction and equality check, counts/lineage conservation, exact rational complete ranking with full zero complement, independent Decimal/Fraction metrics, all nested query values and all bootstrap replicates; no sampled acceptance.'})
        require('planned_synthetic_coverage', len(policy['planned_acceptance']['synthetic_cases']) == 13
                and len(set(policy['planned_acceptance']['synthetic_cases'])) == 13)
        require('complete_artifact_plan', len(policy['planned_acceptance']['artifacts']) == 6)
        equal('limitations', policy['limitations'], [
            'Validation P0 and C1 results were exposed before selection; D1 is not unseen validation or final testing',
            'D1 jointly changes direction and adjacency, not a single isolated causal direction effect',
            'Shared S normalization and complete H make this a custom association score, not standard first-order MC or a probability',
            'No new item content; train-unsupported cold-item gap remains; new visitor with current history is not context-free cold start',
            'Small-group, anonymous-key, missing ingestion/revision/completeness/exposure/propensity/inventory limitations remain',
            'No conversion/revenue/causal/commercial deployment claim; existing CC BY-NC-SA 4.0 conditions and Olist/UCI restrictions retained'])
        selection = inventory['selection']
        for key, value in {'candidate': policy['comparison']['challenger'], 'candidate_count': 1,
                           'validation_already_exposed': True, 'P0_and_C1_scores_known_before_selection': True,
                           'D1_scores_not_computed': True}.items(): equal('inventory_selection.' + key, selection[key], value)
        candidates = inventory['candidates']
        equal('candidate_families', [c['family'] for c in candidates],
              ['directed_adjacent_association', 'session_knn', 'implicit_als', 'bpr', 'ease_dense'])
        equal('candidate_decisions', [c['decision'] for c in candidates],
              ['selected_custom_D1', 'deferred', 'deferred', 'deferred', 'not_selected_under_current_resource_envelope'])
        expected_urls = {'session_evaluation': 'https://arxiv.org/abs/1803.09587v2',
                         'implicit_als': 'https://yifanhu.net/PUB/cf.pdf',
                         'bpr': 'https://arxiv.org/abs/1205.2618v1', 'ease': 'https://arxiv.org/abs/1905.03375v1'}
        equal('primary_source_urls', {s['id']: s['url'] for s in inventory['primary_sources']}, expected_urls)
        equal('primary_source_count', len(inventory['primary_sources']), 4)
        require('candidate_source_mapping', all(set(c['source_ids']) <= expected_urls.keys() and c['source_ids'] for c in candidates))
        evidence = inventory['existing_evidence']; estimate = inventory['dense_EASE_structural_estimate']
        equal('inventory_positive_items', evidence['positive_train_items'], c1['fit_audit']['positive_support_items'])
        for k, n in [('validation_queries', 166897), ('new_visitor_queries', 134249), ('cold_target_queries', 11943)]:
            equal('inventory_evidence.' + k, evidence[k], n)
        equal('inventory_fallback_reference', evidence['C1_full_fallback_queries'],
              sum(n for k, n in c1['validation']['diagnostics']['fallback_reason'].items() if k != 'positive_evidence'))
        equal('estimate_items', estimate['items'], evidence['positive_train_items'])
        equal('estimate_bytes', estimate['float64_matrix_bytes'], estimate['items']**2*8)
        equal('estimate_GiB', estimate['GiB'], estimate['float64_matrix_bytes']/1024**3)
        equal('estimate_not_benchmark', estimate['kind'], 'one_matrix_arithmetic_from_existing_public_aggregate_not_empirical_peak')
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        raise ValueError('Missing or invalid D1 specification metadata') from error
    return checks
