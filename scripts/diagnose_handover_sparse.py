"""Inspect frozen handover-model intersections and daily alert accounting.

Only the already frozen ledger is ranked. No model is deserialized, fitted,
replayed, selected or promoted. Groups never receive their own alert budget.
"""
from __future__ import annotations

import argparse
from itertools import product
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
from scripts.delay_route_exchanges import COUNT_FIELDS, _rank_movements, _row_counts, analyze_route_exchanges
from scripts.diagnose_budget_misses import MIN_GROUP_POSITIVES, MIN_GROUP_ROWS, PROMISE_BINS, daily_rank_bins
from scripts.diagnose_handover_history import (
    ADDED_FEATURES, BASELINE, MATCHED, NEW, history_support,
    validate_source_contract, verify_phase_ledger,
)
from scripts.diagnose_objective_misses import promise_bins
from scripts.diagnose_rank_batch_size import _assert_partition, _day_info, _known_labels, _positions, _rank_summary
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest

ANALYSIS = 'frozen_handover_sparse_intersection_diagnostics'
SOURCE_SHA = '0503ed31ac4c0dc06e5fb52c7848810cfcb408c61fdb9684fa3afc26f2769b6e'
DIAGNOSTICS_SHA = '75a8fb739c8072cefc3540e4b8059133d9a974c7f0d912cca82bb43a14b0ce81'
SUPPORT_BINS = ('history0', 'history1_4', 'history_ge5')
PROMISE_GROUPS = ('promise0_30', 'promise31plus')
ROUTE_GROUPS = ('SP_RJ', 'other_route')
CELL_DEFINITIONS = tuple(product(SUPPORT_BINS, PROMISE_GROUPS, ROUTE_GROUPS))
FOCUS_MASKS = ('all', 'history_lt5', 'promise31plus', 'SP_RJ',
               'history_lt5_and_promise31plus', 'history_lt5_and_SP_RJ',
               'promise31plus_and_SP_RJ', 'triple')
OUTCOMES = ('delayed', 'on_time', 'unknown')


def cell_key(support, promise, route):
    return f'{support}|{promise}|{route}'


def group_definitions(frame):
    """Use the existing history and promise boundaries; keep unknown routes."""
    support, _ = history_support(frame)
    promises = promise_bins(frame).to_numpy()
    numeric_promise = pd.to_numeric(frame.estimated_delivery_days, errors='raise').to_numpy()
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    if any(not value.strip() for value in routes):
        raise ValueError('Routes must be nonempty strings or missing')
    support_groups = np.where(support == 0, SUPPORT_BINS[0],
                              np.where(support < 5, SUPPORT_BINS[1], SUPPORT_BINS[2]))
    long = numeric_promise > 30
    route = routes == 'SP->RJ'
    promise_groups = np.where(long, PROMISE_GROUPS[1], PROMISE_GROUPS[0])
    route_groups = np.where(route, ROUTE_GROUPS[0], ROUTE_GROUPS[1])
    cells = np.asarray([cell_key(*values) for values in zip(support_groups, promise_groups, route_groups, strict=True)])
    sparse = support < 5
    masks = dict(zip(FOCUS_MASKS, (np.ones(len(frame), bool), sparse, long, route,
        sparse & long, sparse & route, long & route, sparse & long & route), strict=True))
    return {'support': support_groups, 'promise_bin': promises, 'routes': routes,
            'promise_group': promise_groups, 'route_group': route_groups,
            'cells': cells, 'masks': masks}


def _counts(mask, known, labels, old, new):
    row = _row_counts(np.flatnonzero(mask), known, labels, old, new)
    row['small_sample'] = not row['minimum_sample_met']
    return row


def _aggregate(values):
    return {'minimum': int(values.min()) if len(values) else None,
            'median': float(np.median(values)) if len(values) else None,
            'maximum': int(values.max()) if len(values) else None}


def focus_rank_summary(mask, known, labels, old, new, positions, ranks, capacity):
    """Ranks and capacity gaps refer to original full days, before masking."""
    selected = np.flatnonzero(mask)
    movement = _rank_movements(known[selected], labels[selected], old[selected], new[selected],
                               ranks[BASELINE][selected], ranks[NEW][selected])
    positive, negative = known & (labels == 1), known & (labels == 0)
    cohorts = {'recovered_delays': positive & ~old & new,
               'lost_delays': positive & old & ~new,
               'both_missed_delays': positive & ~old & ~new,
               'added_on_time_alerts': negative & ~old & new}
    details = {}
    for name, cohort in cohorts.items():
        chosen = mask & cohort
        row = _rank_summary(chosen, positions[BASELINE], positions[NEW], ranks[BASELINE], ranks[NEW])
        row['off_top10_gap_slots'] = {
            'definition': 'Full-day one-based rank minus floor(0.1*N); positive means outside the reminder capacity.',
            'old': _aggregate((positions[BASELINE] - capacity)[chosen]),
            'new': _aggregate((positions[NEW] - capacity)[chosen]),
        }
        details[name] = row
    return {'cohorts': movement, 'changed_and_missed_rank_details': details,
            'score_comparison': 'Scores are not compared across models; only full-day ranks and distances to that same day capacity are compared.'}


