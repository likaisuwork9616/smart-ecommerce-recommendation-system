"""Small synthetic SQL checks for V20's observational lazy-cursor proxy."""
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_diagnostics_v20 as diagnostics
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_sql_v4 as native
from tests import test_retailrocket_session_knn_sql_v4 as fixtures


class _RecordingCursor:
    def __init__(self, cursor, owner):
        self.cursor, self.owner = cursor, owner
        self.calls = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.calls += 1
        self.owner.trace.append(('next', self.calls))
        if self.owner.failure == 'cursor' and self.calls == 2:
            raise self.owner.error
        try:
            row = next(self.cursor)
        except StopIteration:
            self.owner.trace.append(('eof', self.calls))
            raise
        self.owner.trace.append(('row', row))
        return row

    def fetchall(self):
        raise AssertionError('V20 must not materialize the overlap cursor')

    def fetchmany(self, *args):
        raise AssertionError('V20 must preserve per-row overlap iteration')


class _RecordingConnection:
    def __init__(self, connection, *, failure=None, error=None):
        self.connection, self.failure, self.error = connection, failure, error
        self.trace, self.statements, self.cursors = [], [], []

    def execute(self, sql, *args, **kwargs):
        self.statements.append((sql, args, kwargs))
        self.trace.append(('execute', sql, args, kwargs))
        if sql == diagnostics.OVERLAP_SQL and self.failure == 'execute':
            raise self.error
        cursor = self.connection.execute(sql, *args, **kwargs)
        if sql == diagnostics.OVERLAP_SQL:
            cursor = _RecordingCursor(cursor, self)
            self.cursors.append(cursor)
        return cursor


