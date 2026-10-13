"""Monthly refits with historical out-of-time scores and mature validation labels.

The supplied frame is the existing valid-delivered modeling cohort. Scoring
never purges that cohort using future outcomes. Its coverage therefore remains
retrospective and does not represent every originally approved order.
"""
from __future__ import annotations

import hashlib

import pandas as pd

from scripts.compare_delay_models import FIXED_TEST_START
from scripts.delay_multimonth_validation import _partition_report, _require_both_classes
from scripts.delay_waiting_split import _midnight, _validated_frame


WAIT_DAYS = 60
VALIDATION_MONTHS = 3


def _month_start(value):
    boundary = _midnight(value)
    if boundary.day != 1:
        raise ValueError('Monthly refit boundaries must be the first day of a calendar month')
    return boundary


def _scoring_bounds(month_start, score_end):
    start = _month_start(month_start)
    next_month = start + pd.DateOffset(months=1)
    end = next_month if score_end is None else _midnight(score_end)
    if not start < end <= next_month:
        raise ValueError('Require month_start < score_end <= next calendar month start')
    if end > FIXED_TEST_START:
        raise ValueError('Development scoring must end by the original fixed test start (2018-05-26)')
    return start, end


def _order_fingerprint(frame):
    identities = '\n'.join(sorted(frame.order_id.astype(str)))
    return hashlib.sha256(identities.encode('utf-8')).hexdigest()


def split_rolling_month(frame: pd.DataFrame, month_start, score_end=None):
    """Refit at M using approvals before M-60 days and labels before M.

    Return ``{'train': mature_training, 'scoring': approval_month}``, report.
    Scoring includes every eligible completed-cohort order approved in [M,end),
    including orders whose delivery labels become available much later. It may
    contain one class; training must contain both. No performance or outcome
    maturity calculation is performed on the scoring partition here.
    """
    start, end = _scoring_bounds(month_start, score_end)
    train_end = start - pd.Timedelta(days=WAIT_DAYS)
    validated = _validated_frame(frame)
    times = validated.prediction_time
    before = validated.loc[times < train_end]
    train = before.loc[before.label_available_time < start].copy()
    _require_both_classes(train, 'train')
    scoring = validated.loc[(times >= start) & (times < end)].copy()
    if scoring.empty:
        raise ValueError('scoring must contain at least one eligible completed-cohort order')
    train_report = _partition_report(before, train, start)
    train_report['order_id_fingerprint'] = _order_fingerprint(train)
    scoring_report = {
        'rows': len(scoring),
        'prediction_time_min': scoring.prediction_time.min().isoformat(),
        'prediction_time_max': scoring.prediction_time.max().isoformat(),
        'order_id_fingerprint': _order_fingerprint(scoring),
        'label_maturity_cutoff': None,
        'label_maturity_filter_applied': False,
        'outcomes_used_for_selection': False,
    }
    report = {
        'method': 'monthly_refit_with_60_day_training_approval_wait',
        'month': f'{start:%Y-%m}',
        'wait_days': WAIT_DAYS,
        'model_fit_time': start.isoformat(),
        'train_prediction_end': train_end.isoformat(),
        'training_label_cutoff': start.isoformat(),
        'scoring_start': start.isoformat(),
        'scoring_end': end.isoformat(),
        'fixed_test_start': FIXED_TEST_START.isoformat(),
        'training_source_cutoff': (
            'Training approvals are strictly before model_fit_time minus 60 days; '
            'training delivery labels are strictly before model_fit_time. '
            'Each fitted model and preprocessing pipeline use only this training partition.'
        ),
        'scoring_source_cutoff': (
            'Scoring cohort uses only approval timestamps within the supplied valid-delivered cohort; '
            'it is not filtered by label availability. Prior event features must still use '
            'only completed events strictly before each individual approval.'
        ),
        'maturity_scope': (
            'Maturity exclusions are within the existing valid delivered cohort only; '
            'cancelled, unfinished and other excluded orders do not receive inferred negative labels.'
        ),
        'train_wait': {
            'start': train_end.isoformat(), 'end': start.isoformat(), 'days': WAIT_DAYS,
            'prediction_rows_not_assigned': int(((times >= train_end) & (times < start)).sum()),
        },
        'partitions': {'train': train_report, 'scoring': scoring_report},
    }
    return {'train': train, 'scoring': scoring}, report


