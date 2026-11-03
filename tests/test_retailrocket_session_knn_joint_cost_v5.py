"""Only artificial rows: target-blind joint selection and bounded V4 ledger cost."""
from collections import Counter
from contextlib import closing
import csv
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_joint_cost_v5 as joint
from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_pair_probe_v3 as extractor
from scripts import retailrocket_session_knn_readback_v2 as readback
from scripts import retailrocket_session_knn_sql_v2 as sql
from scripts import retailrocket_session_knn_pair_v4 as paired
from tests import test_retailrocket_session_knn_pair_v4 as paired_fixture
from tests.test_retailrocket_session_knn_validation import make_fixture


class JointSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE h(v TEXT,s INTEGER,t INTEGER,k INTEGER,role TEXT,items TEXT,PRIMARY KEY(v,s,t))')
        self.db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        sessions = {str(5000+i): {'1'} for i in range(20)}
        sessions['5500'] = {'2', *(str(i) for i in range(800, 919))}
        sessions.update({str(6000+i): {'3', *(str(10000+i*5+j) for j in range(5))} for i in range(20)})
        self.db.executemany('INSERT INTO m VALUES(?,0,?)', ((v, i) for v, items in sessions.items() for i in items))
        sql.build_index(self.db)
        self.support = dict(Counter(i for items in sessions.values() for i in items))
        self.catalog = {i: 0 for i in self.support}
        self.catalog['100000'] = 90
        headers = ['visitorid', 'session_start_ms', 'query_ms', 'basket_index', 'role', 'target_items', 'candidate_count']
        self.config = {'schemas': {'queries.csv': headers}, 'validation_window_ms': [0, 100], 'fixed_validation': {'queries': 40}}
        self.rows = []
        self.keys = []
        # 31 light rows, 4 overlap-only heavy, 4 large-vote-only, 1 joint tail.
        for index, seed in enumerate(['999999']*31+['1']*4+['2']*4+['3']):
            visitor = str(1000+index)
            at = 95 if seed in ('2', '3') else 20
            self.keys.append([visitor, 0, at])
            self.db.execute('INSERT INTO h VALUES(?,0,?,1,?,?)', (visitor, at, 'validation', json.dumps([seed])))
            self.rows.append(dict(zip(headers, [visitor, '0', str(at), '1', 'validation', 'OPAQUE', 'UNREAD'])))
        self.rows.insert(0, dict(zip(headers, ['INVALID', '-', '-', '-', 'test', 'BAD JSON', 'BAD INT'])))
        with (self.root/'queries.csv').open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(self.rows)

    def select(self, name='out', prior=(), watch=lambda: None):
        return joint.freeze_joint_roster(self.root/name, self.db, self.root, self.config,
                                         self.support, self.catalog, prior, watch)

    def test_joint_corner_is_a_single_actual_row_and_not_two_marginal_extremes(self):
        frozen = self.select()
        pop = frozen['population']
        self.assertTrue(pop['complete'])
        self.assertEqual(pop['total_queries'], 40)
        self.assertEqual(pop['p90_nearest_rank']['eligible_neighbors'], 20)
        self.assertEqual(pop['p90_nearest_rank']['vote_memberships_upper'], 120)
        self.assertEqual(pop['cells']['1111']['population_queries'], 1)
        extreme = [r for r in frozen['probes'] if r['cell'] == '1111']
        self.assertEqual([r['key'] for r in extreme], [self.keys[-1]])
        self.assertEqual(extreme[0]['variable_scalar_slots'], 121)
        self.assertEqual(extreme[0]['selection_reasons'], list(joint.DIRECTIONS))
        self.assertEqual(pop['cells']['1011']['population_queries'], 0)
        self.assertEqual(pop['cells']['1001']['population_queries'], 4)
        self.assertEqual(pop['cells']['0110']['population_queries'], 4)
        self.assertEqual(pop['cells']['0000']['population_queries'], 31)
        self.assertTrue(all(c['selected_queries'] == min(4, c['population_queries']) for c in pop['cells'].values()))
        self.assertLessEqual(len(frozen['probes']), 64)
        self.assertIsNone(pop['T_plan'])
        self.assertFalse(pop['targets_used_for_selection'])
        raw = (self.root/'out'/'joint_roster.jsonl').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), pop['roster_sha256'])
        self.assertEqual(pop['roster_bytes'], len(raw))
        all_rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual([r['original_ordinal'] for r in all_rows], list(range(40)))
        self.assertEqual([r['key'] for r in all_rows], self.keys)
        self.assertEqual(json.loads((self.root/'out'/'frozen_probes.json').read_bytes()), frozen)

    def test_equal_ranks_use_key_sha_and_prior_sample_cannot_steer_selection(self):
        first = self.select('one')
        lows = [r for r in first['probes'] if r['cell'] == '0000']
        expected = sorted((joint.base._sha(k) for k in self.keys[:31]))[:4]
        self.assertEqual(sorted(r['key_sha256'] for r in lows), expected)
        second = self.select('two', list(reversed(first['probes'])))
        self.assertEqual(first['probes'], second['probes'])
        self.assertEqual(second['population']['prior_probe_overlap'], len(first['probes']))
        self.assertEqual(first['population']['roster_sha256'], second['population']['roster_sha256'])
        bad = deepcopy(first['probes'][:1]); bad[0]['history_size'] += 1
        with self.assertRaisesRegex(ValueError, 'Prior probe structural identity'):
            self.select('bad', bad)
        self.assertFalse((self.root/'bad'/'frozen_probes.json').exists())

    def test_test_role_first_and_output_target_columns_are_not_accessed(self):
        class Guard(dict):
            def __getitem__(self, key):
                if key in ('target_items', 'candidate_count') or (super().__getitem__('role') != 'validation' and key != 'role'):
                    raise AssertionError('Forbidden query field: '+key)
                return super().__getitem__(key)
        with patch.object(joint.base, 'read_rows', return_value=map(Guard, self.rows)):
            result = self.select()
        self.assertEqual(result['population']['full_query_predictions_for_selection'], 0)

    def test_population_eof_order_and_interruption_fail_before_sample_publication(self):
        self.config['fixed_validation']['queries'] = 41
        with self.assertRaisesRegex(ValueError, 'Incomplete validation EOF'):
            self.select('short')
        self.config['fixed_validation']['queries'] = 39
        with self.assertRaisesRegex(ValueError, 'Extra validation'):
            self.select('extra')
        self.config['fixed_validation']['queries'] = 40
        with patch.object(joint.base, 'read_rows', return_value=iter(self.rows[:2]+[self.rows[1]])):
            with self.assertRaisesRegex(ValueError, 'unordered validation key'):
                self.select('bad-order')
        def stop():
            if (self.root/'stopped'/'joint_roster.partial.jsonl').exists():
                raise TimeoutError('synthetic budget')
        with self.assertRaises(TimeoutError):
            self.select('stopped', watch=stop)
        for name in ('short', 'extra', 'bad-order', 'stopped'):
            self.assertFalse((self.root/name/'frozen_probes.json').exists())
            self.assertTrue((self.root/name/'joint_roster.partial.jsonl').is_file())

    def test_selected_slots_and_size_bound_exclude_exact_self_but_keep_other_session(self):
        self.db.executemany('INSERT INTO m VALUES(?,?,?)', [('1039', 0, '3'), ('1039', 1, '3')])
        self.db.executemany('INSERT INTO k1_v2_sizes VALUES(?,?,1)', [('1039', 0), ('1039', 1)])
        self.support['3'] += 2
        self.select()
        last = json.loads((self.root/'out'/'joint_roster.jsonl').read_bytes().splitlines()[-1])
        self.assertEqual((last['posting_work'], last['eligible_neighbors'], last['current_session_excluded']), (22, 21, 1))
        self.assertEqual(last['vote_memberships_upper'], 121)
        self.assertEqual(last['selected_neighbor_slots'], 21)

    def test_a_frozen_namespace_cannot_be_overwritten(self):
        self.select()
        with self.assertRaises(FileExistsError):
            self.select()

    def test_threshold_rank_ties_at_zero_and_at_positive_boundary(self):
        self.assertEqual(joint._cdf(Counter({0: 90, 1: 10}), 100), ({0: 90, 1: 100}, 0))
        self.assertEqual(joint._cdf(Counter({0: 88, 7: 8, 9: 4}), 100), ({0: 88, 7: 96, 9: 100}, 7))


