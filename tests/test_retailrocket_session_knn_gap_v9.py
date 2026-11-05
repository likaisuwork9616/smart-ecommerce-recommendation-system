"""V9 synthetic selection and top-500 vote-bound regression tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_gap_v9 as gap
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_joint_cost_v5 import POLICY
from tests import test_retailrocket_session_knn_sql_v4 as sql_fixture


HIGH = '1101/n5/v5'
LOW = '0010/n3/v2'


def digest(value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


class SelectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'roster.jsonl'
        shapes = ([(1000, 10000, 200), (4999, 75000, 100)]*5 +
                  [(100, 100, 220665), (499, 499, 231000)]*5 +
                  [(999, 15000, 100), (5000, 15000, 100), (1000, 9999, 100),
                   (99, 499, 220665), (500, 1000, 100), (110, 230, 50)])
        self.rows = []
        for i,(neighbors,upper,causal) in enumerate(shapes):
            key = [str(5000+i), 0, i]
            self.rows.append({'key':key,'key_sha256':digest(key),'original_ordinal':i,
                              'history_sha256':digest([str(i+1)]),'history_size':1,
                              'eligible_neighbors':neighbors,'posting_work':neighbors,
                              'vote_memberships_upper':upper,'causal_candidates':causal,
                              'variable_scalar_slots':1+6*min(neighbors,500),
                              'current_session_excluded':0})
        self.prior = {'probes':[deepcopy(self.rows[i]) for i in (0,10,20)]}
        for p in self.prior['probes']:
            del p['original_ordinal']
        self.original = {
            'population':{'complete':True,'selection_policy':POLICY,'total_queries':len(shapes),
                          'expected_queries':len(shapes),'p90_nearest_rank':{
                              'eligible_neighbors':538,'vote_memberships_upper':2339,
                              'causal_candidates':220665,'variable_scalar_slots':3001}},
            'probes':[dict(deepcopy(self.rows[20]),cell='1101')]}
        self.previous34 = {'probes':[dict(deepcopy(self.rows[23]),cell='0010/n2/v2')]}
        self.previous8 = {'probes':[dict(deepcopy(self.rows[25]),cell='0000/n3/v2')]}
        self.spec = {'selection':{'quota':4,'planned_unique_queries':8,
                                  'prefix_with_terminator':'k1-gap-v9-20261105\x00'},
                     'quotas':[{'cell':cell,'population':10,'eligible':9,
                                'historical_exclusions':1,'planned_new_queries':4}
                               for cell in (HIGH,LOW)]}
        self.store()

    def store(self):
        raw = b''.join(checkpoint.encoded(r) for r in self.rows)
        self.path.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        self.original['population'].update(roster_bytes=len(raw),roster_sha256=sha)
        self.previous34['roster_sha256'] = self.previous8['roster_sha256'] = sha

    def choose(self):
        return gap.select_gap_roster(self.path,self.prior,self.original,self.previous34,self.previous8,self.spec)

    def audit(self, result):
        gap.audit_gap_order(self.path,result,self.prior,self.original,self.previous34,self.previous8,self.spec)

    def test_known_salted_order_excludes_previous_cohorts_and_wrong_masks(self):
        selected = self.choose()
        self.assertEqual([p['original_ordinal'] for p in selected['probes']], [1,4,5,6,11,12,18,19])
        self.assertEqual([p['cell'] for p in selected['probes']], [HIGH]*4 + [LOW]*4)
        self.audit(selected)
        self.spec['quotas'].reverse()
        self.prior['probes'].reverse()
        self.assertEqual(self.choose(),selected)

    def test_independent_audit_rejects_same_cell_loser_and_structural_tamper(self):
        for corruption in ('winner','workload'):
            selected = self.choose()
            if corruption == 'winner':
                selected['probes'][0] = dict(self.rows[2],cell=HIGH)
            else:
                selected['probes'][0]['posting_work'] += 1
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                self.audit(selected)

    def test_previous_eight_must_be_disjoint_match_roster_and_have_no_target(self):
        original = deepcopy(self.previous8['probes'])
        for corruption in ('overlap','ordinal','cell','history','represented'):
            with self.subTest(corruption=corruption):
                self.previous8['probes'] = deepcopy(original)
                p = self.previous8['probes'][0]
                if corruption == 'overlap':
                    self.previous8['probes'][0] = self.previous34['probes'][0]
                elif corruption == 'represented':
                    self.previous8['probes'][0] = dict(self.rows[1],cell=HIGH)
                elif corruption == 'history':
                    p['history_sha256'] = '0'*64
                elif corruption == 'cell':
                    p['cell'] = '1101/n5/v4'
                else:
                    p['original_ordinal'] += 1
                with self.assertRaises(ValueError):
                    self.choose()

    def test_changed_quota_capacity_and_salt_are_refused(self):
        original = deepcopy(self.spec)
        for corruption in ('duplicate','unknown_cell','salt','quota','capacity','insufficient'):
            with self.subTest(corruption=corruption):
                self.spec = deepcopy(original)
                q = self.spec['quotas'][0]
                if corruption == 'duplicate':
                    self.spec['quotas'][0] = self.spec['quotas'][1]
                elif corruption == 'unknown_cell':
                    q['cell'] = '1101/n6/v5'
                elif corruption == 'salt':
                    self.spec['selection']['prefix_with_terminator'] = 'k1-gap-v9-20261105'
                elif corruption == 'quota':
                    self.spec['selection']['quota'] = 5
                elif corruption == 'capacity':
                    q['eligible'] -= 1
                else:
                    self.prior['probes'].extend(deepcopy(self.rows[i]) for i in range(1,7))
                    q.update(eligible=3,historical_exclusions=7)
                with self.assertRaises(ValueError):
                    self.choose()

    def test_unselected_row_bytes_and_duplicate_ordinals_fail(self):
        self.path.write_bytes(self.path.read_bytes().replace(b'\n', b' \n'))
        with self.assertRaises(ValueError):
            self.choose()
        self.rows[22]['original_ordinal'] += 1
        self.store()
        with self.assertRaises(ValueError):
            self.choose()


class VoteBoundTests(unittest.TestCase):
    def make_case(self, small_count=550):
        oracle = sql_fixture.ExactRankingTests()
        # 1/3 similarities lead the high cell, 1/20 fill its remaining pool.
        # Only the 500 largest session sizes contribute to the structural upper.
        sessions = {(str(i),0):{'1','2','999'} for i in range(small_count)}
        large = {str(x) for x in range(1,20)} | {'999'}
        sessions.update({(str(i),0):large for i in range(small_count,1200)})
        sessions.update({(str(2000+i),0):{'1000','999'} for i in range(120)})
        catalog = {item:0 for row in sessions.values() for item in row}
        catalog['999'] = 100  # Excluded at the query timestamp by the strict causal filter.
        oracle.fixture(sessions,catalog=catalog)
        self.addCleanup(oracle.doCleanups)
        probes=[]; predictions=[]; measured=[]
        for i in range(8):
            cell,seed,n,upper = (HIGH,'1',1200,10000) if i<4 else (LOW,'1000',120,240)
            key=[str(5000+i),0,100]
            prediction,work = oracle.check([seed],current=tuple(key[:2]),at=100)
            probes.append({'key':key,'original_ordinal':i,'key_sha256':digest(key),'cell':cell,
                           'eligible_neighbors':n,'vote_memberships_upper':upper,'posting_work':n,
                           'history_size':1,'causal_candidates':len(catalog)-1,
                           'current_session_excluded':0,'selected_neighbor_slots':min(n,500)})
            predictions.append(prediction)
            measured.append({'subset_ordinal':i,'original_ordinal':i,'key_sha256':digest(key),'sql_workload':work})
        return probes, {'queries':measured}, predictions

    def test_real_votes_use_selected_sizes_and_causal_filter_not_full_pool_upper(self):
        probes,measured,predictions=self.make_case()
        result=gap.sample_workload(probes,measured,predictions)
        high,low=result[HIGH],result[LOW]
        self.assertEqual((high['neighbor_pool_rows_hashed'],high['sql_selected_rows_inserted'],
                          high['sql_vote_membership_rows_returned'],high['exact_vote_additions']),
                         (4800,2000,6000,4000))
        self.assertEqual((high['boundary_ties_total'],high['boundary_ties_excluded']),(2200,200))
        self.assertEqual((low['neighbor_pool_rows_hashed'],low['sql_selected_rows_inserted'],
                          low['sql_vote_membership_rows_returned'],low['exact_vote_additions']),
                         (480,480,960,480))
        self.assertEqual(low['boundary_queries'],0)

    def test_high_cutoff_can_have_zero_excluded_ties(self):
        probes,measured,predictions=self.make_case(small_count=500)
        result=gap.sample_workload(probes,measured,predictions)[HIGH]
        self.assertEqual(result['boundary_queries'],4)
        self.assertEqual(result['boundary_ties_excluded'],0)

    def test_largest_sizes_can_also_be_actually_selected(self):
        probes,measured,predictions=self.make_case(small_count=0)
        result=gap.sample_workload(probes,measured,predictions)[HIGH]
        self.assertEqual(result['sql_vote_membership_rows_returned'],40000)
        self.assertEqual(result['boundary_ties_excluded'],2800)

    def test_preserved_checkpoint_predictions_reproduce_high_and_low_cost_work(self):
        probes,measured,predictions=self.make_case()
        expected=gap.sample_workload(probes,measured,predictions)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            deadline=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            proofs=[]
            for i in range(2):
                store=DetailedTimedStore.create(root/f'repeat_{i}'/'verified_subset',
                    {'scope':'synthetic native V4 payloads'},deadline,120,expected_queries=len(probes),
                    required_stages=('reconstruction','queries'),chunk_queries=3)
                with store.writer():
                    store.seal_stage('reconstruction',{'synthetic':True})
                    for index,(probe,prediction) in enumerate(zip(probes,predictions)):
                        store.append_verified(index,probe['key'],{'expected':{
                            'key':probe['key'],'predictions':{'K1':prediction}}})
                    store.flush_chunk()
                    store.seal_stage('queries',{'queries':8,'paired_streams_eof_checked':True})
                reopened=DetailedTimedStore.open(store.folder,{'scope':'synthetic native V4 payloads'})
                restored=[r['payload']['expected']['predictions']['K1'] for r in reopened.iter_records()]
                self.assertEqual(gap.sample_workload(probes,measured,restored),expected)
                proofs.append(ledger_proof(reopened,probes))
            gap.compare_frames(root,8)
            self.assertEqual(proofs[0],proofs[1])

    def test_summary_uses_capped_work_and_same_query_budget_deduction(self):
        probes,measured,_=self.make_case()
        measured.update(verified_subset_queries=8,committed_prefix_rows=0,chunk_commits=[{'seconds':.25}],
                        setup_seconds=.5,tail_flush_and_eof_seal_seconds=1.)
        detail={'rows':[], 'budget':{'rows':[], 'by_context':{}}}
        for i,q in enumerate(measured['queries']):
            q.update(verification_seconds=1.,rank_seconds=.75,checkpoint_append_seconds=.5,
                     append_without_commit_seconds=.5,chunk_commit_seconds=0.,
                     rank_stages_seconds={'sql_selected_votes_and_accumulation':.125})
            budget=.25 if i%4 else 0.
            detail['rows'].append({'subset_ordinal':i,'append_exclusive_seconds':{'frame_encode':.5-budget,
                                           'budget_publication':budget}})
            detail['budget']['rows'].append({'subset_ordinal':i,'query_append_budget_seconds':budget,
                                             'append_without_commit_or_budget_seconds':.5-budget})
        spec={'selection':{'quota':4,'planned_unique_queries':8,'prefix_with_terminator':'k1-gap-v9-20261105\x00'},
              'quotas':[{'cell':c,'population':80,'eligible':79,'historical_exclusions':1,
                         'planned_new_queries':4} for c in (HIGH,LOW)]}
        result=gap.summarize_gap_cost(measured,detail,{'probes':probes},spec)
        for c in result['cells'].values():
            self.assertEqual(c['measured'],4)
            self.assertEqual(c['seconds']['direct_budget_seconds'],.75)
            self.assertEqual(c['seconds']['verification_seconds'],4.)
            self.assertEqual(c['max_verify_append_excluding_direct_budget_seconds'],1.5)
        self.assertEqual(result['all_chunk_commit_seconds'],.25)
        self.assertEqual(result['tail_flush_and_eof_seal_seconds'],1.)
        measured['queries'][4]['sql_workload']['sql_vote_membership_rows_returned']-=1
        with self.assertRaises(ValueError):
            gap.summarize_gap_cost(measured,detail,{'probes':probes},spec)

    def test_inconsistent_cap_memberships_pool_digest_and_boundary_fail(self):
        probes,measured,predictions=self.make_case()
        for corruption in ('cap','pool','digest','ties','boundary','order','wrong_vote','too_many','truncated_low','causal','identity'):
            with self.subTest(corruption=corruption):
                m, pred=deepcopy(measured),deepcopy(predictions)
                first=pred[0]; work=m['queries'][0]['sql_workload']
                if corruption=='cap':
                    work['sql_selected_rows_inserted']=1200
                elif corruption=='pool':
                    work['neighbor_pool_rows_hashed']=500
                elif corruption=='digest':
                    first['neighbor_pool_sha256']='short'
                elif corruption=='ties':
                    first['boundary_ties_excluded'] += 1
                elif corruption=='boundary':
                    first['boundary_similarity']=[1,20]
                elif corruption=='order':
                    first['selected_neighbors'][:2]=reversed(first['selected_neighbors'][:2])
                elif corruption=='wrong_vote':
                    work['sql_vote_membership_rows_returned']=first['vote_memberships']=1499
                elif corruption=='too_many':
                    work['sql_vote_membership_rows_returned']=first['vote_memberships']=10001
                elif corruption=='truncated_low':
                    m['queries'][4]['sql_workload']['sql_vote_membership_rows_returned']=pred[4]['vote_memberships']=239
                elif corruption=='causal':
                    work['exact_vote_additions']=1501
                else:
                    m['queries'][0]['key_sha256']='0'*64
                with self.assertRaises(ValueError):
                    gap.sample_workload(probes,m,pred)


class ResidualCoverageTests(unittest.TestCase):
    def test_coverage_requires_four_new_verified_queries_in_each_of_exactly_two_cells(self):
        remaining={HIGH:2345,LOW:1081,'1111/n4/v4':572}
        added={cell:{'population':remaining[cell],'measured':4} for cell in (LOW,HIGH)}
        coverage,missing=gap.check_coverage(remaining,added)
        self.assertEqual(coverage,{'v6_plus_new_cells_with_sample':54,'v6_plus_new_unrepresented_population':572,
                                   'distinct_historically_verified_queries':160})
        self.assertEqual(missing,{'1111/n4/v4':572})
        for corruption in ('old_cell','wrong_count','population'):
            changed=deepcopy(added)
            if corruption=='old_cell':
                changed['0000/n3/v2']=changed.pop(LOW)
            elif corruption=='wrong_count':
                changed[HIGH]['measured']=3
            else:
                changed[LOW]['population']+=1
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                gap.check_coverage(remaining,changed)


if __name__=='__main__':
    unittest.main()
