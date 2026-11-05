"""V11 selection and actual-vote guards for the two distinct n4 cells."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import tempfile
from pathlib import Path
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_gap_v11 as gap
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_joint_cost_v5 import POLICY
from tests.test_retailrocket_session_knn_gap_v10 import digest
from tests import test_retailrocket_session_knn_sql_v4 as sql_fixture


LOW, HIGH = '0001/n4/v3', '1101/n4/v5'


def specification(low_population, high_population, excluded):
    return {'selection': {'quota': 4, 'planned_unique_queries': 8,
                          'prefix_with_terminator': 'k1-gap-v11-20261105\x00'},
            'quotas': [{'cell': cell, 'population': n, 'historical_exclusions': excluded,
                        'eligible': n-excluded, 'planned_new_queries': 4}
                       for cell,n in ((LOW, low_population), (HIGH, high_population))]}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'roster.jsonl'
        shapes = ([(500,600,1000), (521,1200,1000), (537,1999,1000)]*3
                  + [(538,10000,1000), (599,14000,1000), (999,19000,1000)]*3
                  + [(538,1999,1000), (10,230,1000), (110,230,1000),
                     (1200,10010,1000), (600,2339,220665), (499,700,1000),
                     (500,2000,1000), (537,537,220665), (538,9999,1000),
                     (1000,10000,1000), (537,10000,1000)])
        self.rows=[]
        for i,(neighbors,upper,causal) in enumerate(shapes):
            key=[str(171011+i),0,i]
            self.rows.append({'original_ordinal':i, 'key':key, 'key_sha256':digest(key),
                              'eligible_neighbors':neighbors, 'vote_memberships_upper':upper,
                              'causal_candidates':causal, 'variable_scalar_slots':1+6*min(neighbors,500),
                              'history_sha256':digest([str(i)]), 'history_size':1, 'posting_work':neighbors,
                              'current_session_excluded':0})
        self.prior={'probes':[deepcopy(self.rows[i]) for i in (0,9,18)]}
        for probe in self.prior['probes']:
            del probe['original_ordinal']
        self.original={'probes':[dict(deepcopy(self.rows[18]), cell='1001')],
                       'population':{'complete':True, 'selection_policy':POLICY,
                                     'total_queries':len(shapes), 'expected_queries':len(shapes),
                                     'p90_nearest_rank':{'eligible_neighbors':538, 'vote_memberships_upper':2339,
                                                         'causal_candidates':220665, 'variable_scalar_slots':3001}}}
        self.later=[{'probes':[dict(deepcopy(self.rows[i]), cell=cell)]}
                    for i,cell in ((19,'0000/n2/v2'), (20,'0000/n3/v2'), (21,'1101/n5/v5'), (22,'1111/n4/v4'))]
        raw=b''.join(cp.encoded(r) for r in self.rows)
        self.path.write_bytes(raw)
        sha=hashlib.sha256(raw).hexdigest()
        self.original['population'].update(roster_sha256=sha,roster_bytes=len(raw))
        for cohort in self.later:
            cohort['roster_sha256']=sha
        self.spec=specification(9,9,1)

    def choose(self):
        return gap.select_gap_roster(self.path,self.prior,self.original,*self.later,self.spec)

    def audit(self,selection):
        gap.audit_gap_order(self.path,selection,self.prior,self.original,*self.later,self.spec)

    def test_known_hash_order_for_two_masks_in_same_n4_band(self):
        selected=self.choose()
        # Golden values use decimal key strings, ASCII salt + one NUL and decoded SHA bytes.
        self.assertEqual([r['original_ordinal'] for r in selected['probes']],[3,4,7,8,11,13,14,17])
        self.assertEqual([r['cell'] for r in selected['probes']],[LOW]*4+[HIGH]*4)
        self.audit(selected)
        self.spec['quotas'].reverse()
        self.assertEqual(self.choose(),selected)

    def test_independent_full_sort_rejects_changed_rank_or_structural_value(self):
        original=self.choose()
        for change in ('key','work'):
            attempt=deepcopy(original)
            if change=='key':
                attempt['probes'][0]=dict(self.rows[1],cell=LOW)
            else:
                attempt['probes'][0]['vote_memberships_upper']+=1
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.audit(attempt)

    def test_sixth_historical_cohort_must_be_disjoint_and_in_its_original_cell(self):
        last=self.later[-1]
        original=deepcopy(last['probes'])
        for change in ('prior_overlap','changed_cell','changed_ordinal','changed_history','already_represented'):
            last['probes']=deepcopy(original)
            if change=='prior_overlap':
                last['probes']=deepcopy(self.later[-2]['probes'])
            elif change=='changed_cell':
                last['probes'][0]['cell']='1111/n5/v4'
            elif change=='changed_ordinal':
                last['probes'][0]['original_ordinal']-=1
            elif change=='changed_history':
                last['probes'][0]['history_sha256']='0'*64
            else:
                last['probes']=[dict(deepcopy(self.rows[6]),cell=LOW)]
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.choose()

    def test_frozen_salt_eligibility_and_roster_bytes_are_required(self):
        original=deepcopy(self.spec)
        for change in ('salt','quota','population','eligible','duplicate','shortfall','roster'):
            self.spec=deepcopy(original)
            if change=='salt':
                self.spec['selection']['prefix_with_terminator']=self.spec['selection']['prefix_with_terminator'][:-1]
            elif change=='quota':
                self.spec['quotas'][0]['planned_new_queries']=3
            elif change in ('population','eligible'):
                self.spec['quotas'][1][change]+=1
            elif change=='duplicate':
                self.spec['quotas'][0]=self.spec['quotas'][1]
            elif change=='shortfall':
                self.prior['probes'] += [deepcopy(self.rows[i]) for i in range(1,6)]
                self.spec['quotas'][0].update(historical_exclusions=6,eligible=3)
            else:
                self.prior['probes']=self.prior['probes'][:3]
                self.path.write_bytes(self.path.read_bytes().replace(b'\n',b' \n'))
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.choose()


class MembershipAndCostTests(unittest.TestCase):
    def case(self, low_n=500, equal_high=False):
        # A true SQL V4 calculation and independent V1/V2 references, with the final item
        # of each session entering the catalog at query time (strict causal exclusion).
        oracle=sql_fixture.ExactRankingTests()
        sessions={}
        for start,n,seed in ((0,low_n,'1'),(2000,600,'200')):
            for i in range(n):
                if seed=='1':
                    size=2 if low_n>500 and i==0 else 3
                else:
                    size=20 if equal_high or i>=100 else 4
                sessions[(str(start+i),0)]={seed,'9999',*(str(700+x) for x in range(size-2))}
        catalog={item:0 for basket in sessions.values() for item in basket}
        catalog['9999']=100
        oracle.fixture(sessions,catalog=catalog)
        self.addCleanup(oracle.doCleanups)
        rows=[]; probes=[]; predictions=[]
        for i in range(8):
            cell,seed,n,upper=(LOW,'1',low_n,1500) if i<4 else (HIGH,'200',600,10000)
            key=[str(171011+i),0,100]
            prediction,work=oracle.check([seed],current=tuple(key[:2]),at=100)
            probes.append({'cell':cell,'key':key,'key_sha256':digest(key),'original_ordinal':i,
                           'eligible_neighbors':n,'vote_memberships_upper':upper,'posting_work':n,
                           'history_size':1,'causal_candidates':len(catalog)-1,'current_session_excluded':0,
                           'selected_neighbor_slots':500})
            rows.append({'subset_ordinal':i,'original_ordinal':i,'key_sha256':digest(key),'sql_workload':work})
            predictions.append(prediction)
        return probes,{'queries':rows},predictions

    def test_exact_500_and_more_than_500_different_upper_rules(self):
        probes,m,preds=self.case()
        values=gap.sample_workload(probes,m,preds)
        expected={LOW:(2000,6000,6000,4000,2000,0),HIGH:(2400,40000,33600,31600,2000,400)}
        for name,want in expected.items():
            actual=values[name]
            self.assertEqual(actual['boundary_queries'],4)
            self.assertEqual((actual['exact500_queries'],actual['over500_queries']),
                             (4,0) if name==LOW else (0,4))
            self.assertEqual(actual['sql_selected_rows_inserted'],2000)
            self.assertEqual(tuple(actual[k] for k in ('neighbor_pool_rows_hashed','vote_upper_sum',
                        'sql_vote_membership_rows_returned','exact_vote_additions','boundary_ties_total',
                        'boundary_ties_excluded')),want)

    def test_501_legitimately_reads_less_than_upper_and_high_can_equal_upper(self):
        p,m,preds=self.case(low_n=501,equal_high=True)
        values=gap.sample_workload(p,m,preds)
        self.assertEqual((values[LOW]['exact500_queries'],values[LOW]['over500_queries']),(0,4))
        self.assertEqual(values[LOW]['sql_vote_membership_rows_returned'],4*1499)
        self.assertEqual(values[LOW]['vote_upper_sum'],4*1500)
        self.assertEqual(values[LOW]['boundary_ties_excluded'],4)
        self.assertEqual(values[HIGH]['sql_vote_membership_rows_returned'],values[HIGH]['vote_upper_sum'])

    def test_exact_500_refuses_loose_upper_changed_pool_sha_and_spurious_excluded_tie(self):
        p,m,preds=self.case()
        for change in ('upper','digest','tie_exclusion','absent_frontier'):
            probes=deepcopy(p); science=deepcopy(preds)
            if change=='upper':
                probes[0]['vote_memberships_upper']+=1
            elif change=='digest':
                science[0]['neighbor_pool_sha256']='a'*64
            elif change=='tie_exclusion':
                science[0]['boundary_ties_total']+=1
                science[0]['boundary_ties_excluded']+=1
            else:
                science[0]['boundary_similarity']=None
            with self.subTest(change=change),self.assertRaises(ValueError):
                gap.sample_workload(probes,m,science)

    def test_high_cell_frontier_order_size_and_causal_relation_are_checked(self):
        p,m,preds=self.case()
        for change in ('order','size','upper','pool','additions','boundary','cell'):
            probes=deepcopy(p); meas=deepcopy(m); science=deepcopy(preds)
            work=meas['queries'][4]['sql_workload']; pred=science[4]
            if change=='order':
                pred['selected_neighbors'][:2]=reversed(pred['selected_neighbors'][:2])
            elif change=='size':
                work['sql_selected_rows_inserted']=600
            elif change=='upper':
                work['sql_vote_membership_rows_returned']=10001
            elif change=='pool':
                work['neighbor_pool_rows_hashed']=500
            elif change=='additions':
                work['exact_vote_additions']=work['sql_vote_membership_rows_returned']+1
            elif change=='cell':
                probes[4]['cell']=LOW
            else:
                pred['boundary_ties_excluded']+=1
            with self.subTest(change=change),self.assertRaises(ValueError):
                gap.sample_workload(probes,meas,science)

    def test_two_fresh_checkpoints_confirm_scientific_bytes_across_different_chunk_shapes(self):
        probes,m,predictions=self.case()
        expected=gap.sample_workload(probes,m,predictions)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); proofs=[]
            deadline=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            for i,chunk in enumerate((3,4)):
                folder=root/f'repeat_{i}'/'verified_subset'
                binding={'scope':'synthetic V11'}
                store=DetailedTimedStore.create(folder,binding,deadline,120,expected_queries=8,
                          required_stages=('reconstruction','queries'),chunk_queries=chunk)
                with store.writer():
                    store.seal_stage('reconstruction',{'fixture':True})
                    for j,(p,k1) in enumerate(zip(probes,predictions)):
                        store.append_verified(j,p['key'],{'expected':{'key':p['key'],'predictions':{'K1':k1}}})
                    store.flush_chunk()
                    store.seal_stage('queries',{'queries':8,'paired_streams_eof_checked':True})
                reopened=DetailedTimedStore.open(folder,binding)
                actual=[r['payload']['expected']['predictions']['K1'] for r in reopened.iter_records()]
                self.assertEqual(gap.sample_workload(probes,m,actual),expected)
                proofs.append(ledger_proof(reopened,probes))
            gap.compare_frames(root,8)
            self.assertEqual(proofs[0],proofs[1])

    def test_sample_scenario_uses_the_largest_single_row_without_its_direct_budget(self):
        probes,m,_=self.case()
        m.update(verified_subset_queries=8,committed_prefix_rows=0,setup_seconds=.2,
                 chunk_commits=[{'seconds':.3}],tail_flush_and_eof_seal_seconds=.5)
        detail={'rows':[], 'budget':{'rows':[],'by_context':{}}}
        for i,r in enumerate(m['queries']):
            direct=.2 if i%4==0 else .03
            r.update(verification_seconds=.5,checkpoint_append_seconds=.4,rank_seconds=.4,
                     append_without_commit_seconds=.4,chunk_commit_seconds=0.,
                     rank_stages_seconds={'sql_selected_votes_and_accumulation':.1})
            detail['rows'].append({'subset_ordinal':i,'append_exclusive_seconds':{'budget_publication':direct,
                                                                                 'frame_encode':.4-direct}})
            detail['budget']['rows'].append({'subset_ordinal':i,'query_append_budget_seconds':direct,
                                              'append_without_commit_or_budget_seconds':.4-direct})
        spec=specification(20,30,0)
        out=gap.summarize_gap_cost(m,detail,{'probes':probes},spec)
        for cell in out['cells'].values():
            self.assertAlmostEqual(cell['max_verify_append_excluding_direct_budget_seconds'],.87)
            self.assertAlmostEqual(cell['seconds']['direct_budget_seconds'],.29)
            self.assertEqual(cell['measured'],4)
        self.assertEqual(out['all_chunk_commit_seconds'],.3)


class CoverageTests(unittest.TestCase):
    def test_coverage_requires_all_eight_and_only_advances_two_frozen_cells(self):
        remaining={LOW:395,HIGH:290,**{f'other{n}':1 for n in range(10)},'final':523}
        added={k:{'population':remaining[k],'measured':4} for k in (LOW,HIGH)}
        cover,missing=gap.check_coverage(remaining,added)
        self.assertEqual(cover,{'v6_plus_new_cells_with_sample':44,
                               'v6_plus_new_unrepresented_population':533,
                               'distinct_historically_verified_queries':176})
        self.assertEqual(len(missing),11)
        self.assertEqual(sum(missing.values()),533)
        added[HIGH]['measured']=3
        with self.assertRaises(ValueError):
            gap.check_coverage(remaining,added)


if __name__=='__main__':
    unittest.main()
