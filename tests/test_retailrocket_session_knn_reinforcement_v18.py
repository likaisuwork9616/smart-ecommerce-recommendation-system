"""Synthetic V18 history, anchors, three ledgers, same-key costs, and telemetry."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_reinforcement_v18 as reinforcement
from scripts import run_retailrocket_session_knn_reinforcement_v18 as entry
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_joint_cost_v5 import POLICY
from tests import test_retailrocket_session_knn_sql_v4 as sql_fixture


A, B = '1101/n4/v4', '1101/n5/v4'
HISTORY = ('V3','V6','V7',*('V'+str(v) for v in range(8,17)))


def digest(value):
    return hashlib.sha256(json.dumps(value,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def specification():
    return {'selection':{'quota_by_cell':{A:4,B:4},'anchor_quota_by_cell':{A:1,B:1},
                         'planned_new_queries':8,'planned_unique_queries':10,
                         'prefix_with_terminator':'k1-reinforcement-v18-20261106\x00'},
            'quotas':[{'cell':cell,'population':9,'historical_exclusions':3,'eligible':6,
                       'planned_new_queries':4,'planned_anchor_queries':1} for cell in (A,B)],
            'measurement':{'fresh_repeats':3,'queries_per_repeat':10,'expected_engineering_checks':30},
            'telemetry':{'interval_seconds':.2,'process_name_prefix':'ollama'}}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'roster.jsonl'
        shapes = [(10,200)]*230
        for ordinal,shape in {0:(650,3000),1:(1200,3000),2:(700,3500),3:(1400,3500),
                              208:(550,2500),209:(1600,4000)}.items():
            shapes[ordinal] = shape
        shapes[218:224] = [(500,2500),(550,2600),(600,2800),(700,3500),(800,5000),(999,9999)]
        shapes[224:230] = [(1000,2000),(1200,3000),(2000,5000),(3000,7500),(4000,9999),(4999,9999)]
        self.rows = []
        for i,(neighbors,upper) in enumerate(shapes):
            key = [str(171011+i),0,i]
            self.rows.append({'key':key,'key_sha256':digest(key),'original_ordinal':i,
                              'eligible_neighbors':neighbors,'vote_memberships_upper':upper,'causal_candidates':1,
                              'variable_scalar_slots':1+6*min(neighbors,500),'history_sha256':digest([str(i)]),
                              'history_size':1,'posting_work':neighbors,'current_session_excluded':0})
        groups = [list(range(2,66)),[0,1,*range(64,110)],list(range(110,144))]
        groups.extend(list(range(start,start+8)) for start in range(144,208,8))
        groups.append(list(range(208,218)))
        self.histories = {}
        for name,ordinals in zip(HISTORY,groups,strict=True):
            probes = []
            for ordinal in ordinals:
                row = deepcopy(self.rows[ordinal])
                if name == 'V3':
                    del row['original_ordinal']
                else:
                    target = A if ordinal in (0,2,208) else B if ordinal in (1,3,209) else '0000/n2/v2'
                    row['cell'] = target.split('/')[0] if name == 'V6' else target
                probes.append(row)
            self.histories[name] = {'probes':probes}
        self.histories['V6']['population'] = {
            'selection_policy':POLICY,'complete':True,'total_queries':230,'expected_queries':230,
            'p90_nearest_rank':{'eligible_neighbors':500,'vote_memberships_upper':2000,
                                'causal_candidates':1000,'variable_scalar_slots':601},
            'cells':{'1101':{'population_queries':18},'0000':{'population_queries':212}}}
        self.seal()
        self.spec = specification()

    def seal(self):
        data = b''.join(cp.encoded(row) for row in self.rows)
        self.path.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        self.histories['V6']['population'].update(roster_sha256=sha,roster_bytes=len(data))
        for name in HISTORY[2:]:
            self.histories[name]['roster_sha256'] = sha

    def choose(self, **kwargs):
        return reinforcement.select_reinforcement_roster(self.path,self.histories,self.spec,**kwargs)

    def audit(self, selected, **kwargs):
        return reinforcement.audit_reinforcement_order(self.path,selected,self.histories,self.spec,**kwargs)

    def test_fixed_hash_subset_excludes_all_218_history_but_retains_two_old_anchors(self):
        historical = {p['key_sha256'] for group in self.histories.values() for p in group['probes']}
        self.assertEqual(len(historical),218)
        selected = self.choose()
        self.assertEqual([p['original_ordinal'] for p in selected['probes']], [0,1,219,220,221,222,225,226,228,229])
        self.assertEqual((selected['new_keys'],selected['anchor_keys']),(8,2))
        self.assertEqual([p['original_ordinal'] for p in selected['probes'] if p['sample_role']=='anchor'],[0,1])
        self.assertTrue(all(p['key_sha256'] not in historical for p in selected['probes'] if p['sample_role']=='new'))
        self.assertTrue(all(p['key_sha256'] in historical for p in selected['probes'] if p['sample_role']=='anchor'))
        self.audit(selected)
        self.spec['quotas'].reverse()
        self.histories['V6']['probes'].reverse()
        self.assertEqual(self.choose(),selected)

    def test_changed_last_history_overlap_identity_or_anchor_is_rejected(self):
        original = deepcopy(self.histories)
        for change in ('missing_v16','last_duplicate','last_overlap','history_sha','wrong_cell','missing_anchor'):
            self.histories = deepcopy(original)
            if change == 'missing_v16':
                self.histories['V16']['probes'].pop()
            elif change == 'last_duplicate':
                self.histories['V16']['probes'][0] = deepcopy(self.histories['V16']['probes'][1])
            elif change == 'last_overlap':
                self.histories['V16']['probes'][0] = deepcopy(self.histories['V15']['probes'][0])
            elif change == 'history_sha':
                self.histories['V16']['probes'][0]['history_sha256'] = 'f'*64
            elif change == 'wrong_cell':
                self.histories['V16']['probes'][0]['cell'] = B
            else:
                # Preserve all cohort sizes and the 218-key union while removing the n4 V6 anchor.
                anchor = self.histories['V6']['probes'][0]
                replacement = self.histories['V16']['probes'][2]
                self.histories['V6']['probes'][0] = dict(replacement,cell='0000')
                self.histories['V16']['probes'][2] = dict(anchor,cell=A)
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.choose()

    def test_frozen_quota_seed_three_repeats_and_capacity_cannot_be_changed(self):
        for change in ('salt','new_total','anchor_as_new','quota_transfer','capacity','repeat_count','telemetry_interval'):
            self.spec = specification()
            if change == 'salt':
                self.spec['selection']['prefix_with_terminator'] = 'k1-reinforcement-v18-20261106'
            elif change == 'new_total':
                self.spec['selection']['planned_new_queries'] = 10
            elif change == 'anchor_as_new':
                self.spec['selection']['anchor_quota_by_cell'][A] = 0
            elif change == 'quota_transfer':
                self.spec['selection']['quota_by_cell'].update({A:3,B:5})
            elif change == 'capacity':
                self.spec['quotas'][0].update(eligible=3,historical_exclusions=6)
            elif change == 'repeat_count':
                self.spec['measurement']['fresh_repeats'] = 2
            else:
                self.spec['telemetry']['interval_seconds'] = 1.
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.choose()

    def test_independent_sort_changed_source_and_stop_are_fail_closed(self):
        selected = self.choose()
        for change in ('replacement','role','order','count'):
            altered = deepcopy(selected)
            if change == 'replacement':
                altered['probes'][2] = dict(self.rows[218],cell=A,sample_role='new')
            elif change == 'role':
                altered['probes'][0]['sample_role'] = 'new'
            elif change == 'order':
                altered['probes'].reverse()
            else:
                altered['new_keys'] = 10
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.audit(altered)
        def stop():
            raise TimeoutError('synthetic absolute deadline')
        with self.assertRaises(TimeoutError):
            self.choose(watch=stop)
        with self.assertRaises(TimeoutError):
            self.audit(selected,watch=stop)
        original = self.path.read_bytes()
        for changed in (original.replace(b'\n',b' \n'),b''.join(original.splitlines(keepends=True)[:-1])):
            self.path.write_bytes(changed)
            with self.assertRaises(ValueError):
                self.choose()
            with self.assertRaises(ValueError):
                self.audit(selected)


def sql_case(cleanup, n4_count=600):
    oracle = sql_fixture.ExactRankingTests()
    sessions = {(str(i),0): {'1','2','3','9999'} | ({'4'} if i>=550 else set()) for i in range(n4_count)}
    sessions.update({(str(2000+i),0): {'200','201','202','9999'} | ({'203'} if i>=550 else set()) for i in range(1000)})
    catalog = {item:0 for members in sessions.values() for item in members}
    catalog['9999'] = 100
    oracle.fixture(sessions,catalog=catalog)
    cleanup(oracle.doCleanups)
    probes,queries,predictions = [],[],[]
    for i in range(10):
        cell,seed,neighbors = (A,'1',n4_count) if i<5 else (B,'200',1000)
        upper = 2000+min(500,max(0,neighbors-550))
        key = [str(171011+i),0,100]
        pred,work = oracle.check([seed],current=tuple(key[:2]),at=100)
        probes.append({'key':key,'key_sha256':digest(key),'original_ordinal':i,'cell':cell,
                       'sample_role':'anchor' if i in (0,5) else 'new','eligible_neighbors':neighbors,
                       'vote_memberships_upper':upper,'posting_work':neighbors,'history_size':1,
                       'causal_candidates':len(catalog)-1,'current_session_excluded':0})
        queries.append({'subset_ordinal':i,'original_ordinal':i,'key_sha256':digest(key),'sql_workload':work})
        predictions.append(pred)
    return probes,{'queries':queries},predictions


def timing_case():
    probes = []
    for i in range(10):
        key = [str(191001+i),0,i]
        probes.append({'key':key,'key_sha256':digest(key),'original_ordinal':i,'cell':A if i<5 else B,
                       'sample_role':'anchor' if i in (0,5) else 'new'})
    repeats = []
    for repeat in range(3):
        queries,events,budgets,commits = [],[],[],[]
        for i,probe in enumerate(probes):
            if i == 0:
                verify,append = ((9.,1.),(8.,4.),(11.,3.))[repeat]
            elif i == 5:
                verify,append = ((29.,1.),(19.,1.),(24.,1.))[repeat]
            else:
                verify,append = (19.+repeat,1.) if i<5 else (49.+repeat,1.)
            queries.append({'subset_ordinal':i,'original_ordinal':i,'key_sha256':probe['key_sha256'],
                            'verification_seconds':verify,'rank_seconds':verify/2,
                            'rank_stages_seconds':{'sql_selected_votes_and_accumulation':verify/4,
                                                  'exact_neighbor_selection':verify/4},
                            'checkpoint_append_seconds':append+5.,'append_without_commit_seconds':append+2.,
                            'chunk_commit_seconds':3.})
            events.append({'subset_ordinal':i,'completed':True,'frame_bytes':64,'seconds':append+5.,
                           'unpartitioned_seconds':0.,'parts_seconds':{'budget_check':2.,'guards_and_key':0.,
                               'frame_encode':append,'payload_open':0.,'payload_write':0.,
                               'pending_and_trigger':0.,'nested_flush':3.}})
            budgets.append({'context':'query_append','subset_ordinal':i,'stage':None,'completed':True,'seconds':2.})
            commits.append({'records':1,'completed':True,'seconds':3.,'payload_bytes':64})
        measured = {'queries':queries,'verified_subset_queries':10,'committed_prefix_rows':0,
                    'chunk_commits':commits,'setup_seconds':.25,'tail_flush_and_eof_seal_seconds':.5}
        observer = object.__new__(DetailedTimedStore)
        observer.append_events,observer.budget_events,observer.commit_events = events,budgets,commits
        repeats.append({'measured':measured,'observations':{'append_events':events,'budget_events':budgets,
                                                           'detail':observer.detailed_cost_summary(measured)}})
    return {'probes':probes,'new_keys':8,'anchor_keys':2,'roster_sha256':'f'*64},repeats


class WorkloadAndRepeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = sql_case(cls.addClassCleanup)

    def test_both_capped_cells_keep_four_new_one_anchor_and_exact_membership_counts(self):
        workload = reinforcement.sample_workload(*self.native)
        fields = ('neighbor_pool_rows_hashed','sql_selected_rows_inserted','vote_upper_sum',
                  'sql_vote_membership_rows_returned','exact_vote_additions','boundary_ties_total','boundary_ties_excluded')
        self.assertEqual(tuple(workload[A][field] for field in fields),(3000,2500,10250,10000,7500,2750,250))
        self.assertEqual(tuple(workload[B][field] for field in fields),(5000,2500,12250,10000,7500,2750,250))
        for cell in (A,B):
            self.assertEqual((workload[cell]['new_queries'],workload[cell]['anchor_queries']),(4,1))
            self.assertEqual(workload[cell]['boundary_queries'],5)

    def test_exact500_pool_and_frozen_neighbor_vote_bands_cannot_drift(self):
        native = sql_case(self.addCleanup,n4_count=500)
        total = reinforcement.sample_workload(*native)[A]
        self.assertEqual(total['exact500_queries'],5)
        self.assertEqual(total['boundary_ties_excluded'],0)
        self.assertEqual(total['vote_upper_sum'],total['sql_vote_membership_rows_returned'])
        for change in ('full_pool','exact_bound','role','n4_low','n4_high','n5_low','n5_high','vote_low','vote_high'):
            probes,measured,predictions = deepcopy(native)
            if change == 'full_pool':
                predictions[0]['neighbor_pool_sha256'] = 'a'*64
            elif change == 'exact_bound':
                probes[0]['vote_memberships_upper'] += 1
            elif change == 'role':
                probes[0]['sample_role'] = 'new'
            elif change == 'n4_low':
                probes[0]['eligible_neighbors'] = 499
            elif change == 'n4_high':
                probes[0]['eligible_neighbors'] = 1000
            elif change == 'n5_low':
                probes[5]['eligible_neighbors'] = 999
            elif change == 'n5_high':
                probes[5]['eligible_neighbors'] = 5000
            else:
                probes[5]['vote_memberships_upper'] = 1999 if change=='vote_low' else 10000
            with self.subTest(change=change),self.assertRaises(ValueError):
                reinforcement.sample_workload(probes,measured,predictions)

    def test_all_three_physical_ledgers_are_checked_even_when_only_third_is_changed(self):
        probes,measured,predictions = self.native
        workload = reinforcement.sample_workload(*self.native)
        with tempfile.TemporaryDirectory() as temp:
            root,repeats = Path(temp),[]
            deadline = (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            for repeat,chunk in enumerate((3,4,7)):
                folder = root/f'repeat_{repeat}'/'verified_subset'
                binding = {'scope':'V18 synthetic three-ledger evidence'}
                store = DetailedTimedStore.create(folder,binding,deadline,120,expected_queries=10,
                    required_stages=('reconstruction','queries'),chunk_queries=chunk)
                with store.writer():
                    store.seal_stage('reconstruction',{'synthetic':True})
                    for i,(probe,prediction) in enumerate(zip(probes,predictions,strict=True)):
                        store.append_verified(i,probe['key'],{'expected':{'key':probe['key'],'predictions':{'K1':prediction}}})
                    store.flush_chunk()
                    store.seal_stage('queries',{'queries':10,'paired_streams_eof_checked':True})
                saved = DetailedTimedStore.open(folder,binding)
                repeats.append({'proof':ledger_proof(saved,probes),'workload_by_cell':deepcopy(workload)})
            reinforcement.compare_repeats(root,repeats)
            with self.assertRaises(ValueError):
                reinforcement.compare_repeats(root,repeats[:2])
            changed = deepcopy(repeats)
            changed[2]['workload_by_cell'][A]['boundary_ties_excluded'] += 1
            with self.assertRaises(ValueError):
                reinforcement.compare_repeats(root,changed)
            payload = next((root/'repeat_2'/'verified_subset'/'payloads').glob('*.jsonl'))
            payload.write_bytes(payload.read_bytes()+b'{}\n')
            with self.assertRaises(ValueError):
                reinforcement.compare_repeats(root,repeats)

    def test_same_key_fast_slow_components_conserve_cost_and_old_anchors_are_not_new(self):
        selection,repeats = timing_case()
        result = reinforcement.summarize_repeats(selection,repeats,specification())
        scope = result['scope']
        self.assertEqual((scope['new_keys'],scope['anchor_keys'],scope['engineering_checks']),(8,2,30))
        self.assertEqual((scope['distinct_historically_verified_queries'],scope['distinct_comparable_queries']), (226,164))
        self.assertEqual((scope['globally_covered_cells'],scope['globally_uncovered_cells']),(55,0))
        for cell in (A,B):
            self.assertEqual(result['cells'][cell]['roles']['new']['distinct_queries'],4)
            self.assertEqual(result['cells'][cell]['roles']['anchor']['distinct_queries'],1)
            self.assertEqual(result['cells'][cell]['repeat_observations'],15)
        a = result['cells'][A]['max_same_query_range_decomposition']
        b = result['cells'][B]['max_same_query_range_decomposition']
        self.assertEqual((a['sample_role'],a['fast_repeat'],a['slow_repeat'],a['fast_core_seconds'],a['slow_core_seconds']),
                         ('anchor',0,2,10.,14.))
        self.assertEqual((b['sample_role'],b['fast_repeat'],b['slow_repeat'],b['fast_core_seconds'],b['slow_core_seconds']),
                         ('anchor',1,0,20.,30.))
        self.assertEqual(a['delta_seconds']['core'],4.)
        self.assertEqual(a['delta_seconds']['verification'],2.)
        self.assertEqual(a['delta_seconds']['append_without_commit_or_budget'],2.)
        self.assertEqual(a['delta_seconds']['rank'],1.)
        self.assertEqual(a['delta_seconds']['vote_sql_and_accumulation'],.5)
        for decomposition in (a,b):
            delta = decomposition['delta_seconds']
            self.assertEqual(delta['core'],delta['verification']+delta['append_without_commit_or_budget'])
        self.assertEqual(result['cells'][B]['pooled_observations_seconds']['core']['range'],32.)
        self.assertEqual(b['delta_seconds']['core'],10.)
        public = json.dumps(result)
        self.assertTrue(all(p['key_sha256'] not in public for p in selection['probes']))

    def test_missing_third_repeat_changed_identity_roles_and_raw_timing_cannot_publish_costs(self):
        for change in ('missing_repeat','identity','role','budget_detail','negative'):
            selection,repeats = timing_case()
            if change == 'missing_repeat':
                repeats.pop()
            elif change == 'identity':
                repeats[2]['measured']['queries'][0]['original_ordinal'] += 1
            elif change == 'role':
                selection['probes'][0]['sample_role'] = 'new'
            elif change == 'budget_detail':
                repeats[2]['observations']['detail']['budget']['rows'][0]['query_append_budget_seconds'] += 1
            else:
                repeats[2]['measured']['queries'][0]['verification_seconds'] = -1.
            with self.subTest(change=change),self.assertRaises(ValueError):
                reinforcement.summarize_repeats(selection,repeats,specification())


def telemetry_case(repeat_index=0, times=(0.,.2,.4,.6)):
    start = datetime(2026,11,6,tzinfo=timezone.utc)
    records = []
    for i,elapsed in enumerate(times):
        def process(pid,name,creation,cpu,rss):
            return {'pid':pid,'name':name,'create_time':creation,'cpu_user_seconds':cpu,
                    'cpu_system_seconds':0.,'rss_bytes':rss,'status':'observed'}
        records.append({'sequence':i,'repeat_index':repeat_index,
                        'kind':'start' if i==0 else 'end' if i==len(times)-1 else 'periodic',
                        'monotonic_seconds':elapsed,'observed_utc':(start+timedelta(seconds=elapsed)).isoformat(),
                        'system_cpu_percent':(None,50.,75.,25.)[i],'logical_cpus':4,
                        'memory':{'total_bytes':10000,'available_bytes':8000,'used_bytes':2000,'percent':20.},
                        'disk_io':{'read_count':2*i,'write_count':i,'read_bytes':200*i,
                                   'write_bytes':100*i,'read_time':10*i,'write_time':5*i},
                        'disk_io_status':'ok','worker':process(1000,'python.exe',10.,i*.3,1000),
                        'ollama':[process(2000,'OLLAMA.exe',20.,i*.1,2000)],
                        'ollama_scan_status':'ok','collector_seconds':.01})
    return records


class TelemetryTests(unittest.TestCase):
    def test_actual_repeat_intervals_keep_system_and_single_core_denominators_distinct(self):
        result = reinforcement.summarize_telemetry(telemetry_case(),0)
        self.assertEqual(result['samples'],4)
        self.assertAlmostEqual(result['duration_seconds'],.6)
        self.assertAlmostEqual(result['system_cpu_percent']['mean'],50.)
        self.assertEqual((result['system_cpu_percent']['min'],result['system_cpu_percent']['max']),(25.,75.))
        self.assertAlmostEqual(result['worker']['cpu_core_percent']['mean'],150.)
        self.assertAlmostEqual(result['ollama']['cpu_core_percent']['mean'],50.)
        self.assertEqual(result['worker']['valid_cpu_intervals'],3)
        self.assertEqual(result['disk_io_delta']['read_bytes'],600)
        self.assertEqual(result['available_memory_bytes']['mean'],8000.)
        self.assertEqual(result['coverage']['missing_periodic_intervals'],0)

    def test_scheduling_gaps_and_unavailable_optional_metrics_are_not_filled_with_zero(self):
        records = telemetry_case(times=(0.,.2,.8,1.))
        result = reinforcement.summarize_telemetry(records,0)
        self.assertAlmostEqual(result['coverage']['max_gap_seconds'],.6)
        self.assertEqual(result['coverage']['missing_periodic_intervals'],2)
        self.assertAlmostEqual(result['system_cpu_percent']['mean'],60.)
        for row in records:
            row['disk_io'],row['disk_io_status'] = None,'AccessDenied'
            row['ollama_scan_status'] = 'AccessDenied'
            row['ollama'][0].update(create_time=None,cpu_user_seconds=None,cpu_system_seconds=None,
                                    rss_bytes=None,status='AccessDenied')
        missing = reinforcement.summarize_telemetry(records,0)
        self.assertIsNone(missing['disk_io_delta'])
        self.assertEqual(missing['disk_unavailable_or_reset_intervals'],3)
        self.assertIsNone(missing['ollama']['cpu_core_percent'])
        self.assertIsNone(missing['ollama']['rss_bytes'])
        self.assertEqual(missing['ollama']['unavailable_observations'],4)
        self.assertEqual(missing['ollama_scan_status_counts'],{'AccessDenied':4})

    def test_pid_reuse_counter_reset_and_missing_process_are_never_bridged(self):
        records = telemetry_case()
        for i in range(1,4):
            records[i]['ollama'][0].update(create_time=21.,cpu_user_seconds=1000.+.1*(i-1))
        reused = reinforcement.summarize_telemetry(records,0)['ollama']
        self.assertEqual(reused['observed_processes'],2)
        self.assertEqual(reused['valid_cpu_intervals'],2)
        self.assertGreater(reused['discontinuous_cpu_intervals'],0)
        self.assertAlmostEqual(reused['cpu_core_percent']['max'],50.)
        records = telemetry_case()
        records[1]['ollama'][0].update(create_time=None,cpu_user_seconds=None,cpu_system_seconds=None,
                                     rss_bytes=None,status='NoSuchProcess')
        missing = reinforcement.summarize_telemetry(records,0)['ollama']
        self.assertEqual(missing['unavailable_observations'],1)
        self.assertEqual(missing['valid_cpu_intervals'],1)
        records = telemetry_case()
        records[2]['ollama'][0]['cpu_user_seconds'] = .05
        reset = reinforcement.summarize_telemetry(records,0)['ollama']
        self.assertEqual(reset['valid_cpu_intervals'],2)
        self.assertGreater(reset['discontinuous_cpu_intervals'],0)

    def test_required_brackets_two_cpu_intervals_and_monotonic_bounds_are_enforced(self):
        for change in ('missing_end','too_short','duplicate_sequence','wrong_repeat','clock_backwards',
                       'utc_backwards','first_cpu','cpu_missing','cpu_over100','memory','logical_cpus','wrong_process'):
            records = telemetry_case()
            if change == 'missing_end':
                records[-1]['kind'] = 'periodic'
            elif change == 'too_short':
                records = records[:1]+records[-1:]
                records[-1]['sequence'] = 1
            elif change == 'duplicate_sequence':
                records[2]['sequence'] = 1
            elif change == 'wrong_repeat':
                records[2]['repeat_index'] = 1
            elif change == 'clock_backwards':
                records[2]['monotonic_seconds'] = .1
            elif change == 'utc_backwards':
                records[2]['observed_utc'] = '2026-11-05T00:00:00+00:00'
            elif change == 'first_cpu':
                records[0]['system_cpu_percent'] = 0.
            elif change == 'cpu_missing':
                records[2]['system_cpu_percent'] = None
            elif change == 'cpu_over100':
                records[2]['system_cpu_percent'] = 101.
            elif change == 'memory':
                records[2]['memory']['available_bytes'] = 10001
            elif change == 'logical_cpus':
                records[2]['logical_cpus'] = 8
            else:
                records[2]['ollama'][0]['name'] = 'unrelated.exe'
            with self.subTest(change=change),self.assertRaises(ValueError):
                reinforcement.summarize_telemetry(records,0)

    def test_sampler_reads_only_scoped_names_primes_cpu_on_its_thread_and_joins(self):
        class Process:
            def __init__(self,pid,name,step):
                self.pid,self.info,self.step,self.calls = pid,{'pid':pid,'name':name},step,0
            def oneshot(self):
                return nullcontext()
            def name(self):
                return self.info['name']
            def create_time(self):
                return float(self.pid)
            def cpu_times(self):
                self.calls += 1
                return SimpleNamespace(user=self.calls*self.step,system=0.)
            def memory_info(self):
                return SimpleNamespace(rss=1000)
        worker,ollama,unrelated = Process(1000,'python.exe',.3),Process(2000,'OLLAMA.exe',.1),Process(3000,'other.exe',1.)
        stop_values = iter((False,False,True))
        sampler = reinforcement.TelemetrySampler()
        sampler._stop = SimpleNamespace(wait=lambda _:next(stop_values),set=lambda:None)
        memory = SimpleNamespace(total=10000,available=8000,used=2000,percent=20.)
        disk = SimpleNamespace(_asdict=lambda:{'read_bytes':0,'write_bytes':0})
        clock_values = [value for start in (0.,.2,.4,.6) for value in (start,start+.01)]
        with patch.object(reinforcement.psutil,'Process',return_value=worker), \
             patch.object(reinforcement.psutil,'process_iter',return_value=[ollama,unrelated]) as processes, \
             patch.object(reinforcement.psutil,'virtual_memory',return_value=memory), \
             patch.object(reinforcement.psutil,'disk_io_counters',return_value=disk), \
             patch.object(reinforcement.psutil,'cpu_count',return_value=4), \
             patch.object(reinforcement.psutil,'cpu_percent',side_effect=(91.,50.,75.,25.)) as cpu, \
             patch.object(reinforcement,'perf_counter',side_effect=clock_values):
            sampler.start(0)
            sampler.stop()
        self.assertFalse(sampler._thread.is_alive())
        self.assertEqual([r['kind'] for r in sampler.records],['start','periodic','periodic','end'])
        self.assertIsNone(sampler.records[0]['system_cpu_percent'])
        self.assertEqual(unrelated.calls,0)
        self.assertTrue(all(call.kwargs == {'interval':None} for call in cpu.call_args_list))
        self.assertTrue(all(call.args == (['pid','name'],) for call in processes.call_args_list))
        self.assertAlmostEqual(reinforcement.summarize_telemetry(sampler.records,0)['worker']['cpu_core_percent']['mean'],150.)
        with self.assertRaises(ValueError):
            sampler.start(1)


class RunnerEvidenceTests(unittest.TestCase):
    def test_original_anchor_entire_payload_matches_despite_new_subset_ordinals(self):
        selection,_ = timing_case()
        frames = [{'ordinal':i,'key':p['key'],'payload':{
            'expected':{'key':p['key'],'predictions':{'K1':{'synthetic':i}}},
            'precise':{'K1':[i,1]},'delta_hex':{'K1':'0x0.0p+0'}}}
            for i,p in enumerate(selection['probes'])]
        old_frames = [dict(deepcopy(frames[i]),ordinal=37+i) for i in (0,5)]
        reference = {digest(frame['key']):frame['payload'] for frame in old_frames}
        entry._compare_anchors(SimpleNamespace(iter_records=lambda:iter(frames)),selection,reference)
        for component in ('expected','precise','delta_hex'):
            changed = deepcopy(frames)
            changed[0]['payload'][component] = {'changed':True}
            with self.subTest(component=component),self.assertRaises(ValueError):
                entry._compare_anchors(SimpleNamespace(iter_records=lambda:iter(changed)),selection,reference)

    def test_completion_requires_all_three_rounds_eight_new_two_anchors_and_thirty_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            completion = {'exit_code':0,'stop_reason':None,'supervisor_error':None,
                          'actual_exit_observed_utc':'2026-11-06T00:20:00+00:00',
                          'tracked_processes_alive_after_cleanup':0}
            phases = ('initial_frozen_source_hash','freeze_reinforcement_selection','seven_source_extract',
                      'reinforcement_repeat_0','reinforcement_repeat_1','reinforcement_repeat_2','final_frozen_source_hash')
            for name,value in [('supervisor_completion.json',completion),
                               ('tracked_process_identities.json',{'identities':[],'live_after_cleanup':0}),
                               *((phase+'_receipt.json',{'completed':True}) for phase in phases)]:
                (root/name).write_bytes(cp.encoded(value))
            done = {'repeats':3,'new_keys':8,'anchor_keys':2,'queries_per_repeat':10,'engineering_checks':30}
            (root/'done.json').write_bytes(cp.encoded(done))
            self.assertEqual(set(entry._completed(root)[1]),set(phases))
            for field,value in (('repeats',2),('new_keys',10),('anchor_keys',0),('engineering_checks',20)):
                (root/'done.json').write_bytes(cp.encoded(dict(done,**{field:value})))
                with self.subTest(field=field),self.assertRaises(ValueError):
                    entry._completed(root)
            (root/'done.json').write_bytes(cp.encoded(done))
            (root/'reinforcement_repeat_2_receipt.json').write_bytes(cp.encoded({'completed':False}))
            with self.assertRaises(ValueError):
                entry._completed(root)

    def test_load_spans_bracket_each_complete_verifier_and_all_three_rounds_are_sequential(self):
        start = datetime(2026,11,6,tzinfo=timezone.utc)
        request = {'created_utc':(start-timedelta(seconds=1)).isoformat(),
                   'deadline_utc':(start+timedelta(seconds=1800)).isoformat()}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(3):
                base = index*10.
                records = telemetry_case(index,tuple(base+t for t in (0.,.2,.4,.6)))
                span = {'repeat_index':index,'completed':True,'start_monotonic_seconds':base+.02,
                        'end_monotonic_seconds':base+.58,'start_utc':(start+timedelta(seconds=base+.02)).isoformat(),
                        'end_utc':(start+timedelta(seconds=base+.58)).isoformat()}
                folder = root/f'repeat_{index}'
                folder.mkdir()
                (folder/'telemetry_records.json').write_bytes(cp.encoded({'repeat_index':index,'records':records}))
                (folder/'verifier_span.json').write_bytes(cp.encoded(span))
                entry._check_telemetry_span(records,span,request,index)
            entry._check_repeat_spans(root,request)
            for change in ('start_unbracketed','end_unbracketed','wrong_round','incomplete'):
                changed = deepcopy(span)
                if change == 'start_unbracketed':
                    changed['start_monotonic_seconds'] = base
                elif change == 'end_unbracketed':
                    changed['end_monotonic_seconds'] = base+.7
                elif change == 'wrong_round':
                    changed['repeat_index'] = 1
                else:
                    changed['completed'] = False
                with self.subTest(change=change),self.assertRaises(ValueError):
                    entry._check_telemetry_span(records,changed,request,index)
            # Each round remains internally valid, but the third observer overlaps the second.
            shifted = telemetry_case(2,(10.2,10.4,10.6,10.8))
            overlapping = dict(span,start_monotonic_seconds=10.22,end_monotonic_seconds=10.78,
                               start_utc=(start+timedelta(seconds=10.22)).isoformat(),
                               end_utc=(start+timedelta(seconds=10.78)).isoformat())
            (folder/'telemetry_records.json').write_bytes(cp.encoded({'repeat_index':2,'records':shifted}))
            (folder/'verifier_span.json').write_bytes(cp.encoded(overlapping))
            entry._check_telemetry_span(shifted,overlapping,request,2)
            with self.assertRaises(ValueError):
                entry._check_repeat_spans(root,request)


if __name__ == '__main__':
    unittest.main()
