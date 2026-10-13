"""Hand-computed route/promise arrival windows and strict input contracts."""
import copy
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_index_equal

from scripts import delay_route_load_features as features
from scripts.delay_ablation_features import build_ablation_order_features
from scripts.delay_engineering_features import build_engineering_order_features
from tests.test_delay_budget_features import tiny_tables
from tests.test_delay_pending_features import pending_tables


def query(times, promises=24, *, seller='RJ', customer='SP'):
    stamps = [pd.Timestamp(value) for value in times]
    if np.isscalar(promises):
        promises = [promises] * len(stamps)
    return pd.DataFrame({
        'order_id': [f'query-{i}' for i in range(len(stamps))],
        'prediction_time': stamps, 'primary_seller_state': seller, 'customer_state': customer,
        'state_route': np.nan if seller is None or customer is None else f'{seller}->{customer}',
        'estimated_delivery_days': promises, 'route_promise_margin_p90_days': -6.,
        'route_overdue_pending_share_30d': .25,
    })


def raw_specs(stamps, promises=None, customer_states=None):
    promises = [24] * len(stamps) if promises is None else promises
    customer_states = ['SP'] * len(stamps) if customer_states is None else customer_states
    return [(f'raw-{i}', stamp, None,
             None if pd.isna(days) else pd.Timestamp(stamp).normalize() + pd.Timedelta(days=days),
             'canceled' if i % 2 else 'shipped', 'seller_a', state)
            for i, (stamp, days, state) in enumerate(zip(stamps, promises, customer_states, strict=True))]


