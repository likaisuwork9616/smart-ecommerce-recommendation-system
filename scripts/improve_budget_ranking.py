"""Train predeclared ranking candidates at a fixed ten-percent daily budget."""
from __future__ import annotations

import argparse
import gc
import hashlib
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
from scripts.delay_budget_features import FEATURE_SET, build_budget_delay_dataset
from scripts.delay_budget_training import (
    LEGACY_CANDIDATES, NEW_CANDIDATES, ALL_CANDIDATES, PRIMARY_SELECTION,
    CAP, MIN_RECALL, feature_names, prepare_input, make_candidate,
    fit_version, decide_ranking_fold, summarize, parameter_report,
)
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.diagnose_budget_misses import analyze_segments
from scripts.train_delay_model import LABEL_METADATA, positive_probability, source_manifest

DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--rolling-report', type=Path, default=DEFAULT_OUTPUT / 'monthly_retraining.json')
    parser.add_argument('--baseline-report', type=Path, default=DEFAULT_OUTPUT / 'calibration_budget.json')
    parser.add_argument('--baseline-scores', type=Path, default=ROOT / 'data/processed/olist_delay_rolling_scores.csv')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=4)
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error('Require n-jobs >= 1')
    rolling = json.loads(args.rolling_report.read_text(encoding='utf-8'))
    baseline = json.loads(args.baseline_report.read_text(encoding='utf-8'))
    manifest = source_manifest(args.data_dir)
    if manifest != rolling['source_files'] or manifest != baseline['source_files']:
        raise ValueError('Source data differs from earlier experiments')
    if sha256(args.rolling_report) != baseline['source_rolling_report_sha256']:
        raise ValueError('Baseline references a different rolling report')
    if sha256(args.baseline_scores) != baseline['source_rolling_scores_sha256']:
        raise ValueError('Old OOT score cache hash mismatch')
    output = args.output_dir.resolve()
    data_dir = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    model_dir = ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models'
    version_dir = model_dir / 'budget_versions'
    for directory in (output, data_dir, version_dir):
        directory.mkdir(parents=True, exist_ok=True)
    report = {'format_version': 1, 'status': 'ok', 'seed': 42, 'daily_cap': CAP,
        'minimum_validation_recall': MIN_RECALL, 'primary_selection_prespecified': PRIMARY_SELECTION,
        'candidate_order': list(ALL_CANDIDATES), 'new_candidate_order': list(NEW_CANDIDATES),
        'new_fit_count': len(rolling['monthly_training']) * len(NEW_CANDIDATES),
        'reused_legacy_version_count': len(rolling['monthly_training']) * len(LEGACY_CANDIDATES),
        'source_files': manifest, 'source_rolling_report_sha256': sha256(args.rolling_report),
        'source_baseline_report_sha256': sha256(args.baseline_report),
        'source_baseline_scores_sha256': sha256(args.baseline_scores),
        'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib', 'xgboost', 'lightgbm')},
        'candidate_specifications': {c: {'numeric_features': feature_names(c)[0], 'categorical_features': feature_names(c)[1],
             'classifier_parameters': parameter_report(make_candidate(c, n_jobs=args.n_jobs).named_steps['classifier'].get_params(deep=False))} for c in NEW_CANDIDATES},
        'policies': {
            'fit': 'each month M: approvals strictly before M-60 days and labels strictly before M; train-only preprocessing',
            'historical_scores': 'each historical month uses its own monthly model; never final-model rescores of training rows',
            'ranking': 'uncalibrated score descending then order_id ascending; threshold zero, fill daily floor(10% * complete eligible scored batch)',
            'label_maturity': 'historical validation outcomes strictly before E; unknown labels still compete for full-batch slots',
            'selection': 'maximize worst recall of three known-label historical months, then pooled TP, pooled raw AP, fixed candidate order',
            'floor': '30% each historical month is a diagnostic suitability gate; no future recall guarantee',
            'search': 'six predefined candidate/feature combinations and fixed parameters; no evaluation-based early stopping or parameter choice',
            'comparison': 'legacy_candidates applies same new selector to old four models; old primary shown separately; changing selection and models is not a pure feature effect',
            'features': 'seller/route history uses deliveries strictly before query approval, 90-day window; seller ID and ZIP3 from static master tables',
            'probabilities': 'ranking scores uncalibrated; no new calibration fit or reliable probability claim',
            'evaluation_role': 'previously inspected development months only; earlier evaluation can enter later historical validation',
            'holdout': 'original 2018-05-26 onward period not scored',
            'coverage': 'eligible valid eventually-delivered cohort only; not every originally approved order',
            'batch_timing': 'complete closed calendar-day batches required; up to one day wait; no per-order online cap guarantee',
            'promotion': 'new artifacts remain research only; original and prior research models preserved',
            'visualization': 'no dashboard or new plots in this experiment; user requested ranking work first',
        },
        'old_primary_context': {'summary': next(r for r in baseline['summary'] if r['method'] == 'sigmoid' and r['budget'] == 'cap_10' and r['model'] == 'validation_selected'),
            'by_fold': [{'name': f['name'], 'candidate': f['experiment']['selected_models']['sigmoid']['cap_10'],
                         'evaluation': f['experiment']['models'][f['experiment']['selected_models']['sigmoid']['cap_10']]['sigmoid']['strategies']['cap_10']['evaluation']} for f in baseline['folds']]},
        'monthly_training': [], 'folds': []}
    # Save the declaration before any new evaluation is computed.
    (output / 'budget_ranking_specification.json').write_text(json.dumps({k: report[k] for k in (
        'seed', 'daily_cap', 'minimum_validation_recall', 'primary_selection_prespecified',
        'candidate_order', 'candidate_specifications', 'policies')}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('Building point-in-time seller/route/ZIP features from verified raw data', flush=True)
    dataset = build_budget_delay_dataset(args.data_dir)
    dataset.to_csv(data_dir / 'olist_delay_budget_features.csv', index=False)
    old_scores = pd.read_csv(args.baseline_scores, float_precision='round_trip')
    cache = {}
    for old in rolling['monthly_training']:
        month = old['month']
        splits, split_report = split_rolling_month(dataset, old['split']['model_fit_time'])
        if split_report != old['split']:
            raise ValueError('New features changed the baseline train/scoring cohort')
        scoring = splits['scoring']
        cache[month] = {'frame': scoring, 'scores': {}, 'paths': {}}
        entry = {'month': month, 'split': split_report, 'models': {}}
        for candidate in LEGACY_CANDIDATES:
            info = old['models'][candidate]['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Legacy model hash mismatch')
            artifact = joblib.load(path)
            if artifact['split'] != split_report or artifact['candidate'] != candidate:
                raise ValueError('Legacy metadata mismatch')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(scoring, candidate))
            comparison = old_scores.loc[(old_scores.model_version == month) & (old_scores.candidate == candidate)]
            replay = comparison.order_id.map(pd.Series(values, index=scoring.order_id)).to_numpy()
            if comparison.empty or not np.isfinite(replay).all() or not np.allclose(replay, comparison.delay_score, rtol=0, atol=1e-12):
                raise ValueError('Legacy OOT score replay mismatch')
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            entry['models'][candidate] = {'reused': True, 'version_artifact': info, 'scoring_rows': len(scoring), 'prior_score_rows_checked': len(comparison)}
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
        print(f'{month}: ten candidates ready', flush=True)
    score_rows, selected_frames, selected_predictions, selected_values = [], [], [], []
    for previous in rolling['folds']:
        name, schedule = previous['name'], previous['schedule']
        months = [m['month'] for m in schedule['validation_months']]
        validation = [cache[m]['frame'].reset_index(drop=True) for m in months]
        audits = [mature_validation_month(f, schedule['evaluation_start'])[1] for f in validation]
        evaluation = cache[name]['frame'].reset_index(drop=True)
        if order_fingerprint(evaluation) != previous['order_id_fingerprints']['evaluation']:
            raise ValueError('Development evaluation identities changed')
        def phase_scores(frame):
            month = frame.prediction_time.dt.strftime('%Y-%m').iloc[0]
            return {c: frame.order_id.map(cache[month]['scores'][c]).to_numpy() for c in ALL_CANDIDATES}
        validation_scores = [phase_scores(frame) for frame in validation]
        evaluation_scores = phase_scores(evaluation)
        experiment = decide_ranking_fold(validation, validation_scores, evaluation, evaluation_scores, schedule['evaluation_start'])
        candidate = experiment['selected_models'][PRIMARY_SELECTION]
        decision = experiment['models'][candidate]
        numeric, categorical = feature_names(candidate)
        base = joblib.load(cache[name]['paths'][candidate])
        feature_set = FEATURE_SET if candidate in NEW_CANDIDATES and not candidate.endswith('_route') else ('route_promise_90d' if candidate.endswith('_route') else 'approval_static')
        artifact = {'format_version': 1, 'selected_model': candidate, 'feature_set': feature_set,
            'pipeline': base['pipeline'], 'threshold': 0., 'daily_alert_cap': CAP,
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**report['policies'], 'research_only': True,
                'schedule': schedule, 'final_split': base['split'], 'source_files': manifest, 'versions': report['versions'],
                'complete_daily_batches_required': True, 'validation_minimum_recall': decision['minimum_validation_month_recall'],
                'historical_floor_met': decision['all_validation_months_meet_30_percent'],
                'base_version_artifact': {'path': relative(cache[name]['paths'][candidate]), 'sha256': sha256(cache[name]['paths'][candidate])}}}
        path = model_dir / f'olist_delay_budget_ranking_{name}.joblib'
        joblib.dump(artifact, path, compress=3)
        report['folds'].append({'name': name, 'schedule': schedule, 'validation_maturity': audits,
            'order_id_fingerprints': {'validation_full_by_month': {m: order_fingerprint(f) for m, f in zip(months, validation, strict=True)},
                                     'evaluation': order_fingerprint(evaluation)},
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
    report['summary'] = summarize(report['folds'])
    report['selected_development_miss_diagnostics'] = analyze_segments(pd.concat(selected_frames, ignore_index=True),
        np.concatenate(selected_predictions), np.concatenate(selected_values))
    primary = next(r for r in report['summary'] if r['model_or_selection'] == PRIMARY_SELECTION)
    report['suitability'] = {'historical_validation_floor_met_in_all_folds': not primary['validation_folds_below_30_percent'],
        'observed_development_months_all_above_30_percent': primary['minimum_development_month_recall'] >= MIN_RECALL,
        'independent_future_test_available': False, 'automatic_promotion': False,
        'note': 'Historical floor is the selection gate. Development stability is a post-selection observation, not independent validation or a reason to pick a different candidate.'}
    pd.concat(score_rows, ignore_index=True).to_csv(data_dir / 'olist_delay_budget_ranking_scores.csv', index=False)
    path = output / 'budget_ranking.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    print(json.dumps(primary, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