def cell_allocations(frame, scores, known, cells):
    """Reuse the daily allocation accountant with cells as its grouping key."""
    grouped = frame.copy()
    grouped['state_route'] = cells
    raw = analyze_route_exchanges(grouped, scores[BASELINE], scores[NEW], known, .1)
    renames = {'state_route': 'cell', 'within_route_exchanges': 'within_cell_exchanges',
               'cross_route_outgoing_slots': 'cross_cell_outgoing_slots',
               'cross_route_incoming_slots': 'cross_cell_incoming_slots',
               'cross_route_slots': 'cross_cell_slots', 'route_days': 'daycells', 'routes': 'cells'}
    def rename(row):
        return {renames.get(key, key): value for key, value in row.items()}
    summary = rename(raw['allocation_summary'])
    summary['cross_cell_outgoing_slots'] = summary['cross_cell_slots']
    summary['cross_cell_incoming_slots'] = summary['cross_cell_slots']
    # Preserve all twelve cells, including empty cells on otherwise complete days.
    empty = {**_row_counts(np.asarray([], int), np.asarray([], bool), np.asarray([], int),
                           np.asarray([], bool), np.asarray([], bool)),
             'within_cell_exchanges': 0, 'cross_cell_outgoing_slots': 0, 'cross_cell_incoming_slots': 0}
    cell_lookup = {row['state_route']: rename(row) for row in raw['routes']}
    daycell_lookup = {(row['day'], row['state_route']): rename(row) for row in raw['route_day_allocations']}
    ordered = [cell_key(*definition) for definition in CELL_DEFINITIONS]
    summary['observed_daycells'] = summary['daycells']
    summary['observed_cells'] = summary['cells']
    summary['cells'] = len(ordered)
    summary['daycells'] = len(raw['days']) * len(ordered)
    cell_rows = [{**cell_lookup.get(key, empty), 'cell': key} for key in ordered]
    daycell_rows = [{**daycell_lookup.get((day['day'], key), empty), 'day': day['day'], 'cell': key}
                   for day in raw['days'] for key in ordered]
    return {'summary': summary, 'cells': cell_rows,
            'daycells': daycell_rows,
            'days': [rename(row) for row in raw['days']],
            'definition': 'Within each complete day and cell: within=min(dropped,added), outgoing=max(dropped-added,0), incoming=max(added-dropped,0). Monthly gross totals sum daily counts; they are not monthly net differences.',
            'interpretation': 'Aggregate count identities only. No specific donor, recipient or causal transfer is paired.'}


def lost_day_context(frame, known, labels, old, new, groups, days):
    """Describe whole-day changes on loss days without inventing pairings."""
    positive = known & (labels == 1)
    outcomes = {'delayed': positive, 'on_time': known & (labels == 0), 'unknown': ~known}
    changed = {'added': ~old & new, 'dropped': old & ~new}
    result = {}
    for focus in ('history_lt5', 'promise31plus_and_SP_RJ', 'triple'):
        support = groups['masks'][focus]
        loss = support & positive & old & ~new
        loss_days = sorted(set(days[loss]))
        focus_days = []
        for day in sorted(set(days[support])):
            mask = support & (days == day)
            focus_days.append({'day': day, **_counts(mask, known, labels, old, new)})
        detail = []
        for day in loss_days:
            same_day = days == day
            rows = []
            for definition in CELL_DEFINITIONS:
                key = cell_key(*definition)
                for direction, movement in changed.items():
                    for outcome, available in outcomes.items():
                        rows.append({'cell': key, 'direction': direction, 'outcome': outcome,
                            'rows': int((same_day & (groups['cells'] == key) & movement & available).sum())})
            whole = _counts(same_day, known, labels, old, new)
            for direction, count_key in (('added', 'added_alerts'), ('dropped', 'dropped_alerts')):
                if sum(row['rows'] for row in rows if row['direction'] == direction) != whole[count_key]:
                    raise AssertionError('Whole loss-day changes do not reconcile cells and outcomes')
            detail.append({'day': day, 'focus': _counts(support & same_day, known, labels, old, new),
                           'whole_day': whole, 'whole_day_changed_alerts_by_cell_outcome': rows})
        result[focus] = {'lost_delay_rows': int(loss.sum()), 'lost_delay_days': len(loss_days),
            'all_focus_days': focus_days, 'days': detail,
            'interpretation': 'All added/dropped reminders in the entire same day, not only this focus. Co-occurrence is not an individual donor/recipient match or evidence of causality. All focus days also retain recovered delays.'}
    return result


