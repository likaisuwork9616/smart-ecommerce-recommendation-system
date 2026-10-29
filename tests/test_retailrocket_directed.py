"""D1 hand cases, full three-arm synthetic readback and independent oracle.

All fixtures and mutations are synthetic and saved inside the ignored shop
verification namespace. These tests never open the real training/query CSVs.
"""
from collections import Counter
from copy import deepcopy
import csv
from dataclasses import replace
from fractions import Fraction
import json
import math
from pathlib import Path
import random
import unittest
import uuid

from scripts import retailrocket_cooccurrence as c
from scripts import retailrocket_cooccurrence_io as c_io
from scripts import retailrocket_directed as d
from scripts import retailrocket_directed_io as io
from scripts import retailrocket_directed_oracle as oracle
from scripts import retailrocket_popularity as p
from tests.test_retailrocket_cooccurrence import fixture as c_fixture
from tests.test_retailrocket_cooccurrence import PARENT, SCHEMAS

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'shop-mysql-runtime/verification/retailrocket-directed-implementation-v1/synthetic'
POLICY=json.loads((ROOT/'docs/contracts/retailrocket_directed_paired_v1.json').read_text(encoding='utf-8'))


def fixture(base=None):
    """Return root,source,P0,C1,D1,policy,original_P0,original_C1,baskets.

    Reuse only the frozen *synthetic generator*, supplying our own shop path.
    Existing accepted real P0/C1 namespaces are never read or written.
    """
    base=Path(base or BASE).resolve()
    if not base.is_relative_to(ROOT):raise ValueError('Synthetic fixture must stay inside shop')
    root,source,baseline,c1_reference,c_policy,original_p0,rows=c_fixture(base=base)
    original_c1=c_io.build(c1_reference,source,baseline,SCHEMAS,c_policy,PARENT,original_p0['aggregate'])
    output=root/'D1';output.mkdir()
    policy=deepcopy(POLICY)
    policy['reference_identity']['P0_fit_id']=original_p0['fit_audit']['fit_id']
    policy['reference_identity']['C1_fit_id']=original_c1['fit_audit']['fit_id']
    policy['fixed_validation']=deepcopy(c_policy['fixed_validation'])
    return root,source,baseline,c1_reference,output,policy,original_p0,original_c1,rows


def reference_model(rows,start=10,end=100):
    counts=Counter(i for b in rows if b.role=='train' for i in b.items)
    model=c.fit(rows,start,end,counts)
    return model,dict(counts)


def fit_rows(rows,start=10,end=100,emit_session=None):
    reference,counts=reference_model(rows,start,end)
    model=d.fit(rows,start,end,reference.support,reference.pairs,counts,emit_session=emit_session)
    return model,reference,counts


def jsonlines(path):
    with path.open(encoding='utf-8') as f:
        for line in f:yield json.loads(line)


def write_jsonlines(path,rows):
    path.write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in rows),encoding='utf-8')


