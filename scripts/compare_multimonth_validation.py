"""Compare recent, pooled and every-month validation with the same fitted models."""
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
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_delay_models import FOLDS
from scripts.compare_waiting_strategies import (
    CANDIDATES, feature_names, make_candidate, prepare_input, evaluation_segments,
)
from scripts.delay_alert_policy import choose_recall_threshold
from scripts.delay_multimonth_validation import split_multimonth_fold, choose_multimonth_threshold
from scripts.delay_route_features import build_route_delay_dataset
from scripts.delay_waiting_split import approval_cohort_audit
from scripts.delay_features import CSV_FILES
from scripts.train_delay_model import LABEL_METADATA, binary_metrics, positive_probability, source_manifest

STRATEGIES = ('recent_month', 'pooled_3months', 'every_month_floor')
PRIMARY_STRATEGY = 'every_month_floor'
DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def order_fingerprint(frame):
    return hashlib.sha256('\n'.join(sorted(frame.order_id.astype(str))).encode('utf-8')).hexdigest()


def monthly_metrics(frame, scores, threshold):
    months = frame.prediction_time.dt.strftime('%Y-%m')
    return {month: binary_metrics(frame.loc[months.eq(month), 'delayed'],
                                  np.asarray(scores)[months.eq(month).to_numpy()], threshold)
            for month in sorted(months.unique())}


def select_model(models, strategy):
    """Decision key uses the designated validation scope, never evaluation."""
    if strategy not in STRATEGIES:
        raise ValueError(f'Unknown strategy: {strategy}')
    return min(CANDIDATES, key=lambda name: (
        models[name]['strategies'][strategy]['selection_validation']['predicted_positive_rows'],
        models[name]['strategies'][strategy]['selection_validation']['confusion_matrix'][0][1],
        -models[name]['strategies'][strategy]['selection_validation']['average_precision'],
        CANDIDATES.index(name)))


def run_experiment(splits, min_recall=.30, seed=42, n_jobs=4):
    validation = splits['validation']
    months = validation.prediction_time.dt.strftime('%Y-%m')
    if months.nunique() != 3:
        raise ValueError('Require exactly three validation calendar months')
    recent = months.eq(months.max()).to_numpy()
    models, pipelines, score_sets = {}, {}, {}
    with threadpool_limits(limits=n_jobs):
        for candidate in CANDIDATES:
            print(f'  {candidate}: fitting', flush=True)
            pipeline = make_candidate(candidate, seed, n_jobs)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                pipeline.fit(prepare_input(splits['train'], candidate), splits['train'].delayed)
            if isinstance(pipeline.named_steps['classifier'], RandomForestClassifier):
                pipeline.set_params(classifier__n_jobs=1)
            scores = positive_probability(pipeline, prepare_input(validation, candidate))
            thresholds = {
                'recent_month': choose_recall_threshold(validation.delayed.to_numpy()[recent], scores[recent], min_recall),
                'pooled_3months': choose_recall_threshold(validation.delayed, scores, min_recall),
                'every_month_floor': choose_multimonth_threshold(validation.delayed, scores, months, min_recall),
            }
            numeric, categorical = feature_names(candidate)
            models[candidate] = {
                'feature_set': 'route_promise_90d' if candidate.endswith('_route') else 'approval_static',
                'numeric_features': numeric, 'categorical_features': categorical,
                'classifier_parameters': pipeline.named_steps['classifier'].get_params(deep=False),
                'training_jobs': n_jobs, 'prediction_jobs': 1 if candidate.startswith('random_forest') else n_jobs,
                'fit_warnings': sorted({f'{item.category.__name__}: {item.message}' for item in caught}),
                'strategies': {},
            }
            for strategy, (threshold, policy) in thresholds.items():
                by_month = monthly_metrics(validation, scores, threshold)
                pooled = binary_metrics(validation.delayed, scores, threshold)
                scope = binary_metrics(validation.delayed.to_numpy()[recent], scores[recent], threshold) if strategy == 'recent_month' else pooled
                models[candidate]['strategies'][strategy] = {
                    'threshold': threshold, 'threshold_policy': policy,
                    'selection_scope': 'latest validation calendar month' if strategy == 'recent_month' else 'all three validation months',
                    'selection_validation': scope, 'validation': pooled, 'validation_by_month': by_month,
                    'minimum_validation_month_recall': min(m['recall'] for m in by_month.values()),
                }
            pipelines[candidate] = pipeline
            score_sets[candidate] = {'validation': scores}
        selections = {strategy: select_model(models, strategy) for strategy in STRATEGIES}
        # All fits, thresholds and selections are frozen before reading evaluation outcomes.
        for candidate, pipeline in pipelines.items():
            scores = positive_probability(pipeline, prepare_input(splits['evaluation'], candidate))
            if not np.isfinite(scores).all():
                raise ValueError('Non-finite evaluation scores')
            score_sets[candidate]['evaluation'] = scores
            for result in models[candidate]['strategies'].values():
                result['evaluation'] = binary_metrics(splits['evaluation'].delayed, scores, result['threshold'])
                result['evaluation_segments'] = evaluation_segments(splits['evaluation'], scores, result['threshold'])
    return {'selected_models': selections, 'models': models}, pipelines, score_sets


