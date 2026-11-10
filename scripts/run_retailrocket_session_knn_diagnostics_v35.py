"""Sealed, supervised, read-only cold and snapshot diagnostics; no query entry."""
import argparse
from collections import Counter
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timezone
import hashlib
import math
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import retailrocket_session_knn_entry_v34 as common
from scripts import accept_retailrocket_session_knn_entry_v34 as parent
from scripts import run_retailrocket_session_knn_compare_v31 as original
from scripts import run_retailrocket_session_knn_compare_v28 as lifecycle
from scripts import run_retailrocket_session_knn_sources_v25 as old
from scripts import retailrocket_session_knn_diagnostics_v35 as diag
from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as s1
from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.retailrocket_session_knn_reinforcement_v18 import TelemetrySampler
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_cost_window_v5 import run_window,LIMITS
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,write,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE,public_json

MODULE='scripts.run_retailrocket_session_knn_diagnostics_v35'
BASE='reports/stage12/retailrocket_session_knn_v35_diagnostics_'
SPEC=BASE+'specification_20261110.json';SEAL=BASE+'seal_20261110.json'
ACCEPT=BASE+'acceptance_20261110.json';REPORT=BASE+'cost_20261110.json';RELEASE=BASE+'release_20261110.json'
EXPLICIT_LOADER_SEEDS=('scripts/analyze_retailrocket_session_knn_compare_v33.py','tests/test_retailrocket_session_knn_compare_v33.py')
METHODS=('scripts/run_retailrocket_session_knn_diagnostics_v35.py','scripts/retailrocket_session_knn_diagnostics_v35.py',
    'tests/test_retailrocket_session_knn_diagnostics_v35.py','tests/test_retailrocket_session_knn_diagnostic_entry_v35.py',
    *parent.METHODS,*EXPLICIT_LOADER_SEEDS)
SUITES=('tests.test_retailrocket_session_knn_diagnostics_v35','tests.test_retailrocket_session_knn_diagnostic_entry_v35',
    'tests.test_retailrocket_session_knn_entry_v34')
COLD_SCHEDULE=[dict(label='cold_warm' if i==0 else f'cold_{i}',mode='cold',warmup=i==0) for i in range(4)]
CODEC_SCHEDULE=[dict(label=('codec_warm' if i==0 else f'codec_{i}')+'_'+mode,mode=mode,cycle=i,warmup=i==0)
    for i,order in enumerate(('BD','BD','DB','BD')) for mode in order]
SCOPE=dict(real_query_runs=0,new_query_verifications=0,new_real_fit_validation_bootstrap=0,
    cold_fresh_cycles=4,cold_recorded_cycles=3,cold_diagnostic_fingerprints=12,cold_reference_fingerprints=4,
    codec_calls=8,codec_recorded_pairs=3,full_validation_complete=False,reserved_test='locked')
DONE=dict(completed=True,cold_cycles=4,codec_calls=8,queries=0)
exclusive=lifecycle.exclusive


def make_plan(original_request=None):
    p=read(ROOT/parent.REPORT)
    common.quiet_contract(parent.audit)
    anchor=p['source_audit']['original_request'];verify_bindings([anchor])
    base=read(ROOT/anchor['path']) if original_request is None else original_request
    if base!=read(ROOT/anchor['path']) or len(base['sources'])!=1937 or len(base['metadata']['context']['methods'])!=26:
        raise ValueError('Preserve the exact original1937 sources and26 methods')
    release=read(ROOT/original.RELEASE)
    if release['report']!=describe(ROOT/original.REPORT):raise ValueError('Original V31 report seal changed')
    verify_bindings([release['report']])
    binding=read(ROOT/base['metadata']['cohort']['old_run'])['binding']
    if len(binding['sources'])!=15:raise ValueError('Original15 binding required')
    dependencies=base['metadata']['context']['dependencies']
    if set(dependencies)!={'counts','catalog','config','model'}:raise ValueError('Four original context dependencies required')
    legacy_py_seeds=sorted(x['path'] for x in base['sources']
        if x['path'].startswith(('scripts/','tests/')) and x['path'].endswith('.py'))
    direct=common.source_inventory((*METHODS,*legacy_py_seeds),dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)
    parents=[describe(ROOT/parent.REPORT),describe(ROOT/original.REPORT),describe(ROOT/original.RELEASE),anchor]
    sources=common.merge_methods(base['sources'],common.merge_methods(direct,parents))
    methods=common.merge_methods(base['metadata']['context']['methods'],direct)
    common.require_direct_sources(methods,sources)
    index={x['path']:x for x in sources}
    if any(index.get(x['path'])!=x for x in [*base['sources'],*binding['sources'],*dependencies.values()]):
        raise ValueError('Original source/binding/dependency descriptor changed')
    return dict(original_request=anchor,original_sources=base['sources'],original_methods=base['metadata']['context']['methods'],
        direct_sources=direct,sources=sources,methods=methods,cohort=base['metadata']['cohort'],
        context_dependencies=dependencies,binding_sources=binding['sources'],parent_inputs=parents,
        original_sources_count=1937,original_methods_count=26,original_binding_count=15,
        dynamic_target_seeds=list(common.DYNAMIC_TARGET_SEEDS),legacy_source_seeds=legacy_py_seeds,
        explicit_loader_seeds=list(EXPLICIT_LOADER_SEEDS),priority_direct=True,append_only_source_plan=True)


