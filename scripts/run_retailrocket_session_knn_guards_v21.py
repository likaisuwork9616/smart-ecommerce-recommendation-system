"""Six controlled V21 observations of the same sealed seven V19 queries.

R uses the frozen V4 verifier and V6 store; D adds observational SQL/append
proxies. There is no selection, extraction, SQL candidate, or coverage gain.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import math
from pathlib import Path
import statistics
import sys
from time import perf_counter
import unittest
from uuid import uuid4

import psutil

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, PATHS, read, write, describe, verify_bindings, environment, check_gates)
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json, _phase, _check_db, _record
from scripts.run_retailrocket_session_knn_gap_v16 import _check_window
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload
from scripts.run_retailrocket_session_knn_tail_v19 import _check_telemetry_span
from scripts.retailrocket_session_knn_checkpoint_v2 import _lock
from scripts.retailrocket_session_knn_cost_window_v5 import LIMITS, run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof, check_index
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_tail_v19 import sample_workload, summarize_repeats
from scripts.retailrocket_session_knn_reinforcement_v18 import TelemetrySampler, summarize_telemetry
from scripts.retailrocket_session_knn_cost_rollup_v17 import normalize_repeat, METRICS
from scripts.retailrocket_session_knn_guards_v21 import (
    DiagnosticTimedStore, make_verifier, summarize_diagnostics, diagnostic_rows)


MODULE = 'scripts.run_retailrocket_session_knn_guards_v21'
BASE = 'reports/stage12/retailrocket_session_knn_'
INVENTORY = BASE+'v21_guards_inventory_20261106.json'
SPEC = BASE+'v21_guards_specification_20261106.json'
SPEC_SHA256 = '865d998fd629941ba0266f24c18322560269ae3f601e1c09d79ec4d1faea6f73'
ACCEPT = BASE+'v21_guards_acceptance_20261106.json'
REPORT = BASE+'v21_guards_cost_20261106.json'
PARENT = BASE+'v19_tail_cost_20261106.json'
METHODS = ('scripts/retailrocket_session_knn_guards_v21.py',
           'scripts/run_retailrocket_session_knn_guards_v21.py',
           'tests/test_retailrocket_session_knn_guards_v21.py')
SUITES = ('tests.test_retailrocket_session_knn_guards_v21',
          'tests.test_retailrocket_session_knn_diagnostics_v20',
          'tests.test_retailrocket_session_knn_diagnostics_sql_v20',
          'tests.test_retailrocket_session_knn_detailed_cost_v6',
          'tests.test_retailrocket_session_knn_reinforcement_v18')
MODES = ('R', 'D', 'D', 'R', 'R', 'D')
COVERAGE = {'covered_cells':55, 'uncovered_cells':0, 'unrepresented_population':0,
            'distinct_historically_verified_queries':232, 'distinct_comparable_queries':170,
            'target_cell_distinct_queries':{'1101/n5/v4':11}, 'target_tail_distinct_queries':6}
DONE = {'rounds':6, 'reference_rounds':3, 'diagnostic_rounds':3,
        'new_keys':0, 'reused_keys':7, 'queries_per_round':7, 'engineering_checks':42}


def schedule():
    seen = {'R':0, 'D':0}
    rows = []
    for index, mode in enumerate(MODES):
        rows.append({'round_index':index, 'mode':mode, 'mode_repeat_index':seen[mode],
                     'label':f'round_{index}'})
        seen[mode] += 1
    return rows


def preregistration():
    spec, inventory = read(ROOT/SPEC), read(ROOT/INVENTORY)
    if (describe(ROOT/SPEC)['sha256'] != SPEC_SHA256
            or spec['status'] != 'v21_guards_specification_frozen'
            or spec['inventory'] != describe(ROOT/INVENTORY)
            or inventory['status'] != 'v21_guards_inventory_verified'):
        raise ValueError('Expected the sealed V21 diagnostic specification and inventory')
    verify_bindings([spec['inventory'], *spec['evidence']])
    if inventory['coverage_before_and_after_reuse'] != COVERAGE:
        raise ValueError('Reusing V19 identities cannot change coverage or historical counts')
    if (spec['schedule'] != list(MODES) or spec['measurement']['fresh_rounds'] != 6
            or spec['measurement']['queries_per_round'] != 7
            or spec['measurement']['engineering_checks'] != 42
            or spec['measurement']['rounds_per_mode'] != 3
            or spec['measurement']['paired_schedule'] != [['R','D'],['D','R'],['R','D']]
            or spec['measurement']['window_seconds'] != 1800 or spec['measurement']['limits'] != LIMITS
            or spec['telemetry']['interval_seconds'] != .2 or spec['telemetry']['process_name_prefix'] != 'ollama'):
        raise ValueError('Only the preregistered RD/DR/RD six-round schedule is permitted')
    if (spec['selection']['source'] != inventory['frozen_selection']
            or spec['selection']['parent_report'] != inventory['parent_report']
            or spec['selection']['parent_binding'] != inventory['parent_binding']
            or spec['selection']['extracted_inputs'] != inventory['existing_extracted_inputs']
            or spec['selection']['identities'] != 7 or spec['selection']['new_keys'] != 0
            or spec['conditional_after_all_verified'] != dict(COVERAGE,new_distinct_queries=0,
                reused_queries=7,reused_anchor_queries=1,new_engineering_checks=42)):
        raise ValueError('The frozen reuse scope differs from the seven-query inventory')
    if (inventory['constraints']['new_selection'] is not False
            or inventory['constraints']['reuse_sealed_extraction'] is not True):
        raise ValueError('Diagnostics must reuse the already extracted fixed seven')
    return spec, inventory


@contextmanager
def _exclusive():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE/'knn-v21-guards.guard').open('a+b') as guard:
        if guard.seek(0, 2) == 0:
            guard.write(b'0'); guard.flush()
        _lock(guard)
        yield


def acceptance():
    with _exclusive():
        spec, _ = preregistration()
        if (ROOT/ACCEPT).exists():
            raise FileExistsError(ROOT/ACCEPT)
        methods = [describe(ROOT/name) for name in METHODS]
        gates = check_gates()
        folder = PRIVATE/('knn-v21-guards-tests-'+uuid4().hex)
        folder.mkdir()
        start = perf_counter()
        with (folder/'tests.log').open('x', encoding='utf-8') as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.testsRun or not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-7000:], file=sys.stderr)
            raise ValueError('V21 synthetic diagnostic acceptance failed')
        verify_bindings(methods)
        if check_gates() != gates or preregistration()[0] != spec:
            raise ValueError('Sources or scientific gates changed during synthetic acceptance')
        receipt = {'status':'v21_guards_tools_synthetic_accepted',
                   'created_utc':datetime.now(timezone.utc).isoformat(), 'tests_run':result.testsRun,
                   'seconds':perf_counter()-start, 'failures':0, 'errors':0, 'skipped':0,
                   'suites':list(SUITES), 'method_files':methods, 'environment':environment(),
                   'gates':gates, 'inventory':spec['inventory'], 'specification':describe(ROOT/SPEC),
                   'log':describe(folder/'tests.log'), 'actual_new_keys_selected':0,
                   'actual_new_query_verifications':0, 'reserved_test':'locked', 'T_plan':None}
        public_json(ROOT/ACCEPT, receipt, exclusive=True)
        print({'tests_run':result.testsRun, 'seconds':receipt['seconds']})


def _accepted(spec):
    accepted = read(ROOT/ACCEPT)
    if (accepted['status'] != 'v21_guards_tools_synthetic_accepted'
            or accepted['environment'] != environment()
            or len(accepted['method_files']) != len(METHODS)
            or {r['path'] for r in accepted['method_files']} != set(METHODS)
            or accepted['suites'] != list(SUITES) or type(accepted['tests_run']) is not int or accepted['tests_run'] <= 0
            or any(accepted[k] != 0 for k in ('failures','errors','skipped','actual_new_keys_selected','actual_new_query_verifications'))
            or accepted['gates'] != check_gates() or accepted['reserved_test'] != 'locked'
            or accepted['T_plan'] is not None or accepted['inventory'] != spec['inventory']
            or accepted['specification'] != describe(ROOT/SPEC)):
        raise ValueError('Unchanged V21 methods and specification must pass acceptance')
    verify_bindings([*accepted['method_files'], accepted['log']])
    return accepted


def _expected_request():
    spec, inventory = preregistration()
    accepted = _accepted(spec)
    if inventory['parent_report']['path'] != PARENT:
        raise ValueError('The public V19 parent report is fixed')
    verify_bindings([inventory['parent_report'], inventory['frozen_selection'], inventory['parent_binding']])
    parent = read(ROOT/PARENT)
    if (parent['status'] != 'v19_tail_6_new_1_anchor_measured_three_times'
            or parent['sources_reverified_before_after_and_post_exit'] is not True
            or any(parent['coverage'][k] != value for k, value in COVERAGE.items())):
        raise ValueError('The completed unchanged V19 result is required')
    anchors = [_record(parent['evidence'], '/'+name) for name in
               ('request.json','supervisor_completion.json','frozen_probes.json','v19_subset_binding.json')]
    verify_bindings(anchors)
    _normal_exit(read(ROOT/anchors[1]['path']))
    if anchors[2] != inventory['frozen_selection'] or anchors[3] != inventory['parent_binding']:
        raise ValueError('The V19 source selection or extraction binding changed')
    prior = read(ROOT/anchors[0]['path'])
    old_acceptance_record = _record(prior['sources'], '/retailrocket_session_knn_v19_tail_acceptance_20261106.json')
    verify_bindings([old_acceptance_record])
    old_acceptance = read(ROOT/old_acceptance_record['path'])
    if (old_acceptance['status'] != 'v19_tail_tools_synthetic_accepted'
            or old_acceptance['environment'] != environment()
            or any(old_acceptance[k] != 0 for k in ('failures','errors','skipped'))):
        raise ValueError('Inherited V19 methods require their original acceptance')
    verify_bindings([*old_acceptance['method_files'], old_acceptance['log']])
    if prior['metadata']['environment'] != environment():
        raise ValueError('Parent engineering environment differs')
    root = Path(parent['namespace'])
    meta = {'environment':environment(), 'schedule':schedule(), 'queries_per_round':7,
            'rounds':6, 'new_keys':0, 'reused_keys':7,
            'parent_report':inventory['parent_report'], 'probes':inventory['frozen_selection'],
            'subset_binding':inventory['parent_binding'],
            'selected_root':inventory['existing_extracted_inputs'],
            'model_root':prior['metadata']['independent_model_folder'],
            'parent_specification':parent['specification'],
            'reference_run':(root/'repeat_0/verified_subset/run.json').as_posix(),
            'reference_proof':(root/'repeat_0/proof.json').as_posix(),
            'source_index':(root/'source_index/manifest.json').as_posix(),
            'specification':describe(ROOT/SPEC), 'inventory':spec['inventory'], 'acceptance':describe(ROOT/ACCEPT)}
    if meta['selected_root'] != (root/'raw_selected_inputs').as_posix():
        raise ValueError('Only V19 existing extracted inputs may be used')
    records = {r['path']:r for r in prior['sources']}
    for record in [*inventory['inherited_sources'], *parent['evidence'], inventory['parent_report'], *inventory['inputs'], *spec['evidence'],
                   *accepted['method_files'], accepted['log'], *old_acceptance['method_files'], old_acceptance['log'],
                   spec['inventory'], describe(ROOT/SPEC), describe(ROOT/ACCEPT)]:
        if record['path'] in records and records[record['path']] != record:
            raise ValueError('An inherited sealed source definition changed: '+record['path'])
        records[record['path']] = record
    binding = read(ROOT/meta['subset_binding']['path'])
    if any(records.get(r['path']) != r for r in [*binding['sources'], binding['transport']]):
        raise ValueError('The reused extraction binding is outside the inherited source closure')
    for name in (meta['reference_run'], meta['reference_proof'], meta['source_index']):
        if name not in records:
            raise ValueError('Missing fixed V19 reference provenance')
    return meta, [records[k] for k in sorted(records)]


def _check_request_contract(request):
    _check_window(request)
    meta, sources = _expected_request()
    if request['metadata'] != meta or request['sources'] != sources:
        raise ValueError('Window differs from the accepted fixed-source diagnostic contract')
    return meta


def _fixed_inputs(request):
    meta = request['metadata']
    selection = read(ROOT/meta['probes']['path'])
    probes = selection['probes']
    if (len(probes) != 7 or len({p['key_sha256'] for p in probes}) != 7
            or [p['original_ordinal'] for p in probes] != sorted(p['original_ordinal'] for p in probes)
            or selection['new_keys'] != 6 or selection['anchor_keys'] != 1):
        raise ValueError('Only the original V19 fixed seven and their original order may be reused')
    # The old source labels describe V19 selection; V21 performs zero selection.
    binding = read(ROOT/meta['subset_binding']['path'])
    selected = ROOT/meta['selected_root']
    if binding['configuration'] != read(selected/'configuration.json') or binding['configuration']['fixed_validation']['queries'] != 7:
        raise ValueError('The seven-row extracted configuration changed')
    ordinals = read(selected/'ordinals.json')
    if (len(ordinals) != 7 or any((row['subset_ordinal'],row['original_ordinal'],row['key']) !=
            (i,p['original_ordinal'],p['key']) for i,(row,p) in enumerate(zip(ordinals,probes,strict=True)))):
        raise ValueError('The existing aligned inputs changed their identity or order')
    bound = {r['path']:r for r in request['sources']}
    if any(bound.get(r['path']) != r for r in [*binding['sources'],binding['transport']]):
        raise ValueError('Reused input source bindings were not verified in the window')
    check_index(read(ROOT/meta['source_index']),probes,166897,bound,ROOT)
    return selection, binding, selected, ordinals


def _physical_frames(checkpoint):
    for manifest in sorted((checkpoint/'chunks').glob('*.json')):
        record = read(manifest)
        payload = (checkpoint/record['payload']['path']).resolve()
        if not payload.is_relative_to(checkpoint.resolve()):
            raise ValueError('Checkpoint payload path escapes its sealed namespace')
        with payload.open('rb') as stream:
            yield from stream


def _reference(request, selection, binding):
    meta = request['metadata']
    run_path = ROOT/meta['reference_run']
    run = read(run_path)
    if run['binding'] != binding or run['expected_queries'] != 7:
        raise ValueError('Reference checkpoint does not use the sealed V19 subset')
    # Initial/post-exit source closure verification covers the model and inputs.
    store = DetailedTimedStore.open(run_path.parent,binding,source_root=ROOT,
                                    external_source_verifier=lambda:None)
    proof = ledger_proof(store,selection['probes'])
    if proof != read(ROOT/meta['reference_proof']) or proof['checkpoint_chain_checked'] is not True:
        raise ValueError('Original V19 seven-query ledger proof changed')
    rows = list(store.iter_records())
    raw = list(_physical_frames(run_path.parent))
    if len(rows) != 7 or len(raw) != 7:
        raise ValueError('Every V19 reference query must be present')
    parent = read(ROOT/meta['parent_report']['path'])
    return {'proof':proof,'rows':rows,'raw_frames':raw,
            'workload_by_cell':parent['repeats'][0]['workload_by_cell']}


def _compare_reference(store, selection, reference):
    proof = ledger_proof(store,selection['probes'])
    _same_payload(proof,reference['proof'])
    for current, original in zip(store.iter_records(),reference['rows'],strict=True):
        if (current['ordinal'] != original['ordinal'] or current['key'] != original['key']
                or current['payload'] != original['payload']):
            raise ValueError('A fixed query scientific payload changed from V19')
    count = 0
    for current, original in zip(_physical_frames(store.folder),reference['raw_frames'],strict=True):
        if current != original:
            raise ValueError('Physical scientific frame bytes differ from the original V19 ledger')
        count += 1
    if count != 7:
        raise ValueError('All seven physical frames must match, including the inherited anchor')
    return proof


def _round(folder, request, selection, binding, selected, ordinals, parent_spec, reference, item,
           *, model=None, database=None, watch=lambda:None):
    run = folder/item['label']; checkpoint = run/'verified_subset'
    index = item['mode_repeat_index']; mode = item['mode']
    if model is not None:
        store_type = DetailedTimedStore if mode == 'R' else DiagnosticTimedStore
        store = store_type.create(checkpoint,binding,request['deadline_utc'],request['budget_seconds'],
                    source_root=ROOT,expected_queries=7,required_stages=('reconstruction','queries'))
        sql = []
        verifier = make_verifier(mode,sql if mode == 'D' else None)
        with store.writer():
            store.seal_stage('reconstruction',{'kind':'reused_v5_reconstructed_model','fit_audit':model['fit_audit']})
            sampler = TelemetrySampler(interval_seconds=.2,process_name_prefix='ollama')
            sampler.start(index)
            span = {'round_index':item['round_index'],'mode':mode,'repeat_index':index,'completed':False,
                    'start_monotonic_seconds':perf_counter(),'start_utc':datetime.now(timezone.utc).isoformat()}
            try:
                measured = verifier(selected/'primary',{k:selected/k for k in PATHS},binding['configuration'],
                                    store,model,database,ordinals,watch)
                span['completed'] = True
            finally:
                span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
                try:
                    sampler.stop()
                finally:
                    write(run/'verifier_span.json',span)
                    write(run/'telemetry_records.json',dict(item,records=sampler.records))
            telemetry = summarize_telemetry(sampler.records,index,interval_seconds=.2)
            _check_telemetry_span(sampler.records,span,request,index)
        write(run/'measurements.json',measured)
        observations = {'append_events':store.append_events,'budget_events':store.budget_events}
        diagnostics = {'sql':sql,'append':store.append_diagnostics if mode == 'D' else []}
        write(run/'diagnostics.json',diagnostics)
        write(run/'telemetry_summary.json',telemetry)
    else:
        saved_run = read(checkpoint/'run.json')
        if (saved_run['binding'] != binding or saved_run['expected_queries'] != 7
                or any(saved_run[k] != request[k] for k in ('deadline_utc','budget_seconds'))):
            raise ValueError('A round changed the original deadline, source binding, or fixed size')
        store = DetailedTimedStore.open(checkpoint,binding,source_root=ROOT)
        measured,observations = read(run/'measurements.json'),read(run/'observations.json')
        store.commit_events = measured['chunk_commits']
        store.append_events = observations['append_events']; store.budget_events = observations['budget_events']
        diagnostics = read(run/'diagnostics.json')
        raw = read(run/'telemetry_records.json')
        if any(raw[k] != value for k,value in item.items()):
            raise ValueError('Telemetry changed its global round or within-mode repeat identity')
        telemetry = summarize_telemetry(raw['records'],index,interval_seconds=.2)
        span = read(run/'verifier_span.json')
        if span['round_index'] != item['round_index'] or span['mode'] != mode:
            raise ValueError('The saved verifier span changed its scheduled mode')
        _check_telemetry_span(raw['records'],span,request,index)
        if telemetry != read(run/'telemetry_summary.json'):
            raise ValueError('Saved resource summary differs from raw interval observations')
    detail = store.detailed_cost_summary(measured)
    proof = _compare_reference(store,selection,reference)
    if proof['actual_committed_bytes'] != sum(row['frame_bytes'] for row in detail['rows']):
        raise ValueError('Observed frame lengths differ from the physical ledger')
    predictions = [row['payload']['expected']['predictions']['K1'] for row in store.iter_records()]
    workload = sample_workload(selection['probes'],measured,predictions,parent_spec)
    if workload != reference['workload_by_cell']:
        raise ValueError('A fixed query logical workload differs from the original V19 result')
    if mode == 'R':
        if diagnostics != {'sql':[],'append':[]}:
            raise ValueError('Reference mode must not enable diagnostic proxies')
        diagnostic_summary = {'enabled':False}
        diagnostic_detail = []
    else:
        diagnostic_summary = summarize_diagnostics(measured,dict(observations,detail=detail),diagnostics)
        diagnostic_detail = diagnostic_rows(measured,dict(observations,detail=detail),diagnostics)
    if model is None:
        if (detail != observations['detail'] or proof != read(run/'proof.json')
                or workload != read(run/'workload.json')
                or diagnostic_detail != read(run/'diagnostic_rows.json')
                or diagnostic_summary != read(run/'diagnostic_summary.json')):
            raise ValueError('Post-exit timing, diagnostic, workload or ledger evidence differs')
    else:
        observations['detail'] = detail
        write(run/'observations.json',observations); write(run/'proof.json',proof)
        write(run/'workload.json',workload); write(run/'diagnostic_summary.json',diagnostic_summary)
        write(run/'diagnostic_rows.json',diagnostic_detail)
    return {'measured':measured,'observations':observations,'proof':proof,'workload_by_cell':workload,
            'telemetry':telemetry,'diagnostics':diagnostic_summary,'diagnostic_rows':diagnostic_detail,'span':span,**item}


def _check_round_spans(folder, request):
    previous_end = None
    for item in schedule():
        run = folder/item['label']
        raw = read(run/'telemetry_records.json'); span = read(run/'verifier_span.json')
        if any(raw[k] != value for k,value in item.items()) or span['round_index'] != item['round_index'] or span['mode'] != item['mode']:
            raise ValueError('The six resource segments must follow the frozen RD/DR/RD order')
        records = raw['records']
        _check_telemetry_span(records,span,request,item['mode_repeat_index'])
        if previous_end is not None and records[0]['monotonic_seconds'] < previous_end:
            raise ValueError('Diagnostic/reference verifier entries or their samplers overlap')
        previous_end = records[-1]['monotonic_seconds']+records[-1]['collector_seconds']


def _completed(folder):
    receipt = read(folder/'supervisor_completion.json'); _normal_exit(receipt)
    tracked = read(folder/'tracked_process_identities.json')
    if tracked['live_after_cleanup'] != 0:
        raise ValueError('Tracked worker cleanup is incomplete')
    for identity in tracked['identities']:
        try:
            process = psutil.Process(identity['pid'])
            if process.is_running() and process.create_time() == identity['create_time']:
                raise ValueError('A recorded diagnostic process is still alive')
        except psutil.NoSuchProcess:
            pass
    phases = {p.name.removesuffix('_receipt.json'):read(p) for p in folder.glob('*_receipt.json')}
    required = {'initial_frozen_source_hash','bind_existing_seven','final_frozen_source_hash',
                *(item['label'] for item in schedule())}
    if set(phases) != required or any(not value['completed'] for value in phases.values()) or read(folder/'done.json') != DONE:
        raise ValueError('Every one of the six fixed-seven observations must complete')
    return receipt,phases


def _execution_seal(meta):
    return {'parent_report':meta['parent_report'],'frozen_selection':meta['probes'],
            'existing_subset_binding':meta['subset_binding'],'specification':meta['specification'],
            'inventory':meta['inventory'],'schedule':schedule(),'new_keys':0,'reused_keys':7,
            'selection_performed':False,'extraction_performed':False}


def _descriptive_mode_summary(selection, rounds, parent_spec, mode):
    selected = [row for row in rounds if row['mode'] == mode]
    if len(selected) != 3 or [r['mode_repeat_index'] for r in selected] != [0,1,2]:
        raise ValueError('Both modes require all three retained observations')
    result = summarize_repeats(selection,selected,parent_spec)

    def relabel(value):
        if isinstance(value,dict):
            changed = {}
            for key,child in value.items():
                if key in ('weighted_scenarios_seconds','scenario_inputs_seconds'):
                    raise ValueError('Population runtime projections are forbidden for fixed-case diagnostics')
                new_key = 'source_tail_queries' if key == 'new_queries' else 'source_anchor_queries' if key == 'anchor_queries' else key
                if key == 'cohort':
                    changed[key] = 'V21_'+mode
                elif key == 'roles':
                    changed[key] = {('source_tail' if label == 'new' else 'source_anchor'):relabel(item) for label,item in child.items()}
                elif key == 'sample_role':
                    changed['source_sample_role'] = 'source_tail' if child == 'new' else 'source_anchor'
                else:
                    changed[new_key] = relabel(child)
            return changed
        if isinstance(value,list):
            return [relabel(item) for item in value]
        return value

    result = relabel(result)
    result['scope'].update(new_keys=0,reused_keys=7,source_tail_keys=6,source_anchor_keys=1,
                          engineering_checks=21,**COVERAGE)
    result['scope'].pop('anchor_keys',None)
    result['interpretation']['tail_reinforcement'] = 'No reinforcement selection occurs in V21. All seven V19 identities are reused; source tail and source anchor labels describe their earlier provenance only.'
    result['interpretation']['diagnostic_mode'] = 'Reference R' if mode == 'R' else 'Observational diagnostics D, including instrumentation overhead'
    return result


def _mode_summaries(selection, rounds, parent_spec):
    return {mode:_descriptive_mode_summary(selection,rounds,parent_spec,mode) for mode in ('R','D')}


def _normalized_rounds(selection, rounds):
    if len(rounds) != 6 or any(any(row[k] != value for k,value in item.items())
                              for row,item in zip(rounds,schedule(),strict=True)):
        raise ValueError('All six cost rows must retain their frozen global and within-mode order')
    probes = selection['probes']; cells = {p['key_sha256']:p['cell'] for p in probes}
    result = {}
    for row in rounds:
        normalized = normalize_repeat('V21_'+row['mode'],row['mode_repeat_index'],probes,
                        row['measured'],row['observations'],cells)['rows']
        for index,query in enumerate(normalized):
            query['seconds']['positive_overlap_inclusive'] = row['measured']['queries'][index]['rank_stages_seconds']['sql_positive_overlaps']
        result[row['round_index']] = normalized
    return result


def _stats(values):
    values = list(values)
    return {'count':len(values),'minimum':min(values),'median':statistics.median(values),
            'maximum':max(values),'range':max(values)-min(values),'mean':math.fsum(values)/len(values)}


def _same_case_pair(index, observations, normalized, metric):
    fastest = min(observations,key=lambda row:(normalized[row['round_index']][index]['seconds'][metric],row['round_index']))
    slowest = max(observations,key=lambda row:(normalized[row['round_index']][index]['seconds'][metric],-row['round_index']))
    a,b = (normalized[row['round_index']][index]['seconds'] for row in (fastest,slowest))
    delta = {name:b[name]-a[name] for name in (*METRICS,'positive_overlap_inclusive')}
    aq,bq = (row['measured']['queries'][index] for row in (fastest,slowest))
    aa,ba = (row['observations']['detail']['rows'][index]['append_exclusive_seconds'] for row in (fastest,slowest))
    if set(aa) != set(ba) or set(aq['rank_stages_seconds']) != set(bq['rank_stages_seconds']):
        raise ValueError('Fixed-case timing partitions changed between retained observations')
    append = {name:ba[name]-aa[name] for name in aa}
    if (not math.isclose(delta['core'],delta['verification']+delta['append_without_commit_or_budget'],abs_tol=1e-12)
            or not math.isclose(delta['append_without_commit_or_budget'],
                math.fsum(value for name,value in append.items() if name not in ('budget_publication','chunk_commit')),abs_tol=1e-10)):
        raise ValueError('Same-observation core/append differences do not conserve their nested costs')
    result = {'selected_by':metric,'fast_round_index':fastest['round_index'],'slow_round_index':slowest['round_index'],
              'fast_mode_repeat_index':fastest['mode_repeat_index'],'slow_mode_repeat_index':slowest['mode_repeat_index'],
              'fast_seconds':a[metric],'slow_seconds':b[metric],'delta_seconds':delta,
              'rank_stage_delta_seconds':{name:bq['rank_stages_seconds'][name]-aq['rank_stages_seconds'][name]
                                          for name in aq['rank_stages_seconds']},
              'append_exclusive_delta_seconds':append,'diagnostic_component_deltas':None}
    if fastest['mode'] == 'D':
        ad,bd = (row['diagnostic_rows'][index] for row in (fastest,slowest))
        clocks = ('wall_seconds','thread_cpu_seconds','wall_minus_thread_cpu_seconds')
        def span(left,right):
            return {clock:right[clock]-left[clock] for clock in clocks}
        grouped = ('sql_parts','rank_phases','append_phases','append_budget_check_parts','guard_check_parts','writer_check_parts')
        diagnostic = {name:{part:span(ad[name][part],bd[name][part]) for part in ad[name]} for name in grouped}
        for name in ('sql_positive_overlap_total','terminal_fetch_included','append_total',
                     'append_wrapper_total','append_wrapper_observer_other','all_append_budget_checks'):
            diagnostic[name] = span(ad[name],bd[name])
        for name in ('append_original_outer_wall_seconds','append_outer_unobserved_wall_seconds',
                     'original_direct_budget_seconds'):
            diagnostic[name+'_delta'] = bd[name]-ad[name]
        diagnostic['append_outer_unobserved_thread_cpu_seconds_delta'] = None
        diagnostic['direct_budget_publications_delta'] = bd['direct_budget_publications']-ad['direct_budget_publications']
        diagnostic['nested_commit_budget_publications_delta'] = bd['nested_commit_budget_publications']-ad['nested_commit_budget_publications']
        if not math.isclose(math.fsum(part['wall_seconds'] for part in diagnostic['sql_parts'].values()),
                            delta['positive_overlap_inclusive'],abs_tol=1e-10):
            raise ValueError('Same-case positive-overlap subparts differ from the selected inclusive phase pair')
        if (not math.isclose(diagnostic['append_total']['wall_seconds']+
                diagnostic['append_wrapper_observer_other']['wall_seconds']+
                diagnostic['append_outer_unobserved_wall_seconds_delta'],delta['checkpoint_append'],abs_tol=1e-10)
                or not math.isclose(diagnostic['original_direct_budget_seconds_delta'],delta['direct_budget'],abs_tol=1e-10)):
            raise ValueError('Same-case append diagnostic differences do not conserve the original outer timer')
        result['diagnostic_component_deltas'] = diagnostic
    return result


def _case_diagnostic_stats(index, observations):
    """Describe the same fixed query's three observed wall/CPU decompositions."""
    rows = [row['diagnostic_rows'][index] for row in observations]
    clocks = ('wall_seconds','thread_cpu_seconds','wall_minus_thread_cpu_seconds')
    def spans(values):
        return {clock:_stats(value[clock] for value in values) for clock in clocks}
    result = {name:{part:spans([row[name][part] for row in rows]) for part in rows[0][name]}
              for name in ('sql_parts','rank_phases','append_phases','append_budget_check_parts','guard_check_parts','writer_check_parts')}
    for name in ('sql_positive_overlap_total','terminal_fetch_included','append_total',
                 'append_wrapper_total','append_wrapper_observer_other','all_append_budget_checks'):
        result[name] = spans([row[name] for row in rows])
    for name in ('append_original_outer_wall_seconds','append_outer_unobserved_wall_seconds',
                 'original_direct_budget_seconds','direct_budget_publications','nested_commit_budget_publications'):
        result[name] = _stats(row[name] for row in rows)
    result['append_outer_unobserved_thread_cpu_seconds'] = None
    return result


