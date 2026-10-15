"""Milestones must be reconstructed at the declared prediction clock."""
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from scripts.logistics_event_availability import (
    event_asof_features,
    history_support_counts,
)
from scripts.audit_logistics_availability import checkpoint_profile, restricted_population


def orders(**changes):
    values = {
        'order_id': ['one'],
        'order_purchase_timestamp': ['2018-01-01 00:00'],
        'order_approved_at': ['2018-01-01 12:00'],
        'order_delivered_carrier_date': [None],
        'order_delivered_customer_date': [None],
        'order_estimated_delivery_date': ['2018-01-10'],
        'order_status': ['delivered'],
    }
    for key, value in changes.items():
        values[key] = value if isinstance(value, list) else [value]
    return pd.DataFrame(values)


def query(frame, value='2018-01-03 12:00'):
    return pd.Series(pd.Timestamp(value), index=frame.index)


class LogisticsAvailabilityTests(unittest.TestCase):
    def test_future_carrier_and_export_null_are_indistinguishable_as_of_query(self):
        future = orders(order_delivered_carrier_date='2018-02-01')
        missing = orders()
        actual = event_asof_features(future, query(future))
        expected = event_asof_features(missing, query(missing))
        assert_frame_equal(actual, expected)
        row = actual.iloc[0]
        self.assertFalse(row.carrier_observed)
        self.assertEqual(row.observed_phase, 'pre_handover')
        self.assertTrue(pd.isna(row.approval_to_carrier_days))
        self.assertTrue(pd.isna(row.transit_age_days))

    def test_carrier_equal_to_query_is_not_observed_but_one_nanosecond_earlier_is(self):
        stamp = pd.Timestamp('2018-01-03 12:00')
        frame = pd.concat([orders(order_id=str(i), order_delivered_carrier_date=value)
                           for i, value in enumerate([stamp-pd.Timedelta(nanoseconds=1), stamp,
                                                      stamp+pd.Timedelta(nanoseconds=1)])],
                          ignore_index=True)
        actual = event_asof_features(frame, query(frame, str(stamp)))
        self.assertEqual(actual.carrier_observed.tolist(), [True, False, False])
        self.assertTrue(actual.loc[[1, 2], ['approval_to_carrier_days', 'transit_age_days']].isna().all(axis=None))

    def test_approval_equal_carrier_becomes_valid_only_after_event(self):
        frame = orders(order_delivered_carrier_date='2018-01-01 12:00')
        at = event_asof_features(frame, query(frame, '2018-01-01 12:00')).iloc[0]
        after = event_asof_features(frame, query(frame, '2018-01-01 12:00:00.000000001')).iloc[0]
        self.assertFalse(at.carrier_observed)
        self.assertTrue(after.carrier_observed)
        self.assertEqual(after.approval_to_carrier_days, 0.)

    def test_carrier_before_approval_is_invalid_never_zero_imputed_duration(self):
        frame = orders(order_delivered_carrier_date='2018-01-01 11:59:59')
        row = event_asof_features(frame, query(frame)).iloc[0]
        self.assertTrue(row.carrier_known_invalid)
        self.assertFalse(row.carrier_observed)
        self.assertTrue(pd.isna(row.approval_to_carrier_days))
        self.assertTrue(pd.isna(row.transit_age_days))

    def test_known_handover_uses_fractional_days_and_remaining_promise_calendar_end(self):
        frame = orders(order_delivered_carrier_date='2018-01-02 18:00')
        row = event_asof_features(frame, query(frame)).iloc[0]
        self.assertEqual(row.observed_phase, 'in_transit')
        self.assertAlmostEqual(row.approval_age_days, 2.)
        self.assertAlmostEqual(row.approval_to_carrier_days, 1.25)
        self.assertAlmostEqual(row.transit_age_days, .75)
        self.assertAlmostEqual(row.promise_remaining_days, 7.5)

    def test_future_delivery_never_exposes_target_or_final_null_indicator(self):
        future = orders(order_delivered_customer_date='2018-02-01')
        absent = orders()
        assert_frame_equal(event_asof_features(future, query(future)),
                           event_asof_features(absent, query(absent)))

    def test_delivered_at_query_suppresses_alert_while_event_visibility_remains_strict(self):
        frame = orders(order_delivered_customer_date='2018-01-03 12:00')
        row = event_asof_features(frame, query(frame)).iloc[0]
        self.assertFalse(row.delivery_observed)
        self.assertTrue(row.already_delivered_by_query)
        self.assertFalse(row.eligible_for_reminder)

    def test_delivery_before_query_exits_alert_population(self):
        frame = orders(order_delivered_customer_date='2018-01-03 11:59:59')
        row = event_asof_features(frame, query(frame)).iloc[0]
        self.assertTrue(row.delivery_observed)
        self.assertTrue(row.already_delivered_by_query)
        self.assertEqual(row.observed_phase, 'delivered')
        self.assertFalse(row.eligible_for_reminder)

    def test_final_cancelled_status_cannot_remove_order_without_cancellation_clock(self):
        cancelled = orders(order_status='canceled')
        delivered = orders(order_status='delivered')
        result = event_asof_features(cancelled, query(cancelled))
        assert_frame_equal(result, event_asof_features(delivered, query(delivered)))
        self.assertTrue(result.iloc[0].eligible_for_reminder)

    def test_actual_handover_cannot_be_inferred_from_scheduled_dispatch_limit(self):
        source = orders()
        source['shipping_limit_date'] = pd.Timestamp('2018-01-01')
        actual = event_asof_features(source, query(source))
        source['shipping_limit_date'] = pd.Timestamp('2018-12-31')
        assert_frame_equal(actual, event_asof_features(source, query(source)))
        self.assertFalse(actual.iloc[0].carrier_observed)

    def test_promise_calendar_day_is_available_until_midnight_then_alert_is_overdue(self):
        frame = orders(order_estimated_delivery_date='2018-01-03')
        last = event_asof_features(frame, query(frame, '2018-01-03 23:59:59.999999999')).iloc[0]
        next_day = event_asof_features(frame, query(frame, '2018-01-04 00:00')).iloc[0]
        self.assertTrue(last.eligible_for_advance_reminder)
        self.assertFalse(last.promise_expired)
        self.assertTrue(next_day.eligible_for_reminder)
        self.assertFalse(next_day.eligible_for_advance_reminder)
        self.assertTrue(next_day.promise_expired)
        self.assertEqual(next_day.promise_remaining_days, 0.)

    def test_unknown_promise_can_be_monitored_but_cannot_claim_advance_eligibility(self):
        frame = orders(order_estimated_delivery_date=None)
        row = event_asof_features(frame, query(frame)).iloc[0]
        self.assertTrue(row.eligible_for_reminder)
        self.assertFalse(row.eligible_for_advance_reminder)
        self.assertFalse(row.promise_expired)
        self.assertTrue(pd.isna(row.promise_remaining_days))

    def test_invalid_approval_sequence_or_future_approval_has_no_valid_event_features(self):
        bad = orders(order_approved_at='2017-12-31')
        row = event_asof_features(bad, query(bad)).iloc[0]
        self.assertFalse(row.valid_approval_query)
        self.assertFalse(row.eligible_for_reminder)
        future = orders(order_approved_at='2018-01-04')
        later = event_asof_features(future, query(future)).iloc[0]
        self.assertFalse(later.valid_approval_query)
        self.assertFalse(later.carrier_observed)
        self.assertFalse(later.eligible_for_reminder)

    def test_missing_approval_or_query_remains_unknown_not_zero_age(self):
        frame = orders(order_approved_at=None)
        missing_approval = event_asof_features(frame, query(frame)).iloc[0]
        self.assertFalse(missing_approval.valid_approval_query)
        self.assertTrue(pd.isna(missing_approval.approval_age_days))
        normal = orders()
        missing_query = event_asof_features(normal, pd.Series([pd.NaT])).iloc[0]
        self.assertFalse(missing_query.valid_approval_query)
        self.assertTrue(pd.isna(missing_query.approval_age_days))

    def test_input_index_and_sources_are_preserved(self):
        source = pd.concat([orders(order_id='a'), orders(order_id='b')], ignore_index=True)
        source.index = [9, 4]
        times = query(source)
        old_source, old_times = source.copy(deep=True), times.copy(deep=True)
        actual = event_asof_features(source, times)
        self.assertEqual(actual.index.tolist(), [9, 4])
        assert_frame_equal(source, old_source)
        assert_series_equal(times, old_times)

    def test_timezone_aware_input_is_rejected(self):
        frame = orders()
        times = pd.Series([pd.Timestamp('2018-01-03', tz='UTC')])
        with self.assertRaises(ValueError):
            event_asof_features(frame, times)


