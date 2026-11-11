"""Exercise the V40 roles in separate interpreters using sealed artificial inputs."""
import argparse
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from shutil import copyfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import run_retailrocket_session_knn_compare_v40 as run
from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts.retailrocket_session_knn_reuse_v27 import ReuseStore
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.run_retailrocket_session_knn_gap_v7 import ledger_proof
from tests import test_retailrocket_session_knn_compare_v28 as prior
from tests import test_retailrocket_session_knn_pair_v4 as fixtures
from tests import test_retailrocket_session_knn_validation as validation


PREFIX = 'knn-v40-typed-artificial-'


def artificial_contract(folder, request):
    bundle = folder.parent
    if (bundle.parent != run.PRIVATE.resolve() or not bundle.name.startswith(PREFIX)
            or folder.name != 'window' or request['metadata'].get('synthetic_acceptance_only') is not True):
        raise ValueError('Only an isolated artificial V40 window is admitted here')
    run.entry.old._check_window(request)
    run.typed.adapter.require_policy(request)
    spec = run.frozen.specification()
    _, methods = run.source_roster()
    meta = request['metadata']
    inputs = [*meta['cohort'].values(), *(row['path'] for row in meta['context']['dependencies'].values())]
    if any(not (run.ROOT / name).resolve().is_relative_to(bundle) for name in inputs):
        raise ValueError('Artificial cohort input escaped its bundle')
    binding = run.read(run.ROOT / meta['cohort']['old_run'])['binding']
    if any(not (run.ROOT / row['path']).resolve().is_relative_to(bundle) for row in binding['sources']):
        raise ValueError('Artificial binding escaped its bundle')
    expected = run.request_metadata(spec, methods, meta['cohort'], meta['context']['dependencies'])
    if meta != dict(expected, synthetic_acceptance_only=True):
        raise ValueError('Artificial window must use the production schedule and methods')
    run.common.require_direct_sources(methods, request['sources'])
    run.typed.adapter.context_contract(request, binding)
    # Both streams are captured by the real run_role implementation.
    print('artificial parent contract diagnostics')


