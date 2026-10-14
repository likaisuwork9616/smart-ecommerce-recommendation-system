"""Hand calculations, event boundaries and future-invariance for backlog changes."""
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.delay_backlog_features import (
    ADDED_FEATURES, LAG_FEATURES, GROUPS, overdue_snapshots, add_backlog_features,
    feature_columns, prepare_backlog_input, build_backlog_order_features,
)
from scripts.delay_pending_features import add_pending_features
from tests.test_delay_pending_features import pending_tables, queries


class BacklogFeaturesTests(unittest.TestCase):
    def test_snapshots_use_their_own_delivery_knowledge_and_calendar_deadlines(self):
        tables = pending_tables([
            ('old', '2020-01-01', '2020-01-25', '2020-01-05', 'delivered', 'seller_a', 'SP'),
            ('new', '2020-01-10', None, '2020-01-23', 'shipped', 'seller_a', 'SP'),
            ('cancel', '2020-01-01', None, '2020-01-05', 'canceled', 'seller_a', 'SP'),
        ])
        frame = queries(['2020-02-01'])
        actual = add_backlog_features(frame, tables).iloc[0]
        for group in GROUPS:
            self.assertEqual(actual[f'{group}_overdue_pending_lag_7d'], 3)
            self.assertEqual(actual[f'{group}_overdue_pending_lag_14d'], 2)
            self.assertEqual(actual[f'{group}_overdue_pending_change_7d'], -1)
            self.assertEqual(actual[f'{group}_overdue_pending_change_14d'], 0)
            self.assertAlmostEqual(actual[f'{group}_overdue_pending_log_growth_7d'], np.log(3/4))
        # A delivery learned after the older snapshot must not remove that
        # order from the historical backlog (old delivered exactly Jan25).
        self.assertEqual(overdue_snapshots(frame, tables)['global'][0].tolist(), [2, 3, 2])

    def test_approval_strict_delivery_strict_deadline_inclusive_and_90day_inclusive(self):
        now = pd.Timestamp('2020-04-01')
        ns = pd.Timedelta(nanoseconds=1)
        rows = [
            ('lower', now-pd.Timedelta(days=90), None, now-pd.Timedelta(days=1)),
            ('expired', now-pd.Timedelta(days=90)-ns, None, now-pd.Timedelta(days=1)),
            ('approval_equal', now, None, now-pd.Timedelta(days=1)),
            ('approval_before', now-ns, None, now-pd.Timedelta(days=1)),
            ('delivery_equal', now-pd.Timedelta(days=5), now, now-pd.Timedelta(days=1)),
            ('delivery_before', now-pd.Timedelta(days=5), now-ns, now-pd.Timedelta(days=1)),
            ('promise_today', now-pd.Timedelta(days=5), None, now),
            ('promise_missing', now-pd.Timedelta(days=5), None, None),
        ]
        tables = pending_tables([(key,a,b,d,'anything','seller_a','SP') for key,a,b,d in rows])
        actual = overdue_snapshots(queries([now, now+ns]), tables)['global'][:, 0]
        self.assertEqual(actual.tolist(), [3, 2])

    def test_moving_window_expiration_is_a_possible_negative_change(self):
        tables = pending_tables([('stale','2020-01-01',None,'2020-01-02','canceled','seller_a','SP')])
        result = add_backlog_features(queries(['2020-04-02']), tables).iloc[0]
        self.assertEqual(result.route_overdue_pending_lag_7d, 1)
        self.assertEqual(result.route_overdue_pending_change_7d, -1)

    def test_final_status_target_and_future_deliveries_or_approvals_do_not_change_past(self):
        tables = pending_tables([
            ('future_delivery','2020-01-01','2020-03-01','2020-01-10','delivered','seller_a','SP'),
            ('cancel','2020-01-01',None,'2020-01-10','canceled','seller_a','SP'),
            ('future_order','2020-03-01',None,'2020-01-01','created','seller_a','SP'),
        ])
        frame = queries(['2020-02-01'])
        expected = add_backlog_features(frame, tables)
        tables['orders']['order_status'] = 'changed'
        tables['orders']['delayed'] = 'unavailable'
        tables['orders'].loc[0, 'order_delivered_customer_date'] = '2020-04-01'
        tables['orders'].loc[2, 'order_estimated_delivery_date'] = '2019-01-01'
        assert_frame_equal(add_backlog_features(frame, tables), expected)
        del tables['orders']['order_status']
        assert_frame_equal(add_backlog_features(frame, tables), expected)

    def test_invalid_approval_missing_promise_and_delivery_before_approval(self):
        tables = pending_tables([
            ('invalid','2020-01-01',None,'2020-01-02','created','seller_a','SP'),
            ('missing','2020-01-01',None,None,'created','seller_a','SP'),
            ('bad_delivery','2020-01-01','2019-01-01','2020-01-02','delivered','seller_a','SP'),
        ])
        tables['orders'].loc[0, 'order_purchase_timestamp'] = pd.Timestamp('2020-02-01')
        actual = add_backlog_features(queries(['2020-02-01']), tables)
        self.assertTrue(actual[ADDED_FEATURES].eq(0).all().all())

    def test_unknown_keys_missing_queries_and_unseen_groups(self):
        tables = pending_tables([('known','2020-01-01',None,'2020-01-02','shipped','seller_a','SP')])
        frame = queries(['2020-02-01', pd.NaT], seller=None, seller_state=None, customer=None)
        actual = add_backlog_features(frame, tables)
        self.assertEqual(actual.iloc[0].global_overdue_pending_lag_7d, 1)
        self.assertTrue(actual.filter(regex='^(seller|route)_overdue').iloc[0].isna().all())
        self.assertTrue(actual[ADDED_FEATURES].iloc[1].isna().all())
        unseen = add_backlog_features(queries(['2020-02-01'], seller='unseen', customer='MG'), tables)
        self.assertTrue(unseen.filter(regex='^(seller|route)_overdue').eq(0).all().all())

    def test_interval_counts_match_bruteforce_and_existing_fenwick_with_shuffled_queries(self):
        rng = np.random.default_rng(91)
        specs = []
        for i in range(75):
            approval = pd.Timestamp('2020-01-01') + pd.Timedelta(hours=int(rng.integers(0, 24*140)))
            delivery = None if i % 4 == 0 else approval + pd.Timedelta(hours=int(rng.integers(0, 24*150)))
            promise = None if i % 11 == 0 else approval + pd.Timedelta(days=int(rng.integers(-3, 60)))
            specs.append((f'raw-{i}', approval, delivery, promise, 'canceled', 'seller_a' if i%2 else 'seller_b', 'SP' if i%3 else 'MG'))
        tables = pending_tables(specs)
        frame = queries(pd.date_range('2020-01-01', periods=45, freq='5D')).sample(frac=1, random_state=7)
        frame.index = np.arange(len(frame)) % 3
        before = frame.copy()
        actual = add_backlog_features(frame, tables)
        assert_frame_equal(actual[list(frame)], before)
        expected = {g: [] for g in GROUPS}
        for stamp in frame.prediction_time:
            for g in GROUPS:
                counts = []
                for lag in (0, 7, 14):
                    at = stamp - pd.Timedelta(days=lag)
                    count = 0
                    for _, a, b, d, _, seller, state in specs:
                        match = g == 'global' or (g == 'seller' and seller == 'seller_a') or (g == 'route' and state == 'SP')
                        count += int(match and at-pd.Timedelta(days=90) <= a < at and d is not None
                            and pd.Timestamp(d).normalize()+pd.Timedelta(days=1) <= at and (b is None or b >= at))
                    counts.append(count)
                expected[g].append(counts)
        snapshots = overdue_snapshots(frame, tables)
        for g in GROUPS:
            np.testing.assert_array_equal(snapshots[g], expected[g])
        for j, lag in enumerate((0, 7, 14)):
            older = frame.copy()
            older['prediction_time'] -= pd.Timedelta(days=lag)
            fenwick = add_pending_features(older, tables)
            for g in GROUPS:
                np.testing.assert_array_equal(snapshots[g][:,j], fenwick[f'{g}_pending_overdue_90d'])

    def test_frozen_current_count_mismatch_and_invalid_input_are_rejected(self):
        tables = pending_tables([('known','2020-01-01',None,'2020-01-02','shipped','seller_a','SP')])
        frame = queries(['2020-02-01'])
        with self.assertRaises(ValueError):
            add_backlog_features(frame.assign(global_pending_overdue_90d=999), tables)
        with self.assertRaises(ValueError):
            add_backlog_features(pd.concat([frame, frame]), tables)
        with self.assertRaises(ValueError):
            add_backlog_features(frame.assign(prediction_time=pd.Timestamp('2020-02-01',tz='UTC')), tables)
        with self.assertRaises(ValueError):
            add_backlog_features(frame.assign(**{ADDED_FEATURES[0]: 0}), tables)

    def test_three_contracts_add_only_declared_numeric_lags(self):
        for backbone, base in (('load',65),('geo',83)):
            for variant, count in (('7d',9),('14d',9),('7_14d',18)):
                numeric, categorical = feature_columns(backbone, variant)
                self.assertEqual(len(numeric+categorical), base+count)
                self.assertEqual(len(set(numeric+categorical)), base+count)
                self.assertFalse(set(numeric+categorical) & {'delayed','prediction_time','label_available_time','training_outcome_known_time'})
                frame = pd.DataFrame({n:[np.inf] for n in numeric} | {n:['001'] for n in categorical})
                prepared = prepare_backlog_input(frame.assign(delayed=1), backbone, variant)
                self.assertTrue(prepared[numeric].isna().all().all())
                self.assertEqual(prepared.customer_zip_prefix3.iloc[0], '001')
        with self.assertRaises(ValueError):
            feature_columns('load','unknown')
        with self.assertRaises(ValueError):
            build_backlog_order_features({}, 'geo','7d')


if __name__ == '__main__':
    unittest.main()
