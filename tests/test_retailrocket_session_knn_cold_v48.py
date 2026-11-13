"""Verify the isolated second window and unchanged V47 cold protocol."""
import argparse
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import run_retailrocket_session_knn_cold_v48 as run
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests import test_retailrocket_session_knn_compare_v40 as prior


PREFIX = 'knn-v48-cold-artificial-'
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
    def test_repeat_preserves_protocol_and_measurement_core(self):
        original = run.frozen.inherited.specification()
        spec = run.frozen.specification_value()
        changed = {'status', 'predecessors', 'namespace_prefix', 'requirements'}
        for key, value in original.items():
            if key not in changed:
                with self.subTest(field=key):
                    self.assertEqual(spec[key], value)
        self.assertIs(run.cold, run.previous.cold)
        self.assertIs(run.completed_report, run.previous.completed_report)
        self.assertEqual(spec['repeat']['baseline'], run.describe(run.ROOT / run.previous.REPORT))
        self.assertEqual(spec['repeat']['baseline']['sha256'], run.frozen.BASELINE_SHA)
        self.assertTrue(all(row in spec['predecessors'] for row in original['predecessors']))
        for name in (run.frozen.inherited.SPEC, run.frozen.inherited.SEAL,
                     run.previous.ACCEPTANCE, run.previous.ACCEPTANCE_SEAL, run.previous.REPORT):
            self.assertIn(run.describe(run.ROOT / name), spec['predecessors'])
        self.assertNotEqual(run.REPORT, run.previous.REPORT)
        self.assertNotEqual(run.ACCEPTANCE, run.previous.ACCEPTANCE)
        self.assertNotEqual(run.frozen.WINDOW_PREFIX, run.frozen.inherited.WINDOW_PREFIX)

    def test_repeat_namespace_and_existing_windows_are_isolated(self):
        valid = run.PRIVATE / (run.frozen.WINDOW_PREFIX + 'a' * 32)
        self.assertEqual(run.folder_path(valid), valid.resolve())
        for folder in (run.PRIVATE / (run.frozen.inherited.WINDOW_PREFIX + 'a' * 32),
                       run.PRIVATE / (PREFIX + 'a' * 32) / 'window',
                       valid / 'nested', run.PRIVATE / (run.frozen.WINDOW_PREFIX + 'short'),
                       run.PRIVATE / (run.frozen.WINDOW_PREFIX + 'g' * 32)):
            with self.subTest(folder=folder), self.assertRaisesRegex(ValueError, 'Direct V48'):
                run.folder_path(folder)
        with TemporaryDirectory(prefix='knn-v48-contract-', dir=run.PRIVATE) as temporary:
            root = Path(temporary)
            expected = []
            for prefix, suffix in ((run.frozen.inherited.WINDOW_PREFIX, 'a'),
                                   (run.frozen.WINDOW_PREFIX, 'b'), (run.frozen.WINDOW_PREFIX, 'c')):
                folder = root / (prefix + suffix * 32)
                folder.mkdir()
                (folder / 'request.json').write_text('{}', encoding='utf-8')
                if prefix == run.frozen.WINDOW_PREFIX:
                    expected.append(folder)
            (root / (run.frozen.WINDOW_PREFIX + 'd' * 32)).mkdir()
            with patch.dict(run.existing_windows.__globals__, PRIVATE=root):
                self.assertEqual(run.existing_windows(), expected)

    def test_measure_refuses_existing_request_or_result(self):
        with TemporaryDirectory(prefix='knn-v48-contract-', dir=run.PRIVATE) as temporary:
            root = Path(temporary)
            report = 'existing-result.json'
            with patch.object(run.entry, 'exclusive', side_effect=nullcontext), \
                    patch.object(run.entry, 'run_window') as supervisor, \
                    patch.dict(run.measure.__globals__, ROOT=root, REPORT=report):
                with patch.dict(run.measure.__globals__, existing_windows=lambda: [Path('saved-request')]):
                    with self.assertRaisesRegex(FileExistsError, 'forbids another measurement'):
                        run.measure()
                (root / report).write_text('{}', encoding='utf-8')
                with patch.dict(run.measure.__globals__, existing_windows=lambda: []):
                    with self.assertRaisesRegex(FileExistsError, 'forbids another measurement'):
                        run.measure()
                supervisor.assert_not_called()

    def test_cross_window_comparison_rejects_changed_authority_schedule_and_summary(self):
        baseline = run.read(run.ROOT / run.previous.REPORT)
        for key in ('authority', 'schedule', 'arms', 'reference'):
            current = deepcopy(baseline)
            current[key] = {} if key != 'schedule' else []
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'Repeat window changed ' + key):
                run.compare_windows(baseline, current)
        for side in ('baseline', 'current'):
            left, right = deepcopy(baseline), deepcopy(baseline)
            changed = left if side == 'baseline' else right
            changed['comparison']['medians']['entry']['saving_seconds'] += 1
            with self.subTest(side=side), self.assertRaisesRegex(ValueError, 'summary differs from signed pairs'):
                run.compare_windows(left, right)

    def test_cross_window_summary_keeps_regressions_and_excludes_warmups(self):
        baseline = run.read(run.ROOT / run.previous.REPORT)
        current = deepcopy(baseline)
        deltas = (2, -3, 0, 4, -1, 1)
        for index, delta in enumerate(deltas, 1):
            for arm, seconds in (('R', 10), ('C', 10 - delta)):
                row = current['runs'][f'pair_{index}_{arm}']
                row['accounting']['costs']['entry_seconds'] = seconds
                row['load']['system_cpu_percent']['mean'] = 20
                row['load']['available_memory_bytes']['min'] = 100
        for arm, seconds in (('R', 1000), ('C', 2000)):
            row = current['runs']['warm_' + arm]
            row['accounting']['costs']['entry_seconds'] = seconds
            row['load']['system_cpu_percent']['mean'] = 99
            row['load']['available_memory_bytes']['min'] = 1
        current['comparison'] = run.cold.comparison(current['runs'])
        spec = dict(repeat=dict(baseline=run.describe(run.ROOT / run.previous.REPORT)))
        with patch.object(run.frozen, 'specification', return_value=spec):
            report = run.compare_windows(baseline, current)
            entry = report['windows']['V48']['metrics']['entry']
            self.assertEqual(entry['saving_seconds'], 0.5)
            self.assertEqual((entry['faster_pairs'], entry['slower_pairs'], entry['tied_pairs']), (3, 2, 1))
            self.assertEqual((entry['min_saving_seconds'], entry['max_saving_seconds']), (-3, 4))
            self.assertEqual(entry['min_saving_percent'], -30)
            self.assertEqual(entry['formal_total_seconds'], {'R': 60, 'C': 57})
            self.assertEqual(entry['formal_total_saving_seconds'], 3)
            self.assertEqual(entry['including_warmup_total_seconds'], {'R': 1060, 'C': 2057})
            self.assertEqual(entry['order_medians'], {'CR': 0, 'RC': 1})
            regressions = report['windows']['V48']['entry_regressions']
            self.assertEqual([row['pair'] for row in regressions], [2, 5])
            self.assertEqual([row['saving_seconds'] for row in regressions], [-3, -1])
            self.assertTrue(report['entry_slowdown_reproduced'])
            load = report['windows']['V48']['load']
            self.assertEqual(load['median_entry_system_cpu_percent'], 20)
            self.assertEqual(load['minimum_available_memory_bytes'], 100)
            for index in range(1, 7):
                current['runs'][f'pair_{index}_C']['accounting']['costs']['entry_seconds'] = 9
            current['comparison'] = run.cold.comparison(current['runs'])
            self.assertFalse(run.compare_windows(baseline, current)['entry_slowdown_reproduced'])

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
