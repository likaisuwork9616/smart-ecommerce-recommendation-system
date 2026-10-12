"""Order-level features available when payment/order approval is recorded.

Actual delivery, shipping milestones, reviews and order status are used only
to construct a retrospective training cohort/label, never as model features.
"""
from pathlib import Path

import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    'item_count', 'seller_count', 'product_count', 'total_price',
    'total_freight_value', 'freight_ratio', 'payment_total', 'payment_count',
    'payment_installments_max', 'product_weight_g_mean',
    'product_volume_cm3_mean', 'estimated_delivery_days', 'approval_wait_hours',
    'purchase_month', 'purchase_dayofweek', 'purchase_hour', 'interstate_item_ratio',
]
CATEGORICAL_FEATURES = [
    'customer_state', 'primary_seller_state', 'primary_category', 'payment_type',
]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
CSV_FILES = {
    'orders': 'olist_orders_dataset.csv',
    'customers': 'olist_customers_dataset.csv',
    'order_items': 'olist_order_items_dataset.csv',
    'order_payments': 'olist_order_payments_dataset.csv',
    'products': 'olist_products_dataset.csv',
    'sellers': 'olist_sellers_dataset.csv',
}


def load_olist_tables(raw_dir: Path) -> dict[str, pd.DataFrame]:
    """Read the six source tables; no MySQL credentials are required."""
    return {name: pd.read_csv(Path(raw_dir) / filename)
            for name, filename in CSV_FILES.items()}


