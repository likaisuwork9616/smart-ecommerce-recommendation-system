"""Compare only daily XGBoost ranker L2 strength on frozen 83/101 features."""
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

from scripts import delay_backlog_training as previous_training
from scripts import delay_objective_training as objective_training
from scripts import compare_backlog_objectives as source_comparison
from scripts import delay_rank_regularization as training
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_budget_training import CAP, MIN_RECALL, decide_ranking_fold, parameter_report, select_candidate, summarize
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.delay_outcome_clock import add_training_outcome_clock, split_outcome_training_month
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.train_backlog_changes import verify_prior_score_part
from scripts.train_delay_model import LABEL_METADATA, positive_probability

CLASSIFIERS = source_comparison.CLASSIFIERS
BASELINE_RANKERS = source_comparison.RANKERS
REPLAYED = (*CLASSIFIERS, *BASELINE_RANKERS)
NEW = training.NEW_CANDIDATES
MATCHED = (*REPLAYED, *NEW)
PREVIOUS = source_comparison.ORDER
ORDER = (*PREVIOUS, *NEW)
PRIMARY = 'primary_without_dispatch'
GROUPS = {
    'previous_candidates': PREVIOUS,
    'geo_rank_l2': (BASELINE_RANKERS[0], *NEW[:2]),
    'backlog_rank_l2': (BASELINE_RANKERS[1], *NEW[2:]),
    'all_rank_l2': (*BASELINE_RANKERS, *NEW),
    'matched_eight': MATCHED, PRIMARY: ORDER,
}
DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def feature_names(candidate):
    return training.feature_names(candidate) if candidate in (*BASELINE_RANKERS, *NEW) else previous_training.feature_names(candidate)


def prepare_input(frame, candidate):
    return training.prepare_input(frame, candidate) if candidate in (*BASELINE_RANKERS, *NEW) else previous_training.prepare_input(frame, candidate)


def feature_set(candidate):
    return training.feature_set(candidate) if candidate in (*BASELINE_RANKERS, *NEW) else previous_training.feature_set(candidate)


def make_candidate(candidate, seed=42, n_jobs=2):
    return training.make_candidate(candidate, seed, n_jobs) if candidate in (*BASELINE_RANKERS, *NEW) else objective_training.make_candidate(candidate, seed, n_jobs)


def candidate_design(candidate):
    if candidate in (*BASELINE_RANKERS, *NEW):
        return training.candidate_design(candidate)
    return {**objective_training.candidate_design(candidate), 'baseline_candidate': candidate,
            'reg_lambda': 10., 'comparison_role': 'frozen_classifier_context'}


def merge_experiments(previous, matched):
    """Reuse frozen previous metrics; choose only by historical fields.

    Four previous classifiers/rankers are replayed in full. The
    other 63 previous metric records remain bound to the frozen source hash.
    Development fields never enter select_candidate's key.
    """
    if set(previous['models']) != set(PREVIOUS) or set(matched['models']) != set(MATCHED):
        raise ValueError('Require the frozen 67 and matched eight model records')
    for candidate in REPLAYED:
        if previous['models'][candidate] != matched['models'][candidate]:
            raise ValueError(f'Frozen classifier metrics changed: {candidate}')
    models = deepcopy(previous['models'])
    models.update({c: deepcopy(matched['models'][c]) for c in NEW})
    selected = {name: select_candidate(models, candidates, ORDER) for name, candidates in GROUPS.items()}
    if selected['previous_candidates'] != previous['selected_models'][PRIMARY]:
        raise ValueError('Frozen previous 67-candidate selection changed')
    return {'models': models, 'selected_models': selected}


def read_features(path, data_dir):
    frame = pd.read_csv(path, float_precision='round_trip', dtype={c: object for c in (
        *CATEGORICAL_FEATURES, 'state_route_promise_bin', 'state_route_promise_growth_bin')})
    for name in ('prediction_time', 'label_available_time', 'order_purchase_timestamp', 'training_outcome_known_time'):
        frame[name] = pd.to_datetime(frame[name])
    return add_training_outcome_clock(frame, pd.read_csv(data_dir / 'olist_orders_dataset.csv'))


def paired_comparisons(folds, summary):
    indexed = {r['model_or_selection']: r for r in summary}
    rows = []
    for label, baseline, candidates in (('geo83', BASELINE_RANKERS[0], NEW[:2]),
                                        ('backlog101', BASELINE_RANKERS[1], NEW[2:])):
        cells = {'10': baseline, **{str(int(training.candidate_design(c)['reg_lambda'])): c for c in candidates}}
        rows.append({'feature_package': label, 'baseline': baseline, 'candidates_by_l2': cells,
                     'development_true_positives': {v: indexed[c]['true_positives'] for v,c in cells.items()},
                     'development_recall': {v: indexed[c]['recall'] for v,c in cells.items()},
                     'net_TP_vs_l2_10': {v: indexed[c]['true_positives']-indexed[baseline]['true_positives'] for v,c in cells.items()},
                     'by_fold': {f['name']: {v: {
                         'candidate': c,
                         'minimum_validation_month_recall': f['experiment']['models'][c]['minimum_validation_month_recall'],
                         'validation_by_month': f['experiment']['models'][c]['validation_by_month'],
                         'development': f['experiment']['models'][c]['development_evaluation'],
                     } for v,c in cells.items()} for f in folds}})
    return rows


