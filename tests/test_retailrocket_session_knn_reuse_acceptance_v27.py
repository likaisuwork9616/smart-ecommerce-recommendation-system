"""Additional C1 adversarial cases and real subprocesses over artificial48 sources only."""
from bisect import bisect_left
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import retailrocket_session_knn_reuse_v27 as reuse
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import run_retailrocket_session_knn_v2 as io
from scripts import run_retailrocket_session_knn_sources_v25 as supervisor
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.retailrocket_session_knn_reinforcement_v18 import TelemetrySampler
from scripts.retailrocket_session_knn_reuse_audit_v27 import audit_saved_runs
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from tests import test_retailrocket_session_knn_reuse_v27 as focused
from tests import test_retailrocket_session_knn_validation as validation
from tests import test_retailrocket_session_knn as base_fixture
from tests import test_retailrocket_session_knn_pair_v4 as four

PRIVATE=io.ROOT/'shop-mysql-runtime/verification'
MODULE='tests.test_retailrocket_session_knn_reuse_acceptance_v27'


class AdversarialTests(unittest.TestCase):
    setUp=focused.ContextTests.setUp
    rebind=focused.ContextTests.rebind
    store=focused.ContextTests.store
    load=focused.ContextTests.load
    cycle=focused.ContextTests.cycle

    def test_same_size_changed_content(self):
        record=self.contract['dependencies']['counts'];p=self.root/record['path']
        p.write_bytes(p.read_bytes().replace(b'1,3',b'1,4'))
        with self.assertRaises(ValueError):reuse.verified_buffer(self.root,record)

    def test_changed_size(self):
        record=self.contract['dependencies']['counts'];p=self.root/record['path'];p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaises(ValueError):reuse.verified_buffer(self.root,record)

    def test_cold_dependency_cannot_substitute_an_unbound_same_content_path(self):
        p=self.root/'unbound.csv';p.write_bytes((self.root/'P0/item_counts.csv').read_bytes())
        self.contract['dependencies']['counts']=cp.descriptor(self.root,'unbound.csv')
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)
        self.assertTrue(self.pool.poisoned)

    def test_malformed_descriptor_cannot_disable_buffer_bound(self):
        original=self.contract['dependencies']['counts']
        for change in (dict(bytes=-2),dict(bytes=True),dict(sha256='X'*64)):
            with self.subTest(change=change),self.assertRaises(ValueError):reuse.verified_buffer(self.root,dict(original,**change))

    def test_changed_parser_or_prepare_method(self):
        self.cycle();store,obs=self.store()
        with store.writer(),patch.object(pair.sql,'prepare_catalog',side_effect=AssertionError('Must reject before parser')),self.assertRaises(ValueError):self.load(store,obs)
        self.rebind();self.contract['methods'][0]['sha256']='0'*64;store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_mtime_only_match_cannot_authorize_hit(self):
        self.cycle();p=self.root/'P0/item_counts.csv';before=p.stat();p.write_bytes(p.read_bytes().replace(b'1,3',b'1,4'))
        os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.assertEqual(p.stat().st_size,before.st_size)
        self.assertEqual(p.stat().st_mtime_ns,before.st_mtime_ns)
        with self.assertRaises(cp.IntegrityError):self.store()

    def test_parse_exact_sha_verified_buffer(self):
        target=self.root/'P0/item_counts.csv';original=target.read_bytes()
        class MutateAfterRead(observed.Observation):
            @contextmanager
            def span(inner,phase,**metadata):
                with super(MutateAfterRead,inner).span(phase,**metadata) as event:
                    if phase=='cache.original_load_context':target.write_bytes(original.replace(b'1,3',b'1,4'))
                    yield event
        store,unused=self.store();obs=MutateAfterRead()
        with store.writer():
            counts,catalog=self.load(store,obs);self.assertEqual(counts['1'],3)
            self.pool.prepare(catalog,counts,lambda:None);self.pool.finish(obs,lambda:None)
        with self.assertRaises(cp.IntegrityError):cp.verify_sources(self.root,self.binding['sources'])

    def test_bytes_change_during_buffer_acquisition(self):
        p=self.root/'large';p.write_bytes(b'A'*(2*1024*1024));record=cp.descriptor(self.root,'large');calls=0
        def watch():
            nonlocal calls
            calls+=1
            if calls==2:
                with p.open('r+b') as stream:stream.seek(1024*1024);stream.write(b'B')
        with self.assertRaises(ValueError):reuse.verified_buffer(self.root,record,watch)
        self.assertGreaterEqual(calls,2)

    def test_header_or_width_error(self):
        p=self.root/'P0/item_counts.csv'
        for content in ('wrong,count\n1,3\n','itemid,count\n1,3,extra\n','itemid,count\n1\n'):
            p.write_text(content,encoding='utf-8');self.rebind()
            with self.subTest(content=content),self.assertRaises(ValueError):self.cycle()
            self.assertTrue(self.pool.poisoned)

    def test_duplicate_id_or_noncanonical_number(self):
        p=self.root/'P0/item_counts.csv'
        for content in ('itemid,count\n1,3\n1,2\n','itemid,count\n01,3\n2,2\n'):
            p.write_text(content,encoding='utf-8');self.rebind()
            with self.subTest(content=content),self.assertRaises(ValueError):self.cycle()

    def test_nonpositive_counts_or_support_mismatch(self):
        p=self.root/'P0/item_counts.csv'
        for content in ('itemid,count\n1,0\n2,2\n','itemid,count\n1,1\n2,2\n','itemid,count\n1,3\n'):
            p.write_text(content,encoding='utf-8');self.rebind()
            with self.subTest(content=content),self.assertRaises(ValueError):self.cycle()

    def test_training_clock_violation(self):
        (self.root/'dataset/catalog.csv').write_text('itemid,first_view_ms\n1,10\n2,2\n',encoding='utf-8');self.rebind()
        with self.assertRaises(ValueError):self.cycle()

    def test_second_sort_tuple_equivalence_including_ties(self):
        (self.root/'dataset/catalog.csv').write_text('itemid,first_view_ms\n1,1\n2,1\n3,11\n',encoding='utf-8');self.rebind()
        _,_,p=self.cycle();original=sorted(p.first.values())
        self.assertEqual(tuple(original),p.first_times)
        for t in (0,1,2,10,11,12):self.assertEqual(bisect_left(original,t),bisect_left(p.first_times,t))
        # C1 keeps the original verify_selected bytecode, including its own sorted call.
        self.assertIs(reuse.ORIGINALS[0],pair.verify_selected)
        self.assertIn('sorted',pair.verify_selected.__code__.co_names)

    def test_writer_lock_failure(self):
        store,obs=self.store()
        with patch.object(cp,'_lock',side_effect=OSError('artificial lock failure')),self.assertRaises(OSError):
            with store.writer():self.fail('Lock failure reached borrower')
        self.assertIsNone(store._guard);self.assertIsNone(self.pool.prepared)

    def test_resume_rejects_previous_process_cache(self):
        store,obs,_=self.cycle();reopened=reuse.ReuseStore.open(store.folder,self.binding,source_root=self.root,observer=observed.Observation())
        with reopened.writer(),self.assertRaises(ValueError):self.load(reopened,observed.Observation())

    def test_deadline_or_resource_stop(self):
        store,obs=self.store()
        def expired():raise TimeoutError('artificial deadline')
        with store.writer(),self.assertRaises(TimeoutError):
            self.pool.load(self.paths,self.config,self.model['support'],expired,model=self.model,store=store,
                namespace='artificial-window',request=self.request,observer=obs)
        self.assertTrue(self.pool.poisoned)
        record=dict(self.contract['dependencies']['counts'],path=str(self.root/'P0/item_counts.csv'))
        result=run_window(self.root/'tiny-limit',[sys.executable,'-B','-c','import time;time.sleep(60)'],[record],
            'joint_tail',budget_seconds=3,limits=dict(LIMITS,rss_bytes=1),poll_seconds=.05)
        self.assertEqual(result['stop_reason'],'rss_limit');self.assertEqual(result['tracked_processes_alive_after_cleanup'],0)

    def test_immutable_acceptance_and_existing_output(self):
        store,obs,_=self.cycle();cp.atomic_json(store.folder/'acceptance.json',{'artificial':True})
        with self.assertRaises(cp.IntegrityError),store.writer():self.fail('Immutable acceptance reached borrower')
        with self.assertRaises(FileExistsError):reuse.ReuseStore.create(store.folder,self.binding,self.request['deadline_utc'],300,source_root=self.root,observer=obs)

    def test_body_exception_cleanup(self):
        with tempfile_artificial_four() as data:
            root,paths,config,primary,database,model,ordinals,binding,contract=data
            pool=reuse.WorkerContext(contract,root,io.ROOT);obs=observed.Observation()
            request=dict(deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat(),budget_seconds=180)
            store=reuse.ReuseStore.create(root/'failed',binding,request['deadline_utc'],180,source_root=root,observer=obs,
                expected_queries=len(ordinals),required_stages=('reconstruction','queries'))
            def interrupt(point):
                if point=='query_work':raise RuntimeError('artificial verifier failure')
            with self.assertRaises(RuntimeError),store.writer():
                four.reconstruct_seal(store,model)
                reuse.make_verifier(obs,pool,'artificial-window',request)(primary,paths,config,store,model,database,ordinals,fault=interrupt)
            self.assertTrue(pool.poisoned);self.assertIsNone(store._guard);self.assertFalse(obs.stack)


