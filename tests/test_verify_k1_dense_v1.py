"""Run both dense vote paths against the independent frozen brute force and source archive."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_io as fixture_builder
from scripts import verify_k1_dense_v1 as dense
from tests import test_verify_k1_predictions_v1 as reference_cases
from tests.test_retailrocket_session_knn_validation import make_fixture


class DenseDifferentialTests(reference_cases.PredictionDifferentialTests):
    def setUp(self):
        self.enterContext(patch.object(reference_cases.verifier, 'Model', dense.DenseModel))

    def test_zero_support_catalog_and_empty_model(self):
        row, = self.compare([], {}, {10: 1, 2: 1}, [(3, ['123'], ['3', 1])])
        self.assertEqual(row['ids'], ['2', '10'])

    def test_large_integer_vote_hits_exact_all_edges_branch(self):
        primes = (7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43)
        model = dense.DenseModel([(i, 1, tuple(range(p))) for i, p in enumerate(primes)], {},
                                 {i: 0 for i in range(43)}, 'synthetic')
        model.predict(3, ['0'], ['100', 1])
        model.predict(3, ['9999'], ['100', 1])
        self.assertEqual(model.voting_modes, {'full_membership_scan_python_int': 1, 'dense_uint32': 1})


class DenseArchiveTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temp)
        fixture, paths, config = make_fixture(self.root)
        files = self.root / dense.RUNTIME
        self.primary = files / 'retailrocket_session_knn_paired_v1'
        self.primary.mkdir(parents=True)
        fixture_builder.build(self.primary, paths, config)
        self.queries = self.primary / 'queries.jsonl'
        self.out = fixture / 'out'
        self.deadline = datetime.now(timezone.utc) + timedelta(minutes=1)

        def descriptor(path):
            b = path.read_bytes()
            return dict(path=path.relative_to(self.root).as_posix(), bytes=len(b), sha256=hashlib.sha256(b).hexdigest())

        inputs = []
        for source, dest in ((paths['P0'] / 'item_counts.csv', 'retailrocket_popularity_v1/development'),
                             (paths['dataset'] / 'catalog.csv', 'retailrocket_dataset_v1')):
            directory = files / dest
            directory.mkdir(parents=True)
            target = directory / source.name
            shutil.copyfile(source, target)
            inputs.append(descriptor(target))
        self.attempt = self.root / dense.ATTEMPT
        self.attempt.parent.mkdir(parents=True)
        spec = self.attempt.parent / 'synthetic.json'
        spec.write_text(json.dumps({'configuration': config, 'direct_input_bindings': inputs}), encoding='utf-8')
        self.doc = {'specification': descriptor(spec), 'preservation': {'execution_artifacts': [
            descriptor(self.primary / name) for name in ('queries.jsonl', 'fit_audit.json', 'sessions.jsonl')]}}
        self.attempt.write_text(json.dumps(self.doc), encoding='utf-8')

    def test_complete_matvec_counts_and_artifact_sha(self):
        result = dense.run(self.out, self.deadline, root=self.root)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual((result['queries'], result['session_query_comparisons']), (7, 49))
        self.assertEqual(sum(result['voting_modes'].values()), 7)
        self.assertEqual(result['membership_intersections_checked'], result['vote_memberships_scanned'])
        self.assertEqual(result['roster_sha256'], json.loads((self.primary / 'aggregate.json').read_bytes())['roster_sha256'])
        self.assertEqual(result['queries_sha256'], hashlib.sha256(self.queries.read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            dense.run(self.out, self.deadline, root=self.root)

    def test_change_inside_bound_synthetic_query_preserves_only_verified_prefix(self):
        rows = self.queries.read_bytes().splitlines(keepends=True)
        changed = json.loads(rows[2])
        changed['predictions']['K1']['neighbor_pool_sha256'] = 'f' * 64
        rows[2] = json.dumps(changed).encode('utf8') + b'\n'
        self.queries.write_bytes(b''.join(rows))
        self.doc['preservation']['execution_artifacts'][0].update(bytes=self.queries.stat().st_size,
                    sha256=hashlib.sha256(self.queries.read_bytes()).hexdigest())
        self.attempt.write_text(json.dumps(self.doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Dense predictions differ at query 3'):
            dense.run(self.out, self.deadline, root=self.root)
        self.assertFalse((self.out / 'k1_dense.json').exists())
        progress = json.loads((self.out / 'k1_dense.progress.json').read_bytes())
        self.assertEqual((progress['queries'], progress['status']), (2, 'incomplete'))
        self.assertEqual(progress['prefix_query_sha256'], hashlib.sha256(b''.join(rows[:2])).hexdigest())


if __name__ == '__main__':
    unittest.main()
