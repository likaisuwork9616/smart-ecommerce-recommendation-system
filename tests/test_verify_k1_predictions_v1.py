"""Differential checks on artificial sessions. The frozen V1 oracle scans every session and item."""

import csv
import hashlib
import json
import math
import random
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from scripts import retailrocket_session_knn_oracle as oracle
from scripts import verify_k1_predictions_v1 as verifier


class PredictionDifferentialTests(unittest.TestCase):
    def compare(self, sessions, counts, catalog, queries):
        fit_id = 'a' * 64
        model = verifier.Model(sessions, counts, catalog, fit_id)
        full = {(str(visitor), start): set(map(str, items)) for visitor, start, items in sessions}
        support = Counter(item for items in full.values() for item in items)
        p0 = {str(item): count for item, count in counts.items()}
        first = {str(item): time for item, time in catalog.items()}
        predictions = []
        for t, history, current in queries:
            with self.subTest(t=t, history=history, current=current):
                got = model.predict(t, history, current)
                want = oracle.predict(full, support, fit_id, p0, first, t, history, current)
                self.assertDictEqual(got, want)
                oracle.exact(got, want)  # JSON equality also distinguishes ints from booleans.
                predictions.append(got)
        return predictions

    def test_numeric_tie_and_exact_boundary(self):
        # Similarity 1/3 has two distinct raw representations. Break the tie across
        # 500 by numeric visitor and session start, including a low visitor with two sessions.
        sessions = [(1, 11, (1, 2, 3)), (2, 10, (1,)), (2, 11, (1, 2, 4, 5, 6))]
        sessions += [(v, 10, (1,) if v % 2 else (1, 2, 4, 5, 6)) for v in range(3, 505)]
        sessions.append((505, 10, (1, 7, 8, 9, 10)))
        catalog = {i: 1 for i in range(1, 14)}
        pred, = self.compare(sessions, {10: 1200}, catalog, [(100, ['1', '2', '3'], ['1', 10])])
        self.assertEqual(pred['eligible_neighbors'], 506)
        self.assertEqual((pred['boundary_similarity'], pred['boundary_ties_total'],
                          pred['boundary_ties_excluded']), ([1, 3], 504, 5))
        keys = [entry['key'] for entry in pred['selected_neighbors']]
        self.assertEqual(keys[:3], [['1', 11], ['2', 10], ['2', 11]])
        self.assertEqual(keys[-1], ['499', 10])

    def test_exact_lcm_beyond_machine_word(self):
        primes = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71]
        sessions = [(i, 1, tuple(range(1, p + 1))) for i, p in enumerate(primes, start=1)]
        pred, = self.compare(sessions, {2: 17}, {i: 1 for i in range(1, 72)},
                             [(3, ['1'], ['100', 1])])
        score = sum((Fraction(1, p) for p in primes), Fraction())
        self.assertGreater(score.denominator, 2 ** 64)
        self.assertEqual(score.denominator, math.prod(primes))
        self.assertEqual(pred['scores'][0], [score.numerator, score.denominator])
        self.assertEqual(pred['ids'][:2], ['2', '1'])

    def test_strict_candidates_seen_items_unknown_seed_and_zero_fill(self):
        sessions = [(2, 10, (2, 7)), (2, 20, (2, 10)), (10, 10, (2, 15))]
        # Current (2,10) is removed. The other session of visitor 2 remains eligible.
        counts = {7: 200, 10: 3, 15: 3, 20: 40, 25: 60}
        catalog = {2: 0, 7: 0, 10: 0, 15: 50, 20: 49, 25: 51, 30: 0, 40: 0}
        pred, later = self.compare(sessions, counts, catalog, [
            (50, ['2', '999'], ['2', 10]), (51, ['2', '999'], ['2', 10])])
        self.assertEqual(pred['ids'], ['2', '10', '7', '20', '30', '40'])
        self.assertEqual(pred['scores'][:2], [[2, 3], [1, 3]])
        self.assertEqual((pred['current_session_excluded'], pred['unknown_seeds'], pred['zero_fill_slots']),
                         (1, 1, 4))
        self.assertEqual(later['ids'][:3], ['2', '10', '15'])

    def test_fallbacks_and_empty_candidate_set(self):
        sessions = [(1, 10, (1,)), (2, 10, (2,))]
        catalog = {1: 20, 2: 20, 10: 10, 100: 10, 20: 10}
        cold, only_self, no_causal, empty = self.compare(sessions, {100: 2}, catalog, [
            (21, ['999'], ['7', 1]), (21, ['1'], ['1', 10]),
            (20, ['2'], ['7', 1]), (10, ['999'], ['7', 1])])
        self.assertEqual([row['fallback_reason'] for row in (cold, only_self, no_causal)],
                         ['no_supported_seed', 'only_self_session_overlap', 'no_positive_causal_vote'])
        self.assertEqual(no_causal['ids'], ['100', '10', '20'])
        self.assertEqual(empty['ids'], [])

    def test_generated_sessions_and_queries(self):
        rng = random.Random(90471)
        for number in range(35):
            item_ids = rng.sample(range(1, 4000), rng.randint(12, 60))
            keys = sorted({(rng.randint(1, 40), rng.randint(1, 3)) for _ in range(rng.randint(2, 65))})
            sessions = [(v, start, tuple(sorted(rng.sample(item_ids, rng.randint(1, 10)))))
                        for v, start in keys]
            catalog = {i: rng.choice([1, 10, 15, 20]) for i in item_ids + [4001, 4002]}
            counts = {i: rng.randint(1, 8) for i in item_ids if rng.randrange(4)}
            queries = []
            for _ in range(4):
                history = sorted(rng.sample(item_ids + [4001, 4002, 5000], rng.randint(1, 8)))
                v, start = rng.choice(keys + [(41, 1)])
                queries.append((rng.choice([10, 15, 20, 21]), list(map(str, history)), [str(v), start]))
            with self.subTest(fixture=number):
                self.compare(sessions, counts, catalog, queries)


