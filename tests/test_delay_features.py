"""Correctness checks for approval-time delay prediction using tiny Olist fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.delay_features import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    add_delay_target,
    build_delay_dataset,
    build_order_features,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_NAMES = {
    name: f"olist_{name}_dataset.csv"
    for name in (
        "orders", "customers", "order_items", "order_payments", "products", "sellers"
    )
}


def sample_orders():
    """One delivery late in the promised day, and one on the following day."""
    return pd.DataFrame(
        [
            {
                "order_id": order_id,
                "customer_id": f"customer_{order_id}",
                "order_status": "delivered",
                "order_purchase_timestamp": "2018-01-01 10:00:00",
                "order_approved_at": "2018-01-01 11:00:00",
                "order_delivered_carrier_date": "2018-01-02 12:00:00",
                "order_delivered_customer_date": delivered_at,
                "order_estimated_delivery_date": "2018-01-10 00:00:00",
            }
            for order_id, delivered_at in (
                ("same_day", "2018-01-10 23:59:59"),
                ("multiple", "2018-01-11 00:00:00"),
            )
        ]
    )


def sample_tables(orders=None):
    orders = sample_orders() if orders is None else orders.copy(deep=True)
    customers = pd.DataFrame(
        [
            {
                "customer_id": row.customer_id,
                "customer_unique_id": f"unique_{row.customer_id}",
                "customer_zip_code_prefix": "01000",
                "customer_city": "sao paulo",
                "customer_state": "SP",
            }
            for row in orders.itertuples()
        ]
    )
    items = []
    payments = []
    for order_id in orders["order_id"]:
        for sequence, price, freight, product_id, seller_id in (
            [(1, 100.0, 10.0, "product_a", "seller_a"),
             (2, 50.0, 5.0, "product_b", "seller_b")]
            if order_id == "multiple"
            else [(1, 20.0, 2.0, "product_a", "seller_a")]
        ):
            items.append(
                {
                    "order_id": order_id,
                    "order_item_id": sequence,
                    "product_id": product_id,
                    "seller_id": seller_id,
                    "shipping_limit_date": "2018-01-04 11:00:00",
                    "price": price,
                    "freight_value": freight,
                }
            )
        for sequence, amount, payment_type in (
            [(1, 80.0, "voucher"), (2, 85.0, "credit_card")]
            if order_id == "multiple"
            else [(1, 22.0, "credit_card")]
        ):
            payments.append(
                {
                    "order_id": order_id,
                    "payment_sequential": sequence,
                    "payment_type": payment_type,
                    "payment_installments": 2,
                    "payment_value": amount,
                }
            )
    products = pd.DataFrame(
        [
            {
                "product_id": product_id,
                "product_category_name": category,
                "product_name_lenght": 20,
                "product_description_lenght": 100,
                "product_photos_qty": 1,
                "product_weight_g": weight,
                "product_length_cm": 10,
                "product_height_cm": 5,
                "product_width_cm": 4,
            }
            for product_id, category, weight in (
                ("product_a", "housewares", 1000),
                ("product_b", "books", 2000),
            )
        ]
    )
    sellers = pd.DataFrame(
        [
            {
                "seller_id": seller_id,
                "seller_zip_code_prefix": "02000",
                "seller_city": "sample city",
                "seller_state": state,
            }
            for seller_id, state in (("seller_a", "SP"), ("seller_b", "RJ"))
        ]
    )
    return {
        "orders": orders,
        "customers": customers,
        "order_items": pd.DataFrame(items),
        "order_payments": pd.DataFrame(payments),
        "products": products,
        "sellers": sellers,
    }


class DelayFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tables = sample_tables()

    def dataset(self, tables=None):
        tables = self.tables if tables is None else tables
        return add_delay_target(build_order_features(tables), tables["orders"])

    def test_multiple_items_and_payments_do_not_duplicate_order_totals(self):
        """Two items x two payments must retain their independent totals."""
        dataset = self.dataset()
        self.assertEqual(len(dataset), 2)
        self.assertTrue(dataset["order_id"].is_unique)
        row = dataset.set_index("order_id").loc["multiple"]
        self.assertEqual(row["item_count"], 2)
        self.assertEqual(row["product_count"], 2)
        self.assertEqual(row["seller_count"], 2)
        self.assertEqual(row["payment_count"], 2)
        self.assertAlmostEqual(row["total_price"], 150.0)
        self.assertAlmostEqual(row["total_freight_value"], 15.0)
        self.assertAlmostEqual(row["payment_total"], 165.0)

    def test_delay_label_uses_calendar_dates(self):
        dataset = self.dataset().set_index("order_id")
        self.assertEqual(dataset.loc["same_day", "delayed"], 0)
        self.assertEqual(dataset.loc["multiple", "delayed"], 1)
        self.assertEqual(
            pd.Timestamp(dataset.loc["same_day", "prediction_time"]),
            pd.Timestamp("2018-01-01 11:00:00"),
        )
        self.assertEqual(
            pd.Timestamp(dataset.loc["multiple", "label_available_time"]),
            pd.Timestamp("2018-01-11 00:00:00"),
        )

    def test_actual_delivery_changes_label_but_never_features(self):
        before = self.dataset().set_index("order_id").sort_index()
        self.tables["orders"].loc[
            self.tables["orders"]["order_id"] == "same_day",
            "order_delivered_customer_date",
        ] = "2018-01-12 08:00:00"
        after = self.dataset().set_index("order_id").sort_index()
        feature_columns = list(NUMERIC_FEATURES) + list(CATEGORICAL_FEATURES)
        assert_frame_equal(before[feature_columns], after[feature_columns])
        self.assertEqual(before.loc["same_day", "delayed"], 0)
        self.assertEqual(after.loc["same_day", "delayed"], 1)
        self.assertNotEqual(
            before.loc["same_day", "label_available_time"],
            after.loc["same_day", "label_available_time"],
        )

    def test_inference_features_do_not_need_delivery_or_reviews(self):
        before = build_order_features(self.tables).sort_values("order_id").reset_index(drop=True)
        self.tables["orders"]["order_delivered_customer_date"] = None
        self.tables["orders"]["order_delivered_carrier_date"] = None
        self.tables["orders"]["order_status"] = "approved"
        self.tables["order_reviews"] = pd.DataFrame(
            [{"order_id": "same_day", "review_score": 1,
              "review_creation_date": "2018-01-15 00:00:00"}]
        )
        after = build_order_features(self.tables).sort_values("order_id").reset_index(drop=True)
        assert_frame_equal(before, after)
        allowed = set(NUMERIC_FEATURES) | set(CATEGORICAL_FEATURES)
        self.assertTrue(allowed)
        self.assertTrue(allowed.issubset(after.columns))
        forbidden = {
            "order_id", "customer_id", "customer_unique_id", "order_status",
            "order_delivered_customer_date", "order_delivered_carrier_date",
            "review_score", "review_creation_date", "review_answer_timestamp",
            "delayed", "label_available_time",
        }
        self.assertFalse(allowed & forbidden)

    def test_incomplete_or_impossible_label_timestamps_are_excluded(self):
        template = sample_orders().iloc[0].to_dict()
        invalid = {
            "missing_purchase": {"order_purchase_timestamp": None},
            "missing_approval": {"order_approved_at": None},
            "missing_actual": {"order_delivered_customer_date": None},
            "missing_estimate": {"order_estimated_delivery_date": None},
            "approval_before_purchase": {"order_approved_at": "2017-12-31 11:00:00"},
            "delivery_before_approval": {"order_delivered_customer_date": "2018-01-01 10:59:59"},
            "estimate_before_approval": {"order_estimated_delivery_date": "2017-12-31 00:00:00"},
            "unparseable_actual": {"order_delivered_customer_date": "not-a-timestamp"},
            "not_delivered": {"order_status": "canceled"},
        }
        rows = [template]
        for order_id, updates in invalid.items():
            rows.append(
                {**template, "order_id": order_id,
                 "customer_id": f"customer_{order_id}", **updates}
            )
        dataset = self.dataset(sample_tables(pd.DataFrame(rows)))
        self.assertEqual(dataset["order_id"].tolist(), ["same_day"])

    def test_six_csv_inputs_build_the_same_dataset_without_database(self):
        temp_root = PROJECT_ROOT / ".runtime" / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="delay_features_", dir=temp_root) as directory:
            raw_dir = Path(directory)
            for name, table in self.tables.items():
                table.to_csv(raw_dir / CSV_NAMES[name], index=False)
            actual = build_delay_dataset(raw_dir).sort_values("order_id").reset_index(drop=True)
        expected = self.dataset().sort_values("order_id").reset_index(drop=True)
        assert_frame_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
