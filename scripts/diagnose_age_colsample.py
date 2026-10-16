"""Audit four prespecified colsample contrasts using saved complete-day scores."""
from __future__ import annotations

SEEDS = (11, 29, 42, 73, 101)
BASELINE = 'xgboost_rank_backlog_7_14d_l2_100_topk_10'
AGE = 'xgboost_rank_unobserved_handover_age_p90_102_l2_100_topk_10'
CANDIDATES = (BASELINE, AGE)
VERSIONS = ('base08', 'age08', 'base10', 'age10')
VERSION_SOURCE = {'base08': ('0.8', BASELINE), 'age08': ('0.8', AGE),
                  'base10': ('1.0', BASELINE), 'age10': ('1.0', AGE)}
CONTRASTS = {'age_minus_base_at_08': ('base08', 'age08'),
             'age_minus_base_at_10': ('base10', 'age10'),
             'base_10_minus_08': ('base08', 'base10'),
             'age_10_minus_08': ('age08', 'age10')}
METRICS = ('TP', 'FP', 'FN', 'known_alerts', 'unknown_alerts', 'alerts', 'recall', 'precision')
EXCHANGES = ('recovered_delays', 'lost_delays', 'added_alerts', 'dropped_alerts',
             'added_on_time_alerts', 'removed_on_time_alerts',
             'unknown_added_alerts', 'unknown_removed_alerts', 'stable_alerts')
ALLOCATIONS = ('within_group_exchanges', 'cross_group_outgoing_slots', 'cross_group_incoming_slots')
DENOMINATORS = ('full_batch_rows', 'known_rows', 'unknown_rows', 'positive_rows')
SUMMARY = ('mean', 'minimum', 'maximum', 'span', 'defined_seed_count', 'undefined_seed_count')
PAIRED_SUMMARY = SUMMARY + ('negative', 'zero', 'positive')
CELLS = tuple(f'{index:03b}' for index in range(8))
GROUPS = ('ALL', 'R', 'P', 'A', 'RP', 'RA', 'PA', 'RPA')
AGE_BINS = ('missing_or_empty', 'up_to_24h', 'over24_to72h', 'over72_to168h', 'over168h')
TARGET_PHASE = '2018-02/2018-02/evaluation'


def diagnostic_contract():
    """Pure pre-fit contract, shared with the immutable training specification."""
    return {
        'format_version': 1, 'seeds': list(SEEDS), 'candidate_order': list(CANDIDATES),
        'versions': list(VERSIONS),
        'version_source': {key: list(value) for key, value in VERSION_SOURCE.items()},
        'contrasts': {key: {'old': value[0], 'new': value[1]} for key, value in CONTRASTS.items()},
        'ranking': 'Complete closed approval day; score descending then order_id ascending; floor(0.1*N) before outcome/group masks. Unknown outcomes consume slots.',
        'historical_outcome': 'Actual delivery strictly before the original fold evaluation-start cutoff; evaluation months remain inspected development retests.',
        'phase_scope': 'All12 original phases at every seed and contrast; repeated historical months stay separate. Only the three disjoint development months may be pooled within a seed.',
        'groups': {'R': 'state_route == SP->RJ', 'P': '21 < estimated_delivery_days <= 30',
                   'A': '24 < seller_unobserved_handover_pending_age_p90_hours_90d <= 72'},
        'group_scope': 'ALL, every observed true route plus the fixed SP->SC focus even when empty, eight RPA marginals, eight disjoint R/P/A cells, five original age bins inside110; no subgroup reranking or quotas.',
        'cells': list(CELLS), 'finer110_age_bins': list(AGE_BINS), 'age_boundaries_hours': [24, 72, 168],
        'missing': 'Missing age has A=false, along with other finite ages outside(24,72]; missing/empty does not imply a particular cause. Undefined rates stay null.',
        'counts': 'Every group retains fixed known/unknown/delayed denominators, four model TP/FP/FN/known-alert/unknown-alert/total-alert/recall/precision, and all four contrast recovered/lost/on-time/unknown exchanges.',
        'gross': 'Within-group=min(dropped,added), outgoing=max(dropped-added,0), incoming=max(added-dropped,0), first per complete day then summed. Route and cell partitions separately conserve daily changed slots; no causal donor-recipient pairing.',
        'statistics': 'Pair new minus old inside each seed, then report mean/min/max/span and negative/zero/positive/undefined counts; never subtract marginal extrema or treat five repetitions as independent orders.',
        'model_stability': 'For each colsample and each feature package, retain all five-seed model metric mean/min/max/span, especially TP and recall; a narrower age-minus101 gap does not imply each model became less variable.',
        'gap_stability': 'For age-minus101 at each colsample, retain paired TP/recall span and direction counts. Report span(1.0)-span(0.8) descriptively; positive mean or consistent negative signs alone is not stable improvement.',
        'did': 'Inside each seed and fixed group compute[(age10-base10)-(age08-base08)] for every model metric, then mean/min/max/span/sign counts. Rates require the same known/delayed denominator; any undefined operand yields null.',
        'lost_sets': {'definition': 'Known delayed, alerted by that contrast own old version and missed by its own new version, at the same seed.',
            'all_phases': 'ALL overlap across five seeds for every phase and four contrasts.',
            'february_focus': 'ALL/R/P/A/RP/RA/PA/RPA, eight cells, five finer110 age bins, SP->SC route; all four contrasts.',
            'statistics': 'Five set sizes, all-five intersection/union, multiplicity1..5, all ten unordered seed-pair intersection/union/Jaccard; empty union Jaccard null.',
            'cross_colsample': 'Within each seed and February focus group compare newly-lost sets of age-minus101 at0.8 versus1.0; each keeps its own paired101 reference.',
            'privacy': 'Only aggregate identity overlap counts are public, never order lists or identity hashes.'},
        'compact_output': 'Public column definitions accompany numeric tables. Retain all groups and12 phases; omit individual order identities, daily detail and rank-transition matrices. Keep the aggregate JSON below50,000,000 bytes.',
        'frozen_reference': 'The0.8 score ledger, metrics, group counts and daily gross totals must reproduce the completed five-seed diagnostic before any1.0 result is summarized.',
        'prohibitions': ['No model deserialization, fit, saved-model replay, calibration or model/seed selection in diagnosis',
            'No best-seed choice, February-driven selection, subgroup quota or new original-holdout scoring',
            'Original80-candidate primary and default RF unchanged; same historical/development data are not independent tests',
            'colsample1.0 retains subsample0.8 and other randomness; no claim that sampling caused any prior loss']}


