"""Hand-computed as-of carrier windows, sparse support and pure inference."""
import copy
import unittest

import numpy as np
import pandas as pd

from scripts import delay_handover_features as features
from scripts.delay_backlog_features import build_backlog_order_features, feature_columns
from tests.test_delay_budget_features import tiny_tables


NOW = pd.Timestamp('2020-04-01 12:00')


def event(order_id, carrier, hours, seller='seller'):
    carrier = pd.Timestamp(carrier)
    approval = carrier - pd.Timedelta(hours=hours)
    return {
        'order_id': order_id, 'order_purchase_timestamp': approval - pd.Timedelta(hours=1),
        'order_approved_at': approval, 'order_delivered_carrier_date': carrier,
        'order_delivered_customer_date': pd.NaT, 'seller': seller,
    }


def source(rows, query_sellers=None):
    query_sellers = {'query': 'seller'} if query_sellers is None else query_sellers
    rows = copy.deepcopy(rows)
    items = [dict(order_id=row['order_id'], order_item_id=1, price=10., seller_id=row.pop('seller'))
             for row in rows]
    existing = {row['order_id'] for row in rows}
    for order_id, seller in query_sellers.items():
        if order_id not in existing:
            rows.append({'order_id': order_id, 'order_purchase_timestamp': NOW-pd.Timedelta(hours=1),
                         'order_approved_at': NOW, 'order_delivered_carrier_date': pd.NaT,
                         'order_delivered_customer_date': pd.NaT})
            items.append(dict(order_id=order_id, order_item_id=1, price=10., seller_id=seller))
    return {'orders': pd.DataFrame(rows), 'order_items': pd.DataFrame(items)}


def query(times=None, ids=None):
    times = [NOW] if times is None else times
    ids = [f'query-{i}' for i in range(len(times))] if ids is None else ids
    return pd.DataFrame({'order_id': ids, 'prediction_time': pd.to_datetime(times)})


