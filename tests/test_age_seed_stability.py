"""Paired deltas and frozen settings, without best-seed or model selection."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np

from scripts import compare_age_seed_stability as driver
from scripts import delay_age_seed_training as training
from scripts import delay_objective_training as objective
from tests.test_delay_unobserved_handover_age_training import frame
from tests.test_delay_objective_training import RecordingRanker


def context(tn, fp, fn, tp, full_rows=None, alerts=None):
    return {'known_outcome_metrics': {'confusion_matrix': [[tn, fp], [fn, tp]],
        'recall': tp/(tp+fn) if tp+fn else None, 'precision': tp/(tp+fp) if tp+fp else None},
        'full_batch': {'scored_rows': tn+fp+fn+tp if full_rows is None else full_rows,
                       'alerts': tp+fp if alerts is None else alerts}}


class AgeSeedStabilityTests(unittest.TestCase):
    def test_paired_ranges_are_computed_inside_each_seed(self):
        baseline = [{'true_positives': 100}, {'true_positives': 0}]
        age = [{'true_positives': 101}, {'true_positives': 2}]
        result = driver.paired_statistics([right['true_positives']-left['true_positives']
                                           for left, right in zip(baseline, age, strict=True)])
        self.assertEqual((result['mean'], result['minimum'], result['maximum']), (1.5, 1., 2.))
        self.assertEqual((result['negative'], result['zero'], result['positive']), (0, 0, 2))
        self.assertNotEqual(result['minimum'], min(row['true_positives'] for row in age)-max(row['true_positives'] for row in baseline))

    def test_direction_and_undefined_rates_are_reported_without_zero_imputation(self):
        result = driver.paired_statistics([-2, 0, 3, None, 4])
        self.assertEqual((result['mean'], result['minimum'], result['maximum']), (1.25, -2., 4.))
        self.assertEqual((result['negative'], result['zero'], result['positive'], result['undefined']), (1, 1, 2, 1))
        self.assertIsNone(driver.paired_statistics([None]*5)['mean'])
        with self.assertRaises(ValueError):
            driver.paired_statistics([np.inf])

    def test_development_confusions_are_pooled_only_within_one_seed(self):
        result = driver.aggregate_development([context(10, 2, 3, 1), context(20, 3, 2, 2), context(30, 4, 1, 3)])
        self.assertEqual((result['true_positives'], result['false_positives'], result['false_negatives']), (6, 9, 6))
        self.assertEqual((result['recall'], result['precision'], result['alerts']), (.5, .4, 15))
        empty = driver.aggregate_development([context(10, 0, 0, 0)])
        self.assertIsNone(empty['recall'])
        self.assertIsNone(empty['precision'])

    def test_full_batch_size_does_not_drop_unknown_rows(self):
        result = driver.count_metrics(context(10, 1, 2, 1, full_rows=20, alerts=2))
        self.assertEqual((result['known_rows'], result['full_batch_rows']), (14, 20))

    def test_parameter_guard_allows_only_requested_seed_change(self):
        train, scoring = frame('2017-09'), frame('2018-02', 20)
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            _, _, original = training.fit_version(train, scoring, training.AGE, 42)
            _, _, seed11 = training.fit_version(train, scoring, training.BASELINE, 11)
        driver.verify_fit_contract(train, seed11, original, 11)
        for field, value in [('reg_lambda', 10.), ('pair_focus_k', 20), ('training_labels_sha256', 'bad'), ('seed', 29)]:
            changed = deepcopy(seed11)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                driver.verify_fit_contract(train, changed, original, 11)
        changed = deepcopy(seed11)
        changed['classifier_parameters']['colsample_bytree'] = 1.
        with self.assertRaises(ValueError):
            driver.verify_fit_contract(train, changed, original, 11)

    def test_diagnostic_contract_hash_and_fixed_seed_order_are_reproducible(self):
        from scripts.diagnose_age_seed_stability import diagnostic_contract
        contract = diagnostic_contract()
        self.assertEqual(contract['seeds'], [11, 29, 42, 73, 101])
        self.assertEqual(contract['candidate_order'], list(driver.MATCHED))
        self.assertEqual(driver.canonical_sha256(contract), '43644959e7ad4ba23b7d76bf1d9934e6a41db33d1f64ddd84bb65a55d7699294')
        self.assertEqual(driver.canonical_sha256({'a': 1, 'b': 2}), driver.canonical_sha256({'b': 2, 'a': 1}))

    def test_outputs_require_git_ignored_paths(self):
        with patch.object(driver.subprocess, 'run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(ValueError, 'must be Git ignored'):
                driver.ensure_ignored([driver.ROOT / 'reports/stage4/local-model.joblib'])
            run.return_value.returncode = 0
            driver.ensure_ignored([driver.ROOT / 'models/research/age_seed_stability_versions'])


if __name__ == '__main__':
    unittest.main()
