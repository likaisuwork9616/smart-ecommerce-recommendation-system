"""Archive I/O safety only; all synthetic scratch remains in the shop directory."""
import hashlib
import copy
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import uuid
import warnings
import zipfile

from scripts import archive_retailrocket_three_arm_v1 as a


class ArchiveTests(unittest.TestCase):
    def scratch(self):
        path = a.inside(a.ROOT, a.VERIFY + '/test-work/' + uuid.uuid4().hex)
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
                value = {'state': 'locked', ('C1_test_authorized' if n < 4 else 'D1_test_authorized'): False, 'logical_test_runs_consumed_this_round': 0}
            self.put(root, path, a.encoded(value))

    def release_fixture(self):
        root, manifest = self.fixture()
        self.gates(root)
        for name in [a.D1 + '/proof.bin', a.C1 + '/proof.bin', a.P0 + '/proof.bin', *a.GATES]:
            if not a.inside(root, name).exists():
                self.put(root, name)
            manifest['files'].append(dict(a.descriptor(root, name), live_role='frozen_research_source'))
        manifest['files'].append(dict(self.put(root, 'README.md'), live_role='mutable_context_snapshot'))
        manifest['external_dependencies'].append(dict(self.put(root, 'data/raw/dependency.bin'),
                                                       live_role='external_dependency_not_archived'))
        manifest['external_dependencies'].append(dict(self.put(root, a.PRIOR_ARCHIVE, b'previous archive'),
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
        prior_archive = self.put(root, a.PRIOR_ARCHIVE, b'previous immutable archive bytes')
        self.put(root, 'README.md')
        nested = self.put(root, 'shop-mysql-runtime/retailrocket_dataset_v1/output_guard.json',
                          a.encoded({'sources': [dependency], 'outputs': [frozen]}))
        p0 = self.put(root, a.P0 + '/proof.bin')
        p0_guard = self.put(root, a.P0 + '/output_guard.json', a.encoded({'sources': [nested, requirements], 'outputs': [p0]}))
        c1 = self.put(root, a.C1 + '/proof.bin')
        c1_guard = self.put(root, a.C1 + '/output_guard.json', a.encoded({'sources': [p0_guard], 'outputs': [c1]}))
        d1 = self.put(root, a.D1 + '/proof.bin')
        self.put(root, a.D1 + '/output_guard.json', a.encoded({'sources': [c1_guard, prior_archive, *[a.descriptor(root, n) for n in a.GATES]],
                                                              'outputs': [d1]}))
        return root

    def collect(self, root):
        with patch.object(a, 'EXTRAS', []), patch.object(a, 'SNAPSHOTS', ['README.md', 'requirements-lock.txt']):
            return a.collect(root)

    def fact_fixture(self):
        """Tiny fabricated aggregates; no actual query, model or dataset is read."""
        root = self.scratch()
        scope = {'reserved_test_state': 'locked', 'reserved_test_ranked_queries': 0, 'final_refits': 0}
        arms = {name: {'metrics': {'ndcg': score}, 'support_floor_queries': 1669,
                       'slices': {'target_model': {'all_zero': {'queries': 11943, 'synthetic': True}}}}
                for name, score in [('P0', .1), ('C1', .3), ('D1', .2)]}
        comparisons = {'D1_minus_C1': {'delta_metrics': {'ndcg': -.1}},
                       'D1_minus_P0': {'delta_metrics': {'ndcg': .1}}}
        small = {family: {group: {'queries': number}} for family, group, number in
                 [('current_basket', 'multiple', 56), ('target_basket', 'multiple', 53), ('target_model', 'mixed', 3)]}
        p = {'status': 'development_fit_and_full_validation_independently_accepted',
             'scope': dict(scope, real_primary_fits=1, validation_ranked_queries=166897),
             'validation': copy.deepcopy(arms['P0']), 'fit_audit': {'fit_id': 'synthetic-p0'}}
        c = {'status': 'C1_paired_validation_and_bootstrap_independently_accepted',
             'scope': dict(scope, real_C1_primary_fits=1, P0_refits_or_rerankings=0, validation_queries=166897),
             'validation': {'arms': {name: copy.deepcopy(arms[name]) for name in ('P0', 'C1')},
                            'paired': {'delta_metrics': {'ndcg': .2}},
                            'uncertainty': {'replicates': 2000, 'mean_delta': .2, 'interval': [.19, .21]},
                            'diagnostics': {'fallback_reason': {'synthetic': 2}}},
             'resources': {'synthetic': True}, 'fit_audit': {'fit_id': 'synthetic-c1'}}
        d = {'status': 'D1_three_arm_validation_and_bootstrap_independently_accepted',
             'scope': dict(scope, real_D1_primary_fits=1, P0_C1_refits_or_rerankings=0,
                           validation_queries=166897, training_ranked_queries=0),
             'validation': {'arms': arms, 'paired': {'queries': 166897, 'visitors': 62235,
                                                    'comparisons': comparisons, 'conditional': {'synthetic': True}, 'slices': small},
                            'uncertainty': {'replicates': 2000, 'visitors': 62235, 'mean_delta': -.1, 'interval': [-.11, -.09]},
                            'roster_sha256': 'synthetic-roster',
                            'diagnostics': {'fallback_reason': {'synthetic': 3}, 'c1_full_fallback_implication': {'synthetic': True},
                                            'incoming_target_support': {'synthetic': True}}},
             'resources': {'synthetic': True}, 'fit_audit': {'fit_id': 'synthetic-d1'}}
        reports = {'reports/stage9/retailrocket_popularity_v1_development.json': p,
                   'reports/stage10/retailrocket_cooccurrence_v1_validation.json': c,
                   'reports/stage11/retailrocket_directed_v1_validation.json': d}
        statuses = ['all_validation_output_cells_and_aggregates_independently_accepted',
                    'complete_C1_model_lineage_queries_nested_values_and_bootstrap_accepted',
                    'complete_D1_counts_lineage_three_arm_queries_and_bootstrap_accepted']
        for (name, report), status in zip(list(reports.items()), statuses):
            result = self.put(root, name, a.encoded(report))
            acceptance = {'status': status, 'result': result, 'scope': copy.deepcopy(report['scope']),
                          'readback': {'synthetic': True}}
            acceptance_name = name.replace('.json', '_acceptance.json')
            self.put(root, acceptance_name, a.encoded(acceptance))
            reports[acceptance_name] = acceptance
        return root, reports

    def rewrite_report_and_acceptance(self, root, reports, name):
        report = reports[name]
        result = self.put(root, name, a.encoded(report))
        acceptance = reports[name.replace('.json', '_acceptance.json')]
        acceptance.update(result=result, scope=copy.deepcopy(report['scope']))
        self.put(root, name.replace('.json', '_acceptance.json'), a.encoded(acceptance))

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

    def test_all_six_gates_checked(self):
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

    def test_successful_release_all_three_arms_and_external_bytes_unchanged(self):
        root, manifest = self.release_fixture()
        before = {d['path']: a.digest(a.inside(root, d['path'])) for d in manifest['files'] + manifest['external_dependencies']}
        receipt = self.publish(root, manifest)
        self.assertEqual(receipt['status'], 'D1_C1_P0_research_handoff_evidence_archived_and_verified')
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
        self.assertEqual({d['path'] for d in dependencies}, {'data/raw/dependency.bin', a.PRIOR_ARCHIVE})
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

    def test_d1_gate_cannot_reuse_c1_authorization(self):
        root = self.scratch()
        self.gates(root)
        for name in a.GATES[4:]:
            original = a.inside(root, name).read_bytes()
            value = a.read(a.inside(root, name))
            value.pop('D1_test_authorized')
            value['C1_test_authorized'] = False
            self.put(root, name, a.encoded(value))
            with self.assertRaises(ValueError):
                a.check_locked(root)
            self.put(root, name, original)

    def test_d1_authorization_or_unlocked_gate_rejected(self):
        for name in a.GATES[4:]:
            for change in ({'D1_test_authorized': True}, {'state': 'unlocked'}):
                root = self.scratch()
                self.gates(root)
                value = a.read(a.inside(root, name))
                self.put(root, name, a.encoded(dict(value, **change)))
                with self.assertRaises(ValueError):
                    a.check_locked(root)

    def test_all_three_namespaces_collected_and_frozen(self):
        root = self.collection_fixture()
        files, _ = self.collect(root)
        paths = {d['path'] for d in files}
        for prefix in (a.D1, a.C1, a.P0):
            self.assertEqual({prefix + '/proof.bin', prefix + '/output_guard.json'},
                             {path for path in paths if path.startswith(prefix + '/')})

    def test_all_three_result_mutations_rejected(self):
        for prefix in (a.D1, a.C1, a.P0):
            root = self.collection_fixture()
            self.put(root, prefix + '/proof.bin', b'modified result')
            with self.assertRaises(ValueError):
                self.collect(root)

    def test_all_three_extra_result_files_rejected(self):
        for prefix in (a.D1, a.C1, a.P0):
            root = self.collection_fixture()
            self.put(root, prefix + '/unexpected.bin')
            with self.assertRaises(ValueError):
                self.collect(root)

    def test_prior_archive_is_hash_bound_external_dependency(self):
        root = self.collection_fixture()
        files, dependencies = self.collect(root)
        self.assertNotIn(a.PRIOR_ARCHIVE, {d['path'] for d in files})
        prior = next(d for d in dependencies if d['path'] == a.PRIOR_ARCHIVE)
        self.assertEqual(prior['sha256'], a.digest(a.inside(root, a.PRIOR_ARCHIVE)))
        self.assertEqual(prior['live_role'], 'external_dependency_not_archived')
        self.put(root, a.PRIOR_ARCHIVE, b'tampered historical archive')
        with self.assertRaises(ValueError):
            self.collect(root)

    def test_unbound_prior_archive_is_not_silently_accepted(self):
        root = self.collection_fixture()
        guard_name = a.D1 + '/output_guard.json'
        guard = a.read(a.inside(root, guard_name))
        guard['sources'] = [d for d in guard['sources'] if d['path'] != a.PRIOR_ARCHIVE]
        self.put(root, guard_name, a.encoded(guard))
        with self.assertRaises(ValueError):
            self.collect(root)

    def test_live_prior_archive_corruption_rejected_but_package_survives(self):
        root, manifest = self.release_fixture()
        self.publish(root, manifest)
        with zipfile.ZipFile(a.inside(root, a.ARCHIVE)) as archive:
            self.assertNotIn(a.PRIOR_ARCHIVE, archive.namelist())
        self.put(root, a.PRIOR_ARCHIVE, b'corrupted prior archive')
        with self.assertRaises(ValueError):
            a.verify(root)
        self.assertEqual(a.verify(root, archive_only=True)['status'], 'archive_only_verified')

    def test_reentry_verifies_without_research_or_repacking(self):
        root, manifest = self.release_fixture()
        self.publish(root, manifest)
        before = a.digest(a.inside(root, a.ARCHIVE))
        with patch.object(a, 'pack', side_effect=AssertionError('unexpected repack')), \
                patch.object(a, 'facts', side_effect=AssertionError('unexpected research facts reload')), \
                patch.object(a, 'collect', side_effect=AssertionError('unexpected collection')):
            self.assertFalse(a.archive_release(root)['research_recomputed'])
        self.assertEqual(before, a.digest(a.inside(root, a.ARCHIVE)))

    def test_post_pack_source_change_preserves_failure_evidence(self):
        root, manifest = self.release_fixture()
        original_pack = a.pack
        def mutate_after_pack(base, path, metadata):
            original_pack(base, path, metadata)
            self.put(base, a.D1 + '/proof.bin', b'changed after packaging')
        with patch.object(a, 'pack', side_effect=mutate_after_pack), self.assertRaises(ValueError):
            self.publish(root, manifest)
        self.assertTrue(a.inside(root, a.PRIVATE + '/failure.json').is_file())
        self.assertTrue(a.inside(root, a.ARCHIVE).with_suffix('.zip.partial').is_file())
        self.assertFalse(a.inside(root, a.REPORT).exists())

    def test_facts_preserve_negative_primary_and_prior_inference_role(self):
        root, reports = self.fact_fixture()
        facts = a.facts(root)
        d = reports['reports/stage11/retailrocket_directed_v1_validation.json']
        self.assertEqual(facts['provenance'], 'copied_from_accepted_reports_no_new_metrics')
        self.assertEqual(facts['evaluation_role'], 'retrospective_exposed_development_validation')
        self.assertEqual(facts['primary_comparison'], 'D1_minus_C1_query_macro_ndcg_at_10')
        self.assertEqual(facts['uncertainty'], d['validation']['uncertainty'])
        self.assertLess(facts['uncertainty']['interval'][1], 0)
        self.assertEqual(facts['historical_C1_minus_P0']['role'], 'prior_stage10_comparison_not_new_three_arm_inference')
        self.assertEqual(facts['metrics'], {arm: value['metrics'] for arm, value in d['validation']['arms'].items()})

    def test_facts_reject_unaccepted_or_test_and_refit_scope(self):
        changes = [('status', 'not_accepted'), ('reserved_test_state', 'unlocked'),
                   ('reserved_test_ranked_queries', 1), ('final_refits', 1),
                   ('P0_C1_refits_or_rerankings', 1), ('training_ranked_queries', 1), ('real_D1_primary_fits', 2)]
        name = 'reports/stage11/retailrocket_directed_v1_validation.json'
        for key, value in changes:
            with self.subTest(key=key):
                root, reports = self.fact_fixture()
                target = reports[name] if key == 'status' else reports[name]['scope']
                target[key] = value
                self.rewrite_report_and_acceptance(root, reports, name)
                with self.assertRaises(ValueError):
                    a.facts(root)

    def test_facts_reject_reference_arm_drift(self):
        name = 'reports/stage11/retailrocket_directed_v1_validation.json'
        for arm in ('P0', 'C1'):
            root, reports = self.fact_fixture()
            reports[name]['validation']['arms'][arm]['metrics']['ndcg'] = 999
            self.rewrite_report_and_acceptance(root, reports, name)
            with self.assertRaises(ValueError):
                a.facts(root)

    def test_facts_reject_changed_denominator_or_primary_bootstrap(self):
        name = 'reports/stage11/retailrocket_directed_v1_validation.json'
        for section, field, value in [('paired', 'queries', 166896), ('paired', 'visitors', 62234),
                                      ('uncertainty', 'replicates', 1999), ('uncertainty', 'visitors', 62234),
                                      ('uncertainty', 'mean_delta', .1)]:
            root, reports = self.fact_fixture()
            reports[name]['validation'][section][field] = value
            self.rewrite_report_and_acceptance(root, reports, name)
            with self.assertRaises(ValueError):
                a.facts(root)

    def test_facts_reject_all_three_acceptance_scope_or_hash_drift(self):
        result_names = ['reports/stage9/retailrocket_popularity_v1_development.json',
                        'reports/stage10/retailrocket_cooccurrence_v1_validation.json',
                        'reports/stage11/retailrocket_directed_v1_validation.json']
        for result_name in result_names:
            for field in ('scope', 'result'):
                root, reports = self.fact_fixture()
                name = result_name.replace('.json', '_acceptance.json')
                acceptance = reports[name]
                if field == 'scope':
                    acceptance['scope']['reserved_test_state'] = 'unlocked'
                else:
                    acceptance['result']['sha256'] = '0' * 64
                self.put(root, name, a.encoded(acceptance))
                with self.assertRaises(ValueError):
                    a.facts(root)


if __name__ == '__main__':
    unittest.main()
