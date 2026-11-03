"""Fixed-sample coverage gaps and parent fallback must remain visible."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.retailrocket_session_knn_checkpoint_v2 import encoded
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS, POLICY
from scripts.retailrocket_session_knn_refined_cost_v6 import refine_roster, summarize_refined


class RefinedCostTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'structural.jsonl'
        rows = [{'original_ordinal': i, 'key': [str(i+1), 0, i], 'key_sha256': str(i),
                 'history_sha256': 'synthetic', 'eligible_neighbors': n, 'vote_memberships_upper': v,
                 'causal_candidates': 10, 'variable_scalar_slots': 1}
                for i, (n, v) in enumerate(zip((0, 1, 8, 60, 200, 700), (0, 5, 40, 400, 1000, 3000)))]
        self.path.write_bytes(b''.join(encoded(row) for row in rows))
        self.frozen = {'population': {'selection_policy': POLICY, 'complete': True, 'total_queries': 6,
                                    'roster_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
                                    'p90_nearest_rank': dict(zip(DIMENSIONS, (500, 9999, 9999, 9999))),
                                    'cells': {'0000': {'population_queries': 5}, '1000': {'population_queries': 1}}},
                       'probes': [dict(rows[4], cell='0000'), dict(rows[5], cell='1000')]}
        self.measured = {'committed_prefix_rows': 0, 'verified_subset_queries': 2,
                         'queries': [{'subset_ordinal': i, 'original_ordinal': p['original_ordinal'],
                                      'key_sha256': p['key_sha256'], 'verification_seconds': float(i+1),
                                      'append_without_commit_seconds': .5, 'rank_seconds': .5}
                                     for i, p in enumerate(self.frozen['probes'])]}
        self.budget = {'rows': [{'subset_ordinal': i, 'append_without_commit_or_budget_seconds': .25} for i in range(2)]}

    def test_refinements_keep_all_population_and_exact_same_samples(self):
        value = refine_roster(self.path, self.frozen)
        self.assertFalse(value['targets_or_predictions_used'])
        self.assertEqual(value['new_sample_keys'], 0)
        for cells in value['cells'].values():
            self.assertEqual(sum(c['population_queries'] for c in cells.values()), 6)
            self.assertEqual(sorted(i for c in cells.values() for i in c['sample_subset_ordinals']), [0, 1])

    def test_uncovered_population_is_never_silently_removed(self):
        refined = refine_roster(self.path, self.frozen)
        value = summarize_refined(refined, self.frozen, self.measured, self.budget)
        parent = value['policies']['parent']; child = value['policies']['neighbor_vote_grid']
        self.assertEqual(parent['uncovered_population'], 0)
        self.assertEqual(child['sample_covered_population'], 2)
        self.assertEqual(child['uncovered_population'], 4)
        scenario = child['scenarios']['verify_append_without_direct_budget']
        self.assertEqual(scenario['sample_covered_seconds'], 3.5)
        self.assertEqual(scenario['parent_fallback_seconds'], 5.)
        self.assertEqual(scenario['total_with_explicit_parent_fallback_seconds'], 8.5)

    def test_changed_bytes_or_incomplete_roster_fail(self):
        self.path.write_bytes(self.path.read_bytes()+b' ')
        with self.assertRaises((ValueError, KeyError)):
            refine_roster(self.path, self.frozen)

    def test_missing_frozen_identity_fails(self):
        self.frozen['probes'][0]['history_sha256'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'identity'):
            refine_roster(self.path, self.frozen)

    def test_wrong_parent_counts_fail(self):
        self.frozen['population']['cells']['0000']['population_queries'] = 4
        with self.assertRaisesRegex(ValueError, 'population'):
            refine_roster(self.path, self.frozen)

    def test_wrong_measured_identity_and_missing_sample_fail(self):
        refined = refine_roster(self.path, self.frozen)
        self.measured['queries'][0]['original_ordinal'] = 1
        with self.assertRaisesRegex(ValueError, 'selection'):
            summarize_refined(refined, self.frozen, self.measured, self.budget)
        self.measured['queries'][0]['original_ordinal'] = 4
        corrupt = deepcopy(refined)
        corrupt['cells']['neighbor_bands']['0000/n3']['sample_subset_ordinals'] = []
        with self.assertRaisesRegex(ValueError, 'coverage'):
            summarize_refined(corrupt, self.frozen, self.measured, self.budget)


if __name__ == '__main__':
    unittest.main()
