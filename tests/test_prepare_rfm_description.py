"""Synthetic full execution wiring; real description is never invoked."""
import copy
import contextlib
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import prepare_rfm_description as entry
from tests.test_rfm_description_sources import make_fixture, fixture_snapshot
from tests.test_rfm_dataset_builder import fixture, add_order, empty_tables


def five_states():
    tables = fixture()
    add_order(tables, 'inactive-old', 'c2', 'u2', purchase='2017-08-01 00:00:00',
              approval='', delivery='2017-08-02 00:00:00')
    add_order(tables, 'mixed-good', 'c3', 'u3')
    add_order(tables, 'mixed-quarantine', 'c3', 'u3', delivery='')
    add_order(tables, 'unknown-good', 'c4', 'u4', price=None)
    add_order(tables, 'inactive-quarantine-old', 'c5', 'u5', purchase='2017-08-01 00:00:00',
              approval='', delivery='2017-08-02 00:00:00')
    add_order(tables, 'inactive-quarantine-new', 'c5', 'u5', delivery='')
    add_order(tables, 'outside-quarantine', 'c6', 'outside', delivery='')
    add_order(tables, 'future', 'c7', 'future-only', purchase='2018-09-01 00:00:00',
              approval='', delivery='')
    add_order(tables, 'outside-cancelled', 'c8', 'outside-cancelled', status='canceled', delivery='')
    return tables


class PrepareRFMDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.scratch = entry.ROOT / '.runtime' / 'stage6_execution_preparation_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.patch = patch.object(entry.sources, 'metadata_snapshot', side_effect=fixture_snapshot)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.case = self.initialize(self.root, five_states())

    def cleanup(self):
        target = self.root.resolve()
        if target == self.scratch.resolve() or not target.is_relative_to(self.scratch.resolve()):
            raise ValueError('Synthetic cleanup escaped its private workspace')
        shutil.rmtree(target)

    def initialize(self, root, tables):
        case = make_fixture(root, tables)
        for relative in entry.IMPLEMENTATION:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic frozen execution implementation\n')
        receipt = {'modules': entry.MODULES, 'tests_by_module': {name: 1 for name in entry.MODULES},
                   'tests_run': 3, 'errors': 0, 'failures': 0, 'skipped': 0,
                   'successful': True, 'elapsed_seconds': 1.0, 'source_bindings': entry.source_bindings(root)}
        entry.base.immutable_write(root / entry.RECEIPT, receipt)
        return case

    def prepare(self):
        return entry.prepare(self.root)

    def execute(self):
        self.prepare()
        return entry.execute_prepared(self.root)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_prepare_only_freezes_full_forty_one_sources_and_does_not_parse_or_describe(self):
        with patch.object(entry.sources, 'read_inputs', side_effect=AssertionError('No real load')), \
                patch.object(entry.core, 'describe_dataset', side_effect=AssertionError('No real description')), \
                patch.object(entry.outputs, 'write_outputs', side_effect=AssertionError('No real output')):
            result = self.prepare()
        self.assertEqual(result['source_bindings'], 41)
        self.assertFalse((self.root / entry.DATASET).exists())
        self.assertFalse((self.root / entry.PUBLIC).exists())
        spec = entry.base.read_json(self.root / entry.SPEC)
        self.assertEqual(len(spec['sources']), 41)
        self.assertTrue(spec['policy']['current_round']['real_description_executed'] is False)

    def test_cli_only_prepare_no_execution_or_path_override(self):
        with patch.object(entry, 'prepare', return_value={'status': 'synthetic'}) as prepared, contextlib.redirect_stdout(io.StringIO()):
            entry.main(['--prepare'])
        prepared.assert_called_once_with()
        for args in ([], ['--describe'], ['--execute'], ['--prepare', '--root', 'elsewhere']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                entry.main(args)

    def test_identical_preparation_preserves_all_bytes(self):
        self.prepare()
        before = self.snapshot()
        self.prepare()
        self.assertEqual(before, self.snapshot())

    def test_synthetic_end_to_end_uses_single_core_call_and_retains_all_source_order_ids(self):
        with patch.object(entry.core, 'describe_dataset', wraps=entry.core.describe_dataset) as describe:
            self.execute()
        self.assertEqual(describe.call_count, 1)
        self.assertEqual(describe.call_args.kwargs['expected_customer_ids'],
                         [r['customer_unique_id'] for r in self.case['dataset']['customers']])
        guard = entry.base.read_json(self.root / entry.OUTPUT_GUARD)
        spec = entry.base.read_json(self.root / entry.SPEC)
        restored = entry.outputs.read_outputs(self.root / entry.DATASET, entry._provenance(self.root, spec))
        self.assertEqual(len(restored['customer_roster']), 5)
        self.assertTrue(all(v == 1 for v in restored['description']['routing_counts']['by_state'].values()))
        order_ids = {r['order_id'] for r in restored['order_roster']}
        self.assertIn('outside-quarantine', order_ids)
        self.assertIn('outside-cancelled', order_ids)
        self.assertNotIn('future', order_ids)
        public = (self.root / entry.PUBLIC).read_text('utf-8')
        for customer in self.case['dataset']['customers']:
            self.assertNotIn(json.dumps(customer['customer_unique_id']), public)
        for descriptor in guard['private_bundle_guard'].values():
            self.assertNotIn(descriptor['sha256'], public)
        self.assertEqual(set(guard['private_bundle_guard']), set(entry.outputs.FILES))

    def test_completed_verify_is_readonly_without_core_reexecution(self):
        self.execute()
        before = self.snapshot()
        with patch.object(entry.core, 'describe_dataset', side_effect=AssertionError('No new statistics')):
            result = entry.verify_completed(self.root)
        self.assertIn('without_core', result['status'])
        self.assertEqual(before, self.snapshot())

    def test_public_or_private_tamper_fails_before_loading_inputs(self):
        self.execute()
        for relative in (entry.PUBLIC, entry.DATASET + '/description.json', entry.OUTPUT_GUARD):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(path=relative), patch.object(entry.sources, 'read_inputs') as read:
                with self.assertRaises(ValueError):
                    entry.verify_completed(self.root)
                read.assert_not_called()
            path.write_bytes(original)

    def test_reexecution_stops_before_loading_and_preserves_successful_outputs(self):
        self.execute()
        before = self.snapshot()
        with patch.object(entry.sources, 'read_inputs') as read:
            with self.assertRaises(ValueError):
                entry.execute_prepared(self.root)
            read.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_existing_empty_execution_namespace_stops_prepare_without_parsing(self):
        (self.root / entry.DATASET).mkdir()
        with patch.object(entry.sources, 'read_inputs') as read, self.assertRaises(ValueError):
            self.prepare()
        read.assert_not_called()
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_partial_or_changed_preparation_is_not_regenerated(self):
        self.prepare()
        path = self.root / entry.INPUT_GUARD
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.prepare()
        path.write_bytes(original + b'\n')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_shortened_or_changed_synthetic_receipt_stops(self):
        path = self.root / entry.RECEIPT
        receipt = entry.base.read_json(path)
        for mutate in (lambda r: r['source_bindings'].pop(),
                       lambda r: r.update({'tests_run': True}),
                       lambda r: r.update({'errors': 1}),
                       lambda r: r.update({'elapsed_seconds': 1}),
                       lambda r: r['modules'].pop()):
            altered = copy.deepcopy(receipt)
            mutate(altered)
            path.write_bytes(entry.typed.json_bytes(altered))
            with self.assertRaises(ValueError):
                self.prepare()
        path.write_bytes(entry.typed.json_bytes(receipt))

    def test_implementation_or_source_change_after_prepare_fails_before_core(self):
        self.prepare()
        path = self.root / entry.IMPLEMENTATION[0]
        path.write_bytes(path.read_bytes() + b'changed')
        with patch.object(entry.core, 'describe_dataset') as describe, self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        describe.assert_not_called()

    def test_changed_source_during_core_stops_before_writes(self):
        self.prepare()
        original = entry.core.describe_dataset
        def describe(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.root / 'synthetic_public_sources/0.bin'
            path.write_bytes(path.read_bytes() + b'late source')
            return result
        with patch.object(entry.core, 'describe_dataset', side_effect=describe), \
                patch.object(entry.outputs, 'write_outputs') as write:
            with self.assertRaises(ValueError):
                entry.execute_prepared(self.root)
        write.assert_not_called()
        self.assertFalse((self.root / entry.PUBLIC).exists())
        self.assertTrue((self.root / entry.FAILURE).exists())

    def test_loader_or_core_failure_stops_without_success_or_replay(self):
        self.prepare()
        with patch.object(entry.sources, 'read_inputs', side_effect=ValueError('synthetic ID mismatch')), \
                patch.object(entry.core, 'describe_dataset') as describe:
            with self.assertRaises(ValueError):
                entry.execute_prepared(self.root)
        describe.assert_not_called()
        self.assertTrue((self.root / entry.FAILURE).exists())
        self.assertFalse((self.root / entry.PUBLIC).exists())
        with self.assertRaises(ValueError):
            entry.execute_prepared(self.root)

    def test_writer_failure_stops_before_publication(self):
        self.prepare()
        with patch.object(entry.outputs, 'write_outputs', side_effect=ValueError('synthetic writer failure')):
            with self.assertRaises(ValueError):
                entry.execute_prepared(self.root)
        self.assertFalse((self.root / entry.PUBLIC).exists())
        self.assertFalse((self.root / entry.OUTPUT_GUARD).exists())
        self.assertTrue((self.root / entry.FAILURE).exists())

    def test_public_write_failure_is_partial_not_success_and_cannot_resume(self):
        self.prepare()
        original = entry.base.immutable_write
        def write(path, payload):
            if Path(path) == self.root / entry.PUBLIC:
                raise OSError('synthetic public disk failure')
            return original(path, payload)
        with patch.object(entry.base, 'immutable_write', side_effect=write):
            with self.assertRaises(OSError):
                entry.execute_prepared(self.root)
        self.assertTrue((self.root / entry.DATASET).exists())
        self.assertFalse((self.root / entry.PUBLIC).exists())
        self.assertFalse((self.root / entry.OUTPUT_GUARD).exists())
        with self.assertRaises(ValueError):
            entry.verify_completed(self.root)
        with self.assertRaises(ValueError):
            entry.execute_prepared(self.root)

    def test_forged_nested_ID_is_rejected_before_publication(self):
        self.prepare()
        original = entry.core.describe_dataset
        def describe(*args, **kwargs):
            result = original(*args, **kwargs)
            result['shape_and_tail_diagnostics']['customer_unique_id'] = 'forbidden'
            return result
        with patch.object(entry.core, 'describe_dataset', side_effect=describe), self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        self.assertFalse((self.root / entry.PUBLIC).exists())

    def test_synthetic_ties_oracle_survives_full_persistence(self):
        root = self.root / 'oracle'
        root.mkdir()
        tables = empty_tables()
        for i, amount in enumerate((1, 1, 2, 9, 9)):
            add_order(tables, 'o' + str(i), 'c' + str(i), 'u' + str(i), price=f'{amount / 100:.2f}')
        self.initialize(root, tables)
        entry.prepare(root)
        entry.execute_prepared(root)
        report = entry.base.read_json(root / entry.PUBLIC)
        raw = report['description']['statistics_and_null_reasons']['raw']['monetary_product_cents']
        tail = report['description']['shape_and_tail_diagnostics']['M_ge_Q99']
        self.assertEqual(raw['sum'], 22)
        self.assertEqual(raw['empirical_quantiles']['99'], 9)
        self.assertEqual(tail['count'], 2)
        self.assertEqual(tail['tail_M_cents'], 18)


if __name__ == '__main__':
    unittest.main()