def main(argv=None):
    from scripts.delay_rank_regularization import fit_version

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--source-report', type=Path, default=DEFAULT_OUTPUT / 'backlog_objectives.json')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--n-jobs', type=int, default=2)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--reuse-new-versions', action='store_true', help='Reuse only own versions with identical specification and provenance.')
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error('Require positive n-jobs')
    source = json.loads(args.source_report.read_text(encoding='utf-8'))
    manifest = engineering_source_manifest(args.data_dir)
    if source['status'] != 'ok' or source['candidate_order'] != list(PREVIOUS) or manifest != source['source_files']:
        raise ValueError('Require the frozen completed 67-candidate objective experiment')
    archive_path = ROOT / source['source_report']['path']
    if sha256(archive_path) != source['source_report']['sha256']:
        raise ValueError('Frozen earlier candidate version manifest changed')
    archive = json.loads(archive_path.read_text(encoding='utf-8'))
    feature_path, score_path = (ROOT / source[k]['path'] for k in ('feature_dataset', 'score_export'))
    if sha256(feature_path) != source['feature_dataset']['sha256'] or sha256(score_path) != source['score_export']['sha256']:
        raise ValueError('Frozen feature or score source changed')
    output = args.output_dir.resolve()
    model_dir = ROOT / 'models/research' if output == DEFAULT_OUTPUT.resolve() else output / 'models'
    data_output = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    version_dir = model_dir / 'rank_regularization_versions'
    for p in (output, data_output, version_dir):
        p.mkdir(parents=True, exist_ok=True)
    policies = {**source['policies'],
        'fit': 'same deadline_wait0 train identities and approval/order-ID sort as paired frozen classifiers; train-only preprocessing',
        'search': 'fixed L2 values1/10/100 on each geo83/backlog101 ranker;10 reused and only1/100 newly fitted; no adaptive expansion, eval set or early stopping',
        'features': 'exact frozen 83/101 column packages; no new features or recalculation',
        'ranker': 'rank:ndcg, topk pair construction20, binary gains; fixed top20 training focus is not each day variable10% cutoff',
        'training_queries': 'contiguous approval days among eligible mature training rows; retain all-positive/all-negative groups, which supply no unlike-label pairs',
        'primary_selection': 'frozen67 plus new4, worst historical recall then pooledTP/AP/fixed order; 30% is suitability only; September route outcomes never override this rule',
        'comparison': 'Only reg_lambda changes; feature columns, train rows/order/query sizes, preprocessing, every other wrapper/native ranker parameter, seed and objective unchanged',
        'previous_reuse': '32 previous paired versions replayed (16 classifiers,16 L2=10 rankers); all67 previous metric records copied value-for-value from SHA-bound source; other504 old versions not rescored',
        'probabilities': 'rank sigmoid is a strictly monotone bounded interface, never calibrated probability; reject distinct-margin collapse',
    }
    specification = {
        'format_version': 1, 'experiment': 'rank_l2_regularization', 'seed': 42, 'daily_cap': CAP,
        'minimum_validation_recall': MIN_RECALL, 'primary_selection_prespecified': PRIMARY,
        'candidate_order': list(ORDER), 'matched_candidate_order': list(MATCHED),
        'new_candidate_order': list(NEW), 'l2_values': list(training.L2_VALUES), 'only_changed_parameter': 'reg_lambda', 'selection_groups': {k: list(v) for k, v in GROUPS.items()},
        'source_files': manifest, 'source_report': {'path': relative(args.source_report), 'sha256': sha256(args.source_report)},
        'source_candidate_versions': {'path': relative(archive_path), 'sha256': sha256(archive_path)},
        'source_features': {k: source['feature_dataset'][k] for k in ('path', 'sha256')},
        'source_scores': {k: source['score_export'][k] for k in ('path', 'sha256')},
        'candidate_specifications': {c: {**candidate_design(c), 'feature_set': feature_set(c),
            'numeric_features': feature_names(c)[0], 'categorical_features': feature_names(c)[1],
            'classifier_parameters': parameter_report(make_candidate(c, n_jobs=args.n_jobs).named_steps['classifier'].get_params(deep=False))} for c in MATCHED},
        'policies': policies,
        'official_references': ['https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html',
                                'https://xgboost.readthedocs.io/en/stable/parameter.html'],
    }
    spec_path = output / 'rank_regularization_specification.json'
    if spec_path.exists() and json.loads(spec_path.read_text(encoding='utf-8')) != specification:
        raise ValueError('Refusing to change the already fixed objective specification')
    if not spec_path.exists():
        spec_path.write_text(json.dumps(specification, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    if args.specification_only:
        print(f'Fixed specification: {spec_path}', flush=True)
        return 0
    dataset = read_features(feature_path, args.data_dir)
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
        'reused_previous_metric_candidates': len(PREVIOUS), 'feature_dataset': source['feature_dataset'],
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
        for candidate in REPLAYED:
            prior = old['models'][candidate]
            info = prior['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Classifier model hash changed')
            artifact = joblib.load(path)
            if (artifact['candidate'] != candidate or artifact['split'] != training_split
                    or artifact['feature_names'] != sum(feature_names(candidate), []) or artifact['source_files'] != manifest):
                raise ValueError('Classifier training/feature provenance changed')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(scoring, candidate))
            comparison = old_scores.iloc[monthly_indices[(month, candidate)]]
            if set(comparison.order_id) != set(scoring.order_id):
                raise ValueError('Frozen classifier score cohort changed')
            replay = comparison.order_id.map(pd.Series(values, index=scoring.order_id)).to_numpy()
            np.testing.assert_allclose(replay, comparison.delay_score, rtol=0, atol=1e-12)
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            entry['models'][candidate] = {'reused': True, 'version_artifact': info, 'training_split': training_split,
                                           'scoring_rows': len(scoring), 'prior_score_rows_checked': len(comparison)}
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
                with threadpool_limits(limits=1):
                    values = positive_probability(pipeline, prepare_input(scoring, candidate))
                report['reloaded_new_version_count'] += 1
            else:
                print(f'{month}: fitting {candidate}', flush=True)
                pipeline, values, fit_report = fit_version(splits['train'], scoring, candidate, n_jobs=args.n_jobs)
                artifact = {'pipeline': pipeline, 'candidate': candidate, 'split': training_split,
                            'feature_names': sum(feature_names(candidate), []), 'source_files': manifest,
                            'fit': fit_report, 'feature_set': feature_set(candidate), 'geolocation_used': True,
                            'specification_sha256': report['specification_sha256']}
                joblib.dump(artifact, path, compress=3)
                report['fit_count_this_execution'] += 1
            info = {'path': relative(path), 'sha256': sha256(path)}
            entry['models'][candidate] = {'reused': False, **fit_report, 'version_artifact': info,
                                           'training_split': training_split, 'scoring_rows': len(scoring)}
            cache[month]['scores'][candidate] = pd.Series(values, index=scoring.order_id)
            cache[month]['paths'][candidate] = path
            del artifact, pipeline
            gc.collect()
        report['monthly_training'].append(entry)
        print(f'{month}: matched eight versions ready', flush=True)
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
                                      selection_groups={'matched_eight': MATCHED})
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
            numeric, categorical = previous_training.feature_names(candidate)
            chosen_feature_set = previous_training.feature_set(candidate)
        base = joblib.load(base_path)
        artifact = {'format_version': 1, 'selected_model': candidate, 'feature_set': chosen_feature_set,
            'pipeline': base['pipeline'], 'threshold': 0., 'daily_alert_cap': CAP,
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**policies, 'research_only': True,
                'schedule': schedule, 'final_split': base['split'], 'source_files': manifest, 'versions': report['versions'],
                'complete_daily_batches_required': True, 'validation_minimum_recall': decision['minimum_validation_month_recall'],
                'historical_floor_met': decision['all_validation_months_meet_30_percent'],
                'base_version_artifact': {'path': relative(base_path), 'sha256': sha256(base_path)}}}
        path = model_dir / f'olist_delay_rank_l2_{name}.joblib'
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
    report['paired_comparisons'] = paired_comparisons(report['folds'], report['summary'])
    primary = next(r for r in report['summary'] if r['model_or_selection'] == PRIMARY)
    report['suitability'] = {
        'historical_validation_floor_met_in_all_folds': not primary['validation_folds_below_30_percent'],
        'observed_development_months_all_above_30_percent': primary['minimum_development_month_recall'] >= MIN_RECALL,
        'independent_future_test_available': False, 'automatic_promotion': False,
    }
    scores_path = data_output / 'olist_delay_rank_l2_scores.csv'
    pd.concat(score_rows, ignore_index=True).to_csv(scores_path, index=False)
    report['score_export'] = {'path': relative(scores_path), 'rows': sum(len(p) for p in score_rows), 'sha256': sha256(scores_path),
                              'coverage': 'Matched eight candidates only; other63 previous metrics are frozen source records, not new scores.'}
    report_path = output / 'rank_regularization.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Report: {report_path}', flush=True)
    print(json.dumps(primary, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    main()
