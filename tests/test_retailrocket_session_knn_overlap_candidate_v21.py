"""Synthetic-only candidate semantics; no timings used as performance evidence."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts import retailrocket_session_knn_overlap_candidate_v21 as candidate
from scripts import retailrocket_session_knn_sql_v4 as original
from scripts import retailrocket_session_knn_readback as oracle
from tests import test_retailrocket_session_knn_sql_v4 as fixtures


class CandidateTests(unittest.TestCase):
    fixture = fixtures.ExactRankingTests.fixture
    test_hand_scores = fixtures.ExactRankingTests.test_hand_scores_unknown_self_other_session_future_and_zero_fill
    test_cutoff_ties = fixtures.ExactRankingTests.test_ties_with_different_raw_ratios_at_499_500_501_and_large_ids
    test_competing_cutoffs = fixtures.ExactRankingTests.test_competing_cutoff_groups_and_session_start_tie
    test_item_ties = fixtures.ExactRankingTests.test_high_scores_p0_then_arbitrary_precision_item_id_tie
    test_empty_unknown_self_and_causality = fixtures.ExactRankingTests.test_fallbacks_strict_causality_no_catalog_and_empty_history
    test_fraction_fallback = fixtures.ExactRankingTests.test_fallback_fraction_accumulation_matches_scaled_integers
    test_seeded_random_cases = fixtures.ExactRankingTests.test_randomized_three_way_full_nested_differential

    def check(self, history, current=('1', 999), at=100, support=None, read_db=None, prepared=True):
        support = self.support if support is None else support
        db = self.db if read_db is None else read_db
        catalog = self.prepared if prepared else self.catalog
        counts = self.prepared.counts if prepared else self.counts
        args = (support, 'synthetic', counts, catalog, at, history, current)
        work_r, work_c, times = {}, {}, {}
        expected = original.predict(db, *args, workload=work_r)
        statements = []
        db.set_trace_callback(statements.append)
        try:
            result = candidate.predict(db, *args, workload=work_c, timings=times)
        finally:
            db.set_trace_callback(None)
        reference = oracle.predict(self.sessions, support, 'synthetic', self.counts,
                                   self.catalog, at, history, current, lambda: None)
        self.assertEqual(result, expected)
        self.assertEqual(result, reference)
        self.assertEqual(work_c, work_r)
        self.assertEqual(statements.count(candidate.CANDIDATE_SQL), 1)
        self.assertNotIn(candidate.OVERLAP_SQL, statements)
        return result, work_c

    def test_missing_invalid_and_stale_sizes_still_rejected_including_self(self):
        for issue in ('missing_self', 'missing_neighbor', 'zero', 'negative', 'stale'):
            self.fixture({('1', 0): {'1', '2'}, ('2', 0): {'1', '2'}})
            if issue.startswith('missing'):
                self.db.execute('DELETE FROM k1_v2_sizes WHERE v=?', ('1' if issue == 'missing_self' else '2',))
            else:
                # Synthetic corruption deliberately bypasses the schema CHECK;
                # the production database is only opened read-only by assessment.
                self.db.execute('PRAGMA ignore_check_constraints=ON')
                self.db.execute('UPDATE k1_v2_sizes SET n=? WHERE v=?',
                                ({'zero': 0, 'negative': -1, 'stale': 1}[issue], '2'))
            errors = []
            for predict in (original.predict, candidate.predict):
                with self.assertRaises(ValueError) as caught:
                    predict(self.db, self.support, 'synthetic', self.prepared.counts, self.prepared,
                            100, ['1', '2'], ('1', 0))
                errors.append(str(caught.exception))
            self.assertEqual(errors[0], errors[1])

    def test_watch_failures_in_overlap_and_vote_keep_original_workload_and_retry(self):
        self.fixture({(str(i), 0): {'1', '2', str(i+10)} for i in range(30)})
        for counter in ('sql_overlap_groups_returned', 'sql_vote_membership_rows_returned'):
            works = []
            for predict in (original.predict, candidate.predict):
                work = {}
                def watch():
                    if work.get(counter, 0) >= 5:
                        raise TimeoutError('synthetic fixed interruption')
                with self.assertRaises(TimeoutError):
                    predict(self.db, self.support, 'synthetic', self.prepared.counts, self.prepared,
                            100, ['1', '2'], ('999', 0), watch, workload=work)
                works.append(work)
            self.assertEqual(works[0], works[1])
            self.check(['1', '2'])

    def test_read_only_bytes_and_plan_move_unique_size_lookup_after_aggregation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'synthetic.sqlite'
            self.fixture({('7', 1): {'1', '2', '9'}, ('2', 0): {'1', '2'}}, database=path)
            self.db.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
                db.execute('PRAGMA temp_store=MEMORY')
                self.check(['1', '2'], read_db=db)
                plans = [[row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql)]
                         for sql in (candidate.OVERLAP_SQL, candidate.CANDIDATE_SQL)]
                for plan in plans:
                    self.assertTrue(any('k1_v2_posting' in line for line in plan))
                    self.assertTrue(any('LEFT-JOIN' in line and 'sizes' in line for line in plan))
                self.assertTrue(any('CO-ROUTINE hits' in line for line in plans[1]))
                self.assertLess(next(i for i, line in enumerate(plans[1]) if 'GROUP BY' in line),
                                next(i for i, line in enumerate(plans[1]) if 'LEFT-JOIN' in line))
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])


if __name__ == '__main__':
    unittest.main()
