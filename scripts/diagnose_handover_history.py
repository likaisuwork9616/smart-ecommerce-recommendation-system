"""Describe the frozen 101-to-104 handover-history experiment from its score ledger.

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
from scripts.delay_handover_features import ADDED_FEATURES
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

ANALYSIS = 'handover_history_matched_route_volume_diagnostics'
BASELINE = 'xgboost_rank_backlog_7_14d_l2_100_topk_10'
NEW = 'xgboost_rank_handover_104_l2_100_topk_10'
MATCHED = (BASELINE, NEW)
FOCUS_PHASES = (
    '2017-12/2017-07/validation', '2017-12/2017-09/validation',
    '2017-12/2017-12/evaluation',
)
MONTHS = ('2017-07', '2017-08', '2017-09', '2017-10', '2017-11',
          '2017-12', '2018-02', '2018-04')
SUPPORT_BINS = ('history_lt5', 'history_ge5')


def history_support(frame):
    """Validate the count-plus-missingness contract without filling histories."""
    if not set(ADDED_FEATURES) <= set(frame):
        raise ValueError('Require the three declared seller handover-history features')
    values = frame.loc[:, ADDED_FEATURES].apply(pd.to_numeric, errors='raise')
    support = values.iloc[:, 0].to_numpy(dtype=float)
    p50, p90 = (values.iloc[:, i].to_numpy(dtype=float) for i in (1, 2))
    if (not np.isfinite(support).all() or (support < 0).any()
            or not np.equal(support, np.floor(support)).all()):
        raise ValueError('Historical event counts must be finite nonnegative integers')
    enough = support >= 5
    if (not (np.isnan(p50[~enough]).all() and np.isnan(p90[~enough]).all())
            or not (np.isfinite(p50[enough]).all() and np.isfinite(p90[enough]).all())
            or (p50[enough] < 0).any() or (p90[enough] < p50[enough]).any()):
        raise ValueError('Require missing durations below five events and ordered nonnegative quantiles otherwise')
    return support, enough


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
        'comparison_kind': 'fixed_approval_l2_100_topk10_three_handover_features_only',
        'old_feature_count': 101, 'new_feature_count': 104, 'pair_method': 'topk',
        'added_features': list(ADDED_FEATURES),
        'fixed_num_pair_per_sample': 10, 'fixed_l2': 100., 'fixed_daily_cap': .1,
        'interpretation': 'Only the three seller 90-day handover-history inputs change. Both models use approval-time prediction, L2=100, native topk10 and separate full-day floor(10%*N) alert policy.',
    }
    for row in result['days']:
        row['volume_bin'] = volume_bin(sizes[row['day']])
        row['models'] = {c: counts(frame, known, alerts[c], days == row['day']) for c in MATCHED}
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    promises = promise_bins(frame).to_numpy()
    positive = known & (labels == 1)
    changed = {'recovered_delays': positive & ~old & new,
               'lost_delays': positive & old & ~new}
    support_counts, enough = history_support(frame)
    result['feature_support_bins'] = []
    for name, support in zip(SUPPORT_BINS, (~enough, enough), strict=True):
        row = _exchange_summary(frame, known, old, new, np.flatnonzero(support))
        row.update(support_bin=name,
                   event_count_minimum=int(support_counts[support].min()) if support.any() else None,
                   event_count_median=float(np.median(support_counts[support])) if support.any() else None,
                   event_count_maximum=int(support_counts[support].max()) if support.any() else None,
                   budget_scope='Row subgroup after full-day ranking; no subgroup reminder cap.')
        result['feature_support_bins'].append(row)
    _assert_partition(result['feature_support_bins'], result['summary'], COUNT_FIELDS)
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
    return {'volume_context': context, 'handover_features': result,
            'verification': {'full_day_ranks_before_outcome_masks': True,
                'daily_and_volume_counts_partition': True,
                'route_and_promise_partition_each_volume_bin': True,
                'feature_support_subgroups_partition_without_new_caps': True,
                'changed_delay_rank_counts_reconcile': True,
                'reminder_budget_conserved': True}}


def validate_source_contract(source, previous, specification):
    """Bind the feature experiment to all 76 unchanged previous metric records."""
    if (source.get('status') != 'ok' or source.get('experiment') != 'handover_history_features'
            or source.get('daily_cap') != .1 or source.get('matched_candidate_order') != list(MATCHED)
            or source.get('new_candidate_order') != [NEW]
            or source.get('reg_lambda') != 100. or source.get('pair_method') != 'topk'
            or source.get('added_features') != list(ADDED_FEATURES)
            or source.get('num_pair_per_sample') != 10
            or source.get('only_changed_component') != 'three_seller_handover_features'):
        raise ValueError('Require the completed fixed-approval L2=100 topk10 handover-history experiment')
    previous_order = previous.get('candidate_order', [])
    if (previous.get('status') != 'ok' or previous.get('experiment') != 'rank_pair_method'
            or len(previous_order) != 76 or len(set(previous_order)) != 76
            or BASELINE not in previous.get('matched_candidate_order', [])
            or source.get('candidate_order') != [*previous_order, NEW]
            or source.get('source_candidate_versions') != previous.get('source_candidate_versions')
            or source.get('source_features') != {
                key: previous.get('feature_dataset', {}).get(key) for key in ('path', 'sha256')}
            or source.get('source_files') != previous.get('source_files')):
        raise ValueError('Require the unchanged 76-candidate source and feature provenance')
    if (specification.get('experiment') != 'handover_history_features'
            or any(source.get(key) != value for key, value in specification.items())):
        raise ValueError('Completed report changed its predeclared specification')
    designs = source.get('candidate_specifications', {})
    if set(designs) != set(MATCHED):
        raise ValueError('Require both declared fixed-model candidate designs')
    baseline, extended = (designs[candidate] for candidate in MATCHED)
    if (len(baseline.get('numeric_features', [])) + len(baseline.get('categorical_features', [])) != 101
            or extended.get('numeric_features') != [*baseline.get('numeric_features', []), *ADDED_FEATURES]
            or extended.get('categorical_features') != baseline.get('categorical_features')
            or extended.get('classifier_parameters') != baseline.get('classifier_parameters')):
        raise ValueError('Only the three declared inputs may change; classifier parameters must match')
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
                raise ValueError('Frozen baseline101 monthly provenance changed')


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
    for method, candidate in zip(('baseline101', 'handover104'), MATCHED, strict=True):
        values = {name: phases[phase]['context'][candidate]['known_outcome_metrics']['confusion_matrix'][1][1]
                  for name, phase in zip(keys, FOCUS_PHASES, strict=True)}
        if candidate == BASELINE and any(values[key] != targets[key] for key in keys):
            raise ValueError('Frozen descriptive topk baseline performance changed')
        differences = {label: values[key] - targets[key]
                       for label, key in zip(('july_difference', 'september_difference', 'december_difference'), keys, strict=True)}
        checks.append({'candidate': candidate, 'feature_package': method, **values, **differences,
            'both_historical_months_not_worse': differences['july_difference'] >= 0 and differences['september_difference'] >= 0,
            'all_three_descriptive_periods_not_worse': all(value >= 0 for value in differences.values()),
            'used_for_selection': False})
    return checks


def build_report(source_path, data_dir):
    source_path, data_dir = Path(source_path), Path(data_dir)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    baseline_feature_path = ROOT / source['source_features']['path']
    prior_path, archive_path = (ROOT / source[key]['path'] for key in ('source_report', 'source_candidate_versions'))
    spec_path = source_path.with_name('handover_history_specification.json')
    files = {source_path: sha256(source_path), feature_path: source['feature_dataset']['sha256'],
             baseline_feature_path: source['source_features']['sha256'],
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
        'previous_pair_method_report': source['source_report'],
        'earlier_candidate_manifest': source['source_candidate_versions'],
        'source_features': source['feature_dataset'], 'baseline_features': source['source_features'],
        'source_scores': source['score_export'], 'added_features': list(ADDED_FEATURES),
        'specification_sha256': source['specification_sha256'],
        'matched_candidate_order': list(MATCHED), 'model_provenance': provenance,
        'compatibility_targets': source['compatibility_targets'],
        'daily_cap': .1, 'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0,
        'new_model_selection': False, 'phases': {},
        'volume_bin_definition': {'order': list(VOLUME_BINS),
            'basis': 'Complete eligible daily N, including orders with unknown outcomes.',
            'capacity_ranges': {'1-99': '0-9', '100-199': '10-19', '200-399': '20-39', '400+': '40+'}},
        'feature_support_definition': {'order': list(SUPPORT_BINS),
            'count_feature': ADDED_FEATURES[0], 'minimum_quantile_events': 5,
            'basis': 'Mutually exclusive row subsets based on seller history at approval time, after full-day ranking; no subgroup capacity or reranking.',
            'history_window': '[prediction_time-90days,prediction_time)',
            'availability_assumption': 'Carrier event time is available promptly; actual ingestion timestamps are absent.'},
        'notes': [
            'Ledger-only aggregate diagnosis; saved-model hashes are checked without loading, replay, fitting, selection, calibration or threshold search.',
            'Only three seller 90-day historical handover features are added, keeping approval-time prediction and the same L2=100 topk10 settings. No current-order future handover or delivery event is an input.',
            'All eligible orders compete in complete closed daily batches before outcomes are masked; floor(0.1*N), no carryover.',
            'Historical labels require actual delivery strictly before the original fold selection cutoff; unknown outcomes are never treated as on time.',
            'All three evaluation months are repeatedly inspected retrospective development results, never independent unknown-data tests.',
            'July/September historical validation and December development preserve extra route-by-promise and route-by-day marginal counts.',
            'Route, promise, volume and rank associations are descriptive. Overlapping marginal views must not be added together or interpreted as causal feature effects or individual slot transfers.',
            'All 76 earlier candidate metric records, selection schedules, original retained test and default production model remain unchanged.',
            'History support partitions are descriptive. Gain in a subgroup does not prove that its added feature value caused the prediction change; the 104-column model also relearns all other splits.',
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
            summary = report['phases'][key]['handover_features']['summary']
            print(f'{key}: baseline101 TP={summary["old_true_positives"]}, handover104 TP={summary["new_true_positives"]}, net={summary["net_TP"]}', flush=True)
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
        'handover_feature_contrasts': len(expected_phases), 'detailed_route_promise_day_phases': len(FOCUS_PHASES),
        'source_metrics_and_full_batch_exactly_reconciled': True,
        'frozen_previous_candidate_metrics_unchanged': True,
        'full_batch_ranks_before_outcome_masks': True, 'source_hashes_rechecked_after_analysis': True,
        'daily_volume_route_promise_rank_counts_reconcile': True,
        'feature_support_groups_partition_without_new_caps': True,
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
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/handover_history.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/handover_history_diagnostics.json')
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
