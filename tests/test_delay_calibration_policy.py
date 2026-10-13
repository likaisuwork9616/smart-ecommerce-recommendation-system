"""Calibration fitting and daily batch budgets must keep their stated contract."""

import io
import json
import unittest

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from scripts.delay_calibration_policy import (
    apply_alert_policy,
    choose_budget_threshold,
    fit_calibrator,
    probability_metrics,
    transform_scores,
)


def batch_frame(sizes=(10,), start='2018-01-01'):
    rows = []
    for day, size in enumerate(sizes):
        for offset in range(size):
            rows.append({
                'order_id': f'day{day:02d}-order{offset:03d}',
                'prediction_time': pd.Timestamp(start) + pd.Timedelta(days=day, minutes=offset),
            })
    return pd.DataFrame(rows)


class ScoreCalibrationTests(unittest.TestCase):
    def test_raw_identity_and_isotonic_interpolation_are_bounded_and_monotone(self):
        labels, scores = [0, 0, 1, 1], [.1, .2, .8, .9]
        query = np.array([0., .15, .5, .85, 1.])
        raw = fit_calibrator(labels, scores, 'raw')
        np.testing.assert_array_equal(transform_scores(raw, query), query)
        isotonic = fit_calibrator(labels, scores, 'isotonic')
        actual = transform_scores(isotonic, query)
        np.testing.assert_allclose(actual, [0., 0., .5, 1., 1.])
        self.assertTrue(np.all(np.diff(actual) >= 0.))

    def test_sigmoid_uses_observed_prevalence_without_balancing_classes(self):
        # A balanced calibrator would keep this constant output near .5.
        calibrator = fit_calibrator(np.r_[np.zeros(180), np.ones(20)],
                                    np.full(200, .8), 'sigmoid')
        probability = transform_scores(calibrator, [.8])[0]
        self.assertAlmostEqual(probability, .1, delta=.002)
        self.assertEqual(calibrator.fit_rows, 200)
        self.assertEqual(calibrator.fit_positive_rows, 20)

    def test_positive_sigmoid_and_reversed_relationship_never_reverse_rank(self):
        scores = np.linspace(.02, .98, 100)
        for labels in (np.r_[np.zeros(80), np.ones(20)],
                       np.r_[np.ones(20), np.zeros(80)]):
            calibrator = fit_calibrator(labels, scores, 'sigmoid')
            values = transform_scores(calibrator, scores)
            self.assertTrue(np.isfinite(values).all())
            self.assertTrue(np.all((0 <= values) & (values <= 1)))
            self.assertTrue(np.all(np.diff(values) >= -1e-14))
        # A negative fitted slope falls back to the calibration sample prevalence.
        reversed_calibrator = fit_calibrator(np.r_[np.ones(20), np.zeros(80)],
                                             scores, 'sigmoid')
        np.testing.assert_allclose(transform_scores(reversed_calibrator, [0., .5, 1.]), .2)

    def test_fitted_mapping_is_independent_of_later_input_mutation_and_serializes(self):
        for method in ('raw', 'sigmoid', 'isotonic'):
            labels = np.array([0, 0, 1, 0, 1, 1])
            scores = np.array([.1, .2, .3, .6, .7, .9])
            calibrator = fit_calibrator(labels, scores, method)
            before = transform_scores(calibrator, [.1, .4, .8])
            labels[:] = 1 - labels
            scores[:] = 1 - scores
            np.testing.assert_array_equal(transform_scores(calibrator, [.1, .4, .8]), before)
            stream = io.BytesIO()
            joblib.dump(calibrator, stream)
            stream.seek(0)
            restored = joblib.load(stream)
            np.testing.assert_array_equal(transform_scores(restored, [.1, .4, .8]), before)

    def test_invalid_fit_vectors_and_unrecognized_methods_fail(self):
        invalid = (
            ([], []), ([0, 1], [.1]), ([[0, 1]], [.1, .9]),
            ([0, 0], [.1, .9]), ([1, 1], [.1, .9]),
            ([0, 2], [.1, .9]), ([0, np.nan, 1], [.1, .5, .9]),
            ([0, 1], [np.nan, .9]), ([0, 1], [-.1, .9]),
            ([0, 1], [.1, 1.1]), ([0, 1], [.1j, .9]),
        )
        for method in ('raw', 'sigmoid', 'isotonic'):
            for labels, scores in invalid:
                with self.subTest(method=method, labels=labels, scores=scores), self.assertRaises(ValueError):
                    fit_calibrator(labels, scores, method)
        with self.assertRaises(ValueError):
            fit_calibrator([0, 1], [.1, .9], 'unknown')

    def test_transform_rejects_invalid_scores_and_cannot_fit_on_query_labels(self):
        calibrator = fit_calibrator([0, 1], [.1, .9], 'sigmoid')
        for scores in ([], [[.1]], [.1, np.inf], [.1, np.nan], [-.01], [1.01], [.1j]):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                transform_scores(calibrator, scores)
        with self.assertRaises(TypeError):
            transform_scores(calibrator, [.1, .9], labels=[1, 0])


