"""Synthetic V19 extreme-plus-hash tail selection and seven-query evidence."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_reinforcement_v18 as previous
from scripts import retailrocket_session_knn_tail_v19 as tail
from scripts import run_retailrocket_session_knn_tail_v19 as entry
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from tests import test_retailrocket_session_knn_reinforcement_v18 as fixtures


CELL = '1101/n5/v4'
SEGMENTS = ('n1946_2499','n2500_2999','n3000_4999')


def specification():
    return {'target_cell':CELL,'target_population':{'population':22,'historical_exclusions':6,
                'eligible':16,'existing_comparable_queries':5},
            'quotas':[{'segment':name,'lower_inclusive':lower,'upper_inclusive':upper,
                       'population':population,'historical_exclusions':excluded,'eligible':population-excluded,
                       'planned_new_queries':2}
                      for name,lower,upper,population,excluded in zip(SEGMENTS,(1946,2500,3000),
                          (2499,2999,4999),(5,5,7),(1,1,2),strict=True)],
            'selection':{'quota_by_segment':dict.fromkeys(SEGMENTS,2),'planned_new_queries':6,
                         'planned_anchor_queries':1,'planned_unique_queries':7,
                         'prefix_with_terminator':'k1-tail-v19-20261106\x00','strategy':'segment_max_then_hash'},
            'measurement':{'fresh_repeats':3,'queries_per_repeat':7,'expected_engineering_checks':21},
            'telemetry':{'interval_seconds':.2,'process_name_prefix':'ollama'}}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the small synthetic structural fixture, never its real ranking helpers.
        old = fixtures.SelectionTests()
        old.setUp()
        self.addCleanup(old.doCleanups)
        self.path,self.rows,self.histories = old.path,deepcopy(old.rows),deepcopy(old.histories)
        prior_ordinals = (0,1,219,220,221,222,225,226,228,229)
        self.histories['V18'] = {'probes':[dict(self.rows[i],cell=fixtures.A if i in (0,219,220,221,222) else CELL,
                                              sample_role='anchor' if i in (0,1) else 'new') for i in prior_ordinals],
                                 'new_keys':8,'anchor_keys':2}
        for ordinal,n,v in ((1,1945,3000),(209,10,200),(225,2999,3000),(226,2499,5000)):
            self.rows[ordinal].update(eligible_neighbors=n,vote_memberships_upper=v,
                                     variable_scalar_slots=1+6*min(n,500),posting_work=n)
        extra = ((1945,3000),(1946,3000),(2001,3000),(2498,4000),(2498,3500),
                 (2500,3000),(2600,3500),(2998,4000),(2998,4500),
                 (3000,3000),(3500,3500),(4998,5000),(4998,6000),
                 (5000,3000),(2499,1999),(2999,10000),(1945,9999))
        for n,v in extra:
            ordinal = len(self.rows)
            key = [str(171011+ordinal),0,ordinal]
            self.rows.append({'key':key,'key_sha256':fixtures.digest(key),'original_ordinal':ordinal,
                              'eligible_neighbors':n,'vote_memberships_upper':v,'causal_candidates':1,
                              'variable_scalar_slots':1+6*min(n,500),'posting_work':n,'history_size':1,
                              'history_sha256':fixtures.digest([str(ordinal)]),'current_session_excluded':0})
        by_key = {row['key_sha256']:row for row in self.rows}
        for name,group in self.histories.items():
            for probe in group['probes']:
                original = by_key[probe['key_sha256']]
                probe.update(original)
                if name == 'V3':
                    probe.pop('original_ordinal')
                elif original['original_ordinal'] == 209:
                    probe['cell'] = '0000/n2/v2'
        self.seal()
        self.spec = specification()

    def seal(self):
        data = b''.join(cp.encoded(row) for row in self.rows)
        self.path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        population = self.histories['V6']['population']
        counts = Counter(''.join(str(int(0 < row[k] and row[k] >= population['p90_nearest_rank'][k]))
                                 for k in DIMENSIONS) for row in self.rows)
        population.update(total_queries=len(self.rows),expected_queries=len(self.rows),roster_bytes=len(data),
                          roster_sha256=digest,cells={name:{'population_queries':n} for name,n in counts.items()})
        for name,group in self.histories.items():
            if name not in ('V3','V6'):
                group['roster_sha256'] = digest

    def choose(self, **kwargs):
        return tail.select_tail_roster(self.path,self.histories,self.spec,**kwargs)

    def audit(self, selected, **kwargs):
        return tail.audit_tail_order(self.path,selected,self.histories,self.spec,**kwargs)

    def test_eligible_maximum_then_distinct_hash_match_independent_golden_selection(self):
        selected = self.choose()
        self.assertEqual([p['original_ordinal'] for p in selected['probes']],[1,227,232,233,235,238,241])
        chosen = {(p['selection_segment'],p['selection_reason']):p for p in selected['probes']}
        self.assertEqual([chosen[name,'segment_max']['original_ordinal'] for name in SEGMENTS],[233,238,241])
        self.assertEqual([chosen[name,'hash']['original_ordinal'] for name in SEGMENTS],[232,235,227])
        self.assertEqual([chosen[name,'segment_max']['eligible_neighbors'] for name in SEGMENTS],[2498,2998,4998])
        self.assertEqual(chosen['anchor','anchor']['eligible_neighbors'],1945)
        historical = {p['key_sha256'] for group in self.histories.values() for p in group['probes']}
        self.assertEqual(len(historical),226)
        self.assertTrue(all(p['key_sha256'] not in historical and p['eligible_neighbors']>1945
                            for p in selected['probes'] if p['sample_role']=='new'))
        self.assertEqual(len({p['key_sha256'] for p in selected['probes']}),7)
        self.assertEqual((selected['new_keys'],selected['anchor_keys']),(6,1))
        # Greater historical maxima exist in every segment and must be excluded first.
        self.assertEqual([self.rows[i]['eligible_neighbors'] for i in (226,225,229)],[2499,2999,4999])
        self.audit(selected)
        self.spec['quotas'].reverse()
        self.histories['V18']['probes'].sort(key=lambda p:p['original_ordinal'])
        self.assertEqual(self.choose(),selected)

    def test_all_v18_new_identities_and_exactly_its_two_reused_anchors_are_bound(self):
        original = deepcopy(self.histories)
        for change in ('missing_v18','v18_new_overlap','new_labeled_anchor','duplicate','different_anchor','history'):
            self.histories = deepcopy(original)
            group = self.histories['V18']
            if change == 'missing_v18':
                group['probes'].pop()
            elif change == 'v18_new_overlap':
                group['probes'][2] = dict(self.rows[2],cell=fixtures.A,sample_role='new')
                group['probes'].sort(key=lambda p:p['original_ordinal'])
            elif change == 'new_labeled_anchor':
                group['probes'][1]['sample_role'] = 'new'
                group['probes'][-1]['sample_role'] = 'anchor'
            elif change == 'duplicate':
                group['probes'][-1] = deepcopy(group['probes'][-2])
            elif change == 'different_anchor':
                group['probes'][1] = dict(self.rows[3],cell=CELL,sample_role='anchor')
            else:
                group['probes'][1]['history_sha256'] = 'a'*64
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.choose()

    def test_segment_capacity_shortfall_cannot_borrow_quota_or_reinclude_1945(self):
        for change in ('shortfall','quota_transfer','boundary','strategy','salt','old_ten_count'):
            self.spec = specification()
            if change == 'shortfall':
                self.spec['quotas'][0].update(eligible=1,historical_exclusions=4)
            elif change == 'quota_transfer':
                self.spec['selection']['quota_by_segment'].update({SEGMENTS[0]:1,SEGMENTS[1]:3})
            elif change == 'boundary':
                self.spec['quotas'][0]['lower_inclusive'] = 1945
            elif change == 'strategy':
                self.spec['selection']['strategy'] = 'hash_only'
            elif change == 'salt':
                self.spec['selection']['prefix_with_terminator'] = 'k1-tail-v19-20261106'
            else:
                self.spec['measurement']['queries_per_repeat'] = 10
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.choose()

    def test_independent_sort_rejects_wrong_extreme_reason_source_and_stop(self):
        selected = self.choose()
        for change in ('not_maximum','duplicate_winner','segment','reason','old_anchor_new'):
            altered = deepcopy(selected)
            if change == 'not_maximum':
                target = next(p for p in altered['probes'] if p['original_ordinal']==233)
                target.update(self.rows[231])
                altered['probes'].sort(key=lambda p:p['original_ordinal'])
            elif change == 'duplicate_winner':
                altered['probes'][2] = deepcopy(altered['probes'][3])
            elif change == 'segment':
                altered['probes'][2]['selection_segment'] = SEGMENTS[1]
            elif change == 'reason':
                altered['probes'][2]['selection_reason'] = 'segment_max'
            else:
                altered['probes'][0]['sample_role'] = 'new'
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.audit(altered)
        def stop():
            raise TimeoutError('synthetic absolute deadline')
        with self.assertRaises(TimeoutError):
            self.choose(watch=stop)
        with self.assertRaises(TimeoutError):
            self.audit(selected,watch=stop)
        data = self.path.read_bytes()
        self.path.write_bytes(data.replace(b'\n',b' \n'))
        with self.assertRaises(ValueError):
            self.choose()
        with self.assertRaises(ValueError):
            self.audit(selected)


def workload_case():
    """All neighbors have exact similarity 1/4 and four members; no ranker is executed."""
    counts = (1945,2499,1946,2999,2500,4999,3000)
    selected_neighbors = [{'key':[str(i),0],'intersection':1,'union':4,'similarity':[1,4]} for i in range(1,501)]
    probes,queries,predictions = [],[],[]
    for i,n in enumerate(counts):
        key = [str(191001+i),0,i]
        anchor = i == 0
        segment = 'anchor' if anchor else SEGMENTS[(i-1)//2]
        reason = 'anchor' if anchor else 'segment_max' if i%2 else 'hash'
        probes.append({'key':key,'key_sha256':fixtures.digest(key),'original_ordinal':i,'cell':CELL,
                       'sample_role':'anchor' if anchor else 'new','selection_segment':segment,'selection_reason':reason,
                       'eligible_neighbors':n,'vote_memberships_upper':2000,'posting_work':n,'causal_candidates':3})
        work = {'neighbor_pool_rows_hashed':n,'sql_selected_rows_inserted':500,'sql_overlap_membership_matches':n,
                'causal_catalog_candidates':3,'sql_vote_membership_rows_returned':2000,'exact_vote_additions':1500}
        queries.append({'subset_ordinal':i,'original_ordinal':i,'key_sha256':fixtures.digest(key),'sql_workload':work})
        pool = hashlib.sha256()
        for neighbor in range(1,n+1):
            pool.update((json.dumps([[str(neighbor),0],1,4],separators=(',',':'))+'\n').encode())
        predictions.append({'eligible_neighbors':n,'selected_neighbor_count':500,'selected_neighbors':deepcopy(selected_neighbors),
                            'history_size':1,'vote_memberships':2000,'neighbor_pool_sha256':pool.hexdigest(),
                            'boundary_similarity':[1,4],'boundary_ties_total':n,'boundary_ties_excluded':n-500})
    return probes,{'queries':queries},predictions


def timing_case():
    probes,_,_ = workload_case()
    _,repeats = fixtures.timing_case()
    for repeat in repeats:
        measured,observations = repeat['measured'],repeat['observations']
        measured['queries'] = measured['queries'][:7]
        measured['verified_subset_queries'] = 7
        measured['chunk_commits'] = measured['chunk_commits'][:7]
        observations['append_events'] = observations['append_events'][:7]
        observations['budget_events'] = observations['budget_events'][:7]
        observer = object.__new__(DetailedTimedStore)
        observer.append_events = observations['append_events']
        observer.budget_events = observations['budget_events']
        observer.commit_events = measured['chunk_commits']
        observations['detail'] = observer.detailed_cost_summary(measured)
    return {'probes':probes,'new_keys':6,'anchor_keys':1,'roster_sha256':'f'*64},repeats


class WorkloadAndEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = workload_case()

    def test_new_tail_bands_are_stricter_than_old_anchor_and_all_votes_remain_capped(self):
        workload = tail.sample_workload(*self.native,specification())[CELL]
        self.assertEqual((workload['queries'],workload['new_queries'],workload['anchor_queries']),(7,6,1))
        self.assertEqual(workload['sql_selected_rows_inserted'],3500)
        self.assertEqual(workload['sql_vote_membership_rows_returned'],14000)
        self.assertEqual(workload['by_role']['anchor']['eligible_neighbors_max'],1945)
        self.assertEqual([workload['by_segment'][segment]['queries'] for segment in SEGMENTS],[2,2,2])
        for index,n in ((2,1945),(2,2500),(4,2499),(4,3000),(6,2999),(6,5000)):
            probes,measured,predictions = deepcopy(self.native)
            probes[index]['eligible_neighbors'] = n
            with self.subTest(index=index,n=n),self.assertRaises(ValueError):
                tail.sample_workload(probes,measured,predictions,specification())
        probes,measured,predictions = deepcopy(self.native)
        predictions[5]['boundary_ties_excluded'] += 1
        with self.assertRaises(ValueError):
            tail.sample_workload(probes,measured,predictions,specification())

    def test_three_seven_row_ledgers_pass_but_old_count_or_third_payload_change_fails(self):
        probes,_,predictions = self.native
        workload = tail.sample_workload(*self.native,specification())
        with tempfile.TemporaryDirectory() as temp:
            root,repeats = Path(temp),[]
            deadline = (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            for repeat,chunk in enumerate((2,3,4)):
                folder = root/f'repeat_{repeat}'/'verified_subset'
                binding = {'scope':'V19 synthetic seven-query ledgers'}
                store = DetailedTimedStore.create(folder,binding,deadline,120,expected_queries=7,
                    required_stages=('reconstruction','queries'),chunk_queries=chunk)
                with store.writer():
                    store.seal_stage('reconstruction',{'synthetic':True})
                    for i,(probe,prediction) in enumerate(zip(probes,predictions,strict=True)):
                        store.append_verified(i,probe['key'],{'expected':{'key':probe['key'],'predictions':{'K1':prediction}},
                                                             'precise':{},'delta_hex':{}})
                    store.flush_chunk()
                    store.seal_stage('queries',{'queries':7,'paired_streams_eof_checked':True})
                repeats.append({'proof':ledger_proof(DetailedTimedStore.open(folder,binding),probes),
                                'workload_by_cell':deepcopy(workload)})
            tail.compare_repeats(root,repeats,specification())
            with self.assertRaises(ValueError):
                tail.compare_repeats(root,repeats[:2],specification())
            altered = deepcopy(repeats)
            for repeat in altered:
                repeat['proof']['records'] = 10
            with self.assertRaises(ValueError):
                tail.compare_repeats(root,altered,specification())
            payload = next((root/'repeat_2'/'verified_subset'/'payloads').glob('*.jsonl'))
            payload.write_bytes(payload.read_bytes()+b'{}\n')
            with self.assertRaises(ValueError):
                tail.compare_repeats(root,repeats,specification())

    def test_descriptive_segment_costs_keep_six_new_one_old_and_publish_no_weighted_estimates(self):
        selected,repeats = timing_case()
        result = tail.summarize_repeats(selected,repeats,specification())
        scope = result['scope']
        self.assertEqual((scope['new_keys'],scope['anchor_keys'],scope['engineering_checks']),(6,1,21))
        self.assertEqual((scope['distinct_historically_verified_queries'],scope['distinct_comparable_queries']),(232,170))
        self.assertEqual(scope['target_cell_distinct_queries'],{CELL:11})
        self.assertEqual(scope['target_tail_distinct_queries'],6)
        self.assertEqual((scope['globally_covered_cells'],scope['globally_uncovered_cells']),(55,0))
        cell = result['cells'][CELL]
        self.assertEqual(cell['roles']['new']['distinct_queries'],6)
        self.assertEqual(cell['roles']['anchor']['distinct_queries'],1)
        self.assertEqual([cell['segments'][segment]['distinct_queries'] for segment in SEGMENTS],[2,2,2])
        self.assertEqual([cell['selection_reasons'][reason]['distinct_queries'] for reason in ('segment_max','hash')],[3,3])
        decomposition = cell['max_same_query_range_decomposition']
        self.assertEqual((decomposition['sample_role'],decomposition['selection_reason'],
                          decomposition['fast_repeat'],decomposition['slow_repeat']),('new','segment_max',1,0))
        delta = decomposition['delta_seconds']
        self.assertEqual(delta['core'],10.)
        self.assertEqual(delta['core'],delta['verification']+delta['append_without_commit_or_budget'])
        self.assertEqual(delta['rank'],5.)
        def verify_no_projection(value):
            if isinstance(value,dict):
                self.assertNotIn('weighted_scenarios_seconds',value)
                self.assertNotIn('scenario_inputs_seconds',value)
                for item in value.values():
                    verify_no_projection(item)
            elif isinstance(value,list):
                for item in value:
                    verify_no_projection(item)
        verify_no_projection(result)
        public = json.dumps(result)
        self.assertTrue(all(probe['key_sha256'] not in public for probe in selected['probes']))

    def test_cost_summary_rejects_missing_round_changed_role_identity_or_budget(self):
        for change in ('missing_round','anchor_as_new','identity','budget','negative'):
            selected,repeats = timing_case()
            if change == 'missing_round':
                repeats.pop()
            elif change == 'anchor_as_new':
                selected['probes'][0]['sample_role'] = 'new'
            elif change == 'identity':
                repeats[2]['measured']['queries'][0]['original_ordinal'] += 1
            elif change == 'budget':
                repeats[2]['observations']['detail']['budget']['rows'][0]['query_append_budget_seconds'] += 1
            else:
                repeats[2]['measured']['queries'][0]['verification_seconds'] = -1.
            with self.subTest(change=change),self.assertRaises(ValueError):
                tail.summarize_repeats(selected,repeats,specification())


class RunnerTests(unittest.TestCase):
    def test_single_old_anchor_whole_payload_is_bound_independently_of_subset_ordinal(self):
        probes,_,_ = workload_case()
        selection = {'probes':probes,'new_keys':6,'anchor_keys':1}
        frames = [{'ordinal':i,'key':probe['key'],'payload':{'expected':{'key':probe['key']},
                   'precise':{'value':i},'delta_hex':{'value':'0x0.0p+0'}}} for i,probe in enumerate(probes)]
        old = dict(deepcopy(frames[0]),ordinal=37)
        reference = {fixtures.digest(old['key']):old['payload']}
        entry._compare_anchors(SimpleNamespace(iter_records=lambda:iter(frames)),selection,reference)
        for component in ('expected','precise','delta_hex'):
            changed = deepcopy(frames)
            changed[0]['payload'][component] = {'changed':True}
            with self.subTest(component=component),self.assertRaises(ValueError):
                entry._compare_anchors(SimpleNamespace(iter_records=lambda:iter(changed)),selection,reference)
        self.assertIs(tail.TelemetrySampler,previous.TelemetrySampler)
        self.assertIs(tail.summarize_telemetry,previous.summarize_telemetry)

    def test_completion_counts_seven_times_three_without_counting_anchor_as_new(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            completion = {'exit_code':0,'stop_reason':None,'supervisor_error':None,
                          'actual_exit_observed_utc':'2026-11-06T00:20:00+00:00',
                          'tracked_processes_alive_after_cleanup':0}
            phases = ('initial_frozen_source_hash','freeze_tail_selection','seven_source_extract',
                      'tail_repeat_0','tail_repeat_1','tail_repeat_2','final_frozen_source_hash')
            for name,value in [('supervisor_completion.json',completion),
                               ('tracked_process_identities.json',{'identities':[],'live_after_cleanup':0}),
                               *((phase+'_receipt.json',{'completed':True}) for phase in phases)]:
                (root/name).write_bytes(cp.encoded(value))
            done = {'repeats':3,'new_keys':6,'anchor_keys':1,'queries_per_repeat':7,'engineering_checks':21}
            (root/'done.json').write_bytes(cp.encoded(done))
            self.assertEqual(set(entry._completed(root)[1]),set(phases))
            for field,value in (('repeats',2),('new_keys',7),('anchor_keys',0),('queries_per_repeat',10),('engineering_checks',30)):
                (root/'done.json').write_bytes(cp.encoded(dict(done,**{field:value})))
                with self.subTest(field=field),self.assertRaises(ValueError):
                    entry._completed(root)
            (root/'done.json').write_bytes(cp.encoded(done))
            (root/'tail_repeat_2_receipt.json').write_bytes(cp.encoded({'completed':False}))
            with self.assertRaises(ValueError):
                entry._completed(root)


if __name__ == '__main__':
    unittest.main()