def build_order_features(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregate items and payments separately, then join one row per order.

    The most expensive item represents category/seller; ties use item sequence.
    The highest-value payment represents payment type; ties use its sequence.
    Missing product attributes remain missing until the train-only imputer.
    """
    orders = tables['orders'].copy()
    if orders['order_id'].duplicated().any():
        raise ValueError('orders.order_id must be unique')
    base = orders[[
        'order_id', 'customer_id', 'order_purchase_timestamp', 'order_approved_at',
        'order_estimated_delivery_date',
    ]].copy()
    for column in ['order_purchase_timestamp', 'order_approved_at',
                   'order_estimated_delivery_date']:
        base[column] = pd.to_datetime(base[column], errors='coerce')
    base = base.rename(columns={'order_approved_at': 'prediction_time'})
    base = base.merge(tables['customers'][['customer_id', 'customer_state']],
                      on='customer_id', how='left', validate='many_to_one')

    items = tables['order_items'].copy()
    if items.duplicated(['order_id', 'order_item_id']).any():
        raise ValueError('order_items must have unique order_id/order_item_id')
    product_columns = ['product_id', 'product_category_name', 'product_weight_g',
                       'product_length_cm', 'product_height_cm', 'product_width_cm']
    items = items.merge(tables['products'][product_columns], on='product_id',
                        how='left', validate='many_to_one')
    items = items.merge(tables['sellers'][['seller_id', 'seller_state']],
                        on='seller_id', how='left', validate='many_to_one')
    items = items.merge(base[['order_id', 'customer_state']], on='order_id',
                        how='left', validate='many_to_one')
    items['product_volume_cm3'] = (items['product_length_cm'] *
                                  items['product_height_cm'] * items['product_width_cm'])
    # Unknown states are unknown, rather than silently treated as same-state.
    states_known = items['seller_state'].notna() & items['customer_state'].notna()
    items['interstate'] = np.where(states_known,
                                  items['seller_state'] != items['customer_state'], np.nan)
    item_summary = items.groupby('order_id', sort=False).agg(
        item_count=('order_item_id', 'size'),
        seller_count=('seller_id', 'nunique'),
        product_count=('product_id', 'nunique'),
        total_price=('price', lambda values: values.sum(min_count=1)),
        total_freight_value=('freight_value', lambda values: values.sum(min_count=1)),
        product_weight_g_mean=('product_weight_g', 'mean'),
        product_volume_cm3_mean=('product_volume_cm3', 'mean'),
        interstate_item_ratio=('interstate', 'mean'),
    ).reset_index()
    primary_items = items.sort_values(
        ['order_id', 'price', 'order_item_id'], ascending=[True, False, True],
        na_position='last',
    ).drop_duplicates('order_id')[['order_id', 'seller_state', 'product_category_name']]
    primary_items = primary_items.rename(columns={
        'seller_state': 'primary_seller_state', 'product_category_name': 'primary_category',
    })
    result = base.merge(item_summary, on='order_id', how='left', validate='one_to_one')
    result = result.merge(primary_items, on='order_id', how='left', validate='one_to_one')

    payments = tables['order_payments'].copy()
    payment_summary = payments.groupby('order_id', sort=False).agg(
        payment_total=('payment_value', lambda values: values.sum(min_count=1)),
        payment_count=('payment_sequential', 'size'),
        payment_installments_max=('payment_installments', 'max'),
    ).reset_index()
    primary_payments = payments.sort_values(
        ['order_id', 'payment_value', 'payment_sequential'], ascending=[True, False, True],
        na_position='last',
    ).drop_duplicates('order_id')[['order_id', 'payment_type']]
    result = result.merge(payment_summary, on='order_id', how='left', validate='one_to_one')
    result = result.merge(primary_payments, on='order_id', how='left', validate='one_to_one')

    result['freight_ratio'] = result['total_freight_value'].div(
        result['total_price'].replace(0, np.nan))
    result['estimated_delivery_days'] = (
        result['order_estimated_delivery_date'].dt.normalize() -
        result['prediction_time'].dt.normalize()).dt.days
    result['approval_wait_hours'] = (
        result['prediction_time'] - result['order_purchase_timestamp']).dt.total_seconds() / 3600
    result['purchase_month'] = result['order_purchase_timestamp'].dt.month
    result['purchase_dayofweek'] = result['order_purchase_timestamp'].dt.dayofweek
    result['purchase_hour'] = result['order_purchase_timestamp'].dt.hour
    for column in CATEGORICAL_FEATURES:
        # sklearn's default missing-value marker is np.nan, not pandas.NA.
        result[column] = result[column].astype(object).where(result[column].notna(), np.nan)
    result[NUMERIC_FEATURES] = result[NUMERIC_FEATURES].astype(float).replace(
        [np.inf, -np.inf], np.nan)
    return result[['order_id', 'order_purchase_timestamp', 'prediction_time'] + FEATURES]


def add_delay_target(features: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Label completed orders by delivery calendar date, and reject bad timelines."""
    outcomes = orders[['order_id', 'order_status', 'order_delivered_customer_date',
                       'order_estimated_delivery_date']].copy()
    for column in ['order_delivered_customer_date', 'order_estimated_delivery_date']:
        outcomes[column] = pd.to_datetime(outcomes[column], errors='coerce')
    frame = features.merge(outcomes, on='order_id', how='left', validate='one_to_one')
    dates = ['order_purchase_timestamp', 'prediction_time',
             'order_delivered_customer_date', 'order_estimated_delivery_date']
    valid = (frame['order_status'].eq('delivered') & frame[dates].notna().all(axis=1) &
             frame['prediction_time'].ge(frame['order_purchase_timestamp']) &
             frame['order_delivered_customer_date'].ge(frame['prediction_time']) &
             frame['order_estimated_delivery_date'].dt.normalize().ge(
                 frame['prediction_time'].dt.normalize()))
    frame = frame.loc[valid].copy()
    frame['delayed'] = (frame['order_delivered_customer_date'].dt.normalize() >
                        frame['order_estimated_delivery_date'].dt.normalize()).astype(int)
    frame['label_available_time'] = frame['order_delivered_customer_date']
    return frame[['order_id', 'order_purchase_timestamp', 'prediction_time',
                  'label_available_time', 'delayed'] + FEATURES].reset_index(drop=True)


def build_delay_dataset(raw_dir: Path) -> pd.DataFrame:
    """Create the labeled historical dataset without exposing outcomes in X."""
    tables = load_olist_tables(raw_dir)
    return add_delay_target(build_order_features(tables), tables['orders'])
