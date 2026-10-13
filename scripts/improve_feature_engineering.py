"""Paired feature-engineering contrasts at a fixed daily ten-percent budget."""
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
from scripts.delay_engineering_features import (
    build_engineering_delay_dataset, GEO_FILENAME, CATEGORICAL_FEATURES,
    BASE_NUMERIC_FEATURES, INTERACTION_NUMERIC_FEATURES,
)
from scripts.delay_engineering_training import (
    PREVIOUS_CANDIDATES, NEW_CANDIDATES, ALL_CANDIDATES, SELECTION_GROUPS,
    PRIMARY_SELECTION, BASE_CANDIDATES, GEO_CANDIDATES, DISPATCH_CANDIDATES,
    feature_names, prepare_input, make_candidate, fit_version, feature_set,
)
from scripts.delay_budget_training import CAP, MIN_RECALL, parameter_report, decide_ranking_fold, summarize
from scripts.delay_outcome_clock import add_training_outcome_clock, split_outcome_training_month
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.diagnose_budget_misses import analyze_segments
from scripts.improve_budget_ranking import sha256, relative
from scripts.train_delay_model import LABEL_METADATA, positive_probability, source_manifest

DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def engineering_source_manifest(raw_dir):
    path = Path(raw_dir) / GEO_FILENAME
    return sorted(source_manifest(raw_dir) + [{'filename': path.name, 'bytes': path.stat().st_size,
                                             'sha256': sha256(path)}], key=lambda item: item['filename'])


