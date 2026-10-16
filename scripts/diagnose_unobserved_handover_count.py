"""Audit one added pending-handover count using frozen full-day score ledgers."""
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

from scripts import diagnose_handover_history as history
from scripts import diagnose_handover_count as completed
from scripts.compare_backlog_objectives import read_features
from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_route_exchanges import COUNT_FIELDS, _row_counts
from scripts.diagnose_budget_misses import PROMISE_BINS, RANK_BINS, daily_rank_bins
from scripts.diagnose_objective_misses import promise_bins
from scripts.diagnose_rank_batch_size import _assert_partition, _known_labels
from scripts.improve_budget_ranking import relative, sha256

BASELINE = history.BASELINE
NEW = 'xgboost_rank_unobserved_handover_count_102_l2_100_topk_10'
MATCHED = (BASELINE, NEW)
FEATURE = 'seller_unobserved_handover_pending_count_90d'
ANALYSIS = 'unobserved_handover_count_route_and_common_miss_diagnostics'
COUNT_BINS = ('missing_seller', 'zero', 'one_to_four', 'five_to_nineteen', 'twenty_plus')
FROZEN_SOURCE_SHA = '57077703b7160c84eca8ab517f2f3325d105ea481bfa5c657f057fbbd0a3f9b3'


def count_bins(frame):
    values = pd.to_numeric(frame[FEATURE], errors='raise').to_numpy(dtype=float)
    valid = ~np.isnan(values)
    if (not np.isfinite(values[valid]).all() or (values[valid] < 0).any()
            or not np.equal(values[valid], np.floor(values[valid])).all()):
        raise ValueError('Pending counts must be missing or nonnegative integers')
    return np.select((~valid, values == 0, values <= 4, values <= 19),
                     COUNT_BINS[:-1], default=COUNT_BINS[-1])


def diagnose_phase(frame, scores, known):
    if set(scores) != set(MATCHED):
        raise ValueError('Require the original101 and new pending-count102 scores')
    local = {history.BASELINE: scores[BASELINE], history.NEW: scores[NEW]}
    mapped = completed._relabel(history.diagnose_phase(frame, local, known, keep_cross=True),
                                {history.NEW: NEW})
    exchange = mapped.pop('handover_features')
    exchange['comparison'] = {
        'old_candidate': BASELINE, 'new_candidate': NEW,
        'old_feature_count': 101, 'new_feature_count': 102, 'added_features': [FEATURE],
        'prediction_time': 'approval', 'fixed_l2': 100., 'pair_method': 'topk',
        'fixed_num_pair_per_sample': 10, 'fixed_daily_cap': .1,
        'interpretation': 'Only one input added. Complete-day ranks precede known-label masks; no subgroup quota, threshold search or causal attribution.',
    }
    known, labels = _known_labels(frame, known)
    old, new = (apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in MATCHED)
    bins = count_bins(frame)
    exchange['pending_count_bins'] = [
        {'count_bin': name, **_row_counts(np.flatnonzero(bins == name), known, labels, old, new)}
        for name in COUNT_BINS]
    _assert_partition(exchange['pending_count_bins'], exchange['summary'], COUNT_FIELDS)
    return {**mapped, 'pending_count_features': exchange}


def common_miss_recovery(frame, frozen_scores, scores, known):
    """Freeze the preceding three-model misses before inspecting new scores."""
    if set(frozen_scores) != set(completed.MATCHED) or set(scores) != set(MATCHED):
        raise ValueError('Require all three frozen scores and both experiment scores')
    known, labels = _known_labels(frame, known)
    frozen_alerts = [apply_alert_policy(frame, frozen_scores[c], 0., .1, raw_scores=frozen_scores[c])
                     for c in completed.MATCHED]
    mask = known & (labels == 1) & ~np.column_stack(frozen_alerts).any(axis=1)
    alerts = apply_alert_policy(frame, scores[NEW], 0., .1, raw_scores=scores[NEW])
    ranks = daily_rank_bins(frame, scores[NEW])

    def row(selected):
        return {'cohort_rows': int(selected.sum()), 'recovered': int((selected & alerts).sum()),
                'still_missed': int((selected & ~alerts).sum()),
                'new_model_rank_bins': {name: int((selected & (ranks == name)).sum()) for name in RANK_BINS}}

    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    promises, bins = promise_bins(frame).to_numpy(), count_bins(frame)
    result = row(mask)
    result['routes'] = [{'state_route': name, **row(mask & (routes == name))} for name in sorted(set(routes))]
    result['promise_days'] = [{'promise_bin': name, **row(mask & (promises == name))} for name in PROMISE_BINS]
    result['pending_count_bins'] = [{'count_bin': name, **row(mask & (bins == name))} for name in COUNT_BINS]
    for key in ('routes', 'promise_days', 'pending_count_bins'):
        _assert_partition(result[key], result, ('cohort_rows', 'recovered', 'still_missed'))
    result['definition'] = 'Known delayed and missed by all frozen101/completed-count102/handover104, defined without the new model scores; no extra reminders.'
    return result


