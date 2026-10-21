"""Calendar/usage inventory using IDs and event clocks, never review scores."""
from __future__ import annotations

import numpy as np
import pandas as pd

ORDER_COLUMNS=('order_id','order_purchase_timestamp','order_approved_at')
REVIEW_COLUMNS=('review_id','order_id','review_creation_date','review_answer_timestamp')
MEMBER_COLUMNS=('outer_fold','role','order_id','prediction_time','role_label_usable')


def inventory_protocol():
    return {
        'unit':'complete_calendar_approval_month_metadata_only',
        'cohort_clock_policy':'parseable_purchase_approval_and_approval_not_before_purchase_no_status_filter',
        'months':'every_month_between_valid_approval_min_and_max_including_empty_months',
        'existing_cohort_end_exclusive':'2018-05-01',
        'existing_H60_observation_cutoff_exclusive':'2018-07-01',
        'horizon_elapsed_days':60,
        'maturity':'approval_plus_60_days_strictly_before_observation_cutoff',
        'whole_calendar_sufficient_cutoff':'next_month_start_plus_60_days; planning_bound_not_observation_evidence',
        'allowed_review_columns':list(REVIEW_COLUMNS),
        'review_score_values_read':False,'new_targets_materialized':False,
        'new_low_rate_or_class_support_computed':False,
        'usage_dimensions':['stage5_fit_roster','stage5_fit_eligible','stage5_inner_selection_query',
                            'stage5_outer_development_query','stage5_global_labels_and_diagnostics',
                            'stage3_source_wide_review_score_aggregation','stage4_cross_task_evaluation'],
        'unused_claim':'absence_of_Stage5_query_usage_is_not_proof_of_unseen_labels_or_external_nonuse',
        'event_maximum':'timestamp_extent_only_never_an_ingestion_watermark_or_label_cutoff',
        'later_window_status':'pending_data_even_if_event_timestamps_reach_the_planning_bound',
        'old_scope_use':'development_only_never_relabelled_as_new_holdout',
        'later_scope_use':'quarantined_future_retrospective_temporal_validation_after_separate_dataset_and_protocol_acceptance',
        'pristine_unseen_holdout_claim':False,
        'no_later_labels_for':['model_selection','feature_selection','calibration','threshold_tuning','window_choice'],
        'no_training_prediction_performance_or_dashboard':True,
        'Stage4':'pending_data_daily_10_percent_seeds_11_29_42_73_101_unchanged',
    }


def _clock(values):
    return pd.to_datetime(values,format='%Y-%m-%d %H:%M:%S',errors='coerce')


def _stamp(value):
    return str(value) if pd.notna(value) else None