def _fixed_case_summaries(selection, rounds):
    normalized = _normalized_rounds(selection,rounds)
    cases = {}
    for index,probe in enumerate(selection['probes']):
        case = probe['selection_segment']+'/'+probe['selection_reason']
        if case in cases:
            raise ValueError('The seven frozen structural case labels must be unique')
        modes = {}
        for mode in ('R','D'):
            observations = [row for row in rounds if row['mode'] == mode]
            modes[mode] = {'observations':3,
                'seconds':{name:_stats(normalized[row['round_index']][index]['seconds'][name] for row in observations)
                           for name in (*METRICS,'positive_overlap_inclusive')},
                'diagnostics':_case_diagnostic_stats(index,observations) if mode == 'D' else None,
                'same_query_fast_slow':{name:_same_case_pair(index,observations,normalized,name)
                    for name in ('core','positive_overlap_inclusive','append_without_commit_or_budget')}}
        cases[case] = {'source_role':'source_tail' if probe['sample_role'] == 'new' else 'source_anchor',
                      'source_segment':probe['selection_segment'],'source_selection_reason':probe['selection_reason'],
                      'eligible_neighbors':probe['eligible_neighbors'],'by_mode':modes}
    if len(cases) != 7:
        raise ValueError('Every frozen case must have separate reference and diagnostic summaries')
    return {'cases':cases,'interpretation':'Each structural case identifies one previously exposed V19 query without publishing its key or ordinal. Every component difference uses the exact same fastest/slowest observations selected by the stated metric; independently chosen maxima are never added.'}


