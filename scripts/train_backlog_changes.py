"""Compare 7/14-day overdue backlog changes at a fixed daily 10% budget."""
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
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.delay_features import load_olist_tables
from scripts.delay_backlog_features import add_backlog_features, ADDED_FEATURES
from scripts.delay_backlog_training import (
    BACKBONES, CANDIDATE_DESIGNS, PREVIOUS_CANDIDATES, NEW_CANDIDATES, ALL_CANDIDATES,
    SELECTION_GROUPS, PRIMARY_SELECTION, candidate_design,
    feature_names, prepare_input, make_candidate, fit_version, feature_set,
)
from scripts import delay_route_load_training as previous_training
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.delay_budget_training import CAP, MIN_RECALL, parameter_report, decide_ranking_fold, summarize
from scripts.delay_outcome_clock import add_training_outcome_clock, split_outcome_training_month
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.diagnose_budget_misses import analyze_segments
from scripts.improve_budget_ranking import sha256, relative
from scripts.train_delay_model import LABEL_METADATA, positive_probability

DEFAULT_OUTPUT = ROOT / 'reports/stage4'
FEATURE_DEFINITION = {
    'raw_population': 'All raw valid purchase/approval orders with approval >= purchase, including cancelled/unfinished orders; final status and target never read.',
    'snapshot': 'At s: approval in [s-90days,s), original promise calendar midnight+1day <= s, actual delivery missing or >= s. Delivery exactly s is still unknown; missing promise cannot establish overdue.',
    'snapshots': ['t', 't-7days', 't-14days'],
    'groups': ['global', 'primary_seller_id', 'primary_seller_state -> customer_state'],
    'features_per_group_per_lag': {'lag': 'B(t-lag)', 'change': 'B(t)-B(t-lag)', 'log_growth': 'log1p(B(t))-log1p(B(t-lag))'},
    'added_features': list(ADDED_FEATURES),
    'variants': {'7d': '9 numeric features', '14d': '9 numeric features', '7_14d': '18 numeric features'},
    'boundaries': 'Approval strictly before each snapshot, delivery strictly before it removes pending status; promise expiry and 90day lower approval boundary inclusive.',
    'missing': 'Known groups without eligible overdue orders have count/growth/change0; unknown seller/route or missing query time stays missing; no unknown-key pooling.',
    'current_count_check': 'Current B(t) independently recomputed and must equal each existing frozen pending_overdue_90d count on known query groups.',
    'preprocessing': 'Corresponding frozen backbone parameters/rows/sort and train-only numeric median/indicators, Logistic StandardScaler and categorical most-frequent/OHE min_frequency20 unchanged.',
    'availability': 'Assumes timely approval/delivery records, original promise, static states and primary seller/item information; no ingestion/revision timestamps. Geographic reference assumption unchanged for XGBoost.',
    'limitations': 'No cancellation timestamps, so cancelled approvals may remain pending; moving90day window can reduce backlog by age-out rather than delivery. Eligible labels remain eventually-delivered retrospective cohort.',
    'contrast': 'Each lag package added directly to original load65 or geo83 backbone; no arrival-trend/cross additions to new candidates, no new C/grid/calibration/threshold.',
}


def paired_comparisons(folds, summary):
    indexed = {row['model_or_selection']: row for row in summary}
    result = []
    for name, (baseline, _) in BACKBONES.items():
        cells = {'baseline': baseline, **{v: f'{name}_backlog_{v}' for v in ('7d', '14d', '7_14d')}}
        recall = {label: indexed[c]['recall'] for label,c in cells.items()}
        result.append({'backbone': name, 'candidates': cells,
            'development_recall': recall,
            'development_true_positives': {label: indexed[c]['true_positives'] for label,c in cells.items()},
            'development_recall_contrasts': {**{v+'_minus_baseline': recall[v]-recall['baseline'] for v in ('7d','14d','7_14d')},
                'combined_minus_7d': recall['7_14d']-recall['7d'], 'combined_minus_14d': recall['7_14d']-recall['14d']},
            'by_fold': {f['name']: {label: {
                'historical_minimum_recall': f['experiment']['models'][c]['minimum_validation_month_recall'],
                'historical_true_positives': f['experiment']['models'][c]['validation_true_positives'],
                'validation_by_month': f['experiment']['models'][c]['validation_by_month'],
                'development': f['experiment']['models'][c]['development_evaluation'],
            } for label,c in cells.items()} for f in folds}})
    return result


