"""Verify a complete inspected day using only the 20 frozen score cohorts.

This module does not read outcome values, load models, or calculate performance.
The caller must establish the roster's source and completeness separately. The
private DataFrame contains identities and scores and must remain Git-ignored.
"""
from __future__ import annotations

from datetime import date, datetime
from numbers import Integral, Real

import numpy as np
import pandas as pd


SEEDS = (11, 29, 42, 73, 101)
VERSIONS = ('base08', 'age08', 'base10', 'age10')
BASELINE = 'xgboost_rank_backlog_7_14d_l2_100_topk_10'
AGE = 'xgboost_rank_unobserved_handover_age_p90_102_l2_100_topk_10'
VERSION_SOURCE = {
    'base08': (.8, BASELINE), 'age08': (.8, AGE),
    'base10': (1., BASELINE), 'age10': (1., AGE),
}
PRIVATE_COLUMNS = (
    'version', 'seed', 'order_id', 'prediction_time', 'score', 'rank',
    'full_day_rows', 'daily_capacity', 'alert',
)
REQUIRED_LEDGER_COLUMNS = (
    'order_id', 'prediction_time', 'fold', 'role', 'candidate', 'model_version',
    'known_at_selection', 'delay_score', 'predicted_delayed', 'seed',
    'colsample_bytree',
)


def schema():
    """Return the explicit outcome-free acceptance and private output contract."""
    return {
        'format_version': 1,
        'versions': list(VERSIONS), 'seeds': list(SEEDS),
        'version_source': {version: {'colsample_bytree': colsample, 'candidate': candidate}
                           for version, (colsample, candidate) in VERSION_SOURCE.items()},
        'required_roster_columns': ['order_id', 'prediction_time'],
        'required_ledger_columns': list(REQUIRED_LEDGER_COLUMNS),
        'private_columns': list(PRIVATE_COLUMNS),
        'ranking': 'score DESC, order_id ASC; exactly floor(full_day_rows / 10) alerts per run',
        'outcomes': 'Outcome values are neither required nor read; no row is removed by outcome availability.',
        'availability_flag': 'Evaluation known_at_selection must be boolean False; it is not an outcome-known denominator.',
        'privacy': 'Public result contains aggregates only; private output contains identities, times, scores and ranks.',
        'completeness_limit': 'The caller must independently bind the roster to its frozen complete-day source.',
    }


def _timestamps(values, description):
    """Reject missing, numeric and timezone-aware clocks rather than coercing."""
    parsed = []
    for value in values:
        if (not isinstance(value, (str, datetime, date, pd.Timestamp, np.datetime64))
                or pd.isna(value)):
            raise ValueError(f'{description} must contain nonmissing timezone-naive timestamps')
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f'{description} contains an invalid timestamp') from exc
        if pd.isna(stamp) or stamp.tzinfo is not None:
            raise ValueError(f'{description} must contain nonmissing timezone-naive timestamps')
        parsed.append(stamp)
    try:
        return pd.DatetimeIndex(parsed)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{description} must use compatible timezone-naive timestamps') from exc


def _ids(values, description):
    if any(not isinstance(value, str) or not value or value != value.strip() for value in values):
        raise ValueError(f'{description} must contain nonempty string identities without outer whitespace')
    return np.asarray(values, dtype=str)


def _binary(values, description):
    if any(isinstance(value, (str, bytes)) or not isinstance(value, (bool, Integral))
           or value not in (0, 1) for value in values):
        raise ValueError(f'{description} must contain boolean or integer binary values')
    return np.asarray(values, dtype=bool)


def _bounded_scores(values):
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) for value in values):
        raise ValueError('Require finite bounded ranking scores')
    scores = np.asarray(values, dtype=float)
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError('Require finite bounded ranking scores in [0, 1]')
    return scores


def _ties(scores, capacity):
    """Only aggregate tie counts leave this function; score values stay private."""
    _, counts = np.unique(scores, return_counts=True)
    tied = counts[counts > 1]
    if capacity:
        cutoff_mask = scores == scores[capacity - 1]
        selected = int(cutoff_mask[:capacity].sum())
        excluded = int(cutoff_mask[capacity:].sum())
    else:
        selected = excluded = 0
    return {
        'tied_score_groups': int(len(tied)), 'rows_in_tied_score_groups': int(tied.sum()),
        'cutoff_tie_rows': selected + excluded, 'cutoff_tie_alerted_rows': selected,
        'cutoff_tie_unalerted_rows': excluded,
        'cross_boundary_tie': bool(selected and excluded),
        'boundary_has_selected_row': bool(capacity),
        'boundary_has_unselected_row': bool(capacity < len(scores)),
    }


