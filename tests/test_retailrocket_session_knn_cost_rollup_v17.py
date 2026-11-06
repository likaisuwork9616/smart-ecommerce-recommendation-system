"""Hand-computable V17 cost accounting, paired variation, and source integrity."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import retailrocket_session_knn_cost_rollup_v17 as rollup
from scripts.retailrocket_session_knn_checkpoint_v2 import encoded
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore


A = '0001/n3/v3'
B = '0001/n3/v4'


def identity(ordinal):
    key = [str(1001+ordinal), 0, ordinal]
    digest = hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest()
    return key, digest


def timer_rows(verification=9., append=1., rank=4., vote=2., ordinal=0):
    """Two budget seconds and three commit seconds surround the exclusive append."""
    row = {'subset_ordinal': ordinal, 'verification_seconds': verification,
           'rank_seconds': rank, 'checkpoint_append_seconds': append+5.,
           'append_without_commit_seconds': append+2., 'chunk_commit_seconds': 3.,
           'rank_stages_seconds': {'sql_selected_votes_and_accumulation': vote,
                                  'exact_neighbor_selection': rank-vote}}
    budget = {'subset_ordinal': ordinal, 'verification_seconds': verification,
              'append_without_commit_seconds': append+2., 'query_append_budget_seconds': 2.,
              'append_without_commit_or_budget_seconds': append, 'chunk_commit_seconds': 3.}
    detail = {'subset_ordinal': ordinal, 'verification_other_seconds': verification-rank,
              'append_exclusive_seconds': {'frame_encode': append, 'budget_publication': 2., 'chunk_commit': 3.}}
    return row,budget,detail


def repeat_fixture(cohort, repeat_index):
    """A has two keys and three repeats; B has one key and two repeats."""
    if cohort == 'V6':
        values = [(0,A,9.+2*repeat_index,1.,4.,2.), (1,A,1.,19.+2*repeat_index,.5,.25)]
    else:
        values = [(2,B,4.+2*repeat_index,1.,2.,1.)]
    probes, queries, append_events, budget_events = [], [], [], []
    cells = {}
    for subset, (ordinal,cell,verify,append,rank,vote) in enumerate(values):
        key, sha = identity(ordinal)
        probes.append({'key': key, 'key_sha256': sha, 'original_ordinal': ordinal,
                       'cell': cell.split('/')[0] if cohort == 'V6' else cell})
        cells[sha] = cell
        row, _, _ = timer_rows(verify,append,rank,vote,subset)
        row.update(key_sha256=sha,original_ordinal=ordinal)
        queries.append(row)
        append_events.append({'subset_ordinal': subset, 'completed': True, 'frame_bytes': 32,
                              'seconds': append+5., 'unpartitioned_seconds': 0.,
                              'parts_seconds': {'budget_check': 2., 'guards_and_key': 0.,
                                                'frame_encode': append, 'payload_open': 0., 'payload_write': 0.,
                                                'pending_and_trigger': 0., 'nested_flush': 3.}})
        budget_events.extend([
            {'context': 'query_append', 'subset_ordinal': subset, 'stage': None, 'completed': True, 'seconds': 2.},
            {'context': 'chunk_commit', 'subset_ordinal': subset, 'stage': None, 'completed': True, 'seconds': .5}])
    commits = [{'completed': True, 'records': 1, 'seconds': 3., 'payload_bytes': 32} for _ in queries]
    measured = {'queries': queries, 'verified_subset_queries': len(queries), 'committed_prefix_rows': 0,
                'chunk_commits': commits, 'setup_seconds': .25, 'tail_flush_and_eof_seal_seconds': .5}
    store = object.__new__(DetailedTimedStore)
    store.append_events, store.budget_events, store.commit_events = append_events,budget_events,commits
    observations = {'append_events': append_events, 'budget_events': budget_events,
                    'detail': store.detailed_cost_summary(measured)}
    return probes,measured,observations,cells


def population_fixture():
    rows, overheads = [], []
    cohorts = {'V6': {'queries': 2, 'repeats': 3}, 'V7': {'queries': 1, 'repeats': 2}}
    for cohort, expected in cohorts.items():
        for repeat in range(expected['repeats']):
            normalized = rollup.normalize_repeat(cohort,repeat,*repeat_fixture(cohort,repeat))
            rows.extend(normalized['rows'])
            overheads.append(normalized['overheads'])
    return {A:10,B:20},rows,overheads,cohorts


class BoundSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base/'sources'
        self.root.mkdir()

    def bound(self, name, data):
        (self.root/name).write_bytes(data)
        return {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def test_bound_json_checks_actual_bytes_size_and_digest(self):
        data = encoded({'synthetic': [1,2]})
        record = self.bound('input.json',data)
        self.assertEqual(rollup.read_bound(self.root,record), {'synthetic': [1,2]})
        for changed in (dict(record,bytes=len(data)+1), dict(record,sha256='f'*64)):
            with self.subTest(record=changed), self.assertRaises(ValueError):
                rollup.read_bound(self.root,changed)
        (self.root/'input.json').write_bytes(data+b' ')
        with self.assertRaises(ValueError):
            rollup.read_bound(self.root,record)
        with self.assertRaises((ValueError,FileNotFoundError)):
            rollup.read_bound(self.root,dict(record,path='missing.json'))

    def test_ambiguous_json_and_path_escape_do_not_become_verified_inputs(self):
        record = self.bound('duplicate.json',b'{"cost":1,"cost":99}')
        with self.assertRaises(ValueError):
            rollup.read_bound(self.root,record)
        data = encoded({'outside': True})
        (self.base/'outside.json').write_bytes(data)
        record = {'path': '../outside.json', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        with self.assertRaises(ValueError):
            rollup.read_bound(self.root,record)

    def test_bound_inventory_checks_every_file_uniquely_and_respects_stop(self):
        records = [self.bound('report.json',encoded({'sample':1})), self.bound('method.py',b'print(1)\n')]
        self.assertEqual(rollup.verify_bindings(self.root,records),2)
        with self.assertRaises(ValueError):
            rollup.verify_bindings(self.root,records+[records[0]])
        def expired():
            raise TimeoutError('synthetic stop request')
        with self.assertRaises(TimeoutError):
            rollup.verify_bindings(self.root,records,watch=expired)
        (self.root/'method.py').write_bytes(b'print(2)\n')
        with self.assertRaises(ValueError):
            rollup.verify_bindings(self.root,records)


class RowAccountingTests(unittest.TestCase):
    def test_nested_rank_vote_commit_and_budget_are_counted_once(self):
        row,budget,detail = timer_rows()
        value = rollup.row_cost(row,budget,detail)
        self.assertEqual(value, {'verification':9., 'rank':4., 'vote_sql_and_accumulation':2.,
                                'checkpoint_append':6., 'append_without_commit':3., 'direct_budget':2.,
                                'append_without_commit_or_budget':1., 'core':10., 'query_nested_commit':3.})
        self.assertEqual(value['checkpoint_append'], value['append_without_commit_or_budget']+
                         value['direct_budget']+value['query_nested_commit'])
        self.assertEqual(value['core'], value['verification']+value['append_without_commit_or_budget'])
        self.assertNotEqual(value['core'], value['verification']+value['rank']+value['vote_sql_and_accumulation']+
                            value['append_without_commit_or_budget'])

    def test_invalid_or_inconsistent_timers_cannot_be_aggregated(self):
        for change in ('negative','nan','infinite','rank_gt_verify','vote_gt_rank','append_sum',
                       'budget_double_deduct','budget_copy','detail_copy','ordinal'):
            row,budget,detail = timer_rows()
            if change in ('negative','nan','infinite'):
                row['verification_seconds'] = {'negative':-1.,'nan':float('nan'),'infinite':float('inf')}[change]
            elif change == 'rank_gt_verify':
                row['rank_seconds'] = 10.
            elif change == 'vote_gt_rank':
                row['rank_stages_seconds']['sql_selected_votes_and_accumulation'] = 5.
            elif change == 'append_sum':
                row['checkpoint_append_seconds'] = 7.
            elif change == 'budget_double_deduct':
                budget['append_without_commit_or_budget_seconds'] = -2.
            elif change == 'budget_copy':
                budget['verification_seconds'] = 8.
            elif change == 'detail_copy':
                detail['verification_other_seconds'] = 4.
            else:
                budget['subset_ordinal'] = 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                rollup.row_cost(row,budget,detail)

    def test_normalizer_replays_original_event_accounting_without_ranking(self):
        probes,measured,observations,cells = repeat_fixture('V6',0)
        value = rollup.normalize_repeat('V6',0,probes,measured,observations,cells)
        self.assertEqual([row['seconds']['core'] for row in value['rows']], [10.,20.])
        self.assertEqual([row['cell'] for row in value['rows']], [A,A])
        overhead = value['overheads']
        self.assertEqual(overhead['query_nested_commit_seconds'], 6.)
        self.assertEqual(overhead['all_chunk_commit_seconds'], 6.)
        self.assertEqual(overhead['final_flush_commit_seconds'], 0.)
        self.assertEqual(overhead['direct_query_budget_seconds'], 4.)
        self.assertEqual(overhead['all_budget_seconds'], 5.)

    def test_saved_detail_raw_events_or_frozen_identities_cannot_drift(self):
        for change in ('saved_detail','raw_event','key','missing_cell_binding','ordinal','missing','resumed'):
            probes,measured,observations,cells = repeat_fixture('V7',0)
            if change == 'saved_detail':
                observations['detail']['rows'][0]['verification_other_seconds'] += 1.
            elif change == 'raw_event':
                observations['append_events'][0]['parts_seconds']['frame_encode'] = -1.
            elif change == 'key':
                measured['queries'][0]['key_sha256'] = 'f'*64
            elif change == 'missing_cell_binding':
                cells.clear()
            elif change == 'ordinal':
                measured['queries'][0]['original_ordinal'] += 1
            elif change == 'missing':
                measured['queries'].clear()
            else:
                measured['committed_prefix_rows'] = 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                rollup.normalize_repeat('V7',0,probes,measured,observations,cells)


class PopulationAndVariationTests(unittest.TestCase):
    def setUp(self):
        self.populations,self.rows,self.overheads,self.cohorts = population_fixture()

    def summarize(self, **overrides):
        values = {'populations': self.populations, 'rows': self.rows,
                  'overheads': self.overheads, 'expected_cohorts': self.cohorts}
        values.update(overrides)
        return rollup.summarize_costs(**values)

    def test_three_and_two_repeats_preserve_unique_query_counts(self):
        value = self.summarize()
        self.assertEqual(value['scope'], {'population_queries':30, 'nonempty_cells':2,
                                         'distinct_queries':3, 'repeat_observations':8, 'parent_fallback_cells':0})
        self.assertEqual(value['cells'][A]['distinct_queries'],2)
        self.assertEqual(value['cells'][A]['repeat_observations'],6)
        self.assertEqual(value['cells'][B]['distinct_queries'],1)
        self.assertEqual(value['cells'][B]['repeat_observations'],2)
        self.assertEqual([r['queries'] for r in value['cells'][A]['by_repeat']], [2,2,2])
        self.assertEqual([r['queries'] for r in value['cells'][B]['by_repeat']], [1,1])
        public = json.dumps(value)
        for row in self.rows:
            self.assertNotIn(row['key_sha256'],public)

    def test_maximum_is_a_measured_same_row_cost_not_component_maxima_sum(self):
        cell = self.summarize()['cells'][A]
        self.assertEqual(cell['pooled_observations_seconds']['core']['maximum'],24.)
        self.assertEqual(cell['pooled_observations_seconds']['core']['mean'],17.)
        verification_max = cell['pooled_observations_seconds']['verification']['maximum']
        append_max = cell['pooled_observations_seconds']['append_without_commit_or_budget']['maximum']
        self.assertEqual(verification_max+append_max,36.)
        self.assertEqual([r['seconds']['core']['maximum'] for r in cell['by_repeat']], [20.,22.,24.])

    def test_within_key_temporal_change_is_separate_from_between_key_spread(self):
        cell = self.summarize()['cells'][A]
        temporal = cell['within_query_temporal']['core']
        self.assertEqual(temporal['query_range_seconds']['count'],2)
        self.assertEqual(temporal['query_range_seconds']['minimum'],4.)
        self.assertEqual(temporal['query_range_seconds']['maximum'],4.)
        self.assertEqual(temporal['query_repeat_median_seconds']['minimum'],12.)
        self.assertEqual(temporal['query_repeat_median_seconds']['maximum'],22.)
        self.assertEqual(temporal['query_repeat_median_seconds']['range'],10.)
        self.assertEqual(cell['pooled_observations_seconds']['core']['range'],14.)
        pairs = {(p['from_repeat'],p['to_repeat']):p for p in temporal['pairs']}
        self.assertEqual(set(pairs), {(0,1),(0,2),(1,2)})
        self.assertEqual(pairs[0,1]['delta_seconds']['mean'],2.)
        self.assertEqual(pairs[0,2]['absolute_delta_seconds']['maximum'],4.)
        other = self.summarize()['cells'][B]['within_query_temporal']['core']
        self.assertEqual(other['query_range_seconds']['maximum'],2.)
        self.assertEqual(other['query_repeat_median_seconds']['range'],0.)

    def test_population_weighting_conserves_per_cell_scenarios_and_keeps_overheads_separate(self):
        value = self.summarize()
        expected = {'minimum':(250.,300.),'median':(290.,340.),'maximum':(330.,380.)}
        for scenario,(mean,maximum) in expected.items():
            weighted = value['weighted_scenarios_seconds']['core'][scenario]
            self.assertEqual(weighted,{'cell_mean':mean,'cell_maximum':maximum})
            for statistic in ('cell_mean','cell_maximum'):
                total = sum(pop*value['cells'][cell]['scenario_inputs_seconds']['core'][scenario][statistic]
                            for cell,pop in self.populations.items())
                self.assertEqual(weighted[statistic],total)
        self.assertEqual(value['weighted_scenarios_seconds'], self.summarize(overheads=[])['weighted_scenarios_seconds'])
        changed = deepcopy(self.overheads)
        changed[0]['setup_seconds'] += 10000.
        changed[0]['tail_flush_and_eof_seal_seconds'] += 10000.
        self.assertEqual(value['weighted_scenarios_seconds'],
                         self.summarize(overheads=changed)['weighted_scenarios_seconds'])

    def test_missing_repeat_duplicate_key_wrong_cell_and_identity_changes_fail(self):
        for change in ('missing_repeat','duplicate','cross_cohort_key','cross_window_cell','cell','unknown_cell','ordinal',
                       'unregistered_repeat','cohort_size','negative','broken_core'):
            rows,cohorts,populations = deepcopy(self.rows),deepcopy(self.cohorts),dict(self.populations)
            if change == 'missing_repeat':
                rows = [r for r in rows if not (r['cohort']=='V6' and r['repeat_index']==2)]
            elif change == 'duplicate':
                rows.append(deepcopy(rows[0]))
            elif change == 'cross_cohort_key':
                for row in rows:
                    if row['cohort'] == 'V7':
                        row['key_sha256'] = rows[0]['key_sha256']
                        row['original_ordinal'] = rows[0]['original_ordinal']
            elif change == 'cross_window_cell':
                populations = {A:30}
                for row in rows:
                    row['cell'] = A
            elif change == 'cell':
                rows[2]['cell'] = B
            elif change == 'unknown_cell':
                rows[0]['cell'] = '0001/n5/v5'
            elif change == 'ordinal':
                rows[2]['original_ordinal'] += 10
            elif change == 'unregistered_repeat':
                rows[0]['repeat_index'] = 3
            elif change == 'cohort_size':
                cohorts['V7']['queries'] = 2
            elif change == 'negative':
                rows[0]['seconds']['rank'] = -1.
            else:
                rows[0]['seconds']['core'] += 1.
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.summarize(rows=rows,expected_cohorts=cohorts,populations=populations)

    def test_all_55_cells_require_their_own_samples_without_parent_fallback(self):
        cells = [f'{parent}/n{n}/v{v}' for parent in ('0000','0001') for n in range(7) for v in range(6)][:55]
        populations = {cell:1 for cell in cells}
        seconds = rollup.row_cost(*timer_rows())
        rows = [{'cohort':'synthetic55', 'repeat_index':repeat, 'key_sha256':identity(i)[1],
                 'original_ordinal':i, 'cell':cell, 'seconds':dict(seconds)}
                for repeat in range(2) for i,cell in enumerate(cells)]
        cohorts = {'synthetic55':{'queries':55,'repeats':2}}
        result = rollup.summarize_costs(populations,rows,[],cohorts)
        self.assertEqual(result['scope']['nonempty_cells'],55)
        self.assertEqual(result['scope']['distinct_queries'],55)
        self.assertEqual(result['scope']['repeat_observations'],110)
        self.assertEqual(result['scope']['parent_fallback_cells'],0)
        self.assertEqual(result['weighted_scenarios_seconds']['core']['median']['cell_mean'],550.)
        rows = [row for row in rows if row['cell'] != cells[-1]]
        cohorts['synthetic55']['queries'] = 54
        with self.assertRaises(ValueError):
            rollup.summarize_costs(populations,rows,[],cohorts)


if __name__ == '__main__':
    unittest.main()