def diagnose_phase(frame, scores, known):
    if not isinstance(frame, pd.DataFrame) or frame.empty or set(scores) != set(MATCHED):
        raise ValueError('Require one nonempty full phase and both fixed candidates')
    known, labels = _known_labels(frame, known)
    groups = group_definitions(frame)
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED}
    positions = {c: _positions(frame, scores[c]) for c in MATCHED}
    ranks = {c: daily_rank_bins(frame, scores[c]) for c in MATCHED}
    old, new = alerts[BASELINE], alerts[NEW]
    days, sizes = _day_info(frame)
    capacity = np.asarray([sizes[day] // 10 for day in days])
    if any(not np.array_equal(alerts[c], positions[c] <= capacity) for c in MATCHED):
        raise AssertionError('Original full-day ranks must reproduce the reminder policy')
    summary = _counts(np.ones(len(frame), bool), known, labels, old, new)
    intersections = []
    for support, promise, route in CELL_DEFINITIONS:
        key = cell_key(support, promise, route)
        intersections.append({'cell': key, 'support_bin': support, 'promise_group': promise,
                              'route_group': route, **_counts(groups['cells'] == key, known, labels, old, new)})
    _assert_partition(intersections, summary, COUNT_FIELDS)
    observed = []
    for route in sorted(set(groups['routes'])):
        for promise in PROMISE_BINS:
            for support in SUPPORT_BINS:
                mask = (groups['routes'] == route) & (groups['promise_bin'] == promise) & (groups['support'] == support)
                if mask.any():
                    observed.append({'state_route': route, 'promise_bin': promise, 'support_bin': support,
                                     **_counts(mask, known, labels, old, new)})
    _assert_partition(observed, summary, COUNT_FIELDS)
    focuses = []
    for name, mask in groups['masks'].items():
        focuses.append({'mask': name, **_counts(mask, known, labels, old, new),
                        'rank_analysis': focus_rank_summary(mask, known, labels, old, new, positions, ranks, capacity)})
    allocation = cell_allocations(frame, scores, known, groups['cells'])
    _assert_partition(allocation['cells'], summary, COUNT_FIELDS)
    return {'summary': summary, 'intersection_cells': intersections,
        'observed_route_promise_support': observed, 'focus_masks': focuses,
        'cell_allocation': allocation,
        'lost_delay_day_context': lost_day_context(frame, known, labels, old, new, groups, days),
        'verification': {'complete_day_ranks_before_masks': True, 'mutually_exclusive_12_cells_partition': True,
            'observed_route_promise_support_partition': True, 'no_subgroup_reranking_or_capacity': True,
            'daily_cell_allocation_conserved': True, 'focus_rank_cohorts_partition': True,
            'loss_day_whole_batch_changes_partition': True}}


def build_report(source_path, data_dir, previous_diagnostics_path):
    source_path, data_dir, previous_diagnostics_path = map(Path, (source_path, data_dir, previous_diagnostics_path))
    if sha256(source_path) != SOURCE_SHA or sha256(previous_diagnostics_path) != DIAGNOSTICS_SHA:
        raise ValueError('Require the frozen handover experiment and its exact published diagnostic')
    source = json.loads(source_path.read_text(encoding='utf-8'))
    prior_diagnostics = json.loads(previous_diagnostics_path.read_text(encoding='utf-8'))
    feature_path = ROOT / source['feature_dataset']['path']
    score_path = ROOT / source['score_export']['path']
    previous_path = ROOT / source['source_report']['path']
    spec_path = source_path.with_name('handover_history_specification.json')
    files = {source_path: SOURCE_SHA, previous_diagnostics_path: DIAGNOSTICS_SHA,
        feature_path: source['feature_dataset']['sha256'], score_path: source['score_export']['sha256'],
        previous_path: source['source_report']['sha256'], spec_path: source['specification_sha256'],
        ROOT / source['source_features']['path']: source['source_features']['sha256'],
        ROOT / source['source_candidate_versions']['path']: source['source_candidate_versions']['sha256']}
    provenance, selected = {}, {}
    for row in source['monthly_training']:
        provenance[row['month']] = {c: row['models'][c]['version_artifact'] for c in MATCHED}
        for info in provenance[row['month']].values():
            files[ROOT / info['path']] = info['sha256']
    for fold in source['folds']:
        info = fold['research_artifact']
        selected[fold['name']] = info
        files[ROOT / info['path']] = info['sha256']
    for info in source['source_files']:
        files[data_dir / info['filename']] = info['sha256']
    def check_sources():
        for path, expected in files.items():
            if sha256(path) != expected:
                raise ValueError(f'Frozen source changed: {relative(path)}')
        if engineering_source_manifest(data_dir) != source['source_files']:
            raise ValueError('Frozen raw sources changed')
    check_sources()
    previous = json.loads(previous_path.read_text(encoding='utf-8'))
    specification = json.loads(spec_path.read_text(encoding='utf-8'))
    validate_source_contract(source, previous, specification)
    if (prior_diagnostics.get('source_report') != {'path': relative(source_path), 'sha256': SOURCE_SHA}
            or prior_diagnostics.get('status') != 'ok' or len(prior_diagnostics.get('phases', {})) != 12):
        raise ValueError('Previous diagnostic does not describe the frozen source')
    features = read_features(feature_path, data_dir)
    if (len(features) != source['feature_dataset']['rows'] or len(features.columns) != 137
            or features.prediction_time.ge('2018-05-01').any()):
        raise ValueError('Require the unchanged 137-column feature cache before May 2018')
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    ledger['prediction_time'] = pd.to_datetime(ledger.prediction_time, errors='raise')
    if (len(ledger) != 128112 or len(ledger) != source['score_export']['rows']
            or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Frozen score size or uniqueness changed')
    report = {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': SOURCE_SHA},
        'source_diagnostics': {'path': relative(previous_diagnostics_path), 'sha256': DIAGNOSTICS_SHA},
        'source_features': source['feature_dataset'], 'baseline_features': source['source_features'],
        'source_scores': source['score_export'], 'model_provenance': provenance, 'selected_artifacts': selected,
        'matched_candidate_order': list(MATCHED), 'added_features': list(ADDED_FEATURES),
        'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0, 'new_model_selection': False,
        'original_holdout_not_rescored': True, 'daily_cap': .1,
        'definitions': {
            'prediction_time': 'approval', 'l2': 100., 'pair_method': 'topk', 'num_pair_per_sample': 10,
            'old_feature_count': 101, 'new_feature_count': 104,
            'support_bins': {'history0': 'event_count == 0', 'history1_4': '1 <= event_count < 5', 'history_ge5': 'event_count >= 5'},
            'promise_groups': {'promise0_30': 'estimated_delivery_days <= 30', 'promise31plus': 'estimated_delivery_days > 30, including fractional 30.x days'},
            'original_promise_bins': list(PROMISE_BINS),
            'route_groups': {'SP_RJ': 'state_route == SP->RJ', 'other_route': 'every other route, including unknown'},
            'cell_order': [cell_key(*definition) for definition in CELL_DEFINITIONS],
            'focus_masks': list(FOCUS_MASKS), 'outcomes': list(OUTCOMES),
            'minimum_group_known_rows': MIN_GROUP_ROWS, 'minimum_group_delayed_rows': MIN_GROUP_POSITIVES,
            'small_sample_rule': 'small_sample is the inverse of minimum_sample_met; empty cells remain with null recalls.',
            'budget': 'Complete closed daily batch floor(0.1*N), no carryover. Unknown outcomes compete before masking. Subgroups are never reranked or capped.',
            'rank_gap': 'One-based full-day rank minus that complete day floor(0.1*N); positive is outside the reminder capacity. No cross-model raw score difference.',
            'interpretation': 'April and the eight masks are retrospective descriptive targets motivated by already inspected results; not a prespecified hypothesis test or model selection. Earlier phases use exactly the same boundaries and accounting. Overlapping focus masks must not be added together.',
        }, 'phases': {}, 'phase_summary': [],
        'notes': [
            'Frozen-ledger diagnosis only: no fitting, model deserialization/replay, calibration, threshold search, new selector or promotion.',
            'All three evaluation months are reused retrospective development retests, not independent unknown-data tests. Historical validation retains each original fold cutoff; repeated validation months are not independent new cohorts.',
            'The actual sparse-history, long-promise and SP->RJ triple intersection is reported independently of its overlapping marginals.',
            'Daily cell incoming/outgoing counts are gross accounting identities, not individual donor/recipient pairs, and same-day alert changes do not establish feature causality.',
            'The new model relearned all splits; subgroup associations do not identify the causal effect of a particular missing quantile or input feature.',
            'No original retained test is rescored, no training setting is altered, and the default production model is unchanged.',
        ]}
    expected_phases, verified_rows = set(), 0
    for fold in source['folds']:
        schedule = [(row['month'], 'validation') for row in fold['schedule']['validation_months']]
        for month, role in [*schedule, (fold['name'], 'evaluation')]:
            key = f'{fold["name"]}/{month}/{role}'
            if key in report['phases']:
                raise ValueError('Duplicate phase')
            expected_phases.add((fold['name'], role, month))
            frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            fingerprint = (fold['order_id_fingerprints']['validation_full_by_month'][month]
                           if role == 'validation' else fold['order_id_fingerprints']['evaluation'])
            if frame.empty or order_fingerprint(frame) != fingerprint:
                raise ValueError('Frozen full scoring identities changed')
            part = ledger.loc[ledger.fold.eq(fold['name']) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            known, scores, context = verify_phase_ledger(frame, part, fold['schedule']['evaluation_start'], role,
                                                       fold['experiment']['models'], month)
            diagnostic = diagnose_phase(frame, scores, known)
            expected = prior_diagnostics['phases'][key]
            if (context != expected['context'] or any(diagnostic['summary'][field] != expected['handover_features']['summary'][field]
                                                     for field in COUNT_FIELDS)):
                raise ValueError('Prior diagnostic counts or verified source metrics changed')
            report['phases'][key] = {'fold': fold['name'], 'month': month, 'ledger_role': role,
                'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                'order_id_fingerprint': fingerprint, 'context': context, **diagnostic}
            report['phase_summary'].append({'phase': key, 'fold': fold['name'], 'month': month,
                'role': report['phases'][key]['role'], **diagnostic['summary']})
            verified_rows += len(part)
            focus = {row['mask']: row for row in diagnostic['focus_masks']}
            print(f'{key}: netTP={diagnostic["summary"]["net_TP"]}, sparse={focus["history_lt5"]["net_TP"]}, triple={focus["triple"]["net_TP"]}', flush=True)
    if (len(expected_phases) != 12 or verified_rows != len(ledger)
            or set(zip(ledger.fold, ledger.role, ledger.model_version, strict=True)) != expected_phases):
        raise ValueError('Unexpected or missing ledger phases')
    check_sources()
    report['source_hashes'] = [{'path': relative(path), 'sha256': expected} for path, expected in files.items()]
    report['verification'] = {'scoring_phases_verified': 12, 'candidate_metric_groups_verified': 24,
        'score_rows_verified': verified_rows, 'monthly_model_hashes_checked': 16, 'selected_artifact_hashes_checked': 3,
        'source_and_model_hashes_checked': len(files), 'source_hashes_checked_before_and_after': True,
        'source_contract_and_previous_76_candidate_metrics_unchanged': True,
        'prior_diagnostic_summary_and_context_exactly_reconciled': True,
        'intersection_cells_per_phase': 12, 'focus_masks_per_phase': 8,
        'all_original_daily_budgets_and_availability_masks_reproduced': True,
        'overlapping_marginals_not_added_as_disjoint_cells': True,
        'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0, 'new_model_selection': False,
        'original_holdout_not_rescored': True}
    return report


def validate_output(output, source, previous_diagnostics):
    output = Path(output).resolve()
    if output in {Path(source).resolve(), Path(previous_diagnostics).resolve()} or output.suffix.lower() != '.json':
        raise ValueError('Require a separate aggregate JSON output')
    if output.exists():
        try:
            own = json.loads(output.read_text(encoding='utf-8'))
            valid = own.get('analysis') == ANALYSIS and own.get('format_version') == 1
        except (OSError, ValueError, AttributeError):
            valid = False
        if not valid:
            raise ValueError('Refusing to overwrite another report')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/handover_history.json')
    parser.add_argument('--previous-diagnostics', type=Path, default=ROOT / 'reports/stage4/handover_history_diagnostics.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/handover_sparse_diagnostics.json')
    args = parser.parse_args(argv)
    try:
        output = validate_output(args.output, args.source_report, args.previous_diagnostics)
    except ValueError as exc:
        parser.error(str(exc))
    report = build_report(args.source_report, args.data_dir, args.previous_diagnostics)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(f'Wrote {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