def verify_prior_score_part(comparison, part):
    """Prove exact cohort, maturity, labels and alert decisions in the frozen ledger."""
    if comparison.order_id.isna().any() or comparison.order_id.duplicated().any():
        raise ValueError('Prior score phase requires unique identities')
    if set(comparison.order_id) != set(part.order_id):
        raise ValueError('Prior score phase cohort mismatch')
    expected = part.set_index('order_id').sort_index()
    actual = comparison.set_index('order_id').sort_index()
    if not np.array_equal(pd.to_datetime(actual.prediction_time).to_numpy(), expected.prediction_time.to_numpy()):
        raise ValueError('Prior score prediction time changed')
    for column in ('fold', 'role', 'candidate', 'model_version', 'known_at_selection', 'predicted_delayed'):
        if not np.array_equal(actual[column].to_numpy(), expected[column].to_numpy()):
            raise ValueError(f'Prior score phase changed: {column}')
    for column in ('outcome_for_metrics', 'delay_score'):
        if not np.allclose(actual[column], expected[column], rtol=0, atol=1e-12, equal_nan=True):
            raise ValueError(f'Prior score phase changed: {column}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--previous-report', type=Path, default=DEFAULT_OUTPUT / 'route_load_interactions.json')
    parser.add_argument('--previous-scores', type=Path, default=ROOT / 'data/processed/olist_delay_route_load_scores.csv')
    parser.add_argument('--previous-features', type=Path, default=ROOT / 'data/processed/olist_delay_route_load_features.csv')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=4)
    parser.add_argument('--specification-only', action='store_true', help='Write the fixed specification without training.')
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error('Require n-jobs >= 1')
    previous = json.loads(args.previous_report.read_text(encoding='utf-8'))
    manifest = engineering_source_manifest(args.data_dir)
    if manifest != previous['source_files'] or previous['candidate_order'] != list(PREVIOUS_CANDIDATES):
        raise ValueError('Prior seven-source data or primary candidate order changed')
    if sha256(args.previous_features) != previous['feature_dataset']['sha256']:
        raise ValueError('Frozen feature dataset changed')
    if sha256(args.previous_scores) != previous['score_export']['sha256']:
        raise ValueError('Prior score dataset changed')
    output = args.output_dir.resolve()
    data_dir = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    model_dir = ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models'
    version_dir = model_dir / 'backlog_versions'
    for directory in (output, data_dir, version_dir):
        directory.mkdir(parents=True, exist_ok=True)
    policies = {**previous['policies'],
        'fit': 'same monthly deadline-clock wait0 training IDs, sorted approval/order-ID rows and train-only preprocessing as the corresponding frozen backbone',
        'search': 'nine fixed cells: Logistic load C1/C.01 and XGBoost geo crossed with 7d/14d/combined overdue backlog changes; backbone parameters unchanged; no adaptive grid or E early stopping',
        'features': '7d or14d adds9 numeric overdue backlog features; combined adds18; no new categorical interactions, arrival features, target encoding or dispatch',
        'paired_comparison': 'baseline versus each fixed lag package; 7d/14d/combined hold identical training IDs, row order and estimator parameters',
        'solver': 'Logistic retains L2/lbfgs C1 or C.01/max_iter10000; reject ConvergenceWarning or n_iter >= max_iter; solver diagnostics never select models',
        'primary_selection': 'previous56 plus new9; selectors previous_candidates, new_backlog, primary_without_dispatch; maximize worst of three historical month recalls then pooled TP/AP/fixed order',
        'evaluation_role': 'all E months and design have been informed by repeatedly inspected development results; pre-fit specification does not make these periods independent tests',
        'ranker': 'fixed backbone classifiers; old56 candidates are verified/replayed and never refit; no new calibration or threshold',
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
        'feature_definition': FEATURE_DEFINITION,
        'candidate_specifications': {c: {**candidate_design(c), 'feature_set': feature_set(c),
            'numeric_features': feature_names(c)[0], 'categorical_features': feature_names(c)[1],
            'classifier_parameters': parameter_report(make_candidate(c, n_jobs=args.n_jobs).named_steps['classifier'].get_params(deep=False))} for c in NEW_CANDIDATES},
        'policies': policies, 'previous_primary_context': next(r for r in previous['summary'] if r['model_or_selection'] == PRIMARY_SELECTION),
        'monthly_training': [], 'folds': []}
    specification_path = output / 'backlog_changes_specification.json'
    specification = {k: report[k] for k in (
        'seed', 'daily_cap', 'minimum_validation_recall', 'primary_selection_prespecified', 'candidate_order',
        'new_candidate_order', 'selection_groups', 'candidate_specifications', 'policies', 'source_files',
        'source_previous_report_sha256', 'source_previous_scores_sha256', 'source_previous_features_sha256', 'feature_definition')}
    specification_path.write_text(json.dumps(specification, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    report['specification_sha256'] = sha256(specification_path)
    if args.specification_only:
        print(f'Fixed specification: {specification_path}', flush=True)
        return 0
    print('Building as-of overdue backlog features and verifying every frozen feature/metadata value', flush=True)
    original = pd.read_csv(args.previous_features, float_precision='round_trip', dtype={c: object for c in CATEGORICAL_FEATURES + ['state_route_promise_bin', 'state_route_promise_growth_bin']})
    for column in ('order_purchase_timestamp', 'prediction_time', 'label_available_time', 'training_outcome_known_time'):
        original[column] = pd.to_datetime(original[column])
    tables = load_olist_tables(args.data_dir)
    original = add_training_outcome_clock(original, tables['orders'])
    dataset = add_backlog_features(original, tables)
    pd.testing.assert_frame_equal(dataset[list(original)], original, check_dtype=True, check_exact=True)
    feature_path = data_dir / 'olist_delay_backlog_features.csv'
    dataset.to_csv(feature_path, index=False)
    report['feature_dataset'] = {'rows': len(dataset), 'columns': list(dataset),
        'frozen_columns_preserved': list(original), 'frozen_values_verified': len(dataset) * len(original.columns),
        'added_columns': [name for name in dataset if name not in original],
        'metadata_columns_preserved': ['order_id', 'order_purchase_timestamp', 'prediction_time', 'label_available_time', 'delayed', 'training_outcome_known_time'],
        'path': relative(feature_path), 'sha256': sha256(feature_path)}
    old_scores = pd.read_csv(args.previous_scores, float_precision='round_trip')
    monthly_indices = old_scores.groupby(['model_version','candidate'], sort=False).indices
    phase_indices = old_scores.groupby(['fold','role','candidate','model_version'], sort=False).indices
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
            declared_features = artifact['feature_names'] if 'feature_names' in artifact else \
                list(artifact['pipeline'].named_steps['preprocessor'].feature_names_in_)
            if declared_features != sum(feature_names(candidate), []):
                raise ValueError('Prior feature contract mismatch')
            if 'source_files' in artifact:
                seven = '_engineering_' in candidate or '_ablation_' in candidate or candidate.startswith('logistic_load_regularization_') or candidate in previous_training.NEW_CANDIDATES
                expected_manifest = manifest if seven else [item for item in manifest if item['filename'] != 'olist_geolocation_dataset.csv']
                if artifact['source_files'] != expected_manifest:
                    raise ValueError('Prior version source mismatch')
            elif candidate not in PREVIOUS_CANDIDATES[:4]:
                raise ValueError('Only the four original legacy candidates may lack embedded source manifests')
            if candidate in [item[0] for item in BACKBONES.values()] and artifact['split'] != training_split:
                raise ValueError('Paired backbone does not match common training cohort')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(scoring, candidate))
            comparison = old_scores.iloc[monthly_indices[(month,candidate)]]
            if comparison.empty or set(comparison.order_id) != set(scoring.order_id):
                raise ValueError('Prior monthly score identities mismatch')
            replay = comparison.order_id.map(pd.Series(values, index=scoring.order_id)).to_numpy()
            if not np.isfinite(replay).all() or not np.allclose(replay, comparison.delay_score, rtol=0, atol=1e-12):
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
            design = candidate_design(candidate)
            artifact = {'pipeline': pipeline, 'candidate': candidate, 'split': training_split,
                'feature_names': numeric + categorical, 'source_files': manifest, 'fit': fit_report,
                'feature_set': feature_set(candidate), 'geolocation_used': design['backbone'] == 'geo'}
            path = version_dir / f'olist_delay_{month}_{candidate}.joblib'
            joblib.dump(artifact, path, compress=3)
            entry['models'][candidate] = {'reused': False, **fit_report, 'training_split': training_split,
                'version_artifact': {'path': relative(path), 'sha256': sha256(path)}, 'scoring_rows': len(scoring)}
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            del pipeline, artifact
            gc.collect()
        report['monthly_training'].append(entry)
        print(f'{month}: sixty-five candidates ready', flush=True)
    score_rows, selected_frames, selected_predictions, selected_values = [], [], [], []
    for old in previous['folds']:
        name, schedule = old['name'], old['schedule']
        months = [m['month'] for m in schedule['validation_months']]
        validation = [cache[m]['frame'].reset_index(drop=True) for m in months]
        audits = [mature_validation_month(f, schedule['evaluation_start'])[1] for f in validation]
        if audits != old['validation_maturity']:
            raise ValueError('Historical outcome maturity changed')
        evaluation = cache[name]['frame'].reset_index(drop=True)
        if order_fingerprint(evaluation) != old['order_id_fingerprints']['evaluation']:
            raise ValueError('Development evaluation identities changed')
        def phase_scores(frame):
            month = frame.prediction_time.dt.strftime('%Y-%m').iloc[0]
            return {c: frame.order_id.map(cache[month]['scores'][c]).to_numpy() for c in ALL_CANDIDATES}
        validation_scores, evaluation_scores = [phase_scores(f) for f in validation], phase_scores(evaluation)
        experiment = decide_ranking_fold(validation, validation_scores, evaluation, evaluation_scores,
            schedule['evaluation_start'], candidate_order=ALL_CANDIDATES, selection_groups=SELECTION_GROUPS)
        for candidate in PREVIOUS_CANDIDATES:
            if experiment['models'][candidate] != old['experiment']['models'][candidate]:
                raise ValueError(f'Frozen previous metrics changed: {name}/{candidate}')
        if experiment['selected_models']['previous_candidates'] != old['experiment']['selected_models'][PRIMARY_SELECTION]:
            raise ValueError('Frozen previous selector changed')
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
        path = model_dir / f'olist_delay_backlog_{name}.joblib'
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
                if candidate in PREVIOUS_CANDIDATES:
                    comparison = old_scores.iloc[phase_indices[(name,role,candidate,part.model_version.iloc[0])]]
                    verify_prior_score_part(comparison, part)
                score_rows.append(part)
        print(f'{name}: selected={experiment["selected_models"][PRIMARY_SELECTION]}; min historical recall={decision["minimum_validation_month_recall"]:.4f}; development recall={decision["development_evaluation"]["recall"]:.4f}', flush=True)
    del old_scores
    report['summary'] = summarize(report['folds'], candidate_order=ALL_CANDIDATES, selection_groups=SELECTION_GROUPS)
    report['paired_comparisons'] = paired_comparisons(report['folds'], report['summary'])
    report['selected_development_miss_diagnostics'] = analyze_segments(pd.concat(selected_frames, ignore_index=True),
        np.concatenate(selected_predictions), np.concatenate(selected_values))
    primary = next(r for r in report['summary'] if r['model_or_selection'] == PRIMARY_SELECTION)
    report['suitability'] = {'historical_validation_floor_met_in_all_folds': not primary['validation_folds_below_30_percent'],
        'observed_development_months_all_above_30_percent': primary['minimum_development_month_recall'] >= MIN_RECALL,
        'independent_future_test_available': False, 'automatic_promotion': False,
        'note': 'Development observations and experimental design have seen these periods; none is a new independent test.'}
    score_path = data_dir / 'olist_delay_backlog_scores.csv'
    pd.concat(score_rows, ignore_index=True).to_csv(score_path, index=False)
    report['score_export'] = {'path': relative(score_path), 'rows': sum(len(f) for f in score_rows), 'sha256': sha256(score_path)}
    path = output / 'backlog_changes.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    print(json.dumps(primary, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