def paired_comparisons(folds, summary):
    """Fixed family contrasts, not a selection based on development performance."""
    indexed = {r['model_or_selection']: r for r in summary}
    result = []
    for base, geo, dispatch in zip(BASE_CANDIDATES, GEO_CANDIDATES, DISPATCH_CANDIDATES, strict=True):
        result.append({'family': geo.removesuffix('_engineering_geo'),
            'candidates': {'base60': base, 'geo_interactions83': geo, 'with_dispatch91': dispatch},
            'development_recall': {label: indexed[c]['recall'] for label, c in
                (('base60', base), ('geo_interactions83', geo), ('with_dispatch91', dispatch))},
            'geo_minus_base_development_recall': indexed[geo]['recall'] - indexed[base]['recall'],
            'dispatch_minus_geo_development_recall': indexed[dispatch]['recall'] - indexed[geo]['recall'],
            'by_fold': {fold['name']: {label: {
                'historical_minimum_recall': fold['experiment']['models'][c]['minimum_validation_month_recall'],
                'historical_true_positives': fold['experiment']['models'][c]['validation_true_positives'],
                'development': fold['experiment']['models'][c]['development_evaluation'],
            } for label, c in (('base60', base), ('geo_interactions83', geo), ('with_dispatch91', dispatch))}
                for fold in folds}})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--previous-report', type=Path, default=DEFAULT_OUTPUT / 'outcome_clock.json')
    parser.add_argument('--previous-scores', type=Path, default=ROOT / 'data/processed/olist_delay_outcome_clock_scores.csv')
    parser.add_argument('--previous-features', type=Path, default=ROOT / 'data/processed/olist_delay_outcome_features.csv')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=4)
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error('Require n-jobs >= 1')
    previous = json.loads(args.previous_report.read_text(encoding='utf-8'))
    manifest = engineering_source_manifest(args.data_dir)
    if source_manifest(args.data_dir) != previous['source_files'] or previous['candidate_order'] != list(PREVIOUS_CANDIDATES):
        raise ValueError('Prior six-source data or candidate order changed')
    output = args.output_dir.resolve()
    data_dir = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    model_dir = ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models'
    version_dir = model_dir / 'engineering_versions'
    for directory in (output, data_dir, version_dir):
        directory.mkdir(parents=True, exist_ok=True)
    policies = {**previous['policies'],
        'fit': 'new variants use identical monthly deadline-clock wait0 training IDs and sorted row order; train-only preprocessing',
        'search': 'four fixed families crossed with base60 / geo+interactions83 / dispatch91; reuse existing deadline0 LGB base, eleven new candidates, no early stopping or evaluation-based hyperparameter search',
        'features': 'nine static postal features and fourteen deterministic interactions; dispatch adds eight deadline features; no full-period target encoding',
        'paired_comparison': 'base60 versus geo+interactions83 measures the combined package; dispatch91 versus83 is an availability sensitivity; within each family classifier parameters and training cohort are identical',
        'geolocation': 'seventh file treated as static postal reference available at approval; paired-valid-coordinate per-ZIP median, great-circle distance not road distance; no as-of version metadata or result-based coordinate clipping',
        'dispatch_availability': 'shipping_limit_date has no creation/revision timestamp; dispatch variants require unverified approval-time availability and are excluded from primary selection',
        'primary_selection': 'primary_without_dispatch uses prior24 + newbase3 + geo4; all_including_dispatch is sensitivity only; selections use three historical months only',
        'evaluation_role': 'all evaluation months and overall design have been informed by repeatedly inspected development data; specification is frozen before this run, not an independent test or independent experimental design',
        'ranker': 'no new rankers in feature-engineering round; old candidates remain frozen',
    }
    report = {'format_version': 1, 'status': 'ok', 'seed': 42, 'daily_cap': CAP,
        'minimum_validation_recall': MIN_RECALL, 'primary_selection_prespecified': PRIMARY_SELECTION,
        'candidate_order': list(ALL_CANDIDATES), 'new_candidate_order': list(NEW_CANDIDATES),
        'selection_groups': {name: list(values) for name, values in SELECTION_GROUPS.items()},
        'new_fit_count': len(previous['monthly_training']) * len(NEW_CANDIDATES),
        'reused_previous_version_count': len(previous['monthly_training']) * len(PREVIOUS_CANDIDATES),
        'source_files': manifest, 'source_previous_report_sha256': sha256(args.previous_report),
        'source_previous_scores_sha256': sha256(args.previous_scores),
        'source_previous_features_sha256': sha256(args.previous_features),
        'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib', 'xgboost', 'lightgbm')},
        'candidate_specifications': {c: {'numeric_features': feature_names(c)[0], 'categorical_features': feature_names(c)[1],
            'classifier_parameters': parameter_report(make_candidate(c, n_jobs=args.n_jobs).named_steps['classifier'].get_params(deep=False))} for c in NEW_CANDIDATES},
        'policies': policies, 'previous_primary_context': next(r for r in previous['summary'] if r['model_or_selection'] == 'all_candidates'),
        'interaction_features': INTERACTION_NUMERIC_FEATURES, 'monthly_training': [], 'folds': []}
    specification_path = output / 'feature_engineering_specification.json'
    specification_path.write_text(json.dumps({k: report[k] for k in (
        'seed', 'daily_cap', 'minimum_validation_recall', 'primary_selection_prespecified', 'candidate_order',
        'new_candidate_order', 'selection_groups', 'candidate_specifications', 'policies', 'source_files')},
        ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    report['specification_sha256'] = sha256(specification_path)
    print('Building 91 features and verifying all prior 60 values and cohort identities', flush=True)
    dataset = build_engineering_delay_dataset(args.data_dir)
    original = pd.read_csv(args.previous_features, float_precision='round_trip', dtype={c: object for c in CATEGORICAL_FEATURES})
    for column in ('order_purchase_timestamp', 'prediction_time', 'label_available_time'):
        original[column] = pd.to_datetime(original[column])
    preserved = ['order_id', 'order_purchase_timestamp', 'prediction_time', 'label_available_time', 'delayed'] + list(BASE_NUMERIC_FEATURES) + list(CATEGORICAL_FEATURES)
    pd.testing.assert_frame_equal(dataset[preserved], original[preserved], check_dtype=False, check_exact=True)
    dataset = add_training_outcome_clock(dataset, pd.read_csv(args.data_dir / 'olist_orders_dataset.csv'))
    if not np.array_equal(dataset.training_outcome_known_time.to_numpy(dtype='datetime64[ns]'),
                          pd.to_datetime(original.training_outcome_known_time).to_numpy(dtype='datetime64[ns]')):
        raise ValueError('Training outcome clock changed')
    feature_path = data_dir / 'olist_delay_engineering_features.csv'
    dataset.to_csv(feature_path, index=False)
    report['feature_dataset'] = {'rows': len(dataset), 'base_values_verified': len(dataset) * 60,
        'metadata_columns_preserved': preserved[:5], 'path': relative(feature_path), 'sha256': sha256(feature_path)}
    old_scores = pd.read_csv(args.previous_scores, float_precision='round_trip')
    cache = {}
    for old in previous['monthly_training']:
        month = old['month']
        splits, split_report = split_rolling_month(dataset, old['split']['model_fit_time'])
        if split_report != old['split']:
            raise ValueError('Previous monthly cohort changed')
        scoring = splits['scoring']
        new_splits, training_split = split_outcome_training_month(dataset, old['split']['model_fit_time'], wait_days=0, clock='deadline')
        if new_splits['scoring'].order_id.tolist() != scoring.order_id.tolist():
            raise ValueError('Training design changed scoring cohort')
        cache[month] = {'frame': scoring, 'scores': {}, 'paths': {}}
        entry = {'month': month, 'split': split_report, 'models': {}}
        for candidate in PREVIOUS_CANDIDATES:
            prior = old['models'][candidate]
            info = prior['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Prior version hash mismatch')
            artifact = joblib.load(path)
            expected_split = prior.get('training_split', split_report)
            if artifact['split'] != expected_split or artifact['candidate'] != candidate:
                raise ValueError('Prior version provenance mismatch')
            if 'source_files' in artifact:
                if artifact['source_files'] != previous['source_files']:
                    raise ValueError('Prior version source mismatch')
            elif candidate not in PREVIOUS_CANDIDATES[:4]:
                raise ValueError('Only the four original legacy candidates may lack embedded source manifests')
            if candidate == 'lightgbm_pending__deadline_wait0' and artifact['split'] != training_split:
                raise ValueError('Reused LGB base does not match paired training cohort')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(scoring, candidate))
            comparison = old_scores.loc[(old_scores.model_version == month) & (old_scores.candidate == candidate)]
            replay = comparison.order_id.map(pd.Series(values, index=scoring.order_id)).to_numpy()
            if comparison.empty or not np.isfinite(replay).all() or not np.allclose(replay, comparison.delay_score, rtol=0, atol=1e-12):
                raise ValueError('Prior score replay mismatch')
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            entry['models'][candidate] = {'reused': True, 'version_artifact': info, 'scoring_rows': len(scoring),
                'training_split': expected_split, 'prior_score_rows_checked': len(comparison),
                'source_manifest_embedded': 'source_files' in artifact}
            del artifact
        for candidate in NEW_CANDIDATES:
            print(f'{month}: fitting {candidate}', flush=True)
            pipeline, values, fit_report = fit_version(new_splits['train'], scoring, candidate, n_jobs=args.n_jobs)
            numeric, categorical = feature_names(candidate)
            artifact = {'pipeline': pipeline, 'candidate': candidate, 'split': training_split,
                'feature_names': numeric + categorical, 'source_files': manifest, 'fit': fit_report,
                'feature_set': feature_set(candidate), 'geolocation_used': candidate not in BASE_CANDIDATES}
            path = version_dir / f'olist_delay_{month}_{candidate}.joblib'
            joblib.dump(artifact, path, compress=3)
            entry['models'][candidate] = {'reused': False, **fit_report, 'training_split': training_split,
                'version_artifact': {'path': relative(path), 'sha256': sha256(path)}, 'scoring_rows': len(scoring)}
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            del pipeline, artifact
            gc.collect()
        report['monthly_training'].append(entry)
        print(f'{month}: thirty-five candidates ready', flush=True)
    del old_scores
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
        artifact = {'format_version': 1, 'selected_model': candidate, 'feature_set': feature_set(candidate),
            'pipeline': base['pipeline'], 'threshold': 0., 'daily_alert_cap': CAP,
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**policies, 'research_only': True,
                'schedule': schedule, 'final_split': base['split'], 'source_files': manifest, 'versions': report['versions'],
                'complete_daily_batches_required': True, 'validation_minimum_recall': decision['minimum_validation_month_recall'],
                'historical_floor_met': decision['all_validation_months_meet_30_percent'],
                'base_version_artifact': {'path': relative(cache[name]['paths'][candidate]), 'sha256': sha256(cache[name]['paths'][candidate])}}}
        path = model_dir / f'olist_delay_feature_engineering_{name}.joblib'
        joblib.dump(artifact, path, compress=3)
        report['folds'].append({'name': name, 'schedule': schedule, 'validation_maturity': audits,
            'order_id_fingerprints': old['order_id_fingerprints'], 'experiment': experiment,
            'research_artifact': {'path': relative(path), 'sha256': sha256(path)}})
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
        print(f'{name}: selected={experiment["selected_models"][PRIMARY_SELECTION]}; min historical recall={decision["minimum_validation_month_recall"]:.4f}; development recall={decision["development_evaluation"]["recall"]:.4f}', flush=True)
    report['summary'] = summarize(report['folds'], candidate_order=ALL_CANDIDATES, selection_groups=SELECTION_GROUPS)
    report['paired_feature_comparisons'] = paired_comparisons(report['folds'], report['summary'])
    report['selected_development_miss_diagnostics'] = analyze_segments(pd.concat(selected_frames, ignore_index=True),
        np.concatenate(selected_predictions), np.concatenate(selected_values))
    primary = next(r for r in report['summary'] if r['model_or_selection'] == PRIMARY_SELECTION)
    report['suitability'] = {'historical_validation_floor_met_in_all_folds': not primary['validation_folds_below_30_percent'],
        'observed_development_months_all_above_30_percent': primary['minimum_development_month_recall'] >= MIN_RECALL,
        'independent_future_test_available': False, 'automatic_promotion': False,
        'note': 'Development observations and experimental design have seen these periods; none is a new independent test.'}
    score_path = data_dir / 'olist_delay_engineering_scores.csv'
    pd.concat(score_rows, ignore_index=True).to_csv(score_path, index=False)
    report['score_export'] = {'path': relative(score_path), 'rows': sum(len(f) for f in score_rows), 'sha256': sha256(score_path)}
    path = output / 'feature_engineering.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    print(json.dumps(primary, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
