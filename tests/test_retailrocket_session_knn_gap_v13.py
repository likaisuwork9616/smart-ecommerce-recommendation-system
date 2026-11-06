"""Synthetic V13 sampling, capped vote bands, checkpoint costs, and stop conditions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_gap_v13 as gap
from scripts import run_retailrocket_session_knn_gap_v13 as entry
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_joint_cost_v5 import POLICY
from tests.test_retailrocket_session_knn_gap_v10 import digest
from tests import test_retailrocket_session_knn_sql_v4 as sql_fixture


N5_LOW = '1011/n5/v3'
N4_HIGH = '0101/n4/v5'


def specification():
    return {
        'selection': {'quota': 4, 'planned_unique_queries': 8,
                      'prefix_with_terminator': 'k1-gap-v13-20261106\x00'},
        'quotas': [{'cell': cell, 'population': 9, 'historical_exclusions': excluded,
                    'eligible': 9-excluded, 'planned_new_queries': 4}
                   for cell, excluded in ((N5_LOW, 1), (N4_HIGH, 0))],
    }


class SelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'roster.jsonl'
        # Candidate rows span the literal bands. The tail misses a neighbor, vote or mask boundary.
        shapes = ([(1000,1000,220665), (1200,1500,220665), (4999,1999,220665)]*3
                  + [(500,10000,1), (520,12000,1), (537,14357,1)]*3
                  + [(538,1999,1), (10,230,1), (110,230,1), (1200,10010,1),
                     (600,2339,220665), (500,1050,1), (1200,1500,1),
                     (999,600,220665), (5000,1500,220665), (1200,2000,220665),
                     (499,10000,1), (520,9999,1), (537,10000,220665)])
        self.rows = []
        for i, (neighbors, upper, causal) in enumerate(shapes):
            key = [str(171011+i), 0, i]
            self.rows.append({
                'original_ordinal': i, 'key': key, 'key_sha256': digest(key),
                'eligible_neighbors': neighbors, 'vote_memberships_upper': upper,
                'causal_candidates': causal, 'variable_scalar_slots': 1+6*min(500, neighbors),
                'history_sha256': digest([str(i)]), 'history_size': 1,
                'posting_work': neighbors, 'current_session_excluded': 0,
            })
        self.prior = {'probes': [deepcopy(self.rows[i]) for i in (0,18)]}
        for probe in self.prior['probes']:
            del probe['original_ordinal']
        self.original = {'probes': [dict(self.rows[18], cell='1001')],
                         'population': {'complete': True, 'selection_policy': POLICY,
                                        'total_queries': len(shapes), 'expected_queries': len(shapes),
                                        'p90_nearest_rank': {'eligible_neighbors': 538, 'vote_memberships_upper': 2339,
                                                             'causal_candidates': 220665, 'variable_scalar_slots': 3001}}}
        cells = ['0000/n2/v2', '0000/n3/v2', '1101/n5/v5', '1111/n4/v4', '0001/n4/v3', '1001/n5/v3']
        self.recent = [{'probes': [dict(self.rows[i], cell=cell)]} for i, cell in enumerate(cells, start=19)]
        data = b''.join(cp.encoded(row) for row in self.rows)
        self.path.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        self.original['population'].update(roster_sha256=sha, roster_bytes=len(data))
        for group in self.recent:
            group['roster_sha256'] = sha
        self.spec = specification()

    def choose(self, **kwargs):
        return gap.select_gap_roster(self.path, self.prior, self.original, *self.recent, self.spec, **kwargs)

    def audit(self, selected, **kwargs):
        return gap.audit_gap_order(self.path, selected, self.prior, self.original, *self.recent, self.spec, **kwargs)

    def test_two_masks_real_golden_hash_order_and_v3_exclusion(self):
        selected = self.choose()
        self.assertEqual([p['original_ordinal'] for p in selected['probes']], [1,2,6,8,11,15,16,17])
        self.assertEqual([p['cell'] for p in selected['probes']], [N5_LOW]*4 + [N4_HIGH]*4)
        self.audit(selected)
        self.spec['quotas'].reverse()
        self.prior['probes'].reverse()
        self.assertEqual(self.choose(), selected)

    def test_eighth_cohort_checked_against_all_preceding_cohorts_and_roster(self):
        last = self.recent[-1]
        original = deepcopy(last['probes'])
        for change in ('v3_overlap', 'v11_overlap', 'duplicate', 'ordinal', 'cell', 'history', 'already_covered'):
            last['probes'] = deepcopy(original)
            probe = last['probes'][0]
            if change == 'v3_overlap':
                last['probes'] = [dict(self.rows[0], cell=N5_LOW)]
            elif change == 'v11_overlap':
                last['probes'] = deepcopy(self.recent[-2]['probes'])
            elif change == 'duplicate':
                last['probes'].append(deepcopy(probe))
            elif change == 'ordinal':
                probe['original_ordinal'] += 1
            elif change == 'cell':
                probe['cell'] = '1101/n4/v5'
            elif change == 'history':
                probe['history_sha256'] = 'a'*64
            else:
                last['probes'] = [dict(self.rows[10], cell=N4_HIGH)]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.choose()

    def test_selection_rejects_reseeding_mismatched_capacity_and_shortfall(self):
        for field, value in [('prefix_with_terminator', 'k1-gap-v13-20261106'), ('planned_unique_queries', 9)]:
            self.spec = specification()
            self.spec['selection'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.choose()
        self.spec = specification()
        self.spec['quotas'][1]['eligible'] -= 1
        with self.assertRaises(ValueError):
            self.choose()
        self.prior['probes'].extend(deepcopy(self.rows[i]) for i in range(1,6))
        self.spec = specification()
        self.spec['quotas'][0].update(eligible=3, historical_exclusions=6)
        with self.assertRaises(ValueError):
            self.choose()

    def test_selection_and_full_sort_reject_changed_bytes_and_respect_stop(self):
        selected = self.choose()
        def expired():
            raise TimeoutError('shared deadline expired')
        with self.assertRaises(TimeoutError):
            self.choose(watch=expired)
        with self.assertRaises(TimeoutError):
            self.audit(selected, watch=expired)
        for change in ('winner', 'structural_row'):
            forged = deepcopy(selected)
            if change == 'winner':
                forged['probes'][0] = dict(self.rows[3], cell=N5_LOW)
            else:
                forged['probes'][0]['posting_work'] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.audit(forged)
        self.path.write_bytes(self.path.read_bytes().replace(b'\n', b' \n'))
        with self.assertRaises(ValueError):
            self.choose()
        with self.assertRaises(ValueError):
            self.audit(selected)


def sql_case(cleanup, small_count=550, n4_count=520, equal_n4=False):
    oracle = sql_fixture.ExactRankingTests()
    # Smaller sessions have higher exact similarity. Each session also has a late item.
    sessions = {(str(i),0): {'1','9999'} if i < small_count else {'1','2','9999'} for i in range(1000)}
    large = {'200','9999'} | {str(i) for i in range(700,723)}
    small = {'200','9999','700','701'}
    sessions.update({(str(2000+i),0): large if equal_n4 or i >= 100 else small for i in range(n4_count)})
    catalog = {item: 0 for session in sessions.values() for item in session}
    catalog['9999'] = 100
    oracle.fixture(sessions, catalog=catalog)
    cleanup(oracle.doCleanups)
    large_in_upper = 500 if equal_n4 else min(500,n4_count-100)
    n4_upper = large_in_upper*25+(500-large_in_upper)*4
    probes, queries, predictions = [], [], []
    for i in range(8):
        cell, seed, neighbors, upper = ((N5_LOW,'1',1000,1000+min(1000-small_count,500)) if i < 4
                                        else (N4_HIGH,'200',n4_count,n4_upper))
        key = [str(171011+i), 0, 100]
        k1, work = oracle.check([seed], current=tuple(key[:2]), at=100)
        probes.append({'cell': cell, 'key': key, 'original_ordinal': i, 'key_sha256': digest(key),
                       'eligible_neighbors': neighbors, 'vote_memberships_upper': upper,
                       'posting_work': neighbors, 'history_size': 1, 'causal_candidates': len(catalog)-1,
                       'current_session_excluded': 0, 'selected_neighbor_slots': 500})
        queries.append({'subset_ordinal': i, 'original_ordinal': i, 'key_sha256': digest(key), 'sql_workload': work})
        predictions.append(k1)
    return probes, {'queries': queries}, predictions


class MembershipAndEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = sql_case(cls.addClassCleanup)

    def test_native_rank_and_sql_work_from_two_distinct_neighborhoods(self):
        by_cell = gap.sample_workload(*self.native)
        fields = ('neighbor_pool_rows_hashed', 'sql_selected_rows_inserted', 'vote_upper_sum',
                  'sql_vote_membership_rows_returned', 'exact_vote_additions', 'boundary_queries',
                  'boundary_ties_total', 'boundary_ties_excluded')
        self.assertEqual(tuple(by_cell[N5_LOW][k] for k in fields), (4000,2000,5800,4000,2000,4,2200,200))
        self.assertEqual(tuple(by_cell[N4_HIGH][k] for k in fields), (2080,2000,43280,41600,39600,4,1680,80))

    def test_capped_votes_can_equal_upper_and_cutoff_can_have_no_excluded_ties(self):
        even = gap.sample_workload(*sql_case(self.addCleanup, small_count=0))[N5_LOW]
        self.assertEqual(even['vote_upper_sum'], even['sql_vote_membership_rows_returned'])
        no_exclusions = gap.sample_workload(*sql_case(self.addCleanup, small_count=500))[N5_LOW]
        self.assertEqual(no_exclusions['boundary_ties_excluded'], 0)

    def test_n4_exact500_requires_equal_bound_complete_pool_and_frontier(self):
        native = sql_case(self.addCleanup, n4_count=500)
        total = gap.sample_workload(*native)[N4_HIGH]
        self.assertEqual(total['sql_vote_membership_rows_returned'], total['vote_upper_sum'])
        self.assertEqual(total['boundary_queries'], 4)
        self.assertEqual(total['boundary_ties_excluded'], 0)
        self.assertEqual((total['exact500_queries'], total['over500_queries']), (4,0))
        for change in ('upper','digest','tie','frontier'):
            probes, measured, predictions = deepcopy(native)
            if change == 'upper':
                probes[4]['vote_memberships_upper'] += 1
            elif change == 'digest':
                predictions[4]['neighbor_pool_sha256'] = 'a'*64
            elif change == 'tie':
                predictions[4]['boundary_ties_total'] += 1
                predictions[4]['boundary_ties_excluded'] += 1
            else:
                predictions[4]['boundary_similarity'] = None
            with self.subTest(change=change), self.assertRaises(ValueError):
                gap.sample_workload(probes, measured, predictions)

    def test_n4_above500_can_equal_upper_and_neighbor_bands_fail_closed(self):
        equal = gap.sample_workload(*sql_case(self.addCleanup, equal_n4=True))[N4_HIGH]
        self.assertEqual(equal['sql_vote_membership_rows_returned'], equal['vote_upper_sum'])
        self.assertGreater(equal['boundary_ties_excluded'], 0)
        for index, neighbors in ((0,999),(0,5000),(4,499),(4,1000)):
            probes, measured, predictions = deepcopy(self.native)
            probes[index]['eligible_neighbors'] = neighbors
            measured['queries'][index]['sql_workload']['neighbor_pool_rows_hashed'] = neighbors
            predictions[index]['eligible_neighbors'] = neighbors
            with self.subTest(index=index, neighbors=neighbors), self.assertRaises(ValueError):
                gap.sample_workload(probes, measured, predictions)

    def test_rank_ties_member_sizes_upper_and_causality_fail_closed(self):
        for change in ('n4_bound','n4_tie','n4_frontier','n5_bound','n5_tie',
                       'selected_order','member_size','causal','ordinal'):
            probes, measured, predictions = deepcopy(self.native)
            index = 4 if change.startswith('n4') else 0
            probe, row, pred = probes[index], measured['queries'][index], predictions[index]
            work = row['sql_workload']
            if change == 'n4_bound':
                probe['vote_memberships_upper'] = 10399
            elif change == 'n4_tie':
                pred['boundary_ties_total'] += 1
            elif change == 'n4_frontier':
                pred['boundary_similarity'] = None
            elif change == 'n5_bound':
                probe['vote_memberships_upper'] = 999
            elif change == 'n5_tie':
                pred['boundary_ties_excluded'] += 1
            elif change == 'selected_order':
                pred['selected_neighbors'][:2] = reversed(pred['selected_neighbors'][:2])
            elif change == 'member_size':
                pred['vote_memberships'] = work['sql_vote_membership_rows_returned'] = 1001
            elif change == 'causal':
                work['exact_vote_additions'] = work['sql_vote_membership_rows_returned'] + 1
            else:
                row['original_ordinal'] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                gap.sample_workload(probes, measured, predictions)

    def test_two_checkpoints_and_tampered_frame(self):
        probes, measured, predictions = self.native
        workload = gap.sample_workload(probes, measured, predictions)
        with tempfile.TemporaryDirectory() as temp:
            root, proofs = Path(temp), []
            deadline = (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            for i, chunk in enumerate((3,4)):
                folder = root/f'repeat_{i}'/'verified_subset'
                binding = {'scope': 'V13 synthetic'}
                store = DetailedTimedStore.create(folder, binding, deadline, 120, expected_queries=8,
                                                  required_stages=('reconstruction','queries'), chunk_queries=chunk)
                with store.writer():
                    store.seal_stage('reconstruction', {'fixture': True})
                    for j, (probe,k1) in enumerate(zip(probes,predictions)):
                        store.append_verified(j, probe['key'], {'expected': {'key': probe['key'], 'predictions': {'K1': k1}}})
                    store.flush_chunk()
                    store.seal_stage('queries', {'queries': 8, 'paired_streams_eof_checked': True})
                saved = DetailedTimedStore.open(folder, binding)
                proofs.append(ledger_proof(saved, probes))
                restored = [row['payload']['expected']['predictions']['K1'] for row in saved.iter_records()]
                self.assertEqual(gap.sample_workload(probes, measured, restored), workload)
            self.assertEqual(proofs[0], proofs[1])
            gap.compare_frames(root,8)
            with self.assertRaises(ValueError):
                gap.compare_frames(root,7)
            payload = next((folder/'payloads').glob('*.jsonl'))
            with payload.open('ab') as stream:
                stream.write(b'{}\n')
            with self.assertRaises(ValueError):
                gap.compare_frames(root,8)

    def test_report_cost_uses_same_row_excluding_commit_and_direct_budget(self):
        probes, measured, _ = deepcopy(self.native)
        measured.update(verified_subset_queries=8, committed_prefix_rows=0, setup_seconds=.2,
                        chunk_commits=[{'seconds': .25}], tail_flush_and_eof_seal_seconds=.5)
        detail = {'rows': [], 'budget': {'rows': [], 'by_context': {}}}
        for i, row in enumerate(measured['queries']):
            direct = .3 if i%4==0 else .05
            verify = 1.1 if i%4==0 else 1.
            commit = .25 if i == 7 else 0.
            row.update(verification_seconds=verify, rank_seconds=.8, checkpoint_append_seconds=.5+commit,
                       append_without_commit_seconds=.5, chunk_commit_seconds=commit,
                       rank_stages_seconds={'sql_selected_votes_and_accumulation': .1})
            detail['rows'].append({'subset_ordinal': i, 'append_exclusive_seconds': {
                'budget_publication': direct, 'frame_encode': .5-direct}})
            detail['budget']['rows'].append({'subset_ordinal': i, 'query_append_budget_seconds': direct,
                                             'append_without_commit_or_budget_seconds': .5-direct})
        report = gap.summarize_gap_cost(measured, detail, {'probes': probes}, specification())
        for cell in report['cells'].values():
            self.assertEqual(cell['measured'], 4)
            self.assertAlmostEqual(cell['max_verify_append_excluding_direct_budget_seconds'], 1.45)
            self.assertAlmostEqual(cell['seconds']['direct_budget_seconds'], .45)
        self.assertEqual(report['all_chunk_commit_seconds'], .25)
        detail['budget']['rows'][4]['subset_ordinal'] = 0
        with self.assertRaises(ValueError):
            gap.summarize_gap_cost(measured, detail, {'probes': probes}, specification())


class CoverageTests(unittest.TestCase):
    def test_only_complete_four_per_cell_release_registered_coverage(self):
        residual = {'0110/n3/v5':25,'1001/n5/v4':23,'1111/n4/v5':23,
                    '0101/n3/v4':7,'0001/n3/v3':4,'0001/n3/v4':4,'1011/n5/v4':2}
        remaining = {N5_LOW:60, N4_HIGH:26, **residual}
        added = {cell: {'population': remaining[cell], 'measured': 4} for cell in (N5_LOW,N4_HIGH)}
        coverage, missing = gap.check_coverage(remaining, added)
        self.assertEqual(coverage, {'v6_plus_new_cells_with_sample':48, 'uncovered_cells':7,
                                    'v6_plus_new_unrepresented_population':88, 'distinct_historically_verified_queries':192})
        self.assertEqual(missing, residual)
        for change in ('incomplete', 'population', 'wrong_cell'):
            changed = deepcopy(added)
            if change == 'incomplete':
                changed[N4_HIGH]['measured'] = 3
            elif change == 'population':
                changed[N5_LOW]['population'] += 1
            else:
                changed['1001/n5/v4'] = changed.pop(N5_LOW)
            with self.subTest(change=change), self.assertRaises(ValueError):
                gap.check_coverage(remaining, changed)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026,11,6,tzinfo=timezone.utc)
        self.request = {
            'created_utc': self.start.isoformat(),
            'deadline_utc': (self.start+timedelta(seconds=1800)).isoformat(),
            'budget_seconds': 1800, 'limits': dict(entry.LIMITS), 'operation': 'joint_tail',
            'full_readback_enabled': False, 'reserved_test': 'locked', 'T_plan': None,
        }
        self.completion = {
            'exit_code': 0, 'stop_reason': None, 'supervisor_error': None,
            'actual_exit_observed_utc': (self.start+timedelta(seconds=100)).isoformat(),
            'tracked_processes_alive_after_cleanup': 0, 'seconds': 100.,
            'operation': 'joint_tail', 'full_readback_started': False, 'reserved_test': 'locked',
            'T_plan': None, 'peak_sampled_tree_and_supervisor_rss_bytes': 1024,
            'peak_sampled_execution_bytes': 2048,
        }

    def test_window_rejects_new_deadline_resource_or_scope_limits(self):
        entry._check_window(self.request)
        for field, value in (
            ('budget_seconds', 1801),
            ('deadline_utc', (self.start+timedelta(seconds=1801)).isoformat()),
            ('limits', dict(entry.LIMITS, rss_bytes=9<<30)),
            ('operation', 'full'),
            ('full_readback_enabled', True),
            ('reserved_test', 'unlocked'),
            ('T_plan', 1.),
        ):
            request = dict(self.request)
            request[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                entry._check_window(request)

    def test_publication_requires_normal_exit_inside_original_window(self):
        entry._check_window(self.request, self.completion)
        for field, value in (
            ('exit_code', 1),
            ('stop_reason', 'deadline'),
            ('supervisor_error', 'interrupted'),
            ('tracked_processes_alive_after_cleanup', 1),
            ('actual_exit_observed_utc', (self.start+timedelta(seconds=1801)).isoformat()),
            ('seconds', 1801.),
            ('peak_sampled_tree_and_supervisor_rss_bytes', (8<<30)+1),
            ('peak_sampled_execution_bytes', (20<<30)+1),
            ('full_readback_started', True),
            ('reserved_test', 'unlocked'),
        ):
            completion = dict(self.completion)
            completion[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                entry._check_window(self.request, completion)


if __name__ == '__main__':
    unittest.main()
