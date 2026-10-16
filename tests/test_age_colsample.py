"""Four paired contrasts, DID, stability and frozen-reference guards."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import compare_age_colsample as driver
from scripts import delay_age_colsample_training as training
from scripts import delay_age_seed_training as previous
from scripts import delay_objective_training as objective
from tests.test_age_seed_stability import context
from tests.test_delay_objective_training import RecordingRanker
from tests.test_delay_unobserved_handover_age_training import frame


def metric(tp, fp=5, delayed=20, alerts=10):
    return {'true_positives': tp, 'false_positives': fp, 'false_negatives': delayed-tp,
            'recall': tp/delayed if delayed else None, 'precision': tp/(tp+fp) if tp+fp else None, 'alerts': alerts}


class AgeColsampleTests(unittest.TestCase):
    def test_four_contrasts_and_did_are_paired_before_seed_summaries(self):
        paired = {}
        for seed, b8, a8, b1, a1 in zip(driver.SEEDS, [0, 100, 40, 5, 70], [1, 102, 43, 9, 75],
                                      [10, 110, 50, 15, 80], [13, 114, 55, 21, 87], strict=True):
            paired[str(seed)] = driver.paired_contrasts({'0.8': {driver.BASELINE: metric(b8, delayed=200), driver.AGE: metric(a8, delayed=200)},
                                                       '1.0': {driver.BASELINE: metric(b1, delayed=200), driver.AGE: metric(a1, delayed=200)}})
        result = driver.summarize_comparisons(paired)
        self.assertEqual(result['cross_seed_statistics']['difference_in_differences']['true_positives']['mean'], 2.)
        self.assertEqual(result['cross_seed_statistics']['difference_in_differences']['true_positives']['minimum'], 2.)
        self.assertEqual(result['cross_seed_statistics']['base_10_minus_08']['true_positives']['minimum'], 10.)
        self.assertEqual(result['by_seed']['11']['age_minus_base_at_08']['true_positives'], 1)
        self.assertEqual(result['by_seed']['11']['age_minus_base_at_10']['true_positives'], 3)
        self.assertEqual(result['cross_seed_statistics']['difference_in_differences']['true_positives']['positive'], 5)

    def test_did_preserves_undefined_rates_and_direction_counts(self):
        values = {'0.8': {driver.BASELINE: metric(0, fp=0, delayed=0), driver.AGE: metric(0, fp=0, delayed=0)},
                  '1.0': {driver.BASELINE: metric(0, fp=0, delayed=0), driver.AGE: metric(0, fp=0, delayed=0)}}
        result = driver.paired_contrasts(values)
        self.assertIsNone(result['difference_in_differences']['recall'])
        self.assertIsNone(result['difference_in_differences']['precision'])
        stats = driver.summarize_comparisons({str(s): result for s in driver.SEEDS})
        self.assertEqual(stats['cross_seed_statistics']['difference_in_differences']['recall']['undefined'], 5)
        with self.assertRaises(ValueError):
            driver.summarize_comparisons({'42': result})

    def test_narrow_gap_does_not_hide_variable_individual_models(self):
        by_col = {col: {} for col in driver.COLSAMPLES}
        for i, seed in enumerate(driver.SEEDS):
            b8, a8 = 10, 10+i
            b1, a1 = 10+10*i, 8+10*i
            by_col['0.8'][str(seed)] = {driver.BASELINE: context(100, 5, 100-b8, b8), driver.AGE: context(100, 5, 100-a8, a8)}
            by_col['1.0'][str(seed)] = {driver.BASELINE: context(100, 5, 100-b1, b1), driver.AGE: context(100, 5, 100-a1, a1)}
        result = driver.february_stability(by_col)
        self.assertEqual(result['by_colsample']['0.8']['age_minus_base']['TP']['span'], 4.)
        self.assertEqual(result['by_colsample']['1.0']['age_minus_base']['TP']['span'], 0.)
        self.assertEqual(result['by_colsample']['1.0']['age_minus_base']['TP']['negative'], 5)
        self.assertEqual(result['by_colsample']['1.0']['by_candidate'][driver.BASELINE]['TP']['span'], 40.)
        self.assertEqual(result['span_change_10_minus_08']['by_candidate'][driver.BASELINE]['TP'], 40.)
        self.assertEqual(result['span_change_10_minus_08']['age_minus_base']['TP'], -4.)

    def test_fit_guard_allows_only_colsample_and_same_preprocessing(self):
        train, scoring = frame('2017-09'), frame('2018-02', 20)
        train.loc[0, training.ADDED_FEATURES[0]] = np.nan
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            _, _, old = previous.fit_version(train, scoring, training.AGE, 11)
            _, _, new = training.fit_version(train, scoring, training.AGE, 11)
        driver.verify_fit_contract(train, new, old, 11, training.AGE)
        for field, value in [('seed', 29), ('feature_count', 101), ('training_labels_sha256', 'bad'),
                             ('numeric_missing_indicator_features', []), ('train_only_preprocessing_verified', False)]:
            changed = deepcopy(new)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                driver.verify_fit_contract(train, changed, old, 11, training.AGE)
        for layer in ('classifier_parameters', 'ranker_parameters'):
            changed = deepcopy(new)
            changed[layer]['subsample'] = 1.
            with self.subTest(layer=layer), self.assertRaises(ValueError):
                driver.verify_fit_contract(train, changed, old, 11, training.AGE)

    def test_frozen_ledger_unknowns_consume_full_day_slots_before_masks(self):
        frame_data = pd.DataFrame({'order_id': [f'id{i:02d}' for i in range(20)],
            'prediction_time': pd.to_datetime(['2018-01-01']*20), 'delayed': [1]*20,
            'label_available_time': pd.to_datetime(['2018-03-01']+['2018-01-15']*19)})
        values = np.linspace(.99, .1, 20)
        known = frame_data.label_available_time.lt('2018-02-01').to_numpy()
        alerts = driver.apply_alert_policy(frame_data, values, 0., .1, raw_scores=values)
        expected_context = {'known_outcome_metrics': driver.alert_metrics(frame_data.delayed.to_numpy()[known], values[known], alerts[known]),
                            'full_batch': driver.batch_audit(frame_data, alerts, .1, known)}
        records = []
        expected = {}
        for seed in driver.SEEDS:
            expected[str(seed)] = {c: expected_context for c in driver.MATCHED}
            for candidate in driver.MATCHED:
                part = frame_data[['order_id', 'prediction_time']].copy()
                part['fold'], part['role'], part['model_version'], part['seed'], part['candidate'] = '2018-02', 'validation', '2018-01', seed, candidate
                part['known_at_selection'], part['outcome_for_metrics'] = known, np.where(known, 1, np.nan)
                part['delay_score'], part['predicted_delayed'] = values, alerts.astype(int)
                records.append(part)
        ledger = pd.concat(records, ignore_index=True)
        plan = {'fold': '2018-02', 'ledger_role': 'validation', 'month': '2018-01', 'historical_outcome_cutoff': '2018-02-01'}
        result = driver.verify_frozen_ledger(frame_data, ledger, plan, expected)
        self.assertEqual(result['11'][driver.BASELINE]['full_batch']['unknown_outcome_alerts'], 1)
        self.assertEqual(result['11'][driver.BASELINE]['known_outcome_metrics']['confusion_matrix'][1][1], 1)
        for column, value in [('delay_score', np.nan), ('known_at_selection', False), ('predicted_delayed', 0)]:
            changed = ledger.copy()
            changed.loc[1, column] = value
            with self.subTest(column=column), self.assertRaises((ValueError, AssertionError)):
                driver.verify_frozen_ledger(frame_data, changed, plan, expected)

    def test_source_hash_guard_fails_before_any_fit_or_model_load(self):
        with (patch.object(driver, 'sha256', return_value='changed'), patch.object(driver.joblib, 'load') as load,
              patch.object(training, 'fit_version') as fit):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                driver.prepare_experiment(driver.DEFAULT_OUTPUT / 'age_seed_stability.json', driver.ROOT / 'data/raw/olist', driver.DEFAULT_OUTPUT.resolve(), 2)
            load.assert_not_called()
            fit.assert_not_called()

    def test_frozen_diagnostic_contract_and_fixed_seeds(self):
        from scripts.diagnose_age_colsample import diagnostic_contract
        contract = diagnostic_contract()
        self.assertEqual(contract['seeds'], list(driver.SEEDS))
        self.assertEqual(contract['candidate_order'], list(driver.MATCHED))
        self.assertEqual(driver.canonical_sha256(contract), 'ddc4ad65f53494edc4741d7b7dee08b19dbe3f03b824f13f0072bdccd40dbf2b')


if __name__ == '__main__':
    unittest.main()
