"""Calendar-month validation with mature labels and a shared recall floor.

All threshold inputs are validation observations. Evaluation labels are used
only in the retrospective split and never enter the threshold policy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.compare_delay_models import FIXED_TEST_START
from scripts.delay_alert_policy import _numeric_vector, choose_recall_threshold
from scripts.delay_waiting_split import _midnight, _validated_frame


WAIT_DAYS = 60
VALIDATION_MONTHS = 3


def _partition_report(before, retained, cutoff):
    """Summarize maturity within the eligible completed modeling cohort."""
    positive_before = int(before.delayed.sum())
    negative_before = len(before) - positive_before
    positive_retained = int(retained.delayed.sum())
    negative_retained = len(retained) - positive_retained
    purged_positive = positive_before - positive_retained
    purged_negative = negative_before - negative_retained
    purged_rows = len(before) - len(retained)
    return {
        'rows_before_purge': len(before),
        'positive_rows_before_purge': positive_before,
        'negative_rows_before_purge': negative_before,
        'positive_rate_before_purge': positive_before / len(before),
        'purged_rows': purged_rows,
        'purged_positive_rows': purged_positive,
        'purged_negative_rows': purged_negative,
        'purged_positive_rate': purged_positive / purged_rows if purged_rows else None,
        'rows': len(retained),
        'positive_rows': positive_retained,
        'negative_rows': negative_retained,
        'positive_rate': positive_retained / len(retained),
        'positive_retention_rate': positive_retained / positive_before,
        'negative_retention_rate': negative_retained / negative_before,
        'eligible_completed_maturity_exclusion_rate': purged_rows / len(before),
        'prediction_time_min': retained.prediction_time.min().isoformat(),
        'prediction_time_max': retained.prediction_time.max().isoformat(),
        'label_available_time_max': retained.label_available_time.max().isoformat(),
        'label_maturity_cutoff': cutoff.isoformat() if cutoff is not None else None,
    }


def _require_both_classes(frame, name):
    if frame.empty or frame.delayed.nunique() != 2:
        raise ValueError(f'{name} must contain both binary classes 0 and 1 after maturity purge')


def split_multimonth_fold(frame: pd.DataFrame, evaluation_start, evaluation_end):
    """Use three full calendar months, with at least 60 days for labels.

    For evaluation start E, validation_end is the first day of the calendar
    month containing E - 60 days, and validation_start is three months earlier.
    Training approvals precede validation_start - 60 days. Training labels
    must be known strictly before validation_start, and validation labels must
    be known strictly before E. Each retained validation month needs both
    classes. Evaluation is retrospective and cannot cross FIXED_TEST_START.

    The common boundary/partition report schema is compatible with
    delay_waiting_split.approval_cohort_audit without an adapter.
    """
    eval_start, eval_end = map(_midnight, (evaluation_start, evaluation_end))
    if not eval_start < eval_end:
        raise ValueError('Require evaluation_start < evaluation_end')
    if eval_end > FIXED_TEST_START:
        raise ValueError('Backtest evaluation must end by the original fixed test start (2018-05-26)')
    val_end = (eval_start - pd.Timedelta(days=WAIT_DAYS)).to_period('M').start_time
    val_start = val_end - pd.DateOffset(months=VALIDATION_MONTHS)
    train_end = val_start - pd.Timedelta(days=WAIT_DAYS)
    validated = _validated_frame(frame)
    times = validated.prediction_time
    masks = {
        'train': times < train_end,
        'validation': (times >= val_start) & (times < val_end),
        'evaluation': (times >= eval_start) & (times < eval_end),
    }
    cutoffs = {'train': val_start, 'validation': eval_start, 'evaluation': None}
    report = {
        'method': 'three_calendar_month_validation_with_60_day_wait',
        'wait_days': WAIT_DAYS,
        'validation_month_count': VALIDATION_MONTHS,
        'validation_days': int((val_end - val_start).days),
        'train_prediction_end': train_end.isoformat(),
        'model_fit_time': val_start.isoformat(),
        'threshold_selection_time': eval_start.isoformat(),
        'validation_start': val_start.isoformat(),
        'validation_end': val_end.isoformat(),
        'evaluation_start': eval_start.isoformat(),
        'evaluation_end': eval_end.isoformat(),
        'fixed_test_start': FIXED_TEST_START.isoformat(),
        'calendar_alignment': 'validation_end = floor_month(evaluation_start - 60 days)',
        'maturity_scope': (
            'Maturity exclusions are within the existing valid delivered cohort only; '
            'they are not coverage estimates for all approved orders.'
        ),
        'recency_tradeoff': (
            'Three full validation months move the training cutoff earlier than a '
            'single-month validation, changing training size and recency.'
        ),
        'evaluation_role': 'retrospective development backtest; never model or threshold selection',
        'partitions': {},
        'validation_months': [],
    }
    for name, start, end in (('train_wait', train_end, val_start),
                             ('validation_wait', val_end, eval_start)):
        report[name] = {
            'start': start.isoformat(),
            'end': end.isoformat(),
            'days': int((end - start).days),
            'minimum_days': WAIT_DAYS,
            'prediction_rows_not_assigned': int(((times >= start) & (times < end)).sum()),
        }
    splits = {}
    for name, mask in masks.items():
        before = validated.loc[mask]
        cutoff = cutoffs[name]
        retained = before if cutoff is None else before.loc[before.label_available_time < cutoff]
        _require_both_classes(retained, name)
        splits[name] = retained.copy()
        partition = _partition_report(before, retained, cutoff)
        if name == 'evaluation':
            partition['labels_not_yet_available_at_evaluation_end'] = int(
                (retained.label_available_time >= eval_end).sum())
            partition['late_known_at_original_holdout_count'] = int(
                (retained.label_available_time >= FIXED_TEST_START).sum())
        report['partitions'][name] = partition
    for start in pd.date_range(val_start, val_end, freq='MS', inclusive='left'):
        end = start + pd.DateOffset(months=1)
        before = validated.loc[(times >= start) & (times < end)]
        retained = before.loc[before.label_available_time < eval_start]
        _require_both_classes(retained, f'validation month {start:%Y-%m}')
        report['validation_months'].append({
            'month': f'{start:%Y-%m}', 'start': start.isoformat(), 'end': end.isoformat(),
            **_partition_report(before, retained, eval_start),
        })
    return splits, report


def _calendar_month_vector(months):
    """Accept explicit month strings, monthly Periods, or naive timestamps."""
    values = np.asarray(months)
    if values.ndim != 1 or values.size == 0:
        raise ValueError('months must be a nonempty one-dimensional calendar-month vector')
    # Casting datetime64[ns] directly to object yields integer nanoseconds;
    # preserve its datetime scalars while retaining mixed input types otherwise.
    if values.dtype.kind != 'M':
        values = np.asarray(months, dtype=object)
    normalized = []
    for value in values:
        try:
            if isinstance(value, pd.Period):
                if value.freqstr != 'M':
                    raise ValueError('Periods must use monthly frequency')
                stamp = value.start_time
            else:
                if isinstance(value, (bool, int, float, np.number)):
                    raise ValueError('Numeric values are not calendar months')
                stamp = pd.Timestamp(str(value) if isinstance(value, (str, np.str_)) else value)
            if pd.isna(stamp) or stamp.tzinfo is not None:
                raise ValueError('Calendar months must be non-null and timezone-naive')
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError('months must contain valid non-null timezone-naive calendar months') from exc
        normalized.append(f'{stamp:%Y-%m}')
    return np.asarray(normalized)


def _threshold_counts(labels, values, threshold):
    predicted = values >= threshold
    tp = int(((labels == 1) & predicted).sum())
    fp = int(((labels == 0) & predicted).sum())
    fn = int(((labels == 1) & ~predicted).sum())
    tn = int(((labels == 0) & ~predicted).sum())
    return {
        'rows': len(labels), 'positive_rows': tp + fn, 'negative_rows': tn + fp,
        'confusion_matrix': [[tn, fp], [fn, tp]],
        'true_positive_rows': tp, 'false_positive_rows': fp,
        'false_negative_rows': fn, 'true_negative_rows': tn,
        'predicted_positive_rows': tp + fp,
        'recall': tp / (tp + fn), 'achieved_recall': tp / (tp + fn),
        'alert_rate': (tp + fp) / len(labels),
        'precision': tp / (tp + fp),
    }


def choose_multimonth_threshold(y, scores, months, min_recall: float = .30) -> tuple[float, dict]:
    """Choose the highest shared threshold meeting recall in every month.

    Compute each month's highest feasible observed threshold, then take their
    minimum. This minimizes alert count within shared ``score >= threshold``
    rules while satisfying every validation month. Score ties are indivisible.
    A pooled recall target alone can hide a month with no delayed orders caught.
    Validation floors do not guarantee evaluation or future-month recall.
    """
    labels = _numeric_vector(y, 'y')
    values = _numeric_vector(scores, 'scores')
    calendar_months = _calendar_month_vector(months)
    if len(labels) != len(values) or len(labels) != len(calendar_months):
        raise ValueError('y, scores and months must have equal lengths')
    if isinstance(min_recall, (bool, np.bool_)):
        raise ValueError('min_recall must be a finite scalar in (0, 1]')
    # Reuse the validated public single-cohort policy, including score range,
    # binary labels, and scalar target checks. No evaluation inputs are accepted.
    _, pooled_policy = choose_recall_threshold(labels, values, min_recall)
    target = pooled_policy['min_recall']
    month_thresholds = {}
    for month in sorted(set(calendar_months)):
        mask = calendar_months == month
        try:
            threshold, _ = choose_recall_threshold(labels[mask], values[mask], target)
        except ValueError as exc:
            raise ValueError(f'validation month {month}: {exc}') from exc
        month_thresholds[month] = threshold
    threshold = min(month_thresholds.values())
    month_reports = []
    for month, highest_threshold in month_thresholds.items():
        mask = calendar_months == month
        month_reports.append({
            'month': month,
            'highest_feasible_threshold': highest_threshold,
            'selected_threshold': threshold,
            'min_recall': target,
            **_threshold_counts(labels[mask], values[mask], threshold),
        })
    pooled = _threshold_counts(labels, values, threshold)
    minimum_month_recall = min(item['recall'] for item in month_reports)
    policy = {
        'data': 'validation only',
        'method': 'highest_shared_threshold_with_monthly_recall_floor',
        'objective': 'minimize validation alerts subject to recall >= min_recall in every calendar month',
        'prediction_rule': 'delay_score >= threshold',
        'selected_threshold': threshold,
        'min_recall': target,
        'minimum_month_recall': minimum_month_recall,
        'all_months_meet_recall_floor': minimum_month_recall >= target,
        'limiting_months': [month for month, value in month_thresholds.items() if value == threshold],
        'month_count': len(month_reports),
        'months': month_reports,
        'pooled': pooled,
        'achieved_recall': pooled['recall'],
        'predicted_positive_rows': pooled['predicted_positive_rows'],
        'true_positive_rows': pooled['true_positive_rows'],
        'false_positive_rows': pooled['false_positive_rows'],
        'alert_rate': pooled['alert_rate'],
        'precision': pooled['precision'],
        'candidate_thresholds': int(np.unique(values).size),
        'tie_policy': 'minimum of monthly highest feasible thresholds; all equal scores receive the same prediction',
        'evaluation_recall_guarantee': False,
        'evaluation_note': 'Validation monthly recall floors do not guarantee evaluation or future-month recall',
    }
    return threshold, policy
