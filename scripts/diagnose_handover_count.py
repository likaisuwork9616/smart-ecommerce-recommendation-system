"""Account for frozen 101/102/104-column daily reminder rankings.

The CLI reads only hashed features and a completed score ledger. It never
loads models, fits, replays, calibrates, searches thresholds or selects models.
All subgroup counts retain the original complete-day ranking and capacity.
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
from scripts.delay_route_exchanges import ALLOCATION_FIELDS, COUNT_FIELDS, _row_counts
from scripts.diagnose_budget_misses import PROMISE_BINS, RANK_BINS, daily_rank_bins
from scripts import diagnose_handover_history as history
from scripts import diagnose_handover_sparse as sparse
from scripts.diagnose_objective_misses import promise_bins
from scripts.diagnose_rank_batch_size import _assert_partition, _day_info, _known_labels, _positions
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest

ANALYSIS = 'handover_count_three_way_route_diagnostics'
BASELINE = history.BASELINE
HANDOVER104 = history.NEW
NEW = 'xgboost_rank_handover_count_102_l2_100_topk_10'
MATCHED = (BASELINE, HANDOVER104, NEW)
FEATURE_COUNTS = {BASELINE: 101, HANDOVER104: 104, NEW: 102}
FEATURE_ADDITIONS = {BASELINE: (), HANDOVER104: tuple(ADDED_FEATURES), NEW: tuple(ADDED_FEATURES[:1])}
COMPARISONS = {'baseline101_to_count102': (BASELINE, NEW),
               'handover104_to_count102': (HANDOVER104, NEW)}
FOCUS_PHASES = (*history.FOCUS_PHASES, '2018-04/2018-04/evaluation')
REGRESSION_GROUPS = ('all_original_lost_delays', 'sparse_short_non_SP_RJ',
                     'supported_long_SP_RJ', 'other_original_lost_delays')


def _relabel(value, mapping):
    """Rename exact local candidate tokens without touching imported globals."""
    if isinstance(value, dict):
        return {mapping.get(key, key): _relabel(part, mapping) for key, part in value.items()}
    if isinstance(value, list):
        return [_relabel(part, mapping) for part in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def pair_diagnostics(frame, scores, known, old_candidate, new_candidate, *, keep_cross=False):
    """Reuse pure aggregators with local score aliases and actual-ID output."""
    if (old_candidate == new_candidate or not {old_candidate, new_candidate} <= set(scores)
            or not {old_candidate, new_candidate} <= set(FEATURE_COUNTS)):
        raise ValueError('Require two distinct available candidates')
    local = {history.BASELINE: scores[old_candidate], history.NEW: scores[new_candidate]}
    mapped = _relabel(history.diagnose_phase(frame, local, known, keep_cross=keep_cross),
                      {history.BASELINE: old_candidate, history.NEW: new_candidate})
    result = mapped['handover_features']
    old_features = list(FEATURE_ADDITIONS[old_candidate])
    new_features = list(FEATURE_ADDITIONS[new_candidate])
    result['comparison'] = {
        'old_candidate': old_candidate, 'new_candidate': new_candidate,
        'old_feature_count': FEATURE_COUNTS[old_candidate], 'new_feature_count': FEATURE_COUNTS[new_candidate],
        'old_extra_features_vs_101': old_features, 'new_extra_features_vs_101': new_features,
        'added_features': [name for name in new_features if name not in old_features],
        'removed_features': [name for name in old_features if name not in new_features],
        'prediction_time': 'approval', 'fixed_l2': 100., 'pair_method': 'topk',
        'fixed_num_pair_per_sample': 10, 'fixed_daily_cap': .1,
        'interpretation': 'Matched inputs only; all models relearn splits. Full closed daily batches receive floor(0.1*N) reminders before outcome masks. No subgroup budget or causal feature attribution.',
    }
    known, labels = _known_labels(frame, known)
    old = apply_alert_policy(frame, scores[old_candidate], 0., .1, raw_scores=scores[old_candidate])
    new = apply_alert_policy(frame, scores[new_candidate], 0., .1, raw_scores=scores[new_candidate])
    groups = sparse.group_definitions(frame)
    result['history_support_bins'] = []
    for name in sparse.SUPPORT_BINS:
        row = _row_counts(np.flatnonzero(groups['support'] == name), known, labels, old, new)
        result['history_support_bins'].append({'support_bin': name, **row,
            'small_sample': not row['minimum_sample_met'], 'budget_scope': 'Row subgroup after complete-day ranking; no new cap.'})
    _assert_partition(result['history_support_bins'], result['summary'], COUNT_FIELDS)
    # The shared marginal accountant retains observed promise bins. Add empty
    # declared bins explicitly without inventing routes or daily capacity.
    empty = _row_counts(np.asarray([], int), known, labels, old, new)
    promise_lookup = {row['promise_bin']: row for row in result['promise_days']}
    result['promise_days'] = [promise_lookup.get(name, {'promise_bin': name, **empty,
        **dict.fromkeys(ALLOCATION_FIELDS, 0)}) for name in PROMISE_BINS]
    _assert_partition(result['promise_days'], result['summary'], COUNT_FIELDS)
    result['intersection_cells'] = []
    for support, promise, route in sparse.CELL_DEFINITIONS:
        key = sparse.cell_key(support, promise, route)
        row = _row_counts(np.flatnonzero(groups['cells'] == key), known, labels, old, new)
        result['intersection_cells'].append({'cell': key, 'support_bin': support,
            'promise_group': promise, 'route_group': route, **row, 'small_sample': not row['minimum_sample_met']})
    _assert_partition(result['intersection_cells'], result['summary'], COUNT_FIELDS)
    if keep_cross:
        detailed = _relabel(sparse.diagnose_phase(frame, local, known),
                            {history.BASELINE: old_candidate, history.NEW: new_candidate})
        if any(detailed['summary'][field] != result['summary'][field] for field in COUNT_FIELDS):
            raise AssertionError('Detailed cells and route/volume accounts disagree')
        result['sparse_intersection_detail'] = detailed
    return {'volume_context': mapped['volume_context'], **result}


def regression_cohorts(frame, scores, known):
    """Freeze 101->104 losses before asking whether 102 recovers them."""
    if set(scores) != set(MATCHED):
        raise ValueError('Require all three prespecified score cohorts')
    known, labels = _known_labels(frame, known)
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED}
    ranks = {c: daily_rank_bins(frame, scores[c]) for c in MATCHED}
    positions = {c: _positions(frame, scores[c]) for c in MATCHED}
    days, sizes = _day_info(frame)
    capacity = np.asarray([sizes[day] // 10 for day in days])
    groups = sparse.group_definitions(frame)
    original = known & (labels == 1) & alerts[BASELINE] & ~alerts[HANDOVER104]
    first = original & (groups['support'] != 'history_ge5') & (groups['promise_group'] == 'promise0_30') & (groups['route_group'] == 'other_route')
    second = original & (groups['support'] == 'history_ge5') & (groups['promise_group'] == 'promise31plus') & (groups['route_group'] == 'SP_RJ')
    masks = dict(zip(REGRESSION_GROUPS, (original, first, second, original & ~first & ~second), strict=True))
    routes, promises, support = groups['routes'], groups['promise_bin'], groups['support']

    def aggregate(mask):
        rows = int(mask.sum())
        models = {}
        for candidate in MATCHED:
            rank_bins = {name: int((mask & (ranks[candidate] == name)).sum()) for name in RANK_BINS}
            gaps = (positions[candidate] - capacity)[mask]
            captured = int((mask & alerts[candidate]).sum())
            if sum(rank_bins.values()) != rows or rank_bins['<=10%'] != captured:
                raise AssertionError('Frozen-regression ranks and alerts do not reconcile')
            models[candidate] = {'in_top10': captured, 'out_of_top10': rows - captured,
                'rank_bins': rank_bins, 'off_top10_gap_slots': sparse._aggregate(gaps)}
        return {'cohort_rows': rows, 'cohort_small_sample': rows < 5,
                'count102_recovered': models[NEW]['in_top10'],
                'count102_still_missed': models[NEW]['out_of_top10'], 'models': models}

    result = {}
    for name, mask in masks.items():
        row = aggregate(mask)
        row['routes'] = [{'state_route': route, **aggregate(mask & (routes == route))} for route in sorted(set(routes))]
        row['promise_days'] = [{'promise_bin': value, **aggregate(mask & (promises == value))} for value in PROMISE_BINS]
        row['support_bins'] = [{'support_bin': value, **aggregate(mask & (support == value))} for value in sparse.SUPPORT_BINS]
        for dimension in ('routes', 'promise_days', 'support_bins'):
            if sum(part['cohort_rows'] for part in row[dimension]) != row['cohort_rows']:
                raise AssertionError('Frozen-regression marginal groups do not partition')
        result[name] = row
    if sum(result[name]['cohort_rows'] for name in REGRESSION_GROUPS[1:]) != result[REGRESSION_GROUPS[0]]['cohort_rows']:
        raise AssertionError('Frozen-regression target groups and remainder do not partition')
    return {'definition': 'Known delayed orders caught by frozen101 but missed by frozen104. Cohorts are defined without count102 scores; each model is ranked on the original full day.',
        'reference_candidates': [BASELINE, HANDOVER104], 'recovery_candidate': NEW,
        'new_model_selection': False, 'cohorts': result,
        'interpretation': 'These are retrospective diagnostic cohorts. Recovery of an old loss is insufficient unless new losses and all other routes are also counted. Marginals overlap and are never added together.'}


def diagnose_phase(frame, scores, known, *, keep_cross=False):
    if not isinstance(frame, pd.DataFrame) or frame.empty or set(scores) != set(MATCHED):
        raise ValueError('Require a nonempty full phase with all three fixed candidates')
    contrasts = {name: pair_diagnostics(frame, scores, known, old, new, keep_cross=keep_cross)
                 for name, (old, new) in COMPARISONS.items()}
    old = history.diagnose_phase(frame, {BASELINE: scores[BASELINE], HANDOVER104: scores[HANDOVER104]}, known)
    return {'comparisons': contrasts,
        'baseline101_to_handover104': {'summary': old['handover_features']['summary']},
        'regression_cohorts': regression_cohorts(frame, scores, known),
        'verification': {'complete_day_ranks_before_masks': True, 'all_routes_retained': True,
            'support_0_1_to_4_ge5_and_12_cells_partition': True,
            'declared_empty_bins_retained': True, 'no_subgroup_reranking_or_capacity': True,
            'actual_candidate_ids_after_local_score_aliases': True}}


def verify_phase_ledger(frame, ledger, cutoff, role, expected_models, month):
    """Reconcile all three complete score cohorts and their actual metrics."""
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
    if len(ledger) != len(frame) * 3 or set(ledger.candidate) != set(MATCHED):
        raise ValueError('Require exactly three complete full-batch candidate cohorts')
    scores, context = {}, {}
    for candidate in MATCHED:
        part = ledger.loc[ledger.candidate.eq(candidate)]
        if part.order_id.duplicated().any() or len(part) != len(frame) or set(part.order_id) != set(frame.order_id):
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


def validate_source_contract(source, previous, specification):
    """Keep all 77 earlier metric records, splits, features and versions frozen."""
    if (source.get('status') != 'ok' or source.get('experiment') != 'handover_count_ablation'
            or source.get('only_changed_component') != 'single_seller_handover_count_feature'
            or source.get('daily_cap') != .1
            or source.get('matched_candidate_order') != list(MATCHED)
            or source.get('new_candidate_order') != [NEW]
            or source.get('reg_lambda') != 100. or source.get('pair_method') != 'topk'
            or source.get('added_features') != [ADDED_FEATURES[0]]
            or source.get('num_pair_per_sample') != 10):
        raise ValueError('Require the completed fixed-approval L2=100 topk10 count-only experiment')
    previous_order = previous.get('candidate_order', [])
    if (previous.get('status') != 'ok' or previous.get('experiment') != 'handover_history_features'
            or len(previous_order) != 77 or len(set(previous_order)) != 77
            or previous.get('matched_candidate_order') != list(history.MATCHED)
            or source.get('candidate_order') != [*previous_order, NEW]
            or source.get('source_features') != {key: previous.get('feature_dataset', {}).get(key) for key in ('path', 'sha256')}
            or source.get('source_scores') != {key: previous.get('score_export', {}).get(key) for key in ('path', 'sha256')}
            or any(source.get(key) != previous.get(key) for key in
                   ('feature_dataset', 'source_files', 'source_candidate_versions'))):
        raise ValueError('Require the unchanged 77-candidate source and feature provenance')
    if any(source.get(key) != value for key, value in specification.items()):
        raise ValueError('Completed report changed its predeclared specification')
    designs = source.get('candidate_specifications', {})
    if set(designs) != set(MATCHED):
        raise ValueError('Require all three declared candidate designs')
    base = designs[BASELINE]
    if len(base.get('numeric_features', [])) + len(base.get('categorical_features', [])) != 101:
        raise ValueError('Require the frozen 101-column baseline')
    for candidate in history.MATCHED:
        if any(designs[candidate].get(key) != previous.get('candidate_specifications', {}).get(candidate, {}).get(key)
               for key in ('numeric_features', 'categorical_features', 'classifier_parameters')):
            raise ValueError('Frozen 101/104 feature designs or classifier parameters changed')
    for candidate, features in ((HANDOVER104, ADDED_FEATURES), (NEW, ADDED_FEATURES[:1])):
        extended = designs[candidate]
        if (extended.get('numeric_features') != [*base['numeric_features'], *features]
                or extended.get('categorical_features') != base.get('categorical_features')
                or extended.get('classifier_parameters') != base.get('classifier_parameters')):
            raise ValueError('Only the declared numeric inputs may change')
    prior_folds = {fold['name']: fold for fold in previous['folds']}
    if len(prior_folds) != 3 or len(source['folds']) != 3 or {f['name'] for f in source['folds']} != set(prior_folds):
        raise ValueError('Require three unchanged development schedules')
    for fold in source['folds']:
        prior = prior_folds[fold['name']]
        if any(fold[key] != prior[key] for key in ('schedule', 'validation_maturity', 'order_id_fingerprints')):
            raise ValueError('Frozen historical schedule, maturity or scoring identities changed')
        original, current = prior['experiment']['models'], fold['experiment']['models']
        if set(original) != set(previous_order) or set(current) != set(source['candidate_order']) or any(current[c] != value for c, value in original.items()):
            raise ValueError('Frozen previous candidate metric records changed')
    prior_training = {row['month']: row for row in previous['monthly_training']}
    if set(prior_training) != set(history.MONTHS) or len(source['monthly_training']) != 8 or {row['month'] for row in source['monthly_training']} != set(history.MONTHS):
        raise ValueError('Require eight unchanged monthly fit schedules')
    for row in source['monthly_training']:
        prior = prior_training[row['month']]
        if row['split'] != prior['split'] or set(row['models']) != set(MATCHED):
            raise ValueError('Monthly scoring cohort or matched versions changed')
        for candidate in history.MATCHED:
            if any(row['models'][candidate][key] != prior['models'][candidate][key]
                   for key in ('version_artifact', 'training_split')):
                raise ValueError('Frozen 101/104 monthly provenance changed')


def build_report(source_path, data_dir):
    source_path, data_dir = Path(source_path), Path(data_dir)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    previous_path = ROOT / source['source_report']['path']
    spec_path = source_path.with_name('handover_count_specification.json')
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    files = {source_path: sha256(source_path), previous_path: source['source_report']['sha256'],
        spec_path: source['specification_sha256'], feature_path: source['feature_dataset']['sha256'],
        score_path: source['score_export']['sha256'], ROOT / source['source_features']['path']: source['source_features']['sha256'],
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
    features = read_features(feature_path, data_dir)
    if len(features) != 70844 or len(features.columns) != 137 or features.prediction_time.ge('2018-05-01').any():
        raise ValueError('Require the unchanged 70,844-row 137-column feature cache before May 2018')
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    ledger['prediction_time'] = pd.to_datetime(ledger.prediction_time, errors='raise')
    if (len(ledger) != 192168 or len(ledger) != source['score_export']['rows']
            or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Frozen score size or uniqueness changed')
    report = {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': files[source_path]},
        'previous_handover_report': source['source_report'], 'specification_sha256': source['specification_sha256'],
        'source_features': source['feature_dataset'], 'source_feature_reference': source['source_features'],
        'source_scores': source['score_export'], 'model_provenance': provenance, 'selected_artifacts': selected,
        'matched_candidate_order': list(MATCHED), 'feature_counts': FEATURE_COUNTS,
        'comparisons': {key: list(pair) for key, pair in COMPARISONS.items()},
        'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0, 'new_model_selection': False,
        'original_holdout_not_rescored': True, 'daily_cap': .1,
        'definitions': {'prediction_time': 'approval', 'l2': 100., 'pair_method': 'topk', 'num_pair_per_sample': 10,
            'count102_added_features': [ADDED_FEATURES[0]], 'handover104_added_features': list(ADDED_FEATURES),
            'support_bins': {'history0': 'event_count == 0', 'history1_4': '1 <= event_count < 5', 'history_ge5': 'event_count >= 5'},
            'promise_groups': {'promise0_30': 'estimated_delivery_days <= 30', 'promise31plus': 'estimated_delivery_days > 30, including fractional 30.x days'},
            'promise_bins': list(PROMISE_BINS), 'rank_bins': list(RANK_BINS),
            'focus_phases': list(FOCUS_PHASES), 'regression_groups': list(REGRESSION_GROUPS),
            'budget': 'Complete closed daily batch floor(0.1*N), no carryover. Unknown outcomes compete before masking. No subgroup reranking or cap.',
            'rank_gap': 'One-based full-day rank minus that full day floor(0.1*N); positive means outside reminder capacity.',
            'interpretation': 'Descriptive reused development analysis. Original 101->104 losses are defined before inspecting 102 scores; no subgroup selector or causal feature claim.'},
        'phases': {}, 'phase_summary': [],
        'notes': ['Only hashed features and ledger are aggregated; model hashes are checked without loading, replay, fitting or selecting.',
            'All three evaluation months are reused development retests. Historical validation retains actual delivery strictly before its original cutoff; repeated validation months are not independent cohorts.',
            'All 77 previous candidate metric records are frozen. The training runner fits eight count102 models and replays sixteen frozen 101/104 versions; the other 75 candidates and 600 archived monthly versions are not rescored.',
            'Every observed route and every declared support, promise, volume and intersection bin is retained. Empty groups have zero counts and null recall.',
            'Subgroups are assessed after complete daily rankings. Marginals overlap; daily route/cell flows are aggregate identities, not individual donor/recipient matches or feature causality.',
            'The original retained test, default production model and visualizations remain unchanged.']}
    expected_phases, verified_rows = set(), 0
    for fold in source['folds']:
        prior_fold = next(row for row in previous['folds'] if row['name'] == fold['name'])
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
            old_part = part.loc[part.candidate.isin(history.MATCHED)]
            prior_known, _, prior_context = history.verify_phase_ledger(frame, old_part, fold['schedule']['evaluation_start'],
                role, prior_fold['experiment']['models'], month)
            if not np.array_equal(known, prior_known) or any(context[c] != prior_context[c] for c in history.MATCHED):
                raise ValueError('Frozen 101/104 replay context changed')
            diagnostic = diagnose_phase(frame, scores, known, keep_cross=key in FOCUS_PHASES)
            report['phases'][key] = {'fold': fold['name'], 'month': month, 'ledger_role': role,
                'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                'order_id_fingerprint': fingerprint, 'context': context, **diagnostic}
            for name, value in diagnostic['comparisons'].items():
                report['phase_summary'].append({'phase': key, 'comparison': name, 'fold': fold['name'], 'month': month,
                    'role': report['phases'][key]['role'], **value['summary']})
            verified_rows += len(part)
            print(f'{key}: ' + ', '.join(f'{name} netTP={value["summary"]["net_TP"]}' for name, value in diagnostic['comparisons'].items()), flush=True)
    if len(expected_phases) != 12 or verified_rows != len(ledger) or set(zip(ledger.fold, ledger.role, ledger.model_version, strict=True)) != expected_phases:
        raise ValueError('Unexpected or missing ledger phases')
    april = report['phases']['2018-04/2018-04/evaluation']['regression_cohorts']['cohorts']
    if (april['sparse_short_non_SP_RJ']['cohort_rows'] != 3
            or april['supported_long_SP_RJ']['cohort_rows'] != 2
            or {row['state_route'] for row in april['sparse_short_non_SP_RJ']['routes'] if row['cohort_rows']} != {'SP->MG', 'SP->PE', 'SP->SP'}):
        raise ValueError('Original published April diagnostic cohorts changed')
    check_sources()
    report['source_hashes'] = [{'path': relative(path), 'sha256': expected} for path, expected in files.items()]
    report['verification'] = {'scoring_phases_verified': 12, 'candidate_metric_groups_verified': 36,
        'score_rows_verified': verified_rows, 'monthly_model_hashes_checked': 24, 'selected_artifact_hashes_checked': 3,
        'source_and_model_hashes_checked': len(files), 'source_hashes_checked_before_and_after': True,
        'source_contract_and_previous_77_candidate_metrics_unchanged': True,
        'frozen101_and_frozen104_metrics_reconciled_to_prior_report': True,
        'pairwise_contrasts': 24, 'detailed_intersection_phases': len(FOCUS_PHASES),
        'intersection_cells_per_comparison_phase': 12, 'support_bins_per_comparison_phase': 3,
        'original_april_lost_3_sparse_and_2_supported_reproduced': True,
        'all_original_daily_budgets_and_availability_masks_reproduced': True,
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
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/handover_count_diagnostics.json')
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
