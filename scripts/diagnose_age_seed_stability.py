"""Describe paired fixed-seed rankers using only saved complete-day scores."""
from __future__ import annotations

SEEDS = (11, 29, 42, 73, 101)
BASELINE = 'xgboost_rank_backlog_7_14d_l2_100_topk_10'
AGE = 'xgboost_rank_unobserved_handover_age_p90_102_l2_100_topk_10'
CANDIDATES = (BASELINE, AGE)
FEATURE = 'seller_unobserved_handover_pending_age_p90_hours_90d'
CELLS = tuple(f'{index:03b}' for index in range(8))
GROUPS = ('ALL', 'R', 'P', 'A', 'RP', 'RA', 'PA', 'RPA')
AGE_BINS = ('missing_or_empty', 'up_to_24h', 'over24_to72h', 'over72_to168h', 'over168h')
TARGET_PHASE = '2018-02/2018-02/evaluation'


def diagnostic_contract():
    """Immutable pre-fit diagnostics; summaries never select a seed or model."""
    return {
        'format_version': 1, 'seeds': list(SEEDS), 'candidate_order': list(CANDIDATES),
        'ranking': 'Complete closed approval day; score descending then order_id ascending; floor(0.1*N), unknown outcomes compete before masks.',
        'historical_outcome': 'Actual delivery strictly before the original fold evaluation-start cutoff; evaluation rows are already inspected development retests.',
        'phase_scope': 'All 12 original phases per seed; repeated historical months remain separate. Only the three disjoint development months may be pooled within each seed.',
        'route_scope': 'All observed true state routes, missing route as unknown; no subgroup reranking or quotas.',
        'groups': {'R': 'state_route == SP->RJ', 'P': '21 < estimated_delivery_days <= 30',
                   'A': '24 < seller_unobserved_handover_pending_age_p90_hours_90d <= 72'},
        'cell_order': 'R,P,A; eight disjoint cells000..111; missing age has A=false, not necessarily the only reason.',
        'cells': list(CELLS), 'marginals': list(GROUPS), 'finer_age_scope': 'Cell110 in every seed and phase',
        'finer_age_bins': list(AGE_BINS), 'finer_age_boundaries_hours': [24, 72, 168],
        'per_seed_phase': ['Known/unknown and delayed denominators', 'Both model TP/FP/FN/recall/precision/alerts',
                           'Newly lost and recovered delays relative to the same-seed101',
                           'Every true route, eight RPA cells, overlapping RPA marginals and five finer110 age bins',
                           'Daily gross changed slots, within/cross true-route and RPA-cell exchanges; monthly totals sum daily flows',
                           'Newly lost delay full-day rank bins and capacity gaps1-3/4-10/11+'],
        'cross_seed_summary': {
            'statistics': ['mean', 'minimum', 'maximum'],
            'paired_direction_counts': ['negative', 'zero', 'positive', 'undefined'],
            'fields': ['TP', 'FP', 'FN', 'recall', 'precision', 'alerts', 'recovered_delays', 'lost_delays',
                       'added_alerts', 'dropped_alerts', 'within_route_exchanges', 'cross_route_slots',
                       'within_cell_exchanges', 'cross_cell_slots'],
            'pairing': 'Compute age102 minus101 inside each seed before summarizing; never subtract marginal extrema.',
            'denominators': 'Same phase/group identities, known masks and delayed denominators across all five seeds; average per-seed results, not five independent populations.',
            'undefined': 'Zero-denominator rates stay null; record defined/undefined seed counts, never replace by zero.',
        },
        'lost_identity_overlap': {
            'definition': 'Known delayed, same-seed101 alerted and same-seedage102 missed. Each seed has its own paired reference101.',
            'all_phases': 'ALL newly lost sets in each of12 phases',
            'february_focus': 'ALL/R/P/A/RP/RA/PA/RPA, every disjoint cell and each finer110 age bin',
            'summaries': ['Five seed counts', 'All ten unordered seed-pair intersection/union/Jaccard',
                          'All-five intersection and union', 'Multiplicity1..5 within lost union',
                          'Known delayed orders never newly lost by any seed'],
            'empty_union': 'Jaccard null when both pairwise sets are empty.',
            'privacy': 'Order identities used internally only; publish aggregate overlap counts, never order lists or identity hashes.',
        },
        'seed42_reference': 'Verify saved scores and complete-day alerts against the frozen original age experiment and preceding intersection counts.',
        'prohibitions': ['No fit, model deserialization, saved-model replay, calibration or selection in diagnosis',
                         'No best-seed choice, February-based model selection or new subgroup quota',
                         'No original holdout scoring; seed repeats on the same data are not independent test samples',
                         'No causal claim that sampling explains a regression'],
    }


