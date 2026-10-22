"""Synthetic typed readback, masking, tamper and whole-bundle acceptance."""
import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import rfm_dataset_artifacts as artifacts
from tests.test_rfm_dataset_builder import add_order, build, fixture, specification


class RFMArtifactTests(unittest.TestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parents[1] / '.runtime'
        runtime.mkdir(exist_ok=True)
        temp = runtime / ('rfm_artifact_test_' + uuid.uuid4().hex)
        temp.mkdir()
        def cleanup():
            if not temp.resolve().is_relative_to(runtime.resolve()):
                raise ValueError('Test cleanup escaped private runtime')
            shutil.rmtree(temp)
        self.addCleanup(cleanup)
        self.output = temp / 'dataset'
        self.spec = specification()
        self.bindings = [{'path': 'reports/stage6/rfm_dataset_specification.json',
                          'bytes': 1, 'sha256': 'synthetic'}]
        self.dataset = build(fixture())

    def write(self):
        return artifacts.write_bundle(self.dataset, self.spec, self.bindings, self.output)

    def rewrite_manifest(self, mutate=None):
        path = self.output / 'manifest.json'
        manifest = json.loads(path.read_text('utf-8'))
        if mutate:
            mutate(manifest)
        manifest['private_bytes_sha'] = {name: artifacts._digest((self.output / name).read_bytes())
                                         for name in artifacts.FILES[:2]}
        path.write_bytes(artifacts.json_bytes(manifest))

    def test_full_typed_readback_and_three_file_guard(self):
        receipt = self.write()
        restored = artifacts.read_bundle(self.output, self.spec, self.bindings)
        self.assertTrue(artifacts._same(restored['customers'], self.dataset['customers']))
        self.assertTrue(artifacts._same(restored['orders'], self.dataset['orders']))
        self.assertEqual(restored['summary'], self.dataset['summary'])
        self.assertEqual(receipt['cells_compared'], 32)
        self.assertEqual(set(artifacts.bundle_guard(self.output)), set(artifacts.FILES))

    def test_nulls_are_empty_and_booleans_lowercase(self):
        tables = fixture()
        add_order(tables, 'q', delivery='', price=None, payment=None)
        self.dataset = build(tables)
        self.write()
        text = (self.output / 'customers.csv').read_text('utf-8')
        self.assertIn('active_with_quarantine,false,false', text)
        self.assertNotIn('None', text)
        self.assertIsNone(artifacts.read_bundle(self.output, self.spec, self.bindings)['customers'][0]['monetary_product_cents'])

    def test_float64_fraction_preserves_bits_and_17_digits(self):
        tables = fixture()
        tables['orders'][0].update(order_purchase_timestamp='2018-08-31 23:59:59',
                                  order_approved_at='2018-08-31 23:59:59',
                                  order_delivered_customer_date='2018-08-31 23:59:59')
        self.dataset = build(tables)
        self.write()
        self.assertIn(format(1 / 86400, '.17g'), (self.output / 'customers.csv').read_text('utf-8'))

    def test_inactive_empty_sum_and_measured_active_zero_are_distinct(self):
        tables = fixture()
        tables['order_items'][0]['price'] = '0.00'
        add_order(tables, 'old', 'c2', 'u2', purchase='2017-08-01 00:00:00',
                  approval='', delivery='2017-08-02 00:00:00')
        self.dataset = build(tables)
        self.write()
        restored = artifacts.read_bundle(self.output, self.spec, self.bindings)
        self.assertEqual([r['monetary_product_cents'] for r in restored['customers']], [0, 0])
        self.assertEqual([r['rfm_usable'] for r in restored['customers']], [True, False])

    def test_existing_empty_namespace_blocks_entire_write(self):
        self.output.mkdir()
        with self.assertRaises(ValueError):
            self.write()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_even_identical_existing_bundle_is_not_rewritten(self):
        self.write()
        before = artifacts.bundle_guard(self.output)
        with self.assertRaises(ValueError):
            self.write()
        self.assertEqual(before, artifacts.bundle_guard(self.output))

    def test_failure_before_publication_retains_private_stage_only(self):
        with patch.object(artifacts, 'read_bundle', side_effect=ValueError('synthetic readback failure')):
            with self.assertRaises(ValueError):
                self.write()
        self.assertFalse(self.output.exists())
        self.assertEqual(len(list(self.output.parent.glob('dataset.staging-*'))), 1)

    def test_failure_does_not_change_other_output_files(self):
        sentinel = self.output.parent / 'sentinel'
        sentinel.write_bytes(b'unchanged')
        self.dataset['customers'][0]['monetary_product_cents'] = 999
        with self.assertRaises(ValueError):
            self.write()
        self.assertEqual(sentinel.read_bytes(), b'unchanged')
        self.assertFalse(self.output.exists())

    def test_verify_is_read_only_and_checks_immutable_guard(self):
        self.write()
        guard = artifacts.bundle_guard(self.output)
        before = {name: (self.output / name).stat().st_mtime_ns for name in artifacts.FILES}
        artifacts.verify_bundle(self.output, self.spec, self.bindings, guard)
        self.assertEqual(before, {name: (self.output / name).stat().st_mtime_ns for name in artifacts.FILES})
        (self.output / 'customers.csv').write_bytes((self.output / 'customers.csv').read_bytes() + b'\n')
        with self.assertRaises(ValueError):
            artifacts.verify_bundle(self.output, self.spec, self.bindings, guard)

    def test_rehashed_customer_forgery_still_fails_semantics(self):
        self.write()
        path = self.output / 'customers.csv'
        path.write_bytes(path.read_bytes().replace(b',1000,', b',1001,'))
        self.rewrite_manifest()
        with self.assertRaisesRegex(ValueError, 'Customer R/F/M'):
            artifacts.read_bundle(self.output, self.spec, self.bindings)

    def test_schema_type_and_precision_corruptions_rejected(self):
        self.write()
        path = self.output / 'customers.csv'
        original = path.read_bytes()
        for before, after in ((b'true', b'True'), (b',1000,', b',1000.0,'),
                              (b',31,', b',31.000,'), (b',1000,', b',9223372036854775808,')):
            with self.subTest(after=after):
                path.write_bytes(original.replace(before, after))
                self.rewrite_manifest()
                with self.assertRaises(ValueError):
                    artifacts.read_bundle(self.output, self.spec, self.bindings)
        path.write_bytes(original)

    def test_duplicate_ids_reordered_ids_and_missing_population_rejected(self):
        for mutation in ('duplicate', 'missing', 'order'):
            dataset = copy.deepcopy(self.dataset)
            if mutation == 'duplicate':
                dataset['customers'].append(copy.deepcopy(dataset['customers'][0]))
            elif mutation == 'missing':
                dataset['customers'] = []
            else:
                dataset['orders'][0]['history_event_eligible'] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                artifacts.write_bundle(dataset, self.spec, self.bindings, self.output)

    def test_null_bool_int_float_and_overflow_writer_rejected(self):
        for field, value in (('rfm_usable', 1), ('frequency_orders', True),
                             ('recency_days', float('nan')), ('monetary_product_cents', -1),
                             ('frequency_orders', 2**63), ('S', None)):
            dataset = copy.deepcopy(self.dataset)
            dataset['customers'][0][field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                artifacts.write_bundle(dataset, self.spec, self.bindings, self.output)

    def test_extra_missing_or_reordered_columns_rejected(self):
        for mutation in ('extra', 'missing', 'reordered'):
            dataset = copy.deepcopy(self.dataset)
            row = dataset['orders'][0]
            if mutation == 'extra':
                row['extra'] = 0
            elif mutation == 'missing':
                del row['price_complete']
            else:
                dataset['orders'][0] = dict(reversed(list(row.items())))
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, KeyError)):
                artifacts.write_bundle(dataset, self.spec, self.bindings, self.output)

    def test_json_duplicate_keys_nonfinite_and_extra_files_rejected(self):
        self.write()
        path = self.output / 'manifest.json'
        original = path.read_bytes()
        for bad in (b'{"rows":0,"rows":0}', b'{"value":NaN}'):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):
                artifacts.read_bundle(self.output, self.spec, self.bindings)
        path.write_bytes(original)
        (self.output / 'extra').write_bytes(b'x')
        with self.assertRaises(ValueError):
            artifacts.read_bundle(self.output, self.spec, self.bindings)

    def test_changed_sources_and_manifest_counters_rejected(self):
        self.write()
        with self.assertRaises(ValueError):
            artifacts.read_bundle(self.output, self.spec, [])
        self.rewrite_manifest(lambda m: m['rows'].update({'customers.csv': 99}))
        with self.assertRaises(ValueError):
            artifacts.read_bundle(self.output, self.spec, self.bindings)

    def test_ledger_future_evidence_does_not_enter_customer_metrics(self):
        tables = fixture()
        add_order(tables, 'future-delivery', delivery='2018-09-01 00:00:00', price='999.00')
        add_order(tables, 'future-purchase', purchase='2018-09-01 00:00:00',
                  approval='', delivery='', price='888.00')
        self.dataset = build(tables)
        self.write()
        restored = artifacts.read_bundle(self.output, self.spec, self.bindings)
        self.assertEqual(len(restored['orders']), 2)
        self.assertEqual(restored['customers'][0]['frequency_orders'], 1)
        self.assertEqual(restored['customers'][0]['monetary_product_cents'], 1000)

    def test_aggregate_population_states_and_masked_money_forgery_rejected(self):
        for group, key in (('history', 'customer_universe'), ('customer_states', 'active_complete'),
                           ('customer_money_conservation', 'known_product_cents_masked_customer_subsets')):
            dataset = copy.deepcopy(self.dataset)
            dataset['summary'][group][key] = 999999
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, 'Aggregate'):
                artifacts.write_bundle(dataset, self.spec, self.bindings, self.output)

    def test_fabricated_missing_delivery_cannot_remove_population(self):
        row = self.dataset['orders'][0]
        row.update(primary_exclusion_reason='missing_or_invalid_delivery',
                   history_event_eligible=False, window_event_eligible=False, window_quarantine=True)
        self.dataset['customers'] = []
        with self.assertRaisesRegex(ValueError, 'contradicts ledger clocks'):
            self.write()

    def test_json_bool_float_cannot_impersonate_integer_metadata(self):
        self.write()
        for mutate in (lambda m: m['rows'].update({'customers.csv': True}),
                       lambda m: m['readback_acceptance'].update({'cells_compared': 32.0}),
                       lambda m: m['source_bindings'][0].update({'bytes': True})):
            original = (self.output / 'manifest.json').read_bytes()
            self.rewrite_manifest(mutate)
            with self.assertRaises(ValueError):
                artifacts.read_bundle(self.output, self.spec, self.bindings)
            (self.output / 'manifest.json').write_bytes(original)


if __name__ == '__main__':
    unittest.main()