class DailyBudgetTests(unittest.TestCase):
    def test_cap_is_floored_per_calendar_day_and_cannot_borrow_capacity(self):
        frame = batch_frame((11, 9))
        scores = np.linspace(.99, .01, len(frame))
        alerted = apply_alert_policy(frame, scores, 0., .10)
        self.assertEqual(int(alerted.sum()), 1)
        self.assertTrue(alerted[0])
        self.assertFalse(alerted[11:].any())
        # Floating binary multiplication must not turn 29% of 100 into 28 orders.
        larger = batch_frame((100,))
        self.assertEqual(int(apply_alert_policy(larger, np.full(100, .5), 0., .29).sum()), 29)
        self.assertFalse(apply_alert_policy(frame, scores, 0., 0.).any())

    def test_threshold_is_applied_before_cap_and_includes_equal_scores(self):
        frame = batch_frame((10,))
        scores = np.array([.9, .8, .7, .6, .5, .4, .3, .2, .1, 0.])
        np.testing.assert_array_equal(apply_alert_policy(frame, scores, .8, .50), scores >= .8)
        np.testing.assert_array_equal(apply_alert_policy(frame, scores, .8, None), scores >= .8)
        self.assertFalse(apply_alert_policy(frame, scores, 1., .10).any())

    def test_ties_use_raw_score_then_order_id_and_ignore_external_dataframe_index(self):
        frame = batch_frame((10,))
        frame.index = [5] * len(frame)
        scores = np.full(10, .4)
        raw = np.array([.1, .9, .8, .9, .3, .2, .7, .4, .5, .6])
        alerted = apply_alert_policy(frame, scores, .4, .20, raw_scores=raw)
        self.assertEqual(set(frame.loc[alerted, 'order_id']),
                         {'day00-order001', 'day00-order003'})
        permutation = np.array([9, 4, 7, 1, 5, 3, 8, 6, 2, 0])
        shuffled = apply_alert_policy(frame.iloc[permutation], scores[permutation], .4, .20,
                                     raw_scores=raw[permutation])
        self.assertEqual(set(frame.iloc[permutation].loc[shuffled, 'order_id']),
                         set(frame.loc[alerted, 'order_id']))
        raw[:] = .5
        tied = apply_alert_policy(frame, scores, .4, .20, raw_scores=raw)
        self.assertEqual(set(frame.loc[tied, 'order_id']),
                         {'day00-order000', 'day00-order001'})

    def test_apply_never_uses_outcomes_and_batches_are_independent(self):
        frame = batch_frame((10, 10))
        frame['delayed'] = np.arange(20) % 2
        frame['label_available_time'] = pd.Timestamp('2018-01-10')
        scores = np.linspace(.05, .95, len(frame))
        before = apply_alert_policy(frame, scores, .1, .20)
        frame['delayed'] = 1 - frame.delayed
        frame['label_available_time'] = pd.Timestamp('2099-01-01')
        after = apply_alert_policy(frame, scores, .1, .20)
        np.testing.assert_array_equal(before, after)
        np.testing.assert_array_equal(before[:10], apply_alert_policy(frame.iloc[:10], scores[:10], .1, .20))
        np.testing.assert_array_equal(before[10:], apply_alert_policy(frame.iloc[10:], scores[10:], .1, .20))

    def test_duplicate_ids_missing_timestamps_and_invalid_budget_inputs_fail(self):
        frame = batch_frame((10,))
        invalid_frames = [frame.drop(columns='order_id'), frame.drop(columns='prediction_time')]
        duplicate = frame.copy()
        duplicate.loc[1, 'order_id'] = duplicate.loc[0, 'order_id']
        invalid_frames.append(duplicate)
        for column, value in (('order_id', None), ('prediction_time', pd.NaT)):
            changed = frame.copy()
            changed.loc[0, column] = value
            invalid_frames.append(changed)
        for changed in invalid_frames:
            with self.subTest(frame=changed.head()), self.assertRaises(ValueError):
                apply_alert_policy(changed, np.full(len(changed), .5), .3, .10)
        for cap in (-.1, 1.1, np.inf, np.nan, [.1], 'bad'):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                apply_alert_policy(frame, np.full(10, .5), .3, cap)
        for threshold in (-.1, 1.1, np.inf, np.nan, [.3], 'bad'):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                apply_alert_policy(frame, np.full(10, .5), threshold, .1)
        with self.assertRaises(ValueError):
            apply_alert_policy(frame, np.full(9, .5), .3, .10)


