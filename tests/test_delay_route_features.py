"""Check route/promise features against calendar-day, point-in-time definitions."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_index_equal

from scripts.delay_features import CSV_FILES, add_delay_target, build_order_features
from scripts.delay_route_features import (
    FEATURES,
    ROUTE_CATEGORICAL_FEATURES,
    ROUTE_NUMERIC_FEATURES,
    add_route_promise_features,
    build_route_delay_dataset,
    build_route_order_features,
)


def queries(rows):
    return pd.DataFrame([
        {"order_id": order_id, "prediction_time": pd.Timestamp(approval),
         "estimated_delivery_days": promise, "primary_seller_state": seller,
         "customer_state": customer}
        for order_id, approval, promise, seller, customer in rows
    ])


def events(rows):
    return pd.DataFrame([
        {"order_id": order_id, "prediction_time": pd.Timestamp(approval),
         "label_available_time": pd.Timestamp(delivery), "delayed": delayed,
         "primary_seller_state": seller, "customer_state": customer}
        for order_id, approval, delivery, delayed, seller, customer in rows
    ], columns=["order_id", "prediction_time", "label_available_time", "delayed",
                "primary_seller_state", "customer_state"])


def tiny_tables():
    specifications = [
        ("history", "2018-01-01 23:00", "2018-01-10 01:00", "2018-01-09", "delivered"),
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


class RoutePromiseTests(unittest.TestCase):
    def test_hand_computed_linear_quantiles_cdf_and_calendar_day_scale(self):
        current = queries([("q", "2020-02-01", 3, "SP", "RJ")])
        history = events([
            ("a", "2020-01-10 23:00", "2020-01-10 23:59", 0, "SP", "RJ"),
            ("b", "2020-01-10 23:00", "2020-01-12 01:00", 1, "SP", "RJ"),
            ("c", "2020-01-10 23:00", "2020-01-14 01:00", 0, "SP", "RJ"),
            ("d", "2020-01-10 23:00", "2020-01-16 01:00", 1, "RJ", "SP"),
        ])
        actual = add_route_promise_features(current, history, prior_strength=2).iloc[0]
        self.assertEqual(actual["state_route"], "SP->RJ")
        self.assertEqual(actual["global_completed_90d"], 4)
        self.assertEqual(actual["route_completed_90d"], 3)
        self.assertAlmostEqual(actual["global_delivery_p90_calendar_days_90d"], 5.4)
        self.assertAlmostEqual(actual["route_delivery_p50_calendar_days_90d"], 2)
        self.assertAlmostEqual(actual["route_delivery_p90_calendar_days_90d"], 3.6)
        self.assertAlmostEqual(actual["route_promise_margin_p90_days"], -.6)
        self.assertAlmostEqual(actual["route_promise_ratio_p90"], 3 / 3.6)
        self.assertAlmostEqual(actual["route_promise_cdf_90d"], (2 + 2 * .5) / 5)

    def test_strict_delivery_time_inclusive_lower_bound_and_current_outcome_exclusion(self):
        approval = pd.Timestamp("2020-04-01 12:00")
        current = queries([("current", approval, 4, "SP", "RJ")])
        delivery_times = [
            approval - pd.Timedelta(days=90) - pd.Timedelta(nanoseconds=1),
            approval - pd.Timedelta(days=90),
            approval - pd.Timedelta(nanoseconds=1), approval,
            approval + pd.Timedelta(nanoseconds=1),
        ]
        history = events([
            (f"past_{index}", delivery - pd.Timedelta(days=index + 1), delivery, 0, "SP", "RJ")
            for index, delivery in enumerate(delivery_times)
        ])
        history = pd.concat([history, events([
            ("current", approval, approval, 0, "SP", "RJ"),
        ])], ignore_index=True)
        actual = add_route_promise_features(current, history).iloc[0]
        self.assertEqual(actual["global_completed_90d"], 2)
        self.assertEqual(actual["route_completed_90d"], 2)
        self.assertAlmostEqual(actual["route_delivery_p50_calendar_days_90d"], 2.5)
        self.assertAlmostEqual(actual["route_delivery_p90_calendar_days_90d"], 2.9)

    def test_reverse_unknown_and_unseen_routes_use_only_global_fallback(self):
        current = queries([
            ("forward", "2020-02-01", 4, "SP", "RJ"),
            ("reverse", "2020-02-01", 4, "RJ", "SP"),
            ("unknown", "2020-02-01", 4, np.nan, "RJ"),
            ("new", "2020-02-01", 4, "MG", "RJ"),
        ])
        history = events([
            ("a", "2020-01-01", "2020-01-03", 0, "SP", "RJ"),
            ("b", "2020-01-01", "2020-01-07", 1, np.nan, "RJ"),
        ])
        actual = add_route_promise_features(current, history)
        self.assertEqual(actual.iloc[0].route_completed_90d, 1)
        self.assertEqual(actual.iloc[0].route_delivery_p90_calendar_days_90d, 2)
        for position in (1, 2, 3):
            row = actual.iloc[position]
            self.assertEqual(row.route_completed_90d, 0)
            self.assertEqual(row.route_delivery_p50_calendar_days_90d, 4)
            self.assertAlmostEqual(row.route_delivery_p90_calendar_days_90d, 5.6)
            self.assertAlmostEqual(row.route_promise_cdf_90d, .5)
        self.assertEqual(actual.iloc[1].state_route, "RJ->SP")
        self.assertTrue(pd.isna(actual.iloc[2].state_route))

    def test_empty_global_history_keeps_zero_counts_and_missing_distribution(self):
        current = queries([("q", "2020-01-01", 10, "SP", "RJ")])
        actual = add_route_promise_features(current, events([])).iloc[0]
        self.assertEqual(actual["global_completed_90d"], 0)
        self.assertEqual(actual["route_completed_90d"], 0)
        self.assertTrue(actual[ROUTE_NUMERIC_FEATURES[2:]].isna().all())

    def test_expired_events_are_removed_even_after_all_events_were_inserted(self):
        current = queries([
            ("early", "2020-02-01", 5, "SP", "RJ"),
            ("late", "2020-07-01", 5, "SP", "RJ"),
        ])
        history = events([("a", "2020-01-01", "2020-01-05", 0, "SP", "RJ")])
        actual = add_route_promise_features(current, history)
        self.assertEqual(actual.iloc[0].route_completed_90d, 1)
        self.assertEqual(actual.iloc[1].route_completed_90d, 0)
        self.assertTrue(pd.isna(actual.iloc[1].route_promise_cdf_90d))

    def test_zero_day_delivery_ratio_and_missing_promise_approval(self):
        current = queries([
            ("zero", "2020-02-01", 0, "SP", "RJ"),
            ("missing_promise", "2020-02-01", np.nan, "SP", "RJ"),
            ("missing_approval", pd.NaT, 10, "SP", "RJ"),
        ])
        history = events([("a", "2020-01-01 12:00", "2020-01-01 13:00", 0, "SP", "RJ")])
        actual = add_route_promise_features(current, history)
        self.assertEqual(actual.iloc[0].route_delivery_p90_calendar_days_90d, 0)
        self.assertTrue(pd.isna(actual.iloc[0].route_promise_ratio_p90))
        self.assertEqual(actual.iloc[0].route_promise_cdf_90d, 1)
        self.assertEqual(actual.iloc[1].route_completed_90d, 1)
        self.assertTrue(actual.iloc[1][ROUTE_NUMERIC_FEATURES[-3:]].isna().all())
        self.assertTrue(actual.iloc[2][ROUTE_NUMERIC_FEATURES].isna().all())

    def test_future_mutation_and_delay_label_changes_do_not_change_earlier_features(self):
        current = queries([
            ("early", "2020-03-01", 12, "SP", "RJ"),
            ("later", "2020-03-05", 12, "SP", "RJ"),
        ])
        history = events([
            ("past", "2020-02-01", "2020-02-08", 0, "SP", "RJ"),
            ("future", "2020-02-01", "2020-03-03", 1, "SP", "RJ"),
        ])
        expected = add_route_promise_features(current, history)
        changed = history.assign(delayed=1 - history.delayed)
        assert_frame_equal(expected, add_route_promise_features(current, changed))
        changed.loc[1, "label_available_time"] = pd.Timestamp("2020-03-04 18:00")
        actual = add_route_promise_features(current, changed)
        assert_frame_equal(expected.iloc[[0]], actual.iloc[[0]])
        self.assertNotEqual(expected.iloc[1].route_delivery_p90_calendar_days_90d,
                            actual.iloc[1].route_delivery_p90_calendar_days_90d)

    def test_input_shuffle_preserves_row_index_and_per_order_values_without_mutation(self):
        current = queries([
            ("q1", "2020-03-01", 10, "SP", "RJ"),
            ("q2", "2020-02-01", 15, "RJ", "SP"),
            ("q3", "2020-04-01", 20, "SP", "RJ"),
        ])
        current.index = [9, 9, 3]
        history = events([
            ("b", "2020-01-01", "2020-01-15", 0, "SP", "RJ"),
            ("a", "2020-01-01", "2020-01-15", 1, "RJ", "SP"),
        ])
        before_current, before_history = current.copy(deep=True), history.copy(deep=True)
        expected = add_route_promise_features(current, history)
        shuffled = current.iloc[[2, 0, 1]]
        actual = add_route_promise_features(shuffled, history.iloc[::-1])
        assert_index_equal(actual.index, shuffled.index)
        assert_frame_equal(expected.set_index("order_id").sort_index(), actual.set_index("order_id").sort_index())
        assert_frame_equal(current, before_current)
        assert_frame_equal(history, before_history)

    def test_rolling_distribution_matches_naive_numpy_oracle(self):
        rng = np.random.default_rng(42)
        origin = pd.Timestamp("2020-01-01")
        history = events([
            (f"e{i}", delivery - pd.Timedelta(days=int(duration)), delivery, i % 2,
             "SP" if i % 3 else "RJ", "RJ" if i % 2 else "SP")
            for i, (delivery, duration) in enumerate(zip(
                origin + pd.to_timedelta(rng.integers(0, 180 * 86400, 300), unit="s"),
                rng.integers(0, 200, 300),
            ))
        ])
        current = queries([
            (f"q{i}", origin + pd.Timedelta(days=int(day)), int(promise),
             "SP" if i % 3 else np.nan, "RJ" if i % 2 else "SP")
            for i, (day, promise) in enumerate(zip(rng.integers(0, 300, 40), rng.integers(0, 150, 40)))
        ])
        actual = add_route_promise_features(current, history, prior_strength=7)
        for position, query in enumerate(current.itertuples()):
            window = history.loc[
                history.label_available_time.ge(query.prediction_time - pd.Timedelta(days=90))
                & history.label_available_time.lt(query.prediction_time)
            ]
            durations = (window.label_available_time.dt.normalize() - window.prediction_time.dt.normalize()).dt.days.to_numpy()
            route = window.loc[window.primary_seller_state.eq(query.primary_seller_state)
                               & window.customer_state.eq(query.customer_state)]
            route_durations = (route.label_available_time.dt.normalize() - route.prediction_time.dt.normalize()).dt.days.to_numpy()
            row = actual.iloc[position]
            self.assertEqual(row.global_completed_90d, len(durations))
            self.assertEqual(row.route_completed_90d, len(route_durations))
            if not len(durations):
                self.assertTrue(pd.isna(row.route_promise_cdf_90d))
                continue
            fallback = route_durations if len(route_durations) else durations
            self.assertAlmostEqual(row.global_delivery_p90_calendar_days_90d, np.quantile(durations, .9, method="linear"))
            self.assertAlmostEqual(row.route_delivery_p50_calendar_days_90d, np.quantile(fallback, .5, method="linear"))
            self.assertAlmostEqual(row.route_delivery_p90_calendar_days_90d, np.quantile(fallback, .9, method="linear"))
            expected_cdf = (np.sum(route_durations <= query.estimated_delivery_days)
                            + 7 * np.mean(durations <= query.estimated_delivery_days)) / (len(route_durations) + 7)
            self.assertAlmostEqual(row.route_promise_cdf_90d, expected_cdf)

    def test_duplicate_events_invalid_timelines_parameters_and_timezones_are_rejected(self):
        current = queries([("q", "2020-02-01", 10, "SP", "RJ")])
        history = events([("a", "2020-01-01", "2020-01-05", 0, "SP", "RJ")])
        with self.assertRaises(ValueError):
            add_route_promise_features(current, pd.concat([history, history]))
        with self.assertRaises(ValueError):
            add_route_promise_features(current, history.assign(label_available_time=pd.Timestamp("2019-01-01")))
        with self.assertRaises(ValueError):
            add_route_promise_features(current, history.drop(columns="label_available_time"))
        for parameter in ({"window_days": 0}, {"window_days": np.inf}, {"prior_strength": -1}, {"prior_strength": np.nan}):
            with self.subTest(parameter=parameter), self.assertRaises(ValueError):
                add_route_promise_features(current, history, **parameter)
        with self.assertRaisesRegex(ValueError, "timezone-naive"):
            add_route_promise_features(current.assign(prediction_time=pd.Timestamp("2020-02-01", tz="UTC")), history)


class RouteBuilderIntegrationTests(unittest.TestCase):
    def test_raw_builder_preserves_base_features_primary_seller_tie_and_one_order_count(self):
        tables = tiny_tables()
        base = build_order_features(tables)
        actual = build_route_order_features(tables)
        assert_frame_equal(actual[base.columns], base)
        current = actual.set_index("order_id").loc["current"]
        self.assertEqual(current.state_route, "RJ->SP")
        self.assertEqual(current.global_completed_90d, 1)
        self.assertEqual(current.route_completed_90d, 1)
        self.assertEqual(current.route_delivery_p90_calendar_days_90d, 9)
        self.assertEqual(current.route_promise_margin_p90_days, 4)
        self.assertEqual(len(ROUTE_NUMERIC_FEATURES), 8)
        self.assertEqual(ROUTE_CATEGORICAL_FEATURES, ["state_route"])
        self.assertEqual(len(FEATURES), 30)
        self.assertFalse({"delayed", "label_available_time", "primary_seller_id"} & set(actual.columns))

    def test_csv_builder_keeps_original_labeled_cohort_and_labels(self):
        tables = tiny_tables()
        expected = add_delay_target(build_order_features(tables), tables["orders"])
        temp_root = Path(__file__).resolve().parents[1] / ".runtime" / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="delay_route_", dir=temp_root) as directory:
            raw_dir = Path(directory)
            for name, filename in CSV_FILES.items():
                tables[name].to_csv(raw_dir / filename, index=False)
            actual = build_route_delay_dataset(raw_dir)
        assert_frame_equal(actual[expected.columns], expected)
        self.assertEqual(actual.order_id.tolist(), ["history", "current"])
        self.assertEqual(set(actual.columns), set(expected.columns) | set(ROUTE_NUMERIC_FEATURES + ROUTE_CATEGORICAL_FEATURES))


if __name__ == "__main__":
    unittest.main()