class JointMeasurementTests(unittest.TestCase):
    def test_genuine_v4_pairing_and_committed_bytes_on_only_the_sealed_artificial_subset(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                paired_fixture, 'make_fixture', side_effect=lambda **opts: make_fixture(temp, **opts)):
            root, paths, config, primary, _, database, model, _, binding = paired_fixture.fixture()
            _, catalog = readback.load_context(paths, config, model['support'])
            local = root/'joint'
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                selected = joint.freeze_joint_roster(local, db, paths['dataset'], config, model['support'], catalog, [])
            extracted = extractor.extract_samples(local, primary, paths, config, selected['probes'])
            store = paired_fixture.create(root, extracted['config'], binding, name='joint_verified')
            with store.writer():
                paired_fixture.reconstruct_seal(store, model)
                measured = paired.verify_selected(Path(extracted['sample_primary']),
                    {k: Path(p) for k, p in extracted['paths'].items()}, extracted['config'],
                    store, model, database, extracted['ordinals'])
            sizes = {extracted['ordinals'][row['ordinal']]['original_ordinal']: len(checkpoint.encoded(row))
                     for row in store.iter_records()}
            summary = joint.summarize_joint_cost(selected, measured, payload_bytes_by_ordinal=sizes)
            self.assertEqual(sum(c['measured_queries'] for c in summary['cells'].values()), len(selected['probes']))
            self.assertEqual(summary['measured_chunk_payload_bytes'], sum(sizes.values()))
            self.assertTrue(summary['verified_per_row_bytes_measured'])
            self.assertNotIn('key_sha256', json.dumps(summary))
            self.assertFalse(summary['formal_acceptance'])
            self.assertIsNone(summary['T_plan'])
            self.assertFalse((store.folder/'acceptance.json').exists())
            bad = deepcopy(measured); bad['queries'][0]['key_sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'differs from frozen selection'):
                joint.summarize_joint_cost(selected, bad)
            bad = deepcopy(measured)
            bad['queries'][0]['sql_workload']['sql_vote_membership_rows_returned'] = selected['probes'][0]['vote_memberships_upper']+1
            with self.assertRaisesRegex(ValueError, 'structural bound'):
                joint.summarize_joint_cost(selected, bad)
            with self.assertRaisesRegex(ValueError, 'payload ordinal roster'):
                joint.summarize_joint_cost(selected, measured, payload_bytes_by_ordinal={})
            wrong_size = dict(sizes); wrong_size[next(iter(sizes))] += 1
            with self.assertRaisesRegex(ValueError, 'frame bytes differ'):
                joint.summarize_joint_cost(selected, measured, payload_bytes_by_ordinal=wrong_size)


if __name__ == '__main__':
    unittest.main()
