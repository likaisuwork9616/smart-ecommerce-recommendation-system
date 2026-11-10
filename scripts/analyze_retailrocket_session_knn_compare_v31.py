"""Reconcile completed V31 original48 costs, full frames and raw observations only."""
import argparse
import math
from pathlib import Path
from statistics import median

import psutil

from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from scripts.run_retailrocket_session_knn_sources_v25 import _check_window,child_exit,load_summary
from scripts.retailrocket_session_knn_sources_v24 import summarize_events
from scripts.retailrocket_session_knn_priority_v23 import summarize_run
from scripts.retailrocket_session_knn_compare_v28 import decision
from scripts.retailrocket_session_knn_snapshot_v30 import SCHEME

BASE='reports/stage12/retailrocket_session_knn_v31_compare_'
COST=BASE+'cost_20261110.json';RELEASE=BASE+'release_20261110.json'
SPEC=BASE+'specification_20261110.json';ACCEPT=BASE+'acceptance_20261110.json'
OUTPUT=BASE+'analysis_20261110.json'
METHOD='scripts/analyze_retailrocket_session_knn_compare_v31.py'
DEPENDENCIES=('scripts/retailrocket_session_knn_priority_v23.py',
    'scripts/retailrocket_session_knn_sources_v24.py','scripts/run_retailrocket_session_knn_sources_v25.py',
    'scripts/retailrocket_session_knn_reinforcement_v18.py','scripts/retailrocket_session_knn_compare_v28.py',
    'scripts/run_retailrocket_session_knn_guards_v21.py','scripts/retailrocket_session_knn_snapshot_v30.py',METHOD)
GUARDS=('cache.identity','cache.pre_use_digest','cache.final_guard')
SNAPSHOT_PHASES=('snapshot.fingerprint','snapshot.validation','snapshot.json','snapshot.utf8','snapshot.sha256','snapshot.release')
PHASES=('binding.verify_sources','context.load_context','context.prepare_catalog','verifier.setup_envelope',
    'cache.cold_build','cache.original_load_context','cache.original_prepare_catalog',*GUARDS,*SNAPSHOT_PHASES)


def distribution(values):
    values=list(values)
    if not values or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise ValueError('Nonempty finite observations required')
    return dict(count=len(values),min=min(values),median=median(values),max=max(values),sum=math.fsum(values))


def remainder(total,parts):
    value=total-math.fsum(parts)
    if not math.isfinite(value) or value < -1e-8:raise ValueError('Disjoint costs exceed their parent')
    return max(0.,value)


def phase_seconds(summary,name):
    return summary['phases'].get(name,{}).get('inclusive_wall_ns',0)/1e9


def check_tree(root,published=None):
    events=read(root/'events.json');summary=summarize_events(events)
    if summary!=read(root/'observation.json') or published is not None and summary!=published:
        raise ValueError('Raw observation tree does not reproduce saved summary')
    if any(not e['completed'] for e in events):raise ValueError('Failed observation in completed window')
    if sum(v['exclusive_wall_ns'] for v in summary['phases'].values())!=summary['root_wall_ns']:
        raise ValueError('Exclusive phase sum differs from observed roots')
    return events,summary


def aggregate_modes(runs,schedule):
    result={}
    for mode in ('R','C'):
        selected=[runs[x['label']] for x in schedule if x['mode']==mode and x['label'].startswith('pair_')]
        if len(selected)!=6:raise ValueError('Six formal paired observations per arm required')
        accounting=selected[0]['accounting']
        groups={name:{key:distribution(row['accounting'][name][key] for row in selected)
            for key in accounting[name]} for name in (
                'entry_exclusive_seconds','primary_parts_seconds','append_parts_seconds','rank_stages_seconds')}
        result[mode]=dict(cost_seconds={key:distribution(row['accounting']['costs'][key] for row in selected)
            for key in accounting['costs'] if key.endswith('_seconds')},
            phase_seconds={name:distribution(phase_seconds(row['diagnostic'],name) for row in selected) for name in PHASES},
            all_observed_budget_seconds=distribution(row['accounting']['all_observed_budget_seconds'] for row in selected),
            **groups)
    return result


