"""Static postal reference features available from customer and item sellers.

The Olist geolocation table has no version or observation timestamps. It is
treated as a static reference, rather than order history or postal frequency
evidence. Each postal prefix uses the median of valid coordinate pairs. The
haversine distances describe representative postal points on the globe; they
are not road distances, actual delivery routes or shipping durations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.delay_history_features import build_primary_sellers


EARTH_RADIUS_KM = 6371.0088
GEO_NUMERIC_FEATURES = [
    "geo_primary_distance_km",
    "geo_item_distance_mean_km",
    "geo_item_distance_max_km",
    "geo_known_distance_item_ratio",
    "geo_same_zip5_item_ratio",
    "geo_customer_latitude",
    "geo_customer_longitude",
    "geo_primary_seller_latitude",
    "geo_primary_seller_longitude",
]


def canonical_zip5(values: pd.Series) -> pd.Series:
    """Use zero-padded five-digit integer prefixes; invalid values stay missing."""
    numeric = pd.to_numeric(values, errors="coerce")
    valid = np.isfinite(numeric) & numeric.between(0, 99999) & numeric.eq(np.floor(numeric))
    # Boolean values are flags, not a postal prefix of 00000 or 00001.
    valid &= ~values.map(lambda value: isinstance(value, (bool, np.bool_)))
    result = pd.Series(np.nan, index=values.index, dtype=object)
    result.loc[valid] = numeric.loc[valid].astype("int64").map(lambda value: f"{value:05d}")
    return result


def _valid_coordinates(latitude, longitude):
    return (
        np.isfinite(latitude) & np.isfinite(longitude)
        & (np.abs(latitude) <= 90) & (np.abs(longitude) <= 180)
    )


def build_postal_coordinates(geolocation: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pairs after excluding rows with either invalid coordinate."""
    required = {"geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng"}
    missing = required.difference(geolocation.columns)
    if missing:
        raise ValueError(f"Missing geolocation columns: {sorted(missing)}")
    postal = canonical_zip5(geolocation["geolocation_zip_code_prefix"])
    latitude = pd.to_numeric(geolocation["geolocation_lat"], errors="coerce")
    longitude = pd.to_numeric(geolocation["geolocation_lng"], errors="coerce")
    valid = postal.notna() & _valid_coordinates(latitude, longitude)
    paired = pd.DataFrame({
        "zip5": postal.loc[valid],
        "latitude": latitude.loc[valid],
        "longitude": longitude.loc[valid],
    })
    return paired.groupby("zip5", sort=True)[["latitude", "longitude"]].median()


def haversine_km(latitude_a, longitude_a, latitude_b, longitude_b):
    """Vectorized great-circle distance, missing if either pair is invalid."""
    lat_a, lon_a, lat_b, lon_b = np.broadcast_arrays(
        np.asarray(latitude_a, dtype=float), np.asarray(longitude_a, dtype=float),
        np.asarray(latitude_b, dtype=float), np.asarray(longitude_b, dtype=float),
    )
    valid = _valid_coordinates(lat_a, lon_a) & _valid_coordinates(lat_b, lon_b)
    # Mask before trigonometry so infinity never produces a runtime warning.
    lat_a, lon_a, lat_b, lon_b = [np.radians(np.where(valid, value, np.nan))
                                for value in (lat_a, lon_a, lat_b, lon_b)]
    argument = (np.sin((lat_b - lat_a) / 2) ** 2
                + np.cos(lat_a) * np.cos(lat_b) * np.sin((lon_b - lon_a) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(argument, 0, 1)))


def _unique_lookup(table: pd.DataFrame, key: str, column: str) -> pd.Series:
    if key not in table:
        raise ValueError(f"Missing lookup key: {key}")
    if table[key].duplicated().any():
        raise ValueError(f"{key} must be unique")
    values = table[column] if column in table else pd.Series(np.nan, index=table.index)
    return pd.Series(canonical_zip5(values).to_numpy(), index=table[key], dtype=object)


def add_geo_features(
    features: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    geolocation: pd.DataFrame,
) -> pd.DataFrame:
    """Append nine features without changing existing rows, columns or index.

    Item summaries weight each order item equally, including repeated sellers.
    Distance means/maxima use only known coordinate pairs. The known-distance
    ratio divides by all items; the same-prefix ratio divides only by items
    with both postal prefixes known, independently of coordinate availability.
    No outcome, fulfillment status or delivery timestamps are read.
    """
    if "order_id" not in features:
        raise ValueError("Features must contain order_id")
    if set(GEO_NUMERIC_FEATURES).intersection(features.columns):
        raise ValueError("Geographic feature columns already exist")
    orders = tables["orders"]
    if orders["order_id"].duplicated().any():
        raise ValueError("orders.order_id must be unique")
    order_customer = orders.set_index("order_id")["customer_id"]
    customer_postal = _unique_lookup(tables["customers"], "customer_id", "customer_zip_code_prefix")
    seller_postal = _unique_lookup(tables["sellers"], "seller_id", "seller_zip_code_prefix")
    coordinates = build_postal_coordinates(geolocation)
    primary_sellers = build_primary_sellers(tables["order_items"]).set_index("order_id")["primary_seller_id"]

    output = features.copy()
    order_ids = output["order_id"]
    customer_zip = order_ids.map(order_customer).map(customer_postal)
    primary_zip = order_ids.map(primary_sellers).map(seller_postal)
    for owner, postal in (("customer", customer_zip), ("primary_seller", primary_zip)):
        for coordinate in ("latitude", "longitude"):
            output[f"geo_{owner}_{coordinate}"] = postal.map(coordinates[coordinate]).to_numpy()
    output["geo_primary_distance_km"] = haversine_km(
        output["geo_customer_latitude"], output["geo_customer_longitude"],
        output["geo_primary_seller_latitude"], output["geo_primary_seller_longitude"],
    )

    items = tables["order_items"][["order_id", "seller_id"]].copy()
    item_customer_zip = items["order_id"].map(order_customer).map(customer_postal)
    item_seller_zip = items["seller_id"].map(seller_postal)
    items["distance"] = haversine_km(
        item_customer_zip.map(coordinates["latitude"]), item_customer_zip.map(coordinates["longitude"]),
        item_seller_zip.map(coordinates["latitude"]), item_seller_zip.map(coordinates["longitude"]),
    )
    items["distance_known"] = items["distance"].notna().astype(float)
    postal_known = item_customer_zip.notna() & item_seller_zip.notna()
    items["same_zip"] = np.where(postal_known, item_customer_zip.eq(item_seller_zip), np.nan)
    summary = items.groupby("order_id", sort=False).agg(
        geo_item_distance_mean_km=("distance", "mean"),
        geo_item_distance_max_km=("distance", "max"),
        geo_known_distance_item_ratio=("distance_known", "mean"),
        geo_same_zip5_item_ratio=("same_zip", "mean"),
    )
    for name in summary:
        output[name] = order_ids.map(summary[name]).to_numpy()
    # Existing column order is retained and the new contract is always fixed.
    return output[list(features.columns) + GEO_NUMERIC_FEATURES]