@contextmanager
def tempfile_artificial_four():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        with patch.object(four,'make_fixture',side_effect=lambda **kw:validation.make_fixture(base=temp,**kw)):
            root,paths,config,primary,_,database,model,ordinals,binding=four.fixture()
        (root/'reconstruction.json').write_text(json.dumps({'receipt':model}),encoding='utf-8')
        binding['sources']=cp.bind_sources(root,[x['path'] for x in binding['sources']]+['reconstruction.json'])
        d={x['path']:x for x in binding['sources']}
        contract=dict(binding=binding,dependencies={k:d[p] for k,p in (
            ('counts','P0/item_counts.csv'),('catalog','dataset/catalog.csv'),('config','configuration.json'),('model','reconstruction.json'))},
            methods=[io.describe(io.ROOT/'scripts/retailrocket_session_knn_reuse_v27.py')],environment=io.environment())
        yield root,paths,config,primary,database,model,ordinals,binding,contract


def artificial48_inputs(boundary=False):
    rows,counts,support,catalog,queries,refs,draws,fits,expected=base_fixture.fixture_inputs(False)
    index=next(i for i,(q,_) in enumerate(queries) if q.visitorid=='90' and q.query_ms==110)
    query,basket_index=queries[index];reference=refs[index]
    validation_rows=[b for b in rows if b.visitor=='90' and b.role=='validation']
    rows=[b for b in rows if b.role!='validation'];new_queries=[];new_refs=[]
    for n in range(48):
        visitor=str(20000+n);rows.extend(replace(b,visitor=visitor) for b in validation_rows)
        new_queries.append((replace(query,visitorid=visitor),basket_index))
        ref=deepcopy(reference);ref['key'][0]=visitor;new_refs.append(ref)
    rows.sort(key=lambda b:b.key());draws=[]
    validation.c.bootstrap([(q.visitorid,r['terms']['C1']['ndcg']-r['terms']['P0']['ndcg']) for (q,_),r in zip(new_queries,new_refs)],draws.append)
    expected=dict(expected,queries=48,visitors=48,target_occurrences=sum(len(q.targets) for q,_ in new_queries),
        reachable_target_occurrences=sum(q.reachable_count for q,_ in new_queries),
        all_targets_reachable_queries=sum(q.all_reachable for q,_ in new_queries),candidate_union_items=query.candidate_count)
    return rows,counts,support,catalog,new_queries,new_refs,draws,fits,expected