class BudgetThresholdTests(unittest.TestCase):
    def test_feasible_threshold_minimizes_all_alerts_at_recall_floor(self):
        frame = batch_frame((10, 10))
        scores = np.tile(np.arange(10, 0, -1) / 10, 2)
        labels = np.zeros(20, dtype=int)
        labels[[0, 1, 7, 10, 18]] = 1
        threshold, policy = choose_budget_threshold(frame, labels, scores, .20, min_recall=.30)
        self.assertEqual(threshold, 1.)
        self.assertTrue(policy['feasible'])
        self.assertEqual(policy['predicted_positive_rows'], 2)
        self.assertEqual(policy['true_positive_rows'], 2)
        self.assertEqual(policy['achieved_recall'], .4)
        self.assertFalse(policy['evaluation_recall_guarantee'])
        json.dumps(policy, allow_nan=False)

    def test_infeasible_budget_keeps_hard_cap_and_reports_maximum_recall(self):
        frame = batch_frame((10,))
        scores = np.arange(10, 0, -1) / 10
        labels = np.array([0, 1, 1, 1, 1, 0, 0, 0, 0, 0])
        threshold, policy = choose_budget_threshold(frame, labels, scores, .10, min_recall=.30)
        self.assertEqual(threshold, 0.)
        self.assertFalse(policy['feasible'])
        self.assertEqual(policy['max_achievable_recall'], 0.)
        self.assertEqual(policy['achieved_recall'], 0.)
        self.assertEqual(policy['predicted_positive_rows'], 1)
        self.assertEqual(policy['false_positive_rows'], 1)
        _, zero_budget = choose_budget_threshold(frame, labels, scores, 0., min_recall=.30)
        self.assertFalse(zero_budget['feasible'])
        self.assertEqual(zero_budget['predicted_positive_rows'], 0)
        self.assertEqual(zero_budget['daily_capacity_rows'], 0)

    def test_threshold_matches_independent_exhaustive_search_under_ties(self):
        rng = np.random.default_rng(67)
        frame = batch_frame((13, 12, 17))
        labels = rng.integers(0, 2, len(frame))
        labels[:2] = [0, 1]
        raw = rng.integers(0, 11, len(frame)) / 10
        # Isotonic plateaus make calibrated ties common; raw ranks resolve them.
        scores = np.round(raw * 2) / 2
        for cap in (None, .10, .20, .50):
            for target in (.1, .3, .5, 1.):
                feasible = []
                for candidate in np.unique(scores):
                    alerts = apply_alert_policy(frame, scores, candidate, cap, raw_scores=raw)
                    recall = np.sum(alerts & (labels == 1)) / labels.sum()
                    if recall >= target:
                        feasible.append((float(candidate), int(alerts.sum())))
                threshold, policy = choose_budget_threshold(frame, labels, scores, cap,
                                                           min_recall=target, raw_scores=raw)
                with self.subTest(cap=cap, target=target):
                    self.assertEqual(policy['feasible'], bool(feasible))
                    if feasible:
                        self.assertEqual(threshold, max(value for value, _ in feasible))
                        self.assertEqual(policy['predicted_positive_rows'], min(n for _, n in feasible))
                    else:
                        self.assertEqual(threshold, 0.)
                    actual = apply_alert_policy(frame, scores, threshold, cap, raw_scores=raw)
                    self.assertEqual(policy['predicted_positive_rows'], int(actual.sum()))

    def test_unknown_high_score_consumes_capacity_but_never_counts_as_a_label(self):
        frame = batch_frame((10,))
        scores = np.arange(10, 0, -1) / 10
        labels = np.array([np.nan, 1, 1, 0, 0, 0, 0, 0, 0, 0], dtype=object)
        known = np.ones(10, dtype=bool)
        known[0] = False
        threshold, policy = choose_budget_threshold(frame, labels, scores, .10, known_mask=known)
        self.assertFalse(policy['feasible'])
        self.assertEqual(threshold, 0.)
        self.assertEqual(policy['daily_capacity_rows'], 1)
        self.assertEqual(policy['full_batch_rows'], 10)
        self.assertEqual(policy['known_rows'], 9)
        self.assertEqual(policy['predicted_positive_rows'], 1)
        self.assertEqual(policy['unknown_predicted_positive_rows'], 1)
        self.assertEqual(policy['known_predicted_positive_rows'], 0)
        self.assertEqual(policy['true_positive_rows'], 0)
        self.assertEqual(policy['false_positive_rows'], 0)
        self.assertEqual(policy['max_achievable_recall'], 0.)
        # Unknown labels can contain garbage and cannot influence selected policy.
        labels[0] = 'future label deliberately unavailable'
        changed_threshold, changed_policy = choose_budget_threshold(frame, labels, scores, .10,
                                                                    known_mask=known)
        self.assertEqual(changed_threshold, threshold)
        self.assertEqual(changed_policy, policy)

    def test_capacity_denominator_uses_unknown_orders_without_dropping_them(self):
        frame = batch_frame((10,))
        scores = np.arange(10, 0, -1) / 10
        labels = np.array([1, 0] + [None] * 8, dtype=object)
        known = np.array([True, True] + [False] * 8)
        threshold, policy = choose_budget_threshold(frame, labels, scores, .10, known_mask=known)
        self.assertTrue(policy['feasible'])
        self.assertEqual(policy['daily_capacity_rows'], 1)
        self.assertEqual(policy['achieved_recall'], 1.)
        self.assertEqual(policy['predicted_positive_rows'], 1)
        self.assertEqual(threshold, 1.)

    def test_unknown_mask_targets_and_observed_labels_are_validated(self):
        frame = batch_frame((10,))
        scores = np.linspace(0, 1, 10)
        labels = np.arange(10) % 2
        invalid_masks = ([True] * 9, [[True] * 10], [1] * 10, [False] * 10)
        for mask in invalid_masks:
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                choose_budget_threshold(frame, labels, scores, .1, known_mask=mask)
        for target in (0, -.1, 1.1, np.inf, np.nan, [.3], 'bad'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                choose_budget_threshold(frame, labels, scores, .1, min_recall=target)
        labels[0] = 2
        with self.assertRaises(ValueError):
            choose_budget_threshold(frame, labels, scores, .1)


class ProbabilityMetricTests(unittest.TestCase):
    def test_probability_losses_match_independent_sklearn_and_bins_preserve_boundaries(self):
        labels = np.array([0, 0, 1, 1, 0, 1])
        probabilities = np.array([0., .1, .2, .5, .9, 1.])
        metrics = probability_metrics(labels, probabilities)
        self.assertAlmostEqual(metrics['brier_score'], brier_score_loss(labels, probabilities))
        self.assertAlmostEqual(metrics['log_loss'], log_loss(labels, probabilities, labels=[0, 1]))
        bins = metrics['reliability_bins']
        self.assertEqual(len(bins), 10)
        self.assertEqual(sum(row['rows'] for row in bins), len(labels))
        self.assertEqual([bins[index]['rows'] for index in (0, 1, 2, 5, 9)], [1, 1, 1, 1, 2])
        self.assertFalse(bins[0]['upper_inclusive'])
        self.assertTrue(bins[-1]['upper_inclusive'])
        for row in bins:
            if row['rows'] == 0:
                self.assertIsNone(row['mean_probability'])
                self.assertIsNone(row['observed_positive_rate'])
                self.assertIsNone(row['absolute_gap'])
        expected_ece = sum(row['rows'] * (row['absolute_gap'] or 0.) for row in bins) / len(labels)
        self.assertAlmostEqual(metrics['expected_calibration_error'], expected_ece)
        json.dumps(metrics, allow_nan=False)

    def test_one_class_probability_metrics_remain_defined(self):
        for label in (0, 1):
            labels = np.full(3, label)
            probabilities = np.array([.1, .2, .9])
            metrics = probability_metrics(labels, probabilities)
            self.assertAlmostEqual(metrics['log_loss'], log_loss(labels, probabilities, labels=[0, 1]))
            self.assertAlmostEqual(metrics['brier_score'], brier_score_loss(labels, probabilities))

    def test_invalid_probability_metric_inputs_fail(self):
        for labels, scores in (([], []), ([0, 1], [.2]), ([0, 2], [.2, .8]),
                               ([0, 1], [np.nan, .8]), ([0, 1], [-.2, .8])):
            with self.subTest(labels=labels, scores=scores), self.assertRaises(ValueError):
                probability_metrics(labels, scores)


if __name__ == '__main__':
    unittest.main()
