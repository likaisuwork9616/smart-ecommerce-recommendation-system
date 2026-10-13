"""Postal-reference distance and missing-data behavior, independent of outcomes."""

import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.delay_geo_features import (
    EARTH_RADIUS_KM,
    GEO_NUMERIC_FEATURES,
    add_geo_features,
    build_postal_coordinates,
    canonical_zip5,
    haversine_km,
)
from scripts.delay_history_features import build_primary_sellers


def fixture():
    features = pd.DataFrame({"order_id": ["multi", "other", "empty"], "existing": [7, 8, 9]})
    tables = {
        "orders": pd.DataFrame({"order_id": ["multi", "other", "empty"],
                                "customer_id": ["customer", "unknown_customer", "customer"]}),
        "customers": pd.DataFrame({"customer_id": ["customer", "unknown_customer"],
                                   "customer_zip_code_prefix": ["01040", np.nan]}),
        "sellers": pd.DataFrame({"seller_id": ["near", "far", "unlocated", "unknown"],
                                 "seller_zip_code_prefix": [1040, "02000", "03000", None]}),
        "order_items": pd.DataFrame([
            {"order_id": "multi", "order_item_id": 1, "seller_id": "near", "price": 10},
            {"order_id": "multi", "order_item_id": 2, "seller_id": "near", "price": 10},
            {"order_id": "multi", "order_item_id": 3, "seller_id": "far", "price": 20},
            {"order_id": "multi", "order_item_id": 4, "seller_id": "unlocated", "price": 5},
            {"order_id": "multi", "order_item_id": 5, "seller_id": "unknown", "price": 5},
            {"order_id": "other", "order_item_id": 1, "seller_id": "far", "price": 20},
        ]),
    }
    geolocation = pd.DataFrame({
        "geolocation_zip_code_prefix": ["01040", "02000"],
        "geolocation_lat": [0.0, 0.0], "geolocation_lng": [0.0, 1.0],
    })
    return features, tables, geolocation


