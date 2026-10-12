"""Synthetic checks for recall-constrained, validation-only alert decisions."""

import json
import unittest

import numpy as np

from scripts.delay_alert_policy import choose_recall_threshold


class RecallThresholdTests(unittest.TestCase):
    def test_known_choice_minimizes_alerts_at_the_requested_recall(self):
        labels = [0, 1, 0, 1, 1, 0]
        scores = [0.95, 0.90, 0.85, 0.80, 0.70, 0.10]
        threshold, policy = choose_recall_threshold(labels, scores, min_recall=0.50)
        self.assertEqual(threshold, 0.80)
        self.assertAlmostEqual(policy["achieved_recall"], 2 / 3)
        self.assertEqual(policy["predicted_positive_rows"], 4)
        self.assertEqual(policy["true_positive_rows"], 2)
        self.assertEqual(policy["false_positive_rows"], 2)
        self.assertAlmostEqual(policy["alert_rate"], 4 / 6)
        self.assertEqual(policy["precision"], 0.50)

    def test_tied_scores_are_indivisible_and_independent_of_input_order(self):
        labels = np.array([0, 1, 0, 1, 0, 1])
        scores = np.array([0.90, 0.80, 0.80, 0.80, 0.80, 0.10])
        threshold, policy = choose_recall_threshold(labels, scores, min_recall=0.30)
        self.assertEqual(threshold, 0.80)
        self.assertEqual(policy["predicted_positive_rows"], 5)
        self.assertEqual(policy["true_positive_rows"], 2)
        self.assertAlmostEqual(policy["achieved_recall"], 2 / 3)
        permutation = [5, 3, 1, 4, 0, 2]
        shuffled_threshold, shuffled_policy = choose_recall_threshold(
            labels[permutation], scores[permutation], min_recall=0.30
        )
        self.assertEqual(shuffled_threshold, threshold)
        self.assertEqual(shuffled_policy, policy)

    def test_default_policy_uses_only_validation_and_promises_no_evaluation_recall(self):
        threshold, policy = choose_recall_threshold([0, 1, 1, 0], [0.9, 0.8, 0.2, 0.1])
        self.assertEqual(threshold, 0.8)
        self.assertEqual(policy["min_recall"], 0.30)
        self.assertEqual(policy["data"], "validation only")
        self.assertFalse(policy["evaluation_recall_guarantee"])
        self.assertIn("does not guarantee", policy["evaluation_note"])
        json.dumps(policy, allow_nan=False)
        with self.assertRaises(TypeError):
            choose_recall_threshold(
                [0, 1], [0.5, 0.4], evaluation_labels=[1, 0]
            )

    def test_full_recall_uses_the_lowest_positive_score_not_the_lowest_score(self):
        threshold, policy = choose_recall_threshold(
            [0, 1, 0, 1, 0], [1.0, 0.9, 0.8, 0.3, 0.0], min_recall=1.0
        )
        self.assertEqual(threshold, 0.3)
        self.assertEqual(policy["achieved_recall"], 1.0)
        self.assertEqual(policy["predicted_positive_rows"], 4)

    def test_highest_feasible_threshold_matches_an_exhaustive_independent_check(self):
        random = np.random.default_rng(46)
        for target_recall in (0.01, 0.30, 0.50, 0.70, 1.0):
            with self.subTest(min_recall=target_recall):
                labels = random.integers(0, 2, size=40)
                labels[:2] = [0, 1]
                scores = random.integers(0, 11, size=40) / 10
                feasible = []
                for candidate in np.unique(scores):
                    alerted = scores >= candidate
                    recall = np.sum(alerted & (labels == 1)) / np.sum(labels == 1)
                    if recall >= target_recall:
                        feasible.append((candidate, int(alerted.sum())))
                threshold, policy = choose_recall_threshold(labels, scores, target_recall)
                self.assertEqual(threshold, max(candidate for candidate, _ in feasible))
                self.assertEqual(policy["predicted_positive_rows"], min(count for _, count in feasible))
                self.assertGreaterEqual(policy["achieved_recall"], target_recall)

    def test_positive_recall_never_degenerates_to_zero_alerts(self):
        for scores in ([0.0, 0.0], [1.0, 1.0], [0.9, 0.1]):
            with self.subTest(scores=scores):
                _, policy = choose_recall_threshold([0, 1], scores)
                self.assertGreater(policy["predicted_positive_rows"], 0)
                self.assertGreater(policy["true_positive_rows"], 0)

    def test_fractional_target_does_not_round_up_an_exactly_feasible_count(self):
        labels = np.r_[np.ones(25), np.zeros(25)]
        scores = np.r_[np.linspace(1.0, 0.2, 25), np.zeros(25)]
        threshold, policy = choose_recall_threshold(labels, scores, min_recall=0.28)
        self.assertEqual(threshold, scores[6])
        self.assertEqual(policy["true_positive_rows"], 7)
        self.assertEqual(policy["achieved_recall"], 0.28)

    def test_invalid_labels_scores_and_recall_targets_fail(self):
        invalid_vectors = (
            ([], []),
            ([0, 1], [0.5]),
            ([[0, 1]], [0.5, 0.4]),
            ([0, 1], [[0.5, 0.4]]),
            ([0, 0], [0.5, 0.4]),
            ([1, 1], [0.5, 0.4]),
            ([0, 2], [0.5, 0.4]),
            ([0, np.nan, 1], [0.5, 0.4, 0.3]),
            ([0, 1], [np.nan, 0.4]),
            ([0, 1], [np.inf, 0.4]),
            ([0, 1], [-0.1, 0.4]),
            ([0, 1], [0.5, 1.1]),
            ([0, 1], ["not-a-score", 0.4]),
            ([0, 1], [0.5j, 0.4]),
        )
        for labels, scores in invalid_vectors:
            with self.subTest(labels=labels, scores=scores), self.assertRaises(ValueError):
                choose_recall_threshold(labels, scores)
        for target in (0, -0.1, 1.1, np.nan, np.inf, None, [0.3], "not-a-recall", 0.3j):
            with self.subTest(min_recall=target), self.assertRaises(ValueError):
                choose_recall_threshold([0, 1], [0.5, 0.4], target)


if __name__ == "__main__":
    unittest.main()