def json_lines(path, rows):
    path.write_text(''.join(oracle.dump(row) + '\n' for row in rows), encoding='utf-8')


def csv_rows(path, header, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


class SyntheticArchiveTests(unittest.TestCase):
    """Drive the actual file reader with V1 SQL membership and exhaustive synthetic query outputs."""

    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temp)
        self.primary, c1, p0, source = [self.root / sub for sub in ('k1', 'c1', 'p0', 'source')]
        for path in (self.primary, c1, p0, source):
            path.mkdir()
        self.enterContext(patch.multiple(verifier, ROOT=self.root, PRIMARY=self.primary, C1=c1,
                                         P0=p0, SOURCE=source, EXPECTED_QUERIES=2))
        begin, end = verifier.TRAIN
        train = [dict(visitor='10', session=begin, time=begin, index=1, items=['1', '20'], role='train'),
                 dict(visitor='10', session=begin, time=begin + 1, index=2, items=['20'], role='train'),
                 dict(visitor='2', session=begin, time=begin, index=1, items=['1', '3'], role='train')]
        full, support, payload, lineage = oracle.reconstruct(train, begin, end)
        counts = dict(Counter(i for row in train for i in row['items']))
        catalog = dict.fromkeys(counts, begin)
        catalog['100'] = end + 1

        baskets = [(r['visitor'], r['session'], r['time'], 'train', r['index'], oracle.dump(r['items']),
                    len(r['items']), len(r['items'])) for r in train]
        # The scorer must discard all nontraining roles before parsing the item payload.
        for role in ('warmup', 'validation', 'test', 'tail'):
            baskets.append(('ignored', 'ignored', 'ignored', role, 'ignored', 'invalid JSON', '', ''))
        csv_rows(source / 'baskets.csv', verifier.BASKET_HEADER, baskets)
        csv_rows(source / 'catalog.csv', ['itemid', 'first_view_ms'],
                 [*catalog.items(), ('held-out-id-is-never-decoded', verifier.VALIDATION[1])])
        csv_rows(p0 / 'item_counts.csv', ['itemid', 'count'], counts.items())
        csv_rows(c1 / 'support.csv', ['itemid', 'support'], support.items())
        for directory in (self.primary, c1):
            json_lines(directory / 'train_sessions.jsonl', lineage)
        json_lines(self.primary / 'sessions.jsonl', payload['sessions'])
        self.postings = payload['postings']
        json_lines(self.primary / 'postings.jsonl', self.postings)
        self.audit = dict(payload['audit'], fit_id=payload['fit_id'])
        (self.primary / 'fit_audit.json').write_text(oracle.dump(self.audit), encoding='utf-8')
        self.queries = []
        for visitor, t, history in [('2', end + 1, ['1']), ('3', end + 2, ['1', '777'])]:
            key = [visitor, begin, t]
            prediction = oracle.predict(full, support, payload['fit_id'], counts, catalog, t, history, key[:2])
            self.queries.append({'key': key, 'history': history, 'predictions': {'K1': prediction}})
        self.file = self.primary / 'queries.jsonl'
        json_lines(self.file, self.queries)
        self.deadline = datetime.now(timezone.utc) + timedelta(minutes=1)

    def test_complete_byte_digest_and_paired_eof(self):
        receipt = verifier.verify(self.root / 'complete', None, self.deadline)
        self.assertEqual(receipt['queries'], 2)
        self.assertEqual(receipt['fit_audit'], self.audit)
        self.assertIs(receipt['query_eof_verified'], True)
        self.assertEqual(receipt['queries_sha256'], hashlib.sha256(self.file.read_bytes()).hexdigest())

    def test_reject_changed_archived_neighbor_evidence(self):
        self.queries[1]['predictions']['K1']['selected_neighbors'][0]['similarity'] = [1, 999]
        json_lines(self.file, self.queries)
        out = self.root / 'bad'
        with self.assertRaises(ValueError):
            verifier.verify(out, None, self.deadline)
        self.assertFalse((out / 'k1_predictions.json').exists())

    def test_missing_and_extra_queries(self):
        extra = dict(self.queries[-1], key=['9', self.queries[-1]['key'][1], self.queries[-1]['key'][2]])
        for rows in (self.queries[:-1], self.queries + [extra]):
            with self.subTest(count=len(rows)):
                json_lines(self.file, rows)
                out = self.root / str(len(rows))
                with self.assertRaises(ValueError):
                    verifier.verify(out, None, self.deadline)
                self.assertFalse((out / 'k1_predictions.json').exists())

    def test_training_postings_checked_even_if_cardinality_matches(self):
        self.postings[0]['sessions'][0] = ['999', verifier.TRAIN[0]]
        json_lines(self.primary / 'postings.jsonl', self.postings)
        with self.assertRaises(ValueError):
            verifier.build(lambda: None)


if __name__ == '__main__':
    unittest.main()
