"""Synthetic G3 sampling, sparse-cell, degeneracy and independent-oracle tests."""
import copy
from collections import Counter
from fractions import Fraction
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.metrics import adjusted_rand_score

from scripts import rfm_g3 as core
from scripts import rfm_g3_outputs as output
from scripts import rfm_rule_candidate as g2
from scripts import rfm_evaluation_contract as method


def fixture(n=1000, frequency=None):
    rows = [{'customer_unique_id': f'customer{i:05d}', 'activity_state': 'active_complete',
             'recency_seconds': i + 1, 'frequency_orders': frequency[i] if frequency is not None else 1 if i < 9*n//10 else 2,
             'monetary_product_cents': (i + 1)*100} for i in range(n)]
    partition = g2._partition(rows)
    cells = Counter(tuple(a['ordinal_tuple']) for a in partition['assignments_by_id'].values())
    floor = max(100, (n+199)//200)
    aggregate = {'reference_n': n, 'axes': partition['axes'], 'gate_status': {'G2': 'passed'},
        'neutral_joint_cell_counts': [{'ordinals': list(k), 'n': v,
            'support_flag': 'insufficient_group_support' if v < floor else None} for k,v in sorted(cells.items())]}
    reference = {'aggregate': aggregate, 'assignments_by_id': partition['assignments_by_id']}
    evaluation = {'format_version': 1, 'policy': method.policy(), 'planned_outputs': method.planned_outputs()}
    return rows, reference, evaluation


class G3CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = fixture()
        cls.result = core.evaluate(*cls.inputs)

    def test_fixed_five_seeds_exact_sample_size_and_full_denominator(self):
        result = self.result
        self.assertEqual(result['aggregate']['seeds'], [11,29,42,73,101])
        self.assertEqual(result['aggregate']['sample_n'],800)
        self.assertEqual(len(result['assignments']),5000)
        for sample in result['samples']:
            expected=np.random.Generator(np.random.PCG64(sample['seed'])).choice(1000,size=800,replace=False).tolist()
            self.assertEqual(sample['canonical_positions_in_draw_order'],expected)
            self.assertEqual(len(set(expected)),800)
        self.assertTrue(output.verify_result(*self.inputs,result)['accepted'])

    def test_stable_fixture_and_worst_case_not_best_seed(self):
        aggregate=self.result['aggregate']
        self.assertEqual(aggregate['gate_status']['G3'],'passed')
        self.assertEqual(aggregate['minimum_joint_ARI'],min(r['joint_ARI'] for r in aggregate['runs']))
        for axis in core.AXES:
            self.assertEqual(aggregate['minimum_axis_agreement'][axis],
                             min(r['axes'][axis]['agreement']['value'] for r in aggregate['runs']))

    def test_ties_never_split_and_f_direction_uses_two_levels(self):
        rows=self.inputs[0]
        for index in range(5):
            ledger=self.result['assignments'][index*1000:(index+1)*1000]
            self.assertEqual({x['f_ordinal'] for x in ledger[:900]},{1})
            self.assertEqual({x['f_ordinal'] for x in ledger[900:]},{2})
            for row in ledger:
                self.assertEqual(row['r_ordinal'],6-row['r_numeric_bin'])
        self.assertEqual(rows[0]['frequency_orders'],1)

    def test_small_joint_cells_preserved_without_failing_global_gate(self):
        values=[(r,1,m) for r in range(1,6) for m in range(1,6) for _ in range(40)]
        stats=core.joint_statistics(values,100)
        self.assertEqual(stats['small_cells'],25)
        self.assertEqual(stats['customers_in_small_cells'],1000)
        self.assertTrue(all(c['support_flag']=='insufficient_group_support' for c in stats['cells']))
        self.assertFalse(stats['degenerate'])

    def test_changed_effective_levels_fail_and_agreement_is_null(self):
        inputs=fixture(frequency=[1]*200+[2]*800)
        result=core.evaluate(*inputs)
        changed=[r for r in result['aggregate']['runs'] if r['axes'][core.AXES[1]]['effective_levels']!=2]
        self.assertTrue(changed)
        self.assertEqual(result['aggregate']['gate_status']['G3'],'ineligible')
        for run in changed:
            self.assertIsNone(run['axes'][core.AXES[1]]['agreement']['value'])
            self.assertIn('frequency_orders:levels_differ_from_reference',run['failed_checks'])
        self.assertTrue(output.verify_result(*inputs,result)['accepted'])

    def test_sample_only_cuts_and_low_agreement_are_not_rescued(self):
        class First800:
            def choice(self,n,size,replace): return np.arange(size)
        with patch.object(core.np.random,'Generator',return_value=First800()):
            result=core.evaluate(*self.inputs)
            first=result['aggregate']['runs'][0]
            self.assertEqual(first['axes'][core.AXES[0]]['cut_values'],[160,320,480,640])
            self.assertAlmostEqual(first['axes'][core.AXES[0]]['agreement']['value'],0.6)
            self.assertIn('recency_seconds:agreement_below_0.90',first['failed_checks'])
            self.assertEqual(result['aggregate']['gate_status']['G3'],'ineligible')
            output.verify_result(*self.inputs,result)

    def test_exact_90_percent_agreement_is_inclusive(self):
        selection=[]
        for start in (0,190,380,570): selection.extend([*range(start,start+159),start+189])
        selection.extend([*range(760,919),999])
        class BoundarySample:
            def choice(self,n,size,replace): return np.array(selection)
        with patch.object(core.np.random,'Generator',return_value=BoundarySample()):
            result=core.evaluate(*self.inputs)
            for run in result['aggregate']['runs']:
                self.assertEqual(run['axes'][core.AXES[0]]['agreement']['matched_customers'],900)
                self.assertNotIn('recency_seconds:agreement_below_0.90',run['failed_checks'])
            output.verify_result(*self.inputs,result)

    def test_domain_missing_duplicate_noncanonical_ID_and_frozen_policy_guards(self):
        rows,reference,evaluation=copy.deepcopy(self.inputs)
        rows[0]['monetary_product_cents']=True
        with self.assertRaises(ValueError): core.evaluate(rows,reference,evaluation)
        for changed in (self.inputs[0][:-1],list(reversed(self.inputs[0])),[self.inputs[0][0]]*1000):
            with self.assertRaises(ValueError): core.evaluate(changed,self.inputs[1],self.inputs[2])
        evaluation['policy']['stability']['seeds']=[42]
        with self.assertRaises(ValueError): core.evaluate(*self.inputs[:2],evaluation)

    def test_no_G2_core_reexecution_and_original_inputs_unchanged(self):
        inputs=copy.deepcopy(self.inputs)
        before=copy.deepcopy(inputs)
        with patch.object(g2,'evaluate_rule_candidate',side_effect=AssertionError), \
             patch.object(g2,'_partition',side_effect=AssertionError):
            core.evaluate(*inputs)
        self.assertEqual(inputs,before)

    def test_legal_zero_and_large_integer_money_keep_exact_cuts(self):
        rows,ref,ev=fixture()
        rows[0]['monetary_product_cents']=0
        # Rebind a synthetic G2 reference after changing the fixture, never real inputs.
        for i in range(1,1000): rows[i]['monetary_product_cents']+=2**53
        part=g2._partition(rows)
        ref['aggregate']['axes']=part['axes'];ref['assignments_by_id']=part['assignments_by_id']
        result=core.evaluate(rows,ref,ev)
        self.assertTrue(all(type(c) is int for r in result['aggregate']['runs']
            for c in r['axes'][core.AXES[2]]['cut_values']))
        output.verify_result(rows,ref,ev,result)


class G3OracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=fixture();cls.result=core.evaluate(*cls.inputs)

    def test_exact_ARI_hand_cases_and_label_permutation(self):
        a=[0,0,1,1];b=[0,1,0,1]
        self.assertEqual(output.exact_ari(a,b),Fraction(-1,2))
        self.assertEqual(output.exact_ari(a,[9,9,4,4]),1)
        for a,b in [([1]*4,[2]*4),(list(range(4)),list(range(4))),([1]*4,list(range(4)))]:
            self.assertAlmostEqual(float(output.exact_ari(a,b)),adjusted_rand_score(a,b))

    def test_tuple_ARI_differs_from_mean_axis_ARI(self):
        a=[(0,0),(0,1),(1,0),(1,1)]*3
        b=[(0,0),(0,0),(1,1),(1,1)]*3
        joint=float(output.exact_ari(a,b))
        average=sum(adjusted_rand_score([r[i] for r in a],[r[i] for r in b]) for i in range(2))/2
        self.assertNotAlmostEqual(joint,average)

    def test_degenerate_partitions_flag_even_when_ARI_is_one(self):
        for labels in ([(1,1,1)]*10,[(i,i,i) for i in range(10)]):
            self.assertTrue(core.joint_statistics(labels,100)['degenerate'])
            self.assertEqual(output.exact_ari(labels,labels),1)

    def test_oracle_never_calls_G3_core_or_sklearn_ARI(self):
        with patch.object(core,'evaluate',side_effect=AssertionError), \
             patch.object(core,'adjusted_rand_score',side_effect=AssertionError), \
             patch.object(core,'joint_statistics',side_effect=AssertionError):
            self.assertTrue(output.verify_result(*self.inputs,self.result)['accepted'])

    def test_sample_membership_cutpoints_ID_swap_and_ARI_tampering_rejected(self):
        mutations=[lambda r:r['samples'][0]['canonical_positions_in_draw_order'].__setitem__(0,-1),
            lambda r:r['assignments'][0].__setitem__('sampled_for_cutpoints',not r['assignments'][0]['sampled_for_cutpoints']),
            lambda r:r['aggregate']['runs'][0]['axes'][core.AXES[0]]['cut_values'].__setitem__(0,999),
            lambda r:r['aggregate']['runs'][0].__setitem__('joint_ARI',0.81),
            lambda r:r['aggregate'].__setitem__('minimum_joint_ARI',1.0),
            lambda r:r['assignments'][0].__setitem__('r_ordinal',True)]
        for mutate in mutations:
            value=copy.deepcopy(self.result);mutate(value)
            with self.assertRaises(ValueError): output.verify_result(*self.inputs,value)
        value=copy.deepcopy(self.result)
        value['assignments'][0],value['assignments'][1]=value['assignments'][1],value['assignments'][0]
        with self.assertRaises(ValueError): output.verify_result(*self.inputs,value)

    def test_extra_keys_missing_seed_and_false_small_cell_claim_rejected(self):
        for mutate in (lambda r:r['aggregate'].__setitem__('extra','bad'),
                       lambda r:r['aggregate']['runs'].pop(),
                       lambda r:r['aggregate']['runs'][0]['joint'].__setitem__('small_cells',999)):
            value=copy.deepcopy(self.result);mutate(value)
            with self.assertRaises(ValueError): output.verify_result(*self.inputs,value)


if __name__=='__main__': unittest.main()
