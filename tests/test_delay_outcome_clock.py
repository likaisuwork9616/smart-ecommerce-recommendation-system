"""Training-only deadline maturity must preserve actual delivery event semantics."""

import json
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_index_equal

from scripts.delay_outcome_clock import (
    TRAINING_OUTCOME_COLUMN,
    add_training_outcome_clock,
    split_outcome_training_month,
)
from scripts.delay_rolling_validation import mature_validation_month, split_rolling_month


def cohort():
    specifications = [
        ("old_on", "2017-12-01", "2017-12-05 12:00", "2017-12-10"),
        ("old_late", "2017-12-02", "2017-12-20 12:00", "2017-12-10"),
        ("old_pending_late", "2018-01-01", "2018-04-10", "2018-01-10"),
        ("wait_boundary", "2018-03-02", "2018-03-03", "2018-03-10"),
        ("recent_on", "2018-03-10", "2018-03-12", "2018-03-15"),
        ("recent_late", "2018-03-15", "2018-04-20", "2018-03-20 23:00"),
        ("deadline_equal", "2018-03-20", "2018-04-05", "2018-03-31"),
        ("delivery_equal", "2018-03-20", "2018-04-01", "2018-04-02"),
        ("score_on", "2018-04-01", "2018-04-05", "2018-04-10"),
        ("score_late", "2018-04-02", "2018-05-05", "2018-04-20"),
    ]
    orders = pd.DataFrame([{
        "order_id": name, "order_purchase_timestamp": pd.Timestamp(approval)-pd.Timedelta(hours=1),
        "order_approved_at": pd.Timestamp(approval), "order_delivered_customer_date": pd.Timestamp(actual),
        "order_estimated_delivery_date": pd.Timestamp(promise), "order_status": "delivered",
    } for name, approval, actual, promise in specifications])
    frame = pd.DataFrame({
        "order_id": orders.order_id,
        "order_purchase_timestamp": orders.order_purchase_timestamp,
        "prediction_time": orders.order_approved_at,
        "label_available_time": orders.order_delivered_customer_date,
        "delayed": (orders.order_delivered_customer_date.dt.normalize() > orders.order_estimated_delivery_date.dt.normalize()).astype(int),
        "unchanged_feature": np.arange(len(orders), dtype=float),
    })
    return frame, orders


