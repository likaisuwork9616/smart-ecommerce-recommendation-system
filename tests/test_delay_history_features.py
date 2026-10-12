"""Point-in-time and integration checks for recently completed delivery history."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_index_equal

from scripts.delay_features import CSV_FILES, FEATURES as BASE_FEATURES, add_delay_target, build_order_features
from scripts.delay_history_features import (
    FEATURES,
    HISTORY_NUMERIC_FEATURES,
    add_delivery_history,
    build_history_delay_dataset,
    build_history_order_features,
    build_primary_sellers,
)


def query_rows(rows):
    return pd.DataFrame([
        {"order_id": order_id, "prediction_time": pd.Timestamp(approval),
         "estimated_delivery_days": promise, "customer_state": customer,
         "primary_seller_state": seller}
        for order_id, approval, promise, customer, seller in rows
    ])


def event_rows(rows):
    columns = ["order_id", "prediction_time", "label_available_time", "delayed",
               "customer_state", "primary_seller_state"]
    return pd.DataFrame([
        {"order_id": order_id, "prediction_time": pd.Timestamp(approval),
         "label_available_time": pd.Timestamp(delivery), "delayed": delayed,
         "customer_state": customer, "primary_seller_state": seller}
        for order_id, approval, delivery, delayed, customer, seller in rows
    ], columns=columns)


def seller_lookup(features, events, overrides=None):
    assignments = {order_id: "seller_a" for order_id in list(features["order_id"]) + list(events["order_id"])}
    assignments.update(overrides or {})
    return pd.DataFrame(assignments.items(), columns=["order_id", "primary_seller_id"])


def tiny_tables():
    specifications = [
        ("history", "2018-01-01 11:00", "2018-01-10 23:00", "2018-01-09", "delivered"),
        ("current", "2018-01-12 11:00", "2018-01-20 12:00", "2018-01-25", "delivered"),
        ("cancelled", "2018-01-02 11:00", "2018-01-08 12:00", "2018-01-09", "canceled"),
    ]
    orders = pd.DataFrame([
        {"order_id": order_id, "customer_id": f"customer_{order_id}",
         "order_purchase_timestamp": pd.Timestamp(approval) - pd.Timedelta(hours=1),
         "order_approved_at": approval, "order_delivered_customer_date": delivery,
         "order_estimated_delivery_date": promise, "order_status": status}
        for order_id, approval, delivery, promise, status in specifications
    ])
    customers = pd.DataFrame([
        {"customer_id": row.customer_id, "customer_state": "SP"}
        for row in orders.itertuples()
    ])
    items = pd.DataFrame([
        {"order_id": "history", "order_item_id": 2, "price": 100.0, "freight_value": 10.0,
         "seller_id": "seller_b", "product_id": "product"},
        {"order_id": "history", "order_item_id": 1, "price": 100.0, "freight_value": 10.0,
         "seller_id": "seller_a", "product_id": "product"},
        *[{"order_id": order_id, "order_item_id": 1, "price": 20.0, "freight_value": 2.0,
           "seller_id": "seller_a", "product_id": "product"} for order_id in ("current", "cancelled")],
    ])
    payments = pd.DataFrame([
        {"order_id": order_id, "payment_sequential": 1, "payment_value": 22.0,
         "payment_type": "credit_card", "payment_installments": 1}
        for order_id in orders["order_id"]
    ])
    products = pd.DataFrame([{
        "product_id": "product", "product_category_name": "housewares", "product_weight_g": 1000,
        "product_length_cm": 10, "product_height_cm": 5, "product_width_cm": 4,
    }])
    sellers = pd.DataFrame([
        {"seller_id": "seller_a", "seller_state": "RJ"},
        {"seller_id": "seller_b", "seller_state": "MG"},
    ])
    return {"orders": orders, "customers": customers, "order_items": items,
            "order_payments": payments, "products": products, "sellers": sellers}


class DeliveryHistoryTests(unittest.TestCase):
    def test_strict_delivery_timestamp_and_inclusive_90_day_boundary(self):
        query_time = pd.Timestamp("2020-04-01 12:00")
        features = query_rows([("current", query_time, 15, "SP", "RJ")])
        deliveries = [
            query_time - pd.Timedelta(days=90) - pd.Timedelta(nanoseconds=1),
            query_time - pd.Timedelta(days=90),
            query_time - pd.Timedelta(nanoseconds=1),
            query_time,
            query_time + pd.Timedelta(days=1),
        ]
        events = event_rows([
            (f"event_{i}", delivery - pd.Timedelta(days=10), delivery, delayed, "SP", "RJ")
            for i, (delivery, delayed) in enumerate(zip(deliveries, [1, 0, 1, 1, 1]))
        ])
        actual = add_delivery_history(features, events, seller_lookup(features, events)).iloc[0]
        self.assertEqual(actual["global_completed_90d"], 2)
        self.assertEqual(actual["seller_completed_90d"], 2)
        self.assertEqual(actual["route_completed_90d"], 2)
        global_rate = (1 + 20 * 0.05) / (2 + 20)
        self.assertAlmostEqual(actual["global_delay_rate_90d"], global_rate)
        self.assertAlmostEqual(actual["seller_delay_rate_90d"], (1 + 20 * global_rate) / 22)
        self.assertAlmostEqual(actual["global_delivery_days_90d"], 10)
        self.assertAlmostEqual(actual["route_promise_margin_days"], 5)

    def test_no_events_use_fixed_prior_and_missing_duration(self):
        features = query_rows([("new", "2020-01-01", 10, "SP", "RJ")])
        events = event_rows([])
        actual = add_delivery_history(features, events, seller_lookup(features, events)).iloc[0]
        for prefix in ("global", "seller", "route"):
            self.assertEqual(actual[f"{prefix}_completed_90d"], 0)
            self.assertAlmostEqual(actual[f"{prefix}_delay_rate_90d"], 0.05)
            self.assertTrue(pd.isna(actual[f"{prefix}_delivery_days_90d"]))
        self.assertTrue(pd.isna(actual["route_promise_margin_days"]))

    def test_unknown_sellers_and_routes_do_not_share_an_unknown_group(self):
        features = query_rows([
            ("missing", "2020-02-01", 12, "SP", np.nan),
            ("unseen", "2020-02-01", 12, "SP", np.nan),
        ])
        events = event_rows([("past", "2020-01-01", "2020-01-09", 1, "SP", np.nan)])
        sellers = seller_lookup(features, events, {"missing": None, "unseen": "never_seen", "past": None})
        actual = add_delivery_history(features, events, sellers)
        for row in actual.itertuples():
            self.assertEqual(row.global_completed_90d, 1)
            self.assertEqual(row.seller_completed_90d, 0)
            self.assertEqual(row.route_completed_90d, 0)
            self.assertAlmostEqual(row.global_delay_rate_90d, 2 / 21)
            self.assertAlmostEqual(row.seller_delay_rate_90d, row.global_delay_rate_90d)
            self.assertAlmostEqual(row.route_delay_rate_90d, row.global_delay_rate_90d)
            self.assertAlmostEqual(row.seller_delivery_days_90d, 8)
            self.assertAlmostEqual(row.route_delivery_days_90d, 8)

    def test_seller_isolation_and_fractional_duration_since_approval(self):
        features = query_rows([("query", "2020-02-01", 10, "SP", "RJ")])
        events = event_rows([
            ("a", "2020-01-01 12:00", "2020-01-04", 1, "SP", "RJ"),
            ("b", "2020-01-01", "2020-01-09", 0, "SP", "RJ"),
        ])
        sellers = seller_lookup(features, events, {"b": "seller_b"})
        actual = add_delivery_history(features, events, sellers).iloc[0]
        self.assertEqual(actual["global_completed_90d"], 2)
        self.assertEqual(actual["seller_completed_90d"], 1)
        self.assertEqual(actual["route_completed_90d"], 2)
        self.assertAlmostEqual(actual["seller_delivery_days_90d"], 2.5)
        self.assertAlmostEqual(actual["global_delivery_days_90d"], 5.25)
        global_rate = (1 + 1) / 22
        self.assertAlmostEqual(actual["seller_delay_rate_90d"], (1 + 20 * global_rate) / 21)

    def test_current_order_and_same_time_deliveries_cannot_label_themselves(self):
        features = query_rows([("current", "2020-02-01", 10, "SP", "RJ")])
        events = event_rows([
            ("current", "2020-02-01", "2020-02-01", 1, "SP", "RJ"),
            ("also_now", "2020-01-01", "2020-02-01", 0, "SP", "RJ"),
        ])
        actual = add_delivery_history(features, events, seller_lookup(features, events)).iloc[0]
        self.assertEqual(actual["global_completed_90d"], 0)
        self.assertAlmostEqual(actual["global_delay_rate_90d"], 0.05)

    def test_future_label_and_delivery_mutation_cannot_change_earlier_features(self):
        features = query_rows([
            ("early", "2020-03-01", 15, "SP", "RJ"),
            ("later", "2020-03-03", 15, "SP", "RJ"),
        ])
        events = event_rows([
            ("known", "2020-02-18", "2020-02-28", 0, "SP", "RJ"),
            ("future", "2020-02-20", "2020-03-02 08:00", 1, "SP", "RJ"),
        ])
        sellers = seller_lookup(features, events)
        before = add_delivery_history(features, events, sellers)
        changed = events.copy(deep=True)
        changed.loc[changed.order_id == "future", "delayed"] = 0
        changed.loc[changed.order_id == "future", "label_available_time"] = pd.Timestamp("2020-03-02 12:00")
        after = add_delivery_history(features, changed, sellers)
        assert_frame_equal(before.iloc[[0]][HISTORY_NUMERIC_FEATURES], after.iloc[[0]][HISTORY_NUMERIC_FEATURES])
        self.assertNotEqual(before.iloc[1].global_delay_rate_90d, after.iloc[1].global_delay_rate_90d)
        self.assertNotEqual(before.iloc[1].global_delivery_days_90d, after.iloc[1].global_delivery_days_90d)

    def test_shuffling_prediction_and_event_rows_preserves_per_order_values(self):
        features = query_rows([
            ("q1", "2020-03-01", 15, "SP", "RJ"),
            ("q2", "2020-03-10", 12, "SP", "RJ"),
            ("q3", "2020-02-01", 10, "SP", "RJ"),
        ])
        features.index = [7, 7, 2]
        events = event_rows([
            ("b", "2020-02-01", "2020-02-20", 1, "SP", "RJ"),
            ("a", "2020-02-10", "2020-02-20", 0, "SP", "RJ"),
        ])
        sellers = seller_lookup(features, events)
        expected = add_delivery_history(features, events, sellers)
        shuffled = features.iloc[[2, 0, 1]]
        actual = add_delivery_history(shuffled, events.iloc[::-1], sellers)
        assert_index_equal(actual.index, shuffled.index)
        self.assertEqual(actual.order_id.tolist(), shuffled.order_id.tolist())
        assert_frame_equal(
            expected.set_index("order_id").sort_index()[HISTORY_NUMERIC_FEATURES],
            actual.set_index("order_id").sort_index()[HISTORY_NUMERIC_FEATURES],
        )

    def test_snapshot_updates_only_apply_after_outcome_becomes_known(self):
        features = query_rows([
            ("before", "2020-03-01 12:00", 15, "SP", "RJ"),
            ("after", "2020-03-02 12:00", 15, "SP", "RJ"),
        ])
        known = event_rows([("old", "2020-02-18", "2020-02-28", 0, "SP", "RJ")])
        updated = pd.concat([
            known,
            event_rows([("newly_completed", "2020-02-20", "2020-03-01 18:00", 1, "SP", "RJ")]),
        ], ignore_index=True)
        sellers = seller_lookup(features, updated)
        before = add_delivery_history(features, known, sellers)
        after = add_delivery_history(features, updated, sellers)
        assert_frame_equal(before.iloc[[0]][HISTORY_NUMERIC_FEATURES], after.iloc[[0]][HISTORY_NUMERIC_FEATURES])
        self.assertEqual(before.iloc[1].global_completed_90d, 1)
        self.assertEqual(after.iloc[1].global_completed_90d, 2)
        self.assertEqual(after.iloc[1].seller_completed_90d, 2)

    def test_missing_approval_has_no_fabricated_history(self):
        features = query_rows([("missing", pd.NaT, 10, "SP", "RJ")])
        events = event_rows([("past", "2020-01-01", "2020-01-09", 1, "SP", "RJ")])
        actual = add_delivery_history(features, events, seller_lookup(features, events))
        self.assertTrue(actual[HISTORY_NUMERIC_FEATURES].isna().all(axis=None))

    def test_duplicate_events_and_impossible_event_timeline_are_rejected(self):
        features = query_rows([("q", "2020-02-01", 10, "SP", "RJ")])
        events = event_rows([("past", "2020-01-01", "2020-01-09", 1, "SP", "RJ")])
        sellers = seller_lookup(features, events)
        with self.assertRaises(ValueError):
            add_delivery_history(features, pd.concat([events, events], ignore_index=True), sellers)
        events.loc[0, "label_available_time"] = pd.Timestamp("2019-12-31")
        with self.assertRaises(ValueError):
            add_delivery_history(features, events, sellers)


class HistoryBuilderIntegrationTests(unittest.TestCase):
    def test_primary_seller_ties_match_v1_and_one_order_counts_once(self):
        tables = tiny_tables()
        sellers = build_primary_sellers(tables["order_items"]).set_index("order_id")
        self.assertEqual(sellers.loc["history", "primary_seller_id"], "seller_a")
        enriched = build_history_order_features(tables)
        base = build_order_features(tables)
        assert_frame_equal(enriched[base.columns], base)
        current = enriched.set_index("order_id").loc["current"]
        self.assertEqual(current["global_completed_90d"], 1)
        self.assertEqual(current["seller_completed_90d"], 1)
        self.assertEqual(current["route_completed_90d"], 1)
        self.assertAlmostEqual(current["global_delivery_days_90d"], 9.5)
        self.assertAlmostEqual(current["route_promise_margin_days"], 3.5)
        self.assertEqual(len(HISTORY_NUMERIC_FEATURES), 10)
        self.assertEqual(len(FEATURES), 31)
        self.assertFalse({"primary_seller_id", "route_key", "delayed", "label_available_time"} & set(enriched.columns))

    def test_raw_csv_builder_preserves_exact_v1_labeled_cohort_and_features(self):
        tables = tiny_tables()
        expected = add_delay_target(build_order_features(tables), tables["orders"])
        temp_root = Path(__file__).resolve().parents[1] / ".runtime" / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="delay_history_", dir=temp_root) as directory:
            raw_dir = Path(directory)
            for name, filename in CSV_FILES.items():
                tables[name].to_csv(raw_dir / filename, index=False)
            actual = build_history_delay_dataset(raw_dir)
        self.assertEqual(actual.order_id.tolist(), expected.order_id.tolist())
        assert_frame_equal(actual[expected.columns], expected)
        self.assertEqual(set(actual.columns), set(expected.columns) | set(HISTORY_NUMERIC_FEATURES))
        self.assertTrue(set(BASE_FEATURES).issubset(actual.columns))
        self.assertEqual(actual.set_index("order_id").loc["current", "global_completed_90d"], 1)


if __name__ == "__main__":
    unittest.main()
