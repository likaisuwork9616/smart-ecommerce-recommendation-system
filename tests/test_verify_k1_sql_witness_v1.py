"""SQL witness differential and failure checks against small artificial files."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_io as primary_fixture
from scripts.verify_k1_sql_witness_v1 import ordinals, verify
from tests.test_retailrocket_session_knn_validation import make_fixture


class SqlWitnessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root, self.paths, self.config = make_fixture(base=Path(temp.name))
        self.primary = self.root / 'primary'
        self.primary.mkdir()
        primary_fixture.build(self.primary, self.paths, self.config)

    def verify(self):
        return verify(self.primary, self.paths, self.config, self.root / 'fresh-sql',
                      sha256((self.primary / 'queries.jsonl').read_bytes()).hexdigest())

    def test_all_training_artifacts_and_full_synthetic_predictions_match(self):
        result = self.verify()
        self.assertEqual(result['fit_audit'], json.loads((self.primary / 'fit_audit.json').read_bytes()))
        self.assertEqual(result['index_counts']['session_item_memberships'],
                         result['fit_audit']['distinct_session_item_memberships'])
        self.assertEqual(result['ordinals_zero_based'], list(range(7)))
        self.assertEqual(result['queries_sql_checked'], 7)
        self.assertEqual(result['queries_scanned'], 7)
        self.assertEqual(result['database_sha256'], sha256((self.root / 'fresh-sql' / 'independent.sqlite').read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            self.verify()

    def test_real_roster_sampling_plan_is_fixed_and_includes_endpoints(self):
        points = ordinals(166897)
        self.assertEqual(len(points), 33)
        self.assertEqual(points[0], 0)
        self.assertEqual(points[-1], 166896)
        self.assertEqual(points, [j * 166896 // 32 for j in range(33)])

    def test_complete_nested_prediction_difference_is_rejected(self):
        path = self.primary / 'queries.jsonl'
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        rows[-1]['predictions']['K1']['neighbor_pool_sha256'] = 'f' * 64
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'exact value mismatch'):
            self.verify()

    def test_sql_uses_raw_baskets_to_check_history(self):
        path = self.primary / 'queries.jsonl'
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        rows[0]['history'] = ['999']
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'exact value mismatch'):
            self.verify()

    def test_sql_reconstruction_compares_both_saved_train_lineages(self):
        path = self.paths['C1'] / 'train_sessions.jsonl'
        path.write_bytes(b''.join(path.read_bytes().splitlines(keepends=True)[1:]))
        with self.assertRaisesRegex(ValueError, 'exact value mismatch'):
            self.verify()