def aggregate_load(loads):
    duration=math.fsum(x['duration_seconds'] for x in loads)
    if duration<=0:raise ValueError('Observed telemetry duration required')
    ollama=[x['ollama'] for x in loads if x['ollama']['cpu_core_percent'] is not None]
    ollama_duration=math.fsum(x['valid_cpu_duration_seconds'] for x in ollama)
    return dict(samples=sum(x['samples'] for x in loads),duration_seconds=duration,
        system_cpu_percent_min=min(x['system_cpu_percent']['min'] for x in loads),
        system_cpu_percent_max=max(x['system_cpu_percent']['max'] for x in loads),
        system_cpu_percent_duration_weighted_mean=math.fsum(x['system_cpu_percent']['mean']*x['duration_seconds'] for x in loads)/duration,
        available_memory_min_bytes=min(x['available_memory_bytes']['min'] for x in loads),
        maximum_sampling_gap_seconds=max(x['coverage']['max_gap_seconds'] for x in loads),
        missing_periodic_intervals=sum(x['coverage']['missing_periodic_intervals'] for x in loads),
        collector_seconds=math.fsum(x['total_collector_seconds'] for x in loads),
        ollama_valid_cpu_intervals=sum(x['ollama']['valid_cpu_intervals'] for x in loads),
        ollama_valid_cpu_duration_seconds=ollama_duration,
        ollama_cpu_core_percent_duration_weighted_mean=(math.fsum(x['cpu_core_percent']['mean']*x['valid_cpu_duration_seconds'] for x in ollama)/ollama_duration if ollama_duration else None),
        interpretation='Only entry/publisher contexts, including this benchmark. Gaps remain explicit. No per-query interpolation, worker-closure CPU coverage, Ollama token/GPU speed or causal slowdown estimate.')


