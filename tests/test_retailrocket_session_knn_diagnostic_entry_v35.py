"""Top-level cold/codec diagnostics over artificial inputs, without SQL queries."""
from contextlib import ExitStack,nullcontext
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import run_retailrocket_session_knn_diagnostics_v35 as entry
from scripts import retailrocket_session_knn_entry_v34 as common
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as s1
from scripts import retailrocket_session_knn_diagnostics_v35 as diagnostic
from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import run_retailrocket_session_knn_v2 as io
from scripts import run_retailrocket_session_knn_sources_v25 as old
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE

MODULE='tests.test_retailrocket_session_knn_diagnostic_entry_v35'
METHODS=('scripts/run_retailrocket_session_knn_diagnostics_v35.py',
    'scripts/retailrocket_session_knn_diagnostics_v35.py',
    'tests/test_retailrocket_session_knn_diagnostic_entry_v35.py')


def cold_schedule():
    return [dict(label='cold_'+('warm' if i==0 else str(i)),mode='cold',warmup=i==0) for i in range(4)]


def codec_schedule():
    return [dict(label='codec_'+('warm' if i==0 else str(i))+'_'+mode,mode=mode,cycle=i,warmup=i==0)
        for i,order in enumerate(('BD','BD','DB','BD')) for mode in order]


def scope(folder):
    folder=Path(folder).resolve()
    if folder.parent.parent!=PRIVATE.resolve() or not folder.parent.name.startswith('knn-v35-diag-synthetic-') or folder.name!='window':
        raise ValueError('Only the artificial cold/codec entry bridge is allowed')
    request=io.read(folder/'request.json')
    if request['metadata'].get('synthetic_acceptance_only') is not True:raise ValueError('Artificial-only marker required')
    return folder,request


def fixture_data(request):
    meta=request['metadata'];source=io.ROOT/meta['cohort']['selected_root']
    binding=io.read(source/'binding.json');config=io.read(source/'configuration.json')
    model=io.read(source/'reconstruction.json')['receipt']
    return dict(paths=dict(P0=source/'P0',dataset=source/'dataset'),config=config,model=model,binding=binding,
        contract=s1.context_contract(request,binding))


def synthetic_contract(candidate,expected):
    print('synthetic parent contract stdout, retained quietly')
    print('synthetic parent contract stderr, retained quietly',file=sys.stderr)
    old._check_window(candidate);s1.require_scheme(candidate)
    if candidate!=expected:raise ValueError('Artificial request identity changed')
    common.require_direct_sources(candidate['metadata']['context']['methods'],candidate['sources'])
    io.verify_bindings(candidate['sources'])
    return candidate['metadata']


def bridge(folder,role):
    folder,request=scope(folder)
    with ExitStack() as stack:
        stack.enter_context(patch.object(entry,'MODULE',MODULE))
        stack.enter_context(patch.object(entry,'folder_path',side_effect=lambda value:scope(value)[0]))
        stack.enter_context(patch.object(entry,'contract',side_effect=lambda value:synthetic_contract(value,request)))
        stack.enter_context(patch.object(entry,'inputs',side_effect=fixture_data))
        stack.enter_context(patch.object(sqlite3,'connect',side_effect=AssertionError('Diagnostic entry must not open a SQL database')))
        return getattr(entry,role)(folder)