class OutcomeClockTests(unittest.TestCase):
    def test_minimum_clock_preserves_actual_metadata_features_order_and_external_index(self):
        frame, orders = cohort()
        frame.index = np.arange(len(frame)) % 3
        original = frame.copy(deep=True)
        actual = add_training_outcome_clock(frame, orders.iloc[::-1])
        assert_frame_equal(actual[frame.columns], original)
        assert_index_equal(actual.index, frame.index)
        by_id = actual.set_index("order_id")
        self.assertEqual(by_id.loc["recent_on", TRAINING_OUTCOME_COLUMN], pd.Timestamp("2018-03-12"))
        self.assertEqual(by_id.loc["recent_late", TRAINING_OUTCOME_COLUMN], pd.Timestamp("2018-03-21"))
        self.assertEqual(by_id.loc["old_pending_late", TRAINING_OUTCOME_COLUMN], pd.Timestamp("2018-01-11"))
        self.assertEqual(by_id.loc["deadline_equal", TRAINING_OUTCOME_COLUMN], pd.Timestamp("2018-04-01"))
        self.assertTrue((actual[TRAINING_OUTCOME_COLUMN] >= actual.prediction_time).all())
        self.assertTrue((actual[TRAINING_OUTCOME_COLUMN] <= actual.label_available_time).all())
        assert_frame_equal(add_training_outcome_clock(actual, orders), actual)

    def test_training_clock_and_wait_change_training_only_with_strict_boundaries(self):
        frame, orders = cohort()
        frame = add_training_outcome_clock(frame, orders)
        original_scoring = split_rolling_month(frame, "2018-04-01")[0]["scoring"]
        expected = {
            (0, "delivery"): {"old_on", "old_late", "wait_boundary", "recent_on"},
            (0, "deadline"): {"old_on", "old_late", "old_pending_late", "wait_boundary", "recent_on", "recent_late"},
            (30, "deadline"): {"old_on", "old_late", "old_pending_late"},
        }
        for (wait, clock), identities in expected.items():
            splits, report = split_outcome_training_month(frame, "2018-04-01", wait_days=wait, clock=clock)
            self.assertEqual(set(splits["train"].order_id), identities)
            assert_frame_equal(splits["scoring"], original_scoring)
            self.assertTrue((splits["train"].prediction_time < pd.Timestamp("2018-04-01")-pd.Timedelta(days=wait)).all())
            selected_column = TRAINING_OUTCOME_COLUMN if clock == "deadline" else "label_available_time"
            self.assertTrue((splits["train"][selected_column] < pd.Timestamp("2018-04-01")).all())
            self.assertEqual(report["baseline_60day_delivery_training"]["rows"], 2)
            self.assertEqual(report["added_vs_baseline_60day_delivery"]["rows"], len(identities)-2)
            self.assertEqual(report["partitions"]["train"]["rows"], len(identities))
            self.assertTrue(report["actual_delivery_metadata_preserved"])
            self.assertFalse(report["partitions"]["scoring"]["label_maturity_filter_applied"])
            json.dumps(report, allow_nan=False)
        early_train, early_report = split_outcome_training_month(frame, "2018-04-01", 0, "deadline")
        self.assertEqual(early_report["partitions"]["train"]["outcomes_known_before_delivery_rows"], 2)
        self.assertEqual(early_report["same_wait_delivery_training"]["rows"], 4)
        self.assertEqual(early_report["partitions"]["train"]["actual_delivery_time_max"], "2018-04-20T00:00:00")
        self.assertEqual(early_report["partitions"]["train"]["selected_training_clock_max"], "2018-03-21T00:00:00")
        self.assertNotIn("deadline_equal", early_train["train"].order_id.tolist())
        self.assertNotIn("delivery_equal", early_train["train"].order_id.tolist())

    def test_validation_keeps_actual_delivery_maturity_even_with_early_positive_clock(self):
        frame, orders = cohort()
        frame = add_training_outcome_clock(frame, orders)
        march = frame.loc[frame.prediction_time.dt.strftime("%Y-%m").eq("2018-03")].copy()
        # The original validator requires both mature classes. Add one truly
        # completed March positive, leaving recent_late immature in April.
        completed = march.iloc[[0]].copy()
        completed["order_id"] = "completed_march_late"
        completed["delayed"] = 1
        completed["label_available_time"] = pd.Timestamp("2018-03-25")
        completed[TRAINING_OUTCOME_COLUMN] = pd.Timestamp("2018-03-20")
        march = pd.concat([march, completed], ignore_index=True)
        retained, _ = mature_validation_month(march, "2018-04-01")
        self.assertNotIn("recent_late", retained.order_id.tolist())
        self.assertIn("completed_march_late", retained.order_id.tolist())
        self.assertTrue((retained.label_available_time < pd.Timestamp("2018-04-01")).all())

    def test_later_future_delivery_mutation_preserves_early_training_membership(self):
        frame, orders = cohort()
        original = add_training_outcome_clock(frame, orders)
        before = split_outcome_training_month(original, "2018-04-01", 0, "deadline")[0]["train"]
        selected = frame.order_id.eq("recent_late")
        frame.loc[selected, "label_available_time"] = pd.Timestamp("2018-06-20")
        orders.loc[orders.order_id.eq("recent_late"), "order_delivered_customer_date"] = pd.Timestamp("2018-06-20")
        changed = add_training_outcome_clock(frame, orders)
        after = split_outcome_training_month(changed, "2018-04-01", 0, "deadline")[0]["train"]
        self.assertEqual(before.order_id.tolist(), after.order_id.tolist())
        assert_frame_equal(before.drop(columns="label_available_time"), after.drop(columns="label_available_time"))

    def test_raw_identity_timestamp_status_and_target_mismatches_are_rejected(self):
        frame, orders = cohort()
        for name in ("order_purchase_timestamp", "prediction_time", "label_available_time"):
            changed = frame.copy()
            changed.loc[0, name] += pd.Timedelta(seconds=1)
            with self.assertRaisesRegex(ValueError, "differs from raw"):
                add_training_outcome_clock(changed, orders)
        changed = frame.copy()
        changed.loc[0, "delayed"] = 1-changed.loc[0, "delayed"]
        with self.assertRaisesRegex(ValueError, "labels differ"):
            add_training_outcome_clock(changed, orders)
        changed_orders = orders.copy()
        changed_orders.loc[0, "order_status"] = "canceled"
        with self.assertRaisesRegex(ValueError, "eventually-delivered"):
            add_training_outcome_clock(frame, changed_orders)
        with self.assertRaisesRegex(ValueError, "exist in raw"):
            add_training_outcome_clock(frame, orders.iloc[1:])
        with self.assertRaisesRegex(ValueError, "unique"):
            add_training_outcome_clock(frame, pd.concat([orders, orders.iloc[[0]]]))

    def test_existing_unverified_clock_cannot_be_silently_overwritten(self):
        frame, orders = cohort()
        frame = add_training_outcome_clock(frame, orders)
        frame.loc[0, TRAINING_OUTCOME_COLUMN] += pd.Timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "Existing training outcome clock differs"):
            add_training_outcome_clock(frame, orders)

    def test_invalid_configuration_and_impossible_attached_clock_are_rejected(self):
        frame, orders = cohort()
        with self.assertRaisesRegex(ValueError, "Attach"):
            split_outcome_training_month(frame, "2018-04-01")
        frame = add_training_outcome_clock(frame, orders)
        for wait in (True, -1, 1, 60, 0.0):
            with self.assertRaisesRegex(ValueError, "either 0 or 30"):
                split_outcome_training_month(frame, "2018-04-01", wait_days=wait)
        with self.assertRaisesRegex(ValueError, "clock must"):
            split_outcome_training_month(frame, "2018-04-01", clock="future")
        for value in (pd.Timestamp("1900-01-01"), pd.Timestamp("2099-01-01")):
            changed = frame.copy()
            changed.loc[0, TRAINING_OUTCOME_COLUMN] = value
            with self.assertRaisesRegex(ValueError, "at or after approval"):
                split_outcome_training_month(changed, "2018-04-01")

    def test_scoring_outcomes_and_external_row_order_cannot_change_training_identity(self):
        frame, orders = cohort()
        attached = add_training_outcome_clock(frame, orders)
        before, report_before = split_outcome_training_month(attached, "2018-04-01")
        changed = attached.copy()
        scoring = changed.prediction_time.ge("2018-04-01")
        changed.loc[scoring, "delayed"] = 1-changed.loc[scoring, "delayed"]
        changed.loc[scoring, "label_available_time"] = pd.Timestamp("2019-01-01")
        changed = changed.iloc[::-1]
        changed.index = np.arange(len(changed)) % 2
        after, report_after = split_outcome_training_month(changed, "2018-04-01")
        assert_frame_equal(before["train"], after["train"])
        self.assertEqual(report_before["partitions"]["train"], report_after["partitions"]["train"])
        self.assertEqual(report_before["partitions"]["scoring"]["order_id_fingerprint"], report_after["partitions"]["scoring"]["order_id_fingerprint"])


if __name__ == "__main__":
    unittest.main()
