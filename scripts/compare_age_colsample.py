"""Compare fixed paired rankers at colsample .8 versus1 without selection."""
from __future__ import annotations

import argparse
from copy import deepcopy
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

from scripts import compare_age_seed_stability as previous
from scripts import delay_age_colsample_training as training
from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_budget_training import parameter_report
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_outcome_clock import split_outcome_training_month
from scripts.delay_rolling_validation import split_rolling_month
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.train_delay_model import positive_probability
from scripts.train_unobserved_handover_age import fixed_json, read_features

SEEDS, MATCHED = training.SEEDS, training.MATCHED
BASELINE, AGE = MATCHED
COLSAMPLES = ('0.8', '1.0')
CONTRASTS = ('age_minus_base_at_08', 'age_minus_base_at_10', 'base_10_minus_08',
             'age_10_minus_08', 'difference_in_differences')
FIELDS = previous.DIFFERENCE_FIELDS
DEFAULT_OUTPUT = ROOT / 'reports/stage4'
SOURCE_SHA256 = '7b0a1e369307a718c3161d3a10045b8a9ecde385b9ab94bfe7c9c859262f11b8'
SOURCE_SPEC_SHA256 = 'd6317e3958fd0ccbca2692bbf2b185e98508149dc5e39f73cc2f36ac2b2f21cc'
SOURCE_DIAG_SHA256 = '03c1e5630be52f5c1424032d539846398557e2a939f3e28c68d8b1df1012c5d6'
EXPERIMENT = 'paired_age_colsample_ablation'
TARGET_PHASE = '2018-02/2018-02/evaluation'
canonical_sha256 = previous.canonical_sha256


def subtract(left, right):
    return {field: None if left[field] is None or right[field] is None else left[field] - right[field]
            for field in FIELDS}


def paired_contrasts(by_colsample):
    """All contrasts are computed within a single seed on the same population."""
    old, new = by_colsample['0.8'], by_colsample['1.0']
    age08, age10 = subtract(old[AGE], old[BASELINE]), subtract(new[AGE], new[BASELINE])
    return {'age_minus_base_at_08': age08, 'age_minus_base_at_10': age10,
            'base_10_minus_08': subtract(new[BASELINE], old[BASELINE]),
            'age_10_minus_08': subtract(new[AGE], old[AGE]),
            'difference_in_differences': subtract(age10, age08)}


def summarize_comparisons(by_seed):
    if set(by_seed) != set(map(str, SEEDS)):
        raise ValueError('Require every prespecified paired seed')
    return {'by_seed': by_seed, 'cross_seed_statistics': {
        contrast: {field: previous.paired_statistics([by_seed[str(seed)][contrast][field] for seed in SEEDS])
                   for field in FIELDS} for contrast in CONTRASTS}}


def phase_comparisons(by_colsample):
    paired = {str(seed): paired_contrasts({col: {candidate: previous.count_metrics(by_colsample[col][str(seed)][candidate])
             for candidate in MATCHED} for col in COLSAMPLES}) for seed in SEEDS}
    return summarize_comparisons(paired)


def stability_statistics(values, *, directions=False):
    statistics = previous.paired_statistics(values)
    result = {field: statistics[field] for field in ('mean', 'minimum', 'maximum', 'defined', 'undefined')}
    result['span'] = statistics['maximum'] - statistics['minimum'] if statistics['defined'] else None
    if directions:
        result.update({field: statistics[field] for field in ('negative', 'zero', 'positive')})
    result['by_seed'] = {str(seed): value for seed, value in zip(SEEDS, values, strict=True)}
    return result