import argparse
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
from scripts import diagnose_age_seed_stability as previous
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.diagnose_rank_batch_size import _known_labels

SOURCE_SHA256 = '7b0a1e369307a718c3161d3a10045b8a9ecde385b9ab94bfe7c9c859262f11b8'
SOURCE_DIAGNOSTIC_SHA256 = '03c1e5630be52f5c1424032d539846398557e2a939f3e28c68d8b1df1012c5d6'
ANALYSIS = 'fixed_seed_four_contrast_colsample_diagnostics'


def schema():
    return {'group_row': ['kind', 'key', 'denominators', 'models', 'contrasts', 'allocations'],
        'cross_group_row': ['kind', 'key', 'denominators', 'models', 'paired', 'did', 'exchanges', 'allocations'],
        'denominators': list(DENOMINATORS), 'versions': list(VERSIONS), 'model_metrics': list(METRICS),
        'contrast_order': list(CONTRASTS), 'exchange_metrics': list(EXCHANGES),
        'allocation_metrics': list(ALLOCATIONS), 'summary_fields': list(SUMMARY),
        'paired_summary_fields': list(PAIRED_SUMMARY),
        'flow_fields': ['complete_days', 'added_alerts', 'dropped_alerts',
                        'within_route_exchanges', 'cross_route_slots', 'within_cell_exchanges', 'cross_cell_slots']}


def summary(values, *, paired=False):
    defined = np.asarray([float(value) for value in values if value is not None], dtype=float)
    if not np.isfinite(defined).all():
        raise ValueError('Statistics require finite values or null')
    row = [float(defined.mean()), float(defined.min()), float(defined.max()), float(np.ptp(defined))] if len(defined) else [None] * 4
    row += [len(defined), len(values) - len(defined)]
    if paired:
        row += [int((defined < 0).sum()), int((defined == 0).sum()), int((defined > 0).sum())]
    return row


def difference(new, old):
    return None if new is None or old is None else new - old


def model_counts(mask, known, labels, alert):
    positive, negative = mask & known & (labels == 1), mask & known & (labels == 0)
    tp, fp = int((positive & alert).sum()), int((negative & alert).sum())
    known_alerts, unknown_alerts = int((mask & known & alert).sum()), int((mask & ~known & alert).sum())
    delayed = int(positive.sum())
    return [tp, fp, delayed - tp, known_alerts, unknown_alerts, known_alerts + unknown_alerts,
            tp / delayed if delayed else None, tp / known_alerts if known_alerts else None]


def exchange_counts(mask, known, labels, old, new):
    added, dropped = mask & ~old & new, mask & old & ~new
    return [int((added & known & (labels == 1)).sum()), int((dropped & known & (labels == 1)).sum()),
        int(added.sum()), int(dropped.sum()), int((added & known & (labels == 0)).sum()),
        int((dropped & known & (labels == 0)).sum()), int((added & ~known).sum()),
        int((dropped & ~known).sum()), int((mask & old & new).sum())]