class RouteLoadFeaturesTests(unittest.TestCase):
    def test_left_inclusive_right_exclusive_boundaries_and_same_time_ties(self):
        now = pd.Timestamp('2020-04-01 12:00')
        ns = pd.Timedelta(nanoseconds=1)
        stamps = [now-pd.Timedelta(days=28)-ns, now-pd.Timedelta(days=28),
                  now-pd.Timedelta(days=14)-ns, now-pd.Timedelta(days=14),
                  now-pd.Timedelta(days=7)-ns, now-pd.Timedelta(days=7),
                  now-ns, now, now, now+ns]
        result = features.add_route_load_features(query([now]), pending_tables(raw_specs(stamps))).iloc[0]
        for prefix in ('route', 'route_promise'):
            np.testing.assert_array_equal(result[[f'{prefix}_approvals_7d', f'{prefix}_approvals_previous_7d',
                                                  f'{prefix}_approvals_14d', f'{prefix}_approvals_previous_14d']],
                                          [2., 2., 4., 2.])
            self.assertEqual(result[f'{prefix}_approval_log_growth_7d'], 0)
            self.assertAlmostEqual(result[f'{prefix}_approval_log_growth_14d'], np.log(5/3))
        self.assertEqual(result.route_approval_share_change_7d, 0)
        self.assertEqual(result.state_route_promise_bin, 'RJ->SP|22-30')
        self.assertEqual(result.state_route_promise_growth_bin, 'RJ->SP|22-30|stable')

    def test_share_denominator_uses_all_approved_routes_and_cross_values_are_hand_computed(self):
        now = pd.Timestamp('2020-04-01')
        stamps = [now-pd.Timedelta(days=d) for d in (1, 2, 3, 4, 8, 9)]
        tables = pending_tables(raw_specs(stamps, [24, 24, 10, 24, 24, 24], ['SP', 'SP', 'SP', 'MG', 'SP', 'MG']))
        result = features.add_route_load_features(query([now]), tables).iloc[0]
        self.assertAlmostEqual(result.route_approval_log_growth_7d, np.log(4/2))
        self.assertAlmostEqual(result.route_promise_approval_log_growth_7d, np.log(3/2))
        self.assertAlmostEqual(result.route_approval_share_change_7d, 3/4-1/2)
        np.testing.assert_allclose(result[features.CROSS_NUMERIC_FEATURES].to_numpy(dtype=float),
                                   [24/30*np.log(2), 24/30*np.log(1.5), -6/30*np.log(2), 24/30*.25])
        self.assertEqual(result.state_route_promise_growth_bin, 'RJ->SP|22-30|increase')

    def test_all_approved_cancelled_unfinished_count_but_invalid_purchase_approval_do_not(self):
        now = pd.Timestamp('2020-04-01')
        tables = pending_tables(raw_specs([now-pd.Timedelta(days=1)] * 5))
        tables['orders']['order_status'] = ['canceled', 'shipped', 'delivered', 'approved', 'created']
        tables['orders'].loc[2, 'order_purchase_timestamp'] = now
        tables['orders'].loc[3, 'order_purchase_timestamp'] = pd.NaT
        tables['orders'].loc[4, 'order_approved_at'] = pd.NaT
        result = features.add_route_load_features(query([now]), tables).iloc[0]
        self.assertEqual(result.route_approvals_7d, 2)
        self.assertEqual(result.route_promise_approvals_7d, 2)

    def test_raw_invalid_promises_count_route_but_not_lane(self):
        now = pd.Timestamp('2020-04-01')
        tables = pending_tables(raw_specs([now-pd.Timedelta(days=1)] * 4, [24, 10, None, -1]))
        result = features.add_route_load_features(query([now]), tables).iloc[0]
        self.assertEqual(result.route_approvals_7d, 4)
        self.assertEqual(result.route_promise_approvals_7d, 1)
        query_invalid = query([now]*4, [np.nan, -1, 1.5, np.inf])
        result = features.add_route_load_features(query_invalid, tables)
        self.assertTrue(result.route_approvals_7d.eq(4).all())
        self.assertTrue(result[features.TREND_NUMERIC_FEATURES[7:]].isna().all(axis=None))
        self.assertTrue(result[features.CROSS_CATEGORICAL_FEATURES].isna().all(axis=None))
        self.assertTrue(result[['promise_x_route_growth_7d', 'promise_x_lane_growth_7d',
                                'promise_x_route_overdue_share_30d']].isna().all(axis=None))

    def test_fixed_promise_bins_and_growth_direction_boundaries(self):
        values = pd.Series([0, 7, 8, 14, 15, 21, 22, 30, 31, 999, -1, 7.5, np.nan, np.inf])
        result = features.promise_bins(values)
        self.assertEqual(result.iloc[:10].tolist(), ['0-7', '0-7', '8-14', '8-14',
                                                    '15-21', '15-21', '22-30', '22-30', '31+', '31+'])
        self.assertTrue(result.iloc[10:].isna().all())
        now = pd.Timestamp('2020-04-01')
        # The threshold ratios (recent+1)/(previous+1)=5/4 and 4/5 stay stable.
        for recent, previous, expected in ((4, 3, 'stable'), (3, 4, 'stable'),
                                           (5, 3, 'increase'), (2, 4, 'decrease')):
            stamps = [now-pd.Timedelta(days=1)]*recent + [now-pd.Timedelta(days=8)]*previous
            row = features.add_route_load_features(query([now]), pending_tables(raw_specs(stamps))).iloc[0]
            self.assertEqual(row.state_route_promise_growth_bin, f'RJ->SP|22-30|{expected}')

    def test_missing_route_is_not_pooled_and_no_history_has_zero_counts_growth(self):
        now = pd.Timestamp('2020-04-01')
        tables = pending_tables(raw_specs([now-pd.Timedelta(days=1)], customer_states=[None]))
        missing = features.add_route_load_features(query([now], customer=None), tables)
        self.assertTrue(missing[features.TREND_NUMERIC_FEATURES].isna().all(axis=None))
        self.assertTrue(missing[features.CROSS_CATEGORICAL_FEATURES].isna().all(axis=None))
        known = features.add_route_load_features(query([now]), tables).iloc[0]
        self.assertEqual(known.route_approvals_7d, 0)
        self.assertEqual(known.route_promise_approvals_7d, 0)
        self.assertEqual(known.route_approval_log_growth_7d, 0)
        self.assertEqual(known.route_promise_approval_log_growth_14d, 0)
        self.assertTrue(pd.isna(known.route_approval_share_change_7d))
        # A zero global denominator in either 7-day window makes change undefined.
        empty = copy.deepcopy(tables)
        empty['orders']['order_approved_at'] = pd.NaT
        row = features.add_route_load_features(query([now]), empty).iloc[0]
        self.assertEqual(row.route_approvals_14d, 0)
        self.assertEqual(row.route_approval_log_growth_14d, 0)
        self.assertTrue(pd.isna(row.route_approval_share_change_7d))

    def test_primary_seller_uses_highest_price_then_lowest_item_sequence(self):
        now = pd.Timestamp('2020-04-01')
        tables = pending_tables(raw_specs([now-pd.Timedelta(days=1)]))
        tables['sellers'] = pd.DataFrame({'seller_id': ['seller_a', 'seller_b', 'seller_c'],
                                         'seller_state': ['RJ', 'SP', 'MG']})
        tables['order_items'] = pd.DataFrame({'order_id': ['raw-0']*3, 'order_item_id': [3, 2, 1],
                                             'price': [15., 20., 20.],
                                             'seller_id': ['seller_a', 'seller_b', 'seller_c']})
        self.assertEqual(features.add_route_load_features(query([now], seller='MG'), tables).iloc[0].route_approvals_7d, 1)
        self.assertEqual(features.add_route_load_features(query([now], seller='SP'), tables).iloc[0].route_approvals_7d, 0)

    def test_future_append_delivery_status_and_target_corruption_cannot_change_new_features(self):
        now = pd.Timestamp('2020-04-01')
        tables = pending_tables(raw_specs([now-pd.Timedelta(days=2), now-pd.Timedelta(days=8)]))
        original_query = query([now])
        original_query['delayed'], original_query['label_available_time'] = 0, pd.Timestamp('2020-05-01')
        before = features.add_route_load_features(original_query, tables)[features.ADDED_FEATURES]
        tables['orders']['order_delivered_customer_date'] = 'invalid delivery'
        tables['orders']['order_status'] = 'invented future status'
        tables['orders']['delayed'] = 'corrupted target'
        future = pending_tables([('future', now+pd.Timedelta(days=1), None, now+pd.Timedelta(days=25),
                                  'canceled', 'seller_a', 'SP')])
        for name in ('orders', 'customers', 'order_items'):
            tables[name] = pd.concat([tables[name], future[name]], ignore_index=True)
        changed_query = original_query.copy()
        changed_query['delayed'], changed_query['label_available_time'] = 'corrupt', pd.Timestamp('1900-01-01')
        assert_frame_equal(before, features.add_route_load_features(changed_query, tables)[features.ADDED_FEATURES])
        tables['orders'] = tables['orders'].drop(columns=['order_delivered_customer_date', 'order_status', 'delayed'])
        assert_frame_equal(before, features.add_route_load_features(changed_query, tables)[features.ADDED_FEATURES])

    def test_original_values_column_order_and_duplicate_external_index_are_preserved(self):
        now = pd.Timestamp('2020-04-01')
        tables = pending_tables(raw_specs([now-pd.Timedelta(days=1)]))
        frame = query([now, now-pd.Timedelta(days=1), now+pd.Timedelta(days=1)])
        frame.index = pd.Index([7, 2, 7], name='external')
        frame['custom_metadata'] = ['001', None, 'third']
        before = frame.copy(deep=True)
        actual = features.add_route_load_features(frame, tables)
        assert_index_equal(actual.index, before.index)
        assert_frame_equal(actual[before.columns], before)
        assert_frame_equal(frame, before)
        self.assertEqual(list(actual), list(before) + features.ADDED_FEATURES)
        np.testing.assert_array_equal(actual.route_approvals_7d, [1, 0, 1])

    def test_counts_match_independent_brute_force_after_shuffle(self):
        rng = np.random.default_rng(75)
        origin = pd.Timestamp('2020-01-01')
        stamps = [origin + pd.Timedelta(hours=int(h)) for h in rng.integers(0, 24*90, 100)]
        days = rng.choice([7., 14., 24., 40., -1., np.nan], 100)
        states = rng.choice(['SP', 'MG', None], 100)
        tables = pending_tables(raw_specs(stamps, days, states))
        times = pd.date_range(origin, periods=30, freq='3D')
        current = query(times, promises=np.resize([7, 14, 24, 40], len(times)))
        actual = features.add_route_load_features(current, tables)
        raw = tables['orders'].set_index('order_id')
        approvals = pd.to_datetime(raw.order_approved_at)
        state_lookup = dict(zip(raw.index, states, strict=True))
        promise_lookup = dict(zip(raw.index, days, strict=True))
        for i, stamp in enumerate(times):
            row = actual.iloc[i]
            current_bin = features.promise_bins(pd.Series([current.iloc[i].estimated_delivery_days])).iloc[0]
            bin_lookup = features.promise_bins(pd.Series(promise_lookup))
            route = pd.Series(state_lookup).eq('SP')
            lane = route & bin_lookup.eq(current_bin)
            global_count = []
            for lower, upper, suffix in ((7, 0, '7d'), (14, 7, 'previous_7d'),
                                          (14, 0, '14d'), (28, 14, 'previous_14d')):
                mask = approvals.ge(stamp-pd.Timedelta(days=lower)) & approvals.lt(stamp-pd.Timedelta(days=upper))
                global_count.append(int(mask.sum()))
                self.assertEqual(row[f'route_approvals_{suffix}'], int((mask & route).sum()))
                self.assertEqual(row[f'route_promise_approvals_{suffix}'], int((mask & lane).sum()))
            expected = (row.route_approvals_7d/global_count[0] - row.route_approvals_previous_7d/global_count[1]
                        if global_count[0] and global_count[1] else np.nan)
            np.testing.assert_allclose(row.route_approval_share_change_7d, expected, equal_nan=True)
        shuffled = features.add_route_load_features(current.sample(frac=1, random_state=5),
                                                    {**tables, 'orders': tables['orders'].sample(frac=1, random_state=8)})
        assert_frame_equal(actual.set_index('order_id').sort_index(), shuffled.set_index('order_id').sort_index())

    def test_input_contracts_exclude_labels_dispatch_metadata_and_preserve_zip_zero(self):
        tables = tiny_tables()
        geolocation = pd.DataFrame({'geolocation_zip_code_prefix': [1040, 1234],
                                    'geolocation_lat': [-23., -22.], 'geolocation_lng': [-46., -43.]})
        for backbone in ('load', 'geo'):
            original = (build_ablation_order_features(tables, 'load_only') if backbone == 'load'
                        else build_engineering_order_features(tables, geolocation, include_dispatch=False))
            frame = features.add_route_load_features(original, tables)
            frame['delayed'], frame['label_available_time'], frame['training_outcome_known_time'] = 1, 'future', 'future'
            frame['customer_zip_prefix3'] = '001'
            frame['dispatch_deadline_days'] = 9999
            for variant, count in (('trend', 78 if backbone == 'load' else 96),
                                    ('cross', 84 if backbone == 'load' else 102)):
                numeric, categorical = features.feature_columns(backbone, variant)
                actual = features.prepare_route_load_input(frame, backbone, variant)
                self.assertEqual(list(actual), numeric+categorical)
                self.assertEqual(len(actual.columns), count)
                self.assertEqual(len(set(actual.columns)), count)
                self.assertTrue(actual.customer_zip_prefix3.eq('001').all())
                self.assertFalse({'order_id', 'prediction_time', 'delayed', 'label_available_time',
                                  'training_outcome_known_time', 'dispatch_deadline_days'}.intersection(actual))
                raw_built = features.build_route_load_order_features(tables, backbone, variant, geolocation)
                self.assertEqual(list(raw_built), ['order_id', 'order_purchase_timestamp', 'prediction_time'] + numeric + categorical)
                assert_frame_equal(features.prepare_route_load_input(raw_built, backbone, variant), features.prepare_route_load_input(
                    features.add_route_load_features(original, tables), backbone, variant))

    def test_invalid_inputs_and_missing_timestamp_fail_or_remain_missing(self):
        now = pd.Timestamp('2020-04-01')
        tables = pending_tables(raw_specs([now-pd.Timedelta(days=1)]))
        frame = query([now])
        for changed in (frame.drop(columns='state_route'), frame.assign(order_id=None)):
            with self.assertRaises(ValueError):
                features.add_route_load_features(changed, tables)
        with self.assertRaises(ValueError):
            features.add_route_load_features(pd.concat([frame, frame]), tables)
        with self.assertRaises(ValueError):
            features.add_route_load_features(features.add_route_load_features(frame, tables), tables)
        missing = frame.copy()
        missing['prediction_time'] = pd.NaT
        self.assertTrue(features.add_route_load_features(missing, tables)[features.TREND_NUMERIC_FEATURES].isna().all(axis=None))
        zoned = frame.copy()
        zoned['prediction_time'] = pd.Timestamp('2020-04-01', tz='UTC')
        with self.assertRaisesRegex(ValueError, 'timezone-naive'):
            features.add_route_load_features(zoned, tables)
        for backbone, variant in (('bad', 'trend'), ('load', 'bad')):
            with self.assertRaises(ValueError):
                features.feature_columns(backbone, variant)
        with self.assertRaisesRegex(ValueError, 'geolocation'):
            features.build_route_load_order_features(tables, 'geo', 'trend')
        with self.assertRaisesRegex(ValueError, 'Missing route/load feature'):
            features.prepare_route_load_input(frame, 'load', 'trend')


if __name__ == '__main__':
    unittest.main()