class HandoverFeaturesTests(unittest.TestCase):
    def test_carrier_window_is_left_inclusive_right_strict_at_nanosecond_resolution(self):
        stamps = [NOW-pd.Timedelta(days=90)-pd.Timedelta(nanoseconds=1),
                  NOW-pd.Timedelta(days=90), NOW-pd.Timedelta(days=45),
                  NOW-pd.Timedelta(nanoseconds=1), NOW, NOW+pd.Timedelta(nanoseconds=1)]
        tables = source([event(str(i), stamp, i+1) for i, stamp in enumerate(stamps)])
        actual = features.add_handover_features(query(ids=['query']), tables).iloc[0]
        self.assertEqual(actual.seller_handover_count_90d, 3)
        self.assertTrue(actual[features.ADDED_FEATURES[1:]].isna().all())

    def test_five_event_linear_quantiles_use_fractional_hours_and_keep_zero(self):
        hours = [0., .5, 2., 5., 100.]
        tables = source([event(str(i), NOW-pd.Timedelta(days=i+1), value)
                         for i, value in enumerate(hours)])
        actual = features.add_handover_features(query(ids=['query']), tables).iloc[0]
        self.assertEqual(actual.seller_handover_count_90d, 5)
        self.assertEqual(actual.seller_handover_p50_hours_90d, 2.)
        self.assertAlmostEqual(actual.seller_handover_p90_hours_90d, 62.)

    def test_four_events_keep_count_and_missing_both_duration_features(self):
        tables = source([event(str(i), NOW-pd.Timedelta(days=i+1), i+.25) for i in range(4)])
        actual = features.add_handover_features(query(ids=['query']), tables).iloc[0]
        self.assertEqual(actual.seller_handover_count_90d, 4)
        self.assertTrue(actual[features.ADDED_FEATURES[1:]].isna().all())

    def test_each_query_has_own_window_and_equal_carrier_ties_never_leak(self):
        tables = source([event(str(i), NOW, 1.) for i in range(5)],
                        {'query-0': 'seller', 'query-1': 'seller', 'query-2': 'seller'})
        actual = features.add_handover_features(query([NOW, NOW+pd.Timedelta(nanoseconds=1),
                                                      NOW+pd.Timedelta(days=90, nanoseconds=1)]), tables)
        self.assertEqual(actual.seller_handover_count_90d.tolist(), [0., 5., 0.])
        self.assertTrue(actual.iloc[0][features.ADDED_FEATURES[1:]].isna().all())
        self.assertEqual(actual.iloc[1].seller_handover_p90_hours_90d, 1.)

    def test_missing_sellers_never_pool_and_are_distinct_from_new_known_sellers(self):
        rows = [event(str(i), NOW-pd.Timedelta(days=1), i, None) for i in range(6)]
        tables = source(rows, {'query-0': None, 'query-1': 'new_seller', 'query-2': 'missing'})
        actual = features.add_handover_features(query([NOW]*3), tables)
        self.assertEqual(actual.seller_handover_count_90d.tolist(), [0., 0., 0.])
        self.assertTrue(actual[features.ADDED_FEATURES[1:]].isna().all(axis=None))

    def test_current_order_identity_is_excluded_even_for_external_bad_query_clock(self):
        rows = [event(str(i), NOW-pd.Timedelta(days=1), i) for i in range(5)]
        rows.append(event('self', NOW-pd.Timedelta(days=1), 100.))
        tables = source(rows, {'self': 'seller'})
        actual = features.add_handover_features(query(ids=['self']), tables).iloc[0]
        self.assertEqual(actual.seller_handover_count_90d, 5.)
        self.assertEqual(actual.seller_handover_p50_hours_90d, 2.)
        self.assertEqual(actual.seller_handover_p90_hours_90d, 3.6)

    def test_primary_seller_matches_price_then_item_sequence_and_does_not_weight_items(self):
        tables = source([event(str(i), NOW-pd.Timedelta(days=1), i) for i in range(5)])
        extras = [dict(order_id='query', order_item_id=2, price=20., seller_id='winner'),
                  dict(order_id='query', order_item_id=3, price=20., seller_id='seller')]
        tables['order_items'] = pd.concat([tables['order_items'], pd.DataFrame(extras)], ignore_index=True)
        result = features.add_handover_features(query(ids=['query']), tables).iloc[0]
        self.assertEqual(result.seller_handover_count_90d, 0.)
        tables['order_items'].loc[tables['order_items'].order_id.eq('query') &
                                  tables['order_items'].order_item_id.eq(2), 'seller_id'] = 'seller'
        result = features.add_handover_features(query(ids=['query']), tables).iloc[0]
        self.assertEqual(result.seller_handover_count_90d, 5.)

    def test_invalid_clocks_and_known_delivery_contradiction_are_excluded_not_clipped(self):
        rows = [event(str(i), NOW-pd.Timedelta(days=1), i) for i in range(5)]
        bad = [event('approval_bad', NOW-pd.Timedelta(days=1), 2),
               event('carrier_bad', NOW-pd.Timedelta(days=1), -1),
               event('delivery_bad', NOW-pd.Timedelta(days=1), 2)]
        bad[0]['order_purchase_timestamp'] = bad[0]['order_approved_at']+pd.Timedelta(seconds=1)
        bad[2]['order_delivered_customer_date'] = bad[2]['order_delivered_carrier_date']-pd.Timedelta(seconds=1)
        tables = source(rows+bad)
        result = features.add_handover_features(query(ids=['query']), tables).iloc[0]
        self.assertEqual(result.seller_handover_count_90d, 5.)
        self.assertEqual(result.seller_handover_p50_hours_90d, 2.)
        counts = features.handover_event_diagnostics(tables)
        self.assertEqual(counts['approval_before_purchase'], 1)
        self.assertEqual(counts['carrier_before_approval'], 1)
        self.assertEqual(counts['delivery_before_carrier'], 1)
        self.assertEqual(counts['valid_handover_events'], 5)
        self.assertEqual(counts['valid_events_with_missing_delivery'], 5)

    def test_future_mutations_and_final_status_labels_do_not_change_any_feature(self):
        rows = [event(str(i), NOW-pd.Timedelta(days=1), i) for i in range(5)]
        rows.append(event('future', NOW+pd.Timedelta(days=10), 100.))
        tables = source(rows)
        original = features.add_handover_features(query(ids=['query']), tables)
        future = copy.deepcopy(tables)
        future['orders']['order_delivered_customer_date'] = NOW+pd.Timedelta(days=100)
        future['orders']['order_status'] = 'canceled'
        future['orders']['delayed'] = 'forbidden'
        future['orders']['order_estimated_delivery_date'] = 'not a date'
        future['orders'].loc[future['orders'].order_id.eq('future'), 'order_delivered_carrier_date'] = NOW+pd.Timedelta(days=20)
        actual = features.add_handover_features(query(ids=['query']), future)
        pd.testing.assert_frame_equal(original, actual)
        # Entirely dropping status/target/promise is also supported.
        pd.testing.assert_frame_equal(actual, features.add_handover_features(query(ids=['query']), tables))

    def test_frame_index_order_values_dtypes_and_sources_are_preserved(self):
        tables = source([event(str(i), NOW-pd.Timedelta(days=1), i) for i in range(5)],
                        {'query-0': 'seller', 'query-1': 'seller', 'query-2': 'seller'})
        frame = query([NOW]*3).iloc[[2, 0, 1]].copy()
        frame.index = pd.Index([7, 2, 2], name='duplicate_index')
        frame['opaque'] = pd.Series(['one', 'two', 'three'], index=frame.index, dtype=object)
        frame['primary_seller_id'] = 'preserve_raw_metadata'
        expected_frame, expected_tables = frame.copy(deep=True), copy.deepcopy(tables)
        actual = features.add_handover_features(frame, tables)
        pd.testing.assert_frame_equal(actual[frame.columns], expected_frame)
        pd.testing.assert_frame_equal(frame, expected_frame)
        self.assertEqual(actual.columns.tolist(), frame.columns.tolist()+features.ADDED_FEATURES)
        for name in tables:
            pd.testing.assert_frame_equal(tables[name], expected_tables[name])

    def test_missing_query_time_stays_unknown_and_empty_frame_is_supported(self):
        tables = source([event(str(i), NOW-pd.Timedelta(days=1), i) for i in range(5)])
        actual = features.add_handover_features(query([pd.NaT], ids=['query']), tables)
        self.assertTrue(actual[features.ADDED_FEATURES].isna().all(axis=None))
        empty = features.add_handover_features(query(ids=['query']).iloc[:0], tables)
        self.assertEqual(empty.shape, (0, 5))

    def test_duplicate_ids_existing_columns_bad_schema_and_zoned_clocks_are_rejected(self):
        tables = source([event('event', NOW-pd.Timedelta(days=1), 2)])
        data = query(ids=['query'])
        invalid = [data.assign(order_id=None), data.assign(order_id=''),
                   pd.concat([data, data], ignore_index=True), data.drop(columns='prediction_time'),
                   data.assign(seller_handover_count_90d=0),
                   data.assign(prediction_time=NOW.tz_localize('UTC'))]
        for value in invalid:
            with self.subTest(columns=value.columns.tolist()), self.assertRaises(ValueError):
                features.add_handover_features(value, tables)
        raw_bad = copy.deepcopy(tables)
        raw_bad['orders'] = pd.concat([raw_bad['orders'], raw_bad['orders'].iloc[:1]])
        with self.assertRaises(ValueError):
            features.add_handover_features(data, raw_bad)
        raw_bad = copy.deepcopy(tables)
        raw_bad['order_items'] = pd.concat([raw_bad['order_items'], raw_bad['order_items'].iloc[:1]])
        with self.assertRaises(ValueError):
            features.add_handover_features(data, raw_bad)

    def test_pure_raw_inference_builder_extends_real_backlog_builder_and_nothing_else(self):
        tables = tiny_tables()
        tables['orders']['order_delivered_carrier_date'] = (
            pd.to_datetime(tables['orders'].order_approved_at) + pd.Timedelta(hours=6))
        tables['customers']['customer_zip_code_prefix'] = 1040
        tables['sellers']['seller_zip_code_prefix'] = 1040
        geo = pd.DataFrame({'geolocation_zip_code_prefix': [1040],
                            'geolocation_lat': [-23.], 'geolocation_lng': [-46.]})
        baseline = build_backlog_order_features(tables, 'geo', '7_14d', geo)
        expected = features.add_handover_features(baseline, tables)
        actual = features.build_handover_order_features(tables, geo)
        numeric, categorical = features.feature_columns()
        pd.testing.assert_frame_equal(actual, expected[
            ['order_id', 'order_purchase_timestamp', 'prediction_time']+numeric+categorical])
        old_numeric, old_categorical = feature_columns('geo', '7_14d')
        self.assertEqual(numeric, old_numeric+features.ADDED_FEATURES)
        self.assertEqual(categorical, old_categorical)
        self.assertEqual((len(numeric), len(categorical)), (96, 8))
        with self.assertRaises(ValueError):
            features.build_handover_order_features(tables)


if __name__ == '__main__':
    unittest.main()