def build_window():
    bundle=PRIVATE/('knn-v35-diag-synthetic-'+uuid4().hex);source=bundle/'inputs'
    (source/'P0').mkdir(parents=True);(source/'dataset').mkdir()
    (source/'P0/item_counts.csv').write_text('itemid,count\n1,3\n2,2\n',encoding='utf-8')
    with (source/'dataset/catalog.csv').open('w',encoding='utf-8',newline='') as out:
        out.write('itemid,first_view_ms\n1,1\n2,2\n3,11\n')
        for i in range(100000):out.write(f'{1000000+i},1000000\n')
    config=dict(schemas={'catalog.csv':['itemid','first_view_ms']},train_window_ms=[0,10])
    model=dict(support={'1':2,'2':1},fit_audit=dict(fit_id='artificial-diagnostic-only'))
    io.write(source/'configuration.json',config);io.write(source/'reconstruction.json',dict(receipt=model))
    rel=lambda path:path.relative_to(io.ROOT).as_posix()
    records=cp.bind_sources(io.ROOT,[rel(source/name) for name in ('P0/item_counts.csv','dataset/catalog.csv','configuration.json','reconstruction.json')])
    binding=dict(sources=records);io.write(source/'binding.json',binding);io.write(source/'original_run.json',dict(binding=binding))
    descriptors={x['path']:x for x in records}
    dependencies={key:descriptors[rel(source/name)] for key,name in (
        ('counts','P0/item_counts.csv'),('catalog','dataset/catalog.csv'),('config','configuration.json'),('model','reconstruction.json'))}
    direct=common.source_inventory(METHODS,dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    sources=common.merge_methods([*records,io.describe(source/'binding.json'),io.describe(source/'original_run.json')],direct)
    meta=dict(cohort=dict(selected_root=rel(source),old_run=rel(source/'original_run.json')),
        context=dict(dependencies=dependencies,methods=direct),environment=io.environment(),gates=io.check_gates(),
        fingerprint_scheme=codec.SCHEME,cold_schedule=cold_schedule(),codec_schedule=codec_schedule(),
        synthetic_acceptance_only=True,specification=dict(artificial=True),acceptance=dict(artificial=True),parent_inputs=[])
    folder=bundle/'window'
    completion=run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],sources,'joint_tail',
        metadata=meta,budget_seconds=1800,limits=LIMITS)
    if completion['exit_code']!=0:
        raise AssertionError('\n'.join(p.read_text(encoding='utf-8',errors='replace')[-10000:] for p in folder.glob('*.log')))
    return folder


