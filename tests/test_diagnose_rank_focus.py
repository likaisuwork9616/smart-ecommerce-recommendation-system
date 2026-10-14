"""Fixed error cohorts and full-batch ledger checks for ranker pair-focus diagnosis."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.diagnose_rank_focus import (
    ANALYSIS, BASELINES, CLASSIFIERS, MATCHED, NEW,
    regression_cohorts, pair_focus_exchanges, validate_output, verify_phase_ledger,
    focus_month_diagnostics, joint_focus_summary, validate_source_contract,
    compatibility_checks_from_phases,
)
from tests.test_delay_route_exchanges import cohort, selected_scores


def example():
    frame = cohort(40)
    frame['delayed'] = 0
    frame.loc[[1, 4, 8], 'delayed'] = 1
    frame['estimated_delivery_days'] = np.resize([10., 25.], len(frame))
    frame['label_available_time'] = pd.Timestamp('2017-08-01')
    frame.loc[0, 'label_available_time'] = pd.Timestamp('2017-12-01')
    scores = {c: selected_scores(40, [0, 1, 2, 3]) for c in MATCHED}
    scores[BASELINES[1]] = selected_scores(40, [0, 2, 4, 5])
    scores[NEW[2]] = selected_scores(40, [0, 1, 4, 6])
    scores[NEW[3]] = selected_scores(40, [0, 2, 5, 7])
    return frame, scores, np.arange(40) != 0


def ledger_fixture(frame, scores, known, role='validation'):
    records, expected = [], {}
    for candidate in MATCHED:
        alert = apply_alert_policy(frame, scores[candidate], 0., .1)
        outcome = np.full(len(frame), np.nan)
        outcome[known] = frame.loc[known, 'delayed'].to_numpy()
        records.append(pd.DataFrame({
            'order_id': frame.order_id, 'prediction_time': frame.prediction_time,
            'candidate': candidate, 'known_at_selection': known if role == 'validation' else np.zeros(len(frame), bool),
            'outcome_for_metrics': outcome, 'delay_score': scores[candidate], 'predicted_delayed': alert.astype(int),
        }))
        metrics = alert_metrics(frame.loc[known, 'delayed'].to_numpy(), scores[candidate][known], alert[known])
        batch = batch_audit(frame, alert, .1, known)
        expected[candidate] = {'validation_by_month': {'2017-07': {
            'known_outcome_metrics': metrics, 'full_batch': batch}},
            'development_evaluation': metrics, 'evaluation_batch': batch}
    return pd.concat(records, ignore_index=True), expected


def source_contract_fixture():
    previous_order = [*CLASSIFIERS, *BASELINES, *(f'prior_{i}' for i in range(67))]
    original = {
        'status': 'ok', 'experiment': 'rank_l2_regularization',
        'candidate_order': previous_order, 'matched_candidate_order': list(CLASSIFIERS + BASELINES),
        'source_candidate_versions': {'path': 'archive.json', 'sha256': 'frozen-archive'},
        'feature_dataset': {'path': 'features.csv', 'sha256': 'frozen-features'},
        'source_files': {'raw': 'frozen-raw'}, 'folds': [], 'monthly_training': [],
    }
    for name in ('2017-12', '2018-02', '2018-04'):
        original['folds'].append({'name': name, 'schedule': {'cutoff': name}, 'validation_maturity': {},
                                  'order_id_fingerprints': {'unchanged': name},
                                  'experiment': {'models': {c: {'value': c} for c in previous_order}}})
    for month in ('2017-07', '2017-08', '2017-09', '2017-10', '2017-11', '2017-12', '2018-02', '2018-04'):
        original['monthly_training'].append({'month': month, 'split': {'unchanged': month},
            'models': {c: {'version_artifact': {'path': f'{month}/{c}', 'sha256': c},
                           'training_split': {'train': month}} for c in CLASSIFIERS + BASELINES}})
    source = json.loads(json.dumps(original))
    source.update({'experiment': 'rank_pair_focus', 'only_changed_parameter': 'lambdarank_num_pair_per_sample',
                   'candidate_order': previous_order + list(NEW), 'matched_candidate_order': list(MATCHED),
                   'new_candidate_order': list(NEW), 'daily_cap': .1, 'reg_lambda': 100.,
                   'pair_focus_values': [10, 20, 40]})
    for fold in source['folds']:
        fold['experiment']['models'].update({c: {'value': c} for c in NEW})
    for row in source['monthly_training']:
        row['models'].update({c: {'version_artifact': {'path': f'{row["month"]}/{c}', 'sha256': c},
                                 'training_split': {'train': row['month']}} for c in NEW})
    specification = {key: source[key] for key in ('experiment', 'daily_cap', 'candidate_order',
                     'matched_candidate_order', 'new_candidate_order', 'only_changed_parameter')}
    return source, original, specification


class RankPairFocusDiagnosisTests(unittest.TestCase):
    def test_both_focus_months_have_classifier_references_and_fixed_cohorts(self):
        frame, scores, known = example()
        phases = {}
        for month in ('2017-07', '2017-09'):
            current = frame.copy()
            current['prediction_time'] += pd.Timestamp(f'{month}-01') - pd.Timestamp('2017-07-01')
            result = focus_month_diagnostics(current, scores, known)
            self.assertEqual(set(result['classification_references']), {BASELINES[1], *NEW[2:]})
            for candidate, record in result['classification_references'].items():
                self.assertIn('route_day_allocations', record)
                self.assertIn('route_by_promise', record)
                self.assertEqual(record['summary']['old_alerts'], record['summary']['new_alerts'])
                self.assertEqual(record['comparison']['fixed_l2'], 100.)
                self.assertEqual(sum(r['net_TP'] for r in record['routes']), record['summary']['net_TP'])
            cohorts = result['regression_cohorts']['cohorts']
            self.assertEqual(cohorts['added_on_time_alerts']['cohort_rows'], 1)
            self.assertEqual(cohorts['lost_delays']['cohort_rows'], 1)
            _, expected = ledger_fixture(current, scores, known)
            phases[month] = {'month': month, 'fold': '2017-12', 'ledger_role': 'validation',
                            'context': {c: {'known_outcome_metrics': expected[c]['development_evaluation']}
                                        for c in MATCHED}}
        joint = joint_focus_summary(phases)
        self.assertFalse(joint['selection_performed'])
        self.assertEqual(joint['months'], ['2017-07', '2017-09'])
        rows = {row['candidate']: row for row in joint['backlog101']}
        self.assertEqual(rows[BASELINES[1]]['pooled_true_positives'], 2)
        self.assertEqual(rows[NEW[2]]['net_TP_vs_topk_20'], 2)
        self.assertTrue(rows[NEW[2]]['neither_month_loses_TP_vs_topk_20'])
        self.assertFalse(rows[NEW[3]]['neither_month_loses_TP_vs_topk_20'])
        targets = {'used_for_selection': False, 'historical_outcome_cutoff': '2017-12-01T00:00:00',
                   'packages': {label: {'current_reference': baseline, 'july_current_TP': 1,
                                        'september_current_TP': 1, 'july_restore_TP': 2}
                                for label, baseline in zip(('geo83', 'backlog101'), BASELINES, strict=True)}}
        checks = {row['candidate']: row for row in compatibility_checks_from_phases(phases, targets)}
        self.assertEqual(len(checks), 6)
        self.assertTrue(checks[BASELINES[1]]['both_months_not_worse_than_l2_100_top20'])
        self.assertFalse(checks[BASELINES[1]]['restore_july_l2_10_and_preserve_september_l2_100'])
        self.assertTrue(checks[NEW[2]]['restore_july_l2_10_and_preserve_september_l2_100'])
        self.assertFalse(checks[NEW[3]]['both_months_not_worse_than_l2_100_top20'])
        self.assertTrue(all(row['used_for_selection'] is False for row in checks.values()))
        changed_targets = json.loads(json.dumps(targets))
        changed_targets['packages']['backlog101']['july_current_TP'] = 2
        with self.assertRaises(ValueError):
            compatibility_checks_from_phases(phases, changed_targets)
        with self.assertRaises(ValueError):
            compatibility_checks_from_phases(phases, {**targets, 'used_for_selection': True})
        with self.assertRaises(ValueError):
            joint_focus_summary({'one_month': phases['2017-07']})

    def test_two_month_unknown_label_corruption_cannot_change_focus_diagnosis(self):
        frame, scores, known = example()
        for month in ('2017-07', '2017-09'):
            frame['prediction_time'] = pd.Timestamp(f'{month}-01') + pd.to_timedelta(np.arange(40), unit='m')
            actual = focus_month_diagnostics(frame, scores, known)
            changed = frame.copy()
            changed['delayed'] = changed.delayed.astype(object)
            changed.loc[~known, 'delayed'] = 'future label forbidden'
            self.assertEqual(focus_month_diagnostics(changed, scores, known), actual)

    def test_fixed_pair_focus_never_turns_small_days_into_alerts(self):
        frame = cohort(9)
        frame['estimated_delivery_days'] = 10.
        scores = {candidate: np.linspace(.01, .99, 9) for candidate in MATCHED}
        result = focus_month_diagnostics(frame, scores, np.ones(9, bool))
        for item in result['classification_references'].values():
            self.assertEqual(item['summary']['old_alerts'], 0)
            self.assertEqual(item['summary']['new_alerts'], 0)
        self.assertTrue(all(row['cohort_rows'] == 0 for row in result['regression_cohorts']['cohorts'].values()))

    def test_source_contract_requires_71_frozen_metrics_and_unchanged_months(self):
        source, original, specification = source_contract_fixture()
        validate_source_contract(source, original, specification)
        mutations = [
            lambda value: value.update(only_changed_parameter='reg_lambda'),
            lambda value: value.update(reg_lambda=10.),
            lambda value: value.update(pair_focus_values=[5, 20, 40]),
            lambda value: value['folds'][0]['experiment']['models'][CLASSIFIERS[0]].update(value='changed'),
            lambda value: value['folds'][0]['schedule'].update(cutoff='changed'),
            lambda value: value['monthly_training'][0]['models'][BASELINES[1]]['version_artifact'].update(sha256='changed'),
            lambda value: value['monthly_training'][0]['models'][CLASSIFIERS[0]]['training_split'].update(train='changed'),
            lambda value: value['monthly_training'].pop(),
            lambda value: value['source_candidate_versions'].update(sha256='changed'),
            lambda value: value['feature_dataset'].update(sha256='changed'),
        ]
        for change in mutations:
            changed = json.loads(json.dumps(source))
            change(changed)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_source_contract(changed, original, specification)
        altered_spec = json.loads(json.dumps(specification))
        altered_spec['daily_cap'] = .2
        with self.assertRaises(ValueError):
            validate_source_contract(source, original, altered_spec)

    def test_phase_ledger_rejects_cross_month_or_role_rows(self):
        frame, scores, known = example()
        ledger, expected = ledger_fixture(frame, scores, known)
        for bad in (ledger.assign(role='evaluation'), ledger.assign(model_version='2017-09')):
            with self.subTest(columns=list(bad.columns)), self.assertRaises(ValueError):
                verify_phase_ledger(frame, bad, '2017-12-01', 'validation', expected, '2017-07')

    def test_fixed_error_cohorts_track_removal_and_recovery_with_complete_day_ranks(self):
        frame, scores, known = example()
        actual = regression_cohorts(frame, scores, known)
        fp, miss = (actual['cohorts'][name] for name in ('added_on_time_alerts', 'lost_delays'))
        self.assertEqual(fp['cohort_rows'], 1)
        self.assertEqual(miss['cohort_rows'], 1)
        self.assertEqual(fp['models'][BASELINES[1]]['in_top10'], 1)
        self.assertEqual(fp['models'][NEW[2]]['out_of_top10'], 1)
        self.assertEqual(fp['models'][NEW[3]]['out_of_top10'], 0)
        self.assertEqual(miss['models'][BASELINES[1]]['in_top10'], 0)
        self.assertEqual(miss['models'][NEW[2]]['in_top10'], 1)
        self.assertEqual(miss['models'][NEW[3]]['in_top10'], 0)
        self.assertEqual(miss['models'][BASELINES[1]]['rank_bins']['10-20%'], 1)
        for item in (fp, miss):
            self.assertEqual(item['known_rows'], 39)
            self.assertEqual(item['known_delayed_rows'], 3)
            for dimension in ('routes', 'promise_days', 'route_by_promise'):
                self.assertEqual(sum(row['cohort_rows'] for row in item[dimension]), 1)
                self.assertEqual(sum(row['known_rows'] for row in item[dimension]), 39)
                self.assertTrue(any(row['cohort_rows'] == 0 for row in item[dimension]))
        self.assertNotIn('private-order-', json.dumps(actual))

    def test_unknown_future_label_corruption_cannot_change_cohorts_or_exchanges(self):
        frame, scores, known = example()
        actual = regression_cohorts(frame, scores, known)
        exchanges = pair_focus_exchanges(frame, scores, known, keep_route_days=True, keep_cross=True)
        changed = frame.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[~known, 'delayed'] = 'future label forbidden'
        self.assertEqual(regression_cohorts(changed, scores, known), actual)
        self.assertEqual(pair_focus_exchanges(changed, scores, known, keep_route_days=True, keep_cross=True), exchanges)
        for record in exchanges.values():
            row = record['summary']
            self.assertEqual(row['old_alerts'], 4)
            self.assertEqual(row['new_alerts'], 4)
            self.assertEqual(row['old_unknown_alerts'], 1)
            self.assertEqual(row['new_unknown_alerts'], 1)
            self.assertEqual(row['net_TP'] + row['net_FP'] + row['net_unknown_alerts'], 0)
            self.assertEqual(sum(route['net_TP'] for route in record['routes']), row['net_TP'])

    def test_nonfocus_phases_omit_only_large_repeated_dimensions(self):
        frame, scores, known = example()
        result = pair_focus_exchanges(frame, scores, known)
        self.assertEqual(set(result), set(NEW))
        for candidate, value in result.items():
            self.assertNotIn('route_by_promise', value)
            self.assertNotIn('route_day_allocations', value)
            self.assertEqual(len(value['days']), 1)
            self.assertEqual(len(value['promise_days']), 2)
            self.assertEqual(value['comparison']['alternative'], candidate)
            self.assertEqual(value['comparison']['alternative_topk'], int(candidate.rsplit('_', 1)[1]))
            self.assertEqual(sum(row['rows'] for row in value['rank_movements']['cohorts']), 40)

    def test_empty_fixed_cohorts_have_zero_counts_and_no_division_claims(self):
        frame, _, known = example()
        scores = {c: selected_scores(40, [0, 1, 2, 3]) for c in MATCHED}
        result = regression_cohorts(frame, scores, known)
        for item in result['cohorts'].values():
            self.assertEqual(item['cohort_rows'], 0)
            self.assertTrue(all(value['in_top10'] == value['out_of_top10'] == 0 for value in item['models'].values()))

    def test_unknown_only_cohort_cannot_produce_fp_or_lost_delay_claims(self):
        frame, scores, _ = example()
        frame['delayed'] = 'unavailable'
        result = regression_cohorts(frame, scores, np.zeros(len(frame), bool))
        for item in result['cohorts'].values():
            self.assertEqual(item['cohort_rows'], 0)
            self.assertEqual(item['known_delayed_rows'], 0)
            self.assertFalse(item['minimum_sample_met'])

    def test_bad_mask_known_labels_or_missing_score_cohort_are_rejected(self):
        frame, scores, known = example()
        for bad in ([1] * len(frame), np.ones(len(frame) - 1, bool), np.ones((len(frame), 1), bool)):
            with self.subTest(mask=np.shape(bad)), self.assertRaises(ValueError):
                regression_cohorts(frame, scores, bad)
        missing = dict(scores)
        missing.pop(NEW[0])
        with self.assertRaises(ValueError):
            regression_cohorts(frame, missing, known)
        with self.assertRaises(ValueError):
            pair_focus_exchanges(frame, missing, known)
        frame.loc[1, 'delayed'] = 2
        with self.assertRaises(ValueError):
            regression_cohorts(frame, scores, known)

    def test_validation_ledger_reconciles_unknown_competition_before_mask(self):
        frame, scores, known = example()
        ledger, expected = ledger_fixture(frame, scores, known)
        actual_known, actual_scores, context = verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', expected, '2017-07')
        np.testing.assert_array_equal(actual_known, known)
        for candidate in MATCHED:
            np.testing.assert_array_equal(actual_scores[candidate], scores[candidate])
            self.assertEqual(context[candidate]['full_batch']['alerts'], 4)
            self.assertEqual(context[candidate]['full_batch']['unknown_outcome_alerts'], 1)
            self.assertEqual(context[candidate]['known_outcome_metrics']['predicted_positive_rows'], 3)
        changed = frame.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[~known, 'delayed'] = 'not yet known'
        self.assertEqual(verify_phase_ledger(changed, ledger, '2017-12-01', 'validation', expected, '2017-07')[2], context)

    def test_ledger_future_labels_incomplete_batch_and_wrong_flags_rejected(self):
        frame, scores, known = example()
        ledger, expected = ledger_fixture(frame, scores, known)
        bad_cases = [ledger.iloc[1:].copy(), ledger.assign(known_at_selection=True),
                     ledger.assign(outcome_for_metrics=ledger.outcome_for_metrics.fillna(1))]
        for bad in bad_cases:
            with self.subTest(rows=len(bad)), self.assertRaises((AssertionError, ValueError)):
                verify_phase_ledger(frame, bad, '2017-12-01', 'validation', expected, '2017-07')
        changed = json.loads(json.dumps(expected))
        changed[MATCHED[0]]['validation_by_month']['2017-07']['known_outcome_metrics']['precision'] = .999
        with self.assertRaises(ValueError):
            verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', changed, '2017-07')

    def test_development_ledger_cannot_claim_labels_known_at_selection(self):
        frame, scores, _ = example()
        known = np.ones(len(frame), bool)
        ledger, expected = ledger_fixture(frame, scores, known, role='evaluation')
        actual_known, _, _ = verify_phase_ledger(frame, ledger, '2017-07-01', 'evaluation', expected, '2017-07')
        self.assertTrue(actual_known.all())
        with self.assertRaises(AssertionError):
            verify_phase_ledger(frame, ledger.assign(known_at_selection=True), '2017-07-01', 'evaluation', expected, '2017-07')

    def test_output_guards_preserve_sources_unrelated_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, unrelated, malformed, own = (root / name for name in ('source.json', 'other.json', 'bad.json', 'own.json'))
            source.write_text('{"status":"ok"}', encoding='utf-8')
            unrelated.write_text('{"analysis":"another"}', encoding='utf-8')
            malformed.write_text('not JSON', encoding='utf-8')
            own.write_text(json.dumps({'analysis': ANALYSIS, 'format_version': 1}), encoding='utf-8')
            for path in (source, unrelated, malformed, root / 'new.csv'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    validate_output(path, source)
            self.assertEqual(validate_output(own, source), own.resolve())
            self.assertEqual(validate_output(root / 'new.json', source), (root / 'new.json').resolve())
            self.assertEqual(source.read_text(encoding='utf-8'), '{"status":"ok"}')


if __name__ == '__main__':
    unittest.main()
