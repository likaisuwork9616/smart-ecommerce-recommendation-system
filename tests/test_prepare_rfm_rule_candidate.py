"""Synthetic G2 preparation/dispatch/publication; no real execution occurs."""
import contextlib
import copy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import prepare_rfm_rule_candidate as entry
from tests.test_rfm_rule_candidate_sources import make_fixture, fixture_snapshot
from tests.test_rfm_description_sources import fixture_snapshot as description_snapshot
from tests.test_rfm_dataset_builder import add_order, empty_tables


def balanced_tables():
    tables = empty_tables()
    cutoff = datetime(2018, 9, 1)
    for level in range(1, 6):
        stamp = (cutoff - timedelta(seconds=level)).strftime('%Y-%m-%d %H:%M:%S')
        for index in range(100):
            uid = f'balanced-{level}-{index:03d}'
            for order in range(level):
                add_order(tables, uid + '-' + str(order), 'c-' + uid, uid,
                          purchase=stamp, approval=stamp, delivery=stamp,
                          price=f'{level}.00' if order == 0 else '0.00', freight='0.00', payment='0.00')
    return tables


class PrepareRFMRuleCandidateTests(unittest.TestCase):
    def setUp(self):
        self.scratch = entry.ROOT / '.runtime' / 'stage6_G2_execution_preparation_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        for owner, name, function in ((entry.sources, 'metadata_snapshot', fixture_snapshot),
                                      (entry.sources.description_sources, 'metadata_snapshot', description_snapshot)):
            handle = patch.object(owner, name, side_effect=function)
            handle.start()
            self.addCleanup(handle.stop)
        self.case = self.initialize(self.root)

    def cleanup(self):
        target, parent = self.root.resolve(), self.scratch.resolve()
        if target == parent or not target.is_relative_to(parent):
            raise ValueError('Synthetic cleanup escaped its private workspace')
        shutil.rmtree(target)

    def initialize(self, root, tables=None):
        case = make_fixture(root, tables)
        for relative in entry.IMPLEMENTATION:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic frozen G2 execution implementation\n')
        receipt = {'modules': entry.MODULES, 'tests_by_module': {name: 1 for name in entry.MODULES},
                   'test_ids': sorted(name + '.Synthetic.test_case' for name in entry.MODULES),
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
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_preparation_binds_57_sources_without_reading_or_assigning(self):
        blocked = AssertionError('Preparation is metadata only')
        with patch.object(entry.sources, 'read_inputs', side_effect=blocked), \
                patch.object(entry.core, 'evaluate_rule_candidate', side_effect=blocked), \
                patch.object(entry.outputs, 'write_outputs', side_effect=blocked), \
                patch.object(entry.sources.description_entry, 'verify_completed', side_effect=blocked):
            result = self.prepare()
        self.assertEqual(result['source_bindings'], 57)
        spec = entry.base.read_json(self.root / entry.SPEC)
        self.assertEqual(len({r['path'] for r in spec['sources']}), 57)
        self.assertEqual(spec['policy'], entry.policy())
        self.assertEqual(spec['output_schema'], entry.outputs._schema())
        self.assertFalse((self.root / entry.DATASET).exists())
        self.assertFalse((self.root / entry.PUBLIC).exists())

    def test_cli_only_prepare_without_execution_or_path_override(self):
        with patch.object(entry, 'prepare', return_value={'status': 'synthetic'}) as prepared, \
                contextlib.redirect_stdout(io.StringIO()):
            entry.main(['--prepare'])
        prepared.assert_called_once_with()
        for args in ([], ['--execute'], ['--verify'], ['--prepare', '--root', 'elsewhere'],
                     ['--prepare', '--input', 'other.csv']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                entry.main(args)

    def test_identical_preparation_does_not_rewrite_or_refreeze(self):
        self.prepare()
        before = self.snapshot()
        times = {p: p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        self.prepare()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(times, {p: p.stat().st_mtime_ns for p in times})

    def test_synthetic_full_source_to_one_core_to_private_public_readback(self):
        with patch.object(entry.core, 'evaluate_rule_candidate', wraps=entry.core.evaluate_rule_candidate) as core:
            result = self.execute()
        self.assertEqual(core.call_count, 1)
        self.assertEqual(core.call_args.kwargs['expected_customer_ids'],
                         [r['customer_unique_id'] for r in self.case['dataset']['customers']])
        self.assertIs(core.call_args.kwargs['g1_accepted'], True)
        self.assertEqual(result['candidate_gate'], 'ineligible')
        self.assertFalse((self.root / entry.FAILURE).exists())
        spec = entry.base.read_json(self.root / entry.SPEC)
        restored = entry.outputs.read_outputs(self.root / entry.DATASET, entry._provenance(self.root, spec))
        self.assertEqual(len(restored['customer_roster']), 5)
        self.assertEqual(restored['aggregate']['routing_counts']['by_state'],
                         dict.fromkeys(self.case['dataset']['summary']['customer_states'], 1))
        order_ids = {r['order_id'] for r in restored['order_roster']}
        self.assertIn('outside-quarantine', order_ids)
        self.assertIn('outside-cancelled', order_ids)
        self.assertNotIn('future', order_ids)
        receipt = result['readback_acceptance']
        self.assertEqual(receipt['roster_cells_compared'],
                         len(restored['customer_roster']) * 9 + len(restored['order_roster']) * 11)

    def test_ineligible_completed_diagnostic_has_no_technical_failure_or_recut(self):
        result = self.execute()
        self.assertEqual(result['candidate_gate'], 'ineligible')
        report = entry.base.read_json(self.root / entry.PUBLIC)
        self.assertEqual(report['aggregate']['gate_status']['G2'], 'ineligible')
        self.assertTrue(report['aggregate']['failed_checks'])
        self.assertFalse((self.root / entry.FAILURE).exists())
        before = self.snapshot()
        with patch.object(entry.core, 'evaluate_rule_candidate') as core, self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        core.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_balanced_synthetic_candidate_pass_is_preserved_after_roundtrip(self):
        root = self.root / 'balanced'
        root.mkdir()
        self.initialize(root, balanced_tables())
        entry.prepare(root)
        result = entry.execute_prepared(root)
        self.assertEqual(result['candidate_gate'], 'passed')
        report = entry.base.read_json(root / entry.PUBLIC)['aggregate']
        self.assertEqual(report['reference_n'], 500)
        self.assertEqual(report['failed_checks'], [])
        for axis in entry.core.AXES:
            self.assertEqual([r['n'] for r in report['axes'][axis]['bin_counts']], [100] * 5)

    def test_completed_verify_is_readonly_with_both_cores_forbidden(self):
        self.execute()
        before = self.snapshot()
        blocked = AssertionError('No core replay')
        with patch.object(entry.core, 'evaluate_rule_candidate', side_effect=blocked), \
                patch.object(entry.sources.description_entry.core, 'describe_dataset', side_effect=blocked):
            result = entry.verify_completed(self.root)
        self.assertIn('without_core', result['status'])
        self.assertEqual(before, self.snapshot())

    def test_public_has_no_customer_order_ID_or_private_fingerprints(self):
        self.execute()
        public = (self.root / entry.PUBLIC).read_text('utf-8')
        for row in self.case['dataset']['customers']:
            self.assertNotIn(json.dumps(row['customer_unique_id']), public)
        for row in self.case['dataset']['orders']:
            self.assertNotIn(json.dumps(row['order_id']), public)
        guard = entry.base.read_json(self.root / entry.OUTPUT_GUARD)
        for desc in guard['private_bundle_guard'].values():
            self.assertNotIn(desc['sha256'], public)

    def test_completed_output_tamper_stops_before_loading(self):
        self.execute()
        for relative in (entry.PUBLIC, entry.DATASET + '/candidate.json', entry.OUTPUT_GUARD):
            path = self.root / relative
            before = path.read_bytes()
            path.write_bytes(before + b'\n')
            with self.subTest(path=relative), patch.object(entry.sources, 'read_inputs') as read, self.assertRaises(ValueError):
                entry.verify_completed(self.root)
            read.assert_not_called()
            path.write_bytes(before)

    def test_reexecution_rejects_before_loading_and_preserves_bytes(self):
        self.execute()
        before = self.snapshot()
        with patch.object(entry.sources, 'read_inputs') as read, self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        read.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_existing_empty_output_namespace_blocks_prepare(self):
        (self.root / entry.DATASET).mkdir()
        with patch.object(entry.sources, 'read_inputs') as read, self.assertRaises(ValueError):
            self.prepare()
        read.assert_not_called()
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_abandoned_staging_blocks_prepare_and_future_execute(self):
        path = self.root / (entry.DATASET + '.staging-synthetic')
        path.mkdir()
        with self.assertRaises(ValueError):
            self.prepare()
        with self.assertRaises(ValueError):
            entry.execute_prepared(self.root)

    def test_partial_or_different_preparation_is_not_regenerated(self):
        self.prepare()
        path = self.root / entry.INPUT_GUARD
        before = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.prepare()
        path.write_bytes(before + b'\n')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_receipt_source_ID_count_type_skip_and_duration_fail_closed(self):
        path = self.root / entry.RECEIPT
        receipt = entry.base.read_json(path)
        mutations = (lambda r: r['source_bindings'].pop(),
                     lambda r: r['test_ids'].pop(), lambda r: r['test_ids'].append(r['test_ids'][0]),
                     lambda r: r.update(tests_run=True), lambda r: r.update(errors=1),
                     lambda r: r.update(skipped=1), lambda r: r.update(successful=1),
                     lambda r: r.update(elapsed_seconds=1),
                     lambda r: r['tests_by_module'].update({entry.MODULES[0]: True}))
        for mutation in mutations:
            altered = copy.deepcopy(receipt)
            mutation(altered)
            path.write_bytes(entry.typed.json_bytes(altered))
            with self.subTest(receipt=altered), self.assertRaises(ValueError):
                self.prepare()
            self.assertFalse((self.root / entry.SPEC).exists())
        path.write_bytes(entry.typed.json_bytes(receipt))

    def test_implementation_change_after_prepare_stops_before_loader_or_core(self):
        self.prepare()
        path = self.root / entry.IMPLEMENTATION[0]
        path.write_bytes(path.read_bytes() + b'changed')
        with patch.object(entry.sources, 'read_inputs') as read, \
                patch.object(entry.core, 'evaluate_rule_candidate') as core, self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        read.assert_not_called()
        core.assert_not_called()

    def test_changed_source_during_core_stops_before_writer(self):
        self.prepare()
        original = entry.core.evaluate_rule_candidate
        def evaluate(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.root / entry.IMPLEMENTATION[0]
            path.write_bytes(path.read_bytes() + b'late source')
            return result
        with patch.object(entry.core, 'evaluate_rule_candidate', side_effect=evaluate), \
                patch.object(entry.outputs, 'write_outputs') as writer, self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        writer.assert_not_called()
        self.assertTrue((self.root / entry.FAILURE).exists())
        self.assertFalse((self.root / entry.PUBLIC).exists())

    def test_loader_failure_is_technical_failure_without_core_or_replay(self):
        self.prepare()
        with patch.object(entry.sources, 'read_inputs', side_effect=ValueError('synthetic roster mismatch')), \
                patch.object(entry.core, 'evaluate_rule_candidate') as core, self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        core.assert_not_called()
        self.assertTrue((self.root / entry.FAILURE).exists())
        self.assertFalse((self.root / entry.PUBLIC).exists())
        with self.assertRaises(ValueError):
            entry.execute_prepared(self.root)

    def test_writer_failure_stops_before_publication(self):
        self.prepare()
        with patch.object(entry.outputs, 'write_outputs', side_effect=ValueError('synthetic output error')), self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        self.assertFalse((self.root / entry.PUBLIC).exists())
        self.assertFalse((self.root / entry.OUTPUT_GUARD).exists())
        self.assertTrue((self.root / entry.FAILURE).exists())

    def test_publication_failure_leaves_partial_evidence_and_blocks_resume(self):
        self.prepare()
        original = entry.base.immutable_write
        def write(path, payload):
            if Path(path) == self.root / entry.PUBLIC:
                raise OSError('synthetic public disk failure')
            return original(path, payload)
        with patch.object(entry.base, 'immutable_write', side_effect=write), self.assertRaises(OSError):
            entry.execute_prepared(self.root)
        self.assertTrue((self.root / entry.DATASET).exists())
        self.assertFalse((self.root / entry.PUBLIC).exists())
        self.assertFalse((self.root / entry.OUTPUT_GUARD).exists())
        with self.assertRaises(ValueError):
            entry.verify_completed(self.root)
        with self.assertRaises(ValueError):
            entry.execute_prepared(self.root)

    def test_forged_nested_ID_or_changed_assignments_reject_before_publication(self):
        self.prepare()
        original = entry.core.evaluate_rule_candidate
        def forged(*args, **kwargs):
            result = original(*args, **kwargs)
            result['aggregate']['routing_counts']['customer_unique_id'] = 'forbidden'
            return result
        with patch.object(entry.core, 'evaluate_rule_candidate', side_effect=forged), self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        self.assertFalse((self.root / entry.PUBLIC).exists())

    def test_public_exists_but_guard_write_failure_is_not_success_or_resumable(self):
        self.prepare()
        original = entry.base.immutable_write
        def write(path, payload):
            if Path(path) == self.root / entry.OUTPUT_GUARD:
                raise OSError('synthetic final guard disk failure')
            return original(path, payload)
        with patch.object(entry.base, 'immutable_write', side_effect=write), self.assertRaises(OSError):
            entry.execute_prepared(self.root)
        self.assertTrue((self.root / entry.DATASET).exists())
        self.assertTrue((self.root / entry.PUBLIC).exists())
        self.assertFalse((self.root / entry.OUTPUT_GUARD).exists())
        self.assertTrue((self.root / entry.FAILURE).exists())
        before = self.snapshot()
        with self.assertRaises(ValueError):
            entry.verify_completed(self.root)
        with self.assertRaises(ValueError):
            entry.execute_prepared(self.root)
        self.assertEqual(before, self.snapshot())

    def test_changed_candidate_gate_in_guard_is_rejected_without_recomputation(self):
        self.execute()
        path = self.root / entry.OUTPUT_GUARD
        guard = entry.base.read_json(path)
        guard['candidate_gate'] = 'passed'
        path.write_bytes(entry.typed.json_bytes(guard))
        with patch.object(entry.core, 'evaluate_rule_candidate', side_effect=AssertionError('No core')), self.assertRaises(ValueError):
            entry.verify_completed(self.root)

    def test_changed_source_during_completed_readback_is_rejected(self):
        self.execute()
        original = entry.outputs.verify_outputs
        def verify(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.root / entry.IMPLEMENTATION[0]
            path.write_bytes(path.read_bytes() + b'late source')
            return result
        with patch.object(entry.outputs, 'verify_outputs', side_effect=verify), self.assertRaises(ValueError):
            entry.verify_completed(self.root)
        self.assertFalse((self.root / entry.FAILURE).exists())

    def test_source_change_during_prepare_stops_before_writes(self):
        original = entry.sources.metadata_snapshot
        calls = 0
        def snapshot(root):
            nonlocal calls
            calls += 1
            result = original(root)
            if calls == 2:
                result = copy.deepcopy(result)
                result['accepted_rows']['customers.csv'] += 1
            return result
        with patch.object(entry.sources, 'metadata_snapshot', side_effect=snapshot), self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.root / entry.SPEC).exists())


if __name__ == '__main__':
    unittest.main()
