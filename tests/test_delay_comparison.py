"""Backtest boundary and model compatibility checks using synthetic records only."""

import unittest

import numpy as np
import pandas as pd

from scripts.compare_delay_models import make_candidates, split_backtest_fold
from scripts.delay_features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from scripts.train_delay_model import positive_probability


EXPECTED_MODELS = {
    "dummy_most_frequent",
    "balanced_logistic_regression",
    "random_forest",
    "extra_trees",
    "hist_gradient_boosting",
    "xgboost",
    "lightgbm",
}


def temporal_records():
    rows = []
    for day in pd.date_range("2018-01-01", "2018-01-24"):
        for hour, delayed in ((8, 0), (20, 1)):
            prediction = day + pd.Timedelta(hours=hour)
            rows.append({
                "order_id": f"{day:%Y%m%d}_{hour}",
                "order_purchase_timestamp": prediction - pd.Timedelta(hours=1),
                "prediction_time": prediction,
                "label_available_time": prediction + pd.Timedelta(hours=2),
                "delayed": delayed,
            })
    for order_id, prediction, available, delayed in (
        ("train_boundary_label", "2018-01-07 12:00", "2018-01-08 00:00", 1),
        ("validation_boundary_label", "2018-01-14 12:00", "2018-01-15 00:00", 1),
        ("evaluation_late_label", "2018-01-21 12:00", "2018-06-01 00:00", 1),
        ("evaluation_end", "2018-01-22 00:00", "2018-01-23 00:00", 0),
        ("original_test_start", "2018-05-26 00:00", "2018-05-27 00:00", 1),
    ):
        prediction = pd.Timestamp(prediction)
        rows.append({
            "order_id": order_id,
            "order_purchase_timestamp": prediction - pd.Timedelta(hours=1),
            "prediction_time": prediction,
            "label_available_time": pd.Timestamp(available),
            "delayed": delayed,
        })
    return pd.DataFrame(rows)


def synthetic_features(rows=120, category_count=6):
    random = np.random.default_rng(2026)
    features = pd.DataFrame({
        name: random.uniform(0.1, 10.0, size=rows)
        for name in NUMERIC_FEATURES
    })
    for name in CATEGORICAL_FEATURES:
        features[name] = [f"category_{index % category_count}" for index in range(rows)]
    features.loc[0, NUMERIC_FEATURES[0]] = np.nan
    features.loc[1, CATEGORICAL_FEATURES[0]] = np.nan
    target = pd.Series(np.arange(rows) % 2, name="delayed")
    return features, target


def reduce_smoke_fit_size(pipeline):
    """Keep the actual estimator/preprocessor types while limiting test runtime."""
    classifier = pipeline.named_steps["classifier"]
    parameters = classifier.get_params(deep=False)
    updates = {}
    if "n_estimators" in parameters:
        updates["classifier__n_estimators"] = 8
    if "max_iter" in parameters and classifier.__class__.__name__ == "HistGradientBoostingClassifier":
        updates["classifier__max_iter"] = 5
    if updates:
        pipeline.set_params(**updates)
    return pipeline


