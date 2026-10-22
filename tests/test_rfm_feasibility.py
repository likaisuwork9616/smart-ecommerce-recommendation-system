"""Synthetic identity, money, join and historical-cutoff checks; no RFM/model."""
import copy
import unittest

from scripts import audit_rfm_feasibility as rfm


def fixture():
    return {
        'orders': [{'order_id': 'o1', 'customer_id': 'c1', 'order_status': 'delivered',
                    'order_purchase_timestamp': '2018-08-01 00:00:00',
                    'order_approved_at': '2018-08-02 00:00:00',
                    'order_delivered_customer_date': '2018-08-10 00:00:00'}],
        'customers': [{'customer_id': 'c1', 'customer_unique_id': 'u1'}],
        'order_items': [{'order_id': 'o1', 'order_item_id': '1', 'price': '10.00', 'freight_value': '2.00'}],
        'order_payments': [{'order_id': 'o1', 'payment_sequential': '1', 'payment_type': 'credit_card',
                            'payment_installments': '12', 'payment_value': '12.00'}],
    }


class RFMInventoryTests(unittest.TestCase):
    def test_cents_exact(self):
        self.assertEqual([rfm.cents(x) for x in ['0', '0.00', '0.10', '12.3', '12.34']],
                         [0, 0, 10, 1230, 1234])

    def test_invalid_cents_never_rounded_or_zeroed(self):
        for value in ['', 'NaN', 'Infinity', '1e2', '1.001', '1,000.00', '99999999999999999999']:
            with self.subTest(value=value):
                self.assertIsNone(rfm.cents(value))

    def test_clock_invalid_and_timezone_not_guessed(self):
        for value in ['', '2018-8-01 00:00:00', '2018-02-30 00:00:00', '2018-08-01T00:00:00Z']:
            self.assertIsNone(rfm.clock(value))

    def test_missing_or_duplicate_master_keys_fail(self):
        for rows in [[{'id': ''}], [{'id': 'x'}, {'id': 'x'}]]:
            with self.assertRaises(ValueError):
                rfm.unique_rows(rows, 'id')

    def test_repeated_unique_customer_is_not_mapping_conflict(self):
        t = fixture()
        t['customers'].append({'customer_id': 'c2', 'customer_unique_id': 'u1'})
        row = dict(t['orders'][0], order_id='o2', customer_id='c2')
        t['orders'].append(row)
        result = rfm.inventory(t)
        self.assertEqual(result['identity']['mapped_unique_customers_all_source'], 1)
        self.assertEqual(result['identity']['mapped_customers_with_multiple_source_orders'], 1)

    def test_many_to_many_join_is_not_used_for_money(self):
        t = fixture()
        t['order_items'].append(dict(t['order_items'][0], order_item_id='2', price='20.00'))
        t['order_payments'][0]['payment_value'] = '10.00'
        t['order_payments'].append(dict(t['order_payments'][0], payment_sequential='2', payment_value='24.00'))
        result = rfm.inventory(t)
        self.assertEqual(result['order_joins']['naive_inner_item_payment_join_rows'], 4)
        self.assertEqual(result['order_joins']['order_aggregate_join_rows'], 1)
        self.assertEqual(result['candidate_window_support']['price']['sum_cents_on_valid_orders'], 3000)
        self.assertEqual(result['payment_vs_product_plus_freight']['exact_equal_cents_orders'], 1)

    def test_installments_not_multiplier(self):
        support = rfm.inventory(fixture())['candidate_window_support']
        self.assertEqual(support['payments']['sum_cents_on_valid_orders'], 1200)

    def test_missing_items_not_zero_or_payment_fallback(self):
        t = fixture(); t['order_items'] = []
        result = rfm.inventory(t)
        self.assertEqual(result['order_joins']['orders_missing_items'], 1)
        self.assertEqual(result['candidate_window_support']['input_supported_orders'], 0)
        self.assertIsNone(result['candidate_window_support']['price']['sum_cents_on_valid_orders'])

    def test_missing_payments_does_not_remove_product_supported_order(self):
        t = fixture(); t['order_payments'] = []
        support = rfm.inventory(t)['candidate_window_support']
        self.assertEqual(support['input_supported_orders'], 1)
        self.assertEqual(support['payments']['unknown_or_invalid_orders'], 1)
        self.assertIsNone(support['payments']['sum_cents_on_valid_orders'])

    def test_invalid_negative_price_is_quarantined(self):
        for price in ['-0.01', '', '1.001']:
            t = fixture(); t['order_items'][0]['price'] = price
            self.assertEqual(rfm.inventory(t)['candidate_window_support']['input_supported_orders'], 0)

    def test_duplicate_item_key_reported_and_quarantined(self):
        t = fixture(); t['order_items'] *= 2
        result = rfm.inventory(t)
        self.assertEqual(result['items']['duplicate_key_groups'], 1)
        self.assertEqual(result['candidate_window_support']['input_supported_orders'], 0)

    def test_bad_payment_not_forced_to_match_price(self):
        t = fixture(); t['order_payments'][0]['payment_value'] = 'NaN'
        support = rfm.inventory(t)['candidate_window_support']
        self.assertEqual(support['input_supported_orders'], 1)
        self.assertEqual(support['payment_reconciliation']['comparable_orders'], 0)

    def test_one_cent_gap_reported_not_accepted_tolerance(self):
        t = fixture(); t['order_payments'][0]['payment_value'] = '12.01'
        result = rfm.inventory(t)['payment_vs_product_plus_freight']
        self.assertEqual(result['nonzero_difference_orders'], 1)
        self.assertEqual(result['absolute_difference_above_one_cent_orders'], 0)
        self.assertFalse(result['one_cent_is_business_acceptance_tolerance'])

    def test_purchase_window_left_closed_right_open(self):
        t = fixture(); t['orders'][0]['order_purchase_timestamp'] = str(rfm.START)
        self.assertEqual(rfm.inventory(t)['candidate_window_support']['input_supported_orders'], 1)
        t['orders'][0]['order_purchase_timestamp'] = str(rfm.CUTOFF)
        self.assertEqual(rfm.inventory(t)['candidate_window_support']['input_supported_orders'], 0)

    def test_late_or_equal_T_delivery_is_future(self):
        for date in ['2018-09-01 00:00:00', '2018-09-02 00:00:00']:
            t = fixture(); t['orders'][0]['order_delivered_customer_date'] = date
            self.assertEqual(rfm.inventory(t)['candidate_window_support']['input_supported_orders'], 0)

    def test_final_status_alone_cannot_prove_delivered_before_T(self):
        t = fixture(); t['orders'][0]['order_delivered_customer_date'] = ''
        support = rfm.inventory(t)['candidate_window_support']
        self.assertEqual(support['input_supported_orders'], 0)
        ledger = {x['rule']: x for x in support['sequential_order_ledger']}
        self.assertEqual(ledger['valid_delivery_clock']['excluded_from_previous'], 1)

    def test_delivery_before_purchase_is_excluded(self):
        t = fixture(); t['orders'][0]['order_delivered_customer_date'] = '2018-07-30 00:00:00'
        self.assertEqual(rfm.inventory(t)['candidate_window_support']['input_supported_orders'], 0)

    def test_approval_is_diagnostic_not_silent_extra_filter(self):
        t = fixture(); t['orders'][0]['order_approved_at'] = ''
        support = rfm.inventory(t)['candidate_window_support']
        self.assertEqual(support['input_supported_orders'], 1)
        self.assertEqual(support['orders_with_missing_approval'], 1)

    def test_orphan_mapping_is_counted_before_candidate_exclusion(self):
        t = fixture(); t['orders'][0]['customer_id'] = 'absent'
        result = rfm.inventory(t)
        self.assertEqual(result['identity']['orphan_customer_id_orders'], 1)
        self.assertEqual(result['candidate_window_support']['input_supported_orders'], 0)

    def test_inventory_does_not_mutate_sources_or_build_customer_RFM(self):
        t = fixture(); before = copy.deepcopy(t)
        result = rfm.inventory(t)
        self.assertEqual(t, before)
        self.assertIn('customer_RFM_values', result['not_executed'])
        self.assertNotIn('u1', str(result))


if __name__ == '__main__':
    unittest.main()
