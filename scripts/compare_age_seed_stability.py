"""Refit frozen101/age102 in pairs at five fixed seeds, without selection."""
from __future__ import annotations

import argparse
from copy import deepcopy
import gc
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import delay_age_seed_training as training
from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_budget_training import parameter_report
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_outcome_clock import split_outcome_training_month
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.train_backlog_changes import verify_prior_score_part
from scripts.train_delay_model import positive_probability
from scripts.train_unobserved_handover_age import fixed_json, read_features, verify_training_contract

SEEDS, MATCHED = training.SEEDS, training.MATCHED
BASELINE, AGE = MATCHED
DEFAULT_OUTPUT = ROOT / 'reports/stage4'
SOURCE_SHA256 = '55ff0a08839f587141ec3e7fb285027ff5ea6d60abb7537050726fd349f0f385'
SOURCE_SPEC_SHA256 = 'c927dd5032072157539ac13396752c68015bd300f724bd929f442aa0096e01bc'
SOURCE_DIAG_SHA256 = '9b46bb1189aa137a3b1c9750634fc59d1fbc81bb74685dc436e5d9276cb91ce2'
INTERSECTION_SHA256 = '96732787ffce4adb26b9dabd273cbc31390ecb79a57bec7089c6161a3d04ea30'
EXPERIMENT = 'paired_fixed_seed_age_stability'
DIFFERENCE_FIELDS = ('true_positives', 'false_positives', 'false_negatives', 'recall', 'precision', 'alerts')


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def paired_statistics(values):
    """Summarize already paired differences, keeping undefined rates null."""
    defined = [float(value) for value in values if value is not None]
    if not np.isfinite(defined).all():
        raise ValueError('Paired differences must be finite or undefined')
    return {'mean': float(np.mean(defined)) if defined else None,
            'minimum': min(defined) if defined else None,
            'maximum': max(defined) if defined else None,
            'negative': sum(value < 0 for value in defined),
            'zero': sum(value == 0 for value in defined),
            'positive': sum(value > 0 for value in defined),
            'defined': len(defined), 'undefined': len(values) - len(defined)}


def paired_differences(baseline, age):
    return {field: None if baseline[field] is None or age[field] is None else age[field] - baseline[field]
            for field in DIFFERENCE_FIELDS}


def count_metrics(context):
    metric, batch = context['known_outcome_metrics'], context['full_batch']
    (tn, fp), (fn, tp) = metric['confusion_matrix']
    return {'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
            'true_negatives': tn, 'known_rows': tn + fp + fn + tp, 'delayed_rows': fn + tp,
            'recall': metric['recall'], 'precision': metric['precision'],
            'alerts': batch['alerts'], 'full_batch_rows': batch['scored_rows']}


def aggregate_development(contexts):
    """Pool only the three disjoint development months inside one seed."""
    rows = [count_metrics(context) for context in contexts]
    keys = ('true_positives', 'false_positives', 'false_negatives', 'true_negatives',
            'known_rows', 'delayed_rows', 'alerts', 'full_batch_rows')
    result = {key: sum(row[key] for row in rows) for key in keys}
    result['recall'] = result['true_positives'] / result['delayed_rows'] if result['delayed_rows'] else None
    known_alerts = result['true_positives'] + result['false_positives']
    result['precision'] = result['true_positives'] / known_alerts if known_alerts else None
    return result


def verify_fit_contract(train, fit, original_fit, seed):
    if fit['seed'] != seed or fit['candidate'] not in MATCHED:
        raise ValueError('Fitted seed/candidate metadata changed')
    expected = deepcopy(original_fit)
    for key in ('classifier_parameters', 'ranker_parameters'):
        expected[key]['random_state'] = int(seed)
    verify_training_contract(train, fit, expected)
    _, layout = training.training_layout(train)
    if any(fit[key] != value for key, value in layout.items()):
        raise ValueError('Seed changed training identities, labels, order or queries')


