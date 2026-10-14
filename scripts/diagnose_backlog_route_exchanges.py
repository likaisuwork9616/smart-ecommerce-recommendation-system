"""Replay fixed July/September models and account for daily route alert exchanges.

This is a historical validation diagnosis, with no fitting or model selection.
"""
from __future__ import annotations

import argparse
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

from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_backlog_training import feature_names, prepare_input
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_engineering_features import CATEGORICAL_FEATURES
from scripts.delay_outcome_clock import add_training_outcome_clock
from scripts.delay_regularization_training import PRIMARY_SELECTION
from scripts.diagnose_budget_misses import PROMISE_BINS
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest
from scripts.train_delay_model import positive_probability

MONTHS = ('2017-07', '2017-09')
CANDIDATES = ('xgboost_engineering_geo', 'xgboost_backlog_7d',
              'xgboost_backlog_14d', 'xgboost_backlog_7_14d')
CUTOFF = pd.Timestamp('2017-12-01')
ANALYSIS = 'backlog_daily_route_exchanges'


def _assert_metric_counts(frame, known, chosen, expected):
    labels = frame.loc[known, 'delayed'].to_numpy()
    pred = chosen[known]
    actual = [[int(((labels == 0) & ~pred).sum()), int(((labels == 0) & pred).sum())],
              [int(((labels == 1) & ~pred).sum()), int(((labels == 1) & pred).sum())]]
    if actual != expected['confusion_matrix'] or len(labels) != expected['rows']:
        raise ValueError('Historical metric counts differ from the frozen experiment')