def daily_allocation(mask, old, new, day_codes, day_count):
    added = np.bincount(day_codes, weights=(mask & ~old & new).astype(int), minlength=day_count).astype(int)
    dropped = np.bincount(day_codes, weights=(mask & old & ~new).astype(int), minlength=day_count).astype(int)
    return [int(np.minimum(added, dropped).sum()), int(np.maximum(dropped - added, 0).sum()),
            int(np.maximum(added - dropped, 0).sum())]


def group_masks(frame):
    cells, groups = intersections.group_masks(frame)
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    ages = intersections.previous.age_bins(frame)
    return ([('overall', 'ALL', np.ones(len(frame), bool))]
        + [('route', route, routes == route) for route in sorted(set(routes) | {'SP->SC'})]
        + [('marginal', name, groups[name]) for name in GROUPS]
        + [('cell', name, cells == name) for name in CELLS]
        + [('cell110_age', name, (cells == '110') & (ages == name)) for name in AGE_BINS])


def diagnose_phase(frame, scores, known):
    """Return compact public counts and private sets; no model is loaded."""
    if frame.empty or set(scores) != set(VERSIONS) or frame.order_id.isna().any() or frame.order_id.duplicated().any():
        raise ValueError('Require four complete scoring versions and unique identities')
    known, labels = _known_labels(frame, known)
    alerts = {}
    for version in VERSIONS:
        value = np.asarray(scores[version], float)
        if value.shape != (len(frame),) or not np.isfinite(value).all() or ((value < 0) | (value > 1)).any():
            raise ValueError('Require finite bounded scores for every full-batch row')
        alerts[version] = apply_alert_policy(frame, value, 0., .1, raw_scores=value)
    day_codes, days = pd.factorize(pd.to_datetime(frame.prediction_time).dt.normalize(), sort=True)
    if (day_codes < 0).any():
        raise ValueError('Invalid approval day')
    expected = np.bincount(day_codes) // 10
    for alert in alerts.values():
        np.testing.assert_array_equal(np.bincount(day_codes, weights=alert.astype(int)), expected)
    records, masks = [], group_masks(frame)
    ids = frame.order_id.to_numpy()
    private = {'delayed': {}, 'lost': {contrast: {} for contrast in CONTRASTS}}
    focus = {('overall', 'ALL'), ('route', 'SP->SC')}
    focus |= {(kind, key) for kind, key, _ in masks
              if kind in ('marginal', 'cell', 'cell110_age') and (kind, key) != ('marginal', 'ALL')}
    for kind, key, mask in masks:
        denominators = [int(mask.sum()), int((mask & known).sum()), int((mask & ~known).sum()), int((mask & known & (labels == 1)).sum())]
        models = [model_counts(mask, known, labels, alerts[version]) for version in VERSIONS]
        exchanges, allocations = [], []
        for contrast, (old_version, new_version) in CONTRASTS.items():
            old, new = alerts[old_version], alerts[new_version]
            row = exchange_counts(mask, known, labels, old, new)
            if row[2] != row[0] + row[4] + row[6] or row[3] != row[1] + row[5] + row[7]:
                raise AssertionError('Known and unknown changes do not reconcile')
            oi, ni = VERSIONS.index(old_version), VERSIONS.index(new_version)
            if models[ni][0] - models[oi][0] != row[0] - row[1]:
                raise AssertionError('Paired TP does not reconcile')
            exchanges.append(row)
            allocations.append(daily_allocation(mask, old, new, day_codes, len(days)))
            if (kind, key) in focus:
                private['lost'][contrast][f'{kind}:{key}'] = set(ids[mask & known & (labels == 1) & old & ~new])
        if (kind, key) in focus:
            private['delayed'][f'{kind}:{key}'] = set(ids[mask & known & (labels == 1)])
        records.append([kind, key, denominators, models, exchanges, allocations])
    overall = records[0]
    for kind in ('route', 'cell'):
        selected = [row for row in records if row[0] == kind]
        if [sum(row[2][i] for row in selected) for i in range(4)] != overall[2]:
            raise AssertionError('Groups do not partition their complete phase')
        for version in range(4):
            for i in range(6):
                if sum(row[3][version][i] for row in selected) != overall[3][version][i]:
                    raise AssertionError('Group model counts do not sum to phase')
        for contrast in range(4):
            for i in range(9):
                if sum(row[4][contrast][i] for row in selected) != overall[4][contrast][i]:
                    raise AssertionError('Group exchanges do not sum to phase')
            within, outgoing, incoming = [sum(row[5][contrast][i] for row in selected) for i in range(3)]
            if outgoing != incoming or within + incoming != overall[4][contrast][2]:
                raise AssertionError('Daily gross group allocation does not conserve changed slots')
    flows = []
    for index in range(4):
        route = [sum(row[5][index][i] for row in records if row[0] == 'route') for i in range(3)]
        cell = [sum(row[5][index][i] for row in records if row[0] == 'cell') for i in range(3)]
        flows.append([len(days), overall[4][index][2], overall[4][index][3], route[0], route[2], cell[0], cell[2]])
    return {'groups': records, 'daily_gross_totals': flows}, private


