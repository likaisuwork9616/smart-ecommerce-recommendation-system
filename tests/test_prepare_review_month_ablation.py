"""Synthetic preparation publication/output contracts; no estimator execution."""
from contextlib import redirect_stderr
from copy import deepcopy
import io
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import prepare_review_month_ablation as runner
from tests.test_review_baseline_sources import bundle as synthetic_base


class SyntheticPrepared:
    def __init__(self, root):
        self.root = root
        self.base = synthetic_base(root=root)
        self.method_spec = {'protocol': {'synthetic_method': 'unchanged'}}
        public_paths = [runner.sources.method.SPEC, runner.sources.PIPELINE_PROOF]
        for path in public_paths + list(runner.CODE):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'{}\n')
        private = root / '.runtime/synthetic_input.json'
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_bytes(b'{"synthetic":true}\n')
        self.public_sources = [runner.files.descriptor(root / p, root) for p in public_paths]
        self.private_sources = [runner.files.descriptor(private, root)]
        self.summary = {'source_bundle': self.base.summary, 'synthetic': True}

    def verify_stable(self):
        runner.files.verify_sources(self.public_sources + self.private_sources, self.root)

    def role_block(self, fold, role):
        return self.base.role_block(fold, role)

    def prediction_block(self, fold, role):
        return self.base.prediction_block(fold, role)


