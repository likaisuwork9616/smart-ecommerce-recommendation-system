"""Compare pending-age102 with frozen101 at approval / L2=100 / topk10."""
from __future__ import annotations

import argparse
from copy import deepcopy
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

from scripts import train_unobserved_handover_count as source_comparison
from scripts import delay_unobserved_handover_age_training as training
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_budget_training import CAP, MIN_RECALL, decide_ranking_fold, parameter_report, select_candidate, summarize
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_outcome_clock import split_outcome_training_month
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.train_backlog_changes import verify_prior_score_part
from scripts.train_delay_model import LABEL_METADATA, positive_probability
from scripts.delay_unobserved_handover_age_training import ADDED_FEATURES
from scripts.delay_unobserved_handover_age_features import feature_contract

SOURCE_SHA256 = 'a4df705408dda332157a5753f39f9b720061cc2d80889efbc2cf12150bd10d81'
AUDIT_SHA256 = 'd2f95b70a8e03668054df7bba2cab7a97b5ad5c237df120b0c33e826a7eacdcf'

BASELINE = training.BASELINE
REPLAYED = (BASELINE,)
NEW = training.NEW_CANDIDATES
MATCHED = (*REPLAYED, *NEW)
PREVIOUS = source_comparison.ORDER
ORDER = (*PREVIOUS, *NEW)
PRIMARY = 'primary_without_dispatch'
GROUPS = {'previous_candidates': PREVIOUS, 'unobserved_handover_age_ablation': MATCHED, PRIMARY: ORDER}
DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def feature_names(candidate):
    return training.feature_names(candidate) if candidate in MATCHED else source_comparison.feature_names(candidate)


def prepare_input(frame, candidate):
    return training.prepare_input(frame, candidate) if candidate in MATCHED else source_comparison.prepare_input(frame, candidate)


def feature_set(candidate):
    return training.feature_set(candidate) if candidate in MATCHED else source_comparison.feature_set(candidate)


def make_candidate(candidate, seed=42, n_jobs=2):
    return training.make_candidate(candidate, seed, n_jobs) if candidate in MATCHED else source_comparison.make_candidate(candidate, seed, n_jobs)


def candidate_design(candidate):
    if candidate in MATCHED:
        return training.candidate_design(candidate)
    return {**source_comparison.candidate_design(candidate), 'comparison_role': 'frozen_previous_context'}


def merge_experiments(previous, matched):
    """Reuse frozen previous metrics; choose only by historical fields.

    Only backlog101 is replayed. The other 78 previous metric records,
    including pending-count102 and completed-handover102/104, stay frozen.
    Development fields never enter select_candidate's key.
    """
    if set(previous['models']) != set(PREVIOUS) or set(matched['models']) != set(MATCHED):
        raise ValueError('Require frozen79 and the two matched model records')
    for candidate in REPLAYED:
        if previous['models'][candidate] != matched['models'][candidate]:
            raise ValueError(f'Frozen topk baseline metrics changed: {candidate}')
    models = deepcopy(previous['models'])
    models.update({c: deepcopy(matched['models'][c]) for c in NEW})
    selected = {name: select_candidate(models, candidates, ORDER) for name, candidates in GROUPS.items()}
    if selected['previous_candidates'] != previous['selected_models'][PRIMARY]:
        raise ValueError('Frozen previous 79-candidate selection changed')
    return {'models': models, 'selected_models': selected}


read_features = source_comparison.read_features


def compatibility_targets(source):
    model = next(f for f in source['folds'] if f['name']=='2017-12')['experiment']['models'][BASELINE]
    return {'reference_candidate': BASELINE, 'historical_outcome_cutoff': '2017-12-01T00:00:00',
        'used_for_selection': False,
        'july_historical_TP': model['validation_by_month']['2017-07']['known_outcome_metrics']['confusion_matrix'][1][1],
        'september_historical_TP': model['validation_by_month']['2017-09']['known_outcome_metrics']['confusion_matrix'][1][1],
        'december_development_TP': model['development_evaluation']['confusion_matrix'][1][1],
        'interpretation': 'Descriptive already inspected July/September historical and December development references; development goal never enters selection.'}