def scope(folder):
    folder=Path(folder).resolve()
    if not folder.is_relative_to(PRIVATE.resolve()) or not folder.parent.name.startswith('knn-v27-c1-synthetic-'):
        raise ValueError('Artificial-only private namespace required')
    request=io.read(folder/'request.json')
    if request['metadata'].get('synthetic_acceptance_only') is not True:raise ValueError('No real execution authority')
    return folder,request


def data_for(request):
    data=io.read(io.ROOT/request['metadata']['synthetic_data']['path']);cohort=request['metadata']['cohort'];selected=io.ROOT/cohort['selected_root']
    return data,(selected,io.read(selected/'configuration.json'),data['contract']['binding'],data['model'],
        io.ROOT/data['database'],data['probes'],data['ordinals'],io.read(io.ROOT/cohort['reference']))


def worker(folder):
    folder,request=scope(folder);data,inputs=data_for(request);watch=supervisor.ThrottledWatch(folder,request['deadline_utc'])
    pool=reuse.WorkerContext(data['contract'],io.ROOT,io.ROOT)
    for phase in ('worker_initial_hash',):supervisor.hash_phase(folder,request,phase,watch)
    for item in request['metadata']['schedule']:
        root=folder/item['label'];root.mkdir();obs=observed.Observation();sampler=TelemetrySampler();sampler.start(0)
        start=time.perf_counter();span=dict(label=item['label'],mode=item['mode'],repeat_index=0,completed=False,
            start_monotonic_seconds=start,start_utc=datetime.now(timezone.utc).isoformat())
        try:
            reuse.run_fixed48(folder,request,item['label'],item['mode'],inputs,observer=obs,pool=pool,source_root=io.ROOT,watch=watch)
            # Artificial harness padding provides >=3 real telemetry brackets; never a speed claim.
            while time.perf_counter()-start<.45:time.sleep(.02)
            span['completed']=True
        finally:
            span.update(end_monotonic_seconds=time.perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
            sampler.stop();io.write(root/'entry_span.json',span)
            io.write(root/'telemetry_records.json',dict(label=item['label'],mode=item['mode'],records=sampler.records))
            supervisor.save_observation(root,obs)
    io.write(folder/'cache_receipt.json',pool.completed_summary());pool.close()
    supervisor.hash_phase(folder,request,'worker_final_hash',watch)
    io.write(folder/'worker_done.json',supervisor.DONE)


def publisher(folder):
    folder,request=scope(folder);root=folder/'publisher';root.mkdir();obs=observed.Observation();sampler=TelemetrySampler();sampler.start(0)
    span=dict(label='publisher',mode='publisher',repeat_index=0,completed=False,start_monotonic_seconds=time.perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:
        obs.publisher(audit_saved_runs,folder,request,obs)
        while time.perf_counter()-span['start_monotonic_seconds']<.45:time.sleep(.02)
        span['completed']=True
    finally:
        span.update(end_monotonic_seconds=time.perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        sampler.stop();io.write(root/'entry_span.json',span)
        io.write(root/'telemetry_records.json',dict(label='publisher',mode='publisher',records=sampler.records))
        supervisor.save_observation(root,obs)


def pipeline(folder):
    folder,request=scope(folder)
    for kind in ('worker','publisher'):
        supervisor.run_child(folder,request,kind,[sys.executable,'-B','-m',MODULE,'--'+kind,str(folder)])
    io.write(folder/'pipeline_done.json',{'completed':True})


def build_window():
    bundle=PRIVATE/('knn-v27-c1-synthetic-'+uuid4().hex);bundle.mkdir()
    with patch.object(validation,'fixture_inputs',side_effect=artificial48_inputs),patch.object(four,'make_fixture',side_effect=lambda **kw:validation.make_fixture(base=bundle,**kw)):
        root,paths,config,primary,_,database,model,ordinals,binding=four.fixture()
    (root/'reconstruction.json').write_text(json.dumps({'receipt':model}),encoding='utf-8')
    # Relative source identities are anchored to the same project root in every child.
    records=cp.bind_sources(io.ROOT,[p.relative_to(io.ROOT).as_posix() for p in root.rglob('*') if p.is_file()])
    binding=dict(binding,sources=records);d={x['path']:x for x in records}
    rel=lambda p:p.relative_to(io.ROOT).as_posix()
    contract=dict(binding=binding,dependencies={k:d[rel(p)] for k,p in (
        ('counts',paths['P0']/'item_counts.csv'),('catalog',paths['dataset']/'catalog.csv'),('config',root/'configuration.json'),('model',root/'reconstruction.json'))},
        methods=[io.describe(io.ROOT/p) for p in ('scripts/retailrocket_session_knn_reuse_v27.py','scripts/retailrocket_session_knn_reuse_audit_v27.py')],environment=io.environment())
    deadline=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    reference_store=reuse.ReuseStore.create(bundle/'reference/verified_subset',binding,deadline,1800,source_root=io.ROOT,
        observer=observed.Observation(),expected_queries=48,required_stages=('reconstruction','queries'))
    with reference_store.writer():
        four.reconstruct_seal(reference_store,model);pair.verify_selected(primary,paths,config,reference_store,model,database,ordinals)
    probes=[dict(key=x['key'],original_ordinal=x['original_ordinal'],key_sha256=hashlib.sha256(pair.dump(x['key']).encode()).hexdigest()) for x in ordinals]
    reference=ledger_proof(reference_store,probes);io.write(bundle/'reference.json',reference);io.write(bundle/'probes.json',{'probes':probes})
    io.write(bundle/'data.json',dict(contract=contract,model=model,database=rel(database),ordinals=ordinals,probes=probes))
    cohort=dict(selected_root=rel(root),model_root=rel(primary),old_run=rel(reference_store.folder/'run.json'),probes=rel(bundle/'probes.json'),reference=rel(bundle/'reference.json'))
    schedule=[dict(label='warm_'+m,mode=m) for m in ('R','C')]+[dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')]
    # Freeze all artificial inputs/reference and actual method bytes before starting the one window.
    sources=[io.describe(p) for p in sorted(bundle.rglob('*')) if p.is_file()]
    for p in ('scripts/retailrocket_session_knn_reuse_v27.py','scripts/retailrocket_session_knn_reuse_audit_v27.py',__file__):
        path=Path(p);sources.append(io.describe(path if path.is_absolute() else io.ROOT/path))
    metadata=dict(cohort=cohort,schedule=schedule,gates=io.check_gates(),synthetic_acceptance_only=True,synthetic_data=io.describe(bundle/'data.json'))
    folder=bundle/'window'
    completion=run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],sources,'joint_tail',metadata=metadata,budget_seconds=1800,limits=LIMITS)
    if completion['exit_code']!=0:
        logs='\n'.join(p.read_text(encoding='utf-8',errors='replace')[-6000:] for p in folder.glob('*.log'))
        raise AssertionError(logs)
    return folder


def release(folder):
    folder,request=scope(folder);supervisor._check_window(request,io.read(folder/'supervisor_completion.json'))
    if io.read(folder/'pipeline_done.json')!={'completed':True}:raise ValueError('Pipeline incomplete')
    for kind in ('worker','publisher'):supervisor.child_exit(folder,request,kind)
    io.verify_bindings(io.read(folder/'publisher_exit.json')['outputs'])
    result=io.read(folder/'audited_result.json');io.verify_bindings(result['evidence'])
    events,summary=supervisor.check_observation(folder/'publisher')
    supervisor.load_summary(folder/'publisher',request,'publisher','publisher')
    binding=io.read(io.ROOT/request['metadata']['cohort']['old_run'])['binding']['sources']
    if summary['source_descriptors']['completed_calls']!=2*len(request['sources'])+14*len(binding):raise ValueError('Independent source count changed')
    if [e['metadata']['descriptor'] for e in events if e['phase']=='closure.descriptor']!=request['sources']*2:raise ValueError('Independent identities changed')
    return result


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.folder=build_window()

    def test_new_interpreter_no_worker_snapshot(self):
        result=release(self.folder)
        self.assertEqual(result['cache']['cold_builds'],1);self.assertEqual(result['cache']['hits'],6)
        self.assertEqual(len(result['runs']),14)
        worker_exit=io.read(self.folder/'worker_exit.json');pub_exit=io.read(self.folder/'publisher_exit.json')
        self.assertNotEqual(worker_exit['pid'],pub_exit['pid']);self.assertLessEqual(worker_exit['ended_utc'],pub_exit['started_utc'])
        self.assertFalse(any('snapshot' in p.name for p in self.folder.rglob('*') if p.is_file()))

    def test_both_full_closure_checks_all_original_sources(self):
        result=release(self.folder);pub=io.read(self.folder/'publisher/observation.json')
        self.assertEqual(pub['phases']['closure.verify_bindings']['calls'],2)
        self.assertEqual(pub['phases']['checkpoint.open']['calls'],14)
        self.assertEqual(result['cache']['candidate_runs'],7)

    def test_all14_original_store_opens_and_physical_frame_proofs(self):
        result=release(self.folder);request=io.read(self.folder/'request.json')
        original=list(_physical_frames((io.ROOT/request['metadata']['cohort']['old_run']).parent))
        for label in result['runs']:self.assertEqual(list(_physical_frames(self.folder/label/'verified_subset')),original)
        self.assertEqual(len(original),48)

    def test_event_cost_load_or_payload_tamper(self):
        for relative in ('pair_1_C/events.json','pair_1_C/measured.json','pair_1_C/telemetry_records.json','cache_receipt.json'):
            p=self.folder/relative;original=p.read_bytes();p.write_bytes(original+b' ')
            try:
                with self.subTest(path=relative),self.assertRaises(ValueError):release(self.folder)
            finally:p.write_bytes(original)
        p=next((self.folder/'pair_1_C/verified_subset/payloads').glob('*.jsonl'));original=p.read_bytes();p.write_bytes(original+b'{}\n')
        try:
            with self.assertRaises(ValueError):release(self.folder)
        finally:p.write_bytes(original)

    def test_publisher_failure_live_descendant_or_expiry_withholds_release(self):
        p=self.folder/'supervisor_completion.json';original=p.read_bytes();saved=json.loads(original)
        for changes in (dict(exit_code=1),dict(tracked_processes_alive_after_cleanup=1),dict(actual_exit_observed_utc='2099-01-01T00:00:00+00:00')):
            p.write_bytes(cp.encoded(dict(saved,**changes)))
            try:
                with self.subTest(changes=changes),self.assertRaises(ValueError):release(self.folder)
            finally:p.write_bytes(original)

    def test_cold_build_key_checks_and_digests_inside_entry(self):
        result=release(self.folder)
        for label,row in result['runs'].items():
            events=io.read(self.folder/label/'events.json');root=next(e for e in events if e['phase']=='run.total')
            for e in events:self.assertLessEqual(root['start_ns'],e['start_ns']);self.assertLessEqual(e['end_ns'],root['end_ns'])
            if row['mode']=='C':
                setup=next(e for e in events if e['phase']=='verifier.setup_envelope')
                for e in events:
                    if e['phase'] in ('cache.identity','cache.pre_use_digest','cache.cold_build'):
                        self.assertLessEqual(setup['start_ns'],e['start_ns']);self.assertLessEqual(e['end_ns'],setup['end_ns'])
                self.assertEqual(row['diagnostic']['phases']['cache.final_guard']['calls'],1)

    def test_hit_miss_bytes_rows_and_phase_counts(self):
        result=release(self.folder);calls=result['cache']['call_observations']
        self.assertEqual([x['cold'] for x in calls],[True]+[False]*6)
        self.assertGreater(calls[0]['buffer_logical_bytes'],0)
        self.assertTrue(all(x['buffer_logical_bytes']==0 for x in calls[1:]))
        self.assertEqual(len({x['snapshot_digest'] for x in calls}),1)
        self.assertGreater(calls[0]['catalog_rows'],0)

    def test_same_fine_observers_for_both_arms(self):
        result=release(self.folder)
        for row in result['runs'].values():
            for phase in ('context.load_context','context.prepare_catalog','verifier.setup_envelope'):
                self.assertEqual(row['diagnostic']['phases'][phase]['calls'],1)

    def test_all14_retained_and_both_orders(self):
        result=release(self.folder);schedule=io.read(self.folder/'request.json')['metadata']['schedule']
        self.assertEqual(list(result['runs']),[x['label'] for x in sorted(schedule,key=lambda x:x['label'])])
        self.assertEqual(len(schedule),14);self.assertEqual(sum(x['mode']=='R' for x in schedule),7)
        for i in range(6):self.assertEqual([x['mode'] for x in schedule[2+i*2:4+i*2]],list('RC' if i%2==0 else 'CR'))

    def test_no_hidden_cache_preload(self):
        result=release(self.folder)
        self.assertEqual(result['runs']['warm_C']['diagnostic']['phases']['cache.cold_build']['calls'],1)
        self.assertFalse(any('cache.cold_build' in row['diagnostic']['phases'] for label,row in result['runs'].items() if label!='warm_C'))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1] in ('--worker','--publisher','--pipeline'):
        {'--worker':worker,'--publisher':publisher,'--pipeline':pipeline}[sys.argv[1]](Path(sys.argv[2]))
    else:unittest.main()
