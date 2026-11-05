"""Synthetic gap selection, seven-stream source binding and new-ledger proofs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_gap_v7 as gap
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS, POLICY
from scripts.retailrocket_session_knn_pair_v4 import verify_selected
from tests.test_retailrocket_session_knn_pair_v4 import fixture
from tests import test_retailrocket_session_knn_sources_v4 as source_fixture


def digest(value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


class GapSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'roster.jsonl'
        shapes = ([(0, 0)]*6 + [(1, 1), (9, 99)]*3 + [(10, 45), (99, 83)]*2
                  + [(18, 100), (40, 499)] + [(100, 500)]*4)
        self.rows = []
        for i, (neighbors, votes) in enumerate(shapes):
            key = [str(1000+i), 0, i]
            self.rows.append({'original_ordinal': i, 'key': key, 'key_sha256': digest(key),
                              'eligible_neighbors': neighbors, 'vote_memberships_upper': votes,
                              'history_sha256': digest([str(2000+i)]), 'history_size': 1,
                              'posting_work': neighbors, 'current_session_excluded': 0,
                              'causal_candidates': 10, 'variable_scalar_slots': 1+6*neighbors})
        self.prior = {'probes': [deepcopy(self.rows[i]) for i in (0, 6, 18)]}
        for row in self.prior['probes']:
            row.pop('original_ordinal')  # The historical V3 roster has no original ordinal.
        self.frozen = {'population': {'complete': True, 'selection_policy': POLICY,
                                      'total_queries': len(self.rows), 'expected_queries': len(self.rows),
                                      'p90_nearest_rank': dict.fromkeys(DIMENSIONS, 99999),
                                      'cells': {'0000': {'population_queries': len(self.rows), 'selected_queries': 4}}},
                       'probes': [dict(deepcopy(row), cell='0000') for row in self.rows[18:]]}
        self.quotas = [{'cell': cell, 'population': n, 'historical_exclusions': taken,
                        'eligible': n-taken, 'planned_new_queries': 2} for cell, n, taken in [
                            ('0000/n0/v0', 6, 1), ('0000/n1/v1', 6, 1),
                            ('0000/n2/v1', 4, 0), ('0000/n2/v2', 2, 0)]]
        self.spec = {
            'quotas': self.quotas,
            'actual_inventory': {'population': 22, 'grid_cells': 5, 'currently_populated_sample_cells': 1,
                                 'currently_unrepresented_population': 18,
                                 'distinct_historical_keys': 6, 'historical_64_and_48_intersection': 1,
                                 'low_neighbor_cells': 4, 'low_neighbor_population': 18,
                                 'low_neighbor_historical_exclusions': 2, 'low_neighbor_eligible': 16},
            'selection': {'quota': 2, 'planned_unique_queries': 8,
                          'prefix_with_terminator': 'k1-gap-v7-20261105\0'}}
        self.write_roster()

    def write_roster(self):
        raw = b''.join(cp.encoded(row) for row in self.rows)
        self.path.write_bytes(raw)
        self.frozen['population'].update(roster_sha256=hashlib.sha256(raw).hexdigest(), roster_bytes=len(raw))

    def select(self, **kwargs):
        return gap.select_gap_roster(self.path, self.prior, self.frozen, self.spec, **kwargs)

    def test_fixed_salt_choices_are_sorted_by_original_ordinal(self):
        # Fixed independently from the specified binary salt and decoded key digest.
        # Rows 0 and 6 are historically excluded; 16/17 are the entire smallest cell.
        expected = [2, 5, 9, 11, 13, 15, 16, 17]
        first = self.select()
        self.assertEqual([row['original_ordinal'] for row in first['probes']], expected)
        self.assertEqual([row['cell'] for row in first['probes']],
                         [quota['cell'] for quota in self.quotas for _ in range(2)])
        self.assertEqual(first['roster_sha256'], self.frozen['population']['roster_sha256'])
        self.prior['probes'].reverse()
        self.assertEqual(first, self.select())

    def test_population_bytes_checked_even_when_shapes_match(self):
        self.path.write_bytes(self.path.read_bytes().replace(b'\n', b' \n'))
        with self.assertRaises(ValueError):
            self.select()

    def test_full_sort_audit_rejects_a_different_eligible_winner(self):
        chosen = self.select()
        gap.audit_gap_order(self.path, chosen, self.prior, self.frozen, self.spec)
        # This row is eligible and belongs to the same cell but loses the salted order.
        chosen['probes'][0] = dict(self.rows[1], cell='0000/n0/v0')
        with self.assertRaises(ValueError):
            gap.audit_gap_order(self.path, chosen, self.prior, self.frozen, self.spec)

    def test_existing_probe_cell_is_no_longer_a_gap(self):
        self.frozen['probes'].append(dict(self.rows[17], cell='0000'))
        self.spec['actual_inventory'].update(distinct_historical_keys=7,
            currently_populated_sample_cells=2, currently_unrepresented_population=16,
            low_neighbor_cells=3, low_neighbor_population=16, low_neighbor_eligible=14)
        # Frozen quotas still ask to measure the now represented cell.
        with self.assertRaises(ValueError):
            self.select()
        self.spec['quotas'] = self.quotas[:-1]
        self.spec['selection']['planned_unique_queries'] = 6
        self.assertEqual([r['original_ordinal'] for r in self.select()['probes']], [2, 5, 9, 11, 13, 15])

    def test_salt_requires_the_exact_terminator(self):
        self.spec['selection']['prefix_with_terminator'] = 'k1-gap-v7-20261105'
        with self.assertRaises(ValueError):
            self.select()

    def test_duplicate_and_malformed_key_identities_are_rejected(self):
        original = deepcopy(self.rows)
        for mutation in ('duplicate_key', 'different_hash', 'wrong_ordinal'):
            with self.subTest(mutation=mutation):
                self.rows = deepcopy(original)
                if mutation == 'duplicate_key':
                    self.rows[3]['key'] = self.rows[2]['key']
                    self.rows[3]['key_sha256'] = self.rows[2]['key_sha256']
                elif mutation == 'different_hash':
                    self.rows[3]['key_sha256'] = '0'*64
                else:
                    self.rows[3]['original_ordinal'] = 8
                self.write_roster()  # Consistent file digest alone is insufficient.
                with self.assertRaises(ValueError):
                    self.select()

    def test_historical_exclusions_require_identity_and_union(self):
        original = deepcopy(self.prior)
        for mutation in ('duplicate_prior', 'missing_prior', 'history_changed'):
            with self.subTest(mutation=mutation):
                self.prior = deepcopy(original)
                prior = self.prior['probes'][0]
                if mutation == 'duplicate_prior':
                    self.prior['probes'].append(deepcopy(prior))
                elif mutation == 'missing_prior':
                    prior['key'] = ['9999', 0, 0]
                    prior['key_sha256'] = digest(prior['key'])
                else:
                    prior['history_sha256'] = 'f'*64
                with self.assertRaises(ValueError):
                    self.select()

    def test_population_and_available_capacity_must_match_each_quota(self):
        for field in ('population', 'historical_exclusions', 'eligible'):
            with self.subTest(field=field):
                self.quotas[0][field] += 1
                with self.assertRaises(ValueError):
                    self.select()
                self.quotas[0][field] -= 1

    def test_duplicate_quota_or_omitted_cell_fails(self):
        original = deepcopy(self.quotas)
        for modified in (original[:-1], original[:-1]+[original[0]]):
            with self.subTest(cells=[q['cell'] for q in modified]):
                self.spec['quotas'] = modified
                with self.assertRaises(ValueError):
                    self.select()

    def test_shortfall_never_moves_to_another_cell(self):
        # Previously verified row in the capacity-two cell leaves one available.
        self.prior['probes'].append(deepcopy(self.rows[16]))
        self.spec['actual_inventory'].update(distinct_historical_keys=7,
                                            low_neighbor_historical_exclusions=3, low_neighbor_eligible=15)
        self.quotas[-1].update(historical_exclusions=1, eligible=1)
        with self.assertRaises(ValueError):
            self.select()

    def test_zero_quota_and_over_cap_are_rejected(self):
        # 33 distinct requested cells fit the specification's arithmetic but
        # exceed the verifier cap. The roster must not be opened in this case.
        self.spec['quotas'] = [dict(self.quotas[0], cell=f'synthetic_cell_{i}') for i in range(33)]
        self.spec['selection']['planned_unique_queries'] = 66
        with self.assertRaises(ValueError):
            self.select(watch=lambda: self.fail('Over-cap request reached roster scan'))
        self.spec['selection'].update(planned_unique_queries=0, quota=0)
        with self.assertRaises(ValueError):
            self.select()

    def test_watch_interruption_propagates_before_selection_finishes(self):
        def stop():
            raise TimeoutError('synthetic deadline')
        with self.assertRaises(TimeoutError):
            self.select(watch=stop)


class GapBindingsTests(unittest.TestCase):
    def setUp(self):
        # Existing mixed-newline/role fixture drives a real seven-stream index.
        self.source = source_fixture.SourceTests()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.probes = [{'original_ordinal': i, 'key': self.source.key(i)} for i in (2, 81)]
        self.binding = {}
        for path, _ in self.source.files.values():
            data = path.read_bytes()
            rel = path.relative_to(self.source.root).as_posix()
            self.binding[rel] = {'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        self.index = self.source.build()

    def check(self):
        return gap.check_index(self.index, self.probes, self.source.n, self.binding, self.source.root)

    def test_source_index_checks_the_selected_original_positions(self):
        self.check()
        self.probes[0]['original_ordinal'] += 1
        with self.assertRaises(ValueError):
            self.check()

    def test_source_index_must_match_all_seven_pinned_digests(self):
        last = self.source.files['k1'][0].relative_to(self.source.root).as_posix()
        self.binding[last]['sha256'] = 'f'*64
        with self.assertRaises(ValueError):
            self.check()


class GapProofTests(unittest.TestCase):
    def test_two_fresh_verified_subsets_match_exact_bytes_and_reject_wrong_order(self):
        root, paths, config, primary, _, database, model, ordinals, binding = fixture()
        deadline = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
        proofs = []
        for repeat in range(2):
            store = DetailedTimedStore.create(root/f'gap_{repeat}', binding, deadline, 300,
                                               expected_queries=len(ordinals), source_root=root,
                                               required_stages=('reconstruction', 'queries'), chunk_queries=2)
            with store.writer():
                store.seal_stage('reconstruction', {'fit_audit': model['fit_audit']})
                measured = verify_selected(primary, paths, config, store, model, database, ordinals)
            store.detailed_cost_summary(measured)
            proof = gap.ledger_proof(store, ordinals)
            physical = b''.join(cp.encoded(row) for row in store.iter_records())
            self.assertEqual(proof['records'], len(ordinals))
            self.assertEqual(proof['actual_committed_bytes'], len(physical))
            self.assertEqual(proof['actual_committed_payload_sha256'], hashlib.sha256(physical).hexdigest())
            proofs.append(proof)
        self.assertEqual(proofs[0], proofs[1])
        with self.assertRaises(ValueError):
            gap.ledger_proof(store, list(reversed(ordinals)))


class GapCostTests(unittest.TestCase):
    def setUp(self):
        # Both rows belong to one first-time low-neighbor cell. A direct budget
        # event on row 0 must not be subtracted from row 1's slower verification.
        self.selection = {'probes': []}
        self.measured = {'queries': [], 'verified_subset_queries': 2, 'committed_prefix_rows': 0,
                         'setup_seconds': 0.1, 'tail_flush_and_eof_seal_seconds': 0.2,
                         'chunk_commits': [{'seconds': 0.05}]}
        self.detail = {'rows': [], 'budget': {'rows': [], 'by_context': {'query_append': {'writes': 1, 'seconds': .1}}}}
        self.spec = {'quotas': [{'cell': '0000/n1/v1', 'planned_new_queries': 2, 'population': 901}]}
        for i, verify, direct_budget in ((0, 1.5, 0.1), (1, 2., 0.)):
            key_hash = digest([str(i+1), 100, 101]); orig = i+7
            self.selection['probes'].append({'original_ordinal': orig, 'key_sha256': key_hash,
                'cell': '0000/n1/v1', 'eligible_neighbors': 1, 'posting_work': 1, 'causal_candidates': 4,
                'vote_memberships_upper': 3})
            self.measured['queries'].append({'subset_ordinal': i, 'original_ordinal': orig, 'key_sha256': key_hash,
                'verification_seconds': verify, 'rank_seconds': 1., 'checkpoint_append_seconds': .25,
                'append_without_commit_seconds': .25, 'chunk_commit_seconds': 0.,
                'rank_stages_seconds': {'sql_selected_votes_and_accumulation': .5}, 'sql_workload': {
                    'sql_selected_rows_inserted': 1, 'sql_overlap_membership_matches': 1,
                    'causal_catalog_candidates': 4, 'sql_vote_membership_rows_returned': 2}})
            self.detail['rows'].append({'subset_ordinal': i,
                'append_exclusive_seconds': {'frame_encode': .25-direct_budget, 'budget_publication': direct_budget}})
            self.detail['budget']['rows'].append({'subset_ordinal': i, 'query_append_budget_seconds': direct_budget,
                                                  'append_without_commit_or_budget_seconds': .25-direct_budget})

    def summary(self):
        return gap.summarize_gap_cost(self.measured, self.detail, self.selection, self.spec)

    def test_cell_summary_retains_counts_stage_times_and_separate_final_commit(self):
        result = self.summary()
        cell = result['cells']['0000/n1/v1']
        self.assertEqual((cell['population'], cell['measured']), (901, 2))
        self.assertEqual(cell['max_verify_append_excluding_direct_budget_seconds'], 2.25)
        self.assertEqual(cell['seconds']['verification_seconds'], 3.5)
        self.assertEqual(cell['rank_stages_seconds']['sql_selected_votes_and_accumulation'], 1.)
        self.assertEqual(cell['append_parts_seconds']['budget_publication'], .1)
        self.assertEqual(result['all_chunk_commit_seconds'], .05)

    def test_cell_summary_rejects_wrong_identity_or_vote_work(self):
        self.measured['queries'][0]['original_ordinal'] += 1
        with self.assertRaises(ValueError):
            self.summary()
        self.measured['queries'][0]['original_ordinal'] -= 1
        self.measured['queries'][0]['sql_workload']['sql_vote_membership_rows_returned'] = 4
        with self.assertRaises(ValueError):
            self.summary()


if __name__ == '__main__':
    unittest.main()
