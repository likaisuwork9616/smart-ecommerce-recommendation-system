"""Partition and ranking checks for descriptive fixed-budget missed delays."""

import json
import unittest

import numpy as np
import pandas as pd

from scripts.delay_calibration_policy import apply_alert_policy
from scripts.diagnose_budget_misses import analyze_segments, daily_rank_bins


COUNT_KEYS = (
    "rows", "positive_rows", "alerts", "true_positives", "false_positives",
    "false_negatives", "true_negatives",
)


def cohort(sizes=(20, 9, 31, 10)):
    rows = []
    days = ["2017-12-01", "2017-12-02", "2018-02-01", "2018-02-02"]
    promises = [0, 7, 8, 14, 15, 21, 22, 30, 31, 60]
    for day, size in zip(days, sizes, strict=False):
        for offset in range(size):
            state = ["SP", "RJ", None][offset % 3]
            rows.append({
                "order_id": f"{day}-order-{offset:03d}",
                "prediction_time": pd.Timestamp(day) + pd.Timedelta(minutes=offset),
                "delayed": int(offset % 4 == 0),
                "state_route": None if state is None else f"SP->{state}",
                "customer_state": state,
                "estimated_delivery_days": promises[offset % len(promises)],
            })
    return pd.DataFrame(rows)


