"""Replay monthly retraining and transfer historical out-of-time score thresholds."""
from __future__ import annotations

import argparse
import gc
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
from scripts.compare_waiting_strategies import CANDIDATES, feature_names, make_candidate, prepare_input, evaluation_segments
from scripts.compare_multimonth_validation import STRATEGIES, PRIMARY_STRATEGY, select_model, monthly_metrics, summarize, order_fingerprint
from scripts.delay_alert_policy import choose_recall_threshold
from scripts.delay_multimonth_validation import choose_multimonth_threshold
from scripts.delay_rolling_validation import split_rolling_month, rolling_validation_schedule, mature_validation_month
from scripts.delay_route_features import build_route_delay_dataset
from scripts.delay_features import CSV_FILES
from scripts.train_delay_model import LABEL_METADATA, binary_metrics, positive_probability, source_manifest

DEFAULT_OUTPUT = ROOT / 'reports/stage4'


def fit_month(splits, candidate, seed=42, n_jobs=4):
    """One monthly fit; scoring labels never enter training or preprocessing."""
    with threadpool_limits(limits=n_jobs):
        pipeline = make_candidate(candidate, seed, n_jobs)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            pipeline.fit(prepare_input(splits['train'], candidate), splits['train'].delayed)
        if isinstance(pipeline.named_steps['classifier'], RandomForestClassifier):
            pipeline.set_params(classifier__n_jobs=1)
        scores = positive_probability(pipeline, prepare_input(splits['scoring'], candidate))
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError('Invalid monthly scores')
    numeric, categorical = feature_names(candidate)
    return {
        'feature_set': 'route_promise_90d' if candidate.endswith('_route') else 'approval_static',
        'numeric_features': numeric, 'categorical_features': categorical,
        'classifier_parameters': pipeline.named_steps['classifier'].get_params(deep=False),
        'training_jobs': n_jobs, 'prediction_jobs': 1 if candidate.startswith('random_forest') else n_jobs,
        'fit_warnings': sorted({f'{item.category.__name__}: {item.message}' for item in caught}),
    }, pipeline, scores


def score_distribution(frame, scores):
    """Post-decision descriptive score drift; these are not calibrated probabilities."""
    values = np.asarray(scores)
    return {'rows': len(frame), 'positive_rows': int(frame.delayed.sum()),
        'positive_rate': float(frame.delayed.mean()),
        'score_quantiles_0_10_50_90_100': [float(x) for x in np.quantile(values, [0, .1, .5, .9, 1])],
        'on_time_score_median': float(np.median(values[frame.delayed.to_numpy() == 0])),
        'delayed_score_median': float(np.median(values[frame.delayed.to_numpy() == 1]))}


def decide_fold(validation, validation_scores, evaluation, evaluation_scores, min_recall=.30):
    """Use historical OOT versions to freeze policies before evaluation labels."""
    months = validation.prediction_time.dt.strftime('%Y-%m')
    if months.nunique() != 3:
        raise ValueError('Require three validation calendar months')
    recent = months.eq(months.max()).to_numpy()
    models = {}
    for candidate in CANDIDATES:
        values = np.asarray(validation_scores[candidate])
        thresholds = {
            'recent_month': choose_recall_threshold(validation.delayed.to_numpy()[recent], values[recent], min_recall),
            'pooled_3months': choose_recall_threshold(validation.delayed, values, min_recall),
            'every_month_floor': choose_multimonth_threshold(validation.delayed, values, months, min_recall),
        }
        models[candidate] = {'strategies': {}}
        for strategy, (threshold, policy) in thresholds.items():
            by_month = monthly_metrics(validation, values, threshold)
            pooled = binary_metrics(validation.delayed, values, threshold)
            scope = binary_metrics(validation.delayed.to_numpy()[recent], values[recent], threshold) if strategy == 'recent_month' else pooled
            models[candidate]['strategies'][strategy] = {
                'threshold': threshold, 'threshold_policy': policy,
                'selection_scope': 'latest OOT validation month' if strategy == 'recent_month' else 'all three OOT validation months',
                'selection_validation': scope, 'validation': pooled, 'validation_by_month': by_month,
                'minimum_validation_month_recall': min(m['recall'] for m in by_month.values()),
            }
    selections = {strategy: select_model(models, strategy) for strategy in STRATEGIES}
    # Frozen above. The following diagnostics and outcomes cannot change any decision.
    for candidate in CANDIDATES:
        values = np.asarray(evaluation_scores[candidate])
        if values.ndim != 1 or len(values) != len(evaluation) or not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError('Invalid evaluation score vector')
        past = np.asarray(validation_scores[candidate])
        distributions = {month: score_distribution(validation.loc[months.eq(month)], past[months.eq(month).to_numpy()])
                         for month in sorted(months.unique())}
        individual = {month: choose_recall_threshold(validation.loc[months.eq(month), 'delayed'],
                      past[months.eq(month).to_numpy()], min_recall)[0] for month in distributions}
        models[candidate]['score_transfer_diagnostics'] = {
            'role': 'descriptive after selection; raw scores are uncalibrated and version distributions may differ',
            'individual_validation_month_thresholds': individual,
            'monthly_threshold_range': max(individual.values()) - min(individual.values()),
            'validation_score_distributions': distributions,
            'evaluation_score_distribution': score_distribution(evaluation, values),
        }
        for result in models[candidate]['strategies'].values():
            result['evaluation'] = binary_metrics(evaluation.delayed, values, result['threshold'])
            result['evaluation_segments'] = evaluation_segments(evaluation, values, result['threshold'])
    return {'selected_models': selections, 'models': models}