def verify_phase_ledger(frame, ledger, cutoff, role, models, month):
    if role not in ('validation', 'evaluation') or len(ledger) != len(frame) * 2 or set(ledger.candidate) != set(MATCHED):
        raise ValueError('Require exactly two complete scoring cohorts')
    known = (frame.label_available_time.lt(pd.Timestamp(cutoff)).to_numpy()
             if role == 'validation' else np.ones(len(frame), bool))
    flags = known if role == 'validation' else np.zeros(len(frame), bool)
    scores, context = {}, {}
    for candidate in MATCHED:
        part = ledger.loc[ledger.candidate.eq(candidate)]
        if part.order_id.duplicated().any() or len(part) != len(frame) or set(part.order_id) != set(frame.order_id):
            raise ValueError('Changed scoring identities')
        part = part.set_index('order_id').loc[frame.order_id]
        if (not part.role.eq(role).all() or not part.model_version.eq(month).all()
                or part.known_at_selection.dtype != bool):
            raise ValueError('Changed phase or availability flag type')
        np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
        np.testing.assert_array_equal(part.known_at_selection.to_numpy(), flags)
        np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
        np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], frame.delayed.to_numpy()[known])
        values = part.delay_score.to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError('Invalid bounded rank score')
        alerts = apply_alert_policy(frame, values, 0., .1, raw_scores=values)
        np.testing.assert_array_equal(part.predicted_delayed.to_numpy(), alerts.astype(int))
        metrics = alert_metrics(frame.delayed.to_numpy()[known], values[known], alerts[known])
        batch = batch_audit(frame, alerts, .1, known)
        expected = (models[candidate]['validation_by_month'][month] if role == 'validation' else
                    {'known_outcome_metrics': models[candidate]['development_evaluation'],
                     'full_batch': models[candidate]['evaluation_batch']})
        if metrics != expected['known_outcome_metrics'] or batch != expected['full_batch']:
            raise ValueError('Training report metrics or daily budget changed')
        scores[candidate], context[candidate] = values, {'known_outcome_metrics': metrics, 'full_batch': batch}
    return known, scores, context


