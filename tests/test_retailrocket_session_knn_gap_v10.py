"""V10 guards for the two capped vote-v4 cells and five historical cohorts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_gap_v10 as gap
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_joint_cost_v5 import POLICY
from tests import test_retailrocket_session_knn_sql_v4 as sql_fixture


N4, N5 = '1111/n4/v4', '1111/n5/v4'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


class SelectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'roster.jsonl'
        shapes = ([(538,2339,220665),(999,9999,232000)]*5 +
                  [(1000,2339,220665),(4999,9999,232000)]*5 +
                  # Outside the p90 mask, n4/n5 bands, or vote v4 band.
                  [(537,8888,220665),(5000,8888,232000),(600,2338,220665),
                   (600,10000,232000),(600,9999,220664),
                   # Distinct comparable historical cohorts in their original fine cells.
                   (10,450,100),(110,230,100),(1200,10000,100)])
        self.rows = []
        for i,(neighbors,upper,causal) in enumerate(shapes):
            key = [str(91000+i),0,i]
            self.rows.append({'key':key,'key_sha256':digest(key),'original_ordinal':i,
                              'history_sha256':digest([str(i+1)]),'history_size':1,
                              'eligible_neighbors':neighbors,'posting_work':neighbors,
                              'current_session_excluded':0,'vote_memberships_upper':upper,
                              'causal_candidates':causal,'variable_scalar_slots':1+6*min(neighbors,500)})
        self.prior = {'probes':[deepcopy(self.rows[i]) for i in (0,10,20)]}
        for p in self.prior['probes']:
            del p['original_ordinal']
        self.original = {'population':{'complete':True,'selection_policy':POLICY,'total_queries':len(shapes),
                            'expected_queries':len(shapes),'p90_nearest_rank':{
                                'eligible_neighbors':538,'vote_memberships_upper':2339,
                                'causal_candidates':220665,'variable_scalar_slots':3001}},
                         'probes':[dict(deepcopy(self.rows[20]),cell='0111')]}
        self.v7 = {'probes':[dict(deepcopy(self.rows[25]),cell='0000/n2/v2')]}
        self.v8 = {'probes':[dict(deepcopy(self.rows[26]),cell='0000/n3/v2')]}
        self.v9 = {'probes':[dict(deepcopy(self.rows[27]),cell='1101/n5/v5')]}
        self.spec = {'selection':{'quota':4,'planned_unique_queries':8,
                                  'prefix_with_terminator':'k1-gap-v10-20261105\x00'},
                     'quotas':[{'cell':cell,'population':10,'eligible':9,'historical_exclusions':1,
                                'planned_new_queries':4} for cell in (N4,N5)]}
        raw = b''.join(checkpoint.encoded(r) for r in self.rows)
        self.path.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        self.original['population'].update(roster_bytes=len(raw),roster_sha256=sha)
        for cohort in (self.v7,self.v8,self.v9):
            cohort['roster_sha256'] = sha

    def args(self):
        return self.path,self.prior,self.original,self.v7,self.v8,self.v9,self.spec

    def choose(self):
        return gap.select_gap_roster(*self.args())

    def audit(self, value):
        path,*rest = self.args()
        gap.audit_gap_order(path,value,*rest)

    def test_salted_known_winners_exact_masks_and_cell_edges(self):
        selected = self.choose()
        self.assertEqual([p['original_ordinal'] for p in selected['probes']],[1,3,5,8,12,14,15,16])
        self.assertEqual([p['cell'] for p in selected['probes']],[N4]*4+[N5]*4)
        self.audit(selected)
        self.spec['quotas'].reverse()
        self.prior['probes'].reverse()
        self.assertEqual(self.choose(),selected)

    def test_independent_audit_rejects_nonwinner_and_changed_structure(self):
        for corruption in ('order','neighbor_count'):
            selection = self.choose()
            if corruption=='order':
                selection['probes'][0]=dict(self.rows[2],cell=N4)
            else:
                selection['probes'][0]['eligible_neighbors'] += 1
            with self.subTest(corruption=corruption),self.assertRaises(ValueError):
                self.audit(selection)

    def test_latest_v9_cohort_is_disjoint_and_matches_its_original_cell(self):
        old = deepcopy(self.v9['probes'])
        for corruption in ('old_overlap','wrong_cell','wrong_ordinal','changed_history','represented'):
            self.v9['probes'] = deepcopy(old)
            q = self.v9['probes'][0]
            if corruption=='old_overlap':
                self.v9['probes'] = deepcopy(self.v8['probes'])
            elif corruption=='wrong_cell':
                q['cell']='1101/n5/v4'
            elif corruption=='wrong_ordinal':
                q['original_ordinal']-=1
            elif corruption=='changed_history':
                q['history_sha256']='f'*64
            else:
                self.v9['probes']=[dict(deepcopy(self.rows[12]),cell=N5)]
            with self.subTest(corruption=corruption),self.assertRaises(ValueError):
                self.choose()

    def test_salt_and_quota_are_fixed_including_terminator(self):
        initial=deepcopy(self.spec)
        for corruption in ('salt','quota','eligibility','duplicate','shortfall'):
            self.spec=deepcopy(initial); q=self.spec['quotas'][0]
            if corruption=='salt':
                self.spec['selection']['prefix_with_terminator']+='x'
            elif corruption=='quota':
                q['planned_new_queries']=3
            elif corruption=='eligibility':
                q['eligible']-=1
            elif corruption=='duplicate':
                self.spec['quotas'][0]=self.spec['quotas'][1]
            else:
                self.prior['probes'] += [deepcopy(self.rows[i]) for i in range(1,7)]
                q.update(eligible=3,historical_exclusions=7)
            with self.subTest(corruption=corruption),self.assertRaises(ValueError):
                self.choose()

    def test_changed_roster_bytes_block_selection(self):
        self.path.write_bytes(self.path.read_bytes().replace(b'\n',b' \n'))
        with self.assertRaises(ValueError):
            self.choose()


class CappedVotingTests(unittest.TestCase):
    def make_case(self, equal_bounds=False):
        oracle=sql_fixture.ExactRankingTests()
        sessions={}
        # N4: 550 size-3, 50 size-20. N5: 300 size-6, 900 size-12.
        # Last member of every session starts exactly at query time.
        for start,n,small_count,small,large,seed in (
                (0,600,550,3,20,'1'),(2000,1200,300,6,12,'200')):
            for i in range(n):
                size=(6 if seed=='1' else 12) if equal_bounds else (small if i<small_count else large)
                sessions[(str(start+i),0)]={seed,'9999',*(str(700+x) for x in range(size-2))}
        catalog={item:0 for values in sessions.values() for item in values}
        catalog['9999']=100
        oracle.fixture(sessions,catalog=catalog)
        self.addCleanup(oracle.doCleanups)
        probes,measured,predictions=[],[],[]
        for i in range(8):
            cell,seed,n,upper=(N4,'1',600,3000 if equal_bounds else 2350) if i<4 else (N5,'200',1200,6000)
            key=[str(91000+i),0,100]
            pred,work=oracle.check([seed],current=tuple(key[:2]),at=100)
            probes.append({'key':key,'original_ordinal':i,'key_sha256':digest(key),'cell':cell,
                           'eligible_neighbors':n,'vote_memberships_upper':upper,'posting_work':n,
                           'history_size':1,'causal_candidates':len(catalog)-1,'current_session_excluded':0,
                           'selected_neighbor_slots':500})
            predictions.append(pred)
            measured.append({'subset_ordinal':i,'original_ordinal':i,'key_sha256':digest(key),'sql_workload':work})
        return probes,{'queries':measured},predictions

    def test_both_cells_cap_at_500_real_membership_rows_and_ties(self):
        p,m,preds=self.make_case()
        work=gap.sample_workload(p,m,preds)
        for cell,expected in [(N4,(2400,9400,6000,4000,2200,200)),(N5,(4800,24000,16800,14800,3600,2800))]:
            with self.subTest(cell=cell):
                w=work[cell]
                self.assertEqual(w['sql_selected_rows_inserted'],2000)
                self.assertEqual(w['boundary_queries'],4)
                self.assertEqual(tuple(w[k] for k in ('neighbor_pool_rows_hashed','vote_upper_sum',
                                       'sql_vote_membership_rows_returned','exact_vote_additions',
                                       'boundary_ties_total','boundary_ties_excluded')),expected)

    def test_both_cells_can_validly_reach_the_vote_upper(self):
        p,m,preds=self.make_case(equal_bounds=True)
        for w in gap.sample_workload(p,m,preds).values():
            self.assertEqual(w['sql_vote_membership_rows_returned'],w['vote_upper_sum'])
            self.assertEqual(w['sql_selected_rows_inserted'],2000)

    def test_bad_work_identity_or_cutoff_is_refused(self):
        p,m,preds=self.make_case()
        for cell,index in ((N4,0),(N5,4)):
            for corruption in ('cap','upper','pool','boundary','ties','tie_order','causality'):
                b=deepcopy(m); science=deepcopy(preds)
                w=b['queries'][index]['sql_workload']; pr=science[index]
                if corruption=='cap':w['sql_selected_rows_inserted']=p[index]['eligible_neighbors']
                elif corruption=='upper':w['sql_vote_membership_rows_returned']=p[index]['vote_memberships_upper']+1
                elif corruption=='pool':w['neighbor_pool_rows_hashed']=500
                elif corruption=='boundary':pr['boundary_similarity']=None
                elif corruption=='ties':pr['boundary_ties_excluded']+=1
                elif corruption=='tie_order':pr['selected_neighbors'][:2]=reversed(pr['selected_neighbors'][:2])
                else:w['exact_vote_additions']=w['sql_vote_membership_rows_returned']+1
                with self.subTest(cell=cell,corruption=corruption),self.assertRaises(ValueError):
                    gap.sample_workload(p,b,science)

    def test_two_real_checkpoint_chains_and_cost_accounting(self):
        probes,m,preds=self.make_case()
        expected=gap.sample_workload(probes,m,preds)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); proofs=[]
            deadline=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            for i in range(2):
                store=DetailedTimedStore.create(root/f'repeat_{i}'/'verified_subset',{'scope':'synthetic V10'},
                      deadline,120,expected_queries=8,required_stages=('reconstruction','queries'),chunk_queries=3)
                with store.writer():
                    store.seal_stage('reconstruction',{'fixture':True})
                    for j,(p,pred) in enumerate(zip(probes,preds)):
                        store.append_verified(j,p['key'],{'expected':{'key':p['key'],'predictions':{'K1':pred}}})
                    store.flush_chunk()
                    store.seal_stage('queries',{'queries':8,'paired_streams_eof_checked':True})
                reopened=DetailedTimedStore.open(store.folder,{'scope':'synthetic V10'})
                science=[r['payload']['expected']['predictions']['K1'] for r in reopened.iter_records()]
                self.assertEqual(gap.sample_workload(probes,m,science),expected)
                proofs.append(ledger_proof(reopened,probes))
            gap.compare_frames(root,8)
            self.assertEqual(proofs[0],proofs[1])

    def test_pair_cost_excludes_only_its_own_direct_budget_and_commit(self):
        probes,m,_=self.make_case()
        m.update(verified_subset_queries=8,committed_prefix_rows=0,setup_seconds=1.,chunk_commits=[{'seconds':.25}],
                 tail_flush_and_eof_seal_seconds=.75)
        detail={'rows':[], 'budget':{'rows':[], 'by_context':{}}}
        for i,row in enumerate(m['queries']):
            row.update(verification_seconds=1.,rank_seconds=.5,checkpoint_append_seconds=.4,
                       append_without_commit_seconds=.4,chunk_commit_seconds=0.,
                       rank_stages_seconds={'sql_selected_votes_and_accumulation':.25})
            direct=.1 if i%4 else 0.
            detail['rows'].append({'subset_ordinal':i,'append_exclusive_seconds':{'frame_encode':.4-direct,
                                         'budget_publication':direct}})
            detail['budget']['rows'].append({'subset_ordinal':i,'query_append_budget_seconds':direct,
                                             'append_without_commit_or_budget_seconds':.4-direct})
        spec={'selection':{'quota':4,'planned_unique_queries':8,'prefix_with_terminator':'k1-gap-v10-20261105\x00'},
              'quotas':[{'cell':c,'population':80,'eligible':79,'historical_exclusions':1,'planned_new_queries':4}
                        for c in (N4,N5)]}
        summary=gap.summarize_gap_cost(m,detail,{'probes':probes},spec)
        for c in summary['cells'].values():
            self.assertEqual(c['measured'],4)
            self.assertAlmostEqual(c['max_verify_append_excluding_direct_budget_seconds'],1.4)
            self.assertAlmostEqual(c['seconds']['direct_budget_seconds'],.3)
        self.assertEqual(summary['all_chunk_commit_seconds'],.25)


class CoverageTests(unittest.TestCase):
    def test_only_registered_populations_advance_coverage(self):
        remaining={N4:572,N5:399,**{f'uncovered{i}':1 for i in range(12)},'last':1206}
        added={c:{'population':remaining[c],'measured':4} for c in (N4,N5)}
        cover,missing=gap.check_coverage(remaining,added)
        self.assertEqual(cover,{'v6_plus_new_cells_with_sample':42,'v6_plus_new_unrepresented_population':1218,
                                'distinct_historically_verified_queries':168})
        self.assertEqual(missing,{k:v for k,v in remaining.items() if k not in added})
        added[N4]['measured']=3
        with self.assertRaises(ValueError):
            gap.check_coverage(remaining,added)


if __name__=='__main__':
    unittest.main()
