"""Diagnose frozen daily ranker pair-focus contrasts without fitting or selecting models.

All orders rank in complete daily batches before known-outcome masks. Route
flows are accounting marginals, never arbitrary individual order transfers.
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
from scripts.delay_route_exchanges import analyze_route_exchanges
from scripts.diagnose_budget_misses import MIN_GROUP_POSITIVES, MIN_GROUP_ROWS, PROMISE_BINS, RANK_BINS, daily_rank_bins
from scripts.diagnose_objective_misses import promise_bins
from scripts.improve_budget_ranking import relative, sha256
from scripts.improve_feature_engineering import engineering_source_manifest

ANALYSIS = 'rank_pair_focus_matched_route_diagnostics'
CLASSIFIERS = ('xgboost_engineering_geo', 'xgboost_backlog_7_14d')
BASELINES = ('xgboost_rank_geo_l2_100', 'xgboost_rank_backlog_7_14d_l2_100')
NEW = ('xgboost_rank_geo_l2_100_topk_10', 'xgboost_rank_geo_l2_100_topk_40',
       'xgboost_rank_backlog_7_14d_l2_100_topk_10', 'xgboost_rank_backlog_7_14d_l2_100_topk_40')
MATCHED = (*CLASSIFIERS, *BASELINES, *NEW)
PREVIOUS_MATCHED = (*CLASSIFIERS, *BASELINES)
FOCUS_MONTHS = ('2017-07', '2017-09')


def regression_cohorts(frame, scores, known_mask):
    """Follow the backlog λ100 top20 errors relative to its unchanged classifier.

    The two disjoint known-outcome cohorts are fixed before inspecting top10/40:
    new on-time alerts and lost delayed alerts. Unknown labels are never read.
    """
    known = np.asarray(known_mask)
    if known.dtype != bool or known.ndim != 1 or len(known) != len(frame):
        raise ValueError('Require an aligned boolean known-outcome mask')
    if set(scores) != set(MATCHED):
        raise ValueError('Require all eight prespecified score cohorts')
    labels = np.full(len(frame), -1, dtype=int)
    observed = frame.loc[known, 'delayed'].to_numpy()
    if not np.isin(observed, [0, 1]).all():
        raise ValueError('Known outcomes must be binary')
    labels[known] = observed.astype(int)
    candidates = (CLASSIFIERS[1], BASELINES[1], *NEW[2:])
    alerts = {c: apply_alert_policy(frame, scores[c], 0., .1, raw_scores=scores[c]) for c in candidates}
    ranks = {c: daily_rank_bins(frame, scores[c]) for c in candidates}
    classifier, baseline = alerts[CLASSIFIERS[1]], alerts[BASELINES[1]]
    masks = {'added_on_time_alerts': known & (labels == 0) & ~classifier & baseline,
             'lost_delays': known & (labels == 1) & classifier & ~baseline}
    routes = frame.state_route.fillna('unknown').astype(str).to_numpy()
    promises = promise_bins(frame).to_numpy()

    def counts(cohort, support):
        selected = cohort & support
        n = int(selected.sum())
        models = {}
        for candidate in candidates:
            bins = {name: int((selected & (ranks[candidate] == name)).sum()) for name in RANK_BINS}
            caught = int((selected & alerts[candidate]).sum())
            if sum(bins.values()) != n or bins['<=10%'] != caught:
                raise AssertionError('Full-day ranks do not reconcile fixed regression cohorts')
            models[candidate] = {'in_top10': caught, 'out_of_top10': n - caught, 'rank_bins': bins}
        supported = int((known & support).sum())
        positives = int((known & support & (labels == 1)).sum())
        return {'cohort_rows': n, 'known_rows': supported, 'known_delayed_rows': positives,
                'minimum_sample_met': supported >= MIN_GROUP_ROWS and positives >= MIN_GROUP_POSITIVES,
                'cohort_small_sample': n < MIN_GROUP_POSITIVES, 'models': models}

    result = {}
    for name, selected in masks.items():
        overall = counts(selected, np.ones(len(frame), bool))
        groups = {
            'routes': [{'state_route': route, **counts(selected, routes == route)} for route in sorted(set(routes))],
            'promise_days': [{'promise_bin': value, **counts(selected, promises == value)} for value in PROMISE_BINS],
            'route_by_promise': [{'state_route': route, 'promise_bin': value,
                                  **counts(selected, (routes == route) & (promises == value))}
                                 for route, value in sorted(set(zip(routes, promises, strict=True)))],
        }
        for rows in groups.values():
            for field in ('cohort_rows', 'known_rows', 'known_delayed_rows'):
                if sum(row[field] for row in rows) != overall[field]:
                    raise AssertionError('Fixed cohort group support does not partition')
            for candidate in candidates:
                for field in ('in_top10', 'out_of_top10'):
                    if sum(row['models'][candidate][field] for row in rows) != overall['models'][candidate][field]:
                        raise AssertionError('Fixed cohort movement does not conserve counts')
        result[name] = {**overall, **groups}
    return {
        'definition': 'Backlog101 λ100 top20 ranking versus backlog101 classification: known newly alerted on-time orders and known lost delayed orders; descriptive cohorts, never a selector.',
        'candidates': list(candidates), 'baseline': BASELINES[1],
        'minimum_group_known_rows': MIN_GROUP_ROWS, 'minimum_group_delayed_rows': MIN_GROUP_POSITIVES,
        'interpretation': 'For added_on_time_alerts, out_of_top10 counts removed old false reminders. For lost_delays, in_top10 counts recovered old misses. Other newly lost/caught orders require the full pairwise contrasts.',
        'cohorts': result,
    }


def exchange_report(frame, old_scores, new_scores, known, *, keep_route_days=False, keep_cross=False):
    """Retain all groups while limiting repeated high-dimensional diagnostics."""
    result = analyze_route_exchanges(frame, old_scores, new_scores, known)
    if not keep_route_days:
        result.pop('route_day_allocations')
    promises = promise_bins(frame)
    grouped = analyze_route_exchanges(frame.assign(state_route=promises), old_scores, new_scores, known)
    result['promise_days'] = [dict(row, promise_bin=row['state_route']) for row in grouped['routes']]
    for row in result['promise_days']:
        del row['state_route']
    if keep_cross:
        route = frame.state_route.fillna('unknown').astype(str)
        grouped = analyze_route_exchanges(frame.assign(state_route=route + ' | ' + promises.astype(str)), old_scores, new_scores, known)
        result['route_by_promise'] = []
        for row in grouped['routes']:
            route, value = row['state_route'].split(' | ', 1)
            result['route_by_promise'].append({**row, 'state_route': route, 'promise_bin': value})
    return result


def pair_focus_exchanges(frame, scores, known, *, keep_route_days=False, keep_cross=False):
    if set(scores) != set(MATCHED):
        raise ValueError('Require all eight prespecified score cohorts')
    result = {}
    for candidate, baseline in zip(NEW, (BASELINES[0], BASELINES[0], BASELINES[1], BASELINES[1]), strict=True):
        value = exchange_report(frame, scores[baseline], scores[candidate], known,
                                keep_route_days=keep_route_days, keep_cross=keep_cross)
        value['comparison'] = {'baseline_topk_20': baseline, 'alternative': candidate,
                               'alternative_topk': int(candidate.rsplit('_', 1)[1]), 'fixed_l2': 100.}
        result[candidate] = value
    return result


def focus_month_diagnostics(frame, scores, known):
    """Describe classifier contrasts and fixed k20 error cohorts in either month.

    July and September are two independently measured historical cohorts. Their
    route and promise views overlap and must not be added to one another.
    """
    if set(scores) != set(MATCHED):
        raise ValueError('Require all eight prespecified score cohorts')
    references = {}
    for candidate in (BASELINES[1], *NEW[2:]):
        value = exchange_report(frame, scores[CLASSIFIERS[1]], scores[candidate], known,
                                keep_route_days=True, keep_cross=True)
        value['comparison'] = {'classification': CLASSIFIERS[1], 'daily_ranking': candidate,
                               'fixed_l2': 100., 'topk': 20 if candidate == BASELINES[1]
                               else int(candidate.rsplit('_', 1)[1])}
        references[candidate] = value
    return {'classification_references': references,
            'regression_cohorts': regression_cohorts(frame, scores, known)}


def joint_focus_summary(phases):
    """Show both months separately before a descriptive, never selected, sum."""
    focus = {value['month']: value for value in phases.values()
             if value['fold'] == '2017-12' and value['ledger_role'] == 'validation'
             and value['month'] in FOCUS_MONTHS}
    if set(focus) != set(FOCUS_MONTHS):
        raise ValueError('Require both prespecified July/September focus phases')
    rows = []
    for candidate in (BASELINES[1], *NEW[2:]):
        by_month = {}
        for month in FOCUS_MONTHS:
            phase = focus[month]
            current = phase['context'][candidate]['known_outcome_metrics']
            baseline = phase['context'][BASELINES[1]]['known_outcome_metrics']
            current_tp, baseline_tp = current['confusion_matrix'][1][1], baseline['confusion_matrix'][1][1]
            by_month[month] = {
                'true_positives': current_tp, 'false_positives': current['confusion_matrix'][0][1],
                'recall': current['recall'], 'net_TP_vs_topk_20': current_tp - baseline_tp,
            }
        rows.append({'candidate': candidate, 'topk': 20 if candidate == BASELINES[1]
                     else int(candidate.rsplit('_', 1)[1]), 'by_month': by_month,
                     'pooled_true_positives': sum(value['true_positives'] for value in by_month.values()),
                     'minimum_month_recall': min(value['recall'] for value in by_month.values()),
                     'net_TP_vs_topk_20': sum(value['net_TP_vs_topk_20'] for value in by_month.values()),
                     'neither_month_loses_TP_vs_topk_20': all(value['net_TP_vs_topk_20'] >= 0
                                                             for value in by_month.values())})
    return {'months': list(FOCUS_MONTHS), 'comparison_role': 'descriptive_historical_diagnosis_only',
            'selection_performed': False, 'fixed_l2': 100., 'backlog101': rows}


def compatibility_checks_from_phases(phases, targets):
    """Reconcile both frozen compatibility goals using verified ledger metrics."""
    if targets['used_for_selection'] is not False or targets['historical_outcome_cutoff'] != '2017-12-01T00:00:00':
        raise ValueError('Compatibility targets must remain descriptive at the original cutoff')
    focus = {value['month']: value for value in phases.values()
             if value['fold'] == '2017-12' and value['ledger_role'] == 'validation'
             and value['month'] in FOCUS_MONTHS}
    if set(focus) != set(FOCUS_MONTHS):
        raise ValueError('Require both prespecified compatibility phases')
    checks = []
    for label, baseline, alternatives in (('geo83', BASELINES[0], NEW[:2]),
                                            ('backlog101', BASELINES[1], NEW[2:])):
        goal = targets['packages'][label]
        if goal['current_reference'] != baseline:
            raise ValueError('Compatibility goal changed its matched current reference')
        for candidate in (baseline, *alternatives):
            tp = {month: focus[month]['context'][candidate]['known_outcome_metrics']['confusion_matrix'][1][1]
                  for month in FOCUS_MONTHS}
            july, september = tp['2017-07'], tp['2017-09']
            if candidate == baseline and (july != goal['july_current_TP'] or september != goal['september_current_TP']):
                raise ValueError('Frozen compatibility target changed current k20 performance')
            checks.append({'feature_package': label, 'candidate': candidate,
                'pair_focus_k': 20 if candidate == baseline else int(candidate.rsplit('_', 1)[1]),
                'july_TP': july, 'september_TP': september,
                'july_difference_from_current': july - goal['july_current_TP'],
                'september_difference_from_current': september - goal['september_current_TP'],
                'july_difference_from_earlier_l2_10': july - goal['july_restore_TP'],
                'both_months_not_worse_than_l2_100_top20': july >= goal['july_current_TP'] and september >= goal['september_current_TP'],
                'restore_july_l2_10_and_preserve_september_l2_100': july >= goal['july_restore_TP'] and september >= goal['september_current_TP'],
                'used_for_selection': False})
    return checks


def validate_source_contract(source, previous, specification):
    """Bind the new experiment to all 71 previous metric records and its spec."""
    if (source.get('status') != 'ok' or source.get('experiment') != 'rank_pair_focus'
            or source.get('daily_cap') != .1 or source.get('matched_candidate_order') != list(MATCHED)
            or source.get('new_candidate_order') != list(NEW)
            or source.get('reg_lambda') != 100. or source.get('pair_focus_values') != [10, 20, 40]
            or source.get('only_changed_parameter') != 'lambdarank_num_pair_per_sample'):
        raise ValueError('Require the completed fixed-L2 pair-focus experiment')
    previous_order = previous.get('candidate_order', [])
    if (previous.get('experiment') != 'rank_l2_regularization' or previous.get('status') != 'ok'
            or len(previous_order) != 71 or len(set(previous_order)) != 71
            or not set(PREVIOUS_MATCHED) <= set(previous.get('matched_candidate_order', []))
            or source.get('candidate_order') != [*previous_order, *NEW]
            or source.get('source_candidate_versions') != previous.get('source_candidate_versions')
            or source.get('feature_dataset') != previous.get('feature_dataset')
            or source.get('source_files') != previous.get('source_files')):
        raise ValueError('Require the unchanged 71-candidate source and feature provenance')
    if (specification.get('experiment') != 'rank_pair_focus' or
            any(source.get(key) != value for key, value in specification.items())):
        raise ValueError('Completed report changed its predeclared specification')
    prior_folds = {fold['name']: fold for fold in previous['folds']}
    if len(prior_folds) != 3 or len(source['folds']) != 3 or {f['name'] for f in source['folds']} != set(prior_folds):
        raise ValueError('Require exactly the three unchanged development schedules')
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
    if (len(prior_training) != 8 or len(source['monthly_training']) != 8
            or {row['month'] for row in source['monthly_training']} != set(prior_training)):
        raise ValueError('Require exactly the eight unchanged monthly fit schedules')
    for row in source['monthly_training']:
        prior = prior_training[row['month']]
        if row['split'] != prior['split'] or set(row['models']) != set(MATCHED):
            raise ValueError('Monthly scoring cohort or matched versions changed')
        for candidate in PREVIOUS_MATCHED:
            for key in ('version_artifact', 'training_split'):
                if row['models'][candidate][key] != prior['models'][candidate][key]:
                    raise ValueError('Frozen matched monthly version provenance changed')


def verify_phase_ledger(frame, ledger, cutoff, role, expected_models, month):
    """Reconcile every score, prediction, metric and complete-day budget."""
    if role not in ('validation', 'evaluation'):
        raise ValueError('Unknown scoring role')
    for column, value in (('role', role), ('model_version', month)):
        if column in ledger and not ledger[column].eq(value).all():
            raise ValueError('Ledger contains rows from another phase')
    known = ((frame.label_available_time < pd.Timestamp(cutoff)).to_numpy()
             if role == 'validation' else np.ones(len(frame), bool))
    ledger_known = known if role == 'validation' else np.zeros(len(frame), bool)
    observed_labels = frame.loc[known, 'delayed'].to_numpy()
    if not np.isin(observed_labels, [0, 1]).all():
        raise ValueError('Known outcomes must be binary')
    observed_labels = observed_labels.astype(int)
    if len(ledger) != len(frame) * len(MATCHED) or set(ledger.candidate) != set(MATCHED):
        raise ValueError('Require exactly eight complete full-batch candidate cohorts')
    scores, context = {}, {}
    for candidate in MATCHED:
        part = ledger.loc[ledger.candidate.eq(candidate)]
        if (part.order_id.duplicated().any() or len(part) != len(frame)
                or set(part.order_id) != set(frame.order_id)):
            raise ValueError('Score ledger changed complete scoring identities')
        part = part.set_index('order_id').loc[frame.order_id]
        np.testing.assert_array_equal(part.prediction_time.to_numpy(), frame.prediction_time.to_numpy())
        if part.known_at_selection.dtype != bool:
            raise ValueError('Ledger known-at-selection flags must be boolean')
        np.testing.assert_array_equal(part.known_at_selection.to_numpy(), ledger_known)
        np.testing.assert_array_equal(part.outcome_for_metrics.notna().to_numpy(), known)
        np.testing.assert_array_equal(part.outcome_for_metrics.to_numpy()[known], observed_labels)
        score = part.delay_score.to_numpy(dtype=float)
        if not np.isfinite(score).all() or ((score < 0) | (score > 1)).any():
            raise ValueError('Ledger contains invalid bounded scores')
        alert = apply_alert_policy(frame, score, 0., .1, raw_scores=score)
        if not part.predicted_delayed.isin([0, 1]).all():
            raise ValueError('Ledger predictions must be binary')
        np.testing.assert_array_equal(part.predicted_delayed.to_numpy(), alert)
        metrics = alert_metrics(observed_labels, score[known], alert[known])
        batch = batch_audit(frame, alert, .1, known)
        record = expected_models[candidate]
        expected = (record['validation_by_month'][month] if role == 'validation' else
                    {'known_outcome_metrics': record['development_evaluation'], 'full_batch': record['evaluation_batch']})
        if metrics != expected['known_outcome_metrics'] or batch != expected['full_batch']:
            raise ValueError(f'Frozen phase metrics or daily batch changed: {month}/{candidate}')
        scores[candidate] = score
        context[candidate] = {'known_outcome_metrics': metrics, 'full_batch': batch}
    return known, scores, context


def build_report(source_path, data_dir):
    source_path, data_dir = Path(source_path), Path(data_dir)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if (source['status'] != 'ok' or source['experiment'] != 'rank_pair_focus'
            or source['daily_cap'] != .1 or source['matched_candidate_order'] != list(MATCHED)
            or source['new_candidate_order'] != list(NEW)):
        raise ValueError('Require the completed matched pair-focus experiment')
    feature_path, score_path = (ROOT / source[key]['path'] for key in ('feature_dataset', 'score_export'))
    prior_path = ROOT / source['source_report']['path']
    files = {source_path: sha256(source_path), feature_path: source['feature_dataset']['sha256'],
             score_path: source['score_export']['sha256'], prior_path: source['source_report']['sha256'],
             source_path.with_name('rank_pair_focus_specification.json'): source['specification_sha256']}
    archive_path = ROOT / source['source_candidate_versions']['path']
    files[archive_path] = source['source_candidate_versions']['sha256']
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError(f'Frozen diagnostic source changed: {relative(path)}')
    previous = json.loads(prior_path.read_text(encoding='utf-8'))
    specification = json.loads(source_path.with_name('rank_pair_focus_specification.json').read_text(encoding='utf-8'))
    validate_source_contract(source, previous, specification)
    objective_path = ROOT / previous['source_report']['path']
    files[objective_path] = previous['source_report']['sha256']
    if sha256(objective_path) != files[objective_path]:
        raise ValueError('Frozen objective source in the earlier report chain changed')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Frozen raw sources changed')
    prior_training = {row['month']: row for row in previous['monthly_training']}
    provenance = {}
    for entry in source['monthly_training']:
        month = entry['month']
        if month in provenance or set(entry['models']) != set(MATCHED):
            raise ValueError('Require eight unique matched monthly versions')
        provenance[month] = {}
        for candidate in MATCHED:
            info = entry['models'][candidate]['version_artifact']
            if candidate in PREVIOUS_MATCHED and info != prior_training[month]['models'][candidate]['version_artifact']:
                raise ValueError('Frozen original matched version provenance changed')
            path = ROOT / info['path']
            if sha256(path) != info['sha256']:
                raise ValueError('Frozen monthly saved-model hash changed')
            files[path] = info['sha256']
            provenance[month][candidate] = info
    features = read_features(feature_path, data_dir)
    ledger = pd.read_csv(score_path, float_precision='round_trip')
    if (len(ledger) != source['score_export']['rows']
            or ledger.duplicated(['fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Ledger size or uniqueness changed')
    ledger['prediction_time'] = pd.to_datetime(ledger.prediction_time, errors='raise')
    report = {
        'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'source_report': {'path': relative(source_path), 'sha256': files[source_path]},
        'previous_l2_report': {'path': relative(prior_path), 'sha256': files[prior_path]},
        'original_objective_report': {'path': relative(objective_path), 'sha256': files[objective_path]},
        'earlier_candidate_manifest': {'path': relative(archive_path), 'sha256': files[archive_path]},
        'source_features': {'path': relative(feature_path), 'sha256': files[feature_path]},
        'source_scores': {'path': relative(score_path), 'sha256': files[score_path]},
        'daily_cap': .1, 'new_fit_count': 0, 'new_model_selection': False,
        'compatibility_targets': source['compatibility_targets'],
        'matched_candidate_order': list(MATCHED), 'model_provenance': provenance, 'phases': {},
        'notes': [
            'Ledger-only aggregate diagnosis: model hashes checked; no joblib loading, fitting, model replay, selection, calibration or threshold search in this CLI.',
            'Complete daily scoring batches rank before outcome masks; historical labels require actual delivery strictly before the fold cutoff.',
            'Evaluation ledger known_at_selection flags remain false; evaluation labels are used only as explicitly marked development retests.',
            'Four fixed-L2=100 top20-to-top10/40 contrasts keep every route, promise group and rank movement; route/promise cells and daily route marginals are retained for both July/September in the first fold.',
            'Both July/September classifier references and fixed L2=100 top20 error cohorts are descriptive; neither selects models nor attributes individual alerts to a causal feature or donor order.',
            'Native topk10/20/40 controls ranking pair construction, not the variable daily10% reminder cutoff; no daily scoring identities or budgets change.',
            'The original retained test and production/default model remain untouched. Overlapping route/promise/cohort views must not be added together.',
        ],
    }
    expected_phases, verified_rows = set(), 0
    for fold in source['folds']:
        name, schedule = fold['name'], fold['schedule']
        for month, role in [(value['month'], 'validation') for value in schedule['validation_months']] + [(name, 'evaluation')]:
            expected_phases.add((name, role, month))
            frame = features.loc[features.prediction_time.dt.strftime('%Y-%m').eq(month)].reset_index(drop=True)
            fingerprint = (fold['order_id_fingerprints']['validation_full_by_month'][month]
                           if role == 'validation' else fold['order_id_fingerprints']['evaluation'])
            if frame.empty or order_fingerprint(frame) != fingerprint or month not in provenance:
                raise ValueError('Complete scoring identities changed')
            part = ledger.loc[ledger.fold.eq(name) & ledger.role.eq(role) & ledger.model_version.eq(month)]
            known, scores, context = verify_phase_ledger(frame, part, schedule['evaluation_start'], role, fold['experiment']['models'], month)
            focus = name == '2017-12' and month in FOCUS_MONTHS and role == 'validation'
            key = f'{name}/{month}/{role}'
            if key in report['phases']:
                raise ValueError('Duplicate scoring phase')
            phase = {
                'fold': name, 'month': month,
                'role': 'historical_validation' if role == 'validation' else 'development_retest',
                'ledger_role': role, 'historical_outcome_cutoff': schedule['evaluation_start'],
                'order_id_fingerprint': fingerprint, 'context': context,
                'full_batch': {'rows': len(frame), 'known_outcome_rows': int(known.sum()),
                               'unknown_outcome_rows': int((~known).sum()), 'capacity': context[MATCHED[0]]['full_batch']['capacity']},
                'pair_focus': pair_focus_exchanges(frame, scores, known, keep_route_days=focus, keep_cross=focus),
            }
            if focus:
                phase.update(focus_month_diagnostics(frame, scores, known))
                for candidate in (BASELINES[1], *NEW[2:]):
                    row = phase['classification_references'][candidate]['summary']
                    sp = next(item for item in phase['classification_references'][candidate]['routes'] if item['state_route'] == 'SP->SP')
                    print(f'{month} {candidate}: TP={row["new_true_positives"]} FP={row["new_false_positives"]}; SP->SP alerts={sp["new_alerts"]} TP={sp["new_true_positives"]} FP={sp["new_false_positives"]}', flush=True)
            report['phases'][key] = phase
            verified_rows += len(part)
            print(f'{key}: eight full score cohorts and four fixed pair-focus contrasts verified', flush=True)
    if set(zip(ledger.fold, ledger.role, ledger.model_version, strict=True)) != expected_phases or verified_rows != len(ledger):
        raise ValueError('Unexpected or missing ledger scoring phases')
    report['joint_july_september'] = joint_focus_summary(report['phases'])
    report['compatibility_checks'] = compatibility_checks_from_phases(report['phases'], report['compatibility_targets'])
    if report['compatibility_checks'] != source['compatibility_checks']:
        raise ValueError('Prespecified compatibility flags do not reconcile verified score metrics')
    for path, expected in files.items():
        if sha256(path) != expected:
            raise ValueError('Frozen source changed during diagnosis')
    if engineering_source_manifest(data_dir) != source['source_files']:
        raise ValueError('Raw sources changed during diagnosis')
    report['verification'] = {
        'source_and_model_hashes_checked': len(files),
        'monthly_model_hashes_checked': sum(len(row) for row in provenance.values()),
        'score_rows_verified': verified_rows, 'scoring_phases_verified': len(expected_phases),
        'pair_focus_contrasts': 4 * len(expected_phases), 'focus_classification_contrasts': 6, 'fixed_error_cohort_months': 2,
        'source_metrics_and_full_batch_exactly_reconciled': True,
        'descriptive_compatibility_checks_exactly_reconciled': True,
        'frozen_previous_candidate_metrics_unchanged': True,
        'full_batch_ranks_before_outcome_masks': True, 'source_hashes_rechecked_after_analysis': True,
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
    parser.add_argument('--source-report', type=Path, default=ROOT / 'reports/stage4/rank_pair_focus.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/stage4/rank_pair_focus_diagnostics.json')
    args = parser.parse_args(argv)
    try:
        output = validate_output(args.output, args.source_report)
    except ValueError as exc:
        parser.error(str(exc))
    report = build_report(args.source_report, args.data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    # This aggregate keeps every zero-change route/day cell; compact JSON avoids
    # duplicating tens of megabytes of whitespace in the published evidence.
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(f'Wrote {output}', flush=True)
    return report


if __name__ == '__main__':
    main()
