"""Pending workload must depend only on earlier approvals and known deliveries."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_index_equal

from scripts.delay_budget_features import FEATURES as BUDGET_FEATURES, build_budget_order_features
from scripts.delay_features import CSV_FILES, add_delay_target, build_order_features
from scripts.delay_pending_features import (
    CATEGORICAL_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    PENDING_NUMERIC_FEATURES,
    add_pending_features,
    build_pending_delay_dataset,
    build_pending_order_features,
    prepare_pending_input,
)
from tests.test_delay_budget_features import tiny_tables


def pending_tables(specifications):
    """order ID, approval, delivery, promise, final status, seller, customer state."""
    rows = []
    for order_id, approval, delivery, promise, status, seller, customer_state in specifications:
        rows.append({
            "order_id": order_id, "customer_id": f"customer_{order_id}",
            "order_purchase_timestamp": pd.Timestamp(approval) - pd.Timedelta(hours=1),
            "order_approved_at": approval, "order_delivered_customer_date": delivery,
            "order_estimated_delivery_date": promise, "order_status": status,
        })
    orders = pd.DataFrame(rows)
    return {
        "orders": orders,
        "customers": pd.DataFrame([{"customer_id": f"customer_{spec[0]}", "customer_state": spec[6]}
            for spec in specifications]),
        "sellers": pd.DataFrame([{"seller_id": seller, "seller_state": "RJ"}
            for seller in sorted({spec[5] for spec in specifications if spec[5] is not None})]),
        "order_items": pd.DataFrame([{"order_id": spec[0], "order_item_id": 1,
            "price": 10., "seller_id": spec[5]} for spec in specifications]),
    }


def queries(times, *, seller="seller_a", customer="SP", seller_state="RJ"):
    return pd.DataFrame([{
        "order_id": f"query-{position}", "prediction_time": pd.Timestamp(stamp),
        "primary_seller_id": seller, "customer_state": customer, "primary_seller_state": seller_state,
    } for position, stamp in enumerate(times)])


class PendingFeaturesTests(unittest.TestCase):
    def test_strict_approval_and_inclusive_window_boundaries(self):
        now = pd.Timestamp("2020-04-01 12:00")
        stamps = [now-pd.Timedelta(days=90)-pd.Timedelta(nanoseconds=1), now-pd.Timedelta(days=90),
                  now-pd.Timedelta(days=30)-pd.Timedelta(nanoseconds=1), now-pd.Timedelta(days=30),
                  now-pd.Timedelta(nanoseconds=1), now, now+pd.Timedelta(nanoseconds=1)]
        tables = pending_tables([(f"order-{i}", stamp, None, now, "shipped", "seller_a", "SP")
            for i, stamp in enumerate(stamps)])
        result = add_pending_features(queries([now]), tables).iloc[0]
        for prefix in ("global", "seller", "route"):
            self.assertEqual(result[f"{prefix}_pending_30d"], 2)
            self.assertEqual(result[f"{prefix}_pending_90d"], 4)
            self.assertAlmostEqual(result[f"{prefix}_pending_mean_age_30d"], 15, places=10)
            self.assertEqual(result[f"{prefix}_pending_overdue_30d"], 0)

    def test_delivery_exact_query_is_pending_but_one_nanosecond_earlier_is_known(self):
        now = pd.Timestamp("2020-02-01 12:00")
        deliveries = [now-pd.Timedelta(nanoseconds=1), now, now+pd.Timedelta(nanoseconds=1), None]
        tables = pending_tables([(f"order-{i}", now-pd.Timedelta(days=5), delivered, now,
            "delivered", "seller_a", "SP") for i, delivered in enumerate(deliveries)])
        actual = add_pending_features(queries([now, now+pd.Timedelta(nanoseconds=2)]), tables)
        self.assertEqual(actual.iloc[0].global_pending_30d, 3)
        self.assertEqual(actual.iloc[1].global_pending_30d, 1)
        self.assertAlmostEqual(actual.iloc[0].global_pending_mean_age_30d, 5)

    def test_overdue_starts_next_calendar_midnight_and_missing_promise_is_unknown(self):
        specifications = [
            ("old", "2020-02-01", None, "2020-02-09 23:00", "shipped", "seller_a", "SP"),
            ("today", "2020-02-01", None, "2020-02-10", "shipped", "seller_a", "SP"),
            ("missing", "2020-02-01", None, None, "shipped", "seller_a", "SP"),
        ]
        actual = add_pending_features(queries(["2020-02-09 23:59:59", "2020-02-10 00:00", "2020-02-11 00:00"]), pending_tables(specifications))
        self.assertEqual(actual.global_pending_30d.tolist(), [3., 3., 3.])
        self.assertEqual(actual.global_pending_overdue_30d.tolist(), [0., 1., 2.])
        self.assertEqual(actual.seller_pending_overdue_90d.tolist(), [0., 1., 2.])

    def test_final_status_and_future_delivery_mutations_cannot_change_past_workload(self):
        tables = pending_tables([
            ("cancelled", "2020-01-01", None, "2020-01-10", "canceled", "seller_a", "SP"),
            ("future_delivery", "2020-01-01", "2020-02-20", "2020-01-20", "delivered", "seller_a", "SP"),
            ("future_approval", "2020-02-10", None, "2020-02-15", "approved", "seller_a", "SP"),
        ])
        current = queries(["2020-02-01"])
        expected = add_pending_features(current, tables)
        self.assertEqual(expected.iloc[0].global_pending_90d, 2)
        tables["orders"]["order_status"] = "anything"
        tables["orders"].loc[tables["orders"].order_id == "future_delivery", "order_delivered_customer_date"] = "2020-03-01"
        tables["orders"].loc[tables["orders"].order_id == "future_approval", "order_estimated_delivery_date"] = "2019-01-01"
        assert_frame_equal(add_pending_features(current, tables), expected)
        # The workload builder does not even require a final-status column.
        del tables["orders"]["order_status"]
        assert_frame_equal(add_pending_features(current, tables), expected)

    def test_unknown_keys_are_not_pooled_and_unseen_seller_has_missing_mean(self):
        tables = pending_tables([
            ("known", "2020-01-01", None, "2020-01-15", "shipped", "seller_a", "SP"),
            ("unknown", "2020-01-01", None, "2020-01-15", "shipped", None, None),
        ])
        missing = queries(["2020-01-20"], seller=None, customer=None, seller_state=None)
        actual = add_pending_features(missing, tables).iloc[0]
        self.assertEqual(actual.global_pending_30d, 2)
        for prefix in ("seller", "route"):
            self.assertEqual(actual[f"{prefix}_pending_90d"], 0)
            self.assertTrue(pd.isna(actual[f"{prefix}_pending_mean_age_30d"]))
        unseen = add_pending_features(queries(["2020-01-20"], seller="unseen"), tables).iloc[0]
        self.assertEqual(unseen.seller_pending_30d, 0)
        self.assertEqual(unseen.route_pending_30d, 1)

    def test_missing_approval_and_empty_valid_raw_population(self):
        tables = pending_tables([("order", "2020-01-01", None, "2020-01-15", "shipped", "seller_a", "SP")])
        current = queries([pd.NaT, "2020-01-20"])
        tables["orders"]["order_approved_at"] = None
        actual = add_pending_features(current, tables)
        self.assertTrue(actual.loc[0, PENDING_NUMERIC_FEATURES].isna().all())
        self.assertEqual(actual.loc[1, "global_pending_90d"], 0)
        self.assertTrue(pd.isna(actual.loc[1, "global_pending_mean_age_30d"]))

    def test_ledger_matches_brute_force_pending_oracle_with_shuffle_and_repeated_index(self):
        rng = np.random.default_rng(69)
        specifications = []
        for i in range(75):
            approval = pd.Timestamp("2020-01-01") + pd.Timedelta(hours=int(rng.integers(0, 24*140)))
            delivery = None if i % 5 == 0 else approval + pd.Timedelta(hours=int(rng.integers(0, 24*120)))
            promise = None if i % 7 == 0 else approval + pd.Timedelta(days=int(rng.integers(0, 80)))
            specifications.append((f"raw-{i}", approval, delivery, promise, "canceled" if i % 3 == 0 else "delivered",
                                   "seller_a" if i % 2 else "seller_b", "SP" if i % 4 else "MG"))
        tables = pending_tables(specifications)
        query = queries(pd.date_range("2020-01-01", periods=75, freq="3D"))
        query.index = np.arange(len(query)) % 4
        actual = add_pending_features(query, tables)
        raw = tables["orders"].copy()
        for name in ("order_approved_at", "order_delivered_customer_date", "order_estimated_delivery_date"):
            raw[name] = pd.to_datetime(raw[name])
        seller_by_id = {row[0]: row[5] for row in specifications}
        state_by_id = {row[0]: row[6] for row in specifications}
        for position, stamp in enumerate(query.prediction_time):
            pending = raw.loc[(raw.order_approved_at < stamp) & (raw.order_delivered_customer_date.isna() | (raw.order_delivered_customer_date >= stamp))]
            for prefix in ("global", "seller", "route"):
                subset = pending
                if prefix == "seller":
                    subset = pending.loc[pending.order_id.map(seller_by_id).eq("seller_a")]
                elif prefix == "route":
                    subset = pending.loc[pending.order_id.map(state_by_id).eq("SP")]
                for window in (30, 90):
                    recent = subset.loc[subset.order_approved_at >= stamp-pd.Timedelta(days=window)]
                    self.assertEqual(actual.iloc[position][f"{prefix}_pending_{window}d"], len(recent))
                    expected_overdue = int(recent.order_estimated_delivery_date.dt.normalize().lt(stamp.normalize()).sum())
                    self.assertEqual(actual.iloc[position][f"{prefix}_pending_overdue_{window}d"], expected_overdue)
                    if window == 30:
                        expected_age = ((stamp-recent.order_approved_at).dt.total_seconds()/86400).mean()
                        observed_age = actual.iloc[position][f"{prefix}_pending_mean_age_30d"]
                        if pd.isna(expected_age):
                            self.assertTrue(pd.isna(observed_age))
                        else:
                            self.assertAlmostEqual(observed_age, expected_age, places=9)
        permutation = rng.permutation(len(query))
        tables["orders"] = tables["orders"].sample(frac=1, random_state=42)
        shuffled = add_pending_features(query.iloc[permutation], tables)
        assert_index_equal(shuffled.index, query.iloc[permutation].index)
        assert_frame_equal(actual.set_index("order_id").sort_index(), shuffled.set_index("order_id").sort_index())

    def test_budget_contract_and_eligible_labeled_cohort_are_unchanged(self):
        tables = tiny_tables()
        budget = build_budget_order_features(tables)
        pending = build_pending_order_features(tables)
        assert_frame_equal(pending[["order_id"] + BUDGET_FEATURES], budget[["order_id"] + BUDGET_FEATURES])
        self.assertEqual(len(NUMERIC_FEATURES), 52)
        self.assertEqual(len(CATEGORICAL_FEATURES), 8)
        self.assertEqual(len(FEATURES), 60)
        self.assertEqual(len(set(FEATURES)), 60)
        baseline = add_delay_target(build_order_features(tables), tables["orders"])
        with TemporaryDirectory() as temporary:
            raw_dir = Path(temporary)
            for name, filename in CSV_FILES.items():
                tables[name].to_csv(raw_dir/filename, index=False)
            labeled = build_pending_delay_dataset(raw_dir)
        assert_frame_equal(labeled[baseline.columns], baseline)

    def test_pending_input_whitelist_normalizes_missing_and_nonfinite_values(self):
        frame = build_pending_order_features(tiny_tables())
        frame["delayed"] = 1
        frame["label_available_time"] = pd.Timestamp("2099-01-01")
        frame.loc[0, "global_pending_mean_age_30d"] = np.inf
        frame.loc[0, "primary_seller_id"] = pd.NA
        actual = prepare_pending_input(frame)
        self.assertEqual(actual.columns.tolist(), FEATURES)
        self.assertEqual(len(actual.columns), 60)
        self.assertFalse({"delayed", "order_id", "prediction_time", "label_available_time"}.intersection(actual.columns))
        self.assertTrue(pd.isna(actual.loc[0, "global_pending_mean_age_30d"]))
        self.assertTrue(pd.isna(actual.loc[0, "primary_seller_id"]))
        self.assertIsInstance(actual.loc[0, "primary_seller_id"], float)
        with self.assertRaisesRegex(ValueError, "Missing pending feature"):
            prepare_pending_input(frame.drop(columns="seller_pending_90d"))


if __name__ == "__main__":
    unittest.main()
