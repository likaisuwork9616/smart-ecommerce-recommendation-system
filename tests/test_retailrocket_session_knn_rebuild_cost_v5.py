"""Synthetic independent reconstruction with seven direct files and no queries."""
from contextlib import closing
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback_v2 as v2
from scripts import retailrocket_session_knn_rebuild_cost_v5 as rebuild
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch


def lines(path, records):
    path.write_bytes(b''.join(cp.encoded(row) for row in records))


class RebuildTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'shop-mysql-runtime' / 'verification'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base, prefix='v5-rebuild-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.primary = self.root / 'original'
        self.paths = {'dataset': self.root / 'dataset', 'C1': self.root / 'C1'}
        for path in (self.primary, *self.paths.values()):
            path.mkdir()
        header = ['role', 'visitorid', 'session_start_ms', 'query_ms', 'basket_index', 'items']
        with (self.paths['dataset'] / 'baskets.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerows([header, ['warmup', '10', 0, 5, 1, '["90"]'],
                ['train', '10', 0, 20, 2, '["2","1"]'], ['train', '10', 0, 30, 3, '["2","3"]'],
                ['validation', '10', 0, 105, 4, '["91"]'], ['train', '2', 10, 40, 1, '["3"]'],
                ['reserved_test', 'opaque', 'opaque', 'opaque', 'opaque', 'invalid-json']])
        (self.paths['C1'] / 'support.csv').write_text('itemid,support\n1,1\n2,1\n3,2\n', encoding='utf-8')
        sessions = [{'key': ['2', 10], 'items': ['3']}, {'key': ['10', 0], 'items': ['1', '2', '3']}]
        lines(self.primary / 'sessions.jsonl', sessions)
        lines(self.primary / 'postings.jsonl', [
            {'itemid': '1', 'sessions': [['10', 0]], 'support': 1},
            {'itemid': '2', 'sessions': [['10', 0]], 'support': 1},
            {'itemid': '3', 'sessions': [['2', 10], ['10', 0]], 'support': 2}])
        lineage = [dict(sessions[1], baskets=2, basket_memberships=4),
                   dict(sessions[0], baskets=1, basket_memberships=1)]
        for path in (self.primary, self.paths['C1']):
            lines(path / 'train_sessions.jsonl', lineage)
        digest = hashlib.sha256(b'K1_Jaccard_exact_session_k500_v1\n10,100\n')
        digest.update(b'[["2",10],["3"]]\n[["10",0],["1","2","3"]]\n')
        counts = {'train_sessions': 2, 'singleton_sessions': 1, 'train_baskets': 3,
                  'basket_item_memberships': 5, 'distinct_session_item_memberships': 4,
                  'positive_support_items': 3, 'maximum_session_items': 3, 'maximum_posting_size': 2}
        (self.primary / 'fit_audit.json').write_bytes(cp.encoded(dict(counts, start_ms=10, end_ms=100,
                                                                      fit_id=digest.hexdigest())))
        self.config = {'schemas': {'baskets.csv': header}, 'train_window_ms': [10, 100],
            'role_windows_ms': {'warmup': [0, 10], 'train': [10, 100], 'validation': [100, 200]},
            'train_cost_audit': counts}
        self.files = [path for directory in (self.primary, *self.paths.values()) for path in directory.iterdir()]
        self.records = self.bind()
        self.folder = self.root / 'new'
        self.deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.watch = ThrottledWatch(self.root, self.deadline)

    def bind(self):
        return cp.bind_sources(self.root, [path.relative_to(self.root).as_posix() for path in self.files])

    def run_cost(self, folder=None, records=None):
        return rebuild.run_rebuild_cost(folder or self.folder, self.primary, self.paths, self.config,
                                        self.records if records is None else records, self.root, self.watch)

    def test_cost_path_matches_frozen_v2_complete_model_from_same_originals(self):
        self.assertIs(rebuild.sql.build_index, v2.sql.build_index)
        guard = {path: path.read_bytes() for path in self.files}
        store = cp.CheckpointStore.create(self.root / 'reference', {'sources': self.records},
            self.deadline, 300, source_root=self.root, required_stages=('reconstruction',))
        with store.writer():
            reference = v2.prepare_model(self.primary, self.paths, self.config, store, self.watch)
        result = self.run_cost()
        seal = cp.read(self.folder / 'reconstruction.json')
        self.assertEqual(reference, seal['receipt'])
        self.assertEqual(result['derived_index_counts'], {'train_sessions': 2, 'session_item_memberships': 4})
        self.assertEqual(seal['artifacts'], [cp.descriptor(self.folder, 'independent.sqlite')])
        self.assertEqual(result['reconstruction'], cp.descriptor(self.folder, 'reconstruction.json'))
        with closing(sqlite3.connect(self.folder / 'independent.sqlite')) as db, \
             closing(sqlite3.connect(store.folder / 'independent.sqlite')) as ref:
            for table, columns in [('h', 'v,s,t'), ('m', 'v,s,i'), ('k1_v2_sizes', 'v,s')]:
                statement = 'SELECT * FROM ' + table + ' ORDER BY ' + columns
                self.assertEqual(list(db.execute(statement)), list(ref.execute(statement)))
            self.assertEqual(list(db.execute('SELECT DISTINCT role FROM h ORDER BY role')),
                             [('train',), ('validation',), ('warmup',)])
        self.assertEqual(result['validation_queries_ranked'], 0)
        self.assertEqual(result['bootstrap_draws'], 0)
        self.assertEqual(result['reserved_test'], 'locked')
        self.assertEqual(result['direct_source_files_verified_each_pass'], 7)
        self.assertEqual(result['direct_source_bytes_verified_each_pass'], sum(len(data) for data in guard.values()))
        self.assertTrue(set(rebuild._BOUNDARIES.values()) <= set(result['phases']))
        self.assertTrue(all(phase['completed'] for phase in result['phases'].values()))
        self.assertEqual(cp.read(self.folder / 'rebuild_cost.json'), result)
        for path, original in guard.items():
            self.assertEqual(original, path.read_bytes())

    def test_missing_or_duplicate_original_binding_refused_before_build(self):
        for records in (self.records[:-1], self.records + self.records[:1]):
            with self.subTest(count=len(records)), self.assertRaises(ValueError):
                self.run_cost(records=records)
        self.assertFalse(self.folder.exists())

    def test_same_bytes_length_changed_before_start_refuses_input(self):
        support = self.paths['C1'] / 'support.csv'
        support.write_bytes(support.read_bytes().replace(b'1,1', b'1,2'))
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.run_cost()
        self.assertFalse((self.folder / 'independent.sqlite').exists())
        self.assertFalse(cp.read(self.folder / 'phases/initial_direct_source_hash_receipt.json')['completed'])

    def test_both_lineages_sessions_postings_support_and_audit_are_checked_against_model(self):
        for path in [self.primary / name for name in ('train_sessions.jsonl', 'sessions.jsonl',
                     'postings.jsonl', 'fit_audit.json')] + [self.paths['C1'] / name
                                                              for name in ('train_sessions.jsonl', 'support.csv')]:
            with self.subTest(file=path):
                before = path.read_bytes()
                if path.suffix == '.json':
                    wrong = json.loads(before)
                    wrong['fit_id'] = 'not-derived'
                    path.write_bytes(cp.encoded(wrong))
                elif path.suffix == '.csv':
                    path.write_bytes(before + b'4,1\n')
                else:
                    path.write_bytes(before + b'{}\n')
                run = self.root / (path.parent.name + '-' + path.name)
                with self.assertRaises(ValueError):
                    self.run_cost(folder=run, records=self.bind())
                self.assertTrue((run / 'failure.json').exists())
                self.assertFalse((run / 'reconstruction.json').exists())
                self.assertFalse((run / 'rebuild_cost.json').exists())
                path.write_bytes(before)

    def test_source_changed_during_build_refuses_seal(self):
        original = rebuild.sql.build_index
        def change(db, watch):
            result = original(db, watch)
            audit = self.primary / 'fit_audit.json'
            audit.write_bytes(audit.read_bytes() + b' ')
            return result
        with patch.object(rebuild.sql, 'build_index', side_effect=change), self.assertRaisesRegex(ValueError, 'identity changed'):
            self.run_cost()
        self.assertFalse(cp.read(self.folder / 'phases/final_direct_source_hash_receipt.json')['completed'])
        self.assertFalse((self.folder / 'reconstruction.json').exists())

    def test_interrupted_index_is_preserved_without_reentry_or_success(self):
        with patch.object(rebuild.sql, 'build_index', side_effect=TimeoutError('existing window')):
            with self.assertRaises(TimeoutError):
                self.run_cost()
        phase = cp.read(self.folder / 'phases/derived_posting_index_and_sizes_receipt.json')
        self.assertFalse(phase['completed'])
        self.assertTrue((self.folder / 'independent.sqlite').exists())
        self.assertFalse((self.folder / 'rebuild_cost.json').exists())
        with self.assertRaises(FileExistsError):
            self.run_cost()

    def test_existing_stop_and_unsafe_output_refused(self):
        (self.root / 'stop_request.json').touch()
        with self.assertRaises(TimeoutError):
            self.run_cost()
        self.assertFalse((self.folder / 'independent.sqlite').exists())
        for directory in (self.primary, *self.paths.values()):
            with self.subTest(directory=directory), self.assertRaisesRegex(ValueError, 'input namespace'):
                self.run_cost(folder=directory / 'nested')
            self.assertFalse((directory / 'nested').exists())