def paired_comparisons(folds, summary, targets):
    indexed = {row['model_or_selection']: row for row in summary}
    first = next(f for f in folds if f['name']=='2017-12')['experiment']['models']
    candidates = {'baseline101': BASELINE, 'unobserved_handover_age102': NEW[0]}
    paired = {'feature_package': 'baseline101_vs_unobserved_handover_age102', 'candidates_by_feature_set': candidates,
        'topk_unchanged': 10, 'reg_lambda': 100.,
        'development_true_positives': {method:indexed[c]['true_positives'] for method,c in candidates.items()},
        'development_recall': {method:indexed[c]['recall'] for method,c in candidates.items()},
        'net_TP_vs_baseline': {method:indexed[c]['true_positives']-indexed[BASELINE]['true_positives'] for method,c in candidates.items()},
        'by_fold': {fold['name']: {method: {
            'candidate': c, 'minimum_validation_month_recall': fold['experiment']['models'][c]['minimum_validation_month_recall'],
            'validation_by_month': fold['experiment']['models'][c]['validation_by_month'],
            'development': fold['experiment']['models'][c]['development_evaluation'],
        } for method,c in candidates.items()} for fold in folds}}
    checks=[]
    for method,c in candidates.items():
        july=first[c]['validation_by_month']['2017-07']['known_outcome_metrics']['confusion_matrix'][1][1]
        september=first[c]['validation_by_month']['2017-09']['known_outcome_metrics']['confusion_matrix'][1][1]
        december=first[c]['development_evaluation']['confusion_matrix'][1][1]
        checks.append({'candidate':c,'feature_package':method,'july_historical_TP':july,'september_historical_TP':september,
            'december_development_TP':december,'july_difference':july-targets['july_historical_TP'],
            'september_difference':september-targets['september_historical_TP'],
            'december_difference':december-targets['december_development_TP'],
            'both_historical_months_not_worse':july>=targets['july_historical_TP'] and september>=targets['september_historical_TP'],
            'all_three_descriptive_periods_not_worse':july>=targets['july_historical_TP'] and september>=targets['september_historical_TP'] and december>=targets['december_development_TP'],
            'used_for_selection':False})
    return paired,checks


def fixed_json(path, payload):
    """Write a new report, or verify an identical existing report unchanged."""
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != payload:
            raise ValueError(f'Refusing to overwrite a different existing report: {path}')
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def feature_quality(frame):
    values = pd.to_numeric(frame[ADDED_FEATURES[0]], errors='raise')
    observed = values.dropna()
    if not np.isfinite(observed).all() or observed.lt(0).any():
        raise ValueError('Pending age p90 must be missing or finite nonnegative hours')
    def summary(part):
        age = pd.to_numeric(part[ADDED_FEATURES[0]], errors='raise')
        return {'rows': len(part), 'age_observed': int(age.notna().sum()),
                'age_missing': int(age.isna().sum()),
                'age_coverage': float(age.notna().mean()) if len(age) else None,
                'age_feature_median_hours': None if age.notna().sum() == 0 else float(age.median()),
                'age_feature_p90_hours': None if age.notna().sum() == 0 else float(age.quantile(.9))}
    return {'overall': summary(frame),
            'by_approval_month': {month: summary(part) for month, part in
                                  frame.groupby(frame.prediction_time.dt.strftime('%Y-%m'), sort=True)}}


def verify_training_contract(train, fit, baseline_fit):
    """Reject any change to mature rows, stable order, daily queries or settings."""
    ordered = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    expected_hash = hashlib.sha256('\n'.join(ordered.order_id.astype(str)).encode('utf-8')).hexdigest()
    groups = ordered.groupby(ordered.prediction_time.dt.normalize(), sort=True).size().tolist()
    for info in (fit, baseline_fit):
        if info['training_order_sha256'] != expected_hash or info['daily_training_groups'] != groups:
            raise ValueError('Mature training IDs, order or daily query groups changed')
    for field in ('classifier_parameters', 'ranker_parameters', 'training_jobs', 'prediction_jobs',
                  'training_design', 'daily_training_query_counts', 'reg_lambda', 'pair_focus_k'):
        if fit[field] != baseline_fit[field]:
            raise ValueError(f'Fixed baseline training setting changed: {field}')
    for info in (fit, baseline_fit):
        method = info.get('pair_method') or info['classifier_parameters']['lambdarank_pair_method']
        if method != 'topk':
            raise ValueError('Fixed baseline training pair method changed')


