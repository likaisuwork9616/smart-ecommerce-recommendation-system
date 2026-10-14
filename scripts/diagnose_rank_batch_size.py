"""Describe frozen ranking changes against complete daily order volume.

Only the already hashed score ledger is read. No model is deserialized, fit,
replayed, selected or promoted. July historical validation and December
development outcomes keep their original, different availability semantics.
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
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_rank_query_alignment import build_training_alignment
from scripts.delay_route_exchanges import COUNT_FIELDS, _row_counts
from scripts.diagnose_budget_misses import MIN_GROUP_POSITIVES, MIN_GROUP_ROWS, PROMISE_BINS, RANK_BINS, daily_rank_bins
from scripts.diagnose_objective_misses import promise_bins
from scripts.diagnose_rank_focus import BASELINES, CLASSIFIERS, MATCHED, NEW, validate_source_contract, verify_phase_ledger
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest

ANALYSIS = 'frozen_rank_daily_volume_diagnostics'
VOLUME_BINS = ('1-99', '100-199', '200-399', '400+')
PAIR_FOCUS = (10, 20, 40)
FOCUS_PHASES = ('2017-12/2017-07/validation', '2017-12/2017-12/evaluation')
COUNT_KEYS = ('full_rows', 'known_rows', 'unknown_rows', 'known_delayed_rows', 'days', 'capacity',
              'alerts', 'known_alerts', 'unknown_alerts', 'TP', 'FP', 'FN', 'TN')
ABSOLUTE_RANK_BINS = ('1-10', '11-20', '21-40', '41+')


def _positive_integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value <= 0:
        raise ValueError(f'{name} must be a positive integer')
    return int(value)


def volume_bin(day_size):
    """Prespecified bins use complete eligible day sizes, never known rows."""
    size = _positive_integer(day_size, 'day_size')
    return VOLUME_BINS[0] if size < 100 else VOLUME_BINS[1] if size < 200 else VOLUME_BINS[2] if size < 400 else VOLUME_BINS[3]


def daily_alignment(day_sizes, k):
    """Compare fixed native k positions with floor(10% * full-day N).

    Equality is an arithmetic property of position counts, not evidence that
    training queries and inference days contain the same orders or rankings.
    """
    k = _positive_integer(k, 'k')
    sizes = [_positive_integer(n, 'day_size') for n in day_sizes]
    fields = ('days', 'full_rows', 'capacity', 'effective_focus_positions')
    relation = {name: dict.fromkeys(fields, 0) for name in ('k_lt_capacity', 'k_eq_capacity', 'k_gt_capacity')}
    effective = {name: dict.fromkeys(fields, 0) for name in ('k_lt_capacity', 'k_eq_capacity', 'k_gt_capacity')}
    totals = dict.fromkeys(fields, 0)
    for size in sizes:
        capacity, focus = size // 10, min(k, size)
        current = {'days': 1, 'full_rows': size, 'capacity': capacity, 'effective_focus_positions': focus}
        for kind, value in ((relation, k), (effective, focus)):
            name = 'k_lt_capacity' if value < capacity else 'k_eq_capacity' if value == capacity else 'k_gt_capacity'
            for field in fields:
                kind[name][field] += current[field]
        for field in fields:
            totals[field] += current[field]
    return {'k': k, **totals, 'relation': relation, 'effective_relation': effective,
            'broad_inclusion_days': effective['k_eq_capacity']['days'] + effective['k_gt_capacity']['days'],
            'exact_position_count_match_days': effective['k_eq_capacity']['days']}


def _known_labels(frame, known_mask):
    known = np.asarray(known_mask)
    if known.ndim != 1 or len(known) != len(frame) or known.dtype != bool:
        raise ValueError('Require an aligned boolean known-outcome mask')
    observed = frame.delayed.to_numpy(dtype=object)[known]
    if not np.isin(observed, [0, 1]).all():
        raise ValueError('Known labels must be binary')
    labels = np.full(len(frame), -1, dtype=int)
    labels[known] = observed.astype(int)
    return known, labels


def _day_info(frame):
    values = pd.to_datetime(frame.prediction_time, errors='raise')
    if values.isna().any() or values.dt.tz is not None:
        raise ValueError('Prediction times must be valid timezone-naive timestamps')
    days = values.dt.strftime('%Y-%m-%d').to_numpy()
    sizes = pd.Series(days).value_counts().sort_index().to_dict()
    return days, {day: int(size) for day, size in sizes.items()}


def counts(frame, known, alert, support=None):
    """Outcome accounting on complete days; unknown labels are never read.

    A support mask must retain every row of any day it includes. Route and
    promise views use separate row marginals without fictitious sub-day caps.
    """
    known, labels = _known_labels(frame, known)
    selected = np.asarray(alert)
    if selected.ndim != 1 or len(selected) != len(frame) or selected.dtype != bool:
        raise ValueError('Require an aligned boolean alert vector')
    mask = np.ones(len(frame), bool) if support is None else np.asarray(support)
    if mask.ndim != 1 or len(mask) != len(frame) or mask.dtype != bool:
        raise ValueError('Require an aligned boolean support mask')
    days, sizes = _day_info(frame)
    selected_days = sorted(set(days[mask]))
    if any(int((mask & (days == day)).sum()) != sizes[day] for day in selected_days):
        raise ValueError('Support must contain complete days')
    positive, negative = known & (labels == 1), known & (labels == 0)
    row = {'full_rows': int(mask.sum()), 'known_rows': int((mask & known).sum()),
           'unknown_rows': int((mask & ~known).sum()), 'known_delayed_rows': int((mask & positive).sum()),
           'days': len(selected_days), 'capacity': sum(sizes[day] // 10 for day in selected_days),
           'alerts': int((mask & selected).sum()), 'known_alerts': int((mask & known & selected).sum()),
           'unknown_alerts': int((mask & ~known & selected).sum()),
           'TP': int((mask & positive & selected).sum()), 'FP': int((mask & negative & selected).sum()),
           'FN': int((mask & positive & ~selected).sum()), 'TN': int((mask & negative & ~selected).sum())}
    row.update(recall=row['TP'] / row['known_delayed_rows'] if row['known_delayed_rows'] else None,
               precision=row['TP'] / row['known_alerts'] if row['known_alerts'] else None,
               observed_delay_rate=row['known_delayed_rows'] / row['known_rows'] if row['known_rows'] else None,
               reminder_rate=row['alerts'] / row['full_rows'] if row['full_rows'] else None,
               minimum_sample_met=row['known_rows'] >= MIN_GROUP_ROWS and row['known_delayed_rows'] >= MIN_GROUP_POSITIVES)
    return row


def _positions(frame, scores):
    """One-based ranks in full-day score-desc/ID-asc order, before labels."""
    days, _ = _day_info(frame)
    ranked = pd.DataFrame({'day': days, 'score': scores, 'id': frame.order_id.to_numpy(),
                           'position': np.arange(len(frame))})
    ranked = ranked.sort_values(['day', 'score', 'id'], ascending=[True, False, True], kind='stable')
    result = np.empty(len(frame), dtype=int)
    result[ranked.position.to_numpy()] = ranked.groupby('day', sort=False).cumcount().to_numpy() + 1
    return result


def _rank_summary(mask, old_positions, new_positions, old_bins, new_bins):
    def aggregate(values):
        selected = values[mask]
        return {'minimum': int(selected.min()) if len(selected) else None,
                'median': float(np.median(selected)) if len(selected) else None,
                'maximum': int(selected.max()) if len(selected) else None,
                'absolute_bins': {name: int(((selected <= 10) if name == '1-10' else
                    ((selected > 10) & (selected <= 20)) if name == '11-20' else
                    ((selected > 20) & (selected <= 40)) if name == '21-40' else (selected > 40)).sum())
                    for name in ABSOLUTE_RANK_BINS}}
    result = {'rows': int(mask.sum()), 'old_positions': aggregate(old_positions), 'new_positions': aggregate(new_positions),
              'old_relative_bins': {name: int((mask & (old_bins == name)).sum()) for name in RANK_BINS},
              'new_relative_bins': {name: int((mask & (new_bins == name)).sum()) for name in RANK_BINS}}
    for side in ('old', 'new'):
        if (sum(result[f'{side}_positions']['absolute_bins'].values()) != result['rows'] or
                sum(result[f'{side}_relative_bins'].values()) != result['rows']):
            raise AssertionError('Rank summaries must partition changed-delay cohorts')
    return result


def _exchange_summary(frame, known, old, new, positions):
    known, labels = _known_labels(frame, known)
    return _row_counts(np.asarray(positions, dtype=int), known, labels, old, new)


def _assert_partition(rows, expected, keys):
    for key in keys:
        if sum(row[key] for row in rows) != expected[key]:
            raise AssertionError(f'Partition does not reconcile {key}')


def diagnose_phase(frame, scores, known, *, include_primary_change=False):
    """Describe eight existing rankings with fixed bins and matched contrasts."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError('Require a nonempty complete phase')
    if set(scores) != set(MATCHED):
        raise ValueError('Require all eight prespecified score cohorts')
    known, labels = _known_labels(frame, known)
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED}
    positions = {c: _positions(frame, scores[c]) for c in MATCHED}
    ranks = {c: daily_rank_bins(frame, scores[c]) for c in MATCHED}
    days, sizes = _day_info(frame)
    row_bins = np.asarray([volume_bin(sizes[day]) for day in days])
    result = {'context': {c: counts(frame, known, alerts[c]) for c in MATCHED},
              'daily_volume': [], 'volume_bins': [], 'contrasts': {}}
    for candidate in MATCHED:
        if not np.array_equal(alerts[candidate], positions[candidate] <= np.asarray([sizes[day] // 10 for day in days])):
            raise AssertionError('Full-day ranks must reproduce existing 10% decisions')
        if result['context'][candidate]['alerts'] != result['context'][candidate]['capacity']:
            raise AssertionError('Complete phase must use exact floor daily budget')
    for day, size in sizes.items():
        support = days == day
        result['daily_volume'].append({'day': day, 'full_rows': size, 'capacity': size // 10, 'volume_bin': volume_bin(size),
            'models': {c: counts(frame, known, alerts[c], support) for c in MATCHED}})
    for name in VOLUME_BINS:
        support = row_bins == name
        selected_sizes = [size for day, size in sizes.items() if volume_bin(size) == name]
        result['volume_bins'].append({'volume_bin': name, 'day_sizes': selected_sizes,
            'models': {c: counts(frame, known, alerts[c], support) for c in MATCHED},
            'k_alignment': {str(k): daily_alignment(selected_sizes, k) for k in PAIR_FOCUS}})
    for candidate in MATCHED:
        for rows in (result['daily_volume'], result['volume_bins']):
            _assert_partition([row['models'][candidate] for row in rows], result['context'][candidate], COUNT_KEYS)

    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    promises = promise_bins(frame).to_numpy()
    comparisons = [(candidate, baseline, candidate, 'fixed_l2_k_only') for candidate, baseline in
                   zip(NEW, (BASELINES[0], BASELINES[0], BASELINES[1], BASELINES[1]), strict=True)]
    if include_primary_change:
        comparisons.append(('primary_change', CLASSIFIERS[0], NEW[2], 'mixed_objective_and_feature_package'))
    for key, old_name, new_name, kind in comparisons:
        old, new = alerts[old_name], alerts[new_name]
        positive = known & (labels == 1)
        newly_caught, lost = positive & ~old & new, positive & old & ~new
        overall = _exchange_summary(frame, known, old, new, np.arange(len(frame)))
        comparison = {'old_candidate': old_name, 'new_candidate': new_name, 'comparison_kind': kind,
            'fixed_daily_cap': .1, 'fixed_l2': 100. if kind == 'fixed_l2_k_only' else None,
            'old_native_k': 20 if kind == 'fixed_l2_k_only' else None,
            'new_native_k': int(new_name.rsplit('_', 1)[1]),
            'interpretation': 'Matched feature package and L2; only native pair-focus k differs.' if kind == 'fixed_l2_k_only' else
                'The historical rule switched classifier geo83 to ranking backlog101 k10; objective, feature package and regularization differ, so this is not a k-only effect.'}
        value = {'comparison': comparison, 'overall': overall, 'daily': [], 'by_volume_bin': []}
        for day in sizes:
            row = _exchange_summary(frame, known, old, new, np.flatnonzero(days == day))
            value['daily'].append({'day': day, 'volume_bin': volume_bin(sizes[day]), 'capacity': sizes[day] // 10, **row})
        for name in VOLUME_BINS:
            support = row_bins == name
            row = _exchange_summary(frame, known, old, new, np.flatnonzero(support))
            route_rows = [{'state_route': route, **_exchange_summary(frame, known, old, new,
                           np.flatnonzero(support & (routes == route)))} for route in sorted(set(routes[support]))]
            promise_rows = [{'promise_bin': promise, **_exchange_summary(frame, known, old, new,
                             np.flatnonzero(support & (promises == promise)))} for promise in PROMISE_BINS]
            for rows in (route_rows, promise_rows):
                _assert_partition(rows, row, COUNT_FIELDS)
            rank_changes = {label: _rank_summary(support & cohort, positions[old_name], positions[new_name], ranks[old_name], ranks[new_name])
                            for label, cohort in (('recovered_delays', newly_caught), ('lost_delays', lost))}
            if any(rank_changes[label]['rows'] != row[label] for label in rank_changes):
                raise AssertionError('Changed-delay ranks must match the alert exchange accounting')
            value['by_volume_bin'].append({'volume_bin': name, **row, 'routes': route_rows,
                'promise_days': promise_rows, 'changed_delay_ranks': rank_changes})
        for rows in (value['daily'], value['by_volume_bin']):
            _assert_partition(rows, overall, COUNT_FIELDS)
        if overall['net_alerts'] != 0 or overall['dropped_alerts'] != overall['added_alerts']:
            raise AssertionError('Fixed daily budget must conserve reminder slots')
        result['contrasts'][key] = value
    result['k_alignment'] = {str(k): daily_alignment(list(sizes.values()), k) for k in PAIR_FOCUS}
    result['verification'] = {'full_day_ranks_before_outcome_masks': True, 'daily_and_volume_counts_partition': True,
        'route_and_promise_counts_partition_each_volume_bin': True, 'changed_delay_rank_counts_reconcile': True,
        'reminder_budget_conserved': True, 'contrast_count': len(comparisons)}
    return result


def build_report(source_path, data_dir):
    source_path, data_dir = Path(source_path), Path(data_dir)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    prior_path, archive_path = (ROOT / source[key]['path'] for key in ('source_report', 'source_candidate_versions'))
    spec_path = source_path.with_name('rank_pair_focus_specification.json')
    files = {source_path: sha256(source_path), feature_path: source['feature_dataset']['sha256'],
        score_path: source['score_export']['sha256'], prior_path: source['source_report']['sha256'],
        archive_path: source['source_candidate_versions']['sha256'], spec_path: source['specification_sha256']}
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError(f'Frozen diagnostic source changed: {relative(path)}')
    previous = json.loads(prior_path.read_text(encoding='utf-8'))
    specification = json.loads(spec_path.read_text(encoding='utf-8'))
    validate_source_contract(source, previous, specification)
    current_december = next(fold for fold in source['folds'] if fold['name'] == '2017-12')
    previous_december = next(fold for fold in previous['folds'] if fold['name'] == '2017-12')
    main_group = source['primary_selection_prespecified']
    prior_main = previous_december['experiment']['selected_models'][main_group]
    current_main = current_december['experiment']['selected_models'][main_group]
    if (prior_main, current_main) != (CLASSIFIERS[0], NEW[2]):
        raise ValueError('Frozen December main-rule switch differs from the declared mixed contrast')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Frozen raw sources changed')
    model_provenance = {}
    for row in source['monthly_training']:
        model_provenance[row['month']] = {}
        for candidate in MATCHED:
            info = row['models'][candidate]['version_artifact']
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Frozen saved-model hash changed')
            files[path] = info['sha256']
            model_provenance[row['month']][candidate] = info
    features = read_features(feature_path, data_dir)
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    ledger['prediction_time'] = pd.to_datetime(ledger.prediction_time, errors='raise')
    if len(ledger) != source['score_export']['rows'] or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any():
        raise ValueError('Frozen ledger size or uniqueness changed')
    report = {'format_version': 1, 'analysis': ANALYSIS, 'status': 'ok', 'daily_cap': .1,
        'source_report': {'path': relative(source_path), 'sha256': files[source_path]},
        'source_features': source['feature_dataset'], 'source_scores': source['score_export'],
        'previous_l2_report': source['source_report'], 'specification_sha256': source['specification_sha256'],
        'model_provenance': model_provenance, 'matched_candidate_order': list(MATCHED),
        'december_frozen_main_selection': {'selection_group': main_group, 'previous_candidate': prior_main,
            'current_candidate': current_main, 'new_selection_performed': False},
        'volume_bin_definition': {'order': list(VOLUME_BINS), 'basis': 'Complete eligible day N, including unknown outcomes.',
            'capacity_ranges': {'1-99': '0-9', '100-199': '10-19', '200-399': '20-39', '400+': '40+'},
            'prespecified_before_analysis': True},
        'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0, 'new_model_selection': False,
        'training_query_alignment': build_training_alignment(features, source), 'phases': {},
        'notes': ['Frozen ledger diagnosis; only arithmetic summaries and source/model hash checks are performed.',
            'July labels require actual delivery strictly before 2017-12-01. Unknown rows still compete in the complete daily budget and are never assumed on time.',
            'December uses eventual labels only as repeatedly inspected retrospective development results; it is not an unknown-data test.',
            'Native k sets a fixed top-position pair-construction focus, not k pairs per query and not a variable top10% cutoff. Focus positions are bounded by min(k,N).',
            'k equals floor(0.1*N) only at N=10*k through 10*k+9; k above capacity broadly includes reminder positions but also optimizes positions outside that cutoff.',
            'Volume associations and changed ranks describe where performance differs; they do not identify a causal effect of volume, route, promise, or k.',
            'The December main-rule switch changes objective, feature package and regularization. Its losses must not be attributed to k alone.',
            'Complete closed daily batches use floor(0.1*N), with no carryover. No threshold, score, model, selector or original retained test is changed.',
            'Route and promise summaries are overlapping marginal views; never add their totals to each other.']}
    expected_phases, verified_rows = set(), 0
    for fold in source['folds']:
        for month, role in [(row['month'], 'validation') for row in fold['schedule']['validation_months']] + [(fold['name'], 'evaluation')]:
            key = f'{fold["name"]}/{month}/{role}'
            expected_phases.add((fold['name'], role, month))
            frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            fingerprint = (fold['order_id_fingerprints']['validation_full_by_month'][month] if role == 'validation' else fold['order_id_fingerprints']['evaluation'])
            if frame.empty or order_fingerprint(frame) != fingerprint:
                raise ValueError('Complete scoring identities changed')
            part = ledger.loc[ledger.fold.eq(fold['name']) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            known, scores, context = verify_phase_ledger(frame, part, fold['schedule']['evaluation_start'], role, fold['experiment']['models'], month)
            verified_rows += len(part)
            if key not in FOCUS_PHASES:
                continue
            report['phases'][key] = {'fold': fold['name'], 'month': month,
                'role': 'historical_validation' if role == 'validation' else 'development_retest', 'ledger_role': role,
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                'outcome_semantics': 'Known strictly before historical cutoff; unknown preserved.' if role == 'validation' else 'Eventual labels, retrospective development only; unavailable at model selection.',
                'order_id_fingerprint': fingerprint, 'source_context': context,
                **diagnose_phase(frame, scores, known, include_primary_change=role == 'evaluation')}
            print(f'{key}: full daily volumes and frozen ranking contrasts reconciled', flush=True)
    if (set(zip(ledger.fold, ledger.role, ledger.model_version, strict=True)) != expected_phases or
            verified_rows != len(ledger) or set(report['phases']) != set(FOCUS_PHASES)):
        raise ValueError('Unexpected, missing or duplicate source scoring phases')
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError('Frozen diagnostic source changed during analysis')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Frozen raw sources changed during analysis')
    report['verification'] = {'source_and_model_hashes_checked': len(files),
        'monthly_model_hashes_checked': sum(len(row) for row in model_provenance.values()),
        'source_score_rows_verified': verified_rows, 'source_scoring_phases_verified': len(expected_phases),
        'diagnosed_phases': len(report['phases']), 'pure_k_contrasts': 8, 'mixed_main_change_contrasts': 1,
        'source_metrics_and_full_batch_exactly_reconciled': True, 'source_hashes_rechecked_after_analysis': True,
        'full_batch_ranks_before_outcome_masks': True, 'saved_versions_replayed_in_this_cli': 0,
        'new_fit_count': 0, 'new_model_selection': False}
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
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/rank_pair_focus.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/rank_batch_size_diagnostics.json')
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
