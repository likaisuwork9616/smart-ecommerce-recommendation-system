"""Contract-only synthetic mutation/publication tests; no model imports or fit."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import freeze_review_month_ablation as subject


@contextmanager
def temporary_root():
    # Default directory mode avoids Windows restricted-token 0700 temp ACLs.
    parent = (subject.ROOT / '.runtime' / 'month_ablation_contract_tests').resolve()
    if not parent.is_relative_to(subject.ROOT.resolve()):
        raise RuntimeError('Temporary directory must stay inside the project')
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / uuid4().hex
    root.mkdir()
    try:
        yield root
    finally:
        if root.resolve().parent != parent:
            raise RuntimeError('Unexpected temporary cleanup path')
        shutil.rmtree(root)


def parent_spec():
    return subject.files.read_json(subject.ROOT / subject.baseline.SPEC)


def fixture(root):
    for name in (subject.CODE, subject.TESTS):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic contract code\n')
    private = root / '.runtime' / 'synthetic_source.dat'
    private.parent.mkdir(exist_ok=True)
    private.write_bytes(b'unchanged private metadata\n')
    dataset = subject.files.read_json(subject.ROOT / subject.files.SPEC)
    return parent_spec(), dataset, {}, [], [subject.files.descriptor(private, root)]


def safe_fixture_paths():
    return patch.object(subject.files, 'safe_output', side_effect=lambda path, *args, **kw: Path(path).resolve())


class ProtocolTests(unittest.TestCase):
    def test_exact_five_changes_and_parent_unchanged(self):
        parent = parent_spec()['protocol']
        snapshot = deepcopy(parent)
        treatment, changes = subject.ablation_protocol(parent)
        self.assertEqual(parent, snapshot)
        self.assertEqual([change['path'] for change in changes], list(subject.ALLOWED_PATHS))
        self.assertEqual(subject.verify_ablation_protocol(parent, treatment), changes)
        restored = deepcopy(treatment)
        restored['features'] = deepcopy(parent['features'])
        self.assertEqual(restored, parent)

    def test_retained_three_definitions_and_32_dimensions(self):
        parent = parent_spec()
        protocol, _ = subject.ablation_protocol(parent['protocol'])
        f = protocol['features']
        self.assertEqual(f['primary_order'], ['purchase_dayofweek', 'purchase_hour', 'approval_wait_hours'])
        self.assertEqual(f['categorical'], {'purchase_dayofweek': list(range(7)), 'purchase_hour': list(range(24))})
        self.assertEqual(f['one_hot']['columns'], 31)
        self.assertEqual(f['output_columns'], 32)
        self.assertIsNone(f['one_hot']['drop'])
        self.assertEqual(f['numeric'], parent['protocol']['features']['numeric'])

    def test_unrelated_protocol_changes_rejected(self):
        parent = parent_spec()['protocol']
        base, _ = subject.ablation_protocol(parent)
        mutations = [('main_model', 'class_weight', 'balanced'),
                     ('main_model', 'tol', 1e-4), ('selection', 'C_candidates', [.1]),
                     ('selection', 'actual_selected_C', .1), ('preprocessing', 'unknown_in_fit', True),
                     ('future_evaluation', 'metric_rows', 'all_rows'),
                     ('protected_stage4', 'daily_budget', .2), ('reference', 'selection_candidate', True)]
        for group, name, value in mutations:
            with self.subTest(group=group, name=name):
                bad = deepcopy(base)
                bad[group][name] = value
                with self.assertRaises(ValueError):
                    subject.verify_ablation_protocol(parent, bad)

    def test_disallowed_feature_transform_and_reordering_rejected(self):
        parent = parent_spec()['protocol']
        base, _ = subject.ablation_protocol(parent)
        for mutation in ('log', 'one_hot_drop', 'order'):
            bad = deepcopy(base)
            if mutation == 'log':
                bad['features']['numeric']['log_clip_winsor'] = True
            elif mutation == 'one_hot_drop':
                bad['features']['one_hot']['drop'] = 'first'
            else:
                bad['features']['primary_order'].reverse()
            with self.assertRaises(ValueError):
                subject.verify_ablation_protocol(parent, bad)

    def test_parent_wrong_dimensions_or_missing_month_rejected(self):
        for name in ('primary_order', 'categorical', 'one_hot', 'output_columns', 'output_order'):
            bad = deepcopy(parent_spec()['protocol'])
            if name == 'categorical':
                bad['features'][name]['purchase_month'] = []
            elif name == 'one_hot':
                bad['features'][name]['columns'] = 42
            else:
                bad['features'][name] = None
            with self.assertRaises(ValueError):
                subject.ablation_protocol(bad)

    def test_treatment_selection_independent_and_null_differences(self):
        plan = subject.comparison_plan()
        self.assertIn('independent_original_inner_AP_rule', plan['treatment_C_selection'])
        self.assertFalse(plan['control_refit_or_reselection'])
        self.assertFalse(plan['training_authorized_this_run'])
        self.assertEqual(plan['future_treatment_inner_fits'] + plan['future_treatment_outer_refits'], 12)
        self.assertEqual(plan['future_control_fits'], 0)
        self.assertIn('either_arm_null', plan['paired_metric_null_policy'])
        self.assertIn('both_arms', plan['paired_macro_support'])

    def test_model_import_gate(self):
        # Other suites may already have imported sklearn; test the gate's input
        # explicitly without importing or executing any estimator here.
        unrelated = {name: module for name, module in sys.modules.items()
                     if name != 'sklearn' and not name.startswith('sklearn.')}
        with patch.dict(sys.modules, unrelated, clear=True):
            subject.require_no_model_imports()
        with patch.dict(sys.modules, {'sklearn': object()}):
            with self.assertRaises(RuntimeError):
                subject.require_no_model_imports()


class GuardAndPublicationTests(unittest.TestCase):
    def test_freeze_and_identical_replay(self):
        with temporary_root() as root, safe_fixture_paths():
            provenance = fixture(root)
            spec = subject.freeze(provenance, root)
            before = [(root / name).read_bytes() for name in (subject.SPEC, subject.GUARD)]
            self.assertEqual(subject.freeze(provenance, root), spec)
            self.assertEqual(before, [(root / name).read_bytes() for name in (subject.SPEC, subject.GUARD)])
            verified, _, _ = subject.verify_specification(provenance, root)
            self.assertEqual(verified['actual_execution']['fits'], 0)
            self.assertTrue(all(value == 0 for value in verified['actual_execution'].values()))
            self.assertIsNone(verified['actual_selected_C'])
            self.assertEqual(verified['dataset_protocol_unchanged'], provenance[1]['protocol'])
            self.assertEqual(verified['dataset_calendar_unchanged'], provenance[0]['dataset_calendar_unchanged'])

    def test_changed_code_or_private_bytes_rejected(self):
        for name in (subject.CODE, '.runtime/synthetic_source.dat'):
            with self.subTest(name=name), temporary_root() as root, safe_fixture_paths():
                provenance = fixture(root)
                subject.freeze(provenance, root)
                (root / name).write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    subject.verify_specification(provenance, root)

    def test_changed_spec_or_guard_rejected(self):
        for name in (subject.SPEC, subject.GUARD):
            with self.subTest(name=name), temporary_root() as root, safe_fixture_paths():
                provenance = fixture(root)
                subject.freeze(provenance, root)
                value = subject.files.read_json(root / name)
                value['format_version'] = 999
                (root / name).write_bytes(subject.files.json_bytes(value))
                with self.assertRaises(ValueError):
                    subject.verify_specification(provenance, root)

    def test_preflight_collision_does_not_write_spec(self):
        with temporary_root() as root, safe_fixture_paths():
            provenance = fixture(root)
            path = root / subject.GUARD
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'existing unrelated guard')
            with self.assertRaises(ValueError):
                subject.freeze(provenance, root)
            self.assertFalse((root / subject.SPEC).exists())
            self.assertEqual(path.read_bytes(), b'existing unrelated guard')

    def test_synthetic_audit_publication_and_identical_replay(self):
        with temporary_root() as root, safe_fixture_paths():
            provenance = fixture(root)
            subject.freeze(provenance, root)
            metadata = ({'raw_orders': 2, 'cohort_orders': 2, 'membership_rows': 4, 'role_blocks': 2}, {}, [])
            with patch.object(subject, 'load_provenance', return_value=provenance), \
                    patch.object(subject, 'audit_metadata', return_value=metadata), \
                    patch.object(subject, 'require_no_model_imports'):
                result = subject.run(root)
                payload = (root / subject.REPORT).read_bytes()
                self.assertEqual(subject.run(root), result)
                self.assertEqual((root / subject.REPORT).read_bytes(), payload)
                self.assertEqual(result['actual_execution']['metrics_computed'], 0)

    def test_late_source_failure_withdraws_only_new_report(self):
        with temporary_root() as root, safe_fixture_paths():
            provenance = fixture(root)
            subject.freeze(provenance, root)
            verify = subject.files.verify_sources

            def fail_late(items, where):
                if (root / subject.REPORT).exists():
                    raise ValueError('synthetic late input change')
                return verify(items, where)

            with patch.object(subject, 'load_provenance', return_value=provenance), \
                    patch.object(subject, 'audit_metadata', return_value=({}, {}, [])), \
                    patch.object(subject, 'require_no_model_imports'), \
                    patch.object(subject.files, 'verify_sources', side_effect=fail_late):
                with self.assertRaisesRegex(ValueError, 'late input change'):
                    subject.run(root)
            self.assertFalse((root / subject.REPORT).exists())
            self.assertTrue((root / subject.SPEC).exists())

    def test_source_conflict_and_missing_or_changed_parent_fail(self):
        a = {'path': 'source', 'bytes': 1, 'sha256': 'a'}
        with self.assertRaises(ValueError):
            subject.merge_sources([a], [dict(a, sha256='b')])
        with temporary_root() as root:
            with self.assertRaises((FileNotFoundError, ValueError)):
                subject.load_provenance(root)
            for name in subject.PINNED:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'ancestor changed'):
                subject.load_provenance(root)


if __name__ == '__main__':
    unittest.main()