def raw_train_audit(orders, dataset, split_report):
    approvals = pd.to_datetime(orders.order_approved_at)
    train_end, cutoff = map(pd.Timestamp, (split_report['train_prediction_end'], split_report['model_fit_time']))
    raw = orders.loc[approvals < train_end]
    eligible = dataset.loc[dataset.prediction_time < train_end]
    return {'scope': 'raw approval cohort, final snapshot statuses; excluded orders get no inferred label',
        'raw_approved_rows': len(raw), 'eligible_completed_rows': len(eligible),
        'known_eligible_labels_at_cutoff': int((eligible.label_available_time < cutoff).sum()),
        'not_in_eligible_cohort_rows': int((~raw.order_id.isin(eligible.order_id)).sum()),
        'status_counts': {str(k): int(v) for k, v in raw.order_status.fillna('<missing>').value_counts().sort_index().items()}}


def save_figure(report, path):
    names = [f['name'] for f in report['folds']]
    x = np.arange(len(names))
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    axes[0].plot(x, report['frozen_context']['train_rows'], 'o-', label='Frozen model', color='#777777')
    axes[0].plot(x, [f['final_training_rows'] for f in report['folds']], 'o-', label='Monthly retraining', color='#44885b')
    axes[0].set(title='Training orders available for evaluation', ylabel='Training orders')
    axes[0].legend(fontsize=8)
    styles = [(-.30, None, 'Frozen / every-month floor', '#777777'),
              (-.10, 'recent_month', 'Rolling / recent month', '#b66a47'),
              (.10, 'pooled_3months', 'Rolling / pooled months', '#2878a5'),
              (.30, 'every_month_floor', 'Rolling / every-month floor', '#44885b')]
    for offset, strategy, label, color in styles:
        results = report['frozen_context']['evaluation_by_fold'] if strategy is None else [
            f['experiment']['models'][f['experiment']['selected_models'][strategy]]['strategies'][strategy]['evaluation'] for f in report['folds']]
        bars = axes[1].bar(x + offset, [r['confusion_matrix'][0][1] for r in results], width=.20, color=color)
        axes[1].bar_label(bars, fontsize=7)
        axes[2].plot(x, [r['recall'] for r in results], 'o-', color=color, label=label)
    axes[1].set(title='Development evaluation false alerts', ylabel='False-positive orders')
    axes[1].set_ylim(top=axes[1].get_ylim()[1] * 1.12)
    axes[2].set(title='Development evaluation recall', ylabel='Recall', ylim=(0, 1.05))
    axes[2].axhline(report['min_validation_recall'], linestyle='--', color='gray')
    for ax in axes:
        ax.set_xticks(x, names)
        ax.grid(axis='y', alpha=.2)
    handles, labels = axes[2].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, fontsize=9)
    fig.suptitle('Rolling validation uses historical model versions; raw score thresholds may not transfer')
    fig.tight_layout(rect=(0, .12, 1, .98))
    fig.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--frozen-report', type=Path, default=DEFAULT_OUTPUT / 'multimonth_validation.json')
    parser.add_argument('--n-jobs', type=int, default=4)
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error('Require n-jobs >= 1')
    output = args.output_dir.resolve()
    default = output == DEFAULT_OUTPUT.resolve()
    image_dir = ROOT / 'reports/images' if default else output / 'images'
    data_dir = ROOT / 'data/processed' if default else output / 'data'
    model_dir = ROOT / 'models/research' if default else output / 'models'
    version_dir = model_dir / 'rolling_versions'
    for directory in (output, image_dir, data_dir, version_dir):
        directory.mkdir(parents=True, exist_ok=True)
    frozen = json.loads(args.frozen_report.read_text(encoding='utf-8'))
    manifest = source_manifest(args.data_dir)
    if manifest != frozen['source_files']:
        raise ValueError('Frozen report uses different source data')
    dataset = build_route_delay_dataset(args.data_dir)
    orders = pd.read_csv(args.data_dir / CSV_FILES['orders'])
    schedules = [rolling_validation_schedule(f['evaluation_start'], f['evaluation_end']) for f in FOLDS]
    model_months = sorted({s['evaluation_start'] for s in schedules} |
                          {m['start'] for s in schedules for m in s['validation_months']})
    report = {'format_version': 1, 'status': 'ok', 'seed': 42, 'min_validation_recall': .30,
        'wait_days': 60, 'validation_calendar_months': 3, 'strategies': list(STRATEGIES),
        'primary_strategy_prespecified': PRIMARY_STRATEGY, 'fit_count': len(model_months) * len(CANDIDATES),
        'source_files': manifest, 'versions': {name: version(name) for name in ('pandas', 'numpy', 'scikit-learn', 'joblib')},
        'policies': {
            'fit': 'each month M uses approvals strictly before M-60 days, delivery labels strictly before M; expanding train',
            'validation_scores': 'each month scored by its own model fitted at that month start; never rescore with final E model',
            'validation_labels': 'three complete calendar cohorts ending floor_month(E-60 days); labels strictly before E',
            'threshold': 'common raw score threshold across historical versions; recent, pooled, or every-month recall >=30%',
            'selection': 'validation alerts then FP then AP then fixed candidate order; recent uses latest month, others all three',
            'overlap': 'final model may train on historical validation rows, but policy uses their earlier genuinely OOT scores',
            'score_transfer': 'scores are uncalibrated; historical monthly recall is not a guarantee for newly retrained model',
            'cache': 'one fit per month/candidate; retain full-month scores and reapply label maturity for each E',
            'comparison': 'frozen context changes both final training recency and validation model versions; not a pure causal retraining effect',
            'evaluation_role': 'previously inspected development months; not a new independent test',
            'holdout': 'original 2018-05-26 onward period is not scored',
            'promotion': 'research only; original, balanced and previous research artifacts unchanged',
        },
        'frozen_context': {'source_report_sha256': hashlib.sha256(args.frozen_report.read_bytes()).hexdigest(),
            'summary': [r for r in frozen['summary'] if r['model'] == 'validation_selected'],
            'train_rows': [f['split']['partitions']['train']['rows'] for f in frozen['folds']],
            'evaluation_by_fold': [f['experiment']['models'][f['experiment']['selected_models'][PRIMARY_STRATEGY]]['strategies'][PRIMARY_STRATEGY]['evaluation'] for f in frozen['folds']]},
        'monthly_training': [], 'folds': []}
    cache = {}
    for month_start in model_months:
        month = month_start[:7]
        print(f'Model version {month}: monthly training', flush=True)
        splits, split_report = split_rolling_month(dataset, month_start)
        entry = {'month': month, 'split': split_report,
            'order_id_fingerprints': {k: order_fingerprint(v) for k, v in splits.items()},
            'raw_train_audit': raw_train_audit(orders, dataset, split_report), 'models': {}}
        cache[month] = {'frame': splits['scoring'], 'scores': {}, 'version_paths': {}, 'train': splits['train']}
        for candidate in CANDIDATES:
            print(f'  {candidate}: fitting', flush=True)
            result, pipeline, scores = fit_month(splits, candidate, n_jobs=args.n_jobs)
            version_path = version_dir / f'olist_delay_{month}_{candidate}.joblib'
            joblib.dump({'pipeline': pipeline, 'candidate': candidate, 'split': split_report}, version_path, compress=3)
            result['version_artifact'] = {'path': version_path.relative_to(ROOT).as_posix() if version_path.is_relative_to(ROOT) else str(version_path),
                                          'sha256': hashlib.sha256(version_path.read_bytes()).hexdigest()}
            entry['models'][candidate] = result
            cache[month]['scores'][candidate] = pd.Series(scores, index=splits['scoring'].order_id)
            cache[month]['version_paths'][candidate] = version_path
            del pipeline
            gc.collect()
        report['monthly_training'].append(entry)
    score_rows = []
    for specification, schedule, old in zip(FOLDS, schedules, frozen['folds'], strict=True):
        evaluation_month = specification['name']
        parts, maturity = [], []
        for month in schedule['validation_months']:
            part, audit = mature_validation_month(cache[month['month']]['frame'], schedule['evaluation_start'])
            parts.append(part)
            maturity.append({'month': month['month'], 'model_version': month['month'], **audit})
        validation = pd.concat(parts, ignore_index=True)
        evaluation = cache[evaluation_month]['frame']
        # Same evaluation order IDs as the frozen multi-month experiment.
        if order_fingerprint(evaluation) != old['order_id_fingerprints']['evaluation']:
            raise ValueError('Evaluation order IDs differ from frozen report')
        validation_scores = {candidate: np.concatenate([part.order_id.map(cache[m['month']]['scores'][candidate]).to_numpy()
            for part, m in zip(parts, schedule['validation_months'], strict=True)]) for candidate in CANDIDATES}
        evaluation_scores = {candidate: evaluation.order_id.map(cache[evaluation_month]['scores'][candidate]).to_numpy() for candidate in CANDIDATES}
        experiment = decide_fold(validation, validation_scores, evaluation, evaluation_scores)
        selected = experiment['selected_models'][PRIMARY_STRATEGY]
        decision = experiment['models'][selected]['strategies'][PRIMARY_STRATEGY]
        numeric, categorical = feature_names(selected)
        version_artifact = joblib.load(cache[evaluation_month]['version_paths'][selected])
        train = cache[evaluation_month]['train']
        overlap = int(validation.order_id.isin(train.order_id).sum())
        artifact = {'format_version': 1, 'selected_model': selected,
            'feature_set': 'route_promise_90d' if selected.endswith('_route') else 'approval_static',
            'pipeline': version_artifact['pipeline'], 'threshold': decision['threshold'],
            'feature_names': numeric + categorical, 'numeric_features': numeric, 'categorical_features': categorical,
            'label_metadata': LABEL_METADATA, 'metadata': {**report['policies'], 'research_only': True,
                'schedule': schedule, 'final_split': version_artifact['split'], 'seed': 42, 'versions': report['versions'],
                'source_files': manifest, 'threshold_policy': decision['threshold_policy'], 'strategy': PRIMARY_STRATEGY,
                'validation_score_model_months': [m['month'] for m in schedule['validation_months']],
                'route_parameters': {'window_days': 90, 'prior_strength': 20, 'quantile_method': 'linear',
                    'duration': 'delivery calendar date - approval calendar date'}}}
        model_path = model_dir / f'olist_delay_rolling_{evaluation_month}.joblib'
        joblib.dump(artifact, model_path, compress=3)
        report['folds'].append({'name': evaluation_month, 'schedule': schedule, 'validation_maturity': maturity,
            'order_id_fingerprints': {'validation': order_fingerprint(validation), 'evaluation': order_fingerprint(evaluation)},
            'final_training_rows': len(train), 'historical_validation_rows_in_final_train': overlap,
            'experiment': experiment, 'research_artifact': {'path': model_path.relative_to(ROOT).as_posix() if model_path.is_relative_to(ROOT) else str(model_path),
                                                           'sha256': hashlib.sha256(model_path.read_bytes()).hexdigest()}})
        for candidate in CANDIDATES:
            for partition, frame, values in (('validation', validation, validation_scores[candidate]), ('evaluation', evaluation, evaluation_scores[candidate])):
                part = frame[['order_id', 'prediction_time', 'delayed']].copy()
                part['fold'], part['dataset_split'], part['candidate'] = evaluation_month, partition, candidate
                part['model_version'] = part.prediction_time.dt.strftime('%Y-%m')
                part['delay_score'] = values
                for strategy in STRATEGIES:
                    threshold = experiment['models'][candidate]['strategies'][strategy]['threshold']
                    part[f'threshold_{strategy}'] = threshold
                    part[f'predicted_{strategy}'] = (part.delay_score >= threshold).astype(int)
                score_rows.append(part)
    report['summary'] = summarize(report['folds'], report['min_validation_recall'])
    pd.concat(score_rows, ignore_index=True).to_csv(data_dir / 'olist_delay_rolling_scores.csv', index=False)
    save_figure(report, image_dir / 'stage4_monthly_retraining.png')
    path = output / 'monthly_retraining.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Report: {path}', flush=True)
    for row in report['summary']:
        if row['model'] == 'validation_selected':
            print(f"{row['strategy']}: FP={row['false_positives']}; TP={row['true_positives']}; FN={row['false_negatives']}; worst recall={row['minimum_evaluation_month_recall']:.4f}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