def accept_day(roster, ledger, *, day, fold='2018-02', model_version='2018-02',
               role='evaluation', saved_rank_column=None):
    """Return ``(public_aggregates, private_rows)`` after checking all 20 runs.

    ``roster`` is an independently sourced complete inspected-day cohort;
    ``ledger`` contains exactly that day for four settings and all five seeds.
    Extra outcome columns are ignored. Every saved binary alert must match the
    reconstructed full-day ranking. A saved rank is checked only if the caller
    explicitly identifies such a source column (the current source has none).
    """
    if (not isinstance(roster, pd.DataFrame) or roster.empty
            or not {'order_id', 'prediction_time'}.issubset(roster)
            or not roster.columns.is_unique):
        raise ValueError('Require a nonempty roster with unique column names and identity/time columns')
    if (not isinstance(ledger, pd.DataFrame) or ledger.empty
            or not set(REQUIRED_LEDGER_COLUMNS).issubset(ledger)
            or not ledger.columns.is_unique):
        raise ValueError('Require a nonempty score ledger with the required unique columns')
    if role != 'evaluation':
        raise ValueError('This delivery acceptance is restricted to an inspected evaluation phase')
    if (not isinstance(fold, str) or not isinstance(model_version, str)
            or not fold or not model_version):
        raise ValueError('Require explicit string fold and model version')
    target = _timestamps([day], 'Day')[0]
    if target != target.normalize() or target.strftime('%Y-%m') != model_version:
        raise ValueError('Require a midnight day in the declared model-version month')
    if saved_rank_column is not None and (not isinstance(saved_rank_column, str)
                                         or saved_rank_column not in ledger):
        raise ValueError('The declared saved-rank column is missing')

    ids = _ids(roster.order_id.tolist(), 'Roster')
    clocks = _timestamps(roster.prediction_time, 'Roster prediction_time')
    if len(set(ids)) != len(ids) or not (clocks.normalize() == target).all():
        raise ValueError('Roster identities must be unique and all belong to the selected day')
    size, capacity = len(ids), len(ids) // 10
    expected_clocks = dict(zip(ids, clocks, strict=True))
    if len(ledger) != size * len(VERSIONS) * len(SEEDS):
        raise ValueError('Require exactly 20 complete day scoring cohorts')
    actual_ids = _ids(ledger.order_id.tolist(), 'Ledger')
    actual_clocks = _timestamps(ledger.prediction_time, 'Ledger prediction_time')
    if not (actual_clocks.normalize() == target).all():
        raise ValueError('Ledger contains a different approval day')
    if (not ledger.fold.eq(fold).all() or not ledger.role.eq(role).all()
            or not ledger.model_version.eq(model_version).all()):
        raise ValueError('Ledger fold, role or model version changed')
    if any(not isinstance(value, (bool, np.bool_)) for value in ledger.known_at_selection):
        raise ValueError('known_at_selection must be boolean')
    if ledger.known_at_selection.any():
        raise ValueError('Evaluation known_at_selection must preserve the frozen all-False rule')
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral)
           for value in ledger.seed):
        raise ValueError('Seeds must be integer identities')
    if set(ledger.seed) != set(SEEDS):
        raise ValueError('Require all five frozen seeds and no additional seed')
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
           or not np.isfinite(value) for value in ledger.colsample_bytree):
        raise ValueError('colsample_bytree must preserve numeric source settings')
    if (set(ledger.colsample_bytree) != {.8, 1.}
            or set(ledger.candidate) != {BASELINE, AGE}):
        raise ValueError('Require exactly the four frozen scoring settings')

    work = ledger.copy(deep=True)
    work['order_id'] = actual_ids
    work['prediction_time'] = actual_clocks
    work['delay_score'] = _bounded_scores(work.delay_score.tolist())
    work['predicted_delayed'] = _binary(work.predicted_delayed.tolist(), 'Saved alerts')
    results, details = [], []
    for version in VERSIONS:
        colsample, candidate = VERSION_SOURCE[version]
        for seed in SEEDS:
            part = work.loc[work.colsample_bytree.eq(colsample) & work.candidate.eq(candidate)
                            & work.seed.eq(seed)].copy()
            if (len(part) != size or part.order_id.duplicated().any()
                    or set(part.order_id) != set(ids)):
                raise ValueError('Each version/seed must have exactly the complete roster once')
            if any(clock != expected_clocks[identity] for identity, clock in
                   zip(part.order_id, part.prediction_time, strict=True)):
                raise ValueError('A ledger prediction timestamp differs from the source roster')
            part = part.sort_values(['delay_score', 'order_id'], ascending=[False, True], kind='stable')
            ranks = np.arange(1, size + 1, dtype=np.int64)
            alerts = ranks <= capacity
            if not np.array_equal(part.predicted_delayed.to_numpy(), alerts):
                raise ValueError('Saved alert flags differ from complete-day reconstructed ranking')
            if saved_rank_column is not None:
                saved = part[saved_rank_column].tolist()
                if (any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) for value in saved)
                        or not np.array_equal(np.asarray(saved), ranks)):
                    raise ValueError('Saved daily ranks differ from reconstructed ranking')
            values = part.delay_score.to_numpy()
            results.append({
                'version': version, 'seed': seed, 'candidate': candidate,
                'colsample_bytree': colsample, 'fold': fold, 'role': role,
                'model_version': model_version, 'full_day_rows': size, 'daily_capacity': capacity,
                'alerts': int(alerts.sum()), 'saved_alerts_verified_rows': size,
                'saved_ranks_verified_rows': size if saved_rank_column is not None else 0,
                'known_at_selection_true_rows': 0, 'ties': _ties(values, capacity),
            })
            details.append(pd.DataFrame({
                'version': version, 'seed': seed, 'order_id': part.order_id.to_numpy(),
                'prediction_time': part.prediction_time.to_numpy(), 'score': values,
                'rank': ranks, 'full_day_rows': size, 'daily_capacity': capacity, 'alert': alerts,
            }, columns=PRIVATE_COLUMNS))
    private = pd.concat(details, ignore_index=True)
    public = {
        'format_version': 1, 'day': target.date().isoformat(), 'status': 'ok',
        'full_day_rows': size, 'daily_capacity': capacity,
        'version_count': len(VERSIONS), 'seed_count': len(SEEDS), 'run_count': len(results),
        'score_rows': len(private), 'alerts_across_runs': int(private.alert.sum()),
        'saved_alert_flags_verified': len(private),
        'saved_daily_ranks_verified': len(private) if saved_rank_column is not None else 0,
        'source_has_saved_daily_rank': saved_rank_column is not None,
        'outcome_columns_read': 0, 'labels_not_read': True, 'outcome_filtering_applied': False,
        'runs': results,
    }
    if (public['score_rows'] != size * 20 or public['alerts_across_runs'] != capacity * 20
            or tuple(private.columns) != PRIVATE_COLUMNS):
        raise AssertionError('Complete-day acceptance output did not reconcile')
    return public, private