import argparse
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import diagnose_age_intersections as intersections
from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_route_exchanges import COUNT_FIELDS, _row_counts, analyze_route_exchanges
from scripts.diagnose_budget_misses import daily_rank_bins
from scripts.diagnose_rank_batch_size import _day_info, _known_labels, _positions

ANALYSIS = 'paired_age_seed_stability_route_and_overlap_diagnostics'
SOURCE_SHA256 = '55ff0a08839f587141ec3e7fb285027ff5ea6d60abb7537050726fd349f0f385'
INTERSECTION_SHA256 = '96732787ffce4adb26b9dabd273cbc31390ecb79a57bec7089c6161a3d04ea30'
METRICS = {'TP': 'true_positives', 'FP': 'false_positives', 'FN': 'false_negatives',
           'recall': 'recall', 'precision': 'precision', 'alerts': 'alerts'}
EXCHANGES = ('recovered_delays', 'lost_delays', 'added_alerts', 'dropped_alerts',
             'within_route_exchanges', 'cross_route_slots', 'within_cell_exchanges', 'cross_cell_slots')
DENOMINATORS = ('full_batch_rows', 'known_rows', 'unknown_rows', 'positive_rows')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def numeric_summary(values, *, paired=False, unit='seed'):
    """Preserve undefined ratios and count paired signs before aggregation."""
    observed = np.asarray([float(v) for v in values if v is not None], dtype=float)
    if not np.isfinite(observed).all():
        raise ValueError('Summary values must be finite numbers or None')
    result = {'mean': float(observed.mean()) if len(observed) else None,
              'minimum': float(observed.min()) if len(observed) else None,
              'maximum': float(observed.max()) if len(observed) else None,
              f'defined_{unit}_count': len(observed), f'undefined_{unit}_count': len(values) - len(observed)}
    if paired:
        result['directions'] = {'negative': int((observed < 0).sum()), 'zero': int((observed == 0).sum()),
                                'positive': int((observed > 0).sum()), 'undefined': len(values) - len(observed)}
    return result


def summarize_group(rows_by_seed, *, seeds=SEEDS):
    """Pair inside a seed; fixed population is never multiplied by seed count."""
    if set(rows_by_seed) != set(seeds):
        raise ValueError('Require exactly the declared paired seeds')
    rows = [rows_by_seed[seed] for seed in seeds]
    denominators = {field: rows[0][field] for field in DENOMINATORS}
    if any(any(row[field] != denominators[field] for field in DENOMINATORS) for row in rows):
        raise ValueError('Cross-seed group denominators changed')
    by_candidate, delta = {}, {}
    for prefix, candidate in [('old', BASELINE), ('new', AGE)]:
        by_candidate[candidate] = {metric: numeric_summary([row[f'{prefix}_{field}'] for row in rows])
                                   for metric, field in METRICS.items()}
    for metric, field in METRICS.items():
        values = [None if row[f'old_{field}'] is None or row[f'new_{field}'] is None
                  else row[f'new_{field}'] - row[f'old_{field}'] for row in rows]
        delta[metric] = {**numeric_summary(values, paired=True),
                         'by_seed': {str(seed): value for seed, value in zip(seeds, values, strict=True)}}
    exchange_fields = [name for name in EXCHANGES if all(name in row for row in rows)]
    return {'denominators': denominators, 'seed_count': len(seeds), 'by_candidate': by_candidate,
            'paired_delta': delta,
            'exchanges': {name: numeric_summary([row[name] for row in rows]) for name in exchange_fields}}


