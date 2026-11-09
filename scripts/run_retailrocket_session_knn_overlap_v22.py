"""One sealed overlap SQL candidate on the unchanged original fixed 48.

No selection, refit, database modification, full validation, or reserved test.
The original V7 implementation and paired decision are immutable dependencies.
"""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from statistics import median
import sqlite3
import sys
from time import perf_counter
import unittest
from uuid import uuid4

import psutil

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, check_gates, describe, environment, read, verify_bindings, write)
from scripts.retailrocket_session_knn_checkpoint_v2 import _lock
from scripts.retailrocket_session_knn_cost_window_v5 import LIMITS, run_window
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell
from scripts.retailrocket_session_knn_checks_v4 import clear_caches
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json, _check_db
from scripts.run_retailrocket_session_knn_vote_v7 import (
    METHODS as V7_METHODS, _costs, schedule, paired_decision)
from scripts.retailrocket_session_knn_overlap_v22 import make_verifier
from scripts.retailrocket_session_knn_reinforcement_v18 import TelemetrySampler, summarize_telemetry
from scripts.run_retailrocket_session_knn_tail_v19 import _check_telemetry_span
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames


MODULE = 'scripts.run_retailrocket_session_knn_overlap_v22'
BASE = 'reports/stage12/retailrocket_session_knn_'
ANCHOR = BASE+'v7_vote_compare48_20261105.json'
GAP = BASE+'v7_gap_cost_20261105.json'
V6 = BASE+'v6_refined_cost_20261103.json'
SPEC = BASE+'v22_overlap_specification_20261109.json'
SPEC_SHA256 = 'cc32eb0469619db62c2a5092808f6c149f32672b517702bc59d4e695c9f70f22'
ACCEPT = BASE+'v22_overlap_acceptance_20261109.json'
OUTPUT = {stage: BASE+'v22_overlap_'+stage+'_20261109.json' for stage in ('compare48',)}
SUITES = ('tests.test_retailrocket_session_knn_overlap_v22',
          'tests.test_retailrocket_session_knn_overlap_candidate_v21',
          'tests.test_retailrocket_session_knn_vote_comparison_v7',
          'tests.test_retailrocket_session_knn_reinforcement_v18')
METHODS = (*V7_METHODS, 'scripts/retailrocket_session_knn_overlap_v22.py',
           'scripts/run_retailrocket_session_knn_overlap_v22.py',
           'tests/test_retailrocket_session_knn_overlap_v22.py',
           'scripts/retailrocket_session_knn_reinforcement_v18.py',
           'scripts/run_retailrocket_session_knn_tail_v19.py',
           'scripts/run_retailrocket_session_knn_guards_v21.py',
           *(name.replace('.', '/')+'.py' for name in SUITES))
METHODS = tuple(dict.fromkeys(METHODS))
PROTOCOL = {'pairs': 6, 'warmup_runs': 2, 'minimum_wins': 5,
            'minimum_median_saving_percent': 5, 'both_order_medians_positive': True,
            'entry_median_must_not_regress': True, 'budget_seconds': 1800}


def preregistration():
    spec = read(ROOT/SPEC)
    if (describe(ROOT/SPEC)['sha256'] != SPEC_SHA256
            or spec['status'] != 'v22_overlap_specification_frozen'
            or spec['candidate'] != 'group_before_size_join' or spec['protocol'] != PROTOCOL
            or spec['schedule'] != [dict(label=l,mode=m) for l,m in schedule('compare48',spec['candidate'])]
            or spec['scope'] != dict(stage='compare48',distinct_queries=48,runs=14,
                warmup_query_checks=96,paired_query_checks=576,total_query_checks=672,
                new_keys=0,compare34_enabled=False,full_validation_complete=False,reserved_test='locked')
            or spec['telemetry']['interval_seconds'] != .2):
        raise ValueError('Expected the sealed V22 fixed48 candidate, schedule and protocol')
    verify_bindings([spec['inventory'], spec['candidate_method']])
    inventory = read(ROOT/spec['inventory']['path'])
    if inventory['status'] != 'v22_overlap_fixed48_inventory_verified' or inventory['new_keys'] != 0:
        raise ValueError('Expected unchanged fixed48 inventory')
    return spec

