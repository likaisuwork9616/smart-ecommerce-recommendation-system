"""Synthetic execution/source/immutability checks; never read the real dataset."""
import copy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import build_rfm_dataset as entry
from tests.test_rfm_feasibility import fixture


class RFMBuildEntryTests(unittest.TestCase):
    def setUp(self):
        self.scratch = entry.ROOT / '.runtime' / 'stage6_build_entry_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup_root)
        self.tables = fixture()
        old_sources = []
        for number in range(12):
            path = self.root / ('old_source_' + str(number))
            path.write_text('frozen source ' + str(number), encoding='utf-8')
            old_sources.append(entry.base.descriptor(path, self.root))
        self.contract = {
            'format_version': 1, 'policy': entry.frozen.policy(),
            'planned_schemas': entry.frozen.schemas(),
            'columns_read': entry.base.COLUMNS,
            'sources': old_sources,
        }
        entry.base.immutable_write(self.root / entry.frozen.SPEC, self.contract)
        audit = {
            'format_version': 1,
            'specification': entry.base.descriptor(self.root / entry.frozen.SPEC, self.root),
            'policy': self.contract['policy'],
            'results': entry.frozen.audit_support(self.tables),
        }
        entry.base.immutable_write(self.root / entry.frozen.OUTPUT, audit)
        for relative in entry.IMPLEMENTATION:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic implementation binding\n', encoding='utf-8')
        self.original_contract = copy.deepcopy(self.contract)
        self.contract_patch = patch.object(
            entry.frozen, 'specification',
            side_effect=lambda root: copy.deepcopy(self.original_contract))
        self.contract_patch.start()
        self.addCleanup(self.contract_patch.stop)

    def cleanup_root(self):
        target = self.root.resolve()
        if not target.is_relative_to(self.scratch.resolve()) or target == self.scratch.resolve():
            raise ValueError('Synthetic cleanup escaped its private scratch namespace')
        shutil.rmtree(target)

    def freeze(self):
        return entry.run(self.root, specification_only=True)

    def build(self):
        self.freeze()
        with patch.object(entry.base, 'read_tables', return_value=copy.deepcopy(self.tables)):
            return entry.run(self.root, build=True)

    def bytes_snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_requires_exactly_one_action(self):
        for flags in ({}, {'build': True, 'verify': True},
                      {'build': True, 'specification_only': True}):
            with self.assertRaises(ValueError):
                entry.run(self.root, **flags)

    def test_specification_only_binds_exact_twenty_without_building(self):
        with patch.object(entry.base, 'read_tables') as read, \
                patch.object(entry.builder, 'build_dataset') as build:
            result = self.freeze()
        self.assertIn('frozen', result['status'])
        read.assert_not_called()
        build.assert_not_called()
        stored = entry.base.read_json(self.root / entry.SPEC)
        self.assertEqual(len(stored['sources']), 20)
        self.assertEqual(stored, entry.specification(self.root))
        self.assertFalse((self.root / entry.PRIVATE).exists())

    def test_shortened_original_source_list_cannot_bypass_guard(self):
        shortened = copy.deepcopy(self.contract)
        shortened['sources'].pop()
        (self.root / entry.frozen.SPEC).unlink()
        entry.base.immutable_write(self.root / entry.frozen.SPEC, shortened)
        with self.assertRaisesRegex(ValueError, 'Complete frozen contract'):
            self.freeze()
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_changed_original_source_bytes_stop(self):
        (self.root / self.contract['sources'][0]['path']).write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.freeze()

    def test_shortened_execution_source_list_stops_before_tables(self):
        self.freeze()
        spec = entry.base.read_json(self.root / entry.SPEC)
        spec['sources'].pop()
        (self.root / entry.SPEC).unlink()
        entry.base.immutable_write(self.root / entry.SPEC, spec)
        with patch.object(entry.base, 'read_tables') as read:
            with self.assertRaisesRegex(ValueError, 'Build specification differs'):
                entry.run(self.root, build=True)
        read.assert_not_called()

    def test_changed_implementation_bytes_stop_before_tables(self):
        self.freeze()
        (self.root / entry.IMPLEMENTATION[0]).write_text('changed implementation', encoding='utf-8')
        with patch.object(entry.base, 'read_tables') as read:
            with self.assertRaises(ValueError):
                entry.run(self.root, build=True)
        read.assert_not_called()

    def test_whole_build_and_public_aggregate(self):
        result = self.build()
        self.assertEqual(result['customers'], 1)
        self.assertEqual(result['order_decisions'], 1)
        guard = entry.base.read_json(self.root / entry.GUARD)
        self.assertEqual(set(guard['private_bundle_guard']),
                         {'customers.csv', 'order_decisions.csv', 'manifest.json'})
        report = entry.base.read_json(self.root / entry.OUTPUT)
        self.assertTrue(all(report['acceptance'][key] for key in entry.ACCEPTANCE_FLAGS))
        self.assertEqual(report['results']['window']['event_eligible_orders'], 1)
        self.assertFalse(report['policy']['training'])
        self.assertNotIn('private_bundle_guard', report)
        self.assertNotIn('u1', str(report))
        self.assertNotIn('o1', str(report))

    def test_existing_bundle_rebuild_stops_before_source_read(self):
        self.build()
        before = self.bytes_snapshot()
        with patch.object(entry.base, 'read_tables') as read:
            with self.assertRaisesRegex(ValueError, 'already exists'):
                entry.run(self.root, build=True)
        read.assert_not_called()
        self.assertEqual(self.bytes_snapshot(), before)

    def test_partial_control_or_public_report_blocks_build(self):
        self.freeze()
        for relative in (entry.CONTROL, entry.OUTPUT):
            with self.subTest(relative=relative):
                path = self.root / relative
                if relative == entry.CONTROL:
                    path.mkdir(parents=True)
                else:
                    path.write_text('{}', encoding='utf-8')
                with patch.object(entry.base, 'read_tables') as read:
                    with self.assertRaisesRegex(ValueError, 'already exists'):
                        entry.run(self.root, build=True)
                read.assert_not_called()
                path.rmdir() if path.is_dir() else path.unlink()

    def test_verify_is_read_only_and_does_not_rebuild_source_tables(self):
        self.build()
        before = self.bytes_snapshot()
        with patch.object(entry.base, 'read_tables') as read, \
                patch.object(entry.builder, 'build_dataset') as build, \
                patch.object(entry.base, 'immutable_write') as write:
            result = entry.run(self.root, verify=True)
        self.assertEqual(result['status'], 'RFM_dataset_verified_read_only')
        read.assert_not_called()
        build.assert_not_called()
        write.assert_not_called()
        self.assertEqual(self.bytes_snapshot(), before)

    def test_changed_bundle_stops_verify_without_rewriting(self):
        self.build()
        path = self.root / entry.PRIVATE / 'customers.csv'
        path.write_bytes(path.read_bytes() + b'\n')
        before = self.bytes_snapshot()
        with self.assertRaises(ValueError):
            entry.run(self.root, verify=True)
        self.assertEqual(self.bytes_snapshot(), before)

    def test_changed_guard_sources_stop_verify(self):
        self.build()
        path = self.root / entry.GUARD
        guard = entry.base.read_json(path)
        guard['source_bindings'].pop()
        path.unlink()
        entry.base.immutable_write(path, guard)
        with self.assertRaisesRegex(ValueError, 'guard binding differs'):
            entry.run(self.root, verify=True)

    def test_changed_public_aggregate_stops_verify(self):
        self.build()
        path = self.root / entry.OUTPUT
        report = entry.base.read_json(path)
        report['results']['history']['customer_universe'] = 999
        path.unlink()
        entry.base.immutable_write(path, report)
        with self.assertRaisesRegex(ValueError, 'Public aggregate report differs'):
            entry.run(self.root, verify=True)

    def test_guard_version_and_nested_integer_type_impersonation_stops_verify(self):
        self.build()
        path = self.root / entry.GUARD
        original = entry.base.read_json(path)
        mutations = [
            (('format_version',), True), (('format_version',), 1.0),
            (('dataset_contract', 'bytes'), float(original['dataset_contract']['bytes'])),
            (('readback_acceptance', 'rows', 'customers.csv'), True),
            (('readback_acceptance', 'rows', 'customers.csv'), 1.0),
        ]
        for keys, value in mutations:
            with self.subTest(keys=keys, value=value):
                payload = copy.deepcopy(original)
                current = payload
                for key in keys[:-1]:
                    current = current[key]
                current[keys[-1]] = value
                path.unlink()
                entry.base.immutable_write(path, payload)
                before = self.bytes_snapshot()
                with self.assertRaisesRegex(ValueError, 'guard .*differs'):
                    entry.run(self.root, verify=True)
                self.assertEqual(self.bytes_snapshot(), before)

    def test_public_version_and_nested_type_impersonation_stops_verify(self):
        self.build()
        path = self.root / entry.OUTPUT
        original = entry.base.read_json(path)
        mutations = [
            (('format_version',), True), (('format_version',), 1.0),
            (('results', 'history', 'customer_universe'), True),
            (('results', 'history', 'customer_universe'), 1.0),
            (('acceptance', 'all_values_read_back'), 1),
            (('policy', 'training'), 0),
        ]
        for keys, value in mutations:
            with self.subTest(keys=keys, value=value):
                payload = copy.deepcopy(original)
                current = payload
                for key in keys[:-1]:
                    current = current[key]
                current[keys[-1]] = value
                path.unlink()
                entry.base.immutable_write(path, payload)
                before = self.bytes_snapshot()
                with self.assertRaisesRegex(ValueError, 'Public aggregate report differs'):
                    entry.run(self.root, verify=True)
                self.assertEqual(self.bytes_snapshot(), before)

    def test_execution_spec_numeric_type_impersonation_stops_before_tables(self):
        self.freeze()
        path = self.root / entry.SPEC
        original = entry.base.read_json(path)
        for version in (True, 1.0):
            with self.subTest(version=version):
                payload = copy.deepcopy(original)
                payload['format_version'] = version
                path.unlink()
                entry.base.immutable_write(path, payload)
                with patch.object(entry.base, 'read_tables') as read:
                    with self.assertRaisesRegex(ValueError, 'Build specification differs'):
                        entry.run(self.root, build=True)
                read.assert_not_called()

    def test_frozen_contract_numeric_type_impersonation_stops(self):
        path = self.root / entry.frozen.SPEC
        for version in (True, 1.0):
            with self.subTest(version=version):
                payload = copy.deepcopy(self.contract)
                payload['format_version'] = version
                path.unlink()
                entry.base.immutable_write(path, payload)
                with self.assertRaisesRegex(ValueError, 'Complete frozen contract'):
                    self.freeze()

    def test_acceptance_row_counts_require_exact_integer_types(self):
        dataset = entry.builder.build_dataset(self.tables, self.contract)
        acceptance = {key: True for key in entry.ACCEPTANCE_FLAGS}
        acceptance.update(rows={'customers.csv': 1, 'order_decisions.csv': 1}, cells_compared=32)
        for value in (True, 1.0):
            with self.subTest(value=value):
                changed = copy.deepcopy(acceptance)
                changed['rows']['customers.csv'] = value
                with self.assertRaisesRegex(ValueError, 'readback population differs'):
                    entry._accepted(changed, dataset)

    def test_support_counts_require_exact_integer_types(self):
        dataset = entry.builder.build_dataset(self.tables, self.contract)
        for value in (True, 1.0):
            with self.subTest(value=value):
                changed = copy.deepcopy(dataset['summary'])
                changed['history']['customer_universe'] = value
                with self.assertRaisesRegex(ValueError, 'frozen support'):
                    entry._support_matches(changed, self.root)

    def test_source_change_during_table_read_stops_before_builder(self):
        self.freeze()
        def change_source(root):
            (self.root / self.contract['sources'][0]['path']).write_text('changed', encoding='utf-8')
            return copy.deepcopy(self.tables)
        with patch.object(entry.base, 'read_tables', side_effect=change_source), \
                patch.object(entry.builder, 'build_dataset') as build:
            with self.assertRaises(ValueError):
                entry.run(self.root, build=True)
        build.assert_not_called()
        self.assertFalse((self.root / entry.PRIVATE).exists())

    def test_build_spec_change_during_table_read_stops_before_builder(self):
        self.freeze()
        def change_spec(root):
            spec = entry.base.read_json(self.root / entry.SPEC)
            spec['sources'].pop()
            (self.root / entry.SPEC).unlink()
            entry.base.immutable_write(self.root / entry.SPEC, spec)
            return copy.deepcopy(self.tables)
        with patch.object(entry.base, 'read_tables', side_effect=change_spec), \
                patch.object(entry.builder, 'build_dataset') as build:
            with self.assertRaises(ValueError):
                entry.run(self.root, build=True)
        build.assert_not_called()

    def test_builder_failure_stops_before_private_artifact_write(self):
        self.freeze()
        with patch.object(entry.base, 'read_tables', return_value=self.tables), \
                patch.object(entry.builder, 'build_dataset', side_effect=ValueError('synthetic failure')), \
                patch.object(entry.artifacts, 'write_bundle') as write:
            with self.assertRaisesRegex(ValueError, 'synthetic failure'):
                entry.run(self.root, build=True)
        write.assert_not_called()
        self.assertFalse((self.root / entry.GUARD).exists())
        self.assertFalse((self.root / entry.OUTPUT).exists())

    def test_prior_support_mismatch_stops_before_write(self):
        self.freeze()
        dataset = entry.builder.build_dataset(self.tables, self.contract)
        dataset['summary']['window']['event_eligible_orders'] = 2
        with patch.object(entry.base, 'read_tables', return_value=self.tables), \
                patch.object(entry.builder, 'build_dataset', return_value=dataset), \
                patch.object(entry.artifacts, 'write_bundle') as write:
            with self.assertRaisesRegex(ValueError, 'frozen support'):
                entry.run(self.root, build=True)
        write.assert_not_called()

    def test_failed_readback_acceptance_prevents_guard_and_report(self):
        self.freeze()
        with patch.object(entry.base, 'read_tables', return_value=self.tables), \
                patch.object(entry.artifacts, 'write_bundle', return_value={}), \
                patch.object(entry.artifacts, 'verify_bundle') as verify:
            with self.assertRaisesRegex(ValueError, 'readback acceptance failed'):
                entry.run(self.root, build=True)
        verify.assert_not_called()
        self.assertFalse((self.root / entry.GUARD).exists())
        self.assertFalse((self.root / entry.OUTPUT).exists())

    def test_verify_missing_output_does_not_create_anything(self):
        self.freeze()
        before = self.bytes_snapshot()
        with self.assertRaises(FileNotFoundError):
            entry.run(self.root, verify=True)
        self.assertEqual(self.bytes_snapshot(), before)


if __name__ == '__main__':
    unittest.main()
