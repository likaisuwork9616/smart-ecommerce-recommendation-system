"""Reduce alert volume at a validation recall target, with time-safe history."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
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

from scripts.compare_delay_models import FOLDS, split_backtest_fold
from scripts.delay_alert_policy import choose_recall_threshold
from scripts.delay_features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from scripts.delay_history_features import HISTORY_NUMERIC_FEATURES, build_history_delay_dataset
from scripts.train_delay_model import (
    LABEL_METADATA, binary_metrics, choose_threshold, chronological_split,
    make_pipeline, positive_probability, source_manifest,
)

DEFAULT_OUTPUT = ROOT / 'reports/stage4'
CANDIDATES = ('random_forest_static', 'logistic_static', 'random_forest_history', 'logistic_history')


def feature_names(use_history):
    numeric = NUMERIC_FEATURES + (HISTORY_NUMERIC_FEATURES if use_history else [])
    return numeric, numeric + CATEGORICAL_FEATURES


def prepare_input(frame, use_history):
    numeric, names = feature_names(use_history)
    result = frame[names].copy()
    for name in numeric:
        result[name] = pd.to_numeric(result[name], errors='coerce').replace([np.inf, -np.inf], np.nan)
    for name in CATEGORICAL_FEATURES:
        result[name] = result[name].astype(object).where(result[name].notna(), np.nan)
    return result


def make_candidate(name, seed, n_jobs):
    is_logistic = name.startswith('logistic')
    classifier = (
        LogisticRegression(class_weight='balanced', max_iter=2000, random_state=seed)
        if is_logistic else
        RandomForestClassifier(n_estimators=200, max_depth=14, min_samples_leaf=8,
                               class_weight='balanced_subsample', n_jobs=n_jobs, random_state=seed)
    )
    pipeline = make_pipeline(classifier, scale_numeric=is_logistic)
    if name.endswith('_history'):
        preprocessor = pipeline.named_steps['preprocessor']
        transformers = list(preprocessor.transformers)
        numeric_name, numeric_transformer, _ = transformers[0]
        transformers[0] = (numeric_name, numeric_transformer, feature_names(True)[0])
        preprocessor.set_params(transformers=transformers)
    return pipeline


def select_candidate(results):
    """Select solely from validation alert counts at the recall constraint."""
    return min(CANDIDATES, key=lambda name: (
        results[name]['validation']['balanced']['predicted_positive_rows'],
        results[name]['validation']['balanced']['confusion_matrix'][0][1],
        -results[name]['validation']['balanced']['average_precision'],
        CANDIDATES.index(name),
    ))


def run_experiment(splits, min_recall, seed, n_jobs):
    """Freeze all decisions from train/validation before any evaluation scoring."""
    results, fitted = {}, {}
    with threadpool_limits(limits=n_jobs):
        for name in CANDIDATES:
            print(f'  {name}: training...', flush=True)
            history = name.endswith('_history')
            pipeline = make_candidate(name, seed, n_jobs)
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter('always')
                pipeline.fit(prepare_input(splits['train'], history), splits['train']['delayed'])
            # Parallel tree summation can move a boundary score by a few ULPs.
            # Keep fit parallel, but freeze validation and saved inference to
            # deterministic tree order so the recall constraint survives reload.
            if isinstance(pipeline.named_steps['classifier'], RandomForestClassifier):
                pipeline.set_params(classifier__n_jobs=1)
            scores = positive_probability(pipeline, prepare_input(splits['validation'], history))
            if not np.isfinite(scores).all():
                raise ValueError(f'{name}: non-finite validation scores')
            f1_threshold, f1_policy = choose_threshold(splits['validation']['delayed'], scores)
            threshold, policy = choose_recall_threshold(splits['validation']['delayed'], scores, min_recall)
            results[name] = {
                'feature_set': 'delivery_history_90d' if history else 'approval_static',
                'feature_names': feature_names(history)[1],
                'classifier_parameters': pipeline.named_steps['classifier'].get_params(deep=False),
                'training_jobs': n_jobs,
                'prediction_jobs': 1 if name.startswith('random_forest') else n_jobs,
                'fit_warnings': sorted({f'{item.category.__name__}: {item.message}' for item in captured}),
                'thresholds': {'f1': f1_threshold, 'balanced': threshold},
                'threshold_policies': {'f1': f1_policy, 'balanced': policy},
                'validation': {
                    'f1': binary_metrics(splits['validation']['delayed'], scores, f1_threshold),
                    'balanced': binary_metrics(splits['validation']['delayed'], scores, threshold),
                },
            }
            fitted[name] = pipeline
        selected = select_candidate(results)
        # Neither model choice nor thresholds below depend on evaluation labels/scores.
        for name, pipeline in fitted.items():
            scores = positive_probability(pipeline, prepare_input(splits['evaluation'], name.endswith('_history')))
            if not np.isfinite(scores).all():
                raise ValueError(f'{name}: non-finite evaluation scores')
            results[name]['evaluation'] = {
                policy: binary_metrics(splits['evaluation']['delayed'], scores, threshold)
                for policy, threshold in results[name]['thresholds'].items()
            }
    return {'selected_model': selected, 'models': results}, fitted


def summarize(folds):
    strategies = [(name, policy) for name in CANDIDATES for policy in ('f1', 'balanced')]
    strategies.append(('validation_selected', 'balanced'))
    summary = []
    for name, policy in strategies:
        metrics = [fold['experiment']['models'][
            fold['experiment']['selected_model'] if name == 'validation_selected' else name
        ]['evaluation'][policy] for fold in folds]
        matrix = np.sum([item['confusion_matrix'] for item in metrics], axis=0)
        tn, fp, fn, tp = (int(value) for value in matrix.ravel())
        rows = tn + fp + fn + tp
        summary.append({
            'model': name, 'policy': policy, 'rows': rows,
            'true_positives': tp, 'false_positives': fp, 'false_negatives': fn, 'true_negatives': tn,
            'alert_rows': tp + fp, 'alert_rate': (tp + fp) / rows,
            'precision': tp / (tp + fp) if tp + fp else 0.0,
            'recall': tp / (tp + fn), 'f1': 2 * tp / (2 * tp + fp + fn),
            'false_positive_rate': fp / (tn + fp),
            'false_positives_per_1000_orders': 1000 * fp / rows,
            'average_precision_mean': float(np.mean([item['average_precision'] for item in metrics])),
            'recall_by_fold': [item['recall'] for item in metrics],
        })
    baseline = summary[0]
    for item in summary:
        item['false_positive_reduction_vs_rf_f1'] = 1 - item['false_positives'] / baseline['false_positives']
        item['true_positive_retention_vs_rf_f1'] = item['true_positives'] / baseline['true_positives']
    return summary


def save_figure(folds, path, min_recall):
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [fold['name'] for fold in folds]
    baseline = [fold['experiment']['models']['random_forest_static']['evaluation']['f1'] for fold in folds]
    balanced = [fold['experiment']['models'][fold['experiment']['selected_model']]['evaluation']['balanced']
                for fold in folds]
    rf_balanced = [fold['experiment']['models']['random_forest_static']['evaluation']['balanced'] for fold in folds]
    positions = np.arange(len(folds))
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    for offset, rows, label, color in ((-.26, baseline, 'Original RF / F1', '#b66a47'),
                                      (0, rf_balanced, 'RF / balanced', '#2878a5'),
                                      (.26, balanced, 'Selected candidates (experimental)', '#888888')):
        bars = axes[0].bar(positions + offset, [row['confusion_matrix'][0][1] for row in rows],
                           width=.26, label=label, color=color)
        axes[0].bar_label(bars, fontsize=9)
        axes[1].plot(positions, [row['recall'] for row in rows], marker='o', label=label, color=color)
    axes[0].set(ylabel='False-positive orders', title='False alerts on the same monthly cohorts',
                xticks=positions, xticklabels=names)
    axes[1].axhline(min_recall, color='gray', linestyle='--',
                    label=f'{min_recall:.0%} validation target (reference)')
    axes[1].set(ylabel='Actual evaluation recall', title='Recall trade-off', ylim=(0, 1),
                xticks=positions, xticklabels=names)
    handles, labels = axes[1].get_legend_handles_labels()
    figure.legend(handles, labels, fontsize=8, loc='lower center', ncol=2)
    figure.suptitle('Development backtest: false alerts and missed delays')
    figure.tight_layout(rect=(0, .14, 1, .98))
    figure.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(figure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--model-path', type=Path, default=ROOT / 'models/olist_delay_balanced.joblib')
    parser.add_argument('--min-recall', type=float, default=.30)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--n-jobs', type=int, default=4)
    args = parser.parse_args(argv)
    if not 0 < args.min_recall <= 1 or args.n_jobs < 1 or not 0 <= args.seed < 2**32:
        parser.error('Require 0 < min-recall <= 1, n-jobs >= 1 and 0 <= seed < 2**32')
    output = args.output_dir.resolve()
    image_dir = ROOT / 'reports/images' if output == DEFAULT_OUTPUT.resolve() else output / 'images'
    output.mkdir(parents=True, exist_ok=True)
    print('Building order-time delivery history...', flush=True)
    dataset = build_history_delay_dataset(args.data_dir.resolve())
    report = {
        'format_version': 1, 'status': 'ok', 'seed': args.seed, 'min_validation_recall': args.min_recall,
        'versions': {'python': platform.python_version(), **{
            package: version(package) for package in ('pandas', 'numpy', 'scikit-learn', 'joblib')
        }},
        'source_files': source_manifest(args.data_dir.resolve()),
        'history_numeric_features': HISTORY_NUMERIC_FEATURES,
        'policies': {
            'purpose': 'development alert optimization; no new independent final test',
            'selection': 'minimum validation alerts at recall target; tie: fewer FP, higher AP, candidate order',
            'threshold': 'highest score threshold achieving min recall on validation only; ties stay together',
            'history': '[approval - 90 days, approval), using completed eligible deliveries only',
            'history_update': 'known delivery outcomes update features as time passes, including within validation/evaluation',
            'history_prior': 'global rate fixed prior .05 with strength20; seller/route rates shrink to current global rate',
            'preprocessing': 'fit only on each maturity-purged train; numeric history columns are included in pipeline',
            'original_holdout': 'already inspected; final-period scores are retrospective diagnostics only, never model/threshold selection',
            'promotion': 'save separate balanced artifact; original artifact and original reports remain intact',
            'recall_guarantee': 'validation target is not a guarantee for later evaluation or live orders',
        },
        'folds': [],
    }
    for specification in FOLDS:
        print(f"Backtest {specification['name']}", flush=True)
        splits, split_report = split_backtest_fold(
            dataset, specification['validation_start'], specification['evaluation_start'],
            specification['evaluation_end'], validation_end=specification['validation_end'],
        )
        experiment, _ = run_experiment(splits, args.min_recall, args.seed, args.n_jobs)
        report['folds'].append({'name': specification['name'], 'split': split_report, 'experiment': experiment})
    report['summary'] = summarize(report['folds'])
    print('Final artifact: original train/validation boundaries; already-seen holdout diagnostic.', flush=True)
    _, original_splits, split_report = chronological_split(dataset)
    splits = {**original_splits, 'evaluation': original_splits['test']}
    del splits['test']
    experiment, pipelines = run_experiment(splits, args.min_recall, args.seed, args.n_jobs)
    selected = experiment['selected_model']
    selected_result = experiment['models'][selected]
    report['final'] = {'split': split_report, 'experiment': experiment,
                       'evaluation_role': 'already-inspected holdout retrospective diagnostic'}
    numeric, names = feature_names(selected.endswith('_history'))
    artifact = {
        'format_version': 1, 'pipeline': pipelines[selected],
        'threshold': selected_result['thresholds']['balanced'], 'selected_model': selected,
        'feature_set': selected_result['feature_set'], 'feature_names': names,
        'numeric_features': numeric, 'categorical_features': CATEGORICAL_FEATURES,
        'label_metadata': LABEL_METADATA,
        'metadata': {**report['policies'], 'min_validation_recall': args.min_recall,
                     'threshold_policy': selected_result['threshold_policies']['balanced'],
                     'selection_data': 'original maturity-purged validation only', 'final_refit': False,
                     'source_files': report['source_files'], 'versions': report['versions'],
                     'split': split_report, 'seed': args.seed},
    }
    model_path = args.model_path.resolve()
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path, compress=3)
    data_dir = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(data_dir / 'olist_delay_history_features.csv', index=False)
    image_path = image_dir / 'stage4_alert_tradeoff.png'
    save_figure(report['folds'], image_path, args.min_recall)
    report['outputs'] = {'model': str(model_path), 'image': str(image_path),
                         'features': str(data_dir / 'olist_delay_history_features.csv')}
    report_path = output / 'alert_optimization.json'
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(f'Selected: {selected}; threshold={artifact["threshold"]:.6f}', flush=True)
    print(f'Report: {report_path}', flush=True)
    for item in report['summary']:
        if item['model'] == 'validation_selected':
            print(f"Backtest FP={item['false_positives']}; recall={item['recall']:.4f}; precision={item['precision']:.4f}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