@contextmanager
def _exclusive():
    PRIVATE.mkdir(parents=True,exist_ok=True)
    with (PRIVATE/'knn-v22-overlap.guard').open('a+b') as guard:
        if guard.seek(0,2)==0:
            guard.write(b'0');guard.flush()
        _lock(guard)
        yield


def _run(folder,request,label,mode,inputs,watch):
    selected,config,binding,model,database,probes,ordinals,reference = inputs
    run = folder/label
    start = perf_counter()
    store = DetailedTimedStore.create(run/'verified_subset',binding,request['deadline_utc'],
        request['budget_seconds'],source_root=ROOT,expected_queries=48,
        required_stages=('reconstruction','queries'))
    verifier = make_verifier(mode)
    with store.writer():
        store.seal_stage('reconstruction',{'kind':'reused_v5_reconstructed_model','fit_audit':model['fit_audit']})
        measured = verifier(selected/'primary',{k:selected/k for k in ('dataset','P0','C1','D1')},
            config,store,model,database,ordinals,watch)
    store.detailed_cost_summary(measured)
    proof = ledger_proof(store,probes)
    _same_payload(proof,reference)
    _costs(measured,probes)
    write(run/'measured.json',measured)
    write(run/'observations.json',{'budget':store.budget_events,'append':store.append_events})
    write(run/'profile.json',[])
    write(run/'proof.json',proof)
    write(run/'entry.json',{'label':label,'mode':mode,'seconds':perf_counter()-start})


def _observed_run(folder,request,label,mode,inputs,watch):
    sampler = TelemetrySampler(interval_seconds=.2,process_name_prefix='ollama')
    sampler.start(0)
    span = dict(label=label,mode=mode,repeat_index=0,completed=False,
        start_monotonic_seconds=perf_counter(),start_utc=datetime.now(timezone.utc).isoformat())
    try:
        _run(folder,request,label,mode,inputs,watch)
        span['completed'] = True
    finally:
        span.update(end_monotonic_seconds=perf_counter(),end_utc=datetime.now(timezone.utc).isoformat())
        try:
            sampler.stop()
        finally:
            write(folder/label/'entry_span.json',span)
            write(folder/label/'telemetry_records.json',dict(label=label,mode=mode,records=sampler.records))
    load,_ = _load_check(folder/label,request,label,mode,None)
    write(folder/label/'telemetry_summary.json',load)


def _load_check(root,request,label,mode,previous_end):
    raw,span = read(root/'telemetry_records.json'),read(root/'entry_span.json')
    if any(obj.get('label')!=label or obj.get('mode')!=mode for obj in (raw,span)):
        raise ValueError('Telemetry changed its unique run identity or mode')
    records = raw['records']
    _check_telemetry_span(records,span,request,0)
    load = summarize_telemetry(records,0,interval_seconds=.2)
    if previous_end is not None and records[0]['monotonic_seconds']<previous_end:
        raise ValueError('Sequential run telemetry overlaps')
    if (root/'telemetry_summary.json').exists() and read(root/'telemetry_summary.json')!=load:
        raise ValueError('Saved telemetry summary differs from raw observations')
    return load,records[-1]['monotonic_seconds']+records[-1]['collector_seconds']


def _validate_stage(stage, prior=None):
    if stage != 'compare48':
        raise ValueError('Only the sealed original fixed48 is authorized in V22')

def _check_window(request, completion=None):
    start = datetime.fromisoformat(request['created_utc'])
    deadline = datetime.fromisoformat(request['deadline_utc'])
    if (start.utcoffset() is None or deadline.utcoffset() is None
            or request['budget_seconds'] != 1800 or deadline-start != timedelta(seconds=1800)
            or request['limits'] != LIMITS or request['operation'] != 'joint_tail'
            or request['full_readback_enabled'] is not False or request['reserved_test'] != 'locked'
            or request['T_plan'] is not None):
        raise ValueError('Changed V22 absolute deadline, resource limits, or permitted scope')
    if completion is not None:
        _normal_exit(completion)
        actual_exit = datetime.fromisoformat(completion['actual_exit_observed_utc'])
        if (actual_exit.utcoffset() is None or completion['operation'] != request['operation']
                or completion['full_readback_started'] is not False
                or completion['T_plan'] is not None or completion['reserved_test'] != 'locked'
                or not start <= actual_exit <= deadline
                or not 0 <= completion['seconds'] <= request['budget_seconds']
                or not 0 <= completion['peak_sampled_tree_and_supervisor_rss_bytes'] <= LIMITS['rss_bytes']
                or not 0 <= completion['peak_sampled_execution_bytes'] <= LIMITS['execution_bytes']):
            raise ValueError('Worker exit or measured resource peak violated the original window')