def summarize_group(rows_by_seed):
    if set(rows_by_seed) != set(SEEDS):
        raise ValueError('Require all five prespecified seeds')
    rows = [rows_by_seed[seed] for seed in SEEDS]
    if any(row[:3] != rows[0][:3] for row in rows):
        raise ValueError('Cross-seed group identities or denominators changed')
    models = [[summary([row[3][version][metric] for row in rows]) for metric in range(len(METRICS))] for version in range(4)]
    paired = []
    for old_version, new_version in CONTRASTS.values():
        oi, ni = VERSIONS.index(old_version), VERSIONS.index(new_version)
        paired.append([summary([difference(row[3][ni][metric], row[3][oi][metric]) for row in rows], paired=True) for metric in range(len(METRICS))])
    did = [summary([difference(difference(row[3][3][metric], row[3][2][metric]),
                              difference(row[3][1][metric], row[3][0][metric])) for row in rows], paired=True) for metric in range(len(METRICS))]
    exchanges = [[summary([row[4][contrast][metric] for row in rows]) for metric in range(len(EXCHANGES))] for contrast in range(4)]
    allocations = [[summary([row[5][contrast][metric] for row in rows]) for metric in range(3)] for contrast in range(4)]
    return rows[0][:3] + [models, paired, did, exchanges, allocations]


def summarize_phases(phases_by_seed):
    if set(phases_by_seed) != set(SEEDS):
        raise ValueError('Require all five prespecified phases')
    rows = {seed: {(row[0], row[1]): row for row in phases_by_seed[seed]['groups']} for seed in SEEDS}
    keys = list(rows[SEEDS[0]])
    if any(set(rows[seed]) != set(keys) for seed in SEEDS):
        raise ValueError('Cross-seed actual route/group support changed')
    return {'groups': [summarize_group({seed: rows[seed][key] for seed in SEEDS}) for key in keys],
        'daily_gross_totals': [[summary([phases_by_seed[seed]['daily_gross_totals'][contrast][metric] for seed in SEEDS])
            for metric in range(7)] for contrast in range(4)]}


def decode_group(phase, kind='overall', key='ALL', *, cross_seed=False):
    """Readable adapter for public compact tables (Notebook/report consumers)."""
    row = next(row for row in phase['groups'] if row[0] == kind and row[1] == key)
    result = {'kind': kind, 'key': key, 'denominators': dict(zip(DENOMINATORS, row[2], strict=True))}
    if not cross_seed:
        result['models'] = {version: dict(zip(METRICS, values, strict=True)) for version, values in zip(VERSIONS, row[3], strict=True)}
        result['contrasts'] = {contrast: dict(zip(EXCHANGES, values, strict=True)) for contrast, values in zip(CONTRASTS, row[4], strict=True)}
        result['allocations'] = {contrast: dict(zip(ALLOCATIONS, values, strict=True)) for contrast, values in zip(CONTRASTS, row[5], strict=True)}
        return result
    def expand(values, metrics, fields):
        return {metric: dict(zip(fields, values[index], strict=True)) for index, metric in enumerate(metrics)}
    result['models'] = {version: expand(values, METRICS, SUMMARY) for version, values in zip(VERSIONS, row[3], strict=True)}
    result['paired'] = {contrast: expand(values, METRICS, PAIRED_SUMMARY) for contrast, values in zip(CONTRASTS, row[4], strict=True)}
    result['did'] = expand(row[5], METRICS, PAIRED_SUMMARY)
    result['exchanges'] = {contrast: expand(values, EXCHANGES, SUMMARY) for contrast, values in zip(CONTRASTS, row[6], strict=True)}
    result['allocations'] = {contrast: expand(values, ALLOCATIONS, SUMMARY) for contrast, values in zip(CONTRASTS, row[7], strict=True)}
    return result


