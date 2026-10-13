"""Cohort and point-in-time checks for seller/route alert-budget features."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.delay_budget_features import (
    CATEGORICAL_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    build_budget_delay_dataset,
    build_budget_order_features,
    prepare_budget_input,
)
from scripts.delay_features import CSV_FILES, add_delay_target, build_order_features
from scripts.delay_route_features import FEATURES as ROUTE_FEATURES, build_route_order_features


def tiny_tables():
    specifications = [
        ("history", "2018-01-01 11:00", "2018-01-10 23:00", "2018-01-09", "delivered"),
        ("same", "2018-01-02 11:00", "2018-01-12 11:00", "2018-01-11", "delivered"),
        ("current", "2018-01-12 11:00", "2018-01-20 12:00", "2018-01-25", "delivered"),
        ("future", "2018-01-08 11:00", "2018-01-15 12:00", "2018-01-14", "delivered"),
        ("cancelled", "2018-01-02 11:00", "2018-01-08 12:00", "2018-01-09", "canceled"),
    ]
    orders = pd.DataFrame([
        {"order_id": order_id, "customer_id": f"customer_{order_id}",
         "order_purchase_timestamp": pd.Timestamp(approval) - pd.Timedelta(hours=1),
         "order_approved_at": approval, "order_delivered_customer_date": delivery,
         "order_estimated_delivery_date": promise, "order_status": status}
        for order_id, approval, delivery, promise, status in specifications
    ])
    return {
        "orders": orders,
        "customers": pd.DataFrame([
            {"customer_id": row.customer_id, "customer_state": "SP", "customer_zip_code_prefix": 1040}
            for row in orders.itertuples()
        ]),
        "order_items": pd.DataFrame([
            {"order_id": order_id, "order_item_id": 1, "price": 20.0, "freight_value": 2.0,
             "seller_id": "seller_a", "product_id": "product"}
            for order_id in orders["order_id"]
        ]),
        "order_payments": pd.DataFrame([
            {"order_id": order_id, "payment_sequential": 1, "payment_value": 22.0,
             "payment_type": "credit_card", "payment_installments": 1}
            for order_id in orders["order_id"]
        ]),
        "products": pd.DataFrame([{
            "product_id": "product", "product_category_name": "housewares", "product_weight_g": 1000,
            "product_length_cm": 10, "product_height_cm": 5, "product_width_cm": 4,
        }]),
        "sellers": pd.DataFrame([{
            "seller_id": "seller_a", "seller_state": "RJ", "seller_zip_code_prefix": 1234,
        }]),
    }


class BudgetFeaturesTests(unittest.TestCase):
    def test_counts_exclude_current_same_time_future_and_cancelled_outcomes(self):
        features = build_budget_order_features(tiny_tables()).set_index("order_id")
        current = features.loc["current"]
        for prefix in ("global", "seller", "route"):
            self.assertEqual(current[f"{prefix}_completed_90d"], 1)
        global_rate = 2 / 21
        seller_rate = (1 + 20 * global_rate) / 21
        self.assertAlmostEqual(current["global_delay_rate_90d"], global_rate)
        self.assertAlmostEqual(current["seller_delay_rate_90d"], seller_rate)
        self.assertAlmostEqual(current["route_delay_rate_90d"], seller_rate)
        self.assertAlmostEqual(current["seller_promise_margin_days"], 13 - 9.5)
        self.assertAlmostEqual(current["seller_promise_ratio"], 13 / 9.5)
        self.assertAlmostEqual(current["seller_delay_rate_excess_global"], seller_rate - global_rate)
        self.assertAlmostEqual(current["route_delay_rate_excess_global"], seller_rate - global_rate)

    def test_future_outcome_mutations_cannot_change_current_features(self):
        tables = tiny_tables()
        expected = build_budget_order_features(tables).set_index("order_id")
        tables["orders"].loc[tables["orders"].order_id == "same", "order_delivered_customer_date"] = "2018-01-12 12:00"
        tables["orders"].loc[tables["orders"].order_id == "future", "order_delivered_customer_date"] = "2018-02-01 12:00"
        tables["orders"].loc[tables["orders"].order_id == "current", "order_delivered_customer_date"] = "2018-01-26 12:00"
        actual = build_budget_order_features(tables).set_index("order_id")
        assert_frame_equal(expected.loc[["current"], FEATURES], actual.loc[["current"], FEATURES])

    def test_unknown_seller_history_falls_back_without_unknown_id_pooling(self):
        tables = tiny_tables()
        tables["order_items"].loc[tables["order_items"].order_id == "current", "seller_id"] = "new_seller"
        tables["sellers"] = pd.concat([
            tables["sellers"], pd.DataFrame([{"seller_id": "new_seller", "seller_state": "RJ"}]),
        ], ignore_index=True)
        current = build_budget_order_features(tables).set_index("order_id").loc["current"]
        self.assertEqual(current["primary_seller_id"], "new_seller")
        self.assertEqual(current["seller_completed_90d"], 0)
        self.assertEqual(current["seller_delay_rate_excess_global"], 0)
        self.assertEqual(current["seller_delivery_days_90d"], current["global_delivery_days_90d"])
        self.assertTrue(pd.isna(current["primary_seller_zip_prefix3"]))

    def test_postal_categories_preserve_leading_zeroes_and_reject_invalid_values(self):
        tables = tiny_tables()
        features = build_budget_order_features(tables).set_index("order_id")
        self.assertEqual(features.loc["current", "customer_zip_prefix3"], "010")
        self.assertEqual(features.loc["current", "primary_seller_zip_prefix3"], "012")
        for invalid in (-1, 100000, 1040.5, np.inf, "unavailable"):
            changed = {name: frame.copy(deep=True) for name, frame in tables.items()}
            changed["customers"]["customer_zip_code_prefix"] = invalid
            changed["sellers"]["seller_zip_code_prefix"] = invalid
            invalid_features = build_budget_order_features(changed)
            self.assertTrue(invalid_features[["customer_zip_prefix3", "primary_seller_zip_prefix3"]].isna().all(axis=None))
        del tables["customers"]["customer_zip_code_prefix"]
        del tables["sellers"]["seller_zip_code_prefix"]
        missing = build_budget_order_features(tables)
        self.assertTrue(missing[["customer_zip_prefix3", "primary_seller_zip_prefix3"]].isna().all(axis=None))

    def test_existing_route_contract_and_exact_labeled_cohort_are_preserved(self):
        tables = tiny_tables()
        budget = build_budget_order_features(tables)
        route = build_route_order_features(tables)
        assert_frame_equal(budget[["order_id"] + ROUTE_FEATURES], route[["order_id"] + ROUTE_FEATURES])
        baseline = add_delay_target(build_order_features(tables), tables["orders"])
        with TemporaryDirectory() as temporary:
            raw_dir = Path(temporary)
            for name, filename in CSV_FILES.items():
                tables[name].to_csv(raw_dir / filename, index=False)
            labeled = build_budget_delay_dataset(raw_dir)
        assert_frame_equal(labeled[baseline.columns], baseline)
        self.assertNotIn("cancelled", labeled["order_id"].tolist())
        self.assertEqual(labeled.order_id.tolist(), ["history", "same", "current", "future"])

    def test_input_contract_normalizes_missing_values_and_excludes_outcomes(self):
        features = build_budget_order_features(tiny_tables())
        features["delayed"] = 1
        features["label_available_time"] = pd.Timestamp("2099-01-01")
        features.loc[0, "seller_promise_ratio"] = np.inf
        features.loc[0, "primary_seller_id"] = pd.NA
        prepared = prepare_budget_input(features)
        self.assertEqual(prepared.columns.tolist(), FEATURES)
        self.assertEqual(len(NUMERIC_FEATURES), 37)
        self.assertEqual(len(CATEGORICAL_FEATURES), 8)
        self.assertEqual(len(FEATURES), len(set(FEATURES)))
        self.assertFalse(set(prepared).intersection({"order_id", "delayed", "prediction_time", "label_available_time"}))
        self.assertTrue(pd.isna(prepared.loc[0, "seller_promise_ratio"]))
        self.assertIsInstance(prepared.loc[0, "primary_seller_id"], float)
        self.assertTrue(pd.isna(prepared.loc[0, "primary_seller_id"]))
        with self.assertRaisesRegex(ValueError, "Missing budget feature"):
            prepare_budget_input(features.drop(columns="seller_delay_rate_90d"))

    def test_missing_approval_has_no_history_but_known_identity_remains_available(self):
        tables = tiny_tables()
        tables["orders"].loc[tables["orders"].order_id == "current", "order_approved_at"] = None
        current = build_budget_order_features(tables).set_index("order_id").loc["current"]
        self.assertTrue(pd.isna(current["seller_completed_90d"]))
        self.assertTrue(pd.isna(current["seller_promise_margin_days"]))
        self.assertTrue(pd.isna(current["seller_delay_rate_excess_global"]))
        self.assertEqual(current["primary_seller_id"], "seller_a")
        self.assertEqual(current["customer_zip_prefix3"], "010")


if __name__ == "__main__":
    unittest.main()
