"""Validate the C1/P0 specification against accepted metadata; no model execution."""
from __future__ import annotations


def validate(policy, parent, baseline, acceptance):
    checks = []

    def require(name, condition):
        if not condition:
            raise ValueError('C1/P0 protocol consistency: ' + name)
        checks.append(name)

    def fixed(section, expected):
        for key, value in expected.items():
            require(section + '.' + key, policy[section][key] == value)

    try:
        require('identity', policy['protocol_id'] == 'retailrocket_cooccurrence_paired_v1' and policy['version'] == 1)
        require('validation_exposure_disclosed', policy['status'] == 'frozen_before_C1_implementation_and_scoring_after_P0_validation_observed')
        fixed('scope_this_round', {
            'specification_only': True, 'C1_implemented': False, 'real_C1_fits': 0,
            'new_P0_fits': 0, 'real_new_ranked_queries': 0, 'real_paired_metrics': 0,
            'real_bootstrap_replicates': 0, 'real_data_CSV_rows_parsed': 0, 'reserved_test_enabled': False})
        fixed('comparison', {
            'control': 'P0_global_canonical_view_count', 'challenger': 'C1_binary_session_conditional_sum',
            'challenger_count': 1, 'hyperparameter_search': False, 'deterministic_models': True,
            'P0_reuse': 'reuse accepted P0 fit table, ranked queries, per-query metrics and aggregates byte-for-byte; no refit or reranking',
            'C1_primary_fit_limit': 1, 'fit_roles': ['train'], 'evaluation_roles': ['validation'],
            'warmup_in_fit': False, 'validation_in_fit': False, 'statistics_update_during_evaluation': False,
            'training_ranking': False, 'final_refit': False, 'test_ranking': False})
        c = policy['comparison']
        require('fit_clock_matches_parent', [c['fit_start_inclusive_utc'], c['fit_end_exclusive_utc']] == parent['time_roles']['train'])
        require('accepted_P0_not_new_result', baseline['status'] == 'development_fit_and_full_validation_independently_accepted'
                and acceptance['status'] == 'all_validation_output_cells_and_aggregates_independently_accepted')
        p0 = policy['P0_identity']
        require('P0_fit_identity', p0['fit_id'] == baseline['fit_audit']['fit_id']
                and p0['positive_fit_items'] == baseline['fit_audit']['positive_items'] == 198946)
        files = {r['path'].split('/')[-1]: r for r in baseline['files']}
        for name in ('item_counts', 'ranked_queries', 'query_metrics'):
            require('P0_' + name + '_identity', p0[name + '_sha256'] == files[name + '.csv']['sha256'])
        require('observed_P0_metrics_only', p0['observed_validation_ndcg'] == baseline['validation']['metrics']['ndcg']
                and p0['observed_validation_hit_rate'] == baseline['validation']['metrics']['hit_rate'])
        require('P0_test_still_locked', baseline['scope']['reserved_test_state'] == 'locked'
                and baseline['scope']['reserved_test_ranked_queries'] == baseline['scope']['final_refits'] == 0)
        fixed('cooccurrence_counts', {
            'source_columns': {'basket_clock': 'query_ms UTC epoch milliseconds', 'memberships': 'items JSON array of distinct canonical numeric-ID strings', 'index': 'basket_index', 'role': 'role'},
            'session_key': ['visitorid', 'session_start_ms'],
            'fit_session_set': 'B_s = distinct item IDs in accepted view baskets with role=train and fit_start <= timestamp < fit_end, grouped by unchanged accepted session key',
            'boundary_policy': 'clip each session to eligible train prefix; ignore warmup and validation members; never use final session length/end or future members to select, merge or delete a session',
            'minimum_session_items': 1,
            'singleton_sessions': 'contribute item support S_i even though they emit no pair',
            'item_support': 'S_i = number of eligible train session sets B_s containing i; one contribution per item/session regardless of repeat views or timestamps',
            'pair_support': 'C_ij = number of eligible train session sets B_s containing both distinct i and j; one contribution per unordered pair/session',
            'unordered_pair_storage': 'canonical numeric item ID order i<j; C_ij=C_ji on lookup; no diagonal self pair C_ii',
            'same_timestamp': 'items in one unordered same-millisecond view basket may cooccur; do not invent click order',
            'minimum_pair_support': 1, 'neighbor_top_L': None, 'max_session_items': None,
            'max_query_history_items': None, 'pruning_or_sampling': False,
            'extra_filters': 'none: no bots/activity/k-core removal, recency weighting, window search, rare-item pruning or validation-dependent filtering',
            'count_invariants': ['S_i positive integers; key set equals accepted P0 positive-fit item key set, including singleton-only items',
                'S_i <= frozen P0 count_i', '0 < C_ij <= min(S_i,S_j) for stored distinct pairs',
                'sum_i S_i = sum_s |B_s|', 'sum_(i<j) C_ij = sum_s |B_s|*(|B_s|-1)/2'],
            'resource_preflight': 'before real fit, report train-only session cardinalities and exact pair-emission work; bind disk/memory/runtime limits in implementation entry; exact chunking/spill inside shop allowed, silently capping/pruning/sampling is forbidden; insufficient resources stop execution or require a new method protocol'})
        fixed('causal_query_history', {
            'history_set': 'H(q) = distinct union of all view basket items in the same accepted session with basket_index <= query basket_index and timestamp <= query_ms',
            'includes_current_same_timestamp_basket': True, 'visitor_lifetime_history': False,
            'item_multiplicity': 'each distinct history item contributes once; no repeat-view amplification, last-N cap, decay or history-length search',
            'cross_role_past_context': 'same-session warmup/train/past-validation context may be used only when already observed by query time; it never updates S_i or C_ij',
            'unknown_history_item': 'keep in history trace; if S_i absent it contributes exact zero, not division by zero or a reason to drop query',
            'empty_history': 'invalid for the accepted nonempty current-basket query contract; stop on missing/empty join rather than hiding a data error as fallback',
            'forbidden_inputs': ['target_items', 'next_view_ms', 'future baskets or rows', 'session_last_time_or_total_length',
                'cart_or_transaction_history', 'P0 per-query metric or known hit status', 'test labels or test aggregates',
                'whole-training activity or seen flags as ranking features']})
        fixed('ranking_and_fallback', {
            'K': 10,
            'candidate_catalog': 'identical parent C(q): all catalog.csv IDs with first_view_ms < query_ms; no future/property-only items, availability filter, negative sampling or target injection',
            'score': 'A_q(j) = sum over distinct i in H(q), i!=j and S_i>0, of C_ij/S_i; missing pair contributes zero',
            'arithmetic': 'exact reduced rational numerator/denominator; compare by exact fractions/cross-products, no floating score tie tolerance',
            'order': ['cooccurrence_rational_score_descending', 'frozen_P0_integer_count_descending', 'numeric_itemid_ascending'],
            'remove_previously_seen': False,
            'self_pair': 'no self-edge contribution, but history item remains a candidate and may receive evidence from other history items or P0 tie/fill',
            'full_fallback': "if no causal candidate has positive A score, ranking exactly equals accepted P0 for that query's complete causal catalog",
            'partial_fallback': 'positive A-score candidates rank first; if fewer than K, fill zero-score candidates by frozen P0 count then numeric ID, excluding already selected IDs; not merely append a truncated P0 list',
            'unknown_candidate_item': 'retain in C(q), score zero and P0 count zero when absent; same numeric-ID tie rule',
            'empty_catalog': 'return empty list; keep valid nonempty-target query with zero retrieval metrics',
            'list_size': 'min(10, |C(q)|) unique IDs; exact complete-catalog total-order top K',
            'fallback_P0_refit': False, 'blend_alpha_or_tuned_weight': None,
            'exact_optimization': 'sparse accumulation over all neighbors of history seeds plus exact P0 zero-fill is allowed only with all-candidate count and exact ranking proof; no neighbor top-L, history cap or sampled catalog'})
        fixed('paired_evaluation', {
            'query_key': ['visitorid', 'session_start_ms', 'query_ms'],
            'join': 'one-to-one complete key/order equality with accepted P0 ranked_queries/query_metrics; missing/extra/duplicate keys stop, never inner-join away difficult cases',
            'targets_and_candidates': 'same complete target set and causal candidate count per query for both methods; unreachable targets remain in Recall and full-target IDCG',
            'primary_estimand': 'Delta_Q = mean over all fixed validation queries of (NDCG_C1(q)-NDCG_P0(q))',
            'primary_denominator': 'all_166897_validation_queries',
            'catalog_coverage_denominator': 'common validation causal candidate union 222754; coverage difference is difference of two union-based coverages, not average per-query coverage',
            'conditional': 'same 161211 queries whose entire target set is causal-catalog reachable; paired descriptive results with separate denominators, never replace main',
            'performance_pass_threshold': None, 'float_tolerance': {'absolute': 1e-12, 'relative': 1e-12},
            'no_training_or_test_scoring': True})
        v = baseline['validation']
        expected = {k: v[k] for k in ('queries', 'visitors', 'target_occurrences', 'reachable_target_occurrences',
                    'all_targets_reachable_queries', 'candidate_union_items', 'support_floor_queries')}
        expected.update(new_visitor_queries=v['slices']['visitor_history']['new']['queries'],
                        multi_item_current_queries=v['slices']['current_basket']['multiple']['queries'],
                        multi_item_target_queries=v['slices']['target_basket']['multiple']['queries'],
                        target_model_query_counts={k: x['queries'] for k, x in v['slices']['target_model'].items()})
        fixed('fixed_validation', expected)
        require('small_groups_preserved', expected['support_floor_queries'] == max(50, (expected['queries'] + 99) // 100)
                and expected['multi_item_current_queries'] < 1669 and expected['multi_item_target_queries'] < 1669)
        fixed('uncertainty', {
            'estimand': 'primary Delta_Q only', 'method': 'paired visitor-cluster percentile bootstrap',
            'cluster_key': 'anonymous visitorid; include every validation query of a selected visitor together in both arms',
            'cluster_order': 'ascending numeric visitorid over exactly 62235 validation visitor keys',
            'replicates': 2000, 'seed': 42, 'numpy_version': '2.5.4', 'bit_generator': 'PCG64',
            'draw': 'for each replicate in order, rng.integers(0,V,size=V,dtype=np.int64) from np.random.Generator(np.random.PCG64(42)); V=62235',
            'replicate_formula': 'for each visitor v let n_v=query count and d_v=sum paired NDCG deltas; with draw multiplicity w_v, Delta_b=sum_v w_v*d_v / sum_v w_v*n_v',
            'numeric_reduction': 'binary64 C1 NDCG minus round-trip parsed accepted P0 NDCG; main mean uses math.fsum in accepted query order; d_v uses math.fsum in accepted within-visitor query order; weighted numerator uses math.fsum(w_v*d_v in numeric visitor order), denominator uses exact integers; percentile input is float64 replicate order',
            'query_weighting': 'ratio of weighted sums; do not average visitor means for the query-macro estimand, do not sample queries independently',
            'confidence_level': 0.95, 'quantiles': [0.025, 0.975], 'quantile_method': 'linear',
            'quantile_call': "np.quantile(replicate_deltas,[0.025,0.975],method='linear')",
            'draw_audit': 'per replicate hash indices as canonical little-endian signed int64 C-order bytes; preserve before/after RNG state, sampled query denominator and delta; independent oracle regenerates identical draw hashes and recomputes all replicates',
            'secondary_or_slice_intervals': False, 'p_values': False})
        fixed('slice_support_and_diagnostics', {
            'support_floor': 'max(50,ceil(166897/100))=1669 queries; separately report visitors and target occurrences',
            'empty_slice': 'null metrics with explicit no-sample reason',
            'inference': 'no slice significance, CI-based slice picking, post-hoc merging, dropping or tuning; bootstrap only for prespecified overall paired primary delta'})
        fixed('reserved_test', {'state': 'locked', 'enabled_this_round': False,
            'later_comparison_implementation_may_open_test': False, 'reuse_P0_gate_as_C1_authorization': False,
            'future_final_selection_refit_and_test_protocol_required': True, 'test_fit_or_rank_or_bootstrap': False,
            'test_output_or_usage_journal_created': False})
        fixed('planned_acceptance_and_artifacts', {'private_execution_root': 'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/',
            'implementation_complete': False,
            'execution_reentry': 'complete outputs verify only; partial evidence preserved, no overwrite, refit or score-based retry'})
        require('independent_acceptance_planned', len(policy['planned_acceptance_and_artifacts']['synthetic_cases_before_real_execution']) == 12
                and len(policy['planned_acceptance_and_artifacts']['uncertainty_outputs']) == 3)
        require('retrospective_and_license_limits', len(policy['limitations']) == 7
                and policy['limitations'][0].startswith('P0 validation was already inspected'))
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        raise ValueError('Missing or invalid C1/P0 specification schema') from error
    return checks
