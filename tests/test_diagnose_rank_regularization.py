"""Fixed error cohorts and full-batch ledger checks for ranker L2 diagnosis."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.diagnose_rank_regularization import (
    ANALYSIS, BASELINES, CLASSIFIERS, MATCHED, NEW,
    regression_cohorts, regularization_exchanges, validate_output, verify_phase_ledger,
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


class RankRegularizationDiagnosisTests(unittest.TestCase):
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
        exchanges = regularization_exchanges(frame, scores, known, keep_route_days=True, keep_cross=True)
        changed = frame.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[~known, 'delayed'] = 'future label forbidden'
        self.assertEqual(regression_cohorts(changed, scores, known), actual)
        self.assertEqual(regularization_exchanges(changed, scores, known, keep_route_days=True, keep_cross=True), exchanges)
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
        result = regularization_exchanges(frame, scores, known)
        self.assertEqual(set(result), set(NEW))
        for candidate, value in result.items():
            self.assertNotIn('route_by_promise', value)
            self.assertNotIn('route_day_allocations', value)
            self.assertEqual(len(value['days']), 1)
            self.assertEqual(len(value['promise_days']), 2)
            self.assertEqual(value['comparison']['alternative'], candidate)
            self.assertEqual(value['comparison']['alternative_l2'], 1 if candidate.endswith('_1') else 100)
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
            regularization_exchanges(frame, missing, known)
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
