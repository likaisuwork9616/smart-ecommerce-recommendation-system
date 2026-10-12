"""Diagnose monthly false alerts without fitting or changing a saved model."""
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.delay_features import add_delay_target, build_order_features, load_olist_tables
from scripts.delay_history_features import build_primary_sellers
from scripts.predict_delay import build_inference_features, predict_features
from scripts.train_delay_model import chronological_split, source_manifest

DEFAULT_OUTPUT = ROOT / 'reports/stage4'
GROUPS = ('customer_state', 'primary_seller_state', 'state_route', 'route_type',
          'promise_band', 'freight_band', 'seller_training_volume', 'primary_category')


def ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def wilson_interval(successes, trials):
    """Descriptive 95% binomial interval; correlated orders are not independent."""
    if not trials:
        return None
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = z * np.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [float(max(0, center - half)), float(min(1, center + half))]


def error_metrics(frame):
    y, predicted = frame['delayed'], frame['predicted_delayed']
    if not y.isin([0, 1]).all() or not predicted.isin([0, 1]).all():
        raise ValueError('Labels and predictions must be binary')
    fp = int(((y == 0) & (predicted == 1)).sum())
    tp = int(((y == 1) & (predicted == 1)).sum())
    fn = int(((y == 1) & (predicted == 0)).sum())
    tn = int(((y == 0) & (predicted == 0)).sum())
    scores = frame['delay_score'].to_numpy(dtype=float)
    if not np.isfinite(scores).all():
        raise ValueError('Scores must be finite')
    result = {
        'rows': len(frame), 'on_time_rows': tn + fp, 'delayed_rows': tp + fn,
        'true_negatives': tn, 'false_positives': fp, 'false_negatives': fn, 'true_positives': tp,
        'alert_rows': tp + fp, 'positive_rate': ratio(tp + fn, len(frame)),
        'alert_rate': ratio(tp + fp, len(frame)), 'precision': ratio(tp, tp + fp),
        'recall': ratio(tp, tp + fn), 'false_positive_rate': ratio(fp, tn + fp),
        'false_discovery_rate': ratio(fp, tp + fp),
        'false_positives_per_1000_orders': ratio(1000 * fp, len(frame)),
        'fpr_wilson_95': wilson_interval(fp, tn + fp),
        'average_precision': float(average_precision_score(y, scores)) if (tp + fn) else None,
        'roc_auc': float(roc_auc_score(y, scores)) if (tn + fp) and (tp + fn) else None,
    }
    for label, subset in (('on_time', scores[y.to_numpy() == 0]),
                          ('delayed', scores[y.to_numpy() == 1])):
        result[f'{label}_score_median'] = float(np.median(subset)) if len(subset) else None
    result['ap_lift_over_prevalence'] = (ratio(result['average_precision'], result['positive_rate'])
                                         if result['average_precision'] is not None else None)
    return result


def score_frame(frame, artifact):
    predictions = predict_features(artifact, frame)
    if len(predictions) != len(frame) or not predictions.index.equals(frame.index):
        raise ValueError('Prediction rows must preserve input index')
    result = frame.copy()
    result[['delay_score', 'predicted_delayed']] = predictions[['delay_score', 'predicted_delayed']]
    return result


def band(values, edges, labels):
    return pd.cut(values, edges, labels=labels, include_lowest=True).astype(object).fillna('missing')


def add_diagnostic_groups(frame, training_seller_counts):
    result = frame.copy()
    result['promise_band'] = band(result['estimated_delivery_days'],
                                 [0, 7, 14, 21, 30, np.inf], ['0-7', '8-14', '15-21', '22-30', '31+'])
    result['freight_band'] = band(result['freight_ratio'],
                                [0, .10, .25, .50, np.inf], ['0-.10', '.10-.25', '.25-.50', '.50+'])
    counts = result['primary_seller_id'].map(training_seller_counts).fillna(0)
    result['seller_training_volume'] = band(counts, [0, 19, 99, np.inf], ['1-19', '20-99', '100+'])
    result.loc[counts == 0, 'seller_training_volume'] = 'unseen'
    result.loc[result['primary_seller_id'].isna(), 'seller_training_volume'] = 'missing'
    interstate = result['interstate_item_ratio']
    result['route_type'] = np.select(
        [interstate == 0, interstate == 1, interstate.between(0, 1, inclusive='neither')],
        ['same_state', 'all_interstate', 'mixed'], default='missing')
    result['state_route'] = (result['primary_seller_state'].fillna('missing').astype(str) + ' -> ' +
                             result['customer_state'].fillna('missing').astype(str))
    return result