def overlap_summary(lost_by_seed, known_delayed_ids, *, seeds=SEEDS):
    """Publish aggregate identity stability only; sets never leave this helper."""
    if set(lost_by_seed) != set(seeds):
        raise ValueError('Require exactly the declared seed sets')
    universe = set(known_delayed_ids)
    sets = {seed: set(lost_by_seed[seed]) for seed in seeds}
    if any(not ids.issubset(universe) for ids in sets.values()):
        raise ValueError('Lost identities must be known delayed members of this group')
    union = set().union(*sets.values())
    shared = set.intersection(*(sets[seed] for seed in seeds))
    multiplicity = {str(n): sum(sum(order in sets[seed] for seed in seeds) == n for order in union)
                    for n in range(1, len(seeds) + 1)}
    pairs = []
    for left, right in itertools.combinations(seeds, 2):
        intersection, combined = sets[left] & sets[right], sets[left] | sets[right]
        pairs.append({'left_seed': left, 'right_seed': right, 'left_rows': len(sets[left]),
                      'right_rows': len(sets[right]), 'intersection': len(intersection), 'union': len(combined),
                      'jaccard': len(intersection) / len(combined) if combined else None})
    if sum(multiplicity.values()) != len(union) or sum(int(n) * count for n, count in multiplicity.items()) != sum(map(len, sets.values())):
        raise AssertionError('Identity multiplicity does not reconcile')
    return {'known_delayed_rows': len(universe), 'by_seed': {str(seed): len(sets[seed]) for seed in seeds},
            'all_seed_intersection': len(shared), 'union': len(union), 'multiplicity': multiplicity,
            'never_newly_lost_by_any_seed': len(universe - union), 'pairwise': pairs,
            'pairwise_jaccard': numeric_summary([pair['jaccard'] for pair in pairs], unit='pair'),
            'definition': 'Newly lost relative to the reference101 with the same seed; identities are not published.'}


