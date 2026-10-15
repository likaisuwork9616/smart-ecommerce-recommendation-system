"""Event-clock and full-day cohort tests for an audit with no model changes."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.audit_approval_signals import (
    AGE_BINS, CANDIDATES, COHORTS, COUNT_BINS, SIGNALS,
    DIAGNOSTIC_SHA256, SOURCE_SHA256, availability_inventory, contract,
    pending_signals, phase_profile, signal_bins, verify_fixed_sources,
)


class ApprovalSignalTests(unittest.TestCase):
    def sources(self, rows):
        orders = pd.DataFrame(rows, columns=['order_id', 'order_purchase_timestamp', 'order_approved_at',
                                             'order_delivered_carrier_date', 'order_delivered_customer_date'])
        items = pd.DataFrame({'order_id': orders.order_id, 'order_item_id': 1, 'price': 10., 'seller_id': 'seller'})
        return orders, items

    def calculate(self, rows, query='2018-04-01', query_id='query', seller=True):
        orders, items = self.sources(rows)
        if seller and query_id not in set(items.order_id):
            items.loc[len(items)] = [query_id, 1, 10., 'seller']
        queries = pd.DataFrame({'order_id': [query_id], 'prediction_time': [query]})
        return pending_signals(queries, orders, items)

    def test_strict_events_equal_time_and_closed_lower_window(self):
        result, _ = self.calculate([
            ['lower', '2018-01-01', '2018-01-01', None, None],  # exactly90 days
            ['too_old', '2017-12-31', '2017-12-31', None, None],
            ['same_approval', '2018-04-01', '2018-04-01', None, None],
            ['same_carrier', '2018-03-31', '2018-03-31', '2018-04-01', None],
            ['past_carrier', '2018-03-31', '2018-03-31', '2018-03-31T23:59:59', None],
            ['same_delivery', '2018-03-30', '2018-03-30', None, '2018-04-01'],
        ])
        self.assertEqual(result[SIGNALS[0]].iloc[0], 3.)
        self.assertAlmostEqual(result[SIGNALS[1]].iloc[0], np.quantile([2160, 24, 48], .9, method='linear'))

    def test_future_contradictions_and_final_status_cannot_leak(self):
        rows = [['other', '2018-03-30', '2018-03-30', '2018-04-05', '2018-04-04']]
        result, _ = self.calculate(rows)
        other, _ = self.calculate([['other', '2018-03-30', '2018-03-30', None, None]])
        np.testing.assert_array_equal(result[list(SIGNALS)], other[list(SIGNALS)])
        orders, items = self.sources(rows)
        items.loc[len(items)] = ['query', 1, 10., 'seller']
        orders['order_status'] = 'canceled'
        queries = pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']})
        canceled, _ = pending_signals(queries, orders, items)
        np.testing.assert_array_equal(result[list(SIGNALS)], canceled[list(SIGNALS)])

    def test_only_already_observed_contradictions_quarantine(self):
        result, quality = self.calculate([
            ['bad_carrier', '2018-03-30', '2018-03-30', '2018-03-29', None],
            ['bad_delivery', '2018-03-30', '2018-03-30', None, '2018-03-29'],
            ['bad_both', '2018-03-28', '2018-03-28', '2018-03-30', '2018-03-29'],
            ['future_carrier_past_delivery', '2018-03-28', '2018-03-28', '2018-04-03', '2018-03-29'],
            ['good_pending', '2018-03-31', '2018-03-31', None, None],
        ])
        self.assertEqual(result[SIGNALS[0]].iloc[0], 1.)
        self.assertEqual(result[SIGNALS[1]].iloc[0], 24.)
        self.assertEqual(quality['carrier_before_approval_observed'], 1)
        self.assertEqual(quality['delivery_before_approval_observed'], 1)
        self.assertEqual(quality['delivery_before_carrier_both_observed'], 1)
        self.assertEqual(quality['delivery_without_carrier_observed'], 2)

    def test_invalid_purchase_approval_and_self_are_excluded(self):
        result, _ = self.calculate([
            ['query', '2018-03-30', '2018-03-30', None, None],
            ['bad', '2018-03-31', '2018-03-29', None, None],
            ['valid', '2018-03-30', '2018-03-30', None, None],
        ])
        self.assertEqual(result[SIGNALS[0]].iloc[0], 1.)
        self.assertEqual(result[SIGNALS[1]].iloc[0], 48.)

    def test_p90_uses_one_event_and_linear_multi_event_rule(self):
        single, _ = self.calculate([['a', '2018-03-30', '2018-03-30', None, None]])
        self.assertEqual(single[SIGNALS[1]].iloc[0], 48.)
        multiple, _ = self.calculate([['a', '2018-03-30', '2018-03-30', None, None],
                                      ['b', '2018-03-31', '2018-03-31', None, None]])
        self.assertAlmostEqual(multiple[SIGNALS[1]].iloc[0], 45.6)

    def test_unknown_sellers_never_pool_and_zero_is_distinct(self):
        missing, _ = self.calculate([['a', '2018-03-30', '2018-03-30', None, None]], seller=False)
        self.assertTrue(missing[list(SIGNALS)].isna().all(axis=None))
        zero, _ = self.calculate([['a', '2018-03-30', '2018-03-30', '2018-03-31', None]])
        self.assertEqual(zero[SIGNALS[0]].iloc[0], 0.)
        self.assertTrue(pd.isna(zero[SIGNALS[1]].iloc[0]))

    def test_primary_seller_ties_follow_existing_contract(self):
        orders, items = self.sources([['a', '2018-03-30', '2018-03-30', None, None]])
        items.loc[len(items)] = ['a', 2, 20., 'chosen']
        items.loc[len(items)] = ['a', 3, 20., 'tie_loses']
        items.loc[len(items)] = ['query', 1, 5., 'chosen']
        result, _ = pending_signals(pd.DataFrame({'order_id': ['query'], 'prediction_time': ['2018-04-01']}), orders, items)
        self.assertEqual(result[SIGNALS[0]].iloc[0], 1.)

    def test_queries_and_physical_observations_bounded_before_may(self):
        rows = [['future_approved', '2018-05-01', '2018-05-01', None, None],
                ['earlier', '2018-04-28', '2018-04-28', '2018-05-01', '2018-05-02']]
        result, quality = self.calculate(rows, query='2018-04-30')
        self.assertEqual(result[SIGNALS[0]].iloc[0], 1.)
        self.assertEqual(quality['valid_approved_raw_orders_before_cutoff'], 1)
        with self.assertRaises(ValueError):
            self.calculate(rows, query='2018-05-01')

    def test_rejects_duplicate_queries_and_raw_identities(self):
        orders, items = self.sources([['a', '2018-03-30', '2018-03-30', None, None]])
        query = pd.DataFrame({'order_id': ['a', 'a'], 'prediction_time': ['2018-04-01'] * 2})
        with self.assertRaises(ValueError):
            pending_signals(query, orders, items)
        with self.assertRaises(ValueError):
            pending_signals(query.iloc[:1], pd.concat([orders, orders]), items)

    def test_fixed_bin_endpoints_and_missingness(self):
        values = pd.DataFrame({SIGNALS[0]: [np.nan, 0, 1, 4, 5, 19, 20, 21],
                               SIGNALS[1]: [np.nan, np.nan, 24, 24.1, 72, 72.1, 168, 168.1]})
        c, a = signal_bins(values)
        self.assertEqual(c.tolist(), [COUNT_BINS[i] for i in (0, 1, 2, 2, 3, 3, 4, 4)])
        self.assertEqual(a.tolist(), [AGE_BINS[i] for i in (0, 1, 2, 3, 3, 4, 4, 5)])
        for count, age in [(1, np.nan), (0, 1), (-1, np.nan), (1.5, 1), (1, 2161), (np.nan, 1)]:
            with self.subTest(count=count, age=age), self.assertRaises(ValueError):
                signal_bins(pd.DataFrame({SIGNALS[0]: [count], SIGNALS[1]: [age]}))

    def test_unknown_high_rank_consumes_original_daily_slot(self):
        frame = pd.DataFrame({'order_id': list('abcdefghij'), 'prediction_time': pd.to_datetime(['2018-04-01'] * 10)})
        frame['label_available_time'] = pd.to_datetime(['2018-04-02', *(['2018-04-01'] * 9)])
        values = pd.DataFrame({SIGNALS[0]: [1.] * 10, SIGNALS[1]: [24.] * 10})
        labels = [np.nan, 1., 0., 1., *([0.] * 6)]
        ledger = pd.concat([pd.DataFrame({'order_id': frame.order_id, 'prediction_time': frame.prediction_time,
                 'candidate': candidate, 'outcome_for_metrics': labels, 'delay_score': np.linspace(.99, .1, 10),
                 'known_at_selection': [False, *([True] * 9)],
                 'predicted_delayed': [1, *([0] * 9)]}) for candidate in CANDIDATES], ignore_index=True)
        result = phase_profile(frame, ledger, values, role='validation', cutoff='2018-04-02')
        self.assertEqual(result['cohorts']['common_missed_delayed']['orders'], 2)
        self.assertEqual(result['cohorts']['other_known_delayed']['orders'], 0)
        self.assertEqual(result['cohorts']['unknown_outcome']['orders'], 1)
        self.assertEqual(sum(result['cohorts'][c]['orders'] for c in COHORTS), 10)
        # One known delayed receives a slot in only one model: outside common misses.
        part = ledger.candidate.eq(CANDIDATES[1])
        ledger.loc[part, 'delay_score'] = [.9, .99, *np.linspace(.8, .1, 8)]
        ledger.loc[part, 'predicted_delayed'] = [0, 1, *([0] * 8)]
        result = phase_profile(frame, ledger, values, role='validation', cutoff='2018-04-02')
        self.assertEqual(result['cohorts']['common_missed_delayed']['orders'], 1)
        self.assertEqual(result['cohorts']['other_known_delayed']['orders'], 1)

    def test_requires_unchanged_full_day_alerts(self):
        frame = pd.DataFrame({'order_id': list('abcdefghij'), 'prediction_time': pd.to_datetime(['2018-04-01'] * 10)})
        values = pd.DataFrame({SIGNALS[0]: [0.] * 10, SIGNALS[1]: [np.nan] * 10})
        ledger = pd.concat([pd.DataFrame({'order_id': frame.order_id, 'prediction_time': frame.prediction_time,
                 'candidate': candidate, 'outcome_for_metrics': 0., 'delay_score': np.linspace(.99, .1, 10),
                 'known_at_selection': False,
                 'predicted_delayed': [0] * 10}) for candidate in CANDIDATES], ignore_index=True)
        with self.assertRaises(AssertionError):
            phase_profile(frame, ledger, values)

    def test_rejects_changed_frozen_source_hashes(self):
        with patch('scripts.audit_approval_signals.sha256', side_effect=[SOURCE_SHA256, DIAGNOSTIC_SHA256]):
            verify_fixed_sources('source', 'diagnostic')
        with patch('scripts.audit_approval_signals.sha256', return_value='modified'), self.assertRaises(ValueError):
            verify_fixed_sources('source', 'diagnostic')
        with patch('scripts.audit_approval_signals.sha256', side_effect=[SOURCE_SHA256, 'modified']), self.assertRaises(ValueError):
            verify_fixed_sources('source', 'diagnostic')

    def test_outcome_observation_at_cutoff_remains_unknown(self):
        frame = pd.DataFrame({'order_id': list('abcdefghij'), 'prediction_time': pd.to_datetime(['2018-04-01'] * 10),
                              'label_available_time': pd.to_datetime(['2018-04-02'] * 10)})
        values = pd.DataFrame({SIGNALS[0]: [0.] * 10, SIGNALS[1]: [np.nan] * 10})
        ledger = pd.concat([pd.DataFrame({'order_id': frame.order_id, 'prediction_time': frame.prediction_time,
                 'candidate': candidate, 'outcome_for_metrics': np.nan, 'delay_score': np.linspace(.99, .1, 10),
                 'known_at_selection': False, 'predicted_delayed': [1, *([0] * 9)]}) for candidate in CANDIDATES], ignore_index=True)
        actual = phase_profile(frame, ledger, values, role='validation', cutoff='2018-04-02')
        self.assertEqual(actual['cohorts']['unknown_outcome']['orders'], 10)
        ledger.loc[0, 'outcome_for_metrics'] = 1.
        with self.assertRaisesRegex(ValueError, 'outcome availability'):
            phase_profile(frame, ledger, values, role='validation', cutoff='2018-04-02')
        ledger.loc[0, 'outcome_for_metrics'] = np.nan
        ledger.loc[0, 'known_at_selection'] = True
        with self.assertRaisesRegex(ValueError, 'selection availability'):
            phase_profile(frame, ledger, values, role='validation', cutoff='2018-04-02')

    def test_inventory_does_not_rebrand_existing_features_as_new(self):
        matrix = availability_inventory()
        self.assertTrue(any('Count already in102/104' in str(row) for row in matrix))
        self.assertTrue(any('Existing8-feature' in str(row) for row in matrix))
        self.assertTrue(contract()['no_threshold_search'])
        self.assertTrue(contract()['no_model_input_change'])


if __name__ == '__main__':
    unittest.main()
