"""Contract and support-only tests; no RFM values, builder or models."""
import copy
import unittest
from unittest.mock import patch

from scripts import freeze_rfm_dataset_spec as contract
from tests.test_rfm_feasibility import fixture


class RFMDatasetContractTests(unittest.TestCase):
    def test_fixed_window_and_no_builder(self):
        p = contract.policy()
        self.assertEqual(p['S_inclusive'], '2017-09-01 00:00:00')
        self.assertEqual(p['T_exclusive'], '2018-09-01 00:00:00')
        self.assertEqual(p['R']['integer_seconds_then_divisor'], 86400)
        self.assertEqual(p['R']['rounding'], 'none_no_floor_no_calendar_day')
        self.assertEqual(p['outputs']['timestamp_format'], '%Y-%m-%d %H:%M:%S')
        self.assertEqual(p['outputs']['csv_boolean_literals'], ['true', 'false'])
        for key in ['builder_implemented', 'RFM_values_built', 'segmentation', 'training', 'dashboard']:
            self.assertFalse(p[key])

    def test_equality_approval_delivery_is_legal(self):
        row = fixture()['orders'][0]
        row['order_approved_at'] = row['order_delivered_customer_date']
        self.assertTrue(contract.event_decision(row)['history_eligible'])

    def test_reverse_approval_is_quarantined_by_rule(self):
        row = fixture()['orders'][0]
        for approval in ['2018-07-31 00:00:00', '2018-08-11 00:00:00']:
            row['order_approved_at'] = approval
            d = contract.event_decision(row)
            self.assertEqual(d['reason'], 'approval_clock_conflict')
            self.assertTrue(d['window_quarantine'])

    def test_missing_invalid_approval_is_flagged_not_replaced(self):
        for value in ['', 'invalid']:
            row = fixture()['orders'][0]; row['order_approved_at'] = value
            d = contract.event_decision(row)
            self.assertTrue(d['history_eligible'])
            self.assertTrue(d['approval_unknown'])

    def test_delivery_at_T_not_completed_not_quality_quarantine(self):
        row = fixture()['orders'][0]
        row['order_delivered_customer_date'] = '2018-09-01 00:00:00'
        d = contract.event_decision(row)
        self.assertEqual(d['reason'], 'delivery_at_or_after_T')
        self.assertFalse(d['window_quarantine'])

    def test_missing_delivery_is_window_quarantine(self):
        row = fixture()['orders'][0]; row['order_delivered_customer_date'] = ''
        self.assertTrue(contract.event_decision(row)['window_quarantine'])

    def test_before_purchase_delivery_is_window_quarantine(self):
        row = fixture()['orders'][0]; row['order_delivered_customer_date'] = '2018-07-01 00:00:00'
        self.assertEqual(contract.event_decision(row)['reason'], 'delivery_before_purchase')

    def test_purchase_T_is_not_history_or_universe(self):
        t = fixture(); t['orders'][0]['order_purchase_timestamp'] = '2018-09-01 00:00:00'
        result = contract.audit_support(t)
        self.assertEqual(result['history']['customer_universe'], 0)

    def test_unlocatable_purchase_stops(self):
        row = fixture()['orders'][0]; row['order_purchase_timestamp'] = ''
        with self.assertRaises(ValueError):
            contract.event_decision(row)

    def test_historical_customer_retained_as_inactive(self):
        t = fixture()
        t['orders'][0].update(order_purchase_timestamp='2017-08-01 00:00:00',
                              order_approved_at='2017-08-02 00:00:00',
                              order_delivered_customer_date='2017-08-10 00:00:00')
        result = contract.audit_support(t)
        self.assertEqual(result['history']['customer_universe'], 1)
        self.assertEqual(result['window']['active_customers'], 0)
        self.assertEqual(result['customer_state_support_only']['inactive_complete'], 1)

    def test_universe_not_filtered_for_missing_money_or_payment(self):
        t = fixture(); t['order_items'] = []; t['order_payments'] = []
        result = contract.audit_support(t)
        self.assertEqual(result['history']['customer_universe'], 1)
        self.assertEqual(result['window']['event_eligible_orders'], 1)
        self.assertEqual(result['customer_state_support_only']['active_money_unknown'], 1)

    def test_payment_missing_does_not_mask_product_M(self):
        t = fixture(); t['order_payments'] = []
        result = contract.audit_support(t)
        self.assertEqual(result['customer_state_support_only']['active_complete'], 1)
        self.assertEqual(result['window']['payments']['unknown_or_invalid_orders'], 1)

    def test_bad_price_does_not_delete_activity(self):
        t = fixture(); t['order_items'][0]['price'] = '-1.00'
        result = contract.audit_support(t)
        self.assertEqual(result['window']['event_eligible_orders'], 1)
        self.assertEqual(result['window']['price_unknown_orders'], 1)
        self.assertEqual(result['window']['zero_eligible_window_customers'], 0)

    def test_duplicate_item_key_masks_money_not_customer(self):
        t = fixture(); t['order_items'] *= 2
        result = contract.audit_support(t)
        self.assertEqual(result['history']['customer_universe'], 1)
        self.assertEqual(result['window']['price_unknown_orders'], 1)

    def test_mixed_clean_and_quarantined_orders_not_complete(self):
        t = fixture()
        t['orders'].append(dict(t['orders'][0], order_id='bad', order_approved_at='2018-08-12 00:00:00'))
        result = contract.audit_support(t)
        self.assertEqual(result['window']['event_eligible_orders'], 1)
        self.assertEqual(result['window_quarantine']['orders_linked_to_universe'], 1)
        self.assertEqual(result['customer_state_support_only']['active_with_quarantine'], 1)

    def test_quarantined_only_customer_not_silently_in_universe(self):
        t = fixture(); t['orders'][0]['order_approved_at'] = '2018-08-12 00:00:00'
        result = contract.audit_support(t)
        self.assertEqual(result['history']['customer_universe'], 0)
        self.assertEqual(result['window_quarantine']['orders_outside_universe'], 1)

    def test_zero_activity_with_quarantine_not_clean_zero(self):
        state = contract.activity_state(0, 0, 1)
        self.assertEqual(state['state'], 'inactive_with_quarantine')
        self.assertFalse(state['monetary_complete'])
        self.assertFalse(state['rfm_usable'])

    def test_clean_zero_retained_but_not_complete_numeric_RFM(self):
        state = contract.activity_state(0, 0, 0)
        self.assertEqual(state['state'], 'inactive_complete')
        self.assertTrue(state['monetary_complete'])
        self.assertFalse(state['rfm_usable'])

    def test_unknown_money_state_priority_and_invalid_counts(self):
        self.assertEqual(contract.activity_state(1, 1, 1)['state'], 'active_money_unknown')
        with self.assertRaises(ValueError):
            contract.activity_state(0, 1, 0)

    def test_missing_historical_identity_stops(self):
        t = fixture(); t['customers'] = []
        with self.assertRaises(ValueError):
            contract.audit_support(t)

    def test_source_binding_change_stops(self):
        spec = {'sources': [{'path': 'source', 'bytes': 1, 'sha256': 'old'}],
                'policy': contract.policy(), 'planned_schemas': contract.schemas()}
        with patch.object(contract.base, 'descriptor', return_value={'path': 'source', 'bytes': 1, 'sha256': 'new'}):
            with self.assertRaises(ValueError):
                contract.verify_sources(spec)

    def test_large_valid_lines_cannot_silently_overflow_aggregates(self):
        t = fixture()
        t['order_items'][0]['price'] = '47000000000000000.00'
        t['order_items'].append(dict(t['order_items'][0], order_item_id='2'))
        with self.assertRaisesRegex(ValueError, 'int64 subset guarantee'):
            contract.audit_support(t)

    def test_no_input_mutation_or_individual_outputs(self):
        t = fixture(); before = copy.deepcopy(t)
        result = contract.audit_support(t)
        self.assertEqual(t, before)
        self.assertNotIn('u1', str(result))
        self.assertFalse(result['acceptance']['individual_RFM_values_built'])
        self.assertFalse(result['acceptance']['private_dataset_created'])


if __name__ == '__main__':
    unittest.main()