def february_stability(by_colsample):
    result = {'phase': TARGET_PHASE, 'by_colsample': {}}
    for col in COLSAMPLES:
        rows = {str(seed): {candidate: previous.count_metrics(by_colsample[col][str(seed)][candidate])
                for candidate in MATCHED} for seed in SEEDS}
        gaps = [subtract(rows[str(seed)][AGE], rows[str(seed)][BASELINE]) for seed in SEEDS]
        result['by_colsample'][col] = {
            'by_candidate': {candidate: {metric: stability_statistics([rows[str(seed)][candidate][field] for seed in SEEDS])
                for metric, field in [('TP', 'true_positives'), ('recall', 'recall')]} for candidate in MATCHED},
            'age_minus_base': {metric: stability_statistics([row[field] for row in gaps], directions=True)
                for metric, field in [('TP', 'true_positives'), ('recall', 'recall')]}}
    def span_difference(left, right):
        return None if left['span'] is None or right['span'] is None else left['span'] - right['span']
    before, after = (result['by_colsample'][col] for col in COLSAMPLES)
    result['span_change_10_minus_08'] = {
        'by_candidate': {candidate: {metric: span_difference(after['by_candidate'][candidate][metric], before['by_candidate'][candidate][metric])
            for metric in ('TP', 'recall')} for candidate in MATCHED},
        'age_minus_base': {metric: span_difference(after['age_minus_base'][metric], before['age_minus_base'][metric]) for metric in ('TP', 'recall')}}
    result['interpretation'] = 'Prespecified descriptive spans and paired sign counts; a narrower gap is not necessarily a more stable individual model, consistent direction is not improvement, and no seed or colsample is selected.'
    return result


def verify_fit_contract(train, fit, reference, seed, candidate):
    if (fit.get('seed') != seed or fit.get('candidate') != candidate or candidate not in MATCHED
            or fit.get('colsample_bytree') != 1. or reference['seed'] != seed or reference['candidate'] != candidate):
        raise ValueError('Changed seed, feature package or column-subsampling contrast')
    expected = deepcopy(reference)
    for field in ('classifier_parameters', 'ranker_parameters'):
        if reference[field]['colsample_bytree'] != .8:
            raise ValueError('Require the frozen .8 source parameters')
        expected[field]['colsample_bytree'] = 1.
    previous.verify_fit_contract(train, fit, expected, seed)
    for field in ('feature_count', 'added_numeric_features', 'transformed_feature_count',
                  'numeric_missing_indicator_features', 'age_missing_indicator_from_original_imputer',
                  'manually_added_missingness_indicators'):
        if fit[field] != reference[field]:
            raise ValueError(f'Fixed preprocessing or feature contract changed: {field}')
    if fit.get('changed_classifier_parameters_vs_source') != ['colsample_bytree'] or not fit.get('train_only_preprocessing_verified'):
        raise ValueError('Only column subsampling may change; train-only preprocessing must be verified')


def verify_frozen_ledger(frame, ledger, plan, expected_by_seed):
    """Re-rank saved .8 scores, never load or replay an old model."""
    known = frame.label_available_time.lt(pd.Timestamp(plan['historical_outcome_cutoff'])).to_numpy() if plan['ledger_role'] == 'validation' else np.ones(len(frame), bool)
    contexts = {}
    for seed in SEEDS:
        contexts[str(seed)] = {}
        for candidate in MATCHED:
            part = ledger.loc[ledger.seed.eq(seed) & ledger.fold.eq(plan['fold']) & ledger.role.eq(plan['ledger_role'])
                              & ledger.model_version.eq(plan['month']) & ledger.candidate.eq(candidate)]
            if len(part) != len(frame) or part.order_id.duplicated().any() or set(part.order_id) != set(frame.order_id):
                raise ValueError('Frozen .8 scoring identities changed')
            part = part.set_index('order_id').loc[frame.order_id]
            np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
            np.testing.assert_array_equal(part.known_at_selection.to_numpy(), known if plan['ledger_role'] == 'validation' else np.zeros(len(frame), bool))
            np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
            np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], frame.delayed.to_numpy()[known])
            values = part.delay_score.to_numpy()
            if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
                raise ValueError('Frozen .8 ranking scores must be finite and bounded')
            alerts = apply_alert_policy(frame, values, 0., .1, raw_scores=values)
            np.testing.assert_array_equal(alerts.astype(int), part.predicted_delayed.to_numpy())
            context = {'known_outcome_metrics': alert_metrics(frame.delayed.to_numpy()[known], values[known], alerts[known]),
                       'full_batch': batch_audit(frame, alerts, .1, known)}
            if context != expected_by_seed[str(seed)][candidate]:
                raise ValueError('Frozen .8 full-day or known-outcome metrics changed')
            contexts[str(seed)][candidate] = context
    return contexts


