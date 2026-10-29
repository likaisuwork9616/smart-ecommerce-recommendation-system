"""K1 hand arithmetic, boundaries, adversarial inputs and complete synthetic oracle."""
from collections import Counter
from copy import deepcopy
import csv
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import unittest
import uuid

from scripts import retailrocket_session_knn as k
from scripts import retailrocket_session_knn_evaluation as evaluation
from scripts import retailrocket_session_knn_oracle as oracle
from scripts import retailrocket_session_knn_cost as cost
from scripts import retailrocket_popularity as p
from scripts import retailrocket_cooccurrence as c
from scripts import retailrocket_directed as d

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'shop-mysql-runtime/verification/retailrocket-session-knn-implementation-v1'


def folder(base=None):
    target = Path(base or BASE/'synthetic')/uuid.uuid4().hex
    if not target.resolve().is_relative_to(ROOT):
        raise ValueError('Synthetic artifacts must remain inside shop')
    target.mkdir(parents=True)
    return target


def model(rows):
    rows = sorted(rows,key=lambda b:b.key())
    counts = dict(Counter(i for b in rows if b.role=='train' for i in b.items))
    cm = c.fit(rows,10,100,counts)
    lineage = []
    km = k.fit(rows,10,100,cm.support,counts,lineage.append)
    return km,counts,lineage


def fixture_inputs(boundary=False):
    if boundary:
        rows = [c.Basket(str(v),10,10,'train',1,('1',str(v+1000))) for v in range(1,502)]
        rows += [c.Basket('9999',105,110,'validation',1,('1',)),c.Basket('9999',105,120,'validation',2,('1501',))]
        raw_queries = [('9999',105,110,1,('1501',))]
        catalog = [(str(i),1) for i in [1,*range(1001,1502),*range(2,15)]]
    else:
        rows = [c.Basket('1',10,10,'train',1,('1',)),c.Basket('1',10,11,'train',2,('2',)),
                c.Basket('1',10,12,'train',3,('1',)),c.Basket('1',15,15,'train',1,('1','4')),
                c.Basket('2',20,20,'train',1,('1','3')),c.Basket('2',20,21,'train',2,('4',)),
                c.Basket('3',30,30,'train',1,('1',)),c.Basket('4',40,40,'train',1,('2','3')),
                c.Basket('4',40,41,'train',2,('2',)),c.Basket('5',90,90,'train',1,('4',)),
                c.Basket('6',60,60,'train',1,('5',)),
                c.Basket('1',10,110,'validation',4,('1',)),c.Basket('1',10,120,'validation',5,('2',)),
                c.Basket('5',90,110,'validation',2,('4','99')),c.Basket('5',90,120,'validation',3,('4',)),
                c.Basket('6',60,110,'validation',2,('5',)),c.Basket('6',60,120,'validation',3,('5',)),
                c.Basket('90',105,110,'validation',1,('1','99')),c.Basket('90',105,120,'validation',2,('2','20')),
                c.Basket('90',105,130,'validation',3,('3',)),
                c.Basket('91',105,111,'validation',1,('99',)),c.Basket('91',105,125,'validation',2,('100',)),
                c.Basket('92',105,112,'validation',1,('1',)),c.Basket('92',105,126,'validation',2,('99',))]
        raw_queries = [('1',10,110,4,('2',)),('5',90,110,2,('4',)),('6',60,110,2,('5',)),
                       ('90',105,110,1,('2','20')),('90',105,120,2,('3',)),
                       ('91',105,111,1,('100',)),('92',105,112,1,('99',))]
        catalog = [(str(i),1) for i in range(1,16)] + [('20',120),('99',110),('100',115)]
    rows.sort(key=lambda b:b.key()); cat = p.Catalog(catalog)
    counts = dict(Counter(i for b in rows if b.role=='train' for i in b.items))
    cm = c.fit(rows,10,100,counts); dm = d.fit(rows,10,100,cm.support,cm.pairs,counts)
    pm = p.Model(counts,'synthetic_P0',{})
    rankers = {'P0':p.Ranker(pm,cat),'C1':c.Ranker(cm,counts,cat),'D1':d.Ranker(dm,counts,cat)}
    fits = {'P0':pm.fit_id,'C1':cm.fit_id,'D1':dm.fit_id}
    references = []; queries = []; pairs = []
    for v,s,t,index,targets in sorted(raw_queries):
        seen = [b for b in rows if b.visitor==v and b.session==s and b.time<=t]
        history = sorted({i for b in seen for i in b.items},key=int)
        current = next(b for b in seen if b.time==t)
        train_views = sum(len(b.items) for b in rows if b.visitor==v and b.role=='train')
        reachable = sum(cat.contains(i,t) for i in targets)
        q = p.Query(v,s,t,'validation',targets,len(current.items),train_views>0,train_views,cat.size(t),reachable,reachable==len(targets))
        pred = {a:r.rank(t) if a=='P0' else r.rank(t,history) for a,r in rankers.items()}
        pred['P0'] = {key:pred['P0'][key] for key in ('ids','candidate_count')}
        terms = {a:p.metric_terms(r['ids'],targets) for a,r in pred.items()}
        references.append({'key':list(q.key()),'history':history,'history_sha256':hashlib.sha256(k.encoded(history).encode()).hexdigest(),
            'targets':list(targets),'candidate_count':cat.size(t),'reachable_targets':reachable,
            'predictions':pred,'terms':terms,'slices':p.slice_names(q,counts),'control_fit_ids':dict(fits)})
        queries.append((q,index)); pairs.append((v,terms['C1']['ndcg']-terms['P0']['ndcg']))
    draws = []; c.bootstrap(pairs,draws.append)
    expected = {'queries':len(queries),'visitors':len({q.visitorid for q,_ in queries}),
        'target_occurrences':sum(len(q.targets) for q,_ in queries),'reachable_target_occurrences':sum(q.reachable_count for q,_ in queries),
        'all_targets_reachable_queries':sum(q.all_reachable for q,_ in queries),
        'candidate_union_items':cat.size(max(q.query_ms for q,_ in queries)),'support_floor_queries':50}
    return rows,counts,dict(cm.support),catalog,queries,references,draws,fits,expected


