"""Synthetic hand counts of H60 availability, coverage and temporal windows."""
import copy
import json
import unittest
import numpy as np
import pandas as pd
from scripts import review_mature_prior_audit as core


def train_block(ages=(10,60,61,90,150,240,300),ys=(None,None,1,0,1,None,0),fit='2018-04-01'):
    fit=pd.Timestamp(fit);t=pd.Series([fit-pd.Timedelta(days=a) for a in ages])
    maturity=np.asarray(ages)>60
    states=['known_low_1_2' if y==1 else 'known_other_3_5' if y==0 else
            'immature_observation_window' if not m else 'no_visible_answer_at_cutoff' for y,m in zip(ys,maturity)]
    return pd.DataFrame({'outer_fold':'2018-04','role':'outer_train_pool','fit_at':fit,
        'order_id':[f'order-{i}' for i in range(len(ages))],'prediction_time':t,
        'window_deadline':t+pd.Timedelta(days=60),'observation_cutoff':fit,
        'horizon_complete':maturity,'label_state':states,
        'role_label_usable':[y is not None for y in ys],'y':pd.Series(ys,dtype='Int64'),
        'first_visible_answer_at':pd.to_datetime([v+pd.Timedelta(days=1) if y is not None or not m else pd.NaT for v,y,m in zip(t,ys,maturity)])})


def query_block():
    q=train_block((100,110),(1,0),fit='2018-07-30')
    # Keep approval/answer times; use earlier model fit and later truth cutoff.
    q['fit_at']=pd.Timestamp('2018-04-01');q['role']='outer_evaluation'
    q['order_id']=['query-0','query-1']
    return q


class CoverageTests(unittest.TestCase):
    def test_hand_counts_unknown_and_immature_disjoint(self):
        c=core.coverage(train_block(),training=True)
        self.assertEqual((c['full_orders'],c['known_mature'],c['mature_unknown'],c['immature_unknown']),(7,4,1,2))
        self.assertEqual(c['unknown_total'],3);self.assertEqual(c['known_low_rate'],.5)
        self.assertEqual(c['known_coverage_of_mature'],.8)

    def test_quality_override_does_not_hide_immaturity(self):
        b=train_block();b.loc[0,'label_state']='unpositionable_answer_source_quality'
        c=core.coverage(b,training=True)
        self.assertEqual(c['immature_unknown'],2)
        self.assertEqual(c['state_maturity']['immature_observation_window']['immature'],1)
        self.assertEqual(c['state_maturity']['unpositionable_answer_source_quality']['immature'],1)

    def test_exact_sixty_day_boundary_stays_unknown(self):
        b=train_block((60,61),(None,1));c=core.coverage(b,training=True)
        self.assertEqual(c['immature_unknown'],1)
        b.loc[0,['role_label_usable','y','label_state']]=[True,1,'known_low_1_2']
        with self.assertRaises(ValueError):core.coverage(b,training=True)

    def test_early_answered_immature_does_not_enter_prior(self):
        b=train_block();self.assertTrue(pd.notna(b.loc[0,'first_visible_answer_at']))
        self.assertEqual(core.training_prior(b)['full_history']['known_mature'],4)

    def test_unknown_cannot_be_filled_as_zero(self):
        b=train_block();b.loc[0,'y']=0
        with self.assertRaises(ValueError):core.coverage(b,training=True)

    def test_future_cutoff_cannot_replace_fit_cutoff(self):
        b=train_block();b['observation_cutoff']+=pd.Timedelta(days=1)
        with self.assertRaises(ValueError):core.training_prior(b)

    def test_answer_at_exclusive_fit_rejected(self):
        b=train_block();b.loc[2,'first_visible_answer_at']=b.fit_at.iloc[0]
        with self.assertRaises(ValueError):core.training_prior(b)

    def test_clock_or_maturity_corruption_rejected(self):
        for name,value in [('window_deadline',pd.Timestamp('2019-01-01')),('horizon_complete',True),('role_label_usable','True')]:
            b=train_block().astype({name:object}) if isinstance(value,str) else train_block()
            b.loc[0,name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):core.coverage(b,training=True)


