"""Compare disjoint historical calibration and complete-day alert budgets.

This is a development replay of previously inspected months. Base estimators
are reused only after their source data, artifact hashes and OOT scores match
the monthly-retraining report. No new independent test is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_waiting_strategies import CANDIDATES, feature_names, prepare_input
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_calibration_policy import (
    fit_calibrator, transform_scores, probability_metrics,
    apply_alert_policy, choose_budget_threshold,
)
from scripts.delay_rolling_validation import split_rolling_month, mature_validation_month
from scripts.delay_route_features import build_route_delay_dataset
from scripts.train_delay_model import LABEL_METADATA, positive_probability, source_manifest

METHODS = ('raw', 'sigmoid', 'isotonic')
BUDGETS = {'uncapped': None, 'cap_05': .05, 'cap_10': .10, 'cap_20': .20}
PRIMARY_METHOD = 'sigmoid'
PRIMARY_BUDGET = 'cap_10'
DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def alert_metrics(labels, scores, predictions):
    """Metrics for the actual capped decisions, not score>=threshold alone."""
    y, p, selected = np.asarray(labels), np.asarray(scores), np.asarray(predictions, dtype=bool)
    if y.ndim != 1 or len(y) != len(p) or len(y) != len(selected) or not np.isin(y, [0, 1]).all():
        raise ValueError('Expected aligned binary outcomes and predictions')
    tn = int(((y == 0) & ~selected).sum())
    fp = int(((y == 0) & selected).sum())
    fn = int(((y == 1) & ~selected).sum())
    tp = int(((y == 1) & selected).sum())
    return {'rows': len(y), 'positive_rows': int(y.sum()), 'positive_rate': float(y.mean()),
        'predicted_positive_rows': int(selected.sum()), 'alert_rate': float(selected.mean()),
        'recall': tp / (tp + fn) if tp + fn else 0., 'precision': tp / (tp + fp) if tp + fp else 0.,
        'average_precision': float(average_precision_score(y, p)) if y.sum() else 0.,
        'roc_auc': float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None,
        'confusion_matrix': [[tn, fp], [fn, tp]],
        'confusion_matrix_order': 'rows=true [on_time,delayed], columns=predicted [on_time,delayed]'}


def batch_audit(frame, selected, cap, known_mask=None):
    """Capacity uses full scoring rows, including rows with unknown outcomes."""
    from decimal import Decimal, ROUND_FLOOR
    known = np.ones(len(frame), dtype=bool) if known_mask is None else np.asarray(known_mask, dtype=bool)
    data = pd.DataFrame({'day': pd.to_datetime(frame.prediction_time).dt.strftime('%Y-%m-%d').to_numpy(),
                         'alert': np.asarray(selected, dtype=bool), 'known': known})
    data['known_alert'] = data.alert & data.known
    rows = []
    for day, part in data.groupby('day', sort=True):
        n, alerts = len(part), int(part.alert.sum())
        capacity = n if cap is None else int((Decimal(str(cap)) * n).to_integral_value(rounding=ROUND_FLOOR))
        if alerts > capacity:
            raise AssertionError('Daily alert capacity exceeded')
        rows.append({'day': day, 'scored_rows': n, 'capacity': capacity, 'alerts': alerts,
                     'alert_rate': alerts / n, 'known_rows': int(part.known.sum()),
                     'known_alerts': int(part.known_alert.sum())})
    return {'scored_rows': len(frame), 'alerts': int(np.sum(selected)),
        'capacity': sum(r['capacity'] for r in rows), 'alert_rate': float(np.mean(selected)),
        'maximum_daily_alert_rate': max(r['alert_rate'] for r in rows),
        'unknown_outcome_alerts': int(np.sum(np.asarray(selected) & ~known)), 'days': rows}


def select_candidate(models, method, budget):
    """Use only policy-month known outcomes and full-batch workload."""
    eligible = [c for c in CANDIDATES if models[c][method]['strategies'][budget]['threshold_policy']['feasible']]
    if eligible:
        def key(candidate):
            row = models[candidate][method]['strategies'][budget]
            return (row['validation_batch']['alerts'], row['validation']['confusion_matrix'][0][1],
                    -models[candidate]['raw_policy_average_precision'], CANDIDATES.index(candidate))
        return min(eligible, key=key)
    def fallback(candidate):
        row = models[candidate][method]['strategies'][budget]
        return (-row['validation']['recall'], row['validation']['confusion_matrix'][0][1],
                row['validation_batch']['alerts'], -models[candidate]['raw_policy_average_precision'], CANDIDATES.index(candidate))
    return min(CANDIDATES, key=fallback)


def decide_calibration_fold(calibration, calibration_scores, policy, policy_scores,
                            evaluation, evaluation_scores, cutoff, min_recall=.30):
    """Fit on first two historical months; choose policy on disjoint third month.

    All three historical cohorts are available at E, not at the start of the
    third month. Unknown policy labels are never read by selection; their
    scores still compete for full-day slots. Evaluation is consulted last.
    """
    boundary = pd.Timestamp(cutoff)
    calibration = calibration.reset_index(drop=True)
    policy = policy.reset_index(drop=True)
    evaluation = evaluation.reset_index(drop=True)
    for part in (calibration, policy, evaluation):
        if part.empty or part.order_id.isna().any() or part.order_id.duplicated().any():
            raise ValueError('Require nonempty unique order cohorts')
    c_months = pd.to_datetime(calibration.prediction_time).dt.to_period('M')
    p_months = pd.to_datetime(policy.prediction_time).dt.to_period('M')
    e_months = pd.to_datetime(evaluation.prediction_time).dt.to_period('M')
    if c_months.nunique() != 2 or p_months.nunique() != 1 or e_months.nunique() != 1:
        raise ValueError('Require two calibration months, one policy month and one evaluation month')
    if not c_months.max() < p_months.min() < e_months.min() or e_months.iloc[0].start_time != boundary:
        raise ValueError('Require calibration < policy < evaluation=cutoff')
    if not (pd.to_datetime(calibration.label_available_time) < boundary).all():
        raise ValueError('Calibration labels must be strictly before selection time')
    if (set(calibration.order_id) & set(policy.order_id) or set(policy.order_id) & set(evaluation.order_id)
            or set(calibration.order_id) & set(evaluation.order_id)):
        raise ValueError('Decision phases must be disjoint')
    known = (pd.to_datetime(policy.label_available_time) < boundary).to_numpy()
    known_labels = pd.to_numeric(policy.loc[known, 'delayed'], errors='raise').to_numpy(dtype=float)
    if not np.array_equal(np.unique(known_labels), [0, 1]):
        raise ValueError('Policy known outcomes must contain both classes')
    selection_labels = np.full(len(policy), np.nan)
    selection_labels[known] = known_labels
    models, calibrators = {}, {}
    for candidate in CANDIDATES:
        c_raw = np.asarray(calibration_scores[candidate])
        p_raw = np.asarray(policy_scores[candidate])
        if len(c_raw) != len(calibration) or len(p_raw) != len(policy):
            raise ValueError('Historical score vectors must align with their phase')
        models[candidate] = {'raw_policy_average_precision': float(average_precision_score(known_labels, p_raw[known]))}
        calibrators[candidate] = {}
        for method in METHODS:
            calibrator = fit_calibrator(calibration.delayed.to_numpy(), c_raw, method)
            calibrators[candidate][method] = calibrator
            c_scores = transform_scores(calibrator, c_raw)
            p_scores = transform_scores(calibrator, p_raw)
            entry = {'calibration': calibrator.to_report(),
                'probability_metrics': {'calibration_fit_descriptive': probability_metrics(calibration.delayed, c_scores),
                                       'policy_validation': probability_metrics(known_labels, p_scores[known])},
                'strategies': {}}
            for budget, cap in BUDGETS.items():
                threshold, rule = choose_budget_threshold(policy, selection_labels, p_scores, cap,
                    min_recall=min_recall, raw_scores=p_raw, known_mask=known)
                selected = apply_alert_policy(policy, p_scores, threshold, cap, raw_scores=p_raw)
                entry['strategies'][budget] = {'threshold': threshold, 'threshold_policy': rule,
                    'validation': alert_metrics(known_labels, p_scores[known], selected[known]),
                    'validation_batch': batch_audit(policy, selected, cap, known)}
            models[candidate][method] = entry
    selections = {method: {budget: select_candidate(models, method, budget) for budget in BUDGETS} for method in METHODS}
    # Decisions above are frozen. Evaluation outcomes and scores enter only here.
    for candidate in CANDIDATES:
        raw = np.asarray(evaluation_scores[candidate])
        if len(raw) != len(evaluation):
            raise ValueError('Evaluation score vector must align')
        for method in METHODS:
            values = transform_scores(calibrators[candidate][method], raw)
            entry = models[candidate][method]
            entry['probability_metrics']['development_evaluation'] = probability_metrics(evaluation.delayed, values)
            for budget, cap in BUDGETS.items():
                decision = entry['strategies'][budget]
                selected = apply_alert_policy(evaluation, values, decision['threshold'], cap, raw_scores=raw)
                decision['evaluation'] = alert_metrics(evaluation.delayed, values, selected)
                decision['evaluation_batch'] = batch_audit(evaluation, selected, cap)
    prevalence = float(calibration.delayed.mean())
    reference = {'probability': prevalence, 'source': 'calibration-fit prevalence; fixed before policy/evaluation',
        'policy_validation': probability_metrics(known_labels, np.full(known.sum(), prevalence)),
        'development_evaluation': probability_metrics(evaluation.delayed, np.full(len(evaluation), prevalence))}
    return {'selected_models': selections, 'models': models, 'constant_probability_reference': reference}, calibrators


def summarize(folds):
    rows = []
    for method in METHODS:
        for budget in BUDGETS:
            for candidate in (*CANDIDATES, 'validation_selected'):
                entries, chosen = [], []
                for fold in folds:
                    selected = fold['experiment']['selected_models'][method][budget] if candidate == 'validation_selected' else candidate
                    chosen.append(selected)
                    entries.append(fold['experiment']['models'][selected][method]['strategies'][budget])
                tn, fp, fn, tp = np.sum([np.array(x['evaluation']['confusion_matrix']).ravel() for x in entries], axis=0).tolist()
                n = tn + fp + fn + tp
                rows.append({'method': method, 'budget': budget, 'model': candidate,
                    'selected_candidates': chosen, 'rows': n, 'false_positives': fp,
                    'true_positives': tp, 'false_negatives': fn, 'true_negatives': tn,
                    'alerts': fp + tp, 'alert_rate': (fp + tp) / n, 'precision': tp / (tp + fp) if tp + fp else 0.,
                    'recall': tp / (tp + fn),
                    'recall_by_month': {f['name']: e['evaluation']['recall'] for f, e in zip(folds, entries, strict=True)},
                    'minimum_evaluation_month_recall': min(e['evaluation']['recall'] for e in entries),
                    'minimum_policy_validation_recall': min(e['validation']['recall'] for e in entries),
                    'infeasible_validation_months': [f['name'] for f, e in zip(folds, entries, strict=True) if not e['threshold_policy']['feasible']],
                    'maximum_daily_alert_rate': max(e['evaluation_batch']['maximum_daily_alert_rate'] for e in entries)})
    return rows


def save_figure(report, path):
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for method, color in zip(METHODS, ('#777777', '#2878a5', '#44885b'), strict=True):
        # Same fixed RF/Route candidate gives a paired calibration comparison.
        metrics = [f['experiment']['models']['random_forest_route'][method]['probability_metrics']['development_evaluation'] for f in report['folds']]
        axes[0, 0].plot([f['name'] for f in report['folds']], [m['brier_score'] for m in metrics], 'o-', color=color, label=method)
        bins = metrics[-1]['reliability_bins']
        nonempty = [b for b in bins if b['rows']]
        axes[0, 1].plot([b['mean_probability'] for b in nonempty], [b['observed_positive_rate'] for b in nonempty], 'o-', color=color, label=method)
    axes[0, 0].plot([f['name'] for f in report['folds']],
        [f['experiment']['constant_probability_reference']['development_evaluation']['brier_score'] for f in report['folds']],
        's--', color='#222222', label='Calibration prevalence')
    axes[0, 0].set(title='Paired RF / Route calibration: development Brier', ylabel='Brier score (lower is better)')
    axes[0, 0].legend()
    axes[0, 1].plot([0, 1], [0, 1], '--', color='gray')
    axes[0, 1].set(title='2018-04 RF / Route reliability (development)', xlabel='Mean predicted probability', ylabel='Observed delay rate')
    x = np.arange(len(report['folds']))
    for budget, color in zip(BUDGETS, ('#777777', '#b66a47', '#2878a5', '#44885b'), strict=True):
        results = [f['experiment']['models'][f['experiment']['selected_models'][PRIMARY_METHOD][budget]][PRIMARY_METHOD]['strategies'][budget]['evaluation'] for f in report['folds']]
        axes[1, 0].plot(x, [r['confusion_matrix'][0][1] for r in results], 'o-', color=color, label=budget)
        axes[1, 1].plot(x, [r['recall'] for r in results], 'o-', color=color, label=budget)
    axes[1, 0].set(title='Sigmoid / validation-selected: false alerts', ylabel='False positives')
    axes[1, 1].set(title='Sigmoid / validation-selected: recall', ylabel='Recall', ylim=(0, 1))
    axes[1, 1].axhline(.30, linestyle='--', color='gray')
    for ax in axes[1]:
        ax.set_xticks(x, [f['name'] for f in report['folds']])
        ax.legend(fontsize=8)
    for ax in axes.flat:
        ax.grid(alpha=.2)
    fig.suptitle('Disjoint historical calibration; complete-day caps on eligible scored orders')
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--rolling-report', type=Path, default=DEFAULT_OUTPUT / 'monthly_retraining.json')
    parser.add_argument('--rolling-scores', type=Path, default=ROOT / 'data/processed/olist_delay_rolling_scores.csv')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    rolling = json.loads(args.rolling_report.read_text(encoding='utf-8'))
    manifest = source_manifest(args.data_dir)
    if manifest != rolling['source_files']:
        raise ValueError('Source data differs from monthly-retraining report')
    output = args.output_dir.resolve()
    default = output == DEFAULT_OUTPUT.resolve()
    image_dir = ROOT / 'reports/images' if default else output / 'images'
    data_dir = ROOT / 'data/processed' if default else output / 'data'
    model_dir = ROOT / 'models/research' if default else output / 'models'
    for directory in (output, image_dir, data_dir, model_dir):
        directory.mkdir(parents=True, exist_ok=True)
    print('Rebuilding point-in-time features from verified local sources', flush=True)
    dataset = build_route_delay_dataset(args.data_dir)
    old_scores = pd.read_csv(args.rolling_scores, float_precision='round_trip')
    if old_scores.duplicated(['fold', 'dataset_split', 'candidate', 'order_id']).any():
        raise ValueError('Duplicate previous OOT score identities')
    expected_groups = {(f['name'], part, c) for f in rolling['folds']
                       for part in ('validation', 'evaluation') for c in CANDIDATES}
    if set(old_scores.groupby(['fold', 'dataset_split', 'candidate']).groups) != expected_groups:
        raise ValueError('Previous OOT score groups are incomplete or unexpected')
    old_times = pd.to_datetime(old_scores.prediction_time, errors='raise')
    if not old_times.dt.strftime('%Y-%m').eq(old_scores.model_version).all():
        raise ValueError('Previous OOT score month/version mismatch')
    scoring_sizes = {m['month']: m['split']['partitions']['scoring']['rows'] for m in rolling['monthly_training']}
    for f in rolling['folds']:
        for part in ('validation', 'evaluation'):
            expected_rows = sum(m['rows'] for m in f['validation_maturity']) if part == 'validation' else scoring_sizes[f['name']]
            for candidate in CANDIDATES:
                old = old_scores.loc[(old_scores.fold == f['name']) & (old_scores.dataset_split == part) & (old_scores.candidate == candidate)]
                if len(old) != expected_rows or order_fingerprint(old) != f['order_id_fingerprints'][part]:
                    raise ValueError('Previous OOT score group row count/identities mismatch')
    cache, version_audit = {}, []
    for month in rolling['monthly_training']:
        name = month['month']
        splits, split_report = split_rolling_month(dataset, month['split']['model_fit_time'])
        if split_report != month['split']:
            raise ValueError(f'Monthly cohort/split mismatch: {name}')
        cache[name] = {'frame': splits['scoring'], 'scores': {}, 'paths': {}}
        for candidate in CANDIDATES:
            info = month['models'][candidate]['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError(f'Historical model hash mismatch: {path}')
            artifact = joblib.load(path)
            if artifact['candidate'] != candidate or artifact['split'] != split_report:
                raise ValueError('Historical artifact metadata mismatch')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(splits['scoring'], candidate))
            old = old_scores.loc[(old_scores.model_version == name) & (old_scores.candidate == candidate)]
            mapped = old.order_id.map(pd.Series(values, index=splits['scoring'].order_id)).to_numpy()
            if not np.isfinite(mapped).all() or not np.allclose(mapped, old.delay_score.to_numpy(), rtol=0, atol=1e-12):
                raise ValueError('Historical OOT score replay mismatch')
            cache[name]['scores'][candidate] = pd.Series(values, index=splits['scoring'].order_id)
            cache[name]['paths'][candidate] = path
            version_audit.append({'month': name, 'candidate': candidate, **info,
                'full_scoring_rows_recomputed': len(values), 'prior_score_rows_checked': len(old)})
        print(f'{name}: four existing versions verified and scored', flush=True)
    report = {'format_version': 1, 'status': 'ok', 'min_validation_recall': .30,
        'primary_method_prespecified': PRIMARY_METHOD, 'primary_budget_prespecified': PRIMARY_BUDGET,
        'methods': list(METHODS), 'daily_budget_fractions': BUDGETS,
        'base_model_fit_count': 0, 'learned_calibrator_fit_count': len(rolling['folds']) * len(CANDIDATES) * 2,
        'source_files': manifest, 'source_rolling_report_sha256': sha256(args.rolling_report),
        'source_rolling_scores_sha256': sha256(args.rolling_scores),
        'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib')},
        'policies': {
            'calibration': 'first two mature historical OOT months; unweighted fit; disjoint from policy month',
            'policy': 'third full historical OOT month; labels strictly before E; all scores count toward daily slots',
            'decision_time': 'calibrator and policy fitted/selected at E; not a deployed as-of-policy-month calibrator',
            'selection': 'feasible candidates: fewest full-batch alerts, known FP, raw AP, fixed order; none feasible: highest known recall then known FP, alerts, raw AP, fixed order',
            'fallback': 'if 30% recall infeasible under cap, threshold=0 maximizes recall; cap takes priority; report infeasible',
            'budget': 'floor(fraction * full eligible scored daily cohort); no carryover; unknown outcomes retain slots; small batches may have zero capacity',
            'batch_timing': 'day closes before ranking; up to one day wait after approval; not immediate per-order inference',
            'ranking': 'calibrated score descending, raw score descending, order_id ascending; threshold includes ties then daily top-K',
            'calibration_transfer': 'one pooled historical mapping transfers to E model; cannot guarantee probability calibration or recall of a new version',
            'coverage': 'historical denominator is valid eventually-delivered cohort, not every raw approved order; mature outcomes may be selectively observed',
            'evaluation_role': 'three previously inspected development months; later folds can use earlier months as historical data; not independent tests',
            'holdout': 'original 2018-05-26 onward period not scored',
            'promotion': 'research only; existing defaults and all previous artifacts preserved',
        }, 'historical_version_audit': version_audit, 'folds': []}
    output_scores = []
    for fold in rolling['folds']:
        name, schedule = fold['name'], fold['schedule']
        months = [m['month'] for m in schedule['validation_months']]
        mature, audits = [], []
        for month in months:
            part, audit = mature_validation_month(cache[month]['frame'], schedule['evaluation_start'])
            mature.append(part)
            audits.append(audit)
        calibration = pd.concat(mature[:2], ignore_index=True)
        policy = cache[months[2]]['frame'].reset_index(drop=True)
        evaluation = cache[name]['frame'].reset_index(drop=True)
        if order_fingerprint(evaluation) != fold['order_id_fingerprints']['evaluation']:
            raise ValueError('Development evaluation identities differ')
        def phase_scores(frame):
            model_months = frame.prediction_time.dt.strftime('%Y-%m')
            return {c: np.array([cache[m]['scores'][c].loc[oid] for m, oid in zip(model_months, frame.order_id, strict=True)]) for c in CANDIDATES}
        c_scores, p_scores, e_scores = phase_scores(calibration), phase_scores(policy), phase_scores(evaluation)
        experiment, calibrators = decide_calibration_fold(calibration, c_scores, policy, p_scores,
            evaluation, e_scores, schedule['evaluation_start'])
        candidate = experiment['selected_models'][PRIMARY_METHOD][PRIMARY_BUDGET]
        decision = experiment['models'][candidate][PRIMARY_METHOD]['strategies'][PRIMARY_BUDGET]
        numeric, categorical = feature_names(candidate)
        base = joblib.load(cache[name]['paths'][candidate])
        artifact = {'format_version': 1, 'selected_model': candidate,
            'feature_set': 'route_promise_90d' if candidate.endswith('_route') else 'approval_static',
            'pipeline': base['pipeline'], 'calibrator': calibrators[candidate][PRIMARY_METHOD],
            'threshold': decision['threshold'], 'daily_alert_cap': BUDGETS[PRIMARY_BUDGET],
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**report['policies'], 'research_only': True,
                'schedule': schedule, 'source_files': manifest, 'versions': report['versions'],
                'final_split': base['split'],
                'base_version_artifact': {'path': cache[name]['paths'][candidate].relative_to(ROOT).as_posix(),
                                          'sha256': sha256(cache[name]['paths'][candidate])},
                'calibration_months': months[:2], 'policy_month': months[2],
                'calibration_report': calibrators[candidate][PRIMARY_METHOD].to_report(),
                'threshold_policy': decision['threshold_policy'], 'complete_daily_batches_required': True}}
        model_path = model_dir / f'olist_delay_calibrated_budget_{name}.joblib'
        joblib.dump(artifact, model_path, compress=3)
        report['folds'].append({'name': name, 'schedule': schedule,
            'phases': {'calibration_months': months[:2], 'policy_month': months[2],
                'calibration_known_rows': len(calibration), 'policy_full_rows': len(policy), 'policy_known_rows': len(mature[2]),
                'maturity': audits, 'label_cutoff': schedule['evaluation_start']},
            'order_id_fingerprints': {'calibration_known': order_fingerprint(calibration), 'policy_full': order_fingerprint(policy),
                                     'policy_known': order_fingerprint(mature[2]), 'evaluation': order_fingerprint(evaluation)},
            'experiment': experiment, 'research_artifact': {'path': model_path.relative_to(ROOT).as_posix() if model_path.is_relative_to(ROOT) else str(model_path),
                'sha256': sha256(model_path)}})
        for candidate in CANDIDATES:
            for phase, frame, raw in (('calibration', calibration, c_scores[candidate]), ('policy', policy, p_scores[candidate]), ('evaluation', evaluation, e_scores[candidate])):
                known = np.ones(len(frame), dtype=bool) if phase != 'policy' else (frame.label_available_time < pd.Timestamp(schedule['evaluation_start'])).to_numpy()
                for method in METHODS:
                    values = transform_scores(calibrators[candidate][method], raw)
                    part = frame[['order_id', 'prediction_time']].copy()
                    part['fold'], part['phase'], part['candidate'], part['method'] = name, phase, candidate, method
                    part['model_version'] = frame.prediction_time.dt.strftime('%Y-%m')
                    part['known_outcome_at_selection'] = known if phase != 'evaluation' else False
                    part['outcome_for_metrics'] = np.where(known, frame.delayed, np.nan)
                    part['raw_delay_score'], part['delay_probability'] = raw, values
                    if phase != 'calibration':
                        for budget, cap in BUDGETS.items():
                            threshold = experiment['models'][candidate][method]['strategies'][budget]['threshold']
                            part[f'threshold_{budget}'] = threshold
                            part[f'predicted_{budget}'] = apply_alert_policy(frame, values, threshold, cap, raw_scores=raw).astype(int)
                    output_scores.append(part)
        primary_candidate = experiment['selected_models'][PRIMARY_METHOD][PRIMARY_BUDGET]
        print(f'{name}: primary={primary_candidate}; feasible={decision["threshold_policy"]["feasible"]}; FP={decision["evaluation"]["confusion_matrix"][0][1]}; recall={decision["evaluation"]["recall"]:.4f}', flush=True)
    report['summary'] = summarize(report['folds'])
    pd.concat(output_scores, ignore_index=True).to_csv(data_dir / 'olist_delay_calibration_budget_scores.csv', index=False)
    save_figure(report, image_dir / 'stage4_calibration_budget.png')
    path = output / 'calibration_budget.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