def _paired_observer_differences(selection, rounds):
    probes = selection['probes']
    normalized = _normalized_rounds(selection,rounds)
    pairs = []
    for pair_index in range(3):
        pair = rounds[2*pair_index:2*pair_index+2]
        reference = next(row for row in pair if row['mode'] == 'R')
        diagnostic = next(row for row in pair if row['mode'] == 'D')
        groups = {'all_fixed_cases':list(range(7)),
                  **{name:[i for i,p in enumerate(probes) if p['selection_segment'] == name]
                     for name in sorted({p['selection_segment'] for p in probes})}}
        summaries = {}
        for name,indices in groups.items():
            metrics = {}
            for metric in (*METRICS,'positive_overlap_inclusive'):
                r = [normalized[reference['round_index']][i]['seconds'][metric] for i in indices]
                d = [normalized[diagnostic['round_index']][i]['seconds'][metric] for i in indices]
                delta = [b-a for a,b in zip(r,d,strict=True)]
                metrics[metric] = {'R_sum_seconds':math.fsum(r),'D_sum_seconds':math.fsum(d),
                    'D_minus_R_sum_seconds':math.fsum(delta),'same_identity_delta_minimum_seconds':min(delta),
                    'same_identity_delta_median_seconds':statistics.median(delta),'same_identity_delta_maximum_seconds':max(delta)}
            summaries[name] = {'fixed_identities':len(indices),'seconds':metrics}
        pairs.append({'pair_index':pair_index,'order':''.join(r['mode'] for r in pair),
            'reference_round':reference['round_index'],'diagnostic_round':diagnostic['round_index'],
            'groups':summaries,
            'D_minus_R_verifier_span_seconds':(diagnostic['span']['end_monotonic_seconds']-diagnostic['span']['start_monotonic_seconds'])
                -(reference['span']['end_monotonic_seconds']-reference['span']['start_monotonic_seconds'])})
    return {'pairs':pairs,'interpretation':'Adjacent same-identity diagnostic-minus-reference observations include instrumentation, system load and temporal variation. They are not an optimization speedup or an isolated causal observer-overhead estimate.'}


