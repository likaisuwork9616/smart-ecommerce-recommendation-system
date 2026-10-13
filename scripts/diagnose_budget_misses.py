"""Diagnose missed delays under the existing fixed 10% daily alert budget.

These are post-hoc descriptions of previously inspected development months.
The groups and labels must not be used to select a model on these months.
Only aggregate counts are written to the public JSON report.
"""
from __future__ import annotations

import argparse
import hashlib
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
from scripts.delay_features import build_delay_dataset
from scripts.predict_delay import predict_features
from scripts.train_delay_model import source_manifest

PROMISE_BINS = ('0-7', '8-14', '15-21', '22-30', '31+')
RANK_BINS = ('<=10%', '10-20%', '20-50%', '50%+')
GROUPINGS = {
    'state_route': ('state_route',),
    'customer_state': ('customer_state',),
    'promise_days': ('promise_bin',),
    'route_by_promise': ('state_route', 'promise_bin'),
}
MIN_GROUP_ROWS = 30
MIN_GROUP_POSITIVES = 5


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _timestamps(values):
    stamps = []
    for value in values:
        try:
            if isinstance(value, (bool, int, float, np.number)):
                raise ValueError
            stamp = pd.Timestamp(value)
            if pd.isna(stamp) or stamp.tzinfo is not None:
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError('Expected valid timezone-naive prediction timestamps') from exc
        stamps.append(stamp)
    return pd.Series(stamps)


def _counts(labels, predictions, *, all_false_negatives=None, scope_false_negatives=None):
    y, chosen = np.asarray(labels), np.asarray(predictions, dtype=bool)
    tp = int(((y == 1) & chosen).sum())
    fp = int(((y == 0) & chosen).sum())
    fn = int(((y == 1) & ~chosen).sum())
    tn = int(((y == 0) & ~chosen).sum())
    rows, positives, alerts = len(y), tp + fn, tp + fp
    report = {'rows': rows, 'positive_rows': positives, 'alerts': alerts,
        'true_positives': tp, 'false_positives': fp, 'false_negatives': fn, 'true_negatives': tn,
        'positive_rate': positives / rows if rows else None,
        'alert_rate': alerts / rows if rows else None,
        'recall': tp / positives if positives else None,
        'precision': tp / alerts if alerts else None,
        'minimum_sample_met': rows >= MIN_GROUP_ROWS and positives >= MIN_GROUP_POSITIVES}
    if all_false_negatives is not None:
        report['share_of_all_false_negatives'] = fn / all_false_negatives if all_false_negatives else 0.
    if scope_false_negatives is not None:
        report['share_of_scope_false_negatives'] = fn / scope_false_negatives if scope_false_negatives else 0.
    return report


def daily_rank_bins(frame, scores, raw_scores=None):
    """Return positional daily rank bins using the actual policy's tie order.

    Fractions use one-based rank / the full eligible scored daily batch. The
    <=10% interval therefore equals floor(0.1 * daily_rows), including ties.
    The frame may have any external index; no labels are consulted here.
    """
    values = np.asarray(scores, dtype=float)
    raw = values if raw_scores is None else np.asarray(raw_scores, dtype=float)
    required = {'order_id', 'prediction_time'}
    if not required.issubset(frame.columns) or len(frame) == 0:
        raise ValueError('Expected nonempty frame with order_id and prediction_time')
    if (values.ndim != 1 or raw.ndim != 1 or len(values) != len(frame) or len(raw) != len(frame)
            or not np.isfinite(values).all() or not np.isfinite(raw).all()
            or ((values < 0) | (values > 1)).any() or ((raw < 0) | (raw > 1)).any()):
        raise ValueError('Require aligned finite score vectors in [0, 1]')
    ids = frame.order_id
    if ids.isna().any() or ids.duplicated().any() or not ids.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise ValueError('Expected unique nonempty string order IDs')
    times = _timestamps(frame.prediction_time)
    ranked = pd.DataFrame({'day': times.dt.normalize().to_numpy(), 'score': values,
        'raw_score': raw, 'order_id': ids.to_numpy(), 'position': np.arange(len(frame))})
    ranked = ranked.sort_values(['day', 'score', 'raw_score', 'order_id'],
        ascending=[True, False, False, True], kind='stable')
    groups = ranked.groupby('day', sort=False)
    ranks = groups.cumcount().to_numpy() + 1
    sizes = groups['order_id'].transform('size').to_numpy()
    # Integer comparisons avoid decimal rounding at the capacity boundary.
    assigned = np.select([10 * ranks <= sizes, 5 * ranks <= sizes, 2 * ranks <= sizes],
                         RANK_BINS[:3], default=RANK_BINS[3])
    result = np.empty(len(frame), dtype=object)
    result[ranked.position.to_numpy()] = assigned
    return result