def summarize(folds, min_recall=.30):
    rows = []
    for strategy in STRATEGIES:
        for candidate in (*CANDIDATES, 'validation_selected'):
            selected = [fold['experiment']['models'][fold['experiment']['selected_models'][strategy]
                        if candidate == 'validation_selected' else candidate]['strategies'][strategy] for fold in folds]
            tn, fp, fn, tp = (int(v) for v in np.sum([r['evaluation']['confusion_matrix'] for r in selected], axis=0).ravel())
            recalls = [r['evaluation']['recall'] for r in selected]
            rows.append({'strategy': strategy, 'model': candidate, 'rows': tn + fp + fn + tp,
                'false_positives': fp, 'true_positives': tp, 'false_negatives': fn, 'true_negatives': tn,
                'alert_rows': fp + tp, 'precision': tp / (fp + tp) if fp + tp else None,
                'recall': tp / (tp + fn), 'recall_by_month': recalls, 'minimum_evaluation_month_recall': min(recalls),
                'minimum_validation_month_recall': min(r['minimum_validation_month_recall'] for r in selected),
                'evaluation_months_below_target': sum(r < min_recall for r in recalls)})
    return rows


def save_figure(report, path):
    names = [f['name'] for f in report['folds']]
    x = np.arange(len(names))
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    for offset, strategy, label, color in zip((-.26, 0, .26), STRATEGIES,
            ('Recent month', 'Pooled 3 months', f"Every month >={report['min_validation_recall']:.0%}"),
            ('#b66a47', '#2878a5', '#44885b')):
        results = [f['experiment']['models'][f['experiment']['selected_models'][strategy]]['strategies'][strategy] for f in report['folds']]
        bars = axes[0].bar(x + offset, [r['evaluation']['confusion_matrix'][0][1] for r in results], width=.26, color=color)
        axes[0].bar_label(bars, fontsize=8)
        axes[1].plot(x, [r['evaluation']['recall'] for r in results], 'o-', color=color, label=label)
        axes[2].plot(x, [r['minimum_validation_month_recall'] for r in results], 'o-', color=color)
    axes[0].set(title='Development evaluation false alerts', ylabel='False-positive orders')
    axes[0].set_ylim(top=axes[0].get_ylim()[1] * 1.12)
    axes[1].set(title='Development evaluation recall', ylabel='Recall', ylim=(0, 1.05))
    axes[2].set(title='Worst validation month recall', ylabel='Recall', ylim=(0, 1.05))
    for ax in axes:
        ax.set_xticks(x, names)
        ax.grid(axis='y', alpha=.2)
    for ax in axes[1:]:
        ax.axhline(report['min_validation_recall'], linestyle='--', color='gray')
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=3, fontsize=9)
    fig.suptitle('Same fitted models; validation constraints change thresholds and candidate selection')
    fig.tight_layout(rect=(0, .09, 1, .98))
    fig.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--waiting-report', type=Path, default=DEFAULT_OUTPUT / 'waiting_strategy_comparison.json')
    parser.add_argument('--n-jobs', type=int, default=4)
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error('Require n-jobs >= 1')
    output = args.output_dir.resolve()
    default = output == DEFAULT_OUTPUT.resolve()
    image_dir = ROOT / 'reports/images' if default else output / 'images'
    data_dir = ROOT / 'data/processed' if default else output / 'data'
    model_dir = ROOT / 'models/research' if default else output / 'models'
    for directory in (output, image_dir, data_dir, model_dir):
        directory.mkdir(parents=True, exist_ok=True)
    previous = json.loads(args.waiting_report.read_text(encoding='utf-8'))
    manifest = source_manifest(args.data_dir)
    if manifest != previous['source_files']:
        raise ValueError('Waiting experiment uses different source data')
    dataset = build_route_delay_dataset(args.data_dir)
    orders = pd.read_csv(args.data_dir / CSV_FILES['orders'])
    report = {
        'format_version': 1, 'status': 'ok', 'seed': 42, 'min_validation_recall': .30,
        'wait_days': 60, 'validation_calendar_months': 3, 'primary_strategy_prespecified': PRIMARY_STRATEGY,
        'strategies': list(STRATEGIES), 'fit_count': len(FOLDS) * len(CANDIDATES), 'source_files': manifest,
        'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib')},
        'policies': {
            'evaluation_role': 'previously inspected development months; not a new independent test',
            'holdout': 'original 2018-05-26 onward period not scored',
            'schedule': 'validation end = calendar month start at/before evaluation_start - 60 days; preceding 3 complete months',
            'fit': 'one model before earliest validation month; training approvals end another 60 days earlier; labels strictly before fit time',
            'validation': 'only delivery labels strictly before evaluation_start; each calendar month must contain both classes',
            'threshold': 'every_month_floor: minimum of each month highest recall-feasible threshold, common score >= threshold',
            'selection': 'validation alerts then FP then AP then fixed candidate order; recent_month uses latest month, other strategies use all 3',
            'matched_comparison': 'all three strategies share training rows, fitted pipelines and scores within each fold/candidate',
            'recency_cost': '3-month validation requires older and fewer training orders; old single-month experiment is context only',
            'features': 'static or route_promise_90d; prior completed events strictly before each approval; no evaluation outcome input',
            'overlap': 'folds reuse historical calendar months; earlier evaluation can be later validation; not independent experiments',
            'recall_guarantee': 'validation monthly recall floor does not guarantee evaluation or future recall',
            'promotion': 'research artifacts only; original and balanced defaults unchanged',
        },
        'previous_single_month_context': {
            'source_report_sha256': hashlib.sha256(args.waiting_report.read_bytes()).hexdigest(),
            'summary': next(row for row in previous['summary'] if row['wait_days'] == 60 and row['model'] == 'validation_selected'),
            'note': 'same evaluation orders, different training/validation dates and row counts'},
        'folds': [],
    }
    score_rows = []
    for specification in FOLDS:
        print(f"Evaluation {specification['name']}: 3 calendar validation months", flush=True)
        splits, split_report = split_multimonth_fold(dataset, specification['evaluation_start'], specification['evaluation_end'])
        old_fold = next(f for f in previous['folds'] if f['wait_days'] == 60 and f['name'] == specification['name'])
        old_metric = old_fold['experiment']['models'][old_fold['experiment']['selected_model']]['evaluation']
        if len(splits['evaluation']) != old_metric['rows'] or int(splits['evaluation'].delayed.sum()) != sum(old_metric['confusion_matrix'][1]):
            raise ValueError('Evaluation cohort differs from previous waiting report')
        experiment, pipelines, score_sets = run_experiment(splits, n_jobs=args.n_jobs)
        selected = experiment['selected_models'][PRIMARY_STRATEGY]
        model_result = experiment['models'][selected]
        decision = model_result['strategies'][PRIMARY_STRATEGY]
        numeric, categorical = feature_names(selected)
        artifact = {'format_version': 1, 'selected_model': selected, 'feature_set': model_result['feature_set'],
            'pipeline': pipelines[selected], 'threshold': decision['threshold'],
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**report['policies'], 'split': split_report,
                'source_files': manifest, 'versions': report['versions'], 'seed': 42, 'research_only': True,
                'strategy': PRIMARY_STRATEGY, 'threshold_policy': decision['threshold_policy'],
                'route_parameters': {'window_days': 90, 'prior_strength': 20, 'quantile_method': 'linear',
                                     'duration': 'delivery calendar date - approval calendar date'}}}
        model_path = model_dir / f"olist_delay_multimonth_{specification['name']}.joblib"
        joblib.dump(artifact, model_path, compress=3)
        report['folds'].append({'name': specification['name'], 'split': split_report,
            'order_id_fingerprints': {name: order_fingerprint(part) for name, part in splits.items()},
            'approval_cohort_audit': approval_cohort_audit(orders, dataset, split_report), 'experiment': experiment,
            'research_artifact': {'path': model_path.relative_to(ROOT).as_posix() if model_path.is_relative_to(ROOT) else str(model_path),
                                  'sha256': hashlib.sha256(model_path.read_bytes()).hexdigest()}})
        for candidate in CANDIDATES:
            for partition in ('validation', 'evaluation'):
                part = splits[partition][['order_id', 'prediction_time', 'delayed']].copy()
                part['fold'], part['dataset_split'], part['candidate'] = specification['name'], partition, candidate
                part['delay_score'] = score_sets[candidate][partition]
                for strategy in STRATEGIES:
                    threshold = experiment['models'][candidate]['strategies'][strategy]['threshold']
                    part[f'threshold_{strategy}'] = threshold
                    part[f'predicted_{strategy}'] = (part.delay_score >= threshold).astype(int)
                score_rows.append(part)
    report['summary'] = summarize(report['folds'], report['min_validation_recall'])
    pd.concat(score_rows, ignore_index=True).to_csv(data_dir / 'olist_delay_multimonth_scores.csv', index=False)
    save_figure(report, image_dir / 'stage4_multimonth_validation.png')
    path = output / 'multimonth_validation.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    for row in report['summary']:
        if row['model'] == 'validation_selected':
            print(f"{row['strategy']}: FP={row['false_positives']}; TP={row['true_positives']}; FN={row['false_negatives']}; worst recall={row['minimum_evaluation_month_recall']:.4f}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