def resource_snapshot():
    """Nonblocking system context only; no service queries or inference calls."""
    memory = psutil.virtual_memory()
    return {'utc': datetime.now(timezone.utc).isoformat(),
            'cpu_percent_nonblocking': psutil.cpu_percent(interval=None),
            'memory_total_bytes': memory.total, 'memory_available_bytes': memory.available,
            'memory_used_bytes': memory.used, 'memory_percent': memory.percent,
            'observer_process_rss_bytes': psutil.Process().memory_info().rss}


def _validate_snapshot(value):
    if set(value) != {'utc', 'cpu_percent_nonblocking', 'memory_total_bytes',
                      'memory_available_bytes', 'memory_used_bytes', 'memory_percent',
                      'observer_process_rss_bytes'}:
        raise ValueError('Changed resource snapshot fields')
    if datetime.fromisoformat(value['utc']).utcoffset() is None:
        raise ValueError('Resource snapshot requires an absolute UTC-offset time')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
           for k, v in value.items() if k != 'utc'):
        raise ValueError('Invalid resource snapshot')
    if (max(value['cpu_percent_nonblocking'], value['memory_percent']) > 100
            or max(value['memory_available_bytes'], value['memory_used_bytes']) > value['memory_total_bytes']):
        raise ValueError('Invalid system resource range')


def _check_timers(measured):
    names = ('verification_seconds', 'rank_seconds', 'checkpoint_append_seconds',
             'append_without_commit_seconds', 'chunk_commit_seconds', 'seconds')
    values = [measured[k] for k in ('setup_seconds', 'tail_flush_and_eof_seal_seconds', 'prefix_replay_seconds')]
    values.extend(c['seconds'] for c in measured['chunk_commits'])
    for row in measured['queries']:
        values.extend(row[k] for k in names)
        values.extend(row['rank_stages_seconds'].values())
        work = row['sql_workload']
        if any(type(v) not in (int, bool) or v < 0 for v in work.values()):
            raise ValueError('Invalid logical workload')
        if (sum(row['rank_stages_seconds'].values()) > row['rank_seconds']+1e-8
                or row['rank_seconds'] > row['verification_seconds']+1e-8
                or row['verification_seconds']+row['checkpoint_append_seconds'] > row['seconds']+1e-8
                or not math.isclose(row['checkpoint_append_seconds']-row['chunk_commit_seconds'],
                                    row['append_without_commit_seconds'], rel_tol=1e-8, abs_tol=1e-8)):
            raise ValueError('Nested query timers do not conserve their enclosing measurements')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('Invalid measured timer')


def acceptance():
    with _exclusive():
        spec = preregistration()
        if (ROOT/ACCEPT).exists():
            raise FileExistsError(ROOT/ACCEPT)
        gates = check_gates()
        methods = [describe(ROOT/name) for name in METHODS]
        folder = PRIVATE/('knn-v22-overlap-tests-'+uuid4().hex)
        folder.mkdir()
        start = perf_counter()
        with (folder/'tests.log').open('x', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.testsRun or not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-6000:], file=sys.stderr)
            raise ValueError('V22 vote synthetic acceptance failed')
        verify_bindings(methods)
        if gates != check_gates() or preregistration() != spec:
            raise ValueError('Sources changed during synthetic acceptance')
        receipt = {'status': 'v22_overlap_methods_synthetic_accepted', 'tests_run': result.testsRun,
                   'created_utc': datetime.now(timezone.utc).isoformat(),
                   'failures': 0, 'errors': 0, 'skipped': 0, 'seconds': perf_counter()-start,
                   'suites': list(SUITES), 'environment': environment(), 'sqlite_version': sqlite3.sqlite_version,
                   'methods': methods, 'specification': describe(ROOT/SPEC),
                   'inventory': spec['inventory'], 'log': describe(folder/'tests.log'), 'gates': gates,
                   'new_keys_selected': 0, 'real_query_measurement_started': False,
                   'full_readback_started': False, 'reserved_test': 'locked', 'T_plan': None}
        public_json(ROOT/ACCEPT, receipt, exclusive=True)
        print(json.dumps({'tests_run': result.testsRun, 'seconds': receipt['seconds']}))


