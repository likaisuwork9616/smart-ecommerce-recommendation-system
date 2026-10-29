"""Hand calculations, exact full-candidate oracles and tiny CSV end-to-end tests."""
from copy import deepcopy
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import random
import unittest
import uuid

from scripts import retailrocket_popularity as p
from scripts import retailrocket_popularity_io as io
from scripts import retailrocket_popularity_oracle as oracle

ROOT=Path(__file__).resolve().parents[1]
POLICY=json.loads((ROOT/'docs/contracts/retailrocket_popularity_execution_v1.json').read_text(encoding='utf-8'))
PARENT=json.loads((ROOT/'docs/contracts/retailrocket_recommendation_v1.json').read_text(encoding='utf-8'))
SCHEMAS=json.loads((ROOT/'reports/stage8/retailrocket_build_v1_specification.json').read_text(encoding='utf-8'))['schemas']
START=io.ms(PARENT['time_roles']['train'][0]);END=io.ms(PARENT['time_roles']['train'][1])


def event(i='2',t=START+1,role='train',kind='view'):
    return {'timestamp':t,'role':role,'event':kind,'itemid':i}


def model(values):
    events=[]
    for i,n in values.items():events.extend(event(i,t=START+j+1) for j in range(n))
    return p.fit_counts(events,START,END)


def query(v='1',t=END+1,targets=('2',),cat=None,seen=True,train=1,current=1):
    c=cat or p.Catalog([('2',START)])
    reach=sum(c.contains(i,t) for i in targets)
    return p.Query(v,t,t,'validation',targets,current,seen,train,c.size(t),reach,reach==len(targets))


def fixture(base=None,many=False):
    scratch=(base or ROOT/'shop-mysql-runtime/verification/retailrocket-popularity-implementation-v1/synthetic')/uuid.uuid4().hex
    source=scratch/'source';output=scratch/'output';source.mkdir(parents=True);output.mkdir()
    counts={'2':3,'10':3,'20':1}
    if many:counts.update({str(i):1 for i in range(21,32)})
    events=[event('1',START-1,'warmup')]
    for i,n in counts.items():events.extend(event(i,START+j+1) for j in range(n))
    events += [event('30',END+25,'validation'),event('999',END+1010,'validation'),event('50',io.ms(PARENT['time_roles']['reserved_test'][0])+1,'reserved_test')]
    cat={i:START+1 for i in counts};cat.update({'1':START-1,'30':END+25,'999':END+1010})
    # If '30' was trained in the many-item case, its first appearance remains in train.
    if '30' in counts:cat['30']=START+1
    qs=[('1',END+10,END+10,('10','999'),('2','10'),True,sum(counts.values())),
        ('1',END+10,END+20,('2',),('2',),True,sum(counts.values())),
        ('2',END+30,END+30,('1','30'),('30',),False,0)]
    def write(name,header,rows):
        with (source/name).open('x',encoding='utf-8',newline='') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(header);w.writerows(rows)
    write('qualified_events.csv',SCHEMAS['qualified_events.csv'],[[j,'a'*64,str(r['timestamp']),'1',r['event'],r['itemid'],'','b'*64,r['role']] for j,r in enumerate(events,2)])
    write('catalog.csv',SCHEMAS['catalog.csv'],sorted(cat.items()))
    basket_rows=[];query_rows=[]
    for no,(v,s,t,targets,current,seen,n) in enumerate(qs):
        reach=sum(i in cat and cat[i]<t for i in targets);candidate_n=sum(first<t for first in cat.values())
        basket_rows.append([v,s,t,'validation',1,list(current),'[2]',len(current)])
        query_rows.append([v,s,t,'validation',1,len(current),t+1000,'validation',1,1,0,'labelled',candidate_n,list(targets),len(targets),reach,int(reach==len(targets)),int(seen),0,n,p.activity(n)])
    def cells(rows):
        return [[json.dumps(v,separators=(',',':')) if isinstance(v,list) else v for v in row] for row in rows]
    write('baskets.csv',SCHEMAS['baskets.csv'],cells(basket_rows))
    # A malformed reserved-test target must never be parsed by a development loader.
    future=[*query_rows[-1]];future[0]='9';future[3]='reserved_test';future[13]='not-json-test-label'
    write('queries.csv',SCHEMAS['queries.csv'],cells(query_rows)+[future])
    policy=deepcopy(POLICY);policy['fixed_denominators_from_accepted_build']['validation']={
        'queries':3,'visitors':2,'target_occurrences':5,'reachable_target_occurrences':4,'all_targets_reachable_queries':2,
        'new_visitor_queries':1,'multi_item_current_basket_queries':1,'multi_item_target_basket_queries':2,'support_floor_queries':50}
    return scratch,source,output,policy


