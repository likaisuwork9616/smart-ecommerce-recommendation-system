"""Hand-calculated evaluation rules, small groups, frozen application and audit parity."""
from copy import deepcopy
import csv
import json
import unittest
from unittest.mock import patch
import uuid
import pandas as pd

from scripts import uci_rfm_temporal as c
from scripts import uci_rfm_temporal_reference as ref
from scripts import run_uci_rfm_temporal_v1 as runner
from scripts import freeze_uci_rfm_contract as frozen
from scripts import build_uci_rfm_v1 as build


def customer(i,R=86400,F=2,M=10000,state='active_complete',arm='main',tid='T1'):
    usable=state=='active_complete'
    if state.endswith('with_quarantine'):R=F=M=None
    elif not usable:R,F,M=None,0,0
    return {'customer_key':str(10000+i),'arm':arm,'T_id':tid,'state':state,'rfm_usable':usable,'R_seconds':R,'F_invoices':F,'M_milli_GBP':M}


def frame(rows):
    out=pd.DataFrame(rows,dtype=object)
    out['rfm_usable']=out.rfm_usable.astype(bool)
    return out


class TemporalTests(unittest.TestCase):
    def scratch(self):
        path=frozen.within(frozen.ROOT,'shop-mysql-runtime/verification/uci-rfm-temporal-v1/synthetic/'+uuid.uuid4().hex)
        path.mkdir(parents=True);return path

    def sample(self,n=250):return [customer(i,R=(i+1)*600,F=i%8+1,M=(i+1)*3) for i in range(n)]

    def test_nearest_rank_hand_endpoints_no_interpolation(self):
        self.assertEqual([c.quantile([1,2,3,4,5],p) for p in [0,.2,.4,.5,1]],[1,1,2,3,5])
        self.assertIsNone(c.quantile([],0.5))

    def test_signed_delta_quantiles(self):
        self.assertEqual(c.quantile([-5,-1,2,9],.5),-1)
        self.assertEqual(c.quantile([-5,-1,2,9],.9),9)

    def test_reference_insufficient_199(self):
        cuts=c.fit_reference(self.sample(199),'main/T1')
        self.assertEqual(cuts['status'],'insufficient_reference')
        self.assertIsNone(c.apply(self.sample(1),cuts)[0]['joint_tuple'])

    def test_reference_200_allowed(self):
        self.assertEqual(c.fit_reference(self.sample(200),'main/T1')['status'],'fitted_once')

    def test_T2_or_sensitivity_reference_rejected(self):
        for name in ['main/T2','duplicate_sensitivity/T1']:
            with self.assertRaises(ValueError):c.fit_reference(self.sample(),name)

    def test_repeated_quantiles_remove_maximum_and_keep_ties(self):
        rows=[customer(i,F=1 if i<200 else 2) for i in range(250)]
        cuts=c.fit_reference(rows,'main/T1');scores=c.apply(rows,cuts)
        self.assertEqual(cuts['axes']['F']['cutpoints'],[1])
        self.assertEqual({r['F_score'] for r in scores[:200]},{1})
        self.assertEqual({r['F_score'] for r in scores[200:]},{2})

    def test_constant_axis_one_level(self):
        rows=[customer(i) for i in range(200)];cuts=c.fit_reference(rows,'main/T1')
        self.assertEqual(cuts['axes']['F']['levels'],1)
        self.assertTrue(cuts['axes']['F']['constant_reference'])
        self.assertEqual(c.apply(rows,cuts)[0]['joint_tuple'],[1,1,1])

    def test_equal_cutpoint_stays_lower_value_bin_R_reversed(self):
        cuts={'status':'fitted_once','axes':{a:{'cutpoints':[2,4,6,8],'levels':5} for a in c.AXES}}
        out=c.apply([customer(0,R=2,F=2,M=2)],cuts)[0]
        self.assertEqual(out['joint_tuple'],[5,1,1])

    def test_application_never_fits_or_mutates_thresholds(self):
        cuts=c.fit_reference(self.sample(),'main/T1');before=deepcopy(cuts)
        with patch.object(c,'fit_reference',side_effect=AssertionError('must not refit')):
            out=c.apply([customer(0,R=1,F=999999,M=99999999,tid='T2')],cuts)
        self.assertEqual(out[0]['F_score'],cuts['axes']['F']['levels'])
        self.assertEqual(cuts,before)

    def test_inactive_and_quarantine_have_no_scores(self):
        rows=self.sample()+[customer(500,state='inactive_complete'),customer(501,state='active_with_quarantine')]
        cuts=c.fit_reference(rows,'main/T1');out=c.apply(rows,cuts)
        self.assertTrue(all(r['joint_tuple'] is None for r in out[-2:]))

    def test_tied_rank_Spearman_hand_calculation(self):
        self.assertAlmostEqual(c.spearman([1,1,2,3],[1,2,2,3]),5/6)
        self.assertAlmostEqual(c.spearman([1,2,3],[3,2,1]),-1)

    def test_constant_Spearman_undefined(self):
        self.assertIsNone(c.spearman([1,1,1],[1,2,3]))

    def test_ARI_hand_negative(self):
        self.assertEqual(c.ari(['A','A','B','B'],['A','B','A','B']),-.5)

    def test_ARI_partition_not_label_agreement(self):
        self.assertEqual(c.ari(['A','A','B','B'],['B','B','A','A']),1)
        self.assertEqual(sum(a==b for a,b in zip(['A','A','B','B'],['B','B','A','A'])),0)

    def test_degenerate_ARI_null(self):
        self.assertIsNone(c.ari(['A']*4,['B']*4))
        self.assertIsNone(c.ari(['A','B','C'],['X','Y','Z']))

    def test_small_panel_no_correlation_or_ARI(self):
        cuts=c.fit_reference(self.sample(),'main/T1');a=c.apply(self.sample(199),cuts)
        result=c.paired_numeric(a,a,cuts)
        self.assertEqual(result['axes']['F']['spearman_null_reason'],'insufficient_n')
        self.assertEqual(result['joint']['ARI_null_reason'],'insufficient_n')

    def test_empty_panel_rates_null_not_100(self):
        cuts=c.fit_reference(self.sample(),'main/T1');out=c.paired_numeric([],[],cuts)
        self.assertIsNone(out['joint']['exact_rate'])
        self.assertIsNone(out['score_axes']['R']['within_one_rate'])

    def test_transition_denominators_and_empty_rows(self):
        out=c.transition(['A','A'],['A','B'],['A','B','C'])
        self.assertEqual(sum(row['n'] for row in out['cells']),2)
        self.assertEqual([row['row_rate'] for row in out['cells']],[.5,.5])
        self.assertEqual(out['empty_source_rows'],['B','C'])

    def test_support_at_50_allowed_49_flagged(self):
        cuts={'status':'fitted_once','axes':{a:{'levels':2} for a in c.AXES}}
        rows=[dict(customer(i),R_score=1,F_score=1,M_score=1,joint_tuple=[1,1,1]) for i in range(49)]
        rows += [dict(customer(i+49),R_score=2,F_score=2,M_score=2,joint_tuple=[2,2,2]) for i in range(51)]
        out=c.support(rows,cuts)
        self.assertEqual(out['joint']['under_supported_groups'],1)
        self.assertEqual(out['joint']['people_in_under_supported_groups'],49)
        self.assertEqual(out['joint']['empty_groups'],6)

    def test_support_floor_ceiling_population(self):
        cuts={'status':'insufficient_reference'}
        self.assertEqual(c.support([customer(i) for i in range(5001)],cuts)['minimum'],51)

    def test_state_population_and_new_keys_not_dropped(self):
        a=self.sample()+[customer(500,state='inactive_complete')]
        b=[customer(r-10000,tid='T2') for r in range(10000,10250)]+[customer(500,state='inactive_complete',tid='T2'),customer(501,tid='T2')]
        cuts=c.fit_reference(a,'main/T1');out=c.temporal(c.apply(a,cuts),c.apply(b,cuts),cuts)
        self.assertEqual(out['U1'],251);self.assertEqual(out['paired']['n'],250)
        self.assertEqual(out['new_observed_keys'],1)
        self.assertEqual(out['paired_coverage']['over_U1'],250/251)

    def test_universe_loss_rejected(self):
        rows=self.sample();cuts=c.fit_reference(rows,'main/T1')
        with self.assertRaises(ValueError):c.temporal(c.apply(rows,cuts),c.apply(rows[:-1],cuts),cuts)

    def test_sensitivity_R_or_state_change_rejected(self):
        rows=self.sample();cuts=c.fit_reference(rows,'main/T1');a=c.apply(rows,cuts);b=deepcopy(a);b[0]['R_seconds']+=1
        with self.assertRaises(ValueError):c.sensitivity(a,b,cuts)

    def test_sensitivity_money_changes_and_zero_main_ratio(self):
        rows=[customer(0,M=0),customer(1,M=1000)];cuts={'status':'insufficient_reference'}
        a=c.apply(rows,cuts);b=deepcopy(a);b[0]['M_milli_GBP']=500;b[1]['M_milli_GBP']=1200
        out=c.sensitivity(a,b,cuts)
        self.assertEqual(out['M_total_delta_milli_GBP'],700)
        self.assertEqual(out['relative_delta_excluded_zero_main'],1)
        self.assertEqual(out['M_customer_relative_delta']['quantiles']['0.5'],.2)

    def test_ledger_missing_ID_signed_and_positive_shares(self):
        path=self.scratch()/'rows.csv'
        header=['timestamp','customer_key','primary_reason','signed_raw_amount_milli_GBP']
        build.write_csv(path,header,[['2010-01-01 00:00:00',None,'unknown_customer',1000],['2010-01-01 00:00:00','12345','eligible_paid_line',3000],['2010-01-01 00:00:00',None,'cancellation_document',-500],['2010-12-01 00:00:00',None,'unknown_customer',9999]])
        actual=c.ledger(path,'2009-12-01 00:00:00','2010-12-01 00:00:00')
        expected=ref.ledger(path,'2009-12-01 00:00:00','2010-12-01 00:00:00')
        self.assertEqual(actual['rows'],3);self.assertEqual(actual['unknown_customer_signed_amount_share'],500/3500)
        self.assertEqual(actual['unknown_customer_positive_amount_share'],.25)
        runner.compare_tree(actual,expected)

    def test_independent_numpy_cutpoints_and_all_metrics(self):
        a=self.sample()+[customer(500,state='inactive_complete'),customer(501,state='active_with_quarantine')]
        b=[customer(i,R=(250-i)*500,F=(i+3)%9+1,M=(i+1)*4,tid='T2') for i in range(240)]
        b += [customer(i,state='inactive_complete',tid='T2') for i in range(240,250)]
        b += [customer(500,state='inactive_complete',tid='T2'),customer(501,state='active_with_quarantine',tid='T2'),customer(502,tid='T2')]
        cuts=c.fit_reference(a,'main/T1');other=ref.cutpoints(frame(a));runner.compare_tree(cuts,other)
        sa,sb=c.apply(a,cuts),c.apply(b,cuts);ra,rb=ref.scored(frame(a),other),ref.scored(frame(b),other)
        runner.compare_tree(c.snapshot(sa,cuts),ref.snapshot(ra,other))
        runner.compare_tree(c.snapshot(sb,cuts),ref.snapshot(rb,other))
        runner.compare_tree(c.temporal(sa,sb,cuts),ref.temporal(ra,rb,other))
        sens=deepcopy(a)
        for r in sens:
            if r['rfm_usable']:r['M_milli_GBP']+=100
        runner.compare_tree(c.sensitivity(sa,c.apply(sens,cuts),cuts),ref.sensitivity(ra,ref.scored(frame(sens),other),other))

    def test_independent_empty_and_degenerate_metrics(self):
        rows=[customer(i) for i in range(200)];cuts=c.fit_reference(rows,'main/T1');a=c.apply(rows,cuts);b=ref.scored(frame(rows),cuts)
        runner.compare_tree(c.paired_numeric(a,a,cuts),ref.paired(b,b,cuts))
        runner.compare_tree(c.paired_numeric([],[],cuts),ref.paired(b.iloc[:0],b.iloc[:0],cuts))

    def test_readback_catches_swapped_scores(self):
        path=self.scratch()/'scores.csv';build.write_csv(path,['key','score'],[['12345',1],['54321',5]])
        with self.assertRaises(ValueError):build.compare_csv(path,['key','score'],[['12345',5],['54321',1]])

    def test_JSON_audit_rejects_wrong_count_or_scope(self):
        with self.assertRaises(ValueError):runner.compare_tree({'n':3},{'n':4})
        with self.assertRaises(ValueError):runner.compare_tree({'T2_fits':0},{'T2_fits':1})

    def test_JSON_float_tolerance_and_undefined_value(self):
        self.assertEqual(runner.compare_tree({'r':.5},{'r':.5+1e-14}),1)
        with self.assertRaises(ValueError):runner.compare_tree({'r':None},{'r':1})


if __name__=='__main__':unittest.main()