def compact_counts(row, contrast):
    """Map a compact row back to the established31 conservation counts."""
    ci = list(CONTRASTS).index(contrast)
    old_version, new_version = CONTRASTS[contrast]
    old, new = (row[3][VERSIONS.index(version)] for version in (old_version, new_version))
    ex, den = row[4][ci], row[2]
    result = dict(zip(DENOMINATORS, den, strict=True))
    for prefix, values in [('old', old), ('new', new)]:
        result.update({f'{prefix}_alerts': values[5], f'{prefix}_known_alerts': values[3],
            f'{prefix}_unknown_alerts': values[4], f'{prefix}_true_positives': values[0],
            f'{prefix}_false_positives': values[1], f'{prefix}_false_negatives': values[2],
            f'{prefix}_true_negatives': den[1] - den[3] - values[1]})
    result.update(dict(zip(EXCHANGES, ex, strict=True)))
    result.update({'net_TP': new[0] - old[0], 'net_FP': new[1] - old[1],
                   'net_unknown_alerts': new[4] - old[4], 'net_alerts': new[5] - old[5]})
    return result


def verify_frozen_phase(phase, frozen):
    """Reproduce the complete0.8 group ledger, not only aggregate TP."""
    sources = {('overall', 'ALL'): frozen['overall']}
    sources.update({('route', row['state_route']): row for row in frozen['routes']})
    sources.update({('marginal', key): row for key, row in frozen['rpa_marginals'].items()})
    sources.update({('cell', row['cell']): row for row in frozen['rpa_cells']})
    sources.update({('cell110_age', row['age_bin']): row for row in frozen['cell110_age_bins']})
    actual = {(row[0], row[1]): row for row in phase['groups']}
    if set(actual) - set(sources) not in (set(), {('route', 'SP->SC')}):
        raise ValueError('Frozen0.8 group support changed')
    if not set(sources).issubset(actual):
        raise ValueError('Frozen0.8 group omitted')
    compared = 0
    for key, expected in sources.items():
        row = actual[key]
        for field, value in compact_counts(row, 'age_minus_base_at_08').items():
            if value != expected[field]:
                raise ValueError(f'Frozen0.8 group count changed: {key}/{field}')
            compared += 1
        if key[0] == 'route':
            names = ('within_route_exchanges', 'cross_route_outgoing_slots', 'cross_route_incoming_slots')
        elif key[0] == 'cell':
            names = ('within_cell_exchanges', 'cross_cell_outgoing_slots', 'cross_cell_incoming_slots')
        else:
            names = ()
        for i, name in enumerate(names):
            if row[5][0][i] != expected[name]:
                raise ValueError('Frozen0.8 daily allocation changed')
            compared += 1
    flow = phase['daily_gross_totals'][0]
    expected_flow = [frozen['daily_batch_count'], frozen['overall']['added_alerts'], frozen['overall']['dropped_alerts'],
        frozen['overall']['within_route_exchanges'], frozen['overall']['cross_route_slots'],
        frozen['overall']['within_cell_exchanges'], frozen['overall']['cross_cell_slots']]
    if flow != expected_flow:
        raise ValueError('Frozen0.8 complete-day gross totals changed')
    return compared + len(flow)


def comparison_values(row):
    names = {'true_positives': 0, 'false_positives': 1, 'false_negatives': 2,
             'recall': 6, 'precision': 7, 'alerts': 5}
    result = {}
    for contrast, (old_version, new_version) in CONTRASTS.items():
        old, new = row[3][VERSIONS.index(old_version)], row[3][VERSIONS.index(new_version)]
        result[contrast] = {name: difference(new[index], old[index]) for name, index in names.items()}
    result['difference_in_differences'] = {name: difference(result['age_minus_base_at_10'][name],
            result['age_minus_base_at_08'][name]) for name in names}
    return result


def verify_comparisons(row, expected):
    actual = comparison_values(row)
    if set(expected) != set(actual):
        raise ValueError('Missing prespecified contrast or DID')
    count = 0
    for contrast, metrics in actual.items():
        if set(metrics) != set(expected[contrast]):
            raise ValueError('Changed contrast metric schema')
        for metric, value in metrics.items():
            before = expected[contrast][metric]
            if value is None or before is None:
                if value is not before:
                    raise ValueError('Undefined contrast rate changed')
            elif not np.isclose(value, before, rtol=0, atol=1e-14):
                raise ValueError(f'Main contrast does not reconcile: {contrast}/{metric}')
            count += 1
    return count


