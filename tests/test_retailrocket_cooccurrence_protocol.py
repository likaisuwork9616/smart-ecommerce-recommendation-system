"""Reject protocol changes that would invalidate a future paired comparison."""
import copy
import json
from pathlib import Path
import unittest

from scripts.retailrocket_cooccurrence_protocol import validate

ROOT = Path(__file__).resolve().parents[1]


class CooccurrenceProtocolTests(unittest.TestCase):
    def setUp(self):
        paths = ['docs/contracts/retailrocket_cooccurrence_paired_v1.json',
                 'docs/contracts/retailrocket_recommendation_v1.json',
                 'reports/stage9/retailrocket_popularity_v1_development.json',
                 'reports/stage9/retailrocket_popularity_v1_development_acceptance.json']
        self.inputs = [json.loads((ROOT / p).read_text(encoding='utf-8')) for p in paths]

    def test_accepted_metadata_and_fixed_specification(self):
        checks = validate(*self.inputs)
        self.assertGreaterEqual(len(checks), 100)
        self.assertEqual(len(checks), len(set(checks)))


# Each test changes one research decision; this suite verifies the specification
# guard, not unimplemented C1 counts, rankings, bootstrap or real-data accuracy.
MUTATIONS = [
    ('scope_this_round', 'real_C1_fits', 1),
    ('scope_this_round', 'real_bootstrap_replicates', 2000),
    ('comparison', 'fit_roles', ['train', 'validation']),
    ('comparison', 'fit_end_exclusive_utc', '2015-08-02T00:00:00Z'),
    ('comparison', 'warmup_in_fit', True),
    ('comparison', 'statistics_update_during_evaluation', True),
    ('comparison', 'P0_reuse', 'refit P0'),
    ('comparison', 'challenger_count', 2),
    ('comparison', 'hyperparameter_search', True),
    ('cooccurrence_counts', 'item_support', 'count repeat views'),
    ('cooccurrence_counts', 'pair_support', 'count directed adjacent events'),
    ('cooccurrence_counts', 'minimum_session_items', 2),
    ('cooccurrence_counts', 'boundary_policy', 'drop sessions using future end'),
    ('cooccurrence_counts', 'unordered_pair_storage', 'include self pairs'),
    ('cooccurrence_counts', 'same_timestamp', 'invent timestamp-tie order'),
    ('cooccurrence_counts', 'minimum_pair_support', 2),
    ('cooccurrence_counts', 'neighbor_top_L', 100),
    ('cooccurrence_counts', 'max_session_items', 100),
    ('cooccurrence_counts', 'max_query_history_items', 20),
    ('cooccurrence_counts', 'pruning_or_sampling', True),
    ('cooccurrence_counts', 'count_invariants', []),
    ('cooccurrence_counts', 'resource_preflight', 'silently cap high-cost sessions'),
    ('causal_query_history', 'history_set', 'all future baskets of visitor'),
    ('causal_query_history', 'includes_current_same_timestamp_basket', False),
    ('causal_query_history', 'visitor_lifetime_history', True),
    ('causal_query_history', 'cross_role_past_context', 'update fit with validation'),
    ('causal_query_history', 'unknown_history_item', 'drop query'),
    ('causal_query_history', 'empty_history', 'silently fallback'),
    ('causal_query_history', 'forbidden_inputs', []),
    ('ranking_and_fallback', 'candidate_catalog', 'sample negatives'),
    ('ranking_and_fallback', 'score', 'normalize by candidate support'),
    ('ranking_and_fallback', 'arithmetic', 'float approximate ties'),
    ('ranking_and_fallback', 'order', ['numeric_itemid_ascending']),
    ('ranking_and_fallback', 'remove_previously_seen', True),
    ('ranking_and_fallback', 'full_fallback', 'drop no evidence'),
    ('ranking_and_fallback', 'partial_fallback', 'append truncated P0 top10'),
    ('ranking_and_fallback', 'empty_catalog', 'exclude query'),
    ('ranking_and_fallback', 'fallback_P0_refit', True),
    ('ranking_and_fallback', 'blend_alpha_or_tuned_weight', 0.5),
    ('paired_evaluation', 'join', 'inner join surviving queries'),
    ('paired_evaluation', 'targets_and_candidates', 'reachable target denominator'),
    ('paired_evaluation', 'primary_denominator', 'conditional_only'),
    ('paired_evaluation', 'catalog_coverage_denominator', 'recommended_items'),
    ('paired_evaluation', 'performance_pass_threshold', 0.01),
    ('fixed_validation', 'queries', 161211),
    ('fixed_validation', 'visitors', 62234),
    ('fixed_validation', 'multi_item_current_queries', 0),
    ('fixed_validation', 'target_model_query_counts', {}),
    ('P0_identity', 'fit_id', 'new_fit'),
    ('P0_identity', 'ranked_queries_sha256', 'different_roster'),
    ('uncertainty', 'method', 'iid query bootstrap'),
    ('uncertainty', 'replicates', 1000),
    ('uncertainty', 'seed', 43),
    ('uncertainty', 'numpy_version', 'unbound'),
    ('uncertainty', 'cluster_order', 'arbitrary order'),
    ('uncertainty', 'replicate_formula', 'unweighted mean of visitor deltas'),
    ('uncertainty', 'quantile_method', 'nearest'),
    ('uncertainty', 'secondary_or_slice_intervals', True),
    ('slice_support_and_diagnostics', 'support_floor', '50'),
    ('reserved_test', 'enabled_this_round', True),
    ('reserved_test', 'reuse_P0_gate_as_C1_authorization', True),
    ('reserved_test', 'future_final_selection_refit_and_test_protocol_required', False),
    ('planned_acceptance_and_artifacts', 'implementation_complete', True),
]


def reject_mutation(section, key, value):
    def test(self):
        inputs = copy.deepcopy(self.inputs)
        inputs[0][section][key] = value
        with self.assertRaises(ValueError):
            validate(*inputs)
    return test


for number, (section, key, value) in enumerate(MUTATIONS, 1):
    setattr(CooccurrenceProtocolTests, f'test_reject_{number:02}_{section}_{key}', reject_mutation(section, key, value))


if __name__ == '__main__':
    unittest.main()