def ensure_ignored(paths):
    for path in paths:
        if subprocess.run(['git', 'check-ignore', '--quiet', str(path)], cwd=ROOT,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            raise ValueError(f'Local model/score outputs must be Git ignored: {path}')


def prepare_experiment(source_path, data_dir, output, n_jobs):
    """Read and freeze provenance/layout only; never fit or load a model."""
    from scripts.diagnose_age_seed_stability import diagnostic_contract
    if n_jobs != 2:
        raise ValueError('The fixed experiment requires n_jobs=2')
    if sha256(source_path) != SOURCE_SHA256:
        raise ValueError('Frozen original age experiment changed')
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if (source['status'] != 'ok' or source['experiment'] != 'unobserved_handover_age_ablation'
            or source['matched_candidate_order'] != list(MATCHED)
            or source['specification_sha256'] != SOURCE_SPEC_SHA256):
        raise ValueError('Require frozen baseline101/age102 and original specification')
    manifest = engineering_source_manifest(data_dir)
    versions = {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib', 'xgboost')}
    if manifest != source['source_files'] or versions != source['versions']:
        raise ValueError('Frozen raw sources or software versions changed')
    files = {source_path.resolve(): SOURCE_SHA256}

    def protect(info):
        path = ROOT / info['path']
        if sha256(path) != info['sha256']:
            raise ValueError(f'Frozen source changed: {path}')
        files[path.resolve()] = info['sha256']
        return path

    for name, expected in [('unobserved_handover_age_specification.json', SOURCE_SPEC_SHA256),
                           ('unobserved_handover_age_diagnostics.json', SOURCE_DIAG_SHA256),
                           ('age_intersection_diagnostics.json', INTERSECTION_SHA256)]:
        protect({'path': relative(DEFAULT_OUTPUT / name), 'sha256': expected})
    protect(source['source_feature_script'])
    feature_path, score_path = protect(source['feature_dataset']), protect(source['score_export'])
    for item in manifest:
        protect({'path': relative(data_dir / item['filename']), 'sha256': item['sha256']})
    original_model_hashes = []
    for month in source['monthly_training']:
        for model in month['models'].values():
            protect(model['version_artifact'])
            original_model_hashes.append(model['version_artifact'])
    for fold in source['folds']:
        protect(fold['research_artifact'])
        original_model_hashes.append(fold['research_artifact'])
    if len(source['monthly_training']) != 8 or len(original_model_hashes) != 19:
        raise ValueError('Require eight unique months and original16+3 artifact hashes')
    dataset = read_features(feature_path, data_dir)
    if (len(dataset) != 70844 or list(dataset.columns) != source['feature_dataset']['columns']
            or dataset.prediction_time.ge('2018-05-01').any()):
        raise ValueError('Changed frozen138-column pre-May feature cohort')
    model_dir = (ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models') / 'age_seed_stability_versions'
    data_output = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    score_output = data_output / 'olist_delay_age_seed_stability_scores.csv'
    planned_model_paths = [model_dir / f'olist_delay_{month["month"]}_{candidate}_seed_{seed}.joblib'
                           for month in source['monthly_training'] for seed in SEEDS for candidate in MATCHED]
    ensure_ignored([*planned_model_paths, score_output])
    plans, splits_by_month = [], {}
    for old in source['monthly_training']:
        month = old['month']
        scoring_split, split_report = split_rolling_month(dataset, old['split']['model_fit_time'])
        splits, training_split = split_outcome_training_month(dataset, old['split']['model_fit_time'], wait_days=0, clock='deadline')
        if (split_report != old['split'] or training_split != old['models'][AGE]['training_split']
                or splits['scoring'].order_id.tolist() != scoring_split['scoring'].order_id.tolist()):
            raise ValueError('Original mature training or complete scoring cohort changed')
        _, layout = training.training_layout(splits['train'])
        for field in ('training_order_sha256', 'daily_training_groups', 'daily_training_query_counts'):
            if layout[field] != old['models'][AGE][field]:
                raise ValueError('Original training order or day query provenance changed')
        plans.append({'month': month, 'split': split_report, 'training_split': training_split,
                      **layout, 'scoring_order_fingerprint': order_fingerprint(splits['scoring'])})
        splits_by_month[month] = splits
    if len({plan['month'] for plan in plans}) != 8:
        raise ValueError('Monthly fit schedule must contain eight unique months')
    phase_plan = []
    for fold in source['folds']:
        audits = [mature_validation_month(splits_by_month[m['month']]['scoring'], fold['schedule']['evaluation_start'])[1]
                  for m in fold['schedule']['validation_months']]
        if audits != fold['validation_maturity']:
            raise ValueError('Historical label maturity changed')
        for role, month in [*(('validation', m['month']) for m in fold['schedule']['validation_months']), ('evaluation', fold['name'])]:
            frame = splits_by_month[month]['scoring']
            expected = (fold['order_id_fingerprints']['validation_full_by_month'][month] if role == 'validation' else
                        fold['order_id_fingerprints']['evaluation'])
            if order_fingerprint(frame) != expected:
                raise ValueError('Original full-day scoring identities changed')
            phase_plan.append({'phase': f'{fold["name"]}/{month}/{role}', 'fold': fold['name'], 'month': month,
                'ledger_role': role, 'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                'order_id_fingerprint': expected})
    contract = diagnostic_contract()
    if contract['seeds'] != list(SEEDS) or contract['candidate_order'] != list(MATCHED):
        raise ValueError('Diagnostic contract changed paired seeds or packages')
    code_paths = [ROOT / 'scripts/delay_age_seed_training.py', ROOT / 'scripts/compare_age_seed_stability.py']
    specification = {'format_version': 1, 'experiment': EXPERIMENT, 'seeds': list(SEEDS),
        'matched_candidate_order': list(MATCHED), 'expected_new_fit_count': 80,
        'only_changed_classifier_parameter': 'random_state', 'n_jobs': 2,
        'daily_cap': .1, 'reg_lambda': 100., 'pair_method': 'topk', 'num_pair_per_sample': 10,
        'source_report': {'path': relative(source_path), 'sha256': SOURCE_SHA256},
        'source_specification': {'path': relative(DEFAULT_OUTPUT / 'unobserved_handover_age_specification.json'), 'sha256': SOURCE_SPEC_SHA256},
        'feature_dataset': deepcopy(source['feature_dataset']), 'source_scores': deepcopy(source['score_export']),
        'source_files': manifest, 'source_model_hashes': original_model_hashes,
        'source_hashes': [{'path': relative(path), 'sha256': value} for path, value in files.items()],
        'software_versions': versions, 'monthly_plan': plans, 'phase_plan': phase_plan,
        'candidate_specifications': {str(seed): {candidate: {'numeric_features': training.feature_names(candidate)[0],
            'categorical_features': training.feature_names(candidate)[1], 'feature_set': training.feature_set(candidate),
            'classifier_parameters': parameter_report(training.make_candidate(candidate, seed, n_jobs).named_steps['classifier'].get_params(deep=False))}
            for candidate in MATCHED} for seed in SEEDS},
        'diagnostic_contract': contract, 'diagnostic_contract_sha256': canonical_sha256(contract),
        'training_code': [{'path': relative(path), 'sha256': sha256(path)} for path in code_paths],
        'output_paths': {'version_directory': relative(model_dir), 'score_export': relative(score_output)},
        'policies': {'training': 'Eight identical mature deadline_wait0 train/scoring cohorts, stable approval-time/ID order and daily queries for both packages and all five seeds.',
            'fit': 'Fresh refit for both packages at all five seeds, including42; no eval set, early stopping, parameter/window/support/feature search.',
            'preprocessing': 'Original train-only median imputation/add_indicator and OHE rules; only age102 has the one original age input, never pending count or a manual indicator.',
            'ranking': 'Complete closed daily floor(0.1*N) batch before known-label masks; unknowns compete, no group quotas or carryover.',
            'seed42': 'New seed42 fits must reproduce original frozen scores to rtol0/atol1e-12 and exact complete-day alert decisions.',
            'statistics': 'First compute age102 minus101 within each seed, then mean/min/max and negative/zero/positive/undefined counts. Do not subtract model marginal ranges or pool seed repetitions as independent orders.',
            'selection': 'No best seed, no new historical model selection or new candidate registry, no February-driven choice; original80-candidate research primary remains frozen.',
            'data_role': 'All historical phases and three development months are already inspected; seed repeats are not independent new data or unknown-test gains.',
            'holdout': 'Original retained period not scored, no new features after the original pre-May cutoff.',
            'preservation': 'Original16 monthly and3 selected artifacts only hashed, never loaded or overwritten; outputs only in Git-ignored paths; unchanged research/default models.',
            'reuse': 'Explicit own-version reuse only with identical specification, seed, source, feature whitelist and training layout; a reused version is not a new fit in that execution.'}}
    return source, specification, splits_by_month, model_dir, score_output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=DEFAULT_OUTPUT / 'unobserved_handover_age.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=2)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--reuse-new-versions', action='store_true')
    args = parser.parse_args(argv)
    if args.n_jobs != 2:
        parser.error('The fixed experiment requires n-jobs=2')
    output = args.output_dir.resolve()
    source, specification, splits, version_dir, score_output = prepare_experiment(args.source_report, args.data_dir, output, args.n_jobs)
    output.mkdir(parents=True, exist_ok=True)
    spec_path, report_path = output / 'age_seed_stability_specification.json', output / 'age_seed_stability.json'
    fixed_json(spec_path, specification)
    if args.specification_only:
        print(json.dumps({'specification': relative(spec_path), 'sha256': sha256(spec_path), 'new_fits': 0}), flush=True)
        return 0
    if report_path.exists() or score_output.exists():
        raise ValueError('Completed report/scores cannot be overwritten; use a fresh ignored output directory')
    if not args.reuse_new_versions and version_dir.exists() and any(version_dir.glob('*.joblib')):
        raise ValueError('Existing own monthly versions require --reuse-new-versions')
    version_dir.mkdir(parents=True, exist_ok=True)
    score_output.parent.mkdir(parents=True, exist_ok=True)
    old_scores = pd.read_csv(ROOT / source['score_export']['path'], float_precision='round_trip', parse_dates=['prediction_time'])
    if len(old_scores) != 128112 or set(old_scores.candidate) != set(MATCHED):
        raise ValueError('Frozen original score ledger changed')
    spec_sha = sha256(spec_path)
    report = {**specification, 'status': 'ok', 'specification_sha256': spec_sha,
        'new_fit_count': 80, 'fit_count_this_execution': 0, 'reloaded_new_version_count': 0,
        'previous_versions_loaded': 0, 'monthly_training': [], 'phase_metrics': {},
        'previous_primary_context': deepcopy(next(x for x in source['summary'] if x['model_or_selection'] == 'primary_without_dispatch'))}
    score_cache, monthly_42_rows = {}, 0
    source_months = {row['month']: row for row in source['monthly_training']}
    plans = {row['month']: row for row in specification['monthly_plan']}
    for month, frames in splits.items():
        train, scoring = frames['train'], frames['scoring']
        score_cache[month] = {}
        original_fit = source_months[month]['models'][AGE]
        for seed in SEEDS:
            entry = {'month': month, 'seed': seed, 'split': plans[month]['split'],
                     'training_split': plans[month]['training_split'], 'models': {}}
            score_cache[month][seed] = {}
            for candidate in MATCHED:
                path = version_dir / f'olist_delay_{month}_{candidate}_seed_{seed}.joblib'
                if args.reuse_new_versions and path.exists():
                    artifact = joblib.load(path)
                    if (artifact['candidate'] != candidate or artifact['seed'] != seed or artifact['specification_sha256'] != spec_sha
                            or artifact['source_files'] != source['source_files'] or artifact['split'] != entry['training_split']
                            or artifact['feature_names'] != sum(training.feature_names(candidate), [])):
                        raise ValueError('Cannot reuse own version with changed specification/provenance')
                    pipeline, fit = artifact['pipeline'], artifact['fit']
                    verify_fit_contract(train, fit, original_fit, seed)
                    with threadpool_limits(limits=1):
                        values = positive_probability(pipeline, training.prepare_input(scoring, candidate))
                    report['reloaded_new_version_count'] += 1
                    reused = True
                else:
                    if path.exists():
                        raise ValueError('Refusing to overwrite an own monthly version')
                    print(f'{month} seed={seed}: fitting {candidate}', flush=True)
                    pipeline, values, fit = training.fit_version(train, scoring, candidate, seed, n_jobs=args.n_jobs)
                    verify_fit_contract(train, fit, original_fit, seed)
                    artifact = {'pipeline': pipeline, 'candidate': candidate, 'seed': seed,
                        'specification_sha256': spec_sha, 'source_files': source['source_files'],
                        'split': entry['training_split'], 'feature_names': sum(training.feature_names(candidate), []),
                        'feature_set': training.feature_set(candidate), 'fit': fit}
                    joblib.dump(artifact, path, compress=3)
                    report['fit_count_this_execution'] += 1
                    reused = False
                if seed == 42:
                    original = old_scores.loc[old_scores.model_version.eq(month) & old_scores.candidate.eq(candidate)]
                    if set(original.order_id) != set(scoring.order_id):
                        raise ValueError('Seed42 original score cohort changed')
                    mapped = original.order_id.map(pd.Series(values, index=scoring.order_id)).to_numpy()
                    np.testing.assert_allclose(mapped, original.delay_score.to_numpy(), rtol=0, atol=1e-12)
                    monthly_42_rows += len(scoring)
                entry['models'][candidate] = {**fit, 'reused_in_this_execution': reused,
                    'scoring_rows': len(scoring), 'version_artifact': {'path': relative(path), 'sha256': sha256(path)}}
                score_cache[month][seed][candidate] = pd.Series(values, index=scoring.order_id)
                del pipeline, artifact
                gc.collect()
            if entry['models'][AGE]['transformed_feature_count'] - entry['models'][BASELINE]['transformed_feature_count'] != 2:
                raise ValueError('Age input plus original imputer indicator must match frozen transformed dimension difference')
            report['monthly_training'].append(entry)
            print(f'{month} seed={seed}: paired versions ready', flush=True)
    exports, original_phase_rows = [], 0
    for plan in specification['phase_plan']:
        month, role = plan['month'], plan['ledger_role']
        frame = splits[month]['scoring'].reset_index(drop=True)
        known = frame.label_available_time.lt(pd.Timestamp(plan['historical_outcome_cutoff'])).to_numpy() if role == 'validation' else np.ones(len(frame), bool)
        context_by_seed = {}
        for seed in SEEDS:
            contexts = {}
            for candidate in MATCHED:
                values = frame.order_id.map(score_cache[month][seed][candidate]).to_numpy()
                alerts = apply_alert_policy(frame, values, 0., .1, raw_scores=values)
                contexts[candidate] = {'known_outcome_metrics': alert_metrics(frame.delayed.to_numpy()[known], values[known], alerts[known]),
                                       'full_batch': batch_audit(frame, alerts, .1, known)}
                part = frame[['order_id', 'prediction_time']].copy()
                part['fold'], part['role'], part['candidate'], part['model_version'] = plan['fold'], role, candidate, month
                part['known_at_selection'] = known if role == 'validation' else np.zeros(len(frame), bool)
                part['outcome_for_metrics'] = np.where(known, frame.delayed, np.nan)
                part['delay_score'], part['predicted_delayed'], part['seed'] = values, alerts.astype(int), seed
                if seed == 42:
                    comparison = old_scores.loc[old_scores.fold.eq(plan['fold']) & old_scores.role.eq(role)
                                                & old_scores.candidate.eq(candidate) & old_scores.model_version.eq(month)]
                    verify_prior_score_part(comparison, part)
                    original_phase_rows += len(part)
                exports.append(part)
            context_by_seed[str(seed)] = contexts
        report['phase_metrics'][plan['phase']] = {**plan, 'by_seed': context_by_seed}
    report['seed_summary'] = []
    for seed in SEEDS:
        development = {candidate: aggregate_development([
            phase['by_seed'][str(seed)][candidate] for phase in report['phase_metrics'].values()
            if phase['ledger_role'] == 'evaluation']) for candidate in MATCHED}
        report['seed_summary'].append({'seed': seed, 'development': development,
            'paired_development_differences': paired_differences(development[BASELINE], development[AGE])})
    report['paired_development_statistics'] = {field: paired_statistics([
        row['paired_development_differences'][field] for row in report['seed_summary']]) for field in DIFFERENCE_FIELDS}
    report['paired_phase_statistics'] = {}
    for key, phase in report['phase_metrics'].items():
        paired = {str(seed): paired_differences(count_metrics(phase['by_seed'][str(seed)][BASELINE]),
                                               count_metrics(phase['by_seed'][str(seed)][AGE])) for seed in SEEDS}
        report['paired_phase_statistics'][key] = {'by_seed': paired,
            'paired_delta_statistics': {field: paired_statistics([row[field] for row in paired.values()]) for field in DIFFERENCE_FIELDS}}
    if len(report['monthly_training']) != 40 or len(report['phase_metrics']) != 12 or monthly_42_rows != 85258 or original_phase_rows != 128112:
        raise ValueError('Unexpected paired fit/phase/seed42 verification coverage')
    combined = pd.concat(exports, ignore_index=True)
    if len(combined) != 640560 or report['fit_count_this_execution'] + report['reloaded_new_version_count'] != 80:
        raise ValueError('Unexpected five-seed ledger or fit coverage')
    combined.to_csv(score_output, index=False)
    report['score_export'] = {'path': relative(score_output), 'sha256': sha256(score_output), 'rows': len(combined),
                            'coverage': 'Five seeds, two fixed feature packages and all12 original phases; no retained-test scores.'}
    report['seed42_original_reproduction'] = {'monthly_score_rows_checked': monthly_42_rows,
        'phase_score_rows_checked': original_phase_rows, 'score_rtol': 0., 'score_atol': 1e-12,
        'original_alert_sets_exact': True, 'original_models_loaded': 0}
    report['verification'] = {'paired_month_seed_records': 40, 'monthly_models': 80, 'phase_seed_model_metrics': 120,
        'all_seeds_reported': list(SEEDS), 'best_seed_selected': False, 'new_candidate_selection': False,
        'previous_primary_unchanged': True, 'original_holdout_not_rescored': True,
        'seed_repeats_are_independent_samples': False}
    for info in specification['source_hashes'] + specification['training_code']:
        if sha256(ROOT / info['path']) != info['sha256']:
            raise ValueError('Frozen source or training code changed during experiment')
    if sha256(spec_path) != spec_sha:
        raise ValueError('Immutable specification changed during experiment')
    fixed_json(report_path, report)
    print(json.dumps({'report': relative(report_path), 'fits': report['fit_count_this_execution'],
                      'paired_development_statistics': report['paired_development_statistics']}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    main()
