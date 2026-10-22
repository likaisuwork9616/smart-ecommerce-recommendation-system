"""Synthetic RFM population, amount and temporal-isolation acceptance tests."""
import copy
import json
import unittest

from scripts import audit_rfm_feasibility as base
from scripts import freeze_rfm_dataset_spec as contract
from scripts import rfm_dataset_builder as builder


def specification():
    return {'format_version': 1, 'policy': contract.policy(),
            'planned_schemas': contract.schemas(), 'columns_read': copy.deepcopy(base.COLUMNS)}


def empty_tables():
    return {name: [] for name in base.COLUMNS}


def add_order(tables, oid='o1', cid='c1', uid='u1', *,
              purchase='2018-08-01 00:00:00', approval='2018-08-02 00:00:00',
              delivery='2018-08-10 00:00:00', status='delivered',
              price='10.00', freight='2.00', payment='12.00'):
    tables['orders'].append({
        'order_id': oid, 'customer_id': cid, 'order_status': status,
        'order_purchase_timestamp': purchase, 'order_approved_at': approval,
        'order_delivered_customer_date': delivery})
    if not any(row['customer_id'] == cid for row in tables['customers']):
        tables['customers'].append({'customer_id': cid, 'customer_unique_id': uid})
    if price is not None:
        tables['order_items'].append({'order_id': oid, 'order_item_id': '1',
                                      'price': price, 'freight_value': freight})
    if payment is not None:
        tables['order_payments'].append({
            'order_id': oid, 'payment_sequential': '1', 'payment_type': 'credit_card',
            'payment_installments': '12', 'payment_value': payment})
    return tables


def fixture():
    return add_order(empty_tables())


def build(tables):
    return builder.build_dataset(tables, specification())


