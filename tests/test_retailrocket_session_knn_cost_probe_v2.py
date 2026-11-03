"""Synthetic-only tests for target-blind V2 cost selection and measurement."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_cost_probe_v2 as probe
from scripts import retailrocket_session_knn_sql_v2 as sql


HEADER = ['visitorid', 'session_start_ms', 'query_ms', 'basket_index', 'role',
          'target_items', 'target_count', 'candidate_count']


class CostProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE h(v TEXT,s INTEGER,t INTEGER,k INTEGER,role TEXT,items TEXT,n INTEGER,PRIMARY KEY(v,s,t))')
        self.db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        self.catalog = {'1': 0, '2': 0, '3': 25, '4': 50, '5': 75}
        self.config = {'validation_window_ms': [0, 100],
                       'fixed_validation': {'queries': 0}, 'schemas': {'queries.csv': HEADER}}

    def model(self, sessions):
        support = Counter()
        for (visitor, start), items in sessions.items():
            for item in items:
                self.db.execute('INSERT INTO m VALUES(?,?,?)', (visitor, start, item))
                support[item] += 1
        sql.build_index(self.db)
        return dict(support)

    def queries(self, specs, forbidden=True):
        rows = []
        for visitor, at, items in specs:
            self.db.execute('INSERT INTO h VALUES(?,?,?,?,?,?,?)',
                            (visitor, 0, at, 1, 'validation', json.dumps(items), len(items)))
            rows.append(dict(zip(HEADER, [visitor, '0', str(at), '1', 'validation',
                                         'INVALID TARGET JSON', 'NOT AN INTEGER', 'IGNORED'])))
        rows.sort(key=lambda row: (row['visitorid'], int(row['session_start_ms']), int(row['query_ms'])))
        if forbidden:
            rows.insert(0, dict(zip(HEADER, ['invalid visitor', 'bad start', 'bad time', 'bad index',
                                          'test', 'NONDECODABLE TEST TARGET', 'BAD', 'BAD'])))
        with (self.source/'queries.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(rows)
        self.config['fixed_validation']['queries'] = len(specs)
        return rows

    def run_stratify(self, support):
        return probe.stratify(self.db, self.source, self.config, support, self.catalog)

    def test_all_time_and_posting_bands_cover_full_population(self):
        sessions = {}
        cursor = 10000
        for item, count in [('10', 1), ('20', 101), ('30', 1001)]:
            for _ in range(count):
                sessions[(str(cursor), 0)] = {item}
                cursor += 1
        support = self.model(sessions)
        specs = []
        for time in range(4):
            for item in ('999', '10', '20', '30'):
                for offset in range(4):
                    specs.append((str(len(specs)+1), time*25+1+offset, [item]))
        self.queries(specs)
        population, selected = self.run_stratify(support)
        self.assertEqual(population['total_queries'], 64)
        self.assertEqual(len(population['cells']), 16)
        self.assertEqual(len(selected), 64)
        self.assertTrue(all(cell['count'] == cell['selected_count'] == 4
                            for cell in population['cells'].values()))
        self.assertEqual({row['posting_work'] for row in selected}, {0, 1, 101, 1001})
        self.assertEqual({row['time_band'] for row in selected}, {0, 1, 2, 3})
        self.assertEqual(len({tuple(row['key']) for row in selected}), 64)

    def test_four_distinct_extremes_are_kept_without_target_access(self):
        sessions = {(str(100+i), 0): {'1'} for i in range(20)}
        sessions[('200', 0)] = {'2', *(str(i) for i in range(101, 150))}
        sessions.update({('201', 0): {'3'}, ('202', 0): {'4'}, ('203', 0): {'5'}})
        support = self.model(sessions)
        self.catalog = {str(i): i for i in range(1, 25)}
        rows = self.queries([('1', 5, ['1']), ('2', 10, ['2']),
                            ('3', 15, ['3', '998', '999']), ('4', 24, ['4']), ('5', 20, ['5'])])

        class Guard(dict):
            def __getitem__(self, key):
                if key in ('target_items', 'target_count', 'candidate_count'):
                    raise AssertionError('Forbidden target or saved candidate read')
                return super().__getitem__(key)

        with patch.object(probe, 'read_rows', return_value=iter(map(Guard, rows))):
            population, selected = self.run_stratify(support)
        self.assertEqual({row['key'][0] for row in selected}, {'1', '2', '3', '4'})
        cell = population['cells']['time_0/posting_1-100']
        self.assertEqual(cell['count'], 5)
        self.assertEqual(cell['maxima'], {'posting_work': 20, 'vote_memberships_upper': 50,
                                          'history_size': 3, 'causal_candidates': 23})

    def test_hash_fill_is_fixed_and_not_source_prefix(self):
        support = self.model({('100', 0): {'1'}})
        self.queries([(str(i), 10, ['1']) for i in range(1, 10)])
        first = self.run_stratify(support)
        second = self.run_stratify(support)
        self.assertEqual(first, second)
        expected = sorted(([str(i), 0, 10] for i in range(1, 10)),
                          key=lambda key: hashlib.sha256(json.dumps(key, separators=(',', ':')).encode()).hexdigest())[:4]
        self.assertEqual([row['key'] for row in first[1]], expected)
        self.assertNotEqual({row['key'][0] for row in first[1]}, {'1', '2', '3', '4'})

    def test_upper_bound_uses_largest_500_and_excludes_only_self(self):
        sessions = {(str(100+i), 0): {'1', str(10000+i)} for i in range(501)}
        sessions[('100', 0)].update(str(i) for i in range(20000, 20008))
        sessions[('9999', 0)] = {'1', *(str(i) for i in range(30000, 30099))}
        sessions[('9999', 1)] = {'1', '40000', '40001'}
        support = self.model(sessions)
        self.queries([('9999', 10, ['1', '999999'])])
        _, selected = self.run_stratify(support)
        self.assertEqual(selected[0]['posting_work'], 503)
        self.assertEqual(selected[0]['eligible_neighbors'], 502)
        self.assertEqual(selected[0]['current_session_excluded'], 1)
        self.assertEqual(selected[0]['vote_memberships_upper'], 1009)
        self.assertEqual(selected[0]['history_size'], 2)

    def test_causal_count_is_strict_and_not_saved_candidate_field(self):
        support = self.model({('100', 0): {'1'}})
        self.catalog = {'1': 9, '2': 10, '3': 11}
        self.queries([('1', 10, ['1'])])
        _, selected = self.run_stratify(support)
        self.assertEqual(selected[0]['causal_candidates'], 1)

    def test_time_band_boundaries_and_independent_history_prefix(self):
        support = self.model({('100', 0): {'1', '2'}})
        self.queries([('1', 0, ['1']), ('2', 25, ['1']),
                      ('3', 50, ['1']), ('4', 75, ['1'])])
        self.db.execute('INSERT INTO h VALUES(?,?,?,?,?,?,?)',
                        ('4', 0, 74, 0, 'train', '["2","999"]', 2))
        self.db.execute('INSERT INTO h VALUES(?,?,?,?,?,?,?)',
                        ('4', 0, 76, 2, 'validation', '["888"]', 1))
        _, selected = self.run_stratify(support)
        by_visitor = {row['key'][0]: row for row in selected}
        self.assertEqual([by_visitor[str(i)]['time_band'] for i in range(1, 5)], [0, 1, 2, 3])
        self.assertEqual(by_visitor['4']['history_size'], 3)
        self.assertEqual(by_visitor['4']['posting_work'], 2)
        self.assertEqual(by_visitor['4']['history_sha256'], probe._sha(['1', '2', '999']))

    def test_full_population_required_and_default_is_166897(self):
        support = self.model({('100', 0): {'1'}})
        self.queries([('1', 10, ['1'])])
        self.config['fixed_validation']['queries'] = 2
        with self.assertRaisesRegex(ValueError, 'incomplete validation population'):
            self.run_stratify(support)
        del self.config['fixed_validation']
        with self.assertRaisesRegex(ValueError, '166897'):
            self.run_stratify(support)

    def test_support_mismatch_fails_before_selecting_probes(self):
        self.model({('100', 0): {'1'}})
        self.queries([('1', 10, ['1'])])
        with self.assertRaisesRegex(ValueError, 'support differs'):
            self.run_stratify({'1': 2})

    def test_current_basket_identity_and_forbidden_history_fail(self):
        support = self.model({('100', 0): {'1'}})
        self.queries([('1', 10, ['1'])])
        self.db.execute('UPDATE h SET k=2')
        with self.assertRaisesRegex(ValueError, 'basket index'):
            self.run_stratify(support)
        self.db.execute("UPDATE h SET k=1,role='test',items='UNDECODABLE'")
        with self.assertRaisesRegex(ValueError, 'validation current basket'):
            self.run_stratify(support)

    def test_measurement_uses_sql_without_publishing_predictions(self):
        support = self.model({('100', 0): {'1', '2'}})
        self.queries([('1', 10, ['1']), ('2', 10, ['999'])])
        _, selected = self.run_stratify(support)
        result = probe.measure_queries(self.db, selected, support, 'synthetic-fit', {'1': 2}, self.catalog)
        self.assertEqual(result['kind'], 'engineering_cost_only')
        self.assertEqual(len(result['queries']), 2)
        self.assertFalse(result['formal_acceptance'])
        self.assertFalse(result['query_checkpoint_io_included'])
        self.assertGreaterEqual(result['catalog_prepare_seconds'], 0)
        for row in result['queries']:
            self.assertGreaterEqual(row['seconds'], 0)
            self.assertIn('sql_overlap_groups_returned', row['workload'])
            self.assertNotIn('scores', row)
            self.assertNotIn('ids', row)
            self.assertNotIn('targets', row)
        self.assertTrue({'global', 'bootstrap', 'resume'}.issubset(result['required_separate_costs']))

    def test_measurement_rejects_history_changes_and_duplicate_keys(self):
        support = self.model({('100', 0): {'1'}})
        self.queries([('1', 10, ['1'])])
        _, selected = self.run_stratify(support)
        with self.assertRaisesRegex(ValueError, 'duplicate or changed frozen key'):
            probe.measure_queries(self.db, selected*2, support, 'fit', {}, self.catalog)
        self.db.execute('UPDATE h SET items=?', ('["2"]',))
        with self.assertRaisesRegex(ValueError, 'history changed'):
            probe.measure_queries(self.db, selected, support, 'fit', {}, self.catalog)

    def test_watch_interrupts_without_success_result(self):
        support = self.model({('100', 0): {'1'}})
        self.queries([('1', 10, ['1'])])
        calls = 0

        def watch():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise TimeoutError('synthetic deadline')

        with self.assertRaisesRegex(TimeoutError, 'synthetic deadline'):
            probe.stratify(self.db, self.source, self.config, support, self.catalog, watch)


if __name__ == '__main__':
    unittest.main()