def pool_development(phases_by_seed, evaluation_keys):
    if (len(evaluation_keys) != 3 or len(set(evaluation_keys)) != 3
            or any(not key.endswith('/evaluation') for key in evaluation_keys)
            or len({key.split('/')[1] for key in evaluation_keys}) != 3):
        raise ValueError('Pool only three disjoint development phases')
    if set(phases_by_seed) != set(SEEDS):
        raise ValueError('Require all fixed seeds for development pool')
    pooled = {}
    for seed in SEEDS:
        rows = [phases_by_seed[seed][key]['groups'][0] for key in evaluation_keys]
        if any(row[:2] != ['overall', 'ALL'] for row in rows):
            raise ValueError('Development group must be the full population')
        den = [sum(row[2][index] for row in rows) for index in range(4)]
        models = []
        for version in range(4):
            value = [sum(row[3][version][index] for row in rows) for index in range(6)]
            value += [value[0] / den[3] if den[3] else None, value[0] / value[3] if value[3] else None]
            models.append(value)
        exchanges = [[sum(row[4][contrast][index] for row in rows) for index in range(9)] for contrast in range(4)]
        allocations = [[sum(row[5][contrast][index] for row in rows) for index in range(3)] for contrast in range(4)]
        pooled[seed] = ['overall', 'ALL', den, models, exchanges, allocations]
    return {'phase_keys': evaluation_keys, 'seed_groups': {str(seed): row for seed, row in pooled.items()},
            'cross_seed_group': summarize_group(pooled)}


def identity_overlaps(private, metadata):
    def contrast_overlap(contrast, sets, universe):
        result = previous.overlap_summary(sets, universe)
        old, new = CONTRASTS[contrast]
        result['definition'] = f'Known delayed, alerted by own {old} and missed by own {new} at the same seed; identities are not published.'
        return result

    all_phases = {}
    for phase in metadata:
        reference = private[phase][SEEDS[0]]['delayed']
        if any(private[phase][seed]['delayed'] != reference for seed in SEEDS):
            raise ValueError('Known delayed identities changed across seeds')
        all_phases[phase] = {contrast: contrast_overlap(contrast,
            {seed: private[phase][seed]['lost'][contrast]['overall:ALL'] for seed in SEEDS},
            reference['overall:ALL']) for contrast in CONTRASTS}
    focus = private[TARGET_PHASE]
    keys = list(focus[SEEDS[0]]['delayed'])
    february = {contrast: {key: contrast_overlap(contrast,
        {seed: focus[seed]['lost'][contrast][key] for seed in SEEDS}, focus[SEEDS[0]]['delayed'][key])
        for key in keys} for contrast in CONTRASTS}
    cross = {}
    for seed in SEEDS:
        cross[str(seed)] = {}
        for key in keys:
            left = focus[seed]['lost']['age_minus_base_at_08'][key]
            right = focus[seed]['lost']['age_minus_base_at_10'][key]
            union, intersection = left | right, left & right
            cross[str(seed)][key] = {'colsample08_rows': len(left), 'colsample10_rows': len(right),
                'intersection': len(intersection), 'union': len(union),
                'jaccard': len(intersection) / len(union) if union else None}
    return all_phases, february, cross


def february_stability(phase):
    decoded = decode_group(phase, cross_seed=True)
    return {'by_version': {version: {metric: decoded['models'][version][metric] for metric in ('TP', 'recall')}
                for version in VERSIONS},
        'age_gap_by_colsample': {col: {metric: decoded['paired'][contrast][metric] for metric in ('TP', 'recall')}
            for col, contrast in [('0.8', 'age_minus_base_at_08'), ('1.0', 'age_minus_base_at_10')]},
        'age_gap_span_change10_minus08': {metric: difference(decoded['paired']['age_minus_base_at_10'][metric]['span'],
                    decoded['paired']['age_minus_base_at_08'][metric]['span']) for metric in ('TP', 'recall')},
        'interpretation': 'Span and signs describe these fixed seeds on the same data; neither a smaller gap span nor a positive mean establishes stable model improvement.'}


