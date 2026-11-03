"""Synthetic exact SQL/V1 differential checks; no real K1 outputs are read."""
import ast
from collections import Counter
from dataclasses import FrozenInstanceError
from fractions import Fraction
import inspect
import hashlib
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from scripts import retailrocket_session_knn_sql_v2 as sql
from scripts import retailrocket_session_knn_readback as v1


class ExactSqlPredictionTests(unittest.TestCase):
    def fixture(self, sessions, counts=None, catalog=None):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE h(v TEXT,s INTEGER,t INTEGER,k INTEGER,'
                        'role TEXT,items TEXT,n INTEGER,PRIMARY KEY(v,s,t),UNIQUE(v,s,k))')
        self.db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        self.sessions = {key: set(items) for key, items in sessions.items()}
        self.db.executemany('INSERT INTO m VALUES(?,?,?)',
                            ((v, session, item) for (v, session), items in sessions.items()
                             for item in set(items)))
        self.db.execute("INSERT INTO h VALUES('90',100,110,1,'validation','[\"99\"]',1)")
        self.support = dict(Counter(item for items in self.sessions.values() for item in items))
        self.counts = dict(self.support if counts is None else counts)
        self.catalog = dict({str(item): 1 for item in range(1, 31)} if catalog is None else catalog)
        self.index_audit = sql.build_index(self.db)
        self.db.commit()
        self.prepared = sql.prepare_catalog(self.catalog, self.counts)

    def check_prediction(self, history=('1', '99'), current=('90', 100), time=110,
                         *, support=None, prepared=True, watch=lambda: None, workload=None):
        actual_support = self.support if support is None else support
        catalog = self.prepared if prepared else self.catalog
        counts = self.prepared.counts if prepared else self.counts
        actual = sql.predict(self.db, actual_support, 'synthetic-fit', counts, catalog,
                             time, history, current, watch, workload=workload)
        expected = v1.predict(self.sessions, actual_support, 'synthetic-fit', self.counts,
                              self.catalog, time, history, current, lambda: None)
        self.assertEqual(actual, expected)
        return actual

    def test_hand_jaccard_exact_votes_and_complete_nested_schema(self):
        self.fixture({('1', 10): {'1', '2'}, ('2', 20): {'1', '3', '4'},
                      ('3', 30): {'1'}})
        prediction = self.check_prediction()
        self.assertEqual([row['similarity'] for row in prediction['selected_neighbors']],
                         [[1, 2], [1, 3], [1, 4]])
        self.assertEqual(prediction['ids'][:4], ['1', '2', '3', '4'])
        self.assertEqual(prediction['scores'][:4], [[13, 12], [1, 3], [1, 4], [1, 4]])
        self.assertEqual(prediction['unknown_seeds'], 1)
        self.assertEqual(prediction['candidate_count'], 30)
        self.assertEqual(set(prediction), {'fit_id', 'ids', 'scores', 'p0_counts', 'candidate_count',
            'history_size', 'supported_seeds', 'unknown_seeds', 'raw_posting_visits',
            'current_session_excluded', 'eligible_neighbors', 'neighbor_pool_sha256',
            'selected_neighbors', 'selected_neighbor_count', 'boundary_similarity',
            'boundary_ties_total', 'boundary_ties_excluded', 'vote_memberships',
            'positive_candidates', 'zero_fill_slots', 'fallback_reason'})

    def test_499_500_501_neighbors_numeric_tie_boundary_and_pool_hash(self):
        for count in (499, 500, 501):
            with self.subTest(count=count):
                sessions = {(str(visitor), 10): {'1', str(visitor + 1000)}
                            for visitor in reversed(range(1, count + 1))}
                self.fixture(sessions, catalog={item: 1 for items in sessions.values() for item in items})
                prediction = self.check_prediction(history=('1',))
                selected = min(count, 500)
                self.assertEqual([row['key'][0] for row in prediction['selected_neighbors']],
                                 [str(visitor) for visitor in range(1, selected + 1)])
                self.assertEqual(prediction['eligible_neighbors'], count)
                self.assertEqual(prediction['selected_neighbor_count'], selected)
                self.assertEqual(prediction['boundary_similarity'], None if count == 499 else [1, 2])
                self.assertEqual(prediction['boundary_ties_total'], 0 if count == 499 else count)
                self.assertEqual(prediction['boundary_ties_excluded'], max(0, count - 500))

    def test_numeric_visitor_session_and_item_order(self):
        self.fixture({('10', 3): {'1', '10'}, ('2', 9): {'1', '9'},
                      ('2', 3): {'1', '11'}},
                     counts={'1': 3, '9': 1, '10': 1, '11': 1},
                     catalog={'11': 1, '10': 1, '9': 1, '1': 1})
        prediction = self.check_prediction(history=('1',))
        self.assertEqual([row['key'] for row in prediction['selected_neighbors']],
                         [['2', 3], ['2', 9], ['10', 3]])
        self.assertEqual(prediction['ids'], ['1', '9', '10', '11'])

    def test_visitor_identifiers_beyond_sqlite_integer_range_keep_python_numeric_order(self):
        self.fixture({('100000000000000000000', 1): {'1'},
                      ('99999999999999999999', 1): {'1'}}, catalog={'1': 1})
        prediction = self.check_prediction(history=('1',))
        self.assertEqual([row['key'][0] for row in prediction['selected_neighbors']],
                         ['99999999999999999999', '100000000000000000000'])

    def test_unknown_history_items_remain_in_union_denominator(self):
        self.fixture({('1', 10): {'1', '2'}, ('2', 20): {'1', '3', '4'}, ('3', 30): {'1'}})
        prediction = self.check_prediction(history=('1', '99', '100'))
        self.assertEqual([row['similarity'] for row in prediction['selected_neighbors']],
                         [[1, 3], [1, 4], [1, 5]])
        self.assertEqual(prediction['scores'][0], [47, 60])
        self.assertEqual(prediction['unknown_seeds'], 2)

    def test_duplicate_history_matches_v1_set_semantics(self):
        self.fixture({('1', 10): {'1', '2'}, ('2', 20): {'1', '3'}})
        prediction = self.check_prediction(history=('1', '1', '99', '99'))
        self.assertEqual(prediction['history_size'], 2)

    def test_exact_self_excluded_other_session_same_visitor_kept(self):
        self.fixture({('1', 10): {'1', '2'}, ('1', 15): {'1', '4'}, ('2', 20): {'1', '3'}})
        work = {}
        prediction = self.check_prediction(history=('1',), current=('1', 10), workload=work)
        self.assertEqual(prediction['current_session_excluded'], 1)
        self.assertNotIn(['1', 10], [row['key'] for row in prediction['selected_neighbors']])
        self.assertIn(['1', 15], [row['key'] for row in prediction['selected_neighbors']])
        self.assertEqual(prediction['raw_posting_visits'], 3)
        self.assertEqual(work['sql_overlap_groups_returned'], 3)
        self.assertEqual(work['sql_selected_rows_inserted'], 2)

    def test_nonoverlapping_self_is_not_counted_as_excluded(self):
        self.fixture({('1', 10): {'2'}, ('2', 20): {'1'}})
        self.assertEqual(self.check_prediction(history=('1',), current=('1', 10))[
            'current_session_excluded'], 0)

    def test_strict_causal_catalog_clock_and_future_votes(self):
        self.fixture({('1', 10): {'1', '2', '3'}},
                     counts={'1': 1, '2': 1000, '3': 1, '4': 500, '5': 100},
                     catalog={'1': 1, '2': 110, '3': 111, '4': 109, '5': 110})
        prediction = self.check_prediction(history=('1',))
        self.assertEqual(prediction['ids'], ['1', '4'])
        self.assertEqual(prediction['candidate_count'], 2)
        self.assertEqual(prediction['positive_candidates'], 1)
        self.assertEqual(prediction['vote_memberships'], 3)

    def test_no_supported_seed_full_p0_fallback(self):
        self.fixture({('1', 10): {'1', '2'}},
                     counts={'1': 1, '2': 3, '10': 4, '9': 4, '11': 100},
                     catalog={'11': 110, '10': 1, '9': 1, '2': 1, '1': 1})
        prediction = self.check_prediction(history=('999',))
        self.assertEqual(prediction['ids'], ['9', '10', '2', '1'])
        self.assertEqual(prediction['scores'], [[0, 1]] * 4)
        self.assertEqual(prediction['fallback_reason'], 'no_supported_seed')

    def test_only_self_session_overlap_fallback(self):
        self.fixture({('1', 10): {'1'}}, catalog={'1': 1, '2': 1})
        prediction = self.check_prediction(history=('1',), current=('1', 10))
        self.assertEqual(prediction['fallback_reason'], 'only_self_session_overlap')
        self.assertEqual(prediction['raw_posting_visits'], 1)
        self.assertEqual(prediction['eligible_neighbors'], 0)

    def test_no_eligible_neighbor_fallback_matches_v1_even_for_external_support(self):
        self.fixture({('1', 10): {'1'}}, catalog={'1': 1, '2': 1})
        prediction = self.check_prediction(history=('99',), support={'99': 1})
        self.assertEqual(prediction['fallback_reason'], 'no_eligible_positive_neighbor')

    def test_no_positive_causal_vote_and_empty_catalog_at_query(self):
        self.fixture({('1', 10): {'1', '2'}}, catalog={'1': 110, '2': 200})
        prediction = self.check_prediction(history=('1',))
        self.assertEqual(prediction['fallback_reason'], 'no_positive_causal_vote')
        self.assertEqual(prediction['candidate_count'], 0)
        self.assertEqual(prediction['ids'], [])
        self.assertEqual(prediction['vote_memberships'], 2)

    def test_empty_membership_and_history_relations(self):
        self.fixture({}, catalog={'1': 1, '2': 110})
        prediction = self.check_prediction(history=())
        self.assertEqual(prediction['ids'], ['1'])
        self.assertEqual(prediction['neighbor_pool_sha256'],
                         'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')

    def test_complete_zero_complement_and_full_candidate_denominator(self):
        self.fixture({('1', 10): {'1'}},
                     counts={str(item): item for item in range(1, 41)},
                     catalog={str(item): 1 if item <= 35 else 110 for item in range(1, 41)})
        prediction = self.check_prediction(history=('1',))
        self.assertEqual(prediction['candidate_count'], 35)
        self.assertEqual(prediction['ids'], ['1', *map(str, range(35, 26, -1))])
        self.assertEqual(prediction['zero_fill_slots'], 9)

    def test_sql_workload_counts_actual_positive_rows_not_all_train_sessions(self):
        sessions = {(str(visitor), 1): {str(visitor + 100)} for visitor in range(1, 1001)}
        sessions[('2000', 1)] = {'1', '2'}
        self.fixture(sessions)
        work = {}
        prediction = self.check_prediction(history=('1',), workload=work)
        self.assertEqual(self.index_audit, {'train_sessions': 1001, 'session_item_memberships': 1002})
        self.assertEqual(work['sql_overlap_groups_returned'], 1)
        self.assertEqual(work['sql_overlap_membership_matches'], 1)
        self.assertEqual(work['sql_vote_membership_rows_returned'], 2)
        self.assertEqual(work['neighbor_pool_rows_hashed'], 1)
        self.assertEqual(work['catalog_snapshot_rows_prepared'], 0)
        self.assertNotIn('all_session_visits', work)
        self.assertNotIn('workload', prediction)

    def test_mutable_catalog_path_and_prepared_path_match_full_v1(self):
        self.fixture({('1', 10): {'1', '2'}, ('2', 20): {'1', '3'}})
        work = {}
        prepared = self.check_prediction()
        direct = self.check_prediction(prepared=False, workload=work)
        self.assertEqual(direct, prepared)
        self.assertEqual(work['catalog_snapshot_rows_prepared'], 30)

    def test_prepared_snapshot_is_immutable_and_rejects_unbound_counts(self):
        self.fixture({('1', 10): {'1'}}, catalog={'1': 1, '2': 1})
        with self.assertRaises(TypeError):
            self.prepared.first['1'] = 999
        with self.assertRaises(TypeError):
            self.prepared.counts['1'] = 999
        with self.assertRaises(FrozenInstanceError):
            self.prepared.fallback = ()
        with self.assertRaisesRegex(ValueError, 'immutable counts snapshot'):
            sql.predict(self.db, self.support, 'fit', self.counts, self.prepared,
                        110, ('1',), ('90', 100))
        self.catalog['1'] = 999
        self.counts['2'] = 999
        actual = sql.predict(self.db, self.support, 'fit', self.prepared.counts,
                             self.prepared, 110, ('1',), ('90', 100))
        expected = v1.predict(self.sessions, self.support, 'fit', self.prepared.counts,
                              self.prepared.first, 110, ('1',), ('90', 100), lambda: None)
        self.assertEqual(actual, expected)

    def test_build_index_preserves_h_m_and_rejects_reentry(self):
        self.fixture({('1', 10): {'1', '2'}, ('2', 20): {'3'}})
        self.assertEqual(self.db.execute('SELECT v,s,n FROM k1_v2_sizes ORDER BY v').fetchall(),
                         [('1', 10, 2), ('2', 20, 1)])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM m').fetchone()[0], 3)
        self.assertEqual(self.db.execute('SELECT role,items FROM h').fetchall(),
                         [('validation', '["99"]')])
        with self.assertRaises(sqlite3.OperationalError):
            sql.build_index(self.db)

    def test_reopened_readonly_main_allows_temp_queries_without_changing_sealed_bytes(self):
        root = Path(__file__).resolve().parents[1]
        private = root / 'shop-mysql-runtime' / 'verification'
        private.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='knn-sql-v2-', dir=private) as folder:
            path = Path(folder) / 'oracle.sqlite'
            writer = sqlite3.connect(path)
            try:
                writer.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
                writer.executemany('INSERT INTO m VALUES(?,?,?)',
                                   [('1', 10, '1'), ('1', 10, '2')])
                sql.build_index(writer)
                writer.commit()
            finally:
                writer.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            before_mtime = path.stat().st_mtime_ns
            reader = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            try:
                prepared = sql.prepare_catalog({'1': 1, '2': 1, '3': 1}, {'1': 1, '2': 1})
                actual = sql.predict(reader, {'1': 1, '2': 1}, 'fit', prepared.counts,
                                     prepared, 110, ('1',), ('90', 100))
                expected = v1.predict({('1', 10): {'1', '2'}}, {'1': 1, '2': 1},
                                      'fit', prepared.counts, prepared.first, 110,
                                      ('1',), ('90', 100), lambda: None)
                self.assertEqual(actual, expected)
                sql.predict(reader, {'1': 1, '2': 1}, 'fit', prepared.counts,
                            prepared, 110, ('99',), ('90', 100))
                reader.commit()
                with self.assertRaises(sqlite3.OperationalError):
                    reader.execute('DELETE FROM main.m')
            finally:
                reader.close()
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertEqual(path.stat().st_mtime_ns, before_mtime)

    def test_missing_and_stale_size_rows_fail_instead_of_silently_dropping_neighbors(self):
        for mutation in ('missing', 'too_small', 'too_large'):
            with self.subTest(mutation=mutation):
                self.fixture({('1', 10): {'1', '2'}})
                if mutation == 'missing':
                    self.db.execute('DELETE FROM k1_v2_sizes')
                else:
                    self.db.execute('UPDATE k1_v2_sizes SET n=?', (1 if mutation == 'too_small' else 3,))
                with self.assertRaises(ValueError):
                    self.check_prediction(history=('1', '2'))

    def test_watch_failure_deep_in_vote_loop_propagates_and_does_not_claim_result(self):
        self.fixture({('1', 10): {str(item) for item in range(1, 21)}})
        work = {}
        class StopReadback(RuntimeError):
            pass
        def watch():
            if work.get('sql_vote_membership_rows_returned', 0) >= 4:
                raise StopReadback('synthetic deadline during nested vote rows')
        with self.assertRaisesRegex(StopReadback, 'nested vote rows'):
            self.check_prediction(history=('1',), workload=work, watch=watch)
        self.assertEqual(work['sql_vote_membership_rows_returned'], 4)
        self.assertNotIn('complete_independent_acceptance', work)
        self.check_prediction(history=('1',))

    def test_sql_vm_interrupt_is_not_swallowed(self):
        self.fixture({('1', 10): {'1', '2'}})
        self.db.set_progress_handler(lambda: 1, 1)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.check_prediction()
        finally:
            self.db.set_progress_handler(None, 0)
        self.check_prediction()

    def test_watch_runs_during_prepare_index_and_empty_overlap_queries(self):
        calls = []
        self.fixture({}, catalog={str(item): 1 for item in range(1, 31)})
        sql.prepare_catalog(self.catalog, self.counts, lambda: calls.append('prepare'))
        self.assertGreaterEqual(len(calls), 31)
        calls.clear()
        self.check_prediction(history=('999',), watch=lambda: calls.append('query'))
        self.assertGreater(len(calls), 10)

    def test_fixed_random_complete_nested_differential(self):
        rng = random.Random(20261103)
        for case in range(20):
            sessions = {(str(visitor), 10 + visitor % 3):
                        set(rng.sample([str(item) for item in range(1, 13)], rng.randint(1, 6)))
                        for visitor in range(1, rng.randint(2, 28))}
            counts = {str(item): rng.randint(1, 100) for item in range(1, 16)}
            catalog = {str(item): rng.choice((1, 109, 110, 111)) for item in range(1, 19)}
            self.fixture(sessions, counts=counts, catalog=catalog)
            for query in range(5):
                history = rng.sample([str(item) for item in range(1, 22)], rng.randint(0, 6))
                current = rng.choice(list(sessions)) if query % 2 else ('90', 100)
                with self.subTest(case=case, query=query):
                    self.check_prediction(history=history, current=current)

    def test_independent_module_has_no_production_or_v1_imports(self):
        tree = ast.parse(inspect.getsource(sql))
        roots = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.extend(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.append(node.module.split('.')[0])
        self.assertEqual(set(roots), {'bisect', 'collections', 'dataclasses', 'fractions',
                                     'hashlib', 'json', 're', 'types'})

    def test_catalog_invalid_identifiers_and_noninteger_clocks_fail(self):
        for catalog, counts in [({'01': 1}, {}), ({'1': 1.0}, {}),
                                ({'1': 1}, {'1': -1}), ({'1': 1}, {'1': True})]:
            with self.subTest(catalog=catalog, counts=counts), self.assertRaises(ValueError):
                sql.prepare_catalog(catalog, counts)


if __name__ == '__main__':
    unittest.main()
