"""Real S1 entry orchestration over separately bound artificial48 sources only."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import run_retailrocket_session_knn_compare_v31 as entry
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as core
from scripts.retailrocket_session_knn_snapshot_v30 import SCHEME
from scripts import accept_retailrocket_session_knn_snapshot_v30 as s1
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import run_retailrocket_session_knn_v2 as io
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.retailrocket_session_knn_reuse_v27 import ReuseStore
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from tests import test_retailrocket_session_knn_reuse_acceptance_v27 as fixture
from tests import test_retailrocket_session_knn_validation as validation
from tests import test_retailrocket_session_knn_pair_v4 as four

MODULE='tests.test_retailrocket_session_knn_compare_v31'


def artificial_inputs(boundary=False):
    data=list(fixture.artificial48_inputs())
    # Future-only artificial items leave all48 scientific predictions unchanged.
    # Real initialization work, not sleeps, makes both arms long enough for telemetry.
    data[3]=list(data[3])+[(str(1000000+i),1000000) for i in range(100000)]
    return tuple(data)


def scope(folder):
    folder=Path(folder).resolve()
    if folder.parent.parent!=entry.PRIVATE.resolve() or not folder.parent.name.startswith('knn-v31-s1-tests-'):
        raise ValueError('Artificial bridge only')
    request=io.read(folder/'request.json')
    if request['metadata'].get('synthetic_acceptance_only') is not True:raise ValueError('Artificial marker required')
    if request['metadata'].get('fingerprint_scheme')!=SCHEME:raise ValueError('Exact S1 fingerprint scheme required')
    return folder,request


def child(folder,kind):
    folder,request=scope(folder)
    if kind=='pipeline':
        return entry.run_pipeline(folder,request,{k:[sys.executable,'-B','-m',MODULE,'--'+k,str(folder)] for k in ('worker','publisher')})
    if kind=='publisher':return entry.run_publisher(folder,request)
    return entry.run_worker(folder,request,lambda:fixture.data_for(request)[1])


def build_window():
    bundle=entry.PRIVATE/('knn-v31-s1-tests-'+uuid4().hex);bundle.mkdir()
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
    method_records={p:io.describe(io.ROOT/p) for p in (*s1.METHODS,*entry.METHODS)}
    methods=[method_records[p] for p in sorted(method_records)]
    io.write(bundle/'data.json',dict(contract=dict(binding=binding),model=model,database=rel(database),ordinals=ordinals,probes=probes))
    cohort=dict(selected_root=rel(root),model_root=rel(primary),old_run=rel(reference.folder/'run.json'),
        probes=rel(bundle/'probes.json'),reference=rel(bundle/'reference.json'))
    schedule=[dict(label='warm_'+m,mode=m) for m in ('R','C')]+[dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')]
    sources=[io.describe(p) for p in sorted(bundle.rglob('*')) if p.is_file()]+methods
    meta=dict(cohort=cohort,schedule=schedule,context=dict(dependencies=dependencies,methods=methods),environment=io.environment(),
        gates=io.check_gates(),synthetic_acceptance_only=True,synthetic_data=io.describe(bundle/'data.json'),
        specification={'artificial':True},acceptance={'artificial':True},fingerprint_scheme=SCHEME,
        core_specification={'artificial':True},core_acceptance={'artificial':True})
    folder=bundle/'window';completion=run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],sources,
        'joint_tail',metadata=meta,budget_seconds=1800,limits=LIMITS)
    if completion['exit_code']!=0:
        raise AssertionError('\n'.join(p.read_text(encoding='utf-8',errors='replace')[-8000:] for p in folder.glob('*.log')))
    return folder


class ContractTests(unittest.TestCase):
    def test_real_specification_and_exact_original_scope(self):
        spec=entry.specification();self.assertEqual(len(spec['inherited_sources']),1261);self.assertEqual(len(spec['original_binding_sources']),15)
        self.assertEqual(spec['activation']['authorized_real_runs'],14);self.assertEqual(spec['activation']['queries_per_run'],48)
        for key,value in (('budget_seconds',1801),('status','synthetic'),('schedule',[])):
            changed=deepcopy(spec);changed[key]=value
            original=entry.read
            with patch.object(entry,'read',side_effect=lambda p:changed if Path(p)==io.ROOT/entry.SPEC else original(p)),self.assertRaises(ValueError):entry.specification()

    def test_request_synthetic_marker_roster_context_and_limits_reject(self):
        request=dict(created_utc='2026-11-09T00:00:00+00:00',deadline_utc='2026-11-09T00:30:00+00:00',budget_seconds=1800,
            limits=LIMITS,operation='joint_tail',full_readback_enabled=False,reserved_test='locked',T_plan=None,sources=[{'path':'artificial'}],metadata={'fixed':'real','fingerprint_scheme':SCHEME})
        with patch.object(entry,'source_contract',return_value=(request['sources'],request['metadata'])):
            entry.contract(request)
            for update in (dict(metadata={'synthetic_acceptance_only':True}),dict(sources=[]),dict(metadata={'context':{}}),dict(budget_seconds=1801)):
                with self.subTest(update=update),self.assertRaises(ValueError):entry.contract(dict(request,**update))

    def test_exact_context_dependencies_and_methods_are_bound(self):
        record=dict(path='x',bytes=1,sha256='0'*64);binding=dict(sources=[record]);deps={n:record for n in ('counts','catalog','config','model')}
        request=dict(sources=[record],metadata=dict(context=dict(dependencies=deps,methods=[record]),environment={},fingerprint_scheme=SCHEME))
        core.context_contract(request,binding)
        for key in ('dependencies','methods'):
            changed=deepcopy(request);bad=dict(record,path='unbound')
            if key=='dependencies':changed['metadata']['context'][key]['model']=bad
            else:changed['metadata']['context'][key]=[bad]
            with self.subTest(key=key),self.assertRaises(ValueError):core.context_contract(changed,binding)

    def test_failed_worker_prevents_publisher_and_existing_request_prevents_retry(self):
        folder=entry.PRIVATE/('knn-v31-s1-unit-'+uuid4().hex);folder.mkdir();request={'artificial':True};io.write(folder/'request.json',request)
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

    def test_request_and_context_reject_missing_or_mixed_fingerprint_scheme(self):
        record=dict(path='x',bytes=1,sha256='0'*64);binding=dict(sources=[record]);deps={n:record for n in ('counts','catalog','config','model')}
        request=dict(created_utc='2026-11-09T00:00:00+00:00',deadline_utc='2026-11-09T00:30:00+00:00',budget_seconds=1800,
            limits=LIMITS,operation='joint_tail',full_readback_enabled=False,reserved_test='locked',T_plan=None,sources=[record],
            metadata=dict(context=dict(dependencies=deps,methods=[record]),environment={},fingerprint_scheme=SCHEME))
        core.context_contract(request,binding)
        with patch.object(entry,'source_contract',return_value=(request['sources'],request['metadata'])):
            entry.contract(request)
            for scheme in (None,'K1-C1-SNAPSHOT-v0',True):
                changed=deepcopy(request)
                if scheme is None:changed['metadata'].pop('fingerprint_scheme')
                else:changed['metadata']['fingerprint_scheme']=scheme
                with self.subTest(scheme=scheme),self.assertRaises(ValueError):core.context_contract(changed,binding)
                # Give the entry an internally matching bad roster: it must
                # still enforce the version rather than reject only inequality.
                with self.subTest(entry_scheme=scheme),patch.object(entry,'source_contract',return_value=(changed['sources'],changed['metadata'])),self.assertRaises(ValueError):
                    entry.contract(changed)

    def test_new_namespace_rejects_old_real_entries_and_nested_artificial_window(self):
        valid=entry.PRIVATE/('knn-v31-s1-'+uuid4().hex)
        self.assertEqual(entry.folder_path(valid),valid.resolve())
        for folder in (entry.PRIVATE/'knn-v28-c1-old',entry.PRIVATE/'knn-v30-s1-old',valid/'window'):
            with self.subTest(folder=folder),self.assertRaises(ValueError):entry.folder_path(folder)

    def test_real_source_contract_appends_methods_without_replacing_original17(self):
        spec=entry.specification();original=spec['original_context_methods']
        self.assertEqual(len(original),17)
        parent=io.read(io.ROOT/spec['parent_acceptance']['path'])
        with tempfile.TemporaryDirectory(prefix='knn-v31-s1-source-unit-',dir=entry.PRIVATE) as temp:
            folder=Path(temp);acceptance=folder/'acceptance.json';log=folder/'tests.log'
            io.write(acceptance,{'artificial':True});log.write_text('method-union contract unit only',encoding='utf-8')
            receipt=dict(methods=[io.describe(io.ROOT/p) for p in entry.METHODS],log=io.describe(log),integration=dict(evidence=[]))
            with patch.object(entry,'specification',return_value=spec),patch.object(entry,'accepted',return_value=receipt),\
                 patch.object(entry,'ACCEPT',acceptance.relative_to(io.ROOT).as_posix()):
                sources,meta=entry.source_contract()
        methods=meta['context']['methods'];actual={x['path']:x for x in methods}
        expected={x['path']:x for x in [*original,*parent['methods'],*receipt['methods']]}
        self.assertEqual(actual,expected);self.assertEqual(len(methods),26)
        for record in original:self.assertEqual(actual[record['path']],record)
        bound={x['path']:x for x in sources}
        for record in [*spec['inherited_sources'],*methods]:self.assertEqual(bound[record['path']],record)
        self.assertEqual(meta['fingerprint_scheme'],SCHEME)
        self.assertEqual(meta['core_specification'],spec['parent_specification'])
        self.assertEqual(meta['core_acceptance'],spec['parent_acceptance'])


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.folder=build_window()
    def completed(self):
        request=io.read(self.folder/'request.json');return entry.audit_completed(self.folder,request)

    def test_actual_v31_worker_and_publisher_complete_without_padding(self):
        result,completion,exits,pub,load=self.completed()
        self.assertEqual(len(result['runs']),14);self.assertEqual(result['cache']['hits'],6)
        self.assertEqual(result['cache']['cold_builds'],1);self.assertEqual(pub['phases']['checkpoint.open']['calls'],14)
        self.assertEqual(completion['tracked_processes_alive_after_cleanup'],0)
        self.assertNotEqual(exits['worker']['pid'],exits['publisher']['pid'])
        self.assertLessEqual(exits['worker']['ended_utc'],exits['publisher']['started_utc'])
        self.assertEqual(result['status'],'v31_C1_S1_independent_real_audit_complete')
        self.assertEqual(result['cache']['fingerprint_scheme'],SCHEME)
        self.assertEqual({x['fingerprint_scheme'] for x in result['cache']['call_observations']},{SCHEME})
        fingerprints=0
        for label,row in result['runs'].items():
            phases=row['diagnostic']['phases']
            if row['mode']=='C':fingerprints+=phases['snapshot.fingerprint']['calls']
            else:self.assertFalse(any(name.startswith(('cache.','snapshot.')) for name in phases))
        self.assertEqual(fingerprints,15);self.assertEqual(pub['phases']['snapshot.fingerprint']['calls'],1)
        request=io.read(self.folder/'request.json');frames=list(_physical_frames((io.ROOT/request['metadata']['cohort']['old_run']).parent))
        self.assertEqual(len(frames),48)
        for label in result['runs']:self.assertEqual(list(_physical_frames(self.folder/label/'verified_subset')),frames)

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
