"""Compare pending-order context and daily rankers at a fixed daily 10% cap."""
from __future__ import annotations

import argparse
import gc
from importlib.metadata import version
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
from scripts.delay_budget_features import FEATURES as BUDGET_FEATURES, CATEGORICAL_FEATURES
from scripts.delay_budget_training import CAP, MIN_RECALL, PRIMARY_SELECTION, parameter_report, decide_ranking_fold, summarize
from scripts.delay_pending_features import FEATURE_SET, build_pending_delay_dataset
from scripts.delay_pending_training import (
    ROUND1_CANDIDATES, NEW_CANDIDATES, ALL_CANDIDATES, SELECTION_GROUPS,
    feature_names, prepare_input, make_candidate, fit_version,
)
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.diagnose_budget_misses import analyze_segments
from scripts.improve_budget_ranking import sha256, relative
from scripts.train_delay_model import LABEL_METADATA, positive_probability, source_manifest

DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--round1-report', type=Path, default=DEFAULT_OUTPUT / 'budget_ranking.json')
    parser.add_argument('--round1-scores', type=Path, default=ROOT / 'data/processed/olist_delay_budget_ranking_scores.csv')
    parser.add_argument('--round1-features', type=Path, default=ROOT / 'data/processed/olist_delay_budget_features.csv')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=4)
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error('Require n-jobs >= 1')
    previous = json.loads(args.round1_report.read_text(encoding='utf-8'))
    manifest = source_manifest(args.data_dir)
    if manifest != previous['source_files'] or previous['candidate_order'] != list(ROUND1_CANDIDATES):
        raise ValueError('Source data or first-round candidates changed')
    output = args.output_dir.resolve()
    data_dir = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    model_dir = ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models'
    version_dir = model_dir / 'pending_versions'
    for directory in (output, data_dir, version_dir):
        directory.mkdir(parents=True, exist_ok=True)
    policies = {**previous['policies'],
        'search': 'second round fixed five candidates; design informed by already-inspected development diagnoses; parameters fixed before new candidate evaluation',
        'features': 'unchanged 45 plus 15 pending workload features: valid past raw approvals regardless final status; delivery < query removes order; promised calendar end establishes overdue',
        'pending_limit': 'no cancellation timestamp available; approved cancelled orders can remain pending inside the 30/90-day windows; static master-table location assumption',
        'ranker': 'LambdaRank with binary gains [0,1], truncation 20; mature train rows grouped by approval calendar day; NDCG loss is a proxy, not exact variable daily recall@10% optimization',
        'probabilities': 'classifier scores uncalibrated; ranker sigmoid is a monotone numerical interface conversion, not probability calibration; reject saturation that collapses distinct margins',
        'comparison': 'round1_candidates replays identical first-round models and selector; new context and ranker groups expose different comparisons; candidate results after E are diagnostic only',
    }
    report = {'format_version': 1, 'status': 'ok', 'seed': 42, 'daily_cap': CAP,
        'minimum_validation_recall': MIN_RECALL, 'primary_selection_prespecified': PRIMARY_SELECTION,
        'candidate_order': list(ALL_CANDIDATES), 'new_candidate_order': list(NEW_CANDIDATES),
        'new_fit_count': len(previous['monthly_training']) * len(NEW_CANDIDATES),
        'reused_round1_version_count': len(previous['monthly_training']) * len(ROUND1_CANDIDATES),
        'source_files': manifest, 'source_round1_report_sha256': sha256(args.round1_report),
        'source_round1_scores_sha256': sha256(args.round1_scores),
        'source_round1_features_sha256': sha256(args.round1_features),
        'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib', 'xgboost', 'lightgbm')},
        'candidate_specifications': {c: {'numeric_features': feature_names(c)[0], 'categorical_features': feature_names(c)[1],
             'classifier_parameters': parameter_report(make_candidate(c, n_jobs=args.n_jobs).named_steps['classifier'].get_params(deep=False))} for c in NEW_CANDIDATES},
        'policies': policies,
        'old_primary_context': previous['old_primary_context'],
        'round1_primary_context': next(r for r in previous['summary'] if r['model_or_selection'] == PRIMARY_SELECTION),
        'monthly_training': [], 'folds': []}
    (output / 'pending_ranking_specification.json').write_text(json.dumps({k: report[k] for k in (
        'seed', 'daily_cap', 'minimum_validation_recall', 'primary_selection_prespecified',
        'candidate_order', 'candidate_specifications', 'policies')}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('Building pending workload features from verified raw approvals', flush=True)
    dataset = build_pending_delay_dataset(args.data_dir)
    old_features = pd.read_csv(args.round1_features, float_precision='round_trip', dtype={c: object for c in CATEGORICAL_FEATURES})
    if dataset.order_id.tolist() != old_features.order_id.tolist():
        raise ValueError('Pending context changed the labeled cohort/order')
    for column in BUDGET_FEATURES:
        if column in CATEGORICAL_FEATURES:
            same = dataset[column].fillna('<missing>').equals(old_features[column].fillna('<missing>'))
        else:
            same = np.allclose(dataset[column], old_features[column], rtol=0, atol=1e-12, equal_nan=True)
        if not same:
            raise ValueError(f'Pending context changed first-round feature: {column}')
    dataset.to_csv(data_dir / 'olist_delay_pending_features.csv', index=False)
    old_scores = pd.read_csv(args.round1_scores, float_precision='round_trip')
    cache = {}
    for old in previous['monthly_training']:
        month = old['month']
        splits, split_report = split_rolling_month(dataset, old['split']['model_fit_time'])
        if split_report != old['split']:
            raise ValueError('Second round changed train/scoring cohort')
        scoring = splits['scoring']
        cache[month] = {'frame': scoring, 'scores': {}, 'paths': {}}
        entry = {'month': month, 'split': split_report, 'models': {}}
        for candidate in ROUND1_CANDIDATES:
            info = old['models'][candidate]['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('First-round version hash mismatch')
            artifact = joblib.load(path)
            if artifact['split'] != split_report or artifact['candidate'] != candidate:
                raise ValueError('First-round metadata mismatch')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(scoring, candidate))
            comparison = old_scores.loc[(old_scores.model_version == month) & (old_scores.candidate == candidate)]
            replay = comparison.order_id.map(pd.Series(values, index=scoring.order_id)).to_numpy()
            if comparison.empty or not np.isfinite(replay).all() or not np.allclose(replay, comparison.delay_score, rtol=0, atol=1e-12):
                raise ValueError('First-round score replay mismatch')
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            entry['models'][candidate] = {'reused': True, 'version_artifact': info, 'scoring_rows': len(scoring), 'prior_score_rows_checked': len(comparison)}
            del artifact
        for candidate in NEW_CANDIDATES:
            print(f'{month}: fitting {candidate}', flush=True)
            pipeline, values, fit_report = fit_version(splits['train'], scoring, candidate, n_jobs=args.n_jobs)
            numeric, categorical = feature_names(candidate)
            artifact = {'pipeline': pipeline, 'candidate': candidate, 'split': split_report,
                'feature_names': numeric + categorical, 'source_files': manifest, 'fit': fit_report}
            path = version_dir / f'olist_delay_{month}_{candidate}.joblib'
            joblib.dump(artifact, path, compress=3)
            entry['models'][candidate] = {'reused': False, **fit_report,
                'version_artifact': {'path': relative(path), 'sha256': sha256(path)}, 'scoring_rows': len(scoring)}
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            del pipeline, artifact
            gc.collect()
        report['monthly_training'].append(entry)
        print(f'{month}: fifteen candidates ready', flush=True)
    score_rows, selected_frames, selected_predictions, selected_values = [], [], [], []
    for old in previous['folds']:
        name, schedule = old['name'], old['schedule']
        months = [m['month'] for m in schedule['validation_months']]
        validation = [cache[m]['frame'].reset_index(drop=True) for m in months]
        audits = [mature_validation_month(f, schedule['evaluation_start'])[1] for f in validation]
        evaluation = cache[name]['frame'].reset_index(drop=True)
        if order_fingerprint(evaluation) != old['order_id_fingerprints']['evaluation']:
            raise ValueError('Development evaluation identities changed')
        def phase_scores(frame):
            month = frame.prediction_time.dt.strftime('%Y-%m').iloc[0]
            return {c: frame.order_id.map(cache[month]['scores'][c]).to_numpy() for c in ALL_CANDIDATES}
        validation_scores, evaluation_scores = [phase_scores(f) for f in validation], phase_scores(evaluation)
        experiment = decide_ranking_fold(validation, validation_scores, evaluation, evaluation_scores,
            schedule['evaluation_start'], candidate_order=ALL_CANDIDATES, selection_groups=SELECTION_GROUPS)
        candidate = experiment['selected_models'][PRIMARY_SELECTION]
        decision = experiment['models'][candidate]
        numeric, categorical = feature_names(candidate)
        base = joblib.load(cache[name]['paths'][candidate])
        feature_set = FEATURE_SET if candidate in NEW_CANDIDATES and candidate != 'lambdarank_budget' else (
            'seller_route_budget_90d' if candidate == 'lambdarank_budget' or (candidate in ROUND1_CANDIDATES and not candidate.endswith(('_route', '_static'))) else (
            'route_promise_90d' if candidate.endswith('_route') else 'approval_static'))
        artifact = {'format_version': 1, 'selected_model': candidate, 'feature_set': feature_set,
            'pipeline': base['pipeline'], 'threshold': 0., 'daily_alert_cap': CAP,
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**policies, 'research_only': True,
                'schedule': schedule, 'final_split': base['split'], 'source_files': manifest, 'versions': report['versions'],
                'complete_daily_batches_required': True, 'validation_minimum_recall': decision['minimum_validation_month_recall'],
                'historical_floor_met': decision['all_validation_months_meet_30_percent'],
                'base_version_artifact': {'path': relative(cache[name]['paths'][candidate]), 'sha256': sha256(cache[name]['paths'][candidate])}}}
        path = model_dir / f'olist_delay_pending_ranking_{name}.joblib'
        joblib.dump(artifact, path, compress=3)
        report['folds'].append({'name': name, 'schedule': schedule, 'validation_maturity': audits,
            'order_id_fingerprints': old['order_id_fingerprints'],
            'experiment': experiment, 'research_artifact': {'path': relative(path), 'sha256': sha256(path)}})
        primary_scores = evaluation_scores[candidate]
        selected_frames.append(evaluation)
        selected_predictions.append(apply_alert_policy(evaluation, primary_scores, 0., CAP, raw_scores=primary_scores))
        selected_values.append(primary_scores)
        for candidate in ALL_CANDIDATES:
            for role, frame, values in [*(('validation', f, s[candidate]) for f, s in zip(validation, validation_scores, strict=True)),
                                       ('evaluation', evaluation, evaluation_scores[candidate])]:
                known = (frame.label_available_time < pd.Timestamp(schedule['evaluation_start'])).to_numpy() if role == 'validation' else np.zeros(len(frame), dtype=bool)
                part = frame[['order_id', 'prediction_time']].copy()
                part['fold'], part['role'], part['candidate'] = name, role, candidate
                part['model_version'] = frame.prediction_time.dt.strftime('%Y-%m')
                part['known_at_selection'] = known
                part['outcome_for_metrics'] = np.where(known, frame.delayed, np.nan) if role == 'validation' else frame.delayed.to_numpy()
                part['delay_score'] = values
                part['predicted_delayed'] = apply_alert_policy(frame, values, 0., CAP, raw_scores=values).astype(int)
                score_rows.append(part)
        print(f'{name}: selected={experiment["selected_models"][PRIMARY_SELECTION]}; min validation recall={decision["minimum_validation_month_recall"]:.4f}; development recall={decision["development_evaluation"]["recall"]:.4f}', flush=True)
    report['summary'] = summarize(report['folds'], candidate_order=ALL_CANDIDATES, selection_groups=SELECTION_GROUPS)
    report['selected_development_miss_diagnostics'] = analyze_segments(pd.concat(selected_frames, ignore_index=True),
        np.concatenate(selected_predictions), np.concatenate(selected_values))
    primary = next(r for r in report['summary'] if r['model_or_selection'] == PRIMARY_SELECTION)
    report['suitability'] = {'historical_validation_floor_met_in_all_folds': not primary['validation_folds_below_30_percent'],
        'observed_development_months_all_above_30_percent': primary['minimum_development_month_recall'] >= MIN_RECALL,
        'independent_future_test_available': False, 'automatic_promotion': False,
        'note': 'Development results are post-selection observations. The experiment design has seen these development periods; none is a new independent test.'}
    pd.concat(score_rows, ignore_index=True).to_csv(data_dir / 'olist_delay_pending_ranking_scores.csv', index=False)
    path = output / 'pending_ranking.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    print(json.dumps(primary, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