class CountTests(unittest.TestCase):
    def test_view_unit_includes_repeats_and_unlabelled_ends(self):
        m=p.fit_counts([event(),event(t=START+2),event(kind='addtocart'),event(kind='transaction')],START,END)
        self.assertEqual(dict(m.counts),{'2':2});self.assertEqual(m.audit['counted_view_rows'],2)
    def test_warmup_validation_test_do_not_enter_counts(self):
        data=[event(),event('1',START-1,'warmup'),event('3',END,'validation'),event('4',END+999,'reserved_test')]
        self.assertEqual(dict(p.fit_counts(data,START,END).counts),{'2':1})
    def test_future_injection_cannot_change_fit_identity(self):
        a=p.fit_counts([event()],START,END);b=p.fit_counts([event(),event('99',END+1,'validation')],START,END)
        self.assertEqual(a.fit_id,b.fit_id)
    def test_fit_is_immutable(self):
        with self.assertRaises(TypeError):model({'2':1}).counts['2']=9
    def test_development_cannot_fit_validation_roles(self):
        with self.assertRaises(ValueError):p.fit_counts([],START,END,('train','validation'))
    def test_selected_role_end_boundary_is_rejected(self):
        with self.assertRaises(ValueError):p.fit_counts([event(t=END)],START,END)
    def test_empty_fit_is_explicit(self):self.assertTrue(p.fit_counts([],START,END).audit['all_zero_fit'])
    def test_unknown_selected_event_stops(self):
        with self.assertRaises(ValueError):p.fit_counts([event(kind='click')],START,END)


class RankTests(unittest.TestCase):
    def test_numeric_ties(self):self.assertEqual(p.Ranker(model({'10':2,'2':2}),p.Catalog([('10',0),('2',0)])).rank(1)['ids'],['2','10'])
    def test_future_high_score_cannot_enter(self):
        ranker=p.Ranker(model({'99':10,'2':1}),p.Catalog([('99',100),('2',0)]))
        self.assertEqual(ranker.rank(100)['ids'],['2'])
    def test_zero_scores_participate_and_sort_numeric(self):
        ranker=p.Ranker(model({'5':1}),p.Catalog([('5',0),('10',0),('2',0)]))
        self.assertEqual(ranker.rank(1)['ids'],['5','2','10']);self.assertEqual(ranker.rank(1)['scores'],[1,0,0])
    def test_empty_fit_all_zero_order(self):self.assertEqual(p.Ranker(model({}),p.Catalog([('10',0),('2',0)])).rank(1)['ids'],['2','10'])
    def test_empty_catalog_no_padding(self):self.assertEqual(p.Ranker(model({}),p.Catalog([])).rank(1)['ids'],[])
    def test_same_clock_first_seen_excluded(self):self.assertEqual(p.Ranker(model({}),p.Catalog([('2',1)])).rank(1)['candidate_count'],0)
    def test_exact_top10_no_duplicates(self):
        self.assertEqual(p.Ranker(model({}),p.Catalog((str(i),0) for i in range(20))).rank(1)['ids'],[str(i) for i in range(10)])
    def test_wrong_fit_identity_rejected(self):
        r=p.Ranker(model({'2':1}),p.Catalog([('2',0)]));x=r.rank(1);x['fit_id']='wrong'
        with self.assertRaises(ValueError):r.validate_prediction(1,x)
    def test_suboptimal_but_sorted_shortlist_rejected(self):
        r=p.Ranker(model({}),p.Catalog((str(i),0) for i in range(11)));x=r.rank(1);x['ids']=[str(i) for i in range(1,11)]
        with self.assertRaises(ValueError):r.validate_prediction(1,x)
    def test_noninteger_score_rejected(self):
        r=p.Ranker(model({'2':1}),p.Catalog([('2',0)]));x=r.rank(1);x['scores']=[1.0]
        with self.assertRaises(ValueError):r.validate_prediction(1,x)
    def test_all_prefixes_match_independent_full_sort(self):
        rng=random.Random(42);counts={str(i):rng.randrange(1,20) for i in range(30)};catalog={str(i):rng.randrange(0,25) for i in range(45)}
        r=p.Ranker(model(counts),p.Catalog(catalog.items()))
        for t in range(27):
            expected,n=oracle.full_order(counts,catalog,t);actual=r.rank(t)
            self.assertEqual(actual['ids'],expected);self.assertEqual(actual['candidate_count'],n)


