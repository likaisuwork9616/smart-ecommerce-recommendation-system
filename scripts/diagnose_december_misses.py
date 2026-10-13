"""Replay December and its three historical validation months; aggregate misses.

No models, selectors, thresholds, or feature values are fitted or changed.
December remains a repeatedly inspected development evaluation, not a test.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_budget_training import score_validation
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_december_diagnostics import analyze_month
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.delay_outcome_clock import add_training_outcome_clock, split_outcome_training_month
from scripts.delay_regularization_training import feature_names, prepare_input, PRIMARY_SELECTION
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month, rolling_validation_schedule
from scripts.improve_budget_ranking import sha256, relative
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.train_delay_model import positive_probability

CANDIDATES = ('xgboost_engineering_geo', 'logistic_load_regularization_c1',
              'logistic_load_regularization_c0p01')
HISTORICAL_MONTHS = ('2017-07', '2017-08', '2017-09')
EVALUATION_MONTH = '2017-12'
CUTOFF = pd.Timestamp('2017-12-01')


def load_target_scores(path):
    """Read only the frozen fold/candidates; retain all daily batch members."""
    parts = []
    for chunk in pd.read_csv(path, chunksize=200000, float_precision='round_trip'):
        selected = chunk.loc[chunk.fold.eq(EVALUATION_MONTH) & chunk.candidate.isin(CANDIDATES)]
        if len(selected):
            parts.append(selected)
    if not parts:
        raise ValueError('No frozen December scores found')
    result = pd.concat(parts, ignore_index=True)
    if result.duplicated(['model_version', 'candidate', 'order_id']).any():
        raise ValueError('Frozen score identities must be unique')
    if set(result.model_version) != {*HISTORICAL_MONTHS, EVALUATION_MONTH}:
        raise ValueError('Unexpected model months in December fold')
    result['prediction_time'] = pd.to_datetime(result.prediction_time)
    return result


def verify_month_scores(frame, scores, candidate, month, known, values, predictions):
    """Check timestamps, cutoff flags, scores and exact frozen alert membership."""
    if month not in (*HISTORICAL_MONTHS, EVALUATION_MONTH) or candidate not in CANDIDATES:
        raise ValueError('Require a declared month and candidate')
    known = np.asarray(known)
    if known.ndim != 1 or len(known) != len(frame) or known.dtype != np.dtype(bool):
        raise ValueError('Require an aligned boolean availability mask')
    if (frame.empty or frame.order_id.duplicated().any() or frame.order_id.isna().any()
            or not frame.order_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
        raise ValueError('Require unique nonempty monthly order identities')
    times = pd.to_datetime(frame.prediction_time)
    if not times.dt.strftime('%Y-%m').eq(month).all():
        raise ValueError('Frame approvals must match the declared month')
    expected_known = (pd.to_datetime(frame.label_available_time) < CUTOFF).to_numpy() if month in HISTORICAL_MONTHS else np.ones(len(frame), dtype=bool)
    if not np.array_equal(known, expected_known):
        raise ValueError('Availability mask differs from the strict historical cutoff or retrospective role')
    part = scores.loc[scores.model_version.eq(month) & scores.candidate.eq(candidate)]
    if (len(part) != len(frame) or part.order_id.duplicated().any()
            or set(part.order_id) != set(frame.order_id)):
        raise ValueError('Score source does not cover the complete monthly cohort')
    part = part.set_index('order_id').loc[frame.order_id]
    role = 'evaluation' if month == EVALUATION_MONTH else 'validation'
    expected_flags = np.zeros(len(frame), dtype=bool) if role == 'evaluation' else known
    if not part.role.eq(role).all() or not np.array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy()):
        raise ValueError('Score role or approval timestamps changed')
    if not np.array_equal(part.known_at_selection.to_numpy(), expected_flags):
        raise ValueError('Frozen outcome-availability flags changed')
    if not np.array_equal(part.outcome_for_metrics.notna().to_numpy(), known):
        raise ValueError('Unknown historical outcomes must stay absent from metric labels')
    np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], frame.delayed.to_numpy()[known])
    np.testing.assert_allclose(part.delay_score.to_numpy(), values, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(part.predicted_delayed.to_numpy(), predictions)


def verify_counts(diagnostics, metrics):
    tn, fp = metrics['confusion_matrix'][0]
    fn, tp = metrics['confusion_matrix'][1]
    expected = {'rows': metrics['rows'], 'positive_rows': metrics['positive_rows'],
                'true_negatives': tn, 'false_positives': fp,
                'false_negatives': fn, 'true_positives': tp,
                'alerts': metrics['predicted_positive_rows']}
    actual = diagnostics['aggregate']['overall']
    for key, value in expected.items():
        if actual[key] != value:
            raise ValueError(f'Diagnostic {key} differs from frozen experiment')
    for key in ('recall', 'precision'):
        if not np.isclose(actual[key], metrics[key], rtol=0, atol=1e-12):
            raise ValueError(f'Diagnostic {key} differs from frozen experiment')


def build_report(source_report, scores_path, features_path, data_dir):
    previous = json.loads(source_report.read_text(encoding='utf-8'))
    if previous['status'] != 'ok' or previous['daily_cap'] != .1:
        raise ValueError('Require the frozen ten-percent regularization experiment')
    manifest = engineering_source_manifest(data_dir)
    if manifest != previous['source_files']:
        raise ValueError('Seven raw source hashes differ from the frozen experiment')
    for path, info in ((features_path, previous['feature_dataset']), (scores_path, previous['score_export'])):
        if sha256(path) != info['sha256']:
            raise ValueError('Frozen feature or score source changed')
    fold = next(f for f in previous['folds'] if f['name'] == EVALUATION_MONTH)
    schedule = rolling_validation_schedule(CUTOFF, '2018-01-01')
    if fold['schedule'] != schedule or fold['experiment']['selected_models'][PRIMARY_SELECTION] != CANDIDATES[0]:
        raise ValueError('December schedule or historical selection changed')
    frame = pd.read_csv(features_path, float_precision='round_trip',
                        dtype={c: object for c in CATEGORICAL_FEATURES})
    for column in ('order_purchase_timestamp', 'prediction_time', 'label_available_time', 'training_outcome_known_time'):
        frame[column] = pd.to_datetime(frame[column])
    # Raw-derived timestamps and calendar target are checked without fitting.
    frame = add_training_outcome_clock(frame, pd.read_csv(data_dir / 'olist_orders_dataset.csv'))
    if len(frame) != previous['feature_dataset']['rows']:
        raise ValueError('Frozen eligible population changed')
    scores = load_target_scores(scores_path)
    monthly = {entry['month']: entry for entry in previous['monthly_training']}
    context = fold['experiment']['models']
    primary_summary = next(row for row in previous['summary'] if row['model_or_selection'] == PRIMARY_SELECTION)
    result = {
        'format_version': 1, 'status': 'ok', 'analysis': 'december_and_its_historical_validation_misses',
        'fold': EVALUATION_MONTH, 'historical_months': list(HISTORICAL_MONTHS),
        'candidate_order': list(CANDIDATES), 'daily_cap': .1, 'threshold': 0.,
        'selection_time': CUTOFF.isoformat(), 'schedule': schedule,
        'source_report': {'path': relative(source_report), 'sha256': sha256(source_report)},
        'source_scores': {'path': relative(scores_path), 'sha256': sha256(scores_path),
                          'source_rows': previous['score_export']['rows'], 'checked_rows': len(scores)},
        'source_features': {'path': relative(features_path), 'sha256': sha256(features_path), 'rows': len(frame)},
        'source_files': manifest, 'new_fit_count': 0, 'new_model_selection': False,
        'frozen_selection_context': {
            'primary_selection': PRIMARY_SELECTION, 'selected_candidate': CANDIDATES[0],
            'selection_rule': 'maximize worst historical month recall, then pooled historical TP, pooled AP, fixed candidate order',
            'candidate_count_in_original_selection': len(previous['selection_groups'][PRIMARY_SELECTION]),
            'compared_candidates': {c: {key: context[c][key] for key in (
                'minimum_validation_month_recall', 'validation_true_positives',
                'validation_pooled_average_precision')} for c in CANDIDATES},
            'overall_primary_minimum_historical_recall': primary_summary['minimum_validation_month_recall'],
            'suitability': previous['suitability'],
        },
        'policies': {
            'budget': 'Complete closed approval-day batches, floor(0.1*N), no carryover; score descending then order_id ascending. Unknown outcomes still compete.',
            'historical_labels': 'Actual delivery timestamp strictly before 2017-12-01; unknown outcomes receive no FN/FP/TP/TN or label-derived segment statistics.',
            'evaluation_labels': 'December outcomes only describe repeatedly inspected development evaluation; none are known at December selection or used to reselect.',
            'ranking': 'All rank intervals use the complete daily cohort before the outcome-availability mask.',
            'groups': 'Fixed route/state/promise/support/margin bins; minimum_sample_met requires 30 known rows and 5 known delayed rows. Groups overlap across separate dimensions.',
            'interpretation': 'Descriptive associations and model error overlap; no causal claim, new ensemble, or deployment improvement is established.',
            'coverage': 'Existing valid eventually-delivered eligible population only; not all approved, unfinished or cancelled orders.',
            'geolocation': 'Frozen geographic centroids have no event timestamps; prior static-geography assumption unchanged.',
            'holdout': 'No scoring on or after original fixed test start 2018-05-26.',
        },
        'months': {},
    }
    versions_checked, scoring_rows_checked = 0, 0
    for month in (*HISTORICAL_MONTHS, EVALUATION_MONTH):
        print(f'{month}: verifying complete cohort and replaying three saved versions', flush=True)
        old = monthly[month]
        splits, baseline_split = split_rolling_month(frame, old['split']['model_fit_time'])
        if baseline_split != old['split']:
            raise ValueError('Frozen rolling cohort changed')
        _, training_split = split_outcome_training_month(frame, old['split']['model_fit_time'], wait_days=0, clock='deadline')
        scoring = splits['scoring'].reset_index(drop=True)
        historical = month in HISTORICAL_MONTHS
        known = (scoring.label_available_time < CUTOFF).to_numpy() if historical else np.ones(len(scoring), dtype=bool)
        fingerprint = order_fingerprint(scoring)
        expected_fp = fold['order_id_fingerprints']['validation_full_by_month'][month] if historical else fold['order_id_fingerprints']['evaluation']
        if fingerprint != expected_fp:
            raise ValueError('Frozen monthly identity fingerprint changed')
        if historical:
            retained, maturity = mature_validation_month(scoring, CUTOFF)
            if maturity != next(m for m in fold['validation_maturity'] if m['month'] == month):
                raise ValueError('Historical label cutoff partition changed')
            np.testing.assert_array_equal(retained.order_id, scoring.loc[known, 'order_id'])
        values_by_candidate, artifacts = {}, {}
        for candidate in CANDIDATES:
            info = old['models'][candidate]['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Saved version SHA changed')
            artifact = joblib.load(path)
            numeric, categorical = feature_names(candidate)
            if (artifact['candidate'] != candidate or artifact['split'] != training_split
                    or old['models'][candidate]['training_split'] != training_split
                    or artifact['feature_names'] != numeric + categorical
                    or artifact['source_files'] != manifest):
                raise ValueError('Saved version training/source/feature contract changed')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(scoring, candidate))
            predictions = apply_alert_policy(scoring, values, 0., .1, raw_scores=values)
            verify_month_scores(scoring, scores, candidate, month, known, values, predictions)
            if historical and score_validation(scoring, values, CUTOFF) != context[candidate]['validation_by_month'][month]:
                raise ValueError('Historical metrics or complete-day audits changed')
            values_by_candidate[candidate] = values
            artifacts[candidate] = {**info, 'model_fit_time': training_split['model_fit_time'],
                                    'training_order_id_fingerprint': training_split['partitions']['train']['order_id_fingerprint'],
                                    'feature_count': len(numeric) + len(categorical),
                                    'score_rows_replayed': len(scoring)}
            versions_checked += 1
            scoring_rows_checked += len(scoring)
            del artifact
        diagnosis = analyze_month(scoring, values_by_candidate, known)
        for candidate in CANDIDATES:
            metrics = context[candidate]['validation_by_month'][month]['known_outcome_metrics'] if historical else context[candidate]['development_evaluation']
            verify_counts(diagnosis['models'][candidate]['known_outcome_diagnostics'], metrics)
            batch = context[candidate]['validation_by_month'][month]['full_batch'] if historical else context[candidate]['evaluation_batch']
            if (diagnosis['complete_batch']['capacity'] != batch['capacity']
                    or diagnosis['models'][candidate]['unknown_outcome_alerts']['alerts'] != batch['unknown_outcome_alerts']):
                raise ValueError('Frozen complete-day budget or unknown slot counts changed')
            # Top-level months already identify this single-month scope.
            # Avoid publishing a second identical copy of every group table.
            diagnosis['models'][candidate]['known_outcome_diagnostics'].pop('by_month')
        result['months'][month] = {
            'role': 'historical_validation' if historical else 'development_evaluation',
            'outcome_cutoff': CUTOFF.isoformat() if historical else None,
            'outcomes_used_for_new_selection': False,
            'known_at_original_selection_rows': int(known.sum()) if historical else 0,
            'order_id_fingerprint': fingerprint,
            'known_outcome_order_id_fingerprint': order_fingerprint(scoring.loc[known]),
            'artifacts': artifacts, **diagnosis,
        }
    result['verification'] = {'saved_versions_replayed': versions_checked,
                              'scores_and_alerts_checked': scoring_rows_checked,
                              'source_labels_timestamps_and_training_splits_verified': True,
                              'frozen_metrics_and_budget_counts_unchanged': True}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/logistic_regularization.json')
    parser.add_argument('--scores', type=Path, default=ROOT / 'data/processed/olist_delay_logistic_regularization_scores.csv')
    parser.add_argument('--features', type=Path, default=ROOT / 'data/processed/olist_delay_engineering_features.csv')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/december_miss_diagnostics.json')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    protected = {args.source_report.resolve(), args.scores.resolve(), args.features.resolve()}
    if output in protected or output.suffix.lower() != '.json':
        parser.error('Output must be a separate aggregate JSON report')
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding='utf-8'))
            own_report = (isinstance(existing, dict) and existing.get('format_version') == 1
                          and existing.get('analysis') == 'december_and_its_historical_validation_misses')
        except (OSError, ValueError):
            own_report = False
        if not own_report:
            parser.error('Refusing to overwrite an existing file other than this December diagnostic report')
    report = build_report(args.source_report, args.scores, args.features, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Wrote aggregate diagnostics: {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
