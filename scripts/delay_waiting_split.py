"""Development-only waiting-window splits and raw approval-cohort audits.

Both model fitting and threshold validation leave an explicit waiting period
after their prediction cohorts. Waiting improves label maturity by using older
orders; it does not make excluded or undelivered orders into negative labels.
"""
from __future__ import annotations

from numbers import Integral

import pandas as pd

from scripts.compare_delay_models import FIXED_TEST_START
from scripts.train_delay_model import METADATA_COLUMNS


def _midnight(value):
    boundary = pd.Timestamp(value)
    if (pd.isna(boundary) or boundary.tzinfo is not None
            or boundary != boundary.normalize()):
        raise ValueError('Boundaries must be timezone-naive dates at midnight')
    return boundary


def _validated_frame(frame):
    missing = set(METADATA_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f'Missing metadata columns: {sorted(missing)}')
    result = frame.copy()
    for name in ('order_purchase_timestamp', 'prediction_time', 'label_available_time'):
        result[name] = pd.to_datetime(result[name], errors='raise')
        if result[name].isna().any() or result[name].dt.tz is not None:
            raise ValueError(f'{name} must contain non-null timezone-naive timestamps')
    if result['order_id'].isna().any() or result['order_id'].duplicated().any():
        raise ValueError('Expected one row per non-null order_id')
    if not result['delayed'].isin([0, 1]).all():
        raise ValueError('delayed must contain only binary classes 0 and 1')
    if (result['label_available_time'] < result['prediction_time']).any():
        raise ValueError('Delivery labels cannot be available before prediction time')
    result['delayed'] = result['delayed'].astype(int)
    # Reset before masks/purges: external duplicate indices are not row identity.
    return result.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)


def _cohort_masks(prediction_time, train_end, val_start, val_end, eval_start, eval_end):
    return {
        'train': prediction_time < train_end,
        'validation': (prediction_time >= val_start) & (prediction_time < val_end),
        'evaluation': (prediction_time >= eval_start) & (prediction_time < eval_end),
    }


def split_waiting_fold(
    frame: pd.DataFrame, evaluation_start, evaluation_end, *, wait_days=60, validation_days=30,
):
    """Split approval cohorts with waits before fitting and before evaluation.

    For evaluation start E, validation is [E-wait-validation_days, E-wait).
    Training approvals end another wait before validation starts. Training
    outcomes must be known strictly before validation starts; validation
    outcomes strictly before E. Evaluation labels are retrospective, never
    supplied to fitting or threshold selection by this function.

    Zero wait is supported for controlled tests; experiments compare 30/60 days.
    Evaluation approval dates cannot cross the existing fixed-test boundary.
    """
    for name, value, minimum in (('wait_days', wait_days, 0), ('validation_days', validation_days, 1)):
        if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    wait_days, validation_days = int(wait_days), int(validation_days)
    eval_start, eval_end = map(_midnight, (evaluation_start, evaluation_end))
    if not eval_start < eval_end:
        raise ValueError('Require evaluation_start < evaluation_end')
    if eval_end > FIXED_TEST_START:
        raise ValueError('Backtest evaluation must end by the original fixed test start (2018-05-26)')
    val_end = eval_start - pd.Timedelta(days=wait_days)
    val_start = val_end - pd.Timedelta(days=validation_days)
    train_end = val_start - pd.Timedelta(days=wait_days)
    frame = _validated_frame(frame)
    prediction_time = frame['prediction_time']
    masks = _cohort_masks(prediction_time, train_end, val_start, val_end, eval_start, eval_end)
    cutoffs = {'train': val_start, 'validation': eval_start, 'evaluation': None}
    report = {
        'method': 'dual_wait_approval_cohorts',
        'wait_days': wait_days, 'validation_days': validation_days,
        'train_prediction_end': train_end.isoformat(), 'model_fit_time': val_start.isoformat(),
        'validation_start': val_start.isoformat(), 'validation_end': val_end.isoformat(),
        'evaluation_start': eval_start.isoformat(), 'evaluation_end': eval_end.isoformat(),
        'fixed_test_start': FIXED_TEST_START.isoformat(),
        'maturity_scope': (
            'Maturity exclusions are within the existing valid delivered cohort only; '
            'they are not coverage estimates for all approved orders.'
        ),
        'recency_tradeoff': (
            'Larger waits move both train and validation approval cohorts earlier; '
            'this changes recency and training size as well as label maturity.'
        ),
        'evaluation_role': 'retrospective development backtest; never model or threshold selection',
        'partitions': {},
    }
    for name, start, end in (('train_wait', train_end, val_start),
                             ('validation_wait', val_end, eval_start)):
        report[name] = {
            'start': start.isoformat(), 'end': end.isoformat(), 'days': wait_days,
            'prediction_rows_not_assigned': int(((prediction_time >= start) & (prediction_time < end)).sum()),
        }
    splits = {}
    for name, mask in masks.items():
        before = frame.loc[mask]
        cutoff = cutoffs[name]
        known = pd.Series(True, index=before.index) if cutoff is None else before['label_available_time'] < cutoff
        retained, removed = before.loc[known], before.loc[~known]
        if retained.empty or retained['delayed'].nunique() != 2:
            raise ValueError(f'{name} must contain both binary classes 0 and 1 after maturity purge')
        splits[name] = retained.copy()
        positive_before = int(before['delayed'].sum())
        positive_retained = int(retained['delayed'].sum())
        negative_before = len(before) - positive_before
        negative_retained = len(retained) - positive_retained
        partition = {
            'rows_before_purge': len(before),
            'positive_rows_before_purge': positive_before,
            'negative_rows_before_purge': negative_before,
            'positive_rate_before_purge': float(before['delayed'].mean()),
            'purged_rows': len(removed),
            'purged_positive_rows': int(removed['delayed'].sum()),
            'purged_negative_rows': int((removed['delayed'] == 0).sum()),
            'purged_positive_rate': float(removed['delayed'].mean()) if len(removed) else None,
            'rows': len(retained), 'positive_rows': positive_retained,
            'negative_rows': negative_retained,
            'positive_rate': float(retained['delayed'].mean()),
            'positive_retention_rate': positive_retained / positive_before,
            'negative_retention_rate': negative_retained / negative_before,
            'eligible_completed_maturity_exclusion_rate': len(removed) / len(before),
            'prediction_time_min': retained['prediction_time'].min().isoformat(),
            'prediction_time_max': retained['prediction_time'].max().isoformat(),
            'label_available_time_max': retained['label_available_time'].max().isoformat(),
            'label_maturity_cutoff': cutoff.isoformat() if cutoff is not None else None,
        }
        if name == 'evaluation':
            partition['labels_not_yet_available_at_evaluation_end'] = int(
                (retained['label_available_time'] >= eval_end).sum()
            )
            partition['late_known_at_original_holdout_count'] = int(
                (retained['label_available_time'] >= FIXED_TEST_START).sum()
            )
        report['partitions'][name] = partition
    return splits, report


