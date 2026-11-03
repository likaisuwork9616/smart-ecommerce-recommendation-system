"""Differential byte protocol, accounting, expiry and fault recovery guards."""
from copy import deepcopy
from itertools import count
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch
from uuid import UUID

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts.retailrocket_session_knn_checkpoint_cost_v5 import BudgetTimedStore
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from tests.test_retailrocket_session_knn_checkpoint_v2 import FakeClock, FakeProcesses
from tests.test_retailrocket_session_knn_pair_v4 import fixture


class DetailedCostTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def create(self, cls, name, **kwargs):
        return cls.create(self.root/name, {'kind': 'synthetic'}, 1100., 90.,
                          expected_queries=4, required_stages=('reconstruction', 'queries'),
                          chunk_queries=2, chunk_seconds=120, clock=FakeClock(),
                          process_api=FakeProcesses(), **kwargs)

    def execute(self, cls, name):
        serial = count(1); measured = []
        with patch.object(cp.uuid, 'uuid4', side_effect=lambda: UUID(int=next(serial))):
            store = self.create(cls, name)
            with store.writer():
                store.seal_stage('reconstruction', {'synthetic': True})
                for ordinal in range(4):
                    store.clock.advance(.6)
                    start = perf_counter(); prior = store.commit_seconds
                    store.append_verified(ordinal, ['1', 0, ordinal], {'a': [ordinal]*100})
                    seconds = perf_counter()-start; commit = store.commit_seconds-prior
                    measured.append({'subset_ordinal': ordinal, 'checkpoint_append_seconds': seconds,
                                     'append_without_commit_seconds': seconds-commit,
                                     'chunk_commit_seconds': commit, 'verification_seconds': .1, 'rank_seconds': .05})
                store.flush_chunk(); store.seal_stage('queries', {'queries': 4})
        return store, {'queries': measured, 'committed_prefix_rows': 0, 'verified_subset_queries': 4,
                       'chunk_commits': list(store.commit_events)}

    def test_actual_protocol_and_payload_bytes_identical_to_v5(self):
        baseline, _ = self.execute(BudgetTimedStore, 'v5')
        observed, _ = self.execute(DetailedTimedStore, 'v6')
        for name in ('chunks', 'payloads', 'stages'):
            self.assertEqual({p.name: p.read_bytes() for p in (baseline.folder/name).iterdir()},
                             {p.name: p.read_bytes() for p in (observed.folder/name).iterdir()}, name)
        for name in ('run.json', 'latest.json', 'budget.json'):
            self.assertEqual((baseline.folder/name).read_bytes(), (observed.folder/name).read_bytes())

    def test_all_append_cost_is_conserved_without_double_deduction(self):
        store, measured = self.execute(DetailedTimedStore, 'parts')
        original = deepcopy(measured); result = store.detailed_cost_summary(measured)
        self.assertEqual(original, measured)
        self.assertEqual(result['budget']['writes'], len(store.budget_events))
        for raw, part in zip(measured['queries'], result['rows']):
            self.assertAlmostEqual(sum(part['append_exclusive_seconds'].values()), raw['checkpoint_append_seconds'])
            self.assertEqual(part['verification_other_seconds'], .05)
            self.assertGreater(part['append_exclusive_seconds']['frame_encode'], 0)
            self.assertGreater(part['append_exclusive_seconds']['payload_write'], 0)
        self.assertEqual(sum(r['frame_bytes'] for r in result['rows']), sum(c['payload_bytes'] for c in store.commit_events))

    def test_deadline_and_rejected_append_are_retained(self):
        store = self.create(DetailedTimedStore, 'deadline')
        with self.assertRaises(cp.BudgetExceeded), store.writer():
            store.seal_stage('reconstruction', {})
            store.clock.advance(90)
            store.append_verified(0, ['1', 0, 0], {})
        self.assertEqual(store.recover()['records'], 0)
        self.assertFalse(store.append_events[-1]['completed'])
        self.assertTrue((store.folder/'stop_requested.json').exists())

    def test_fault_boundaries_recover_the_same_committed_payload(self):
        baseline, _ = self.execute(BudgetTimedStore, 'reference')
        expected = list(baseline.iter_records())
        for point in ('payload_half_written', 'after_payload_fsync', 'before_manifest_commit', 'after_manifest_commit'):
            with self.subTest(point=point):
                def fault(event):
                    if event == point:
                        raise OSError('synthetic interruption')
                store = self.create(DetailedTimedStore, point, fault=fault)
                with self.assertRaises(OSError), store.writer():
                    store.seal_stage('reconstruction', {'synthetic': True})
                    for ordinal in range(4):
                        store.append_verified(ordinal, ['1', 0, ordinal], {'a': [ordinal]*100})
                resumed = DetailedTimedStore.open(store.folder, {'kind': 'synthetic'},
                                                  clock=store.clock, process_api=FakeProcesses())
                with resumed.writer():
                    done = resumed.recover()['records']
                    for ordinal in range(done, 4):
                        resumed.append_verified(ordinal, ['1', 0, ordinal], {'a': [ordinal]*100})
                    resumed.flush_chunk(); resumed.seal_stage('queries', {'queries': 4})
                self.assertEqual(list(resumed.iter_records()), expected)

    def test_invalid_partition_is_rejected(self):
        store, measured = self.execute(DetailedTimedStore, 'invalid')
        store.append_events[0]['parts_seconds']['frame_encode'] = -1
        with self.assertRaisesRegex(ValueError, 'partition'):
            store.detailed_cost_summary(measured)

    def test_real_process_exit_then_reopen_keeps_original_prefix(self):
        folder = self.root/'real_crash'
        code = """
from datetime import datetime, timezone, timedelta
import os, sys
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
def fault(point):
    if point == 'payload_half_written' and store._summary['records'] == 2:
        os._exit(9)
store = DetailedTimedStore.create(sys.argv[1], {'kind':'process_fixture'},
    (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(), 300,
    expected_queries=4, required_stages=('reconstruction','queries'), chunk_queries=2, fault=fault)
with store.writer():
    store.seal_stage('reconstruction', {})
    for i in range(4):
        store.append_verified(i, ['1',0,i], {'a':[i]*100})
"""
        child = subprocess.run([sys.executable, '-B', '-c', code, str(folder)],
                               capture_output=True, text=True, timeout=30,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(child.returncode, 9, child.stderr)
        store = DetailedTimedStore.open(folder, {'kind': 'process_fixture'})
        before = (folder/'run.json').read_bytes()
        with store.writer():
            self.assertEqual(store.recover()['records'], 2)
            for i in range(2, 4):
                store.append_verified(i, ['1', 0, i], {'a': [i]*100})
            store.flush_chunk(); store.seal_stage('queries', {'queries': 4})
        self.assertEqual(before, (folder/'run.json').read_bytes())
        self.assertEqual([r['payload'] for r in store.iter_records()], [{'a': [i]*100} for i in range(4)])

    def test_four_arm_exact_verification_payload_matches_v5(self):
        root, paths, config, primary, _, database, model, ordinals, binding = fixture(boundary=True)
        from datetime import datetime, timezone, timedelta
        stores = []
        for cls in (BudgetTimedStore, DetailedTimedStore):
            store = cls.create(root/cls.__name__, binding,
                               (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(), 600,
                               source_root=root, expected_queries=len(ordinals),
                               required_stages=('reconstruction', 'queries'), chunk_queries=2)
            with store.writer():
                store.seal_stage('reconstruction', {'fit_audit': model['fit_audit']})
                measured = pair.verify_selected(primary, paths, config, store, model, database, ordinals)
            if cls is DetailedTimedStore:
                store.detailed_cost_summary(measured)
            stores.append(store)
        self.assertEqual([cp.encoded(r) for r in stores[0].iter_records()],
                         [cp.encoded(r) for r in stores[1].iter_records()])


if __name__ == '__main__':
    unittest.main()