class BudgetMissDiagnosticsTests(unittest.TestCase):
    def test_every_grouping_and_month_partition_reconcile_all_counts_and_fn_shares(self):
        frame = cohort()
        scores = np.linspace(.01, .99, len(frame))
        predictions = apply_alert_policy(frame, scores, 0, cap=.1)
        report = analyze_segments(frame, predictions, scores)
        aggregate = report["aggregate"]["overall"]
        for key in COUNT_KEYS:
            self.assertEqual(sum(month["overall"][key] for month in report["by_month"].values()), aggregate[key])
        for scope in [report["aggregate"], *report["by_month"].values()]:
            overall = scope["overall"]
            for groups in [*scope["groups"].values(), scope["daily_rank_bins"]]:
                for key in COUNT_KEYS:
                    self.assertEqual(sum(row[key] for row in groups), overall[key])
                expected_scope_share = 1. if overall["false_negatives"] else 0.
                self.assertAlmostEqual(sum(row["share_of_scope_false_negatives"] for row in groups), expected_scope_share)
                self.assertAlmostEqual(
                    sum(row["share_of_all_false_negatives"] for row in groups),
                    overall["false_negatives"] / aggregate["false_negatives"],
                )
        self.assertEqual(set(report["by_month"]), {"2017-12", "2018-02"})
        self.assertIn("unknown", [row["customer_state"] for row in report["aggregate"]["groups"]["customer_state"]])
        json.dumps(report, allow_nan=False)

    def test_undefined_recall_precision_are_null_and_zero_fn_shares_are_explicit(self):
        frame = cohort((10,))
        frame["delayed"] = 0
        report = analyze_segments(frame, np.zeros(len(frame), dtype=bool))
        overall = report["aggregate"]["overall"]
        self.assertIsNone(overall["recall"])
        self.assertIsNone(overall["precision"])
        self.assertEqual(overall["share_of_all_false_negatives"], 0.)
        for rows in report["aggregate"]["groups"].values():
            for row in rows:
                self.assertIsNone(row["recall"])
                self.assertIsNone(row["precision"])
                self.assertEqual(row["share_of_all_false_negatives"], 0.)
                self.assertEqual(row["share_of_scope_false_negatives"], 0.)
        all_alerts = analyze_segments(frame, np.ones(len(frame), dtype=bool))["aggregate"]["overall"]
        self.assertEqual(all_alerts["precision"], 0.)
        self.assertIsNone(all_alerts["recall"])
        self.assertNotIn("daily_rank_bins", report["aggregate"])

    def test_small_sample_flag_requires_both_row_and_positive_boundaries(self):
        parts = []
        for group, rows, positives in (("enough", 30, 5), ("few_rows", 29, 5), ("few_positives", 30, 4)):
            part = pd.concat([cohort((10,))] * 3, ignore_index=True).iloc[:rows].copy()
            part["order_id"] = [f"{group}-{position}" for position in range(rows)]
            part["state_route"] = group
            part["delayed"] = np.arange(rows) < positives
            parts.append(part)
        frame = pd.concat(parts, ignore_index=True)
        report = analyze_segments(frame, np.zeros(len(frame), dtype=bool))
        flags = {row["state_route"]: row["minimum_sample_met"] for row in report["aggregate"]["groups"]["state_route"]}
        self.assertEqual(flags, {"enough": True, "few_rows": False, "few_positives": False})
        self.assertEqual(report["minimum_group_rows"], 30)
        self.assertEqual(report["minimum_group_positive_rows"], 5)

    def test_promise_calendar_boundaries_each_land_in_exactly_one_bin(self):
        frame = cohort((10,))
        frame["delayed"] = 1
        groups = analyze_segments(frame, np.zeros(10, dtype=bool))["aggregate"]["groups"]["promise_days"]
        self.assertEqual({row["promise_bin"]: row["rows"] for row in groups},
                         {"0-7": 2, "8-14": 2, "15-21": 2, "22-30": 2, "31+": 2})
        for invalid in (None, np.nan, np.inf, -1, "unknown"):
            invalid_frame = frame.copy()
            invalid_frame["estimated_delivery_days"] = invalid_frame["estimated_delivery_days"].astype(object)
            invalid_frame.loc[0, "estimated_delivery_days"] = invalid
            with self.assertRaises((ValueError, TypeError)):
                analyze_segments(invalid_frame, np.zeros(10, dtype=bool))

    def test_rank_bins_use_full_daily_denominator_and_match_actual_top_ten_percent(self):
        frame = cohort()
        scores = np.full(len(frame), .5)
        raw = np.tile([.3, .9, .9, .1, .5], 14)
        bins = daily_rank_bins(frame, scores, raw)
        chosen = apply_alert_policy(frame, scores, threshold=0, cap=.1, raw_scores=raw)
        np.testing.assert_array_equal(bins == "<=10%", chosen)
        self.assertEqual(int(chosen.sum()), 2 + 0 + 3 + 1)
        dates = frame.prediction_time.dt.normalize()
        first = bins[dates.eq(pd.Timestamp("2017-12-01"))]
        self.assertEqual({name: int((first == name).sum()) for name in set(first)},
                         {"<=10%": 2, "10-20%": 2, "20-50%": 6, "50%+": 10})
        nine = bins[dates.eq(pd.Timestamp("2017-12-02"))]
        self.assertEqual(int((nine == "<=10%").sum()), 0)
        self.assertEqual(int((nine == "10-20%").sum()), 1)
        self.assertEqual(int((nine == "20-50%").sum()), 3)
        self.assertEqual(int((nine == "50%+").sum()), 5)

    def test_calibration_plateau_ties_use_raw_then_id_and_do_not_consult_labels(self):
        frame = cohort((10,)).iloc[::-1].reset_index(drop=True)
        scores = np.full(10, .5)
        raw = np.full(10, .4)
        raw[0] = raw[1] = .9
        expected_id = min(frame.order_id.iloc[0], frame.order_id.iloc[1])
        bins = daily_rank_bins(frame, scores, raw)
        self.assertEqual(frame.loc[bins == "<=10%", "order_id"].tolist(), [expected_id])
        changed = frame.assign(delayed=1 - frame.delayed)
        np.testing.assert_array_equal(daily_rank_bins(changed, scores, raw), bins)
        # Without raw scores, the lexical ID is the final deterministic key.
        without_raw = daily_rank_bins(frame, scores)
        self.assertEqual(frame.loc[without_raw == "<=10%", "order_id"].tolist(), [min(frame.order_id)])

    def test_permutation_and_duplicate_external_index_preserve_order_identity_results(self):
        frame = cohort()
        frame.index = np.arange(len(frame)) % 3
        scores = np.linspace(.1, .9, len(frame))
        raw = scores[::-1].copy()
        chosen = apply_alert_policy(frame, scores, 0, cap=.1, raw_scores=raw)
        expected_bins = dict(zip(frame.order_id, daily_rank_bins(frame, scores, raw), strict=True))
        expected_report = analyze_segments(frame, chosen, scores, raw)
        permutation = np.random.default_rng(42).permutation(len(frame))
        shuffled = frame.iloc[permutation]
        actual_bins = dict(zip(shuffled.order_id, daily_rank_bins(shuffled, scores[permutation], raw[permutation]), strict=True))
        self.assertEqual(actual_bins, expected_bins)
        self.assertEqual(analyze_segments(shuffled, chosen[permutation], scores[permutation], raw[permutation]), expected_report)

    def test_invalid_score_and_identity_inputs_cannot_silently_misalign_diagnostics(self):
        frame = cohort((10,))
        for values in ([.1] * 9, [[.1] * 10], [.1] * 9 + [np.nan], [.1] * 9 + [1.1]):
            with self.assertRaises(ValueError):
                daily_rank_bins(frame, values)
        for raw in ([.1] * 9, [.1] * 9 + [-.1]):
            with self.assertRaises(ValueError):
                daily_rank_bins(frame, [.5] * 10, raw)
        duplicates = frame.copy()
        duplicates.loc[1, "order_id"] = duplicates.loc[0, "order_id"]
        with self.assertRaises(ValueError):
            daily_rank_bins(duplicates, [.5] * 10)
        with self.assertRaises(ValueError):
            analyze_segments(duplicates, [0] * 10)
        for predictions in ([0] * 9, [0] * 9 + [2], [[0] * 10]):
            with self.assertRaises(ValueError):
                analyze_segments(frame, predictions)
        with self.assertRaises(ValueError):
            analyze_segments(frame.iloc[:0], [])
        invalid_time = frame.copy()
        invalid_time.loc[0, "prediction_time"] = pd.NaT
        with self.assertRaises(ValueError):
            daily_rank_bins(invalid_time, [.5] * 10)
        with self.assertRaises(ValueError):
            analyze_segments(invalid_time, [0] * 10)
        with self.assertRaises(ValueError):
            analyze_segments(frame, [0] * 10, raw_scores=[.5] * 10)
        for invalid in (0, True, "2018-01-01T00:00:00+00:00"):
            invalid_time = frame.copy()
            invalid_time["prediction_time"] = invalid_time["prediction_time"].astype(object)
            invalid_time.loc[0, "prediction_time"] = invalid
            with self.assertRaises(ValueError):
                daily_rank_bins(invalid_time, [.5] * 10)
            with self.assertRaises(ValueError):
                analyze_segments(invalid_time, [0] * 10)


if __name__ == "__main__":
    unittest.main()