def _spec_value():
    return dict(status='v35_readonly_cold_and_validation_diagnostics_specification_frozen',plan=make_plan(),
        cold_schedule=COLD_SCHEDULE,codec_schedule=CODEC_SCHEDULE,scope=SCOPE,budget_seconds=1800,limits=LIMITS,
        fingerprint_scheme=codec.SCHEME,watch_sample_every=1024,environment=environment(),gates=check_gates(),T_plan=None,
        historical_context=dict(source=describe(ROOT/original.REPORT),cold_build_seconds=6.111406,
            original_load_context_seconds=2.844051,original_prepare_catalog_seconds=.828289,
            expected_fingerprint_seconds=1.219879,unattributed_cold_exclusive_seconds=1.219187,
            interpretation='Saved V31 background only, a different observation scope. These values are not allocated to new spans or treated as a new speed comparison.'),
        interpretation='Independent read-only diagnostic replay, not a new original48 experiment or optimization candidate. All original binding/lock checks remain. Watch samples are not total watch cost; no subtraction or extrapolation. No adoption, SQL, fit, token/GPU speed or reserved-test evaluation.')


def specification():
    value=read(ROOT/SPEC);seal=read(ROOT/SEAL);verify_bindings([seal['specification']])
    if seal!=dict(status='v35_diagnostics_specification_sealed',specification=describe(ROOT/SPEC)):
        raise ValueError('Specification seal changed')
    if {k:v for k,v in value.items() if k!='created_utc'}!=_spec_value():raise ValueError('Rebuilt diagnostic specification differs')
    return value


def freeze():
    with exclusive():
        if (ROOT/SPEC).exists():return specification()
        if (ROOT/SEAL).exists():raise FileExistsError('Orphan immutable specification seal')
        value=dict(_spec_value(),created_utc=datetime.now(timezone.utc).isoformat())
        public_json(ROOT/SPEC,value,exclusive=True)
        public_json(ROOT/SEAL,dict(status='v35_diagnostics_specification_sealed',specification=describe(ROOT/SPEC)),exclusive=True)
        print(dict(specification=SPEC,direct_sources=len(value['plan']['direct_sources']),real_queries=0))
        return value


