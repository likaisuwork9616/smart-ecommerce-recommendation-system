"""Specification consistency checks only; no popularity fit, ranking or metrics."""
from __future__ import annotations


def validate(policy, parent, build):
    checks=[]
    def require(name,condition):
        if not condition:raise ValueError('Protocol consistency: '+name)
        checks.append(name)
    try:
        require('protocol_identity',policy['protocol_id']=='retailrocket_popularity_execution_v1' and policy['version']==1)
        scope=policy['scope_this_round']
        require('freeze_only_no_real_execution',scope=={'specification_freeze_only':True,'real_statistic_fits':0,'real_ranked_queries':0,'real_metric_calculations':0,'reserved_test_enabled':False,'implementation_complete':False})
        a=policy['algorithm']
        require('sole_deterministic_candidate',a['candidate_count']==1 and a['deterministic'] is True and a['hyperparameter_search'] is False)
        require('view_only_fit',a['fit_event_types']==['view'] and a['fit_source']=='qualified_events.csv')
        require('warmup_and_tail_excluded_from_fit',a['include_warmup_in_fit'] is False and a['include_tail_in_fit'] is False)
        require('labels_not_fit_inputs',a['fit_uses_query_labels'] is False and a['include_unlabelled_session_ends_in_fit'] is True)
        dev=a['development_fit'];final=a['final_refit']
        require('development_roles',dev['roles']==['train'] and dev['evaluation_roles']==['validation'])
        require('development_clock',dev['start_inclusive_utc']==parent['time_roles']['train'][0] and dev['end_exclusive_utc']==parent['time_roles']['train'][1])
        require('final_roles',final['roles']==['train','validation'] and final['evaluation_roles']==['reserved_test'])
        require('final_clock',final['start_inclusive_utc']==parent['time_roles']['train'][0] and final['end_exclusive_utc']==parent['time_roles']['validation'][1])
        require('one_primary_fit_per_phase',dev['primary_fit_limit']==final['primary_fit_limit']==1)
        require('frozen_statistics',dev['statistics_frozen_during_evaluation'] is True and final['statistics_frozen_during_evaluation'] is True)
        require('final_refit_separate_and_gated',final['separate_artifact_from_development'] is True and final['requires_development_acceptance_and_frozen_implementation'] is True)
        rank=policy['ranking_and_fallback'];e=policy['evaluation']
        require('fixed_K10',rank['K']==e['K']==10)
        require('integer_popularity_order',rank['order']==['count_descending','numeric_itemid_ascending'])
        require('no_seen_or_availability_or_property_filter',rank['remove_previously_seen'] is False and rank['availability_filter'] is False and rank['item_property_features'] is False)
        require('ranker_does_not_receive_labels',rank['ranker_inputs']==['frozen_item_count_table','query_ms','causal_catalog_item_ids'])
        require('label_and_future_fields_forbidden',{'target_items','next_view_ms','session_end_or_total_length','future_event_or_property_values','test_aggregates'}.issubset(set(rank['forbidden_ranker_inputs'])))
        require('full_catalog_without_sampling_or_target_injection',e['negative_sampling'] is False and e['target_injection'] is False and rank['no_global_topk_shortcut_without_proof'] is True)
        require('full_query_denominator',e['primary_denominator']=='all_eligible_queries' and e['eligible_filter']=='exact role equality only; all source queries in that role already have status=labelled')
        require('full_target_IDCG',e['idcg_target_basis']=='full_target_set')
        require('causal_union_coverage_denominator',e['catalog_coverage_denominator']=='union_causal_catalogs')
        require('empty_catalog_keeps_query',e['empty_catalog_policy']=='retain_query_zero_retrieval_metrics')
        require('no_training_resubstitution_or_performance_threshold',e['training_metrics'] is False and e['performance_pass_threshold'] is None)
        require('finite_metric_tolerances',e['precision']['float_absolute_tolerance']==e['precision']['float_relative_tolerance']==1e-12)
        mapping={'queries':lambda r:r['statuses']['labelled'],'visitors':lambda r:r['labelled_visitors'],
                 'target_occurrences':lambda r:r['labelled_targets'],'reachable_target_occurrences':lambda r:r['reachable_targets'],
                 'all_targets_reachable_queries':lambda r:r['all_targets_reachable_queries'],'new_visitor_queries':lambda r:r['new_visitor_queries'],
                 'multi_item_current_basket_queries':lambda r:r['multi_item_context_queries'],'multi_item_target_basket_queries':lambda r:r['multi_item_target_queries'],
                 'support_floor_queries':lambda r:r['support_floor_queries']}
        for role in ('validation','reserved_test'):
            expected={name:fn(build['summary']['roles'][role]) for name,fn in mapping.items()}
            actual=policy['fixed_denominators_from_accepted_build'][role]
            require(role+'_denominators_match_accepted_dataset',actual==expected)
            require(role+'_support_floor',actual['support_floor_queries']==max(50,(actual['queries']+99)//100))
            require(role+'_multi_item_small_groups_preserved',0<actual['multi_item_current_basket_queries']<actual['support_floor_queries'] and 0<actual['multi_item_target_basket_queries']<actual['support_floor_queries'])
        gate=policy['reserved_test_gate']
        require('test_initially_locked',gate['initial_state']=='locked' and gate['enabled_this_round'] is False)
        require('later_explicit_test_request',gate['later_explicit_test_execution_request_required'] is True)
        require('no_performance_based_test_gate',gate['performance_gates']==[])
        require('one_logical_reserved_test',gate['logical_test_runs']==1)
        require('all_test_prerequisites_retained',len(gate['requirements'])==8 and len(set(gate['requirements']))==8)
        require('implementation_not_claimed',policy['planned_artifacts_and_acceptance']['implementation_not_yet_started_at_freeze'] is True)
        require('upstream_no_scoring_claim',build['scope']['model_fits']==build['scope']['ranking_metrics']==0 and build['scope']['reserved_test_scored'] is False)
    except (KeyError,TypeError,IndexError) as error:
        raise ValueError('Missing or invalid protocol schema') from error
    return checks
