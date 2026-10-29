"""Source reconstruction, one-shot recovery and corruption tests for v2."""
import copy
import csv
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from scripts import rebuild_rfm_v2 as entry
from scripts import rfm_rebuild_reference as reference
from scripts import rfm_evaluation_contract as method
from tests.test_rfm_dataset_builder import fixture, empty_tables, add_order, build, specification


def evaluation():
    return {'format_version': 1, 'policy': method.policy(), 'planned_outputs': method.planned_outputs()}


class IndependentReferenceTests(unittest.TestCase):
    def check(self, tables):
        dataset = build(tables)
        receipt, rosters = reference.verify_dataset(tables, dataset)
        self.assertTrue(receipt['accepted'])
        self.assertEqual(receipt['cells_compared'], 16 * (len(dataset['customers']) + len(dataset['orders'])))
        return dataset, rosters

    def test_known_values_and_full_schema(self):
        dataset, _ = self.check(fixture())
        row = dataset['customers'][0]
        self.assertEqual((row['recency_seconds'], row['frequency_orders'], row['monetary_product_cents']),
                         (2678400, 1, 1000))

    def test_clock_precedence_boundaries_and_unknown_approval(self):
        mutations = [dict(purchase='2017-08-31 23:59:59'), dict(approval=''), dict(approval='invalid'),
                     dict(delivery=''), dict(delivery='2018-07-31 00:00:00'),
                     dict(delivery='2018-09-01 00:00:00'), dict(approval='2018-08-11 00:00:00'),
                     dict(status='canceled'), dict(purchase='2018-09-01 00:00:00')]
        for index, options in enumerate(mutations):
            with self.subTest(index=index):
                tables = fixture()
                add_order(tables, 'o2', 'c2', 'u2', **options)
                self.check(tables)

    def test_all_five_states_and_future_order(self):
        tables = fixture()
        add_order(tables, 'unknown', 'c2', 'u2', price=None)
        add_order(tables, 'active', 'c3', 'u3')
        add_order(tables, 'bad_active', 'c3', 'u3', approval='2018-07-01 00:00:00')
        add_order(tables, 'old', 'c4', 'u4', purchase='2017-01-01 00:00:00')
        add_order(tables, 'old_q', 'c5', 'u5', purchase='2017-01-01 00:00:00')
        add_order(tables, 'bad_inactive', 'c5', 'u5', delivery='')
        add_order(tables, 'future', 'c6', 'u6', purchase='2018-10-01 00:00:00')
        dataset, rosters = self.check(tables)
        self.assertEqual({r['activity_state'] for r in dataset['customers']}, set(entry.contract.policy()['activity_states']))
        self.assertNotIn('future', rosters['order_ids'])

    def test_duplicate_missing_invalid_zero_and_large_amounts(self):
        for value in ('0.00', '-1.00', '1.001', 'nan', '', '90071992547409.93'):
            with self.subTest(value=value):
                tables = fixture()
                tables['order_items'][0]['price'] = value
                self.check(tables)
        tables = fixture()
        tables['order_items'].append(copy.deepcopy(tables['order_items'][0]))
        self.check(tables)
        tables = fixture()
        tables['order_items'][0]['order_item_id'] = '0'
        tables['order_payments'] = []
        self.check(tables)

    def test_master_duplicates_and_unlocatable_purchase_rejected(self):
        for name in ('orders', 'customers'):
            tables = fixture()
            tables[name].append(copy.deepcopy(tables[name][0]))
            with self.assertRaises(ValueError):
                reference.reference_rows(tables)
        tables = fixture()
        tables['orders'][0]['order_purchase_timestamp'] = 'invalid'
        with self.assertRaises(ValueError):
            reference.reference_rows(tables)

    def test_equal_total_customer_swap_is_rejected(self):
        tables = fixture()
        add_order(tables, 'o2', 'c2', 'u2', price='20.00')
        dataset = build(tables)
        a, b = dataset['customers']
        a['monetary_product_cents'], b['monetary_product_cents'] = b['monetary_product_cents'], a['monetary_product_cents']
        with self.assertRaises(ValueError):
            reference.verify_dataset(tables, dataset)

    def test_missing_order_and_bool_instead_of_integer_rejected(self):
        tables = fixture()
        dataset = build(tables)
        dataset['orders'] = []
        with self.assertRaises(ValueError):
            reference.verify_dataset(tables, dataset)
        dataset = build(tables)
        dataset['customers'][0]['frequency_orders'] = True
        with self.assertRaises(ValueError):
            reference.verify_dataset(tables, dataset)

    def test_reference_does_not_call_builder_or_original_decision(self):
        tables = fixture()
        dataset = build(tables)
        with patch.object(entry.builder, 'build_dataset', side_effect=AssertionError), \
             patch.object(entry.contract, 'event_decision', side_effect=AssertionError), \
             patch.object(entry.contract, 'activity_state', side_effect=AssertionError):
            reference.verify_dataset(tables, dataset)


