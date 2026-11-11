"""Direct-comparison acceptance using the production roles on artificial data."""
import argparse
from contextlib import nullcontext
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import run_retailrocket_session_knn_compare_v41 as run
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests import test_retailrocket_session_knn_compare_v40 as prior


PREFIX = 'knn-v41-typed-artificial-'
build_window = _clone(prior.build_window, run=run, PREFIX=PREFIX)
artificial_contract = _clone(prior.artificial_contract, run=run, PREFIX=PREFIX)


def window_evidence(folder, expected_manifest=None):
    report, manifest = run.completed_report(folder, run.read(folder / 'request.json'), expected_manifest=expected_manifest)
    proof = report['typed_validation']
    return dict(namespace=report['namespace'], runs=len(report['runs']), engineering_checks=report['engineering_checks'],
        reference_records=report['reference']['records'], sources=report['sources'], worker_contexts=report['worker_contexts'],
        worker_snapshots=report['worker_snapshots'], late_comparisons=proof['late_comparisons'],
        independently_rebuilt_roots=proof['independently_rebuilt_roots'],
        tracked_processes=report['supervisor']['tracked_processes'],
        live_after_cleanup=report['supervisor']['tracked_processes_alive_after_cleanup']), manifest


class ContractTests(unittest.TestCase):
    def test_retains_v40_sources_methods_original_cohort_and_schedule(self):
        spec = run.frozen.specification()
        previous, metadata = run.prior.source_contract()
        sources, methods = run.source_roster()
        index = {row['path']: row for row in sources}
        self.assertTrue(all(index[row['path']] == row for row in previous))
        self.assertTrue(all(row in methods for row in metadata['context']['methods']))
        self.assertEqual(spec['cohort'], metadata['cohort'])
        self.assertEqual(spec['dependencies'], metadata['context']['dependencies'])
        self.assertEqual(spec['schedule'][:2], [dict(label='cold_S', mode='S'), dict(label='cold_T', mode='T')])
        self.assertEqual([''.join(row['mode'] for row in spec['schedule'][i:i + 2]) for i in range(2, 14, 2)], ['TS', 'ST'] * 3)
        run.frozen.verify_original_reference(spec)

    def test_aggregate_charges_both_colds_and_signed_pair_deltas(self):
        runs = {row['label']: dict(mode=row['mode'], accounting=dict(costs=dict(entry_seconds=5, primary_seconds=1)))
                for row in run.frozen.SCHEDULE}
        runs['cold_S']['accounting']['costs']['entry_seconds'] = 8
        runs['cold_T']['accounting']['costs']['entry_seconds'] = 20
        runs['pair_1_T']['accounting']['costs']['entry_seconds'] = 4
        result = run.comparison.comparison(runs)
        self.assertEqual(result['cold']['T_minus_S_seconds'], 12)
        self.assertEqual(result['hit_pairs'][0]['T_minus_S_percent'], -20)
        self.assertEqual(result['all7_entry_seconds'], {'S': 38, 'T': 49})
        self.assertEqual(result['all7_T_minus_S_seconds'], 11)
        runs['pair_1_T']['mode'] = 'S'
        with self.assertRaises(ValueError):
            run.comparison.comparison(runs)

    def test_missing_acceptance_and_existing_request_fail_before_supervision(self):
        with patch.object(run.entry, 'exclusive', side_effect=nullcontext), patch.object(run, 'existing_windows') as windows, \
                patch.object(run, 'source_contract', side_effect=FileNotFoundError('acceptance missing')) as sources, \
                patch.object(run.entry, 'run_window') as supervisor:
            windows.return_value = []
            with self.assertRaisesRegex(FileNotFoundError, 'acceptance missing'):
                run.measure()
            windows.return_value = [Path('failed-real-window')]
            with self.assertRaisesRegex(FileExistsError, 'forbids another measurement'):
                run.measure()
            sources.assert_called_once()
            supervisor.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Direct V41 real namespace required'):
            run.folder_path(run.PRIVATE / (PREFIX + 'fake') / 'window')


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = build_window()
        cls.request = run.read(cls.folder / 'request.json')
        cls.summary, cls.manifest = window_evidence(cls.folder)

    def test_two_independent_pools_and_complete_independent_scientific_checks(self):
        self.assertEqual(self.summary['reference_records'], 48)
        self.assertEqual(self.summary['engineering_checks'], 672)
        self.assertEqual(self.summary['runs'], 14)
        self.assertEqual(self.summary['worker_contexts'], {arm: dict(cold_builds=1, hits=6) for arm in 'ST'})
        self.assertEqual(self.summary['worker_snapshots'], {'S': 15, 'T': 15})
        self.assertEqual(self.summary['sources']['publisher_store_opens'], 14)
        self.assertEqual(self.summary['independently_rebuilt_roots'], 2)
        self.assertEqual(self.summary['live_after_cleanup'], 0)
        worker, publisher = [run.read(self.folder / (role + '_exit.json')) for role in ('worker', 'publisher')]
        self.assertNotEqual(worker['pid'], publisher['pid'])
        self.assertLessEqual(worker['ended_utc'], publisher['started_utc'])

    def test_late_timing_is_ordered_and_cost_includes_reference_build(self):
        report, _ = run.completed_report(self.folder, self.request, expected_manifest=self.manifest)
        data = report['cold_replaced_work']
        self.assertEqual(set(data['S_late_canonical_seconds']), {'config', 'model'})
        self.assertEqual(set(data['T_late_typed_seconds']), {'config', 'model'})
        self.assertGreater(data['T_reference_build_seconds'], 0)
        self.assertAlmostEqual(data['S_total_seconds'], sum(data['S_late_canonical_seconds'].values()))
        self.assertAlmostEqual(data['T_total_seconds'], data['T_reference_build_seconds'] + sum(data['T_late_typed_seconds'].values()))
        self.assertAlmostEqual(data['T_minus_S_seconds'], data['T_total_seconds'] - data['S_total_seconds'])
        receipt = run.read(self.folder / 'cache_receipt.json')
        self.assertNotIn('typed_reference', receipt['S'])
        self.assertEqual(len(receipt['T']['call_observations'][0]['typed_reference']['checks']), 2)
        self.assertTrue(all(not use['typed_reference']['checks'] for use in receipt['T']['call_observations'][1:]))

    def test_raw_publisher_rejects_invalid_original_late_timing(self):
        path = self.folder / 'original_late_timing.json'
        original = path.read_bytes()
        value = run.read(path)
        value[1]['start_ns'] = value[0]['start_ns']
        try:
            path.write_bytes(prior.checkpoint.encoded(value))
            with self.assertRaisesRegex(ValueError, 'Original late canonical timing left the charged cold boundary'):
                run.comparison.audit_saved_runs(self.folder, self.request, prior.Observation())
        finally:
            path.write_bytes(original)

    def test_raw_publisher_rejects_mixed_typed_policy(self):
        path = self.folder / 'cache_receipt.json'
        original = path.read_bytes()
        value = run.read(path)
        value['T']['typed_reference_policy'] = 'mixed'
        try:
            path.write_bytes(prior.checkpoint.encoded(value))
            with self.assertRaisesRegex(ValueError, 'Mixed or missing late typed policy'):
                run.comparison.audit_saved_runs(self.folder, self.request, prior.Observation())
        finally:
            path.write_bytes(original)

    def test_closed_log_manifest_refuses_late_write(self):
        path = self.folder / 'stdout_stderr.log'
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'late write\n')
            with self.assertRaisesRegex(ValueError, 'Post-seal file set or bytes changed'):
                window_evidence(self.folder, self.manifest)
        finally:
            path.write_bytes(original)
        self.assertEqual(window_evidence(self.folder, self.manifest), (self.summary, self.manifest))

    def test_release_and_read_only_audit_recompute_from_same_artifacts(self):
        path = self.folder.parent / 'test_release.json'
        metadata = dict(self.request['metadata'], acceptance={'artificial': True})
        with patch.object(run, 'existing_windows', return_value=[self.folder]), patch.object(run, 'folder_path', return_value=self.folder), \
                patch.object(run, 'contract', return_value=metadata), patch.object(run, 'REPORT', path.relative_to(run.ROOT).as_posix()):
            report = run.release(audit_only=False)
            before = path.read_bytes()
            self.assertEqual(run.release(audit_only=True), report)
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
