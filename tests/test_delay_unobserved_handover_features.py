"""Point-in-time boundaries for the single unobserved-handover count feature."""
import unittest
from io import StringIO

import numpy as np
import pandas as pd

from scripts.delay_unobserved_handover_features import (
    ADDED_FEATURES, add_unobserved_handover_count, feature_contract, pending_count,
    read_feature_cache,
)

COUNT = ADDED_FEATURES[0]


class UnobservedHandoverCountTests(unittest.TestCase):
    def sources(self, rows):
        orders = pd.DataFrame(rows, columns=['order_id', 'order_purchase_timestamp', 'order_approved_at',
                                            'order_delivered_carrier_date', 'order_delivered_customer_date'])
        items = pd.DataFrame({'order_id': orders.order_id, 'order_item_id': 1,
                              'price': 10., 'seller_id': 'seller'})
        return orders, items

    def calculate(self, rows, *, query_time='2018-04-01', query_id='query', known_seller=True):
        orders, items = self.sources(rows)
        if known_seller and query_id not in set(items.order_id):
            items.loc[len(items)] = [query_id, 1, 10., 'seller']
        queries = pd.DataFrame({'order_id': [query_id], 'prediction_time': [query_time]})
        return pending_count(queries, orders, items)

    def test_exactly_one_feature_and_no_age_or_completed_count(self):
        self.assertEqual(ADDED_FEATURES, ('seller_unobserved_handover_pending_count_90d',))
        result = self.calculate([['history', '2018-03-30', '2018-03-30', None, None]])
        self.assertEqual(list(result), ['order_id', 'prediction_time', COUNT])
        self.assertEqual(feature_contract()['added_features'], list(ADDED_FEATURES))

    def test_closed_90_day_lower_and_open_approval_upper_boundary(self):
        result = self.calculate([
            ['lower', '2018-01-01', '2018-01-01', None, None],
            ['one_second_older', '2017-12-31 23:59:59', '2017-12-31 23:59:59', None, None],
            ['equal_approval', '2018-04-01', '2018-04-01', None, None],
            ['future_approval', '2018-04-02', '2018-04-02', None, None],
        ])
        self.assertEqual(result[COUNT].iloc[0], 1.)

    def test_physical_events_strictly_before_query_only(self):
        result = self.calculate([
            ['equal_carrier', '2018-03-30', '2018-03-30', '2018-04-01', None],
            ['past_carrier', '2018-03-30', '2018-03-30', '2018-03-31 23:59:59', None],
            ['equal_delivery', '2018-03-30', '2018-03-30', None, '2018-04-01'],
            ['past_delivery', '2018-03-30', '2018-03-30', None, '2018-03-31 23:59:59'],
        ])
        self.assertEqual(result[COUNT].iloc[0], 2.)

    def test_current_identity_excluded_even_with_earlier_raw_approval(self):
        result = self.calculate([
            ['query', '2018-03-30', '2018-03-30', None, None],
            ['other', '2018-03-31', '2018-03-31', None, None],
        ])
        self.assertEqual(result[COUNT].iloc[0], 1.)

    def test_invalid_or_missing_purchase_approval_not_history(self):
        result = self.calculate([
            ['bad', '2018-03-31', '2018-03-29', None, None],
            ['no_purchase', None, '2018-03-29', None, None],
            ['no_approval', '2018-03-29', None, None, None],
            ['equal_valid', '2018-03-30', '2018-03-30', None, None],
        ])
        self.assertEqual(result[COUNT].iloc[0], 1.)

    def test_future_events_and_future_contradictions_cannot_change_count(self):
        future = self.calculate([
            ['one', '2018-03-30', '2018-03-30', '2018-04-05', '2018-04-04'],
            ['two', '2018-03-30', '2018-03-30', '2018-05-01', '2018-06-01'],
        ])
        missing = self.calculate([
            ['one', '2018-03-30', '2018-03-30', None, None],
            ['two', '2018-03-30', '2018-03-30', None, None],
        ])
        pd.testing.assert_frame_equal(future, missing)
        self.assertEqual(future[COUNT].iloc[0], 2.)

    def test_observed_contradictions_and_delivery_without_carrier_excluded(self):
        result = self.calculate([
            ['carrier_before_approval', '2018-03-30', '2018-03-30', '2018-03-29', None],
            ['delivery_before_approval', '2018-03-30', '2018-03-30', None, '2018-03-29'],
            ['delivery_before_carrier', '2018-03-28', '2018-03-28', '2018-03-30', '2018-03-29'],
            ['delivery_no_seen_carrier', '2018-03-28', '2018-03-28', '2018-04-03', '2018-03-29'],
            ['pending', '2018-03-31', '2018-03-31', None, None],
        ])
        self.assertEqual(result[COUNT].iloc[0], 1.)

    def test_final_status_targets_and_deadlines_unused(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['query', 1, 10., 'seller']
        query = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        original = pending_count(query, orders, items)
        orders['order_status'] = 'canceled'
        orders['is_delayed'] = 1
        orders['label_available_time'] = '2018-01-01'
        items['shipping_limit_date'] = '2017-01-01'
        pd.testing.assert_frame_equal(original, pending_count(query, orders, items))

    def test_unknown_sellers_are_missing_and_never_pooled(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items['seller_id'] = None
        items.loc[len(items)] = ['query', 1, 10., None]
        queries = pd.DataFrame({'order_id': ['query', 'no_items'], 'prediction_time': ['2018-04-01'] * 2})
        self.assertTrue(pending_count(queries, orders, items)[COUNT].isna().all())

    def test_known_seller_without_pending_or_any_history_is_zero(self):
        result = self.calculate([['history', '2018-03-30', '2018-03-30', '2018-03-31', None]])
        self.assertEqual(result[COUNT].iloc[0], 0.)
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['query', 1, 10., 'different_seller']
        query = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        self.assertEqual(pending_count(query, orders, items)[COUNT].iloc[0], 0.)

    def test_primary_seller_price_and_item_sequence_tie_rule(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['history', 2, 20., 'chosen']
        items.loc[len(items)] = ['history', 3, 20., 'tie_loses']
        items.loc[len(items)] = ['query', 1, 5., 'chosen']
        query = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        self.assertEqual(pending_count(query, orders, items)[COUNT].iloc[0], 1.)

    def test_query_order_and_existing_columns_index_dtypes_unchanged(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['later', 1, 1., 'seller']
        items.loc[len(items)] = ['earlier', 1, 1., 'seller']
        dataset = pd.DataFrame({'order_id': ['later', 'earlier'],
                                'prediction_time': ['2018-04-01', '2018-03-29'],
                                'existing_float': [np.nan, 0.12345678901234567],
                                'existing_category': pd.Categorical(['x', 'y']),
                                'is_delayed': [1, 0]}, index=[19, 7])
        snapshot, raw_snapshot, items_snapshot = dataset.copy(deep=True), orders.copy(deep=True), items.copy(deep=True)
        augmented, quality = add_unobserved_handover_count(dataset, orders, items)
        pd.testing.assert_frame_equal(augmented[list(dataset.columns)], snapshot, check_exact=True)
        pd.testing.assert_frame_equal(dataset, snapshot, check_exact=True)
        pd.testing.assert_frame_equal(orders, raw_snapshot, check_exact=True)
        pd.testing.assert_frame_equal(items, items_snapshot, check_exact=True)
        self.assertEqual(list(augmented), [*dataset.columns, COUNT])
        self.assertEqual(augmented[COUNT].tolist(), [1., 0.])
        self.assertEqual(quality['query_history_occurrences'], 1)

    def test_rejects_invalid_query_times_cutoff_and_timezone(self):
        for value in ['invalid', None, '2018-05-01', '2018-04-01T00:00:00Z']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.calculate([['history', '2018-03-30', '2018-03-30', None, None]], query_time=value)

    def test_csv_roundtrip_preserves_categorical_zip_leading_zeroes(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['query', 1, 10., 'seller']
        source = StringIO('order_id,prediction_time,customer_zip_prefix3,primary_seller_zip_prefix3,state_route_promise_bin,state_route_promise_growth_bin,value\n'
                          'query,2018-04-01,012,001,SP_RJ_long,SP_RJ_long_stable,0.12345678901234567\n')
        dataset = read_feature_cache(source)
        self.assertEqual(dataset.customer_zip_prefix3.iloc[0], '012')
        self.assertEqual(dataset.primary_seller_zip_prefix3.iloc[0], '001')
        augmented, _ = add_unobserved_handover_count(dataset, orders, items)
        output = StringIO()
        augmented.to_csv(output, index=False)
        output.seek(0)
        restored = read_feature_cache(output)
        pd.testing.assert_frame_equal(restored[list(dataset.columns)], dataset, check_exact=True)
        self.assertEqual(restored.customer_zip_prefix3.iloc[0], '012')
        self.assertEqual(restored.primary_seller_zip_prefix3.iloc[0], '001')
        self.assertEqual(restored[COUNT].iloc[0], 1.)

    def test_rejects_duplicate_identities_and_existing_new_column(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        query = pd.DataFrame({'order_id': ['history'], 'prediction_time': ['2018-04-01']})
        with self.assertRaises(ValueError):
            pending_count(pd.concat([query, query]), orders, items)
        with self.assertRaises(ValueError):
            pending_count(query, pd.concat([orders, orders]), items)
        query[COUNT] = 1.
        with self.assertRaises(ValueError):
            add_unobserved_handover_count(query, orders, items)


if __name__ == '__main__':
    unittest.main()