def build_report(source_path):
    source_path = Path(source_path).resolve()
    source = json.loads(source_path.read_text(encoding='utf-8'))
    contract = diagnostic_contract()
    if (source.get('status') != 'ok' or source.get('seeds') != list(SEEDS)
            or source.get('matched_candidate_order') != list(CANDIDATES)
            or source.get('diagnostic_contract') != contract
            or source.get('diagnostic_contract_sha256') != previous.canonical_sha256(contract)):
        raise ValueError('Require completed prespecified five-seed colsample experiment')
    files = {source_path: previous.sha256(source_path)}

    def protect(info):
        path = (ROOT / info['path']).resolve()
        if previous.sha256(path) != info['sha256']:
            raise ValueError(f'Changed frozen source: {path}')
        files[path] = info['sha256']
        return path

    prior_path = protect(source['source_report'])
    if files[prior_path] != SOURCE_SHA256:
        raise ValueError('Require the frozen five-seed0.8 main report')
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    frozen_path = ROOT / 'reports/stage4/age_seed_stability_diagnostics.json'
    if previous.sha256(frozen_path) != SOURCE_DIAGNOSTIC_SHA256:
        raise ValueError('Frozen0.8 diagnostic changed')
    files[frozen_path] = SOURCE_DIAGNOSTIC_SHA256
    frozen = json.loads(frozen_path.read_text(encoding='utf-8'))
    spec_path = source_path.with_name('age_colsample_specification.json')
    specification = json.loads(spec_path.read_text(encoding='utf-8'))
    if (previous.sha256(spec_path) != source['specification_sha256']
            or any(source.get(key) != value for key, value in specification.items())):
        raise ValueError('Pre-fit specification changed')
    files[spec_path] = source['specification_sha256']
    for info in source['source_hashes']:
        protect(info)
    for info in prior['source_hashes'] + prior['source_model_hashes']:
        protect(info)
    feature_path = protect(source['feature_dataset'])
    if source['feature_dataset'] != prior['feature_dataset']:
        raise ValueError('The original138-column age cache changed')
    score_path, old_score_path = protect(source['score_export']), protect(prior['score_export'])
    counts = []
    for report in [prior, source]:
        pairs, paths = set(), set()
        for monthly in report['monthly_training']:
            pair = (monthly['month'], monthly['seed'])
            if pair in pairs or monthly['seed'] not in SEEDS or set(monthly['models']) != set(CANDIDATES):
                raise ValueError('Changed40 monthly/seed pairs')
            pairs.add(pair)
            for model in monthly['models'].values():
                paths.add(protect(model['version_artifact']))
        expected_months = {row['month'] for row in prior['monthly_training']}
        if pairs != set(itertools.product(expected_months, SEEDS)) or len(paths) != 80:
            raise ValueError('Require80 unique artifacts at each colsample')
        counts.append(len(paths))
    frame = pd.read_csv(feature_path, float_precision='round_trip', dtype={name: object for name in
        ('order_id', 'state_route', 'primary_seller_id', 'customer_zip_prefix3', 'primary_seller_zip_prefix3')})
    for name in ('prediction_time', 'label_available_time'):
        frame[name] = pd.to_datetime(frame[name], errors='raise')
    if (frame.shape != (70844, 138) or frame.prediction_time.ge('2018-05-01').any()
            or frame.order_id.isna().any() or frame.order_id.duplicated().any()):
        raise ValueError('Changed original pre-May138-column population')
    ledger = pd.read_csv(score_path, float_precision='round_trip', parse_dates=['prediction_time'])
    old_ledger = pd.read_csv(old_score_path, float_precision='round_trip', parse_dates=['prediction_time'])
    if (len(ledger) != 1281120 or source['score_export']['rows'] != len(ledger)
            or set(ledger.seed) != set(SEEDS) or set(ledger.colsample_bytree) != {.8, 1.}
            or ledger.duplicated(['colsample_bytree', 'seed', 'fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Require1281120 unique combined scoring rows')
    identity = ['seed', 'fold', 'role', 'candidate', 'model_version', 'order_id']
    old_part = ledger.loc[ledger.colsample_bytree.eq(.8), old_ledger.columns]
    if len(old_part) != 640560 or len(old_ledger) != 640560:
        raise ValueError('Frozen0.8 ledger size changed')
    pd.testing.assert_frame_equal(old_part.sort_values(identity).reset_index(drop=True),
        old_ledger.sort_values(identity).reset_index(drop=True), check_exact=True)
    plans = source['phase_metrics']
    if len(plans) != 12 or set(plans) != set(prior['phase_metrics']):
        raise ValueError('Original12 phase identities changed')
    metadata_fields = ('fold', 'month', 'ledger_role', 'role', 'historical_outcome_cutoff')
    for key, plan in plans.items():
        if any(plan.get(field) != prior['phase_metrics'][key][field] for field in metadata_fields):
            raise ValueError('Original phase metadata or mature-outcome cutoff changed')
        if set(plan['by_colsample']) != {'0.8', '1.0'}:
            raise ValueError('Require both colsample contexts')
    phased = {seed: {} for seed in SEEDS}
    private, frozen_fields, contrast_fields, ledger_rows = {}, 0, 0, 0
    for key, plan in plans.items():
        batch = frame.loc[frame.prediction_time.dt.strftime('%Y-%m').eq(plan['month'])].reset_index(drop=True)
        private[key] = {}
        for seed in SEEDS:
            scores, known_reference = {}, None
            for col in ('0.8', '1.0'):
                part = ledger.loc[ledger.colsample_bytree.eq(float(col)) & ledger.seed.eq(seed)
                    & ledger.fold.eq(plan['fold']) & ledger.model_version.eq(plan['month']) & ledger.role.eq(plan['ledger_role'])]
                expected = plan['by_colsample'][col][str(seed)]
                if col == '0.8' and expected != prior['phase_metrics'][key]['by_seed'][str(seed)]:
                    raise ValueError('Frozen0.8 main metric context changed')
                known, values, _ = previous.verify_phase_ledger(batch, part, plan, seed, expected)
                if known_reference is not None:
                    np.testing.assert_array_equal(known_reference, known)
                known_reference = known
                for version, (version_col, candidate) in VERSION_SOURCE.items():
                    if version_col == col:
                        scores[version] = values[candidate]
                ledger_rows += len(part)
            phase, identities = diagnose_phase(batch, scores, known_reference)
            frozen_fields += verify_frozen_phase(phase, frozen['seed_phases'][str(seed)][key])
            contrast_fields += verify_comparisons(phase['groups'][0], source['phase_comparisons'][key]['by_seed'][str(seed)])
            phased[seed][key], private[key][seed] = phase, identities
    if ledger_rows != len(ledger):
        raise ValueError('Unrecognized combined scoring rows')
    cross = {key: summarize_phases({seed: phased[seed][key] for seed in SEEDS}) for key in plans}
    evaluation_keys = [key for key, plan in plans.items() if plan['ledger_role'] == 'evaluation']
    pool = pool_development(phased, evaluation_keys)
    for seed in SEEDS:
        contrast_fields += verify_comparisons(pool['seed_groups'][str(seed)], source['development_comparisons']['by_seed'][str(seed)])
    overlaps, focus, cross_overlaps = identity_overlaps(private, plans)
    for path, expected in files.items():
        if previous.sha256(path) != expected:
            raise ValueError('Source changed during four-contrast diagnosis')
    return {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': source_path.relative_to(ROOT).as_posix(), 'sha256': files[source_path]},
        'source_hashes': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest} for path, digest in files.items()],
        'diagnostic_contract': contract, 'diagnostic_contract_sha256': previous.canonical_sha256(contract),
        'seeds': list(SEEDS), 'schema': schema(),
        'phases': {key: {field: plan[field] for field in metadata_fields} for key, plan in plans.items()},
        'seed_phases': {str(seed): phased[seed] for seed in SEEDS}, 'cross_seed_phases': cross,
        'development_pool': pool, 'february_stability': february_stability(cross[TARGET_PHASE]),
        'newly_lost_identity_overlap': overlaps, 'february_focus_identity_overlap': focus,
        'february_cross_colsample_lost_overlap': cross_overlaps,
        'verification': {'seed_count': 5, 'phases_per_seed': 12, 'seed_phase_groups_verified': 60,
            'contrast_phase_groups_verified': 240, 'candidate_metric_groups_verified': 240,
            'score_rows_verified': ledger_rows, 'frozen_score_rows_verified': len(old_ledger),
            'frozen_group_count_and_gross_fields_verified': frozen_fields,
            'main_contrast_fields_verified': contrast_fields, 'old_artifact_hashes_checked': counts[0],
            'new_artifact_hashes_checked': counts[1], 'models_deserialized': 0, 'new_fits': 0,
            'saved_models_replayed': 0, 'new_selection': False, 'unknown_ranked_before_masks': True,
            'original_holdout_not_rescored': True, 'private_order_identities_exported': False},
        'limitations': ['All five seeds reuse the same inspected development/historical identities; repetitions are not independent new tests.',
            'Four contrasts use their own old/new pair; DID is a paired difference of model metrics, not an identified causal effect.',
            'Span and direction counts describe these five seeds; neither a narrower gap nor positive mean alone proves stable improvement.',
            'Group views overlap and share the original complete-day budget; no per-route quotas or causal donor-recipient pairing.',
            'colsample1.0 keeps subsample0.8 and all other fixed settings; it does not remove all randomness.',
            'Original413TP primary, default RF and original retained holdout are unchanged.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/age_colsample.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/age_colsample_diagnostics.json')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == args.source_report.resolve() or output.suffix.lower() != '.json':
        parser.error('Require a separate aggregate JSON output')
    report = build_report(args.source_report)
    encoded = json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) >= 50_000_000:
        raise ValueError('Public aggregate must remain below50MB')
    output.parent.mkdir(parents=True, exist_ok=True)
    created = previous.fixed_json(output, report)
    print(json.dumps({'report': output.relative_to(ROOT).as_posix(), 'bytes': output.stat().st_size,
        'seed_phases': 60, 'contrasts': 240, 'created': created, 'new_fits': 0, 'new_replays': 0}), flush=True)
    return report


if __name__ == '__main__':
    main()