def _phase_diagnostics(frame, scores, known):
    if frame.empty or set(scores) != set(CANDIDATES):
        raise ValueError('Require both candidate scores on a nonempty complete phase')
    known, labels = _known_labels(frame, known)
    alerts = {candidate: apply_alert_policy(frame, scores[candidate], 0., .1, raw_scores=scores[candidate])
              for candidate in CANDIDATES}
    old, new = (alerts[candidate] for candidate in CANDIDATES)
    positions = {candidate: _positions(frame, scores[candidate]) for candidate in CANDIDATES}
    ranks = {candidate: daily_rank_bins(frame, scores[candidate]) for candidate in CANDIDATES}
    days, sizes = _day_info(frame)
    capacity = np.asarray([sizes[day] // 10 for day in days])
    if any(not np.array_equal(alerts[candidate], positions[candidate] <= capacity) for candidate in CANDIDATES):
        raise AssertionError('Complete-day capacity and alerts differ')
    lost = known & (labels == 1) & old & ~new
    cells, groups = intersections.group_masks(frame)
    ages = intersections.previous.age_bins(frame)
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()

    def row(mask):
        return {**_row_counts(np.flatnonzero(mask), known, labels, old, new),
                'lost_rank_capacity': intersections._rank_capacity(mask & lost, positions, ranks, capacity)}

    route_view = analyze_route_exchanges(frame, scores[BASELINE], scores[AGE], known)
    cell_view = analyze_route_exchanges(frame.assign(state_route=cells), scores[BASELINE], scores[AGE], known)
    actual_routes = [{**route, 'lost_rank_capacity': intersections._rank_capacity(
                         (routes == route['state_route']) & lost, positions, ranks, capacity)}
                     for route in route_view['routes']]
    allocated_cells = {record['state_route']: record for record in cell_view['routes']}
    cell_rows = []
    for cell in CELLS:
        allocation = allocated_cells.get(cell, {})
        cell_rows.append({'cell': cell, **row(cells == cell),
            'within_cell_exchanges': allocation.get('within_route_exchanges', 0),
            'cross_cell_incoming_slots': allocation.get('cross_route_incoming_slots', 0),
            'cross_cell_outgoing_slots': allocation.get('cross_route_outgoing_slots', 0)})
    fine = [{'age_bin': name, **row((cells == '110') & (ages == name))} for name in AGE_BINS]
    overall = row(np.ones(len(frame), bool))
    overall.update({'within_route_exchanges': route_view['allocation_summary']['within_route_exchanges'],
                    'cross_route_slots': route_view['allocation_summary']['cross_route_slots'],
                    'within_cell_exchanges': cell_view['allocation_summary']['within_route_exchanges'],
                    'cross_cell_slots': cell_view['allocation_summary']['cross_route_slots']})
    by_day_cells = {record['day']: record for record in cell_view['days']}
    day_rows = []
    for record in route_view['days']:
        cell_record = by_day_cells[record['day']]
        day_rows.append({**record, 'within_cell_exchanges': cell_record['within_route_exchanges'],
                         'cross_cell_slots': cell_record['cross_route_slots']})
    for records in (actual_routes, cell_rows, fine):
        expected = overall if records is not fine else next(record for record in cell_rows if record['cell'] == '110')
        for field in COUNT_FIELDS:
            if sum(record[field] for record in records) != expected[field]:
                raise AssertionError('Published groups do not partition their parent counts')
    for field in COUNT_FIELDS:
        if sum(record[field] for record in day_rows) != overall[field]:
            raise AssertionError('Complete days do not partition the phase')
    for within, cross in [('within_route_exchanges', 'cross_route_slots'), ('within_cell_exchanges', 'cross_cell_slots')]:
        if sum(record[within] for record in day_rows) != overall[within] or sum(record[cross] for record in day_rows) != overall[cross]:
            raise AssertionError('Daily gross flows changed when aggregated')
        if overall[within] + overall[cross] != overall['added_alerts']:
            raise AssertionError('Gross exchanges do not conserve full-day changed slots')
    focus_masks = {**groups, **{f'cell_{cell}': cells == cell for cell in CELLS},
                   **{f'cell110_age_{name}': (cells == '110') & (ages == name) for name in AGE_BINS}}
    ids = frame.order_id.to_numpy()
    internals = {'lost': {name: set(ids[lost & mask]) for name, mask in focus_masks.items()},
                 'delayed': {name: set(ids[known & (labels == 1) & mask]) for name, mask in focus_masks.items()}}
    return {'overall': overall, 'routes': actual_routes, 'rpa_marginals': {name: row(mask) for name, mask in groups.items()},
            'rpa_cells': cell_rows, 'cell110_age_bins': fine, 'days': day_rows,
            'daily_batch_count': len(sizes)}, internals


def diagnose_phase(frame, scores, known):
    """Public pure phase API; private identities are discarded before return."""
    return _phase_diagnostics(frame, scores, known)[0]


def verify_phase_ledger(frame, ledger, metadata, seed, expected):
    """Validate clocks, identities and source metrics without loading a model."""
    role, month, fold = metadata['ledger_role'], metadata['month'], metadata['fold']
    if role not in ('validation', 'evaluation') or set(ledger.candidate) != set(CANDIDATES) or len(ledger) != len(frame) * 2:
        raise ValueError('Require two complete scoring cohorts for this seed/phase')
    if (not ledger.seed.eq(seed).all() or not ledger.role.eq(role).all()
            or not ledger.model_version.eq(month).all() or not ledger.fold.eq(fold).all()):
        raise ValueError('Changed seed or phase metadata')
    known = (frame.label_available_time.lt(pd.Timestamp(metadata['historical_outcome_cutoff'])).to_numpy()
             if role == 'validation' else np.ones(len(frame), bool))
    known, labels = _known_labels(frame, known)
    scores, contexts = {}, {}
    for candidate in CANDIDATES:
        part = ledger.loc[ledger.candidate.eq(candidate)]
        if part.order_id.isna().any() or part.order_id.duplicated().any() or set(part.order_id) != set(frame.order_id):
            raise ValueError('Changed full scoring identities')
        part = part.set_index('order_id').loc[frame.order_id]
        if part.known_at_selection.dtype != bool:
            raise ValueError('Availability flags must be boolean')
        np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
        np.testing.assert_array_equal(part.known_at_selection.to_numpy(), known if role == 'validation' else np.zeros(len(frame), bool))
        np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
        np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], labels[known])
        values = part.delay_score.to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError('Invalid bounded ranking scores')
        alerts = apply_alert_policy(frame, values, 0., .1, raw_scores=values)
        if not part.predicted_delayed.isin([0, 1]).all():
            raise ValueError('Alerts must be binary')
        np.testing.assert_array_equal(alerts.astype(int), part.predicted_delayed.to_numpy())
        context = {'known_outcome_metrics': alert_metrics(labels[known], values[known], alerts[known]),
                   'full_batch': batch_audit(frame, alerts, .1, known)}
        if context != expected[candidate]:
            raise ValueError('Source metrics or complete-day budget changed')
        scores[candidate], contexts[candidate] = values, context
    return known, scores, contexts