class PrepareMonthAblationTest(unittest.TestCase):
    def setUp(self):
        self.root = runner.ROOT / '.runtime' / ('prepare-unit-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.bundle = SyntheticPrepared(self.root)

    def tearDown(self):
        resolved = self.root.resolve()
        assert resolved.is_relative_to((runner.ROOT / '.runtime').resolve())
        assert resolved.name.startswith('prepare-unit-')
        shutil.rmtree(resolved)

    def run_preparation(self, specification_only=False):
        with patch.object(runner.sources, 'load_prepared_sources', return_value=self.bundle):
            return runner.run(self.root, specification_only=specification_only)

    def test_execution_and_output_contract_defer_training_preserve_independent_C(self):
        spec = runner.make_specification(self.bundle, self.root)
        plan = spec['execution_plan']
        self.assertFalse(plan['training_authorized_this_run'])
        self.assertTrue(plan['control_C_cannot_set_treatment_C'])
        self.assertEqual((plan['future_inner_fits'], plan['future_outer_refits'], plan['future_control_fits']), (9, 3, 0))
        self.assertEqual(spec['method_protocol_unchanged'], self.bundle.method_spec['protocol'])
        self.assertIn('requires_separate', plan['future_training_dispatcher'])
        self.assertEqual(spec['output_contract']['score_columns'], runner.control.SCORE_COLUMNS)
        self.assertNotEqual(runner.FUTURE_PRIVATE, runner.control.PRIVATE)
        self.assertFalse(spec['output_contract']['preparation_creates_treatment_outputs'])
        self.assertTrue(all(v == 0 for v in spec['current_run'].values()))
        self.assertIsNone(spec['actual_treatment_selected_C'])

    def test_exact_role_summary_keeps_unknown_and_masks_seven_query_fields(self):
        roles = runner.role_acceptance(self.bundle)
        self.assertEqual(len(roles), 12)
        self.assertEqual(sum('future_truth_columns_masked' in row for row in roles), 6)
        for row in roles:
            self.assertEqual(row['known_labels'] + row['unknown_labels'], row['orders'])
            if 'future_truth_columns_masked' in row:
                self.assertEqual(row['future_truth_columns_masked'], 7)
        self.assertGreater(sum(row['unknown_labels'] for row in roles), 0)

    def test_query_truth_unmasked_or_dropped_ID_rejected(self):
        original = self.bundle.prediction_block
        for failure in ('unmasked', 'dropped'):
            def bad(fold, role):
                return self.bundle.role_block(fold, role) if failure == 'unmasked' else original(fold, role).iloc[:-1]
            with patch.object(self.bundle, 'prediction_block', side_effect=bad):
                with self.assertRaises(ValueError):
                    runner.role_acceptance(self.bundle)

    def test_freeze_and_preflight_roundtrip_without_creating_training_outputs(self):
        spec = self.run_preparation(True)
        report = self.run_preparation()
        self.assertEqual(report['pair_acceptance']['treatment'], 'pending_not_trained')
        self.assertEqual(report['pair_acceptance']['paired_effect'], 'not_computed')
        self.assertTrue(all(value == 0 for value in report['actual_execution'].values()))
        self.assertEqual(runner.files.read_json(self.root / runner.SPEC), spec)
        self.assertEqual(runner.files.read_json(self.root / runner.REPORT), report)
        guard = runner.files.read_json(self.root / runner.GUARD)
        self.assertEqual(guard['specification'], report['specification'])
        self.assertFalse((self.root / runner.FUTURE_PRIVATE).exists())
        self.assertFalse((self.root / runner.FUTURE_REPORT).exists())
        public = (self.root / runner.SPEC).read_text() + (self.root / runner.REPORT).read_text()
        self.assertNotIn(self.bundle.private_sources[0]['sha256'], public)

    def test_identical_freeze_and_preflight_are_idempotent(self):
        self.run_preparation(True)
        self.run_preparation()
        paths = runner.output_paths(self.root)
        before = [path.read_bytes() for path in paths]
        self.run_preparation(True)
        self.run_preparation()
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_private_guard_conflict_preflights_before_any_public_write(self):
        guard = self.root / runner.GUARD
        guard.parent.mkdir(parents=True)
        guard.write_bytes(b'conflict')
        with self.assertRaises(ValueError):
            self.run_preparation(True)
        self.assertFalse((self.root / runner.SPEC).exists())
        self.assertEqual(guard.read_bytes(), b'conflict')

    def test_existing_report_cannot_be_rebound_by_freeze(self):
        report = self.root / runner.REPORT
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_bytes(b'{"specification":null}\n')
        with self.assertRaises(ValueError):
            self.run_preparation(True)
        self.assertFalse((self.root / runner.SPEC).exists())
        self.assertFalse((self.root / runner.GUARD).exists())

    def test_changed_code_or_policy_rejected_without_overwrite(self):
        self.run_preparation(True)
        before = (self.root / runner.SPEC).read_bytes()
        (self.root / runner.CODE[0]).write_bytes(b'changed code')
        with self.assertRaises(ValueError):
            self.run_preparation()
        with self.assertRaises(ValueError):
            self.run_preparation(True)
        self.assertEqual((self.root / runner.SPEC).read_bytes(), before)
        self.assertFalse((self.root / runner.REPORT).exists())

    def test_changed_private_source_or_guard_rejected(self):
        self.run_preparation(True)
        guard_path = self.root / runner.GUARD
        guard = runner.files.read_json(guard_path)
        changed = deepcopy(guard)
        changed['specification']['sha256'] = 'bad'
        guard_path.write_bytes(runner.files.json_bytes(changed))
        with self.assertRaises(ValueError):
            self.run_preparation()
        guard_path.write_bytes(runner.files.json_bytes(guard))
        (self.root / self.bundle.private_sources[0]['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.run_preparation()
        self.assertFalse((self.root / runner.REPORT).exists())

    def test_future_final_failure_and_unexpected_files_all_block_before_loading(self):
        directory = self.root / runner.FUTURE_PRIVATE
        directory.mkdir(parents=True)
        for name in (*runner.FUTURE_FILES, 'unrecognized.txt'):
            path = directory / name
            path.write_bytes(b'preserve')
            with patch.object(runner.sources, 'load_prepared_sources') as loader:
                with self.assertRaises(ValueError):
                    runner.run(self.root, specification_only=True)
                loader.assert_not_called()
            self.assertEqual(path.read_bytes(), b'preserve')
            path.unlink()
        self.assertTrue(runner.require_future_outputs_absent(self.root)['namespace_empty'])

    def test_existing_future_public_report_blocks_and_is_preserved(self):
        path = self.root / runner.FUTURE_REPORT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'preserve')
        with self.assertRaises(ValueError):
            self.run_preparation(True)
        self.assertEqual(path.read_bytes(), b'preserve')

    def test_future_namespace_file_instead_of_directory_rejected(self):
        path = self.root / runner.FUTURE_PRIVATE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'not a directory')
        with self.assertRaises(ValueError):
            runner.require_future_outputs_absent(self.root)

    def test_output_escape_alias_and_source_collision_rejected(self):
        with self.assertRaises(ValueError):
            runner._path(self.root, '../escape.json')
        with patch.object(runner.control, 'reject_output_aliases', side_effect=ValueError('alias')):
            with self.assertRaises(ValueError):
                runner.output_paths(self.root)
        source = self.bundle.public_sources[0]
        with self.assertRaises(ValueError):
            runner._publish([(self.root / source['path'], b'{}')], [source], self.root)

    def test_late_source_failure_retracts_only_new_exact_files(self):
        path = self.root / '.runtime/new-proof.json'
        original = runner.files.verify_sources
        calls = 0
        def failing(bound, root):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('late source drift')
            return original(bound, root)
        with patch.object(runner.files, 'verify_sources', side_effect=failing):
            with self.assertRaises(ValueError):
                runner._publish([(path, b'{}\n')], self.bundle.public_sources, self.root)
        self.assertFalse(path.exists())
        path.write_bytes(b'{}\n')
        calls = 0
        with patch.object(runner.files, 'verify_sources', side_effect=failing):
            with self.assertRaises(ValueError):
                runner._publish([(path, b'{}\n')], self.bundle.public_sources, self.root)
        self.assertEqual(path.read_bytes(), b'{}\n')

    def test_failed_report_publication_preserves_spec_and_guard(self):
        self.run_preparation(True)
        before = [(self.root / p).read_bytes() for p in (runner.SPEC, runner.GUARD)]
        path = self.root / runner.REPORT
        path.write_bytes(b'conflicting prior report')
        with self.assertRaises(ValueError):
            self.run_preparation()
        self.assertEqual(before, [(self.root / p).read_bytes() for p in (runner.SPEC, runner.GUARD)])
        self.assertEqual(path.read_bytes(), b'conflicting prior report')

    def test_training_CLI_flag_is_not_available(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                runner.main(['--train'])
        self.assertEqual(stopped.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