class CoreHandTests(unittest.TestCase):
    def setUp(self):
        self.rows=[c.Basket('1',10,10,'train',1,('1',)),c.Basket('1',10,11,'train',2,('2',)),
                   c.Basket('1',10,12,'train',3,('1',)),c.Basket('1',10,13,'train',4,('2',)),
                   c.Basket('2',10,10,'train',1,('1','2')),c.Basket('2',10,11,'train',2,('2','3')),
                   c.Basket('3',10,10,'train',1,('4',))]
        self.model,self.reference,self.counts=fit_rows(self.rows)
        self.cat=p.Catalog([(str(i),1) for i in range(1,16)])

    def test_hand_directed_binary_counts_reverse_and_cartesian(self):
        self.assertEqual(dict(self.model.support),{'1':2,'2':2,'3':1,'4':1})
        self.assertEqual(dict(self.model.edges),{('1','2'):2,('2','1'):1,('1','3'):1,('2','3'):1})
        self.assertEqual(self.model.audit['eligible_adjacent_basket_pairs'],4)
        self.assertEqual(self.model.audit['raw_directed_emissions'],6)
        self.assertEqual(self.model.audit['distinct_session_directed_edges'],5)
        self.assertEqual(self.model.audit['singleton_sessions'],1)
        self.assertNotIn(('2','2'),self.model.edges)

    def test_reverse_sum_can_exceed_C1_pair_without_violating_each_bound(self):
        self.assertGreater(self.model.edges['1','2']+self.model.edges['2','1'],self.reference.pairs['1','2'])
        for (a,b),n in self.model.edges.items():
            pair=tuple(sorted((a,b),key=int))
            self.assertLessEqual(n,self.reference.pairs[pair])
        self.assertLessEqual(sum(self.model.edges.values()),2*sum(self.reference.pairs.values()))

    def test_shared_support_singleton_and_incoming_only_not_dropped(self):
        self.assertIn('4',self.model.support)
        self.assertIn('3',self.model.support)
        self.assertFalse(any(a=='3' for a,b in self.model.edges))
        self.assertTrue(any(b=='3' for a,b in self.model.edges))
        self.assertEqual(dict(self.model.support),dict(self.reference.support))

    def test_lineage_conserves_all_session_edges(self):
        rows=[]
        model,_,_=fit_rows(self.rows,emit_session=rows.append)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['edges'],[['1','2'],['2','1']])
        self.assertEqual(rows[-1]['items'],['4'])
        self.assertEqual(rows[-1]['edges'],[])
        self.assertEqual(sum(len(r['edges']) for r in rows),sum(model.edges.values()))

    def test_gap_does_not_bridge_original_indices(self):
        rows=[c.Basket('1',10,10,'train',1,('1',)),c.Basket('1',10,11,'train',3,('2',))]
        model,_,_=fit_rows(rows)
        self.assertEqual(dict(model.edges),{})
        self.assertEqual(dict(model.support),{'1':1,'2':1})

    def test_nontrain_middle_does_not_bridge(self):
        rows=[c.Basket('1',10,10,'train',1,('1',)),c.Basket('1',10,11,'validation',2,('999',)),
              c.Basket('1',10,12,'train',3,('2',))]
        model,_,_=fit_rows(rows)
        self.assertEqual(dict(model.edges),{})
        self.assertNotIn('999',model.support)

    def test_cross_boundary_prefix_retained_without_crossing_edge(self):
        rows=[c.Basket('1',1,1,'warmup',1,('99',)),c.Basket('1',1,10,'train',2,('1',)),
              c.Basket('1',1,11,'train',3,('2',)),c.Basket('1',1,100,'validation',4,('999',))]
        model,_,_=fit_rows(rows)
        self.assertEqual(dict(model.edges),{('1','2'):1})
        self.assertEqual(dict(model.support),{'1':1,'2':1})

    def test_future_roles_cannot_change_fit(self):
        rows=self.rows+[c.Basket('9',100,100,'validation',1,('999',)),c.Basket('9',100,101,'reserved_test',2,('98',))]
        self.assertEqual(fit_rows(rows)[0].fit_id,self.model.fit_id)

    def test_same_millisecond_unordered_members_do_not_invent_edges(self):
        rows=[c.Basket('1',10,10,'train',1,('3','2','1'))]
        self.assertEqual(dict(fit_rows(rows)[0].edges),{})

    def test_session_change_never_links(self):
        rows=[c.Basket('1',10,10,'train',1,('1',)),c.Basket('1',11,11,'train',1,('2',))]
        self.assertEqual(dict(fit_rows(rows)[0].edges),{})

    def test_over_30_minute_adjacent_pair_not_counted(self):
        rows=[c.Basket('1',10,10,'train',1,('1',)),c.Basket('1',10,1800011,'train',2,('2',))]
        self.assertEqual(dict(fit_rows(rows,10,2000000)[0].edges),{})

    def test_train_clock_mismatch_rejected(self):
        rows=[replace(self.rows[0],time=100)]
        with self.assertRaises(ValueError):d.fit(rows,10,100,self.reference.support,self.reference.pairs,self.counts)

    def test_duplicate_train_timestamp_rejected(self):
        with self.assertRaises(ValueError):d.fit([self.rows[0],self.rows[0]],10,100,self.reference.support,self.reference.pairs,self.counts)

    def test_invalid_shared_support_or_pair_upper_bound_rejected(self):
        with self.assertRaises(ValueError):d.fit(self.rows,10,100,{'1':1,'2':2,'3':1,'4':1},self.reference.pairs,self.counts)
        with self.assertRaises(ValueError):d.fit(self.rows,10,100,self.reference.support,{},self.counts)
        with self.assertRaises(ValueError):d.fit(self.rows,10,100,{'1':2,'2':2,'3':1},self.reference.pairs,self.counts)

    def test_hand_rank_full_history_rational_score(self):
        pred=d.Ranker(self.model,self.counts,self.cat).rank(200,('1',))
        self.assertEqual(pred['ids'][:4],['2','3','1','4'])
        self.assertEqual(pred['scores'][:4],[[1,1],[1,2],[0,1],[0,1]])
        self.assertEqual(pred['supported_seeds'],1)
        self.assertEqual(pred['outgoing_seeds'],1)
        pred2=d.Ranker(self.model,self.counts,self.cat).rank(200,('1','2'))
        self.assertEqual(pred2['ids'][:3],['2','3','1'])
        self.assertEqual(pred2['scores'][:3],[[1,1],[1,1],[1,2]])

    def test_incoming_only_candidate_kept_and_noedge_P0_remains_positive(self):
        pred=d.Ranker(self.model,self.counts,self.cat).rank(200,('1',))
        self.assertIn('3',pred['ids'])
        n=pred['ids'].index('4')
        self.assertEqual(pred['scores'][n],[0,1])
        self.assertEqual(pred['p0_counts'][n],1)

    def test_fallback_reasons_distinguish_shared_support_and_outgoing(self):
        ranker=d.Ranker(self.model,self.counts,self.cat)
        a=ranker.rank(200,('99',));b=ranker.rank(200,('4',));z=ranker.rank(0,('1',))
        self.assertEqual(a['fallback_reason'],'no_shared_supported_seed')
        self.assertEqual(b['fallback_reason'],'no_outgoing_seed')
        self.assertEqual(z['fallback_reason'],'no_positive_causal_neighbor')
        self.assertEqual(a['ids'],b['ids'])
        self.assertEqual(a['ids'][:4],['2','1','3','4'])
        self.assertEqual(z['ids'],[])

    def test_exact_clock_catalog_exclusion_short_catalog_and_seen_retained(self):
        ranker=d.Ranker(self.model,self.counts,p.Catalog([(i,1) for i in self.counts]))
        self.assertEqual(ranker.rank(1,('1',))['ids'],[])
        self.assertEqual(len(ranker.rank(2,('1',))['ids']),4)
        self.assertIn('1',ranker.rank(2,('1',))['ids'])

    def test_positive_and_score_upper_bounds_do_not_rank_by_C1_scores(self):
        dr=d.Ranker(self.model,self.counts,self.cat);cr=c.Ranker(self.reference,self.counts,self.cat)
        for history in (('1',),('2',),('3',),('4',),('99',),('1','2')):
            dp=dr.rank(200,history);cp=cr.rank(200,history)
            self.assertEqual(dp['supported_seeds'],cp['supported_seeds'])
            self.assertLessEqual(dp['positive_candidates'],cp['positive_candidates'])
            if cp['fallback_reason'] is not None:self.assertIsNotNone(dp['fallback_reason'])
            for j in self.cat.first:
                ds=sum((Fraction(self.model.edges.get((i,j),0),self.model.support[i]) for i in history if i in self.model.support),Fraction())
                cs=sum((Fraction(self.reference.pairs.get(tuple(sorted((i,j),key=int)),0),self.reference.support[i]) for i in history if i in self.reference.support and i!=j),Fraction())
                self.assertLessEqual(ds,cs)

    def test_fraction_order_not_rounded_float_tie(self):
        n=2**54;support={'1':2*n,'2':n+1,'3':n+1}
        model=d.Model(support,{('1','2'):n,('1','3'):n+1},'synthetic',{})
        self.assertEqual(float(Fraction(n,2*n)),float(Fraction(n+1,2*n)))
        self.assertEqual(d.Ranker(model,support,self.cat).rank(200,('1',))['ids'][0],'3')

    def test_exact_ties_use_P0_then_numeric_ID(self):
        model=d.Model({'1':2,'2':1,'3':1},{('1','2'):1,('1','3'):1},'synthetic',{})
        self.assertEqual(d.Ranker(model,{'1':3,'2':2,'3':3},self.cat).rank(200,('1',))['ids'][:2],['3','2'])
        self.assertEqual(d.Ranker(model,{'1':3,'2':2,'3':2},self.cat).rank(200,('1',))['ids'][:2],['2','3'])

    def test_history_is_prefix_not_lifetime_or_target(self):
        rows=[c.Basket('1',1,1,'train',1,('99',)),c.Basket('1',10,10,'train',1,('1',)),
              c.Basket('1',10,11,'validation',2,('2',)),c.Basket('1',10,12,'validation',3,('3',))]
        q=p.Query('1',10,11,'validation',('3',),1,True,1,3,1,True)
        self.assertEqual(c.Histories(rows).at(q,2),('1','2'))

    def test_random_small_models_against_direct_full_catalog_enumeration(self):
        rng=random.Random(42)
        for trial in range(24):
            baskets=[];session_edges=[];counts=Counter();supports=Counter()
            for visitor in range(8):
                seq=[tuple(sorted(rng.sample([str(i) for i in range(1,13)],rng.randint(1,4)),key=int)) for _ in range(rng.randint(1,5))]
                members=set().union(*map(set,seq));supports.update(members)
                edges=set()
                for ix,items in enumerate(seq):
                    counts.update(items);baskets.append(c.Basket(str(visitor),10,10+ix,'train',ix+1,items))
                    if ix:edges.update((a,b) for a in seq[ix-1] for b in items if a!=b)
                session_edges.append(edges)
            baskets.sort(key=lambda b:b.key())
            model,_,_=fit_rows(baskets)
            expected_edges=Counter(e for edges in session_edges for e in edges)
            self.assertEqual(dict(model.edges),dict(expected_edges))
            cat=p.Catalog([(str(i),rng.choice((1,20,30))) for i in range(1,17)])
            ranker=d.Ranker(model,counts,cat)
            for _ in range(6):
                history=tuple(rng.sample([str(i) for i in range(1,18)],rng.randint(1,4)));t=rng.choice((20,30,40))
                def score(j):return sum((Fraction(sum((i,j) in edges for edges in session_edges),supports[i]) for i in history if supports[i] and i!=j),Fraction())
                want=sorted((j for j in cat.first if cat.first[j]<t),key=lambda j:(-score(j),-counts[j],int(j)))[:10]
                actual=ranker.rank(t,history)
                self.assertEqual(actual['ids'],want)
                self.assertEqual(actual['scores'],[[score(i).numerator,score(i).denominator] for i in want])


