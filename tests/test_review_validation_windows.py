"""Hand calendar boundaries and label-blind exposure classification."""
import json
import unittest
import pandas as pd
from scripts import review_validation_windows as core


def fixture():
    times=['2018-04-01 00:00:00','2018-04-30 23:59:59','2018-05-01 00:00:00',
           '2018-05-02 00:00:00','2018-06-01 00:00:00','2018-09-01 00:00:00']
    orders=pd.DataFrame({'order_id':[f'o{i}' for i in range(len(times))],
        'order_purchase_timestamp':times,'order_approved_at':times})
    reviews=pd.DataFrame({'review_id':['r1','r2'],'order_id':['o2','o5'],
        'review_creation_date':['2018-05-05 00:00:00','2018-09-02 00:00:00'],
        'review_answer_timestamp':['2018-05-06 00:00:00','2020-01-01 00:00:00']})
    membership=pd.DataFrame({'outer_fold':['2018-04','2018-04'],'role':['outer_evaluation','outer_evaluation'],
        'order_id':['o0','o1'],'prediction_time':pd.to_datetime(times[:2]),'role_label_usable':[True,False]})
    usage={'stage5_inner_months':['2017-09','2017-11','2017-12'],
           'stage5_outer_months':['2017-12','2018-02','2018-04'],
           'stage4_test_months':['2018-05','2018-06','2018-07','2018-08']}
    return orders,reviews,membership,usage


class WindowTests(unittest.TestCase):
    def result(self):return core.inventory(*fixture())

    def test_calendar_counts_and_empty_months(self):
        r=self.result();self.assertEqual(sum(m['raw_valid_approval_orders'] for m in r['months']),6)
        self.assertEqual([m['approval_month'] for m in r['months']],['2018-04','2018-05','2018-06','2018-07','2018-08','2018-09'])
        self.assertEqual(r['months'][3]['raw_valid_approval_orders'],0)

    def test_exact_original_C_boundary_is_not_mature(self):
        may=self.result()['months'][1]
        self.assertEqual(may['H60_at_original_C']['mature_clock_orders'],1)
        self.assertEqual(may['H60_at_original_C']['immature_clock_orders'],1)
        self.assertFalse(may['H60_at_original_C']['original_C_suffices_for_whole_calendar'])

    def test_whole_month_bound_not_observed_last_order_bound(self):
        may=self.result()['months'][1]
        self.assertEqual(may['calendar_sufficient_observation_cutoff_planning_bound'],'2018-07-31 00:00:00')
        self.assertEqual(self.result()['months'][2]['calendar_sufficient_observation_cutoff_planning_bound'],'2018-08-30 00:00:00')

    def test_late_timestamp_never_proves_observation_or_changes_cutoff(self):
        r=self.result();may=r['months'][1]
        self.assertTrue(may['review_timestamp_max_reaches_planning_bound'])
        self.assertEqual(may['status'],'pending_data');self.assertFalse(may['new_validation_authorized_now'])
        self.assertEqual(r['original_C_unchanged'],'2018-07-01 00:00:00')
        self.assertEqual(r['accepted_new_validation_windows'],0)

    def test_existing_scope_cannot_be_rebranded_as_holdout(self):
        april=self.result()['months'][0]
        self.assertEqual(april['status'],'historical_development_only')
        self.assertEqual(april['historical_usage']['stage5_global_H60_label_bundle_orders'],2)
        self.assertTrue(april['historical_usage']['outer_development_query_month'])
        self.assertFalse(april['pristine_unseen_claim'])

    def test_no_stage5_selection_does_not_mean_no_prior_exposure(self):
        may=self.result()['months'][1];u=may['historical_usage']
        self.assertFalse(u['inner_C_selection_query_month']);self.assertFalse(u['outer_development_query_month'])
        self.assertTrue(u['stage3_source_wide_review_aggregation'])
        self.assertTrue(u['stage4_distinct_target_test_month']);self.assertFalse(may['pristine_unseen_claim'])

    def test_later_window_has_no_existing_labels_or_classes(self):
        for row in self.result()['months'][1:]:
            self.assertEqual(row['historical_usage']['stage5_global_H60_label_bundle_orders'],0)
            self.assertIsNone(row['new_class_support'])
            self.assertEqual(row['label_support'],'keys_and_timestamps_only_no_accepted_targets')

    def test_raw_review_score_column_rejected(self):
        o,r,m,u=fixture();r['review_score']=[1,5]
        with self.assertRaises(ValueError):core.inventory(o,r,m,u)

    def test_even_historical_y_column_rejected(self):
        o,r,m,u=fixture();m['y']=[1,None]
        with self.assertRaises(ValueError):core.inventory(o,r,m,u)

    def test_missing_approval_not_replaced_with_purchase(self):
        o,r,m,u=fixture();o.loc[5,'order_approved_at']=None
        result=core.inventory(o,r,m,u)
        self.assertEqual(result['unlocatable_or_invalid_order_rows'],1)
        self.assertEqual(result['valid_purchase_approval_rows'],5)

    def test_historical_membership_clock_mismatch_rejected(self):
        o,r,m,u=fixture();m.loc[0,'prediction_time']+=pd.Timedelta(seconds=1)
        with self.assertRaises(ValueError):core.inventory(o,r,m,u)

    def test_later_rows_in_historical_membership_rejected(self):
        o,r,m,u=fixture();m.loc[0,['order_id','prediction_time']]=['o2',pd.Timestamp('2018-05-01')]
        with self.assertRaises(ValueError):core.inventory(o,r,m,u)

    def test_usage_counts_deduplicate_repeated_roles(self):
        o,r,m,u=fixture();m=m.iloc[[0,0]].copy();m['role']=['inner_train_pool','outer_train_pool']
        row=core.inventory(o,r,m,u)['months'][0]
        self.assertEqual(row['historical_usage']['stage5_fit_roster_orders'],1)
        self.assertEqual(row['historical_usage']['stage5_fit_eligible_orders'],1)

    def test_unknown_answer_metadata_is_not_a_negative_label(self):
        o,r,m,u=fixture();r['review_answer_timestamp']=None
        result=core.inventory(o,r,m,u)
        self.assertFalse(result['months'][1]['review_timestamp_max_reaches_planning_bound'])
        self.assertIsNone(result['months'][1]['new_class_support'])
        self.assertEqual(result['months'][1]['parseable_answer_metadata_orders'],0)

    def test_duplicate_raw_ID_stops(self):
        o,r,m,u=fixture();o.loc[1,'order_id']='o0'
        with self.assertRaises(ValueError):core.inventory(o,r,m,u)

    def test_protocol_freezes_nonselection_purpose(self):
        p=core.inventory_protocol();json.dumps(p,allow_nan=False)
        self.assertFalse(p['review_score_values_read']);self.assertFalse(p['new_targets_materialized'])
        self.assertIn('calibration',p['no_later_labels_for'])
        self.assertFalse(p['pristine_unseen_holdout_claim'])


if __name__=='__main__':unittest.main()