def rolling_validation_schedule(evaluation_start, evaluation_end):
    """Prespecify three full historical scoring months for a monthly refit.

    Validation ends at floor_month(E-60 days), starts three calendar months
    earlier, and uses delivery labels known strictly before E. Each validation
    month's scores must come from its own model fitted at that month's start.
    The evaluation model instead refits at E, without using evaluation labels.
    """
    start, end = _scoring_bounds(evaluation_start, evaluation_end)
    val_end = (start - pd.Timedelta(days=WAIT_DAYS)).to_period('M').start_time
    val_start = val_end - pd.DateOffset(months=VALIDATION_MONTHS)
    months = [{
        'month': f'{month:%Y-%m}', 'start': month.isoformat(),
        'end': (month + pd.DateOffset(months=1)).isoformat(),
        'model_fit_time': month.isoformat(),
        'label_maturity_cutoff': start.isoformat(),
    } for month in pd.date_range(val_start, val_end, freq='MS', inclusive='left')]
    return {
        'method': 'three_historical_monthly_refit_validation_scores',
        'wait_days': WAIT_DAYS,
        'validation_month_count': VALIDATION_MONTHS,
        'validation_days': int((val_end - val_start).days),
        'validation_start': val_start.isoformat(),
        'validation_end': val_end.isoformat(),
        'evaluation_start': start.isoformat(),
        'evaluation_end': end.isoformat(),
        'model_fit_time': start.isoformat(),
        'threshold_selection_time': start.isoformat(),
        'validation_label_cutoff': start.isoformat(),
        'fixed_test_start': FIXED_TEST_START.isoformat(),
        'calendar_alignment': 'validation_end = floor_month(evaluation_start - 60 days)',
        'validation_wait': {
            'start': val_end.isoformat(), 'end': start.isoformat(),
            'days': int((start - val_end).days), 'minimum_days': WAIT_DAYS,
        },
        'validation_months': months,
        'evaluation_role': 'previously inspected retrospective development month; never selection outcomes',
        'transfer_caveat': (
            'Validation scores come from older monthly refits; one shared threshold '
            'transfers to the evaluation refit without a future recall guarantee.'
        ),
    }


def mature_validation_month(scoring: pd.DataFrame, cutoff):
    """Keep one historical scoring month's labels known strictly before cutoff.

    The input must represent a single calendar month completed by cutoff.
    Unknown outcomes are removed from validation, never relabeled as on-time.
    """
    boundary = _midnight(cutoff)
    if boundary > FIXED_TEST_START:
        raise ValueError('Validation cutoff must not cross the original fixed test start (2018-05-26)')
    validated = _validated_frame(scoring)
    months = validated.prediction_time.dt.to_period('M')
    if validated.empty or months.nunique() != 1:
        raise ValueError('Expected scoring orders from exactly one nonempty calendar month')
    start = months.iloc[0].start_time
    end = start + pd.DateOffset(months=1)
    if boundary < end:
        raise ValueError('Validation cutoff must be at or after the historical calendar month end')
    retained = validated.loc[validated.label_available_time < boundary].copy()
    _require_both_classes(retained, f'validation month {start:%Y-%m}')
    report = {
        'month': f'{start:%Y-%m}', 'start': start.isoformat(), 'end': end.isoformat(),
        **_partition_report(validated, retained, boundary),
        'scoring_order_id_fingerprint': _order_fingerprint(validated),
        'retained_order_id_fingerprint': _order_fingerprint(retained),
        'label_policy': 'only labels strictly before cutoff; excluded unknown outcomes are not negative labels',
    }
    return retained, report
