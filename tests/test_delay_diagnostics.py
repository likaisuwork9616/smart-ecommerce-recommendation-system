"""Hand-calculated error diagnostics on synthetic orders, without model files."""

import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.diagnose_delay_errors import (
    add_diagnostic_groups,
    error_metrics,
    score_frame,
    standardized_monthly_fpr,
)


def scored_rows(labels, predictions):
    return pd.DataFrame({
        "delayed": labels,
        "delay_score": [0.9 if prediction else 0.1 for prediction in predictions],
        "predicted_delayed": predictions,
    })


def stratum_rows(month, state, promise, on_time_rows, false_positives, delayed_rows=0):
    rows = []
    for index in range(on_time_rows + delayed_rows):
        delayed = int(index >= on_time_rows)
        predicted = int(index < false_positives or delayed)
        rows.append({
            "month": month,
            "customer_state": state,
            "promise_band": promise,
            "delayed": delayed,
            "delay_score": 0.9 if predicted else 0.1,
            "predicted_delayed": predicted,
        })
    return rows


class FixedScorePipeline:
    """Return the synthetic probe as class-1 score, with reversed class order."""

    classes_ = np.array([1, 0])

    def predict_proba(self, features):
        if list(features.columns) != ["probe"]:
            raise AssertionError("Only the artifact feature whitelist may reach the model")
        scores = features["probe"].to_numpy(dtype=float)
        return np.column_stack([scores, 1.0 - scores])


class ErrorMetricsTests(unittest.TestCase):
    def test_confusion_and_rates_match_hand_calculation(self):
        frame = scored_rows(
            [1, 1, 1, 0, 0, 0, 0, 0],
            [1, 1, 0, 1, 1, 1, 0, 0],
        )
        result = error_metrics(frame)
        expected_counts = {
            "rows": 8,
            "on_time_rows": 5,
            "delayed_rows": 3,
            "true_positives": 2,
            "false_positives": 3,
            "false_negatives": 1,
            "true_negatives": 2,
            "alert_rows": 5,
        }
        for name, expected in expected_counts.items():
            self.assertEqual(result[name], expected, name)
        self.assertAlmostEqual(result["false_positive_rate"], 3 / 5)
        self.assertAlmostEqual(result["precision"], 2 / 5)
        self.assertAlmostEqual(result["recall"], 2 / 3)
        self.assertAlmostEqual(result["false_discovery_rate"], 3 / 5)
        self.assertAlmostEqual(result["false_positives_per_1000_orders"], 375.0)

    def test_missing_denominators_are_none_and_defined_zero_rates_stay_zero(self):
        empty = error_metrics(scored_rows([], []))
        for name in (
            "false_positive_rate", "precision", "recall",
            "false_discovery_rate", "false_positives_per_1000_orders",
        ):
            self.assertIsNone(empty[name], name)
        self.assertEqual(empty["rows"], 0)

        on_time_only = error_metrics(scored_rows([0, 0], [0, 0]))
        self.assertEqual(on_time_only["false_positive_rate"], 0.0)
        self.assertEqual(on_time_only["false_positives_per_1000_orders"], 0.0)
        self.assertIsNone(on_time_only["recall"])
        self.assertIsNone(on_time_only["precision"])
        self.assertIsNone(on_time_only["false_discovery_rate"])

        delayed_only = error_metrics(scored_rows([1, 1], [1, 0]))
        self.assertIsNone(delayed_only["false_positive_rate"])
        self.assertEqual(delayed_only["precision"], 1.0)
        self.assertEqual(delayed_only["recall"], 0.5)
        self.assertEqual(delayed_only["false_discovery_rate"], 0.0)

    def test_scoring_uses_saved_threshold_inclusively_and_preserves_rows(self):
        frame = pd.DataFrame({
            "order_id": ["below", "equal", "above"],
            "probe": [0.4999, 0.5, 0.5001],
            "delayed": [0, 1, 0],
            "customer_state": ["SP", "RJ", "MG"],
        }, index=[4, 9, 12])
        before = frame.copy(deep=True)
        artifact = {
            "format_version": 1,
            "pipeline": FixedScorePipeline(),
            "threshold": 0.5,
            "feature_names": ["probe"],
            "numeric_features": ["probe"],
            "categorical_features": [],
        }
        result = score_frame(frame, artifact)
        self.assertEqual(result["order_id"].tolist(), ["below", "equal", "above"])
        self.assertEqual(result["predicted_delayed"].tolist(), [0, 1, 1])
        np.testing.assert_allclose(result["delay_score"], [0.4999, 0.5, 0.5001])
        self.assertEqual(result["delayed"].tolist(), frame["delayed"].tolist())
        assert_frame_equal(frame, before)