def analyze_segments(frame, predictions, scores=None, raw_scores=None):
    """Describe counts by route/promise/month without fitting or selecting.

    Inputs are positional and must cover complete daily scoring cohorts when
    scores are supplied. Undefined recall/precision is null, not a zero claim.
    Small groups remain present, with a descriptive reliability flag.
    """
    required = {'order_id', 'prediction_time', 'delayed', 'state_route',
                'customer_state', 'estimated_delivery_days'}
    if not required.issubset(frame.columns) or len(frame) == 0:
        raise ValueError(f'Require nonempty diagnostic frame with {sorted(required)}')
    if raw_scores is not None and scores is None:
        raise ValueError('raw_scores requires scores for daily ranking')
    if frame.order_id.isna().any() or frame.order_id.duplicated().any():
        raise ValueError('Diagnostic order identities must be unique')
    y = frame.delayed.to_numpy()
    chosen = np.asarray(predictions)
    if chosen.ndim != 1 or len(chosen) != len(frame) or not np.isin(chosen, [0, 1]).all() or not np.isin(y, [0, 1]).all():
        raise ValueError('Expected aligned binary labels and predictions')
    data = frame[list(required)].copy().reset_index(drop=True)
    data['predicted_delayed'] = chosen.astype(bool)
    times = _timestamps(data.prediction_time)
    data['month'] = times.dt.strftime('%Y-%m')
    promise = pd.to_numeric(data.estimated_delivery_days, errors='raise')
    if not np.isfinite(promise).all() or (promise < 0).any():
        raise ValueError('Promise calendar days must be finite and nonnegative')
    data['promise_bin'] = pd.cut(promise, [-np.inf, 7, 14, 21, 30, np.inf],
                                labels=PROMISE_BINS, right=True).astype(object)
    for name in ('state_route', 'customer_state'):
        data[name] = data[name].astype(object).where(data[name].notna(), 'unknown')
    all_fn = int(((y == 1) & ~chosen.astype(bool)).sum())
    if scores is not None:
        data['daily_rank_bin'] = daily_rank_bins(data, scores, raw_scores)

    def scope_report(scope):
        result = {'overall': _counts(scope.delayed, scope.predicted_delayed, all_false_negatives=all_fn)}
        scope_fn = result['overall']['false_negatives']
        result['groups'] = {}
        for name, columns in GROUPINGS.items():
            rows = []
            for keys, part in scope.groupby(list(columns), sort=True, observed=True, dropna=False):
                keys = keys if isinstance(keys, tuple) else (keys,)
                row = dict(zip(columns, keys, strict=True))
                row.update(_counts(part.delayed, part.predicted_delayed,
                    all_false_negatives=all_fn, scope_false_negatives=scope_fn))
                rows.append(row)
            rows.sort(key=lambda row: (-row['false_negatives'], -row['positive_rows'], str(row)))
            if sum(row['rows'] for row in rows) != len(scope) or sum(row['false_negatives'] for row in rows) != scope_fn:
                raise AssertionError('Diagnostic groups do not partition the cohort')
            result['groups'][name] = rows
        if scores is not None:
            result['daily_rank_bins'] = []
            for name in RANK_BINS:
                part = scope.loc[scope.daily_rank_bin == name]
                row = {'daily_rank_bin': name}
                row.update(_counts(part.delayed, part.predicted_delayed,
                    all_false_negatives=all_fn, scope_false_negatives=scope_fn))
                result['daily_rank_bins'].append(row)
        return result

    return {'minimum_group_rows': MIN_GROUP_ROWS, 'minimum_group_positive_rows': MIN_GROUP_POSITIVES,
        'grouping_notes': 'Small groups retained; minimum_sample_met requires >=30 rows and >=5 delayed orders. '
            'All shares use observed FN counts, not causal attribution; null rates have zero denominator.',
        'promise_bin_notes': 'Calendar-day promise intervals [0,7], (7,14], (14,21], (21,30], (30,infinity).',
        'rank_notes': 'Within each complete closed day: calibrated score descending, raw score descending, '
            'order_id ascending; one-based rank / full eligible daily batch; independent of labels.',
        'aggregate': scope_report(data),
        'by_month': {str(month): scope_report(part) for month, part in data.groupby('month', sort=True)}}


