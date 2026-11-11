"""Check that timing preserves authority and only counts exclusive work once."""
from copy import deepcopy
import hashlib
import json
import unittest

from scripts import diagnose_retailrocket_session_knn_reference_v42 as run


class ReferenceDiagnosticTests(unittest.TestCase):
    def setUp(self):
        config = {'dates': [None, True, 1, -0.0, '台灣\n🍀'], 'limit': 64}
        model = {'receipt': {'support': {'甲': 1, '乙': 4}, 'version': 'v1'}}
        self.raw = {name: json.dumps(value, ensure_ascii=False).encode('utf-8')
                    for name, value in (('config', config), ('model', model))}
        self.dependencies = {name: dict(path=name + '.json', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                             for name, data in self.raw.items()}

    def cycle(self, mode):
        return run.cycle(self.raw, self.dependencies, mode)

    def test_observed_and_plain_match_exact_canonical_identity_and_full_late_validation(self):
        functions = (run.typed._build_verified_reference, run.typed._decode, run.adapter._Load.buffer_root)
        plain, expected = self.cycle('plain')
        observed, actual = self.cycle('observed')
        self.assertEqual(expected, actual)
        self.assertEqual(expected['raw_sources'], self.dependencies)
        self.assertEqual(plain['late_roots'], ['config', 'model'])
        self.assertEqual(observed['late_roots'], plain['late_roots'])
        for root, descriptor in expected['canonical'].items():
            value = json.loads(self.raw[root])
            data = run.typed.ORIGINAL_CANONICAL(value['receipt'] if root == 'model' else value)
            self.assertEqual(descriptor['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(descriptor['bytes'], len(data))
        self.assertEqual(functions, (run.typed._build_verified_reference, run.typed._decode, run.adapter._Load.buffer_root))

    def test_exclusive_phases_conserve_elapsed_time_and_reject_misplaced_spans(self):
        sample, _ = self.cycle('observed')
        total, parts = run.phases(sample)
        self.assertEqual(total, sum(parts.values()))
        self.assertTrue(all(value >= 0 for value in parts.values()))
        invalid = deepcopy(sample)
        invalid['spans']['model.grammar'] = invalid['spans']['config.decode']
        with self.assertRaisesRegex(ValueError, 'overlap or left'):
            run.phases(invalid)

    def test_summary_uses_six_alternating_pairs_and_ignores_warmups(self):
        warmups = [self.cycle(mode)[0] for mode in ('plain', 'observed')]
        pairs = [[self.cycle(mode)[0] for mode in order] for order in run.ORDERS]
        summary = run.summarize(warmups, pairs)
        expected = []
        for pair in pairs:
            times = {sample['mode']: run.phases(sample)[0] for sample in pair}
            expected.append(times['observed'] - times['plain'])
        self.assertEqual(summary['observed_minus_plain_ns'], expected)
        with self.assertRaisesRegex(ValueError, 'order differs'):
            run.summarize(warmups, pairs[::-1])
