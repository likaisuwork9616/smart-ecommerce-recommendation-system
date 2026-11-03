"""Small artificial proxy cases, including all 2000 frozen bootstrap draws."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_proxy_v3 as proxy


class ProxyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.config = {'fixed_validation': {'queries': 7, 'visitors': 3, 'candidate_union_items': 20,
                       'target_occurrences': 10, 'multi_item_target_queries': 2, 'multi_item_current_queries': 1,
                       'all_targets_reachable_queries': 5, 'reachable_target_occurrences': 7,
                       'new_visitor_queries': 4, 'target_model_query_counts': {'mixed': 1, 'all_positive': 4, 'all_zero': 2}}}

    def test_physical_ledger_complete_global_shapes_frozen_draws_and_reopen(self):
        result = proxy.run_proxy(self.folder, self.config, lambda: None)
        self.assertEqual(result['kind'], 'synthetic_engineering_only')
        self.assertFalse(result['real_acceptance'])
        self.assertFalse(result['full_readback_started'])
        self.assertFalse(result['same_query_visitor_catalog_shape'])
        self.assertFalse(result['full_production_payload_shape_coverage'])
        self.assertFalse(result['real_source_and_prefix_resume_measured'])
        self.assertIsNone(result['T_plan'])
        observed = result['observed_global']
        self.assertEqual((observed['queries'], observed['visitors'], observed['catalog']), (7, 3, 20))
        self.assertEqual((observed['target_occurrences'], observed['reachable_target_occurrences'],
                          observed['conditional_queries']), (10, 7, 5))
        self.assertEqual(observed['slices']['visitor_history'], {'seen': 3, 'new': 4})
        self.assertEqual(observed['slices']['target_basket'], {'multiple': 2, 'single': 5})
        self.assertEqual(observed['slices']['target_model'], self.config['fixed_validation']['target_model_query_counts'])
        self.assertEqual(result['recovered'], {'records': 7, 'chunks': 1})
        self.assertEqual(result['bootstrap'], {'replicates': 2000, 'visitors_per_draw': 3, 'indices': 6000})
        self.assertGreater(result['ledger_bytes'], result['ledger_payload_bytes'])
        self.assertGreater(result['neighbor_stress_payload_bytes']['500'], result['neighbor_stress_payload_bytes']['499'])
        directory = self.folder/'synthetic_proxy'
        self.assertEqual(json.loads((directory/'engineering_summary.json').read_bytes()), result)
        for name, timing in result['phases'].items():
            self.assertTrue(timing['completed'])
            self.assertGreaterEqual(timing['seconds'], 0)
            self.assertTrue((directory/(name+'_started.json')).is_file())
            self.assertEqual(timing, json.loads((directory/(name+'_receipt.json')).read_bytes()))
        payload = next((directory/'ledger'/'payloads').glob('*.jsonl'))
        with payload.open(encoding='utf-8') as stream:
            ledger = [json.loads(line) for line in stream]
        self.assertEqual([row['ordinal'] for row in ledger], list(range(7)))
        one = ledger[3]['payload']
        self.assertEqual(set(one['expected']['predictions']), {'P0', 'C1', 'D1', 'K1'})
        self.assertIsInstance(one['precise']['D1']['mrr'], str)
        self.assertEqual(float.fromhex(one['delta_hex']['K1_minus_C1']['ndcg']), one['expected']['delta']['K1_minus_C1']['ndcg'])
        self.assertEqual(len(one['expected']['predictions']['K1']['selected_neighbors']), 8)
        for name in ('synthetic_output.jsonl', 'synthetic_reference.jsonl'):
            with (directory/name).open(encoding='utf-8') as stream:
                self.assertEqual(sum(1 for _ in stream), 2000)
        self.assertFalse(list(directory.rglob('acceptance.json')))
        with self.assertRaises(FileExistsError):
            proxy.run_proxy(self.folder, self.config, lambda: None)

    def test_partial_phase_records_timeout_without_claiming_completion(self):
        directory = self.folder/'synthetic_proxy'

        def watch():
            if (directory/'global_replay_started.json').exists():
                raise TimeoutError('Synthetic external stop')

        with self.assertRaisesRegex(TimeoutError, 'external stop'):
            proxy.run_proxy(self.folder, self.config, watch)
        built = json.loads((directory/'build_ledger_receipt.json').read_bytes())
        self.assertTrue(built['completed'])
        self.assertEqual(built['evidence']['records'], 7)
        self.assertGreater(built['evidence']['payload_bytes'], 0)
        failed = json.loads((directory/'global_replay_receipt.json').read_bytes())
        self.assertFalse(failed['completed'])
        self.assertIsNone(failed['evidence'])
        self.assertEqual(failed['error_type'], 'TimeoutError')
        self.assertFalse((directory/'engineering_summary.json').exists())

    def test_expired_absolute_deadline_preserves_start_and_failed_receipt(self):
        self.config['deadline_utc'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(TimeoutError, 'absolute deadline'):
            proxy.run_proxy(self.folder, self.config, lambda: None)
        directory = self.folder/'synthetic_proxy'
        self.assertTrue((directory/'build_ledger_started.json').is_file())
        self.assertFalse(json.loads((directory/'build_ledger_receipt.json').read_bytes())['completed'])

    def test_invalid_margins_and_budget_rejected_before_writing(self):
        self.config['budget_seconds'] = 1801
        with self.assertRaisesRegex(ValueError, '1800'):
            proxy.run_proxy(self.folder, self.config, lambda: None)
        self.config['budget_seconds'] = 300
        self.config['fixed_validation']['reachable_target_occurrences'] = 0
        with self.assertRaisesRegex(ValueError, 'reachable-target'):
            proxy.run_proxy(self.folder, self.config, lambda: None)
        self.assertFalse((self.folder/'synthetic_proxy').exists())


if __name__ == '__main__':
    unittest.main()