class BacktestSplitTests(unittest.TestCase):
    def setUp(self):
        self.frame = temporal_records()
        self.boundaries = ("2018-01-08", "2018-01-15", "2018-01-22")

    def split(self, frame=None, boundaries=None):
        return split_backtest_fold(
            self.frame if frame is None else frame,
            *(self.boundaries if boundaries is None else boundaries),
        )

    def test_whole_day_intervals_are_disjoint_and_exclude_original_test(self):
        splits, _ = self.split()
        train = splits["train"]
        validation = splits["validation"]
        evaluation = splits["evaluation"]
        self.assertTrue((train["prediction_time"] < pd.Timestamp("2018-01-08")).all())
        self.assertTrue(validation["prediction_time"].between(
            pd.Timestamp("2018-01-08"), pd.Timestamp("2018-01-15"), inclusive="left"
        ).all())
        self.assertTrue(evaluation["prediction_time"].between(
            pd.Timestamp("2018-01-15"), pd.Timestamp("2018-01-22"), inclusive="left"
        ).all())
        self.assertTrue({"20180108_8", "20180108_20"}.issubset(set(validation["order_id"])))
        self.assertTrue({"20180115_8", "20180115_20"}.issubset(set(evaluation["order_id"])))
        identifier_sets = [set(part["order_id"]) for part in splits.values()]
        for left in range(len(identifier_sets)):
            for right in range(left + 1, len(identifier_sets)):
                self.assertFalse(identifier_sets[left] & identifier_sets[right])
        all_identifiers = set().union(*identifier_sets)
        self.assertNotIn("evaluation_end", all_identifiers)
        self.assertNotIn("original_test_start", all_identifiers)

    def test_training_and_threshold_validation_require_strictly_mature_labels(self):
        splits, report = self.split()
        self.assertTrue((splits["train"]["label_available_time"] < pd.Timestamp("2018-01-08")).all())
        self.assertTrue((splits["validation"]["label_available_time"] < pd.Timestamp("2018-01-15")).all())
        self.assertNotIn("train_boundary_label", set(splits["train"]["order_id"]))
        self.assertNotIn("validation_boundary_label", set(splits["validation"]["order_id"]))
        self.assertEqual(report["partitions"]["train"]["purged_rows"], 1)
        self.assertEqual(report["partitions"]["validation"]["purged_rows"], 1)

    def test_duplicate_dataframe_indices_do_not_change_purge_counts(self):
        expected_splits, expected_report = self.split()
        frame = self.frame.copy()
        frame.index = [0] * len(frame)
        splits, report = self.split(frame=frame)
        self.assertEqual(report, expected_report)
        for name in splits:
            self.assertEqual(set(splits[name].order_id), set(expected_splits[name].order_id))

    def test_evaluation_retains_later_outcomes_without_using_future_prediction_cohorts(self):
        splits, report = self.split()
        evaluation = splits["evaluation"].set_index("order_id")
        self.assertIn("evaluation_late_label", evaluation.index)
        self.assertEqual(
            evaluation.loc["evaluation_late_label", "label_available_time"],
            pd.Timestamp("2018-06-01"),
        )
        self.assertEqual(report["partitions"]["evaluation"]["purged_rows"], 0)
        self.assertTrue((evaluation["prediction_time"] < pd.Timestamp("2018-05-26")).all())

    def test_waiting_gap_excludes_new_predictions_but_matures_validation_labels(self):
        extra = pd.DataFrame([
            {
                "order_id": "validation_label_in_waiting_gap",
                "order_purchase_timestamp": pd.Timestamp("2018-01-10 11:00"),
                "prediction_time": pd.Timestamp("2018-01-10 12:00"),
                "label_available_time": pd.Timestamp("2018-01-14 12:00"),
                "delayed": 1,
            },
            {
                "order_id": "validation_label_at_evaluation_start",
                "order_purchase_timestamp": pd.Timestamp("2018-01-10 12:00"),
                "prediction_time": pd.Timestamp("2018-01-10 13:00"),
                "label_available_time": pd.Timestamp("2018-01-15 00:00"),
                "delayed": 1,
            },
        ])
        frame = pd.concat([self.frame, extra], ignore_index=True)
        splits, _ = split_backtest_fold(
            frame, *self.boundaries, validation_end="2018-01-11"
        )
        validation_ids = set(splits["validation"]["order_id"])
        self.assertIn("validation_label_in_waiting_gap", validation_ids)
        self.assertNotIn("validation_label_at_evaluation_start", validation_ids)
        gap_ids = set(frame.loc[frame["prediction_time"].between(
            pd.Timestamp("2018-01-11"), pd.Timestamp("2018-01-15"), inclusive="left"
        ), "order_id"])
        included_ids = set().union(*(set(part["order_id"]) for part in splits.values()))
        self.assertFalse(gap_ids & included_ids)

    def test_invalid_or_non_midnight_boundaries_fail(self):
        invalid = (
            ("2018-01-08 12:00", "2018-01-15", "2018-01-22"),
            ("2018-01-08", "2018-01-08", "2018-01-22"),
            ("2018-01-15", "2018-01-08", "2018-01-22"),
            ("2018-01-08", "2018-01-15", "2018-01-15"),
            ("2018-01-08", "2018-01-15", "2018-05-27"),
        )
        for boundaries in invalid:
            with self.subTest(boundaries=boundaries), self.assertRaises(ValueError):
                self.split(boundaries=boundaries)
        for validation_end in ("2018-01-08", "2018-01-16", "2018-01-11 12:00"):
            with self.subTest(validation_end=validation_end), self.assertRaises(ValueError):
                split_backtest_fold(
                    self.frame, *self.boundaries, validation_end=validation_end
                )

    def test_missing_class_fails_in_each_partition(self):
        prediction = self.frame["prediction_time"]
        masks = {
            "train": prediction < pd.Timestamp("2018-01-08"),
            "validation": prediction.between(
                pd.Timestamp("2018-01-08"), pd.Timestamp("2018-01-15"), inclusive="left"
            ),
            "evaluation": prediction.between(
                pd.Timestamp("2018-01-15"), pd.Timestamp("2018-01-22"), inclusive="left"
            ),
        }
        for partition, mask in masks.items():
            frame = self.frame.copy()
            frame.loc[mask, "delayed"] = 0
            with self.subTest(partition=partition), self.assertRaises(ValueError):
                self.split(frame=frame)


class ComparisonCandidateSmokeTests(unittest.TestCase):
    def test_all_seven_models_fit_and_score_missing_and_unseen_values(self):
        features, target = synthetic_features()
        holdout, _ = synthetic_features(rows=24)
        holdout.loc[0, CATEGORICAL_FEATURES[0]] = "previously_unseen_state"
        candidates = make_candidates(target, seed=7, n_jobs=1)
        self.assertEqual(set(candidates), EXPECTED_MODELS)
        for name, pipeline in candidates.items():
            with self.subTest(model=name):
                reduce_smoke_fit_size(pipeline).fit(features, target)
                scores = positive_probability(pipeline, holdout)
                self.assertEqual(scores.shape, (len(holdout),))
                self.assertTrue(np.isfinite(scores).all())
                self.assertTrue(((scores >= 0.0) & (scores <= 1.0)).all())

    def test_hist_gradient_boosting_handles_dense_encoded_input(self):
        # 25 levels x 20 observations retain many one-hot columns. A default
        # sparse preprocessor would produce CSR input that HGB cannot consume.
        features, target = synthetic_features(rows=500, category_count=25)
        pipeline = make_candidates(target, seed=7, n_jobs=1)["hist_gradient_boosting"]
        reduce_smoke_fit_size(pipeline).fit(features, target)
        transformed = pipeline.named_steps["preprocessor"].transform(features)
        self.assertIsInstance(transformed, np.ndarray)
        self.assertTrue(np.isfinite(positive_probability(pipeline, features.iloc[:5])).all())


if __name__ == "__main__":
    unittest.main()
