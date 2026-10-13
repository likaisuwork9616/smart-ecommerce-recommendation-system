"""Approval-time contractual dispatch deadlines, including missingness."""

import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.delay_dispatch_features import DISPATCH_NUMERIC_FEATURES, add_dispatch_features


def tables_with_items(items):
    return {
        "orders": pd.DataFrame([
            {"order_id": "mixed", "order_estimated_delivery_date": "2018-01-05 08:00"},
            {"order_id": "empty", "order_estimated_delivery_date": "2018-01-05"},
            {"order_id": "unknown", "order_estimated_delivery_date": "2018-01-05"},
        ]),
        "order_items": pd.DataFrame(items, columns=[
            "order_id", "order_item_id", "price", "seller_id", "shipping_limit_date",
        ]),
    }


def queries(order_ids=("mixed",), index=None):
    return pd.DataFrame({
        "order_id": list(order_ids),
        "prediction_time": ["2018-01-01 12:00"] * len(order_ids),
        "existing_feature": np.arange(len(order_ids), dtype=float),
    }, index=index)


class DispatchFeaturesTests(unittest.TestCase):
    def test_hand_calculated_aggregates_use_valid_deadlines_and_calendar_promise_end(self):
        tables = tables_with_items([
            ("mixed", 1, 10., "a", "2018-01-01 00:00"),
            ("mixed", 2, 20., "b", "2018-01-02 12:00"),
            ("mixed", 3, 30., "a", "2018-01-03 00:00"),
            ("mixed", 4, 5., "b", None),
        ])
        row = add_dispatch_features(queries(), tables).iloc[0]
        expected = {
            "dispatch_limit_min_hours_from_approval": -12.,
            "dispatch_limit_max_hours_from_approval": 36.,
            "dispatch_limit_mean_hours_from_approval": 16.,
            "dispatch_limit_spread_hours": 48.,
            "promise_after_latest_dispatch_days": 3.,
            "past_deadline_item_ratio": 1 / 3,
            "missing_limit_item_ratio": 1 / 4,
            "primary_item_dispatch_limit_hours": 36.,
        }
        self.assertEqual(len(DISPATCH_NUMERIC_FEATURES), 8)
        self.assertEqual(set(expected), set(DISPATCH_NUMERIC_FEATURES))
        for name, value in expected.items():
            self.assertAlmostEqual(row[name], value)

    def test_deadline_equal_to_approval_is_not_past_but_one_nanosecond_earlier_is(self):
        tables = tables_with_items([
            ("mixed", 1, 10., "a", "2018-01-01 12:00:00"),
            ("mixed", 2, 10., "a", "2018-01-01 11:59:59.999999999"),
            ("mixed", 3, 10., "a", "2018-01-01 12:00:00.000000001"),
            ("mixed", 4, 10., "a", None),
        ])
        row = add_dispatch_features(queries(), tables).iloc[0]
        self.assertAlmostEqual(row.past_deadline_item_ratio, 1 / 3)
        self.assertEqual(row.primary_item_dispatch_limit_hours, 0.)
        self.assertGreater(row.dispatch_limit_spread_hours, 0.)

    def test_invalid_all_missing_deadlines_and_no_items_have_distinct_missingness(self):
        tables = tables_with_items([
            ("mixed", 1, 10., "a", "invalid timestamp"),
            ("mixed", 2, 10., "a", None),
            ("unknown", 1, 10., "a", "not a date"),
        ])
        result = add_dispatch_features(queries(("mixed", "empty", "unknown")), tables)
        rest = [name for name in DISPATCH_NUMERIC_FEATURES if name != "missing_limit_item_ratio"]
        self.assertTrue(result[rest].isna().all(axis=None))
        self.assertEqual(result.loc[0, "missing_limit_item_ratio"], 1.)
        self.assertTrue(pd.isna(result.loc[1, "missing_limit_item_ratio"]))
        self.assertEqual(result.loc[2, "missing_limit_item_ratio"], 1.)
        del tables["order_items"]["shipping_limit_date"]
        absent_column = add_dispatch_features(queries(), tables)
        self.assertEqual(absent_column.loc[0, "missing_limit_item_ratio"], 1.)
        self.assertTrue(absent_column[rest].isna().all(axis=None))
        tables["order_items"] = tables["order_items"].iloc[0:0]
        no_items = add_dispatch_features(queries(), tables)
        self.assertTrue(no_items[DISPATCH_NUMERIC_FEATURES].isna().all(axis=None))

    def test_preserves_base_values_order_duplicate_index_and_does_not_mutate_sources(self):
        tables = tables_with_items([
            ("mixed", 1, 10., "a", "2018-01-02 12:00"),
            ("unknown", 1, 10., "a", "2018-01-03 12:00"),
        ])
        frame = queries(("unknown", "mixed", "empty"), index=[7, 2, 7])
        frame["label_available_time"] = pd.Timestamp("2099-01-01")
        copies = {name: source.copy(deep=True) for name, source in tables.items()}
        original = frame.copy(deep=True)
        result = add_dispatch_features(frame, tables)
        assert_frame_equal(result[frame.columns], original)
        assert_frame_equal(frame, original)
        for name, source in tables.items():
            assert_frame_equal(source, copies[name])
        self.assertEqual(result.iloc[0].dispatch_limit_min_hours_from_approval, 48.)
        self.assertEqual(result.iloc[1].dispatch_limit_min_hours_from_approval, 24.)
        self.assertTrue(pd.isna(result.iloc[2].dispatch_limit_min_hours_from_approval))
        self.assertEqual(result.columns.tolist(), frame.columns.tolist() + DISPATCH_NUMERIC_FEATURES)
        empty_frame = frame.iloc[0:0]
        empty = add_dispatch_features(empty_frame, tables)
        assert_frame_equal(empty[empty_frame.columns], empty_frame)
        self.assertEqual(empty.columns.tolist(), result.columns.tolist())

    def test_final_outcomes_and_actual_carrier_events_do_not_change_deadline_features(self):
        tables = tables_with_items([
            ("mixed", 1, 10., "a", "2018-01-03 12:00"),
        ])
        before = add_dispatch_features(queries(), tables)
        tables["orders"]["order_delivered_carrier_date"] = "2018-01-01 11:00"
        tables["orders"]["order_delivered_customer_date"] = "2030-01-01"
        tables["orders"]["order_status"] = "canceled"
        tables["orders"]["review_score"] = 1
        tables["order_items"]["actual_dispatch_time"] = "2030-01-01"
        after = add_dispatch_features(queries(), tables)
        assert_frame_equal(before, after)

    def test_primary_item_uses_highest_price_then_sequence_across_multiple_sellers(self):
        tables = tables_with_items([
            ("mixed", 3, 99., "seller_a", "2018-01-04 12:00"),
            ("mixed", 1, 99., "seller_b", "2018-01-02 12:00"),
            ("mixed", 2, 10., "seller_b", "2018-01-05 12:00"),
            ("mixed", 4, np.nan, "seller_c", "2018-01-01 12:00"),
        ])
        row = add_dispatch_features(queries(), tables).iloc[0]
        self.assertEqual(row.primary_item_dispatch_limit_hours, 24.)
        tables["order_items"].loc[tables["order_items"].order_item_id == 1, "shipping_limit_date"] = None
        row = add_dispatch_features(queries(), tables).iloc[0]
        self.assertTrue(pd.isna(row.primary_item_dispatch_limit_hours))
        self.assertEqual(row.dispatch_limit_max_hours_from_approval, 96.)

    def test_rejects_duplicate_keys_missing_contract_and_preexisting_features(self):
        tables = tables_with_items([
            ("mixed", 1, 10., "a", "2018-01-02 12:00"),
        ])
        duplicate_items = {name: frame.copy() for name, frame in tables.items()}
        duplicate_items["order_items"] = pd.concat([tables["order_items"]] * 2, ignore_index=True)
        with self.assertRaisesRegex(ValueError, "unique within each order"):
            add_dispatch_features(queries(), duplicate_items)
        with self.assertRaisesRegex(ValueError, "query order IDs must be unique"):
            add_dispatch_features(queries(("mixed", "mixed")), tables)
        duplicate_orders = {name: frame.copy() for name, frame in tables.items()}
        duplicate_orders["orders"] = pd.concat([tables["orders"]] * 2, ignore_index=True)
        with self.assertRaisesRegex(ValueError, "source order IDs must be unique"):
            add_dispatch_features(queries(), duplicate_orders)
        with self.assertRaisesRegex(ValueError, "Missing dispatch queries"):
            add_dispatch_features(queries().drop(columns="prediction_time"), tables)
        existing = queries()
        existing[DISPATCH_NUMERIC_FEATURES[0]] = 1.
        with self.assertRaisesRegex(ValueError, "already exist"):
            add_dispatch_features(existing, tables)
        tables["order_items"].loc[0, "order_item_id"] = np.nan
        with self.assertRaisesRegex(ValueError, "sequences must be non-null"):
            add_dispatch_features(queries(), tables)

    def test_timezone_aware_inputs_are_rejected_and_missing_query_times_remain_unknown(self):
        tables = tables_with_items([
            ("mixed", 1, 10., "a", "2018-01-02 12:00"),
            ("mixed", 2, 10., "a", "2018-01-03 12:00"),
        ])
        for kind in ("query", "promise", "limit"):
            with self.subTest(kind=kind):
                changed = {name: frame.copy() for name, frame in tables.items()}
                frame = queries()
                if kind == "query":
                    frame["prediction_time"] = "2018-01-01T12:00:00+00:00"
                elif kind == "promise":
                    changed["orders"]["order_estimated_delivery_date"] = "2018-01-05T00:00:00+00:00"
                else:
                    changed["order_items"]["shipping_limit_date"] = "2018-01-02T12:00:00+00:00"
                with self.assertRaisesRegex(ValueError, "timezone-naive"):
                    add_dispatch_features(frame, changed)
        frame = queries()
        frame["prediction_time"] = "invalid"
        row = add_dispatch_features(frame, tables).iloc[0]
        approval_dependent = [
            "dispatch_limit_min_hours_from_approval", "dispatch_limit_max_hours_from_approval",
            "dispatch_limit_mean_hours_from_approval", "past_deadline_item_ratio",
            "primary_item_dispatch_limit_hours",
        ]
        self.assertTrue(row[approval_dependent].isna().all())
        self.assertEqual(row.dispatch_limit_spread_hours, 24.)
        self.assertEqual(row.missing_limit_item_ratio, 0.)
        tables["orders"]["order_estimated_delivery_date"] = None
        row = add_dispatch_features(queries(), tables).iloc[0]
        self.assertTrue(pd.isna(row.promise_after_latest_dispatch_days))


if __name__ == "__main__":
    unittest.main()
