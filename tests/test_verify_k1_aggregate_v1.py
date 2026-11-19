"""Aggregate replay uses artificial queries, controls and bootstrap files only."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import retailrocket_session_knn_io as primary_fixture
from scripts import retailrocket_session_knn_readback as original_oracle
from scripts.verify_k1_aggregate_v1 import checked_prerequisites, run_stage, verify_aggregate, write_result
from tests.test_retailrocket_session_knn_validation import make_fixture


class AggregateReplayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root, self.paths, self.config = make_fixture(base=Path(temp.name))
        self.primary = root / 'primary'
        self.primary.mkdir()
        primary_fixture.build(self.primary, self.paths, self.config)
        self.model = {
            'support': original_oracle.positive_table(
                self.paths['C1'] / 'support.csv', ['itemid', 'support'], lambda: None),
            'fit_audit': json.loads((self.primary / 'fit_audit.json').read_bytes()),
        }
        self.queries = self.primary / 'queries.jsonl'
        self.digest = sha256(self.queries.read_bytes()).hexdigest()
        self.count = self.config['fixed_validation']['queries']

    def verify(self):
        return verify_aggregate(self.primary, self.paths, self.config, self.model,
                                queries_checked=self.count, verified_query_sha256=self.digest)

    def test_matches_frozen_full_oracle_and_direct_hits(self):
        reference = original_oracle.verify(self.primary, self.paths, self.config)
        result = self.verify()
        self.assertEqual(result['aggregate'], reference['aggregate'])
        self.assertEqual(result['queries'], 7)
        self.assertEqual(result['bootstrap_replicates'], 2000)
        rows = list(original_oracle.rows(self.queries))
        main = result['paired_hits']['main']
        pair = Counter()
        for row in rows:
            hits = [bool(set(row['predictions'][arm]['ids']) & set(row['targets']))
                    for arm in ('K1', 'C1')]
            pair[{(True, True): 'both', (True, False): 'k1_only',
                  (False, True): 'c1_only', (False, False): 'neither'}[tuple(hits)]] += 1
        self.assertEqual(pair, Counter(main['K1_vs_C1']))
        for field, groups in result['paired_hits']['slices'].items():
            for group, counts in groups.items():
                self.assertEqual(counts['queries'], sum(row['slices'][field] == group for row in rows))
            self.assertEqual(sum(counts['hits']['K1'] for counts in groups.values()), main['hits']['K1'])

    def test_missing_or_extra_coverage_cannot_release_aggregate(self):
        self.count -= 1
        with self.assertRaises(ValueError):
            self.verify()
        self.count += 1
        lines = self.queries.read_bytes().splitlines(keepends=True)
        self.queries.write_bytes(b''.join(lines[:-1]))
        with self.assertRaisesRegex(ValueError, 'count or SHA-256'):
            self.verify()
        self.queries.write_bytes(b''.join(lines + [lines[-1]]))
        with self.assertRaisesRegex(ValueError, 'duplicate|Extra query'):
            self.verify()

    def test_changed_bytes_with_identical_json_cannot_reuse_query_receipt(self):
        self.queries.write_bytes(b' ' + self.queries.read_bytes())
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.verify()

    def test_independent_terms_reject_wrong_metric_even_with_matching_bytes(self):
        rows = list(original_oracle.rows(self.queries))
        rows[0]['terms']['K1']['ndcg'] += 0.5
        self.queries.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        self.digest = sha256(self.queries.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'float differs'):
            self.verify()

    def test_original_draw_identity_and_recomputed_paired_delta_are_checked(self):
        for path, field, wrong in ((self.paths['C1'] / 'bootstrap.jsonl', 'query_denominator', -1),
                                   (self.primary / 'bootstrap.jsonl', 'delta', 10.0)):
            with self.subTest(field=field):
                saved = path.read_bytes()
                rows = list(original_oracle.rows(path))
                rows[-1][field] = wrong
                path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.verify()
                path.write_bytes(saved)

    def test_changed_slice_denominator_in_primary_aggregate_is_rejected(self):
        path = self.primary / 'aggregate.json'
        aggregate = json.loads(path.read_bytes())
        aggregate['slices']['visitor_history']['seen']['queries'] += 1
        path.write_text(json.dumps(aggregate), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'exact scalar differs'):
            self.verify()

    def test_verify_both_prerequisites_before_opening_development_results(self):
        out = self.primary.parent
        cohort = {'status': 'passed', 'queries': self.count, 'queries_sha256': self.digest,
                  'roster_sha256': 'a' * 64}
        (out / 'k1_cohort.json').write_text(json.dumps(cohort))
        with self.assertRaises(FileNotFoundError):
            checked_prerequisites(out, self.count, self.digest)
        for wrong in ({'status': 'partial'}, {'queries': 1}, {'queries_sha256': 'f' * 64},
                      {'roster_sha256': 'b' * 64}):
            with self.subTest(wrong=wrong):
                (out / 'k1_predictions.json').write_text(json.dumps(cohort | wrong))
                with self.assertRaises(ValueError):
                    checked_prerequisites(out, self.count, self.digest)

    def test_complete_statistical_entry_binds_receipts_then_publishes_once(self):
        root = self.primary.parent
        runtime = root / 'shop-mysql-runtime'
        primary = runtime / 'retailrocket_session_knn_paired_v1'
        inputs = []
        artifacts = []

        def describe(path):
            data = path.read_bytes()
            return {'path': path.relative_to(root).as_posix(), 'sha256': sha256(data).hexdigest(), 'bytes': len(data)}

        for old, dest, names, bindings in (
                (self.primary, primary, ['queries.jsonl', 'fit_audit.json', 'aggregate.json', 'bootstrap.jsonl'], artifacts),
                (self.paths['C1'], runtime / 'retailrocket_cooccurrence_paired_v1', ['bootstrap.jsonl', 'support.csv'], inputs),
                (self.paths['P0'], runtime / 'retailrocket_popularity_v1' / 'development', ['item_counts.csv'], inputs),
                (self.paths['dataset'], runtime / 'retailrocket_dataset_v1', ['catalog.csv'], inputs)):
            dest.mkdir(parents=True)
            for name in names:
                shutil.copyfile(old / name, dest / name)
                bindings.append(describe(dest / name))
        stage = root / 'reports' / 'stage12'
        stage.mkdir(parents=True)
        spec = stage / 'synthetic-spec.json'
        spec.write_text(json.dumps({'configuration': self.config, 'direct_input_bindings': inputs}))
        (stage / 'retailrocket_session_knn_v1_validation_attempt.json').write_text(json.dumps({
            'specification': describe(spec), 'preservation': {'execution_artifacts': artifacts}}))
        out = root / 'out'
        out.mkdir()
        receipt = {'status': 'passed', 'queries': self.count, 'queries_sha256': self.digest,
                   'roster_sha256': json.loads((primary / 'aggregate.json').read_bytes())['roster_sha256']}
        for name in ('k1_predictions.json', 'k1_cohort.json'):
            (out / name).write_text(json.dumps(receipt))
        run_stage(out, root)
        result = json.loads((out / 'k1_aggregate.json').read_bytes())
        for name, value in receipt.items():
            self.assertEqual(result[name], value)
        self.assertEqual(len(result['inputs']), 9)
        self.assertEqual(result['bootstrap_replicates'], 2000)
        with self.assertRaises(FileExistsError):
            run_stage(out, root)

    def test_failed_serialization_leaves_no_partial_receipt(self):
        dest = self.primary / 'never-published.json'
        with self.assertRaises(ValueError):
            write_result(dest, {'invalid': float('nan')})
        self.assertFalse(dest.exists())
        self.assertFalse(list(dest.parent.glob('*.tmp')))
