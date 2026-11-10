"""New S1 pools under inherited mutations and real independent artificial48 subprocesses."""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as adapter
from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_compare_v28 as old_core
from scripts import run_retailrocket_session_knn_compare_v28 as old_entry
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import run_retailrocket_session_knn_v2 as io
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from tests import test_retailrocket_session_knn_reuse_v27 as focused
from tests import test_retailrocket_session_knn_reuse_acceptance_v27 as legacy
from tests import test_retailrocket_session_knn_compare_v28 as previous
from tests import test_retailrocket_session_knn_validation as validation
from tests import test_retailrocket_session_knn_pair_v4 as four

MODULE='tests.test_retailrocket_session_knn_snapshot_integration_v30'
METHODS=('scripts/retailrocket_session_knn_snapshot_v30.py','scripts/retailrocket_session_knn_snapshot_adapter_v30.py',
         'tests/test_retailrocket_session_knn_snapshot_integration_v30.py')


def add_methods(contract):
    records={x['path']:x for x in contract['methods']}
    for name in METHODS[:2]:records[name]=io.describe(io.ROOT/name)
    contract['methods']=[records[k] for k in sorted(records)]


def rebind_s1(self):
    focused.ContextTests.rebind(self)
    self.request.setdefault('metadata',{})['fingerprint_scheme']=codec.SCHEME
    add_methods(self.contract)
    self.pool=adapter.WorkerContext(self.contract,self.root,io.ROOT)


class InheritedContextTests(focused.ContextTests):
    """All inherited lookup tests actually borrow an S1 pool after every rebind."""
    rebind=rebind_s1


class InheritedAdversarialTests(legacy.AdversarialTests):
    rebind=rebind_s1

    def test_same_size_changed_content(self):
        store,obs=self.store();p=self.root/'P0/item_counts.csv'
        with store.writer(),self.assertRaisesRegex(ValueError,'initialization buffer differs'):
            before=p.stat().st_size;p.write_bytes(p.read_bytes().replace(b'1,3',b'1,4'))
            self.assertEqual(p.stat().st_size,before);self.load(store,obs)
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool.prepared)

    def test_changed_size(self):
        store,obs=self.store();p=self.root/'P0/item_counts.csv'
        with store.writer(),self.assertRaisesRegex(ValueError,'initialization buffer differs'):
            p.write_bytes(p.read_bytes()+b'\n');self.load(store,obs)
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool.prepared)

    def test_bytes_change_during_buffer_acquisition(self):
        p=self.root/'P0/item_counts.csv'
        p.write_bytes(b'itemid,count\n'+b''.join(f'{i},3\n'.encode() for i in range(1,300001)))
        self.rebind();store,obs=self.store();calls=0
        def watch():
            nonlocal calls
            if obs.stack and obs.events[obs.stack[-1]]['phase']=='cache.cold_build':
                calls+=1
                if calls==2:
                    with p.open('r+b') as stream:
                        stream.seek(1024*1024);before=stream.read(1);stream.seek(1024*1024)
                        stream.write(b'8' if before==b'9' else b'9')
        with store.writer(),self.assertRaisesRegex(ValueError,'initialization buffer differs'):
            self.pool.load(self.paths,self.config,self.model['support'],watch,model=self.model,store=store,
                namespace='artificial-window',request=self.request,observer=obs)
        self.assertGreaterEqual(calls,2);self.assertTrue(self.pool.poisoned)

    def test_body_exception_cleanup(self):
        with legacy.tempfile_artificial_four() as data:
            root,paths,config,primary,database,model,ordinals,binding,contract=data
            add_methods(contract);pool=adapter.WorkerContext(contract,root,io.ROOT);obs=observed.Observation()
            request=dict(deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat(),budget_seconds=180,
                         metadata=dict(fingerprint_scheme=codec.SCHEME))
            store=c1.ReuseStore.create(root/'failed-s1',binding,request['deadline_utc'],180,source_root=root,observer=obs,
                expected_queries=len(ordinals),required_stages=('reconstruction','queries'))
            def interrupt(point):
                if point=='query_work':raise RuntimeError('artificial S1 interruption')
            with self.assertRaises(RuntimeError),store.writer():
                four.reconstruct_seal(store,model)
                adapter.make_verifier(obs,pool,'artificial-window',request)(primary,paths,config,store,model,database,ordinals,fault=interrupt)
            self.assertTrue(pool.poisoned);self.assertIsNone(store._guard);self.assertFalse(obs.stack)


