"""Reject protocol mutations that leak time, shrink denominators or unlock test."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.retailrocket_popularity_protocol import validate

ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
P=load('docs/contracts/retailrocket_popularity_execution_v1.json')
DATA=load('docs/contracts/retailrocket_recommendation_v1.json')
BUILD=load('reports/stage8/retailrocket_build_v1.json')


class ProtocolGuardTests(unittest.TestCase):
    def reject(self,path,value):
        policy=deepcopy(P);node=policy
        for key in path[:-1]:node=node[key]
        node[path[-1]]=value
        with self.assertRaises(ValueError):validate(policy,DATA,BUILD)
    def test_frozen_protocol_matches_accepted_source(self):self.assertGreater(len(validate(P,DATA,BUILD)),30)
    def test_validation_cannot_enter_development_fit(self):self.reject(['algorithm','development_fit','roles'],['train','validation'])
    def test_test_cannot_enter_final_refit(self):self.reject(['algorithm','final_refit','roles'],['train','validation','reserved_test'])
    def test_cutoff_shift_rejected(self):self.reject(['algorithm','development_fit','end_exclusive_utc'],'2015-08-02T00:00:00Z')
    def test_warmup_cannot_be_counted(self):self.reject(['algorithm','include_warmup_in_fit'],True)
    def test_cart_weighting_rejected(self):self.reject(['algorithm','fit_event_types'],['view','addtocart'])
    def test_labels_not_used_for_fit(self):self.reject(['algorithm','fit_uses_query_labels'],True)
    def test_multiple_candidates_rejected(self):self.reject(['algorithm','candidate_count'],2)
    def test_online_statistic_updates_rejected(self):self.reject(['algorithm','development_fit','statistics_frozen_during_evaluation'],False)
    def test_repeated_primary_fit_rejected(self):self.reject(['algorithm','final_refit','primary_fit_limit'],2)
    def test_seen_item_removal_rejected(self):self.reject(['ranking_and_fallback','remove_previously_seen'],True)
    def test_future_or_label_ranker_inputs_rejected(self):self.reject(['ranking_and_fallback','ranker_inputs'],['frozen_item_count_table','target_items'])
    def test_negative_sampling_rejected(self):self.reject(['evaluation','negative_sampling'],True)
    def test_target_injection_rejected(self):self.reject(['evaluation','target_injection'],True)
    def test_reachable_only_main_denominator_rejected(self):self.reject(['evaluation','primary_denominator'],'reachable_queries_only')
    def test_unreachable_targets_cannot_shrink_IDCG(self):self.reject(['evaluation','idcg_target_basis'],'reachable_target_set')
    def test_whole_future_catalog_coverage_rejected(self):self.reject(['evaluation','catalog_coverage_denominator'],'all_period_items')
    def test_empty_catalog_query_cannot_be_dropped(self):self.reject(['evaluation','empty_catalog_policy'],'drop_query')
    def test_validation_count_change_rejected(self):self.reject(['fixed_denominators_from_accepted_build','validation','queries'],166896)
    def test_test_visitor_count_change_rejected(self):self.reject(['fixed_denominators_from_accepted_build','reserved_test','visitors'],34874)
    def test_small_group_floor_reduction_rejected(self):self.reject(['fixed_denominators_from_accepted_build','validation','support_floor_queries'],50)
    def test_locked_test_not_activated_by_freeze(self):self.reject(['reserved_test_gate','enabled_this_round'],True)
    def test_performance_based_activation_rejected(self):self.reject(['reserved_test_gate','performance_gates'],['NDCG greater than 0.1'])
    def test_test_request_cannot_be_omitted(self):self.reject(['reserved_test_gate','later_explicit_test_execution_request_required'],False)
    def test_test_prerequisites_cannot_be_removed(self):self.reject(['reserved_test_gate','requirements'],P['reserved_test_gate']['requirements'][:-1])
    def test_multiple_logical_tests_rejected(self):self.reject(['reserved_test_gate','logical_test_runs'],2)
    def test_no_fabricated_fit_claim(self):self.reject(['scope_this_round','real_statistic_fits'],1)
    def test_missing_required_protocol_field_rejected(self):
        candidate=deepcopy(P);del candidate['evaluation']['precision']
        with self.assertRaises(ValueError):validate(candidate,DATA,BUILD)


if __name__=='__main__':unittest.main()
