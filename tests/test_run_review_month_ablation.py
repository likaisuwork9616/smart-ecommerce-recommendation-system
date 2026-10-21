"""Synthetic entry-point, source binding and no-replay integration checks."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import run_review_month_ablation as runner
from tests.test_prepare_review_month_ablation import SyntheticPrepared


class DispatcherEntryTest(unittest.TestCase):
    def setUp(self):
        self.root = runner.ROOT / '.runtime' / ('dispatcher-cli-unit-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.bundle = SyntheticPrepared(self.root)
        control_manifest = self.root / runner.control.PRIVATE / 'manifest.json'
        control_manifest.parent.mkdir(parents=True)
        control_manifest.write_bytes(b'{"synthetic_control":true}\n')
        self.bundle.private_sources.append(runner.files.descriptor(control_manifest, self.root))
        for name in runner.CODE:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# synthetic binding fixture\n')
        runner.preparation.freeze(self.bundle, self.root)
        (self.root / runner.preparation.REPORT).write_bytes(b'{"synthetic_preflight":true}\n')
        self.pin = patch.object(runner, 'PARENTS', {
            name: runner.files.descriptor(self.root / name, self.root)['sha256'] for name in runner.PARENTS})
        self.pin.start()
        self.loader = patch.object(runner.sources, 'load_prepared_sources', return_value=self.bundle)
        self.loader.start()

    def tearDown(self):
        self.loader.stop()
        self.pin.stop()
        path = self.root.resolve()
        assert path.is_relative_to((runner.ROOT / '.runtime').resolve())
        assert path.name.startswith('dispatcher-cli-unit-')
        shutil.rmtree(path)

    def freeze(self):
        return runner.freeze(self.root)

    def proof(self, spec):
        _, ids, counts = runner._suite()
        result = {'status': 'passed_synthetic_month_ablation_dispatcher_verification',
                  'specification': runner.files.descriptor(self.root / runner.SPEC, self.root),
                  'sources': spec['public_sources'], 'software_versions': spec['software_versions'],
                  'synthetic_execution': {'sklearn_fits_attempted': 12, 'sklearn_fits_completed': 12,
                                          'completed_fits_by_feature_count': {'32': 12}},
                  'tests': {'modules': list(runner.TEST_MODULES), 'test_ids': ids,
                            'counts_by_module': counts, 'tests_run': len(ids),
                            'failures': 0, 'errors': 0, 'skips': 0,
                            'expected_failures': 0, 'unexpected_successes': 0}}
        (self.root / runner.REPORT).write_bytes(runner.files.json_bytes(result))
        return result

    def test_default_and_help_never_load_or_fit(self):
        with patch.object(runner.sources, 'load_prepared_sources') as loader, \
                patch.object(runner, 'train') as train, redirect_stdout(io.StringIO()):
            runner.main([])
            with self.assertRaises(SystemExit) as caught:
                runner.main(['--help'])
            self.assertEqual(caught.exception.code, 0)
        loader.assert_not_called()
        train.assert_not_called()

    def test_actions_mutually_exclusive_no_implicit_training(self):
        with patch.object(runner, 'train') as train, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                runner.main(['--check', '--train'])
        train.assert_not_called()

    def test_each_cli_action_dispatches_only_requested_function(self):
        cases = [('--specification-only', 'freeze', {'role': 'frozen'}),
                 ('--verify-synthetic', 'verify_synthetic', {'status': 'synthetic', 'tests': {'tests_run': 1}}),
                 ('--check', 'prepared', None), ('--train', 'train', {'status': 'synthetic'})]
        for flag, name, result in cases:
            with patch.object(runner, name, return_value=result) as call, redirect_stdout(io.StringIO()):
                runner.main([flag])
            call.assert_called_once()

    def test_binding_roundtrip_code_schema_and_private_sources_no_training(self):
        spec = self.freeze()
        actual, bound = runner.verify_binding(self.bundle, self.root)
        self.assertEqual(actual, spec)
        self.assertEqual(actual['execution_plan'], runner.preparation.execution_plan())
        self.assertEqual(actual['output_contract_unchanged'], runner.preparation.output_contract())
        self.assertTrue(set(runner.CODE).issubset(item['path'] for item in actual['public_sources']))
        self.assertTrue(all(value == 0 for value in spec['current_real_execution'].values()))
        self.assertIsNone(spec['actual_treatment_selected_C'])
        guard = runner.files.read_json(self.root / runner.GUARD)
        self.assertEqual(guard['specification'], runner.files.descriptor(self.root / runner.SPEC, self.root))
        self.assertEqual(len({item['path'] for item in bound}), len(bound))
        for item in guard['private_sources']:
            self.assertNotIn(item['sha256'], (self.root / runner.SPEC).read_text(encoding='utf-8'))
        self.assertFalse((self.root / runner.preparation.FUTURE_PRIVATE).exists())

    def test_identical_binding_freeze_does_not_rewrite(self):
        self.freeze()
        paths = [self.root / name for name in (runner.SPEC, runner.GUARD)]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        self.freeze()
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths])

    def test_changed_dispatcher_test_or_private_source_blocks_before_fit(self):
        self.freeze()
        for name in (runner.CODE[0], runner.CODE[-1], self.bundle.private_sources[0]['path']):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.assertRaises(ValueError):
                runner.prepared(self.root, require_tests=False)
            path.write_bytes(original)
        self.assertFalse((self.root / runner.preparation.FUTURE_PRIVATE).exists())

    def test_parent_version_mismatch_rejected(self):
        self.freeze()
        path = self.root / runner.preparation.REPORT
        path.write_bytes(b'changed parent')
        with self.assertRaises(ValueError):
            runner.prepared(self.root, require_tests=False)

    def test_guard_mismatch_rejected_without_training_output(self):
        self.freeze()
        guard = runner.files.read_json(self.root / runner.GUARD)
        guard['specification']['sha256'] = '0' * 64
        (self.root / runner.GUARD).write_bytes(runner.files.json_bytes(guard))
        with self.assertRaises(ValueError):
            runner.prepared(self.root, require_tests=False)
        self.assertFalse((self.root / runner.preparation.FUTURE_PRIVATE).exists())

    def test_missing_or_stale_verification_refuses_before_training_start(self):
        spec = self.freeze()
        training, artifacts = runner.modules()
        with patch.object(training, 'execute_training') as execute, \
                patch.object(artifacts, 'write_failure_receipt') as receipt:
            with self.assertRaises(FileNotFoundError):
                runner.train(self.root)
            proof = self.proof(spec)
            proof['specification']['sha256'] = '0' * 64
            (self.root / runner.REPORT).write_bytes(runner.files.json_bytes(proof))
            with self.assertRaises(ValueError):
                runner.train(self.root)
        execute.assert_not_called()
        receipt.assert_not_called()
        self.assertFalse((self.root / runner.preparation.FUTURE_PRIVATE).exists())

    def test_skipped_failed_missing_or_different_test_roster_rejected(self):
        spec = self.freeze()
        original = self.proof(spec)
        variants = []
        for key in ('skips', 'failures', 'errors', 'expected_failures', 'unexpected_successes'):
            changed = deepcopy(original)
            changed['tests'][key] = 1
            variants.append(changed)
        changed = deepcopy(original)
        changed['tests']['test_ids'] = changed['tests']['test_ids'][:-1]
        variants.append(changed)
        changed = deepcopy(original)
        changed['sources'] = []
        variants.append(changed)
        for evidence in ({}, {'sklearn_fits_attempted': 12, 'sklearn_fits_completed': 12,
                             'completed_fits_by_feature_count': {'44': 12}}):
            changed = deepcopy(original)
            changed['synthetic_execution'] = evidence
            variants.append(changed)
        for value in variants:
            (self.root / runner.REPORT).write_bytes(runner.files.json_bytes(value))
            with self.assertRaises(ValueError):
                runner.verify_test_report(spec, self.root)

    def test_full_readiness_keeps_output_empty_and_binds_every_reference(self):
        spec = self.freeze()
        self.proof(spec)
        _, accepted, references, bound = runner.prepared(self.root)
        self.assertEqual(accepted, spec)
        self.assertTrue(all(item in bound for item in references.values()))
        self.assertIn(runner.REPORT, [item['path'] for item in bound])
        self.assertFalse((self.root / runner.preparation.FUTURE_PRIVATE).exists())

    def test_unexpected_output_or_failure_receipt_refuses_before_source_loading(self):
        directory = self.root / runner.preparation.FUTURE_PRIVATE
        directory.mkdir(parents=True)
        for name in ('unexpected.tmp', 'failure_receipt.json', 'manifest.json'):
            path = directory / name
            path.write_bytes(b'keep')
            with patch.object(runner.sources, 'load_prepared_sources') as load:
                with self.assertRaises(ValueError):
                    runner.prepared(self.root)
            load.assert_not_called()
            self.assertEqual(path.read_bytes(), b'keep')
            path.unlink()

    def test_late_source_change_in_binding_publication_retracts_new_spec_and_guard(self):
        original = runner.preparation.require_future_outputs_absent
        calls = []
        def check(root):
            calls.append(root)
            if (self.root / runner.GUARD).exists():
                raise ValueError('late source/path failure')
            return original(root)
        with patch.object(runner.preparation, 'require_future_outputs_absent', side_effect=check):
            with self.assertRaises(ValueError):
                self.freeze()
        self.assertFalse((self.root / runner.SPEC).exists())
        self.assertFalse((self.root / runner.GUARD).exists())

    def test_train_core_failure_records_completed_fits_and_does_not_publish(self):
        training, artifacts = runner.modules()
        context = {'phase': 'predict', 'outer_fold': '2017-12', 'role': 'inner_train_pool',
                   'C': 1.0, 'completed_estimator_fits': 2}
        error = training.TrainingStopped(context, ValueError('synthetic'))
        with patch.object(runner, 'prepared', return_value=(self.bundle, {}, {}, [])), \
                patch.object(training, 'execute_training', side_effect=error) as execute, \
                patch.object(artifacts, 'publish') as publish, \
                patch.object(artifacts, 'write_failure_receipt') as receipt:
            with self.assertRaises(training.TrainingStopped):
                runner.train(self.root)
        execute.assert_called_once()
        publish.assert_not_called()
        receipt.assert_called_once_with(context, 'ValueError', {}, root=self.root)

    def test_train_publication_failure_records_twelve_fits_without_retry(self):
        training, artifacts = runner.modules()
        with patch.object(runner, 'prepared', return_value=(self.bundle, {}, {}, [])), \
                patch.object(training, 'execute_training', return_value=('synthetic',)) as execute, \
                patch.object(artifacts, 'publish', side_effect=OSError('synthetic write failure')) as publish, \
                patch.object(artifacts, 'write_failure_receipt') as receipt:
            with self.assertRaises(OSError):
                runner.train(self.root)
        execute.assert_called_once()
        publish.assert_called_once()
        self.assertEqual(receipt.call_args.args[0]['phase'], 'publication')
        self.assertEqual(receipt.call_args.args[0]['completed_estimator_fits'], 12)
        self.assertEqual(receipt.call_args.args[1], 'OSError')

    def test_training_callback_retains_exact_bound_sources_after_output_exists(self):
        training, artifacts = runner.modules()
        file = self.root / '.runtime/captured_source.json'
        file.write_bytes(b'{}')
        bound = [runner.files.descriptor(file, self.root)]
        def execute(bundle, spec, *, emit, verify_sources):
            verify_sources()
            directory = self.root / runner.preparation.FUTURE_PRIVATE
            directory.mkdir(parents=True)
            (directory / 'synthetic-progress').write_bytes(b'progress')
            verify_sources()  # Must not call the parent's empty-output gate here.
            file.write_bytes(b'changed')
            verify_sources()
        with patch.object(runner, 'prepared', return_value=(self.bundle, {}, {}, bound)), \
                patch.object(training, 'execute_training', side_effect=execute), \
                patch.object(artifacts, 'publish') as publish, \
                patch.object(artifacts, 'write_failure_receipt') as receipt:
            with self.assertRaises(ValueError):
                runner.train(self.root)
        publish.assert_not_called()
        receipt.assert_called_once()

    def test_end_to_end_synthetic_entry_actual_twelve_fits_and_private_publication(self):
        from tests.test_review_month_ablation_training import synthetic_training_bundle
        training, artifacts = runner.modules()
        spec = self.freeze()
        _, bound = runner.verify_binding(self.bundle, self.root)
        references = {key: runner.files.descriptor(self.root / name, self.root)
                      for key, name in artifacts.REFERENCE_PATHS.items()}
        bundle = synthetic_training_bundle()
        with patch.object(runner, 'prepared', return_value=(bundle, spec, references, bound)), \
                patch.object(training, 'GuardedReviewMonthAblation', wraps=training.GuardedReviewMonthAblation) as factory:
            result = runner.train(self.root)
        self.assertEqual(factory.call_count, 12)
        self.assertEqual(result['verification']['paired_blocks'], 18)
        self.assertEqual(result['results']['execution']['inner_candidates_evaluated'], 9)
        self.assertEqual(result['results']['execution']['outer_refits_completed'], 3)
        manifest = runner.files.read_json(self.root / artifacts.PRIVATE / 'manifest.json')
        self.assertEqual(manifest['completed_estimator_fits'], 12)
        for descriptor in [manifest['public_report'], *manifest['files'].values()]:
            self.assertEqual(descriptor, runner.files.descriptor(self.root / descriptor['path'], self.root))
        with self.assertRaises(ValueError):
            artifacts.preflight(root=self.root, bound_sources=bound)
        self.assertFalse((self.root / artifacts.PRIVATE / 'failure_receipt.json').exists())

    def test_end_to_end_synthetic_prediction_failure_writes_receipt_and_blocks_replay(self):
        from tests.test_review_month_ablation_training import synthetic_training_bundle
        training, artifacts = runner.modules()
        spec = self.freeze()
        _, bound = runner.verify_binding(self.bundle, self.root)
        references = {key: runner.files.descriptor(self.root / name, self.root)
                      for key, name in artifacts.REFERENCE_PATHS.items()}
        bundle = synthetic_training_bundle()
        with patch.object(runner, 'prepared', return_value=(bundle, spec, references, bound)), \
                patch.object(training.GuardedReviewMonthAblation, 'predict_orders', side_effect=ValueError('synthetic prediction failure')):
            with self.assertRaises(training.TrainingStopped):
                runner.train(self.root)
        receipt = runner.files.read_json(self.root / artifacts.PRIVATE / 'failure_receipt.json')
        self.assertEqual(receipt['execution_context']['completed_estimator_fits'], 1)
        self.assertEqual(receipt['execution_context']['phase'], 'prediction')
        self.assertFalse((self.root / artifacts.REPORT).exists())
        self.assertEqual([p.name for p in (self.root / artifacts.PRIVATE).iterdir()], ['failure_receipt.json'])
        with self.assertRaises(ValueError):
            artifacts.preflight(root=self.root, bound_sources=bound)

    def test_end_to_end_final_pairing_failure_preserves_twelve_fit_receipt(self):
        from tests.test_review_month_ablation_training import synthetic_training_bundle, SyntheticModel
        training, artifacts = runner.modules()
        spec = self.freeze()
        _, bound = runner.verify_binding(self.bundle, self.root)
        references = {key: runner.files.descriptor(self.root / name, self.root)
                      for key, name in artifacts.REFERENCE_PATHS.items()}
        bundle = synthetic_training_bundle()
        with patch.object(runner, 'prepared', return_value=(bundle, spec, references, bound)), \
                patch.object(training, 'GuardedReviewMonthAblation', SyntheticModel), \
                patch.object(training.pairing, 'validate_treatment_pairing', side_effect=ValueError('synthetic final pairing failure')):
            with self.assertRaises(training.TrainingStopped):
                runner.train(self.root)
        receipt = runner.files.read_json(self.root / artifacts.PRIVATE / 'failure_receipt.json')
        self.assertEqual(receipt['execution_context']['completed_estimator_fits'], 12)
        self.assertEqual(receipt['execution_context']['phase'], 'complete_same_id_pairing')
        self.assertFalse((self.root / artifacts.REPORT).exists())
        with self.assertRaises(ValueError):
            artifacts.preflight(root=self.root, bound_sources=bound)

    def test_synthetic_verifier_failure_leaves_private_log_without_public_success(self):
        spec = self.freeze()
        _, bound = runner.verify_binding(self.bundle, self.root)
        def fail():
            raise AssertionError('intentional synthetic suite failure')
        suite = unittest.TestSuite([unittest.FunctionTestCase(fail)])
        with patch.object(runner, 'prepared', return_value=(self.bundle, spec, {}, bound)), \
                patch.object(runner, '_suite', return_value=(suite, ['synthetic-failure'], {'synthetic': 1})):
            with self.assertRaises(ValueError):
                runner.verify_synthetic(self.root)
        self.assertFalse((self.root / runner.REPORT).exists())
        receipt = runner.files.read_json(self.root / runner.LAST_RUN)
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['tests']['failures'], 1)
        self.assertEqual(receipt['synthetic_execution']['sklearn_fits_completed'], 0)


if __name__ == '__main__':
    unittest.main()
