"""H60 role-only mature-prior and temporal-coverage descriptions; no models."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts import review_score_diagnostics as labels

RECENT_DAYS = (90, 180)
AGE_EDGES = (0, 30, 60, 90, 180, float('inf'))


def audit_protocol():
    return {
        'horizon_elapsed_days': 60,
        'training_roles': ['inner_train_pool', 'outer_train_pool'],
        'query_roles': ['inner_validation', 'outer_evaluation'],
        'fit_contexts': 6, 'distinct_calendar_fit_times': 5,
        'training_availability': 'own_role_cutoff_equals_fit; deadline_strictly_before_fit; first_answer_strictly_before_fit',
        'prior': 'known_low_1_2_divided_by_own_eligible_known_labels_unsmoothed_null_if_no_known',
        'coverage_partition': ['known_mature', 'mature_unknown', 'immature_unknown'],
        'state_maturity_crosstab': 'all_nine_label_states_cross_mature_immature; quality_states_can_override_immature_state',
        'recent_mature_approval_windows_days': list(RECENT_DAYS),
        'recent_mature_window': '[fit_minus_60_days_minus_W,fit_minus_60_days); approval_clock; eligible_labels_only',
        'approval_age_bins_days': [0,30,60,90,180,'positive_infinity'],
        'age_bin_closure': 'left_closed_right_open; age_equals_60_is_still_immature_at_exclusive_fit',
        'calendar_bins': 'approval_month_from_first_history_month_through_month_before_fit_including_empty_months',
        'query_comparison': 'separate_retrospective_role_truth; signed_query_known_rate_minus_each_fixed_prior',
        'query_at_fit': 'all_query_approvals_at_or_after_fit; zero_query_labels_used_for_prior',
        'window_selection': False, 'closest_prior_selection': False,
        'shared_history_transition': 'inner_train_to_outer_train_same_ID_only; known_labels_must_not_change; later_labels_never_joined_back',
        'global_cutoff_labels_substituted_for_fit': False,
        'unknown_labels_filled': False, 'parameter_updates': False,
        'score_files': 'integrity_hash_only_no_score_values_read',
        'feature_builds': 0, 'fit_transform_predict_calls': 0,
        'performance_metrics': 0, 'calibration': False, 'dashboard': False,
        'empty_rate': None, 'scope': 'already_inspected_development_role_metadata_not_operational_ingestion_proof',
    }


def _ratio(a, b):
    return float(a/b) if b else None


def validate_role(block, *, training):
    ids, masks, numeric = labels._labels(block)
    required = ['prediction_time','window_deadline','observation_cutoff','fit_at','horizon_complete']
    if not all(n in block for n in required):
        raise ValueError('Full role clocks and maturity required')
    for name in required[:-1]:
        if (not pd.api.types.is_datetime64_dtype(block[name].dtype)
                or block[name].isna().any() or block[name].dt.tz is not None):
            raise ValueError('Role clocks must be finite timezone-naive datetimes')
    if block.fit_at.nunique()!=1 or block.observation_cutoff.nunique()!=1:
        raise ValueError('Each role requires one fit and own cutoff')
    if not block.horizon_complete.map(lambda x:isinstance(x,(bool,np.bool_))).all():
        raise ValueError('Maturity must be boolean')
    if not block.window_deadline.eq(block.prediction_time+pd.Timedelta(days=60)).all():
        raise ValueError('H60 deadline differs')
    mature=block.window_deadline.lt(block.observation_cutoff).to_numpy()
    if not np.array_equal(mature,block.horizon_complete.to_numpy()):
        raise ValueError('Maturity differs from exclusive own cutoff')
    if np.any(masks['known'] & ~mature):
        raise ValueError('Immature labels must remain unknown')
    answer=block.first_visible_answer_at
    if (not pd.api.types.is_datetime64_dtype(answer.dtype)
            or (answer.notna() & ~answer.lt(block.observation_cutoff)).any()):
        raise ValueError('Visible answer metadata at or after cutoff')
    known_clock=(answer.gt(block.prediction_time)&answer.le(block.window_deadline)).to_numpy()
    if np.any(masks['known'] & ~known_clock):
        raise ValueError('Known answer outside H60 interval')
    if training:
        if not block.observation_cutoff.eq(block.fit_at).all() or not block.prediction_time.lt(block.fit_at).all():
            raise ValueError('Training role must contain only history at its own fit')
    elif (not block.prediction_time.ge(block.fit_at).all()
          or not block.observation_cutoff.gt(block.fit_at).all()):
        raise ValueError('Query truth is retrospective and must not enter the prior')
    return ids,masks,numeric,mature


def coverage(block, *, training):
    _, masks, _, mature=validate_role(block,training=training)
    n=len(block);known=int(masks['known'].sum());low=int(masks['low'].sum())
    mature_unknown=mature & ~masks['known'];immature=~mature
    return {
        'full_orders': n, 'known_mature':known,
        'mature_unknown':int(mature_unknown.sum()),'immature_unknown':int(immature.sum()),
        'unknown_total':int(masks['unknown'].sum()),
        'mature_total':int(mature.sum()), 'known_low_1_2':low,'known_other_3_5':known-low,
        'known_low_rate':_ratio(low,known),'known_coverage_of_full':_ratio(known,n),
        'mature_unknown_coverage_of_full':_ratio(int(mature_unknown.sum()),n),
        'immature_coverage_of_full':_ratio(int(immature.sum()),n),
        'known_coverage_of_mature':_ratio(known,int(mature.sum())),
        'state_maturity':{state:{'mature':int((block.label_state.eq(state).to_numpy() & mature).sum()),
                                  'immature':int((block.label_state.eq(state).to_numpy() & immature).sum())}
                          for state in labels.STATES},
    }


def training_prior(block):
    """Only own-fit historical truth can enter this function; no query argument."""
    ids, _, _, _=validate_role(block,training=True)
    fit=block.fit_at.iloc[0]
    result={'fit_at':str(fit),'full_history':coverage(block,training=True),
            'recent_mature_windows':[], 'approval_age_bins':[], 'approval_months':[]}
    end=fit-pd.Timedelta(days=60)
    for days in RECENT_DAYS:
        start=end-pd.Timedelta(days=days)
        local=block.loc[block.prediction_time.ge(start)&block.prediction_time.lt(end)]
        result['recent_mature_windows'].append({'days':days,'start_inclusive':str(start),
            'end_exclusive':str(end),'coverage':coverage(local,training=True) if len(local) else empty_coverage()})
    age=(fit-block.prediction_time).dt.total_seconds()/86400
    for lo,hi in zip(AGE_EDGES[:-1],AGE_EDGES[1:]):
        local=block.loc[age.ge(lo)&age.lt(hi)]
        result['approval_age_bins'].append({'lower_inclusive_days':lo,
            'upper_exclusive_days':hi if np.isfinite(hi) else None,
            'coverage':coverage(local,training=True) if len(local) else empty_coverage()})
    first=block.prediction_time.min().to_period('M');last=fit.to_period('M')-1
    for month in pd.period_range(first,last,freq='M'):
        local=block.loc[block.prediction_time.dt.to_period('M').eq(month)]
        result['approval_months'].append({'approval_month':str(month),
            'coverage':coverage(local,training=True) if len(local) else empty_coverage()})
    for partition in ('approval_age_bins','approval_months'):
        for key in ('full_orders','known_mature','mature_unknown','immature_unknown','known_low_1_2','known_other_3_5'):
            if sum(v['coverage'][key] for v in result[partition])!=result['full_history'][key]:
                raise ValueError('History partition does not reconstruct full support')
    return result


def empty_coverage():
    return {'full_orders':0,'known_mature':0,'mature_unknown':0,'immature_unknown':0,
            'unknown_total':0,'mature_total':0,'known_low_1_2':0,'known_other_3_5':0,
            'known_low_rate':None,'known_coverage_of_full':None,
            'mature_unknown_coverage_of_full':None,'immature_coverage_of_full':None,
            'known_coverage_of_mature':None,
            'state_maturity':{s:{'mature':0,'immature':0} for s in labels.STATES}}


def compare_retrospective_query(prior, query):
    support=coverage(query,training=False)
    if str(query.fit_at.iloc[0])!=prior['fit_at']:
        raise ValueError('Query and prior must share the same fit')
    rate=support['known_low_rate']
    references=[('expanding',prior['full_history'])]+[(f"mature_recent_{v['days']}_days",v['coverage']) for v in prior['recent_mature_windows']]
    return {'retrospective_observation_cutoff':str(query.observation_cutoff.iloc[0]),
            'coverage':support,'query_labels_used_in_prior':0,
            'query_approvals_at_or_after_fit':len(query),'available_query_labels_at_fit':0,
            'diagnostic_deltas':[{'reference':name,'frozen_history_known_rate':c['known_low_rate'],
                'query_known_rate_minus_history_rate':rate-c['known_low_rate']
                 if rate is not None and c['known_low_rate'] is not None else None}
                 for name,c in references],
            'parameters_modified':False,'window_selected':False}


def shared_history_transition(earlier,later):
    validate_role(earlier,training=True);validate_role(later,training=True)
    if earlier.fit_at.iloc[0]>=later.fit_at.iloc[0]:
        raise ValueError('Shared-history transition requires increasing fits')
    later=later.set_index('order_id')
    if not set(earlier.order_id).issubset(later.index):
        raise ValueError('Earlier full history must remain in later history')
    new=later.loc[earlier.order_id].reset_index();old=earlier.reset_index(drop=True)
    old_known=old.role_label_usable.to_numpy();new_known=new.role_label_usable.to_numpy()
    if (np.any(old_known & ~new_known)
            or not old.loc[old_known,'y'].reset_index(drop=True).equals(new.loc[old_known,'y'].reset_index(drop=True))):
        raise ValueError('Previously mature known labels changed')
    return {'shared_orders':len(old),'earlier_known':int(old_known.sum()),
            'later_known_among_shared':int(new_known.sum()),
            'unknown_to_known':int((~old_known & new_known).sum()),
            'unknown_to_still_unknown':int((~old_known & ~new_known).sum()),
            'earlier_immature_to_later_known':int((~old.horizon_complete.to_numpy() & new_known).sum()),
            'earlier_known_values_changed':0,'later_labels_backfilled_into_earlier_fit':False}