def inventory(orders,reviews,membership,usage):
    if tuple(orders.columns)!=ORDER_COLUMNS or tuple(reviews.columns)!=REVIEW_COLUMNS:
        raise ValueError('Inventory permits only exact ID/clock columns, never review_score')
    if tuple(membership.columns)!=MEMBER_COLUMNS:
        raise ValueError('Only historical role membership flags, never y, are permitted')
    if (orders.order_id.isna().any() or orders.order_id.eq('').any() or orders.order_id.duplicated().any()
            or not membership.role_label_usable.map(lambda x:isinstance(x,(bool,np.bool_))).all()):
        raise ValueError('Raw IDs and historical usability must be valid')
    purchase,approval=(_clock(orders[c]) for c in ORDER_COLUMNS[1:])
    valid=purchase.notna()&approval.notna()&approval.ge(purchase)
    cohort=pd.DataFrame({'order_id':orders.loc[valid,'order_id'],'approval':approval.loc[valid]})
    cohort=cohort.sort_values(['approval','order_id']).reset_index(drop=True)
    if cohort.empty:raise ValueError('No time-locatable approval cohort')
    fit=membership.loc[membership.role.isin(['inner_train_pool','outer_train_pool'])]
    fit_ids=set(fit.order_id);eligible_ids=set(fit.loc[fit.role_label_usable,'order_id'])
    inner_ids=set(membership.loc[membership.role.eq('inner_validation'),'order_id'])
    outer_ids=set(membership.loc[membership.role.eq('outer_evaluation'),'order_id'])
    indexed=cohort.set_index('order_id')
    if not set(membership.order_id).issubset(indexed.index):
        raise ValueError('Historical membership is not contained in the raw valid roster')
    member_clock=pd.to_datetime(membership.prediction_time,errors='coerce')
    expected=membership.order_id.map(indexed.approval)
    if not np.array_equal(member_clock.to_numpy(),expected.to_numpy()):
        raise ValueError('Historical role approval clocks differ from raw source')
    end=pd.Timestamp('2018-05-01');C=pd.Timestamp('2018-07-01')
    if not set(membership.order_id).issubset(set(cohort.loc[cohort.approval.lt(end),'order_id'])):
        raise ValueError('Historical roles unexpectedly contain later orders')
    answer=_clock(reviews.review_answer_timestamp);creation=_clock(reviews.review_creation_date)
    review_ids=set(reviews.order_id.dropna())
    answer_ids=set(reviews.loc[answer.notna(),'order_id'].dropna())
    months=[]
    for month in pd.period_range(cohort.approval.min().to_period('M'),cohort.approval.max().to_period('M'),freq='M'):
        start=month.start_time;stop=(month+1).start_time
        block=cohort.loc[cohort.approval.ge(start)&cohort.approval.lt(stop)]
        ids=set(block.order_id);existing=stop<=end
        mincut=stop+pd.Timedelta(days=60)
        n=len(block);mature=int((block.approval+pd.Timedelta(days=60)).lt(C).sum())
        known_usage={'stage5_fit_roster_orders':len(ids&fit_ids),'stage5_fit_eligible_orders':len(ids&eligible_ids),
            'stage5_inner_query_orders':len(ids&inner_ids),'stage5_outer_query_orders':len(ids&outer_ids),
            'stage5_global_H60_label_bundle_orders':n if existing else 0,
            'inner_C_selection_query_month':str(month) in usage['stage5_inner_months'],
            'outer_development_query_month':str(month) in usage['stage5_outer_months'],
            'stage3_source_wide_review_aggregation':True,
            'stage4_distinct_target_test_month':str(month) in usage['stage4_test_months']}
        if not existing and any(known_usage[k] for k in ['stage5_fit_roster_orders','stage5_fit_eligible_orders','stage5_inner_query_orders','stage5_outer_query_orders']):
            raise ValueError('Later window already occurs in historical Stage5 roles')
        gaps=[] if existing else ['outside_existing_approval_cohort','whole_month_not_mature_at_original_C',
            'no_accepted_new_observation_cutoff_or_completion_watermark','no_new_H60_label_bundle_or_role_version',
            'original_ingestion_and_review_revision_versions_unverified','unseen_exposure_cannot_be_proven']
        months.append({'approval_month':str(month),'start_inclusive':str(start),'end_exclusive':str(stop),
            'raw_valid_approval_orders':n,'historical_usage':known_usage,
            'H60_at_original_C':{'mature_clock_orders':mature,'immature_clock_orders':n-mature,
                                'original_C_suffices_for_whole_calendar':bool(mincut<=C)},
            'calendar_sufficient_observation_cutoff_planning_bound':str(mincut),
            'linked_review_metadata_orders':len(ids&review_ids),'parseable_answer_metadata_orders':len(ids&answer_ids),
            'review_timestamp_max_reaches_planning_bound':bool(answer.max()>=mincut) if answer.notna().any() else False,
            'label_support':'existing_H60_bundle_only' if existing else 'keys_and_timestamps_only_no_accepted_targets',
            'new_class_support':None,'pristine_unseen_claim':False,
            'status':'historical_development_only' if existing else 'pending_data',
            'reserved_use':'existing_development' if existing else 'future_retrospective_temporal_validation_pending_acceptance',
            'new_validation_authorized_now':False,'gaps':gaps})
    if sum(m['raw_valid_approval_orders'] for m in months)!=len(cohort):
        raise ValueError('Calendar census lost orders')
    return {'raw_order_rows':len(orders),'valid_purchase_approval_rows':len(cohort),
        'unlocatable_or_invalid_order_rows':int((~valid).sum()),
        'valid_approval_minimum':_stamp(cohort.approval.min()),'valid_approval_maximum':_stamp(cohort.approval.max()),
        'raw_review_metadata_rows':len(reviews),'review_answer_clock_minimum':_stamp(answer.min()),
        'review_answer_clock_maximum':_stamp(answer.max()),'review_creation_clock_maximum':_stamp(creation.max()),
        'unparseable_or_missing_answer_clock_rows':int(answer.isna().sum()),
        'original_C_unchanged':str(C),'months':months,
        'later_windows':sum(m['status']=='pending_data' for m in months),
        'accepted_new_validation_windows':0,'fresh_unseen_holdout_windows':0,
        'model_fits':0,'score_values_read':False,'new_targets_created':False}