class ContractTests(unittest.TestCase):
    def test_real_plan_keeps_original_sources_methods_binding_and_direct_dependencies(self):
        plan=entry.make_plan()
        self.assertEqual(len(plan['original_sources']),1937);self.assertEqual(len(plan['original_methods']),26)
        self.assertEqual(len(plan['binding_sources']),15)
        sources={x['path']:x for x in plan['sources']};methods={x['path']:x for x in plan['methods']}
        for record in plan['original_sources']:self.assertEqual(sources[record['path']],record)
        for record in plan['original_methods']:self.assertEqual(methods[record['path']],record)
        direct={x['path']:x for x in plan['direct_sources']}
        for name in (common.PRIORITY_SOURCE,'scripts/retailrocket_session_knn_checkpoint_v2.py'):
            self.assertEqual(sources[name],direct[name]);self.assertEqual(methods[name],direct[name])
        common.require_direct_sources(plan['methods'],plan['sources'])

    def test_missing_direct_priority_or_transitive_dependency_cannot_hide_behind_ancestor(self):
        plan=entry.make_plan()
        for missing in (common.PRIORITY_SOURCE,'scripts/retailrocket_session_knn_checkpoint_v2.py'):
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                common.require_direct_sources(plan['methods'],[x for x in plan['sources'] if x['path']!=missing])

    def test_request_roster_schedules_scope_and_scheme_are_exact(self):
        priority=io.describe(io.ROOT/common.PRIORITY_SOURCE)
        meta=dict(fingerprint_scheme=codec.SCHEME,cold_schedule=cold_schedule(),codec_schedule=codec_schedule(),fixed='unit',
            context=dict(methods=[priority]))
        request=dict(created_utc='2026-11-10T00:00:00+00:00',deadline_utc='2026-11-10T00:30:00+00:00',budget_seconds=1800,
            limits=LIMITS,operation='joint_tail',full_readback_enabled=False,reserved_test='locked',T_plan=None,
            sources=[priority],metadata=meta)
        with patch.object(entry,'source_contract',return_value=(request['sources'],meta)):
            self.assertEqual(entry.contract(request),meta)
            for update in (dict(sources=[]),dict(metadata=dict(meta,cold_schedule=[])),dict(metadata=dict(meta,codec_schedule=[])),
                           dict(metadata=dict(meta,synthetic_acceptance_only=True)),dict(budget_seconds=1801),dict(reserved_test='unlocked')):
                with self.subTest(update=update),self.assertRaises(ValueError):entry.contract(dict(request,**update))
        for scheme in (None,True,'old-S1-scheme'):
            changed=deepcopy(request)
            if scheme is None:changed['metadata'].pop('fingerprint_scheme')
            else:changed['metadata']['fingerprint_scheme']=scheme
            with self.subTest(scheme=scheme),patch.object(entry,'source_contract',return_value=(changed['sources'],changed['metadata'])),self.assertRaises(ValueError):
                entry.contract(changed)

    def test_existing_request_refuses_retry_before_sources_or_new_supervisor(self):
        folder=PRIVATE/('knn-v35-diagnostics-unit-'+uuid4().hex);folder.mkdir();io.write(folder/'request.json',dict(artificial=True))
        try:
            with patch.object(entry,'exclusive',side_effect=lambda:nullcontext()),patch.object(entry,'source_contract') as sources,\
                 patch.object(entry,'run_window') as window,self.assertRaises(FileExistsError):entry.measure()
            sources.assert_not_called();window.assert_not_called()
        finally:
            target=folder/'unit';target.mkdir();(folder/'request.json').rename(target/'request.json')

    def test_original_request_roster_cannot_be_replaced_by_same_size_or_smaller_context(self):
        plan=entry.make_plan();original=io.read(io.ROOT/plan['original_request']['path'])
        for key in ('sources','methods','same-size-source-change'):
            changed=deepcopy(original)
            if key=='sources':changed['sources']=changed['sources'][:-1]
            elif key=='methods':changed['metadata']['context']['methods']=changed['metadata']['context']['methods'][:-1]
            else:changed['sources'][0]['sha256']='0'*64
            with self.subTest(key=key),patch.object(entry.parent,'audit',return_value=None),self.assertRaises(ValueError):
                entry.make_plan(original_request=changed)

    def test_top_level_pipeline_failure_does_not_publish_or_claim_completion(self):
        for failed in ('worker','publisher'):
            with self.subTest(failed=failed),tempfile.TemporaryDirectory(dir=PRIVATE,prefix='knn-v35-pipeline-unit-') as temp:
                folder=Path(temp);io.write(folder/'request.json',dict(metadata=dict(fingerprint_scheme=codec.SCHEME)))
                effects=[ValueError('artificial worker failure')] if failed=='worker' else [None,ValueError('artificial publisher failure')]
                with patch.object(entry,'folder_path',side_effect=lambda value:Path(value)),patch.object(entry,'contract',return_value={}),\
                     patch.object(entry.old,'run_child',side_effect=effects) as run,self.assertRaises(ValueError):entry.pipeline(folder)
                self.assertEqual([call.args[2] for call in run.call_args_list],['worker'] if failed=='worker' else ['worker','publisher'])
                self.assertFalse((folder/'pipeline_done.json').exists())
                self.assertEqual(io.read(folder/'pipeline_failure.json'),dict(error_type='ValueError'))

    def test_watch_report_rejects_field_reallocation_extra_fields_and_invalid_times(self):
        first={str(i):i for i in range(2050)};counts={'0':1,'1':1,'2':1}
        snapshot=codec.FrozenCatalog(MappingProxyType(first),MappingProxyType(counts),tuple(first.values()),tuple(first))
        records=[];diagnostic.fingerprint(snapshot,watch_observations=records)
        report=records[0];dimensions=entry._dimensions(snapshot);entry._watch_report(report,dimensions)
        bad=[]
        changed=deepcopy(report);changed['fields']['first']['watch_calls']-=1;changed['fields']['fallback']['watch_calls']+=1;bad.append(changed)
        changed=deepcopy(report);changed['fields']['first']['sampled_calls']-=1;changed['fields']['first_times']['sampled_calls']+=1;bad.append(changed)
        changed=deepcopy(report);changed['fields']['unexpected']=dict(changed['fields']['outside_validation']);bad.append(changed)
        for value in (float('nan'),float('inf'),-1,True):
            changed=deepcopy(report);changed['sample_seconds']=value;bad.append(changed)
            changed=deepcopy(report);changed['fields']['first']['sample_seconds']=value;bad.append(changed)
        for index,changed in enumerate(bad):
            with self.subTest(mutation=index),self.assertRaises(ValueError):entry._watch_report(changed,dimensions)