class SQLDiagnosticTests(unittest.TestCase):
    fixture = fixtures.ExactRankingTests.fixture

    def setUp(self):
        self.fixture({('7', 1): {'1', '88'}, ('7', 2): {'1'},
                      ('10', 1): {'1', '2'}, ('2', 1): {'1', '3', '4'}},
                     catalog={'1': 1, '2': 1, '3': 1, '4': 100, '8': 1, '9': 1},
                     counts={'9': 3, '8': 3})
        self.original_predict = native.predict
        self.original_sql = pair.sql

    def arguments(self, connection, history=('1', '999', '1')):
        return (connection, self.support, 'synthetic-v20', self.prepared.counts,
                self.prepared, 100, list(history), ('7', 1))

    def observed_call(self, predict, connection, history=('1', '999', '1'), *, fail_watch=None):
        work, timings = {}, {}
        def watch():
            connection.trace.append(('watch', work.get('sql_overlap_groups_returned', 0),
                                     work.get('sql_vote_membership_rows_returned', 0)))
            if fail_watch is not None and work.get('sql_overlap_groups_returned', 0) == 1:
                raise fail_watch
        result = predict(*self.arguments(connection, history), watch, workload=work, timings=timings)
        return result, work, timings

    def assert_untouched(self):
        self.assertIs(native.predict, self.original_predict)
        self.assertIs(pair.sql, self.original_sql)
        self.assertIs(pair.sql.predict, self.original_predict)
        self.assertIs(diagnostics.make_verifier('R'), pair.verify_selected)

    def test_exact_statement_full_prediction_workload_watch_and_empty_eof(self):
        for history in (('1', '999', '1'), (), ('999',)):
            with self.subTest(history=history):
                reference = _RecordingConnection(self.db)
                expected, original_work, original_times = self.observed_call(native.predict, reference, history)
                observed = _RecordingConnection(self.db)
                events = []
                cloned = []
                original_clone = diagnostics._clone
                def clone(function, **overrides):
                    result = original_clone(function, **overrides)
                    self.assertIs(result.__code__, function.__code__)
                    cloned.append(function)
                    return result
                with patch.object(diagnostics, '_clone', clone):
                    verifier = diagnostics.make_verifier('D', events)
                    self.assertIs(verifier.__code__, pair.verify_selected.__code__)
                    self.assertIsNot(verifier.__globals__['sql'], pair.sql)
                    predictor = verifier.__globals__['sql'].predict
                    actual, work, timings = self.observed_call(predictor, observed, history)
                self.assertIn(native.predict, cloned)
                self.assertIn(pair.verify_selected, cloned)
                self.assertEqual(checkpoint.encoded(actual), checkpoint.encoded(expected))
                self.assertEqual(work, original_work)
                self.assertEqual(set(timings), set(original_times))
                self.assertEqual(observed.statements, reference.statements)
                self.assertEqual(observed.trace, reference.trace)
                self.assertEqual(sum(sql == diagnostics.OVERLAP_SQL for sql, _, _ in observed.statements), 1)
                self.assertFalse(any('EXPLAIN' in sql or 'PRAGMA' in sql for sql, _, _ in observed.statements))
                event, = events
                self.assertTrue(event['completed'])
                self.assertEqual(event['execute_calls'], 1)
                self.assertEqual(event['eof_calls'], 1)
                self.assertEqual(event['fetch_calls'], work['sql_overlap_groups_returned']+1)
                self.assertEqual(event['returned_rows'], work['sql_overlap_groups_returned'])
                self.assertEqual(event['intersection_sum'], work['sql_overlap_membership_matches'])
                self.assertEqual(event['returned_rows'], actual['eligible_neighbors']+actual['current_session_excluded'])
                self.assertEqual(len(event['clock_samples']), 8)
                self.assertEqual(observed.cursors[0].calls, event['fetch_calls'])
                if history == ('1', '999', '1'):
                    self.assertEqual((actual['current_session_excluded'], actual['eligible_neighbors']), (1, 3))
                else:
                    self.assertEqual((event['returned_rows'], event['fetch_calls']), (0, 1))
                for metric in ('wall_ns', 'thread_cpu_ns'):
                    self.assertGreaterEqual(event['fetch'][metric], event['terminal_fetch'][metric])
                self.assert_untouched()

    def test_execute_cursor_and_watch_exceptions_preserved_without_global_mutation(self):
        expected = native.predict(*self.arguments(self.db))
        for failure in ('execute', 'cursor', 'watch'):
            with self.subTest(failure=failure):
                error = TimeoutError('synthetic '+failure+' interruption')
                reference = _RecordingConnection(self.db, failure=failure, error=error)
                with self.assertRaises(TimeoutError) as raised:
                    self.observed_call(native.predict, reference, fail_watch=error if failure == 'watch' else None)
                self.assertIs(raised.exception, error)
                observed = _RecordingConnection(self.db, failure=failure, error=error)
                events = []
                predictor = diagnostics.make_predictor(events)
                with self.assertRaises(TimeoutError) as raised:
                    self.observed_call(predictor, observed, fail_watch=error if failure == 'watch' else None)
                self.assertIs(raised.exception, error)
                self.assertEqual(observed.statements, reference.statements)
                self.assertEqual(observed.trace, reference.trace)
                self.assertEqual(len(events), 1)
                self.assertFalse(events[0]['completed'])
                self.assertEqual(events[0]['eof_calls'], 0)
                self.assert_untouched()
                # Synthetic follow-up verifies no leaked namespace/connection mutation;
                # a failed real experimental window is still withheld, never retried.
                subsequent = _RecordingConnection(self.db)
                actual, _, _ = self.observed_call(predictor, subsequent)
                self.assertEqual(checkpoint.encoded(actual), checkpoint.encoded(expected))
                self.assertTrue(events[-1]['completed'])
                self.assertEqual(checkpoint.encoded(native.predict(*self.arguments(self.db))), checkpoint.encoded(expected))
                self.assert_untouched()

    def test_lazy_original_next_including_terminal_fetch_and_signed_raw_clocks(self):
        rows = [('10', 1, 2, 4), ('20', 2, 1, 3)]
        class Cursor:
            def __init__(self):
                self.iterator = iter(rows)
                self.calls = 0
            def __iter__(self):
                return self
            def __next__(self):
                self.calls += 1
                return next(self.iterator)
            def fetchall(self):
                raise AssertionError('Unexpected prefetch')
            def fetchmany(self, *args):
                raise AssertionError('Unexpected batching')
        class Connection:
            def __init__(self):
                self.cursor, self.calls = Cursor(), []
            def execute(self, sql, *args, **kwargs):
                self.calls.append((sql, args, kwargs))
                return self.cursor
        connection = Connection()
        event = {'execute_calls': 0, 'fetch_calls': 0, 'eof_calls': 0,
                 'returned_rows': 0, 'intersection_sum': 0,
                 'execute': diagnostics._zero(), 'fetch': diagnostics._zero(), 'terminal_fetch': None}
        proxy = diagnostics._ConnectionProxy(connection, event)
        with patch.object(diagnostics, 'perf_counter_ns', side_effect=[100,300,1000,1200,2000,2200,3000,3100]), \
             patch.object(diagnostics, 'thread_time_ns', side_effect=[20,20,100,500,600,600,700,800]):
            cursor = proxy.execute(diagnostics.OVERLAP_SQL)
            self.assertEqual(connection.cursor.calls, 0)
            self.assertIs(iter(cursor), cursor)
            self.assertEqual(next(cursor), rows[0])
            self.assertEqual(connection.cursor.calls, 1)
            self.assertEqual(event['fetch']['wall_minus_thread_cpu_ns'], -200)
            self.assertEqual(next(cursor), rows[1])
            with self.assertRaises(StopIteration):
                next(cursor)
        self.assertEqual(event['execute'], {'wall_ns':200, 'thread_cpu_ns':0, 'wall_minus_thread_cpu_ns':200})
        self.assertEqual(event['fetch'], {'wall_ns':500, 'thread_cpu_ns':500, 'wall_minus_thread_cpu_ns':0})
        self.assertEqual(event['terminal_fetch'], {'wall_ns':100, 'thread_cpu_ns':100, 'wall_minus_thread_cpu_ns':0})
        self.assertEqual((event['fetch_calls'], event['eof_calls'], event['returned_rows'], event['intersection_sum']), (3,1,2,3))
        self.assertEqual(connection.calls, [(diagnostics.OVERLAP_SQL, (), {})])
        # Every other SQL call is delegated untouched and adds no overlap timer.
        self.assertIs(proxy.execute('SELECT ?', (7,)), connection.cursor)
        self.assertEqual(connection.calls[-1], ('SELECT ?', ((7,),), {}))
        self.assertEqual(event['execute_calls'], 1)


if __name__ == '__main__':
    unittest.main()