def load_verified_baseline(report_path, scores_path, features_path, data_dir):
    """Verify raw provenance, diagnostic features, model reloads and decisions."""
    report = json.loads(Path(report_path).read_text(encoding='utf-8'))
    if report['primary_method_prespecified'] != 'sigmoid' or report['primary_budget_prespecified'] != 'cap_10':
        raise ValueError('Require existing prespecified sigmoid / 10% baseline')
    if report['daily_budget_fractions']['cap_10'] != .10 or report['source_files'] != source_manifest(data_dir):
        raise ValueError('Raw data or fixed budget differs from baseline report')
    expected_months = ['2017-12', '2018-02', '2018-04']
    if [fold['name'] for fold in report['folds']] != expected_months:
        raise ValueError('Require the same three prespecified development months')
    features = pd.read_csv(features_path, float_precision='round_trip')
    if features.order_id.isna().any() or features.order_id.duplicated().any():
        raise ValueError('Feature cache must have unique order IDs')
    raw = build_delay_dataset(data_dir).set_index('order_id')
    cached = features.set_index('order_id')
    if len(raw) != len(cached) or set(raw.index) != set(cached.index):
        raise ValueError('Raw and cached eligible cohorts differ')
    raw = raw.loc[cached.index]
    for name in ('prediction_time', 'label_available_time'):
        if not np.array_equal(pd.to_datetime(raw[name]).to_numpy(), pd.to_datetime(cached[name]).to_numpy()):
            raise ValueError(f'Cached {name} differs from raw source')
    for name in ('delayed', 'estimated_delivery_days'):
        if not np.array_equal(raw[name].to_numpy(), cached[name].to_numpy()):
            raise ValueError(f'Cached {name} differs from raw source')
    for name in ('customer_state', 'primary_seller_state'):
        if not raw[name].fillna('unknown').eq(cached[name].fillna('unknown')).all():
            raise ValueError(f'Cached {name} differs from raw source')
    route = (raw.primary_seller_state.astype('string') + '->' + raw.customer_state.astype('string')).fillna('unknown')
    if not route.eq(cached.state_route.fillna('unknown')).all():
        raise ValueError('Cached directed routes differ from raw seller/customer states')
    scores = pd.read_csv(scores_path, float_precision='round_trip')
    if scores.duplicated(['fold', 'phase', 'candidate', 'method', 'order_id']).any():
        raise ValueError('Duplicate source score identities')
    joined, audits = [], []
    for fold in report['folds']:
        name = fold['name']
        candidate = fold['experiment']['selected_models']['sigmoid']['cap_10']
        part = scores.loc[(scores.fold == name) & (scores.phase == 'evaluation')
            & (scores.candidate == candidate) & (scores.method == 'sigmoid')].copy()
        if part.empty or order_fingerprint(part) != fold['order_id_fingerprints']['evaluation']:
            raise ValueError('Baseline development cohort identity differs')
        frame = features.set_index('order_id').loc[part.order_id].reset_index()
        if not np.array_equal(pd.to_datetime(part.prediction_time).to_numpy(), pd.to_datetime(frame.prediction_time).to_numpy()):
            raise ValueError('Source score and feature timestamps differ')
        if not pd.to_datetime(frame.prediction_time).dt.strftime('%Y-%m').eq(name).all():
            raise ValueError('Unexpected development month')
        if not np.array_equal(part.outcome_for_metrics.to_numpy(), frame.delayed.to_numpy()):
            raise ValueError('Source score outcomes differ from raw targets')
        reference = fold['experiment']['models'][candidate]['sigmoid']['strategies']['cap_10']
        if not part.threshold_cap_10.eq(reference['threshold']).all():
            raise ValueError('Cached decision threshold differs from report')
        artifact_path = (ROOT / fold['research_artifact']['path']).resolve()
        if not artifact_path.is_relative_to(ROOT) or sha256(artifact_path) != fold['research_artifact']['sha256']:
            raise ValueError('Baseline model path/hash differs from report')
        artifact = joblib.load(artifact_path)
        if artifact.get('daily_alert_cap') != .10 or artifact.get('threshold') != reference['threshold']:
            raise ValueError('Reloaded model decision contract differs')
        for _, estimator in artifact['pipeline'].steps:
            if hasattr(estimator, 'n_jobs'):
                estimator.n_jobs = 1
        with threadpool_limits(limits=2):
            reloaded = predict_features(artifact, frame, complete_daily_batches=True)
        for source, predicted in (('raw_delay_score', 'raw_delay_score'), ('delay_probability', 'delay_score')):
            if not np.allclose(part[source], reloaded[predicted], rtol=0, atol=1e-12):
                raise ValueError('Baseline score differs from hashed model reload')
        if not np.array_equal(part.predicted_cap_10.to_numpy(), reloaded.predicted_delayed.to_numpy()):
            raise ValueError('Baseline daily budget decision differs from model reload')
        metrics = _counts(frame.delayed, part.predicted_cap_10)
        cm = [[metrics['true_negatives'], metrics['false_positives']],
              [metrics['false_negatives'], metrics['true_positives']]]
        if metrics['rows'] != reference['evaluation']['rows'] or cm != reference['evaluation']['confusion_matrix']:
            raise ValueError('Baseline confusion matrix differs from report')
        for column in ('raw_delay_score', 'delay_probability', 'predicted_cap_10'):
            frame[column] = part[column].to_numpy()
        frame['fold'] = name
        joined.append(frame)
        audits.append({'month': name, 'candidate': candidate, 'rows': len(frame),
            'evaluation_order_fingerprint': order_fingerprint(frame),
            'artifact': fold['research_artifact'], 'model_reload_scores_matched': True,
            'model_reload_daily_predictions_matched': True})
    combined = pd.concat(joined, ignore_index=True)
    reference = next(row for row in report['summary'] if row['method'] == 'sigmoid'
        and row['budget'] == 'cap_10' and row['model'] == 'validation_selected')
    counts = _counts(combined.delayed, combined.predicted_cap_10)
    for key in ('rows', 'true_negatives', 'false_positives', 'false_negatives', 'true_positives', 'alerts'):
        if counts[key] != reference[key]:
            raise ValueError(f'Baseline aggregate {key} differs from report')
    return combined, {'source_files': report['source_files'],
        'baseline_report_sha256': sha256(report_path), 'baseline_scores_sha256': sha256(scores_path),
        'route_features_sha256': sha256(features_path),
        'diagnostic_feature_cache_verified_against_raw': True, 'folds': audits}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-report', type=Path, default=ROOT / 'reports/stage4/calibration_budget.json')
    parser.add_argument('--scores', type=Path, default=ROOT / 'data/processed/olist_delay_calibration_budget_scores.csv')
    parser.add_argument('--features', type=Path, default=ROOT / 'data/processed/olist_delay_route_features.csv')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/budget_miss_diagnostics.json')
    args = parser.parse_args(argv)
    frame, provenance = load_verified_baseline(args.baseline_report, args.scores, args.features, args.data_dir)
    diagnostics = analyze_segments(frame, frame.predicted_cap_10,
        frame.delay_probability, frame.raw_delay_score)
    report = {'format_version': 1, 'status': 'ok',
        'evaluation_role': 'post-hoc diagnosis of previously inspected development months; not independent test results',
        'selection_warning': 'Groups and evaluation labels are descriptive only; never use these months to select features, models or parameters.',
        'baseline': 'historical-policy-selected candidate / sigmoid / daily cap 10%',
        'daily_budget_fraction': .10,
        'coverage': 'valid eventually-delivered historical eligible orders; denominator is not every raw approved order',
        'batch_timing': 'Complete closed calendar day; up to one day wait; floor(10% * full eligible daily cohort), no carryover.',
        'holdout': 'Original 2018-05-26 onward period not scored.',
        'provenance': provenance, 'diagnostics': diagnostics}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    counts = diagnostics['aggregate']['overall']
    print(f"Verified {counts['rows']} development orders; FN={counts['false_negatives']}; TP={counts['true_positives']}; FP={counts['false_positives']}")
    print(f'Report: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
