"""Describe frozen route/promise/age overlaps and complete-day alert exchanges.

Only existing score ledgers are ranked. Models are hashed, never loaded,
fitted, replayed or selected. Every mask follows the complete daily ranking.
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

from scripts import diagnose_unobserved_handover_age as previous
from scripts.compare_multimonth_validation import order_fingerprint
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_route_exchanges import COUNT_FIELDS, _allocation, _row_counts, analyze_route_exchanges
from scripts.diagnose_budget_misses import PROMISE_BINS, RANK_BINS, daily_rank_bins
from scripts.diagnose_objective_misses import promise_bins
from scripts.diagnose_rank_batch_size import _assert_partition, _day_info, _known_labels, _positions, _rank_summary
from scripts.improve_budget_ranking import relative, sha256

BASELINE, NEW = previous.MATCHED
MATCHED = previous.MATCHED
FEATURE = previous.FEATURE
ANALYSIS = 'frozen_age_route_promise_intersection_diagnostics'
SOURCE_SHA256 = '55ff0a08839f587141ec3e7fb285027ff5ea6d60abb7537050726fd349f0f385'
DIAGNOSTIC_SHA256 = '9b46bb1189aa137a3b1c9750634fc59d1fbc81bb74685dc436e5d9276cb91ce2'
SPECIFICATION_SHA256 = 'c927dd5032072157539ac13396752c68015bd300f724bd929f442aa0096e01bc'
CELLS = tuple(f'{index:03b}' for index in range(8))
GROUPS = ('ALL', 'R', 'P', 'A', 'RP', 'RA', 'PA', 'RPA')
OUTCOMES = ('known_delayed', 'known_on_time', 'unknown')
GAP_BINS = ('inside_budget', 'one_to_three', 'four_to_ten', 'eleven_plus')
COHORT_FIELDS = ('both_caught_delays', 'both_missed_delays', 'recovered_delays', 'lost_delays')
TARGET_PHASE = '2018-02/2018-02/evaluation'


def group_masks(frame):
    """R/P/A are fixed masks, never a learned threshold or a new quota."""
    required = {'state_route', 'estimated_delivery_days', FEATURE}
    if not required.issubset(frame):
        raise ValueError('Require route, promise and age columns')
    observed_routes = frame.state_route.dropna()
    if not observed_routes.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise ValueError('Routes must be nonempty strings or missing')
    age = previous.age_bins(frame)
    masks = {'R': frame.state_route.fillna('unknown').eq('SP->RJ').to_numpy(),
             'P': promise_bins(frame).eq('22-30').to_numpy(),
             'A': age == 'over24_to72h'}
    cells = np.array([''.join('1' if masks[name][i] else '0' for name in 'RPA')
                      for i in range(len(frame))], dtype=object)
    result = {'ALL': np.ones(len(frame), bool), **masks}
    result.update({name: np.logical_and.reduce([masks[bit] for bit in name])
                   for name in ('RP', 'RA', 'PA', 'RPA')})
    return cells, result


def _numeric_summary(values):
    return {'minimum': int(values.min()) if len(values) else None,
            'median': float(np.median(values)) if len(values) else None,
            'maximum': int(values.max()) if len(values) else None}


def _rank_capacity(mask, positions, ranks, capacity):
    result = _rank_summary(mask, positions[BASELINE], positions[NEW], ranks[BASELINE], ranks[NEW])
    result['capacity_gap_definition'] = 'one-based full-day position minus floor(0.1*full-day N); nonpositive means inside budget'
    for side, candidate in (('old', BASELINE), ('new', NEW)):
        gaps = positions[candidate] - capacity
        selected = gaps[mask]
        bins = {'inside_budget': int((selected <= 0).sum()),
                'one_to_three': int(((selected > 0) & (selected <= 3)).sum()),
                'four_to_ten': int(((selected > 3) & (selected <= 10)).sum()),
                'eleven_plus': int((selected > 10).sum())}
        if sum(bins.values()) != result['rows']:
            raise AssertionError('Capacity gaps do not partition the selected cohort')
        result[f'{side}_capacity_gap'] = {**_numeric_summary(selected), 'bins': bins}
    return result


def _counts_row(mask, known, labels, old, new, positions, ranks, capacity, *, with_ranks=True):
    row = _row_counts(np.flatnonzero(mask), known, labels, old, new)
    positive = known & (labels == 1)
    cohort_masks = {'known_delayed': positive,
                    'both_caught_delays': positive & old & new,
                    'both_missed_delays': positive & ~old & ~new,
                    'recovered_delays': positive & ~old & new,
                    'lost_delays': positive & old & ~new}
    row.update({name: int((mask & cohort_masks[name]).sum()) for name in COHORT_FIELDS})
    row['known_delayed_rows'] = row['positive_rows']
    row['known_on_time_rows'] = row['known_rows'] - row['positive_rows']
    row['known_delay_rate'] = row['positive_rows'] / row['known_rows'] if row['known_rows'] else None
    row['both_missed_fraction_of_delays'] = row['both_missed_delays'] / row['positive_rows'] if row['positive_rows'] else None
    row['small_sample'] = not row['minimum_sample_met']
    if sum(row[name] for name in COHORT_FIELDS) != row['positive_rows']:
        raise AssertionError('Caught/missed/exchanged delayed cohorts do not partition delays')
    if with_ranks:
        row['rank_capacity'] = {name: _rank_capacity(mask & support, positions, ranks, capacity)
                                for name, support in cohort_masks.items()}
    return row


def _changes(mask, groups, known, labels, old, new):
    """Each dimension partitions selected complete days, with explicit unknowns."""
    outcomes = {'known_delayed': known & (labels == 1),
                'known_on_time': known & (labels == 0), 'unknown': ~known}
    added, dropped = ~old & new, old & ~new
    result = []
    for name, support in groups:
        selected = mask & support
        by_outcome = {outcome: {'added': int((selected & outcome_mask & added).sum()),
                                'dropped': int((selected & outcome_mask & dropped).sum())}
                      for outcome, outcome_mask in outcomes.items()}
        result.append({'group': name, 'full_batch_rows': int(selected.sum()),
                       'added': int((selected & added).sum()), 'dropped': int((selected & dropped).sum()),
                       'outcomes': by_outcome})
    if sum(row['added'] for row in result) != int((mask & added).sum()) or sum(row['dropped'] for row in result) != int((mask & dropped).sum()):
        raise AssertionError('Change marginals do not partition complete selected days')
    for row in result:
        if sum(row['outcomes'][name]['added'] for name in OUTCOMES) != row['added'] or sum(row['outcomes'][name]['dropped'] for name in OUTCOMES) != row['dropped']:
            raise AssertionError('Known/unknown change outcomes do not partition')
    return result


def _focus_lost_days(frame, groups, cells, known, labels, old, new, positions, ranks, capacity, days):
    positive_lost = known & (labels == 1) & old & ~new
    focus_days = {name: sorted(set(days[positive_lost & groups[name]])) for name in 'RPA'}
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    promises, ages = promise_bins(frame).to_numpy(), previous.age_bins(frame)

    def changes_for(mask):
        actual_routes = sorted(set(routes[mask]))
        return {'cells': _changes(mask, [(c, cells == c) for c in CELLS], known, labels, old, new),
                'routes': _changes(mask, [(c, routes == c) for c in actual_routes], known, labels, old, new),
                'promise_days': _changes(mask, [(c, promises == c) for c in PROMISE_BINS], known, labels, old, new),
                'age_bins': _changes(mask, [(c, ages == c) for c in previous.AGE_BINS], known, labels, old, new)}

    union_days = sorted(set().union(*map(set, focus_days.values())))
    day_rows = []
    for day in union_days:
        mask = days == day
        day_rows.append({'day': day,
            'focus_lost_delays': {name: int((positive_lost & groups[name] & mask).sum()) for name in 'RPA'},
            'whole_day_counts': _counts_row(mask, known, labels, old, new, positions, ranks, capacity, with_ranks=False),
            'whole_day_changes': changes_for(mask)})
    by_focus = {}
    for name, selected_days in focus_days.items():
        mask = np.isin(days, selected_days)
        by_focus[name] = {'focus_lost_delays': int((positive_lost & groups[name]).sum()),
                          'day_count': len(selected_days), 'days': selected_days,
                          'whole_selected_days_counts': _counts_row(mask, known, labels, old, new, positions, ranks, capacity, with_ranks=False),
                          'whole_selected_days_changes': changes_for(mask)}
    union_mask = np.isin(days, union_days)
    cell_lost_days = {cell: sorted(set(days[positive_lost & (cells == cell)])) for cell in CELLS}
    return {'by_focus': by_focus,
            'by_cell_lost_days': {cell: {'days': selected_days, 'day_count': len(selected_days),
                'lost_delays': int((positive_lost & (cells == cell)).sum())} for cell, selected_days in cell_lost_days.items()},
            'union_day_count': len(union_days), 'union_days': day_rows,
            'whole_union_days_counts': _counts_row(union_mask, known, labels, old, new, positions, ranks, capacity, with_ranks=False),
            'whole_union_days_changes': changes_for(union_mask),
            'interpretation': 'Whole closed days containing at least one known newly lost delay in each focus. Focus-day sets overlap; changes are marginal counts, never individual donor/recipient pairs.'}


def diagnose_phase(frame, scores, known, *, include_focus_days=True):
    if frame.empty or set(scores) != set(MATCHED):
        raise ValueError('Require a nonempty complete phase with both fixed models')
    known, labels = _known_labels(frame, known)
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED}
    old, new = (alerts[c] for c in MATCHED)
    positions = {c: _positions(frame, scores[c]) for c in MATCHED}
    ranks = {c: daily_rank_bins(frame, scores[c]) for c in MATCHED}
    days, sizes = _day_info(frame)
    capacity = np.asarray([sizes[day] // 10 for day in days])
    if any(not np.array_equal(alerts[c], positions[c] <= capacity) for c in MATCHED):
        raise AssertionError('Daily rank/capacity mismatch')
    cells, groups = group_masks(frame)

    def row(mask):
        return _counts_row(mask, known, labels, old, new, positions, ranks, capacity)

    cell_rows = [{'cell': cell, 'bits': dict(zip('RPA', (bit == '1' for bit in cell), strict=True)),
                  **row(cells == cell)} for cell in CELLS]
    ages = previous.age_bins(frame)
    for cell_row in cell_rows:
        mask = cells == cell_row['cell']
        cell_row['finer_age_bins'] = [{'age_bin': name, **row(mask & (ages == name))} for name in previous.AGE_BINS]
        _assert_partition(cell_row['finer_age_bins'], cell_row,
                          (*COUNT_FIELDS, 'both_caught_delays', 'both_missed_delays'))
    marginals = {name: row(mask) for name, mask in groups.items()}
    _assert_partition(cell_rows, marginals['ALL'], (*COUNT_FIELDS, 'known_delayed_rows', 'both_caught_delays', 'both_missed_delays'))
    for name in GROUPS[1:]:
        matching = [r for r in cell_rows if all(r['bits'][bit] for bit in name)]
        _assert_partition(matching, marginals[name], (*COUNT_FIELDS, 'both_caught_delays', 'both_missed_delays'))
    # Reuse the shared daily allocation implementation with disjoint cells as
    # grouping labels. Its monthly allocation totals sum daily gross flows.
    allocations = analyze_route_exchanges(frame.assign(state_route=cells), scores[BASELINE], scores[NEW], known)
    day_lookup = {(r['day'], r['state_route']): r for r in allocations['route_day_allocations']}
    day_cells = []
    for day in sizes:
        day_mask = days == day
        for cell in CELLS:
            mask = day_mask & (cells == cell)
            counts = _row_counts(np.flatnonzero(mask), known, labels, old, new)
            allocated = _allocation(counts)
            expected = day_lookup.get((day, cell))
            if expected is not None and any(expected[k] != value for k, value in {**counts, **allocated}.items()):
                raise AssertionError('Daily cell ledger differs from shared allocation')
            day_cells.append({'day': day, 'cell': cell, **counts,
                'within_cell_exchanges': allocated['within_route_exchanges'],
                'cross_cell_outgoing_slots': allocated['cross_route_outgoing_slots'],
                'cross_cell_incoming_slots': allocated['cross_route_incoming_slots']})
    for day in sizes:
        rows = [r for r in day_cells if r['day'] == day]
        expected = next(r for r in allocations['days'] if r['day'] == day)
        _assert_partition(rows, expected, COUNT_FIELDS)
        if (sum(r['cross_cell_incoming_slots'] for r in rows) != sum(r['cross_cell_outgoing_slots'] for r in rows)
                or sum(r['within_cell_exchanges'] + r['cross_cell_incoming_slots'] for r in rows) != expected['added_alerts']):
            raise AssertionError('Full-day cross-cell flows do not conserve changed slots')
    cell_totals = []
    for cell in CELLS:
        rows = [r for r in day_cells if r['cell'] == cell]
        counts = _row_counts(np.flatnonzero(cells == cell), known, labels, old, new)
        _assert_partition(rows, counts, COUNT_FIELDS)
        cell_totals.append({'cell': cell, **counts, **{field: sum(r[field] for r in rows) for field in
            ('within_cell_exchanges', 'cross_cell_outgoing_slots', 'cross_cell_incoming_slots')}})
    lost = known & (labels == 1) & old & ~new
    union = groups['R'] | groups['P'] | groups['A']
    overlap = {'lost_delays_union_R_P_A': int((lost & union).sum()),
               'lost_delays_sum_R_P_A': sum(marginals[name]['lost_delays'] for name in 'RPA'),
               'lost_delays_triple_RPA': marginals['RPA']['lost_delays']}
    if overlap['lost_delays_union_R_P_A'] != sum(marginals[name]['lost_delays'] for name in 'RPA') - sum(marginals[name]['lost_delays'] for name in ('RP', 'RA', 'PA')) + marginals['RPA']['lost_delays']:
        raise AssertionError('Lost-delay inclusion/exclusion does not reconcile')
    result = {'cells': cell_rows, 'marginals': marginals, 'lost_overlap': overlap,
        'allocations': {'summary': {'within_cell_exchanges': allocations['allocation_summary']['within_route_exchanges'],
            'cross_cell_slots': allocations['allocation_summary']['cross_route_slots'],
            'capacity': allocations['allocation_summary']['capacity'], 'total_days': len(sizes),
            'changed_slots': marginals['ALL']['added_alerts']},
            'days': [{k: v for k, v in r.items() if k not in ('within_route_exchanges', 'cross_route_slots')}
                     | {'within_cell_exchanges': r['within_route_exchanges'], 'cross_cell_slots': r['cross_route_slots']}
                     for r in allocations['days']], 'day_cells': day_cells, 'cell_totals': cell_totals},
        'verification': {'eight_cells_partition_full_batch': True, 'intersections_match_cells': True,
            'daily_cell_allocations_conserved': True, 'rank_capacity_matches_full_day_alerts': True,
            'unknown_ranked_before_outcome_masks': True, 'no_subgroup_caps': True}}
    if include_focus_days:
        result['focus_lost_days'] = _focus_lost_days(frame, groups, cells, known, labels, old, new, positions, ranks, capacity, days)
    return result


def verify_preceding_marginals(frame, scores, known, preceding):
    route = analyze_route_exchanges(frame, scores[BASELINE], scores[NEW], known)
    promises = promise_bins(frame)
    grouped = analyze_route_exchanges(frame.assign(state_route=promises), scores[BASELINE], scores[NEW], known)
    promise_rows = [{('promise_bin' if k == 'state_route' else k): v for k, v in row.items()} for row in grouped['routes']]
    known, labels = _known_labels(frame, known)
    old, new = (apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED)
    ages = previous.age_bins(frame)
    age_rows = [{'age_bin': name, **_row_counts(np.flatnonzero(ages == name), known, labels, old, new)} for name in previous.AGE_BINS]
    expected = preceding['pending_age_features']
    actual = {'summary': route['summary'], 'routes': route['routes'], 'promise_days': promise_rows,
              'pending_age_bins': age_rows}
    if any(actual[name] != expected[name] for name in actual):
        raise ValueError('Earlier route, promise, age or overall marginal changed')
    return actual


def bound_json(path, expected):
    if sha256(path) != expected:
        raise ValueError(f'Frozen source SHA changed: {path}')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def build_report(source_path, diagnostic_path, specification_path, data_dir):
    source = bound_json(source_path, SOURCE_SHA256)
    preceding = bound_json(diagnostic_path, DIAGNOSTIC_SHA256)
    specification = bound_json(specification_path, SPECIFICATION_SHA256)
    if (source['status'] != 'ok' or source['experiment'] != 'unobserved_handover_age_ablation'
            or source['matched_candidate_order'] != list(MATCHED)
            or source['specification_sha256'] != SPECIFICATION_SHA256
            or any(source.get(k) != value for k, value in specification.items())
            or preceding['source_report']['sha256'] != SOURCE_SHA256):
        raise ValueError('Require the completed fixed age experiment and its matching diagnostic')
    files = {Path(source_path): SOURCE_SHA256, Path(diagnostic_path): DIAGNOSTIC_SHA256,
             Path(specification_path): SPECIFICATION_SHA256}

    def protect(info):
        path = ROOT / info['path']
        if sha256(path) != info['sha256']:
            raise ValueError(f'Frozen artifact changed: {path}')
        files[path] = info['sha256']
        return path

    model_paths = set()
    for month in source['monthly_training']:
        if set(month['models']) != set(MATCHED):
            raise ValueError('Changed fixed monthly model cohort')
        for info in month['models'].values():
            model_paths.add(protect(info['version_artifact']))
    for fold in source['folds']:
        protect(fold['research_artifact'])
    if len(model_paths) != 16 or len(source['folds']) != 3:
        raise ValueError('Require 16 monthly and three selected artifact hashes')
    for item in source['source_files']:
        protect({'path': relative(Path(data_dir) / item['filename']), 'sha256': item['sha256']})
    feature_path, ledger_path = protect(source['feature_dataset']), protect(source['score_export'])
    frame = pd.read_csv(feature_path, float_precision='round_trip', dtype={c: object for c in
        ('order_id', 'state_route', 'primary_seller_id', 'customer_zip_prefix3', 'primary_seller_zip_prefix3')})
    for name in ('prediction_time', 'label_available_time', 'order_purchase_timestamp', 'training_outcome_known_time'):
        frame[name] = pd.to_datetime(frame[name], errors='raise')
    if (len(frame) != 70844 or list(frame.columns) != source['feature_dataset']['columns']
            or frame.prediction_time.ge('2018-05-01').any() or frame.order_id.isna().any()
            or frame.order_id.duplicated().any()):
        raise ValueError('Changed frozen pre-May feature cohort')
    ledger = pd.read_csv(ledger_path, float_precision='round_trip', parse_dates=['prediction_time'])
    if len(ledger) != 128112 or len(ledger) != source['score_export']['rows']:
        raise ValueError('Changed frozen score ledger size')
    phases, summaries, verified_rows = {}, [], 0
    compact_fields = (*COUNT_FIELDS, 'both_caught_delays', 'both_missed_delays', 'known_delayed_rows', 'small_sample')
    for fold in source['folds']:
        for role, month in [*(('validation', m['month']) for m in fold['schedule']['validation_months']), ('evaluation', fold['name'])]:
            key = f'{fold["name"]}/{month}/{role}'
            batch = frame.loc[frame.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            expected_fingerprint = (fold['order_id_fingerprints']['validation_full_by_month'][month] if role == 'validation' else fold['order_id_fingerprints']['evaluation'])
            if order_fingerprint(batch) != expected_fingerprint:
                raise ValueError('Complete scoring identities changed')
            part = ledger.loc[ledger.fold.eq(fold['name']) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            known, scores, context = previous.verify_phase_ledger(batch, part, fold['schedule']['evaluation_start'], role, fold['experiment']['models'], month)
            before = preceding['phases'][key]
            if context != before['context']:
                raise ValueError('Prior verified context changed')
            result = diagnose_phase(batch, scores, known)
            result['preceding_marginals'] = verify_preceding_marginals(batch, scores, known, before)
            metadata = {'fold': fold['name'], 'month': month, 'role': before['role'],
                        'historical_outcome_cutoff': before['historical_outcome_cutoff']}
            phases[key] = {**metadata, 'context': context, **result}
            summaries.append({'phase': key, **metadata,
                'all': {field: result['marginals']['ALL'][field] for field in compact_fields},
                'groups': {name: {field: result['marginals'][name][field] for field in compact_fields} for name in GROUPS[1:]},
                **result['lost_overlap']})
            verified_rows += len(part)
            print(f'{key}: verified intersections and daily allocation', flush=True)
    if len(phases) != 12 or verified_rows != len(ledger):
        raise ValueError('Unexpected frozen phase coverage')
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError('Source changed during intersection diagnosis')
    return {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': SOURCE_SHA256},
        'source_hashes': [{'path': relative(path), 'sha256': value} for path, value in files.items()],
        'matched_candidate_order': list(MATCHED),
        'intersection_contract': {'bit_order': ['R', 'P', 'A'], 'cells': list(CELLS),
            'R': 'state_route == SP->RJ', 'P': 'original promise bin 22-30, meaning 21 < days <= 30',
            'A': '24 < pending age p90 hours <= 72', 'groups': list(GROUPS),
            'A_false': 'Includes missing/empty, age<=24 and age>72; not equivalent to long waiting.',
            'ranking': 'Original full closed day floor(0.1*N), score DESC / ID ASC before known-label masks.',
            'capacity_gap_bins': list(GAP_BINS), 'new_threshold_or_quota_search': False,
            'overlap': 'Eight cells partition rows; overlapping marginal counts cannot be added as independent orders.',
            'allocation': 'Within each day/cell min(dropped,added), outgoing=max(dropped-added,0), incoming=max(added-dropped,0); monthly totals sum daily gross, never individual order pairing.'},
        'phases': phases, 'phase_summary': summaries,
        'focus_context': {'target_phase': TARGET_PHASE,
            'target': next(row for row in summaries if row['phase'] == TARGET_PHASE),
            'earlier_contexts': [row for row in summaries if row['month'] < '2018-02'],
            'later_development_contexts': [row for row in summaries if row['role'] == 'development_retest' and row['month'] > '2018-02'],
            'interpretation': 'All twelve phases retained; repeated validation months keep their own historical cutoffs and are not pooled as independent evidence.'},
        'verification': {'phases_verified': 12, 'candidate_metric_groups_verified': 24,
            'score_rows_verified': verified_rows, 'monthly_model_hashes_checked': 16, 'selected_model_hashes_checked': 3,
            'models_deserialized': 0, 'new_fits': 0, 'new_saved_model_replays': 0, 'new_model_selection': False,
            'prior_route_promise_age_marginals_match': True, 'unknown_ranked_before_masks': True,
            'original_holdout_not_rescored': True},
        'limitations': ['Reused historical validation and development, never new unknown-test performance.',
            'This diagnoses overlaps and ranking exchanges; no feature causality or individual donor/recipient pairing.',
            'Small cells and no-delay groups retain denominators and None rates; no subgroup policy is selected.',
            'No count-plus-age fit, no threshold adjustment, no route/age quota or default-model change.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/unobserved_handover_age.json')
    parser.add_argument('--preceding-diagnostic', type=Path, default=ROOT / 'reports/stage4/unobserved_handover_age_diagnostics.json')
    parser.add_argument('--specification', type=Path, default=ROOT / 'reports/stage4/unobserved_handover_age_specification.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/age_intersection_diagnostics.json')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.suffix.lower() != '.json' or output in {p.resolve() for p in (args.source_report, args.preceding_diagnostic, args.specification)}:
        parser.error('Require a separate aggregate JSON output')
    report = build_report(args.source_report, args.preceding_diagnostic, args.specification, args.data_dir)
    serialized = json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if output.exists():
        if json.loads(output.read_text(encoding='utf-8')) != report:
            raise ValueError('Refusing to overwrite a different existing report')
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding='utf-8')
    print(json.dumps({'report': relative(output), 'phases': len(report['phases']), 'new_fits': 0}), flush=True)
    return report


if __name__ == '__main__':
    main()
