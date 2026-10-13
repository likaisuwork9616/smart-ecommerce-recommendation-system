"""Paired route/promise/rank errors for the fixed route-load feature experiment.

Replay December and its historical months without fitting or selecting. Model
comparisons are descriptive; their alert union is not a daily-budget policy.
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
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_december_diagnostics import analyze_month
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.delay_regularization_training import PRIMARY_SELECTION
from scripts.delay_outcome_clock import add_training_outcome_clock
from scripts.improve_budget_ranking import sha256, relative
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.train_delay_model import positive_probability

PAIRED_CANDIDATES = {
    'logistic_c1': ('logistic_load_regularization_c1', 'logistic_c1_route_load_trend', 'logistic_c1_route_load_cross'),
    'logistic_c0p01': ('logistic_load_regularization_c0p01', 'logistic_c0p01_route_load_trend', 'logistic_c0p01_route_load_cross'),
    'xgboost': ('xgboost_engineering_geo', 'xgboost_route_load_trend', 'xgboost_route_load_cross'),
}
MONTHS = ('2017-07', '2017-08', '2017-09', '2017-12')
CUTOFF = pd.Timestamp('2017-12-01')


def _check_counts(actual, expected):
    tn, fp, fn, tp = np.asarray(expected['confusion_matrix']).ravel()
    for key, value in {'rows': expected['rows'], 'true_negatives': tn, 'false_positives': fp,
                       'false_negatives': fn, 'true_positives': tp}.items():
        if actual[key] != value:
            raise ValueError('Paired diagnostic differs from the feature experiment')


def build_report(source_path, data_dir):
    from scripts.delay_route_load_training import feature_names, prepare_input

    source = json.loads(source_path.read_text(encoding='utf-8'))
    if source['status'] != 'ok' or source['daily_cap'] != .1 or source['new_fit_count'] != 48:
        raise ValueError('Require the completed fixed route-load experiment')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Seven raw sources changed')
    features_path = ROOT / source['feature_dataset']['path']
    scores_path = ROOT / source['score_export']['path']
    if sha256(features_path) != source['feature_dataset']['sha256'] or sha256(scores_path) != source['score_export']['sha256']:
        raise ValueError('Frozen route-load feature or score source changed')
    features = pd.read_csv(features_path, float_precision='round_trip', dtype={c: object for c in (
        *CATEGORICAL_FEATURES, 'state_route_promise_bin', 'state_route_promise_growth_bin')})
    for name in ('order_purchase_timestamp', 'prediction_time', 'label_available_time', 'training_outcome_known_time'):
        features[name] = pd.to_datetime(features[name])
    features = add_training_outcome_clock(features, pd.read_csv(data_dir / 'olist_orders_dataset.csv'))
    candidates = {c for trio in PAIRED_CANDIDATES.values() for c in trio}
    parts = []
    for chunk in pd.read_csv(scores_path, chunksize=200000, float_precision='round_trip'):
        part = chunk.loc[chunk.fold.eq('2017-12') & chunk.candidate.isin(candidates)]
        if len(part):
            parts.append(part)
    scores = pd.concat(parts, ignore_index=True)
    if scores.duplicated(['model_version', 'candidate', 'order_id']).any():
        raise ValueError('Duplicate score identities')
    scores['prediction_time'] = pd.to_datetime(scores.prediction_time)
    monthly = {m['month']: m for m in source['monthly_training']}
    fold = next(f for f in source['folds'] if f['name'] == '2017-12')
    report = {
        'format_version': 1, 'status': 'ok', 'analysis': 'paired_route_load_errors',
        'source_report': {'path': relative(source_path), 'sha256': sha256(source_path)},
        'source_features': {'path': relative(features_path), 'sha256': sha256(features_path)},
        'source_scores': {'path': relative(scores_path), 'sha256': sha256(scores_path)},
        'daily_cap': .1, 'historical_outcome_cutoff': CUTOFF.isoformat(),
        'new_fit_count': 0, 'new_model_selection': False,
        'frozen_december_selection': fold['experiment']['selected_models'][PRIMARY_SELECTION],
        'notes': [
            'Historical scores use their own month-start models and actual deliveries strictly before 2017-12-01.',
            'Unknown outcomes compete in complete closed daily batches before metric filtering.',
            'December is repeatedly inspected development evaluation, never an independent test or new selector input.',
            'Each family compares baseline, trend and cross at identical classifier settings and training identities.',
            'Route/promise top20 is a non-exhaustive list ordered by FN, with small-sample flags retained.',
            'Separate route and promise groups overlap; do not sum dimensions. Error overlap does not establish an ensemble.',
        ],
        'paired_candidates': {k: list(v) for k, v in PAIRED_CANDIDATES.items()}, 'months': {},
    }
    versions_checked = 0
    for month in MONTHS:
        frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
        if frame.empty or frame.order_id.isna().any() or frame.order_id.duplicated().any():
            raise ValueError('Require a complete monthly cohort with unique identities')
        historical = month != '2017-12'
        known = (frame.label_available_time < CUTOFF).to_numpy() if historical else np.ones(len(frame), dtype=bool)
        expected_fp = fold['order_id_fingerprints']['validation_full_by_month'][month] if historical else fold['order_id_fingerprints']['evaluation']
        if order_fingerprint(frame) != expected_fp:
            raise ValueError('Monthly identity fingerprint changed')
        values_by_candidate = {}
        for candidate in sorted(candidates):
            model_info = monthly[month]['models'][candidate]
            info = model_info['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Monthly model hash changed')
            artifact = joblib.load(path)
            numeric, categorical = feature_names(candidate)
            if (artifact['candidate'] != candidate or artifact['feature_names'] != numeric + categorical
                    or artifact['split'] != model_info['training_split']
                    or artifact['source_files'] != source['source_files']):
                raise ValueError('Monthly model feature or training provenance changed')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(frame, candidate))
            chosen = apply_alert_policy(frame, values, 0., .1, raw_scores=values)
            part = scores.loc[scores.model_version.eq(month) & scores.candidate.eq(candidate)]
            if len(part) != len(frame) or set(part.order_id) != set(frame.order_id):
                raise ValueError('Score ledger must preserve every monthly batch member')
            part = part.set_index('order_id').loc[frame.order_id]
            if not part.role.eq('validation' if historical else 'evaluation').all():
                raise ValueError('Score phase changed')
            np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
            np.testing.assert_array_equal(part.known_at_selection.to_numpy(), known if historical else np.zeros(len(frame), dtype=bool))
            np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
            np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], frame.delayed.to_numpy()[known])
            np.testing.assert_allclose(part.delay_score.to_numpy(), values, rtol=0, atol=1e-12)
            np.testing.assert_array_equal(part.predicted_delayed.to_numpy(), chosen)
            values_by_candidate[candidate] = values
            versions_checked += 1
        entry = {'role': 'historical_validation' if historical else 'development_evaluation',
                 'order_id_fingerprint': expected_fp, 'families': {}}
        for family, trio in PAIRED_CANDIDATES.items():
            full = analyze_month(frame, {c: values_by_candidate[c] for c in trio}, known)
            compact = {'models': {}, 'pairwise_comparisons': full['pairwise_comparisons'],
                       'delayed_overlap': full['delayed_overlap']}
            for candidate in trio:
                model = full['models'][candidate]
                aggregate = model['known_outcome_diagnostics']['aggregate']
                expected = fold['experiment']['models'][candidate]
                metrics = expected['validation_by_month'][month]['known_outcome_metrics'] if historical else expected['development_evaluation']
                _check_counts(aggregate['overall'], metrics)
                compact['models'][candidate] = {
                    'overall': aggregate['overall'], 'unknown_outcome_alerts': model['unknown_outcome_alerts'],
                    'state_route': aggregate['groups']['state_route'],
                    'promise_days': aggregate['groups']['promise_days'],
                    'route_by_promise_top20': aggregate['groups']['route_by_promise'][:20],
                    'daily_rank_bins': aggregate['daily_rank_bins'],
                }
            entry['families'][family] = compact
            entry['complete_batch'] = full['complete_batch']
        report['months'][month] = entry
        print(f'{month}: paired baseline/trend/cross diagnostics verified', flush=True)
    report['verification'] = {'saved_versions_replayed': versions_checked, 'score_rows_verified': len(scores)}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/route_load_interactions.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/route_load_diagnostics.json')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == args.source_report.resolve() or output.suffix.lower() != '.json':
        parser.error('Require a separate aggregate JSON output')
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding='utf-8'))
            own = isinstance(existing, dict) and existing.get('analysis') == 'paired_route_load_errors' and existing.get('format_version') == 1
        except (OSError, ValueError):
            own = False
        if not own:
            parser.error('Refusing to overwrite another existing report')
    report = build_report(args.source_report, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Wrote {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