def acceptance():
    with exclusive():
        if (ROOT/ACCEPT).exists():raise FileExistsError('Immutable diagnostics acceptance exists')
        spec=specification();methods=spec['plan']['direct_sources'];verify_bindings(methods)
        folder=PRIVATE/('knn-v35-tests-'+uuid4().hex);folder.mkdir();start=perf_counter()
        expected=parent.ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
            result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=parent.Result).run(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.wasSuccessful() or result.skipped or Counter(result.passed)!=Counter(expected):
            print((folder/'tests.log').read_text(encoding='utf-8')[-14000:]);raise ValueError('Readonly diagnostic synthetic acceptance failed')
        verify_bindings(methods)
        if specification()!=spec:raise ValueError('Specification or direct source closure changed during acceptance')
        from tests import test_retailrocket_session_knn_diagnostic_entry_v35 as fixture
        integration=fixture.integration_evidence();_check_integration(integration)
        value=dict(status='v35_readonly_diagnostics_tools_synthetic_accepted',created_utc=datetime.now(timezone.utc).isoformat(),
            specification=describe(ROOT/SPEC),seal=describe(ROOT/SEAL),methods=methods,suites=list(SUITES),
            tests_run=result.testsRun,passed_test_ids=result.passed,failures=0,errors=0,skipped=0,
            log=describe(folder/'tests.log'),seconds=perf_counter()-start,integration=integration,
            environment=environment(),gates=spec['gates'],real_query_runs=0,T_plan=None)
        public_json(ROOT/ACCEPT,value,exclusive=True)
        print(dict(tests=result.testsRun,real_query_runs=0,acceptance=ACCEPT));return value


def accepted(spec=None):
    spec=specification() if spec is None else spec;value=read(ROOT/ACCEPT)
    expected=parent.ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if (value['status']!='v35_readonly_diagnostics_tools_synthetic_accepted' or value['specification']!=describe(ROOT/SPEC)
            or value['seal']!=describe(ROOT/SEAL) or value['methods']!=spec['plan']['direct_sources']
            or value['suites']!=list(SUITES) or Counter(value['passed_test_ids'])!=Counter(expected)
            or value['tests_run']!=len(expected) or any(value[k]!=0 for k in ('failures','errors','skipped','real_query_runs'))
            or value['environment']!=environment() or value['gates']!=spec['gates'] or value['T_plan'] is not None):
        raise ValueError('Exact current diagnostic methods must pass acceptance')
    verify_bindings([*value['methods'],value['log'],*value['integration']['evidence']])
    _check_integration(value['integration'])
    return value


def _check_integration(integration):
    expected=dict(synthetic_only=True,top_level_contract_exercised=True,cold_cycles=4,cold_fresh_cycles=4,
        cold_recorded_cycles=3,codec_calls=8,codec_recorded_pairs=3,real_query_runs=0,empty_checkpoint_records=0,
        publisher_independent_rebuilds=1)
    for name,value in expected.items():
        if type(integration.get(name)) is not type(value) or integration[name]!=value:
            raise ValueError('Synthetic top-level diagnostic lifecycle/scope was not accepted')
    folder=(ROOT/integration['namespace']).resolve()
    if (folder.name!='window' or folder.parent.parent!=PRIVATE.resolve()
            or not folder.parent.name.startswith('knn-v35-diag-synthetic-')):
        raise ValueError('Independent nested artificial integration namespace required')
    request=read(folder/'request.json');completion=read(folder/'supervisor_completion.json')
    if request['metadata'].get('synthetic_acceptance_only') is not True:raise ValueError('Synthetic integration marker required')
    exits={kind:old.child_exit(folder,request,kind) for kind in ('worker','publisher')}
    common.closed_log_manifest(folder,request,completion,exits,expected=integration['final_seal'])
    verify_bindings(integration['evidence'])


def source_contract():
    spec=specification();approval=accepted(spec);plan=spec['plan']
    extra=[describe(ROOT/SPEC),describe(ROOT/SEAL),describe(ROOT/ACCEPT),approval['log'],*approval['integration']['evidence']]
    sources=common.merge_methods(plan['sources'],extra)
    common.require_direct_sources(plan['methods'],sources)
    meta=dict(cohort=plan['cohort'],context=dict(dependencies=plan['context_dependencies'],methods=plan['methods']),
        cold_schedule=COLD_SCHEDULE,codec_schedule=CODEC_SCHEDULE,scope=SCOPE,fingerprint_scheme=codec.SCHEME,
        environment=spec['environment'],gates=spec['gates'],specification=describe(ROOT/SPEC),seal=describe(ROOT/SEAL),
        acceptance=describe(ROOT/ACCEPT),original_request=plan['original_request'],parent_inputs=plan['parent_inputs'])
    return sources,meta


def contract(request):
    old._check_window(request);s1.require_scheme(request);sources,meta=source_contract()
    if request['sources']!=sources or request['metadata']!=meta:raise ValueError('Readonly request differs from sealed diagnostics activation')
    common.require_direct_sources(meta['context']['methods'],sources)
    return meta


def folder_path(folder):
    folder=Path(folder).resolve()
    if folder.parent!=PRIVATE.resolve() or not folder.name.startswith('knn-v35-diagnostics-'):
        raise ValueError('One direct diagnostics-window namespace required')
    return folder


def quiet_role(folder,request,role):
    value,text=common.quiet_contract(contract,request)
    record=dict(role=role,contract_complete=True,captured_output=text)
    path=folder/'contract_diagnostics'/f'{role}.json'
    if path.exists():
        if read(path)!=record:raise ValueError('Closed contract diagnostics differ')
    else:path.parent.mkdir(parents=True,exist_ok=True);write(path,record)
    return value


def inputs(request):
    meta=request['metadata'];deps=meta['context']['dependencies'];binding=read(ROOT/meta['cohort']['old_run'])['binding']
    config=read(ROOT/deps['config']['path']);model=read(ROOT/deps['model']['path'])['receipt']
    paths=dict(P0=(ROOT/deps['counts']['path']).parent,dataset=(ROOT/deps['catalog']['path']).parent)
    return dict(paths=paths,config=config,model=model,binding=binding,contract=s1.context_contract(request,binding))


def _schedules(request):
    meta=request['metadata']
    if meta['cold_schedule']!=COLD_SCHEDULE or meta['codec_schedule']!=CODEC_SCHEDULE:
        raise ValueError('Fixed four cold and alternating eight codec observations required')
    return [*COLD_SCHEDULE,*CODEC_SCHEDULE]


def _dimensions(prepared):
    return dict(catalog_rows=len(prepared.first),count_rows=len(prepared.counts),first_times=len(prepared.first_times),fallback=len(prepared.fallback))


def _bytes_identity(value):return dict(bytes=len(value),sha256=hashlib.sha256(value).hexdigest())


def _sampled(root,request,item,function):
    root.mkdir();obs=Observation();sampler=TelemetrySampler(interval_seconds=.2,process_name_prefix='ollama');sampler.start(0)
    span=dict(label=item['label'],mode=item['mode'],repeat_index=0,completed=False,
        start_monotonic_seconds=perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:
        result=function(obs);write(root/'result.json',result);span['completed']=True;return result
    finally:
        span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        try:sampler.stop()
        finally:
            write(root/'entry_span.json',span)
            write(root/'telemetry_records.json',dict(label=item['label'],mode=item['mode'],records=sampler.records))
            old.save_observation(root,obs)


def run_cold_cycle(folder,request,item,data,watch):
    root=folder/item['label']
    def run(obs):
        pool=diag.WorkerContext(data['contract'],ROOT,ROOT);prepared=None
        try:
            with obs.span('replay.cold.total'):
                store=c1.ReuseStore.create(root/'empty_store',data['binding'],request['deadline_utc'],request['budget_seconds'],
                    source_root=ROOT,observer=obs,expected_queries=0,required_stages=())
                with store.writer():
                    counts,catalog=pool.load(data['paths'],data['config'],data['model']['support'],watch,
                        model=data['model'],store=store,namespace=str(folder.resolve()),request=request,observer=obs)
                    prepared=pool.prepare(catalog,counts,watch);pool.finish(obs,watch)
                    if store.recover()['records'] or list(store.iter_records()):raise ValueError('Readonly cold cycle committed query rows')
                    reference=obs.call('replay.cold.equivalence',codec.fingerprint,prepared,obs,watch)
                    if reference!=pool.expected_digest:raise ValueError('Cold observed fingerprint differs from original codec')
                    result=dict(item=item,digest=reference,dimensions=_dimensions(prepared),cache_use=dict(pool.calls[0]),
                        full_checks=list(store.full_checks),empty_records=0,watch_observations=list(pool.watch_observations),
                        expected_config=_bytes_identity(pool.expected_config),expected_model=_bytes_identity(pool.expected_model),
                        diagnostic_fingerprints=3,reference_fingerprints=1)
            return result
        finally:pool.close()
    return _sampled(root,request,item,run)


def _rebuild(data,observer,watch):
    deps=data['contract']['dependencies']
    values={}
    for name,record in deps.items():
        with observer.span('replay.setup.buffer',dependency=name):values[name]=c1.verified_buffer(ROOT,record,watch)
    with observer.span('replay.setup.parse_and_compare'):
        config=c1.json.loads(values['config']);model=c1.json.loads(values['model'])['receipt']
        if c1.canonical(config)!=c1.canonical(data['config']) or c1.canonical(model)!=c1.canonical(data['model']):
            raise ValueError('Independent reconstruction differs from exact config/model buffers')
    paths=dict(data['paths'],P0=c1.BufferRoot('item_counts.csv',values['counts']),dataset=c1.BufferRoot('catalog.csv',values['catalog']))
    with observer.span('replay.setup.original_load_context'):
        counts,catalog=c1.ORIGINALS[1](paths,data['config'],data['model']['support'],watch)
    with observer.span('replay.setup.original_prepare_catalog'):prepared=c1.ORIGINALS[2](catalog,counts,watch)
    return prepared


def prepare_validation(folder,request,data,watch):
    root=folder/'validation_setup';root.mkdir();obs=Observation()
    try:
        with obs.span('replay.validation_setup'):
            prepared=_rebuild(data,obs,watch)
            with obs.span('replay.preimage_equivalence'):
                baseline=codec.encode_snapshot(prepared,watch=watch);instrumented=diag.encode_snapshot(prepared,watch=watch)
                if baseline!=instrumented:raise ValueError('Complete original and observed preimage bytes differ')
                preimage=_bytes_identity(baseline);del baseline,instrumented
            digest=obs.call('replay.setup.expected_fingerprint',codec.fingerprint,prepared,obs,watch)
            result=dict(digest=digest,preimage=preimage,dimensions=_dimensions(prepared),
                expected_config=_bytes_identity(c1.canonical(data['config'])),expected_model=_bytes_identity(c1.canonical(data['model'])),
                timer_overhead=diag.timer_overhead(256),setup_is_charged=True)
            write(root/'result.json',result)
        return prepared,result
    finally:old.save_observation(root,obs)


def run_codec_call(folder,request,item,prepared,expected_digest,watch):
    def run(obs):
        calls=0;records=[]
        def counted():
            nonlocal calls
            calls+=1;return watch()
        with obs.span('replay.codec.call',mode=item['mode']):
            digest=(codec.fingerprint(prepared,obs,counted) if item['mode']=='B' else
                diag.fingerprint(prepared,obs,counted,watch_sample_every=1024,watch_observations=records))
        if digest!=expected_digest:raise ValueError('Paired codec fingerprint differs from exact reference')
        return dict(item=item,digest=digest,watch_calls=calls,watch_observations=records,dimensions=_dimensions(prepared))
    return _sampled(folder/item['label'],request,item,run)


def run_worker(folder,request,data):
    _schedules(request);watch=ThrottledWatch(folder,request['deadline_utc'])
    try:
        old.hash_phase(folder,request,'worker_initial_hash',watch)
        input_obs=Observation()
        try:
            with input_obs.span('replay.input_load'):data=data() if callable(data) else data
        finally:old.save_observation(folder/'input_setup',input_obs)
        for item in COLD_SCHEDULE:
            watch.force();run_cold_cycle(folder,request,item,data,watch)
        prepared,setup=prepare_validation(folder,request,data,watch)
        for item in CODEC_SCHEDULE:
            watch.force();run_codec_call(folder,request,item,prepared,setup['digest'],watch)
        del prepared
        old.hash_phase(folder,request,'worker_final_hash',watch);write(folder/'worker_done.json',DONE)
    except BaseException as error:
        write(folder/'worker_failure.json',dict(error_type=type(error).__name__));raise


def _owners(events,event,phase):
    parent_id=event['parent']
    while parent_id is not None:
        parent=events[parent_id]
        if parent['phase']==phase:return True
        parent_id=parent['parent']
    return False


def _phase_calls(summary,name,expected):
    if summary['phases'].get(name,{}).get('calls',0)!=expected:raise ValueError('Diagnostic phase count differs: '+name)


def _watch_report(report,dimensions):
    segments=[('first',dimensions['catalog_rows']),('counts',dimensions['count_rows']),
        ('first_times',dimensions['first_times']),('fallback',dimensions['fallback']),
        ('final_validation',1),('outside_validation',3)]
    expected_calls=sum(count for _,count in segments)
    sampled=expected_calls//1024
    integers=('watch_calls','sampled_calls','sample_every','unsampled_count','started_sampling_counter','stopped_sampling_counter')
    if (any(type(report[name]) is not int for name in integers)
            or report['watch_calls']!=expected_calls or report['sampled_calls']!=sampled or report['sample_every']!=1024
            or report['unsampled_count']!=expected_calls-sampled or report['started_sampling_counter']!=sampled
            or report['stopped_sampling_counter']!=sampled or report['completed'] is not True
            or type(report['sample_seconds']) not in (int,float) or not math.isfinite(report['sample_seconds']) or report['sample_seconds']<0
            or set(report['fields'])!={name for name,_ in segments}):
        raise ValueError('Amortized watch observation counters differ')
    offset=0
    for name,count in segments:
        row=report['fields'][name];samples=(offset+count)//1024-offset//1024;offset+=count
        if (set(row)!={'watch_calls','sampled_calls','sample_seconds','unsampled_count'}
                or any(type(row[key]) is not int for key in ('watch_calls','sampled_calls','unsampled_count'))
                or row['watch_calls']!=count or row['sampled_calls']!=samples or row['unsampled_count']!=count-samples
                or type(row['sample_seconds']) not in (int,float) or not math.isfinite(row['sample_seconds']) or row['sample_seconds']<0):
            raise ValueError('Per-field complete watch coverage or sampling position differs')
    if not math.isclose(math.fsum(row['sample_seconds'] for row in report['fields'].values()),report['sample_seconds'],abs_tol=1e-12):
        raise ValueError('Per-field watch durations differ from sampled sum')


def reconcile_saved(folder,request,data,expected,observer=None):
    """Recompute saved trees/telemetry/empty ledgers; no context or query replay."""
    _schedules(request);binding=data['binding'];cold={};codecs={};loads=[];previous=None
    if read(folder/'worker_done.json')!=DONE:raise ValueError('All readonly worker observations must complete')
    for name in ('worker_initial_hash','worker_final_hash'):
        events,summary=old.check_observation(folder/name)
        if [e['metadata']['descriptor'] for e in events if e['phase']=='closure.descriptor']!=request['sources']:
            raise ValueError('Worker full source coverage changed')
    _,input_setup=old.check_observation(folder/'input_setup');_phase_calls(input_setup,'replay.input_load',1)
    setup=read(folder/'validation_setup/result.json');old.check_observation(folder/'validation_setup')
    for name in ('digest','dimensions','expected_config','expected_model'):
        if setup[name]!=expected[name]:raise ValueError('Independent setup/reference differs')
    if setup['preimage']!=expected['preimage'] or setup['setup_is_charged'] is not True or setup['timer_overhead']['samples']!=256:
        raise ValueError('Complete preimage proof or charged setup differs')
    dimensions=expected['dimensions'];watch_calls=dimensions['catalog_rows']+dimensions['count_rows']+dimensions['first_times']+dimensions['fallback']+4
    for item in [*COLD_SCHEDULE,*CODEC_SCHEDULE]:
        root=folder/item['label'];row=read(root/'result.json');events,summary=old.check_observation(root)
        if row['item']!=item or row['digest']!=expected['digest'] or row['dimensions']!=dimensions:raise ValueError('Saved replay identity/content differs')
        load,previous=old.load_summary(root,request,item['label'],item['mode'],previous);loads.append(load)
        if item['mode']=='cold':
            descriptors=[e['metadata']['descriptor'] for e in events if e['phase']=='binding.descriptor']
            if descriptors!=binding['sources']*2 or row['full_checks']!=[dict(force=False,external=False),dict(force=True,external=False)]:
                raise ValueError('Cold original create/post-lock source checks differ')
            checks=[e['metadata'] for e in events if e['phase']=='checkpoint.check_sources']
            if checks!=[dict(force=False,cached_before=False,external=False),dict(force=True,cached_before=True,external=False)]:
                raise ValueError('Cold original lock/source verification boundaries differ')
            if row['empty_records']!=0 or row['diagnostic_fingerprints']!=3 or row['reference_fingerprints']!=1:
                raise ValueError('Readonly cold fingerprint/record scope differs')
            for name in ('expected_config','expected_model'):
                if row[name]!=expected[name]:raise ValueError('Cold exact retained canonical bytes differ')
            use=row['cache_use'];deps=data['contract']['dependencies'];methods=data['contract']['methods']
            expected_use=dict(cold=True,hit=False,snapshot_digest=expected['digest'],fingerprint_scheme=codec.SCHEME,
                catalog_rows=dimensions['catalog_rows'],count_rows=dimensions['count_rows'],
                buffer_logical_bytes=sum(x['bytes'] for x in deps.values()),
                context_source_logical_bytes=sum(deps[n]['bytes'] for n in ('counts','catalog')),
                method_logical_bytes=sum(x['bytes'] for x in methods),method_verifications=len(methods))
            if use!=expected_use:raise ValueError('Fresh cold use/complete source-byte accounting differs')
            uses=[e['metadata'] for e in events if e['phase']=='cache.use']
            if uses!=[use]:raise ValueError('Cache use metadata differs')
            for name in ('cache.cold_build','cache.original_load_context','cache.original_prepare_catalog','cache.identity','cache.pre_use_digest','cache.final_guard'):
                _phase_calls(summary,name,1)
            for name in ('snapshot.fingerprint','snapshot.validation','snapshot.json','snapshot.utf8','snapshot.sha256'):_phase_calls(summary,name,4)
            _phase_calls(summary,'snapshot.release',8)
            for name in diag.VALIDATION_PHASES:_phase_calls(summary,name,3)
            expected_parts={'cold.buffer.acquire':4,'cold.parse.config':1,'cold.parse.model':1,'cold.canonical.compare':4,
                'cold.canonical.expected':2,'cold.buffer.view':2,'cold.prepare.mapping_view':2,'cold.prepare.frozen_catalog':1,'cold.expected_fingerprint':1}
            for name,count in expected_parts.items():_phase_calls(summary,name,count)
            fingerprints=[e for e in events if e['phase']=='snapshot.fingerprint']
            owners=('cache.cold_build','cache.pre_use_digest','cache.final_guard','replay.cold.equivalence')
            if any(sum(_owners(events,event,phase) for phase in owners)!=1 for event in fingerprints):
                raise ValueError('Each cold fingerprint requires exactly one integrity boundary')
            for phase in owners:
                if sum(_owners(events,e,phase) for e in fingerprints)!=1:raise ValueError('Cold live fingerprint left original boundary')
            if len(row['watch_observations'])!=3:raise ValueError('Three cold diagnostic watch records required')
            for record in row['watch_observations']:_watch_report(record,dimensions)
            store_root=root/'empty_store';run=read(store_root/'run.json')
            if (run['binding']!=binding or run['expected_queries']!=0 or run['required_stages']!=[]
                    or run['deadline_utc']!=request['deadline_utc'] or run['budget_seconds']!=request['budget_seconds']):
                raise ValueError('Readonly checkpoint run contract differs')
            if observer is not None:
                store=c1.ReuseStore.open(store_root,binding,source_root=ROOT,observer=observer)
                if store.recover()['records'] or list(store.iter_records()):raise ValueError('Readonly ledger is not empty')
            elif any((store_root/'chunks').iterdir()):raise ValueError('Readonly ledger has committed chunks')
            cold[item['label']]=dict(result=row,diagnostic=summary,load=load)
        else:
            _phase_calls(summary,'replay.codec.call',1)
            for phase in ('snapshot.fingerprint','snapshot.validation','snapshot.json','snapshot.utf8','snapshot.sha256'):_phase_calls(summary,phase,1)
            _phase_calls(summary,'snapshot.release',2)
            if row['watch_calls']!=watch_calls:raise ValueError('Every original codec watch invocation must remain')
            if item['mode']=='D':
                for phase in diag.VALIDATION_PHASES:_phase_calls(summary,phase,1)
                if len(row['watch_observations'])!=1:raise ValueError('One observed codec watch report required')
                _watch_report(row['watch_observations'][0],dimensions)
            elif row['watch_observations'] or any(e['phase'] in diag.VALIDATION_PHASES for e in events):
                raise ValueError('Baseline was instrumented as observed codec')
            codecs[item['label']]=dict(result=row,diagnostic=summary,load=load)
        if any(e['metadata'].get('scheme')!=codec.SCHEME for e in events if e['phase'].startswith('snapshot.')):
            raise ValueError('Mixed snapshot scheme in replay')
    return dict(cold=cold,codec=codecs,setup=setup,input_setup=input_setup,loads=loads,last_telemetry_end=previous)


def _distribution(values):
    values=list(values)
    return dict(count=len(values),min=min(values),median=median(values),max=max(values),sum=math.fsum(values))


def summarize_replay(saved):
    cold=[x for label,x in saved['cold'].items() if label!='cold_warm']
    names=sorted(set().union(*(x['diagnostic']['phases'] for x in cold)))
    cold_parts={name:{label:_distribution(x['diagnostic']['phases'].get(name,{}).get(kind,0)/1e9 for x in cold)
        for kind,label in (('inclusive_wall_ns','inclusive_seconds'),('exclusive_wall_ns','exclusive_seconds'))} for name in names}
    modes={}
    for mode in 'BD':
        rows=[x for x in saved['codec'].values() if x['result']['item']['mode']==mode and not x['result']['item']['warmup']]
        phases=sorted(set().union(*(x['diagnostic']['phases'] for x in rows)))
        modes[mode]=dict(outer_call_seconds=_distribution(x['diagnostic']['phases']['replay.codec.call']['inclusive_wall_ns']/1e9 for x in rows),
            phases={name:_distribution(x['diagnostic']['phases'].get(name,{}).get('inclusive_wall_ns',0)/1e9 for x in rows) for name in phases})
    pairs=[]
    for i,order in ((1,'BD'),(2,'DB'),(3,'BD')):
        values={mode:saved['codec'][f'codec_{i}_{mode}']['diagnostic']['phases']['replay.codec.call']['inclusive_wall_ns']/1e9 for mode in 'BD'}
        pairs.append(dict(cycle=i,order=order,original_seconds=values['B'],observed_seconds=values['D'],
            observed_minus_original_seconds=values['D']-values['B']))
    watch=[r for rows in (saved['cold'],saved['codec']) for x in rows.values() for r in x['result']['watch_observations']]
    return dict(cold_recorded_phase_seconds=cold_parts,codec_formal_modes=modes,codec_formal_pairs=pairs,
        one_time_input_setup_seconds=saved['input_setup']['root_wall_ns']/1e9,
        watch=dict(records=len(watch),watch_calls=sum(x['watch_calls'] for x in watch),sampled_calls=sum(x['sampled_calls'] for x in watch),
            sampled_seconds=math.fsum(x['sample_seconds'] for x in watch),unsampled_count=sum(x['unsampled_count'] for x in watch)),
        load_coverage=dict(contexts=len(saved['loads']),samples=sum(x['samples'] for x in saved['loads']),
            missing_periodic_intervals=sum(x['coverage']['missing_periodic_intervals'] for x in saved['loads']),
            max_gap_seconds=max(x['coverage']['max_gap_seconds'] for x in saved['loads']),
            interpretation='Twelve individual cold/codec contexts only. Worker input setup, validation setup, closure hashes and between-context intervals have wall observations but no entry telemetry; publisher telemetry is separate.'),
        interpretation='Independent diagnostic replay only. Inclusive/exclusive units are seconds; inclusive fields nest. Gross traversal includes wrapper/watch overhead. Watch samples cannot be added to traversal or extrapolated. B/D differences measure observation overhead, never an optimization gain or a breakdown of historical original48 time.')


def audit_saved(folder,request,observer):
    old.child_exit(folder,request,'worker');watch=ThrottledWatch(folder,request['deadline_utc'])
    with observer.span('publisher.initial_hash'):observer.verify_bindings(request['sources'],watch)
    data=inputs(request)
    with observer.span('publisher.independent_context'):
        prepared=_rebuild(data,observer,watch)
        raw=codec.encode_snapshot(prepared,watch=watch)
        digest=observer.call('publisher.expected_fingerprint',codec.fingerprint,prepared,observer,watch)
        if digest!=hashlib.sha256(raw).hexdigest():raise ValueError('Independent original digest differs from full preimage')
        expected=dict(digest=digest,preimage=_bytes_identity(raw),dimensions=_dimensions(prepared),
            expected_config=_bytes_identity(c1.canonical(data['config'])),expected_model=_bytes_identity(c1.canonical(data['model'])))
        del raw,prepared
    with observer.span('publisher.saved_observations_and_empty_ledgers'):
        saved=reconcile_saved(folder,request,data,expected,observer)
    with observer.span('publisher.final_hash'):observer.verify_bindings(request['sources'],watch)
    if check_gates()!=request['metadata']['gates']:raise ValueError('Scientific gates changed')
    result=dict(status='v35_readonly_diagnostics_independent_audit_complete',cold=saved['cold'],codec=saved['codec'],setup=saved['setup'],
        summary=summarize_replay(saved),reference=expected,scope=SCOPE,evidence=common.publisher_evidence(folder),T_plan=None)
    observer.call('publisher.result_write',write,folder/'audited_result.json',result)
    return result


def run_publisher(folder,request):
    (folder/'publisher').mkdir();obs=Observation();sampler=TelemetrySampler(interval_seconds=.2,process_name_prefix='ollama');sampler.start(0)
    span=dict(label='publisher',mode='publisher',repeat_index=0,completed=False,
        start_monotonic_seconds=perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:obs.publisher(audit_saved,folder,request,obs);span['completed']=True
    finally:
        span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        try:sampler.stop()
        finally:
            write(folder/'publisher/entry_span.json',span)
            write(folder/'publisher/telemetry_records.json',dict(label='publisher',mode='publisher',records=sampler.records))
            old.save_observation(folder/'publisher',obs)


def worker(folder):
    folder=folder_path(folder);request=read(folder/'request.json');quiet_role(folder,request,'worker')
    return run_worker(folder,request,lambda:inputs(request))


def publisher(folder):
    folder=folder_path(folder);request=read(folder/'request.json');quiet_role(folder,request,'publisher')
    return run_publisher(folder,request)


def pipeline(folder):
    folder=folder_path(folder);request=read(folder/'request.json');quiet_role(folder,request,'pipeline')
    return lifecycle.run_pipeline(folder,request,{k:[sys.executable,'-B','-m',MODULE,'--'+k,str(folder)] for k in ('worker','publisher')})


def audit_completed(folder,request):
    completion=read(folder/'supervisor_completion.json');old._check_window(request,completion)
    exits={k:old.child_exit(folder,request,k) for k in ('worker','publisher')}
    if exits['worker']['ended_utc']>exits['publisher']['started_utc']:raise ValueError('Readonly worker and publisher overlapped')
    verify_bindings(exits['publisher']['outputs']);result=read(folder/'audited_result.json');verify_bindings(result['evidence'])
    if result['status']!='v35_readonly_diagnostics_independent_audit_complete' or result['scope']!=SCOPE or result['T_plan'] is not None:
        raise ValueError('Readonly independent publication scope differs')
    events,pub=old.check_observation(folder/'publisher')
    if [e['metadata']['descriptor'] for e in events if e['phase']=='closure.descriptor']!=request['sources']*2:
        raise ValueError('Publisher two full source passes differ')
    data=inputs(request)
    if [e['metadata']['descriptor'] for e in events if e['phase']=='binding.descriptor']!=data['binding']['sources']*4:
        raise ValueError('Publisher four empty original-store checks differ')
    saved=reconcile_saved(folder,request,data,result['reference'])
    if (result['cold']!=saved['cold'] or result['codec']!=saved['codec'] or result['setup']!=saved['setup']
            or result['summary']!=summarize_replay(saved)):raise ValueError('Published raw diagnostic summary differs')
    load,_=old.load_summary(folder/'publisher',request,'publisher','publisher',saved['last_telemetry_end'])
    seal=common.closed_log_manifest(folder,request,completion,exits)
    return result,completion,exits,pub,load,seal


def release(folder):
    folder=folder_path(folder);request=read(folder/'request.json');meta,text=common.quiet_contract(contract,request)
    result,completion,exits,pub,load,seal=audit_completed(folder,request)
    # External release diagnostics cannot alter the closed original window.
    outside=PRIVATE/'knn-v35-publication'/folder.name;path=outside/'contract_diagnostics.json'
    diagnostics=dict(role='release',contract_complete=True,captured_output=text)
    if path.exists():
        if read(path)!=diagnostics:raise ValueError('Closed external release diagnostics differ')
    else:path.parent.mkdir(parents=True,exist_ok=True);write(path,diagnostics)
    report=dict(status='v35_readonly_cold_and_validation_diagnostics_measured',namespace=folder.relative_to(ROOT).as_posix(),
        specification=meta['specification'],acceptance=meta['acceptance'],parent_inputs=meta['parent_inputs'],
        supervisor=completion,results=result,summary=result['summary'],publisher_observation=pub,publisher_load=load,
        worker_source_observations={name:read(folder/name/'observation.json') for name in ('worker_initial_hash','worker_final_hash')},
        process_wall_seconds={k:v['seconds'] for k,v in exits.items()},final_log_seal=seal,release_contract_diagnostics=describe(path),
        evidence=seal['window_evidence'],scope=SCOPE,gates=check_gates(),T_plan=None,
        interpretation='New independent readonly observations. Zero original48/query/fit reruns. Not an adoption decision, historical cost allocation, optimization speedup, population/test score or Ollama token/GPU speed measurement.')
    if report['gates']!=meta['gates']:raise ValueError('Scientific gates changed at release')
    if (ROOT/REPORT).exists():
        existing=read(ROOT/REPORT);verify_bindings(existing['evidence'])
        common.closed_log_manifest(folder,request,completion,exits,expected=existing['final_log_seal'])
        if existing!=report:raise ValueError('Immutable diagnostics report differs')
        receipt=read(ROOT/RELEASE);seconds=receipt['public_serialization_seconds']
        if (receipt['status']!='v35_readonly_diagnostics_public_report_released' or receipt['report']!=describe(ROOT/REPORT)
                or receipt['deadline_utc']!=request['deadline_utc'] or type(seconds) not in (int,float)
                or not math.isfinite(seconds) or seconds<0):raise ValueError('Diagnostics release seal differs')
    else:
        start=perf_counter();public_json(ROOT/REPORT,report,exclusive=True)
        public_json(ROOT/RELEASE,dict(status='v35_readonly_diagnostics_public_report_released',report=describe(ROOT/REPORT),
            deadline_utc=request['deadline_utc'],public_serialization_seconds=perf_counter()-start),exclusive=True)
    print(dict(report=REPORT,seconds=completion['seconds'],real_query_runs=0));return report


def measure():
    with exclusive():
        if (ROOT/REPORT).exists():raise FileExistsError('Use --release to audit the completed diagnostics window')
        for path in PRIVATE.glob('knn-v35-diagnostics-*/request.json'):
            raise FileExistsError('Existing diagnostics window forbids automatic retry: '+str(path.parent))
        sources,meta=source_contract();folder=PRIVATE/('knn-v35-diagnostics-'+uuid4().hex)
        print('V35 readonly diagnostics namespace: '+folder.relative_to(ROOT).as_posix(),flush=True)
        run_window(folder,[sys.executable,'-B','-m',MODULE,'--pipeline',str(folder)],sources,'joint_tail',
            metadata=meta,budget_seconds=1800,limits=LIMITS)
        return release(folder)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('specification','acceptance','measure'):mode.add_argument('--'+name,action='store_true')
    for name in ('pipeline','worker','publisher','release'):mode.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.specification:freeze()
    elif args.acceptance:acceptance()
    elif args.measure:measure()
    elif args.pipeline:pipeline(args.pipeline)
    elif args.worker:worker(args.worker)
    elif args.publisher:publisher(args.publisher)
    else:
        with exclusive():release(args.release)