class SchemeTests(unittest.TestCase):
    setUp=focused.ContextTests.setUp
    rebind=rebind_s1
    store=focused.ContextTests.store
    load=focused.ContextTests.load
    cycle=focused.ContextTests.cycle

    def test_scheme_prefix_and_event_version_mismatch(self):
        self.request['metadata']['fingerprint_scheme']='wrong-scheme';store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)
        self.assertTrue(self.pool.poisoned)
        self.rebind();self.cycle();self.request['metadata']['fingerprint_scheme']='wrong-scheme';store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_cached_encoded_bytes_cannot_hide_live_mutation(self):
        _,_,snapshot=self.cycle();before=codec.fingerprint(snapshot)
        first=dict(snapshot.first);first['1']=first['1']+1
        from types import MappingProxyType
        object.__setattr__(snapshot,'first',MappingProxyType(first))
        self.assertNotEqual(codec.fingerprint(snapshot),before)
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_15_live_snapshot_checks_and22_digests_retained(self):
        all_events=[];calls=Counter();digests=Counter()
        original=c1.canonical;original_digest=c1.digest
        def canonical(value):
            if 'first_times' in value:role='snapshot'
            elif 'namespace' in value:role='identity_key'
            elif 'schemas' in value:role='config'
            elif 'support' in value:role='model'
            else:role='binding'
            calls[role]+=1;return original(value)
        def digest(value):
            self.assertIn('namespace',value)
            digests['identity_key']+=1;return original_digest(value)
        # Actual S1 methods can use their own invocation-local canonical alias.
        targets=[patch.object(c1,'canonical',side_effect=canonical),patch.object(c1,'digest',side_effect=digest)]
        if hasattr(adapter,'canonical'):targets.append(patch.object(adapter,'canonical',side_effect=canonical))
        from contextlib import ExitStack
        with ExitStack() as stack:
            for target in targets:stack.enter_context(target)
            for _ in range(7):
                _,obs,_=self.cycle();all_events.extend(obs.events)
        self.assertEqual(dict(calls),dict(binding=14,identity_key=7,config=10,model=10))
        fingerprints=[e for e in all_events if e['phase']=='snapshot.fingerprint']
        self.assertEqual(len(fingerprints),15)
        self.assertEqual(digests['identity_key'],7)
        self.assertEqual(digests['identity_key']+len(fingerprints),22)
        receipt=self.pool.completed_summary()
        self.assertEqual(receipt['hits'],6);self.assertEqual(receipt['fingerprint_scheme'],codec.SCHEME)
        self.pool.calls[3]['fingerprint_scheme']='old-C1-scheme'
        with self.assertRaisesRegex(ValueError,'scheme'):self.pool.completed_summary()

    def test_identity_key_binding_and_model_canonical_unchanged(self):
        store,obs,snapshot=self.cycle()
        use=next(e['metadata'] for e in obs.events if e['phase']=='cache.use')
        self.assertEqual(use['fingerprint_scheme'],codec.SCHEME)
        self.assertEqual(self.pool.calls[0]['fingerprint_scheme'],codec.SCHEME)
        old=c1.digest(dict(first=snapshot.first,counts=snapshot.counts,first_times=snapshot.first_times,fallback=snapshot.fallback))
        self.assertNotEqual(old,use['snapshot_digest'])
        self.assertEqual(use['snapshot_digest'],codec.fingerprint(snapshot))
        self.assertEqual(store.full_checks,[dict(force=False,external=False),dict(force=True,external=False)])

    def test_separate_validation_JSON_UTF8_SHA_release_timers(self):
        _,obs,_=self.cycle();summary=obs.summary()
        self.assertEqual(summary['phases']['snapshot.fingerprint']['calls'],3)
        children={e['phase'] for e in obs.events if e['phase'].startswith('snapshot.') and e['phase']!='snapshot.fingerprint'}
        for fragment in ('valid','json','utf8','sha','release'):
            self.assertTrue(any(fragment in name.lower() for name in children),(fragment,children))
        self.assertEqual(sum(x['exclusive_wall_ns'] for x in summary['phases'].values()),summary['root_wall_ns'])


class FullVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=[]
        for boundary in (False,True):
            with tempfile.TemporaryDirectory() as temp:
                with patch.object(four,'make_fixture',side_effect=lambda **kw:validation.make_fixture(base=temp,**kw)):
                    root,paths,config,primary,_,database,model,ordinals,binding=four.fixture(boundary=boundary)
                (root/'reconstruction.json').write_text(json.dumps({'receipt':model}),encoding='utf-8')
                binding['sources']=cp.bind_sources(root,[x['path'] for x in binding['sources']]+['reconstruction.json'])
                records={x['path']:x for x in binding['sources']}
                contract=dict(binding=binding,dependencies={k:records[p] for k,p in (
                    ('counts','P0/item_counts.csv'),('catalog','dataset/catalog.csv'),('config','configuration.json'),('model','reconstruction.json'))},
                    methods=[io.describe(io.ROOT/p) for p in METHODS[:2]],environment=io.environment())
                pool=adapter.WorkerContext(contract,root,io.ROOT)
                request=dict(deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),budget_seconds=300,
                    metadata=dict(fingerprint_scheme=codec.SCHEME))
                saved=[];workloads=[];fingerprints=0
                for index in range(8):
                    obs=observed.Observation();store=c1.ReuseStore.create(root/('s1-'+str(index)),binding,request['deadline_utc'],300,
                        source_root=root,observer=obs,expected_queries=len(ordinals),required_stages=('reconstruction','queries'))
                    with store.writer():
                        four.reconstruct_seal(store,model)
                        verify=observed.make_verifier(obs) if index==0 else adapter.make_verifier(obs,pool,'artificial-window',request)
                        measured=verify(primary,paths,config,store,model,database,ordinals)
                    saved.append(list(store.iter_records()));workloads.append([q['sql_workload'] for q in measured['queries']])
                    fingerprints+=obs.summary()['phases'].get('snapshot.fingerprint',{}).get('calls',0)
                cls.cases.append(dict(boundary=boundary,records=saved,workloads=workloads,fingerprints=fingerprints,receipt=pool.completed_summary()))

    def test_cold_and_six_hits_complete_four_arm_payload_bytes(self):
        for case in self.cases:
            expected=[cp.encoded(row) for row in case['records'][0]]
            for rows in case['records'][1:]:self.assertEqual([cp.encoded(row) for row in rows],expected)
            self.assertEqual(case['fingerprints'],15);self.assertEqual(case['receipt']['hits'],6)

    def test_Decimal_and_binary64_delta_hex_unchanged(self):
        for case in self.cases:
            expected=[row['payload'] for row in case['records'][0]]
            for rows in case['records'][1:]:
                self.assertEqual([row['payload'] for row in rows],expected)
                for row in rows:
                    payload=row['payload']
                    for arm in payload['precise'].values():self.assertTrue(all(type(v) is str for v in arm.values()))
                    for arm in payload['delta_hex'].values():
                        for value in arm.values():self.assertIsInstance(float.fromhex(value),float)

    def test_SQL_workload_and_query_order_unchanged(self):
        for case in self.cases:
            for workload in case['workloads'][1:]:self.assertEqual(workload,case['workloads'][0])
            keys=[row['key'] for row in case['records'][0]]
            for rows in case['records'][1:]:self.assertEqual([row['key'] for row in rows],keys)


def scope(folder):
    folder=Path(folder).resolve()
    if folder.parent.parent!=old_entry.PRIVATE.resolve() or not folder.parent.name.startswith('knn-v30-s1-synthetic-'):
        raise ValueError('Artificial S1 bridge only')
    request=io.read(folder/'request.json')
    if request['metadata'].get('synthetic_acceptance_only') is not True:raise ValueError('Artificial marker required')
    if request['metadata'].get('fingerprint_scheme')!=codec.SCHEME:raise ValueError('S1 scheme required')
    return folder,request


def child(folder,kind):
    folder,request=scope(folder)
    if kind=='pipeline':
        return adapter.run_pipeline(folder,request,{k:[sys.executable,'-B','-m',MODULE,'--'+k,str(folder)] for k in ('worker','publisher')})
    if kind=='publisher':return adapter.run_publisher(folder,request)
    return adapter.run_worker(folder,request,lambda:legacy.data_for(request)[1])


