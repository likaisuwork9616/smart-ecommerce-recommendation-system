"""Real V28 orchestration bytecode over separately identified artificial48 sources."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import run_retailrocket_session_knn_compare_v28 as entry
from scripts import retailrocket_session_knn_compare_v28 as core
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import run_retailrocket_session_knn_v2 as io
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.retailrocket_session_knn_reuse_v27 import ReuseStore
from tests import test_retailrocket_session_knn_reuse_acceptance_v27 as fixture
from tests import test_retailrocket_session_knn_validation as validation
from tests import test_retailrocket_session_knn_pair_v4 as four

MODULE='tests.test_retailrocket_session_knn_compare_v28'


def artificial_inputs(boundary=False):
    data=list(fixture.artificial48_inputs())
    # Future-only artificial items leave all48 scientific predictions unchanged.
    # Real initialization work, not sleeps, makes both arms long enough for telemetry.
    data[3]=list(data[3])+[(str(1000000+i),1000000) for i in range(100000)]
    return tuple(data)


def scope(folder):
    folder=Path(folder).resolve()
    if folder.parent.parent!=entry.PRIVATE.resolve() or not folder.parent.name.startswith('knn-v28-c1-synthetic-'):
        raise ValueError('Artificial bridge only')
    request=io.read(folder/'request.json')
    if not request['metadata'].get('synthetic_acceptance_only'):raise ValueError('Artificial marker required')
    return folder,request


def child(folder,kind):
    folder,request=scope(folder)
    if kind=='pipeline':
        return entry.run_pipeline(folder,request,{k:[sys.executable,'-B','-m',MODULE,'--'+k,str(folder)] for k in ('worker','publisher')})
    if kind=='publisher':return entry.run_publisher(folder,request)
    return entry.run_worker(folder,request,lambda:fixture.data_for(request)[1])


def build_window():
    bundle=entry.PRIVATE/('knn-v28-c1-synthetic-'+uuid4().hex);bundle.mkdir()
    with patch.object(validation,'fixture_inputs',side_effect=artificial_inputs),patch.object(four,'make_fixture',side_effect=lambda **kw:validation.make_fixture(base=bundle,**kw)):
        root,paths,config,primary,_,database,model,ordinals,binding=four.fixture()
    io.write(root/'reconstruction.json',{'receipt':model})
    rel=lambda p:p.relative_to(io.ROOT).as_posix()
    records=cp.bind_sources(io.ROOT,[rel(p) for p in root.rglob('*') if p.is_file()]);binding=dict(binding,sources=records);d={x['path']:x for x in records}
    deadline=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    reference=ReuseStore.create(bundle/'reference/verified_subset',binding,deadline,1800,source_root=io.ROOT,observer=Observation(),
        expected_queries=48,required_stages=('reconstruction','queries'))
    with reference.writer():
        four.reconstruct_seal(reference,model);pair.verify_selected(primary,paths,config,reference,model,database,ordinals)
    probes=[dict(key=x['key'],original_ordinal=x['original_ordinal'],key_sha256=hashlib.sha256(pair.dump(x['key']).encode()).hexdigest()) for x in ordinals]
    io.write(bundle/'reference.json',ledger_proof(reference,probes));io.write(bundle/'probes.json',dict(probes=probes))
    dependencies={k:d[rel(p)] for k,p in (('counts',paths['P0']/'item_counts.csv'),('catalog',paths['dataset']/'catalog.csv'),
        ('config',root/'configuration.json'),('model',root/'reconstruction.json'))}
    methods=[io.describe(io.ROOT/p) for p in entry.METHODS]
    io.write(bundle/'data.json',dict(contract=dict(binding=binding),model=model,database=rel(database),ordinals=ordinals,probes=probes))
    cohort=dict(selected_root=rel(root),model_root=rel(primary),old_run=rel(reference.folder/'run.json'),
        probes=rel(bundle/'probes.json'),reference=rel(bundle/'reference.json'))
    schedule=[dict(label='warm_'+m,mode=m) for m in ('R','C')]+[dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')]
    sources=[io.describe(p) for p in sorted(bundle.rglob('*')) if p.is_file()]+methods
    meta=dict(cohort=cohort,schedule=schedule,context=dict(dependencies=dependencies,methods=methods),environment=io.environment(),
        gates=io.check_gates(),synthetic_acceptance_only=True,synthetic_data=io.describe(bundle/'data.json'),
        specification={'artificial':True},acceptance={'artificial':True})
    folder=bundle/'window';completion=run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],sources,
        'joint_tail',metadata=meta,budget_seconds=1800,limits=LIMITS)
    if completion['exit_code']!=0:
        raise AssertionError('\n'.join(p.read_text(encoding='utf-8',errors='replace')[-8000:] for p in folder.glob('*.log')))
    return folder


class ContractTests(unittest.TestCase):
    def test_real_specification_and_exact_original_scope(self):
        spec=entry.specification();self.assertEqual(len(spec['inherited_sources']),596);self.assertEqual(len(spec['original_binding_sources']),15)
        for key,value in (('budget_seconds',1801),('status','synthetic'),('schedule',[])):
            changed=deepcopy(spec);changed[key]=value
            original=entry.read
            with patch.object(entry,'read',side_effect=lambda p:changed if Path(p)==io.ROOT/entry.SPEC else original(p)),self.assertRaises(ValueError):entry.specification()

    def test_request_synthetic_marker_roster_context_and_limits_reject(self):
        request=dict(created_utc='2026-11-09T00:00:00+00:00',deadline_utc='2026-11-09T00:30:00+00:00',budget_seconds=1800,
            limits=LIMITS,operation='joint_tail',full_readback_enabled=False,reserved_test='locked',T_plan=None,sources=[{'path':'artificial'}],metadata={'fixed':'real'})
        with patch.object(entry,'source_contract',return_value=(request['sources'],request['metadata'])):
            entry.contract(request)
            for update in (dict(metadata={'synthetic_acceptance_only':True}),dict(sources=[]),dict(metadata={'context':{}}),dict(budget_seconds=1801)):
                with self.subTest(update=update),self.assertRaises(ValueError):entry.contract(dict(request,**update))

    def test_exact_context_dependencies_and_methods_are_bound(self):
        record=dict(path='x',bytes=1,sha256='0'*64);binding=dict(sources=[record]);deps={n:record for n in ('counts','catalog','config','model')}
        request=dict(sources=[record],metadata=dict(context=dict(dependencies=deps,methods=[record]),environment={}))
        core.context_contract(request,binding)
        for key in ('dependencies','methods'):
            changed=deepcopy(request);bad=dict(record,path='unbound')
            if key=='dependencies':changed['metadata']['context'][key]['model']=bad
            else:changed['metadata']['context'][key]=[bad]
            with self.subTest(key=key),self.assertRaises(ValueError):core.context_contract(changed,binding)

    def test_failed_worker_prevents_publisher_and_existing_request_prevents_retry(self):
        folder=entry.PRIVATE/('knn-v28-c1-unit-'+uuid4().hex);folder.mkdir();request={'artificial':True};io.write(folder/'request.json',request)
        with patch.object(entry.old,'run_child',side_effect=ValueError('worker failed')) as child,self.assertRaises(ValueError):
            entry.run_pipeline(folder,request,dict(worker=[],publisher=[]))
        self.assertEqual(child.call_count,1)
        try:
            # The formal acceptance already owns this same OS lock. Isolate the
            # request-refusal unit check; production locking remains unchanged.
            with patch.object(entry,'exclusive',side_effect=lambda:nullcontext()),patch.object(entry,'source_contract') as sources,\
                 patch.object(entry,'run_window') as window,self.assertRaises(FileExistsError):entry.measure()
            sources.assert_not_called();window.assert_not_called()
        finally:
            # Unit-only evidence never claims the direct real-window slot.
            target=folder/'unit';target.mkdir();(folder/'request.json').rename(target/'request.json')

    def test_decision_thresholds_orders_cold_and_primary_are_not_weakened(self):
        def runs():return {k:dict(accounting=dict(costs=dict(entry_seconds=10. if k.endswith('_R') else 9.4,primary_seconds=2.)))
            for k in ['warm_R','warm_C',*[f'pair_{i}_{m}' for i in range(1,7) for m in ('R','C')]]}
        value=runs();self.assertTrue(core.decision(value)['adopted'])
        for change in ('cold','primary','magnitude','orders','wins','missing'):
            value=runs()
            if change=='cold':value['warm_C']['accounting']['costs']['entry_seconds']=100.
            elif change=='primary':
                for k in value:
                    if k.endswith('_C'):value[k]['accounting']['costs']['primary_seconds']=2.2
            elif change=='magnitude':
                for k in value:
                    if k.endswith('_C'):value[k]['accounting']['costs']['entry_seconds']=9.6
            elif change=='orders':
                for i in (2,4,6):value[f'pair_{i}_C']['accounting']['costs']['entry_seconds']=10.1
            elif change=='wins':
                for i in (1,2):value[f'pair_{i}_C']['accounting']['costs']['entry_seconds']=10.1
            else:
                value.pop('warm_R')
                with self.assertRaises(ValueError):core.decision(value)
                continue
            with self.subTest(change=change):self.assertFalse(core.decision(value)['adopted'])


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.folder=build_window()
    def completed(self):
        request=io.read(self.folder/'request.json');return entry.audit_completed(self.folder,request)

    def test_actual_v28_worker_and_publisher_complete_without_padding(self):
        result,completion,exits,pub,load=self.completed()
        self.assertEqual(len(result['runs']),14);self.assertEqual(result['cache']['hits'],6)
        self.assertEqual(result['cache']['cold_builds'],1);self.assertEqual(pub['phases']['checkpoint.open']['calls'],14)
        self.assertEqual(completion['tracked_processes_alive_after_cleanup'],0)
        self.assertNotEqual(exits['worker']['pid'],exits['publisher']['pid'])

    def test_raw_cost_event_load_cache_and_payload_changes_rejected(self):
        for relative in ('pair_1_C/measured.json','pair_1_C/events.json','pair_1_C/telemetry_records.json','cache_receipt.json','audited_result.json'):
            p=self.folder/relative;original=p.read_bytes();p.write_bytes(original+b' ')
            try:
                with self.subTest(path=relative),self.assertRaises(ValueError):self.completed()
            finally:p.write_bytes(original)
        p=next((self.folder/'pair_1_C/verified_subset/payloads').glob('*.jsonl'));original=p.read_bytes();p.write_bytes(original+b'{}\n')
        try:
            with self.assertRaises(ValueError):self.completed()
        finally:p.write_bytes(original)

    def test_post_exit_release_is_immutable_and_outer_failure_withholds_it(self):
        request=io.read(self.folder/'request.json')
        with patch.object(entry,'folder_path',side_effect=lambda x:Path(x)),patch.object(entry,'contract',return_value=request['metadata']),\
             patch.object(entry,'REPORT',self.folder.relative_to(io.ROOT).as_posix()+'/public.json'),\
             patch.object(entry,'RELEASE',self.folder.relative_to(io.ROOT).as_posix()+'/release.json'):
            # Private test outputs stay outside the sealed evidence tree used by the real release.
            with patch.object(entry,'REPORT',self.folder.parent.relative_to(io.ROOT).as_posix()+'/public.json'),\
                 patch.object(entry,'RELEASE',self.folder.parent.relative_to(io.ROOT).as_posix()+'/release.json'):
                first=entry.release(self.folder);self.assertEqual(first,entry.release(self.folder))
                p=self.folder/'supervisor_completion.json';original=p.read_bytes();value=io.read(p);value['tracked_processes_alive_after_cleanup']=1;p.write_bytes(cp.encoded(value))
                try:
                    with self.assertRaises(ValueError):entry.release(self.folder)
                finally:p.write_bytes(original)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1] in ('--worker','--publisher','--pipeline'):child(sys.argv[2],sys.argv[1][2:])
    else:unittest.main()
