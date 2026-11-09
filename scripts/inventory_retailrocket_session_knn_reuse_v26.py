"""Read saved V25 observations only; never rank, build a model or hash raw sources."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import math
from statistics import median

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.retailrocket_session_knn_sources_v24 import summarize_events

BASE='reports/stage12/retailrocket_session_knn_'
COST=BASE+'v25_sources_cost_20261109.json'
ANALYSIS=BASE+'v25_sources_analysis_20261109.json'
RELEASE=BASE+'v25_sources_release_20261109.json'
OUTPUT=BASE+'v26_reuse_inventory_20261109.json'
METHOD='scripts/inventory_retailrocket_session_knn_reuse_v26.py'
METHODS=('scripts/retailrocket_session_knn_checkpoint_v2.py',
 'scripts/retailrocket_session_knn_pair_v4.py','scripts/retailrocket_session_knn_readback_v2.py',
 'scripts/retailrocket_session_knn_sql_v2.py','scripts/retailrocket_session_knn_sql_v4.py',
 'scripts/retailrocket_session_knn_sources_v24.py','scripts/run_retailrocket_session_knn_sources_v25.py')


def distribution(values):
    values=list(values)
    return dict(count=len(values),minimum=min(values),median=median(values),maximum=max(values),total=math.fsum(values))


def observation(folder):
    events=read(folder/'events.json');summary=summarize_events(events)
    if summary!=read(folder/'observation.json') or not all(x['completed'] for x in events):
        raise ValueError('Saved observation tree differs')
    return events,summary


def main():
    if (ROOT/OUTPUT).exists():raise FileExistsError('Immutable inventory already exists')
    report,analysis,release=(read(ROOT/p) for p in (COST,ANALYSIS,RELEASE))
    verify_bindings([release['report'],*analysis['inputs'],analysis['method']])
    # These are small, saved worker/publisher receipts and payload proofs.
    # This verifies historical observation evidence, not current raw data identity.
    verify_bindings(report['evidence'])
    folder=ROOT/report['namespace'];request=read(folder/'request.json')
    sources=request['sources'];source_map={x['path']:x for x in sources}
    if len(source_map)!=len(sources):raise ValueError('Duplicate source paths')
    verify_bindings([source_map[request['metadata']['cohort']['old_run']]])
    old=read(ROOT/request['metadata']['cohort']['old_run']);binding=old['binding']['sources']
    if any(source_map[x['path']]!=x for x in binding):raise ValueError('Binding outside closure')
    methods=[describe(ROOT/p) for p in METHODS]
    if any(source_map[x['path']]!=x for x in methods):raise ValueError('Frozen method changed')
    by_content=defaultdict(list)
    for x in sources:by_content[(x['bytes'],x['sha256'])].append(x)
    duplicate=[v for v in by_content.values() if len(v)>1]
    closure_rows=[];binding_rows=defaultdict(list);diagnostics=[];observed_descriptors=[]
    summaries=[]
    for phase in ('worker_initial_hash','worker_final_hash','publisher'):
        events,summary=observation(folder/phase);summaries.append(summary)
        rows=[x for x in events if x['phase']=='closure.descriptor']
        expected=sources*(2 if phase=='publisher' else 1)
        if [x['metadata']['descriptor'] for x in rows]!=expected:raise ValueError('Closure coverage differs')
        observed_descriptors.extend(rows)
        if phase=='publisher':
            for name in ('publisher.initial_hash','publisher.final_hash'):
                closure_rows.append(dict(boundary=name,descriptors=len(sources),logical_bytes=sum(x['bytes'] for x in sources),
                    wall_seconds=summary['phases'][name]['inclusive_wall_ns']/1e9))
            checks=[x for x in events if x['phase']=='binding.verify_sources']
            if len(checks)!=14:raise ValueError('Publisher open checks differ')
            binding_rows['independent_publisher_open'] += [(x['end_ns']-x['start_ns'])/1e9 for x in checks]
            b=[x for x in events if x['phase']=='binding.descriptor']
            if [x['metadata']['descriptor'] for x in b]!=binding*14:raise ValueError('Publisher binding descriptors differ')
            observed_descriptors.extend(b)
        else:
            closure_rows.append(dict(boundary=phase,descriptors=len(sources),logical_bytes=sum(x['bytes'] for x in sources),wall_seconds=summary['root_wall_ns']/1e9))
    for item in request['metadata']['schedule']:
        if item['mode']!='D':continue
        label=item['label'];events,summary=observation(folder/label);summaries.append(summary)
        if summary!=report['results']['runs'][label]['diagnostic']:raise ValueError('Published diagnostic differs')
        b=[x for x in events if x['phase']=='binding.descriptor']
        if [x['metadata']['descriptor'] for x in b]!=binding*2:raise ValueError('D source descriptors differ')
        observed_descriptors.extend(b)
        for x in [x for x in events if x['phase']=='binding.verify_sources']:
            ancestors=[];parent=x['parent']
            while parent is not None:
                ancestors.append(events[parent]['phase']);parent=events[parent]['parent']
            boundary='D_after_writer_lock' if 'checkpoint.writer_acquire' in ancestors else 'D_before_creation'
            if boundary=='D_before_creation' and 'checkpoint.create' not in ancestors:raise ValueError('Unknown source boundary')
            owner=events[x['parent']]
            if owner['phase']!='checkpoint.check_sources' or owner['metadata']['force']!=(boundary=='D_after_writer_lock'):
                raise ValueError('Original forced source boundary differs')
            binding_rows[boundary].append((x['end_ns']-x['start_ns'])/1e9)
        phases=summary['phases']
        for name in ('context.load_context','context.prepare_catalog','verifier.setup_envelope'):
            if phases[name]['calls']!=1:raise ValueError('Initialization count differs')
        diagnostics.append(dict(label=label,warmup=label.startswith('warm_'),
            context_load_seconds=phases['context.load_context']['inclusive_wall_ns']/1e9,
            catalog_prepare_seconds=phases['context.prepare_catalog']['inclusive_wall_ns']/1e9,
            setup_other_seconds=phases['verifier.setup_envelope']['exclusive_wall_ns']/1e9))
    identities={(x['metadata']['descriptor']['path'],x['metadata']['descriptor']['bytes'],x['metadata']['descriptor']['sha256']) for x in observed_descriptors}
    if len(identities)!=len(sources):raise ValueError('Observed identities differ')
    init_paths=[request['metadata']['cohort']['selected_root']+'/'+p for p in (
        'P0/item_counts.csv','dataset/catalog.csv','configuration.json')]
    init_paths += [request['metadata']['cohort']['model_root']+'/reconstruction.json']
    init_dependencies=[source_map[p] for p in init_paths]
    config=read(ROOT/init_paths[2]);verify_bindings([init_dependencies[2]])
    formal=[x for x in diagnostics if not x['warmup']]
    source_wall=math.fsum(x['wall_seconds'] for x in closure_rows)
    boundary_rows={key:dict(verification_calls=len(v),descriptor_calls=len(v)*len(binding),
        logical_bytes=len(v)*sum(x['bytes'] for x in binding),wall_seconds=distribution(v)) for key,v in binding_rows.items()}
    descriptor_logical_bytes=sum(x['metadata']['descriptor']['bytes'] for x in observed_descriptors)
    result=dict(status='v26_saved_evidence_repeated_cost_inventory_complete',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_report=describe(ROOT/COST),parent_analysis=describe(ROOT/ANALYSIS),parent_release=describe(ROOT/RELEASE),
        evidence_audit=dict(saved_files=len(report['evidence']),saved_bytes=sum(x['bytes'] for x in report['evidence']),
            current_raw_sources_rehashed=False,current_model_loaded=False,new_predictions=0),
        methods=methods,inventory_method=describe(ROOT/METHOD),cohort=request['metadata']['cohort'],schedule=request['metadata']['schedule'],
        closure=dict(unique_path_identities=len(sources),single_pass_logical_bytes=sum(x['bytes'] for x in sources),
            four_boundary_observations=closure_rows,total_wall_seconds=source_wall,window_percent=source_wall/report['supervisor']['seconds']*100,
            duplicate_content_groups=len(duplicate),duplicate_content_paths=sum(len(v) for v in duplicate),
            extra_paths_with_same_content=sum(len(v)-1 for v in duplicate),
            same_content_extra_logical_bytes_per_pass=sum(v[0]['bytes']*(len(v)-1) for v in duplicate),
            same_content_descriptor_wall_seconds_four_passes=math.fsum((x['end_ns']-x['start_ns'])/1e9 for x in observed_descriptors
                if x['phase']=='closure.descriptor' and len(by_content[(x['metadata']['descriptor']['bytes'],x['metadata']['descriptor']['sha256'])])>1),
            interpretation='Different lexical paths retain different identities. Equal bytes/hash neither prove a common physical file nor authorize removing a check.'),
        observed_binding_boundaries=boundary_rows,
        observed_descriptor_coverage=dict(calls=len(observed_descriptors),unique_path_identities=len(identities),
            repeated_calls=len(observed_descriptors)-len(identities),logical_bytes=descriptor_logical_bytes,
            interpretation='Instrumented closure and D/publisher binding descriptors only. Contract/reference-gate reads and native R binding costs are not timed here.'),
        structural_unobserved=dict(native_R_runs=7,native_R_binding_verifications=14,native_R_descriptor_calls=14*len(binding),
            native_R_logical_bytes=14*sum(x['bytes'] for x in binding),native_R_source_wall_seconds=None,
            native_R_context_load_calls=7,native_R_catalog_prepare_calls=7,
            contract_evaluations_in_one_successful_measure=5,
            note='Frozen call-flow inference, not observed counts/timing. source_contract and reference-gate verification also repeat; their wall is not independently observed. Additional --release re-audits are excluded.'),
        initialization=dict(dependencies=init_dependencies,per_D_run=diagnostics,
            formal_D={key:distribution(x[key] for x in formal) for key in ('context_load_seconds','catalog_prepare_seconds','setup_other_seconds')},
            observed_D_build_calls=7,structural_all14_build_calls=14,
            code_findings=['load_context parses item_counts and catalog; checks support inclusion/counts, duplicate IDs, canonical numbers and train clocks.',
                'prepare_catalog copies and validates all counts/catalog, creates MappingProxyType maps and immutable first_times/fallback tuples.',
                'verify_selected sorts catalog.values again after prepare_catalog; second sort is inside setup_other with other work, not independently timed.',
                'Original payload/control streams, SQL connection/TEMP state and checkpoint writer state are per-run and must not enter a reusable context.'],
            validation_fields=dict(train_window_ms=config['train_window_ms'],catalog_schema=config['schemas']['catalog.csv']),
            interpretation='Each D phase is measured; native R count is inferred. No measured cache saving or sorting-only cost is available.'),
        preserved_boundaries=['worker full closure before and after all runs','source path/size/SHA256 identity at create',
            'forced full source check after each writer lock','independent publisher full closure before/after audit and all14 original opens',
            'normal exits/deadline/resources/immutable outputs and full payload/workload verification'],
        scope=dict(new_predictions=0,new_performance_windows=0,new_model_fit=0,new_full_validation=0,new_bootstrap=0,
            reserved_test='locked',covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232),T_plan=None)
    public_json(ROOT/OUTPUT,result,exclusive=True)
    print(dict(report=OUTPUT,closure_sources=len(sources),observed_descriptor_calls=len(observed_descriptors),
        duplicate_content_groups=len(duplicate),formal_initialization=result['initialization']['formal_D']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',action='store_true',required=True)
    parser.parse_args();main()