class LogisticsHistorySupportTests(unittest.TestCase):
    def test_ninety_day_window_is_left_inclusive_and_query_exclusive(self):
        now = pd.Timestamp('2018-04-01 12:00')
        events = pd.DataFrame({
            'event_time': [now-pd.Timedelta(days=90)-pd.Timedelta(nanoseconds=1),
                           now-pd.Timedelta(days=90), now-pd.Timedelta(nanoseconds=1),
                           now, now+pd.Timedelta(nanoseconds=1)],
            'seller': ['a'] * 5,
        })
        queries = pd.DataFrame({'prediction_time': [now], 'seller': ['a']})
        actual = history_support_counts(queries, events, 'seller')
        self.assertEqual(actual.tolist(), [2])

    def test_missing_groups_do_not_pool_and_distinct_sellers_never_leak(self):
        events = pd.DataFrame({'event_time': pd.to_datetime(['2018-01-01'] * 4),
                               'seller': ['a', 'a', 'b', None]})
        queries = pd.DataFrame({'prediction_time': pd.to_datetime(['2018-01-02'] * 4),
                                'seller': ['a', 'b', 'c', None]}, index=[8, 3, 5, 4])
        actual = history_support_counts(queries, events, 'seller')
        self.assertEqual(actual.tolist(), [2, 1, 0, 0])
        self.assertEqual(actual.index.tolist(), [8, 3, 5, 4])

    def test_future_events_do_not_change_support_and_inputs_are_not_mutated(self):
        events = pd.DataFrame({'event_time': pd.to_datetime(['2018-01-01', '2018-01-04']),
                               'route': ['SP|RJ', 'SP|RJ']})
        queries = pd.DataFrame({'prediction_time': pd.to_datetime(['2018-01-03']),
                                'route': ['SP|RJ']})
        saved_events, saved_queries = events.copy(deep=True), queries.copy(deep=True)
        actual = history_support_counts(queries, events, 'route')
        expected = history_support_counts(queries, events.iloc[:1], 'route')
        assert_series_equal(actual, expected)
        assert_frame_equal(events, saved_events)
        assert_frame_equal(queries, saved_queries)

    def test_unsorted_events_count_the_same_completed_events(self):
        events = pd.DataFrame({'event_time': pd.to_datetime(['2018-01-02', '2017-12-31', '2018-01-01']),
                               'seller': ['a', 'a', 'a']})
        queries = pd.DataFrame({'prediction_time': pd.to_datetime(['2018-01-03', '2018-01-01']),
                                'seller': ['a', 'a']})
        self.assertEqual(history_support_counts(queries, events, 'seller').tolist(), [3, 1])

    def test_duplicate_event_index_labels_do_not_duplicate_observations(self):
        events = pd.DataFrame({'event_time': pd.to_datetime(['2018-01-01', '2018-01-02']),
                               'seller': ['a', 'a']}, index=[7, 7])
        queries = pd.DataFrame({'prediction_time': pd.to_datetime(['2018-01-03']),
                                'seller': ['a']})
        self.assertEqual(history_support_counts(queries, events, 'seller').tolist(), [2])

    def test_window_must_be_positive(self):
        events = pd.DataFrame({'event_time': pd.to_datetime(['2018-01-01']), 'seller': ['a']})
        queries = pd.DataFrame({'prediction_time': pd.to_datetime(['2018-01-02']), 'seller': ['a']})
        for window in (0, -1):
            with self.assertRaises(ValueError):
                history_support_counts(queries, events, 'seller', window_days=window)