class RFMDatasetBuilderTests(unittest.TestCase):
    def test_basic_frozen_schema_order_and_python_types(self):
        result = build(fixture())
        self.assertEqual(set(result), {'customers', 'orders', 'summary'})
        customer, order = result['customers'][0], result['orders'][0]
        self.assertEqual(list(customer), [name for name, _ in contract.schemas()['customers.csv']])
        self.assertEqual(list(order), [name for name, _ in contract.schemas()['order_decisions.csv']])
        self.assertEqual(customer['activity_state'], 'active_complete')
        self.assertEqual(customer['frequency_orders'], 1)
        self.assertEqual(customer['monetary_product_cents'], 1000)
        self.assertEqual(customer['recency_days'], 31.0)
        self.assertIs(type(customer['frequency_orders']), int)
        self.assertIs(type(customer['monetary_product_cents']), int)
        self.assertIs(type(customer['recency_days']), float)
        self.assertIs(type(customer['rfm_usable']), bool)
        self.assertEqual(order['payment_difference_cents'], 0)
        self.assertTrue(all(result['summary']['invariants'].values()))

    def test_exact_recency_seconds_and_unrounded_days(self):
        tables = add_order(empty_tables(), purchase='2018-08-31 23:59:59',
                           approval='2018-08-31 23:59:59', delivery='2018-08-31 23:59:59')
        row = build(tables)['customers'][0]
        self.assertEqual(row['last_window_purchase_at'], '2018-08-31 23:59:59')
        self.assertEqual(row['recency_seconds'], 1)
        self.assertEqual(row['recency_days'], 1 / 86400.0)
        self.assertNotEqual(row['recency_days'], 0)

    def test_S_is_inclusive_with_365_elapsed_days(self):
        tables = add_order(empty_tables(), purchase='2017-09-01 00:00:00',
                           approval='2017-09-01 00:00:00', delivery='2017-09-02 00:00:00')
        row = build(tables)['customers'][0]
        self.assertEqual(row['recency_seconds'], 365 * 86400)
        self.assertEqual(row['recency_days'], 365.0)

    def test_before_S_retains_clean_inactive_customer_without_borrowing_R(self):
        tables = add_order(empty_tables(), purchase='2017-08-31 23:59:59',
                           approval='2017-09-01 00:00:00', delivery='2017-09-02 00:00:00')
        row = build(tables)['customers'][0]
        self.assertEqual(row['activity_state'], 'inactive_complete')
        for key in ('last_window_purchase_at', 'recency_seconds', 'recency_days'):
            self.assertIsNone(row[key])
        self.assertEqual(row['frequency_orders'], 0)
        self.assertEqual(row['monetary_product_cents'], 0)
        self.assertTrue(row['monetary_complete'])
        self.assertFalse(row['rfm_usable'])

    def test_cross_S_window_uses_only_eligible_window_purchase_and_money(self):
        tables = fixture()
        add_order(tables, 'old', purchase='2017-08-01 00:00:00',
                  approval='2017-08-02 00:00:00', delivery='2017-08-10 00:00:00', price='999.00')
        result = build(tables)
        self.assertEqual(result['summary']['history']['event_eligible_orders'], 2)
        self.assertEqual(result['customers'][0]['frequency_orders'], 1)
        self.assertEqual(result['customers'][0]['monetary_product_cents'], 1000)
        self.assertEqual(result['customers'][0]['recency_days'], 31.0)

    def test_purchase_T_and_future_customers_are_not_in_outputs(self):
        tables = fixture()
        add_order(tables, 'future', 'future_c', 'future_u', purchase='2018-09-01 00:00:00',
                  approval='2018-09-02 00:00:00', delivery='2018-09-10 00:00:00')
        result = build(tables)
        self.assertEqual([row['customer_unique_id'] for row in result['customers']], ['u1'])
        self.assertEqual([row['order_id'] for row in result['orders']], ['o1'])
        self.assertEqual(result['summary']['source']['purchase_at_or_after_T_orders'], 1)

    def test_future_events_for_existing_customer_cannot_change_RFM(self):
        tables = fixture()
        original = build(tables)['customers']
        add_order(tables, 'future', purchase='2018-09-15 00:00:00',
                  approval='2018-09-16 00:00:00', delivery='2018-09-20 00:00:00', price='1000.00')
        self.assertEqual(build(tables)['customers'], original)

    def test_unmapped_future_identity_allowed_but_never_enters_population(self):
        tables = fixture()
        add_order(tables, 'future', 'future_c', '', purchase='2018-09-01 00:00:00',
                  approval='', delivery='2018-09-10 00:00:00')
        tables['customers'].pop()
        result = build(tables)
        self.assertEqual(len(result['customers']), 1)
        self.assertEqual(result['summary']['source']['unmapped_future_orders'], 1)

    def test_T_delivery_retained_as_audit_evidence_without_quarantine_or_feature(self):
        tables = fixture()
        original = build(tables)['customers']
        add_order(tables, 'uncompleted', purchase='2018-08-31 00:00:00',
                  approval='2018-09-02 00:00:00', delivery='2018-09-03 00:00:00', price='1000.00')
        result = build(tables)
        self.assertEqual(result['customers'], original)
        row = next(row for row in result['orders'] if row['order_id'] == 'uncompleted')
        self.assertEqual(row['approval_at'], '2018-09-02 00:00:00')
        self.assertEqual(row['delivery_at'], '2018-09-03 00:00:00')
        self.assertEqual(row['primary_exclusion_reason'], 'delivery_at_or_after_T')
        self.assertFalse(row['window_quarantine'])
        self.assertFalse(row['window_event_eligible'])

    def test_future_approval_conflict_is_evidence_not_last_purchase(self):
        tables = fixture()
        add_order(tables, 'q', purchase='2018-08-30 00:00:00',
                  approval='2018-09-02 00:00:00', delivery='2018-08-31 00:00:00')
        result = build(tables)
        customer = result['customers'][0]
        order = next(row for row in result['orders'] if row['order_id'] == 'q')
        self.assertEqual(order['approval_at'], '2018-09-02 00:00:00')
        self.assertEqual(order['primary_exclusion_reason'], 'approval_clock_conflict')
        self.assertEqual(customer['last_window_purchase_at'], '2018-08-01 00:00:00')
        self.assertEqual(customer['frequency_orders'], 1)
        self.assertIsNone(customer['monetary_product_cents'])

    def test_missing_items_keeps_F_and_mother_without_payment_fallback(self):
        tables = fixture()
        tables['order_items'].clear()
        result = build(tables)
        row = result['customers'][0]
        self.assertEqual(row['frequency_orders'], 1)
        self.assertEqual(row['recency_days'], 31.0)
        self.assertEqual(row['activity_state'], 'active_money_unknown')
        self.assertEqual(row['window_price_unknown_orders'], 1)
        self.assertIsNone(row['monetary_product_cents'])
        self.assertEqual(result['orders'][0]['payment_cents'], 1200)
        self.assertIsNone(result['orders'][0]['product_cents'])
        self.assertFalse(row['rfm_usable'])
        self.assertFalse(row['monetary_complete'])

    def test_invalid_product_variants_are_unknown_not_dropped_or_zero(self):
        for value in ('', '-1.00', '1.005', 'NaN', '1e2', '92233720368547758.08'):
            with self.subTest(value=value):
                tables = fixture()
                tables['order_items'][0]['price'] = value
                row = build(tables)['customers'][0]
                self.assertEqual(row['frequency_orders'], 1)
                self.assertIsNone(row['monetary_product_cents'])
                self.assertEqual(row['activity_state'], 'active_money_unknown')

    def test_valid_zero_price_is_complete_active_money_not_unknown(self):
        tables = add_order(empty_tables(), price='0.00', freight='0.00', payment='0.00')
        row = build(tables)['customers'][0]
        self.assertEqual(row['activity_state'], 'active_complete')
        self.assertEqual(row['frequency_orders'], 1)
        self.assertEqual(row['monetary_product_cents'], 0)
        self.assertTrue(row['monetary_complete'])
        self.assertTrue(row['rfm_usable'])

    def test_unknown_history_money_does_not_invent_window_activity_or_mask_clean_zero(self):
        tables = add_order(empty_tables(), purchase='2017-08-01 00:00:00',
                           approval='', delivery='2017-08-10 00:00:00', price=None, payment=None)
        row = build(tables)['customers'][0]
        self.assertEqual(row['activity_state'], 'inactive_complete')
        self.assertEqual(row['monetary_product_cents'], 0)
        self.assertEqual(row['window_price_unknown_orders'], 0)
        self.assertEqual(row['window_approval_missing_or_invalid_orders'], 0)
        self.assertEqual(row['window_payment_missing_or_invalid_orders'], 0)
        self.assertEqual(row['window_freight_missing_or_invalid_orders'], 0)

    def test_quality_counts_use_window_eligible_orders_and_quarantine_is_separate(self):
        tables = fixture()
        add_order(tables, 'q', approval='', delivery='', price=None, payment=None)
        row = build(tables)['customers'][0]
        self.assertEqual(row['window_quarantined_orders'], 1)
        self.assertEqual(row['window_price_unknown_orders'], 0)
        self.assertEqual(row['window_approval_missing_or_invalid_orders'], 0)
        self.assertEqual(row['window_payment_missing_or_invalid_orders'], 0)
        self.assertEqual(row['window_freight_missing_or_invalid_orders'], 0)

    def test_missing_payment_is_optional_and_does_not_mask_product_M(self):
        tables = fixture()
        tables['order_payments'].clear()
        result = build(tables)
        self.assertEqual(result['customers'][0]['monetary_product_cents'], 1000)
        self.assertEqual(result['customers'][0]['window_payment_missing_or_invalid_orders'], 1)
        self.assertTrue(result['customers'][0]['rfm_usable'])
        self.assertIsNone(result['orders'][0]['payment_difference_cents'])

    def test_invalid_freight_is_optional_and_does_not_mask_product_M(self):
        tables = fixture()
        tables['order_items'][0]['freight_value'] = '-1.00'
        result = build(tables)
        self.assertEqual(result['customers'][0]['monetary_product_cents'], 1000)
        self.assertEqual(result['customers'][0]['window_freight_missing_or_invalid_orders'], 1)
        self.assertTrue(result['customers'][0]['rfm_usable'])
        self.assertIsNone(result['orders'][0]['payment_difference_cents'])

    def test_invalid_approval_is_nonblocking_and_never_imputed(self):
        for value in ('', 'not-a-clock', '2018-8-2 00:00:00'):
            with self.subTest(value=value):
                tables = fixture()
                tables['orders'][0]['order_approved_at'] = value
                result = build(tables)
                self.assertTrue(result['customers'][0]['rfm_usable'])
                self.assertEqual(result['customers'][0]['window_approval_missing_or_invalid_orders'], 1)
                self.assertIsNone(result['orders'][0]['approval_at'])
                self.assertTrue(result['orders'][0]['approval_missing_or_invalid'])

    def test_mixed_eligible_and_quarantined_retains_subset_R_F_and_masks_M(self):
        tables = fixture()
        add_order(tables, 'q', delivery='', price='999.00')
        result = build(tables)
        row = result['customers'][0]
        self.assertEqual(row['activity_state'], 'active_with_quarantine')
        self.assertEqual(row['frequency_orders'], 1)
        self.assertEqual(row['recency_days'], 31.0)
        self.assertEqual(row['window_quarantined_orders'], 1)
        self.assertIsNone(row['monetary_product_cents'])
        conservation = result['summary']['customer_money_conservation']
        self.assertEqual(conservation['published_customer_product_cents'], 0)
        self.assertEqual(conservation['known_product_cents_masked_customer_subsets'], 1000)
        self.assertEqual(conservation['eligible_window_product_cents_on_known_orders'], 1000)
        self.assertTrue(conservation['known_product_cents_equal_published_plus_masked_known'])

    def test_inactive_with_quarantine_is_not_clean_zero_money(self):
        tables = add_order(empty_tables(), purchase='2017-08-01 00:00:00',
                           approval='2017-08-02 00:00:00', delivery='2017-08-10 00:00:00')
        add_order(tables, 'q', delivery='')
        row = build(tables)['customers'][0]
        self.assertEqual(row['activity_state'], 'inactive_with_quarantine')
        self.assertEqual(row['frequency_orders'], 0)
        self.assertIsNone(row['recency_days'])
        self.assertIsNone(row['monetary_product_cents'])
        self.assertFalse(row['monetary_complete'])

    def test_price_unknown_has_priority_over_window_quarantine(self):
        tables = fixture()
        tables['order_items'].clear()
        add_order(tables, 'q', delivery='')
        row = build(tables)['customers'][0]
        self.assertEqual(row['activity_state'], 'active_money_unknown')
        self.assertEqual(row['window_price_unknown_orders'], 1)
        self.assertEqual(row['window_quarantined_orders'], 1)

    def test_only_quarantined_customer_stays_outside_universe_but_in_ledger(self):
        tables = add_order(empty_tables(), delivery='')
        result = build(tables)
        self.assertEqual(result['customers'], [])
        self.assertEqual(len(result['orders']), 1)
        self.assertEqual(result['summary']['window_quarantine']['orders_outside_universe'], 1)

    def test_all_exclusion_reasons_and_precedence_are_preserved(self):
        cases = (
            ('status', {'status': 'canceled', 'delivery': ''}, 'status_not_delivered'),
            ('missing', {'delivery': ''}, 'missing_or_invalid_delivery'),
            ('reverse', {'delivery': '2018-07-31 00:00:00'}, 'delivery_before_purchase'),
            ('future', {'approval': '2018-09-03 00:00:00', 'delivery': '2018-09-02 00:00:00'}, 'delivery_at_or_after_T'),
            ('approval', {'approval': '2018-07-31 00:00:00'}, 'approval_clock_conflict'),
        )
        tables = fixture()
        for oid, updates, _ in cases:
            add_order(tables, oid, oid + '_c', oid + '_u', **updates)
        result = build(tables)
        reasons = {row['order_id']: row['primary_exclusion_reason'] for row in result['orders']}
        for oid, _, reason in cases:
            self.assertEqual(reasons[oid], reason)
        self.assertEqual(len(result['orders']), 6)
        self.assertEqual(len(result['customers']), 1)
        self.assertEqual(sum(result['summary']['history']['mutually_exclusive_primary_reasons'].values()), 6)

    def test_distinct_orders_not_detail_rows_installments_or_payment_rows(self):
        tables = fixture()
        tables['order_items'].append({'order_id': 'o1', 'order_item_id': '2', 'price': '0.01', 'freight_value': '0.00'})
        tables['order_payments'].append({
            'order_id': 'o1', 'payment_sequential': '2', 'payment_type': 'voucher',
            'payment_installments': '100', 'payment_value': '0.02'})
        result = build(tables)
        self.assertEqual(result['customers'][0]['frequency_orders'], 1)
        self.assertEqual(result['customers'][0]['monetary_product_cents'], 1001)
        self.assertEqual(result['orders'][0]['payment_cents'], 1202)
        self.assertEqual(result['orders'][0]['payment_difference_cents'], 1)

    def test_signed_reconciliation_preserves_differences_without_fixing_M(self):
        tables = fixture()
        tables['order_payments'][0]['payment_value'] = '11.98'
        add_order(tables, 'o2', 'c2', 'u2', payment='12.01')
        result = build(tables)
        self.assertEqual([row['monetary_product_cents'] for row in result['customers']], [1000, 1000])
        self.assertEqual([row['payment_difference_cents'] for row in result['orders']], [-2, 1])
        summary = result['summary']['reconciliation']['window_event_eligible']
        self.assertEqual(summary['sum_payment_minus_items_freight_cents'], -1)
        self.assertEqual(summary['nonzero_difference_orders'], 2)
        self.assertEqual(summary['absolute_difference_above_one_cent_orders'], 1)
        self.assertFalse(summary['one_cent_is_business_acceptance_tolerance'])

    def test_duplicate_item_pair_is_unknown_without_dropping_population(self):
        tables = fixture()
        tables['order_items'].append(copy.deepcopy(tables['order_items'][0]))
        result = build(tables)
        self.assertEqual(result['customers'][0]['frequency_orders'], 1)
        self.assertIsNone(result['customers'][0]['monetary_product_cents'])
        self.assertIsNone(result['orders'][0]['freight_cents'])
        self.assertEqual(result['summary']['money_quality']['items']['duplicate_key_groups'], 1)

    def test_duplicate_payment_pair_does_not_mask_product_M(self):
        tables = fixture()
        tables['order_payments'].append(copy.deepcopy(tables['order_payments'][0]))
        result = build(tables)
        self.assertEqual(result['customers'][0]['monetary_product_cents'], 1000)
        self.assertTrue(result['customers'][0]['rfm_usable'])
        self.assertIsNone(result['orders'][0]['payment_cents'])

    def test_invalid_detail_sequence_marks_amount_unknown(self):
        for value in ('', '0', '-1', '1.0'):
            with self.subTest(value=value):
                tables = fixture()
                tables['order_items'][0]['order_item_id'] = value
                result = build(tables)
                self.assertIsNone(result['customers'][0]['monetary_product_cents'])
                self.assertEqual(result['customers'][0]['frequency_orders'], 1)

    def test_per_order_product_aggregate_overflow_is_unknown(self):
        tables = fixture()
        tables['order_items'][0].update(price='92233720368547758.07', freight_value='0.00')
        tables['order_items'].append({'order_id': 'o1', 'order_item_id': '2', 'price': '0.01', 'freight_value': '0.00'})
        tables['order_payments'].clear()
        result = build(tables)
        self.assertEqual(result['customers'][0]['frequency_orders'], 1)
        self.assertIsNone(result['customers'][0]['monetary_product_cents'])
        self.assertEqual(result['summary']['money_quality']['items']['amount_quality']['price']['aggregate_overflow_orders'], 1)

    def test_source_money_support_overflow_stops_instead_of_unsafe_customer_sum(self):
        tables = fixture()
        tables['order_items'][0].update(price='92233720368547758.07', freight_value='0.00')
        tables['order_payments'].clear()
        add_order(tables, 'o2', 'c2', 'u2', price='0.01', freight='0.00', payment=None)
        with self.assertRaisesRegex(ValueError, 'conservative int64'):
            build(tables)

    def test_checked_sum_enforces_real_int64_bounds_and_types(self):
        self.assertEqual(builder._checked_sum((builder.INT64_MAX - 1, 1)), builder.INT64_MAX)
        with self.assertRaises(OverflowError):
            builder._checked_sum((builder.INT64_MAX, 1))
        with self.assertRaises(OverflowError):
            builder._checked_sum((builder.INT64_MIN, -1), nonnegative=False)
        for values in ((True,), (1.0,), (-1,)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                builder._checked_sum(values)

    def test_shared_unique_customer_mapping_combines_distinct_order_ids(self):
        tables = fixture()
        add_order(tables, 'o2', 'c2', 'u1', price='0.01')
        result = build(tables)
        self.assertEqual(len(result['customers']), 1)
        self.assertEqual(result['customers'][0]['frequency_orders'], 2)
        self.assertEqual(result['customers'][0]['monetary_product_cents'], 1001)

    def test_output_is_canonical_sorted_despite_source_order(self):
        tables = add_order(empty_tables(), 'z', 'z_c', 'z_u')
        add_order(tables, 'a', 'a_c', 'a_u')
        result = build(tables)
        self.assertEqual([row['order_id'] for row in result['orders']], ['a', 'z'])
        self.assertEqual([row['customer_unique_id'] for row in result['customers']], ['a_u', 'z_u'])
        reversed_tables = {name: list(reversed(rows)) for name, rows in tables.items()}
        self.assertEqual(result, build(reversed_tables))

    def test_source_tables_and_specification_are_unchanged(self):
        tables, spec = fixture(), specification()
        original_tables, original_spec = copy.deepcopy(tables), copy.deepcopy(spec)
        result = builder.build_dataset(tables, spec)
        self.assertEqual(tables, original_tables)
        self.assertEqual(spec, original_spec)
        result['orders'][0]['order_id'] = 'changed-output'
        self.assertEqual(tables, original_tables)

    def test_unlocatable_purchase_stops_even_if_order_otherwise_excluded(self):
        for value in ('', '2018-08-01', '2018-02-30 00:00:00'):
            with self.subTest(value=value):
                tables = fixture()
                tables['orders'][0].update(order_purchase_timestamp=value, order_status='canceled')
                with self.assertRaisesRegex(ValueError, 'Unlocatable purchase'):
                    build(tables)

    def test_unmapped_pre_T_identity_stops_even_if_order_ineligible(self):
        for missing in ('mapping', 'unique_id'):
            with self.subTest(missing=missing):
                tables = fixture()
                tables['orders'][0]['order_status'] = 'canceled'
                if missing == 'mapping':
                    tables['customers'].clear()
                else:
                    tables['customers'][0]['customer_unique_id'] = ''
                with self.assertRaisesRegex(ValueError, 'Unmapped historical'):
                    build(tables)

    def test_duplicate_or_empty_required_master_keys_stop(self):
        for name, key in (('orders', 'order_id'), ('customers', 'customer_id')):
            for problem in ('duplicate', 'empty'):
                with self.subTest(name=name, problem=problem):
                    tables = fixture()
                    if problem == 'duplicate':
                        tables[name].append(copy.deepcopy(tables[name][0]))
                    else:
                        tables[name][0][key] = ''
                    with self.assertRaisesRegex(ValueError, 'master key'):
                        build(tables)

    def test_changed_contract_or_source_schema_and_nonstring_raw_stop(self):
        for part in ('policy', 'schema', 'columns', 'raw', 'table'):
            with self.subTest(part=part):
                tables, spec = fixture(), specification()
                if part == 'policy':
                    spec['policy']['S_inclusive'] = '2018-01-01 00:00:00'
                elif part == 'schema':
                    spec['planned_schemas']['customers.csv'].reverse()
                elif part == 'columns':
                    tables['orders'][0].pop('order_status')
                elif part == 'raw':
                    tables['order_items'][0]['price'] = 1.0
                else:
                    tables['reviews'] = []
                with self.assertRaises(ValueError):
                    builder.build_dataset(tables, spec)

    def test_empty_sources_have_zero_population_and_no_fake_money(self):
        result = build(empty_tables())
        self.assertEqual(result['customers'], [])
        self.assertEqual(result['orders'], [])
        self.assertEqual(result['summary']['history']['customer_universe'], 0)
        self.assertEqual(result['summary']['window']['price']['sum_cents_on_valid_orders'], None)
        self.assertTrue(all(result['summary']['invariants'].values()))

    def test_summary_has_aggregates_without_private_ids_or_digests(self):
        tables = add_order(empty_tables(), 'private-order-identifier', 'private-customer-key', 'private-unique-id')
        summary = build(tables)['summary']
        encoded = json.dumps(summary, allow_nan=False, sort_keys=True)
        for value in ('private-order-identifier', 'private-customer-key', 'private-unique-id', 'sha256', 'digest'):
            self.assertNotIn(value, encoded)
        self.assertEqual(set(summary), {
            'source', 'history', 'window', 'window_quarantine', 'customer_states',
            'customer_money_conservation', 'reconciliation', 'money_quality', 'invariants'})

    def test_orphan_detail_rows_are_reported_without_affecting_customer(self):
        tables = fixture()
        expected = build(tables)['customers']
        tables['order_items'].append({'order_id': 'orphan', 'order_item_id': '1', 'price': '999.00', 'freight_value': '0.00'})
        result = build(tables)
        self.assertEqual(result['customers'], expected)
        self.assertEqual(result['summary']['money_quality']['items']['quality']['orphan_order_rows'], 1)

    def test_known_money_conservation_separates_masked_unknown_and_complete(self):
        tables = fixture()
        add_order(tables, 'mixed_good', 'c2', 'u2', price='3.00')
        add_order(tables, 'mixed_unknown', 'c2', 'u2', price=None)
        add_order(tables, 'old', 'c3', 'u3', purchase='2017-08-01 00:00:00',
                  approval='2017-08-02 00:00:00', delivery='2017-08-10 00:00:00')
        result = build(tables)
        money = result['summary']['customer_money_conservation']
        self.assertEqual(money['eligible_window_product_cents_on_known_orders'], 1300)
        self.assertEqual(money['published_customer_product_cents'], 1000)
        self.assertEqual(money['known_product_cents_masked_customer_subsets'], 300)
        self.assertEqual(money['eligible_window_product_unknown_orders'], 1)
        self.assertEqual(money['inactive_complete_zero_customers'], 1)
        self.assertFalse(money['unknown_product_amounts_are_zero_filled'])


if __name__ == '__main__':
    unittest.main()