def run_case(base=None,boundary=False,mutate=None):
    out = folder(base)
    rows,counts,support,catalog,queries,refs,draws,fits,expected = fixture_inputs(boundary)
    inputs = {'kind':'synthetic_K1_acceptance','train_window':[10,100],'validation_window':[100,1000],
        'baskets':[asdict(b) for b in rows],'counts':counts,'support':support,'catalog':catalog,
        'queries':[[asdict(q),index] for q,index in queries],'references':refs,'control_fit_ids':fits,'expected':expected}
    (out/'inputs.json').write_text(k.encoded(inputs)+'\n',encoding='utf-8')
    lineage = []; km = k.fit(rows,10,100,support,counts,lineage.append)
    (out/'model.json').write_text(k.encoded(k.model_payload(km))+'\n',encoding='utf-8')
    (out/'train_sessions.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in lineage),encoding='utf-8')
    (out/'reference_bootstrap.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in draws),encoding='utf-8')
    if mutate: mutate(refs)
    outputs = []; replicates = []
    result = evaluation.evaluate(k.Ranker(km,counts,p.Catalog(catalog)),rows,queries,refs,draws,fits,(100,1000),expected,outputs.append,replicates.append)
    (out/'queries.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in outputs),encoding='utf-8')
    (out/'bootstrap.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in replicates),encoding='utf-8')
    (out/'aggregate.json').write_text(k.encoded(result)+'\n',encoding='utf-8')
    return out,result


class HandAndIndexTests(unittest.TestCase):
    def setUp(self):
        self.rows = [c.Basket('1',10,10,'train',1,('1','2')),
                     c.Basket('2',20,20,'train',1,('1','3','4')),c.Basket('3',30,30,'train',1,('1',))]
        self.model,self.counts,self.lineage = model(self.rows)
        self.catalog = p.Catalog([(str(i),1) for i in range(1,16)]+[('99',100)])

    def rank(self,history=('1','99'),key=('9',100)):
        return k.Ranker(self.model,self.counts,self.catalog).rank(110,history,key)

    def test_hand_jaccard_and_votes(self):
        pred = self.rank()
        self.assertEqual([n['similarity'] for n in pred['selected_neighbors']],[[1,2],[1,3],[1,4]])
        self.assertEqual(pred['ids'][:4],['1','2','3','4'])
        self.assertEqual(pred['scores'][:4],[[13,12],[1,3],[1,4],[1,4]])
        self.assertEqual(pred['unknown_seeds'],1)

    def test_complete_session_membership_and_postings(self):
        sessions,support,payload,lineage = oracle.reconstruct([asdict(b) for b in self.rows],10,100)
        self.assertEqual(k.model_payload(self.model),payload)
        self.assertEqual(self.lineage,lineage)
        self.assertEqual(len(self.model.postings['1']),3)

    def test_self_session_excluded_same_visitor_other_session_kept(self):
        rows = self.rows+[c.Basket('1',15,15,'train',1,('1','4'))]
        km,counts,_ = model(rows)
        pred = k.Ranker(km,counts,self.catalog).rank(110,('1','99'),('1',10))
        keys = [n['key'] for n in pred['selected_neighbors']]
        self.assertNotIn(['1',10],keys); self.assertIn(['1',15],keys)
        self.assertEqual(pred['current_session_excluded'],1)

    def test_singleton_self_item_vote_and_seen_recommendations(self):
        pred = self.rank(('1',))
        self.assertEqual(pred['ids'][0],'1')
        self.assertEqual(pred['scores'][0],[11,6])

    def test_repeated_items_across_baskets_once(self):
        km,counts,_ = model(self.rows+[c.Basket('1',10,11,'train',2,('1','2'))])
        self.assertEqual(dict(km.support),dict(self.model.support))
        self.assertEqual(km.fit_id,self.model.fit_id)
        self.assertEqual(km.audit['basket_item_memberships'],8)

    def test_crossing_sessions_keep_only_train_part(self):
        poison = c.Basket('1',10,110,'validation',2,None)
        km,_,_ = model(self.rows+[poison])
        self.assertEqual(km.fit_id,self.model.fit_id)
        warm = c.Basket('1',10,9,'warmup',1,None)
        km = k.fit([warm,*self.rows,poison],10,100,self.model.support,self.counts)
        self.assertEqual(km.fit_id,self.model.fit_id)

    def test_unknown_seeds_stay_in_union_denominator(self):
        pred = self.rank(('1','99','100'))
        self.assertEqual([n['similarity'] for n in pred['selected_neighbors']],[[1,3],[1,4],[1,5]])
        self.assertEqual(pred['scores'][0],[47,60])

    def test_cold_history_full_P0_fallback(self):
        pred = self.rank(('99',))
        self.assertEqual(pred['fallback_reason'],'no_supported_seed')
        expected = sorted(self.catalog.numeric,key=lambda i:(-self.counts.get(i,0),int(i)))[:10]
        self.assertEqual(pred['ids'],expected)

    def test_only_self_session_fallback(self):
        km,counts,_ = model([c.Basket('1',10,10,'train',1,('1',))])
        pred = k.Ranker(km,counts,p.Catalog([('1',1),('2',1)])).rank(100,('1',),('1',10))
        self.assertEqual(pred['fallback_reason'],'only_self_session_overlap')
        self.assertEqual(pred['scores'],[[0,1],[0,1]])

    def test_499_500_501_neighbors_and_numeric_boundary_ties(self):
        for n in (499,500,501):
            with self.subTest(n=n):
                rows = [c.Basket(str(v),10,10,'train',1,('1',str(v+1000))) for v in range(1,n+1)]
                km,counts,_ = model(rows); cat = p.Catalog((i,1) for i in counts)
                pred = k.Ranker(km,counts,cat).rank(100,('1',),('9999',100))
                self.assertEqual(pred['eligible_neighbors'],n)
                self.assertEqual([int(r['key'][0]) for r in pred['selected_neighbors']],list(range(1,min(n,500)+1)))
                self.assertEqual(pred['boundary_ties_excluded'],max(0,n-500))
                self.assertEqual(pred,oracle.predict(dict(km.sessions),dict(km.support),km.fit_id,counts,dict(cat.first),100,('1',),('9999',100)))

    def test_neighbor_tie_uses_session_start_after_numeric_visitor(self):
        rows = [c.Basket('2',20,20,'train',1,('1','2')),c.Basket('2',10,10,'train',1,('1','3')),c.Basket('10',10,10,'train',1,('1','4'))]
        km,counts,_ = model(rows)
        pred = k.Ranker(km,counts,self.catalog).rank(110,('1',),('9',100))
        self.assertEqual([r['key'] for r in pred['selected_neighbors']],[['2',10],['2',20],['10',10]])

    def test_full_zero_complement_and_strict_first_view(self):
        cat = p.Catalog([(str(i),1) for i in range(1,6)]+[('6',110),('7',1),('8',111),('99',100)])
        pred = k.Ranker(self.model,self.counts,cat).rank(110,('99',),('9',100))
        self.assertEqual(pred['ids'],['1','2','3','4','5','7','99'])
        self.assertNotIn('6',pred['ids']);self.assertNotIn('8',pred['ids'])
        self.assertEqual(pred['p0_counts'],[3,1,1,1,0,0,0])

    def test_empty_catalog_empty_model(self):
        km = k.fit([],10,100,{},{}); pred = k.Ranker(km,{},p.Catalog([])).rank(100,('99',),('1',100))
        self.assertEqual(pred['ids'],[])
        self.assertEqual(p.metric_terms(pred['ids'],('99',))['ndcg'],0)

    def test_frozen_index_readonly(self):
        with self.assertRaises(TypeError): self.model.sessions['x']=frozenset()
        with self.assertRaises(AttributeError): self.model.sessions['1',10].add('8')

    def test_reject_incomplete_posting(self):
        bad = dict(self.model.postings);bad['1']=bad['1'][:2]
        with self.assertRaises(ValueError): k.Ranker(replace(self.model,postings=bad),self.counts,self.catalog)

    def test_reject_support_mismatch(self):
        support = dict(self.model.support);support['1']=2
        with self.assertRaises(ValueError): k.fit(self.rows,10,100,support,self.counts)

    def test_reject_duplicate_unsorted_or_future_train_basket(self):
        for rows in [self.rows+[self.rows[0]],list(reversed(self.rows)),[replace(self.rows[0],time=100)],
                     [replace(self.rows[0],items=('1','1'))],[replace(self.rows[0],session=True)]]:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError): k.fit(rows,10,100,self.model.support,self.counts)

    def test_reject_missing_history_or_train_ranking(self):
        ranker = k.Ranker(self.model,self.counts,self.catalog)
        for t,h,s in [(99,('1',),('1',10)),(110,(),('1',100)),(110,('1','1'),('1',100)),(110,('1',),('01',100))]:
            with self.assertRaises(ValueError): ranker.rank(t,h,s)

    def test_future_injection_does_not_change_index_or_earlier_history(self):
        rows,counts,support,cat,queries,refs,draws,fits,expected = fixture_inputs()
        outputs = []
        km = k.fit(rows,10,100,support,counts)
        histories = c.Histories(rows)
        q,index = queries[0]
        h = histories.at(q,index)
        changed = [replace(b,items=('123456',)) if b.role=='validation' and b.time>q.query_ms else b for b in rows]
        km2 = k.fit(changed,10,100,support,counts)
        self.assertEqual(km.fit_id,km2.fit_id)
        self.assertEqual(h,c.Histories(changed).at(q,index))

    def test_random_synthetic_full_enumeration(self):
        rng = random.Random(73)
        for case in range(12):
            rows = [c.Basket(str(v),10,10,'train',1,tuple(str(i) for i in sorted(rng.sample(range(1,12),rng.randint(1,6))))) for v in range(1,18)]
            km,counts,_ = model(rows);cat=p.Catalog([(str(i),1) for i in range(1,16)])
            history = tuple(str(i) for i in rng.sample(range(1,18),rng.randint(1,5)))
            key = (str(rng.randint(1,20)),10)
            actual = k.Ranker(km,counts,cat).rank(100,history,key)
            expected = oracle.predict(dict(km.sessions),dict(km.support),km.fit_id,counts,dict(cat.first),100,history,key)
            self.assertEqual(actual,expected)


class CompleteOracleTests(unittest.TestCase):
    def test_full_four_arm_readback_and_bootstrap(self):
        out,result = run_case()
        receipt = oracle.verify_case(out)
        self.assertEqual(receipt['queries'],7);self.assertEqual(receipt['bootstrap_replicates'],2000)
        self.assertEqual(result['main']['arms']['K1']['target_occurrences'],8)
        self.assertLess(result['main']['arms']['K1']['reachable_target_occurrences'],8)

    def test_501_neighbor_full_oracle(self):
        out,result = run_case(boundary=True)
        self.assertEqual(oracle.verify_case(out)['sessions'],501)

    def test_reference_roster_and_provenance_fail_closed(self):
        for mutate in [lambda refs:refs.pop(),lambda refs:refs.append(deepcopy(refs[-1])),
                       lambda refs:refs[0].update(key=['0',0,0]),lambda refs:refs[0]['control_fit_ids'].update(P0='wrong')]:
            with self.subTest(mutation=mutate):
                with self.assertRaises(ValueError): run_case(mutate=mutate)

    def test_independent_oracle_detects_nested_tampering(self):
        out,_ = run_case()
        records = list(oracle.jsonlines(out/'queries.jsonl'))
        records[0]['predictions']['K1']['selected_neighbors'][0]['union'] += 1
        (out/'queries.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in records),encoding='utf-8')
        with self.assertRaises(ValueError): oracle.verify_case(out)

    def test_independent_bootstrap_detects_changed_draw(self):
        out,_ = run_case()
        records = list(oracle.jsonlines(out/'bootstrap.jsonl'));records[100]['query_denominator'] += 1
        (out/'bootstrap.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in records),encoding='utf-8')
        with self.assertRaises(ValueError): oracle.verify_case(out)

    def test_missing_current_history_stops(self):
        rows,counts,support,cat,queries,refs,draws,fits,expected = fixture_inputs()
        km=k.fit(rows,10,100,support,counts)
        rows=[b for b in rows if b.key()!=queries[0][0].key()]
        with self.assertRaises(ValueError):
            evaluation.evaluate(k.Ranker(km,counts,p.Catalog(cat)),rows,queries,refs,draws,fits,(100,1000),expected)

    def test_test_role_and_changed_denominator_stop(self):
        for change in ('test','candidate'):
            rows,counts,support,cat,queries,refs,draws,fits,expected = fixture_inputs()
            km=k.fit(rows,10,100,support,counts);q,index=queries[0]
            queries[0]=(replace(q,role='test') if change=='test' else replace(q,candidate_count=q.candidate_count-1),index)
            with self.assertRaises(ValueError):
                evaluation.evaluate(k.Ranker(km,counts,p.Catalog(cat)),rows,queries,refs,draws,fits,(100,1000),expected)

    def test_binary64_metric_and_full_target_denominator(self):
        primary=p.metric_terms(['1'],('1','99'));independent,_=oracle.terms(['1'],('1','99'))
        oracle.close(primary,independent)
        self.assertEqual(primary['recall'],0.5)
        self.assertAlmostEqual(primary['ndcg'],1/(1+1/__import__('math').log2(3)))


def cost_fixture():
    root=folder(); rows,counts,support,cat,queries,refs,draws,fits,expected = fixture_inputs()
    km,_,lineage=model(rows)
    header=['visitorid','session_start_ms','query_ms','role','basket_index','items']
    with (root/'baskets.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header)
        for b in rows:
            w.writerow([b.visitor,b.session,b.time,b.role,b.index,json.dumps(b.items) if b.role=='train' else 'DO NOT DECODE'])
        w.writerow(['999',1000,1000,'test',1,'DO NOT DECODE'])
    with (root/'support.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['itemid','support']);w.writerows(sorted(support.items(),key=lambda r:int(r[0])))
    (root/'lineage.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in lineage),encoding='utf-8')
    return root,header,km


class CostTests(unittest.TestCase):
    def test_two_pass_cost_ignores_poison_validation_and_test_arrays(self):
        root,header,km=cost_fixture()
        result=cost.audit(root/'baskets.csv',header,10,100,root/'support.csv',root/'lineage.jsonl',root/'cost')
        for name in ('train_sessions','train_baskets','singleton_sessions','distinct_session_item_memberships','maximum_posting_size'):
            self.assertEqual(result[name],km.audit[name])
        self.assertEqual(result['validation_test_item_arrays_decoded'],0)
        self.assertFalse(result['global_K1_index_built'])
        self.assertEqual(result['independent_rows_checked'],7)

    def test_cost_lineage_tamper_and_existing_output_rejected(self):
        root,header,_=cost_fixture()
        rows=list(oracle.jsonlines(root/'lineage.jsonl'));rows[0]['items']=['12345']
        (root/'lineage.jsonl').write_text(''.join(k.encoded(r)+'\n' for r in rows),encoding='utf-8')
        with self.assertRaises(ValueError): cost.audit(root/'baskets.csv',header,10,100,root/'support.csv',root/'lineage.jsonl',root/'cost')
        with self.assertRaises(FileExistsError): cost.audit(root/'baskets.csv',header,10,100,root/'support.csv',root/'lineage.jsonl',root/'cost')

    def test_cost_independent_row_hash_tampering_detected(self):
        root,header,_=cost_fixture()
        cost.audit(root/'baskets.csv',header,10,100,root/'support.csv',root/'lineage.jsonl',root/'cost')
        ledger=root/'cost/train_session_costs.csv'
        text=ledger.read_text(encoding='utf-8').replace('1,10,3,3,2,','1,10,3,3,1,',1)
        ledger.write_text(text,encoding='utf-8')
        with self.assertRaises(ValueError): cost.independent_cost(root/'baskets.csv',header,10,100,ledger)


if __name__=='__main__':
    unittest.main()