class RebuildExecutionTests(unittest.TestCase):
    def setUp(self):
        scratch = entry.ROOT / '.runtime' / 'rfm_rebuild_v2_synthetic'
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = scratch / uuid.uuid4().hex
        self.root.mkdir()
        def cleanup():
            target, parent = self.root.resolve(), scratch.resolve()
            if target == parent or not target.is_relative_to(parent):
                raise ValueError('Synthetic cleanup escaped its scratch directory')
            shutil.rmtree(target)
        self.addCleanup(cleanup)
        tables = fixture()
        dataset = build(tables)
        files = {entry.contract.SPEC: specification(), entry.EVALUATION: evaluation(),
                 entry.OLD_BUILD: {'results': dataset['summary']},
                 entry.OLD_G1: {'description': entry.description.describe_dataset(
                     dataset, evaluation(), expected_customer_ids=['u1'])}}
        for path, data in files.items():
            entry.base.immutable_write(self.root / path, data)
        for name, relative in entry.base.FILES.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=entry.base.COLUMNS[name])
                writer.writeheader()
                writer.writerows(tables[name])
        source_paths = [*files, *entry.base.FILES.values()]
        self.snapshot = lambda root: [entry.base.descriptor(root / p, root) for p in source_paths]
        self.mock_snapshot = patch.object(entry, '_snapshot', side_effect=self.snapshot)
        self.mock_snapshot.start()
        self.addCleanup(self.mock_snapshot.stop)
        spec = {'format_version': 1, 'policy': entry.policy(), 'sources': self.snapshot(self.root),
                'synthetic_verification': {'fixture_only': True}}
        entry.base.immutable_write(self.root / entry.SPEC, spec)
        log = self.root / entry.TEST_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('synthetic fixture; not an actual test receipt', encoding='utf-8')
        entry.base.immutable_write(self.root / entry.INPUT,
            {'specification': entry.base.descriptor(self.root / entry.SPEC, self.root),
             'test_log': entry.base.descriptor(log, self.root)})

    def test_ineligible_is_completed_and_verify_never_calls_cores(self):
        result = entry.run(self.root)
        self.assertEqual(result['G2'], 'ineligible')
        self.assertFalse((self.root / entry.FAILURE).exists())
        with patch.object(entry.builder, 'build_dataset', side_effect=AssertionError), \
             patch.object(entry.description, 'describe_dataset', side_effect=AssertionError), \
             patch.object(entry.candidate, 'evaluate_rule_candidate', side_effect=AssertionError):
            self.assertEqual(entry.verify(self.root), result)
        with self.assertRaises(ValueError):
            entry.run(self.root)

    def test_source_change_stops_before_build(self):
        with (self.root / entry.base.FILES['orders']).open('a') as stream:
            stream.write('\n')
        with patch.object(entry.builder, 'build_dataset', side_effect=AssertionError):
            with self.assertRaises(ValueError):
                entry.run(self.root)
        self.assertFalse((self.root / entry.RUN).exists())

    def test_changed_receipt_and_partial_namespace_rejected(self):
        (self.root / entry.TEST_LOG).write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            entry.run(self.root)
        with self.assertRaises(ValueError):
            entry._fresh(self.root)

    def test_modified_private_assignment_is_rejected(self):
        entry.run(self.root)
        path = self.root / entry.RUN / 'candidate' / 'customer_roster.csv'
        path.write_bytes(path.read_bytes().replace(b',1,1,1,', b',2,1,1,'))
        with self.assertRaises(ValueError):
            entry.verify(self.root)

    def test_partial_run_cannot_resume(self):
        (self.root / entry.RUN).mkdir()
        with self.assertRaises(ValueError):
            entry.run(self.root)

    def test_late_output_guard_failure_blocks_success_and_replay(self):
        original = entry.base.immutable_write
        def write(path, payload):
            if path == self.root / entry.GUARD:
                raise OSError('synthetic late failure')
            return original(path, payload)
        with patch.object(entry.base, 'immutable_write', side_effect=write):
            with self.assertRaises(OSError):
                entry.run(self.root)
        self.assertTrue((self.root / entry.REPORT).exists())
        self.assertTrue((self.root / entry.FAILURE).exists())
        with self.assertRaises(ValueError):
            entry.verify(self.root)
        with self.assertRaises(ValueError):
            entry.run(self.root)

    def test_aggregate_comparison_exact_types_and_frozen_float_tolerance(self):
        receipt = entry.compare_historical({'a': 1.0}, {'a': 1.0 + 1e-13})
        self.assertEqual(receipt['nonidentical_float_values_within_tolerance'], 1)
        for value in (True, 1.0, 2):
            with self.assertRaises(ValueError):
                entry.compare_historical({'a': value}, {'a': 1})
        with self.assertRaises(ValueError):
            entry.compare_historical({'a': 1.001}, {'a': 1.0})


if __name__ == '__main__':
    unittest.main()