def grouped_metrics(frame, columns, min_on_time=100, min_alerts=50):
    rows = []
    total_fp = int(((frame.delayed == 0) & (frame.predicted_delayed == 1)).sum())
    for keys, group in frame.groupby(columns, observed=True, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {column: str(key) if pd.notna(key) else 'missing' for column, key in zip(columns, keys)}
        row.update(error_metrics(group))
        row['share_of_period_orders'] = ratio(len(group), len(frame))
        row['share_of_all_false_positives'] = ratio(row['false_positives'], total_fp)
        row['sufficient_on_time_rows'] = row['on_time_rows'] >= min_on_time
        row['sufficient_alert_rows'] = row['alert_rows'] >= min_alerts
        rows.append(row)
    return rows


def standardized_monthly_fpr(frame, min_on_time=20):
    """Fix state/promise mix on common support; this is descriptive, not causal."""
    months = sorted(frame['month'].unique())
    on_time = frame.loc[frame.delayed == 0].copy()
    on_time['state'] = on_time.customer_state.fillna('missing')
    strata = ['state', 'promise_band']
    counts = on_time.groupby(strata + ['month'], observed=True).size().unstack('month', fill_value=0)
    counts = counts.reindex(columns=months, fill_value=0)
    common = counts.loc[(counts >= min_on_time).all(axis=1)]
    pooled = common.sum(axis=1)
    weights = pooled / pooled.sum() if len(pooled) else pooled
    result = {
        'method': 'pooled on-time state x promise-band weights, common strata only; no causal attribution',
        'min_on_time_per_month_stratum': min_on_time, 'common_strata': len(common), 'months': [],
        'weights': [{'customer_state': state, 'promise_band': promise, 'weight': float(weight)}
                    for (state, promise), weight in weights.items()],
    }
    for month in months:
        subset = on_time.loc[on_time.month == month]
        rates = subset.groupby(strata, observed=True).predicted_delayed.agg(['sum', 'count'])
        matched = rates.reindex(common.index)
        covered = int(matched['count'].sum())
        result['months'].append({
            'month': month, 'on_time_rows_covered': covered, 'coverage': ratio(covered, len(subset)),
            'observed_fpr_on_common_strata': ratio(matched['sum'].sum(), covered),
            'standardized_fpr': float((weights * matched['sum'] / matched['count']).sum()) if len(common) else None,
        })
    return result


def maturity_audit(partitioned, split_report):
    rows = []
    for (split, month), group in partitioned.groupby(['dataset_split', 'month'], sort=True):
        kept, purged = group.loc[~group.label_purged], group.loc[group.label_purged]
        rows.append({
            'split': split, 'month': month, 'before_rows': len(group),
            'before_delayed_rows': int(group.delayed.sum()), 'before_delay_rate': float(group.delayed.mean()),
            'retained_rows': len(kept), 'retained_delayed_rows': int(kept.delayed.sum()),
            'retained_delay_rate': float(kept.delayed.mean()) if len(kept) else None,
            'purged_rows': len(purged), 'purged_delayed_rows': int(purged.delayed.sum()),
            'purged_delay_rate': float(purged.delayed.mean()) if len(purged) else None,
            'delayed_retention_rate': ratio(kept.delayed.sum(), group.delayed.sum()),
        })
    return {'boundaries': {key: split_report[key] for key in ('validation_start', 'test_start')}, 'months': rows}


def cohort_audit(orders, dataset):
    approved = orders.copy()
    approved['prediction_time'] = pd.to_datetime(approved.order_approved_at, errors='coerce')
    approved = approved.loc[approved.prediction_time.notna()].copy()
    approved['month'] = approved.prediction_time.dt.strftime('%Y-%m')
    approved['in_labeled_cohort'] = approved.order_id.isin(dataset.order_id)
    rows = []
    for month, group in approved.groupby('month', sort=True):
        rows.append({'month': month, 'approved_rows': len(group),
                     'eligible_completed_rows': int(group.in_labeled_cohort.sum()),
                     'eligible_completed_share': float(group.in_labeled_cohort.mean()),
                     'status_counts': {str(key): int(value) for key, value in group.order_status.value_counts().items()}})
    return {
        'interpretation': 'cohort inclusion, not true label coverage: cancellations and invalid timelines also excluded',
        'snapshot_time': None,
        'snapshot_limit': 'no extraction timestamp: right censoring cannot be measured from max observed delivery',
        'latest_approval': approved.prediction_time.max().isoformat(),
        'latest_observed_delivery': pd.to_datetime(orders.order_delivered_customer_date, errors='coerce').max().isoformat(),
        'months': rows,
    }


def save_figures(monthly, groups, image_dir):
    image_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(len(monthly))
    labels = [row['month'] + ('*' if row['partial_month'] else '') for row in monthly]
    axes[0].plot(x, [100 * row['positive_rate'] for row in monthly], 'o-', label='Actual delayed rate')
    axes[0].plot(x, [100 * row['alert_rate'] for row in monthly], 'o-', label='Alert rate')
    axes[0].plot(x, [100 * row['false_positive_rate'] for row in monthly], 'o-', label='FP / on-time orders')
    axes[0].set(ylabel='Percent of relevant orders', title='Fixed saved model: rates by approval month')
    axes[0].legend(fontsize=8)
    bars = axes[1].bar(x, [row['false_positives'] for row in monthly], color='#b66a47', label='False alerts')
    axes[1].bar_label(bars, fontsize=9)
    axes[1].set(ylabel='False-positive orders', title='False alerts and recall')
    twin = axes[1].twinx()
    twin.plot(x, [100 * row['recall'] for row in monthly], 'o-', color='#2878a5', label='Recall')
    twin.set(ylabel='Recall (%)', ylim=(0, 100))
    twin.legend(loc='upper left', fontsize=8)
    for ax in axes:
        ax.set_xticks(x, labels)
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('Retrospective diagnostics only; * partial month; model and threshold unchanged')
    fig.tight_layout()
    fig.savefig(image_dir / 'stage4_monthly_errors.png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    dimensions = ('customer_state', 'promise_band', 'freight_band')
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    for ax, dimension in zip(axes, dimensions):
        eligible = [row for row in groups[dimension] if row['sufficient_on_time_rows']]
        top = sorted(eligible, key=lambda row: row['false_positive_rate'], reverse=True)[:7]
        top.reverse()
        y = np.arange(len(top))
        values = np.array([100 * row['false_positive_rate'] for row in top])
        errors = np.array([[100 * row['fpr_wilson_95'][0], 100 * row['fpr_wilson_95'][1]] for row in top])
        ax.barh(y, values, color='#2878a5', xerr=np.array([values - errors[:, 0], errors[:, 1] - values]))
        ax.set_yticks(y, [f"{row[dimension]}\nFP {row['false_positives']:,} / n {row['on_time_rows']:,}" for row in top], fontsize=8)
        ax.set(title=dimension.replace('_', ' '), xlabel='FP / on-time orders (%)')
    fig.suptitle('Observed high-FPR groups (on-time n >= 100); descriptive Wilson intervals')
    fig.tight_layout()
    fig.savefig(image_dir / 'stage4_false_positive_groups.png', dpi=160, bbox_inches='tight')
    plt.close(fig)


def development_threshold_audit(report):
    result = []
    for fold in report['folds']:
        model = fold['experiment']['models']['random_forest_static']
        val = fold['split']['partitions']['validation']
        result.append({'evaluation_month': fold['name'], 'validation_start': fold['split']['validation_start'],
                       'validation_end': fold['split']['validation_end'],
                       'validation_positive_rate_before_purge': val['positive_rate_before_purge'],
                       'validation_positive_rate_after_purge': val['positive_rate'],
                       'validation_positive_retention': val['positive_retention_rate'],
                       'balanced_threshold': model['thresholds']['balanced'],
                       'evaluation': model['evaluation']['balanced']})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--model', type=Path, default=ROOT / 'models/olist_delay_balanced.joblib')
    parser.add_argument('--experiment-report', type=Path, default=DEFAULT_OUTPUT / 'alert_optimization.json')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    image_dir = ROOT / 'reports/images' if output == DEFAULT_OUTPUT.resolve() else output / 'images'
    artifact = joblib.load(args.model)
    tables = load_olist_tables(args.data_dir)
    static = build_order_features(tables)
    dataset = add_delay_target(static, tables['orders'])
    primary = build_primary_sellers(tables['order_items'])
    dataset = dataset.merge(primary, on='order_id', how='left', validate='one_to_one')
    if artifact.get('feature_set', 'approval_static') != 'approval_static':
        inference = build_inference_features(artifact, tables).set_index('order_id')
        for name in artifact['feature_names']:
            if name not in dataset:
                dataset[name] = dataset.order_id.map(inference[name])
    partitioned, splits, split_report = chronological_split(dataset)
    manifest = source_manifest(args.data_dir)
    metadata = artifact.get('metadata', {})
    if metadata.get('source_files', metadata.get('raw_source_files')) != manifest:
        raise ValueError('Source files differ from the saved model; rebuild or use its original data')
    if any(metadata.get('split', {}).get(key) != split_report[key]
           for key in ('validation_start', 'test_start')):
        raise ValueError('Reconstructed split boundaries differ from the saved model')
    partitioned['month'] = partitioned.prediction_time.dt.strftime('%Y-%m')
    training_counts = splits['train'].primary_seller_id.value_counts()
    scored = {}
    for split in ('validation', 'test'):
        scored[split] = add_diagnostic_groups(score_frame(splits[split], artifact), training_counts)
        scored[split]['month'] = scored[split].prediction_time.dt.strftime('%Y-%m')
    test = scored['test']
    monthly = grouped_metrics(test, ['month'])
    for row in monthly:
        part = test.loc[test.month == row['month']]
        start, end = part.prediction_time.min().normalize(), part.prediction_time.max().normalize()
        row.update({'prediction_date_min': start.date().isoformat(), 'prediction_date_max': end.date().isoformat(),
                    'partial_month': start.day != 1 or end.day != end.days_in_month})
        delivery_days = (part.label_available_time - part.prediction_time).dt.total_seconds() / 86400
        row['feature_and_outcome_summary'] = {
            'promise_days_mean': float(part.estimated_delivery_days.mean()),
            'promise_days_median': float(part.estimated_delivery_days.median()),
            'actual_delivery_days_mean': float(delivery_days.mean()),
            'actual_delivery_days_p90': float(delivery_days.quantile(.9)),
            'promise_at_most_7_days_share': float((part.estimated_delivery_days <= 7).mean()),
            'customer_sp_share': float(part.customer_state.eq('SP').mean()),
            'all_interstate_share': float(part.route_type.eq('all_interstate').mean()),
            'freight_ratio_median': float(part.freight_ratio.median()),
            'note': 'actual delivery is retrospective only; promise uses calendar days, actual uses fractional days',
        }
    groups = {dimension: grouped_metrics(test, [dimension]) for dimension in GROUPS}
    monthly_groups = {dimension: grouped_metrics(test, ['month', dimension]) for dimension in GROUPS}
    fp = test.loc[(test.delayed == 0) & (test.predicted_delayed == 1)].copy()
    # Actual delivery is consulted after scoring, solely to describe the errors.
    fp['days_early'] = (fp.estimated_delivery_days -
                        (fp.label_available_time.dt.normalize() - fp.prediction_time.dt.normalize()).dt.days)
    full_months = [row['month'] for row in monthly if not row['partial_month']]
    experiment_report = json.loads(args.experiment_report.read_text(encoding='utf-8'))
    if experiment_report.get('source_files') != manifest:
        raise ValueError('Development report source files differ from this diagnosis')
    report = {
        'format_version': 1, 'purpose': 'post-hoc error analysis, no fitting, selection or threshold change',
        'evaluation_role': 'already-inspected holdout retrospective diagnostic; not an independent new test',
        'model': {'selected_model': artifact['selected_model'], 'feature_set': artifact.get('feature_set', 'approval_static'),
                  'threshold': float(artifact['threshold']),
                  'sha256': hashlib.sha256(args.model.read_bytes()).hexdigest()},
        'source_files': manifest,
        'versions': {package: version(package) for package in ('pandas', 'numpy', 'scikit-learn', 'joblib')},
        'metric_definitions': {'false_positive_rate': 'FP / (FP + TN): fraction of on-time orders wrongly alerted',
                               'false_discovery_rate': 'FP / (FP + TP): fraction of alerts that were false',
                               'recall': 'TP / (TP + FN): fraction of delayed orders caught',
                               'zero_denominator': 'null, not zero',
                               'group_shares': 'share_of_period_orders and share_of_all_false_positives use all test orders/FP, including monthly groups',
                               'intervals': 'Wilson 95% descriptive binomial intervals; seller/day correlation ignored'},
        'limitations': ['approved completed valid-timeline cohort only; excludes unresolved, cancelled and invalid orders',
                        'month is approval month; partial edge months are flagged',
                        'validation is maturity-purged and used to select this model/threshold',
                        'associations do not establish causes; groups overlap, so their FP counts cannot be added',
                        'many exploratory comparisons; small groups not reliable and no significance claim',
                        'delay_score is uncalibrated; score averages are not expected delivery probabilities',
                        'diagnostics must not be used to claim improvement on this already-inspected period'],
        'split': split_report,
        'overall': {split: error_metrics(frame) for split, frame in scored.items()},
        'validation_months': grouped_metrics(scored['validation'], ['month']),
        'test_months': monthly, 'groups': groups, 'monthly_groups': monthly_groups,
        'ranking_rules': {'min_on_time_rows': 100, 'min_alert_rows': 50,
                          'high_fpr': 'filter sufficient_on_time_rows; sort FPR, check monthly consistency and denominators',
                          'volume': 'sort FP count separately; no automated suppression or state-specific thresholds'},
        'standardized_full_months': standardized_monthly_fpr(test.loc[test.month.isin(full_months)]),
        'label_maturity_audit': maturity_audit(partitioned, split_report),
        'cohort_audit': cohort_audit(tables['orders'], dataset),
        'false_positive_outcomes': {
            'rows': len(fp), 'days_early_median': float(fp.days_early.median()) if len(fp) else None,
            'delivered_at_least_7_days_early': int((fp.days_early >= 7).sum()),
            'delivered_at_least_7_days_early_share': ratio((fp.days_early >= 7).sum(), len(fp)),
            'note': 'observed outcome description only; days_early never used for prediction or rules'},
        'development_rf_thresholds': development_threshold_audit(experiment_report),
    }
    save_figures(monthly, groups, image_dir)
    report_path = output / 'monthly_error_diagnostics.json'
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    local_output = ROOT / 'data/processed' if output == DEFAULT_OUTPUT.resolve() else output / 'data'
    local_output.mkdir(parents=True, exist_ok=True)
    test.drop(columns=['primary_seller_id']).to_csv(local_output / 'olist_delay_error_diagnostics.csv', index=False)
    print(f'Report: {report_path}')
    print(f"Frozen threshold {artifact['threshold']:.9f}; retrospective FP={report['overall']['test']['false_positives']}")
    for row in monthly:
        print(f"{row['month']}: n={row['rows']}, FP={row['false_positives']}, FPR={row['false_positive_rate']:.2%}, recall={row['recall']:.2%}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
