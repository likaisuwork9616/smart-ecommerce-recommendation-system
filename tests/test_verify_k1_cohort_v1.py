"""Exercise the independent cohort verifier with the original frozen V1 artificial archive format."""

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_io as fixture_builder
from scripts import verify_k1_cohort_v1 as cohort
from tests.test_retailrocket_session_knn_validation import csv_rows, make_fixture, write_csv, write_lines


class CohortVerificationTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        root, self.paths, self.config = make_fixture(Path(temp))
        self.primary = root / 'primary'
        self.primary.mkdir()
        fixture_builder.build(self.primary, self.paths, self.config)
        self.archive = self.primary / 'queries.jsonl'

    def verify(self, digest=None):
        return cohort.verify_cohort(self.primary, self.paths, self.config,
                                    digest or sha256(self.archive.read_bytes()).hexdigest())

    def test_original_roster_pairing_role_exclusion_and_digest(self):
        # Frozen fixture has deliberately unparsable reserved-test and tail fields.
        receipt = self.verify()
        self.assertEqual(receipt['queries'], 7)
        self.assertEqual(receipt['test_ranked_queries'], 0)
        self.assertEqual(receipt['visitors'], self.config['fixed_validation']['visitors'])
        self.assertTrue(receipt['paired_streams_eof'])
        self.assertEqual(receipt['roster_sha256'], json.loads((self.primary / 'aggregate.json').read_bytes())['roster_sha256'])
        with self.assertRaises(ValueError):
            self.verify('f' * 64)

    def test_missing_extra_and_misaligned_original_controls(self):
        path = self.paths['D1'] / 'queries.jsonl'
        original = [json.loads(line) for line in path.read_bytes().splitlines()]
        for tag, rows in [('missing', original[:-1]), ('extra', [*original, original[-1]]),
                          ('swapped', [original[1], original[0], *original[2:]])]:
            with self.subTest(tag=tag):
                write_lines(path, rows)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_reject_wrong_control_or_causal_history_even_when_digest_matches(self):
        original = self.archive.read_bytes()
        for tag in ('future item in history', 'control fit', 'extra output field'):
            with self.subTest(tag=tag):
                rows = [json.loads(line) for line in original.splitlines()]
                if tag == 'future item in history':
                    rows[0]['history'].append('99999999')
                elif tag == 'control fit':
                    rows[0]['predictions']['C1']['fit_id'] = 'incorrect'
                else:
                    rows[0]['extra'] = None
                write_lines(self.archive, rows)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_missing_or_ineligible_source_queries(self):
        path = self.paths['dataset'] / 'queries.csv'
        header, original = csv_rows(path)
        first = next(i for i, row in enumerate(original) if row['role'] == 'validation')
        cases = {'role': 'reserved_test', 'mature': '0', 'cross_role': '1',
                 'next_in_session': '0', 'next_role': 'train', 'status': 'unlabelled',
                 'next_view_ms': original[first]['query_ms'], 'basket_index': '0',
                 'target_items': '["99999999"]'}
        for field, value in cases.items():
            with self.subTest(field=field):
                changed = list(original)
                changed[first] = {**original[first], field: value}
                write_csv(path, header, changed)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_raw_basket_clock_and_role_are_checked(self):
        path = self.paths['dataset'] / 'baskets.csv'
        header, original = csv_rows(path)
        first = next(i for i, row in enumerate(original) if row['role'] == 'validation')
        for field, value in [('role', 'train'), ('query_ms', str(self.config['validation_window_ms'][1])),
                             ('basket_index', '99')]:
            with self.subTest(field=field):
                changed = list(original)
                changed[first] = {**original[first], field: value}
                write_csv(path, header, changed)
                with self.assertRaises(ValueError):
                    self.verify()


if __name__ == '__main__':
    unittest.main()