class DiagnosticGroupingTests(unittest.TestCase):
    def test_promise_seller_volume_and_freight_boundaries_include_the_right_edge(self):
        frame = pd.DataFrame({
            "primary_seller_id": [
                "unknown", "one", "nineteen", "twenty", "ninety_nine",
                "hundred", None, "unknown", "one", "one", "one",
            ],
            "estimated_delivery_days": [0, 7, 8, 14, 15, 21, 22, 30, 31, 100, np.nan],
            "freight_ratio": [0, .10, .100001, .25, .250001, .50, .500001, 1.0, np.nan, .05, .15],
            "interstate_item_ratio": [0.0] * 11,
            "customer_state": ["SP"] * 11,
            "primary_seller_state": ["SP"] * 11,
        })
        training_counts = pd.Series({
            "one": 1, "nineteen": 19, "twenty": 20,
            "ninety_nine": 99, "hundred": 100,
        })
        before = frame.copy(deep=True)
        result = add_diagnostic_groups(frame, training_counts)
        self.assertEqual(result["promise_band"].tolist(), [
            "0-7", "0-7", "8-14", "8-14", "15-21", "15-21",
            "22-30", "22-30", "31+", "31+", "missing",
        ])
        self.assertEqual(result["seller_training_volume"].tolist(), [
            "unseen", "1-19", "1-19", "20-99", "20-99", "100+",
            "missing", "unseen", "1-19", "1-19", "1-19",
        ])
        self.assertEqual(result["freight_band"].tolist(), [
            "0-.10", "0-.10", ".10-.25", ".10-.25", ".25-.50", ".25-.50",
            ".50+", ".50+", "missing", "0-.10", ".10-.25",
        ])
        assert_frame_equal(frame, before)

    def test_same_state_interstate_mixed_and_unknown_routes_are_distinct(self):
        frame = pd.DataFrame({
            "primary_seller_id": ["seller"] * 4,
            "estimated_delivery_days": [10] * 4,
            "freight_ratio": [.2] * 4,
            "interstate_item_ratio": [0.0, 1.0, 0.5, np.nan],
            "customer_state": ["SP", "RJ", "SP", None],
            "primary_seller_state": ["SP", "SP", "RJ", "SP"],
        })
        result = add_diagnostic_groups(frame, pd.Series({"seller": 100}))
        self.assertEqual(
            result["route_type"].tolist(),
            ["same_state", "all_interstate", "mixed", "missing"],
        )
        self.assertEqual(result["state_route"].tolist(), [
            "SP -> SP", "SP -> RJ", "RJ -> SP", "SP -> missing",
        ])


class StandardizedFalsePositiveRateTests(unittest.TestCase):
    def test_fixed_pooled_weights_remove_a_hand_calculated_composition_difference(self):
        rows = (
            stratum_rows("2018-01", "SP", "0-7", 80, 8, delayed_rows=5)
            + stratum_rows("2018-01", "RJ", "8-14", 20, 10)
            + stratum_rows("2018-01", "MG", "15-21", 40, 20)
            + stratum_rows("2018-02", "SP", "0-7", 20, 2, delayed_rows=7)
            + stratum_rows("2018-02", "RJ", "8-14", 80, 40)
            + stratum_rows("2018-02", "MG", "15-21", 19, 0)
        )
        result = standardized_monthly_fpr(pd.DataFrame(rows), min_on_time=20)
        self.assertEqual(result["common_strata"], 2)
        months = {row["month"]: row for row in result["months"]}
        self.assertEqual(set(months), {"2018-01", "2018-02"})
        january, february = months["2018-01"], months["2018-02"]
        self.assertEqual(january["on_time_rows_covered"], 100)
        self.assertEqual(february["on_time_rows_covered"], 100)
        self.assertAlmostEqual(january["coverage"], 100 / 140)
        self.assertAlmostEqual(february["coverage"], 100 / 119)
        self.assertAlmostEqual(january["observed_fpr_on_common_strata"], 0.18)
        self.assertAlmostEqual(february["observed_fpr_on_common_strata"], 0.42)
        self.assertAlmostEqual(january["standardized_fpr"], 0.30)
        self.assertAlmostEqual(february["standardized_fpr"], 0.30)

    def test_pooled_weights_reflect_unequal_monthly_sample_sizes(self):
        frame = pd.DataFrame(
            stratum_rows("2018-01", "SP", "0-7", 80, 8)
            + stratum_rows("2018-01", "RJ", "8-14", 20, 10)
            + stratum_rows("2018-02", "SP", "0-7", 20, 4)
            + stratum_rows("2018-02", "RJ", "8-14", 180, 72)
        )
        result = standardized_monthly_fpr(frame, min_on_time=20)
        months = {row["month"]: row for row in result["months"]}
        weights = {
            (row["customer_state"], row["promise_band"]): row["weight"]
            for row in result["weights"]
        }
        self.assertAlmostEqual(weights[("SP", "0-7")], 1 / 3)
        self.assertAlmostEqual(weights[("RJ", "8-14")], 2 / 3)
        self.assertAlmostEqual(months["2018-01"]["standardized_fpr"], 11 / 30)
        self.assertAlmostEqual(months["2018-02"]["standardized_fpr"], 1 / 3)

    def test_no_supported_common_stratum_cannot_produce_a_standardized_rate(self):
        frame = pd.DataFrame(
            stratum_rows("2018-01", "SP", "0-7", 20, 2)
            + stratum_rows("2018-02", "SP", "0-7", 19, 2)
        )
        result = standardized_monthly_fpr(frame, min_on_time=20)
        self.assertEqual(result["common_strata"], 0)
        self.assertEqual(len(result["months"]), 2)
        for month in result["months"]:
            self.assertEqual(month["on_time_rows_covered"], 0)
            self.assertEqual(month["coverage"], 0.0)
            self.assertIsNone(month["observed_fpr_on_common_strata"])
            self.assertIsNone(month["standardized_fpr"])


if __name__ == "__main__":
    unittest.main()