class BootstrapTests(unittest.TestCase):
    def reference(self):
        values=[]
        c.bootstrap([('1',.2),('1',.4),('2',.1)],values.append)
        return values

    def test_hand_query_weighted_cluster_ratio_reuses_draw_not_delta(self):
        reference=self.reference();actual=[]
        result=d.bootstrap([('1',1.0),('1',1.0),('2',-1.0)],iter(reference),actual.append)
        self.assertEqual(result['mean_delta'],1/3)
        self.assertEqual(result['interval'],[-1.0,1.0])
        self.assertEqual(len(actual),2000)
        self.assertEqual({v['query_denominator'] for v in actual},{2,3,4})
        for a,b in zip(actual,reference):
            for key in ('replicate','draw_sha256','query_denominator','rng_before','rng_after'):self.assertEqual(a[key],b[key])
            self.assertIn(a['delta'],(-1.0,1/3,1.0))
            self.assertNotEqual(a['delta'],b['delta'])

    def test_reference_bootstrap_missing_or_extra_rows_rejected(self):
        rows=self.reference();records=[('1',1.0),('1',1.0),('2',-1.0)]
        for damaged in (rows[:-1],rows+[rows[-1]]):
            with self.assertRaises(ValueError):d.bootstrap(records,iter(damaged))

    def test_reference_draw_rng_denominator_or_order_changes_rejected(self):
        records=[('1',1.0),('1',1.0),('2',-1.0)]
        for field,value in [('draw_sha256','0'*64),('query_denominator',999),('rng_before',{}),('replicate',1)]:
            rows=deepcopy(self.reference());rows[0][field]=value
            with self.assertRaises(ValueError):d.bootstrap(records,iter(rows))

    def test_nonfinite_new_delta_rejected(self):
        with self.assertRaises(ValueError):d.bootstrap([('1',float('nan'))],iter(self.reference()))

    def test_empty_bootstrap_keeps_undefined_and_rejects_reference_draws(self):
        self.assertIsNone(d.bootstrap([],[])['interval'])
        with self.assertRaises(ValueError):d.bootstrap([],self.reference())


