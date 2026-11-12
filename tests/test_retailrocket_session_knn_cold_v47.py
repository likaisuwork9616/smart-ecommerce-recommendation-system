"""Verify cold worker isolation, byte-exact output and closed evidence."""
import argparse
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import run_retailrocket_session_knn_cold_v47 as run
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests import test_retailrocket_session_knn_compare_v40 as prior


PREFIX = 'knn-v47-cold-artificial-'
build_window = _clone(prior.build_window, run=run, PREFIX=PREFIX)
artificial_contract = _clone(prior.artificial_contract, run=run, PREFIX=PREFIX)


def window_evidence(folder, expected_manifest=None):
    result, manifest = run.completed_report(folder, run.read(folder / 'request.json'), expected_manifest=expected_manifest)
    return dict(namespace=result['namespace'], runs=len(result['runs']), engineering_checks=result['engineering_checks'],
        reference_records=result['reference']['records'], sources=result['sources'],
        cold_entries=sum(row['diagnostic']['phases']['cache.cold_build']['calls'] for row in result['runs'].values()),
        snapshots=sum(row['diagnostic']['phases']['snapshot.fingerprint']['calls'] for row in result['runs'].values()),
        tracked_processes=result['supervisor']['tracked_processes'],
        live_after_cleanup=result['supervisor']['tracked_processes_alive_after_cleanup']), manifest


class ContractTests(unittest.TestCase):
    def test_original_and_candidate_build_both_roots_with_equal_typed_authority(self):
        cold = run.cold
        config = {'a': '商品🍀\n'}
        model = {'support': {'x': 1, 'y': 2}}
        deps = {name: dict(path=name + '.json', bytes=1, sha256='0' * 64) for name in ('config', 'model')}
        calls = []
        builder = cold.CandidateLoad.buffer_root.__globals__['typed']._build_verified_reference
        actual_decode = cold.decoder.candidate.decode

        def track(source):
            calls.append(source)
            return actual_decode(source)

        def build(kind):
            pool = SimpleNamespace(contract={'dependencies': deps}, poisoned=False, _typed_comparing=False)
            state = kind(pool, config, model)
            for value in (config, config, model, model):
                state.canonical(value)
            state.buffer_root('item_counts.csv', b'')
            for index, value in enumerate((config, model)):
                self.assertEqual(state.canonical(value), state.source_bytes[index])
            return pool._typed_authority, [ref.root for ref in state.references]

        with patch.dict(builder.__globals__, _decode=track):
            original = build(cold.adapter._Load)
            self.assertEqual(calls, [])
            self.assertEqual(build(cold.CandidateLoad), original)
        self.assertEqual(calls, [cold.typed.ORIGINAL_CANONICAL(config), cold.typed.ORIGINAL_CANONICAL(model)])

    def test_cost_summary_uses_only_formal_pairs_and_four_independent_boundaries(self):
        runs = {}
        for item in run.cold.SCHEDULE:
            label, mode = item['label'], item['mode']
            seconds = 10 if mode == 'R' else 8
            if label.startswith('warm_'):
                seconds = 100
            runs[label] = dict(mode=mode, decode_seconds=seconds / 10, reference_build_seconds=seconds / 5,
                diagnostic=dict(phases={'cache.cold_build': {'inclusive_wall_ns': seconds * 500000000}}),
                accounting=dict(costs=dict(entry_seconds=seconds)))
        report = run.cold.comparison(runs)
        self.assertEqual(report['medians']['entry']['saving_seconds'], 2)
        self.assertEqual(report['medians']['decode']['faster_pairs'], 6)
        self.assertAlmostEqual(report['medians']['reference_build']['saving_percent'], 20)
        self.assertEqual(report['warmups']['C']['entry'], 100)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = build_window()
        cls.request = run.read(cls.folder / 'request.json')
        cls.summary, cls.manifest = window_evidence(cls.folder)

    def test_all_entries_are_fresh_and_independent_publisher_checks_fixed48_outputs(self):
        self.assertEqual(self.summary['reference_records'], 48)
        self.assertEqual(self.summary['runs'], 14)
        self.assertEqual(self.summary['engineering_checks'], 672)
        self.assertEqual(self.summary['cold_entries'], 14)
        self.assertEqual(self.summary['snapshots'], 42)
        self.assertEqual(self.summary['live_after_cleanup'], 0)
        self.assertEqual(self.summary['sources']['publisher_store_opens'], 14)
        receipts = run.read(self.folder / 'cache_receipt.json')
        self.assertTrue(all(row['use']['cold'] and not row['use']['hit'] for row in receipts.values()))
        self.assertEqual(len(run.read(self.folder / 'decode_receipt.json')), 14)

    def test_independent_verifier_rejects_build_outside_original_boundary(self):
        result = run.read(self.folder / 'audited_result.json')
        label = 'warm_C'
        events = run.read(self.folder / label / 'events.json')
        use = result['cache'][label]['use']
        stats = {row['root']: row['statistics'] for row in use['typed_reference']['checks']}
        self.assertGreater(run.cold.build_timing(events, use, result['authority'], stats), 0)
        build = use['typed_reference']['build']
        build['end_ns'] = run.cold.prior._phase(events, 'cache.original_load_context')['end_ns']
        with self.assertRaisesRegex(ValueError, 'charged build interval differs'):
            run.cold.build_timing(events, use, result['authority'], stats)

    def test_stopped_audit_rejects_log_append(self):
        path = self.folder / 'stdout_stderr.log'
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'late append\n')
            with self.assertRaisesRegex(ValueError, 'Post-seal file set or bytes changed'):
                window_evidence(self.folder, self.manifest)
        finally:
            path.write_bytes(original)
        self.assertEqual(window_evidence(self.folder, self.manifest), (self.summary, self.manifest))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for role in run.ROLES:
        modes.add_argument('--' + role, type=Path)
    args = parser.parse_args()
    for role in run.ROLES:
        folder = getattr(args, role)
        if folder is not None:
            run.run_role(folder, role, admit=artificial_contract, module=run.SUITE)
            break
