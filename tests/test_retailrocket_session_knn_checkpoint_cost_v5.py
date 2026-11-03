"""Small deterministic checkpoints; budget publication still performs real I/O."""
from copy import deepcopy
from itertools import count
from pathlib import Path
import tempfile
from time import perf_counter
from unittest.mock import patch
import unittest
from uuid import UUID

from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts.retailrocket_session_knn_checkpoint_cost_v5 import BudgetTimedStore
from scripts.retailrocket_session_knn_pair_v4 import TimedStore
from tests.test_retailrocket_session_knn_checkpoint_v2 import FakeClock, FakeProcesses


class BudgetObserverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def make_store(self, cls, folder, clock):
        return cls.create(folder, {'kind': 'unit_fixture'}, 1100.0, 90.0, expected_queries=4,
                          required_stages=('reconstruction', 'queries'), chunk_queries=2,
                          chunk_seconds=120, clock=clock, process_api=FakeProcesses())

    def execute(self, cls, name):
        # The two runs have identical run ID, chunk filenames, wall clocks and
        # artificial input. Thus actual manifest bytes, not normalized dicts,
        # must be identical as well as the concatenated ledger payload bytes.
        serial = count(1)
        clock = FakeClock()
        rows = []
        with patch.object(checkpoint.uuid, 'uuid4', side_effect=lambda: UUID(int=next(serial))):
            store = self.make_store(cls, self.root/name, clock)
            with store.writer():
                store.seal_stage('reconstruction', {'fixture': True})
                for ordinal, advance in enumerate((.4, .7, .3, 1.0)):
                    clock.advance(advance)
                    started = perf_counter()
                    prior_commit = store.commit_seconds
                    store.append_verified(ordinal, ['1', 0, ordinal], {'a': ['synthetic', ordinal]})
                    append_seconds = perf_counter()-started
                    commit = store.commit_seconds-prior_commit
                    rows.append({'subset_ordinal': ordinal, 'verification_seconds': .1,
                                 'checkpoint_append_seconds': append_seconds, 'chunk_commit_seconds': commit,
                                 'append_without_commit_seconds': max(0, append_seconds-commit)})
                store.flush_chunk()  # empty flush still forces a budget write
                store.seal_stage('queries', {'queries': 4})
                self.assertEqual(store.recover()['records'], 4)
        return store, {'committed_prefix_rows': 0, 'verified_subset_queries': 4, 'queries': rows,
                       'chunk_commits': list(store.commit_events)}

    def test_observer_preserves_actual_ledger_and_manifest_bytes(self):
        baseline, _ = self.execute(TimedStore, 'baseline')
        observed, _ = self.execute(BudgetTimedStore, 'observed')
        for name in ('chunks', 'payloads', 'stages'):
            self.assertEqual({p.name: p.read_bytes() for p in (baseline.folder/name).iterdir()},
                             {p.name: p.read_bytes() for p in (observed.folder/name).iterdir()}, name)
        for name in ('run.json', 'latest.json', 'budget.json'):
            self.assertEqual((baseline.folder/name).read_bytes(), (observed.folder/name).read_bytes())

    def test_exclusive_nested_contexts_and_original_cost_conservation(self):
        store, measured = self.execute(BudgetTimedStore, 'costs')
        original = deepcopy(measured)
        summary = store.budget_cost_summary(measured)
        self.assertEqual(measured, original)
        self.assertEqual(summary['writes'], len(store.budget_events))
        self.assertEqual({name: bucket['writes'] for name, bucket in summary['by_context'].items()},
                         {'store_setup': 1, 'writer_setup': 1, 'stage': 4, 'query_append': 2,
                          'chunk_commit': 4, 'empty_flush': 1})
        self.assertEqual([e['subset_ordinal'] for e in store.budget_events if e['context'] == 'query_append'], [1, 3])
        self.assertEqual([e['subset_ordinal'] for e in store.budget_events if e['context'] == 'chunk_commit'], [1, 1, 3, 3])
        self.assertEqual([e['stage'] for e in store.budget_events if e['context'] == 'stage'],
                         ['reconstruction', 'reconstruction', 'queries', 'queries'])
        self.assertAlmostEqual(sum(s['seconds'] for s in summary['by_context'].values()), summary['budget_seconds'])
        self.assertGreater(summary['query_append_budget_seconds'], 0)
        for raw, row in zip(measured['queries'], summary['rows']):
            self.assertEqual(row['query_append_budget_writes'], int(row['subset_ordinal'] in (1, 3)))
            self.assertAlmostEqual(raw['append_without_commit_seconds'],
                                   row['append_without_commit_or_budget_seconds']+row['query_append_budget_seconds'])
            self.assertAlmostEqual(raw['checkpoint_append_seconds'], row['append_without_commit_or_budget_seconds']
                                   +row['query_append_budget_seconds']+row['chunk_commit_seconds'])

    def test_deadline_and_failures_remain_enforced(self):
        clock = FakeClock()
        store = self.make_store(BudgetTimedStore, self.root/'expired', clock)
        with self.assertRaises(checkpoint.BudgetExceeded):
            with store.writer():
                store.seal_stage('reconstruction', {'fixture': True})
                clock.advance(90)
                store.append_verified(0, ['1', 0, 0], {})
        self.assertEqual(store.recover()['records'], 0)
        self.assertTrue((store.folder/'stop_requested.json').exists())
        self.assertEqual(store.budget_events[-1]['context'], 'query_append')
        # The budget publication itself succeeded, even though the outer
        # append was refused. No completion report can be made for this run.
        self.assertTrue(store.budget_events[-1]['completed'])

    def test_failed_atomic_publication_is_observed_and_propagated(self):
        clock = FakeClock()
        store = self.make_store(BudgetTimedStore, self.root/'failed', clock)
        with store.writer():
            store.seal_stage('reconstruction', {'fixture': True})
            clock.advance(1.1)
            atomic = checkpoint.CheckpointStore._atomic
            def fail_budget(obj, name, value, replace=False):
                if name == 'budget.json':
                    raise OSError('synthetic write refusal')
                return atomic(obj, name, value, replace=replace)
            with patch.object(checkpoint.CheckpointStore, '_atomic', new=fail_budget):
                with self.assertRaisesRegex(OSError, 'write refusal'):
                    store.append_verified(0, ['1', 0, 0], {})
        self.assertEqual(store.recover()['records'], 0)
        self.assertFalse(store.budget_events[-1]['completed'])
        self.assertEqual(store.budget_events[-1]['subset_ordinal'], 0)

    def test_rejects_inconsistent_measurements_without_clamping_cost(self):
        store, measured = self.execute(BudgetTimedStore, 'validation')
        measured['queries'][1]['append_without_commit_seconds'] = 0.0
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            store.budget_cost_summary(measured)
        measured['chunk_commits'] = []
        with self.assertRaisesRegex(ValueError, 'commit events'):
            store.budget_cost_summary(measured)


if __name__ == '__main__':
    unittest.main()