class MetricTests(unittest.TestCase):
    def test_hand_unreachable_target_full_IDCG(self):
        m=p.metric_terms(['2','10'],['10','999']);d=1/math.log2(3)
        self.assertAlmostEqual(m['ndcg'],d/(1+d),14);self.assertEqual(m['recall'],0.5);self.assertEqual(m['mrr'],0.5);self.assertEqual(m['hits'],1)
    def test_empty_recommendations_are_zero(self):self.assertEqual(p.metric_terms([],['2'])['ndcg'],0)
    def test_target_larger_than_K_uses_ten_ideal_slots(self):self.assertAlmostEqual(p.metric_terms([str(i) for i in range(10)],[str(i) for i in range(20)])['ndcg'],1)
    def test_duplicate_predictions_rejected(self):
        with self.assertRaises(ValueError):p.metric_terms(['2','2'],['2'])
    def test_duplicate_target_rejected(self):
        with self.assertRaises(ValueError):p.metric_terms([],['2','2'])
    def test_empty_target_rejected(self):
        with self.assertRaises(ValueError):p.metric_terms([],[])
    def test_Decimal_oracle_all_binary_patterns(self):
        for mask in range(1<<10):
            targets=[str(i) for i in range(10) if mask&(1<<i)]+['999']
            a=p.metric_terms([str(i) for i in range(10)],targets);b,_=oracle.terms([str(i) for i in range(10)],targets);oracle.close(a,b)


class AggregateTests(unittest.TestCase):
    def test_hand_query_and_visitor_macro_and_conditional(self):
        c=p.Catalog([('2',0)]);r=p.Ranker(model({'2':1}),c)
        qs=[query('1',END+1,cat=c),query('1',END+2,cat=c),query('2',END+3,('999',),c,seen=False,train=0)]
        a=p.evaluate(r,qs)
        self.assertAlmostEqual(a['metrics']['ndcg'],2/3);self.assertEqual(a['metrics']['visitor_macro_ndcg'],0.5)
        self.assertEqual(a['conditional']['queries'],2);self.assertEqual(a['conditional']['metrics']['ndcg'],1)
        self.assertEqual(a['slices']['current_basket']['multiple']['support'],'empty')
        self.assertEqual(a['slices']['target_model']['all_zero']['support'],'descriptive_only')
    def test_candidate_union_excludes_future_and_equal_max_time(self):
        c=p.Catalog([('2',0),('3',END+2),('99',END+3)]);r=p.Ranker(model({'2':1}),c)
        a=p.evaluate(r,[query('1',END+1,cat=c),query('1',END+3,cat=c)])
        self.assertEqual(a['candidate_union_items'],2)
    def test_empty_catalog_query_is_not_dropped(self):
        c=p.Catalog([]);r=p.Ranker(model({}),c);a=p.evaluate(r,[query(cat=c)])
        self.assertEqual(a['queries'],1);self.assertEqual(a['metrics']['ndcg'],0);self.assertIsNone(a['metrics']['catalog_coverage'])
    def test_zero_queries_are_null(self):self.assertIsNone(p.evaluate(p.Ranker(model({}),p.Catalog([])),[])['metrics']['ndcg'])
    def test_reserved_test_eval_refused(self):
        with self.assertRaises(ValueError):p.evaluate(p.Ranker(model({}),p.Catalog([])),[],role='reserved_test')
    def test_duplicate_query_refused(self):
        c=p.Catalog([('2',0)]);q=query(cat=c)
        with self.assertRaises(ValueError):p.evaluate(p.Ranker(model({'2':1}),c),[q,q])
    def test_candidate_count_mismatch_stops(self):
        c=p.Catalog([('2',0)])
        with self.assertRaises(ValueError):p.evaluate(p.Ranker(model({'2':1}),c),[replace(query(cat=c),candidate_count=0)])


