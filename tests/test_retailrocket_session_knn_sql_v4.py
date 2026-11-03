"""Synthetic-only V4 full-output differential checks against both frozen oracles."""
from collections import Counter
from contextlib import closing
from fractions import Fraction
import hashlib
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_readback as v1
from scripts import retailrocket_session_knn_sql_v2 as v2
from scripts import retailrocket_session_knn_sql_v4 as v4


class ExactRankingTests(unittest.TestCase):
    def fixture(self, sessions, catalog=None, counts=None, database=':memory:'):
        self.db = sqlite3.connect(database)
        self.addCleanup(self.db.close)
        self.sessions = {key: set(items) for key, items in sessions.items()}
        self.db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        self.db.executemany('INSERT INTO m VALUES(?,?,?)', ((v, s, i) for (v, s), members
                            in self.sessions.items() for i in sorted(members, key=int)))
        self.support = dict(Counter(item for members in self.sessions.values() for item in members))
        self.catalog = dict.fromkeys(self.support, 0) if catalog is None else catalog
        self.counts = self.support if counts is None else counts
        self.prepared = v4.prepare_catalog(self.catalog, self.counts)
        v4.build_index(self.db)
        self.db.commit()

    def check(self, history, current=('1', 999), at=100, support=None, read_db=None, prepared=True):
        support = self.support if support is None else support
        db = self.db if read_db is None else read_db
        model = self.prepared if prepared else self.catalog
        counts = self.prepared.counts if prepared else self.counts
        arguments = db, support, 'synthetic', counts, model, at, history, current
        work2, work4, times = {}, {}, {}
        reference = v1.predict(self.sessions, support, 'synthetic', self.counts, self.catalog, at,
                               history, current, lambda: None)
        old = v2.predict(*arguments, workload=work2)
        new = v4.predict(*arguments, workload=work4, timings=times)
        self.assertEqual(reference, new)
        self.assertEqual(old, new)
        for key in set(work2)-{'fraction_vote_additions'}:
            self.assertEqual(work2[key], work4[key], key)
        self.assertEqual(work2['fraction_vote_additions'], work4['exact_vote_additions'])
        self.assertEqual(work4['integer_vote_additions']+work4['fraction_vote_additions'], work4['exact_vote_additions'])
        self.assertEqual(set(times), {'history_and_temp_setup', 'sql_positive_overlaps', 'neighbor_pool_sha',
            'exact_neighbor_selection', 'sql_selected_votes_and_accumulation', 'top_ten_and_zero_fill', 'prediction_output'})
        self.assertTrue(all(value >= 0 for value in times.values()))
        self.assertNotIn('workload', new)
        self.assertNotIn('timings', new)
        return new, work4

    def test_hand_scores_unknown_self_other_session_future_and_zero_fill(self):
        self.fixture({('7', 1): {'1', '88'}, ('7', 2): {'1'}, ('10', 1): {'1', '2'},
                      ('2', 1): {'1', '3', '4'}},
                     {'1': 1, '2': 1, '3': 1, '4': 100, '9': 1, '8': 1}, {'9': 3, '8': 3})
        row, work = self.check(['1', '999', '1'], ('7', 1))
        self.assertEqual(row['ids'], ['1', '2', '3', '8', '9'])
        self.assertEqual(row['scores'], [[13, 12], [1, 3], [1, 4], [0, 1], [0, 1]])
        self.assertEqual((row['unknown_seeds'], row['current_session_excluded']), (1, 1))
        self.assertEqual(row['selected_neighbors'][0]['key'], ['7', 2])
        self.assertEqual(work['integer_vote_additions'], 5)
        self.assertEqual(work['fraction_vote_additions'], 0)

    def test_ties_with_different_raw_ratios_at_499_500_501_and_large_ids(self):
        for n in (499, 500, 501):
            with self.subTest(n=n):
                # Ratios 1/3 and 2/6 belong to one cutoff group; SHA keeps raw counts.
                start_id = 10**24-250
                sessions = {(str(start_id+i), 0): ({'1'} if i%2 else {'1', '2', '4', '5', '6'})
                            for i in reversed(range(n))}
                self.fixture(sessions)
                row, work = self.check(['1', '2', '3'])
                self.assertEqual([entry['key'][0] for entry in row['selected_neighbors']],
                                 [str(start_id+i) for i in range(min(n, 500))])
                self.assertEqual(row['boundary_ties_total'], n if n >= 500 else 0)
                self.assertEqual(row['boundary_ties_excluded'], max(0, n-500))
                self.assertEqual(work['distinct_neighbor_similarities'], 1)

    def test_competing_cutoff_groups_and_session_start_tie(self):
        sessions = {(str(v), 0): {'1', '3'} for v in range(600)}
        sessions.update({('5', 1): {'1', '2'}, ('5', 2): {'1', '2'}, ('2', 1): {'1', '2'}})
        self.fixture(sessions)
        row, _ = self.check(['1', '2'])
        self.assertEqual([entry['key'] for entry in row['selected_neighbors'][:3]], [['2', 1], ['5', 1], ['5', 2]])
        self.assertEqual(row['boundary_ties_total'], 600)
        self.assertEqual(row['boundary_ties_excluded'], 103)

    def test_high_scores_p0_then_arbitrary_precision_item_id_tie(self):
        big = str(10**23)
        bigger = str(int(big)+1)
        self.fixture({('3', 1): {'1', big, bigger, '20'}}, counts={'20': 9, big: 5, bigger: 5})
        row, _ = self.check(['1'])
        self.assertEqual(row['ids'], ['20', big, bigger, '1'])
        self.assertEqual(row['scores'], [[1, 4]]*4)

    def test_fallbacks_strict_causality_no_catalog_and_empty_history(self):
        self.fixture({('7', 1): {'1'}}, catalog={'1': 100, '2': 110})
        cases = [([], ('7', 1), None, 'no_supported_seed'),
                 (['9'], ('7', 1), {'9': 1}, 'no_eligible_positive_neighbor'),
                 (['1'], ('7', 1), None, 'only_self_session_overlap'),
                 (['1'], ('7', 2), None, 'no_positive_causal_vote')]
        for history, current, support, reason in cases:
            with self.subTest(reason=reason):
                row, _ = self.check(history, current, support=support, prepared=False)
                self.assertEqual(row['fallback_reason'], reason)
                self.assertEqual(row['candidate_count'], 0)

    def test_fallback_fraction_accumulation_matches_scaled_integers(self):
        self.fixture({('1', 0): {'1'}, ('2', 0): {'1', '2'}, ('3', 0): {'1', '3', '4', '5'}})
        ints, _ = self.check(['1', '9'])
        with patch.object(v4, 'MAX_VOTE_SCALE_BITS', 2):
            fractions, work = self.check(['1', '9'])
        self.assertEqual(ints, fractions)
        self.assertTrue(work['fraction_fallback'])
        self.assertEqual(work['integer_vote_additions'], 0)
        self.assertEqual(work['fraction_vote_additions'], 7)
        self.assertIsNone(v4._common_scale(iter([2**4096+1, 3])))

    def test_cross_product_near_equal_ratios_beyond_float_precision(self):
        n = 10**70
        pairs = [((n+1, n), (n+2, n+1)), ((n+2, n+1), (n+1, n)), ((2, 6), (1, 3))]
        for a, b in pairs:
            left, right = Fraction(*a), Fraction(*b)
            self.assertEqual(v4._greater_ratio_first(a, b), (left < right)-(left > right))

    def test_randomized_three_way_full_nested_differential(self):
        rng = random.Random(48971)
        items = [str(i) for i in range(70)]
        sessions = {(str(i//2), i%2): set(rng.sample(items, rng.randint(1, 18))) for i in range(85)}
        self.fixture(sessions, {i: rng.randrange(150) for i in items}, {i: rng.randrange(20) for i in items})
        for _ in range(30):
            self.check(rng.sample(items+['99'], rng.randint(0, 17)), rng.choice(list(sessions)), at=rng.randrange(150))

    def test_reopened_read_only_model_bytes_are_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'sealed.sqlite'
            self.fixture({('7', 4): {'1', '9'}}, database=path)
            self.db.close()
            original = hashlib.sha256(path.read_bytes()).digest()
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as read_db:
                self.check(['1'], read_db=read_db)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), original)
            self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])

    def test_missing_size_row_detected_even_for_self(self):
        self.fixture({('1', 0): {'1'}, ('2', 0): {'1'}})
        self.db.execute("DELETE FROM k1_v2_sizes WHERE v='1'")
        with self.assertRaisesRegex(ValueError, 'Missing or invalid'):
            v4.predict(self.db, self.support, 'fit', self.counts, self.catalog, 100, ['1'], ('1', 0))

    def test_watch_interrupts_vote_loop_and_retry_discards_temp_tail(self):
        self.fixture({(str(v), 0): {'1', str(v+2)} for v in range(150)})
        work = {}
        def watch():
            if work.get('sql_vote_membership_rows_returned', 0) >= 15:
                raise TimeoutError('synthetic interrupt inside vote loop')
        with self.assertRaisesRegex(TimeoutError, 'inside vote loop'):
            v4.predict(self.db, self.support, 'fit', self.prepared.counts, self.prepared,
                       100, ['1'], ('9', 9), watch, workload=work)
        self.assertEqual(work['sql_vote_membership_rows_returned'], 15)
        self.assertEqual(work['integer_vote_additions'], 15)
        self.check(['1'])


if __name__ == '__main__':
    unittest.main()
