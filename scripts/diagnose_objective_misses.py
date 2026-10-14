"""Diagnose matched daily ranking objectives from a verified frozen score ledger.

No model is fit, reselected or deserialized here. Full daily membership and
saved-model hashes are checked before aggregate route and missed-delay reports
are produced. Development months are retrospective retests, not new tests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_backlog_objectives import CLASSIFIERS, MATCHED, RANKERS, read_features
from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_route_exchanges import analyze_route_exchanges
from scripts.diagnose_budget_misses import (
    MIN_GROUP_POSITIVES, MIN_GROUP_ROWS, PROMISE_BINS, RANK_BINS, daily_rank_bins,
)
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest

ANALYSIS = 'matched_objective_missed_delay_diagnostics'


def promise_bins(frame):
    values = pd.to_numeric(frame.estimated_delivery_days, errors='raise')
    if not np.isfinite(values).all() or values.lt(0).any():
        raise ValueError('Require finite nonnegative promise days')
    return pd.cut(values, [-np.inf, 7, 14, 21, 30, np.inf],
                  labels=PROMISE_BINS, right=True).astype(object)


def original_regression_cohort(frame, scores_by_candidate, known_mask):
    """Follow known delays dropped by the two original classifiers.

    Unknown labels never enter the cohort, even if their scores displace known
    orders. Every rank and alert is calculated on the full complete batch.
    """
    known = np.asarray(known_mask)
    if known.dtype != bool or known.ndim != 1 or len(known) != len(frame):
        raise ValueError('Require an aligned boolean known-outcome mask')
    if set(scores_by_candidate) != set(MATCHED):
        raise ValueError('Require all four prespecified objective scores')
    known_labels = frame.loc[known, 'delayed'].to_numpy()
    if not np.isin(known_labels, [0, 1]).all():
        raise ValueError('Known labels must be binary')
    positive = np.zeros(len(frame), bool)
    positive[known] = known_labels == 1
    alerts = {c: apply_alert_policy(frame, scores_by_candidate[c], 0., .1,
                                   raw_scores=scores_by_candidate[c]) for c in MATCHED}
    ranks = {c: daily_rank_bins(frame, scores_by_candidate[c]) for c in MATCHED}
    cohort = positive & alerts[CLASSIFIERS[0]] & ~alerts[CLASSIFIERS[1]]
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    promises = promise_bins(frame).to_numpy()

    def counts(mask):
        selected = mask & cohort
        n = int(selected.sum())
        support, delayed = int((mask & known).sum()), int((mask & positive).sum())
        models = {}
        for candidate in MATCHED:
            bins = {name: int((selected & (ranks[candidate] == name)).sum()) for name in RANK_BINS}
            caught = int((selected & alerts[candidate]).sum())
            if sum(bins.values()) != n or bins['<=10%'] != caught:
                raise AssertionError('Regression cohort full-batch ranks do not reconcile')
            models[candidate] = {
                'in_top10': caught, 'out_of_top10': n - caught,
                'in_top20': bins['<=10%'] + bins['10-20%'],
                'fraction_in_top10': caught / n if n else None,
                'rank_bins': bins,
            }
        return {'cohort_rows': n, 'known_rows': support, 'known_delayed_rows': delayed,
                'minimum_sample_met': support >= MIN_GROUP_ROWS and delayed >= MIN_GROUP_POSITIVES,
                'cohort_small_sample': n < MIN_GROUP_POSITIVES, 'models': models}

    overall = counts(np.ones(len(frame), bool))
    grouped = {
        'routes': [{'state_route': route, **counts(routes == route)} for route in sorted(set(routes))],
        'promise_days': [{'promise_bin': name, **counts(promises == name)} for name in PROMISE_BINS],
        'route_by_promise': [{'state_route': route, 'promise_bin': name,
                              **counts((routes == route) & (promises == name))}
                             for route, name in sorted(set(zip(routes, promises, strict=True)))],
    }
    for rows in grouped.values():
        for field in ('cohort_rows', 'known_rows', 'known_delayed_rows'):
            if sum(row[field] for row in rows) != overall[field]:
                raise AssertionError('Regression cohort groups do not partition their support')
        for candidate in MATCHED:
            if sum(row['models'][candidate]['in_top10'] for row in rows) != overall['models'][candidate]['in_top10']:
                raise AssertionError('Regression cohort recovered counts do not partition')
    return {
        'definition': 'Known delayed orders alerted by geo83 classifier and not alerted by backlog101 classifier; descriptive cohort, never a selection rule.',
        'candidates': list(MATCHED), 'rank_bins': list(RANK_BINS),
        'minimum_group_known_rows': MIN_GROUP_ROWS, 'minimum_group_delayed_rows': MIN_GROUP_POSITIVES,
        'group_support': 'minimum_sample_met uses all known group rows and delayed rows; cohort_small_sample separately marks fewer than five cohort orders.',
        **overall, **grouped,
    }


def objective_exchanges(frame, scores, known, keep_route_days=False):
    promise = promise_bins(frame)
    routes = frame.state_route.fillna('unknown').astype(str)
    result = {}
    for package, classifier, ranker in zip(('geo83', 'backlog101'), CLASSIFIERS, RANKERS, strict=True):
        old, new = scores[classifier], scores[ranker]
        value = analyze_route_exchanges(frame, old, new, known)
        if not keep_route_days:
            value.pop('route_day_allocations')
        grouped = analyze_route_exchanges(frame.assign(state_route=promise), old, new, known)
        value['promise_days'] = [dict(row, promise_bin=row['state_route']) for row in grouped['routes']]
        for row in value['promise_days']:
            del row['state_route']
        crossed = analyze_route_exchanges(frame.assign(state_route=routes + ' | ' + promise.astype(str)), old, new, known)
        value['route_by_promise'] = []
        for row in crossed['routes']:
            route, promise_bin = row['state_route'].split(' | ', 1)
            value['route_by_promise'].append({**row, 'state_route': route, 'promise_bin': promise_bin})
        value['comparison'] = {'classification': classifier, 'daily_ranking': ranker}
        result[package] = value
    return result


def verify_phase_ledger(frame, ledger, cutoff, role, expected_models, month):
    """Verify every full-batch score and its frozen metric/budget record."""
    if role not in ('validation', 'evaluation'):
        raise ValueError('Unknown scoring role')
    known = ((frame.label_available_time < pd.Timestamp(cutoff)).to_numpy()
             if role == 'validation' else np.ones(len(frame), bool))
    ledger_known = known if role == 'validation' else np.zeros(len(frame), bool)
    values, context = {}, {}
    if len(ledger) != len(frame) * len(MATCHED) or set(ledger.candidate) != set(MATCHED):
        raise ValueError('Score ledger must contain exactly the four full candidate cohorts')
    for candidate in MATCHED:
        part = ledger.loc[ledger.candidate.eq(candidate)]
        if (part.order_id.duplicated().any() or len(part) != len(frame)
                or set(part.order_id) != set(frame.order_id)):
            raise ValueError('Score ledger changed complete daily identities')
        part = part.set_index('order_id').loc[frame.order_id]
        np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
        if part.known_at_selection.dtype != bool:
            raise ValueError('Score ledger availability flags must be boolean')
        np.testing.assert_array_equal(part.known_at_selection.to_numpy(), ledger_known)
        np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
        np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], frame.loc[known, 'delayed'].to_numpy())
        score = part.delay_score.to_numpy(dtype=float)
        if not np.isfinite(score).all() or ((score < 0) | (score > 1)).any():
            raise ValueError('Score ledger contains invalid bounded scores')
        prediction = apply_alert_policy(frame, score, 0., .1, raw_scores=score)
        if not part.predicted_delayed.isin([0, 1]).all():
            raise ValueError('Score ledger predictions must be binary')
        np.testing.assert_array_equal(part.predicted_delayed.to_numpy(), prediction)
        metrics = alert_metrics(frame.loc[known, 'delayed'].to_numpy(), score[known], prediction[known])
        batch = batch_audit(frame, prediction, .1, known)
        record = expected_models[candidate]
        expected = (record['validation_by_month'][month] if role == 'validation' else
                    {'known_outcome_metrics': record['development_evaluation'], 'full_batch': record['evaluation_batch']})
        if metrics != expected['known_outcome_metrics'] or batch != expected['full_batch']:
            raise ValueError(f'Frozen source phase metrics or full batch changed: {month}/{candidate}')
        values[candidate] = score
        context[candidate] = {'known_outcome_metrics': metrics, 'full_batch': batch}
    return known, values, context


def build_report(source_path, data_dir):
    source_path = Path(source_path)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if (source['status'] != 'ok' or source['experiment'] != 'matched_backlog_objectives'
            or source['daily_cap'] != .1 or source['matched_candidate_order'] != list(MATCHED)
            or source['new_candidate_order'] != list(RANKERS)):
        raise ValueError('Require the completed matched-objective experiment')
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    specification_path = source_path.with_name('backlog_objectives_specification.json')
    prior_path = ROOT / source['source_report']['path']
    files = {
        source_path: sha256(source_path), feature_path: source['feature_dataset']['sha256'],
        score_path: source['score_export']['sha256'], specification_path: source['specification_sha256'],
        prior_path: source['source_report']['sha256'],
    }
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError(f'Frozen diagnostic source changed: {relative(path)}')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Frozen raw data sources changed')
    provenance = {}
    for entry in source['monthly_training']:
        month = entry['month']
        if month in provenance or set(entry['models']) != set(MATCHED):
            raise ValueError('Require unique matched four-model monthly versions')
        provenance[month] = {}
        for candidate in MATCHED:
            info = entry['models'][candidate]['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Frozen monthly model hash changed')
            files[path] = info['sha256']
            provenance[month][candidate] = info
    features = read_features(feature_path, Path(data_dir))
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    if len(ledger) != source['score_export']['rows'] or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any():
        raise ValueError('Score ledger row count or uniqueness changed')
    ledger['prediction_time'] = pd.to_datetime(ledger.prediction_time, errors='raise')
    report = {
        'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': files[source_path]},
        'source_features': {'path': relative(feature_path), 'sha256': files[feature_path]},
        'source_scores': {'path': relative(score_path), 'sha256': files[score_path]},
        'daily_cap': .1, 'new_fit_count': 0, 'new_model_selection': False,
        'comparison': 'Matched XGBoost classification versus daily ranking within each unchanged feature contract.',
        'model_provenance': provenance, 'phases': {},
        'notes': [
            'Ledger-based aggregate diagnosis; saved model hashes checked, no joblib model deserialization or replay in this CLI.',
            'Full complete daily membership ranks first; historical actual-delivery labels require strict availability before each fold cutoff.',
            'Evaluation ledger known_at_selection flags must all be false; its observed outcomes are used only in marked development retests.',
            'Daily route allocation counts are accounting marginals, not individual order transfers or feature-causality claims.',
            'All route and route/promise groups remain present with sample-support flags; overlapping dimensions must not be added together.',
            'Original regression cohorts are descriptive views of known delayed orders lost between the two original classifiers, never a new selector.',
            'No final retained test scores, model objective, alert threshold or deployment artifact are changed.',
        ],
    }
    expected_phases = set()
    verified_rows = 0
    for fold in source['folds']:
        name, schedule = fold['name'], fold['schedule']
        phases = [(item['month'], 'validation') for item in schedule['validation_months']] + [(name, 'evaluation')]
        for month, role in phases:
            expected_phases.add((name, role, month))
            frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            fingerprint = (fold['order_id_fingerprints']['validation_full_by_month'][month]
                           if role == 'validation' else fold['order_id_fingerprints']['evaluation'])
            if frame.empty or order_fingerprint(frame) != fingerprint or month not in provenance:
                raise ValueError('Complete monthly feature/scoring identities changed')
            part = ledger.loc[ledger.fold.eq(name) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            known, scores, context = verify_phase_ledger(frame, part, schedule['evaluation_start'], role,
                                                        fold['experiment']['models'], month)
            keep_days = name == '2017-12' and month in ('2017-07', '2017-09') and role == 'validation'
            key = f'{name}/{month}/{role}'
            if key in report['phases']:
                raise ValueError('Duplicate scoring phase')
            report['phases'][key] = {
                'fold': name, 'month': month, 'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'ledger_role': role, 'historical_outcome_cutoff': schedule['evaluation_start'],
                'order_id_fingerprint': fingerprint, 'context': context,
                'full_batch': {'rows': len(frame), 'known_outcome_rows': int(known.sum()),
                               'unknown_outcome_rows': int((~known).sum()), 'capacity': context[MATCHED[0]]['full_batch']['capacity']},
                'objectives': objective_exchanges(frame, scores, known, keep_route_days=keep_days),
                'original_regression_cohort': original_regression_cohort(frame, scores, known),
            }
            verified_rows += len(part)
            print(f'{key}: full batch, frozen metrics, two objective contrasts and regression cohort verified', flush=True)
    actual_phases = set(zip(ledger.fold, ledger.role, ledger.model_version, strict=True))
    if actual_phases != expected_phases or verified_rows != len(ledger):
        raise ValueError('Score ledger contains missing or unexpected scoring phases')
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError('A frozen diagnostic source changed during analysis')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Raw data changed during analysis')
    report['verification'] = {
        'source_and_model_hashes_checked': len(files),
        'monthly_model_hashes_checked': sum(len(value) for value in provenance.values()),
        'score_rows_verified': verified_rows, 'scoring_phases_verified': len(expected_phases),
        'objective_contrasts': 2 * len(expected_phases),
        'source_metrics_and_full_batch_exactly_reconciled': True,
        'full_batch_ranks_before_outcome_masks': True, 'source_hashes_rechecked_after_analysis': True,
        'saved_versions_replayed_in_this_cli': 0, 'new_fit_count': 0, 'new_model_selection': False,
    }
    return report


def validate_output(output, source):
    output, source = Path(output).resolve(), Path(source).resolve()
    if output == source or output.suffix.lower() != '.json':
        raise ValueError('Require a separate aggregate JSON output')
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding='utf-8'))
            own = previous.get('analysis') == ANALYSIS and previous.get('format_version') == 1
        except (OSError, ValueError, AttributeError):
            own = False
        if not own:
            raise ValueError('Refusing to overwrite another report')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/backlog_objectives.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/backlog_objective_diagnostics.json')
    args = parser.parse_args(argv)
    try:
        output = validate_output(args.output, args.source_report)
    except ValueError as exc:
        parser.error(str(exc))
    report = build_report(args.source_report, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Wrote {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
