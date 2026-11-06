"""Synthetic V16 census, uncapped/capped SQL, and publication evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_gap_v16 as gap
from scripts import run_retailrocket_session_knn_gap_v16 as entry
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_joint_cost_v5 import POLICY
from tests.test_retailrocket_session_knn_gap_v10 import digest
from tests import test_retailrocket_session_knn_sql_v4 as sql_fixture


LOW = '0001/n3/v3'
MEDIUM = '0001/n3/v4'
CAPPED = '1011/n5/v4'
QUOTAS = {LOW: 4, MEDIUM: 4, CAPPED: 2}


def specification():
    return {
        'selection': {'quota_by_cell': dict(QUOTAS), 'planned_unique_queries': 10,
                      'prefix_with_terminator': 'k1-gap-v16-20261106\x00'},
        'quotas': [{'cell': cell, 'population': quota, 'historical_exclusions': 0,
                    'eligible': quota, 'planned_new_queries': quota}
                   for cell, quota in QUOTAS.items()],
    }


class SelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'roster.jsonl'
        # All ten targets are retained; later rows exercise the outside edges and history.
        shapes = [(100,500,1), (200,600,1), (400,1999,1), (499,1500,1),
                  (100,2000,1), (300,5000,1), (499,9999,1), (400,2001,1),
                  (1000,2000,1000), (4999,9999,1000),
                  (600,1999,1), (10,230,1), (110,230,1), (1200,10010,1),
                  (600,2339,1000), (500,1050,1), (1200,1500,1),
                  (1200,1500,1000), (1200,2000,1), (520,10000,1000),
                  (99,500,1), (500,1000,1), (400,499,1), (400,10000,1),
                  (400,2000,1000), (999,2000,1000), (5000,2000,1000),
                  (1200,1999,1000), (1200,10000,1000)]
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
        self.prior = {'probes': [deepcopy(self.rows[i]) for i in (10,20)]}
        for probe in self.prior['probes']:
            del probe['original_ordinal']
        self.original = {'probes': [dict(self.rows[10], cell='1001')],
                         'population': {'complete': True, 'selection_policy': POLICY,
                                        'p90_nearest_rank': {'eligible_neighbors': 500, 'vote_memberships_upper': 10000,
                                                             'causal_candidates': 1000, 'variable_scalar_slots': 601}}}
        cells = ['0000/n2/v2', '0001/n3/v2', '1101/n5/v5', '1011/n4/v4',
                 '1001/n4/v3', '1001/n5/v3', '1011/n5/v3', '1001/n5/v4', '1111/n4/v5']
        self.recent = [{'probes': [dict(self.rows[i], cell=cell)]} for i, cell in enumerate(cells, start=11)]
        self.seal_roster()
        self.spec = specification()

    def seal_roster(self):
        data = b''.join(cp.encoded(row) for row in self.rows)
        self.path.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        self.original['population'].update(roster_sha256=sha, roster_bytes=len(data),
                                           total_queries=len(self.rows), expected_queries=len(self.rows))
        for group in self.recent:
            group['roster_sha256'] = sha

    def choose(self, **kwargs):
        return gap.select_gap_roster(self.path, self.prior, self.original, *self.recent, self.spec, **kwargs)

    def audit(self, selected, **kwargs):
        return gap.audit_gap_order(self.path, selected, self.prior, self.original, *self.recent, self.spec, **kwargs)

    def test_all_remaining_capacity_is_selected_in_original_order(self):
        selected = self.choose()
        self.assertEqual([p['original_ordinal'] for p in selected['probes']], list(range(10)))
        self.assertEqual([p['cell'] for p in selected['probes']], [LOW]*4 + [MEDIUM]*4 + [CAPPED]*2)
        self.assertEqual({p['key_sha256'] for p in selected['probes']}, {r['key_sha256'] for r in self.rows[:10]})
        self.audit(selected)
        self.spec['quotas'].reverse()
        self.prior['probes'].reverse()
        self.assertEqual(self.choose(), selected)
        self.audit(selected)

    def test_v3_exclusion_is_not_replaced_or_transferred_between_cells(self):
        selected = self.choose()
        extra = deepcopy(self.rows[1])
        extra.update(original_ordinal=len(self.rows), key=['191110',0,99])
        extra['key_sha256'] = digest(extra['key'])
        self.rows.append(extra)
        historical = deepcopy(extra)
        del historical['original_ordinal']
        self.prior['probes'].append(historical)
        self.spec['quotas'][0].update(population=5, historical_exclusions=1)
        self.seal_roster()
        with_exclusion = self.choose()
        self.assertEqual(with_exclusion['probes'], selected['probes'])
        self.audit(with_exclusion)
        # A newly historical target leaves only three eligible rows: no replacement is allowed.
        historical = deepcopy(self.rows[0])
        del historical['original_ordinal']
        self.prior['probes'].append(historical)
        self.spec['quotas'][0].update(historical_exclusions=2, eligible=3)
        with self.assertRaises(ValueError):
            self.choose()

    def test_eleventh_cohort_checked_against_all_history_and_full_roster(self):
        last = self.recent[-1]
        original = deepcopy(last['probes'])
        for change in ('v3_overlap', 'v14_overlap', 'duplicate', 'ordinal', 'cell', 'history', 'missing', 'already_covered'):
            last['probes'] = deepcopy(original)
            probe = last['probes'][0]
            if change == 'v3_overlap':
                last['probes'] = [dict(self.rows[20], cell='0000/n2/v3')]
            elif change == 'v14_overlap':
                last['probes'] = deepcopy(self.recent[-2]['probes'])
            elif change == 'duplicate':
                last['probes'].append(deepcopy(probe))
            elif change == 'ordinal':
                probe['original_ordinal'] += 1
            elif change == 'cell':
                probe['cell'] = '1101/n4/v5'
            elif change == 'history':
                probe['history_sha256'] = 'a'*64
            elif change == 'missing':
                probe['key'] = ['999999',0,1]
                probe['key_sha256'] = digest(probe['key'])
            else:
                last['probes'] = [dict(self.rows[8], cell=CAPPED)]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.choose()

    def test_selection_rejects_changed_salt_schema_capacity_or_redistributed_quota(self):
        for change in ('salt', 'total', 'scalar', 'transfer', 'wrong_cell', 'duplicate_cell',
                       'eligible', 'planned', 'population', 'negative', 'boolean'):
            self.spec = specification()
            rule, rows = self.spec['selection'], self.spec['quotas']
            if change == 'salt':
                rule['prefix_with_terminator'] = 'k1-gap-v16-20261106'
            elif change == 'total':
                rule['planned_unique_queries'] = 12
            elif change == 'scalar':
                rule['quota'] = 4
            elif change == 'transfer':
                rule['quota_by_cell'].update({MEDIUM: 3, CAPPED: 3})
                rows[1]['planned_new_queries'], rows[2]['planned_new_queries'] = 3, 3
            elif change == 'wrong_cell':
                rule['quota_by_cell']['1111/n5/v4'] = rule['quota_by_cell'].pop(CAPPED)
            elif change == 'duplicate_cell':
                rows[2] = deepcopy(rows[1])
            elif change == 'eligible':
                rows[2]['eligible'] = 1
            elif change == 'planned':
                rows[2]['planned_new_queries'] = 4
            elif change == 'population':
                rows[0]['population'] = 5
            elif change == 'negative':
                rows[0]['historical_exclusions'] = -1
            else:
                rows[2]['historical_exclusions'] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.choose()

    def test_selection_full_sort_source_integrity_eof_and_stop(self):
        selected = self.choose()
        def expired():
            raise TimeoutError('shared deadline expired')
        with self.assertRaises(TimeoutError):
            self.choose(watch=expired)
        with self.assertRaises(TimeoutError):
            self.audit(selected, watch=expired)
        for change in ('order', 'outside', 'structural_row', 'missing'):
            forged = deepcopy(selected)
            if change == 'order':
                forged['probes'].reverse()
            elif change == 'outside':
                forged['probes'][0] = dict(self.rows[21], cell=LOW)
            elif change == 'missing':
                forged['probes'].pop()
            else:
                forged['probes'][0]['posting_work'] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.audit(forged)
        original = self.path.read_bytes()
        for data in (original.replace(b'\n',b' \n'), b''.join(original.splitlines(keepends=True)[:-1])):
            self.path.write_bytes(data)
            with self.assertRaises(ValueError):
                self.choose()
            with self.assertRaises(ValueError):
                self.audit(selected)

    def test_structural_identity_ordinal_and_workload_checked_outside_targets(self):
        original = deepcopy(self.rows)
        for change in ('duplicate', 'ordinal', 'identity', 'negative', 'fractional'):
            self.rows = deepcopy(original)
            row = self.rows[-1]
            if change == 'duplicate':
                row['key'], row['key_sha256'] = self.rows[-2]['key'], self.rows[-2]['key_sha256']
            elif change == 'ordinal':
                row['original_ordinal'] -= 1
            elif change == 'identity':
                row['key_sha256'] = 'f'*64
            else:
                row['causal_candidates'] = -1 if change == 'negative' else .5
            self.seal_roster()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.choose()


def sql_case(cleanup, small_count=550, low_count=200, medium_count=400):
    oracle = sql_fixture.ExactRankingTests()
    # Three seed neighborhoods; every neighbor includes one catalog item not yet causal.
    sessions = {(str(i),0): {'1','11','9999'} for i in range(low_count)}
    sessions.update({(str(2000+i),0): {'200','300','301','302','9999'} for i in range(medium_count)})
    small = {'400','401','402','9999'}
    large = small | {'403'}
    sessions.update({(str(4000+i),0): small if i < small_count else large for i in range(1000)})
    catalog = {item: 0 for session in sessions.values() for item in session}
    catalog['9999'] = 100
    oracle.fixture(sessions, catalog=catalog)
    cleanup(oracle.doCleanups)
    large_in_upper = min(500,1000-small_count)
    upper_capped = large_in_upper*5+(500-large_in_upper)*4
    probes, queries, predictions = [], [], []
    for i in range(10):
        if i < 4:
            cell, seed, neighbors, upper = LOW,'1',low_count,3*low_count
        elif i < 8:
            cell, seed, neighbors, upper = MEDIUM,'200',medium_count,5*medium_count
        else:
            cell, seed, neighbors, upper = CAPPED,'400',1000,upper_capped
        key = [str(171011+i), 0, 100]
        k1, work = oracle.check([seed], current=tuple(key[:2]), at=100)
        probes.append({'cell': cell, 'key': key, 'original_ordinal': i, 'key_sha256': digest(key),
                       'eligible_neighbors': neighbors, 'vote_memberships_upper': upper,
                       'posting_work': neighbors, 'history_size': 1, 'causal_candidates': len(catalog)-1,
                       'current_session_excluded': 0, 'selected_neighbor_slots': min(500,neighbors)})
        queries.append({'subset_ordinal': i, 'original_ordinal': i, 'key_sha256': digest(key), 'sql_workload': work})
        predictions.append(k1)
    return probes, {'queries': queries}, predictions


class MembershipAndEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = sql_case(cls.addClassCleanup)

    def test_native_rank_and_sql_work_from_three_distinct_neighborhoods(self):
        by_cell = gap.sample_workload(*self.native)
        fields = ('neighbor_pool_rows_hashed', 'sql_selected_rows_inserted', 'vote_upper_sum',
                  'sql_vote_membership_rows_returned', 'exact_vote_additions', 'boundary_queries',
                  'boundary_ties_total', 'boundary_ties_excluded')
        self.assertEqual(tuple(by_cell[LOW][k] for k in fields), (800,800,2400,2400,1600,0,0,0))
        self.assertEqual(tuple(by_cell[MEDIUM][k] for k in fields), (1600,1600,8000,8000,6400,0,0,0))
        self.assertEqual(tuple(by_cell[CAPPED][k] for k in fields), (2000,1000,4900,4000,3000,2,1100,100))
        for cell, counts in ((LOW,(4,0,0)), (MEDIUM,(4,0,0)), (CAPPED,(0,0,2))):
            self.assertEqual(tuple(by_cell[cell][k] for k in ('under500_queries','exact500_queries','over500_queries')), counts)

    def test_capped_votes_can_equal_upper_and_cutoff_can_have_no_excluded_ties(self):
        even = gap.sample_workload(*sql_case(self.addCleanup, small_count=0))[CAPPED]
        self.assertEqual(even['vote_upper_sum'], 5000)
        self.assertEqual(even['vote_upper_sum'], even['sql_vote_membership_rows_returned'])
        no_exclusions = gap.sample_workload(*sql_case(self.addCleanup, small_count=500))[CAPPED]
        self.assertEqual(no_exclusions['boundary_ties_excluded'], 0)
        self.assertEqual(no_exclusions['boundary_ties_total'], 1000)

    def test_both_n3_cells_at_499_remain_complete_without_500th_frontier(self):
        workload = gap.sample_workload(*sql_case(self.addCleanup, low_count=499, medium_count=499))
        for cell, votes in ((LOW,5988),(MEDIUM,9980)):
            total = workload[cell]
            self.assertEqual(total['neighbor_pool_rows_hashed'], 1996)
            self.assertEqual(total['sql_selected_rows_inserted'], 1996)
            self.assertEqual(total['sql_vote_membership_rows_returned'], votes)
            self.assertEqual(total['vote_upper_sum'], votes)
            self.assertEqual(total['boundary_queries'], 0)
            self.assertEqual(total['boundary_ties_total'], 0)
            self.assertEqual(total['boundary_ties_excluded'], 0)
            self.assertEqual(tuple(total[k] for k in ('under500_queries','exact500_queries','over500_queries')), (4,0,0))

    def test_vote_bands_and_neighbor_bounds_reject_drift(self):
        cases = ((0,'eligible_neighbors',99), (0,'eligible_neighbors',500),
                 (4,'eligible_neighbors',99), (4,'eligible_neighbors',500),
                 (8,'eligible_neighbors',999), (8,'eligible_neighbors',5000),
                 (0,'vote_memberships_upper',499), (0,'vote_memberships_upper',2000),
                 (4,'vote_memberships_upper',1999), (4,'vote_memberships_upper',10000),
                 (8,'vote_memberships_upper',1999), (8,'vote_memberships_upper',10000))
        for index, field, value in cases:
            probes, measured, predictions = deepcopy(self.native)
            probes[index][field] = value
            with self.subTest(index=index, field=field, value=value), self.assertRaises(ValueError):
                gap.sample_workload(probes, measured, predictions)
        probes, measured, predictions = sql_case(self.addCleanup, small_count=0)
        probes[8]['vote_memberships_upper'] = 2499
        with self.assertRaises(ValueError):
            gap.sample_workload(probes, measured, predictions)

    def test_both_uncapped_cells_require_full_pool_votes_digest_and_zero_frontier(self):
        for index in (0,4):
            for change in ('upper','digest','tie','excluded','frontier'):
                probes, measured, predictions = deepcopy(self.native)
                if change == 'upper':
                    probes[index]['vote_memberships_upper'] += 1
                elif change == 'digest':
                    predictions[index]['neighbor_pool_sha256'] = 'a'*64
                elif change == 'tie':
                    predictions[index]['boundary_ties_total'] = 1
                elif change == 'excluded':
                    predictions[index]['boundary_ties_excluded'] = 1
                else:
                    predictions[index]['boundary_similarity'] = [1,5]
                with self.subTest(index=index,change=change), self.assertRaises(ValueError):
                    gap.sample_workload(probes, measured, predictions)

    def test_capped_rank_ties_member_sizes_and_work_identity_fail_closed(self):
        for change in ('tie','frontier','selected_order','member_size','pool','selected_count','causal','ordinal'):
            probes, measured, predictions = deepcopy(self.native)
            row, pred = measured['queries'][8], predictions[8]
            work = row['sql_workload']
            if change == 'tie':
                pred['boundary_ties_excluded'] += 1
            elif change == 'frontier':
                pred['boundary_similarity'] = None
            elif change == 'selected_order':
                pred['selected_neighbors'][:2] = reversed(pred['selected_neighbors'][:2])
            elif change == 'member_size':
                pred['vote_memberships'] = work['sql_vote_membership_rows_returned'] = 2001
            elif change == 'pool':
                work['neighbor_pool_rows_hashed'] -= 1
            elif change == 'selected_count':
                work['sql_selected_rows_inserted'] -= 1
            elif change == 'causal':
                work['exact_vote_additions'] = work['sql_vote_membership_rows_returned'] + 1
            else:
                row['original_ordinal'] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                gap.sample_workload(probes, measured, predictions)

    def test_workload_rejects_shortfall_and_same_total_quota_transfer(self):
        for change in ('shortfall','transfer','extra_prediction'):
            probes, measured, predictions = deepcopy(self.native)
            if change == 'shortfall':
                probes.pop()
                measured['queries'].pop()
                predictions.pop()
            elif change == 'transfer':
                probes[4] = deepcopy(probes[8])
                measured['queries'][4] = deepcopy(measured['queries'][8])
                predictions[4] = deepcopy(predictions[8])
            else:
                predictions.append(deepcopy(predictions[-1]))
            with self.subTest(change=change), self.assertRaises(ValueError):
                gap.sample_workload(probes, measured, predictions)

    def test_two_ten_query_checkpoints_and_tampered_frame(self):
        probes, measured, predictions = self.native
        workload = gap.sample_workload(probes, measured, predictions)
        with tempfile.TemporaryDirectory() as temp:
            root, proofs = Path(temp), []
            deadline = (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            for i, chunk in enumerate((3,4)):
                folder = root/f'repeat_{i}'/'verified_subset'
                binding = {'scope': 'V16 synthetic'}
                store = DetailedTimedStore.create(folder, binding, deadline, 120, expected_queries=10,
                                                  required_stages=('reconstruction','queries'), chunk_queries=chunk)
                with store.writer():
                    store.seal_stage('reconstruction', {'fixture': True})
                    for j, (probe,k1) in enumerate(zip(probes,predictions)):
                        store.append_verified(j, probe['key'], {'expected': {'key': probe['key'], 'predictions': {'K1': k1}}})
                    store.flush_chunk()
                    store.seal_stage('queries', {'queries': 10, 'paired_streams_eof_checked': True})
                saved = DetailedTimedStore.open(folder, binding)
                proofs.append(ledger_proof(saved, probes))
                restored = [row['payload']['expected']['predictions']['K1'] for row in saved.iter_records()]
                self.assertEqual(gap.sample_workload(probes, measured, restored), workload)
            self.assertEqual(proofs[0], proofs[1])
            gap.compare_frames(root,10)
            repeats = [{'proof': proof, 'workload_by_cell': deepcopy(workload)} for proof in proofs]
            entry._compare(root,repeats)
            repeats[1]['workload_by_cell'][CAPPED]['boundary_ties_total'] += 1
            with self.assertRaises(ValueError):
                entry._compare(root,repeats)
            with self.assertRaises(ValueError):
                gap.compare_frames(root,8)
            payload = next((folder/'payloads').glob('*.jsonl'))
            with payload.open('ab') as stream:
                stream.write(b'{}\n')
            with self.assertRaises(ValueError):
                gap.compare_frames(root,10)

    def test_runner_rejects_two_valid_legacy_eight_query_checkpoints(self):
        probes, _, predictions = self.native
        with tempfile.TemporaryDirectory() as temp:
            root, repeats = Path(temp), []
            deadline = (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            for i in range(2):
                folder = root/f'repeat_{i}'/'verified_subset'
                binding = {'scope': 'V16 synthetic obsolete eight-row namespace'}
                store = DetailedTimedStore.create(folder, binding, deadline, 120, expected_queries=8,
                                                  required_stages=('reconstruction','queries'), chunk_queries=4)
                with store.writer():
                    store.seal_stage('reconstruction', {'fixture': True})
                    for j, (probe,k1) in enumerate(zip(probes[:8],predictions[:8])):
                        store.append_verified(j, probe['key'], {'expected': {'key': probe['key'], 'predictions': {'K1': k1}}})
                    store.flush_chunk()
                    store.seal_stage('queries', {'queries': 8, 'paired_streams_eof_checked': True})
                saved = DetailedTimedStore.open(folder, binding)
                repeats.append({'proof': ledger_proof(saved,probes[:8]), 'workload_by_cell': {}})
            # Both old checkpoints are valid and equal; the V16 runner must still reject eight.
            self.assertEqual(repeats[0]['proof'], repeats[1]['proof'])
            gap.compare_frames(root,8)
            with self.assertRaises(ValueError):
                entry._compare(root,repeats)

    def test_report_cost_uses_same_row_and_four_four_two_counts(self):
        probes, measured, _ = deepcopy(self.native)
        measured.update(verified_subset_queries=10, committed_prefix_rows=0, setup_seconds=.2,
                        chunk_commits=[{'seconds': .25}], tail_flush_and_eof_seal_seconds=.5)
        detail = {'rows': [], 'budget': {'rows': [], 'by_context': {}}}
        for i, row in enumerate(measured['queries']):
            first = i in (0,4,8)
            direct = .3 if first else .05
            verify = 1.1 if first else 1.
            commit = .25 if i == 9 else 0.
            row.update(verification_seconds=verify, rank_seconds=.8, checkpoint_append_seconds=.5+commit,
                       append_without_commit_seconds=.5, chunk_commit_seconds=commit,
                       rank_stages_seconds={'sql_selected_votes_and_accumulation': .1})
            detail['rows'].append({'subset_ordinal': i, 'append_exclusive_seconds': {
                'budget_publication': direct, 'frame_encode': .5-direct}})
            detail['budget']['rows'].append({'subset_ordinal': i, 'query_append_budget_seconds': direct,
                                             'append_without_commit_or_budget_seconds': .5-direct})
        report = gap.summarize_gap_cost(measured, detail, {'probes': probes}, specification())
        for name, cell in report['cells'].items():
            self.assertEqual(cell['measured'], QUOTAS[name])
            self.assertAlmostEqual(cell['max_verify_append_excluding_direct_budget_seconds'], 1.45)
            self.assertAlmostEqual(cell['seconds']['direct_budget_seconds'], .35 if name == CAPPED else .45)
        self.assertEqual(report['all_chunk_commit_seconds'], .25)
        for change in ('budget_ordinal','partial','resumed','transfer'):
            changed_m, changed_d, changed_p = deepcopy(measured), deepcopy(detail), deepcopy(probes)
            if change == 'budget_ordinal':
                changed_d['budget']['rows'][4]['subset_ordinal'] = 0
            elif change == 'partial':
                changed_m['verified_subset_queries'] = 9
            elif change == 'resumed':
                changed_m['committed_prefix_rows'] = 1
            else:
                changed_p[4] = deepcopy(changed_p[8])
                changed_m['queries'][4] = deepcopy(changed_m['queries'][8])
                changed_m['queries'][4]['subset_ordinal'] = 4
            with self.subTest(change=change), self.assertRaises(ValueError):
                gap.summarize_gap_cost(changed_m, changed_d, {'probes': changed_p}, specification())


class CoverageTests(unittest.TestCase):
    def test_only_complete_remaining_four_four_two_release_full_coverage(self):
        remaining = dict(QUOTAS)
        added = {cell: {'population': quota, 'measured': quota} for cell, quota in QUOTAS.items()}
        coverage, missing = gap.check_coverage(remaining, added)
        self.assertEqual(coverage, {'v6_plus_new_cells_with_sample':55, 'uncovered_cells':0,
                                    'v6_plus_new_unrepresented_population':0, 'distinct_historically_verified_queries':218})
        self.assertEqual(missing, {})
        for change in ('incomplete','population','wrong_cell','extra_remaining','transfer','new_keys','history','total_cells'):
            changed, left, kwargs = deepcopy(added), dict(remaining), {}
            if change == 'incomplete':
                changed[CAPPED]['measured'] = 1
            elif change == 'population':
                changed[LOW]['population'] += 1
            elif change == 'wrong_cell':
                changed['1111/n5/v4'] = changed.pop(CAPPED)
            elif change == 'extra_remaining':
                left['1111/n5/v4'] = 1
            elif change == 'transfer':
                changed[MEDIUM]['measured'], changed[CAPPED]['measured'] = 3, 3
            elif change == 'new_keys':
                kwargs['new_keys'] = 8
            elif change == 'history':
                kwargs['historic_unique'] = 200
            else:
                kwargs['total_cells'] = 56
            with self.subTest(change=change), self.assertRaises(ValueError):
                gap.check_coverage(left, changed, **kwargs)


class HistoricalBindingTests(unittest.TestCase):
    def test_runner_requires_all_eleven_fixed_cohorts_and_208_distinct_keys(self):
        groups = [list(range(64)), [62,63]+list(range(64,110))]
        start = 110
        for size in (34,8,8,8,8,8,8,8,8):
            groups.append(list(range(start,start+size)))
            start += size
        self.assertEqual(start, 208)
        names = ('history64','history48','history34','history8','history8_v9','history8_v10',
                 'history8_v11','history8_v12','history8_v13','history8_v14','history8_v15')
        meta = {name: name+'.json' for name in names}
        meta['roster'] = 'synthetic_roster.jsonl'
        fixtures = {meta[name]: {'probes':[{'key_sha256':f'{i:064x}'} for i in values]}
                    for name,values in zip(names,groups,strict=True)}
        with patch.object(entry,'preregistration',return_value=(specification(),{})):
            with patch.object(entry,'read',side_effect=lambda path:fixtures[Path(path).name]):
                args = entry._selection_args(meta)
                self.assertEqual(len(args), 13)
                self.assertEqual([len(group['probes']) for group in args[1:-1]], [64,48,34,8,8,8,8,8,8,8,8])
            for change in ('last_overlap','last_duplicate','last_shortfall','initial_intersection'):
                changed = deepcopy(fixtures)
                last = changed[meta[names[-1]]]['probes']
                if change == 'last_overlap':
                    last[0] = deepcopy(changed[meta[names[-2]]]['probes'][0])
                elif change == 'last_duplicate':
                    last[0] = deepcopy(last[1])
                elif change == 'last_shortfall':
                    last.pop()
                else:
                    changed[meta[names[1]]]['probes'][0] = {'key_sha256':f'{1000:064x}'}
                with self.subTest(change=change), patch.object(entry,'read',side_effect=lambda path:changed[Path(path).name]):
                    with self.assertRaises(ValueError):
                        entry._selection_args(meta)


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

    def test_completed_requires_ten_keys_twenty_checks_and_all_phase_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry.write(root/'supervisor_completion.json',self.completion)
            entry.write(root/'tracked_process_identities.json',{'identities': []})
            phases = {'initial_frozen_source_hash','freeze_gap_selection','seven_source_extract',
                      'gap_repeat_0','gap_repeat_1','final_frozen_source_hash'}
            for phase in phases:
                entry.write(root/(phase+'_receipt.json'),{'completed': True})
            done = {'repeats':2,'new_keys':10,'engineering_checks':20}
            entry.write(root/'done.json',done)
            completion, receipts = entry._completed(root)
            self.assertEqual(completion,self.completion)
            self.assertEqual(set(receipts),phases)
            for changed in ({'repeats':2,'new_keys':8,'engineering_checks':16},
                            dict(done,new_keys=8), dict(done,engineering_checks=16),
                            dict(done,repeats=1)):
                (root/'done.json').write_bytes(cp.encoded(changed))
                with self.subTest(done=changed), self.assertRaises(ValueError):
                    entry._completed(root)
            (root/'done.json').write_bytes(cp.encoded(done))
            (root/'gap_repeat_1_receipt.json').write_bytes(cp.encoded({'completed': False}))
            with self.assertRaises(ValueError):
                entry._completed(root)

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
