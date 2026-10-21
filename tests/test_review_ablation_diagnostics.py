"""Hand-computed paired diagnostics; no model or private data."""
import json
import unittest
import numpy as np
import pandas as pd
from scripts import review_ablation_diagnostics as core
from tests.test_review_score_diagnostics import block, scores, features


class RankingTests(unittest.TestCase):
    def test_reverse_ranking_hand_computed(self):
        r=core.ranking([.1,.2,.3],[.3,.2,.1])
        self.assertAlmostEqual(r['spearman_average_ranks'],-1)
        self.assertEqual((r['moved_up'],r['moved_down'],r['unchanged_position']),(1,1,1))
        self.assertAlmostEqual(r['absolute_position_change']['mean'],4/3)
        self.assertEqual(r['absolute_position_change']['maximum'],2)

    def test_ties_use_canonical_order_and_average_ranks(self):
        r=core.ranking([.5,.5,.1],[.5,.1,.5])
        self.assertAlmostEqual(r['spearman_average_ranks'],-.5)
        self.assertEqual(r['unchanged_position'],1)
        self.assertEqual(r['control_tie_excess_rows'],1)

    def test_constant_spearman_null_but_order_stable(self):
        r=core.ranking([.5,.5,.5],[.5,.5,.5])
        self.assertIsNone(r['spearman_average_ranks'])
        self.assertEqual(r['unchanged_position'],3)

    def test_empty_and_singleton_are_json_safe(self):
        for c,t in [([],[]),([.5],[.2])]:
            r=core.ranking(c,t)
            self.assertIsNone(r['spearman_average_ranks'])
            json.dumps(r,allow_nan=False)

    def test_invalid_values_or_shapes_stop(self):
        for c,t in [([.1],[.2,.3]),([np.nan],[.1]),([1.1],[.2]),([.1],[-.1]),([[.1]],[[.2]])]:
            with self.subTest(c=c,t=t),self.assertRaises(ValueError):core.ranking(c,t)


class ProbabilityTests(unittest.TestCase):
    def test_unknown_never_enters_known_bias(self):
        truth=block((1,0,None));c=scores(truth,[.2,.2,.9]);t=scores(truth,[.4,.1,0])
        r=core.paired_profile(c,t,truth)
        self.assertAlmostEqual(r['treatment']['known_probability_bias'],-.25)
        self.assertAlmostEqual(r['probability_change']['known']['signed']['mean'],.05)
        self.assertEqual(r['ranking']['full']['orders'],3)
        self.assertEqual(r['ranking']['known']['orders'],2)
        self.assertEqual(r['ranking']['unknown']['orders'],1)
        self.assertEqual(r['probability_change']['unknown']['decreased'],1)

    def test_all_unknown_keeps_scores_known_empty(self):
        truth=block((None,None));r=core.paired_profile(scores(truth,[.1,.2]),scores(truth,[.2,.1]),truth)
        self.assertIsNone(r['treatment']['known_probability_bias'])
        self.assertEqual(r['ranking']['known']['orders'],0)
        self.assertIsNone(r['ranking']['known']['spearman_average_ranks'])

    def test_score_order_and_unknown_filling_rejected(self):
        truth=block();c=scores(truth,[.2,.3,.4])
        with self.assertRaises(ValueError):core.paired_profile(c.iloc[::-1],c,truth)
        truth.loc[2,'y']=0
        with self.assertRaises(ValueError):core.paired_profile(c,c,truth)

    def test_constant_reference_not_ranked_when_requested(self):
        truth=block();c=scores(truth,[.2]*3)
        r=core.paired_profile(c,c,truth,include_ranking=False)
        self.assertNotIn('ranking',r)
        self.assertEqual(r['probability_change']['full']['exactly_equal'],3)


class StrataTests(unittest.TestCase):
    def fixture(self,labels=(1,0,None)):
        truth=block(labels);qx=features(truth.order_id,waits=[0,1,72]);tx=features(['t1','t2'],waits=[0,100])
        qx['purchase_dayofweek']=[0,1,2];qx['purchase_hour']=[0,1,2]
        return truth,qx,tx

    def test_hand_calculated_whole_known_loss_denominator(self):
        truth,qx,tx=self.fixture();c=scores(truth,[.2,.2,.9]);t=scores(truth,[.4,.1,0])
        r=core.feature_strata(tx,qx,truth,c,t)
        rows=r['purchase_dayofweek']['strata']
        self.assertAlmostEqual(rows[0]['loss_delta_contributions']['brier'],-.14)
        self.assertAlmostEqual(rows[1]['loss_delta_contributions']['brier'],-.015)
        self.assertEqual(rows[2]['loss_delta_contributions']['brier'],0)
        self.assertIsNone(rows[2]['known_low_rate'])
        for v in r.values():
            self.assertAlmostEqual(v['summed_loss_delta_contributions']['brier'],-.155)
            for key,total in v['summed_loss_delta_contributions'].items():
                self.assertAlmostEqual(sum(row['loss_delta_contributions'][key] for row in v['strata']),total)

    def test_wait_boundaries_fixed_left_closed(self):
        truth,qx,tx=self.fixture();c=scores(truth,[.2]*3)
        rows=core.feature_strata(tx,qx,truth,c,c)['approval_wait_hours']['strata']
        self.assertEqual([r['full_orders'] for r in rows],[1,1,0,0,1,0])
        self.assertEqual(rows[-1]['upper'],None)

    def test_all_unknown_contributions_null(self):
        truth,qx,tx=self.fixture((None,None,None));c=scores(truth,[0,1,.5])
        r=core.feature_strata(tx,qx,truth,c,c)
        for group in r.values():
            self.assertIsNone(group['summed_loss_delta_contributions']['brier'])
            for row in group['strata']:self.assertIsNone(row['loss_delta_contributions']['brier'])
        json.dumps(r,allow_nan=False)

    def test_clipped_extremes_finite(self):
        truth,qx,tx=self.fixture();c=scores(truth,[0,1,.5]);t=scores(truth,[1,0,.5])
        r=core.feature_strata(tx,qx,truth,c,t)
        self.assertTrue(np.isfinite(r['purchase_hour']['summed_loss_delta_contributions']['binary_log_loss']))

    def test_support_is_own_training_and_only_three_features(self):
        truth,qx,tx=self.fixture();r=core.feature_support(tx,qx,truth)
        self.assertEqual(set(r['categorical']),{'purchase_dayofweek','purchase_hour'})
        self.assertEqual(r['eligible_training_orders'],2)
        self.assertEqual(r['categorical']['purchase_hour']['query_subsets']['full']['zero_training_support']['orders'],2)

    def test_reordered_features_rejected(self):
        truth,qx,tx=self.fixture();c=scores(truth,[.2]*3)
        with self.assertRaises(ValueError):core.feature_strata(tx,qx.iloc[::-1],truth,c,c)

    def test_protocol_no_alert_or_reselection(self):
        p=core.diagnostic_protocol();json.dumps(p,allow_nan=False)
        self.assertFalse(p['rank']['alert_budget_or_top_k_selection'])
        self.assertEqual(p['candidate_selections'],0)
        self.assertEqual(p['model_fit_transform_predict_calls'],0)
        p['features'].clear();self.assertEqual(len(core.diagnostic_protocol()['features']),3)


if __name__=='__main__':unittest.main()