def build_report(source_path, data_dir):
    source_path = Path(source_path).resolve()
    source = json.loads(source_path.read_text(encoding='utf-8'))
    files = {source_path: sha256(source_path)}

    def protect(info):
        path = ROOT / info['path']
        if sha256(path) != info['sha256']:
            raise ValueError(f'Changed source: {path}')
        files[path] = info['sha256']
        return path

    prior_path = protect(source['source_report'])
    if sha256(prior_path) != FROZEN_SOURCE_SHA:
        raise ValueError('Require the exact frozen78-candidate source')
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    spec_path = source_path.with_name('unobserved_handover_count_specification.json')
    specification = json.loads(spec_path.read_text(encoding='utf-8'))
    if sha256(spec_path) != source['specification_sha256'] or any(source.get(k) != v for k, v in specification.items()):
        raise ValueError('Experiment changed its predeclared specification')
    files[spec_path] = sha256(spec_path)
    if (source['status'] != 'ok' or source['matched_candidate_order'] != list(MATCHED)
            or source['new_candidate_order'] != [NEW] or source['added_features'] != [FEATURE]
            or source['daily_cap'] != .1 or source['reg_lambda'] != 100.
            or source['pair_method'] != 'topk' or source['num_pair_per_sample'] != 10
            or source['candidate_order'] != [*prior['candidate_order'], NEW]):
        raise ValueError('Only the declared pending-count input may change')
    for fold, old in zip(source['folds'], prior['folds'], strict=True):
        if any(fold[k] != old[k] for k in ('name', 'schedule', 'validation_maturity', 'order_id_fingerprints')):
            raise ValueError('Changed folds, maturity or full-day identities')
        if any(fold['experiment']['models'].get(c) != v for c, v in old['experiment']['models'].items()):
            raise ValueError('Frozen78-candidate metric context changed')
        protect(fold['research_artifact'])
    for month in source['monthly_training']:
        for model in month['models'].values():
            protect(model['version_artifact'])
    frame = read_features(protect(source['feature_dataset']), data_dir)
    ledger = pd.read_csv(protect(source['score_export']), float_precision='round_trip', parse_dates=['prediction_time'])
    old_ledger = pd.read_csv(protect(prior['score_export']), float_precision='round_trip', parse_dates=['prediction_time'])
    if len(frame) != 70844 or len(frame.columns) != 138 or frame.prediction_time.ge('2018-05-01').any():
        raise ValueError('Require the unchanged pre-May cohort plus exactly one cache column')
    phases, summaries, verified_rows = {}, [], 0
    for fold in source['folds']:
        old_fold = next(x for x in prior['folds'] if x['name'] == fold['name'])
        months = [('validation', x['month']) for x in fold['schedule']['validation_months']] + [('evaluation', fold['name'])]
        for role, month in months:
            key = f'{fold["name"]}/{month}/{role}'
            batch = frame.loc[frame.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            part = ledger.loc[ledger.fold.eq(fold['name']) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            oldpart = old_ledger.loc[old_ledger.fold.eq(fold['name']) & old_ledger.role.eq(role) & old_ledger.model_version.eq(month)]
            known, scores, context = verify_phase_ledger(batch, part, fold['schedule']['evaluation_start'], role, fold['experiment']['models'], month)
            oldknown, oldscores, _ = completed.verify_phase_ledger(batch, oldpart, fold['schedule']['evaluation_start'], role, old_fold['experiment']['models'], month)
            np.testing.assert_array_equal(known, oldknown)
            np.testing.assert_allclose(scores[BASELINE], oldscores[BASELINE], rtol=0, atol=1e-12)
            diagnostic = diagnose_phase(batch, scores, known)
            recovery = common_miss_recovery(batch, oldscores, scores, known)
            phases[key] = {'fold': fold['name'], 'month': month,
                'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'historical_outcome_cutoff': fold['schedule']['evaluation_start'] if role == 'validation' else None,
                'context': context, **diagnostic, 'frozen_three_model_common_miss_recovery': recovery}
            summaries.append({'phase': key, 'fold': fold['name'], 'month': month, 'role': phases[key]['role'],
                              **diagnostic['pending_count_features']['summary'],
                              'previous_common_missed': recovery['cohort_rows'], 'common_missed_recovered': recovery['recovered']})
            verified_rows += len(part)
    if len(phases) != 12 or verified_rows != len(ledger):
        raise ValueError('Unexpected scoring phases or ledger rows')
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError('Source changed during diagnostic')
    return {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': files[source_path]},
        'source_hashes': [{'path': relative(p), 'sha256': h} for p, h in files.items()],
        'matched_candidate_order': list(MATCHED), 'added_features': [FEATURE], 'phases': phases,
        'phase_summary': summaries, 'verification': {'phases_verified': 12, 'candidate_metric_groups_verified': 24,
            'score_rows_verified': verified_rows, 'monthly_model_hashes_checked': 16, 'selected_artifact_hashes_checked': 3,
            'new_fit_count': 0, 'saved_versions_replayed_in_this_cli': 0, 'new_model_selection': False,
            'full_day_ranks_before_masks': True, 'original_holdout_not_rescored': True},
        'limitations': ['All phases are reused historical validation/development, not new unknown test performance.',
            'Route, promise, volume and support views overlap; do not sum across dimensions or give each a quota.',
            'Pending count is an unobserved-event proxy with missing cancellation, ingestion and static version clocks.',
            'Recovered common misses are descriptive and must be read with all newly lost delays; no feature causality.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/unobserved_handover_count.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/unobserved_handover_count_diagnostics.json')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == args.source_report.resolve() or output.suffix.lower() != '.json':
        parser.error('Require a separate aggregate JSON output')
    if output.exists() and json.loads(output.read_text(encoding='utf-8')).get('analysis') != ANALYSIS:
        parser.error('Refusing to overwrite another report')
    report = build_report(args.source_report, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(json.dumps({'report': relative(output), 'phases': len(report['phases']), 'new_fits': 0}), flush=True)
    return report


if __name__ == '__main__':
    main()