class InventoryPopulationTests(unittest.TestCase):
    def test_restricted_population_censors_future_events_without_using_final_status(self):
        source = pd.concat([
            orders(order_id='before', order_approved_at='2018-04-30',
                   order_delivered_carrier_date='2018-05-01',
                   order_delivered_customer_date='2018-06-01', order_status='canceled'),
            orders(order_id='after', order_approved_at='2018-05-01'),
        ], ignore_index=True)
        frame, scope = restricted_population(source)
        self.assertEqual(frame.order_id.tolist(), ['before'])
        self.assertNotIn('order_status', frame)
        self.assertTrue(frame[['order_delivered_carrier_date', 'order_delivered_customer_date']].isna().all(axis=None))
        self.assertFalse(scope['final_status_filter'])
        self.assertFalse(scope['target_or_performance_metrics_computed'])
        changed = source.copy()
        changed['order_status'] = 'delivered'
        actual, actual_scope = restricted_population(changed)
        assert_frame_equal(frame, actual)
        self.assertEqual(scope, actual_scope)
        with self.assertRaises(ValueError):
            restricted_population(source, cutoff='2018-05-02')

    def test_checkpoint_delivery_equality_and_original_promise_boundary_are_distinct(self):
        source = pd.concat([
            orders(order_id='equal', order_approved_at='2018-01-01 00:00',
                   order_delivered_customer_date='2018-01-02 00:00'),
            orders(order_id='overdue', order_approved_at='2018-01-01 00:00',
                   order_estimated_delivery_date='2018-01-01'),
        ], ignore_index=True)
        frame, _ = restricted_population(source)
        result = checkpoint_profile(frame, approval_days=1)
        self.assertEqual(result['observable_queries_before_cutoff'], 2)
        self.assertEqual(result['customer_delivery_observed_before_query'], 0)
        self.assertEqual(result['customer_delivery_equal_query_conservative_suppression'], 1)
        self.assertEqual(result['eligible_for_reminder_proxy'], 1)
        self.assertEqual(result['already_overdue_pending_among_generic_eligible'], 1)
        self.assertEqual(result['eligible_for_advance_reminder_proxy'], 0)


if __name__ == '__main__':
    unittest.main()