class GeoFeaturesTests(unittest.TestCase):
    def test_haversine_zero_antipodal_quarter_circle_and_symmetry(self):
        actual = haversine_km([0, 0, 0, -23.55], [0, 0, 0, -46.63],
                              [0, 0, 90, -22.91], [0, 180, 0, -43.17])
        self.assertEqual(actual[0], 0)
        self.assertAlmostEqual(actual[1], np.pi * EARTH_RADIUS_KM)
        self.assertAlmostEqual(actual[2], np.pi * EARTH_RADIUS_KM / 2)
        reverse = haversine_km(-22.91, -43.17, -23.55, -46.63)
        self.assertAlmostEqual(actual[3], reverse)

    def test_invalid_coordinate_in_either_pair_produces_missing_distance(self):
        actual = haversine_km([91, 0, np.nan, 0, 0], [0, 181, 0, 0, 0],
                              [0, 0, 0, np.inf, 0], [0, 0, 0, 0, -181])
        self.assertTrue(np.isnan(actual).all())

    def test_postal_normalization_keeps_leading_zeroes_and_invalids_missing(self):
        actual = canonical_zip5(pd.Series(["01040", 1040.0, 0, "99999", -1,
                                          100000, 1040.5, "missing", None, np.inf, True]))
        self.assertEqual(actual.iloc[:4].tolist(), ["01040", "01040", "00000", "99999"])
        self.assertTrue(actual.iloc[4:].isna().all())

    def test_coordinate_medians_only_include_whole_valid_pairs(self):
        geolocation = pd.DataFrame({
            "geolocation_zip_code_prefix": ["01040"] * 5 + ["invalid", "02000"],
            "geolocation_lat": [-23, -21, 89, 91, np.nan, 0, 0],
            "geolocation_lng": [-46, -44, np.nan, 178, 179, 0, np.inf],
        })
        coordinates = build_postal_coordinates(geolocation)
        self.assertEqual(coordinates.index.tolist(), ["01040"])
        self.assertEqual(coordinates.loc["01040"].tolist(), [-22, -45])

    def test_all_item_sellers_are_weighted_by_items_and_ratios_have_distinct_denominators(self):
        features, tables, geolocation = fixture()
        current = add_geo_features(features, tables, geolocation).set_index("order_id").loc["multi"]
        distance = np.pi * EARTH_RADIUS_KM / 180
        self.assertAlmostEqual(current.geo_primary_distance_km, distance)
        self.assertAlmostEqual(current.geo_item_distance_mean_km, distance / 3)
        self.assertAlmostEqual(current.geo_item_distance_max_km, distance)
        self.assertAlmostEqual(current.geo_known_distance_item_ratio, 3 / 5)
        # Four items have both postal prefixes; coordinate-missing 03000 still counts.
        self.assertAlmostEqual(current.geo_same_zip5_item_ratio, 2 / 4)
        self.assertEqual(current.geo_customer_longitude, 0)
        self.assertEqual(current.geo_primary_seller_longitude, 1)

    def test_primary_seller_price_and_item_sequence_ties_match_existing_contract(self):
        features, tables, geolocation = fixture()
        tables["order_items"].loc[tables["order_items"].order_item_id.eq(2), "price"] = 20
        primary = build_primary_sellers(tables["order_items"]).set_index("order_id")
        self.assertEqual(primary.loc["multi", "primary_seller_id"], "near")
        actual = add_geo_features(features, tables, geolocation).set_index("order_id")
        self.assertEqual(actual.loc["multi", "geo_primary_distance_km"], 0)
        # The farther item remains present in the all-item maximum.
        self.assertGreater(actual.loc["multi", "geo_item_distance_max_km"], 100)

    def test_original_order_duplicate_index_and_existing_columns_are_preserved(self):
        features, tables, geolocation = fixture()
        features = features.iloc[[2, 0, 1, 0]].copy()
        features.index = pd.Index([8, 2, 2, 1], name="custom_index")
        expected = features.copy(deep=True)
        actual = add_geo_features(features, tables, geolocation)
        assert_frame_equal(actual[features.columns], expected)
        assert_frame_equal(features, expected)
        self.assertEqual(actual.columns.tolist(), features.columns.tolist() + GEO_NUMERIC_FEATURES)
        self.assertEqual(len(GEO_NUMERIC_FEATURES), 9)
        self.assertTrue(np.issubdtype(actual[GEO_NUMERIC_FEATURES].to_numpy().dtype, np.floating))

    def test_missing_customer_no_items_and_missing_postal_columns_stay_explicit(self):
        features, tables, geolocation = fixture()
        actual = add_geo_features(features, tables, geolocation).set_index("order_id")
        self.assertTrue(actual.loc["other", ["geo_primary_distance_km", "geo_same_zip5_item_ratio"]].isna().all())
        self.assertEqual(actual.loc["other", "geo_known_distance_item_ratio"], 0)
        self.assertTrue(actual.loc["empty", ["geo_primary_distance_km", "geo_item_distance_mean_km",
                                            "geo_known_distance_item_ratio", "geo_same_zip5_item_ratio"]].isna().all())
        del tables["customers"]["customer_zip_code_prefix"]
        del tables["sellers"]["seller_zip_code_prefix"]
        no_postal = add_geo_features(features, tables, geolocation)
        self.assertTrue(no_postal[[name for name in GEO_NUMERIC_FEATURES
                                 if name != "geo_known_distance_item_ratio"]].isna().all(axis=None))

    def test_future_delivery_status_and_labels_never_change_geographic_features(self):
        features, tables, geolocation = fixture()
        expected = add_geo_features(features, tables, geolocation)
        tables["orders"]["order_status"] = "canceled"
        tables["orders"]["order_delivered_customer_date"] = "2099-01-01"
        tables["orders"]["order_approved_at"] = "2098-01-01"
        tables["orders"]["order_estimated_delivery_date"] = "2098-12-31"
        actual = add_geo_features(features, tables, geolocation)
        assert_frame_equal(actual, expected)

    def test_duplicate_lookup_keys_and_duplicate_item_sequence_are_rejected(self):
        features, tables, geolocation = fixture()
        tables["customers"] = pd.concat([tables["customers"], tables["customers"].iloc[[0]]])
        with self.assertRaisesRegex(ValueError, "customer_id must be unique"):
            add_geo_features(features, tables, geolocation)
        _, tables, _ = fixture()
        tables["order_items"] = pd.concat([tables["order_items"], tables["order_items"].iloc[[0]]])
        with self.assertRaisesRegex(ValueError, "item sequences must be unique"):
            add_geo_features(features, tables, geolocation)


if __name__ == "__main__":
    unittest.main()