class ThreeArmIntegrationTests(unittest.TestCase):
    def setUp(self):
        (self.root,self.source,self.baseline,self.reference,self.output,self.policy,
         self.original_p0,self.original_c1,self.baskets)=fixture()

    def build(self):
        return io.build(self.output,self.source,self.baseline,self.reference,SCHEMAS,self.policy,PARENT,
                        self.original_p0['aggregate'],self.original_c1['aggregate']['arms']['C1'])

    def verify(self,brute=True):
        return oracle.verify(self.output,self.source,self.baseline,self.reference,SCHEMAS,self.policy,PARENT,brute=brute)

    def test_hand_three_arm_full_catalog_independent_oracle(self):
        primary=self.build();accepted=self.verify()
        oracle.close(primary['aggregate'],accepted['aggregate'])
        rows=list(jsonlines(self.output/'queries.jsonl'));old_rows=list(jsonlines(self.reference/'queries.jsonl'))
        self.assertEqual(rows[0]['predictions']['D1']['ids'][:3],['3','1','2'])
        self.assertEqual(rows[0]['terms']['D1']['recall'],.5)
        self.assertAlmostEqual(rows[0]['terms']['D1']['ndcg'],.5/(1+1/math.log2(3)))
        self.assertEqual(rows[3]['history'],['5','6'])
        for row,old_row in zip(rows,old_rows):
            for arm in ('P0','C1'):
                self.assertEqual(row['predictions'][arm],old_row['predictions'][arm])
                self.assertEqual(row['terms'][arm],old_row['terms'][arm])
            self.assertEqual(row['delta']['D1_minus_C1']['ndcg'],row['terms']['D1']['ndcg']-old_row['terms']['C1']['ndcg'])
        self.assertEqual((self.output/'support.csv').read_bytes(),(self.reference/'support.csv').read_bytes())
        self.assertEqual(primary['aggregate']['arms']['P0'],self.original_c1['aggregate']['arms']['P0'])
        self.assertEqual(primary['aggregate']['arms']['C1'],self.original_c1['aggregate']['arms']['C1'])

    def test_independent_sparse_complete_complement_matches_all_nested_outputs(self):
        primary=self.build();accepted=self.verify(brute=False)
        oracle.close(primary['aggregate'],accepted['aggregate'])

    def test_cold_slice_uses_shared_S_not_outgoing_keys(self):
        primary=self.build()
        for group,expected in primary['aggregate']['arms']['P0']['slices']['target_model'].items():
            actual=primary['aggregate']['arms']['D1']['slices']['target_model'][group]
            for key in ('queries','visitors','target_occurrences','reachable_target_occurrences','all_targets_reachable_queries','support'):
                self.assertEqual(actual[key],expected[key])

    def test_missing_P0_query_rejected(self):
        path=self.baseline/'ranked_queries.csv';lines=path.read_text().splitlines();path.write_text('\n'.join(lines[:-1])+'\n')
        with self.assertRaises(ValueError):self.build()

    def test_missing_extra_or_out_of_order_C1_query_rejected(self):
        path=self.reference/'queries.jsonl';rows=list(jsonlines(path));write_jsonlines(path,[rows[1],rows[0],*rows[2:]])
        with self.assertRaises(ValueError):self.build()

    def test_missing_C1_query_rejected(self):
        path=self.reference/'queries.jsonl';rows=list(jsonlines(path));write_jsonlines(path,rows[:-1])
        with self.assertRaises(ValueError):self.build()

    def test_extra_C1_query_rejected(self):
        path=self.reference/'queries.jsonl';rows=list(jsonlines(path));write_jsonlines(path,rows+[rows[-1]])
        with self.assertRaises(ValueError):self.build()

    def test_C1_history_mismatch_rejected(self):
        path=self.reference/'queries.jsonl';rows=list(jsonlines(path));rows[0]['history']=['999'];write_jsonlines(path,rows)
        with self.assertRaises(ValueError):self.build()

    def test_full_denominator_drift_rejected(self):
        self.policy['fixed_validation']['queries']=4
        with self.assertRaises(ValueError):self.build()

    def test_oracle_rejects_directed_edge_corruption(self):
        self.build();path=self.output/'edges.csv'
        with path.open(newline='',encoding='utf-8') as f:rows=list(csv.reader(f))
        rows[1][2]=str(int(rows[1][2])+1)
        with path.open('w',newline='',encoding='utf-8') as f:csv.writer(f,lineterminator='\n').writerows(rows)
        with self.assertRaises(ValueError):self.verify()

    def test_oracle_rejects_rational_corruption(self):
        self.build();path=self.output/'queries.jsonl';rows=list(jsonlines(path))
        rows[0]['predictions']['D1']['scores'][0]=[99,1];write_jsonlines(path,rows)
        with self.assertRaises(ValueError):self.verify()

    def test_oracle_rejects_copied_C1_metric_corruption(self):
        self.build();path=self.output/'queries.jsonl';rows=list(jsonlines(path))
        rows[0]['terms']['C1']['ndcg']+=.01;write_jsonlines(path,rows)
        with self.assertRaises(ValueError):self.verify()

    def test_oracle_rejects_new_delta_replaced_with_old_delta(self):
        self.build();path=self.output/'queries.jsonl';rows=list(jsonlines(path));old_rows=list(jsonlines(self.reference/'queries.jsonl'))
        rows[0]['delta']['D1_minus_C1']['ndcg']=old_rows[0]['delta']['ndcg'];write_jsonlines(path,rows)
        with self.assertRaises(ValueError):self.verify()

    def test_oracle_rejects_bootstrap_draw_corruption(self):
        self.build();path=self.output/'bootstrap.jsonl';rows=list(jsonlines(path));rows[0]['draw_sha256']='0'*64;write_jsonlines(path,rows)
        with self.assertRaises(ValueError):self.verify()

    def test_oracle_rejects_bootstrap_old_C1_delta(self):
        self.build();path=self.output/'bootstrap.jsonl';rows=list(jsonlines(path));old_rows=list(jsonlines(self.reference/'bootstrap.jsonl'))
        rows[0]['delta']=old_rows[0]['delta'];write_jsonlines(path,rows)
        with self.assertRaises(ValueError):self.verify()

    def test_exclusive_outputs_reject_replay(self):
        self.build()
        with self.assertRaises(FileExistsError):self.build()


if __name__=='__main__':unittest.main()
