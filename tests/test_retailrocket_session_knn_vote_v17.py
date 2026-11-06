"""V17 entry contracts and saved-evidence publication; no benchmark or model ranking."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import run_retailrocket_session_knn_v2 as source_io
from scripts import run_retailrocket_session_knn_vote_v7 as legacy
from scripts import run_retailrocket_session_knn_vote_v17 as entry
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof


GATES = {'reference_gates_verified':6,'reserved_test':'locked'}
CELL = '0000/n2/v2'


def sha(value):
    return hashlib.sha256(json.dumps(value,separators=(',',':')).encode()).hexdigest()


def snapshot(at):
    return {'utc':at.isoformat(), 'cpu_percent_nonblocking':25., 'memory_total_bytes':10000,
            'memory_available_bytes':8000, 'memory_used_bytes':2000, 'memory_percent':20.,
            'observer_process_rss_bytes':500}


def measurements(probes, verify, frame_bytes):
    rows, events = [], []
    for i,probe in enumerate(probes):
        rows.append({'subset_ordinal':i,'original_ordinal':probe['original_ordinal'],
                     'key_sha256':probe['key_sha256'],'verification_seconds':verify,
                     'rank_seconds':verify*.8,'seconds':verify+.5,
                     'rank_stages_seconds':{'sql_selected_votes_and_accumulation':verify*.4,
                                           'exact_neighbor_selection':verify*.4},
                     'checkpoint_append_seconds':.5,'append_without_commit_seconds':.5,'chunk_commit_seconds':0.,
                     'sql_workload':{'sql_selected_rows_inserted':1,'sql_vote_membership_rows_returned':1,
                                     'exact_vote_additions':1,'fraction_fallback':False}})
        events.append({'subset_ordinal':i,'completed':True,'frame_bytes':frame_bytes[i],
                       'seconds':.5,'unpartitioned_seconds':0.,'parts_seconds':{
                           'budget_check':.05,'guards_and_key':.05,'frame_encode':.25,'payload_open':0.,
                           'payload_write':.1,'pending_and_trigger':.05,'nested_flush':0.}})
    measured = {'queries':rows,'committed_prefix_rows':0,'verified_subset_queries':len(probes),
                'chunk_commits':[{'records':len(probes),'completed':True,'seconds':.25,
                                  'payload_bytes':sum(frame_bytes)}],
                'setup_seconds':.2,'tail_flush_and_eof_seal_seconds':.25,'prefix_replay_seconds':0.}
    return measured,{'append':events,'budget':[]}


class VoteEntryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (entry,source_io):
            self.stack.enter_context(patch.object(module,'ROOT',self.root))
        self.stack.enter_context(patch.object(entry,'PRIVATE',self.root/'private'))
        self.stack.enter_context(patch.object(entry,'check_gates',return_value=GATES))
        self.stack.enter_context(patch.object(entry,'_check_db',return_value=None))
        self.start = datetime.now(timezone.utc)-timedelta(seconds=1)
        self.request = {'created_utc':self.start.isoformat(),
                        'deadline_utc':(self.start+timedelta(seconds=1800)).isoformat(),
                        'budget_seconds':1800,'limits':dict(entry.LIMITS),'operation':'joint_tail',
                        'full_readback_enabled':False,'reserved_test':'locked','T_plan':None}
        self.completion = {'exit_code':0,'stop_reason':None,'supervisor_error':None,
                           'actual_exit_observed_utc':(self.start+timedelta(seconds=1500)).isoformat(),
                           'tracked_processes_alive_after_cleanup':0,'seconds':1500.,
                           'operation':'joint_tail','full_readback_started':False,'reserved_test':'locked',
                           'T_plan':None,'peak_sampled_tree_and_supervisor_rss_bytes':1024,
                           'peak_sampled_execution_bytes':4096}
        self.put('rollup.json',{'status':'synthetic_saved_cost_rollup'})
        self.put(entry.V6,{'repeats':[{'refinement_sensitivity':{'policies':{
            'neighbor_vote_grid':{'cells':{CELL:{'population_queries':100}}}}}}]})
        self.put(entry.GAP,{'status':'synthetic_original_gap','generation':1})
        self.put('inventory.json',{'status':'v17_cost_inventory_verified','comparable_scope':{
            'distinct_queries':156,'query_observations':360,'covered_cells':55},
            'inputs':[entry.describe(self.root/name) for name in (entry.V6,entry.GAP)]})
        self.evidence_names = (entry.ANCHOR,entry.BASE+'v7_vote_profile_20261105.json',
                               entry.BASE+'v7_sql_vote_assessment_20261105.json',
                               'scripts/retailrocket_session_knn_vote_v7.py',
                               'scripts/retailrocket_session_knn_sql_v4.py')
        for name in self.evidence_names:
            self.put(name,{'synthetic_evidence':True,'generation':1})
        self.spec = {'status':'v17_cost_sql_specification_frozen','candidate':'rank_counts',
                     'protocol':dict(entry.PROTOCOL),'rollup':entry.describe(self.root/'rollup.json'),
                     'inventory':entry.describe(self.root/'inventory.json'),
                     'evidence':[entry.describe(self.root/name) for name in
                                 ('inventory.json','rollup.json',*self.evidence_names)]}
        self.put(entry.SPEC,self.spec)
        self.stack.enter_context(patch.object(entry,'SPEC_SHA256',entry.describe(self.root/entry.SPEC)['sha256']))
        self.put(entry.ACCEPT,{'gates':GATES})
        self.contracts = {}
        self.stack.enter_context(patch.object(entry,'accepted_methods',return_value={'synthetic_acceptance':True}))
        self.stack.enter_context(patch.object(entry,'_source_contract',side_effect=lambda stage,*_:
                                             self.contracts[stage]))

    def put(self, path, value):
        path = Path(path)
        if not path.is_absolute():
            path = self.root/path
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(cp.encoded(value))
        return path

    def comparison(self, stage='compare48', create_runs=True):
        size = 48 if stage == 'compare48' else 34
        base = self.root/(stage+'_reference')
        folder = self.root/'private'/('synthetic_'+stage)
        folder.mkdir(parents=True)
        probes = []
        for i in range(size):
            key = [str(1001+i),0,i]
            probes.append({'key':key,'key_sha256':sha(key),'original_ordinal':i,
                           'cell':'0000' if stage=='compare48' else CELL,
                           'eligible_neighbors':20,'vote_memberships_upper':200})
        binding = {'sources':[],'scope':'synthetic frozen scientific frames'}
        store = DetailedTimedStore.create(base/'verified_subset',binding,self.request['deadline_utc'],1800,
            source_root=self.root,expected_queries=size,required_stages=('reconstruction','queries'),chunk_queries=64)
        with store.writer():
            store.seal_stage('reconstruction',{'synthetic':True})
            for i,probe in enumerate(probes):
                store.append_verified(i,probe['key'],{'expected':{'key':probe['key'],
                    'predictions':{'K1':{'synthetic_exact_output':[i,1]}}}})
            store.flush_chunk()
            store.seal_stage('queries',{'queries':size,'paired_streams_eof_checked':True})
        reference = ledger_proof(store,probes)
        frame_bytes = [len(cp.encoded(row)) for row in store.iter_records()]
        paths = {'probes':stage+'_probes.json','reference':stage+'_reference.json',
                 'old_run':stage+'_old_run.json','selected_root':stage+'_selected','model_root':'synthetic_model'}
        self.put(paths['probes'],{'probes':probes})
        self.put(paths['reference'],reference)
        self.put(paths['old_run'],{'binding':binding})
        self.put(paths['selected_root']+'/configuration.json',{'fixed_validation':{'queries':size}})
        self.put(paths['selected_root']+'/ordinals.json',list(range(size)))
        self.put(paths['model_root']+'/reconstruction.json',{'receipt':{'fit_audit':{'synthetic':True}}})
        metadata = dict(paths,stage=stage,candidate='rank_counts',environment=entry.environment(),
                        sqlite_version=entry.sqlite3.sqlite_version,specification=entry.describe(self.root/entry.SPEC),
                        rollup=self.spec['rollup'],inventory=self.spec['inventory'],
                        acceptance=entry.describe(self.root/entry.ACCEPT),anchor=entry.describe(self.root/paths['reference']),
                        protocol=dict(entry.PROTOCOL))
        names = [paths['probes'],paths['reference'],paths['old_run'],entry.SPEC,entry.ACCEPT,entry.V6,
                 'rollup.json','inventory.json']
        sources = [entry.describe(self.root/name) for name in names]
        self.contracts[stage] = sources,metadata
        request = dict(self.request,metadata=metadata,sources=sources)
        self.put(folder/'request.json',request)
        if create_runs:
            self.put(folder/'supervisor_completion.json',self.completion)
            self.put(folder/'tracked_process_identities.json',{'identities':[],'live_after_cleanup':0})
            self.put(folder/'done.json',{'stage':stage,'candidate':'rank_counts','completed':True,'scope':size,'runs':14})
            for phase in ('initial','final'):
                self.put(folder/(phase+'_hash.json'),{'count':len(sources),'seconds':.1})
            for i,(label,mode) in enumerate(entry.schedule(stage,'rank_counts')):
                run = folder/label
                shutil.copytree(base/'verified_subset',run/'verified_subset')
                verify = .4 if label=='warm_A' else 1.5 if label=='warm_B' else 1. if mode=='baseline' else .8
                measured,observations = measurements(probes,verify,frame_bytes)
                self.put(run/'measured.json',measured)
                self.put(run/'observations.json',observations)
                self.put(run/'proof.json',reference)
                self.put(run/'profile.json',[])
                self.put(run/'entry.json',{'label':label,'mode':mode,
                                           'seconds':entry._costs(measured,probes)['primary_seconds']+1.})
                self.put(folder/(label+'_resources_before.json'),snapshot(self.start+timedelta(seconds=10+100*i)))
                self.put(folder/(label+'_resources_after.json'),snapshot(self.start+timedelta(seconds=109+100*i)))
        return folder,probes,reference,frame_bytes

    def publish(self, folder):
        with redirect_stdout(io.StringIO()):
            return entry._publish(folder)

    def test_candidate_protocol_and_cost_sources_are_pinned_before_entry(self):
        self.assertEqual(entry.preregistration(),self.spec)
        for change in ('candidate','protocol','status','bytes'):
            changed = deepcopy(self.spec)
            if change == 'candidate':
                changed['candidate'] = 'batch_fetch'
            elif change == 'protocol':
                changed['protocol']['minimum_median_saving_percent'] = 1
            elif change == 'status':
                changed['status'] = 'draft'
            else:
                changed['unexpected'] = True
            self.put(entry.SPEC,changed)
            if change == 'bytes':
                with self.assertRaises(ValueError):
                    entry.preregistration()
            else:
                with patch.object(entry,'SPEC_SHA256',entry.describe(self.root/entry.SPEC)['sha256']):
                    with self.subTest(change=change),self.assertRaises(ValueError):
                        entry.preregistration()
        self.put(entry.SPEC,self.spec)
        self.put('rollup.json',{'status':'changed_existing_cost_evidence'})
        with self.assertRaises(ValueError):
            entry.preregistration()

    def test_original_anchor_profile_and_methods_cannot_be_rebound_to_changed_bytes(self):
        specification_bytes = (self.root/entry.SPEC).read_bytes()
        self.assertEqual(entry.preregistration(),self.spec)
        for name in self.evidence_names:
            path = self.root/name
            original = path.read_bytes()
            changed = original.replace(b'"generation":1',b'"generation":2')
            self.assertNotEqual(changed,original)
            self.assertEqual(len(changed),len(original))
            path.write_bytes(changed)
            try:
                with self.subTest(source=name),self.assertRaises(ValueError):
                    entry.preregistration()
                self.assertEqual((self.root/entry.SPEC).read_bytes(),specification_bytes)
            finally:
                path.write_bytes(original)
        self.assertEqual(entry.preregistration(),self.spec)

    def test_compare34_requires_same_candidate_reproducible_passing_48(self):
        runs = {label:{'mode':mode,'primary_seconds':100. if mode=='baseline' else 90.,
                       'entry_seconds':110. if mode=='baseline' else 100.}
                for label,mode in entry.schedule('compare48','rank_counts')}
        prior = {'status':'v17_vote_compare48_measured','stage':'compare48','candidate':'rank_counts',
                 'specification':entry.describe(self.root/entry.SPEC),'all_scientific_bytes_match_reference':True,
                 'runs':runs,'decision':entry.paired_decision(runs),'original_distinct_sample_size':48,
                 'repeat_query_checks':672,'new_unique_keys':0}
        entry._validate_stage('compare34',prior)
        for change in ('missing','candidate','failed','spec','forged_decision','missing_run','changed_mode','new_keys'):
            changed = deepcopy(prior)
            if change == 'missing':
                changed = None
            elif change == 'candidate':
                changed['candidate'] = 'batch_insert'
            elif change == 'failed':
                changed['decision']['supports_candidate'] = False
            elif change == 'spec':
                changed['specification']['sha256'] = 'a'*64
            elif change == 'forged_decision':
                changed['runs']['pair_1_B']['primary_seconds'] = 200.
            elif change == 'missing_run':
                changed['runs'].pop('warm_B')
            elif change == 'changed_mode':
                changed['runs']['pair_1_B']['mode'] = 'baseline'
            else:
                changed['new_unique_keys'] = 1
            with self.subTest(change=change),self.assertRaises(ValueError):
                entry._validate_stage('compare34',changed)
        with self.assertRaises(ValueError):
            entry._validate_stage('profile')

    def test_window_scope_resource_and_original_deadline_fail_closed(self):
        entry._check_window(self.request,self.completion)
        for key,value in (('budget_seconds',1801),('limits',dict(entry.LIMITS,rss_bytes=9<<30)),
                          ('deadline_utc',(self.start+timedelta(seconds=1801)).isoformat()),
                          ('operation','full'),('full_readback_enabled',True),('reserved_test','unlocked')):
            with self.subTest(request=key),self.assertRaises(ValueError):
                entry._check_window(dict(self.request,**{key:value}),self.completion)
        for key,value in (('exit_code',1),('tracked_processes_alive_after_cleanup',1),
                          ('actual_exit_observed_utc',(self.start+timedelta(seconds=1801)).isoformat()),
                          ('peak_sampled_tree_and_supervisor_rss_bytes',(8<<30)+1),
                          ('peak_sampled_execution_bytes',(20<<30)+1),('seconds',1801.)):
            with self.subTest(completion=key),self.assertRaises(ValueError):
                entry._check_window(self.request,dict(self.completion,**{key:value}))

    def test_request_metadata_and_changed_source_are_rejected_before_any_run(self):
        folder,_,_,_ = self.comparison(create_runs=False)
        request = entry.read(folder/'request.json')
        self.assertEqual(entry._check_request_contract(request),request['metadata'])
        for change in ('candidate','source','deadline'):
            changed = deepcopy(request)
            if change == 'candidate':
                changed['metadata']['candidate'] = 'batch_fetch'
            elif change == 'source':
                changed['sources'][0]['sha256'] = 'f'*64
            else:
                changed['deadline_utc'] = (self.start+timedelta(seconds=1801)).isoformat()
            self.put(folder/'request.json',changed)
            with patch.object(entry,'_run') as run,self.subTest(change=change),self.assertRaises(ValueError):
                entry.worker(folder)
            run.assert_not_called()
        self.put(folder/'request.json',request)
        path = self.root/request['metadata']['probes']
        path.write_bytes(path.read_bytes()+b' ')
        with patch.object(entry,'_run') as run,self.assertRaises(ValueError):
            entry.worker(folder)
        run.assert_not_called()

    def test_resource_observation_is_read_only_nonblocking_and_outside_all_run_timers(self):
        memory = SimpleNamespace(total=10000,available=8000,used=2000,percent=20.)
        process = SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=500))
        with patch.object(entry.psutil,'virtual_memory',return_value=memory), \
             patch.object(entry.psutil,'cpu_percent',return_value=25.) as cpu, \
             patch.object(entry.psutil,'Process',return_value=process):
            observed = entry.resource_snapshot()
            entry._validate_snapshot(observed)
            cpu.assert_called_once_with(interval=None)
        self.assertIs(entry._run,legacy._run)
        folder,probes,_,frame_bytes = self.comparison(create_runs=False)
        measured,_ = measurements(probes,1.,frame_bytes)
        initial = entry._costs(measured,probes)
        measured['system_observation_seconds'] = 10000.
        self.assertEqual(entry._costs(measured,probes),initial)
        calls = []
        def observe():
            calls.append('snapshot')
            return snapshot(self.start+timedelta(seconds=len(calls)))
        def run(run_folder,request,label,mode,inputs,watch):
            calls.append(label)
            self.put(run_folder/label/'measured.json',measured)
        watcher = lambda:None
        watcher.force = watcher
        with patch.object(entry,'resource_snapshot',side_effect=observe), \
             patch.object(entry,'_run',side_effect=run),patch.object(entry,'clear_caches') as clear, \
             patch.object(entry,'ThrottledWatch',return_value=watcher):
            entry.worker(folder)
        self.assertEqual(calls,[item for label,_ in entry.schedule('compare48','rank_counts')
                                for item in ('snapshot',label,'snapshot')])
        clear.assert_called_once_with()
        self.assertEqual(entry.read(folder/'done.json'),{'stage':'compare48','candidate':'rank_counts',
                                                       'completed':True,'scope':48,'runs':14})

    def test_failed_run_keeps_both_resource_observations_and_cannot_finish(self):
        folder,_,_,_ = self.comparison(create_runs=False)
        watcher = lambda:None
        watcher.force = watcher
        observations = [snapshot(self.start+timedelta(seconds=i)) for i in (1,2)]
        with patch.object(entry,'resource_snapshot',side_effect=observations), \
             patch.object(entry,'_run',side_effect=RuntimeError('synthetic interruption')), \
             patch.object(entry,'clear_caches'),patch.object(entry,'ThrottledWatch',return_value=watcher):
            with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):
                entry.worker(folder)
        self.assertEqual(entry.read(folder/'warm_A_resources_before.json'),observations[0])
        self.assertEqual(entry.read(folder/'warm_A_resources_after.json'),observations[1])
        self.assertEqual(entry.read(folder/'failure.json')['error_type'],'RuntimeError')
        self.assertFalse((folder/'done.json').exists())
        self.assertFalse((self.root/entry.OUTPUT['compare48']).exists())

    def test_complete_48_and_34_saved_frames_match_reference_and_exclude_warmups(self):
        for stage,size in (('compare48',48),('compare34',34)):
            folder,_,reference,_ = self.comparison(stage)
            report = self.publish(folder)
            self.assertEqual(len(report['runs']),14)
            self.assertEqual(report['repeat_query_checks'],14*size)
            self.assertEqual(report['warmup_query_checks'],2*size)
            self.assertEqual(report['paired_query_checks'],12*size)
            self.assertEqual(report['new_unique_keys'],0)
            self.assertEqual(report['reference'],{k:reference[k] for k in (
                'records','actual_committed_bytes','actual_committed_payload_sha256')})
            self.assertTrue(report['all_scientific_bytes_match_reference'])
            self.assertTrue(report['decision']['supports_candidate'])
            self.assertEqual(report['decision']['faster_pairs'],6)
            self.assertGreater(report['runs']['warm_B']['primary_seconds'],report['runs']['warm_A']['primary_seconds'])
            self.assertAlmostEqual(report['runs']['pair_1_A']['primary_seconds'],size*1.5+.25)
            self.assertAlmostEqual(report['runs']['pair_1_B']['primary_seconds'],size*1.3+.25)
            self.assertEqual(self.publish(folder),report)
            other = self.root/'private'/('different_'+stage)
            other.mkdir()
            self.put(other/'request.json',entry.read(folder/'request.json'))
            with self.assertRaises(FileExistsError):
                self.publish(other)

    def test_forged_passing_48_summary_cannot_override_unchanged_failed_raw_runs(self):
        folder,probes,_,frame_bytes = self.comparison()
        for pair in range(1,7):
            label = f'pair_{pair}_B'
            measured,observations = measurements(probes,1.1,frame_bytes)
            self.put(folder/label/'measured.json',measured)
            self.put(folder/label/'observations.json',observations)
            self.put(folder/label/'entry.json',{'label':label,'mode':'rank_counts',
                'seconds':entry._costs(measured,probes)['primary_seconds']+1.})
        original = self.publish(folder)
        self.assertFalse(original['decision']['supports_candidate'])
        metadata = self.contracts['compare48'][1]
        entry._audit_prior_runs(original,metadata)
        forged = deepcopy(original)
        for pair in range(1,7):
            baseline = forged['runs'][f'pair_{pair}_A']
            forged['runs'][f'pair_{pair}_B'] = {
                name:value*.9 if isinstance(value,(int,float)) else value for name,value in baseline.items()}
            forged['runs'][f'pair_{pair}_B']['mode'] = 'rank_counts'
        forged['decision'] = entry.paired_decision(forged['runs'])
        self.assertTrue(forged['decision']['supports_candidate'])
        self.put(entry.OUTPUT['compare48'],forged)
        entry._validate_stage('compare34',forged)
        with self.assertRaises(ValueError):
            entry._audit_prior_runs(forged,metadata)

    def test_incomplete_runs_changed_proof_deadline_profile_or_timers_withhold_publication(self):
        folder,_,_,_ = self.comparison()
        run = folder/'pair_6_A'
        cases = [('done.json',lambda v:v.update(runs=13)),
                 ('pair_6_A/proof.json',lambda v:v.update(actual_committed_payload_sha256='a'*64)),
                 ('pair_6_A/verified_subset/run.json',lambda v:v.update(
                     deadline_utc=(self.start+timedelta(seconds=1801)).isoformat())),
                 ('pair_6_A/profile.json',lambda v:v.append({'unexpected_profile':True})),
                 ('pair_6_A/measured.json',lambda v:v['queries'][0].update(verification_seconds=-1.)),
                 ('pair_6_A/entry.json',lambda v:v.update(seconds=.01)),
                 ('pair_6_A_resources_before.json',lambda v:v.update(
                     utc=(self.start-timedelta(seconds=1)).isoformat()))]
        for relative,mutate in cases:
            path = folder/relative
            original = path.read_bytes()
            changed = json.loads(original)
            mutate(changed)
            self.put(path,changed)
            try:
                with self.subTest(source=relative),self.assertRaises(ValueError):
                    self.publish(folder)
                self.assertFalse((self.root/entry.OUTPUT['compare48']).exists())
            finally:
                path.write_bytes(original)
        missing = run/'entry.json'
        saved = missing.read_bytes()
        missing.unlink()
        try:
            with self.assertRaises(FileNotFoundError):
                self.publish(folder)
        finally:
            missing.write_bytes(saved)
        payload = next((run/'verified_subset'/'payloads').glob('*.jsonl'))
        payload.write_bytes(payload.read_bytes()+b'{}\n')
        with self.assertRaises(ValueError):
            self.publish(folder)
        self.assertFalse((self.root/entry.OUTPUT['compare48']).exists())


if __name__ == '__main__':
    unittest.main()