def prepare_experiment(source_path, data_dir, output, n_jobs):
    from scripts.diagnose_age_colsample import diagnostic_contract
    if n_jobs != 2:
        raise ValueError('Fixed experiment requires n_jobs=2')
    if sha256(source_path) != SOURCE_SHA256:
        raise ValueError('Frozen five-seed .8 source changed')
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if (source['status'] != 'ok' or source['experiment'] != 'paired_fixed_seed_age_stability'
            or source['seeds'] != list(SEEDS) or source['matched_candidate_order'] != list(MATCHED)
            or source['specification_sha256'] != SOURCE_SPEC_SHA256
            or source['fit_count_this_execution'] != 80 or source['reloaded_new_version_count'] != 0):
        raise ValueError('Require the frozen five-seed paired .8 experiment')
    versions = {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib', 'xgboost')}
    manifest = engineering_source_manifest(data_dir)
    if versions != source['software_versions'] or manifest != source['source_files']:
        raise ValueError('Frozen software versions or raw sources changed')
    protected = {source_path.resolve(): SOURCE_SHA256}
    def protect(info):
        path = (ROOT / info['path']).resolve()
        if sha256(path) != info['sha256']:
            raise ValueError(f'Frozen source changed: {path}')
        protected[path] = info['sha256']
        return path
    for name, digest in [('age_seed_stability_specification.json', SOURCE_SPEC_SHA256),
                         ('age_seed_stability_diagnostics.json', SOURCE_DIAG_SHA256)]:
        protect({'path': relative(DEFAULT_OUTPUT / name), 'sha256': digest})
    for info in source['source_hashes'] + source['training_code']:
        protect(info)
    feature_path, old_score_path = protect(source['feature_dataset']), protect(source['score_export'])
    old_versions = []
    month_seeds = set()
    for monthly in source['monthly_training']:
        pair = (monthly['month'], monthly['seed'])
        if pair in month_seeds or monthly['seed'] not in SEEDS or set(monthly['models']) != set(MATCHED):
            raise ValueError('Frozen .8 month/seed/model schedule changed')
        month_seeds.add(pair)
        for candidate, fit in monthly['models'].items():
            protect(fit['version_artifact'])
            old_versions.append({'month': monthly['month'], 'seed': monthly['seed'], 'candidate': candidate,
                                 **fit['version_artifact']})
    months = {plan['month'] for plan in source['monthly_plan']}
    if month_seeds != {(month, seed) for month in months for seed in SEEDS} or len(old_versions) != 80 or len(months) != 8:
        raise ValueError('Require all80 frozen .8 artifacts and eight unique months')
    dataset = read_features(feature_path, data_dir)
    if (dataset.shape != (70844, 138) or list(dataset.columns) != source['feature_dataset']['columns']
            or dataset.prediction_time.ge('2018-05-01').any()):
        raise ValueError('Frozen age138 feature cache or holdout boundary changed')
    model_dir = (ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models') / 'age_colsample_versions'
    data_output = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    score_output = data_output / 'olist_delay_age_colsample_scores.csv'
    planned = [model_dir / f'olist_delay_{month}_{candidate}_seed_{seed}_colsample_10.joblib'
               for month in sorted(months) for seed in SEEDS for candidate in MATCHED]
    previous.ensure_ignored([*planned, score_output])
    splits, plans = {}, []
    for old in source['monthly_plan']:
        scoring, split_report = split_rolling_month(dataset, old['split']['model_fit_time'])
        frames, training_split = split_outcome_training_month(dataset, old['split']['model_fit_time'], wait_days=0, clock='deadline')
        _, layout = training.training_layout(frames['train'])
        if (split_report != old['split'] or training_split != old['training_split']
                or frames['scoring'].order_id.tolist() != scoring['scoring'].order_id.tolist()
                or order_fingerprint(frames['scoring']) != old['scoring_order_fingerprint']
                or any(layout[key] != old[key] for key in layout)):
            raise ValueError('Frozen mature identities, labels, order or daily query layout changed')
        plans.append(deepcopy(old))
        splits[old['month']] = frames
    if len(source['phase_plan']) != 12 or set(source['phase_metrics']) != {p['phase'] for p in source['phase_plan']}:
        raise ValueError('Require all12 original phases')
    old_scores = pd.read_csv(old_score_path, float_precision='round_trip', parse_dates=['prediction_time'])
    if (len(old_scores) != 640560 or set(old_scores.seed) != set(SEEDS)
            or set(old_scores.candidate) != set(MATCHED)
            or old_scores.duplicated(['seed', 'fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Frozen .8 score ledger changed')
    for plan in source['phase_plan']:
        frame = splits[plan['month']]['scoring'].reset_index(drop=True)
        if order_fingerprint(frame) != plan['order_id_fingerprint']:
            raise ValueError('Frozen complete scoring-day cohort changed')
        if any(source['phase_metrics'][plan['phase']][key] != value for key, value in plan.items()):
            raise ValueError('Frozen historical phase clock changed')
        verify_frozen_ledger(frame, old_scores, plan, source['phase_metrics'][plan['phase']]['by_seed'])
    contract = diagnostic_contract()
    if contract['seeds'] != list(SEEDS) or contract['candidate_order'] != list(MATCHED):
        raise ValueError('Diagnostic contract changed fixed seeds or feature packages')
    code_paths = [ROOT / 'scripts/delay_age_colsample_training.py', ROOT / 'scripts/compare_age_colsample.py']
    spec = {'format_version': 1, 'experiment': EXPERIMENT, 'seeds': list(SEEDS), 'matched_candidate_order': list(MATCHED),
        'colsample_order': list(COLSAMPLES), 'contrast_order': list(CONTRASTS), 'expected_new_fit_count': 80,
        'expected_frozen_model_hash_count': 80, 'only_changed_classifier_parameter': 'colsample_bytree',
        'source_colsample_bytree': .8, 'new_colsample_bytree': 1., 'fixed_subsample': .8,
        'n_jobs': 2, 'daily_cap': .1, 'reg_lambda': 100., 'pair_method': 'topk', 'num_pair_per_sample': 10,
        'source_report': {'path': relative(source_path), 'sha256': SOURCE_SHA256},
        'source_specification': {'path': relative(DEFAULT_OUTPUT / 'age_seed_stability_specification.json'), 'sha256': SOURCE_SPEC_SHA256},
        'source_diagnostics': {'path': relative(DEFAULT_OUTPUT / 'age_seed_stability_diagnostics.json'), 'sha256': SOURCE_DIAG_SHA256},
        'source_files': manifest, 'software_versions': versions, 'feature_dataset': deepcopy(source['feature_dataset']),
        'source_scores': deepcopy(source['score_export']), 'frozen_reference': {'colsample_bytree': .8, 'monthly_models': old_versions},
        'source_hashes': [{'path': relative(path), 'sha256': digest} for path, digest in protected.items()],
        'monthly_plan': plans, 'phase_plan': deepcopy(source['phase_plan']),
        'candidate_specifications': {str(seed): {candidate: {'numeric_features': training.feature_names(candidate)[0],
            'categorical_features': training.feature_names(candidate)[1], 'feature_set': training.feature_set(candidate),
            'preprocessing': training.preprocessing_specification(training.make_candidate(candidate, seed, n_jobs)),
            'classifier_parameters': parameter_report(training.make_candidate(candidate, seed, n_jobs).named_steps['classifier'].get_params(deep=False))}
            for candidate in MATCHED} for seed in SEEDS},
        'diagnostic_contract': contract, 'diagnostic_contract_sha256': canonical_sha256(contract),
        'training_code': [{'path': relative(path), 'sha256': sha256(path)} for path in code_paths],
        'output_paths': {'version_directory': relative(model_dir), 'score_export': relative(score_output)},
        'prespecified_stability': {'phase': TARGET_PHASE, 'metrics': ['TP', 'recall'],
            'individual_models': 'Each colsample and feature package: five-seed mean/min/max/span, with same population.',
            'age_gap': 'Within each seed age102 minus101: five-seed mean/min/max/span and negative/zero/positive/undefined counts.',
            'span_change': 'Span at1.0 minus span at.8, for individual models and paired age gaps separately.',
            'interpretation': 'Descriptive only; narrow gap does not imply a stable individual model, direction consistency does not imply improvement; no thresholds or winners.'},
        'policies': {'training': 'Eight identical deadline_wait0 mature monthly cohorts, all five fixed paired seeds and both frozen feature packages; exactly80 new1.0 fits including seed42.',
            'only_change': 'colsample_bytree .8 to1.0; subsample remains.8, L2=100, native topk10 and every other full classifier/ranker parameter unchanged.',
            'preprocessing': 'Unchanged train-only median/add_indicator and categorical imputer/OHE rules; same train values imply same deterministic statistics, checked from train and frozen dimensions/indicator names. No old model is loaded to inspect its statistics.',
            'frozen_reference': 'Old80 models are hashed, never deserialized or replayed. Old640560 score rows are checked against source metrics/alerts and preserved unchanged in the combined ledger.',
            'ranking': 'Full closed daily floor(.1*N), score DESC/ID ASC, unknown outcomes compete before original historical known-label masks.',
            'statistics': 'Every feature, colsample and difference-in-differences contrast is paired inside a seed before five-seed mean/min/max/direction counts. Only three disjoint development months pool inside each seed.',
            'selection': 'No seed, colsample, feature package or new historical candidate selection; previous primary/default unchanged.',
            'limitations': 'Already inspected historical/development data, not new independent tests; stable direction is not causal evidence about feature sampling.',
            'holdout': 'Original retained period remains unscored; no feature rows at or after2018-05-01.',
            'reuse': 'Only explicit same-spec own1.0 partial version reuse; actual fit and reload counts reported separately, never old.8 model reuse.'}}
    return source, spec, splits, old_scores, model_dir, score_output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=DEFAULT_OUTPUT / 'age_seed_stability.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=2)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--reuse-new-versions', action='store_true')
    args = parser.parse_args(argv)
    if args.n_jobs != 2:
        parser.error('Fixed experiment requires n-jobs=2')
    output = args.output_dir.resolve()
    source, spec, splits, old_scores, version_dir, score_output = prepare_experiment(args.source_report, args.data_dir, output, args.n_jobs)
    output.mkdir(parents=True, exist_ok=True)
    spec_path, report_path = output / 'age_colsample_specification.json', output / 'age_colsample.json'
    fixed_json(spec_path, spec)
    if args.specification_only:
        print(json.dumps({'specification': relative(spec_path), 'sha256': sha256(spec_path), 'new_fits': 0}), flush=True)
        return 0
    if report_path.exists() or score_output.exists():
        raise ValueError('Completed report/scores cannot be overwritten')
    if not args.reuse_new_versions and version_dir.exists() and any(version_dir.glob('*.joblib')):
        raise ValueError('Existing own1.0 versions require --reuse-new-versions')
    version_dir.mkdir(parents=True, exist_ok=True)
    score_output.parent.mkdir(parents=True, exist_ok=True)
    spec_sha = sha256(spec_path)
    references = {(row['month'], row['seed']): row for row in source['monthly_training']}
    plans = {row['month']: row for row in spec['monthly_plan']}
    report = {**spec, 'status': 'ok', 'specification_sha256': spec_sha, 'new_fit_count': 80,
        'fit_count_this_execution': 0, 'reloaded_new_version_count': 0, 'previous_versions_loaded': 0,
        'monthly_training': [], 'phase_metrics': {}, 'phase_comparisons': {},
        'previous_primary_context': deepcopy(source['previous_primary_context'])}
    score_cache = {}
    for month, frames in splits.items():
        train, scoring = frames['train'], frames['scoring']
        score_cache[month] = {}
        for seed in SEEDS:
            score_cache[month][seed] = {}
            entry = {'month': month, 'seed': seed, 'colsample_bytree': 1., 'split': plans[month]['split'],
                     'training_split': plans[month]['training_split'], 'models': {}}
            for candidate in MATCHED:
                path = version_dir / f'olist_delay_{month}_{candidate}_seed_{seed}_colsample_10.joblib'
                if args.reuse_new_versions and path.exists():
                    artifact = joblib.load(path)
                    if (artifact['candidate'] != candidate or artifact['seed'] != seed or artifact['colsample_bytree'] != 1.
                            or artifact['specification_sha256'] != spec_sha or artifact['source_files'] != source['source_files']
                            or artifact['split'] != entry['training_split']
                            or artifact['feature_names'] != sum(training.feature_names(candidate), [])):
                        raise ValueError('Cannot reuse own1.0 version with changed provenance')
                    pipeline, fit = artifact['pipeline'], artifact['fit']
                    verify_fit_contract(train, fit, references[month, seed]['models'][candidate], seed, candidate)
                    training.verify_preprocessing(pipeline, train, candidate)
                    with threadpool_limits(limits=1):
                        values = positive_probability(pipeline, training.prepare_input(scoring, candidate))
                    report['reloaded_new_version_count'] += 1
                    reused = True
                else:
                    if path.exists():
                        raise ValueError('Refusing to overwrite own1.0 monthly version')
                    print(f'{month} seed={seed}: fitting colsample1.0 {candidate}', flush=True)
                    pipeline, values, fit = training.fit_version(train, scoring, candidate, seed, args.n_jobs)
                    verify_fit_contract(train, fit, references[month, seed]['models'][candidate], seed, candidate)
                    artifact = {'pipeline': pipeline, 'candidate': candidate, 'seed': seed, 'colsample_bytree': 1.,
                        'specification_sha256': spec_sha, 'source_files': source['source_files'],
                        'split': entry['training_split'], 'feature_names': sum(training.feature_names(candidate), []),
                        'feature_set': training.feature_set(candidate), 'fit': fit}
                    joblib.dump(artifact, path, compress=3)
                    report['fit_count_this_execution'] += 1
                    reused = False
                entry['models'][candidate] = {**fit, 'reused_in_this_execution': reused, 'scoring_rows': len(scoring),
                    'version_artifact': {'path': relative(path), 'sha256': sha256(path)}}
                score_cache[month][seed][candidate] = pd.Series(values, index=scoring.order_id)
                del artifact, pipeline
                gc.collect()
            if entry['models'][AGE]['transformed_feature_count'] - entry['models'][BASELINE]['transformed_feature_count'] != 2:
                raise ValueError('Age raw feature plus original automatic indicator must retain +2 dimensions')
            report['monthly_training'].append(entry)
            print(f'{month} seed={seed}: colsample1.0 paired versions ready', flush=True)
    exports = []
    for plan in spec['phase_plan']:
        frame = splits[plan['month']]['scoring'].reset_index(drop=True)
        known = frame.label_available_time.lt(pd.Timestamp(plan['historical_outcome_cutoff'])).to_numpy() if plan['ledger_role'] == 'validation' else np.ones(len(frame), bool)
        by_seed = {}
        for seed in SEEDS:
            by_seed[str(seed)] = {}
            for candidate in MATCHED:
                values = frame.order_id.map(score_cache[plan['month']][seed][candidate]).to_numpy()
                alerts = apply_alert_policy(frame, values, 0., .1, raw_scores=values)
                by_seed[str(seed)][candidate] = {'known_outcome_metrics': alert_metrics(frame.delayed.to_numpy()[known], values[known], alerts[known]),
                                               'full_batch': batch_audit(frame, alerts, .1, known)}
                part = frame[['order_id', 'prediction_time']].copy()
                part['fold'], part['role'], part['candidate'], part['model_version'] = plan['fold'], plan['ledger_role'], candidate, plan['month']
                part['known_at_selection'] = known if plan['ledger_role'] == 'validation' else np.zeros(len(frame), bool)
                part['outcome_for_metrics'] = np.where(known, frame.delayed, np.nan)
                part['delay_score'], part['predicted_delayed'], part['seed'] = values, alerts.astype(int), seed
                exports.append(part)
        phase = {**plan, 'by_colsample': {'0.8': deepcopy(source['phase_metrics'][plan['phase']]['by_seed']), '1.0': by_seed}}
        report['phase_metrics'][plan['phase']] = phase
        report['phase_comparisons'][plan['phase']] = phase_comparisons(phase['by_colsample'])
    report['seed_summary'] = []
    development_paired = {}
    for seed in SEEDS:
        development = {col: {candidate: previous.aggregate_development([
            phase['by_colsample'][col][str(seed)][candidate] for phase in report['phase_metrics'].values()
            if phase['ledger_role'] == 'evaluation']) for candidate in MATCHED} for col in COLSAMPLES}
        comparisons = paired_contrasts(development)
        report['seed_summary'].append({'seed': seed, 'development_by_colsample': development, 'comparisons': comparisons})
        development_paired[str(seed)] = comparisons
    report['development_comparisons'] = summarize_comparisons(development_paired)
    report['february_stability'] = february_stability(report['phase_metrics'][TARGET_PHASE]['by_colsample'])
    fresh_scores = pd.concat(exports, ignore_index=True)
    if (len(report['monthly_training']) != 40 or len(report['phase_metrics']) != 12 or len(fresh_scores) != 640560
            or report['fit_count_this_execution'] + report['reloaded_new_version_count'] != 80):
        raise ValueError('Unexpected monthly fit, phase or score coverage')
    pd.testing.assert_index_equal(fresh_scores.columns, old_scores.columns)
    combined = pd.concat([old_scores.assign(colsample_bytree=.8), fresh_scores.assign(colsample_bytree=1.)], ignore_index=True)
    if len(combined) != 1281120:
        raise ValueError('Require both complete five-seed score ledgers')
    pd.testing.assert_frame_equal(combined.loc[combined.colsample_bytree.eq(.8), old_scores.columns].reset_index(drop=True), old_scores)
    combined.to_csv(score_output, index=False)
    roundtrip = pd.read_csv(score_output, float_precision='round_trip', parse_dates=['prediction_time'])
    pd.testing.assert_frame_equal(roundtrip.loc[roundtrip.colsample_bytree.eq(.8), old_scores.columns].reset_index(drop=True), old_scores)
    report['score_export'] = {'path': relative(score_output), 'sha256': sha256(score_output), 'rows': len(combined),
        'rows_by_colsample': {'0.8': 640560, '1.0': 640560}, 'source_columns': old_scores.columns.tolist(),
        'appended_discriminator': 'colsample_bytree', 'coverage': 'Both colsample settings, five seeds, two fixed packages and all12 phases; no retained-test scores.'}
    report['frozen_reference_reproduction'] = {'score_rows_preserved': 640560, 'all_source_columns_preserved': old_scores.columns.tolist(),
        'values_exact_after_csv_roundtrip': True, 'original_alert_sets_exact': True, 'original_metric_groups_checked': 120,
        'old_models_hashed': 80, 'old_models_loaded': 0, 'old_models_replayed': 0}
    report['verification'] = {'new_monthly_models': 80, 'month_seed_records': 40, 'phase_seed_feature_colsample_metrics': 240,
        'new_fits_expected': 80, 'all_seeds_reported': list(SEEDS), 'best_seed_selected': False,
        'colsample_selected': False, 'new_candidate_selection': False, 'primary_and_default_unchanged': True,
        'original_holdout_not_rescored': True, 'seed_repeats_are_independent_samples': False}
    for info in spec['source_hashes'] + spec['training_code']:
        if sha256(ROOT / info['path']) != info['sha256']:
            raise ValueError('Frozen source or training code changed during experiment')
    if sha256(spec_path) != spec_sha:
        raise ValueError('Immutable pre-fit specification changed')
    fixed_json(report_path, report)
    print(json.dumps({'report': relative(report_path), 'fits': report['fit_count_this_execution'],
        'development_DID': report['development_comparisons']['cross_seed_statistics']['difference_in_differences'],
        'february_stability': report['february_stability']}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    main()
