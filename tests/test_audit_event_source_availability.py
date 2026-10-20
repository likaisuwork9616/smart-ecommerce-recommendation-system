"""Regression checks for source-clock eligibility and immutable audit evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from scripts import audit_event_source_availability as audit


def fixture():
    return pd.DataFrame([
        ['a', 'c', 'canceled', '2018-02-01', '2018-02-01 12:00:00',
         None, None, '2018-02-01'],
        ['b', 'c', 'delivered', '2018-04-30', '2018-04-30 23:59:59',
         '2018-05-01', '2018-05-02', '2018-04-29'],
        ['future', 'c', 'unavailable', '2018-04-30', '2018-05-01',
         None, None, '2018-05-10'],
    ], columns=audit.ORDER_COLUMNS)


class SourceClockTests(unittest.TestCase):
    def test_cutoff_is_exclusive_and_future_status_cannot_enter_profile(self):
        orders = fixture()
        result = audit.orders_profile(orders)
        self.assertEqual(result['approval_population']['eligible_orders'], 2)
        self.assertEqual(result['approval_population']['final_status_counts'],
                         {'canceled': 1, 'delivered': 1})
        self.assertEqual(result['approval_population']['carrier_event_before_cutoff'], 0)
        self.assertEqual(result['approval_population']['delivery_event_before_cutoff'], 0)
        orders.loc[2, 'order_status'] = 'future-label-must-not-enter'
        self.assertEqual(audit.orders_profile(orders), result)

    def test_invalid_approval_purchase_and_reversed_clocks_are_not_eligible(self):
        orders = fixture().iloc[[0]].copy()
        extra = pd.concat([orders] * 4, ignore_index=True)
        extra.order_id = ['bad_approval', 'bad_purchase', 'missing_purchase', 'reversed']
        extra.loc[0, 'order_approved_at'] = 'invalid'
        extra.loc[1, 'order_purchase_timestamp'] = 'invalid'
        extra.loc[2, 'order_purchase_timestamp'] = None
        extra.loc[3, 'order_purchase_timestamp'] = '2018-02-02'
        result = audit.orders_profile(pd.concat([orders, extra], ignore_index=True))
        pop = result['approval_population']
        self.assertEqual(pop['approval_before_cutoff'], 4)
        self.assertEqual(pop['missing_purchase_before_cutoff'], 2)
        self.assertEqual(pop['reversed_purchase_approval_before_cutoff'], 1)
        self.assertEqual(pop['eligible_orders'], 1)

    def test_promise_is_calendar_day_not_earlier_midnight_on_approval_day(self):
        result = audit.orders_profile(fixture())
        self.assertEqual(result['by_approval_month']['2018-02']['negative_promise_days'], 0)
        self.assertEqual(result['by_approval_month']['2018-04']['negative_promise_days'], 1)

    def test_missing_and_invalid_promises_are_not_nonnegative_promise_proof(self):
        orders = fixture().iloc[:2].copy()
        orders.loc[0, 'order_estimated_delivery_date'] = None
        orders.loc[1, 'order_estimated_delivery_date'] = 'invalid'
        result = audit.orders_profile(orders)
        self.assertEqual(result['approval_population']['promise_present'], 0)
        self.assertEqual(result['approval_population']['promise_missing'], 2)
        self.assertEqual(result['eligible_timestamp_parse_failures']['order_estimated_delivery_date'], 1)

    def test_final_status_does_not_establish_observed_clocks_or_actual_capture(self):
        orders = fixture()
        first = audit.orders_profile(orders)
        orders['order_status'] = 'canceled'
        second = audit.orders_profile(orders)
        self.assertEqual(first['availability'], second['availability'])
        self.assertNotEqual(first['approval_population']['final_status_counts'],
                            second['approval_population']['final_status_counts'])
        availability = second['availability']
        self.assertEqual(availability['orders_with_provable_cancellation_known_before_query_t'], 0)
        self.assertIsNone(availability['actual_cancellation_event_capture_rate'])
        self.assertIsNone(availability['actual_non_delivery_closure_event_capture_rate'])
        self.assertIsNone(availability['actual_promise_revision_capture_rate'])

    def test_new_clock_column_requires_reacceptance_instead_of_reporting_missing(self):
        orders = fixture()
        orders['canceled_at'] = '2018-02-02'
        with self.assertRaisesRegex(ValueError, 'schema changed'):
            audit.orders_profile(orders)
        with self.assertRaisesRegex(ValueError, 'schema changed'):
            audit.orders_profile(fixture().drop(columns='order_status'))

    def test_ambiguous_join_keys_are_rejected(self):
        for value in (None, 'a'):
            with self.subTest(value=value):
                orders = fixture()
                orders.loc[1, 'order_id'] = value
                with self.assertRaisesRegex(ValueError, 'join keys'):
                    audit.orders_profile(orders)

    def test_new_timezone_semantics_are_rejected(self):
        orders = fixture().iloc[:1].copy()
        orders['order_approved_at'] = '2018-02-01T12:00:00Z'
        with self.assertRaisesRegex(ValueError, 'timezone-naive'):
            audit.orders_profile(orders)

    def test_empty_pre_cutoff_cohort_has_no_made_up_range_or_events(self):
        result = audit.orders_profile(fixture().iloc[[2]].copy())
        self.assertEqual(result['by_approval_month'], {})
        self.assertEqual(result['approval_population']['eligible_orders'], 0)
        self.assertIsNone(result['approval_population']['earliest_approval'])


class EvidenceIntegrityTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_keys_and_nonfinite_constants(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'evidence.json'
            for content in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}'):
                with self.subTest(content=content):
                    path.write_text(content, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        audit.read_json(path)

    def test_identical_rerun_preserves_bytes_and_different_report_cannot_overwrite(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            path.write_text('{"status":"ok"}', encoding='utf-8')
            original = path.read_bytes()
            audit.immutable_json(path, {'status': 'ok'})
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
                audit.immutable_json(path, {'status': 'changed'})
            self.assertEqual(path.read_bytes(), original)

    def test_source_hash_change_is_rejected_even_if_byte_count_is_same(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'source.json'
            path.write_text('{}', encoding='utf-8')
            spec = {'analysis': audit.ANALYSIS, 'contract': audit.acceptance_contract(),
                    'protected_sources': [audit.descriptor(path, root)], 'analysis_code': []}
            self.assertEqual(audit.verify_sources(spec, root), 1)
            path.write_text('[]', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Changed protected source'):
                audit.verify_sources(spec, root)

    def test_database_claim_requires_success_and_exact_orders_snapshot(self):
        raw = [{'path': 'data/raw/olist/olist_orders_dataset.csv', 'sha256': 'expected'}]
        database = {'status': 'ok', 'errors': [], 'tables': [], 'metadata_checks': {},
            'orders_snapshot_comparison': {'all_values_equal': True, 'raw_sha256': 'other',
                                           'rows': 2, 'columns': 8, 'values_compared': 16}}
        with self.assertRaisesRegex(ValueError, 'does not match'):
            audit.sanitized_database(database, raw)
        database['orders_snapshot_comparison']['raw_sha256'] = 'expected'
        database['orders_snapshot_comparison']['values_compared'] = 15
        with self.assertRaisesRegex(ValueError, 'denominator differs'):
            audit.sanitized_database(database, raw)
        database['status'] = 'partial'
        with self.assertRaisesRegex(ValueError, 'successful'):
            audit.sanitized_database(database, raw)

    def test_public_source_artifact_paths_are_not_published(self):
        evidence = {'new_accepted_event_sources': 0, 'decision': 'pending_data_no_training',
                    'public_sources': [{'url': 'https://example.test', 'artifacts': [{'path': 'private'}]}]}
        result = audit.sanitized_public(evidence)
        self.assertEqual(result['public_sources'], [{'url': 'https://example.test'}])
        evidence['new_accepted_event_sources'] = 1
        with self.assertRaisesRegex(ValueError, 'updated acceptance'):
            audit.sanitized_public(evidence)

    def test_database_table_schema_must_match_even_with_exact_orders_comparison(self):
        raw = [{'path': 'data/raw/olist/olist_orders_dataset.csv', 'sha256': 'expected',
                'rows': 2, 'columns': ['order_id', 'order_status']}]
        database = {'status': 'ok', 'errors': [], 'metadata_checks': {},
            'tables': [{'name': 'orders', 'kind': 'BASE TABLE', 'rows': 2,
                        'columns': [{'name': 'order_id'}, {'name': 'order_status'}]}],
            'orders_snapshot_comparison': {'all_values_equal': True, 'raw_sha256': 'expected',
                                           'rows': 2, 'columns': 2, 'values_compared': 4}}
        self.assertEqual(audit.sanitized_database(database, raw)['table_count'], 1)
        database['tables'][0]['columns'].append({'name': 'canceled_at'})
        with self.assertRaisesRegex(ValueError, 'table schema or row counts differ'):
            audit.sanitized_database(database, raw)


if __name__ == '__main__':
    unittest.main()
