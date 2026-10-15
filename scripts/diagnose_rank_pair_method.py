"""Describe the frozen backlog101 topk-to-mean experiment from its score ledger.

No models are loaded, fit, replayed, selected or promoted. Complete daily
batches rank before outcome masks; volume, route and promise views are
descriptive marginal accounts rather than explanations of causal effects.
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

from scripts.compare_backlog_objectives import read_features
from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_route_exchanges import COUNT_FIELDS
from scripts.diagnose_budget_misses import PROMISE_BINS, daily_rank_bins
from scripts.diagnose_objective_misses import promise_bins
from scripts.diagnose_rank_batch_size import (
    COUNT_KEYS, VOLUME_BINS, _assert_partition, _day_info, _exchange_summary,
    _known_labels, _positions, _rank_summary, counts, volume_bin,
)
from scripts.diagnose_rank_focus import exchange_report
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest

ANALYSIS = 'rank_pair_method_matched_route_volume_diagnostics'
BASELINE = 'xgboost_rank_backlog_7_14d_l2_100_topk_10'
NEW = 'xgboost_rank_backlog_7_14d_l2_100_mean_10'
MATCHED = (BASELINE, NEW)
FOCUS_PHASES = (
    '2017-12/2017-07/validation', '2017-12/2017-09/validation',
    '2017-12/2017-12/evaluation',
)
MONTHS = ('2017-07', '2017-08', '2017-09', '2017-10', '2017-11',
          '2017-12', '2018-02', '2018-04')


def diagnose_phase(frame, scores, known, *, keep_cross=False):
    """One matched comparison; only full-day volume supports receive caps."""
    if not isinstance(frame, pd.DataFrame) or frame.empty or set(scores) != set(MATCHED):
        raise ValueError('Require a nonempty full phase with the two prespecified candidates')
    known, labels = _known_labels(frame, known)
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED}
    positions = {c: _positions(frame, scores[c]) for c in MATCHED}
    ranks = {c: daily_rank_bins(frame, scores[c]) for c in MATCHED}
    days, sizes = _day_info(frame)
    row_bins = np.asarray([volume_bin(sizes[day]) for day in days])
    context = {c: counts(frame, known, alerts[c]) for c in MATCHED}
    capacity = np.asarray([sizes[day] // 10 for day in days])
    for candidate in MATCHED:
        if (not np.array_equal(alerts[candidate], positions[candidate] <= capacity)
                or context[candidate]['alerts'] != context[candidate]['capacity']):
            raise AssertionError('Full-day ranks must reproduce the exact floor daily budget')
    old, new = alerts[BASELINE], alerts[NEW]
    result = exchange_report(frame, scores[BASELINE], scores[NEW], known,
                             keep_route_days=keep_cross, keep_cross=keep_cross)
    result['comparison'] = {
        'old_candidate': BASELINE, 'new_candidate': NEW,
        'comparison_kind': 'fixed_backlog101_l2_100_num10_pair_method_only',
        'old_pair_method': 'topk', 'new_pair_method': 'mean',
        'fixed_num_pair_per_sample': 10, 'fixed_l2': 100., 'fixed_daily_cap': .1,
        'interpretation': 'Only pair method changes. The retained integer 10 means top-position focus for topk and sampled pairs per document for mean; it is not a daily 10% cutoff or equal effective pair count.',
    }
    for row in result['days']:
        row['volume_bin'] = volume_bin(sizes[row['day']])
        row['models'] = {c: counts(frame, known, alerts[c], days == row['day']) for c in MATCHED}
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    promises = promise_bins(frame).to_numpy()
    positive = known & (labels == 1)
    changed = {'recovered_delays': positive & ~old & new,
               'lost_delays': positive & old & ~new}
    result['volume_bins'] = []
    for name in VOLUME_BINS:
        support = row_bins == name
        row = _exchange_summary(frame, known, old, new, np.flatnonzero(support))
        route_rows = [{'state_route': route, **_exchange_summary(
            frame, known, old, new, np.flatnonzero(support & (routes == route)))}
            for route in sorted(set(routes[support]))]
        promise_rows = [{'promise_bin': promise, **_exchange_summary(
            frame, known, old, new, np.flatnonzero(support & (promises == promise)))}
            for promise in PROMISE_BINS]
        for partition in (route_rows, promise_rows):
            _assert_partition(partition, row, COUNT_FIELDS)
        movements = {label: _rank_summary(support & cohort, positions[BASELINE], positions[NEW],
                                        ranks[BASELINE], ranks[NEW])
                     for label, cohort in changed.items()}
        if any(movements[label]['rows'] != row[label] for label in movements):
            raise AssertionError('Changed-delay rank cohorts do not reconcile exchanges')
        result['volume_bins'].append({
            'volume_bin': name, 'days': sum(volume_bin(n) == name for n in sizes.values()),
            'capacity': sum(n // 10 for n in sizes.values() if volume_bin(n) == name),
            **row, 'models': {c: counts(frame, known, alerts[c], support) for c in MATCHED},
            'routes': route_rows, 'promise_days': promise_rows, 'changed_delay_ranks': movements,
        })
    for partition in (result['days'], result['volume_bins']):
        _assert_partition(partition, result['summary'], COUNT_FIELDS)
        for candidate in MATCHED:
            _assert_partition([row['models'][candidate] for row in partition], context[candidate], COUNT_KEYS)
    return {'volume_context': context, 'pair_method': result,
            'verification': {'full_day_ranks_before_outcome_masks': True,
                'daily_and_volume_counts_partition': True,
                'route_and_promise_partition_each_volume_bin': True,
                'changed_delay_rank_counts_reconcile': True,
                'reminder_budget_conserved': True}}


def validate_source_contract(source, previous, specification):
    """Bind the method experiment to all 75 unchanged previous metric records."""
    if (source.get('status') != 'ok' or source.get('experiment') != 'rank_pair_method'
            or source.get('daily_cap') != .1 or source.get('matched_candidate_order') != list(MATCHED)
            or source.get('new_candidate_order') != [NEW]
            or source.get('reg_lambda') != 100. or source.get('pair_methods') != ['topk', 'mean']
            or source.get('num_pair_per_sample') != 10
            or source.get('only_changed_parameter') != 'lambdarank_pair_method'):
        raise ValueError('Require the completed fixed-backlog101 L2=100 num10 method experiment')
    previous_order = previous.get('candidate_order', [])
    if (previous.get('status') != 'ok' or previous.get('experiment') != 'rank_pair_focus'
            or len(previous_order) != 75 or len(set(previous_order)) != 75
            or BASELINE not in previous.get('matched_candidate_order', [])
            or source.get('candidate_order') != [*previous_order, NEW]
            or source.get('source_candidate_versions') != previous.get('source_candidate_versions')
            or source.get('feature_dataset') != previous.get('feature_dataset')
            or source.get('source_files') != previous.get('source_files')):
        raise ValueError('Require the unchanged 75-candidate source and feature provenance')
    if (specification.get('experiment') != 'rank_pair_method'
            or any(source.get(key) != value for key, value in specification.items())):
        raise ValueError('Completed report changed its predeclared specification')
    prior_folds = {fold['name']: fold for fold in previous['folds']}
    if (len(prior_folds) != 3 or len(source['folds']) != 3
            or {f['name'] for f in source['folds']} != set(prior_folds)):
        raise ValueError('Require the three unchanged development schedules')
    for fold in source['folds']:
        prior = prior_folds[fold['name']]
        for key in ('schedule', 'validation_maturity', 'order_id_fingerprints'):
            if fold[key] != prior[key]:
                raise ValueError('Frozen historical schedule, maturity or scoring identities changed')
        original, current = prior['experiment']['models'], fold['experiment']['models']
        if (set(original) != set(previous_order) or set(current) != set(source['candidate_order'])
                or any(current[c] != value for c, value in original.items())):
            raise ValueError('Frozen previous candidate metric records changed')
    prior_training = {row['month']: row for row in previous['monthly_training']}
    if (set(prior_training) != set(MONTHS) or len(source['monthly_training']) != 8
            or {row['month'] for row in source['monthly_training']} != set(MONTHS)):
        raise ValueError('Require the eight unchanged monthly fit schedules')
    for row in source['monthly_training']:
        prior = prior_training[row['month']]
        if row['split'] != prior['split'] or set(row['models']) != set(MATCHED):
            raise ValueError('Monthly scoring cohort or matched versions changed')
        for key in ('version_artifact', 'training_split'):
            if row['models'][BASELINE][key] != prior['models'][BASELINE][key]:
                raise ValueError('Frozen topk monthly provenance changed')


def verify_phase_ledger(frame, ledger, cutoff, role, expected_models, month):
    """Verify scores, masks, decisions, metric records and complete day budgets."""
    if role not in ('validation', 'evaluation'):
        raise ValueError('Unknown scoring role')
    for column, value in (('role', role), ('model_version', month)):
        if column in ledger and not ledger[column].eq(value).all():
            raise ValueError('Ledger contains another scoring phase')
    known = ((frame.label_available_time < pd.Timestamp(cutoff)).to_numpy()
             if role == 'validation' else np.ones(len(frame), bool))
    ledger_known = known if role == 'validation' else np.zeros(len(frame), bool)
    labels = frame.loc[known, 'delayed'].to_numpy()
    if not np.isin(labels, [0, 1]).all():
        raise ValueError('Known outcomes must be binary')
    labels = labels.astype(int)
    if len(ledger) != len(frame) * 2 or set(ledger.candidate) != set(MATCHED):
        raise ValueError('Require exactly two complete full-batch candidate cohorts')
    scores, context = {}, {}
    for candidate in MATCHED:
        part = ledger.loc[ledger.candidate.eq(candidate)]
        if (part.order_id.duplicated().any() or len(part) != len(frame)
                or set(part.order_id) != set(frame.order_id)):
            raise ValueError('Ledger changed complete scoring identities')
        part = part.set_index('order_id').loc[frame.order_id]
        np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
        if part.known_at_selection.dtype != bool:
            raise ValueError('Ledger selection availability flags must be boolean')
        np.testing.assert_array_equal(part.known_at_selection.to_numpy(), ledger_known)
        np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
        np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], labels)
        score = part.delay_score.to_numpy(dtype=float)
        if not np.isfinite(score).all() or ((score < 0) | (score > 1)).any():
            raise ValueError('Ledger contains invalid bounded scores')
        alert = apply_alert_policy(frame, score, 0., .1, raw_scores=score)
        if not part.predicted_delayed.isin([0, 1]).all():
            raise ValueError('Ledger predictions must be binary')
        np.testing.assert_array_equal(part.predicted_delayed.to_numpy(), alert)
        metrics = alert_metrics(labels, score[known], alert[known])
        batch = batch_audit(frame, alert, .1, known)
        record = expected_models[candidate]
        expected = (record['validation_by_month'][month] if role == 'validation' else
                    {'known_outcome_metrics': record['development_evaluation'], 'full_batch': record['evaluation_batch']})
        if metrics != expected['known_outcome_metrics'] or batch != expected['full_batch']:
            raise ValueError(f'Frozen phase metrics or daily budget changed: {month}/{candidate}')
        scores[candidate] = score
        context[candidate] = {'known_outcome_metrics': metrics, 'full_batch': batch}
    return known, scores, context


def compatibility_checks_from_phases(phases, targets):
    """Recompute frozen descriptive goals, keeping historical/development apart."""
    if (targets.get('used_for_selection') is not False
            or targets.get('reference_candidate') != BASELINE
            or targets.get('historical_outcome_cutoff') != '2017-12-01T00:00:00'):
        raise ValueError('Require the original descriptive topk reference and historical cutoff')
    if not set(FOCUS_PHASES) <= set(phases):
        raise ValueError('Require the July/September historical and December development phases')
    keys = ('july_historical_TP', 'september_historical_TP', 'december_development_TP')
    checks = []
    for method, candidate in zip(('topk', 'mean'), MATCHED, strict=True):
        values = {name: phases[phase]['context'][candidate]['known_outcome_metrics']['confusion_matrix'][1][1]
                  for name, phase in zip(keys, FOCUS_PHASES, strict=True)}
        if candidate == BASELINE and any(values[key] != targets[key] for key in keys):
            raise ValueError('Frozen descriptive topk baseline performance changed')
        differences = {label: values[key] - targets[key]
                       for label, key in zip(('july_difference', 'september_difference', 'december_difference'), keys, strict=True)}
        checks.append({'candidate': candidate, 'pair_method': method, **values, **differences,
            'both_historical_months_not_worse': differences['july_difference'] >= 0 and differences['september_difference'] >= 0,
            'all_three_descriptive_periods_not_worse': all(value >= 0 for value in differences.values()),
            'used_for_selection': False})
    return checks


def build_report(source_path, data_dir):
    source_path, data_dir = Path(source_path), Path(data_dir)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    prior_path, archive_path = (ROOT / source[key]['path'] for key in ('source_report', 'source_candidate_versions'))
    spec_path = source_path.with_name('rank_pair_method_specification.json')
    files = {source_path: sha256(source_path), feature_path: source['feature_dataset']['sha256'],
             score_path: source['score_export']['sha256'], prior_path: source['source_report']['sha256'],
             archive_path: source['source_candidate_versions']['sha256'], spec_path: source['specification_sha256']}
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError(f'Frozen diagnostic source changed: {relative(path)}')
    previous = json.loads(prior_path.read_text(encoding='utf-8'))
    specification = json.loads(spec_path.read_text(encoding='utf-8'))
    validate_source_contract(source, previous, specification)
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Frozen raw sources changed')
    provenance = {}
    for row in source['monthly_training']:
        provenance[row['month']] = {}
        for candidate in MATCHED:
            info = row['models'][candidate]['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Frozen saved-model hash changed')
            files[path] = info['sha256']
            provenance[row['month']][candidate] = info
    features = read_features(feature_path, data_dir)
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    ledger['prediction_time'] = pd.to_datetime(ledger.prediction_time, errors='raise')
    if (len(ledger) != source['score_export']['rows']
            or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Frozen score-ledger size or uniqueness changed')
    report = {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': files[source_path]},
        'previous_pair_focus_report': source['source_report'],
        'earlier_candidate_manifest': source['source_candidate_versions'],
        'source_features': source['feature_dataset'], 'source_scores': source['score_export'],
        'specification_sha256': source['specification_sha256'],
        'matched_candidate_order': list(MATCHED), 'model_provenance': provenance,
        'compatibility_targets': source['compatibility_targets'],
        'daily_cap': .1, 'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0,
        'new_model_selection': False, 'phases': {},
        'volume_bin_definition': {'order': list(VOLUME_BINS),
            'basis': 'Complete eligible daily N, including orders with unknown outcomes.',
            'capacity_ranges': {'1-99': '0-9', '100-199': '10-19', '200-399': '20-39', '400+': '40+'}},
        'notes': [
            'Ledger-only aggregate diagnosis; saved-model hashes are checked without loading, replay, fitting, selection, calibration or threshold search.',
            'Only native lambdarank_pair_method changes: topk to mean. The fixed integer 10 has different pair-construction semantics and does not imply equal effective pair count or the variable 10% decision cutoff.',
            'All eligible orders compete in complete closed daily batches before outcomes are masked; floor(0.1*N), no carryover.',
            'Historical labels require actual delivery strictly before the original fold selection cutoff; unknown outcomes are never treated as on time.',
            'All three evaluation months are repeatedly inspected retrospective development results, never independent unknown-data tests.',
            'July/September historical validation and December development preserve extra route-by-promise and route-by-day marginal counts.',
            'Route, promise, volume and rank associations are descriptive. Overlapping marginal views must not be added together or interpreted as causal feature effects or individual slot transfers.',
            'All 75 earlier candidate metric records, selection schedules, original retained test and default production model remain unchanged.',
        ]}
    expected_phases, verified_rows = set(), 0
    for fold in source['folds']:
        for month, role in [(row['month'], 'validation') for row in fold['schedule']['validation_months']] + [(fold['name'], 'evaluation')]:
            key = f'{fold["name"]}/{month}/{role}'
            if key in report['phases']:
                raise ValueError('Duplicate scoring phase')
            expected_phases.add((fold['name'], role, month))
            frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            fingerprint = (fold['order_id_fingerprints']['validation_full_by_month'][month]
                           if role == 'validation' else fold['order_id_fingerprints']['evaluation'])
            if frame.empty or order_fingerprint(frame) != fingerprint or month not in provenance:
                raise ValueError('Complete scoring identities changed')
            part = ledger.loc[ledger.fold.eq(fold['name']) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            known, scores, context = verify_phase_ledger(frame, part, fold['schedule']['evaluation_start'], role,
                                                       fold['experiment']['models'], month)
            report['phases'][key] = {
                'fold': fold['name'], 'month': month, 'ledger_role': role,
                'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                'order_id_fingerprint': fingerprint, 'context': context,
                **diagnose_phase(frame, scores, known, keep_cross=key in FOCUS_PHASES),
            }
            verified_rows += len(part)
            summary = report['phases'][key]['pair_method']['summary']
            print(f'{key}: topk TP={summary["old_true_positives"]}, mean TP={summary["new_true_positives"]}, net={summary["net_TP"]}', flush=True)
    if (len(expected_phases) != 12
            or set(zip(ledger.fold, ledger.role, ledger.model_version, strict=True)) != expected_phases
            or verified_rows != len(ledger)):
        raise ValueError('Unexpected or missing ledger scoring phases')
    report['compatibility_checks'] = compatibility_checks_from_phases(report['phases'], report['compatibility_targets'])
    if report['compatibility_checks'] != source['compatibility_checks']:
        raise ValueError('Prespecified descriptive compatibility checks do not reconcile score-ledger metrics')
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError('Frozen source changed during diagnosis')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Frozen raw sources changed during diagnosis')
    report['verification'] = {
        'source_and_model_hashes_checked': len(files), 'monthly_model_hashes_checked': 16,
        'score_rows_verified': verified_rows, 'scoring_phases_verified': len(expected_phases),
        'pair_method_contrasts': len(expected_phases), 'detailed_route_promise_day_phases': len(FOCUS_PHASES),
        'source_metrics_and_full_batch_exactly_reconciled': True,
        'frozen_previous_candidate_metrics_unchanged': True,
        'full_batch_ranks_before_outcome_masks': True, 'source_hashes_rechecked_after_analysis': True,
        'daily_volume_route_promise_rank_counts_reconcile': True,
        'descriptive_compatibility_checks_exactly_reconciled': True,
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
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/rank_pair_method.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/rank_pair_method_diagnostics.json')
    args = parser.parse_args(argv)
    try:
        output = validate_output(args.output, args.source_report)
    except ValueError as exc:
        parser.error(str(exc))
    report = build_report(args.source_report, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(f'Wrote {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