def accepted_methods():
    value = read(ROOT/ACCEPT)
    if (value['status'] != 'v22_overlap_methods_synthetic_accepted'
            or value['environment'] != environment() or value['sqlite_version'] != sqlite3.sqlite_version
            or value['specification'] != describe(ROOT/SPEC)
            or {r['path'] for r in value['methods']} != set(METHODS)
            or len(value['methods']) != len(METHODS)
            or value['suites'] != list(SUITES) or type(value['tests_run']) is not int or value['tests_run'] <= 0
            or any(value[k] != 0 for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('The unchanged V22 and inherited V7 methods must pass acceptance')
    verify_bindings(value['methods']+[value['log']])
    if value['gates'] != check_gates():
        raise ValueError('Scientific reference gates differ from acceptance')
    return value


def _source_contract(stage, spec, acceptance):
    _validate_stage(stage)
    inventory = read(ROOT/spec['inventory']['path'])
    if inventory['environment'] != environment() or inventory['gates'] != check_gates():
        raise ValueError('Inherited environment or gates differ')
    records = {r['path']:r for r in inventory['inherited_sources']}
    for record in [*acceptance['methods'],acceptance['log'],spec['inventory'],
                   describe(ROOT/SPEC),describe(ROOT/ACCEPT)]:
        if records.get(record['path'],record) != record:
            raise ValueError('Conflicting inherited source definition')
        records[record['path']] = record
    meta = dict(inventory['cohort'],stage=stage,candidate=spec['candidate'],environment=environment(),
        sqlite_version=sqlite3.sqlite_version,specification=describe(ROOT/SPEC),
        inventory=spec['inventory'],acceptance=describe(ROOT/ACCEPT),
        anchor=inventory['previous_comparison'],protocol=PROTOCOL)
    for key in ('probes','reference','old_run'):
        if meta[key] not in records:
            raise ValueError('Fixed cohort source is outside the sealed closure')
    for record in read(ROOT/meta['old_run'])['binding']['sources']:
        if records.get(record['path']) != record:
            raise ValueError('Model/input binding is outside the sealed closure')
    return [records[k] for k in sorted(records)],meta

def _check_request_contract(request):
    _check_window(request)
    spec, acceptance = preregistration(), accepted_methods()
    sources, metadata = _source_contract(request['metadata']['stage'], spec, acceptance)
    if request['sources'] != sources or request['metadata'] != metadata:
        raise ValueError('Window sources or candidate metadata differ from the sealed contract')
    return metadata


def worker(folder):
    request = read(folder/'request.json')
    meta = _check_request_contract(request)
    watch = ThrottledWatch(folder, request['deadline_utc'])
    try:
        def verify_sources(phase):
            start = perf_counter()
            verify_bindings(request['sources'], watch)
            if check_gates() != read(ROOT/ACCEPT)['gates']:
                raise ValueError('Scientific gates changed')
            write(folder/(phase+'_hash.json'), {'count': len(request['sources']), 'seconds': perf_counter()-start})

        verify_sources('initial')
        selected = ROOT/meta['selected_root']
        config = read(selected/'configuration.json')
        binding = read(ROOT/meta['old_run'])['binding']
        probes = read(ROOT/meta['probes'])['probes']
        ordinals = read(selected/'ordinals.json')
        expected = 48 if meta['stage'] == 'compare48' else 34
        if len(probes) != expected or len(ordinals) != expected or config['fixed_validation']['queries'] != expected:
            raise ValueError('Only the existing fixed cohort may run')
        model_root = ROOT/meta['model_root']
        database = model_root/'independent.sqlite'
        _check_db(database)
        model = read(model_root/'reconstruction.json')['receipt']
        reference = read(ROOT/meta['reference'])
        inputs = (selected, config, binding, model, database, probes, ordinals, reference)
        clear_caches()
        for label, mode in schedule(meta['stage'], meta['candidate']):
            watch.force()
            write(folder/(label+'_started.json'), {'label': label, 'mode': mode})
            before = resource_snapshot(); _validate_snapshot(before)
            write(folder/(label+'_resources_before.json'), before)
            try:
                _observed_run(folder, request, label, mode, inputs, watch)
            finally:
                after = resource_snapshot(); _validate_snapshot(after)
                write(folder/(label+'_resources_after.json'), after)
            _check_timers(read(folder/label/'measured.json'))
            _check_db(database)
            watch.force()
        verify_sources('final')
        write(folder/'done.json', {'stage': meta['stage'], 'candidate': meta['candidate'],
                                 'completed': True, 'scope': expected, 'runs': 14})
    except BaseException as exc:
        write(folder/'failure.json', {'error_type': type(exc).__name__, 'full_readback_started': False})
        raise


def _publish(folder):
    request = read(folder/'request.json')
    meta = _check_request_contract(request)
    stage = meta['stage']
    target = ROOT/OUTPUT[stage]
    existing = read(target) if target.exists() else None
    if existing is not None:
        if existing['namespace'] != folder.relative_to(ROOT).as_posix():
            raise FileExistsError('A different V22 window already owns this public report')
        verify_bindings(existing['evidence'])
    completion = read(folder/'supervisor_completion.json')
    _check_window(request, completion)
    for identity in read(folder/'tracked_process_identities.json')['identities']:
        try:
            process = psutil.Process(identity['pid'])
            if process.is_running() and process.create_time() == identity['create_time']:
                raise ValueError('A tracked benchmark process is still alive')
        except psutil.NoSuchProcess:
            pass
    if read(folder/'tracked_process_identities.json')['live_after_cleanup'] != 0:
        raise ValueError('Tracked processes were not fully stopped')
    verify_bindings(request['sources'])
    probes, reference = read(ROOT/meta['probes'])['probes'], read(ROOT/meta['reference'])
    expected = 48 if stage == 'compare48' else 34
    if read(folder/'done.json') != {'stage': stage, 'candidate': meta['candidate'],
                                  'completed': True, 'scope': expected, 'runs': 14}:
        raise ValueError('Incomplete fixed-cohort comparison')
    if len(probes) != expected:
        raise ValueError('Frozen cohort size changed')
    runs, raw, snapshots = {}, {}, {}
    binding = read(ROOT/meta['old_run'])['binding']
    _check_db(ROOT/meta['model_root']/'independent.sqlite')
    previous_snapshot_end = datetime.fromisoformat(request['created_utc'])
    previous_monotonic_end = None
    loads = {}
    reference_frames = list(_physical_frames((ROOT/meta['old_run']).parent))
    for label, mode in schedule(stage, meta['candidate']):
        root = folder/label
        run = read(root/'verified_subset/run.json')
        if (run['deadline_utc'] != request['deadline_utc'] or run['budget_seconds'] != request['budget_seconds']
                or run['binding'] != binding or run['expected_queries'] != expected):
            raise ValueError('Run deadline, binding, or fixed cohort changed')
        store = DetailedTimedStore.open(root/'verified_subset', binding, source_root=ROOT)
        proof = ledger_proof(store, probes)
        _same_payload(proof, reference)
        if proof != read(root/'proof.json'):
            raise ValueError('Post-exit scientific ledger proof differs')
        measured, observations = read(root/'measured.json'), read(root/'observations.json')
        _check_timers(measured)
        store.commit_events = measured['chunk_commits']
        store.append_events = observations['append']; store.budget_events = observations['budget']
        detail = store.detailed_cost_summary(measured)
        if proof['actual_committed_bytes'] != sum(row['frame_bytes'] for row in detail['rows']):
            raise ValueError('Observed encoded bytes differ from committed scientific ledger')
        if list(_physical_frames(root/'verified_subset')) != reference_frames:
            raise ValueError('All 48 physical scientific frames must match the original ledger')
        load, previous_monotonic_end = _load_check(root,request,label,mode,previous_monotonic_end)
        loads[label] = load
        costs = _costs(measured, probes)
        costs['positive_overlap_seconds'] = sum(q['rank_stages_seconds']['sql_positive_overlaps'] for q in measured['queries'])
        costs['direct_budget_seconds'] = sum(q['query_append_budget_seconds'] for q in detail['budget']['rows'])
        costs['append_without_commit_or_budget_seconds'] = sum(q['append_without_commit_or_budget_seconds'] for q in detail['budget']['rows'])
        entry = read(root/'entry.json')
        if ((entry['label'], entry['mode']) != (label, mode) or not math.isfinite(entry['seconds'])
                or entry['seconds'] <= 0 or measured['verified_subset_queries'] != expected):
            raise ValueError('Invalid run order or complete-entry timing')
        if any(costs[k] > entry['seconds']+1e-8 for k in ('primary_seconds', 'setup_seconds', 'tail_seconds')):
            raise ValueError('Complete-entry duration is smaller than its measured work')
        if read(root/'profile.json'):
            raise ValueError('Profiling is forbidden during the timed candidate comparison')
        runs[label] = dict(costs, mode=mode, entry_seconds=entry['seconds'])
        raw[label] = measured['queries']
        snapshots[label] = {when: read(folder/(label+'_resources_'+when+'.json')) for when in ('before', 'after')}
        for value in snapshots[label].values():
            _validate_snapshot(value)
        if not (previous_snapshot_end <= datetime.fromisoformat(snapshots[label]['before']['utc'])
                <= datetime.fromisoformat(snapshots[label]['after']['utc'])
                <= datetime.fromisoformat(completion['actual_exit_observed_utc'])):
            raise ValueError('System observations lie outside their original window')
        previous_snapshot_end = datetime.fromisoformat(snapshots[label]['after']['utc'])
    reference_work = [row['sql_workload'] for row in raw['warm_A']]
    if any([row['sql_workload'] for row in rows] != reference_work for rows in raw.values()):
        raise ValueError('Candidate changed logical workload')
    hashes = {phase: read(folder/(phase+'_hash.json')) for phase in ('initial', 'final')}
    if any(value['count'] != len(request['sources']) or not math.isfinite(value['seconds']) or value['seconds'] < 0
           for value in hashes.values()):
        raise ValueError('Incomplete before/after source verification')
    gates = check_gates()
    if gates != read(ROOT/ACCEPT)['gates']:
        raise ValueError('Reference gates changed after measurement')
    cells = defaultdict(list)
    for pair in range(1, 7):
        for index, probe in enumerate(probes):
            cell = probe['cell'] if stage == 'compare34' else _cell(probe, probe['cell'], 'neighbor_vote_grid')
            cells[cell].append(tuple(raw[f'pair_{pair}_{arm}'][index]['verification_seconds']
                                    + raw[f'pair_{pair}_{arm}'][index]['append_without_commit_seconds'] for arm in 'AB'))
    grid = read(ROOT/V6)['repeats'][0]['refinement_sensitivity']['policies']['neighbor_vote_grid']['cells']
    by_cell = {}
    for cell, ref in grid.items():
        pairs = cells.get(cell, [])
        savings = [a-b for a, b in pairs]
        by_cell[cell] = {'population': ref['population_queries'], 'measured_queries': len(pairs)//6,
                         'worst_A_seconds': max((a for a, _ in pairs), default=None),
                         'worst_B_seconds': max((b for _, b in pairs), default=None),
                         'worst_saving_seconds': min(savings, default=None),
                         'median_saving_seconds': median(savings) if savings else None}
    if sum(row['measured_queries'] for row in by_cell.values()) != expected:
        raise ValueError('Frozen samples did not map completely to the fixed 55-cell grid')
    verify_bindings(request['sources'])
    audit = {'sources_reverified_after_exit': True, 'runs': 14, 'query_checks': 14*expected,
             'all_scientific_bytes_match_reference': True, 'logical_workload_equal': True,
             'original_deadline_verified': True, 'tracked_processes_stopped': True, 'gates': gates}
    if (folder/'post_exit_audit.json').exists():
        if read(folder/'post_exit_audit.json') != audit:
            raise ValueError('Post-exit audit receipt differs')
    else:
        write(folder/'post_exit_audit.json', audit)
    report = {'status': 'v22_overlap_'+stage+'_measured', 'stage': stage,
              'created_utc': request['created_utc'], 'namespace': folder.relative_to(ROOT).as_posix(),
              'specification': meta['specification'], 'inventory': meta['inventory'],
              'acceptance': meta['acceptance'], 'anchor': meta['anchor'], 'candidate': meta['candidate'],
              'supervisor': completion, 'environment': meta['environment'], 'sqlite_version': meta['sqlite_version'],
              'sources_bound': len(request['sources']), 'sources_reverified_before_after_and_post_exit': True,
              'hash_checks': hashes, 'all_scientific_bytes_match_reference': True,
              'reference': {k: reference[k] for k in ('records', 'actual_committed_bytes', 'actual_committed_payload_sha256')},
              'runs': runs, 'decision': paired_decision(runs), 'protocol': PROTOCOL,
              'cell_paired_rows_excluding_commit': by_cell, 'system_resource_snapshots': snapshots, 'continuous_load':loads,
              'resource_interpretation': 'Identical continuous 200ms target telemetry brackets every complete run; global run label/mode is separate from the frozen sampler slot zero. Start/end/non-overlap validated. Observer work can overlap timers. No CPU causation or Ollama GPU/token slowdown claim.',
              'cost_interpretation': 'Fair-comparison primary = verification + append excluding nested commit + all chunk commits, including final flush commit. Rank is nested in verification. Setup/tail/entry are separate overlapping diagnostics. This differs from the V22 cell rollup per-query cost excluding direct budget publication.',
              'original_distinct_sample_size': expected, 'repeat_query_checks': 14*expected,
              'warmup_query_checks': 2*expected, 'paired_query_checks': 12*expected,
              'new_unique_keys': 0, 'new_primary_fit_validation_bootstrap': 0,
              'full_validation_complete': False, 'full_readback_started': False, 'reserved_test': 'locked',
              'gates': gates, 'T_plan': None,
              'evidence': [describe(path) for path in sorted(folder.rglob('*')) if path.is_file()]}
    if existing is not None:
        if report != existing:
            raise ValueError('Re-audit differs from the immutable published comparison')
    else:
        public_json(target, report, exclusive=True)
    print(json.dumps({'stage': stage, 'report': OUTPUT[stage], 'elapsed': completion['seconds'],
                      'decision': report['decision'], 're_audited': existing is not None}))
    return report


def publish(folder):
    with _exclusive():
        return _publish(Path(folder).resolve())


def supervise(stage):
    with _exclusive():
        if stage not in OUTPUT:
            raise ValueError('Unsupported V22 comparison stage')
        if (ROOT/OUTPUT[stage]).exists():
            raise FileExistsError(ROOT/OUTPUT[stage])
        spec, acceptance = preregistration(), accepted_methods()
        sources, metadata = _source_contract(stage, spec, acceptance)
        for old in PRIVATE.glob('knn-v22-overlap-compare48-*/request.json'):
            raise FileExistsError('Inspect the existing V22 window instead of restarting: '+str(old.parent))
        folder = PRIVATE/('knn-v22-overlap-'+stage+'-'+uuid4().hex)
        print('V22 vote window: '+folder.relative_to(ROOT).as_posix(), flush=True)
        receipt = run_window(folder, [sys.executable, '-B', '-m', MODULE, '--worker', str(folder)],
                             sources, 'joint_tail', metadata=metadata, budget_seconds=1800, limits=LIMITS)
        _normal_exit(receipt)
        return _publish(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance', action='store_true')
    modes.add_argument('--compare48', action='store_true')
    modes.add_argument('--publish', type=Path)
    modes.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.acceptance:
        acceptance()
    elif args.worker:
        worker(args.worker)
    elif args.publish:
        publish(args.publish)
    else:
        supervise('compare48')