def _pool_counts(rows):
    result = {field: sum(row.get(field, 0) for row in rows) for field in COUNT_FIELDS}
    for side in ('old', 'new'):
        tp, positives = result[f'{side}_true_positives'], result['positive_rows']
        result[f'{side}_recall'] = tp / positives if positives else None
        alerts = result[f'{side}_known_alerts']
        result[f'{side}_precision'] = tp / alerts if alerts else None
    for field in EXCHANGES[4:]:
        if any(field in row for row in rows):
            result[field] = sum(row.get(field, 0) for row in rows)
    return result


def summarize_phases(by_seed, *, seeds=SEEDS):
    """Summaries retain every actual route and all predeclared empty cells."""
    if set(by_seed) != set(seeds):
        raise ValueError('Require all paired seeds')
    routes = [{row['state_route'] for row in by_seed[seed]['routes']} for seed in seeds]
    if any(route_set != routes[0] for route_set in routes[1:]):
        raise ValueError('Actual route support changed across seeds')
    return {
        'overall': summarize_group({seed: by_seed[seed]['overall'] for seed in seeds}, seeds=seeds),
        'routes': [{'state_route': route, **summarize_group({seed: next(row for row in by_seed[seed]['routes']
                    if row['state_route'] == route) for seed in seeds}, seeds=seeds)} for route in sorted(routes[0])],
        'rpa_marginals': {name: summarize_group({seed: by_seed[seed]['rpa_marginals'][name] for seed in seeds}, seeds=seeds) for name in GROUPS},
        'rpa_cells': [{'cell': cell, **summarize_group({seed: next(row for row in by_seed[seed]['rpa_cells']
                    if row['cell'] == cell) for seed in seeds}, seeds=seeds)} for cell in CELLS],
        'cell110_age_bins': [{'age_bin': name, **summarize_group({seed: next(row for row in by_seed[seed]['cell110_age_bins']
                    if row['age_bin'] == name) for seed in seeds}, seeds=seeds)} for name in AGE_BINS],
    }


def development_pool(phases_by_seed, evaluation_keys, *, seeds=SEEDS):
    if len(evaluation_keys) != 3 or len(set(evaluation_keys)) != 3 or any(not key.endswith('/evaluation') for key in evaluation_keys):
        raise ValueError('Only the three disjoint development phases may be pooled')
    pool = {}
    for seed in seeds:
        parts = [phases_by_seed[seed][key] for key in evaluation_keys]
        routes = sorted(set().union(*({row['state_route'] for row in part['routes']} for part in parts)))
        pool[seed] = {
            'overall': _pool_counts([part['overall'] for part in parts]),
            'routes': [{'state_route': route, **_pool_counts([row for part in parts for row in part['routes'] if row['state_route'] == route])} for route in routes],
            'rpa_marginals': {name: _pool_counts([part['rpa_marginals'][name] for part in parts]) for name in GROUPS},
            'rpa_cells': [{'cell': cell, **_pool_counts([next(row for row in part['rpa_cells'] if row['cell'] == cell) for part in parts])} for cell in CELLS],
            'cell110_age_bins': [{'age_bin': name, **_pool_counts([next(row for row in part['cell110_age_bins'] if row['age_bin'] == name) for part in parts])} for name in AGE_BINS],
        }
    return {'development_phases': evaluation_keys, 'by_seed': {str(seed): pool[seed] for seed in seeds},
            'cross_seed': summarize_phases(pool, seeds=seeds),
            'interpretation': 'Disjoint development months are pooled inside each seed; five repetitions do not create five independent populations.'}


