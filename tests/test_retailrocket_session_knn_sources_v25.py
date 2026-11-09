"""Saved artificial48 integration plus real tiny subprocess supervision."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import psutil

from scripts import run_retailrocket_session_knn_sources_v25 as entry
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from tests import test_retailrocket_session_knn_overlap_v22 as fixture
from tests import test_retailrocket_session_knn_reinforcement_v18 as load_fixture


class IntegratedTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.EntryTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.stack=self.fixture.stack
        for name,value in (('ROOT',self.root),('PRIVATE',self.root/'private'),('check_gates',lambda:self.fixture.spec.get('gates',{'reference_gates_verified':6,'reserved_test':'locked'}))):
            self.stack.enter_context(patch.object(entry,name,value))
        self.stack.enter_context(patch.object(entry,'contract',side_effect=lambda r:r['metadata']))
        original,probes,reference,_=self.fixture.comparison()
        self.folder=self.root/'private/knn-v25-sources-synthetic';self.folder.mkdir()
        self.probes,self.reference=probes,reference
        old_request=entry.read(original/'request.json');old_meta=old_request['metadata']
        schedule=[dict(label='warm_R',mode='R'),dict(label='warm_D',mode='D')]
        for i in range(6):
            schedule.extend(dict(label=f'pair_{i+1}_{m}',mode=m) for m in ('RD' if i%2==0 else 'DR'))
        cohort={k:old_meta[k] for k in ('model_root','selected_root','old_run','probes','reference')}
        (self.root/'tiny.txt').write_bytes(b'artificial closure\n')
        self.request=dict(old_request,sources=[entry.describe(self.root/'tiny.txt')],
            metadata=dict(cohort=cohort,schedule=schedule,gates={'reference_gates_verified':6,'reserved_test':'locked'},
                          specification={'synthetic':True},acceptance={'synthetic':True}))
        self.put(self.folder/'request.json',self.request);self.put(self.folder/'worker_done.json',entry.DONE)
        for i,(item,(old_label,_)) in enumerate(zip(schedule,fixture.entry.schedule('compare48','group_before_size_join'))):
            root=self.folder/item['label'];shutil.copytree(original/old_label,root)
            value=entry.read(root/'entry.json');value.update(label=item['label'],mode='baseline');self.put(root/'entry.json',value)
            for name in ('entry_span.json','telemetry_records.json'):
                value=entry.read(root/name);value.update(label=item['label'],mode=item['mode']);self.put(root/name,value)
            if item['mode']=='D':
                obs=Observation()
                with obs.span('run.total'):
                    with obs.span('checkpoint.create'):
                        with obs.span('checkpoint.check_sources',force=False):pass
                    with obs.span('checkpoint.writer_acquire'):
                        with obs.span('checkpoint.check_sources',force=True):pass
                    with obs.span('verifier.total') as event:
                        with obs.span('verifier.setup_envelope'):
                            with obs.span('context.load_context'):pass
                            with obs.span('context.prepare_catalog'):pass
                        event['metadata']['original_setup_seconds']=entry.read(root/'measured.json')['setup_seconds']
                entry.save_observation(root,obs)
        for phase in ('worker_initial_hash','worker_final_hash'):
            obs=Observation()
            with obs.span(phase):obs.verify_bindings(self.request['sources'])
            entry.save_observation(self.folder/phase,obs)
        self.exit('worker',2.,3.)

    def put(self,path,value):return self.fixture.put(path,value)

    def exit(self,kind,start,end):
        value=dict(kind=kind,pid=99999999,create_time=0.,returncode=0,seconds=end-start,
            started_utc=(self.fixture.start+timedelta(seconds=start)).isoformat(),
            ended_utc=(self.fixture.start+timedelta(seconds=end)).isoformat())
        self.put(self.folder/(kind+'_exit.json'),value);return value

    def audited(self):
        obs=Observation();result=obs.publisher(entry.audit_result,self.folder,self.request,obs)
        entry.save_observation(self.folder/'publisher',obs)
        records=load_fixture.telemetry_case(0,(1401.,1401.2,1401.4,1401.6))
        for record in records:record['observed_utc']=(self.fixture.start+timedelta(seconds=record['monotonic_seconds'])).isoformat()
        span=dict(label='publisher',mode='publisher',repeat_index=0,completed=True,
            start_monotonic_seconds=1401.02,end_monotonic_seconds=1401.58,
            start_utc=(self.fixture.start+timedelta(seconds=1401.02)).isoformat(),
            end_utc=(self.fixture.start+timedelta(seconds=1401.58)).isoformat())
        self.put(self.folder/'publisher/entry_span.json',span)
        self.put(self.folder/'publisher/telemetry_records.json',dict(label='publisher',mode='publisher',records=records))
        value=self.exit('publisher',4.,1500.)
        value['outputs']=[entry.describe(self.folder/name) for name in ('audited_result.json','publisher/events.json',
            'publisher/observation.json','publisher/entry_span.json','publisher/telemetry_records.json')]
        self.put(self.folder/'publisher_exit.json',value)
        self.put(self.folder/'supervisor_completion.json',self.fixture.completion)
        self.put(self.folder/'pipeline_done.json',{'completed':True})
        return result

    def test_independent_all14_artificial48_payloads_recompute_and_release_is_immutable(self):
        result=self.audited()
        self.assertEqual(len(result['runs']),14)
        self.assertEqual(result['reference']['records'],48)
        report=entry.release(self.folder)
        self.assertEqual(report['scope']['engineering_checks'],672)
        self.assertEqual(report,entry.release(self.folder))
        self.assertEqual(report['publisher_observation']['source_descriptors']['completed_calls'],2)

    def test_worker_failure_prevents_publisher_and_publisher_failure_prevents_pipeline_done(self):
        for failure in ('worker','publisher'):
            folder=self.root/'private'/('knn-v25-sources-'+failure)
            folder.mkdir();self.put(folder/'request.json',self.request)
            calls=[]
            def child(folder,request,kind):
                calls.append(kind)
                if kind==failure:raise ValueError('artificial child failure')
            with patch.object(entry,'run_child',side_effect=child),self.assertRaises(ValueError):entry.pipeline(folder)
            self.assertEqual(calls,['worker'] if failure=='worker' else ['worker','publisher'])
            self.assertFalse((folder/'pipeline_done.json').exists())
            self.assertFalse((self.root/entry.REPORT).exists())

    def test_stale_worker_deadline_and_mismatched_sources_reject_before_success(self):
        value=entry.read(self.folder/'worker_exit.json');original=deepcopy(value)
        value.update(pid=psutil.Process().pid,create_time=psutil.Process().create_time())
        self.put(self.folder/'worker_exit.json',value)
        with self.assertRaises(ValueError):entry.audit_result(self.folder,self.request,Observation())
        self.put(self.folder/'worker_exit.json',original)
        deadline=dict(original,ended_utc=(self.fixture.start+timedelta(seconds=1801)).isoformat())
        self.put(self.folder/'worker_exit.json',deadline)
        with self.assertRaises(ValueError):entry.audit_result(self.folder,self.request,Observation())
        self.put(self.folder/'worker_exit.json',original)
        (self.root/'tiny.txt').write_bytes(b'changed same bytes\n')
        with self.assertRaises(ValueError):entry.audit_result(self.folder,self.request,Observation())

    def test_original_payload_cost_event_load_and_clock_tampering_withholds_audit(self):
        root=self.folder/'pair_1_D'
        cases=[('measured.json',lambda x:x['queries'][0].update(verification_seconds=-1.)),
            ('events.json',lambda x:x[-1].update(end_ns=None)),
            ('entry_span.json',lambda x:x.update(completed=False)),
            ('telemetry_records.json',lambda x:x.update(mode='R')),
            ('verified_subset/run.json',lambda x:x.update(budget_seconds=1801)),
            ('proof.json',lambda x:x.update(actual_committed_payload_sha256='0'*64))]
        for name,mutate in cases:
            p=root/name;raw=p.read_bytes();value=json.loads(raw);mutate(value);self.put(p,value)
            try:
                with self.subTest(name=name),self.assertRaises(ValueError):entry.audit_result(self.folder,self.request,Observation())
                self.assertFalse((self.root/entry.REPORT).exists())
            finally:p.write_bytes(raw)
        payload=next((root/'verified_subset/payloads').glob('*.jsonl'));payload.write_bytes(payload.read_bytes()+b'{}\n')
        with self.assertRaises(ValueError):entry.audit_result(self.folder,self.request,Observation())

    def test_post_publisher_result_or_worker_evidence_modification_rejected(self):
        self.audited()
        for path in (self.folder/'audited_result.json',self.folder/'pair_1_R/measured.json'):
            raw=path.read_bytes();path.write_bytes(raw+b' ')
            try:
                with self.assertRaises(ValueError):entry.release(self.folder)
                self.assertFalse((self.root/entry.REPORT).exists())
            finally:path.write_bytes(raw)

    def test_actual_child_exit_is_observed_and_nonzero_exit_rejected(self):
        self.folder.joinpath('worker_exit.json').unlink()
        result=entry.run_child(self.folder,self.request,'worker',[sys.executable,'-B','-c','pass'])
        self.assertEqual(result['returncode'],0)
        with self.assertRaises(ValueError):
            entry.run_child(self.folder,self.request,'publisher',[sys.executable,'-B','-c','raise SystemExit(3)'])
        self.assertEqual(entry.read(self.folder/'publisher_exit.json')['returncode'],3)

    def test_outer_failure_after_private_audit_withholds_public_result(self):
        self.audited()
        for key,value in (('exit_code',1),('tracked_processes_alive_after_cleanup',1),
            ('actual_exit_observed_utc',(self.fixture.start+timedelta(seconds=1801)).isoformat())):
            changed=dict(self.fixture.completion,**{key:value})
            self.put(self.folder/'supervisor_completion.json',changed)
            with self.subTest(key=key),self.assertRaises(ValueError):entry.release(self.folder)
            self.assertFalse((self.root/entry.REPORT).exists())

    def test_existing_failed_namespace_prevents_new_measurement(self):
        with patch.object(entry,'source_contract',return_value=(self.request['sources'],self.request['metadata'])),patch.object(entry,'run_window') as run:
            with self.assertRaises(FileExistsError):entry.measure()
        run.assert_not_called()


class ContractTests(unittest.TestCase):
    def test_sealed_scope_and_original_window_constraints(self):
        spec=entry.specification();self.assertEqual(len(spec['schedule']),14)
        request=dict(created_utc='2026-11-09T00:00:00+00:00',deadline_utc='2026-11-09T00:30:00+00:00',
            budget_seconds=1800,limits=entry.LIMITS,operation='joint_tail',full_readback_enabled=False,
            reserved_test='locked',T_plan=None,sources=[{'artificial':True}],metadata={'artificial':True})
        with patch.object(entry,'source_contract',return_value=(request['sources'],request['metadata'])):
            entry.contract(request)
            for key,value in (('budget_seconds',1801),('deadline_utc','2026-11-09T00:31:00+00:00'),
                              ('limits',dict(entry.LIMITS,rss_bytes=1)),('reserved_test','open'),('metadata',{})):
                with self.subTest(key=key),self.assertRaises(ValueError):entry.contract(dict(request,**{key:value}))

    def test_actual_supervisor_deadline_cleans_pipeline_descendant(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/'small';data.write_bytes(b'x')
            record=dict(path=str(data),bytes=1,sha256=hashlib.sha256(b'x').hexdigest())
            code='import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);time.sleep(60)'
            result=run_window(root/'window',[sys.executable,'-B','-c',code],[record],
                              'joint_tail',budget_seconds=2,limits=entry.LIMITS,poll_seconds=.05)
            self.assertEqual(result['stop_reason'],'deadline')
            self.assertEqual(result['tracked_processes_alive_after_cleanup'],0)
            self.assertGreaterEqual(result['tracked_processes'],2)


if __name__=='__main__':unittest.main()