def build_report(source_path, paired_path, data_dir):
    from scripts.delay_route_exchanges import analyze_route_exchanges

    source = json.loads(source_path.read_text(encoding='utf-8'))
    paired = json.loads(paired_path.read_text(encoding='utf-8'))
    if (source['status'] != 'ok' or source['daily_cap'] != .1
            or source['new_fit_count'] != 72 or paired['status'] != 'ok'
            or paired['daily_cap'] != .1 or paired['analysis'] != 'paired_backlog_errors'
            or paired['historical_outcome_cutoff'] != CUTOFF.isoformat()
            or paired['source_report']['sha256'] != sha256(source_path)):
        raise ValueError('Require the completed fixed backlog experiment and its paired diagnosis')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Seven raw sources changed')
    features_path = ROOT / source['feature_dataset']['path']
    scores_path = ROOT / source['score_export']['path']
    for key, info in (('source_features', source['feature_dataset']),
                      ('source_scores', source['score_export'])):
        if paired[key] != {k: info[k] for k in ('path', 'sha256')}:
            raise ValueError('Paired diagnosis uses different features or scores')
    for path, info in ((features_path, source['feature_dataset']), (scores_path, source['score_export'])):
        if sha256(path) != info['sha256']:
            raise ValueError('Frozen feature or score source changed')
    features = pd.read_csv(features_path, float_precision='round_trip',
                           dtype={c: object for c in (*CATEGORICAL_FEATURES,
                                  'state_route_promise_bin', 'state_route_promise_growth_bin')})
    for name in ('order_purchase_timestamp', 'prediction_time', 'label_available_time',
                 'training_outcome_known_time'):
        features[name] = pd.to_datetime(features[name])
    features = add_training_outcome_clock(features, pd.read_csv(data_dir / 'olist_orders_dataset.csv'))
    parts = []
    for chunk in pd.read_csv(scores_path, chunksize=200000, float_precision='round_trip'):
        selected = chunk.loc[chunk.fold.eq('2017-12') & chunk.role.eq('validation')
                             & chunk.model_version.isin(MONTHS) & chunk.candidate.isin(CANDIDATES)]
        if len(selected):
            parts.append(selected)
    scores = pd.concat(parts, ignore_index=True)
    if scores.duplicated(['model_version', 'candidate', 'order_id']).any():
        raise ValueError('Duplicate score identities')
    scores['prediction_time'] = pd.to_datetime(scores.prediction_time)
    monthly = {m['month']: m for m in source['monthly_training']}
    fold = next(f for f in source['folds'] if f['name'] == '2017-12')
    report = {
        'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': sha256(source_path)},
        'source_paired_diagnostics': {'path': relative(paired_path), 'sha256': sha256(paired_path)},
        'source_features': {'path': relative(features_path), 'sha256': sha256(features_path)},
        'source_scores': {'path': relative(scores_path), 'sha256': sha256(scores_path)},
        'daily_cap': .1, 'historical_outcome_cutoff': CUTOFF.isoformat(),
        'new_fit_count': 0, 'new_model_selection': False,
        'frozen_december_selection': fold['experiment']['selected_models'][PRIMARY_SELECTION],
        'comparison': {'old': CANDIDATES[0], 'new': CANDIDATES[-1]},
        'context_candidates': list(CANDIDATES), 'model_provenance': {}, 'months': {},
        'notes': [
            'July and September are historical validation months at the December 1 selection cutoff.',
            'Each score comes from that month-start model; actual delivery must be strictly before the cutoff to count an outcome.',
            'Rank complete closed daily batches before masking outcomes; use floor(0.10*N), score descending, order ID ascending.',
            'Same-route exchanges and cross-route marginal reallocation are accounting identities, not paired order transfers or causal feature attribution.',
            'Sum daily route changes to measure movement; the monthly net route balance can hide reversals across days.',
            'All route and promise groups are retained, including small-sample flags; dimensions overlap and must not be added together.',
            '7d and 14d scores provide descriptive context, not a new selector or an ensemble policy.',
            'No development evaluation or final holdout scores are recomputed; no model, feature, or threshold is changed.',
        ],
    }
    for month in MONTHS:
        frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
        known = (frame.label_available_time < CUTOFF).to_numpy()
        fingerprint = fold['order_id_fingerprints']['validation_full_by_month'][month]
        if frame.empty or order_fingerprint(frame) != fingerprint:
            raise ValueError('Complete historical monthly cohort changed')
        values_by_candidate = {}
        context = {}
        report['model_provenance'][month] = {}
        for candidate in CANDIDATES:
            model_info = monthly[month]['models'][candidate]
            info = model_info['version_artifact']
            model_path = ROOT / info['path']
            if sha256(model_path) != info['sha256']:
                raise ValueError('Monthly model hash changed')
            artifact = joblib.load(model_path)
            numeric, categorical = feature_names(candidate)
            if (artifact['candidate'] != candidate or artifact['feature_names'] != numeric + categorical
                    or artifact['split'] != model_info['training_split']
                    or artifact['source_files'] != source['source_files']):
                raise ValueError('Monthly model feature or training provenance changed')
            with threadpool_limits(limits=1):
                values = positive_probability(artifact['pipeline'], prepare_input(frame, candidate))
            chosen = apply_alert_policy(frame, values, 0., .1, raw_scores=values)
            part = scores.loc[scores.model_version.eq(month) & scores.candidate.eq(candidate)]
            if len(part) != len(frame) or set(part.order_id) != set(frame.order_id):
                raise ValueError('Score ledger must preserve every complete daily batch member')
            part = part.set_index('order_id').loc[frame.order_id]
            np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
            np.testing.assert_array_equal(part.known_at_selection.to_numpy(), known)
            np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
            np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], frame.delayed.to_numpy()[known])
            np.testing.assert_allclose(part.delay_score.to_numpy(), values, rtol=0, atol=1e-12)
            np.testing.assert_array_equal(part.predicted_delayed.to_numpy(), chosen)
            expected = fold['experiment']['models'][candidate]['validation_by_month'][month]['known_outcome_metrics']
            _assert_metric_counts(frame, known, chosen, expected)
            context[candidate] = {
                'known_outcome_metrics': expected,
                'unknown_alerts': int(chosen[~known].sum()), 'full_alerts': int(chosen.sum()),
            }
            report['model_provenance'][month][candidate] = info
            values_by_candidate[candidate] = values
        old_scores, new_scores = (values_by_candidate[c] for c in (CANDIDATES[0], CANDIDATES[-1]))
        result = analyze_route_exchanges(frame, old_scores, new_scores, known)
        # Promise grouping is independent of labels and does not alter the daily ranks.
        promise = pd.to_numeric(frame.estimated_delivery_days, errors='raise')
        if not np.isfinite(promise).all() or promise.lt(0).any():
            raise ValueError('Require finite nonnegative promise days')
        promise_frame = frame.assign(state_route=pd.cut(
            promise, [-np.inf, 7, 14, 21, 30, np.inf], labels=PROMISE_BINS, right=True).astype(object))
        promise_result = analyze_route_exchanges(promise_frame, old_scores, new_scores, known)
        result['promise_days'] = [dict(row, promise_bin=row['state_route']) for row in promise_result['routes']]
        for row in result['promise_days']:
            del row['state_route']
        cross_frame = frame.assign(state_route=frame.state_route.fillna('unknown').astype(str)
                                   + ' | ' + promise_frame.state_route.astype(str))
        cross_result = analyze_route_exchanges(cross_frame, old_scores, new_scores, known)
        result['route_by_promise'] = []
        for row in cross_result['routes']:
            route, promise_bin = row['state_route'].split(' | ', 1)
            result['route_by_promise'].append({**row, 'state_route': route, 'promise_bin': promise_bin})
        # Reconcile transitions against the independently published paired report.
        expected_pair = next(p for p in paired['months'][month]['families']['xgboost']['pairwise_comparisons']
                             if p['model_a'] == CANDIDATES[0] and p['model_b'] == CANDIDATES[-1])
        for key in ('recovered_delays', 'lost_delays', 'added_on_time_alerts',
                    'removed_on_time_alerts', 'net_TP', 'net_FP'):
            if result['summary'][key] != expected_pair['known_outcome']['overall'][key]:
                raise ValueError('Exchange counts differ from frozen paired diagnosis')
        report['months'][month] = {
            'role': 'historical_validation', 'order_id_fingerprint': fingerprint,
            'context': context, **result,
        }
        print(f'{month}: 4 frozen model versions and full daily route allocation verified', flush=True)
    report['verification'] = {'saved_versions_replayed': len(MONTHS) * len(CANDIDATES),
                              'score_rows_verified': len(scores), 'new_fit_count': 0,
                              'new_model_selection': False}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/backlog_changes.json')
    parser.add_argument('--paired-diagnostics', type=Path, default=ROOT / 'reports/stage4/backlog_diagnostics.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/backlog_route_exchanges.json')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output in (args.source_report.resolve(), args.paired_diagnostics.resolve()) or output.suffix.lower() != '.json':
        parser.error('Require a separate aggregate JSON output')
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding='utf-8'))
            own = previous.get('analysis') == ANALYSIS and previous.get('format_version') == 1
        except (OSError, ValueError, AttributeError):
            own = False
        if not own:
            parser.error('Refusing to overwrite another report')
    report = build_report(args.source_report, args.paired_diagnostics, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Wrote {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
