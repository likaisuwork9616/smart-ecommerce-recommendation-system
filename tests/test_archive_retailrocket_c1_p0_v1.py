"""Archive I/O safety only; all synthetic scratch remains in the shop directory."""
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import uuid
import warnings
import zipfile

from scripts import archive_retailrocket_c1_p0_v1 as a


class ArchiveTests(unittest.TestCase):
    def scratch(self):
        path = a.inside(a.ROOT, a.VERIFY + '/synthetic/' + uuid.uuid4().hex)
        path.mkdir(parents=True)
        return path

    def put(self, root, name, content=b'synthetic evidence\n'):
        path = a.inside(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return a.descriptor(root, name)

    def fixture(self):
        root = self.scratch()
        item = self.put(root, 'docs/evidence.md', '合成研究證據\n'.encode())
        return root, {'release_id': 'synthetic', 'files': [dict(item, live_role='frozen_research_source')],
                      'external_dependencies': [], 'research_facts': {'synthetic': True}}

    def gates(self, root):
        for n, path in enumerate(a.GATES):
            if n < 2:
                value = {'status': ('locked_at_specification_freeze', 'locked_at_development_entry_freeze')[n],
                         'test_ranking_started': False, 'logical_tests_consumed': 0}
            else:
                value = {'state': 'locked', 'C1_test_authorized': False, 'logical_test_runs_consumed_this_round': 0}
            self.put(root, path, a.encoded(value))

    def release_fixture(self):
        root, manifest = self.fixture()
        self.gates(root)
        for name in [a.C1 + '/proof.bin', a.P0 + '/proof.bin', *a.GATES]:
            if not a.inside(root, name).exists():
                self.put(root, name)
            manifest['files'].append(dict(a.descriptor(root, name), live_role='frozen_research_source'))
        manifest['files'].append(dict(self.put(root, 'README.md'), live_role='mutable_context_snapshot'))
        manifest['external_dependencies'].append(dict(self.put(root, 'data/raw/dependency.bin'),
                                                       live_role='external_dependency_not_archived'))
        a.inside(root, a.REPORT).parent.mkdir(parents=True)
        return root, manifest

    def publish(self, root, manifest):
        return a.publish(root, manifest['files'], manifest['external_dependencies'], manifest['research_facts'],
                         {'tests_run': 0, 'synthetic_fixture': True})

    def collection_fixture(self):
        root = self.scratch()
        self.gates(root)
        frozen = self.put(root, 'docs/frozen.md')
        dependency = self.put(root, 'data/raw/dependency.bin')
        requirements = self.put(root, 'requirements-lock.txt')
        self.put(root, 'README.md')
        nested = self.put(root, 'shop-mysql-runtime/retailrocket_dataset_v1/output_guard.json',
                          a.encoded({'sources': [dependency], 'outputs': [frozen]}))
        p0 = self.put(root, a.P0 + '/proof.bin')
        p0_guard = self.put(root, a.TOP_GUARDS[1], a.encoded({'sources': [nested, requirements], 'outputs': [p0]}))
        c1 = self.put(root, a.C1 + '/proof.bin')
        self.put(root, a.TOP_GUARDS[0], a.encoded({'sources': [p0_guard, *[a.descriptor(root, n) for n in a.GATES]],
                                                 'outputs': [c1]}))
        return root

    def collect(self, root):
        with patch.object(a, 'EXTRAS', []), patch.object(a, 'SNAPSHOTS', ['README.md', 'requirements-lock.txt']):
            return a.collect(root)

    def test_crc_sha_full_readback(self):
        root, manifest = self.fixture()
        path = root / 'archive.zip'
        a.pack(root, path, manifest)
        restored, checked = a.inspect_archive(path, hashlib.sha256(a.encoded(manifest)).hexdigest())
        self.assertEqual(restored, manifest)
        self.assertEqual(checked['payload_files'], 1)
        self.assertTrue(checked['all_payload_CRC_and_SHA256_passed'])

    def test_original_utf8_preserved(self):
        root, manifest = self.fixture()
        a.pack(root, root / 'archive.zip', manifest)
        with zipfile.ZipFile(root / 'archive.zip') as z:
            self.assertEqual(z.read('docs/evidence.md'), (root / 'docs/evidence.md').read_bytes())

    def test_source_mutation_rejected(self):
        root, manifest = self.fixture()
        (root / 'docs/evidence.md').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            a.pack(root, root / 'archive.zip', manifest)

    def test_missing_source_rejected(self):
        root, manifest = self.fixture()
        manifest['files'][0]['path'] = 'missing.bin'
        with self.assertRaises(FileNotFoundError):
            a.pack(root, root / 'archive.zip', manifest)

    def test_archive_no_overwrite(self):
        root, manifest = self.fixture()
        path = root / 'archive.zip'
        a.pack(root, path, manifest)
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            a.pack(root, path, manifest)
        self.assertEqual(before, path.read_bytes())

    def test_archive_destination_cannot_leave_root(self):
        root, manifest = self.fixture()
        destination = root.parent / (uuid.uuid4().hex + '.zip')
        with self.assertRaises(ValueError):
            a.pack(root, destination, manifest)
        self.assertFalse(destination.exists())

    def test_unsafe_member_names(self):
        for name in ['../escape', '/absolute', 'E:/outside', 'a\\b', 'a//b', './a', 'a/../b',
                     'a/', 'a\0b', 'CON', 'a/NUL.txt', 'a.', 'a ', 'x?y', 'COM1.bin']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                a.safe_name(name)

    def test_resolved_path_cannot_leave_shop(self):
        root = self.scratch()
        # Resolution check is independent of lexical '..' rejection (junction/symlink case).
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            return root.parent if path.name == 'linked.txt' else original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve), self.assertRaises(ValueError):
            a.inside(root, 'linked.txt')

    def test_source_wrong_size_or_hash_rejected(self):
        root, manifest = self.fixture()
        for change in ({'bytes': 0}, {'sha256': '0' * 64}):
            with self.assertRaises(ValueError):
                a.assert_descriptor(root, dict(manifest['files'][0], **change))

    def test_conflicting_descriptor_rejected(self):
        _, manifest = self.fixture()
        item = manifest['files'][0]
        with self.assertRaises(ValueError):
            a.normalize([item, dict(item, sha256='0' * 64)])
        self.assertEqual(len(a.normalize([item, item])), 1)

    def test_manifest_hash_change_rejected(self):
        root, manifest = self.fixture()
        a.pack(root, root / 'archive.zip', manifest)
        with self.assertRaises(ValueError):
            a.inspect_archive(root / 'archive.zip', '0' * 64)

    def test_missing_member_rejected(self):
        root, manifest = self.fixture()
        with zipfile.ZipFile(root / 'bad.zip', 'x') as z:
            z.writestr(a.MANIFEST_MEMBER, a.encoded(manifest))
        with self.assertRaises(ValueError):
            a.inspect_archive(root / 'bad.zip')

    def test_valid_crc_but_changed_payload_rejected(self):
        root, manifest = self.fixture()
        with zipfile.ZipFile(root / 'bad.zip', 'x') as z:
            z.writestr(a.MANIFEST_MEMBER, a.encoded(manifest))
            z.writestr('docs/evidence.md', b'wrong payload')
        with self.assertRaises(ValueError):
            a.inspect_archive(root / 'bad.zip')

    def test_corrupted_payload_crc_rejected(self):
        root, manifest = self.fixture()
        path = root / 'bad.zip'
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_STORED) as z:
            z.writestr(a.MANIFEST_MEMBER, a.encoded(manifest))
            z.writestr('docs/evidence.md', (root / 'docs/evidence.md').read_bytes())
            offset = z.getinfo('docs/evidence.md').header_offset
        raw = bytearray(path.read_bytes())
        name_len, extra_len = struct.unpack_from('<HH', raw, offset + 26)
        raw[offset + 30 + name_len + extra_len] ^= 1
        path.write_bytes(raw)
        with self.assertRaises(zipfile.BadZipFile):
            a.inspect_archive(path)

    def test_duplicate_zip_member_rejected(self):
        root, manifest = self.fixture()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(root / 'bad.zip', 'x') as z:
                z.writestr(a.MANIFEST_MEMBER, a.encoded(manifest))
                z.writestr('docs/evidence.md', b'1')
                z.writestr('docs/evidence.md', b'2')
        with self.assertRaises(ValueError):
            a.inspect_archive(root / 'bad.zip')

    def test_case_alias_and_unsafe_zip_members_rejected(self):
        for name in ['DOCS/evidence.md', '../outside']:
            root, manifest = self.fixture()
            with zipfile.ZipFile(root / 'bad.zip', 'x') as z:
                z.writestr(a.MANIFEST_MEMBER, a.encoded(manifest))
                z.writestr('docs/evidence.md', b'1')
                z.writestr(name, b'2')
            with self.assertRaises(ValueError):
                a.inspect_archive(root / 'bad.zip')

    def test_duplicate_or_overlap_manifest_inventory_rejected(self):
        for kind in ['files', 'external_dependencies']:
            root, manifest = self.fixture()
            manifest[kind].append(manifest['files'][0])
            with zipfile.ZipFile(root / 'bad.zip', 'x') as z:
                z.writestr(a.MANIFEST_MEMBER, a.encoded(manifest))
                z.writestr('docs/evidence.md', (root / 'docs/evidence.md').read_bytes())
            with self.assertRaises(ValueError):
                a.inspect_archive(root / 'bad.zip')

    def test_all_four_gates_checked(self):
        root = self.scratch()
        self.gates(root)
        a.check_locked(root)
        for n, name in enumerate(a.GATES):
            original = a.inside(root, name).read_bytes()
            value = a.read(a.inside(root, name))
            value['logical_tests_consumed' if n < 2 else 'logical_test_runs_consumed_this_round'] = 1
            a.inside(root, name).write_bytes(a.encoded(value))
            with self.assertRaises(ValueError):
                a.check_locked(root)
            a.inside(root, name).write_bytes(original)

    def test_final_test_failure_paths_rejected(self):
        for name in a.ABSENT:
            root = self.scratch()
            self.gates(root)
            self.put(root, name)
            with self.assertRaises(ValueError):
                a.check_locked(root)

    def test_partial_release_preserved(self):
        root = self.scratch()
        a.inside(root, a.PRIVATE).mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            a.archive_release(root)
        self.assertFalse(a.inside(root, a.REPORT).exists())

    def test_successful_release_p0_and_external_bytes_unchanged(self):
        root, manifest = self.release_fixture()
        before = {d['path']: a.digest(a.inside(root, d['path'])) for d in manifest['files'] + manifest['external_dependencies']}
        receipt = self.publish(root, manifest)
        self.assertEqual(receipt['status'], 'C1_P0_research_handoff_evidence_archived_and_verified')
        self.assertEqual(a.verify(root)['status'], 'archive_and_live_frozen_evidence_dependencies_verified')
        self.assertEqual(before, {name: a.digest(a.inside(root, name)) for name in before})
        with zipfile.ZipFile(a.inside(root, a.ARCHIVE)) as z:
            self.assertNotIn('data/raw/dependency.bin', z.namelist())

    def test_mutable_index_may_evolve_but_frozen_payload_may_not(self):
        root, manifest = self.release_fixture()
        self.publish(root, manifest)
        self.put(root, 'README.md', b'updated index')
        self.assertFalse(a.verify(root)['research_recomputed'])
        self.put(root, 'docs/evidence.md', b'changed frozen source')
        with self.assertRaises(ValueError):
            a.verify(root)

    def test_archive_only_survives_unavailable_live_dependency(self):
        root, manifest = self.release_fixture()
        self.publish(root, manifest)
        self.put(root, 'data/raw/dependency.bin', b'unavailable original')
        self.assertEqual(a.verify(root, archive_only=True)['status'], 'archive_only_verified')
        with self.assertRaises(ValueError):
            a.verify(root)

    def test_post_release_gate_or_namespace_change_rejected(self):
        root, manifest = self.release_fixture()
        self.publish(root, manifest)
        self.put(root, a.P0 + '/unexpected.bin')
        with self.assertRaises(ValueError):
            a.verify(root)

    def test_publish_failure_keeps_partial_zip_and_marker(self):
        root, manifest = self.release_fixture()
        self.put(root, 'docs/evidence.md', b'changed before archiving')
        with self.assertRaises(ValueError):
            self.publish(root, manifest)
        self.assertTrue(a.inside(root, a.PRIVATE + '/failure.json').is_file())
        self.assertTrue(a.inside(root, a.ARCHIVE).with_suffix('.zip.partial').is_file())
        with self.assertRaises(FileExistsError):
            a.archive_release(root)

    def test_recursive_guard_and_package_dependency_separation(self):
        root = self.collection_fixture()
        payload, dependencies = self.collect(root)
        self.assertIn('docs/frozen.md', {d['path'] for d in payload})
        self.assertEqual([d['path'] for d in dependencies], ['data/raw/dependency.bin'])
        roles = {d['path']: d['live_role'] for d in payload}
        self.assertEqual(roles['README.md'], 'mutable_context_snapshot')
        self.assertEqual(roles['requirements-lock.txt'], 'frozen_research_source')

    def test_guard_bound_result_mutation_rejected_by_collection(self):
        root = self.collection_fixture()
        self.put(root, a.P0 + '/proof.bin', b'tampered P0')
        with self.assertRaises(ValueError):
            self.collect(root)

    def test_unbound_namespace_file_rejected_by_collection(self):
        root = self.collection_fixture()
        self.put(root, a.C1 + '/unbound.bin')
        with self.assertRaises(ValueError):
            self.collect(root)

    def test_recursive_dependency_mutation_rejected_by_collection(self):
        root = self.collection_fixture()
        self.put(root, 'data/raw/dependency.bin', b'tampered raw dependency')
        with self.assertRaises(ValueError):
            self.collect(root)


if __name__ == '__main__':
    unittest.main()