class IntegratedTests(unittest.TestCase):
    publication_evidence=[]

    @classmethod
    def setUpClass(cls):
        cls.folder=build_window();request=io.read(cls.folder/'request.json')
        with patch.object(entry,'inputs',side_effect=fixture_data):
            *_,cls.seal=entry.audit_completed(cls.folder,request)

    def completed(self):
        request=io.read(self.folder/'request.json')
        with patch.object(entry,'inputs',side_effect=fixture_data):result=entry.audit_completed(self.folder,request)
        common.closed_log_manifest(self.folder,request,result[1],result[2],expected=self.seal)
        return result

    def test_all_four_fresh_cold_stores_are_empty_with_full_lock_checks(self):
        result,completion,exits,pub,load,seal=self.completed();request=io.read(self.folder/'request.json');data=fixture_data(request)
        self.assertEqual(list(result['cold']),sorted(x['label'] for x in cold_schedule()))
        self.assertEqual(result['scope']['real_query_runs'],0);self.assertEqual(result['scope']['new_query_verifications'],0)
        for label,row in result['cold'].items():
            record=row['result'];self.assertEqual(record['empty_records'],0)
            self.assertEqual(record['full_checks'],[dict(force=False,external=False),dict(force=True,external=False)])
            self.assertTrue(record['cache_use']['cold']);self.assertFalse(record['cache_use']['hit'])
            self.assertEqual(record['diagnostic_fingerprints'],3);self.assertEqual(record['reference_fingerprints'],1)
            events=io.read(self.folder/label/'events.json')
            self.assertEqual([e['metadata']['descriptor'] for e in events if e['phase']=='binding.descriptor'],data['binding']['sources']*2)
            self.assertEqual(row['diagnostic']['phases']['snapshot.fingerprint']['calls'],4)
            for phase in diagnostic.COLD_PHASES:self.assertGreater(row['diagnostic']['phases'][phase]['calls'],0)
            store=self.folder/label/'empty_store';self.assertFalse(list((store/'chunks').iterdir()))
            self.assertEqual(io.read(store/'run.json')['expected_queries'],0)
            self.assertFalse(any(e['phase'].startswith(('query.','sql.')) for e in events))
        self.assertEqual(completion['tracked_processes_alive_after_cleanup'],0)

    def test_codec_pairs_preserve_all_bytes_watch_calls_orders_and_warmups(self):
        result,*_=self.completed();request=io.read(self.folder/'request.json')
        self.assertEqual(request['metadata']['codec_schedule'],entry.CODEC_SCHEDULE)
        self.assertEqual(len(result['codec']),8);self.assertEqual(len(result['summary']['codec_formal_pairs']),3)
        dimensions=result['reference']['dimensions'];expected_calls=sum(dimensions.values())+4
        for label,row in result['codec'].items():
            value=row['result'];self.assertEqual(value['digest'],result['reference']['digest']);self.assertEqual(value['watch_calls'],expected_calls)
            self.assertEqual(row['diagnostic']['phases']['snapshot.fingerprint']['calls'],1)
            if value['item']['mode']=='D':
                self.assertEqual(len(value['watch_observations']),1);watch=value['watch_observations'][0]
                self.assertEqual(watch['watch_calls'],expected_calls);self.assertEqual(watch['sampled_calls'],expected_calls//1024)
                self.assertLess(watch['sampled_calls'],watch['watch_calls'])
                for phase in diagnostic.VALIDATION_PHASES:self.assertEqual(row['diagnostic']['phases'][phase]['calls'],1)
            else:self.assertEqual(value['watch_observations'],[])
        self.assertEqual([x['order'] for x in result['summary']['codec_formal_pairs']],['BD','DB','BD'])
        self.assertEqual(result['setup']['timer_overhead']['samples'],256);self.assertTrue(result['setup']['setup_is_charged'])
        self.assertNotIn('adopted',result);self.assertNotIn('corrected_seconds',result['summary'])

    def test_independent_publisher_rebuilds_and_top_level_contract_diagnostics_stay_quiet(self):
        result,completion,exits,pub,load,seal=self.completed();request=io.read(self.folder/'request.json')
        self.assertNotEqual(exits['worker']['pid'],exits['publisher']['pid'])
        self.assertLessEqual(exits['worker']['ended_utc'],exits['publisher']['started_utc'])
        self.assertEqual(pub['phases']['publisher.independent_context']['calls'],1)
        self.assertEqual(pub['phases']['publisher.expected_fingerprint']['calls'],1)
        self.assertEqual(pub['phases']['checkpoint.open']['calls'],4)
        events=io.read(self.folder/'publisher/events.json')
        self.assertEqual([e['metadata']['descriptor'] for e in events if e['phase']=='closure.descriptor'],request['sources']*2)
        initial=io.read(self.folder/'worker_initial_hash/events.json')
        input_events,input_summary=old.check_observation(self.folder/'input_setup')
        self.assertEqual(input_summary['phases']['replay.input_load']['calls'],1)
        self.assertLessEqual(max(e['end_ns'] for e in initial),min(e['start_ns'] for e in input_events))
        cold_events=io.read(self.folder/'cold_warm/events.json')
        self.assertLessEqual(max(e['end_ns'] for e in input_events),min(e['start_ns'] for e in cold_events))
        self.assertEqual(result['summary']['one_time_input_setup_seconds'],input_summary['root_wall_ns']/1e9)
        for role in ('pipeline','worker','publisher'):
            captured=io.read(self.folder/'contract_diagnostics'/f'{role}.json')
            self.assertTrue(captured['contract_complete']);self.assertIn('contract stdout',captured['captured_output'])
            self.assertIn('contract stderr',captured['captured_output'])
        for name in common.ACTIVE_LOG_NAMES:
            self.assertNotIn('synthetic parent contract',(self.folder/name).read_text(encoding='utf-8'))
            self.assertNotIn((self.folder/name).relative_to(io.ROOT).as_posix(),{x['path'] for x in result['evidence']})
        self.assertEqual(seal,self.seal)

    def test_raw_results_event_trees_load_and_final_log_changes_are_rejected(self):
        for relative in ('cold_1/result.json','cold_1/events.json','cold_1/telemetry_records.json','codec_2_D/result.json',
                         'validation_setup/result.json','audited_result.json','stdout_stderr.log','publisher.log'):
            path=self.folder/relative;original=path.read_bytes();path.write_bytes(original+b' ')
            try:
                with self.subTest(path=relative),self.assertRaises(ValueError):self.completed()
            finally:path.write_bytes(original)
        extra=self.folder/'not-in-final-seal.txt';extra.write_bytes(b'unexpected late file')
        try:
            with self.assertRaises(ValueError):self.completed()
        finally:extra.unlink()

    def test_release_is_immutable_and_does_not_change_closed_window(self):
        request=io.read(self.folder/'request.json');bundle=self.folder.parent
        report_path=(bundle/'private-public.json').relative_to(io.ROOT).as_posix()
        release_path=(bundle/'private-release.json').relative_to(io.ROOT).as_posix()
        with patch.object(entry,'folder_path',side_effect=lambda value:scope(value)[0]),\
             patch.object(entry,'contract',side_effect=lambda value:synthetic_contract(value,request)),\
             patch.object(entry,'inputs',side_effect=fixture_data),patch.object(entry,'REPORT',report_path),\
             patch.object(entry,'RELEASE',release_path),patch.object(entry,'PRIVATE',bundle/'publication'):
            first=entry.release(self.folder);self.assertEqual(first,entry.release(self.folder))
            self.assertEqual(first['final_log_seal'],self.seal);self.assertEqual(first['scope']['real_query_runs'],0)
            self.assertNotIn('publication_recovery',first)
            receipt=io.read(io.ROOT/release_path);saved=(io.ROOT/release_path).read_bytes()
            (io.ROOT/release_path).write_bytes(cp.encoded(dict(receipt,status='another-release')))
            try:
                with self.assertRaises(ValueError):entry.release(self.folder)
            finally:(io.ROOT/release_path).write_bytes(saved)
        type(self).publication_evidence=[io.describe(io.ROOT/report_path),io.describe(io.ROOT/release_path),first['release_contract_diagnostics']]


def integration_evidence():
    fixture=IntegratedTests('test_all_four_fresh_cold_stores_are_empty_with_full_lock_checks')
    result,completion,exits,pub,load,seal=fixture.completed()
    return dict(namespace=fixture.folder.relative_to(io.ROOT).as_posix(),synthetic_only=True,top_level_contract_exercised=True,
        cold_cycles=4,cold_fresh_cycles=4,cold_recorded_cycles=3,codec_calls=8,codec_recorded_pairs=3,real_query_runs=0,
        empty_checkpoint_records=0,publisher_independent_rebuilds=1,final_seal=seal,
        evidence=common.merge_methods(seal['window_evidence'],IntegratedTests.publication_evidence))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1] in ('--pipeline','--worker','--publisher'):bridge(sys.argv[2],sys.argv[1][2:])
    else:unittest.main()