def verify_seed42_reference(actual, prior_phase):
    """Seed42 retains every old RPA count and newly lost rank distribution."""
    compared = 0
    prior_cells = {row['cell']: row for row in prior_phase['cells']}
    groups = [(actual['rpa_marginals'][name], prior_phase['marginals'][name]) for name in GROUPS]
    groups.extend((row, prior_cells[row['cell']]) for row in actual['rpa_cells'])
    old_fine = {row['age_bin']: row for row in prior_cells['110']['finer_age_bins']}
    groups.extend((row, old_fine[row['age_bin']]) for row in actual['cell110_age_bins'])
    for row, prior in groups:
        for field in COUNT_FIELDS:
            if row[field] != prior[field]:
                raise ValueError(f'Seed42 frozen intersection changed: {field}')
            compared += 1
        if row['lost_rank_capacity'] != prior['rank_capacity']['lost_delays']:
            raise ValueError('Seed42 frozen lost-rank/capacity distribution changed')
    return compared


def build_report(source_path, data_dir):
    source_path = Path(source_path).resolve()
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if (source.get('status') != 'ok' or source.get('seeds') != list(SEEDS)
            or source.get('matched_candidate_order') != list(CANDIDATES)
            or source.get('diagnostic_contract') != diagnostic_contract()
            or source.get('diagnostic_contract_sha256') != canonical_sha256(diagnostic_contract())):
        raise ValueError('Require the completed prespecified five paired seeds')
    files = {source_path: sha256(source_path)}

    def protect(info):
        path = (ROOT / info['path']).resolve()
        if sha256(path) != info['sha256']:
            raise ValueError(f'Changed frozen source: {path}')
        files[path] = info['sha256']
        return path

    prior_path = protect(source['source_report'])
    if files[prior_path] != SOURCE_SHA256:
        raise ValueError('Require the original fixed seed42 age experiment')
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    spec_path = source_path.with_name('age_seed_stability_specification.json')
    specification = json.loads(spec_path.read_text(encoding='utf-8'))
    if sha256(spec_path) != source['specification_sha256'] or any(source.get(key) != value for key, value in specification.items()):
        raise ValueError('Pre-fit specification changed')
    files[spec_path] = source['specification_sha256']
    intersection_path = ROOT / 'reports/stage4/age_intersection_diagnostics.json'
    if sha256(intersection_path) != INTERSECTION_SHA256:
        raise ValueError('Frozen seed42 intersection reference changed')
    files[intersection_path] = INTERSECTION_SHA256
    preceding = json.loads(intersection_path.read_text(encoding='utf-8'))
    for fold in prior['folds']:
        protect(fold['research_artifact'])
    feature_path = protect(source['feature_dataset'])
    if source['feature_dataset']['sha256'] != prior['feature_dataset']['sha256']:
        raise ValueError('Original age feature cache changed')
    ledger_path = protect(source['score_export'])
    old_ledger_path = protect(prior['score_export'])
    models, month_seeds = set(), set()
    for monthly in source['monthly_training']:
        pair = (monthly['month'], monthly['seed'])
        if pair in month_seeds or monthly['seed'] not in SEEDS or set(monthly['models']) != set(CANDIDATES):
            raise ValueError('Monthly paired seed cohort changed')
        month_seeds.add(pair)
        for model in monthly['models'].values():
            models.add(protect(model['version_artifact']))
    expected_months = {monthly['month'] for monthly in prior['monthly_training']}
    if month_seeds != set(itertools.product(expected_months, SEEDS)) or len(models) != 80:
        raise ValueError('Require all80 fitted paired monthly artifacts for hash checks')
    for entry in prior['source_files']:
        protect({'path': (Path(data_dir) / entry['filename']).resolve().relative_to(ROOT).as_posix(), 'sha256': entry['sha256']})
    frame = pd.read_csv(feature_path, float_precision='round_trip', dtype={name: object for name in
        ('order_id', 'state_route', 'primary_seller_id', 'customer_zip_prefix3', 'primary_seller_zip_prefix3')})
    for name in ('prediction_time', 'label_available_time'):
        frame[name] = pd.to_datetime(frame[name], errors='raise')
    if frame.shape != (70844, 138) or frame.prediction_time.ge('2018-05-01').any() or frame.order_id.isna().any() or frame.order_id.duplicated().any():
        raise ValueError('Changed frozen pre-May age-feature population')
    ledger = pd.read_csv(ledger_path, float_precision='round_trip', parse_dates=['prediction_time'])
    if (len(ledger) != 640560 or len(ledger) != source['score_export']['rows'] or set(ledger.seed) != set(SEEDS)
            or ledger.duplicated(['seed', 'fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Changed640560-row complete paired-seed ledger')
    old_ledger = pd.read_csv(old_ledger_path, float_precision='round_trip', parse_dates=['prediction_time'])
    phase_plans = source['phase_metrics']
    expected_plans = {}
    for fold in prior['folds']:
        for role, month in [*(('validation', record['month']) for record in fold['schedule']['validation_months']), ('evaluation', fold['name'])]:
            expected_plans[f'{fold["name"]}/{month}/{role}'] = {
                'fold': fold['name'], 'month': month, 'ledger_role': role,
                'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None}
    if len(phase_plans) != 12 or set(phase_plans) != set(expected_plans):
        raise ValueError('Require exactly the original12 phases')
    for key, expected in expected_plans.items():
        if any(phase_plans[key].get(field) != value for field, value in expected.items()):
            raise ValueError('Original phase role, population or historical outcome cutoff changed')
    phased, internal, rows_verified, seed42_fields = {seed: {} for seed in SEEDS}, {}, 0, 0
    for key, metadata in phase_plans.items():
        if key != f'{metadata["fold"]}/{metadata["month"]}/{metadata["ledger_role"]}':
            raise ValueError('Phase identity changed')
        batch = frame.loc[frame.prediction_time.dt.strftime('%Y-%m').eq(metadata['month'])].reset_index(drop=True)
        internal[key] = {}
        for seed in SEEDS:
            part = ledger.loc[ledger.seed.eq(seed) & ledger.fold.eq(metadata['fold'])
                              & ledger.model_version.eq(metadata['month']) & ledger.role.eq(metadata['ledger_role'])]
            known, scores, contexts = verify_phase_ledger(batch, part, metadata, seed, metadata['by_seed'][str(seed)])
            diagnostic, identity_sets = _phase_diagnostics(batch, scores, known)
            phased[seed][key] = {'fold': metadata['fold'], 'month': metadata['month'], 'role': metadata['role'],
                                'historical_outcome_cutoff': metadata['historical_outcome_cutoff'], 'context': contexts, **diagnostic}
            internal[key][seed] = identity_sets
            rows_verified += len(part)
            if seed == 42:
                for candidate in CANDIDATES:
                    before = old_ledger.loc[old_ledger.fold.eq(metadata['fold']) & old_ledger.role.eq(metadata['ledger_role'])
                        & old_ledger.model_version.eq(metadata['month']) & old_ledger.candidate.eq(candidate)]
                    if before.order_id.duplicated().any() or set(before.order_id) != set(batch.order_id):
                        raise ValueError('Frozen seed42 score identities changed')
                    before = before.set_index('order_id').loc[batch.order_id]
                    np.testing.assert_allclose(scores[candidate], before.delay_score.to_numpy(), rtol=0, atol=1e-12)
                seed42_fields += verify_seed42_reference(diagnostic, preceding['phases'][key])
    if rows_verified != len(ledger):
        raise ValueError('Scoring ledger contains unrecognized rows')
    summaries, overlaps = {}, {}
    for key, metadata in phase_plans.items():
        summaries[key] = {'fold': metadata['fold'], 'month': metadata['month'], 'role': metadata['role'],
                          'historical_outcome_cutoff': metadata['historical_outcome_cutoff'],
                          **summarize_phases({seed: phased[seed][key] for seed in SEEDS})}
        universes = [internal[key][seed]['delayed']['ALL'] for seed in SEEDS]
        if any(universe != universes[0] for universe in universes[1:]):
            raise ValueError('Known delayed identities changed across seeds')
        overlaps[key] = overlap_summary({seed: internal[key][seed]['lost']['ALL'] for seed in SEEDS}, universes[0])
    target_sets = internal[TARGET_PHASE]
    focus_overlap = {name: overlap_summary({seed: target_sets[seed]['lost'][name] for seed in SEEDS},
                    target_sets[SEEDS[0]]['delayed'][name]) for name in target_sets[SEEDS[0]]['lost']}
    evaluation_keys = [key for key, metadata in phase_plans.items() if metadata['ledger_role'] == 'evaluation']
    pooled = development_pool(phased, evaluation_keys)
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError('Source changed during seed diagnosis')
    return {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': source_path.relative_to(ROOT).as_posix(), 'sha256': files[source_path]},
        'source_hashes': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest} for path, digest in files.items()],
        'diagnostic_contract': diagnostic_contract(), 'diagnostic_contract_sha256': canonical_sha256(diagnostic_contract()),
        'seeds': list(SEEDS), 'matched_candidate_order': list(CANDIDATES),
        'seed_phases': {str(seed): phased[seed] for seed in SEEDS}, 'cross_seed_phases': summaries,
        'development_pool': pooled, 'newly_lost_identity_overlap': overlaps,
        'february_focus_identity_overlap': focus_overlap,
        'verification': {'seed_count': 5, 'phases_per_seed': 12, 'seed_phase_groups_verified': 60,
            'candidate_metric_groups_verified': 120, 'score_rows_verified': rows_verified,
            'monthly_artifact_hashes_checked': len(models), 'primary_artifact_hashes_checked': len(prior['folds']),
            'seed42_prior_score_rows_verified': len(old_ledger),
            'seed42_prior_count_fields_verified': seed42_fields, 'models_deserialized': 0, 'new_fits': 0,
            'saved_models_replayed': 0, 'new_selection': False, 'unknown_ranked_before_masks': True,
            'original_holdout_not_rescored': True, 'private_order_identities_exported': False},
        'limitations': ['All results reuse the same inspected historical/development data; seed repetitions are not independent samples.',
            'Every delta is paired within its seed; no best seed or February-based model selection is performed.',
            'Route/RPA/age summaries overlap and share a complete-day budget, never separate quotas.',
            'Newly lost sets are relative to each seed own101 reference, not the seed42 baseline for every run.',
            'Daily gross flows count exchanges, never causal donor/recipient order pairs; sampling causality is not established.',
            'The existing80-candidate primary, original RF and original holdout remain unchanged.']}


def fixed_json(path, payload):
    """Create once; identical rechecks leave bytes intact, changes require a new path."""
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != payload:
            raise ValueError(f'Refusing to overwrite a different frozen diagnostic: {path}')
        return False
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/age_seed_stability.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/age_seed_stability_diagnostics.json')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == args.source_report.resolve() or output.suffix.lower() != '.json':
        parser.error('Require a separate aggregate JSON output')
    report = build_report(args.source_report, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    created = fixed_json(output, report)
    print(json.dumps({'report': output.relative_to(ROOT).as_posix(), 'bytes': output.stat().st_size,
                      'seed_phases': 60, 'created': created, 'new_fits': 0, 'new_replays': 0}), flush=True)
    return report


if __name__ == '__main__':
    main()
