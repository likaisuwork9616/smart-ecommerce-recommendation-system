"""Synthetic metadata/receipt/publication checks for the G2-only verifier.

The prior preparation verifier is replaced by an opaque forty-one-file fixture;
the new runner itself reads real JSON metadata and hashes the four opaque bundle
files.  No customer CSV, real descriptor or real candidate is invoked.
"""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import verify_rfm_rule_candidate as entry


def _probe(identity, behavior='pass'):
    """Actual unittest cases used to exercise receipt collection without recursion."""
    class Probe(unittest.TestCase):
        def id(self):
            return identity

        def runTest(self):
            if behavior == 'skip':
                self.skipTest('synthetic skip must not be accepted')
            if behavior == 'fail':
                self.fail('synthetic failure must not be accepted')
            if behavior == 'error':
                raise RuntimeError('synthetic error must not be accepted')
    return Probe('runTest')


class RFMRuleCandidateVerificationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = entry.ROOT / '.runtime' / 'stage6_rule_candidate_verification_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.source_paths = [f'synthetic_sources/source_{i:02d}.bin' for i in range(41)]
        for index, relative in enumerate(self.source_paths):
            self.write_bytes(relative, f'opaque frozen source {index}\n'.encode())
        for relative in entry.IMPLEMENTATION:
            self.write_bytes(relative, b'opaque new synthetic implementation binding\n')
        self.write(entry.prior.SPEC, {'synthetic': 'prepared specification'})
        self.write(entry.prior.PREFLIGHT, {'synthetic': 'accepted preflight'})
        self.write(entry.prior.INPUT_GUARD, {'synthetic': 'private prepared provenance'})
        self.gates = {'G0': 'passed', 'G1': 'ready_for_aggregate_review',
                      'G2': 'not_executed', 'G3': 'not_executed', 'temporal': 'pending_data'}
        self.readback = {'synthetic_four_file_readback': True}
        self.write(entry.prior.PUBLIC, {'description': {'gate_status': self.gates},
                                        'readback_acceptance': self.readback})
        self.write(entry.ACCEPTANCE, {
            'gate_status': self.gates, 'readback_acceptance': self.readback,
            'decision': 'description_accepted_next_synthetic_rule_candidate_implementation_no_real_cuts_or_groups',
            'completed_verification': {'core_calls': 0, 'output_guard_valid': True},
            'source_bindings_before_after_match': True,
        })
        for index, name in enumerate(entry.prior.outputs.FILES):
            self.write_bytes(entry.prior.DATASET + '/' + name,
                             f'opaque private bundle {index}; not parseable CSV/JSON\n'.encode())
        self.refresh_completed_guard()
        self.prepared = patch.object(entry.prior, 'verify_prepared', side_effect=self.synthetic_prepared)
        self.prepared.start()
        self.addCleanup(self.prepared.stop)
        self.receipt = {
            'modules': entry.MODULES,
            'tests_by_module': {name: 1 for name in entry.MODULES},
            'test_ids': [name + '.Synthetic.test_case' for name in entry.MODULES],
            'tests_run': 2, 'errors': 0, 'failures': 0, 'skipped': 0,
            'successful': True, 'elapsed_seconds': 0.125,
        }
        self.suites = patch.object(entry, '_run_suites', return_value=(self.receipt, 'opaque actual test log\n'))
        self.mock_suites = self.suites.start()
        self.addCleanup(self.suites.stop)
        self.cases = patch.object(entry, '_run_cases', return_value=entry._expected_cases())
        self.cases.start()
        self.addCleanup(self.cases.stop)

    def cleanup(self):
        target, parent = self.root.resolve(), self.scratch.resolve()
        if target == parent or not target.is_relative_to(parent):
            raise ValueError('Synthetic cleanup escaped its private workspace')
        shutil.rmtree(target)

    def write(self, relative, value):
        self.write_bytes(relative, entry.typed.json_bytes(value))

    def write_bytes(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def synthetic_prepared(self, root):
        self.assertEqual(Path(root), self.root)
        return ({'sources': [entry.base.descriptor(self.root / p, self.root) for p in self.source_paths]},
                {'opaque_prepared_metadata': True},
                {'accepted_metadata_checks': {'opaque_fixture_prepared': True}})

    def refresh_completed_guard(self):
        self.write(entry.prior.OUTPUT_GUARD, {
            'format_version': 1,
            'specification': entry.base.descriptor(self.root / entry.prior.SPEC, self.root),
            'input_guard': entry.base.descriptor(self.root / entry.prior.INPUT_GUARD, self.root),
            'private_bundle_guard': entry.prior.outputs.bundle_guard(self.root / entry.prior.DATASET),
            'public_report': entry.base.descriptor(self.root / entry.prior.PUBLIC, self.root),
            'readback_acceptance': self.readback,
        })

    def verify(self):
        return entry.run(self.root, verify_synthetic=True)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_only_explicit_synthetic_action_is_supported(self):
        for value in (False, 1, 'true', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                entry.run(self.root, verify_synthetic=value)
        for args in ([], ['--real'], ['--verify-synthetic', '--input', 'other.csv'],
                     ['--verify-synthetic', '--root', 'elsewhere']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                entry.main(args)
        self.mock_suites.assert_not_called()

    def test_cli_dispatches_only_synthetic_flag(self):
        with patch.object(entry, 'run', return_value={'status': 'synthetic'}) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            entry.main(['--verify-synthetic'])
        run.assert_called_once_with(verify_synthetic=True)

    def test_complete_forty_nine_distinct_source_bindings(self):
        snapshot = entry._prior_snapshot(self.root)
        bindings = snapshot['source_bindings']
        self.assertEqual(len(bindings), 49)
        self.assertEqual(len({item['path'] for item in bindings}), 49)
        self.assertEqual({item['path'] for item in bindings},
                         set(self.source_paths) | set(entry.IMPLEMENTATION) |
                         {entry.prior.SPEC, entry.prior.PREFLIGHT, entry.prior.PUBLIC, entry.ACCEPTANCE})
        self.assertEqual(entry._specification(snapshot)['policy'], entry.policy())

    def test_missing_or_duplicate_prior_source_binding_is_rejected(self):
        original = self.source_paths[:]
        for changed in (original[:-1], [original[0], *original[1:-1], original[0]]):
            self.source_paths = changed
            with self.assertRaisesRegex(ValueError, 'forty-nine'):
                self.verify()
        self.source_paths = original
        self.mock_suites.assert_not_called()

    def test_success_records_validated_receipt_and_no_real_execution(self):
        result = self.verify()
        self.assertEqual(result['source_bindings'], 49)
        self.assertEqual(result['tests_run'], 2)
        self.assertFalse(result['existing_verified_without_test_rerun'])
        report = entry.base.read_json(self.root / entry.OUTPUT)
        self.assertEqual(report['unit_tests'], self.receipt)
        self.assertTrue(report['prior_metadata']['all_passed'])
        self.assertFalse(report['prior_metadata']['individual_readback_rerun'])
        self.assertFalse(report['execution']['real_CSV_parsed'])
        self.assertFalse(report['execution']['real_cutpoints_estimated'])
        self.assertFalse(report['execution']['real_ordinals_or_tuples_assigned'])
        self.assertFalse(report['execution']['G3_executed'])
        self.assertEqual(report['execution']['model_fits'], 0)
        self.assertFalse(report['execution']['dashboard'])
        self.mock_suites.assert_called_once_with()

    def test_metadata_only_never_parses_opaque_bundle_or_calls_real_entry(self):
        blocked = AssertionError('Real CSV parsing or execution is forbidden')
        with patch.object(csv, 'reader', side_effect=blocked), \
                patch.object(csv, 'DictReader', side_effect=blocked), \
                patch.object(entry.prior.sources, 'read_inputs', side_effect=blocked), \
                patch.object(entry.prior.core, 'describe_dataset', side_effect=blocked), \
                patch.object(entry.prior, 'execute_prepared', side_effect=blocked), \
                patch.object(entry.prior, 'verify_completed', side_effect=blocked), \
                patch.object(entry.prior.outputs, 'read_outputs', side_effect=blocked):
            self.verify()

    def test_public_reports_exclude_private_digests_and_guards(self):
        self.verify()
        text = ''.join((self.root / p).read_text('utf-8') for p in (entry.SPEC, entry.OUTPUT))
        snapshot = entry.base.read_json(self.root / entry.GUARD)['input_snapshot']
        private = snapshot['private_provenance']
        for field in ('prepared_input_guard', 'completed_output_guard'):
            self.assertNotIn(private[field]['sha256'], text)
        for digest in private['completed_guard']['private_bundle_guard'].values():
            self.assertNotIn(digest['sha256'], text)
        for forbidden in ('private_provenance', 'private_bundle_guard', 'input_snapshot'):
            self.assertNotIn(forbidden, text)

    def test_same_bytes_reentry_preserves_outputs_and_never_reruns_suites(self):
        self.verify()
        before = self.snapshot()
        times = {p: p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        with patch.object(entry, '_run_suites', side_effect=AssertionError('Must not rerun')):
            result = self.verify()
        self.assertTrue(result['existing_verified_without_test_rerun'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(times, {p: p.stat().st_mtime_ns for p in times})

    def test_partial_outputs_are_not_regenerated(self):
        self.write(entry.SPEC, {'partial': True})
        with self.assertRaisesRegex(ValueError, 'Partial'):
            self.verify()
        self.assertFalse((self.root / entry.OUTPUT).exists())
        self.assertFalse((self.root / entry.GUARD).exists())
        self.mock_suites.assert_not_called()

    def test_unexpected_control_file_is_preserved_and_rejected(self):
        self.verify()
        self.write_bytes(entry.PRIVATE + '/extra', b'preserve unexpected evidence')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            self.verify()
        self.assertEqual((self.root / entry.PRIVATE / 'extra').read_bytes(), b'preserve unexpected evidence')

    def test_changed_existing_outputs_never_overwritten(self):
        self.verify()
        for relative in (entry.SPEC, entry.OUTPUT, entry.GUARD, entry.LOG):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.verify()
            self.assertEqual(path.read_bytes(), original + b'\n')
            path.write_bytes(original)

    def test_changed_new_implementation_or_prior_source_blocks_existing_receipt(self):
        self.verify()
        for relative in (*entry.IMPLEMENTATION, self.source_paths[0]):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'changed source')
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'sources'):
                self.verify()
            path.write_bytes(original)

    def test_source_mutation_during_suites_stops_before_publication(self):
        def mutate():
            path = self.root / self.source_paths[0]
            path.write_bytes(path.read_bytes() + b'changed during tests')
            return self.receipt, 'test log\n'
        self.mock_suites.side_effect = mutate
        with self.assertRaisesRegex(ValueError, 'changed during synthetic'):
            self.verify()
        self.assertFalse((self.root / entry.SPEC).exists())
        self.assertFalse((self.root / entry.OUTPUT).exists())

    def test_source_mutation_during_existing_verification_is_detected(self):
        self.verify()
        original = entry._check_existing
        def mutate(root, snapshot):
            result = original(root, snapshot)
            path = self.root / self.source_paths[0]
            path.write_bytes(path.read_bytes() + b'changed during existing verify')
            return result
        with patch.object(entry, '_check_existing', side_effect=mutate), \
                self.assertRaisesRegex(ValueError, 'changed during verification'):
            self.verify()

    def test_source_mutation_during_publication_stops_and_retains_evidence(self):
        original_write = entry.base.immutable_write
        def mutate(path, payload):
            original_write(path, payload)
            if Path(path) == self.root / entry.GUARD:
                source = self.root / self.source_paths[0]
                source.write_bytes(source.read_bytes() + b'changed during publication')
        with patch.object(entry.base, 'immutable_write', side_effect=mutate), \
                self.assertRaisesRegex(ValueError, 'changed during publication'):
            self.verify()
        preserved = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'sources'):
            self.verify()
        self.assertEqual(preserved, self.snapshot())

    def test_prior_failure_marker_stops_before_suites(self):
        self.write(entry.prior.FAILURE, {'failed': True})
        with self.assertRaisesRegex(ValueError, 'execution failed'):
            self.verify()
        self.mock_suites.assert_not_called()

    def test_prior_private_bundle_and_input_guard_bytes_are_checked(self):
        for relative in (entry.prior.INPUT_GUARD,
                         entry.prior.DATASET + '/customer_roster.csv',
                         entry.prior.DATASET + '/description.json'):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'provenance'):
                self.verify()
            path.write_bytes(original)
        self.mock_suites.assert_not_called()

    def test_prior_output_guard_canonical_schema_and_version_are_checked(self):
        path = self.root / entry.prior.OUTPUT_GUARD
        original = path.read_bytes()
        for mutate in (lambda x: x.update(format_version=True), lambda x: x.update(extra=True)):
            guard = entry.base.read_json(path)
            mutate(guard)
            self.write(entry.prior.OUTPUT_GUARD, guard)
            with self.assertRaisesRegex(ValueError, 'provenance'):
                self.verify()
            path.write_bytes(original)
        path.write_bytes(original + b'\n')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.verify()

    def test_prior_G1_acceptance_gate_readback_and_decision_are_required(self):
        path = self.root / entry.ACCEPTANCE
        original = path.read_bytes()
        mutations = (
            lambda a: a['gate_status'].update(G2='passed'),
            lambda a: a.update(readback_acceptance={'different': True}),
            lambda a: a.update(decision='allow_real_execution'),
            lambda a: a['completed_verification'].update(core_calls=1),
            lambda a: a['completed_verification'].update(output_guard_valid=1),
            lambda a: a.update(source_bindings_before_after_match=1),
        )
        for mutate in mutations:
            accepted = entry.base.read_json(path)
            mutate(accepted)
            self.write(entry.ACCEPTANCE, accepted)
            with self.assertRaisesRegex(ValueError, 'G1 acceptance'):
                self.verify()
            path.write_bytes(original)

    def test_prior_completed_core_count_rejects_bool_and_float_impersonation(self):
        path = self.root / entry.ACCEPTANCE
        original = path.read_bytes()
        for value in (False, 0.0):
            accepted = entry.base.read_json(path)
            accepted['completed_verification']['core_calls'] = value
            self.write(entry.ACCEPTANCE, accepted)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'G1 acceptance'):
                self.verify()
            path.write_bytes(original)

    def test_prior_public_G2_gate_cannot_be_relabelled_even_with_refreshed_guard(self):
        public = entry.base.read_json(self.root / entry.prior.PUBLIC)
        public['description']['gate_status']['G2'] = 'passed'
        self.write(entry.prior.PUBLIC, public)
        self.refresh_completed_guard()
        with self.assertRaisesRegex(ValueError, 'G1 acceptance'):
            self.verify()

    def test_receipt_schema_counts_identity_and_module_requirements(self):
        mutations = (
            lambda r: r.update(extra=True),
            lambda r: r.update(tests_run=3),
            lambda r: r.update(test_ids=[]),
            lambda r: r.update(test_ids=[r['test_ids'][0], r['test_ids'][0]]),
            lambda r: r['test_ids'].reverse(),
            lambda r: r['test_ids'].__setitem__(1, 'unrelated.Synthetic.test_case'),
            lambda r: r.update(modules=[entry.MODULES[0]]),
            lambda r: r['tests_by_module'].update({entry.MODULES[0]: 0}),
            lambda r: r['tests_by_module'].update(extra=1),
        )
        for mutate in mutations:
            receipt = copy.deepcopy(self.receipt)
            mutate(receipt)
            with self.assertRaises(ValueError):
                entry._validate_receipt(receipt)

    def test_receipt_fail_skip_error_and_imprecise_numeric_types_rejected(self):
        mutations = [('tests_run', 2.0), ('errors', False), ('errors', 1),
                     ('failures', 1), ('skipped', 1), ('successful', False),
                     ('successful', 1), ('elapsed_seconds', 1),
                     ('elapsed_seconds', -0.1), ('elapsed_seconds', float('inf')),
                     ('elapsed_seconds', float('nan'))]
        for key, value in mutations:
            receipt = copy.deepcopy(self.receipt)
            receipt[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                entry._validate_receipt(receipt)

    def test_invalid_mocked_actual_receipt_stops_before_any_output(self):
        self.receipt['skipped'] = 1
        with self.assertRaises(ValueError):
            self.verify()
        self.assertFalse((self.root / entry.SPEC).exists())
        self.assertFalse((self.root / entry.OUTPUT).exists())
        self.assertFalse((self.root / entry.GUARD).exists())

    def test_synthetic_scenario_disagreement_stops_before_any_output(self):
        with patch.object(entry, '_run_cases', return_value=[]), self.assertRaises(ValueError):
            self.verify()
        self.assertFalse((self.root / entry.SPEC).exists())
        self.assertFalse((self.root / entry.OUTPUT).exists())

    def test_real_unittest_receipt_collection_records_actual_ids_counts_and_log(self):
        probes = unittest.TestSuite([_probe(identity) for identity in self.receipt['test_ids']])
        self.suites.stop()
        with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=probes) as loader:
            receipt, log = entry._run_suites()
        loader.assert_called_once_with(entry.MODULES)
        self.assertEqual(receipt['test_ids'], self.receipt['test_ids'])
        self.assertEqual(receipt['tests_by_module'], self.receipt['tests_by_module'])
        self.assertEqual(receipt['tests_run'], 2)
        self.assertTrue(receipt['successful'])
        self.assertIs(type(receipt['elapsed_seconds']), float)
        self.assertIn('Ran 2 tests', log)

    def test_actual_suite_skips_failures_errors_and_duplicate_ids_are_rejected(self):
        self.suites.stop()
        for behavior in ('skip', 'fail', 'error', 'duplicate'):
            ids = self.receipt['test_ids']
            probes = unittest.TestSuite([_probe(ids[0]),
                _probe(ids[0] if behavior == 'duplicate' else ids[1], behavior)])
            with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=probes), \
                    self.subTest(behavior=behavior), self.assertRaises(ValueError):
                entry._run_suites()

    def test_actual_suite_empty_or_outside_required_modules_is_rejected(self):
        self.suites.stop()
        for probes in (unittest.TestSuite(), unittest.TestSuite([
                _probe(self.receipt['test_ids'][0]), _probe('unrelated.Probe.test_case')])):
            with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=probes), \
                    self.assertRaises(ValueError):
                entry._run_suites()

    def test_synchronized_report_and_guard_tampering_is_rejected(self):
        self.verify()
        report = entry.base.read_json(self.root / entry.OUTPUT)
        report['execution']['real_cutpoints_estimated'] = True
        self.write(entry.OUTPUT, report)
        guard = entry.base.read_json(self.root / entry.GUARD)
        guard['report'] = entry.base.descriptor(self.root / entry.OUTPUT, self.root)
        self.write(entry.GUARD, guard)
        with self.assertRaises(ValueError):
            self.verify()


if __name__ == '__main__':
    unittest.main()
