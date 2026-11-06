"""Synthetic-only V20 observers: frozen science, signed clocks and fixed reuse."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import count
import json
import math
from pathlib import Path
import tempfile
from time import perf_counter
from unittest.mock import patch
from uuid import UUID
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_diagnostics_v20 as diagnostic
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import run_retailrocket_session_knn_diagnostics_v20 as entry
from scripts import run_retailrocket_session_knn_v2 as sources
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof, NAMES
from tests import test_retailrocket_session_knn_pair_v4 as pair_fixtures
from tests import test_retailrocket_session_knn_validation as validation_fixtures
from tests import test_retailrocket_session_knn_reinforcement_v18 as load_fixtures
from tests import test_retailrocket_session_knn_tail_v19 as tail_fixtures
from tests.test_retailrocket_session_knn_checkpoint_v2 import FakeClock, FakeProcesses


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cp.encoded(value))


def span(wall, cpu):
    wall, cpu = round(wall*1e9), round(cpu*1e9)
    return {'wall_ns':wall, 'thread_cpu_ns':cpu, 'wall_minus_thread_cpu_ns':wall-cpu}


def taps(walls, cpus):
    result = [{'wall_seconds':100., 'thread_cpu_ns':100_000_000_000}]
    for wall, cpu in zip(walls, cpus, strict=True):
        result.append({'wall_seconds':result[-1]['wall_seconds']+wall,
                       'thread_cpu_ns':result[-1]['thread_cpu_ns']+round(cpu*1e9)})
    return result


def hand_accounting():
    """One row: overlap 4 wall/8 CPU; append 21 wall, including commit 5 and budget 1."""
    rank_walls = (1.,4.,1.,1.,1.,1.,1.)
    append_walls = (6.,1.,2.,1.,2.,1.,5.)
    row = {'subset_ordinal':0, 'verification_seconds':20., 'rank_seconds':10.,
           'rank_stages_seconds':dict(zip(diagnostic.RANK_PHASES, rank_walls, strict=True)),
           'checkpoint_append_seconds':21., 'append_without_commit_seconds':16., 'chunk_commit_seconds':5.,
           'sql_workload':{'sql_overlap_groups_returned':2, 'sql_overlap_membership_matches':3,
                           'neighbor_pool_rows_hashed':1}}
    original = {'subset_ordinal':0, 'completed':True, 'frame_bytes':64, 'seconds':19.,
                'unpartitioned_seconds':1.,
                'parts_seconds':dict(zip(diagnostic.APPEND_PHASES, append_walls, strict=True))}
    budgets = [{'context':context, 'subset_ordinal':0, 'stage':None, 'completed':True, 'seconds':1.}
               for context in ('query_append','chunk_commit')]
    commits = [{'records':1, 'completed':True, 'seconds':5., 'payload_bytes':64}]
    measured = {'queries':[row], 'committed_prefix_rows':0, 'verified_subset_queries':1, 'chunk_commits':commits}
    store = object.__new__(DetailedTimedStore)
    store.append_events, store.budget_events, store.commit_events = [original], budgets, commits
    observations = {'append_events':[original], 'budget_events':budgets, 'detail':store.detailed_cost_summary(measured)}
    sql_event = {'subset_ordinal':0, 'completed':True, 'execute_calls':1, 'fetch_calls':3, 'eof_calls':1,
                 'returned_rows':2, 'intersection_sum':3, 'eligible_neighbors':1, 'current_session_excluded':1,
                 'execute':span(1,3), 'fetch':span(1,2), 'terminal_fetch':span(.2,.4),
                 'clock_samples':taps(rank_walls, (1,8,1,1,1,1,1))}
    checks = []
    for context, total, read, parse, publication in (
            ('query_append',(4,3),(1,.5),(1,.5),(1,1)),
            ('chunk_commit',(3,1),(.5,.2),(.5,.2),(1,.3))):
        checks.append({'context':context, 'subset_ordinal':0, 'stage':None,
                       'persist':context=='chunk_commit', 'completed':True, 'total':span(*total),
                       'reads':[{'completed':True, 'text_characters':100,
                                 'read_text':span(*read), 'json_parse':span(*parse)}],
                       'publications':[{'completed':True, 'context':context, 'replace':True,
                                        'total':span(*publication)}]})
    append = {'subset_ordinal':0, 'completed':True, 'budget_checks':checks, 'wrapper_total':span(20,11),
              'clock_samples':taps((*append_walls,1.), (4,.5,1,.5,1,.5,2,.5))}
    return measured, observations, {'sql':[sql_event], 'append':[append]}


class InstrumentationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)




    def test_complete_verifier_keeps_all_four_arm_payloads_and_nested_commit_diagnostics(self):
        with patch.object(pair_fixtures,'make_fixture',side_effect=lambda **kw:validation_fixtures.make_fixture(base=self.root,**kw)):
            root,paths,config,primary,_,database,model,ordinals,binding = pair_fixtures.fixture(boundary=True)
        outputs, workloads = [],[]
        for mode,cls in (('R',DetailedTimedStore),('D',diagnostic.DiagnosticTimedStore)):
            profiles = []
            store = cls.create(root/mode,binding,(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat(),120,
                               source_root=root,expected_queries=len(ordinals),required_stages=('reconstruction','queries'),chunk_queries=1)
            with store.writer():
                store.seal_stage('reconstruction',{'fit_audit':model['fit_audit']})
                measured = diagnostic.make_verifier(mode,profiles if mode=='D' else None)(
                    primary,paths,config,store,model,database,ordinals)
            outputs.append([cp.encoded(frame) for frame in store.iter_records()])
            workloads.append([row['sql_workload'] for row in measured['queries']])
            if mode=='D':
                observations = {'append_events':store.append_events,'budget_events':store.budget_events,
                                'detail':store.detailed_cost_summary(measured)}
                detail = diagnostic.diagnostic_rows(measured,observations,{'sql':profiles,'append':store.append_diagnostics})
                self.assertEqual(len(detail),len(ordinals))
                self.assertEqual([p['eof_calls'] for p in profiles],[1]*len(ordinals))
                self.assertTrue(all(row['nested_commit_budget_publications']>0 for row in detail))
                for row in detail:
                    for clock in ('wall_seconds','thread_cpu_seconds'):
                        self.assertAlmostEqual(sum(part[clock] for part in row['sql_parts'].values()),row['sql_positive_overlap_total'][clock])
                        self.assertAlmostEqual(sum(part[clock] for part in row['append_phases'].values()),row['append_total'][clock])
                self.assertIsNone(store._active_append_diagnostic)
                self.assertIsNone(store._active_budget_diagnostic)
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(workloads[0],workloads[1])

    def make_store(self, cls, name, **options):
        return cls.create(self.root/name,{'kind':'synthetic-v20'},1100.,90.,expected_queries=2,
                          required_stages=('reconstruction','queries'),chunk_queries=1,
                          clock=FakeClock(),process_api=FakeProcesses(),**options)

    def test_append_protocol_bytes_match_v6_and_budget_reads_keep_exclusive_contexts(self):
        stores = []
        for cls in (DetailedTimedStore,diagnostic.DiagnosticTimedStore):
            serial = count(1)
            with patch.object(cp.uuid,'uuid4',side_effect=lambda:UUID(int=next(serial))):
                store = self.make_store(cls,cls.__name__)
                with store.writer():
                    store.seal_stage('reconstruction',{})
                    for i in range(2):
                        store.clock.advance(1.1)
                        store.append_verified(i,['1',0,i],{'synthetic':i})
                    store.flush_chunk()
                    store.seal_stage('queries',{'queries':2,'paired_streams_eof_checked':True})
                stores.append(store)
        for name in ('chunks','payloads','stages'):
            self.assertEqual({p.name:p.read_bytes() for p in (stores[0].folder/name).iterdir()},
                             {p.name:p.read_bytes() for p in (stores[1].folder/name).iterdir()})
        for name in ('run.json','latest.json','budget.json'):
            self.assertEqual((stores[0].folder/name).read_bytes(),(stores[1].folder/name).read_bytes())
        for event in stores[1].append_diagnostics:
            self.assertEqual(len(event['clock_samples']),9)
            checks = event['budget_checks']
            self.assertEqual(Counter(c['context'] for c in checks),{'query_append':1,'chunk_commit':2})
            for check in checks:
                self.assertEqual(len(check['reads']),1)
                self.assertTrue(check['reads'][0]['completed'])
                self.assertGreater(check['reads'][0]['text_characters'],0)
                self.assertEqual({p['context'] for p in check['publications']},{check['context']})

    def test_failed_append_budget_parse_deadline_and_fault_restore_contexts(self):
        for failure in ('json','nonfinite','deadline','payload_half_written','before_manifest_commit'):
            store = self.make_store(diagnostic.DiagnosticTimedStore,failure)
            with store.writer():
                store.seal_stage('reconstruction',{})
                budget = (store.folder/'budget.json').read_bytes()
                if failure in ('json','nonfinite'):
                    (store.folder/'budget.json').write_bytes(b'{' if failure=='json' else b'{"bad":NaN}')
                    expected = ValueError
                elif failure=='deadline':
                    store.clock.advance(90.)
                    expected = cp.BudgetExceeded
                else:
                    def fault(point):
                        if point==failure:
                            raise OSError('same synthetic fault')
                    store.fault = fault
                    expected = OSError
                try:
                    with self.subTest(failure=failure),self.assertRaises(expected):
                        store.append_verified(0,['1',0,0],{})
                    self.assertFalse(store.append_diagnostics[-1]['completed'])
                    self.assertIsNone(store._active_append_diagnostic)
                    self.assertIsNone(store._active_budget_diagnostic)
                    self.assertEqual(store._budget_context,('writer_body',None,None))
                    if failure in ('json','nonfinite'):
                        read = store.append_diagnostics[-1]['budget_checks'][0]['reads'][0]
                        self.assertFalse(read['completed'])
                        self.assertIn('json_parse',read)
                    if failure=='deadline':
                        self.assertTrue((store.folder/'stop_requested.json').exists())
                finally:
                    (store.folder/'budget.json').write_bytes(budget)
                    store.fault = lambda point:None
                    if failure=='deadline':
                        store.clock.advance(-90.)
            self.assertIsNone(store._guard)

    def test_hand_computable_signed_cpu_and_nested_costs_conserve_and_reject_tampering(self):
        measured,observations,raw = hand_accounting()
        result = diagnostic.diagnostic_rows(measured,observations,raw)[0]
        self.assertEqual(result['sql_positive_overlap_total'],{'wall_seconds':4.,'thread_cpu_seconds':8.,'wall_minus_thread_cpu_seconds':-4.})
        self.assertEqual(result['sql_parts']['python_watch_proxy_other']['wall_seconds'],2.)
        self.assertEqual(result['sql_parts']['python_watch_proxy_other']['thread_cpu_seconds'],3.)
        self.assertEqual(result['append_total']['wall_seconds'],19.)
        self.assertEqual(result['append_wrapper_observer_other']['wall_seconds'],1.)
        self.assertEqual(result['append_outer_unobserved_wall_seconds'],1.)
        self.assertEqual(sum(part['wall_seconds'] for part in result['append_budget_check_parts'].values()),6.)
        self.assertEqual((result['direct_budget_publications'],result['nested_commit_budget_publications']),(1,1))
        budget = observations['detail']['budget']['rows'][0]
        self.assertEqual(budget['append_without_commit_or_budget_seconds'],15.)
        self.assertEqual(21.,budget['append_without_commit_or_budget_seconds']+budget['query_append_budget_seconds']+budget['chunk_commit_seconds'])
        summary = diagnostic.summarize_diagnostics(measured,observations,raw)
        self.assertEqual(summary['sql_positive_overlap_total']['wall_minus_thread_cpu_seconds']['minimum'],-4.)
        self.assertIsNone(summary['append_outer_unobserved_thread_cpu_seconds'])
        for change in ('eof','fetch','count','missing_append','negative','nan','cpu_backwards','signed_clamp','child_exceeds','budget_context','old_detail','wrapper'):
            m,o,d = deepcopy((measured,observations,raw))
            if change=='eof': d['sql'][0]['eof_calls']=0
            elif change=='fetch': d['sql'][0]['fetch_calls']=2
            elif change=='count': d['sql'][0]['intersection_sum']=4
            elif change=='missing_append': d['append'].clear()
            elif change=='negative': d['sql'][0]['execute']=span(-1,0)
            elif change=='nan': d['sql'][0]['clock_samples'][0]['wall_seconds']=float('nan')
            elif change=='cpu_backwards': d['sql'][0]['clock_samples'][1]['thread_cpu_ns']=0
            elif change=='signed_clamp': d['sql'][0]['execute']['wall_minus_thread_cpu_ns']=0
            elif change=='child_exceeds': d['sql'][0]['execute']=span(5,3)
            elif change=='budget_context': d['append'][0]['budget_checks'][1]['context']='query_append'
            elif change=='old_detail': o['detail']['budget']['rows'][0]['query_append_budget_seconds']=2.
            else: d['append'][0]['wrapper_total']=span(22,11)
            with self.subTest(change=change),self.assertRaises(ValueError):
                diagnostic.summarize_diagnostics(m,o,d)


class FixedEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def checkpoint(self, folder, probes, payloads, chunk):
        store = DetailedTimedStore.create(folder,{'kind':'V20 fixed-seven fixture'},1100.,90.,
                    expected_queries=7,required_stages=('reconstruction','queries'),chunk_queries=chunk,
                    clock=FakeClock(),process_api=FakeProcesses())
        with store.writer():
            store.seal_stage('reconstruction',{})
            for i,(probe,payload) in enumerate(zip(probes,payloads,strict=True)):
                store.append_verified(i,probe['key'],payload)
            store.flush_chunk()
            store.seal_stage('queries',{'queries':7,'paired_streams_eof_checked':True})
        return store

    def test_all_six_physical_seven_query_ledgers_match_v19_including_nonanchor_payload(self):
        probes,_,_ = tail_fixtures.workload_case()
        selection = {'probes':probes,'new_keys':6,'anchor_keys':1}
        payloads = [{'expected':{'key':p['key'],'synthetic':i},'precise':{'value':str(i)},
                     'delta_hex':{'value':'0x0.0p+0'}} for i,p in enumerate(probes)]
        original = self.checkpoint(self.root/'V19',probes,payloads,3)
        reference = {'proof':ledger_proof(original,probes),'rows':list(original.iter_records()),
                     'raw_frames':list(entry._physical_frames(original.folder))}
        stores = [self.checkpoint(self.root/item['label'],probes,payloads,1+item['round_index']%4) for item in entry.schedule()]
        for store in stores:
            entry._compare_reference(store,selection,reference)
        for component in ('expected','precise','delta_hex'):
            changed = deepcopy(payloads)
            changed[4][component]['changed'] = True
            store = self.checkpoint(self.root/component,probes,changed,2)
            with self.subTest(component=component),self.assertRaises(ValueError):
                entry._compare_reference(store,selection,reference)
        payload = next((stores[5].folder/'payloads').glob('*.jsonl'))
        payload.write_bytes(payload.read_bytes()+b'{}\n')
        with self.assertRaises((ValueError,cp.IntegrityError)):
            entry._compare_reference(stores[5],selection,reference)

    def test_frozen_input_order_and_source_closure_are_required_without_new_selection(self):
        probes,_,_ = tail_fixtures.workload_case()
        selection = {'probes':probes,'new_keys':6,'anchor_keys':1}
        configuration = {'fixed_validation':{'queries':7}}
        ordinals = [{'subset_ordinal':i,'original_ordinal':p['original_ordinal'],'key':p['key']} for i,p in enumerate(probes)]
        put(self.root/'probes.json',selection); put(self.root/'selected/configuration.json',configuration)
        put(self.root/'selected/ordinals.json',ordinals)
        (self.root/'tiny_source.txt').write_bytes(b'bound synthetic input\n')
        put(self.root/'transport.json',{'synthetic':True})
        with patch.object(entry,'ROOT',self.root),patch.object(sources,'ROOT',self.root):
            source,transport = (entry.describe(self.root/name) for name in ('tiny_source.txt','transport.json'))
            binding = {'configuration':configuration,'sources':[source],'transport':transport}
            put(self.root/'binding.json',binding)
            indexed = {'validation_queries':166897,'sampled_queries':7,'sampled_ordinals':[p['original_ordinal'] for p in probes],
                       'source_root':str(self.root),'sources':dict.fromkeys(NAMES,source),'samples':dict.fromkeys(NAMES,{})}
            put(self.root/'index.json',indexed)
            request = {'metadata':{'probes':entry.describe(self.root/'probes.json'),
                       'subset_binding':entry.describe(self.root/'binding.json'),'selected_root':'selected','source_index':'index.json'},
                       'sources':[source,transport]}
            entry.verify_bindings(request['sources'])
            self.assertEqual(entry._fixed_inputs(request)[0],selection)
            for change in ('order','ordinal','missing_source','changed_binding','size'):
                altered = deepcopy(request)
                put(self.root/'probes.json',selection); put(self.root/'selected/ordinals.json',ordinals)
                if change=='order': put(self.root/'probes.json',dict(selection,probes=list(reversed(probes))))
                elif change=='ordinal':
                    rows=deepcopy(ordinals); rows[6]['original_ordinal']+=1; put(self.root/'selected/ordinals.json',rows)
                elif change=='missing_source': altered['sources'].pop(0)
                elif change=='changed_binding': altered['sources'][0]['sha256']='f'*64
                else: put(self.root/'probes.json',dict(selection,probes=probes[:-1]))
                with self.subTest(change=change),self.assertRaises(ValueError):
                    entry._fixed_inputs(altered)
            (self.root/'tiny_source.txt').write_bytes(b'changed synthetic input\n')
            with self.assertRaises(ValueError):
                entry.verify_bindings(request['sources'])

    def test_rd_dr_rd_completion_and_descriptions_do_not_create_new_coverage(self):
        self.assertEqual([row['mode'] for row in entry.schedule()],['R','D','D','R','R','D'])
        self.assertEqual([row['mode_repeat_index'] for row in entry.schedule()],[0,0,1,1,2,2])
        selected,repeats = tail_fixtures.timing_case()
        rounds = []
        for item in entry.schedule():
            row = deepcopy(repeats[item['mode_repeat_index']])
            for query in row['measured']['queries']:
                stages = query['rank_stages_seconds']
                stages['exact_neighbor_selection']/=2
                stages['sql_positive_overlaps']=stages['exact_neighbor_selection']
            row.update(item,span={'start_monotonic_seconds':0.,'end_monotonic_seconds':10.})
            rounds.append(row)
        summaries = entry._mode_summaries(selected,rounds,tail_fixtures.specification())
        for summary in summaries.values():
            self.assertEqual((summary['scope']['new_keys'],summary['scope']['reused_keys']),(0,7))
            self.assertEqual((summary['scope']['distinct_historically_verified_queries'],summary['scope']['distinct_comparable_queries']),(232,170))
            self.assertEqual(summary['scope']['covered_cells'],55)
            self.assertEqual(set(summary['cells'][tail_fixtures.CELL]['roles']),{'source_tail','source_anchor'})
        differences = entry._paired_observer_differences(selected,rounds)
        self.assertEqual([p['order'] for p in differences['pairs']],['RD','DR','RD'])
        self.assertEqual([p['groups']['all_fixed_cases']['seconds']['core']['D_minus_R_sum_seconds'] for p in differences['pairs']],[0.,0.,0.])
        with self.assertRaises(ValueError):
            entry._paired_observer_differences(selected,rounds[:-1])
        completion = {'exit_code':0,'stop_reason':None,'supervisor_error':None,
                      'actual_exit_observed_utc':'2026-11-06T00:20:00+00:00','tracked_processes_alive_after_cleanup':0}
        put(self.root/'supervisor_completion.json',completion)
        put(self.root/'tracked_process_identities.json',{'identities':[],'live_after_cleanup':0})
        for phase in ('initial_frozen_source_hash','bind_existing_seven','final_frozen_source_hash',*(r['label'] for r in entry.schedule())):
            put(self.root/(phase+'_receipt.json'),{'completed':True})
        done = {'rounds':6,'reference_rounds':3,'diagnostic_rounds':3,'new_keys':0,'reused_keys':7,'queries_per_round':7,'engineering_checks':42}
        put(self.root/'done.json',done); entry._completed(self.root)
        for field,value in (('new_keys',6),('engineering_checks',21),('rounds',5),('reused_keys',6)):
            put(self.root/'done.json',dict(done,**{field:value}))
            with self.subTest(field=field),self.assertRaises(ValueError): entry._completed(self.root)
        put(self.root/'done.json',done); put(self.root/'round_5_receipt.json',{'completed':False})
        with self.assertRaises(ValueError): entry._completed(self.root)

    def test_load_brackets_follow_all_six_rounds_and_do_not_overlap_or_relabel_modes(self):
        start = datetime(2026,11,6,tzinfo=timezone.utc)
        request = {'created_utc':(start-timedelta(seconds=1)).isoformat(),'deadline_utc':(start+timedelta(seconds=1800)).isoformat()}
        saved = []
        for item in entry.schedule():
            base = item['round_index']*10.
            records = load_fixtures.telemetry_case(item['mode_repeat_index'],tuple(base+t for t in (0.,.2,.4,.6)))
            span = {'round_index':item['round_index'],'mode':item['mode'],'repeat_index':item['mode_repeat_index'],'completed':True,
                    'start_monotonic_seconds':base+.02,'end_monotonic_seconds':base+.58,
                    'start_utc':(start+timedelta(seconds=base+.02)).isoformat(),'end_utc':(start+timedelta(seconds=base+.58)).isoformat()}
            raw = dict(item,records=records)
            put(self.root/item['label']/'telemetry_records.json',raw)
            put(self.root/item['label']/'verifier_span.json',span)
            saved.append((raw,span))
        entry._check_round_spans(self.root,request)
        raw,span = saved[-1]
        for change in ('mode','repeat','missing_end','start','overlap'):
            r,s = deepcopy((raw,span))
            if change=='mode': r['mode']='R'
            elif change=='repeat': s['repeat_index']=1
            elif change=='missing_end': r['records'][-1]['kind']='periodic'
            elif change=='start': s['start_monotonic_seconds']=50.
            else:
                for record in r['records']:
                    record['monotonic_seconds']-=10.
                    record['observed_utc']=(datetime.fromisoformat(record['observed_utc'])-timedelta(seconds=10)).isoformat()
                for key in ('start_monotonic_seconds','end_monotonic_seconds'): s[key]-=10.
                for key in ('start_utc','end_utc'): s[key]=(datetime.fromisoformat(s[key])-timedelta(seconds=10)).isoformat()
            put(self.root/'round_5/telemetry_records.json',r); put(self.root/'round_5/verifier_span.json',s)
            with self.subTest(change=change),self.assertRaises(ValueError): entry._check_round_spans(self.root,request)


if __name__ == '__main__':
    unittest.main()