def build_window():
    bundle=old_entry.PRIVATE/('knn-v30-s1-synthetic-'+uuid4().hex);bundle.mkdir()
    with patch.object(validation,'fixture_inputs',side_effect=previous.artificial_inputs),patch.object(four,'make_fixture',side_effect=lambda **kw:validation.make_fixture(base=bundle,**kw)):
        root,paths,config,primary,_,database,model,ordinals,binding=four.fixture()
    io.write(root/'reconstruction.json',{'receipt':model})
    rel=lambda p:p.relative_to(io.ROOT).as_posix()
    records=cp.bind_sources(io.ROOT,[rel(p) for p in root.rglob('*') if p.is_file()]);binding=dict(binding,sources=records);d={x['path']:x for x in records}
    deadline=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    reference=c1.ReuseStore.create(bundle/'reference/verified_subset',binding,deadline,1800,source_root=io.ROOT,observer=observed.Observation(),
        expected_queries=48,required_stages=('reconstruction','queries'))
    with reference.writer():
        four.reconstruct_seal(reference,model);pair.verify_selected(primary,paths,config,reference,model,database,ordinals)
    probes=[dict(key=x['key'],original_ordinal=x['original_ordinal'],key_sha256=hashlib.sha256(pair.dump(x['key']).encode()).hexdigest()) for x in ordinals]
    io.write(bundle/'reference.json',ledger_proof(reference,probes));io.write(bundle/'probes.json',dict(probes=probes))
    dependencies={k:d[rel(p)] for k,p in (('counts',paths['P0']/'item_counts.csv'),('catalog',paths['dataset']/'catalog.csv'),
        ('config',root/'configuration.json'),('model',root/'reconstruction.json'))}
    methods=[io.describe(io.ROOT/p) for p in METHODS]
    io.write(bundle/'data.json',dict(contract=dict(binding=binding),model=model,database=rel(database),ordinals=ordinals,probes=probes))
    cohort=dict(selected_root=rel(root),model_root=rel(primary),old_run=rel(reference.folder/'run.json'),
        probes=rel(bundle/'probes.json'),reference=rel(bundle/'reference.json'))
    schedule=[dict(label='warm_'+m,mode=m) for m in ('R','C')]+[dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')]
    sources=[io.describe(p) for p in sorted(bundle.rglob('*')) if p.is_file()]+methods
    meta=dict(cohort=cohort,schedule=schedule,context=dict(dependencies=dependencies,methods=methods),environment=io.environment(),
        gates=io.check_gates(),synthetic_acceptance_only=True,synthetic_data=io.describe(bundle/'data.json'),
        fingerprint_scheme=codec.SCHEME,specification={'artificial':True},acceptance={'artificial':True})
    folder=bundle/'window';completion=run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],sources,
        'joint_tail',metadata=meta,budget_seconds=1800,limits=LIMITS)
    if completion['exit_code']!=0:
        raise AssertionError('\n'.join(p.read_text(encoding='utf-8',errors='replace')[-9000:] for p in folder.glob('*.log')))
    return folder


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.folder=build_window()
    def completed(self):return adapter.audit_completed(self.folder,io.read(self.folder/'request.json'))

    def test_equal_fields_independent_worker_publisher_fingerprint(self):
        result,completion,exits,pub,load=self.completed()
        self.assertNotEqual(exits['worker']['pid'],exits['publisher']['pid'])
        self.assertLessEqual(exits['worker']['ended_utc'],exits['publisher']['started_utc'])
        self.assertEqual(result['cache']['hits'],6)
        self.assertEqual(result['cache']['fingerprint_scheme'],codec.SCHEME)
        self.assertEqual({x['fingerprint_scheme'] for x in result['cache']['call_observations']},{codec.SCHEME})
        self.assertEqual(pub['phases']['publisher.independent_context']['calls'],1)

    def test_all_original_closure_identities_and14_publisher_opens(self):
        result,completion,exits,pub,load=self.completed();request=io.read(self.folder/'request.json')
        events=io.read(self.folder/'publisher/events.json')
        self.assertEqual([e['metadata']['descriptor'] for e in events if e['phase']=='closure.descriptor'],request['sources']*2)
        self.assertEqual(pub['phases']['checkpoint.open']['calls'],14)
        original=list(_physical_frames((io.ROOT/request['metadata']['cohort']['old_run']).parent))
        self.assertEqual(len(original),48)
        for label in result['runs']:self.assertEqual(list(_physical_frames(self.folder/label/'verified_subset')),original)

    def test_publisher_new_process_rebuild_no_worker_buffers(self):
        result,completion,exits,pub,load=self.completed()
        self.assertEqual(len(result['runs']),14)
        self.assertEqual(completion['tracked_processes_alive_after_cleanup'],0)
        self.assertFalse(any('snapshot' in p.name or 'encoded' in p.name for p in self.folder.rglob('*') if p.is_file()))
        self.assertEqual(pub['phases']['publisher.independent_context']['calls'],1)

    def test_every_create_and_post_lock_full_source_check(self):
        result,*_=self.completed();request=io.read(self.folder/'request.json')
        binding=io.read(io.ROOT/request['metadata']['cohort']['old_run'])['binding']['sources']
        for label,row in result['runs'].items():
            events=io.read(self.folder/label/'events.json')
            self.assertEqual([e['metadata']['descriptor'] for e in events if e['phase']=='binding.descriptor'],binding*2)
            self.assertEqual([e['metadata']['force'] for e in events if e['phase']=='checkpoint.check_sources'],[False,True])

    def test_cold_pre_and_post_guards_inside_complete_entry(self):
        result,*_=self.completed();total=0
        for label,row in result['runs'].items():
            events=io.read(self.folder/label/'events.json');root=next(e for e in events if e['phase']=='run.total')
            for e in events:self.assertLessEqual(root['start_ns'],e['start_ns']);self.assertLessEqual(e['end_ns'],root['end_ns'])
            if row['mode']=='C':
                total+=row['diagnostic']['phases']['snapshot.fingerprint']['calls']
                setup=next(e for e in events if e['phase']=='verifier.setup_envelope');finish=next(e for e in events if e['phase']=='cache.final_guard')
                self.assertLessEqual(setup['end_ns'],finish['start_ns'])
                for e in events:
                    if e['phase'] in ('cache.identity','cache.pre_use_digest','cache.cold_build'):
                        self.assertLessEqual(setup['start_ns'],e['start_ns']);self.assertLessEqual(e['end_ns'],setup['end_ns'])
        self.assertEqual(total,15)

    def test_hit_miss_bytes_rows_and_phase_counts(self):
        result,*_=self.completed();request=io.read(self.folder/'request.json');context=request['metadata']['context']
        calls=result['cache']['call_observations'];dependencies=context['dependencies']
        self.assertEqual([x['cold'] for x in calls],[True]+[False]*6)
        self.assertEqual(calls[0]['buffer_logical_bytes'],sum(x['bytes'] for x in dependencies.values()))
        self.assertEqual(calls[0]['context_source_logical_bytes'],sum(dependencies[n]['bytes'] for n in ('counts','catalog')))
        self.assertTrue(all(x['buffer_logical_bytes']==x['context_source_logical_bytes']==0 for x in calls[1:]))
        self.assertEqual(len({x['snapshot_digest'] for x in calls}),1)
        self.assertGreater(calls[0]['catalog_rows'],100000);self.assertGreater(calls[0]['count_rows'],0)
        for call in calls:
            self.assertEqual(call['method_verifications'],len(context['methods']))
            self.assertEqual(call['method_logical_bytes'],sum(x['bytes'] for x in context['methods']))

    def test_same_fine_observers_for_both_arms(self):
        result,*_=self.completed()
        for row in result['runs'].values():
            for phase in ('context.load_context','context.prepare_catalog','verifier.setup_envelope'):
                self.assertEqual(row['diagnostic']['phases'][phase]['calls'],1)

    def test_no_hidden_cache_preload(self):
        result,*_=self.completed()
        self.assertEqual(result['runs']['warm_C']['diagnostic']['phases']['cache.cold_build']['calls'],1)
        self.assertFalse(any('cache.cold_build' in row['diagnostic']['phases'] for label,row in result['runs'].items() if label!='warm_C'))
        for label,row in result['runs'].items():
            if row['mode']=='R':self.assertFalse(any(name.startswith(('cache.','snapshot.')) for name in row['diagnostic']['phases']))

    def test_event_cost_load_cache_payload_tamper_rejects(self):
        for relative in ('pair_1_C/measured.json','pair_1_C/events.json','pair_1_C/telemetry_records.json','cache_receipt.json','audited_result.json'):
            p=self.folder/relative;original=p.read_bytes();p.write_bytes(original+b' ')
            try:
                with self.subTest(path=relative),self.assertRaises(ValueError):self.completed()
            finally:p.write_bytes(original)
        p=next((self.folder/'pair_1_C/verified_subset/payloads').glob('*.jsonl'));original=p.read_bytes();p.write_bytes(original+b'{}\n')
        try:
            with self.assertRaises(ValueError):self.completed()
        finally:p.write_bytes(original)

    def test_publisher_semantically_rejects_mixed_schemes(self):
        request=io.read(self.folder/'request.json')
        # Call the raw independent audit, so a post-exit byte seal cannot make
        # these tests pass before the semantic fingerprint checks are reached.
        events_path=self.folder/'warm_C/events.json';original=events_path.read_bytes()
        events=json.loads(original)
        use=next(e for e in events if e['phase']=='cache.use')
        use['metadata']['fingerprint_scheme']='old-C1-scheme'
        events_path.write_bytes(cp.encoded(events))
        try:
            self.assertEqual(observed.summarize_events(events),io.read(self.folder/'warm_C/observation.json'))
            obs=observed.Observation()
            with self.assertRaisesRegex(ValueError,'Cache use differs from independently rebuilt context'):
                adapter.audit_saved_runs(self.folder,request,obs)
            self.assertFalse(obs.stack)
        finally:events_path.write_bytes(original)
        receipt_path=self.folder/'cache_receipt.json';original=receipt_path.read_bytes()
        receipt=json.loads(original);receipt['fingerprint_scheme']='old-C1-scheme'
        receipt_path.write_bytes(cp.encoded(receipt))
        try:
            with self.assertRaisesRegex(ValueError,'cache receipt differs'):
                adapter.audit_saved_runs(self.folder,request,observed.Observation())
        finally:receipt_path.write_bytes(original)
        wrong=deepcopy(request);wrong['metadata']['fingerprint_scheme']='old-C1-scheme'
        with self.assertRaisesRegex(ValueError,'request fingerprint scheme'):
            adapter.audit_saved_runs(self.folder,wrong,observed.Observation())

    def test_worker_failure_deadline_resources_existing_request_and_stopped_descendants(self):
        request_path=self.folder/'request.json';request_bytes=request_path.read_bytes();request=json.loads(request_bytes)
        with self.subTest(existing_request=True),patch('scripts.retailrocket_session_knn_cost_window_v5.subprocess.Popen') as spawn:
            with self.assertRaises(FileExistsError):
                run_window(self.folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(self.folder)],request['sources'],
                    request['operation'],metadata=request['metadata'],budget_seconds=request['budget_seconds'],limits=request['limits'])
            spawn.assert_not_called();self.assertEqual(request_path.read_bytes(),request_bytes)
        p=self.folder/'supervisor_completion.json';original=p.read_bytes();saved=json.loads(original)
        for change in (dict(exit_code=1),dict(tracked_processes_alive_after_cleanup=1),dict(actual_exit_observed_utc='2099-01-01T00:00:00+00:00')):
            p.write_bytes(cp.encoded(dict(saved,**change)))
            try:
                with self.subTest(change=change),self.assertRaises(ValueError):self.completed()
            finally:p.write_bytes(original)
        folder=self.folder.parent/'failed-pipeline';folder.mkdir()
        with patch.object(old_entry.old,'run_child',side_effect=ValueError('worker failed')) as child,self.assertRaises(ValueError):
            adapter.run_pipeline(folder,io.read(self.folder/'request.json'),dict(worker=[],publisher=[]))
        self.assertEqual(child.call_count,1);self.assertFalse((folder/'pipeline_done.json').exists())
        folder=self.folder.parent/'failed-publisher-pipeline';folder.mkdir();commands=dict(worker=['worker'],publisher=['publisher'])
        with patch.object(old_entry.old,'run_child',side_effect=[None,ValueError('publisher failed')]) as child,self.assertRaisesRegex(ValueError,'publisher failed'):
            adapter.run_pipeline(folder,request,commands)
        self.assertEqual(child.call_count,2)
        self.assertEqual([call.args[2] for call in child.call_args_list],['worker','publisher'])
        self.assertFalse((folder/'pipeline_done.json').exists())
        self.assertEqual(io.read(folder/'pipeline_failure.json'),dict(error_type='ValueError'))

    def test_all14_pairs_cold_sum_and_adoption_thresholds_fixed(self):
        result,*_=self.completed();request=io.read(self.folder/'request.json')
        self.assertEqual(len(result['runs']),14);self.assertEqual(old_core.decision(result['runs']),result['decision'])
        for i in range(6):self.assertEqual([x['mode'] for x in request['metadata']['schedule'][2+2*i:4+2*i]],list('RC' if i%2==0 else 'CR'))
        self.assertEqual(sum(x['mode']=='C' for x in request['metadata']['schedule']),7)
        contract_test=previous.ContractTests('test_decision_thresholds_orders_cold_and_primary_are_not_weakened')
        contract_test.test_decision_thresholds_orders_cold_and_primary_are_not_weakened()


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1] in ('--worker','--publisher','--pipeline'):child(sys.argv[2],sys.argv[1][2:])
    else:unittest.main()