def build_window():
    bundle = run.PRIVATE / (PREFIX + uuid4().hex)
    bundle.mkdir()
    with patch.object(validation, 'fixture_inputs', side_effect=prior.artificial_inputs), patch.object(
            fixtures, 'make_fixture', side_effect=lambda **kw: validation.make_fixture(base=bundle, **kw)):
        root, paths, _, primary, _, database, model, ordinals, binding = fixtures.fixture()
    model_path = primary / 'reconstruction.json'
    run.write(model_path, dict(receipt=model))
    run.write(root / 'ordinals.json', ordinals)
    copyfile(database, primary / 'independent.sqlite')

    def relative(path):
        return path.relative_to(run.ROOT).as_posix()

    records = checkpoint.bind_sources(run.ROOT, [relative(p) for p in root.rglob('*') if p.is_file()])
    binding = dict(binding, sources=records)
    reference = ReuseStore.create(bundle / 'reference' / 'verified_subset', binding,
        (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(), 1800, source_root=run.ROOT,
        observer=Observation(), expected_queries=48, required_stages=('reconstruction', 'queries'))
    with reference.writer():
        fixtures.reconstruct_seal(reference, model)
        pair.verify_selected(primary, paths, binding['configuration'], reference, model, database, ordinals)
    probes = [dict(key=row['key'], original_ordinal=row['original_ordinal'],
        key_sha256=hashlib.sha256(pair.dump(row['key']).encode()).hexdigest()) for row in ordinals]
    run.write(bundle / 'reference.json', ledger_proof(reference, probes))
    run.write(bundle / 'probes.json', dict(probes=probes))
    dependencies = {name: run.describe(path) for name, path in dict(counts=paths['P0'] / 'item_counts.csv',
        catalog=paths['dataset'] / 'catalog.csv', config=root / 'configuration.json', model=model_path).items()}
    cohort = dict(selected_root=relative(root), model_root=relative(primary), old_run=relative(reference.folder / 'run.json'),
                  probes=relative(bundle / 'probes.json'), reference=relative(bundle / 'reference.json'))
    spec = run.frozen.specification()
    _, methods = run.source_roster()
    metadata = dict(run.request_metadata(spec, methods, cohort, dependencies), synthetic_acceptance_only=True)
    sources = run.common.merge_methods([run.describe(p) for p in sorted(bundle.rglob('*')) if p.is_file()], methods)
    folder = bundle / 'window'
    completion = run.entry.run_window(folder, run.command(run.SUITE, 'pipeline', folder), sources, 'joint_tail',
        metadata=metadata, budget_seconds=spec['budget_seconds'], limits=spec['limits'])
    if completion['exit_code'] != 0:
        raise AssertionError('\n'.join(p.read_text(encoding='utf-8', errors='replace')[-9000:] for p in folder.glob('*.log')))
    return folder


def window_evidence(folder, expected_manifest=None):
    request = run.read(folder / 'request.json')
    report, manifest = run.completed_report(folder, request, expected_manifest=expected_manifest)
    proof = report['typed_validation']
    return dict(namespace=report['namespace'], runs=len(report['runs']), engineering_checks=report['engineering_checks'],
        reference_records=report['reference']['records'], sources=report['sources'],
        original_binding_count=len(run.read(run.ROOT / request['metadata']['cohort']['old_run'])['binding']['sources']),
        tracked_processes=report['supervisor']['tracked_processes'],
        live_after_cleanup=report['supervisor']['tracked_processes_alive_after_cleanup'],
        cold_builds=proof['cold_builds'], typed_roots=proof['independently_rebuilt_roots'],
        late_comparisons=proof['late_comparisons'], hits=proof['hits']), manifest


class ContractTests(unittest.TestCase):
    def test_real_roster_preserves_all_parents_and_exact_schedule(self):
        spec = run.frozen.specification()
        sources, methods = run.source_roster()
        old = run.read(run.ROOT / run.frozen.inherited.SPEC)['preserved']
        accepted = run.read(run.ROOT / run.frozen.accepted.REPORT)['preserved_contract']['actual_methods']
        index = {row['path']: row for row in sources}
        self.assertTrue(all(index[row['path']] == row for row in old['current_sources']))
        self.assertTrue(all(row in methods for row in accepted))
        self.assertIn(run.common.PRIORITY_SOURCE, {row['path'] for row in methods})
        self.assertEqual(len(spec['original_binding']), 15)
        self.assertEqual(len(spec['schedule']), 14)
        run.frozen.verify_original_reference(spec)

    def test_real_contract_rejects_changed_policy_sources_cohort_and_schedule(self):
        spec = run.frozen.specification()
        sources, methods = run.source_roster()
        metadata = run.request_metadata(spec, methods, spec['cohort'], spec['dependencies'])
        start = datetime.now(timezone.utc)
        request = dict(created_utc=start.isoformat(), deadline_utc=(start + timedelta(minutes=30)).isoformat(),
            budget_seconds=1800, limits=spec['limits'], operation='joint_tail', full_readback_enabled=False,
            reserved_test='locked', T_plan=None, sources=sources, metadata=metadata)
        folder = run.PRIVATE / (run.frozen.WINDOW_PREFIX + uuid4().hex)
        with patch.object(run, 'source_contract', return_value=(sources, metadata)):
            run.contract(folder, request)
            changes = [dict(request, sources=sources[1:]), dict(request, budget_seconds=1801)]
            for key, value in (('schedule', []), ('cohort', {}), ('typed_reference_policy', 'legacy'),
                               ('typed_reference_scheme', True), ('synthetic_acceptance_only', True)):
                changes.append(dict(request, metadata=dict(metadata, **{key: value})))
            for changed in changes:
                with self.subTest(changed=changes.index(changed)), self.assertRaises(ValueError):
                    run.contract(folder, changed)

    def test_measure_requires_acceptance_and_refuses_existing_request(self):
        with patch.object(run.entry, 'exclusive', side_effect=nullcontext), patch.object(run, 'existing_windows') as windows, \
                patch.object(run, 'accepted_entry', side_effect=FileNotFoundError('acceptance missing')) as accepted, \
                patch.object(run.entry, 'run_window') as supervisor:
            windows.return_value = []
            with self.assertRaisesRegex(FileNotFoundError, 'acceptance missing'):
                run.measure()
            accepted.assert_called_once()
            accepted.reset_mock()
            windows.return_value = [Path('failed-real-window')]
            with self.assertRaisesRegex(FileExistsError, 'forbids another measurement'):
                run.measure()
            accepted.assert_not_called()
            supervisor.assert_not_called()

    def test_real_namespace_rejects_artificial_and_legacy(self):
        for folder in (run.PRIVATE / (PREFIX + uuid4().hex) / 'window', run.PRIVATE / 'knn-v31-s1-other',
                       run.PRIVATE / (run.frozen.WINDOW_PREFIX + 'incomplete')):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                run.folder_path(folder)

    def test_failed_worker_prevents_publisher(self):
        folder = run.PRIVATE / (PREFIX + uuid4().hex) / 'failure'
        folder.mkdir(parents=True)
        run.write(folder / 'request.json', {})
        with patch.object(run.entry.old, 'run_child', side_effect=ValueError('failed worker')) as child:
            with self.assertRaisesRegex(ValueError, 'failed worker'):
                run.run_role(folder, 'pipeline', admit=lambda *_: None, module=run.SUITE)
        child.assert_called_once()
        self.assertEqual(child.call_args.args[2], 'worker')
        self.assertFalse((folder / 'publisher_contract.json').exists())


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = build_window()
        cls.request = run.read(cls.folder / 'request.json')
        cls.summary, cls.manifest = window_evidence(cls.folder)

    def test_production_loader_and_sequential_stopped_independent_roles(self):
        self.assertEqual(self.summary['reference_records'], 48)
        self.assertEqual(self.summary['runs'], 14)
        self.assertEqual(self.summary['engineering_checks'], 672)
        self.assertEqual(self.summary['sources']['publisher_store_opens'], 14)
        self.assertEqual(self.summary['live_after_cleanup'], 0)
        identities = [run.read(self.folder / name)['pid'] for name in ('worker_identity.json', 'worker_exit.json', 'publisher_exit.json')]
        self.assertEqual(len(set(identities)), 3)
        worker = run.read(self.folder / 'worker_exit.json')
        publisher = run.read(self.folder / 'publisher_exit.json')
        self.assertLessEqual(worker['ended_utc'], publisher['started_utc'])
        self.assertEqual([self.summary[key] for key in ('cold_builds', 'typed_roots', 'late_comparisons', 'hits')], [1, 2, 2, 6])

    def test_role_diagnostics_are_closed_and_final_log_tampering_fails(self):
        for role, log in zip(run.ROLES, ('stdout_stderr.log', 'worker.log', 'publisher.log')):
            value = run.read(self.folder / (role + '_contract.json'))
            self.assertEqual(value['diagnostics'], 'artificial parent contract diagnostics\n')
            self.assertNotIn(value['diagnostics'].strip(), (self.folder / log).read_text(encoding='utf-8'))
        log = self.folder / 'stdout_stderr.log'
        original = log.read_bytes()
        try:
            log.write_bytes(original + b'late write\n')
            with self.assertRaisesRegex(ValueError, 'Post-seal file set or bytes changed'):
                window_evidence(self.folder, self.manifest)
        finally:
            log.write_bytes(original)
        self.assertEqual(window_evidence(self.folder, self.manifest), (self.summary, self.manifest))

    def test_publisher_rejects_raw_typed_policy_tampering(self):
        path = self.folder / 'cache_receipt.json'
        original = path.read_bytes()
        value = run.read(path)
        value['typed_reference_policy'] = 'mixed'
        try:
            path.write_bytes(checkpoint.encoded(value))
            with self.assertRaisesRegex(ValueError, 'Mixed or missing late typed policy'):
                run.audit_saved_runs(self.folder, self.request, Observation())
        finally:
            path.write_bytes(original)

    def test_publication_and_read_only_audit_share_completed_checks(self):
        path = self.folder.parent / 'test_release.json'
        request = deepcopy(self.request)
        request['metadata'].pop('synthetic_acceptance_only')
        metadata = dict(request['metadata'], acceptance={'artificial': True})
        with patch.object(run, 'existing_windows', return_value=[self.folder]), patch.object(run, 'folder_path', return_value=self.folder), \
                patch.object(run, 'contract', return_value=metadata), patch.object(run, 'REPORT', path.relative_to(run.ROOT).as_posix()):
            published = run.release(audit_only=False)
            self.assertEqual(published['closed_manifest'], self.manifest)
            before = path.read_bytes()
            self.assertEqual(run.release(audit_only=True), published)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(FileExistsError):
                run.release(audit_only=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in run.ROLES:
        mode.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    for role in run.ROLES:
        folder = getattr(args, role)
        if folder is not None:
            run.run_role(folder, role, admit=artificial_contract, module=run.SUITE)
            break
