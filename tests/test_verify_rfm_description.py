"""Synthetic provenance checks; opaque CSV cannot become a real description."""
import copy
import csv
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import verify_rfm_description as entry
from tests import test_rfm_evaluation_spec as old_tests


class RFMDescriptionVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = old_tests.RFMEvaluationSpecTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        for relative in entry.IMPLEMENTATION:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'opaque synthetic implementation binding\n')
        self.fixture.freeze()
        self.fixture.audit()
        self.receipt = {
            'modules': entry.MODULES,
            'tests_by_module': {entry.MODULES[0]: 5, entry.MODULES[1]: 4},
            'tests_run': 9, 'errors': 0, 'failures': 0, 'skipped': 0,
            'successful': True, 'elapsed_seconds': 0.25,
            'source_bindings': entry.source_bindings(self.root),
        }
        self.write_receipt()

    def write_receipt(self):
        self.fixture.write(entry.RECEIPT, self.receipt)

    def verify(self):
        return entry.run(self.root, verify_synthetic=True)

    def snapshot(self):
        return self.fixture.snapshot()

    def test_single_synthetic_action_and_no_real_cli_action(self):
        for value in (False, 1, 'true'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                entry.run(self.root, verify_synthetic=value)
        for args in ([], ['--describe-real'], ['--verify-synthetic', '--input', 'other.csv']):
            with patch('sys.stderr'), self.subTest(args=args), self.assertRaises(SystemExit):
                entry.main(args)

    def test_exact_thirty_three_sources_and_frozen_method(self):
        spec = entry.specification(self.root)
        self.assertEqual(len(spec['sources']), 33)
        self.assertEqual(len({source['path'] for source in spec['sources']}), 33)
        self.assertIn(entry.prior.SPEC, [item['path'] for item in spec['sources']])
        self.assertIn(entry.prior.OUTPUT, [item['path'] for item in spec['sources']])
        self.assertEqual(spec['policy'], entry.policy())

    def test_success_records_actual_receipt_counts_without_real_description(self):
        result = self.verify()
        self.assertEqual(result['tests_run'], 9)
        report = entry.base.read_json(self.root / entry.OUTPUT)
        self.assertEqual(report['unit_tests']['tests_by_module'], self.receipt['tests_by_module'])
        self.assertTrue(report['accepted_dataset_metadata']['all_passed'])
        self.assertEqual(len(report['accepted_dataset_metadata']['checks']), 42)
        self.assertTrue(report['execution']['description_core_implemented'])
        self.assertFalse(report['execution']['real_descriptive_statistics_computed'])
        self.assertFalse(report['execution']['cutpoints_estimated'])
        self.assertEqual(report['execution']['model_fits'], 0)
        self.assertFalse((self.root / '.runtime/stage6_rfm_evaluation_v1').exists())

    def test_opaque_sources_never_parse_csv_replay_builder_or_read_values(self):
        blocked = AssertionError('Only source hashes and metadata may be read')
        with patch.object(csv, 'reader', side_effect=blocked), \
                patch.object(csv, 'DictReader', side_effect=blocked), \
                patch.object(entry.prior.base, 'read_tables', side_effect=blocked), \
                patch.object(entry.prior.prior, 'run', side_effect=blocked), \
                patch.object(entry.prior.prior, 'verify_sources', side_effect=blocked), \
                patch.object(entry.prior.prior.builder, 'build_dataset', side_effect=blocked), \
                patch.object(entry.artifacts, 'read_bundle', side_effect=blocked), \
                patch.object(entry.artifacts, 'verify_bundle', side_effect=blocked):
            self.verify()

    def test_public_report_has_no_private_bundle_or_receipt_fingerprints(self):
        self.verify()
        report = (self.root / entry.OUTPUT).read_text('utf-8')
        guard = entry.base.read_json(self.root / entry.GUARD)
        private = guard['prior_private_provenance']['private_bundle_guard']
        for descriptor in private.values():
            self.assertNotIn(descriptor['sha256'], report)
        self.assertNotIn(guard['synthetic_verification_receipt']['sha256'], report)
        self.assertNotIn('private_bundle_guard', report)

    def test_idempotent_verification_never_rewrites_existing_outputs(self):
        self.verify()
        before = self.snapshot()
        times = {path: path.stat().st_mtime_ns for path in self.root.rglob('*') if path.is_file()}
        self.verify()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(times, {path: path.stat().st_mtime_ns for path in times})

    def test_receipt_missing_sources_or_source_bytes_change_stops(self):
        self.receipt['source_bindings'].pop()
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'receipt source'):
            self.verify()
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_changed_new_core_or_test_bytes_cannot_reuse_receipt(self):
        for relative in entry.IMPLEMENTATION:
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'receipt source'):
                self.verify()
            path.write_bytes(original)

    def test_new_specification_cannot_shorten_complete_bindings(self):
        self.verify()
        shortened = entry.base.read_json(self.root / entry.SPEC)
        shortened['sources'].pop()
        self.fixture.write(entry.SPEC, shortened)
        with self.assertRaises(ValueError):
            entry.verify_sources(shortened, self.root)

    def test_original_frozen_source_list_or_audit_cannot_be_changed(self):
        for relative in (entry.prior.SPEC, entry.prior.OUTPUT):
            path = self.root / relative
            original = path.read_bytes()
            payload = entry.base.read_json(path)
            if relative == entry.prior.SPEC:
                payload['sources'].pop()
            else:
                payload['execution']['new_descriptive_statistics_computed'] = True
            self.fixture.write(relative, payload)
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(original)

    def test_prior_audit_status_scope_and_numeric_types_are_exact(self):
        path = self.root / entry.prior.OUTPUT
        original = path.read_bytes()
        mutations = (
            lambda data: data.update(format_version=True),
            lambda data: data['metadata_checks'].update(complete_twenty_original_sources=1),
            lambda data: data['execution'].update(model_fits=0.0),
            lambda data: data.update(status='description_already_done'),
        )
        for mutate in mutations:
            payload = entry.base.read_json(path)
            mutate(payload)
            self.fixture.write(entry.prior.OUTPUT, payload)
            with self.assertRaisesRegex(ValueError, 'Prior evaluation audit'):
                self.verify()
            path.write_bytes(original)

    def test_prior_private_guard_or_bundle_change_stops_before_new_outputs(self):
        for relative in (entry.prior.GUARD, entry.prior.prior.PRIVATE + '/customers.csv'):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(original)
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_receipt_failed_skipped_or_inconsistent_counts_are_rejected(self):
        original = copy.deepcopy(self.receipt)
        mutations = (
            lambda data: data.update(successful=False),
            lambda data: data.update(errors=1),
            lambda data: data.update(failures=1),
            lambda data: data.update(skipped=1),
            lambda data: data.update(tests_run=10),
            lambda data: data['tests_by_module'].update({entry.MODULES[0]: 0}),
            lambda data: data.update(modules=[entry.MODULES[0]]),
        )
        for mutate in mutations:
            self.receipt = copy.deepcopy(original)
            mutate(self.receipt)
            self.write_receipt()
            with self.assertRaises(ValueError):
                self.verify()

    def test_receipt_numeric_bool_float_impersonation_and_nonfinite_rejected(self):
        original = copy.deepcopy(self.receipt)
        for field, value in (('tests_run', 9.0), ('errors', False), ('successful', 1),
                             ('elapsed_seconds', 1), ('elapsed_seconds', float('inf'))):
            self.receipt = copy.deepcopy(original)
            self.receipt[field] = value
            if value == float('inf'):
                path = self.root / entry.RECEIPT
                path.write_text('{"elapsed_seconds":Infinity}', encoding='utf-8')
            else:
                self.write_receipt()
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.verify()

    def test_receipt_extra_or_duplicate_json_key_rejected(self):
        self.receipt['extra'] = True
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.verify()
        (self.root / entry.RECEIPT).write_text('{"tests_run":9,"tests_run":9}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.verify()

    def test_missing_receipt_does_not_create_outputs(self):
        (self.root / entry.RECEIPT).unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_partial_new_outputs_cannot_be_refrozen(self):
        self.fixture.write(entry.SPEC, {'partial': True})
        with self.assertRaisesRegex(ValueError, 'Partial'):
            self.verify()
        self.assertFalse((self.root / entry.GUARD).exists())
        self.assertFalse((self.root / entry.OUTPUT).exists())

    def test_unexpected_control_file_cannot_be_erased_or_ignored(self):
        self.verify()
        extra = self.root / entry.PRIVATE / 'extra'
        extra.write_bytes(b'keep evidence')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            self.verify()
        self.assertEqual(extra.read_bytes(), b'keep evidence')

    def test_changed_existing_report_or_guard_never_overwritten(self):
        self.verify()
        for relative in (entry.OUTPUT, entry.GUARD):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'Refusing'):
                self.verify()
            self.assertEqual(path.read_bytes(), original + b'\n')
            path.write_bytes(original)

    def test_before_after_changed_inputs_stop_before_writes(self):
        original_state = entry._state
        calls = []
        def changed_state(root):
            state = original_state(root)
            calls.append(True)
            if len(calls) == 2:
                state = copy.deepcopy(state)
                state[1]['synthetic_verification_receipt']['bytes'] += 1
            return state
        with patch.object(entry, '_state', side_effect=changed_state):
            with self.assertRaisesRegex(ValueError, 'changed during verification'):
                self.verify()
        self.assertFalse((self.root / entry.SPEC).exists())
        self.assertFalse((self.root / entry.GUARD).exists())
        self.assertFalse((self.root / entry.OUTPUT).exists())


if __name__ == '__main__':
    unittest.main()
