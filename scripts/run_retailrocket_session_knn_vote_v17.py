"""One preregistered V17 SQL candidate on the unchanged fixed 48, then 34.

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
    METHODS as V7_METHODS, SUITES as V7_SUITES, _run, _costs, schedule, paired_decision)


MODULE = 'scripts.run_retailrocket_session_knn_vote_v17'
BASE = 'reports/stage12/retailrocket_session_knn_'
ANCHOR = BASE+'v7_vote_compare48_20261105.json'
GAP = BASE+'v7_gap_cost_20261105.json'
V6 = BASE+'v6_refined_cost_20261103.json'
SPEC = BASE+'v17_cost_sql_specification_20261106.json'
SPEC_SHA256 = '4a950ab8db4ca93c2977ba1799fbe511ecbe7760a524c603709cff8af5d999db'
ACCEPT = BASE+'v17_vote_acceptance_20261106.json'
OUTPUT = {stage: BASE+'v17_vote_'+stage+'_20261106.json' for stage in ('compare48', 'compare34')}
SUITES = ('tests.test_retailrocket_session_knn_vote_v17', *V7_SUITES)
METHODS = tuple(dict.fromkeys((*V7_METHODS, 'scripts/run_retailrocket_session_knn_vote_v17.py',
                             'tests/test_retailrocket_session_knn_vote_v17.py')))
PROTOCOL = {'pairs': 6, 'warmup_runs': 2, 'minimum_wins': 5,
            'minimum_median_saving_percent': 5, 'both_order_medians_positive': True,
            'entry_median_must_not_regress': True, 'budget_seconds': 1800}


def preregistration():
    spec = read(ROOT/SPEC)
    if (describe(ROOT/SPEC)['sha256'] != SPEC_SHA256
            or spec['status'] != 'v17_cost_sql_specification_frozen'
            or spec['candidate'] != 'rank_counts' or spec['protocol'] != PROTOCOL):
        raise ValueError('Expected the sealed V17 candidate and paired protocol')
    verify_bindings([spec['rollup'], spec['inventory'], *spec['evidence']])
    inventory = read(ROOT/spec['inventory']['path'])
    if (inventory['status'] != 'v17_cost_inventory_verified'
            or inventory['comparable_scope']['distinct_queries'] != 156
            or inventory['comparable_scope']['query_observations'] != 360
            or inventory['comparable_scope']['covered_cells'] != 55):
        raise ValueError('Candidate must follow the complete V17 cost inventory')
    return spec


@contextmanager
def _exclusive():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE/'knn-v17-vote-entry.guard').open('a+b') as guard:
        guard.seek(0, 2)
        if guard.tell() == 0:
            guard.write(b'0'); guard.flush()
        _lock(guard)
        yield


def _validate_stage(stage, prior=None):
    if stage not in OUTPUT:
        raise ValueError('Only fixed 48 and fixed 34 comparisons are authorized')
    if stage == 'compare34' and (prior is None or prior.get('stage') != 'compare48'
            or prior.get('candidate') != 'rank_counts'
            or prior.get('status') != 'v17_vote_compare48_measured'
            or prior.get('all_scientific_bytes_match_reference') is not True
            or prior.get('specification') != describe(ROOT/SPEC)
            or prior.get('decision', {}).get('supports_candidate') is not True):
        raise ValueError('A passing V17 fixed-48 comparison is required before fixed 34')
    if stage == 'compare34':
        expected = schedule('compare48', 'rank_counts')
        if (set(prior.get('runs', {})) != {label for label, _ in expected}
                or any(prior['runs'][label]['mode'] != mode for label, mode in expected)
                or prior.get('original_distinct_sample_size') != 48
                or prior.get('repeat_query_checks') != 672 or prior.get('new_unique_keys') != 0
                or prior['decision'] != paired_decision(prior['runs'])):
            raise ValueError('Prior fixed-48 timing evidence does not reproduce its passing decision')


def _check_window(request, completion=None):
    start = datetime.fromisoformat(request['created_utc'])
    deadline = datetime.fromisoformat(request['deadline_utc'])
    if (start.utcoffset() is None or deadline.utcoffset() is None
            or request['budget_seconds'] != 1800 or deadline-start != timedelta(seconds=1800)
            or request['limits'] != LIMITS or request['operation'] != 'joint_tail'
            or request['full_readback_enabled'] is not False or request['reserved_test'] != 'locked'
            or request['T_plan'] is not None):
        raise ValueError('Changed V17 absolute deadline, resource limits, or permitted scope')
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
        folder = PRIVATE/('knn-v17-vote-tests-'+uuid4().hex)
        folder.mkdir()
        start = perf_counter()
        with (folder/'tests.log').open('x', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.testsRun or not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-6000:], file=sys.stderr)
            raise ValueError('V17 vote synthetic acceptance failed')
        verify_bindings(methods)
        if gates != check_gates() or preregistration() != spec:
            raise ValueError('Sources changed during synthetic acceptance')
        receipt = {'status': 'v17_vote_methods_synthetic_accepted', 'tests_run': result.testsRun,
                   'created_utc': datetime.now(timezone.utc).isoformat(),
                   'failures': 0, 'errors': 0, 'skipped': 0, 'seconds': perf_counter()-start,
                   'suites': list(SUITES), 'environment': environment(), 'sqlite_version': sqlite3.sqlite_version,
                   'methods': methods, 'specification': describe(ROOT/SPEC), 'rollup': spec['rollup'],
                   'inventory': spec['inventory'], 'log': describe(folder/'tests.log'), 'gates': gates,
                   'new_keys_selected': 0, 'real_query_measurement_started': False,
                   'full_readback_started': False, 'reserved_test': 'locked', 'T_plan': None}
        public_json(ROOT/ACCEPT, receipt, exclusive=True)
        print(json.dumps({'tests_run': result.testsRun, 'seconds': receipt['seconds']}))


def accepted_methods():
    value = read(ROOT/ACCEPT)
    if (value['status'] != 'v17_vote_methods_synthetic_accepted'
            or value['environment'] != environment() or value['sqlite_version'] != sqlite3.sqlite_version
            or value['specification'] != describe(ROOT/SPEC)
            or {r['path'] for r in value['methods']} != set(METHODS)
            or len(value['methods']) != len(METHODS)
            or value['suites'] != list(SUITES) or type(value['tests_run']) is not int or value['tests_run'] <= 0
            or any(value[k] != 0 for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('The unchanged V17 and inherited V7 methods must pass acceptance')
    verify_bindings(value['methods']+[value['log']])
    if value['gates'] != check_gates():
        raise ValueError('Scientific reference gates differ from acceptance')
    return value


def _audit_prior_runs(prior, expected_meta):
    """Reproduce the prior decision from frozen raw runs, without rehashing models.

    The enclosing new window checks the complete inherited source inventory.
    Here the prior report's small evidence and its original fixed-cohort source
    bindings are checked before raw timings and committed ledgers are reopened.
    """
    verify_bindings(prior['evidence'])
    folder = ROOT/prior['namespace']
    request = read(folder/'request.json')
    metadata = request['metadata']
    if (prior['stage'] != 'compare48' or metadata['stage'] != 'compare48'
            or metadata['candidate'] != 'rank_counts'
            or metadata['specification'] != describe(ROOT/SPEC)
            or any(metadata[k] != expected_meta[k] for k in
                   ('probes', 'reference', 'old_run', 'selected_root', 'model_root'))):
        raise ValueError('Prior comparison changed its original fixed-48 source contract')
    completion = read(folder/'supervisor_completion.json')
    _check_window(request, completion)
    if completion != prior['supervisor']:
        raise ValueError('Prior comparison exit observation differs')
    sources = {record['path']: record for record in request['sources']}
    verify_bindings([sources[metadata[k]] for k in ('probes', 'reference', 'old_run')])
    probes = read(ROOT/metadata['probes'])['probes']
    reference = read(ROOT/metadata['reference'])
    binding = read(ROOT/metadata['old_run'])['binding']
    if len(probes) != 48 or any(sources.get(record['path']) != record for record in binding.get('sources', [])):
        raise ValueError('Prior fixed cohort or inherited source bindings differ')
    runs, work = {}, None
    for label, mode in schedule('compare48', 'rank_counts'):
        root = folder/label
        run = read(root/'verified_subset/run.json')
        if (run['binding'] != binding or run['expected_queries'] != 48
                or any(run[k] != request[k] for k in ('deadline_utc', 'budget_seconds'))):
            raise ValueError('Prior raw run changed its binding or original deadline')
        # All ledger bytes are checked here; full model/raw-data fingerprints
        # remain the enclosing window's initial/final/post-exit source checks.
        store = DetailedTimedStore.open(root/'verified_subset', binding, source_root=ROOT,
                                        external_source_verifier=lambda: None)
        proof = ledger_proof(store, probes)
        _same_payload(proof, reference)
        if proof != read(root/'proof.json'):
            raise ValueError('Prior raw scientific ledger differs from its proof')
        measured = read(root/'measured.json')
        _check_timers(measured)
        costs = _costs(measured, probes)
        entry = read(root/'entry.json')
        if ((entry['label'], entry['mode']) != (label, mode)
                or not math.isfinite(entry['seconds']) or entry['seconds'] <= 0
                or measured['verified_subset_queries'] != 48
                or any(costs[k] > entry['seconds']+1e-8 for k in ('primary_seconds', 'setup_seconds', 'tail_seconds'))):
            raise ValueError('Prior raw run has invalid order or complete-entry timing')
        current = [row['sql_workload'] for row in measured['queries']]
        if work is not None and current != work:
            raise ValueError('Prior raw runs changed their logical workload')
        work = current
        runs[label] = dict(costs, mode=mode, entry_seconds=entry['seconds'])
    if runs != prior['runs'] or paired_decision(runs) != prior['decision']:
        raise ValueError('Prior public timing summary does not reproduce its frozen raw runs')
    return runs


def _source_contract(stage, spec, acceptance):
    prior = read(ROOT/OUTPUT['compare48']) if stage == 'compare34' else None
    _validate_stage(stage, prior)
    verify_bindings([spec['inventory']])
    sealed = {}
    for record in [*read(ROOT/spec['inventory']['path'])['inputs'], *spec['evidence']]:
        if record['path'] in sealed and sealed[record['path']] != record:
            raise ValueError('Conflicting sealed source fingerprints: '+record['path'])
        sealed[record['path']] = record
    if any(name not in sealed for name in (ANCHOR, V6, GAP)):
        raise ValueError('Required comparison anchors were not sealed by the specification or inventory')
    verify_bindings([sealed[name] for name in (ANCHOR, V6, GAP)])
    base = read(ROOT/ANCHOR)
    if base['stage'] != 'compare48' or base['all_scientific_bytes_match_reference'] is not True:
        raise ValueError('Published V7 fixed-48 provenance is required')
    anchors = {r['path']: r for r in base['evidence']}
    request_path = base['namespace']+'/request.json'
    completion_path = base['namespace']+'/supervisor_completion.json'
    verify_bindings([anchors[request_path], anchors[completion_path]])
    _normal_exit(read(ROOT/completion_path))
    old = read(ROOT/request_path)
    if len(old['sources']) != 546 or len({r['path'] for r in old['sources']}) != 546:
        raise ValueError('Expected the complete 546-source V7 fixed-48 anchor')
    records = {r['path']: r for r in old['sources']}

    def add(record):
        if record['path'] in records and records[record['path']] != record:
            raise ValueError('Attempt to replace an inherited frozen source: '+record['path'])
        records[record['path']] = record

    meta = {k: old['metadata'][k] for k in ('model_root', 'selected_root', 'old_run', 'probes', 'reference')}
    meta.update(stage=stage, candidate=spec['candidate'], environment=environment(),
                sqlite_version=sqlite3.sqlite_version, specification=describe(ROOT/SPEC),
                rollup=spec['rollup'], inventory=spec['inventory'], acceptance=describe(ROOT/ACCEPT),
                anchor=sealed[ANCHOR], protocol=PROTOCOL)
    if (old['metadata']['environment'] != meta['environment']
            or old['metadata']['sqlite_version'] != meta['sqlite_version']):
        raise ValueError('Reference host environment differs')
    for item in [anchors[request_path], anchors[completion_path], *acceptance['methods'], *spec['evidence'],
                 spec['rollup'], spec['inventory']]:
        add(item)
    for name in (ANCHOR, V6, GAP):
        add(sealed[name])
    for name in (SPEC, ACCEPT):
        add(describe(ROOT/name))
    if stage == 'compare34':
        add(describe(ROOT/OUTPUT['compare48']))
        _audit_prior_runs(prior, meta)
        for item in prior['evidence']:
            if item['path'].endswith(('/request.json', '/supervisor_completion.json')):
                add(item)
        gap = read(ROOT/GAP)
        if (gap['status'] != 'v7_gap_34_measured_twice' or gap['scope']['new_keys'] != 34
                or gap['sources_reverified_before_after'] is not True):
            raise ValueError('Completed fixed V7 gap evidence is required')
        pinned = {r['path']: r for r in gap['evidence']}
        namespace = gap['namespace']
        for suffix in ('request.json', 'supervisor_completion.json'):
            verify_bindings([pinned[namespace+'/'+suffix]])
            add(pinned[namespace+'/'+suffix])
        _normal_exit(read(ROOT/(namespace+'/supervisor_completion.json')))
        meta.update(selected_root=namespace+'/raw_selected_inputs', probes=namespace+'/frozen_probes.json',
                    old_run=namespace+'/repeat_0/verified_subset/run.json', reference=namespace+'/repeat_0/proof.json')
        for name, descriptor in pinned.items():
            if name.startswith(meta['selected_root']+'/') or name in (meta['probes'], meta['old_run'], meta['reference']):
                add(descriptor)
        verify_bindings([pinned[meta[k]] for k in ('old_run', 'reference', 'probes')])
        for source in read(ROOT/meta['old_run'])['binding']['sources']:
            if records.get(source['path']) != source:
                if pinned.get(source['path']) != source:
                    raise ValueError('Missing gap source provenance: '+source['path'])
                add(source)
    return [records[k] for k in sorted(records)], meta


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
                _run(folder, request, label, mode, inputs, watch)
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
            raise FileExistsError('A different V17 window already owns this public report')
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
        costs = _costs(measured, probes)
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
    report = {'status': 'v17_vote_'+stage+'_measured', 'stage': stage,
              'created_utc': request['created_utc'], 'namespace': folder.relative_to(ROOT).as_posix(),
              'specification': meta['specification'], 'rollup': meta['rollup'], 'inventory': meta['inventory'],
              'acceptance': meta['acceptance'], 'anchor': meta['anchor'], 'candidate': meta['candidate'],
              'supervisor': completion, 'environment': meta['environment'], 'sqlite_version': meta['sqlite_version'],
              'sources_bound': len(request['sources']), 'sources_reverified_before_after_and_post_exit': True,
              'hash_checks': hashes, 'all_scientific_bytes_match_reference': True,
              'reference': {k: reference[k] for k in ('records', 'actual_committed_bytes', 'actual_committed_payload_sha256')},
              'runs': runs, 'decision': paired_decision(runs), 'protocol': PROTOCOL,
              'cell_paired_rows_excluding_commit': by_cell, 'system_resource_snapshots': snapshots,
              'resource_interpretation': 'Nonblocking before/after system context, outside measured entry and primary timers. CPU values are sampling-context observations, not a cause-of-speedup attribution; no inference service was queried or changed.',
              'cost_interpretation': 'Fair-comparison primary = verification + append excluding nested commit + all chunk commits, including final flush commit. Rank is nested in verification. Setup/tail/entry are separate overlapping diagnostics. This differs from the V17 cell rollup per-query cost excluding direct budget publication.',
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
            raise ValueError('Unsupported V17 comparison stage')
        if (ROOT/OUTPUT[stage]).exists():
            raise FileExistsError(ROOT/OUTPUT[stage])
        spec, acceptance = preregistration(), accepted_methods()
        sources, metadata = _source_contract(stage, spec, acceptance)
        folder = PRIVATE/('knn-v17-vote-'+stage+'-'+uuid4().hex)
        print('V17 vote window: '+folder.relative_to(ROOT).as_posix(), flush=True)
        receipt = run_window(folder, [sys.executable, '-B', '-m', MODULE, '--worker', str(folder)],
                             sources, 'joint_tail', metadata=metadata, budget_seconds=1800, limits=LIMITS)
        _normal_exit(receipt)
        return _publish(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance', action='store_true')
    modes.add_argument('--compare48', action='store_true')
    modes.add_argument('--compare34', action='store_true')
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
        supervise('compare48' if args.compare48 else 'compare34')