class TemporalTests(unittest.TestCase):
    def test_mature_recent_window_boundaries_and_hand_prior(self):
        p=core.training_prior(train_block())
        w=p['recent_mature_windows'][0]
        self.assertEqual(w['days'],90)
        self.assertEqual(w['coverage']['full_orders'],3)
        self.assertAlmostEqual(w['coverage']['known_low_rate'],2/3)
        self.assertEqual(w['coverage']['immature_unknown'],0)
        self.assertEqual(p['recent_mature_windows'][1]['coverage']['mature_unknown'],1)

    def test_age_sixty_bin_still_contains_one_immature(self):
        bins=core.training_prior(train_block())['approval_age_bins']
        self.assertEqual(bins[2]['lower_inclusive_days'],60)
        self.assertEqual(bins[2]['coverage']['immature_unknown'],1)

    def test_all_history_partitions_reconstruct_counts(self):
        p=core.training_prior(train_block())
        for key in ['approval_age_bins','approval_months']:
            self.assertEqual(sum(x['coverage']['full_orders'] for x in p[key]),7)
            self.assertEqual(sum(x['coverage']['known_mature'] for x in p[key]),4)

    def test_empty_months_and_window_prior_are_null(self):
        p=core.training_prior(train_block((10,300),(None,0)))
        self.assertIsNone(p['recent_mature_windows'][0]['coverage']['known_low_rate'])
        self.assertTrue(any(x['coverage']['full_orders']==0 for x in p['approval_months']))
        for x in p['approval_months']:
            if x['coverage']['full_orders']==0:self.assertIsNone(x['coverage']['known_low_rate'])
        json.dumps(p,allow_nan=False)

    def test_query_answers_change_diagnostic_only_not_prior(self):
        history=train_block();prior=core.training_prior(history);before=copy.deepcopy(prior)
        query=query_block();first=core.compare_retrospective_query(prior,query)
        query['y']=pd.Series([0,0],dtype='Int64');query['label_state']='known_other_3_5'
        second=core.compare_retrospective_query(prior,query)
        self.assertNotEqual(first['coverage']['known_low_rate'],second['coverage']['known_low_rate'])
        self.assertEqual(prior,before);self.assertEqual(first['query_labels_used_in_prior'],0)
        self.assertEqual(first['available_query_labels_at_fit'],0)
        self.assertFalse(first['window_selected'])

    def test_query_truth_cannot_be_passed_as_history(self):
        with self.assertRaises(ValueError):core.training_prior(query_block())

    def test_query_fit_mismatch_rejected(self):
        q=query_block();q['fit_at']-=pd.Timedelta(days=1)
        with self.assertRaises(ValueError):core.compare_retrospective_query(core.training_prior(train_block()),q)


class TransitionTests(unittest.TestCase):
    def pair(self):
        earlier=train_block();later=earlier.copy(deep=True)
        later['fit_at']+=pd.Timedelta(days=90);later['observation_cutoff']=later.fit_at
        later['horizon_complete']=True
        later.loc[[0,1],['role_label_usable','label_state','y']]=[True,'known_low_1_2',1]
        return earlier,later

    def test_later_maturity_does_not_backfill_earlier_labels(self):
        a,b=self.pair();before=a.copy(deep=True);r=core.shared_history_transition(a,b)
        self.assertEqual(r['unknown_to_known'],2)
        self.assertEqual(r['earlier_immature_to_later_known'],2)
        pd.testing.assert_frame_equal(a,before)

    def test_previously_known_label_change_stops(self):
        a,b=self.pair();b.loc[2,['y','label_state']]=[0,'known_other_3_5']
        with self.assertRaises(ValueError):core.shared_history_transition(a,b)

    def test_missing_shared_history_stops(self):
        a,b=self.pair()
        with self.assertRaises(ValueError):core.shared_history_transition(a,b.iloc[1:])

    def test_protocol_has_no_window_selection_or_parameters(self):
        p=core.audit_protocol();json.dumps(p,allow_nan=False)
        self.assertFalse(p['window_selection']);self.assertFalse(p['parameter_updates'])
        self.assertFalse(p['unknown_labels_filled']);self.assertEqual(p['performance_metrics'],0)


if __name__=='__main__':unittest.main()
