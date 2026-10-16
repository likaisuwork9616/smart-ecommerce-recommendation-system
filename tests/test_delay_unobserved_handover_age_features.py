"""Age-only feature tests for approval-time knowledge and quantile boundaries."""
from io import StringIO
import unittest

import numpy as np
import pandas as pd

from scripts.delay_unobserved_handover_age_features import (
    ADDED_FEATURES, add_unobserved_handover_age, feature_contract,
    pending_age_p90, read_feature_cache,
)

AGE = ADDED_FEATURES[0]


class UnobservedHandoverAgeTests(unittest.TestCase):
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
        query = pd.DataFrame({'order_id': [query_id], 'prediction_time': [query_time]})
        return pending_age_p90(query, orders, items)

    def test_returns_only_age_not_pending_count_or_completed_quantiles(self):
        self.assertEqual(ADDED_FEATURES, ('seller_unobserved_handover_pending_age_p90_hours_90d',))
        result = self.calculate([['history', '2018-03-30', '2018-03-30', None, None]])
        self.assertEqual(list(result), ['order_id', 'prediction_time', AGE])
        contract = feature_contract()
        self.assertEqual(contract['added_features'], list(ADDED_FEATURES))
        self.assertEqual(contract['minimum_pending_observations'], 1)
        self.assertEqual(contract['quantile_method'], 'linear')

    def test_single_pending_order_is_observed_without_five_event_threshold(self):
        result = self.calculate([['single', '2018-03-31', '2018-03-31', None, None]])
        self.assertEqual(result[AGE].iloc[0], 24.)

    def test_linear_quantile_uses_approval_age_hours(self):
        result = self.calculate([
            ['one', '2018-03-27', '2018-03-29', None, None],
            ['two', '2018-03-29', '2018-03-30', None, None],
            ['three', '2018-03-30', '2018-03-31', None, None],
        ])
        self.assertAlmostEqual(result[AGE].iloc[0], 67.2)

    def test_closed_90_day_lower_open_approval_upper_bounds(self):
        result = self.calculate([
            ['lower', '2018-01-01', '2018-01-01', None, None],
            ['too_old', '2017-12-31 23:59:59', '2017-12-31 23:59:59', None, None],
            ['same', '2018-04-01', '2018-04-01', None, None],
            ['future', '2018-04-02', '2018-04-02', None, None],
        ])
        self.assertEqual(result[AGE].iloc[0], 2160.)

    def test_equal_query_events_unknown_but_past_events_exclude(self):
        result = self.calculate([
            ['equal_carrier', '2018-03-31', '2018-03-31', '2018-04-01', None],
            ['past_carrier', '2018-03-30', '2018-03-30', '2018-03-31 23:59:59', None],
            ['equal_delivery', '2018-03-30', '2018-03-30', None, '2018-04-01'],
            ['past_delivery', '2018-03-29', '2018-03-29', None, '2018-03-31 23:59:59'],
        ])
        self.assertAlmostEqual(result[AGE].iloc[0], 45.6)

    def test_current_identity_excluded_independently_of_raw_approval_clock(self):
        result = self.calculate([
            ['query', '2018-03-01', '2018-03-01', None, None],
            ['other', '2018-03-31', '2018-03-31', None, None],
        ])
        self.assertEqual(result[AGE].iloc[0], 24.)

    def test_invalid_purchase_approval_cannot_enter_age_quantile(self):
        result = self.calculate([
            ['bad', '2018-03-31', '2018-03-01', None, None],
            ['missing_purchase', None, '2018-03-01', None, None],
            ['missing_approval', '2018-03-01', None, None, None],
            ['valid', '2018-03-31', '2018-03-31', None, None],
        ])
        self.assertEqual(result[AGE].iloc[0], 24.)

    def test_future_milestone_contradictions_are_counterfactually_irrelevant(self):
        future = self.calculate([
            ['one', '2018-03-30', '2018-03-30', '2018-04-05', '2018-04-04'],
            ['two', '2018-03-31', '2018-03-31', '2018-05-01', '2018-06-01'],
        ])
        missing = self.calculate([
            ['one', '2018-03-30', '2018-03-30', None, None],
            ['two', '2018-03-31', '2018-03-31', None, None],
        ])
        pd.testing.assert_frame_equal(future, missing)
        self.assertAlmostEqual(future[AGE].iloc[0], 45.6)

    def test_observed_contradictions_and_delivery_without_carrier_exclude(self):
        result = self.calculate([
            ['bad_carrier', '2018-03-30', '2018-03-30', '2018-03-29', None],
            ['bad_delivery', '2018-03-30', '2018-03-30', None, '2018-03-29'],
            ['bad_both', '2018-03-28', '2018-03-28', '2018-03-30', '2018-03-29'],
            ['no_seen_carrier', '2018-03-28', '2018-03-28', '2018-04-03', '2018-03-29'],
            ['valid', '2018-03-31', '2018-03-31', None, None],
        ])
        self.assertEqual(result[AGE].iloc[0], 24.)

    def test_status_labels_and_shipping_limit_unused(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['query', 1, 10., 'seller']
        query = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        expected = pending_age_p90(query, orders, items)
        orders['order_status'], orders['delayed'] = 'canceled', 1
        orders['label_available_time'] = '2018-01-01'
        items['shipping_limit_date'] = '2017-01-01'
        pd.testing.assert_frame_equal(expected, pending_age_p90(query, orders, items))

    def test_known_empty_and_unknown_sellers_are_both_missing_but_quality_separate(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', '2018-03-31', None]])
        items.loc[len(items)] = ['known', 1, 10., 'seller']
        items.loc[len(items)] = ['unknown', 1, 10., None]
        query = pd.DataFrame({'order_id': ['known', 'unknown', 'no_items'], 'prediction_time': ['2018-04-01'] * 3})
        augmented, quality = add_unobserved_handover_age(query, orders, items)
        self.assertTrue(augmented[AGE].isna().all())
        self.assertEqual(quality['missing_seller_queries'], 2)
        self.assertEqual(quality['known_seller_without_pending_queries'], 1)
        self.assertEqual(quality['age_missing_queries'], 3)
        self.assertFalse(quality['pending_count_exported_as_feature'])

    def test_unknown_sellers_do_not_pool_pending_orders(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items['seller_id'] = None
        items.loc[len(items)] = ['query', 1, 10., None]
        query = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        self.assertTrue(pending_age_p90(query, orders, items)[AGE].isna().all())

    def test_known_seller_without_history_remains_missing(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['query', 1, 10., 'other_seller']
        query = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        output, quality = add_unobserved_handover_age(query, orders, items)
        self.assertTrue(output[AGE].isna().all())
        self.assertEqual(quality['known_seller_without_pending_queries'], 1)

    def test_primary_seller_price_then_item_sequence(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['history', 2, 20., 'chosen']
        items.loc[len(items)] = ['history', 3, 20., 'tie_loses']
        items.loc[len(items)] = ['query', 1, 5., 'chosen']
        query = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        self.assertEqual(pending_age_p90(query, orders, items)[AGE].iloc[0], 48.)

    def test_append_preserves_original_values_order_index_and_inputs(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        for query_id in ('later', 'earlier'):
            items.loc[len(items)] = [query_id, 1, 1., 'seller']
        query = pd.DataFrame({'order_id': ['later', 'earlier'], 'prediction_time': ['2018-04-01', '2018-03-29'],
                              'original_float': [0.12345678901234567, np.nan],
                              'original_category': pd.Categorical(['x', 'y']), 'delayed': [0, 1]}, index=[9, 2])
        snapshot, order_snapshot, item_snapshot = query.copy(deep=True), orders.copy(deep=True), items.copy(deep=True)
        result, _ = add_unobserved_handover_age(query, orders, items)
        pd.testing.assert_frame_equal(result[list(query.columns)], snapshot, check_exact=True)
        pd.testing.assert_frame_equal(query, snapshot, check_exact=True)
        pd.testing.assert_frame_equal(orders, order_snapshot, check_exact=True)
        pd.testing.assert_frame_equal(items, item_snapshot, check_exact=True)
        self.assertEqual(list(result), [*query.columns, AGE])
        self.assertEqual(result[AGE].iloc[0], 48.)
        self.assertTrue(pd.isna(result[AGE].iloc[1]))

    def test_csv_round_trip_preserves_zip_leading_zeroes_and_missing_age(self):
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['query', 1, 10., 'seller']
        source = StringIO('order_id,prediction_time,customer_zip_prefix3,primary_seller_zip_prefix3,state_route_promise_bin,state_route_promise_growth_bin,value\n'
                          'query,2018-04-01,012,001,SP_RJ_long,SP_RJ_long_stable,0.12345678901234567\n'
                          'unknown,2018-04-01,001,002,SP_SP_short,SP_SP_short_stable,1.0\n')
        dataset = read_feature_cache(source)
        self.assertEqual(dataset.customer_zip_prefix3.tolist(), ['012', '001'])
        self.assertEqual(dataset.primary_seller_zip_prefix3.tolist(), ['001', '002'])
        result, _ = add_unobserved_handover_age(dataset, orders, items)
        restored = read_feature_cache(StringIO(result.to_csv(index=False)))
        pd.testing.assert_frame_equal(restored[list(dataset.columns)], dataset, check_exact=True)
        pd.testing.assert_series_equal(restored[AGE], result[AGE], check_exact=True)

    def test_invalid_query_cutoff_timezone_duplicates_and_existing_column_rejected(self):
        for value in [None, 'invalid', '2018-05-01', '2018-04-01T00:00:00Z']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.calculate([['history', '2018-03-30', '2018-03-30', None, None]], query_time=value)
        orders, items = self.sources([['history', '2018-03-30', '2018-03-30', None, None]])
        query = pd.DataFrame({'order_id': ['history'], 'prediction_time': ['2018-04-01']})
        with self.assertRaises(ValueError):
            pending_age_p90(pd.concat([query, query]), orders, items)
        with self.assertRaises(ValueError):
            pending_age_p90(query, pd.concat([orders, orders]), items)
        query[AGE] = 1.
        with self.assertRaises(ValueError):
            add_unobserved_handover_age(query, orders, items)


if __name__ == '__main__':
    unittest.main()
