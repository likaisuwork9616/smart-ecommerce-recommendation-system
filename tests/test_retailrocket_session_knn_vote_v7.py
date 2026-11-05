"""Exact V4 vote-method differential, profiling accounting and crash boundaries."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_sql_v4 as native
from scripts import retailrocket_session_knn_vote_v7 as vote
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from tests import test_retailrocket_session_knn_sql_v4 as ranking_fixture
from tests.test_retailrocket_session_knn_pair_v4 import fixture as paired_fixture


MODES = ('profile', *vote.CANDIDATES)


class VoteTests(unittest.TestCase):
    fixture = ranking_fixture.ExactRankingTests.fixture

    def check_modes(self, history, at=100, current=('1', 999)):
        args = (self.db, self.support, 'fixture', self.prepared.counts, self.prepared, at, history, current)
        original_work, original_times = {}, {}
        expected = native.predict(*args, workload=original_work, timings=original_times)
        for mode in MODES:
            with self.subTest(mode=mode):
                events = [] if mode == 'profile' else None
                work, timings = {}, {}
                result = vote.make_predictor(mode, events)(*args, workload=work, timings=timings)
                self.assertEqual(cp.encoded(result), cp.encoded(expected))
                self.assertEqual(work, original_work)
                self.assertEqual(timings.keys(), original_times.keys())
                if events is not None:
                    event, = events
                    self.assertEqual(set(event['parts_seconds']), set(vote.PARTS))
                    self.assertEqual(event['outer_seconds'], timings['sql_selected_votes_and_accumulation'])
                    self.assertAlmostEqual(event['outer_seconds'], math.fsum(event['parts_seconds'].values()), places=12)
                    self.assertTrue(all(x >= 0 for x in event['parts_seconds'].values()))
                    self.assertEqual(event['membership_rows'], work['sql_vote_membership_rows_returned'])
                    self.assertEqual(event['fetch_batches'], math.ceil(event['membership_rows']/128))
                    self.assertEqual(event['selected_rows'], work['sql_selected_rows_inserted'])
                    self.assertEqual(event['additions'], work['exact_vote_additions'])
                    self.assertEqual(event['fallback'], work['fraction_fallback'])
        return expected, original_work

    def test_causal_boundary_self_exclusion_multiple_batches_and_zero_fill(self):
        self.fixture({(str(i), 0): {'1', '2', '3', '4'} for i in range(180)},
                     catalog={'1': 5, '2': 100, '3': 110, '4': 3, '5': 0})
        result, work = self.check_modes(['1', '1', '999'], current=('1', 0))
        self.assertEqual(result['current_session_excluded'], 1)
        self.assertEqual(result['ids'], ['1', '4', '5'])
        self.assertEqual(work['sql_vote_membership_rows_returned'], 179*4)
        self.assertEqual(work['exact_vote_additions'], 179*2)

    def test_zero_neighbor_no_causal_catalog_and_only_self(self):
        self.fixture({('7', 0): {'1'}}, catalog={'1': 100, '2': 110})
        for history, current, expected in (([], ('7', 0), 'no_supported_seed'),
                                           (['1'], ('7', 0), 'only_self_session_overlap'),
                                           (['1'], ('8', 0), 'no_positive_causal_vote')):
            result, _ = self.check_modes(history, current=current)
            self.assertEqual(result['fallback_reason'], expected)

    def test_499_500_501_full_pool_and_equal_similarity_boundary(self):
        for n in (499, 500, 501):
            with self.subTest(n=n):
                self.fixture({(str(10**25+i), 0): {'1', '2'} for i in reversed(range(n))})
                result, work = self.check_modes(['1'])
                self.assertEqual(work['neighbor_pool_rows_hashed'], n)
                self.assertEqual(result['boundary_ties_excluded'], max(0, n-500))
                self.assertEqual(len(result['selected_neighbors']), min(n, 500))

    def test_unbounded_integer_weight_and_forced_fraction_fallback(self):
        primes = (2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61)
        self.fixture({(str(n), 0): {str(i) for i in range(1, n+1)} for n in primes})
        integer_result, work = self.check_modes(['1'])
        self.assertGreater(work['vote_scale_bits'], 64)
        self.assertEqual(work['fraction_vote_additions'], 0)
        with patch.object(native, 'MAX_VOTE_SCALE_BITS', 3):
            fraction_result, work = self.check_modes(['1'])
        self.assertTrue(work['fraction_fallback'])
        self.assertGreater(work['fraction_vote_additions'], 0)
        self.assertEqual(integer_result, fraction_result)

    def test_membership_check_rejects_stale_selected_size(self):
        self.fixture({('1', 0): {'1','2'}})
        self.db.execute('UPDATE k1_v2_sizes SET n=3')
        for mode in MODES:
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'Selected membership rows differ'):
                events = [] if mode == 'profile' else None
                vote.make_predictor(mode, events)(self.db, self.support, 'fixture', self.prepared.counts,
                                                  self.prepared, 100, ['1'], ('1', 999))

    def test_each_membership_retains_watch_and_stopped_temp_tail_is_discarded(self):
        self.fixture({(str(i), 0): {'1', str(i+3)} for i in range(150)})
        args = self.db, self.support, 'fixture', self.prepared.counts, self.prepared, 100, ['1'], ('1', 999)
        expected = native.predict(*args)
        for mode in MODES:
            with self.subTest(mode=mode):
                work = {}
                def watch():
                    if work.get('sql_vote_membership_rows_returned', 0) == 15:
                        raise TimeoutError('interrupted in vote')
                events = [] if mode == 'profile' else None
                predict = vote.make_predictor(mode, events)
                with self.assertRaisesRegex(TimeoutError, 'interrupted in vote'):
                    predict(*args, watch, workload=work)
                self.assertEqual(work['sql_vote_membership_rows_returned'], 15)
                if events is not None:
                    self.assertEqual(events, [])
                self.assertEqual(cp.encoded(predict(*args)), cp.encoded(expected))

    def test_selection_is_only_from_measured_exclusive_actionable_parts(self):
        def row(**fields):
            parts = dict.fromkeys(vote.PARTS, 0.)
            parts.update(fields)
            return {'outer_seconds': sum(parts.values()), 'parts_seconds': parts}
        self.assertEqual(vote.choose_candidate([row(temp_insert=4, cursor_execute=1, cursor_fetch=2)]), 'batch_insert')
        self.assertEqual(vote.choose_candidate([row(temp_insert=4, cursor_execute=2, cursor_fetch=3)]), 'batch_fetch')
        self.assertEqual(vote.choose_candidate([row(accumulate=2, check=3), row(cursor_fetch=4)]), 'rank_counts')
        self.assertEqual(vote.choose_candidate([row(weights=10, other=100, temp_insert=1, accumulate=1)]), 'batch_insert')
        invalid = row(temp_insert=1)
        invalid['outer_seconds'] = 2
        for rows in ([], [invalid], [row(other=1)], [row(accumulate=-1)], [row(cursor_fetch=float('nan'))]):
            with self.assertRaises(ValueError):
                vote.choose_candidate(rows)
        with self.assertRaises(ValueError):
            vote.make_predictor('profile')
        with self.assertRaises(ValueError):
            vote.make_predictor('rank_counts', [])


class PairedVoteTests(unittest.TestCase):
    def setUp(self):
        (self.root, self.paths, self.config, self.primary, _, self.db, self.model,
         self.ordinals, self.binding) = paired_fixture()

    def create(self, name):
        return DetailedTimedStore.create(self.root/name, self.binding,
                (datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(), 900,
                source_root=self.root, expected_queries=len(self.ordinals),
                required_stages=('reconstruction','queries'), chunk_queries=2)

    def run_store(self, store, mode):
        events = [] if mode == 'profile' else None
        verifier = vote.make_verifier(mode, events)
        with store.writer():
            if store.get_stage('reconstruction') is None:
                store.seal_stage('reconstruction', {'fixture': True, 'fit_audit': self.model['fit_audit']})
            measured = verifier(self.primary, self.paths, self.config, store, self.model, self.db, self.ordinals)
        if events is not None:
            self.assertEqual(len(events), len(measured['queries']))
        return measured

    def test_all_four_arm_payload_bytes_and_local_verifier_isolation(self):
        self.assertIs(vote.make_verifier('baseline'), pair.verify_selected)
        original_predict = native.predict
        reference = self.create('reference')
        self.run_store(reference, 'baseline')
        expected = [cp.encoded(r) for r in reference.iter_records()]
        for mode in MODES:
            with self.subTest(mode=mode):
                store = self.create(mode)
                measured = self.run_store(store, mode)
                store.detailed_cost_summary(measured)
                self.assertEqual([cp.encoded(r) for r in store.iter_records()], expected)
                self.assertIs(pair.sql.predict, original_predict)

    def test_real_process_interruption_and_half_write_recover_identical_bytes(self):
        reference = self.create('reference')
        self.run_store(reference, 'baseline')
        expected = [cp.encoded(r) for r in reference.iter_records()]
        request = self.root/'vote_recovery_fixture.json'
        request.write_text(json.dumps({'paths': {k:str(v) for k,v in self.paths.items()}, 'root':str(self.root),
            'config':self.config, 'primary':str(self.primary), 'database':str(self.db), 'binding':self.binding,
            'model':self.model, 'ordinals':self.ordinals}), encoding='utf-8')
        worker = """