def verify_private_output(roster, output, *, day, fold='2018-02', model_version='2018-02',
                          role='evaluation'):
    """Recheck a private output's schema, full roster, values and canonical order.

    This establishes internal output consistency only. The caller must also
    compare a file readback with the originally accepted frozen-score output;
    it cannot establish score provenance from an output file alone.
    """
    if (not isinstance(output, pd.DataFrame) or output.empty
            or tuple(output.columns) != PRIVATE_COLUMNS):
        raise ValueError('Require exactly the private output schema in its declared order')
    if not isinstance(roster, pd.DataFrame) or roster.empty:
        raise ValueError('Require a nonempty independently sourced roster')
    if set(output.version) != set(VERSIONS):
        raise ValueError('Private output must contain exactly the four frozen versions')
    size, capacity = len(roster), len(roster) // 10
    for name, expected in (('full_day_rows', size), ('daily_capacity', capacity)):
        if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral)
               or value != expected for value in output[name]):
            raise ValueError('Private output denominator or capacity changed')
    ledger = output[['order_id', 'prediction_time', 'seed']].copy()
    ledger['fold'], ledger['role'], ledger['model_version'] = fold, role, model_version
    ledger['candidate'] = output.version.map({version: value[1] for version, value in VERSION_SOURCE.items()})
    ledger['colsample_bytree'] = output.version.map({version: value[0] for version, value in VERSION_SOURCE.items()})
    ledger['known_at_selection'] = False
    ledger['delay_score'] = output.score
    ledger['predicted_delayed'] = output.alert
    ledger['source_daily_rank'] = output['rank']
    public, canonical = accept_day(roster, ledger, day=day, fold=fold, model_version=model_version,
                                   role=role, saved_rank_column='source_daily_rank')
    observed = output.reset_index(drop=True).copy()
    observed['prediction_time'] = _timestamps(observed.prediction_time, 'Private output prediction_time')
    try:
        pd.testing.assert_frame_equal(observed, canonical, check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError('Private output differs from canonical version, seed and rank order') from exc
    return {
        'rows_verified': len(output), 'runs_verified': public['run_count'],
        'rank_rows_verified': public['saved_daily_ranks_verified'],
        'alert_flags_verified': public['saved_alert_flags_verified'],
        'canonical_row_order_verified': True,
        'source_score_provenance_verified_by_this_function': False,
    }