class CSVTests(unittest.TestCase):
    def test_end_to_end_independent_readback_and_hand_value(self):
        _,source,out,policy=fixture();result=io.build_development(out,source,SCHEMAS,policy,PARENT);proof=oracle.verify(out,source,SCHEMAS,policy,PARENT)
        self.assertEqual(proof['aggregate']['queries'],3);self.assertGreater(proof['cells'],0);self.assertFalse(proof['ranking_oracle']['universal_positive_order_proved'])
        oracle.close(result['aggregate'],proof['aggregate'])
        with (out/'query_metrics.csv').open(encoding='utf-8',newline='') as f:first=next(csv.DictReader(f))
        d=1/math.log2(3);self.assertAlmostEqual(float(first['ndcg']),d/(1+d),14)
    def test_cached_positive_order_has_full_catalog_proof(self):
        _,source,out,policy=fixture(many=True);io.build_development(out,source,SCHEMAS,policy,PARENT)
        self.assertTrue(oracle.verify(out,source,SCHEMAS,policy,PARENT)['ranking_oracle']['universal_positive_order_proved'])
    def test_corrupt_metric_rejected_by_oracle(self):
        _,source,out,policy=fixture();io.build_development(out,source,SCHEMAS,policy,PARENT)
        path=out/'query_metrics.csv';lines=path.read_text(encoding='utf-8').splitlines();r=list(csv.reader(lines));r[1][-4]='nan'
        with path.open('w',encoding='utf-8',newline='') as f:csv.writer(f,lineterminator='\n').writerows(r)
        with self.assertRaisesRegex(ValueError,'cell mismatch'):oracle.verify(out,source,SCHEMAS,policy,PARENT)
    def test_extra_ranked_record_rejected(self):
        _,source,out,policy=fixture();io.build_development(out,source,SCHEMAS,policy,PARENT)
        path=out/'ranked_queries.csv'
        with path.open('a',encoding='utf-8') as f:f.write('extra\n')
        with self.assertRaises(ValueError):oracle.verify(out,source,SCHEMAS,policy,PARENT)
    def test_wrong_denominator_refused(self):
        _,source,out,policy=fixture();policy['fixed_denominators_from_accepted_build']['validation']['queries']=2
        with self.assertRaises(ValueError):io.build_development(out,source,SCHEMAS,policy,PARENT)
    def test_source_header_change_stops(self):
        _,source,out,policy=fixture();(source/'catalog.csv').write_text('bad,header\n',encoding='utf-8')
        with self.assertRaises(ValueError):io.build_development(out,source,SCHEMAS,policy,PARENT)
    def test_existing_artifact_not_overwritten(self):
        _,source,out,policy=fixture();io.build_development(out,source,SCHEMAS,policy,PARENT);before=(out/'item_counts.csv').read_bytes()
        with self.assertRaises(FileExistsError):io.build_development(out,source,SCHEMAS,policy,PARENT)
        self.assertEqual(before,(out/'item_counts.csv').read_bytes())
    def test_test_loader_refuses_before_open(self):
        with self.assertRaises(ValueError):list(io.queries(Path('does-not-exist'),SCHEMAS,PARENT,'reserved_test'))


if __name__=='__main__':unittest.main()
