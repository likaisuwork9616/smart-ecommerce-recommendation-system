"""Describe common misses and alert exchanges of three frozen approval models.

Only hashed feature and score files are aggregated. Models are checked by hash,
never loaded, fitted, replayed, selected or combined into a new alert policy.
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
from scripts.delay_route_exchanges import ALLOCATION_FIELDS, COUNT_FIELDS, _row_counts, analyze_route_exchanges
from scripts.diagnose_budget_misses import MIN_GROUP_POSITIVES, MIN_GROUP_ROWS, PROMISE_BINS, RANK_BINS, daily_rank_bins
from scripts import diagnose_handover_count as count
from scripts import diagnose_handover_sparse as sparse
from scripts.diagnose_rank_batch_size import VOLUME_BINS, _assert_partition, _day_info, _known_labels, _positions, volume_bin
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest

ANALYSIS = 'frozen_handover_three_model_common_misses'
SOURCE_SHA = '57077703b7160c84eca8ab517f2f3325d105ea481bfa5c657f057fbbd0a3f9b3'
DIAGNOSTICS_SHA = '35f15584b6843318872e561531dc870e392c0cfec19cbf66f7c9e98c32b35121'
BASELINE, COUNT102, HANDOVER104 = count.BASELINE, count.NEW, count.HANDOVER104
# The ledger source orders 101,104,102; the explicitly declared bit order below
# is instead the intuitive column-count order. Never infer it from a dict.
MATCHED = (BASELINE, COUNT102, HANDOVER104)
PATTERNS = tuple(''.join(bits) for bits in product('01', repeat=3))
COMPARISONS = {'baseline101_to_count102': (BASELINE, COUNT102),
               'baseline101_to_handover104': (BASELINE, HANDOVER104),
               'handover104_to_count102': (HANDOVER104, COUNT102)}
GAP_BINS = ('1-3', '4-10', '11+')
COMMON_COUNT_FIELDS = ('full_batch_rows', 'known_rows', 'unknown_rows', 'known_delayed_rows',
                       'known_on_time_rows', 'common_missed_delays', 'other_known_delayed_rows',
                       'all_caught_delays', 'some_but_not_all_caught_delays')
PATTERN_COUNT_FIELDS = ('full_batch_rows', 'known_delayed_rows', 'known_on_time_rows', 'unknown_rows')
FOCUS_PHASES = (*count.history.FOCUS_PHASES, '2018-04/2018-04/evaluation')


def _aggregate(values):
    values = np.asarray(values)
    return {'minimum': float(values.min()) if len(values) else None,
            'median': float(np.median(values)) if len(values) else None,
            'maximum': float(values.max()) if len(values) else None}


def _gap_bins(values):
    values = np.asarray(values)
    if (values <= 0).any():
        raise AssertionError('Missed-order capacity gaps must be positive')
    return np.where(values <= 3, GAP_BINS[0], np.where(values <= 10, GAP_BINS[1], GAP_BINS[2]))


def _common_row(mask, known, labels, alerts):
    positive, negative = known & (labels == 1), known & (labels == 0)
    matrix = np.column_stack([alerts[c] for c in MATCHED])
    missed = positive & ~matrix.any(axis=1)
    all_caught = positive & matrix.all(axis=1)
    row = {'full_batch_rows': int(mask.sum()), 'known_rows': int((mask & known).sum()),
        'unknown_rows': int((mask & ~known).sum()), 'known_delayed_rows': int((mask & positive).sum()),
        'known_on_time_rows': int((mask & negative).sum()), 'common_missed_delays': int((mask & missed).sum()),
        'other_known_delayed_rows': int((mask & positive & ~missed).sum()),
        'all_caught_delays': int((mask & all_caught).sum()),
        'some_but_not_all_caught_delays': int((mask & positive & matrix.any(axis=1) & ~matrix.all(axis=1)).sum())}
    row['models'] = {c: {'true_positives': int((mask & positive & alerts[c]).sum()),
        'false_negatives': int((mask & positive & ~alerts[c]).sum()),
        'alerts': int((mask & alerts[c]).sum())} for c in MATCHED}
    row.update(common_missed_share_of_known_delays=(row['common_missed_delays'] / row['known_delayed_rows']
               if row['known_delayed_rows'] else None),
        known_delay_rate=(row['known_delayed_rows'] / row['known_rows'] if row['known_rows'] else None),
        minimum_sample_met=row['known_rows'] >= MIN_GROUP_ROWS and row['known_delayed_rows'] >= MIN_GROUP_POSITIVES)
    if (row['known_rows'] + row['unknown_rows'] != row['full_batch_rows'] or
            row['known_delayed_rows'] + row['known_on_time_rows'] != row['known_rows'] or
            row['common_missed_delays'] + row['other_known_delayed_rows'] != row['known_delayed_rows'] or
            row['all_caught_delays'] + row['some_but_not_all_caught_delays'] != row['other_known_delayed_rows']):
        raise AssertionError('Common-miss outcome counts do not partition')
    return row


def _assert_common_partition(rows, summary):
    _assert_partition(rows, summary, COMMON_COUNT_FIELDS)
    for c in MATCHED:
        for field in ('true_positives', 'false_negatives', 'alerts'):
            if sum(row['models'][c][field] for row in rows) != summary['models'][c][field]:
                raise AssertionError('Model counts do not partition common-miss marginals')


def _ranks(mask, candidates, positions, ranks, capacity, sizes):
    result = {}
    for c in candidates:
        selected_ranks = ranks[c][mask]
        gaps = (positions[c] - capacity)[mask]
        result[c] = {'rows': int(mask.sum()),
            'rank_bins': {name: int((selected_ranks == name).sum()) for name in RANK_BINS},
            'full_day_positions': _aggregate(positions[c][mask]),
            'relative_rank_fraction': _aggregate((positions[c] / sizes)[mask]),
            'capacity_gap_slots': _aggregate(gaps)}
        if sum(result[c]['rank_bins'].values()) != int(mask.sum()):
            raise AssertionError('Full-day rank bins do not partition selected rows')
    return result


def common_miss_diagnostics(frame, scores, known, *, focus=False):
    """Eight alert patterns and all denominators, ranked before outcome masks."""
    if not isinstance(frame, pd.DataFrame) or frame.empty or set(scores) != set(MATCHED):
        raise ValueError('Require a nonempty phase and all three fixed candidate scores')
    known, labels = _known_labels(frame, known)
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED}
    positions = {c: _positions(frame, scores[c]) for c in MATCHED}
    ranks = {c: daily_rank_bins(frame, scores[c]) for c in MATCHED}
    days, day_sizes = _day_info(frame)
    sizes = np.asarray([day_sizes[day] for day in days])
    capacity = sizes // 10
    for c in MATCHED:
        if not np.array_equal(alerts[c], positions[c] <= capacity):
            raise AssertionError('Original full-day ranks must match floor(10%*N) alerts')
    patterns = np.asarray([''.join(str(int(alerts[c][i])) for c in MATCHED) for i in range(len(frame))])
    pattern_rows = []
    for pattern in PATTERNS:
        mask = patterns == pattern
        row = _common_row(mask, known, labels, alerts)
        pattern_rows.append({'pattern': pattern, **{key: row[key] for key in PATTERN_COUNT_FIELDS}})
    summary = _common_row(np.ones(len(frame), bool), known, labels, alerts)
    _assert_partition(pattern_rows, summary, PATTERN_COUNT_FIELDS)
    if pattern_rows[0]['known_delayed_rows'] != summary['common_missed_delays']:
        raise AssertionError('Pattern 000 known delays must be the common missed cohort')
    groups = sparse.group_definitions(frame)
    volume = np.asarray([volume_bin(n) for n in sizes])
    dimensions = {'routes': ('state_route', groups['routes'], sorted(set(groups['routes']))),
        'promise_days': ('promise_bin', groups['promise_bin'], PROMISE_BINS),
        'support_bins': ('support_bin', groups['support'], sparse.SUPPORT_BINS),
        'volume_bins': ('volume_bin', volume, VOLUME_BINS)}
    positive = known & (labels == 1)
    common = positive & (patterns == '000')
    result = {'summary': summary}
    for name, (field, values, declared) in dimensions.items():
        rows = [{field: key, **_common_row(values == key, known, labels, alerts)} for key in declared]
        _assert_common_partition(rows, summary)
        result[name] = rows
    result['rank_details'] = _ranks(common, MATCHED, positions, ranks, capacity, sizes)
    for c in MATCHED:
        gaps = (positions[c] - capacity)[common]
        bins = _gap_bins(gaps)
        result['rank_details'][c]['capacity_gap_bins'] = {name: int((bins == name).sum()) for name in GAP_BINS}
    closest = np.min(np.column_stack([positions[c] for c in MATCHED]), axis=1)
    closest_relative = closest / sizes
    closest_gap = closest - capacity
    relative_bins = np.where(closest_relative <= .1, RANK_BINS[0], np.where(closest_relative <= .2,
                    RANK_BINS[1], np.where(closest_relative <= .5, RANK_BINS[2], RANK_BINS[3])))
    gap_bins = np.full(len(frame), 'not_common', object)
    gap_bins[common] = _gap_bins(closest_gap[common])
    result['closest_rank_views'] = {'interpretation': 'Retrospective minimum across the three existing full-day ranks for each common miss. It is neither a combined score nor a deployable policy; no union budget or oracle recall is evaluated.',
        'relative_rank_fraction': _aggregate(closest_relative[common]),
        'capacity_gap_slots': _aggregate(closest_gap[common]), 'relative_rank_bins': [], 'capacity_gap_bins': []}
    for name, field, values, declared in (('relative_rank_bins', 'rank_bin', relative_bins, RANK_BINS),
                                        ('capacity_gap_bins', 'gap_bin', gap_bins, GAP_BINS)):
        for value in declared:
            mask = common & (values == value)
            row = {field: value, 'common_missed_delays': int(mask.sum())}
            if focus:
                for dimension, (group_field, group_values, group_names) in dimensions.items():
                    row[dimension] = [{group_field: item, 'common_missed_delays': int((mask & (group_values == item)).sum())}
                                      for item in group_names]
            result['closest_rank_views'][name].append(row)
        if sum(row['common_missed_delays'] for row in result['closest_rank_views'][name]) != summary['common_missed_delays']:
            raise AssertionError('Closest-rank descriptive bins must partition common misses')
    return {'capture_patterns': pattern_rows, 'common_misses': result}


def pair_diagnostics(frame, scores, known, old, new):
    """All route and daily capacity accounting without duplicated sparse cells."""
    if old == new or not {old, new} <= set(MATCHED):
        raise ValueError('Require two distinct declared frozen models')
    known, labels = _known_labels(frame, known)
    result = analyze_route_exchanges(frame, scores[old], scores[new], known, .1)
    result.pop('route_day_allocations')
    # The mutually exclusive three-way pattern table already describes stable
    # captures and misses. Keep only actual lost/recovered delay rank movements.
    movement = result['rank_movements']
    movement['cohorts'] = [row for row in movement['cohorts'] if row['cohort'] in ('lost_delays', 'recovered_delays')]
    groups = sparse.group_definitions(frame)
    days, sizes = _day_info(frame)
    volume = np.asarray([volume_bin(sizes[day]) for day in days])
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in (old, new)}
    for name, field, values, declared in (('promise_days', 'promise_bin', groups['promise_bin'], PROMISE_BINS),
        ('support_bins', 'support_bin', groups['support'], sparse.SUPPORT_BINS),
        ('volume_bins', 'volume_bin', volume, VOLUME_BINS)):
        result[name] = [{field: key, **_row_counts(np.flatnonzero(values == key), known, labels, alerts[old], alerts[new])}
                        for key in declared]
        _assert_partition(result[name], result['summary'], COUNT_FIELDS)
    result['comparison'] = {'old_candidate': old, 'new_candidate': new,
        'old_feature_count': count.FEATURE_COUNTS[old], 'new_feature_count': count.FEATURE_COUNTS[new]}
    return result


def diagnose_phase(frame, scores, known, *, focus=False):
    result = common_miss_diagnostics(frame, scores, known, focus=focus)
    result['comparisons'] = {name: pair_diagnostics(frame, scores, known, *pair) for name, pair in COMPARISONS.items()}
    return result


def reconcile_previous(diagnostic, previous):
    """The two published count contrasts retain their original full accounts."""
    for name in count.COMPARISONS:
        current, prior = diagnostic['comparisons'][name], previous['comparisons'][name]
        if current['summary'] != prior['summary'] or current['allocation_summary'] != prior['allocation_summary']:
            raise ValueError('Published count comparison summary or daily capacity changed')
        for dimension, key in (('routes', 'state_route'), ('days', 'day')):
            old = {row[key]: row for row in prior[dimension]}
            new = {row[key]: row for row in current[dimension]}
            fields = COUNT_FIELDS + (ALLOCATION_FIELDS if dimension == 'routes' else ('capacity', 'within_route_exchanges', 'cross_route_slots'))
            if old.keys() != new.keys() or any(old[value][field] != new[value][field] for value in old for field in fields):
                raise ValueError('Published route/day counts or allocations changed')


def pool_development(phases):
    """Pool only the three disjoint reused development months, never history."""
    selected = {key: value for key, value in phases.items() if value['ledger_role'] == 'evaluation'}
    if len(selected) != 3 or len({value['month'] for value in selected.values()}) != 3:
        raise ValueError('Require three distinct development months')
    summary = {field: sum(row['common_misses']['summary'][field] for row in selected.values()) for field in COMMON_COUNT_FIELDS}
    summary['models'] = {c: {field: sum(row['common_misses']['summary']['models'][c][field] for row in selected.values())
                             for field in ('true_positives', 'false_negatives', 'alerts')} for c in MATCHED}
    patterns = [{'pattern': pattern, **{field: sum(next(row for row in phase['capture_patterns'] if row['pattern'] == pattern)[field]
        for phase in selected.values()) for field in PATTERN_COUNT_FIELDS}} for pattern in PATTERNS]
    result = {'phase_keys': list(selected), 'role': 'reused_development_retests',
        'historical_phases_excluded': True, 'summary': summary, 'capture_patterns': patterns}
    for dimension, key in (('routes', 'state_route'), ('promise_days', 'promise_bin'), ('support_bins', 'support_bin'), ('volume_bins', 'volume_bin')):
        keys = (list(PROMISE_BINS) if dimension == 'promise_days' else list(sparse.SUPPORT_BINS)
                if dimension == 'support_bins' else list(VOLUME_BINS) if dimension == 'volume_bins' else
                sorted({row[key] for phase in selected.values() for row in phase['common_misses'][dimension]}))
        rows = []
        for value in keys:
            parts = [row for phase in selected.values() for row in phase['common_misses'][dimension] if row[key] == value]
            row = {key: value, **{field: sum(part[field] for part in parts) for field in COMMON_COUNT_FIELDS}}
            row['models'] = {c: {field: sum(part['models'][c][field] for part in parts)
                for field in ('true_positives', 'false_negatives', 'alerts')} for c in MATCHED}
            rows.append(row)
        _assert_common_partition(rows, summary)
        result[dimension] = rows
    result['closest_rank_views'] = {dimension: [{key: value, 'common_missed_delays': sum(next(row for row in phase['common_misses']['closest_rank_views'][dimension]
        if row[key] == value)['common_missed_delays'] for phase in selected.values())} for value in values]
        for dimension, key, values in (('relative_rank_bins', 'rank_bin', RANK_BINS), ('capacity_gap_bins', 'gap_bin', GAP_BINS))}
    _assert_partition(patterns, summary, PATTERN_COUNT_FIELDS)
    return result


def build_report(source_path, data_dir, previous_diagnostics_path):
    source_path, data_dir, previous_diagnostics_path = map(Path, (source_path, data_dir, previous_diagnostics_path))
    if sha256(source_path) != SOURCE_SHA or sha256(previous_diagnostics_path) != DIAGNOSTICS_SHA:
        raise ValueError('Require the exact published count experiment and diagnostics')
    source = json.loads(source_path.read_text(encoding='utf-8'))
    previous_diagnostics = json.loads(previous_diagnostics_path.read_text(encoding='utf-8'))
    previous_path = ROOT / source['source_report']['path']
    spec_path = source_path.with_name('handover_count_specification.json')
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    files = {source_path: SOURCE_SHA, previous_diagnostics_path: DIAGNOSTICS_SHA,
        previous_path: source['source_report']['sha256'], spec_path: source['specification_sha256'],
        feature_path: source['feature_dataset']['sha256'], score_path: source['score_export']['sha256'],
        ROOT / source['source_features']['path']: source['source_features']['sha256'],
        ROOT / source['source_candidate_versions']['path']: source['source_candidate_versions']['sha256']}
    provenance, selected = {}, {}
    for row in source['monthly_training']:
        provenance[row['month']] = {c: row['models'][c]['version_artifact'] for c in MATCHED}
        for info in provenance[row['month']].values():
            files[ROOT / info['path']] = info['sha256']
    for fold in source['folds']:
        selected[fold['name']] = fold['research_artifact']
        files[ROOT / fold['research_artifact']['path']] = fold['research_artifact']['sha256']
    for info in source['source_files']:
        files[data_dir / info['filename']] = info['sha256']

    def check_sources():
        for path, expected in files.items():
            if sha256(path) != expected:
                raise ValueError(f'Frozen source changed: {relative(path)}')
        if engineering_source_manifest(data_dir) != source['source_files']:
            raise ValueError('Frozen raw sources changed')

    check_sources()
    count.validate_source_contract(source, json.loads(previous_path.read_text(encoding='utf-8')),
        json.loads(spec_path.read_text(encoding='utf-8')))
    if (previous_diagnostics.get('analysis') != count.ANALYSIS or previous_diagnostics.get('source_report') !=
            {'path': relative(source_path), 'sha256': SOURCE_SHA}):
        raise ValueError('Previous diagnostic provenance changed')
    features = read_features(feature_path, data_dir)
    if len(features) != 70844 or len(features.columns) != 137 or features.prediction_time.ge('2018-05-01').any():
        raise ValueError('Require unchanged pre-May 70,844-row 137-column features')
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    ledger['prediction_time'] = pd.to_datetime(ledger.prediction_time, errors='raise')
    if len(ledger) != 192168 or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any():
        raise ValueError('Frozen ledger size or uniqueness changed')
    report = {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': SOURCE_SHA},
        'previous_diagnostics': {'path': relative(previous_diagnostics_path), 'sha256': DIAGNOSTICS_SHA},
        'source_features': source['feature_dataset'], 'source_scores': source['score_export'],
        'model_provenance': provenance, 'selected_artifacts': selected,
        'matched_candidate_order': list(MATCHED), 'source_candidate_order': list(count.MATCHED),
        'feature_counts': count.FEATURE_COUNTS, 'comparisons': {name: list(pair) for name, pair in COMPARISONS.items()},
        'daily_cap': .1, 'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0,
        'new_model_selection': False, 'original_holdout_not_rescored': True,
        'definitions': {'prediction_time': 'approval', 'l2': 100., 'pair_method': 'topk', 'num_pair_per_sample': 10,
            'capture_pattern_bit_order': list(MATCHED), 'capture_patterns': list(PATTERNS),
            'pattern000': 'Known delayed rows with pattern 000 are common misses; pattern000 on-time or unknown rows are not called misses.',
            'pattern111': 'Known delayed rows caught by all three models.',
            'other_known_delayed': 'Caught by at least one frozen model. Counts only: the uncapped union is not evaluated as a new alert policy or reported as a new model recall.',
            'budget': 'Complete closed daily floor(0.1*N), no carryover. Unknown outcomes compete before masks. No subgroup cap.',
            'common_miss_rank': 'Per model: original full-day one-based rank, rank/N, and rank-floor(0.1*N). Closest is retrospective minimum across existing models, not a deployable selector.',
            'support_bins': list(sparse.SUPPORT_BINS), 'promise_bins': list(PROMISE_BINS),
            'volume_bins': list(VOLUME_BINS), 'rank_bins': list(RANK_BINS), 'capacity_gap_bins': list(GAP_BINS),
            'focus_phases': list(FOCUS_PHASES),
            'interpretation': 'Descriptive reused-development evidence only. Counts conserve complete daily budgets; marginal groups overlap and do not establish feature causality or individual slot donor/recipient relationships.'},
        'phases': {}, 'phase_summary': [], 'notes': [
            'All three fixed model families and daily budgets remain unchanged. No model or selected artifact is deserialized.',
            'Three evaluation months are repeatedly used development retests; the original retained test is not rescored.',
            'Historical validation uses actual customer delivery strictly before each original cutoff. Repeated historical months across cutoffs are not pooled as independent samples.',
            'All observed routes and declared empty bins are retained; common-miss and other-delay denominators partition each marginal.',
            'Unknown labels never become delayed/on-time outcomes. Ranking and capacity always use the complete original day.',
            'A minimum existing rank across models is only a hindsight description; no oracle selection, new blended scores, union policy or suitability claim is made.']}
    expected_phases, verified_rows = set(), 0
    for fold in source['folds']:
        schedule = [(row['month'], 'validation') for row in fold['schedule']['validation_months']]
        for month, role in [*schedule, (fold['name'], 'evaluation')]:
            key = f'{fold["name"]}/{month}/{role}'
            expected_phases.add((fold['name'], role, month))
            frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            fingerprint = (fold['order_id_fingerprints']['validation_full_by_month'][month]
                           if role == 'validation' else fold['order_id_fingerprints']['evaluation'])
            if frame.empty or order_fingerprint(frame) != fingerprint:
                raise ValueError('Frozen full-day scoring identities changed')
            part = ledger.loc[ledger.fold.eq(fold['name']) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            known, scores, context = count.verify_phase_ledger(frame, part, fold['schedule']['evaluation_start'], role,
                fold['experiment']['models'], month)
            diagnostic = diagnose_phase(frame, scores, known, focus=key in FOCUS_PHASES)
            reconcile_previous(diagnostic, previous_diagnostics['phases'][key])
            report['phases'][key] = {'fold': fold['name'], 'month': month, 'ledger_role': role,
                'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                'order_id_fingerprint': fingerprint, 'context': context, **diagnostic}
            report['phase_summary'].append({'phase': key, 'fold': fold['name'], 'month': month,
                'role': report['phases'][key]['role'], **diagnostic['common_misses']['summary']})
            verified_rows += len(part)
            print(f'{key}: common missed={diagnostic["common_misses"]["summary"]["common_missed_delays"]}', flush=True)
    if len(expected_phases) != 12 or verified_rows != len(ledger) or set(zip(ledger.fold, ledger.role, ledger.model_version, strict=True)) != expected_phases:
        raise ValueError('Unexpected or missing scoring phases')
    report['development_pool'] = pool_development(report['phases'])
    check_sources()
    report['source_hashes'] = [{'path': relative(path), 'sha256': expected} for path, expected in files.items()]
    report['verification'] = {'scoring_phases_verified': 12, 'candidate_metric_groups_verified': 36,
        'score_rows_verified': verified_rows, 'monthly_model_hashes_checked': 24, 'selected_artifact_hashes_checked': 3,
        'source_and_model_hashes_checked': len(files), 'source_hashes_checked_before_and_after': True,
        'previous_78_candidate_records_and_design_contract_unchanged': True,
        'old_two_pair_summaries_routes_days_and_allocations_reconciled': True,
        'pairwise_contrasts': 36, 'eight_exclusive_capture_patterns_per_phase': True,
        'common_miss_denominators_and_all_declared_marginals_partition': True,
        'complete_day_ranks_and_capacity_before_known_masks': True,
        'three_disjoint_development_months_pooled_without_historical_repeats': True,
        'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0, 'new_model_selection': False,
        'original_holdout_not_rescored': True}
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
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/handover_count.json')
    parser.add_argument('--previous-diagnostics', type=Path, default=ROOT / 'reports/stage4/handover_count_diagnostics.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/handover_common_misses.json')
    args = parser.parse_args(argv)
    try:
        output = validate_output(args.output, args.source_report)
    except ValueError as exc:
        parser.error(str(exc))
    report = build_report(args.source_report, args.data_dir, args.previous_diagnostics)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(f'Wrote {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