import json, os, sys
from pathlib import Path
from scripts.retailrocket_session_knn_vote_v7 import make_verifier
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
r=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
def fault(point):
    if point == sys.argv[3] and store._summary['records'] == 2:
        os._exit(9)
store=DetailedTimedStore.open(sys.argv[2],r['binding'],source_root=r['root'],fault=fault)
with store.writer():
    store.seal_stage('reconstruction',{'fixture':True,'fit_audit':r['model']['fit_audit']})
    make_verifier(sys.argv[4])(Path(r['primary']),{k:Path(v) for k,v in r['paths'].items()},
        r['config'],store,r['model'],Path(r['database']),r['ordinals'],fault=fault)
"""
        for mode in vote.CANDIDATES:
            for point in ('query_work','payload_half_written'):
                with self.subTest(mode=mode, point=point):
                    store = self.create(mode+'_'+point)
                    original_run = (store.folder/'run.json').read_bytes()
                    child = subprocess.run([sys.executable,'-B','-c',worker,str(request),str(store.folder),point,mode],
                        capture_output=True, text=True, timeout=90,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.assertEqual(child.returncode, 9, child.stderr)
                    reopened = DetailedTimedStore.open(store.folder, self.binding, source_root=self.root)
                    self.assertEqual(reopened.recover()['records'], 2)
                    measured = self.run_store(reopened, mode)
                    self.assertEqual(measured['committed_prefix_rows'], 2)
                    self.assertEqual([cp.encoded(r) for r in reopened.iter_records()], expected)
                    self.assertEqual(original_run, (reopened.folder/'run.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
