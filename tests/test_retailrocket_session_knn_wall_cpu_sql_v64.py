"""Synthetic SQLite and injected clocks only; trace proxies exist in tests only."""
from collections import Counter
import json
import sqlite3
import unittest

from scripts import retailrocket_session_knn_sql_v4 as native
from scripts.retailrocket_session_knn_wall_cpu_adapter_v64 import bind_predictor
from scripts.retailrocket_session_knn_wall_cpu_v63 import BoundaryRecorder


OVERLAP_SQL = (
    'SELECT membership.v,membership.s,COUNT(*),sizes.n '
    'FROM temp.k1_v4_history AS query '
    'CROSS JOIN main.m AS membership INDEXED BY k1_v2_posting '
    'ON membership.i=query.i '
    'LEFT JOIN main.k1_v2_sizes AS sizes '
    'ON sizes.v=membership.v AND sizes.s=membership.s '
    'GROUP BY membership.v,membership.s')
VOTE_SQL = (
    'SELECT chosen.r,membership.i FROM temp.k1_v4_selected AS chosen '
    'CROSS JOIN main.m AS membership '
    'ON membership.v=chosen.v AND membership.s=chosen.s')
PHASES = ('history_and_temp_setup', 'sql_positive_overlaps', 'neighbor_pool_sha',
          'exact_neighbor_selection', 'sql_selected_votes_and_accumulation',
          'top_ten_and_zero_fill', 'prediction_output')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


class FakeRankClock:
    """Every logical call has the same primary wall value in O and D."""
    def __init__(self, mode):
        self.mode, self.logical_calls, self.wall_calls, self.cpu_calls = mode, 0, 0, 0
        self.thread_calls = 0
        self.recorder = (BoundaryRecorder(recording_id='synthetic-sql', wall_clock=self.wall,
                         cpu_clock=self.cpu, thread_identity=self.thread) if mode == 'D' else None)

    def wall(self):
        index, half = divmod(self.wall_calls, 2)
        self.wall_calls += 1
        return 1_000_000 + 10_000*index + 3*half

    def cpu(self):
        value = 100_000 + 15_000*self.cpu_calls
        self.cpu_calls += 1
        return value

    def thread(self):
        self.thread_calls += 1
        return 7

    def __call__(self):
        index = self.logical_calls
        self.logical_calls += 1
        if self.mode == 'O':
            return (1_000_000 + 10_000*index) / 1e9
        return self.recorder.tap(f'ranking:{index}')


class TraceCursor:
    """A common O/D test observer; it never reads a clock or prefetches rows."""
    def __init__(self, cursor, owner, kind):
        self.cursor, self.owner, self.kind = cursor, owner, kind
        self.calls, self.rows, self.eof = 0, 0, 0

    def __iter__(self):
        self.owner.trace.append(('iter', self.kind))
        return self

    def __next__(self):
        self.calls += 1
        self.owner.trace.append(('next', self.kind, self.calls))
        if self.owner.failure == f'{self.kind}_next' and self.calls == 2:
            raise self.owner.error
        try:
            value = next(self.cursor)
        except StopIteration:
            self.eof += 1
            self.owner.trace.append(('eof', self.kind, self.calls))
            raise
        self.rows += 1
        self.owner.trace.append(('row', self.kind, value))
        return value

    def fetchall(self):
        raise AssertionError('The boundary adapter must not prefetch SQL rows')

    def fetchmany(self, *args):
        raise AssertionError('The boundary adapter must preserve lazy next calls')


class TraceConnection:
    def __init__(self, connection, *, failure=None, error=None):
        self.connection, self.failure, self.error = connection, failure, error
        self.trace, self.statements, self.cursors = [], [], {}

    def execute(self, statement, *args, **kwargs):
        self.statements.append((statement, args, kwargs))
        self.trace.append(('execute', statement, args, kwargs))
        kind = 'overlap' if statement == OVERLAP_SQL else 'vote' if statement == VOTE_SQL else None
        if kind is not None and self.failure == f'{kind}_execute':
            raise self.error
        cursor = self.connection.execute(statement, *args, **kwargs)
        if kind is not None:
            cursor = TraceCursor(cursor, self, kind)
            self.cursors[kind] = cursor
            # Creation itself must not consume a row.
            self.trace.append(('cursor_created', kind, cursor.calls))
        return cursor


class SQLBoundaryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.sessions = {('7', 1): {'1', '88'}, ('7', 2): {'1'},
                         ('10', 1): {'1', '2'}, ('2', 1): {'1', '3', '4'}}
        self.db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        self.db.executemany('INSERT INTO m VALUES(?,?,?)',
            ((visitor, session, item) for (visitor, session), members in self.sessions.items()
             for item in sorted(members, key=int)))
        native.build_index(self.db)
        self.db.commit()
        self.support = dict(Counter(item for items in self.sessions.values() for item in items))
        self.catalog = {'1': 1, '2': 1, '3': 1, '4': 100, '8': 1, '9': 1}
        self.counts = {'9': 3, '8': 3}
        self.prepared = native.prepare_catalog(self.catalog, self.counts)
        self.original_function = native.predict
        self.original_clock = native.predict.__globals__['perf_counter']
        self.original_globals = dict(native.predict.__globals__)

    def call(self, mode, *, history=('1', '999', '1'), failure=None, error=None,
             prepared=True, clock=None):
        connection = TraceConnection(self.db, failure=failure, error=error)
        clock = FakeRankClock(mode) if clock is None else clock
        predictor = bind_predictor(native.predict, clock)
        work, timings = {}, {}
        state = dict(connection=connection, clock=clock, predictor=predictor,
                     work=work, timings=timings)
        self.last_call = state

        def watch():
            overlap = work.get('sql_overlap_groups_returned', 0)
            votes = work.get('sql_vote_membership_rows_returned', 0)
            connection.trace.append(('watch', overlap, votes))
            if (failure == 'overlap_watch' and overlap == 1 and votes == 0
                    or failure == 'vote_watch' and votes == 1):
                raise error

        model = self.prepared if prepared else self.catalog
        counts = self.prepared.counts if prepared else self.counts
        state['result'] = predictor(connection, self.support, 'synthetic-v64', counts,
            model, 100, list(history), ('7', 1), watch, workload=work, timings=timings)
        return state

    def assert_original_unchanged(self):
        self.assertIs(native.predict, self.original_function)
        self.assertIs(native.predict.__globals__['perf_counter'], self.original_clock)
        self.assertEqual(native.predict.__globals__.keys(), self.original_globals.keys())
        for key, value in self.original_globals.items():
            self.assertIs(native.predict.__globals__[key], value, key)

    def assert_same_behavior(self, original, diagnostic):
        self.assertEqual(encoded(diagnostic['result']), encoded(original['result']))
        self.assertEqual(diagnostic['work'], original['work'])
        self.assertEqual(diagnostic['timings'], original['timings'])
        self.assertEqual(diagnostic['connection'].statements, original['connection'].statements)
        self.assertEqual(diagnostic['connection'].trace, original['connection'].trace)
        self.assertEqual(tuple(diagnostic['timings']), PHASES)
        self.assertEqual(diagnostic['clock'].logical_calls, 8)
        self.assertEqual(diagnostic['clock'].wall_calls, 16)
        self.assertEqual(diagnostic['clock'].cpu_calls, 8)
        self.assertEqual(diagnostic['clock'].thread_calls, 16)
        self.assertEqual(len(diagnostic['clock'].recorder.boundaries), 8)
        self.assertEqual(original['clock'].logical_calls, 8)
        self.assertEqual((original['clock'].wall_calls, original['clock'].cpu_calls,
                          original['clock'].thread_calls), (0, 0, 0))
        self.assertIsNone(original['clock'].recorder)
        self.assert_original_unchanged()

    def test_complete_prediction_bytes_workload_and_all_seven_timings_match(self):
        original, diagnostic = self.call('O'), self.call('D')
        self.assert_same_behavior(original, diagnostic)
        row = diagnostic['result']
        self.assertEqual(row['ids'], ['1', '2', '3', '8', '9'])
        self.assertEqual(row['scores'], [[13, 12], [1, 3], [1, 4], [0, 1], [0, 1]])
        self.assertEqual((row['current_session_excluded'], row['eligible_neighbors']), (1, 3))
        self.assertEqual(row['selected_neighbors'][0]['key'], ['7', 2])
        self.assertEqual((diagnostic['work']['integer_vote_additions'],
                          diagnostic['work']['fraction_vote_additions']), (5, 0))

    def test_exact_statements_parameters_and_no_additional_probe_sql(self):
        original, diagnostic = self.call('O'), self.call('D')
        self.assert_same_behavior(original, diagnostic)
        statements = diagnostic['connection'].statements
        self.assertEqual(sum(sql == OVERLAP_SQL for sql, _, _ in statements), 1)
        self.assertEqual(sum(sql == VOTE_SQL for sql, _, _ in statements), 1)
        history = [args for sql, args, _ in statements if sql.startswith('INSERT INTO temp.k1_v4_history')]
        self.assertEqual(history, [(('1',),), (('999',),)])
        selected = [args for sql, args, _ in statements if sql.startswith('INSERT INTO temp.k1_v4_selected')]
        self.assertEqual(selected, [(('7', 2, 0),), (('10', 1, 1),), (('2', 1, 2),)])
        self.assertFalse(any('EXPLAIN' in sql or 'PRAGMA' in sql for sql, _, _ in statements))
        self.assertTrue(all(kwargs == {} for _, _, kwargs in statements))

    def test_lazy_overlap_and_vote_each_keep_per_row_next_and_terminal_eof(self):
        original, diagnostic = self.call('O'), self.call('D')
        self.assert_same_behavior(original, diagnostic)
        for kind, work_key in (('overlap', 'sql_overlap_groups_returned'),
                               ('vote', 'sql_vote_membership_rows_returned')):
            cursor = diagnostic['connection'].cursors[kind]
            self.assertEqual(cursor.rows, diagnostic['work'][work_key])
            self.assertEqual(cursor.calls, cursor.rows+1)
            self.assertEqual(cursor.eof, 1)
            self.assertIn(('cursor_created', kind, 0), diagnostic['connection'].trace)
        # The raw memberships remain untouched by either arm's TEMP operations.
        actual = self.db.execute('SELECT v,s,i FROM m ORDER BY v,s,i').fetchall()
        expected = sorted((visitor, session, item) for (visitor, session), members in self.sessions.items()
                          for item in members)
        self.assertEqual(actual, expected)

    def test_empty_unknown_and_unprepared_catalog_keep_full_output_and_eof(self):
        for history, prepared in (((), True), (('999',), True), (('1', '999'), False)):
            with self.subTest(history=history, prepared=prepared):
                original = self.call('O', history=history, prepared=prepared)
                diagnostic = self.call('D', history=history, prepared=prepared)
                self.assert_same_behavior(original, diagnostic)
                for kind in ('overlap', 'vote'):
                    cursor = diagnostic['connection'].cursors[kind]
                    self.assertEqual(cursor.calls, cursor.rows+1)
                    self.assertEqual(cursor.eof, 1)
                if history in ((), ('999',)):
                    self.assertEqual(diagnostic['connection'].cursors['overlap'].calls, 1)
                    self.assertEqual(diagnostic['connection'].cursors['vote'].calls, 1)

    def test_execute_next_and_watch_faults_preserve_original_exception_and_prefix(self):
        for failure in ('overlap_execute', 'overlap_next', 'vote_execute', 'vote_next',
                        'overlap_watch', 'vote_watch'):
            with self.subTest(failure=failure):
                error = TimeoutError('synthetic '+failure)
                with self.assertRaises(TimeoutError) as caught:
                    self.call('O', failure=failure, error=error)
                self.assertIs(caught.exception, error)
                original = self.last_call
                with self.assertRaises(TimeoutError) as caught:
                    self.call('D', failure=failure, error=error)
                self.assertIs(caught.exception, error)
                diagnostic = self.last_call
                self.assertEqual(diagnostic['connection'].statements, original['connection'].statements)
                self.assertEqual(diagnostic['connection'].trace, original['connection'].trace)
                self.assertEqual(diagnostic['work'], original['work'])
                self.assertEqual(diagnostic['timings'], original['timings'])
                self.assertEqual(diagnostic['clock'].logical_calls, original['clock'].logical_calls)
                self.assertEqual(len(diagnostic['clock'].recorder.boundaries), diagnostic['clock'].logical_calls)
                self.assertLess(diagnostic['clock'].logical_calls, 8)
                self.assert_original_unchanged()

    def test_invocation_local_clone_keeps_code_and_independent_clock_namespaces(self):
        first, second = self.call('D'), self.call('D')
        self.assertIs(first['predictor'].__code__, native.predict.__code__)
        self.assertIs(second['predictor'].__code__, native.predict.__code__)
        self.assertIsNot(first['predictor'].__globals__, second['predictor'].__globals__)
        self.assertIs(first['predictor'].__globals__['perf_counter'], first['clock'])
        self.assertIs(second['predictor'].__globals__['perf_counter'], second['clock'])
        self.assertIsNot(first['clock'].recorder, second['clock'].recorder)
        self.assertEqual(encoded(first['result']), encoded(second['result']))
        self.assertEqual(first['connection'].trace, second['connection'].trace)
        self.assertEqual((first['clock'].logical_calls, second['clock'].logical_calls), (8, 8))
        self.assert_original_unchanged()


if __name__ == '__main__':
    unittest.main()
