"""Hand-computed interaction values and explicit model-input contracts."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.delay_engineering_features import (
    BASE_NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    DISPATCH_ENGINEERING_NUMERIC_FEATURES,
    ENGINEERING_NUMERIC_FEATURES,
    INTERACTION_NUMERIC_FEATURES,
    add_engineering_interactions,
    prepare_engineering_input,
)
from scripts.predict_delay import build_inference_features


def interaction_fixture():
    return pd.DataFrame([{
        "order_id": "order", "prediction_time": pd.Timestamp("2018-01-03 23:47"),
        "geo_primary_distance_km": 600.0, "estimated_delivery_days": 10.0,
        "seller_pending_30d": 12.0, "seller_completed_90d": 60.0,
        "route_pending_30d": 30.0, "route_completed_90d": 90.0,
        "global_pending_30d": 70.0, "seller_pending_overdue_30d": 3.0,
        "route_pending_overdue_30d": 6.0, "global_pending_overdue_30d": 7.0,
        "product_weight_g_mean": 300.0, "product_volume_cm3_mean": 120.0,
        "total_freight_value": 48.0, "total_price": 400.0, "item_count": 4.0,
    }])


class EngineeringFeaturesTests(unittest.TestCase):
    def test_all_fourteen_interactions_match_hand_calculation(self):
        actual = add_engineering_interactions(interaction_fixture()).iloc[0]
        expected = [60, 10 / 6, 12 / 21, 30 / 31, .25, .2, .1, 2.5, 12, 100, 2, 23, 5, .08]
        self.assertEqual(len(INTERACTION_NUMERIC_FEATURES), 14)
        np.testing.assert_allclose(actual[INTERACTION_NUMERIC_FEATURES].to_numpy(dtype=float), expected)

    def test_zero_denominators_are_missing_but_zero_numerators_remain_valid(self):
        frame = pd.concat([interaction_fixture()] * 2, ignore_index=True)
        zero_columns = ["geo_primary_distance_km", "estimated_delivery_days", "seller_pending_30d",
                        "route_pending_30d", "global_pending_30d", "product_volume_cm3_mean", "item_count"]
        frame.loc[0, zero_columns] = 0
        actual = add_engineering_interactions(frame)
        missing_names = ["geo_distance_per_promise_day", "geo_promise_days_per_100km",
                         "seller_overdue_pending_share_30d", "route_overdue_pending_share_30d",
                         "global_overdue_pending_share_30d", "product_density_g_cm3", "freight_per_item",
                         "price_per_item", "geo_freight_per_km"]
        self.assertTrue(actual.loc[0, missing_names].isna().all())
        self.assertEqual(actual.loc[0, "seller_pending_vs_completed_30d"], 0)
        self.assertEqual(actual.loc[0, "promise_weekday"], 2)
        frame.loc[1, ["total_freight_value", "total_price", "product_weight_g_mean",
                      "seller_pending_overdue_30d", "seller_completed_90d"]] = 0
        actual = add_engineering_interactions(frame)
        self.assertEqual(actual.loc[1, "freight_per_item"], 0)
        self.assertEqual(actual.loc[1, "price_per_item"], 0)
        self.assertEqual(actual.loc[1, "product_density_g_cm3"], 0)
        self.assertEqual(actual.loc[1, "seller_overdue_pending_share_30d"], 0)
        self.assertEqual(actual.loc[1, "seller_pending_vs_completed_30d"], 12)

    def test_negative_nonfinite_and_missing_measurements_cannot_make_valid_ratios(self):
        frame = pd.concat([interaction_fixture()] * 4, ignore_index=True)
        measurements = frame.select_dtypes("number").columns
        for index, invalid in enumerate([-1, np.inf, -np.inf, np.nan]):
            frame.loc[index, measurements] = invalid
        actual = add_engineering_interactions(frame)
        ratio_names = [name for name in INTERACTION_NUMERIC_FEATURES
                       if name not in {"approval_weekday", "approval_hour", "promise_weekday"}]
        self.assertTrue(actual[ratio_names].isna().all(axis=None))
        self.assertTrue(actual.promise_weekday.isna().all())
        self.assertTrue(actual.approval_weekday.eq(2).all())
        self.assertTrue(actual.approval_hour.eq(23).all())
        self.assertFalse(np.isinf(actual[INTERACTION_NUMERIC_FEATURES].to_numpy(dtype=float)).any())

    def test_promise_weekday_is_calendar_offset_not_fractional_approval_time(self):
        frame = pd.concat([interaction_fixture()] * 4, ignore_index=True)
        frame["estimated_delivery_days"] = [0, 1, 1.5, np.nan]
        actual = add_engineering_interactions(frame)
        self.assertEqual(actual.promise_weekday.iloc[:2].tolist(), [2, 3])
        self.assertTrue(actual.promise_weekday.iloc[2:].isna().all())
        frame.loc[0, "prediction_time"] = pd.NaT
        missing = add_engineering_interactions(frame)
        self.assertTrue(missing.loc[0, ["approval_weekday", "approval_hour", "promise_weekday"]].isna().all())
        # Quantitative ratios are independent of approval's clock time.
        self.assertEqual(missing.loc[1, "geo_distance_per_promise_day"], 600)

    def test_duplicate_index_and_existing_columns_are_preserved_without_mutation(self):
        frame = pd.concat([interaction_fixture()] * 3, ignore_index=True)
        frame["order_id"] = ["third", "first", "second"]
        frame.index = pd.Index([8, 2, 2], name="custom")
        expected = frame.copy(deep=True)
        actual = add_engineering_interactions(frame)
        assert_frame_equal(actual[expected.columns], expected)
        assert_frame_equal(frame, expected)
        self.assertEqual(actual.columns.tolist(), expected.columns.tolist() + INTERACTION_NUMERIC_FEATURES)

    def test_outcome_columns_never_affect_the_interactions(self):
        frame = interaction_fixture()
        expected = add_engineering_interactions(frame)[INTERACTION_NUMERIC_FEATURES]
        frame["delayed"] = 1
        frame["order_status"] = "canceled"
        frame["label_available_time"] = pd.Timestamp("2099-01-01")
        frame["order_delivered_customer_date"] = pd.Timestamp("2099-01-01")
        frame["order_delivered_carrier_date"] = pd.Timestamp("2098-12-31")
        actual = add_engineering_interactions(frame)[INTERACTION_NUMERIC_FEATURES]
        assert_frame_equal(actual, expected)

    def test_prepare_variants_whitelist_exact_sixty_eighty_three_and_ninety_one_features(self):
        frame = pd.DataFrame({name: [1.0] for name in DISPATCH_ENGINEERING_NUMERIC_FEATURES})
        for name in CATEGORICAL_FEATURES:
            frame[name] = "known"
        frame["customer_zip_prefix3"] = "001"
        frame["primary_seller_zip_prefix3"] = "010"
        frame["delayed"] = 1
        frame["order_id"] = "order"
        frame["prediction_time"] = pd.Timestamp("2018-01-03")
        frame["label_available_time"] = pd.Timestamp("2099-01-01")
        expected = frame.copy(deep=True)
        choices = [("base", BASE_NUMERIC_FEATURES, 60), ("geo", ENGINEERING_NUMERIC_FEATURES, 83),
                   ("dispatch", DISPATCH_ENGINEERING_NUMERIC_FEATURES, 91)]
        for variant, numeric, count in choices:
            actual = prepare_engineering_input(frame, variant)
            self.assertEqual(actual.columns.tolist(), list(numeric) + list(CATEGORICAL_FEATURES))
            self.assertEqual(len(actual.columns), count)
            self.assertEqual(actual.customer_zip_prefix3.iloc[0], "001")
            self.assertEqual(actual.primary_seller_zip_prefix3.iloc[0], "010")
            self.assertFalse(set(actual).intersection({"delayed", "order_id", "prediction_time", "label_available_time"}))
        assert_frame_equal(frame, expected)

    def test_prepare_normalizes_numeric_invalids_and_categorical_missing_values(self):
        frame = pd.DataFrame({name: [1.0] for name in DISPATCH_ENGINEERING_NUMERIC_FEATURES})
        for name in CATEGORICAL_FEATURES:
            frame[name] = pd.NA
        frame["geo_primary_distance_km"] = np.inf
        frame["product_weight_g_mean"] = "invalid"
        actual = prepare_engineering_input(frame, "geo")
        self.assertTrue(actual[["geo_primary_distance_km", "product_weight_g_mean"]].isna().all(axis=None))
        self.assertTrue(actual[list(CATEGORICAL_FEATURES)].isna().all(axis=None))
        self.assertTrue(all(actual[name].dtype == object for name in CATEGORICAL_FEATURES))

    def test_feature_contract_errors_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "Interaction columns already exist"):
            add_engineering_interactions(add_engineering_interactions(interaction_fixture()))
        with self.assertRaisesRegex(ValueError, "Unknown feature variant"):
            prepare_engineering_input(pd.DataFrame(), "unregistered")
        with self.assertRaisesRegex(ValueError, "Missing engineering feature columns"):
            prepare_engineering_input(pd.DataFrame(), "geo")

    def test_engineering_inference_dispatches_feature_contract_and_original_objects(self):
        tables = {"orders": pd.DataFrame({"order_id": ["order"]})}
        geolocation = pd.DataFrame({"reference": ["postal"]})
        expected = pd.DataFrame({"order_id": ["order"], "feature": [1.0]})
        choices = [("geo_engineered_approval", False), ("dispatch_geo_engineered_approval", True)]
        for feature_set, include_dispatch in choices:
            with self.subTest(feature_set=feature_set):
                with patch("scripts.delay_engineering_features.build_engineering_order_features",
                           return_value=expected) as builder:
                    actual = build_inference_features({"feature_set": feature_set}, tables, geolocation)
                self.assertIs(actual, expected)
                builder.assert_called_once_with(tables, geolocation, include_dispatch=include_dispatch)
                self.assertIs(builder.call_args.args[0], tables)
                self.assertIs(builder.call_args.args[1], geolocation)

    def test_engineering_inference_rejects_missing_geolocation_before_building(self):
        for feature_set in ("geo_engineered_approval", "dispatch_geo_engineered_approval"):
            with self.subTest(feature_set=feature_set):
                with patch("scripts.delay_engineering_features.build_engineering_order_features") as builder:
                    with self.assertRaisesRegex(ValueError, "requires the static geolocation reference table"):
                        build_inference_features({"feature_set": feature_set}, {"orders": pd.DataFrame()})
                builder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