def _public_workload(value):
    if isinstance(value,dict):
        result = {}
        for name,item in value.items():
            if name == 'by_role':
                result['by_source_role'] = {('source_tail' if role == 'new' else 'source_anchor'):_public_workload(group)
                                            for role,group in item.items()}
            else:
                name = 'source_tail_queries' if name == 'new_queries' else 'source_anchor_queries' if name == 'anchor_queries' else name
                result[name] = _public_workload(item)
        return result
    if isinstance(value,list):
        return [_public_workload(item) for item in value]
    return value


def worker(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v21-guards-'):
        raise ValueError('V21 worker requires its own new private namespace')
    request = read(folder/'request.json'); watch = ThrottledWatch(folder,request['deadline_utc'])
    try:
        with _phase(folder,'initial_frozen_source_hash',watch):
            meta = _check_request_contract(request)
            verify_bindings(request['sources'],watch)
            check_gates()
        with _phase(folder,'bind_existing_seven',watch):
            selection,binding,selected,ordinals = _fixed_inputs(request)
            reference = _reference(request,selection,binding)
            write(folder/'execution_seal.json',dict(_execution_seal(meta),utc=datetime.now(timezone.utc).isoformat()))
        parent_spec = read(ROOT/meta['parent_specification']['path'])
        model_root = ROOT/meta['model_root']; database = model_root/'independent.sqlite'; _check_db(database)
        model = read(model_root/'reconstruction.json')['receipt']
        rounds = []
        for item in schedule():
            with _phase(folder,item['label'],watch):
                rounds.append(_round(folder,request,selection,binding,selected,ordinals,parent_spec,reference,item,
                                     model=model,database=database,watch=watch))
                _check_db(database)
        _check_round_spans(folder,request)
        if any(row['workload_by_cell'] != rounds[0]['workload_by_cell'] for row in rounds):
            raise ValueError('Reference and diagnostic modes changed logical query work')
        result = {'by_mode':_mode_summaries(selection,rounds,parent_spec),
                  'fixed_cases':_fixed_case_summaries(selection,rounds),
                  'paired_observations':_paired_observer_differences(selection,rounds)}
        write(folder/'cost_summary.json',result)
        with _phase(folder,'final_frozen_source_hash',watch):
            verify_bindings(request['sources'],watch); _check_db(database); check_gates()
        write(folder/'done.json',DONE)
    except BaseException as error:
        write(folder/'failure.json',{'error_type':type(error).__name__,'reserved_test':'locked','full_readback_started':False})
        raise


def _publish(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v21-guards-'):
        raise ValueError('V21 publication requires its own private namespace')
    namespace = folder.relative_to(ROOT).as_posix()
    existing = read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    if existing:
        if existing['namespace'] != namespace:
            raise FileExistsError('A different V21 window already owns the report')
        verify_bindings(existing['evidence'])
    completion,phases = _completed(folder)
    request = read(folder/'request.json'); meta = _check_request_contract(request)
    _check_window(request,completion); verify_bindings(request['sources'])
    selection,binding,selected,ordinals = _fixed_inputs(request)
    reference = _reference(request,selection,binding)
    seal = read(folder/'execution_seal.json')
    if not seal.get('utc') or any(seal.get(k) != v for k,v in _execution_seal(meta).items()):
        raise ValueError('The unchanged-selection execution seal differs')
    parent_spec = read(ROOT/meta['parent_specification']['path'])
    rounds = [_round(folder,request,selection,binding,selected,ordinals,parent_spec,reference,item) for item in schedule()]
    _check_round_spans(folder,request)
    if any(row['workload_by_cell'] != rounds[0]['workload_by_cell'] for row in rounds):
        raise ValueError('Frozen reference and diagnostic logical workloads differ')
    result = {'by_mode':_mode_summaries(selection,rounds,parent_spec),
              'fixed_cases':_fixed_case_summaries(selection,rounds),
              'paired_observations':_paired_observer_differences(selection,rounds)}
    if result != read(folder/'cost_summary.json'):
        raise ValueError('Post-exit reference/diagnostic costs differ from saved raw observations')
    verify_bindings(request['sources']); gates = check_gates()
    if gates != read(ROOT/ACCEPT)['gates']:
        raise ValueError('The six scientific gates changed')
    audit = {'same_v19_seven_and_order':True,'selection_or_extraction_performed':False,
             'all_42_full_payloads_and_physical_frames_match_v19':True,'all_six_rounds_recomputed':True,
             'diagnostic_events_recomputed':True,'six_telemetry_segments_recomputed_and_nonoverlapping':True,
             'original_deadline_verified':True,'sources_reverified_after_exit':True,'tracked_processes_stopped':True}
    if (folder/'post_exit_audit.json').exists():
        if read(folder/'post_exit_audit.json') != audit:
            raise ValueError('Existing immutable post-exit audit differs')
    else:
        write(folder/'post_exit_audit.json',audit)
    public_rounds = []
    for row in rounds:
        measured = row['measured']
        public_rounds.append({**{k:row[k] for k in ('round_index','mode','mode_repeat_index','label')},
            'proof':row['proof'],'workload_by_cell':_public_workload(row['workload_by_cell']),'telemetry':row['telemetry'],
            'diagnostics':row['diagnostics'],'setup_seconds':measured['setup_seconds'],
            'tail_flush_and_eof_seal_seconds':measured['tail_flush_and_eof_seal_seconds'],
            'all_chunk_commit_seconds':math.fsum(e['seconds'] for e in measured['chunk_commits']),
            'verifier_span_seconds':row['span']['end_monotonic_seconds']-row['span']['start_monotonic_seconds']})
    report = {'status':'v21_same_seven_reference_diagnostics_six_rounds_measured',
              'previous_diagnostics':read(ROOT/INVENTORY)['previous_diagnostic_report'],
        'created_utc':existing['created_utc'] if existing else datetime.now(timezone.utc).isoformat(),
        'namespace':namespace,'environment':environment(),'supervisor':completion,'phases':phases,
        'specification':meta['specification'],'inventory':meta['inventory'],'acceptance':meta['acceptance'],
        'parent_report':meta['parent_report'],'frozen_selection':meta['probes'],'parent_binding':meta['subset_binding'],
        'schedule':schedule(),'sources_bound':len(request['sources']),'sources_reverified_before_after_and_post_exit':True,
        'reference_ledger_proof':reference['proof'],'rounds':public_rounds,'summary':result,
        'coverage_before_and_after_reuse':COVERAGE,
        'scope':{'new_keys':0,'reused_v19_keys':7,'fresh_rounds':6,'new_engineering_verifications':42,
                 'new_primary_fits':0,'new_primary_validation_runs':0,'new_primary_bootstrap':0,
                 'SQL_candidate_runs':0,'new_selection_performed':False,'new_extraction_performed':False,
                 'full_validation_complete':False,'full_readback_started':False,'reserved_test':'locked'},
        'interpretation':{'reference':'R keeps the frozen V4 verifier, SQL and V6 detailed checkpoint store.',
            'diagnostic':'D observes the same workload through invocation-local proxies. Original scientific output, original timers and checkpoint protocol remain fixed; diagnostic instrumentation adds observer overhead.',
            'append_scope':'Fine diagnostic observations cover active per-query append, including its budget check. Setup and tail retain original V6 accounting; do not extend this diagnostic coverage to unobserved paths.',
            'clocks':'Wall time and current-thread CPU time use separate monotonic clocks. Thread CPU excludes the concurrent telemetry thread. Wall minus thread CPU is a signed clock difference and may be negative because of accounting resolution; it is not measured waiting time or an identified disk, scheduler or Ollama cause.',
            'telemetry':'One continuous inherited sampler covers each full verifier entry. Six sequential segments use within-mode repeat indices 0..2 and separate global round indices 0..5. Background observer overhead remains in the environment and is not added to primary timers.',
            'inference':'All 42 observations reuse seven known validation identities. No population runtime projection, speedup claim, causal attribution or coverage gain follows.'},
        'gates':gates,'T_plan':None,'evidence':[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]}
    if existing is None:
        public_json(ROOT/REPORT,report,exclusive=True)
    elif existing != report:
        raise ValueError('Re-audit differs from the immutable V21 report')
    print({'report':REPORT,'namespace':namespace,'seconds':completion['seconds'],'scope':report['scope']})
    return report


def publish(folder):
    with _exclusive():
        return _publish(Path(folder))


def supervise():
    with _exclusive():
        if (ROOT/REPORT).exists():
            raise FileExistsError('Use --publish to re-audit the existing V21 result')
        meta,sources = _expected_request()
        for request in PRIVATE.glob('knn-v21-guards-*/request.json'):
            raise FileExistsError('Review the existing V21 execution instead of opening another: '+str(request.parent))
        folder = PRIVATE/('knn-v21-guards-'+uuid4().hex)
        print('V21 diagnostic window: '+folder.relative_to(ROOT).as_posix(),flush=True)
        receipt = run_window(folder,[sys.executable,'-B','-m',MODULE,'--worker',str(folder)],sources,'joint_tail',
                             metadata=meta,budget_seconds=1800,limits=LIMITS)
        _normal_exit(receipt)
        return _publish(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance',action='store_true'); modes.add_argument('--measure',action='store_true')
    modes.add_argument('--publish',type=Path); modes.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.acceptance:
        acceptance()
    elif args.measure:
        supervise()
    elif args.publish:
        publish(args.publish)
    else:
        worker(args.worker)