def main(argv=None):
    from scripts.delay_unobserved_handover_age_training import fit_version

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--source-report', type=Path, default=DEFAULT_OUTPUT / 'unobserved_handover_count.json')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=2)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--reuse-new-versions', action='store_true', help='Reuse only own versions with identical specification and provenance.')
    args = parser.parse_args(argv)
    if args.n_jobs != 2:
        parser.error('The fixed experiment requires n-jobs=2')
    source = json.loads(args.source_report.read_text(encoding='utf-8'))
    manifest = engineering_source_manifest(args.data_dir)
    if (sha256(args.source_report) != SOURCE_SHA256
            or source['status'] != 'ok' or source.get('experiment') != 'unobserved_handover_count_ablation'
            or source['candidate_order'] != list(PREVIOUS) or manifest != source['source_files']):
        raise ValueError('Require the exact frozen completed79-candidate pending-count experiment')
    audit_path = DEFAULT_OUTPUT / 'approval_signal_inventory.json'
    if sha256(audit_path) != AUDIT_SHA256:
        raise ValueError('Frozen approval-signal availability audit changed')
    archive_path = ROOT / source['source_candidate_versions']['path']
    if sha256(archive_path) != source['source_candidate_versions']['sha256']:
        raise ValueError('Frozen earlier candidate version manifest changed')
    archive = json.loads(archive_path.read_text(encoding='utf-8'))
    prior_feature_path = ROOT / source['feature_dataset']['path']
    if sha256(prior_feature_path) != source['feature_dataset']['sha256']:
        raise ValueError('Frozen prior pending-count feature cache changed')
    feature_path, score_path = (ROOT / source[k]['path'] for k in ('source_features', 'score_export'))
    if sha256(feature_path) != source['source_features']['sha256'] or sha256(score_path) != source['score_export']['sha256']:
        raise ValueError('Frozen feature or score source changed')
    output = args.output_dir.resolve()
    model_dir = ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models'
    data_output = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    version_dir = model_dir / 'unobserved_handover_age_versions'
    for p in (output, data_output, version_dir):
        p.mkdir(parents=True, exist_ok=True)
    frozen_dataset = read_features(feature_path, args.data_dir)
    new_feature_path = data_output / 'olist_delay_unobserved_handover_age_features.csv'
    dataset = read_features(new_feature_path, args.data_dir)
    if (len(frozen_dataset) != source['feature_dataset']['rows']
            or list(frozen_dataset.columns) != source['feature_dataset']['frozen_columns_preserved']
            or len(frozen_dataset.columns) != 137
            or list(dataset.columns) != list(frozen_dataset.columns) + list(ADDED_FEATURES)
            or dataset.prediction_time.ge('2018-05-01').any()
            or len(dataset) != len(frozen_dataset)):
        raise ValueError('Frozen137 columns, new138 cache or pre-May cohort changed')
    pd.testing.assert_frame_equal(dataset[frozen_dataset.columns], frozen_dataset, check_exact=True)
    quality = feature_quality(dataset)
    feature_dataset = {'path': relative(new_feature_path), 'sha256': sha256(new_feature_path),
        'rows': len(dataset), 'columns': list(dataset.columns),
        'prediction_cutoff_exclusive': '2018-05-01T00:00:00', 'added_features': list(ADDED_FEATURES),
        'frozen_columns_preserved': list(frozen_dataset.columns),
        'frozen_values_verified': int(frozen_dataset.size), 'original_holdout_features_generated': False}
    contract = feature_contract()
    contract_hash = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    policies = {**source['policies'],
        'fit': 'same deadline_wait0 IDs/order/daily queries as frozen101; train-only preprocessing',
        'search': 'one prespecified unobserved-handover-age-p90-102 candidate; no parameter/window/support/quantile search; no eval set or early stopping',
        'features': 'original101 plus exactly seller_unobserved_handover_pending_age_p90_hours_90d; frozen137 columns unchanged in138 cache; pending count, completed-handover count and completed-duration quantiles excluded from102',
        'ranker': 'rank:ndcg / native topk10 / L2=100 and all other classifier settings unchanged; training10 is not a dynamic daily10% target',
        'primary_selection': 'frozen79 plus new1; original worst historical recall then pooledTP/AP/fixed order;30% suitability only; no development or subgroup target enters selection',
        'comparison': 'only the feature whitelist changes:101/reference versus102/unobserved-handover pending age p90. Train-only preprocessing and add_indicator rules unchanged; fitted trees/dimensions/feature sampling can differ.',
        'paired_comparison': '101 versus pending-age102 on identical approved orders, labels, queries and complete-day floor10% slots; pending-count102 and completed-count102/104 keep frozen metrics without replay',
        'pending_history': 'Primary-seller other identities approved in[t-90d,t), neither carrier nor delivery observed strictly before t; no final-status/future-delivery filtering',
        'pending_interpretation': 'Missing observation is a proxy; absent ingestion/cancellation clocks prevent claiming physical backlog at approval',
        'feature_scope': 'frozen137 columns plus one new age feature; no pending-count feature in this cache; approvals strictly before2018-05-01; no new holdout features or scores',
        'age_support': 'Linear p90 of t minus historical approval hours among pending, minimum1 event; empty known-seller history and unknown seller remain missing; no manually added count or missingness indicator; original imputer add_indicator preserved',
        'preprocessing_dimensions': 'Record raw whitelist and fitted transformed dimensions separately; the original train-fitted add_indicator may derive an age-missingness column, without a manually added feature or rule change',
        'previous_reuse': '8 existing101 monthly versions replayed;79 old candidate metrics frozen;other624 old monthly versions not rescored',
        'probabilities': 'strictly monotone bounded sigmoid(raw margin), not calibrated probability',
    }
    policies.pop('count_support', None)
    specification = {
        'format_version': 1, 'experiment': 'unobserved_handover_age_ablation', 'seed': 42, 'daily_cap': CAP,
        'minimum_validation_recall': MIN_RECALL, 'primary_selection_prespecified': PRIMARY,
        'candidate_order': list(ORDER), 'matched_candidate_order': list(MATCHED),
        'new_candidate_order': list(NEW), 'reg_lambda': 100., 'pair_method': 'topk', 'num_pair_per_sample': 10, 'added_features': list(ADDED_FEATURES), 'only_changed_component': 'single_seller_unobserved_handover_pending_age_p90_feature', 'compatibility_targets': compatibility_targets(source), 'selection_groups': {k: list(v) for k, v in GROUPS.items()},
        'source_files': manifest, 'feature_dataset': feature_dataset, 'feature_quality': quality,
        'feature_contract': contract, 'feature_contract_sha256': contract_hash,
        'source_signal_audit': {'path': relative(audit_path), 'sha256': sha256(audit_path)},
        'source_feature_script': {'path': relative(ROOT / 'scripts/delay_unobserved_handover_age_features.py'),
                                  'sha256': sha256(ROOT / 'scripts/delay_unobserved_handover_age_features.py')},
        'source_previous_feature_dataset': {k: source['feature_dataset'][k] for k in ('path', 'sha256')},
        'source_report': {'path': relative(args.source_report), 'sha256': sha256(args.source_report)},
        'source_candidate_versions': {'path': relative(archive_path), 'sha256': sha256(archive_path)},
        'source_features': {k: source['source_features'][k] for k in ('path', 'sha256')},
        'source_scores': {k: source['score_export'][k] for k in ('path', 'sha256')},
        'candidate_specifications': {c: {**candidate_design(c), 'feature_set': feature_set(c),
            'numeric_features': feature_names(c)[0], 'categorical_features': feature_names(c)[1],
            'classifier_parameters': parameter_report(make_candidate(c, n_jobs=args.n_jobs).named_steps['classifier'].get_params(deep=False))} for c in MATCHED},
        'policies': policies,
        'official_references': ['https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html',
                                'https://xgboost.readthedocs.io/en/stable/parameter.html'],
    }
    spec_path = output / 'unobserved_handover_age_specification.json'
    fixed_json(spec_path, specification)
    if args.specification_only:
        print(f'Fixed specification: {spec_path}', flush=True)
        return 0
    existing_outputs = [output / 'unobserved_handover_age.json',
                        data_output / 'olist_delay_unobserved_handover_age_scores.csv',
                        *(model_dir / f'olist_delay_unobserved_handover_age_{f["name"]}.joblib' for f in source['folds'])]
    if any(path.exists() for path in existing_outputs):
        raise ValueError('Refusing to overwrite completed experiment outputs; inspect the existing report instead')
    if not args.reuse_new_versions and any(version_dir.glob('*.joblib')):
        raise ValueError('Existing new monthly versions require --reuse-new-versions; they cannot be overwritten')
    parts = []
    for chunk in pd.read_csv(score_path, float_precision='round_trip', chunksize=200000):
        part = chunk.loc[chunk.candidate.isin(REPLAYED)]
        if len(part): parts.append(part)
    old_scores = pd.concat(parts, ignore_index=True)
    phase_indices = old_scores.groupby(['fold', 'role', 'candidate', 'model_version'], sort=False).indices
    monthly_indices = old_scores.groupby(['model_version', 'candidate'], sort=False).indices
    report = {**specification, 'status': 'ok', 'specification_sha256': sha256(spec_path),
        'new_fit_count': len(source['monthly_training']) * len(NEW), 'fit_count_this_execution': 0,
        'reloaded_new_version_count': 0, 'replayed_previous_version_count': 0, 'replayed_previous_candidates': list(REPLAYED),
        'reused_previous_metric_candidates': len(PREVIOUS), 'feature_dataset': feature_dataset,
        'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib', 'xgboost')},
        'previous_primary_context': next(r for r in source['summary'] if r['model_or_selection'] == PRIMARY),
        'monthly_training': [], 'folds': [],
    }
    cache = {}
    for old in source['monthly_training']:
        month = old['month']
        original_splits, split_report = split_rolling_month(dataset, old['split']['model_fit_time'])
        if split_report != old['split']:
            raise ValueError('Original scoring cohort changed')
        splits, training_split = split_outcome_training_month(dataset, old['split']['model_fit_time'], wait_days=0, clock='deadline')
        scoring = splits['scoring']
        if scoring.order_id.tolist() != original_splits['scoring'].order_id.tolist():
            raise ValueError('Objective contrast changed complete scoring rows')
        entry = {'month': month, 'split': split_report, 'models': {}}
        cache[month] = {'frame': scoring, 'scores': {}, 'paths': {}}
        baseline_fit = None
        baseline_transformed_features = None
        for candidate in REPLAYED:
            prior = old['models'][candidate]
            info = prior['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Frozen topk model hash changed')
            artifact = joblib.load(path)
            if (artifact['candidate'] != candidate or artifact['split'] != training_split
                    or artifact['feature_names'] != sum(feature_names(candidate), []) or artifact['source_files'] != manifest):
                raise ValueError('Frozen topk training/feature provenance changed')
            baseline_fit = deepcopy(artifact['fit'])
            baseline_transformed_features = len(artifact['pipeline'].named_steps['preprocessor'].get_feature_names_out())
            verify_training_contract(splits['train'], baseline_fit, baseline_fit)
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(scoring, candidate))
            comparison = old_scores.iloc[monthly_indices[(month, candidate)]]
            if set(comparison.order_id) != set(scoring.order_id):
                raise ValueError('Frozen topk score cohort changed')
            replay = comparison.order_id.map(pd.Series(values, index=scoring.order_id)).to_numpy()
            np.testing.assert_allclose(replay, comparison.delay_score, rtol=0, atol=1e-12)
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            entry['models'][candidate] = {'reused': True, 'version_artifact': info, 'training_split': training_split,
                                           'scoring_rows': len(scoring), 'prior_score_rows_checked': len(comparison),
                                           'transformed_feature_count': baseline_transformed_features}
            report['replayed_previous_version_count'] += 1
            del artifact
        for candidate in NEW:
            path = version_dir / f'olist_delay_{month}_{candidate}.joblib'
            if args.reuse_new_versions and path.exists():
                artifact = joblib.load(path)
                if (artifact['candidate'] != candidate or artifact['split'] != training_split
                        or artifact['feature_names'] != sum(feature_names(candidate), [])
                        or artifact['source_files'] != manifest or artifact['specification_sha256'] != report['specification_sha256']):
                    raise ValueError('Cannot reuse a new ranker with changed provenance')
                pipeline, fit_report = artifact['pipeline'], artifact['fit']
                verify_training_contract(splits['train'], fit_report, baseline_fit)
                with threadpool_limits(limits=1):
                    values = positive_probability(pipeline, prepare_input(scoring, candidate))
                report['reloaded_new_version_count'] += 1
            else:
                if path.exists():
                    raise ValueError('Refusing to overwrite an existing new monthly version')
                print(f'{month}: fitting {candidate}', flush=True)
                pipeline, values, fit_report = fit_version(splits['train'], scoring, candidate, n_jobs=args.n_jobs)
                verify_training_contract(splits['train'], fit_report, baseline_fit)
                artifact = {'pipeline': pipeline, 'candidate': candidate, 'split': training_split,
                            'feature_names': sum(feature_names(candidate), []), 'source_files': manifest,
                            'fit': fit_report, 'feature_set': feature_set(candidate), 'geolocation_used': True,
                            'specification_sha256': report['specification_sha256']}
                joblib.dump(artifact, path, compress=3)
                report['fit_count_this_execution'] += 1
            info = {'path': relative(path), 'sha256': sha256(path)}
            entry['models'][candidate] = {'reused': False, **fit_report, 'version_artifact': info,
                                           'training_split': training_split, 'scoring_rows': len(scoring)}
            entry['preprocessing_dimensions'] = {
                'raw_model_inputs': {'baseline': 101, 'age': 102},
                'baseline_transformed': baseline_transformed_features,
                'age_transformed': fit_report['transformed_feature_count'],
                'transformed_difference': fit_report['transformed_feature_count'] - baseline_transformed_features,
                'age_missing_indicator_from_original_imputer': fit_report['age_missing_indicator_from_original_imputer'],
                'manual_features_added': list(ADDED_FEATURES), 'manual_missingness_indicators_added': [],
            }
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            del artifact, pipeline
            gc.collect()
        report['monthly_training'].append(entry)
        print(f'{month}: matched two versions ready', flush=True)
    score_rows = []
    source_monthly = {m['month']: m for m in source['monthly_training']}
    archive_monthly = {m['month']: m for m in archive['monthly_training']}
    for old in source['folds']:
        name, schedule = old['name'], old['schedule']
        validation = [cache[m['month']]['frame'].reset_index(drop=True) for m in schedule['validation_months']]
        evaluation = cache[name]['frame'].reset_index(drop=True)
        audits = [mature_validation_month(f, schedule['evaluation_start'])[1] for f in validation]
        if audits != old['validation_maturity'] or order_fingerprint(evaluation) != old['order_id_fingerprints']['evaluation']:
            raise ValueError('Historical maturity or development cohort changed')
        for m, frame in zip(schedule['validation_months'], validation, strict=True):
            if order_fingerprint(frame) != old['order_id_fingerprints']['validation_full_by_month'][m['month']]:
                raise ValueError('Full historical scoring identities changed')
        def scores_for(frame):
            month = frame.prediction_time.dt.strftime('%Y-%m').iloc[0]
            return {c: frame.order_id.map(cache[month]['scores'][c]).to_numpy() for c in MATCHED}
        validation_scores, evaluation_scores = [scores_for(f) for f in validation], scores_for(evaluation)
        matched = decide_ranking_fold(validation, validation_scores, evaluation, evaluation_scores,
                                      schedule['evaluation_start'], candidate_order=MATCHED,
                                      selection_groups={'unobserved_handover_age_ablation': MATCHED})
        experiment = merge_experiments(old['experiment'], matched)
        candidate = experiment['selected_models'][PRIMARY]
        decision = experiment['models'][candidate]
        if candidate in MATCHED:
            base_path = cache[name]['paths'][candidate]
            numeric, categorical = feature_names(candidate)
            chosen_feature_set = feature_set(candidate)
        else:
            model_info = source_monthly[name]['models'].get(candidate)
            if model_info is None:
                model_info = archive_monthly[name]['models'][candidate]
            info = model_info['version_artifact']
            base_path = ROOT / info['path']
            if sha256(base_path) != info['sha256']: raise ValueError('Selected old model hash changed')
            numeric, categorical = source_comparison.feature_names(candidate)
            chosen_feature_set = source_comparison.feature_set(candidate)
        base = joblib.load(base_path)
        artifact = {'format_version': 1, 'selected_model': candidate, 'feature_set': chosen_feature_set,
            'pipeline': base['pipeline'], 'threshold': 0., 'daily_alert_cap': CAP,
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**policies, 'research_only': True,
                'schedule': schedule, 'final_split': base['split'], 'source_files': manifest, 'versions': report['versions'],
                'complete_daily_batches_required': True, 'validation_minimum_recall': decision['minimum_validation_month_recall'],
                'historical_floor_met': decision['all_validation_months_meet_30_percent'],
                'base_version_artifact': {'path': relative(base_path), 'sha256': sha256(base_path)}}}
        path = model_dir / f'olist_delay_unobserved_handover_age_{name}.joblib'
        joblib.dump(artifact, path, compress=3)
        report['folds'].append({'name': name, 'schedule': schedule, 'validation_maturity': audits,
            'order_id_fingerprints': old['order_id_fingerprints'], 'experiment': experiment,
            'research_artifact': {'path': relative(path), 'sha256': sha256(path)}})
        for candidate in MATCHED:
            for role, frame, values in [*(('validation', f, s[candidate]) for f, s in zip(validation, validation_scores, strict=True)),
                                       ('evaluation', evaluation, evaluation_scores[candidate])]:
                known = (frame.label_available_time < pd.Timestamp(schedule['evaluation_start'])).to_numpy() if role == 'validation' else np.zeros(len(frame), bool)
                part = frame[['order_id', 'prediction_time']].copy()
                part['fold'], part['role'], part['candidate'] = name, role, candidate
                part['model_version'] = frame.prediction_time.dt.strftime('%Y-%m')
                part['known_at_selection'] = known
                part['outcome_for_metrics'] = np.where(known, frame.delayed, np.nan) if role == 'validation' else frame.delayed.to_numpy()
                part['delay_score'] = values
                part['predicted_delayed'] = apply_alert_policy(frame, values, 0., CAP, raw_scores=values).astype(int)
                if candidate in REPLAYED:
                    comparison = old_scores.iloc[phase_indices[(name, role, candidate, part.model_version.iloc[0])]]
                    verify_prior_score_part(comparison, part)
                score_rows.append(part)
        print(f'{name}: frozen-history selection={experiment["selected_models"][PRIMARY]}; minimum={decision["minimum_validation_month_recall"]:.4f}; development={decision["development_evaluation"]["recall"]:.4f}', flush=True)
    report['summary'] = summarize(report['folds'], candidate_order=ORDER, selection_groups=GROUPS)
    report['paired_comparisons'], report['compatibility_checks'] = paired_comparisons(report['folds'], report['summary'], report['compatibility_targets'])
    primary = next(r for r in report['summary'] if r['model_or_selection'] == PRIMARY)
    report['suitability'] = {
        'historical_validation_floor_met_in_all_folds': not primary['validation_folds_below_30_percent'],
        'observed_development_months_all_above_30_percent': primary['minimum_development_month_recall'] >= MIN_RECALL,
        'independent_future_test_available': False, 'automatic_promotion': False,
    }
    scores_path = data_output / 'olist_delay_unobserved_handover_age_scores.csv'
    pd.concat(score_rows, ignore_index=True).to_csv(scores_path, index=False)
    report['score_export'] = {'path': relative(scores_path), 'rows': sum(len(p) for p in score_rows), 'sha256': sha256(scores_path),
                              'coverage': 'Matched frozen101 and new unobserved-handover age-p90-102 only; other78 previous candidates, including pending-count102 and completed-count102/104, keep frozen source metrics without new scores.'}
    report_path = output / 'unobserved_handover_age.json'
    fixed_json(report_path, report)
    print(f'Report: {report_path}', flush=True)
    print(json.dumps(primary, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    main()