def build():
    r=read(ROOT/COST);receipt=read(ROOT/RELEASE);spec=read(ROOT/SPEC);accepted=read(ROOT/ACCEPT)
    verify_bindings([receipt['report'],r['specification'],r['acceptance']])
    if receipt['report']!=describe(ROOT/COST) or r['specification']!=describe(ROOT/SPEC) or r['acceptance']!=describe(ROOT/ACCEPT):
        raise ValueError('Public result/specification/acceptance identities differ')
    if r['status']!='v31_C1_S1_original48_real_comparison_measured':raise ValueError('Completed real S1 comparison required')
    if (r['scope']['real_runs']!=14 or r['scope']['engineering_checks']!=672 or r['scope']['new_keys']!=0
            or r['scope']['full_validation_complete'] is not False or r['scope']['reserved_test']!='locked' or r['T_plan'] is not None):
        raise ValueError('Expected original48 known-validation engineering scope')
    verify_bindings(r['evidence'])
    folder=(ROOT/r['namespace']).resolve()
    if not folder.is_relative_to((ROOT/'shop-mysql-runtime/verification').resolve()):raise ValueError('Private execution namespace required')
    request=read(folder/'request.json');_check_window(request,r['supervisor'])
    if request['metadata'].get('synthetic_acceptance_only') or request['metadata']['environment']!=environment():
        raise ValueError('Real unchanged environment required')
    schedule=[dict(label='warm_'+m,mode=m) for m in ('R','C')]+[
        dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')]
    if r['schedule']!=schedule or request['metadata']['schedule']!=schedule or spec['schedule']!=schedule:
        raise ValueError('Original balanced14 schedule differs')
    if request['metadata']['cohort']!=spec['cohort']:raise ValueError('Sealed original cohort changed')
    sources={x['path']:x for x in request['sources']}
    if len(sources)!=len(request['sources']):raise ValueError('Duplicate source identity')
    dependencies=[]
    for name in DEPENDENCIES:
        actual=describe(ROOT/name)
        if sources.get(name)!=actual:raise ValueError('Analysis method was not part of the measured source contract')
        dependencies.append(actual)
    verify_bindings(dependencies)
    cohort=request['metadata']['cohort'];probes=read(ROOT/cohort['probes'])['probes'];reference=read(ROOT/cohort['reference'])
    binding_sources=read(ROOT/cohort['old_run'])['binding']['sources']
    original_frames=list(_physical_frames((ROOT/cohort['old_run']).parent))
    if len(probes)!=48 or len(original_frames)!=48:raise ValueError('Complete original48 roster/reference required')
    original_bytes=b''.join(original_frames)
    import hashlib
    if len(original_bytes)!=reference['actual_committed_bytes'] or hashlib.sha256(original_bytes).hexdigest()!=reference['actual_committed_payload_sha256']:
        raise ValueError('Original full physical reference differs')
    if r['results']['reference']!=reference:raise ValueError('Published reference differs')
    runs=r['results']['runs'];loads=[];snapshot_events=[];tree_count=0;previous=None
    if set(runs)!={x['label'] for x in schedule}:raise ValueError('All14 runs must remain')
    for item in schedule:
        label,mode=item['label'],item['mode'];root=folder/label;row=runs[label]
        if row['mode']!=mode:raise ValueError('Saved arm differs')
        measured,raw,entry=(read(root/p) for p in ('measured.json','observations.json','entry.json'))
        if summarize_run(measured,raw,entry,probes)!=row['accounting']:raise ValueError('Raw saved costs differ')
        if list(_physical_frames(root/'verified_subset'))!=original_frames:raise ValueError('Full scientific frames differ')
        events,summary=check_tree(root,row['diagnostic']);tree_count+=1
        if [e['metadata']['descriptor'] for e in events if e['phase']=='binding.descriptor']!=binding_sources*2:
            raise ValueError('Original create/post-lock source identities differ')
        load,previous=load_summary(root,request,label,mode,previous)
        if load!=row['load']:raise ValueError('Raw telemetry differs from published context')
        loads.append(load)
        current=[e for e in events if e['phase'].startswith('snapshot.')]
        if mode=='R' and current:raise ValueError('Reference unexpectedly used S1 snapshot')
        if mode=='C':
            for event in current:
                if event['metadata'].get('scheme')!=SCHEME:raise ValueError('S1 snapshot scheme differs')
            expected=3 if label=='warm_C' else 2
            for phase in SNAPSHOT_PHASES:
                calls=summary['phases'].get(phase,{}).get('calls',0)
                if calls!=expected*(2 if phase=='snapshot.release' else 1):raise ValueError('Complete live snapshot phase count differs')
            snapshot_events.extend(dict(label=label,warmup=label=='warm_C',phase=e['phase'],seconds=(e['end_ns']-e['start_ns'])/1e9) for e in current)
    if decision(runs)!=r['decision'] or r['results']['decision']!=r['decision']:raise ValueError('Cold-inclusive original gates do not reproduce')
    for name in ('worker_initial_hash','worker_final_hash'):
        events,summary=check_tree(folder/name,r['worker_source_observations'][name]);tree_count+=1
        if [e['metadata']['descriptor'] for e in events if e['phase']=='closure.descriptor']!=request['sources']:
            raise ValueError('Worker full source coverage differs')
    pub_events,pub=check_tree(folder/'publisher',r['publisher_observation']);tree_count+=1
    if [e['metadata']['descriptor'] for e in pub_events if e['phase']=='closure.descriptor']!=request['sources']*2:
        raise ValueError('Publisher full source identities differ')
    if [e['metadata']['descriptor'] for e in pub_events if e['phase']=='binding.descriptor']!=binding_sources*14:
        raise ValueError('Publisher14 original open source identities differ')
    pub_load,_=load_summary(folder/'publisher',request,'publisher','publisher',previous)
    if pub_load!=r['publisher_load']:raise ValueError('Publisher load differs')
    exits={name:child_exit(folder,request,name) for name in ('worker','publisher')}
    if exits['worker']['ended_utc']>exits['publisher']['started_utc']:raise ValueError('Independent publisher overlapped worker')
    for identity in read(folder/'tracked_process_identities.json')['identities']:
        try:
            process=psutil.Process(identity['pid'])
            if process.is_running() and process.create_time()==identity['create_time']:raise ValueError('Tracked identity still running')
        except psutil.NoSuchProcess:pass
    formal_C=[runs[x['label']] for x in schedule if x['mode']=='C' and x['label'].startswith('pair_')]
    guard_sums=distribution(math.fsum(phase_seconds(row['diagnostic'],p) for p in GUARDS) for row in formal_C)
    snapshot_calls={p:sum(e['phase']==p for e in snapshot_events) for p in SNAPSHOT_PHASES}
    if snapshot_calls['snapshot.fingerprint']!=15:raise ValueError('Expected cold plus14 live snapshot checks')
    worker_parts={name:r['worker_source_observations'][name]['root_wall_ns']/1e9 for name in ('worker_initial_hash','worker_final_hash')}
    worker_parts['all14_entry_seconds']=math.fsum(runs[x['label']]['accounting']['costs']['entry_seconds'] for x in schedule)
    worker_parts['other_worker_process_seconds']=remainder(r['process_wall_seconds']['worker'],worker_parts.values())
    pub_total=phase_seconds(pub,'publisher.total')
    pub_parts={p:phase_seconds(pub,p) for p in ('publisher.initial_hash','publisher.final_hash','publisher.independent_context','publisher.open_and_proof','publisher.result_write')}
    pub_parts['other_callback_seconds']=remainder(pub_total,pub_parts.values())
    whole=dict(worker=r['process_wall_seconds']['worker'],publisher=r['process_wall_seconds']['publisher'])
    whole['other_pipeline_and_supervisor']=remainder(r['supervisor']['seconds'],whole.values())
    telemetry=aggregate_load([*loads,pub_load]);telemetry.update(entry_samples=sum(x['samples'] for x in loads),publisher_samples=pub_load['samples'])
    return dict(status='v31_original48_S1_costs_frames_events_and_load_reconciled',
        inputs=[describe(ROOT/p) for p in (COST,RELEASE,SPEC,ACCEPT)],method=describe(ROOT/METHOD),dependencies=dependencies,
        window_created_utc=request['created_utc'],real_saved_runs=14,checks=672,frame_rows_compared=672,
        event_trees_recomputed=tree_count,raw_telemetry_contexts_recomputed=15,
        saved_source_coverage=dict(closure_sources_per_pass=len(request['sources']),closure_passes=4,
            binding_sources=len(binding_sources),worker_binding_verifications=28,publisher_binding_verifications=14,
            observed_descriptor_calls=4*len(request['sources'])+42*len(binding_sources),
            logical_descriptor_bytes=4*sum(x['bytes'] for x in request['sources'])+42*sum(x['bytes'] for x in binding_sources),
            interpretation='Saved successful descriptor identities at original boundaries, not a new raw-global-source rehash or physical I/O count. Extra method-buffer reads and source-gate checks are not this descriptor count.'),
        decision=r['decision'],formal_modes=aggregate_modes(runs,schedule),C_nonoverlapping_guard_seconds=guard_sums,
        all7_C_snapshot_phase_calls=snapshot_calls,
        formal_C_snapshot_phase_seconds_per_entry={p:distribution(phase_seconds(row['diagnostic'],p) for row in formal_C) for p in SNAPSHOT_PHASES},
        formal_C_snapshot_phase_seconds_per_call={p:distribution(e['seconds'] for e in snapshot_events if not e['warmup'] and e['phase']==p) for p in SNAPSHOT_PHASES},
        worker_process_parts_seconds=worker_parts,publisher_callback_parts_seconds=pub_parts,publisher_callback_seconds=pub_total,
        publisher_process_other_seconds=remainder(r['process_wall_seconds']['publisher'],[pub_total]),
        public_serialization_seconds=receipt['public_serialization_seconds'],whole_supervised_window_parts_seconds=whole,telemetry=telemetry,
        saved_evidence=r['evidence'],scope=r['scope'],T_plan=None,
        interpretation='Original48 known-validation engineering only. Inclusive phases nest and cannot be added; guards use disjoint scopes. Six-pair summaries exclude warmups; decision all7 sums include cold. Per-entry snapshot phases aggregate two fingerprints on each formal C. No cross-V28 historical baseline, mixed-window speedup, population/test score or Ollama token/GPU slowdown claim.')


def main(audit=False):
    if audit:
        existing=read(ROOT/OUTPUT);verify_bindings([*existing['inputs'],existing['method'],*existing['dependencies'],*existing['saved_evidence']])
        current=build()
        if current!=existing:raise ValueError('Immutable analysis differs from completed saved evidence')
    else:
        if (ROOT/OUTPUT).exists():raise FileExistsError('Immutable V31 analysis exists; use --audit')
        current=build();public_json(ROOT/OUTPUT,current,exclusive=True)
    print(dict(report=OUTPUT,audit=audit,checks=current['checks'],adopted=current['decision']['adopted'],
        median_entry_saving_percent=current['decision']['median_entry_saving_percent'],
        all7_entry_seconds=current['decision']['all7_entry_seconds'],snapshot_calls=current['all7_C_snapshot_phase_calls']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--analysis',action='store_true');mode.add_argument('--audit',action='store_true')
    main(parser.parse_args().audit)
