"""Compare predefined label-waiting schedules and route/promise features."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import warnings

import joblib
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_delay_models import FOLDS
from scripts.delay_alert_policy import choose_recall_threshold
from scripts.delay_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES, CSV_FILES
from scripts.delay_route_features import ROUTE_NUMERIC_FEATURES, ROUTE_CATEGORICAL_FEATURES, build_route_delay_dataset
from scripts.delay_waiting_split import split_waiting_fold, approval_cohort_audit
from scripts.train_delay_model import LABEL_METADATA, make_pipeline, positive_probability, binary_metrics, source_manifest

DEFAULT_OUTPUT = ROOT / 'reports/stage4'
WAIT_DAYS = (30, 60)
PRIMARY_WAIT_DAYS = 60
CANDIDATES = ('random_forest_static', 'logistic_static', 'random_forest_route', 'logistic_route')


def feature_names(candidate):
    if candidate not in CANDIDATES:
        raise ValueError(f'Unknown candidate: {candidate}')
    route = candidate.endswith('_route')
    numeric = list(NUMERIC_FEATURES) + (list(ROUTE_NUMERIC_FEATURES) if route else [])
    categorical = list(CATEGORICAL_FEATURES) + (list(ROUTE_CATEGORICAL_FEATURES) if route else [])
    return numeric, categorical


def prepare_input(frame, candidate):
    numeric, categorical = feature_names(candidate)
    result = frame[numeric + categorical].copy()
    for name in numeric:
        result[name] = pd.to_numeric(result[name], errors='coerce').replace([np.inf, -np.inf], np.nan)
    for name in categorical:
        result[name] = result[name].astype(object).where(result[name].notna(), np.nan)
    return result


def make_candidate(candidate, seed=42, n_jobs=4):
    if candidate not in CANDIDATES:
        raise ValueError(f'Unknown candidate: {candidate}')
    logistic = candidate.startswith('logistic')
    classifier = (LogisticRegression(class_weight='balanced', max_iter=2000, random_state=seed)
                  if logistic else RandomForestClassifier(n_estimators=200, max_depth=14, min_samples_leaf=8,
                         class_weight='balanced_subsample', n_jobs=n_jobs, random_state=seed))
    pipeline = make_pipeline(classifier, scale_numeric=logistic)
    numeric, categorical = feature_names(candidate)
    preprocessor = pipeline.named_steps['preprocessor']
    transformers = list(preprocessor.transformers)
    transformers[0] = (transformers[0][0], transformers[0][1], numeric)
    transformers[1] = (transformers[1][0], transformers[1][1], categorical)
    preprocessor.set_params(transformers=transformers)
    return pipeline


def select_candidate(results):
    """No evaluation values are accepted in the decision key."""
    return min(CANDIDATES, key=lambda name: (
        results[name]['validation']['predicted_positive_rows'],
        results[name]['validation']['confusion_matrix'][0][1],
        -results[name]['validation']['average_precision'], CANDIDATES.index(name)))


def evaluation_segments(frame, scores, threshold):
    """Previously identified groups, inspected only after decisions are frozen."""
    if not {'state_route', 'customer_state', 'estimated_delivery_days'}.issubset(frame.columns):
        return {}
    masks = {f'route_{route}': frame.state_route.eq(route) for route in ('SP->RJ', 'SP->SC', 'SP->BA', 'SP->PE')}
    masks['customer_SP'] = frame.customer_state.eq('SP')
    for low, high, name in ((0, 7, '0-7'), (8, 14, '8-14'), (15, 21, '15-21'),
                             (22, 30, '22-30'), (31, np.inf, '31+')):
        masks[f'promise_{name}'] = frame.estimated_delivery_days.between(low, high)
    predicted = np.asarray(scores) >= threshold
    result = {}
    for name, mask in masks.items():
        y, p = frame.loc[mask, 'delayed'].to_numpy(), predicted[mask.to_numpy()]
        fp, tp = int(((y == 0) & p).sum()), int(((y == 1) & p).sum())
        tn, fn = int(((y == 0) & ~p).sum()), int(((y == 1) & ~p).sum())
        result[name] = {'rows': len(y), 'false_positives': fp, 'true_positives': tp,
            'false_negatives': fn, 'true_negatives': tn, 'on_time_rows': fp + tn, 'delayed_rows': tp + fn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'false_positive_rate': fp / (fp + tn) if fp + tn else None}
    return result


def run_experiment(splits, min_recall=.30, seed=42, n_jobs=4):
    results, pipelines = {}, {}
    with threadpool_limits(limits=n_jobs):
        for candidate in CANDIDATES:
            print(f'  {candidate}: fitting', flush=True)
            pipeline = make_candidate(candidate, seed, n_jobs)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                pipeline.fit(prepare_input(splits['train'], candidate), splits['train'].delayed)
            if isinstance(pipeline.named_steps['classifier'], RandomForestClassifier):
                pipeline.set_params(classifier__n_jobs=1)
            scores = positive_probability(pipeline, prepare_input(splits['validation'], candidate))
            threshold, policy = choose_recall_threshold(splits['validation'].delayed, scores, min_recall)
            numeric, categorical = feature_names(candidate)
            results[candidate] = {
                'feature_set': 'route_promise_90d' if candidate.endswith('_route') else 'approval_static',
                'numeric_features': numeric, 'categorical_features': categorical,
                'classifier_parameters': pipeline.named_steps['classifier'].get_params(deep=False),
                'training_jobs': n_jobs, 'prediction_jobs': 1 if candidate.startswith('random_forest') else n_jobs,
                'fit_warnings': sorted({f'{item.category.__name__}: {item.message}' for item in caught}),
                'threshold': threshold, 'threshold_policy': policy,
                'validation': binary_metrics(splits['validation'].delayed, scores, threshold),
            }
            pipelines[candidate] = pipeline
        selected = select_candidate(results)
        evaluation_scores = {}
        # All decisions above are frozen before inspecting any evaluation outcome.
        for candidate, pipeline in pipelines.items():
            scores = positive_probability(pipeline, prepare_input(splits['evaluation'], candidate))
            if not np.isfinite(scores).all():
                raise ValueError(f'{candidate}: non-finite evaluation score')
            evaluation_scores[candidate] = scores
            results[candidate]['evaluation'] = binary_metrics(splits['evaluation'].delayed, scores,
                                                               results[candidate]['threshold'])
            results[candidate]['evaluation_segments'] = evaluation_segments(
                splits['evaluation'], scores, results[candidate]['threshold'])
    return {'selected_model': selected, 'models': results}, pipelines, evaluation_scores


def summarize(folds, baseline):
    rows = []
    for wait_days in WAIT_DAYS:
        for candidate in (*CANDIDATES, 'validation_selected'):
            metrics = [fold['experiment']['models'][fold['experiment']['selected_model']
                       if candidate == 'validation_selected' else candidate]['evaluation']
                       for fold in folds if fold['wait_days'] == wait_days]
            tn, fp, fn, tp = (int(x) for x in np.sum([m['confusion_matrix'] for m in metrics], axis=0).ravel())
            n = tn + fp + fn + tp
            rows.append({
                'wait_days': wait_days, 'model': candidate, 'rows': n,
                'false_positives': fp, 'true_positives': tp, 'false_negatives': fn, 'true_negatives': tn,
                'alert_rows': fp + tp, 'alert_rate': (fp + tp) / n,
                'precision': tp / (fp + tp) if fp + tp else None, 'recall': tp / (tp + fn),
                'false_positive_rate': fp / (fp + tn), 'false_positives_per_1000_orders': 1000 * fp / n,
                'average_precision_month_mean': float(np.mean([m['average_precision'] for m in metrics])),
                'recall_by_month': [m['recall'] for m in metrics],
                'minimum_month_recall': min(m['recall'] for m in metrics),
                'false_positive_change_vs_legacy_rf_balanced': fp - baseline['false_positives'],
                'true_positive_change_vs_legacy_rf_balanced': tp - baseline['true_positives'],
                'note': 'same evaluation orders; training/validation cohorts and feature sets may differ',
            })
    return rows


def save_figure(report, image_path):
    names = [spec['name'] for spec in FOLDS]
    legacy = report['legacy_context']['folds']
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    x = np.arange(len(names))
    styles = [(-.26, [row['evaluation'] for row in legacy], 'Legacy RF / balanced', '#b66a47',
               [row['validation_positive_retention'] for row in legacy])]
    for offset, wait, color in ((0, 30, '#2878a5'), (.26, 60, '#44885b')):
        folds = [f for f in report['folds'] if f['wait_days'] == wait]
        styles.append((offset, [f['experiment']['models'][f['experiment']['selected_model']]['evaluation'] for f in folds],
                       f'{wait}-day wait / validation-selected', color,
                       [f['split']['partitions']['validation']['positive_retention_rate'] for f in folds]))
    for offset, metrics, label, color, retention in styles:
        bars = axes[0].bar(x + offset, [m['confusion_matrix'][0][1] for m in metrics], width=.26, color=color)
        axes[0].bar_label(bars, fontsize=8)
        axes[1].plot(x, [m['recall'] for m in metrics], 'o-', label=label, color=color)
        axes[2].plot(x, retention, 'o-', color=color)
    axes[0].set(title='False alerts: same evaluation orders', ylabel='False-positive orders')
    axes[0].set_ylim(top=axes[0].get_ylim()[1] * 1.12)
    axes[1].axhline(report['min_validation_recall'], linestyle='--', color='gray',
                    label=f"{report['min_validation_recall']:.0%} validation target (reference)")
    axes[1].set(title='Evaluation recall trade-off', ylabel='Recall', ylim=(0, 1.05))
    axes[2].set(title='Validation delayed-label retention', ylabel='Retained / retrospective eligible delayed', ylim=(0, 1.05))
    for ax in axes:
        ax.set_xticks(x, names)
        ax.grid(axis='y', alpha=.2)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, fontsize=8)
    fig.suptitle('Development experiment: waiting changes cohort recency as well as label availability')
    fig.tight_layout(rect=(0, .14, 1, .98))
    fig.savefig(image_path, dpi=160, bbox_inches='tight')
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--legacy-report', type=Path, default=DEFAULT_OUTPUT / 'alert_optimization.json')
    parser.add_argument('--n-jobs', type=int, default=4)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--min-recall', type=float, default=.30)
    args = parser.parse_args(argv)
    if args.n_jobs < 1 or not 0 <= args.seed < 2**32 or not 0 < args.min_recall <= 1:
        parser.error('Require n-jobs >= 1, 0 <= seed < 2**32, 0 < min-recall <= 1')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    default = output == DEFAULT_OUTPUT.resolve()
    image_dir = ROOT / 'reports/images' if default else output / 'images'
    data_dir = ROOT / 'data/processed' if default else output / 'data'
    model_dir = ROOT / 'models/research' if default else output / 'models'
    for directory in (image_dir, data_dir, model_dir):
        directory.mkdir(parents=True, exist_ok=True)
    legacy = json.loads(args.legacy_report.read_text(encoding='utf-8'))
    manifest = source_manifest(args.data_dir)
    if manifest != legacy['source_files']:
        raise ValueError('Legacy report uses different source data')
    print('Building point-in-time route distributions...', flush=True)
    dataset = build_route_delay_dataset(args.data_dir)
    orders = pd.read_csv(args.data_dir / CSV_FILES['orders'])
    baseline = next(row for row in legacy['summary']
                    if row['model'] == 'random_forest_static' and row['policy'] == 'balanced')
    legacy_folds = []
    for old, specification in zip(legacy['folds'], FOLDS, strict=True):
        if old['name'] != specification['name'] or old['split']['evaluation_start'] != pd.Timestamp(specification['evaluation_start']).isoformat():
            raise ValueError('Legacy evaluation windows differ')
        legacy_folds.append({'name': old['name'], 'evaluation': old['experiment']['models']['random_forest_static']['evaluation']['balanced'],
                             'validation_positive_retention': old['split']['partitions']['validation']['positive_retention_rate']})
    report = {
        'format_version': 1, 'status': 'ok', 'min_validation_recall': args.min_recall,
        'primary_wait_days_prespecified': PRIMARY_WAIT_DAYS, 'wait_days': list(WAIT_DAYS), 'validation_days': 30,
        'seed': args.seed, 'source_files': manifest,
        'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib')},
        'policies': {
            'evaluation_role': 'previously inspected development months, not a new independent test',
            'holdout': 'original 2018-05-26 onward period is not scored in this experiment',
            'primary_schedule': '60 days fixed before results; 30 days is sensitivity analysis, not selected on evaluation',
            'train': 'approvals before validation_start - wait_days; labels strictly before validation_start',
            'validation': '30 approval days ending evaluation_start - wait_days; labels strictly before evaluation_start',
            'evaluation': 'same original monthly eligible-completed cohorts; labels retrospective',
            'selection': 'per schedule/fold, minimum validation alerts at recall floor; ties FP, AP, fixed candidate order',
            'features': '90-day delivery events strictly before approval; calendar-day durations; directed state route',
            'history_bias': 'completed valid-delivery events only; pending/cancelled outcomes are not included',
            'wait_tradeoff': 'waiting changes cohort date ranges and recency, not solely label coverage',
            'promotion': 'research artifacts only; original and balanced inference defaults unchanged',
            'recall': 'validation recall floor does not guarantee later recall',
        },
        'legacy_context': {'summary': baseline, 'folds': legacy_folds,
                           'note': 'same evaluation orders, different training/validation cohorts; no causal wait effect'},
        'folds': [],
    }
    predictions = []
    for wait in WAIT_DAYS:
        for specification in FOLDS:
            print(f"Wait {wait} days; evaluation {specification['name']}", flush=True)
            splits, split_report = split_waiting_fold(dataset, specification['evaluation_start'],
                                                      specification['evaluation_end'], wait_days=wait, validation_days=30)
            old_metrics = next(row['evaluation'] for row in legacy_folds if row['name'] == specification['name'])
            if (len(splits['evaluation']) != old_metrics['rows'] or
                    int(splits['evaluation'].delayed.sum()) != sum(old_metrics['confusion_matrix'][1])):
                raise ValueError('Evaluation cohort differs from legacy experiment')
            experiment, pipelines, scores = run_experiment(splits, args.min_recall, args.seed, args.n_jobs)
            selected = experiment['selected_model']
            result = experiment['models'][selected]
            numeric, categorical = feature_names(selected)
            artifact = {
                'format_version': 1, 'selected_model': selected, 'feature_set': result['feature_set'],
                'pipeline': pipelines[selected], 'threshold': result['threshold'],
                'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
                'label_metadata': LABEL_METADATA,
                'metadata': {**report['policies'], 'split': split_report, 'source_files': manifest,
                             'versions': report['versions'], 'seed': args.seed, 'wait_days': wait,
                             'research_only': True, 'threshold_policy': result['threshold_policy'],
                             'route_parameters': {'window_days': 90, 'prior_strength': 20, 'quantile_method': 'linear',
                                                  'duration': 'delivery calendar date - approval calendar date'}},
            }
            model_path = model_dir / f"olist_delay_wait{wait}_{specification['name']}.joblib"
            joblib.dump(artifact, model_path, compress=3)
            report['folds'].append({'name': specification['name'], 'wait_days': wait, 'split': split_report,
                'approval_cohort_audit': approval_cohort_audit(orders, dataset, split_report), 'experiment': experiment,
                'research_artifact': {'path': str(model_path), 'sha256': hashlib.sha256(model_path.read_bytes()).hexdigest()}})
            for candidate in CANDIDATES:
                part = splits['evaluation'][['order_id', 'delayed']].copy()
                part['fold'] = specification['name']
                part['wait_days'] = wait
                part['candidate'] = candidate
                part['delay_score'] = scores[candidate]
                part['threshold'] = experiment['models'][candidate]['threshold']
                part['predicted_delayed'] = (part.delay_score >= part.threshold).astype(int)
                predictions.append(part)
    report['summary'] = summarize(report['folds'], baseline)
    dataset.to_csv(data_dir / 'olist_delay_route_features.csv', index=False)
    pd.concat(predictions, ignore_index=True).to_csv(data_dir / 'olist_delay_waiting_predictions.csv', index=False)
    save_figure(report, image_dir / 'stage4_waiting_tradeoff.png')
    path = output / 'waiting_strategy_comparison.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    for row in report['summary']:
        if row['model'] == 'validation_selected':
            print(f"Wait {row['wait_days']}: FP={row['false_positives']}; TP={row['true_positives']}; FN={row['false_negatives']}; recall={row['recall']:.2%}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
