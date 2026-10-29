"""Hand results, leakage boundaries, paired denominator and independent oracle."""
from copy import deepcopy
import csv
from dataclasses import replace
from fractions import Fraction
import json
import math
import random
from pathlib import Path
import unittest
import uuid

from scripts import retailrocket_cooccurrence as c
from scripts import retailrocket_cooccurrence_io as io
from scripts import retailrocket_cooccurrence_oracle as oracle
from scripts import retailrocket_popularity as p
from scripts import retailrocket_popularity_io as old

ROOT=Path(__file__).resolve().parents[1]
POLICY=json.loads((ROOT/'docs/contracts/retailrocket_cooccurrence_paired_v1.json').read_text())
PARENT=json.loads((ROOT/'docs/contracts/retailrocket_recommendation_v1.json').read_text())
SCHEMAS=json.loads((ROOT/'reports/stage8/retailrocket_build_v1_specification.json').read_text())['schemas']
START,END=map(old.ms,PARENT['time_roles']['train'])


def fixture(base=None):
    root=(base or ROOT/'shop-mysql-runtime/verification/retailrocket-cooccurrence-implementation-v1/synthetic')/uuid.uuid4().hex
    source=root/'source';baseline=root/'P0';output=root/'C1'
    for folder in (source,baseline,output):folder.mkdir(parents=True)
    rows=[c.Basket('0',START-10,START-10,'warmup',1,('90',)),c.Basket('0',START-10,START+1,'train',2,('14',)),
          c.Basket('1',START+1,START+1,'train',1,('1','2')),c.Basket('1',START+1,START+2,'train',2,('1','3')),
          c.Basket('2',START+1,START+1,'train',1,('1','2')),
          c.Basket('4',END-20,END-20,'train',1,('5',)),c.Basket('4',END-20,END+10,'validation',2,('6',)),
          c.Basket('4',END-20,END+20,'validation',3,('7',))]
    rows.extend(c.Basket('3'+str(i),START+1,START+1,'train',1,(str(i),)) for i in range(4,15))
    rows.extend([c.Basket('1',END+100,END+100,'validation',1,('1',)),c.Basket('1',END+100,END+110,'validation',2,('2','999')),
                 c.Basket('1',END+100,END+120,'validation',3,('3',)),c.Basket('2',END+100,END+100,'validation',1,('99',)),
                 c.Basket('7',END+100,END+100,'validation',1,('1','2')),c.Basket('7',END+100,END+110,'validation',2,('3','4')),
                 c.Basket('8',START-20,START-20,'warmup',1,('99',))])
    rows.sort(key=lambda b:b.key())
    def write(folder,name,header,values):
        with (folder/name).open('w',encoding='utf-8',newline='') as stream:
            writer=csv.writer(stream,lineterminator='\n');writer.writerow(header);writer.writerows(values)
    train=[b for b in rows if b.role=='train'];events=[]
    for b in train:
        for i in b.items:events.append([len(events)+2,'a'*64,b.time,b.visitor,'view',i,'','b'*64,'train'])
    write(source,'qualified_events.csv',SCHEMAS['qualified_events.csv'],events)
    catalog={}
    for b in rows:
        for i in b.items:catalog[i]=min(b.time,catalog.get(i,b.time))
    write(source,'catalog.csv',SCHEMAS['catalog.csv'],sorted(catalog.items(),key=lambda x:int(x[0])))
    basket_rows=[[b.visitor,b.session,b.time,b.role,b.index,io.dump(list(b.items)),'[2]',len(b.items)] for b in rows]
    basket_rows.append(['99',END+999999999,END+999999999,'reserved_test','invalid','MUST_NOT_PARSE','invalid','invalid'])
    write(source,'baskets.csv',SCHEMAS['baskets.csv'],basket_rows)
    definitions=[('1',END+100,END+100,1,('2','999'),True,3),('1',END+100,END+110,2,('3',),True,3),
                 ('2',END+100,END+100,1,('4',),True,2),('4',END-20,END+10,2,('7',),True,1),
                 ('7',END+100,END+100,1,('3','4'),False,0)]
    query_rows=[]
    for v,s,t,index,targets,seen,views in definitions:
        reachable=sum(i in catalog and catalog[i]<t for i in targets)
        query_rows.append([v,s,t,'validation',index,1,t+10,'validation',1,1,0,'labelled',sum(x<t for x in catalog.values()),
                           io.dump(list(targets)),len(targets),reachable,int(reachable==len(targets)),int(seen),0,views,p.activity(views)])
    query_rows.append(['99','invalid','invalid','reserved_test','invalid','invalid','invalid','reserved_test',0,0,0,'not_read',0,'MUST_NOT_PARSE',0,0,0,0,0,0,'0'])
    write(source,'queries.csv',SCHEMAS['queries.csv'],query_rows)
    pp=json.loads((ROOT/'docs/contracts/retailrocket_popularity_execution_v1.json').read_text())
    pp['fixed_denominators_from_accepted_build']['validation']={'queries':5,'visitors':4,'target_occurrences':7,'reachable_target_occurrences':6,
         'all_targets_reachable_queries':4,'new_visitor_queries':1,'multi_item_current_basket_queries':2,'multi_item_target_basket_queries':2,'support_floor_queries':50}
    original=old.build_development(baseline,source,SCHEMAS,pp,PARENT)
    policy=deepcopy(POLICY);policy['P0_identity']['fit_id']=original['fit_audit']['fit_id'];v=original['aggregate']
    fixed={k:v[k] for k in ('queries','visitors','target_occurrences','reachable_target_occurrences','all_targets_reachable_queries','candidate_union_items','support_floor_queries')}
    fixed.update(new_visitor_queries=1,multi_item_current_queries=2,multi_item_target_queries=2,
                 target_model_query_counts={g:x['queries'] for g,x in v['slices']['target_model'].items()})
    policy['fixed_validation']=fixed
    return root,source,baseline,output,policy,original,rows


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.baskets=[c.Basket('1',10,10,'train',1,('1','2')),c.Basket('1',10,11,'train',2,('1','3')),
                      c.Basket('2',10,10,'train',1,('1','2')),c.Basket('3',10,10,'train',1,('4',))]
        self.counts={'1':3,'2':2,'3':1,'4':1}
        self.model=c.fit(self.baskets,10,20,self.counts)
        self.cat=p.Catalog([(str(i),1) for i in range(1,16)])
    def test_binary_counts_and_singleton(self):
        self.assertEqual(dict(self.model.support),{'1':2,'2':2,'3':1,'4':1})
        self.assertEqual(dict(self.model.pairs),{('1','2'):2,('1','3'):1,('2','3'):1})
        self.assertEqual(self.model.audit['singleton_sessions'],1)
    def test_unordered_no_self_pair(self):
        self.assertTrue(all(int(a)<int(b) for a,b in self.model.pairs))
    def test_future_cannot_change_fit(self):
        extra=c.Basket('1',10,20,'validation',3,('999',))
        self.assertEqual(c.fit(self.baskets+[extra],10,20,self.counts).fit_id,self.model.fit_id)
    def test_warmup_excluded_before_set(self):
        extra=c.Basket('1',10,9,'warmup',1,('999',))
        self.assertEqual(c.fit([extra]+self.baskets,10,20,self.counts).fit_id,self.model.fit_id)
    def test_train_clock_rejected(self):
        with self.assertRaises(ValueError):c.fit([replace(self.baskets[0],time=20)],10,20,self.counts)
    def test_missing_singleton_key_rejected(self):
        with self.assertRaises(ValueError):c.fit(self.baskets,10,20,{'1':3,'2':2,'3':1})
    def test_exact_score_partial_fallback_seen_retained(self):
        pred=c.Ranker(self.model,self.counts,self.cat).rank(30,('1',))
        self.assertEqual(pred['ids'][:4],['2','3','1','4'])
        self.assertEqual(pred['scores'][:2],[[1,1],[1,2]])
        self.assertEqual(len(pred['ids']),10)
    def test_full_fallback_unknown_and_singleton(self):
        ranker=c.Ranker(self.model,self.counts,self.cat)
        for history in (('99',),('4',)):
            self.assertEqual(ranker.rank(30,history)['ids'],['1','2','3','4','5','6','7','8','9','10'])
    def test_self_edge_excluded_other_seed_can_score_seen(self):
        self.assertEqual(c.Ranker(self.model,self.counts,self.cat).rank(30,('1','2'))['ids'][:3],['1','2','3'])
    def test_empty_catalog(self):
        self.assertEqual(c.Ranker(self.model,self.counts,self.cat).rank(0,('1',))['ids'],[])
    def test_future_candidate_at_equal_clock_excluded(self):
        self.assertEqual(c.Ranker(self.model,self.counts,self.cat).rank(1,('1',))['candidate_count'],0)
    def test_rational_order_does_not_collapse_to_float_tie(self):
        n=2**54
        support={'1':2*n,'2':n+1,'3':n+1}
        model=c.Model(support,{('1','2'):n,('1','3'):n+1},'synthetic',{})
        self.assertEqual(float(Fraction(n,2*n)),float(Fraction(n+1,2*n)))
        self.assertEqual(c.Ranker(model,support,self.cat).rank(30,('1',))['ids'][0],'3')
    def test_rational_tie_uses_P0_then_numeric_ID(self):
        model=c.Model({'1':2,'2':1,'3':1},{('1','2'):1,('1','3'):1},'synthetic',{})
        self.assertEqual(c.Ranker(model,{'1':3,'2':2,'3':3},self.cat).rank(30,('1',))['ids'][:2],['3','2'])
        self.assertEqual(c.Ranker(model,{'1':3,'2':2,'3':2},self.cat).rank(30,('1',))['ids'][:2],['2','3'])
    def test_history_prefix_no_lifetime(self):
        rows=[c.Basket('1',1,1,'train',1,('1',)),c.Basket('1',1,2,'validation',2,('2',)),c.Basket('1',1,3,'validation',3,('3',))]
        h=c.Histories(rows);q=p.Query('1',1,2,'validation',('3',),1,True,1,1,1,True)
        self.assertEqual(h.at(q,2),('1','2'))
    def test_history_missing_index_stops(self):
        q=p.Query('1',1,2,'validation',('3',),1,True,1,1,1,True)
        with self.assertRaises(ValueError):c.Histories([c.Basket('1',1,2,'validation',2,('2',))]).at(q,2)
    def test_old_session_not_lifetime_history(self):
        rows=[c.Basket('1',1,1,'train',1,('99',)),c.Basket('1',4,4,'validation',1,('2',))]
        q=p.Query('1',4,4,'validation',('3',),1,True,1,1,1,True)
        self.assertEqual(c.Histories(rows).at(q,1),('2',))
    def test_randomized_full_catalog_differential(self):
        rng=random.Random(42)
        for trial in range(40):
            rows=[];sets=[];counts={}
            for visitor in range(12):
                items=tuple(sorted(rng.sample([str(i) for i in range(1,16)],rng.randint(1,6)),key=int))
                rows.append(c.Basket(str(visitor),10,10,'train',1,items));sets.append(set(items))
                for i in items:counts[i]=counts.get(i,0)+1
            rows.sort(key=lambda b:b.key());model=c.fit(rows,10,20,counts)
            cat=p.Catalog([(str(i),rng.choice((1,20,30))) for i in range(1,20)])
            ranker=c.Ranker(model,counts,cat)
            for _ in range(8):
                history=tuple(rng.sample([str(i) for i in range(1,21)],rng.randint(1,4)));t=rng.choice((20,30,40))
                def score(j):
                    value=Fraction()
                    for i in history:
                        denominator=sum(i in s for s in sets)
                        if i!=j and denominator:value+=Fraction(sum(i in s and j in s for s in sets),denominator)
                    return value
                eligible=[i for i in cat.first if cat.first[i]<t]
                expected=sorted(eligible,key=lambda j:(-score(j),-counts.get(j,0),int(j)))[:10]
                actual=ranker.rank(t,history)
                self.assertEqual(actual['ids'],expected)
                self.assertEqual(actual['scores'],[[score(i).numerator,score(i).denominator] for i in expected])
    def test_bootstrap_hand_weighted_ratio_and_quantile(self):
        values=[];records=[('1',1.0),('1',1.0),('2',-1.0)]
        result=c.bootstrap(records,values.append)
        self.assertEqual(result['mean_delta'],1/3)
        self.assertEqual(result['interval'],[-1.0,1.0])
        self.assertEqual(len(values),2000)
        self.assertEqual({v['query_denominator'] for v in values},{2,3,4})
        self.assertTrue(all(v['delta'] in (-1.0,1/3,1.0) for v in values))
        root=ROOT/'shop-mysql-runtime/verification/retailrocket-cooccurrence-implementation-v1/synthetic'/uuid.uuid4().hex
        root.mkdir(parents=True);path=root/'bootstrap.jsonl';path.write_text(''.join(io.dump(v)+'\n' for v in values),encoding='utf-8')
        oracle.close(oracle.check_bootstrap(path,records),result)
    def test_empty_bootstrap(self):self.assertIsNone(c.bootstrap([])['interval'])
    def test_nonfinite_bootstrap_rejected(self):
        with self.assertRaises(ValueError):c.bootstrap([('1',float('nan'))])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root,self.source,self.baseline,self.output,self.policy,self.original,self.rows=fixture()
    def build(self):return io.build(self.output,self.source,self.baseline,SCHEMAS,self.policy,PARENT,self.original['aggregate'])
    def test_complete_independent_full_catalog_oracle(self):
        primary=self.build();accepted=oracle.verify(self.output,self.source,self.baseline,SCHEMAS,self.policy,PARENT,brute=True)
        oracle.close(primary['aggregate'],accepted['aggregate'])
        queries=list(oracle.jsonlines(self.output/'queries.jsonl'))
        self.assertEqual(queries[0]['predictions']['C1']['ids'][:3],['2','3','1'])
        self.assertEqual(queries[0]['terms']['C1']['recall'],.5)
        self.assertAlmostEqual(queries[0]['terms']['C1']['ndcg'],1/(1+1/math.log2(3)))
        self.assertEqual(queries[2]['predictions']['C1']['ids'],queries[2]['predictions']['P0']['ids'])
        self.assertEqual(queries[3]['history'],['5','6'])
    def test_independent_sparse_complete_catalog_proof(self):
        self.build();oracle.verify(self.output,self.source,self.baseline,SCHEMAS,self.policy,PARENT,brute=False)
    def test_missing_P0_query_stops(self):
        path=self.baseline/'ranked_queries.csv';lines=path.read_text().splitlines();path.write_text('\n'.join(lines[:-1])+'\n')
        with self.assertRaises(ValueError):self.build()
    def test_duplicate_P0_key_stops(self):
        path=self.baseline/'ranked_queries.csv';lines=path.read_text().splitlines();lines[2]=lines[1];path.write_text('\n'.join(lines)+'\n')
        with self.assertRaises(ValueError):self.build()
    def test_primary_denominator_drift_stops(self):
        self.policy['fixed_validation']['queries']=4
        with self.assertRaises(ValueError):self.build()
    def test_bad_saved_P0_slice_stops(self):
        path=self.baseline/'query_slices.csv';path.write_text(path.read_text().replace('all_positive','all_zero',1))
        with self.assertRaises(ValueError):self.build()
    def test_oracle_rejects_rational_corruption(self):
        self.build();path=self.output/'queries.jsonl';rows=list(oracle.jsonlines(path));rows[0]['predictions']['C1']['scores'][0]=[2,1]
        path.write_text(''.join(io.dump(r)+'\n' for r in rows))
        with self.assertRaises(ValueError):oracle.verify(self.output,self.source,self.baseline,SCHEMAS,self.policy,PARENT,brute=True)
    def test_oracle_rejects_bootstrap_draw_corruption(self):
        self.build();path=self.output/'bootstrap.jsonl';rows=list(oracle.jsonlines(path));rows[0]['draw_sha256']='0'*64
        path.write_text(''.join(io.dump(r)+'\n' for r in rows))
        with self.assertRaises(ValueError):oracle.verify(self.output,self.source,self.baseline,SCHEMAS,self.policy,PARENT,brute=True)
    def test_exclusive_outputs_refuse_replay(self):
        self.build()
        with self.assertRaises(FileExistsError):self.build()


if __name__=='__main__':unittest.main()
