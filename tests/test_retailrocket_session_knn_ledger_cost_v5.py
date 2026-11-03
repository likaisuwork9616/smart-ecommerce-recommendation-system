"""Small source-backed engineering fixtures; no real dataset or K1 prediction."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_ledger_cost_v5 as ledger
from scripts.retailrocket_session_knn_checkpoint_v2 import encoded, CheckpointStore
from scripts.retailrocket_session_knn_proxy_v3 import _shape, _row


class SourceBackedLedgerTests(unittest.TestCase):
    def setUp(self):
        base = ledger.PRIVATE / 'verification'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='ledger-v5-small-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.primary = self.root / 'original_saved'; self.primary.mkdir()
        self.dataset = self.root / 'dataset'; self.dataset.mkdir()
        self.paths = {'dataset': self.dataset}
        fixed = {'queries': 7, 'visitors': 3, 'candidate_union_items': 20,
                 'multi_item_target_queries': 1, 'target_occurrences': 8,
                 'all_targets_reachable_queries': 7, 'reachable_target_occurrences': 8,
                 'new_visitor_queries': 4, 'multi_item_current_queries': 1,
                 'target_model_query_counts': {'all_positive': 6, 'mixed': 1, 'all_zero': 0}}
        self.config = {'fixed_validation': fixed,
                       'schemas': {'catalog.csv': ['itemid', 'first_view_ms']}}
        shape = _shape(self.config)
        self.source_rows = []; self.payloads = []
        for index in range(7):
            _, payload = _row(index, shape)
            payload['expected']['key'][2] += 100
            self.source_rows.append(payload['expected']); self.payloads.append(payload)
        self.saved = self.primary / 'queries.jsonl'
        self.write_source()
        (self.dataset / 'catalog.csv').write_text(
            'itemid,first_view_ms\n' + ''.join(f'{item},0\n' for item in range(20)), encoding='utf-8')
        self.deadline = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()

    def write_source(self):
        self.saved.write_bytes(b''.join(encoded(row) for row in self.source_rows))

    def descriptor(self, path):
        return {'path': str(path), 'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def build(self, name='engineering', **kwargs):
        return ledger.build_source_ledger(self.root / name, self.primary, self.paths,
            self.config, deadline_utc=self.deadline, budget_seconds=180, **kwargs)

    def stage_options(self, result):
        return {'deadline_utc': self.deadline, 'budget_seconds': 180,
                'expected_seal_sha256': result['engineering_seal_sha256']}

    def records(self, result):
        root, seal, contract, _ = ledger._open_engineering(
            result['engineering_ledger_folder'], result['engineering_seal_sha256'], lambda: None, True)
        return list(ledger._records(root, seal, contract, lambda: None, {}))

    def test_build_exact_cp_payload_schema_actual_visitors_and_no_scientific_namespace(self):
        original = self.saved.read_bytes()
        built = self.build(expected_primary=self.descriptor(self.saved), chunk_queries=2)
        self.assertEqual(built['records'], 7)
        self.assertEqual(built['visitors'], 3)
        self.assertEqual(built['chunks'], 4)
        self.assertEqual(self.saved.read_bytes(), original)
        self.assertEqual(built['raw_primary_bytes'], len(original))
        for index, record in enumerate(self.records(built)):
            expected = {'ordinal': index, 'key': self.source_rows[index]['key'], 'payload': self.payloads[index]}
            self.assertEqual(encoded(record), encoded(expected))
        root = Path(built['engineering_ledger_folder'])
        for name in ('run.json', 'run_identity.json', 'candidate.json', 'acceptance.json', 'chunks', 'payloads'):
            self.assertFalse((root / name).exists())
        with self.assertRaises(FileNotFoundError):
            CheckpointStore.open(root, {})
        self.assertFalse(built['full_scientific_acceptance'])
        self.assertEqual(built['independent_K1_rank_checks'], 0)

    def test_known_verified_sample_mapping_ignores_subset_ordinals_and_deduplicates(self):
        samples = self.root / 'verified_sample.jsonl'
        rows = [{'ordinal': j, 'key': self.source_rows[i]['key'], 'payload': self.payloads[i]}
                for j, i in enumerate((0, 3, 6))]
        samples.write_bytes(b''.join(encoded(row) for row in rows))
        descriptor = self.descriptor(samples)
        built = self.build(verified_sample_payloads=[descriptor, descriptor])
        self.assertEqual(built['known_verified_sample_payloads_matched'], 3)
        self.assertEqual(built['records'], 7)
        self.assertFalse(built['full_scientific_acceptance'])

    def test_conflicting_or_mutated_verified_sample_is_rejected(self):
        samples = self.root / 'verified_sample.jsonl'
        rows = [{'ordinal': 0, 'key': self.source_rows[0]['key'], 'payload': self.payloads[0]}]
        samples.write_bytes(b''.join(encoded(row) for row in rows))
        original = self.descriptor(samples)
        samples.write_bytes(samples.read_bytes().replace(b'"ndcg"', b'"nDcg"', 1))
        with self.assertRaises(ledger.EngineeringIntegrityError):
            self.build(verified_sample_payloads=[original])

    def test_conflicting_same_key_or_missing_verified_sample_reference_rejects(self):
        first = self.root / 'verified_first.jsonl'
        second = self.root / 'verified_second.jsonl'
        record = {'ordinal': 0, 'key': self.source_rows[0]['key'], 'payload': self.payloads[0]}
        first.write_bytes(encoded(record))
        conflict = deepcopy(record)
        conflict['payload']['precise']['K1']['ndcg'] = '0.125'
        second.write_bytes(encoded(conflict))
        with self.assertRaises(ValueError):
            self.build(name='conflict', verified_sample_payloads=[self.descriptor(first), self.descriptor(second)])
        missing = deepcopy(record)
        missing['key'][0] = '999999'
        missing['payload']['expected']['key'] = list(missing['key'])
        second.write_bytes(encoded(missing))
        with self.assertRaises(ledger.EngineeringIntegrityError):
            self.build(name='missing_sample', verified_sample_payloads=[self.descriptor(second)])

    def test_wrong_rank_intersection_is_not_misrepresented_as_independently_verified(self):
        self.source_rows[1]['predictions']['K1']['selected_neighbors'][0]['union'] = 999999
        self.write_source()
        built = self.build()
        self.assertEqual(built['records'], 7)
        self.assertEqual(built['new_K1_predictions'], 0)
        self.assertFalse(built['full_scientific_acceptance'])
        self.assertEqual(self.records(built)[1]['payload']['expected']['predictions']['K1'][
            'selected_neighbors'][0]['union'], 999999)

    def test_metric_or_binary_delta_self_inconsistency_rejects_engineering_build(self):
        for fault in ('metric', 'delta'):
            with self.subTest(fault=fault):
                original = deepcopy(self.source_rows)
                if fault == 'metric':
                    self.source_rows[0]['terms']['K1']['ndcg'] += .1
                else:
                    self.source_rows[0]['delta']['K1_minus_C1']['ndcg'] += .1
                self.write_source()
                with self.assertRaises(ValueError):
                    self.build(name='bad_' + fault)
                self.assertFalse((self.root / ('bad_' + fault) / 'engineering_seal.json').exists())
                self.source_rows = original
        self.write_source()

    def test_missing_extra_duplicate_and_reordered_source_rows_fail_closed(self):
        original = deepcopy(self.source_rows)
        variants = {'missing': original[:-1], 'extra': [*original, original[-1]],
                    'duplicate': [original[0], *original[0:-1]], 'reorder': [original[1], original[0], *original[2:]]}
        for name, rows in variants.items():
            self.source_rows = rows; self.write_source()
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.build(name=name)
            self.assertFalse((self.root / name / 'engineering_seal.json').exists())
        self.source_rows = original; self.write_source()

    def test_fixed_workload_denominators_and_zero_buckets_are_bound(self):
        for field in ('target_occurrences', 'reachable_target_occurrences', 'all_targets_reachable_queries',
                      'new_visitor_queries', 'multi_item_current_queries', 'multi_item_target_queries',
                      'target_model_query_counts'):
            original = deepcopy(self.config)
            if field == 'target_model_query_counts':
                self.config['fixed_validation'][field]['all_zero'] = 1
            else:
                self.config['fixed_validation'][field] += 1
            with self.subTest(field=field), self.assertRaises(ledger.EngineeringIntegrityError):
                self.build(name='wrong_' + field)
            self.assertFalse((self.root / ('wrong_' + field) / 'engineering_seal.json').exists())
            self.config = original

    def test_global_candidate_union_shape_is_checked_without_ranking(self):
        self.config['fixed_validation']['candidate_union_items'] += 1
        built = self.build()
        with self.assertRaises(ledger.EngineeringIntegrityError):
            ledger.global_engineering_replay(built['engineering_ledger_folder'], self.root / 'wrong_union',
                                              **self.stage_options(built))

    def test_global_and_recovery_are_readonly_counts_and_never_return_quality_metrics(self):
        built = self.build(chunk_queries=2)
        root = Path(built['engineering_ledger_folder'])
        before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
        recovered = ledger.recover_engineering_ledger(root, self.root / 'recover', **self.stage_options(built))
        replayed = ledger.global_engineering_replay(root, self.root / 'global', **self.stage_options(built))
        self.assertEqual(recovered['records'], 7)
        self.assertEqual(replayed['records'], 7)
        self.assertEqual(replayed['visitors'], 3)
        self.assertEqual(replayed['catalog_union'], 20)
        self.assertEqual(replayed['conditional_queries'], 7)
        self.assertFalse(recovered['full_verified_real_ledger_recovered'])
        self.assertFalse(replayed['effectiveness_values_returned_or_retained'])
        self.assertFalse(replayed['original_bootstrap_files_opened'])
        self.assertNotIn('aggregate', replayed)
        self.assertNotIn('ndcg', json.dumps(replayed))
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(set(before), {path for path in root.rglob('*') if path.is_file()})

    def test_new_engineering_draws_use_self_reference_and_not_original_bootstrap(self):
        (self.primary / 'bootstrap.jsonl').write_text('ORIGINAL MUST NOT BE OPENED', encoding='utf-8')
        built = self.build()
        result = ledger.engineering_draw_cost(built['engineering_ledger_folder'], self.root / 'draw_cost',
                                              **self.stage_options(built))
        self.assertEqual(result['engineering_self_reference_draws'], 2000)
        self.assertEqual(result['visitors_per_draw'], 3)
        self.assertEqual(result['records'], 7)
        self.assertFalse(result['original_bootstrap_files_opened'])
        self.assertFalse(result['original_draws_accepted'])
        self.assertFalse(result['effectiveness_values_published'])
        self.assertTrue(result['new_engineering_draw_values_retained_private'])
        self.assertNotIn('delta', result)
        self.assertEqual((self.primary / 'bootstrap.jsonl').read_text(), 'ORIGINAL MUST NOT BE OPENED')

    def test_sealed_corruption_gap_and_unknown_seal_are_rejected_without_repair(self):
        for fault in ('payload', 'gap', 'seal'):
            built = self.build(name='ledger_' + fault, chunk_queries=2)
            root = Path(built['engineering_ledger_folder'])
            options = self.stage_options(built)
            if fault == 'payload':
                payload = next((root / 'engineering_payloads').glob('*.jsonl'))
                payload.write_bytes(payload.read_bytes().replace(b'"ndcg"', b'"nDcg"', 1))
            elif fault == 'gap':
                (root / 'engineering_chunks/00000001.json').unlink()
            else:
                options['expected_seal_sha256'] = '0' * 64
            with self.subTest(fault=fault), self.assertRaises(ledger.EngineeringIntegrityError):
                ledger.recover_engineering_ledger(root, self.root / ('recovery_' + fault), **options)
            self.assertFalse((root / 'acceptance.json').exists())

    def test_source_change_after_seal_prevents_later_source_bound_reuse(self):
        built = self.build()
        self.saved.write_bytes(self.saved.read_bytes().replace(b'"history"', b'"histoRy"', 1))
        with self.assertRaises(ledger.EngineeringIntegrityError):
            ledger.recover_engineering_ledger(built['engineering_ledger_folder'], self.root / 'mutated_recovery',
                                               **self.stage_options(built))

    def test_fault_boundaries_preserve_incomplete_evidence_without_acceptance_or_seal(self):
        for point in ('payload_half_written', 'after_payload_fsync', 'before_manifest_commit',
                      'after_manifest_commit', 'before_engineering_seal'):
            def fault(event):
                if event == point:
                    raise RuntimeError('small engineering fault')
            with self.subTest(point=point), self.assertRaisesRegex(RuntimeError, 'engineering fault'):
                self.build(name=point, chunk_queries=2, fault=fault)
            root = self.root / point
            self.assertFalse((root / 'engineering_seal.json').exists())
            self.assertFalse((root / 'acceptance.json').exists())
            self.assertTrue((root / 'engineering_phase_receipt.json').exists())
            if point != 'before_engineering_seal':
                self.assertTrue(list((root / 'engineering_payloads').iterdir()))

    def test_new_phase_output_cannot_modify_existing_engineering_namespace(self):
        built = self.build()
        root = Path(built['engineering_ledger_folder'])
        for operation in (ledger.recover_engineering_ledger, ledger.global_engineering_replay,
                          ledger.engineering_draw_cost):
            with self.assertRaisesRegex(ValueError, 'read-only engineering ledger'):
                operation(root, root / 'new_output', **self.stage_options(built))

    def test_expired_budget_scope_and_reentry_are_rejected(self):
        with self.assertRaises(TimeoutError):
            ledger.build_source_ledger(self.root / 'expired', self.primary, self.paths, self.config,
                deadline_utc=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        self.assertFalse((self.root / 'expired').exists())
        built = self.build()
        with self.assertRaises(FileExistsError):
            self.build()
        with self.assertRaises(ValueError):
            ledger.build_source_ledger(self.root / 'badbudget', self.primary, self.paths, self.config,
                deadline_utc=self.deadline, budget_seconds=1801)
        self.assertFalse((Path(built['engineering_ledger_folder']) / 'candidate.json').exists())

    def test_small_orchestrator_explicitly_skips_draws_without_filling_zero_cost(self):
        result = ledger.run_ledger_cost(self.root / 'all_small', self.primary, self.paths, self.config,
            deadline_utc=self.deadline, budget_seconds=180, engineering_draws=0)
        self.assertIsNone(result['engineering_draw_cost'])
        self.assertFalse(result['full_verified_real_ledger'])
        self.assertEqual(result['new_K1_predictions'], 0)
        self.assertIsNone(result['T_plan'])

    def test_orchestrator_preserves_total_budget_across_phase_resets(self):
        elapsed = [0.0]
        visited = []
        def phase(*args, **kwargs):
            visited.append(args[0])
            args[-1]()
            elapsed[0] += 2.0
            args[-1]()
            return {'engineering_seal_sha256': '0' * 64}
        with patch.object(ledger, 'monotonic', side_effect=lambda: elapsed[0]), \
                patch.object(ledger, 'build_source_ledger', side_effect=phase), \
                patch.object(ledger, 'global_engineering_replay', side_effect=phase), \
                patch.object(ledger, 'recover_engineering_ledger', side_effect=phase):
            with self.assertRaises(TimeoutError):
                ledger.run_ledger_cost(self.root / 'total_budget', self.primary, self.paths, self.config,
                    deadline_utc=self.deadline, budget_seconds=5, engineering_draws=0)
        self.assertEqual(len(visited), 3)
        self.assertFalse((self.root / 'total_budget/engineering_cost_summary.json').exists())


if __name__ == '__main__':
    unittest.main()