def approval_cohort_audit(orders: pd.DataFrame, frame: pd.DataFrame, report: dict):
    """Count raw approvals and eligible completed labels without inventing outcomes.

    ``orders`` is the raw orders table, including cancelled/unfinished orders.
    ``frame`` is the full existing eligible delivered modeling cohort, before
    maturity purges. Evaluation has no label cutoff: its known-label count is
    None, rather than implying retrospective outcomes were already available.
    No extraction/snapshot date or on-time outcome for excluded rows is assumed.
    """
    required = {'order_id', 'order_approved_at', 'order_status'}
    missing = required.difference(orders.columns)
    if missing:
        raise ValueError(f'Missing raw orders columns: {sorted(missing)}')
    raw = orders[list(required)].copy()
    if raw['order_id'].isna().any() or raw['order_id'].duplicated().any():
        raise ValueError('Raw orders must have one row per non-null order_id')
    raw['order_approved_at'] = pd.to_datetime(raw['order_approved_at'], errors='raise')
    if raw['order_approved_at'].dt.tz is not None:
        raise ValueError('order_approved_at must contain timezone-naive timestamps')
    eligible = _validated_frame(frame)
    approval_by_id = raw.set_index('order_id')['order_approved_at']
    raw_times = eligible['order_id'].map(approval_by_id)
    if raw_times.isna().any() or not raw_times.eq(eligible['prediction_time']).all():
        raise ValueError('Eligible frame orders must match raw non-null approval timestamps')
    boundaries = [_midnight(report[name]) for name in (
        'train_prediction_end', 'validation_start', 'validation_end', 'evaluation_start', 'evaluation_end',
    )]
    raw_masks = _cohort_masks(raw['order_approved_at'], *boundaries)
    eligible_masks = _cohort_masks(eligible['prediction_time'], *boundaries)
    result = {
        'scope': (
            'Raw orders with non-null approval timestamps, using the same approval cohorts; '
            'status counts describe the supplied raw table, not status as of a historical cutoff. '
            'Cancelled, unknown and other excluded orders receive no inferred delivery label. '
            'No dataset snapshot date is assumed.'
        ),
        'raw_rows_without_approval': int(raw['order_approved_at'].isna().sum()),
        'partitions': {},
    }
    for name in raw_masks:
        raw_part = raw.loc[raw_masks[name]]
        eligible_part = eligible.loc[eligible_masks[name]]
        cutoff_text = report['partitions'][name]['label_maturity_cutoff']
        cutoff = _midnight(cutoff_text) if cutoff_text is not None else None
        known = int((eligible_part['label_available_time'] < cutoff).sum()) if cutoff is not None else None
        statuses = raw_part['order_status'].fillna('<missing>').astype(str).value_counts().sort_index()
        result['partitions'][name] = {
            'raw_approved_rows': len(raw_part),
            'status_counts': {status: int(count) for status, count in statuses.items()},
            'eligible_completed_rows': len(eligible_part),
            'known_eligible_labels_at_cutoff': known,
            'label_maturity_cutoff': cutoff_text,
            'not_in_eligible_cohort_rows': int((~raw_part['order_id'].isin(eligible_part['order_id'])).sum()),
        }
    return result
