"""Bounded V19 tail profiling: six new queries and one fixed anchor, three repeats."""
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
from scripts.run_retailrocket_session_knn_gap_v9 import _extract
from scripts.run_retailrocket_session_knn_gap_v16 import _check_window
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit
from scripts.retailrocket_session_knn_checkpoint_v2 import _lock
from scripts.retailrocket_session_knn_cost_window_v5 import LIMITS, run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_gap_v7 import check_index, ledger_proof
from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_pair_v4 import verify_selected
from scripts.retailrocket_session_knn_tail_v19 import (
    validate_spec, select_tail_roster, audit_tail_order, sample_workload,
    compare_repeats, summarize_repeats, TelemetrySampler, summarize_telemetry)


MODULE = 'scripts.run_retailrocket_session_knn_tail_v19'
BASE = 'reports/stage12/retailrocket_session_knn_'
INVENTORY = BASE+'v19_tail_inventory_20261106.json'
SPEC = BASE+'v19_tail_sampling_specification_20261106.json'
SPEC_SHA256 = '65a2022c6481006664af0b19b4d6c79a6dd7a3cb0263d258f9a68d2239fe2d4b'
ACCEPT = BASE+'v19_tail_acceptance_20261106.json'
REPORT = BASE+'v19_tail_cost_20261106.json'
PARENT = BASE+'v18_reinforcement_cost_20261106.json'
CELL = '1101/n5/v4'
METHODS = ('scripts/retailrocket_session_knn_tail_v19.py',
           'scripts/run_retailrocket_session_knn_tail_v19.py',
           'tests/test_retailrocket_session_knn_tail_v19.py')
SUITES = ('tests.test_retailrocket_session_knn_tail_v19',
          'tests.test_retailrocket_session_knn_reinforcement_v18')
HISTORY_FIELDS = {'V3': 'history64', 'V6': 'history48', 'V7': 'history34', 'V8': 'history8',
                  **{f'V{i}': f'history8_v{i}' for i in range(9, 16)},
                  'V16': 'history10_v16', 'V18': 'history10_v18'}
DONE = {'repeats': 3, 'new_keys': 6, 'anchor_keys': 1, 'queries_per_repeat': 7, 'engineering_checks': 21}


def preregistration():
    spec, inventory = read(ROOT/SPEC), read(ROOT/INVENTORY)
    if (describe(ROOT/SPEC)['sha256'] != SPEC_SHA256
            or spec['status'] != 'v19_tail_specification_frozen'
            or spec['inventory'] != describe(ROOT/INVENTORY)
            or inventory['status'] != 'v19_tail_inventory_verified'):
        raise ValueError('Expected the sealed V19 specification and tail inventory')
    verify_bindings([spec['inventory'], *spec['evidence']])
    validate_spec(spec)
    for source, target in ((inventory['whole_cell'], spec['target_population']),
                           (inventory['target_tail'], spec['target_tail'])):
        if (any(source[k] != target[k] for k in ('population', 'historical_exclusions', 'eligible'))
                or source['comparable_distinct_queries'] != target['existing_comparable_queries']):
            raise ValueError('The frozen whole-cell and strict-tail capacities differ')
    quotas = {row['segment']: row for row in spec['quotas']}
    if set(quotas) != {row['segment'] for row in inventory['tail_segments']}:
        raise ValueError('The same three registered neighbor bands are required')
    for row in inventory['tail_segments']:
        if (any(quotas[row['segment']][k] != row[k] for k in
                ('population', 'historical_exclusions', 'eligible', 'lower_inclusive', 'upper_inclusive'))
                or quotas[row['segment']]['planned_new_queries'] != 2):
            raise ValueError('Registered tail capacities or quotas changed')
    if (inventory['fixed_control']['count'] != 1
            or inventory['fixed_control']['same_identity_in_V6_and_V18'] is not True):
        raise ValueError('The one unchanged original V6 n5 control is required')
    if inventory['coverage_before'] != {
            'population': 166897, 'grid_cells': 55, 'covered_cells': 55, 'uncovered_cells': 0,
            'unrepresented_population': 0, 'distinct_historical_queries': 226,
            'distinct_comparable_queries': 164}:
        raise ValueError('The complete 226-history and 164-comparable inventory is required')
    return spec, inventory


@contextmanager
def _exclusive():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE/'knn-v19-tail.guard').open('a+b') as guard:
        if guard.seek(0, 2) == 0:
            guard.write(b'0'); guard.flush()
        _lock(guard)
        yield


def acceptance():
    with _exclusive():
        spec, _ = preregistration()
        if (ROOT/ACCEPT).exists():
            raise FileExistsError(ROOT/ACCEPT)
        gates = check_gates()
        methods = [describe(ROOT/name) for name in METHODS]
        folder = PRIVATE/('knn-v19-tail-tests-'+uuid4().hex)
        folder.mkdir()
        start = perf_counter()
        with (folder/'tests.log').open('x', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.testsRun or not result.wasSuccessful() or result.skipped:
            print((folder/'tests.log').read_text(encoding='utf-8')[-6000:], file=sys.stderr)
            raise ValueError('V19 synthetic acceptance failed')
        verify_bindings(methods)
        if check_gates() != gates or preregistration()[0] != spec:
            raise ValueError('Sources or scientific gates changed during acceptance')
        receipt = {'status': 'v19_tail_tools_synthetic_accepted',
                   'created_utc': datetime.now(timezone.utc).isoformat(), 'tests_run': result.testsRun,
                   'seconds': perf_counter()-start, 'failures': 0, 'errors': 0, 'skipped': 0,
                   'suites': list(SUITES), 'environment': environment(), 'method_files': methods,
                   'gates': gates, 'specification': describe(ROOT/SPEC), 'inventory': spec['inventory'],
                   'log': describe(folder/'tests.log'), 'actual_new_keys_selected': 0,
                   'actual_new_query_verifications': 0, 'reserved_test': 'locked', 'T_plan': None}
        public_json(ROOT/ACCEPT, receipt, exclusive=True)
        print({'tests_run': result.testsRun, 'seconds': receipt['seconds']})


def _accepted(spec):
    accepted = read(ROOT/ACCEPT)
    if (accepted['status'] != 'v19_tail_tools_synthetic_accepted'
            or accepted['environment'] != environment()
            or len(accepted['method_files']) != len(METHODS)
            or {r['path'] for r in accepted['method_files']} != set(METHODS)
            or accepted['suites'] != list(SUITES) or type(accepted['tests_run']) is not int or accepted['tests_run'] <= 0
            or any(accepted[k] != 0 for k in ('failures', 'errors', 'skipped', 'actual_new_keys_selected', 'actual_new_query_verifications'))
            or accepted['gates'] != check_gates() or accepted['reserved_test'] != 'locked' or accepted['T_plan'] is not None
            or accepted['inventory'] != spec['inventory'] or accepted['specification'] != describe(ROOT/SPEC)):
        raise ValueError('Current V19 methods, specification and environment require acceptance')
    verify_bindings([*accepted['method_files'], accepted['log']])
    return accepted


def _expected_request():
    spec, inventory = preregistration()
    accepted = _accepted(spec)
    parent_record = _record(inventory['inputs'], '/'+Path(PARENT).name)
    verify_bindings([parent_record])
    parent = read(ROOT/PARENT)
    if (parent['status'] != 'v18_reinforcement_8_new_2_anchor_measured_three_times'
            or parent['sources_reverified_before_after_and_post_exit'] is not True
            or parent['coverage']['covered_cells'] != 55 or parent['coverage']['uncovered_cells'] != 0
            or parent['coverage']['distinct_historically_verified_queries'] != 226
            or parent['coverage']['distinct_comparable_queries'] != 164
            or parent['scope']['new_keys'] != 8 or parent['scope']['reused_anchor_keys'] != 2):
        raise ValueError('Completed V18 coverage and correctly deduplicated history are required')
    anchors = [_record(parent['evidence'], '/'+name) for name in
               ('request.json', 'supervisor_completion.json', 'frozen_probes.json')]
    verify_bindings(anchors)
    _normal_exit(read(ROOT/anchors[1]['path']))
    prior = read(ROOT/anchors[0]['path'])
    old_acceptance_record = _record(prior['sources'], '/retailrocket_session_knn_v18_reinforcement_acceptance_20261106.json')
    verify_bindings([old_acceptance_record])
    old_acceptance = read(ROOT/old_acceptance_record['path'])
    if (old_acceptance['status'] != 'v18_reinforcement_tools_synthetic_accepted'
            or old_acceptance['environment'] != environment()
            or any(old_acceptance[k] != 0 for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('Inherited V18 timing and resource methods require their original acceptance')
    verify_bindings([*old_acceptance['method_files'], old_acceptance['log']])
    meta = {k: prior['metadata'][k] for k in
            (*list(HISTORY_FIELDS.values())[:-1], 'roster', 'independent_model_folder', 'environment')}
    if meta['environment'] != environment():
        raise ValueError('Parent engineering environment differs')
    control = inventory['fixed_control']
    if control['source_selection']['path'] != meta['history48']:
        raise ValueError('Original V6 anchor selection differs')
    meta.update(history10_v18=anchors[2]['path'], queries=7, new_keys=6, anchor_keys=1, repeats=3,
                anchor_reference_run=control['reference_run']['path'],
                anchor_reference_proof=control['reference_proof']['path'])
    records = {record['path']: record for record in prior['sources']}
    for record in [*inventory['inputs'], *spec['evidence'], *anchors, *accepted['method_files'], accepted['log'],
                   *old_acceptance['method_files'], old_acceptance['log'],
                   spec['inventory'], describe(ROOT/SPEC), describe(ROOT/ACCEPT)]:
        if record['path'] in records and records[record['path']] != record:
            raise ValueError('Inherited frozen source definition changed')
        records[record['path']] = record
    if any(name not in records for name in (meta['anchor_reference_run'], meta['anchor_reference_proof'])):
        raise ValueError('V6 anchor ledger lacks sealed source provenance')
    for dependency in ('scripts/retailrocket_session_knn_reinforcement_v18.py',
                       'scripts/retailrocket_session_knn_cost_rollup_v17.py'):
        inherited = next(r for r in prior['sources'] if r['path'] == dependency)
        if records[dependency] != inherited:
            raise ValueError('An inherited timing or telemetry method changed')
        verify_bindings([inherited])
    return meta, [records[k] for k in sorted(records)]


def _selection_args(meta):
    spec, _ = preregistration()
    histories = {name: read(ROOT/meta[field]) for name, field in HISTORY_FIELDS.items()}
    sets = [{row['key_sha256'] for row in histories[name]['probes']} for name in HISTORY_FIELDS]
    sizes = [64,48,34,8,8,8,8,8,8,8,8,10,10]
    old_union = set.union(*sets[:-1])
    old_v18 = histories['V18']['probes']
    old_new = {row['key_sha256'] for row in old_v18 if row['sample_role'] == 'new'}
    old_anchors = {row['key_sha256'] for row in old_v18 if row['sample_role'] == 'anchor'}
    if ([len(histories[name]['probes']) for name in HISTORY_FIELDS] != sizes
            or [len(group) for group in sets] != sizes or len(sets[0] & sets[1]) != 2
            or any(sets[i] & set.union(*sets[:i]) for i in range(2, len(sets)-1))
            or len(old_union) != 218 or len(old_new) != 8 or len(old_anchors) != 2
            or old_new & old_union or not old_anchors <= sets[1]
            or sets[-1] & old_union != old_anchors or len(set.union(*sets)) != 226):
        raise ValueError('Historical V18 contributes eight new identities, not its two old anchors')
    return ROOT/meta['roster'], histories, spec


def _selection(args, watch=lambda: None):
    selected = select_tail_roster(*args, watch=watch)
    audit_tail_order(args[0], selected, *args[1:], watch=watch)
    if (len(selected['probes']) != 7 or selected['new_keys'] != 6 or selected['anchor_keys'] != 1
            or [row['original_ordinal'] for row in selected['probes']] != sorted(row['original_ordinal'] for row in selected['probes'])):
        raise ValueError('Tail profiling requires six new identities and the one old anchor in original order')
    return selected


def _seal(folder, selection, spec):
    return {'selection': describe(folder/'frozen_probes.json'), 'specification': describe(ROOT/SPEC),
            'inventory': spec['inventory'], 'roster_sha256': selection['roster_sha256'],
            'new_keys': 6, 'anchor_keys': 1, 'full_sort_agrees': True}


def _anchor_references(request, selection):
    meta = request['metadata']
    probes = read(ROOT/meta['history48'])['probes']
    run = read(ROOT/meta['anchor_reference_run'])
    bound = {row['path']: row for row in request['sources']}
    if len(probes) != 48 or any(bound.get(row['path']) != row for row in run['binding']['sources']):
        raise ValueError('Original anchor ledger sources differ from the verified window inventory')
    checkpoint = (ROOT/meta['anchor_reference_run']).parent
    # The enclosing phase has checked all source bindings; retain independent
    # ledger verification without rehashing the large model for every anchor.
    store = DetailedTimedStore.open(checkpoint, run['binding'], source_root=ROOT,
                                    external_source_verifier=lambda: None)
    proof = ledger_proof(store, probes)
    original = read(ROOT/meta['anchor_reference_proof'])
    if (proof['checkpoint_chain_checked'] is not True
            or original.get('checkpoint_chain_checked', True) is not True
            or any(proof[name] != original[name] for name in
                   ('records', 'actual_committed_bytes', 'actual_committed_payload_sha256'))):
        raise ValueError('Original V6 anchor scientific ledger proof changed')
    wanted = {row['key_sha256'] for row in selection['probes'] if row['sample_role'] == 'anchor'}
    result = {_sha(frame['key']): frame['payload'] for frame in store.iter_records()
              if _sha(frame['key']) in wanted}
    if len(wanted) != 1 or set(result) != wanted:
        raise ValueError('The unique original V6 n5 anchor is required')
    return result


def _compare_anchors(store, selection, reference):
    found = {}
    for probe, frame in zip(selection['probes'], store.iter_records(), strict=True):
        if frame['key'] != probe['key']:
            raise ValueError('Anchor comparison encountered a changed fixed query identity')
        if probe['sample_role'] != 'anchor':
            continue
        identity = probe['key_sha256']
        if identity not in reference or frame['payload'] != reference[identity]:
            raise ValueError('Anchor scientific payload differs from the original V6 output')
        found[identity] = True
    if set(found) != set(reference) or len(found) != 1:
        raise ValueError('Missing or duplicate original anchor payload')


def _check_telemetry_span(records, span, request, index):
    if (span['repeat_index'] != index or span['completed'] is not True
            or records[0]['kind'] != 'start' or records[-1]['kind'] != 'end'):
        raise ValueError('Complete verifier span and bracketing telemetry are required')
    start, end = span['start_monotonic_seconds'], span['end_monotonic_seconds']
    if (any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (start, end))
            or not records[0]['monotonic_seconds']+records[0]['collector_seconds'] <= start <= end
            or end > records[-1]['monotonic_seconds']):
        raise ValueError('Resource observations do not bracket the complete verifier entry')
    values = [datetime.fromisoformat(value) for value in
              (request['created_utc'], records[0]['observed_utc'], span['start_utc'], span['end_utc'],
               records[-1]['observed_utc'], request['deadline_utc'])]
    if any(value.utcoffset() is None for value in values) or values != sorted(values):
        raise ValueError('Verifier telemetry UTC times violate the original absolute window')


def _check_repeat_spans(folder, request):
    previous_end = None
    for index in range(3):
        run = folder/f'repeat_{index}'
        records = read(run/'telemetry_records.json')['records']
        span = read(run/'verifier_span.json')
        _check_telemetry_span(records, span, request, index)
        if previous_end is not None and records[0]['monotonic_seconds'] < previous_end:
            raise ValueError('Resource samplers or verifier rounds overlap')
        previous_end = records[-1]['monotonic_seconds']+records[-1]['collector_seconds']


def _repeat(folder, request, binding, selection, spec, index, *, references,
            model=None, database=None, watch=lambda: None):
    run = folder/f'repeat_{index}'
    checkpoint = run/'verified_subset'
    if model is not None:
        subset = folder/'raw_selected_inputs'
        store = DetailedTimedStore.create(checkpoint, binding, request['deadline_utc'], request['budget_seconds'],
                    source_root=ROOT, expected_queries=7, required_stages=('reconstruction', 'queries'))
        with store.writer():
            store.seal_stage('reconstruction', {'kind': 'reused_v5_reconstructed_model', 'fit_audit': model['fit_audit']})
            sampler = TelemetrySampler(interval_seconds=.2, process_name_prefix='ollama')
            sampler.start(index)
            span = {'repeat_index': index, 'completed': False, 'start_monotonic_seconds': perf_counter(),
                    'start_utc': datetime.now(timezone.utc).isoformat()}
            try:
                measured = verify_selected(subset/'primary', {k: subset/k for k in PATHS}, binding['configuration'],
                            store, model, database, read(subset/'ordinals.json'), watch)
                span['completed'] = True
            finally:
                span.update(end_monotonic_seconds=perf_counter(), end_utc=datetime.now(timezone.utc).isoformat())
                try:
                    sampler.stop()
                finally:
                    write(run/'verifier_span.json', span)
                    write(run/'telemetry_records.json', {'repeat_index': index, 'records': sampler.records})
            telemetry = summarize_telemetry(sampler.records, index, interval_seconds=.2)
            _check_telemetry_span(sampler.records, span, request, index)
            write(run/'telemetry_summary.json', telemetry)
        write(run/'measurements.json', measured)
        observations = {'append_events': store.append_events, 'budget_events': store.budget_events}
    else:
        record = read(checkpoint/'run.json')
        if (record['binding'] != binding or record['expected_queries'] != 7
                or any(record[k] != request[k] for k in ('deadline_utc', 'budget_seconds'))):
            raise ValueError('Changed repeat binding, size or absolute deadline')
        store = DetailedTimedStore.open(checkpoint, binding, source_root=ROOT)
        measured, observations = read(run/'measurements.json'), read(run/'observations.json')
        store.commit_events = measured['chunk_commits']
        store.append_events = observations['append_events']; store.budget_events = observations['budget_events']
        saved = read(run/'telemetry_records.json')
        if saved['repeat_index'] != index:
            raise ValueError('Resource observations changed their repeat identity')
        telemetry = summarize_telemetry(saved['records'], index, interval_seconds=.2)
        _check_telemetry_span(saved['records'], read(run/'verifier_span.json'), request, index)
        if telemetry != read(run/'telemetry_summary.json'):
            raise ValueError('Saved resource summary differs from raw observation intervals')
    detail = store.detailed_cost_summary(measured)
    proof = ledger_proof(store, selection['probes'])
    if proof['actual_committed_bytes'] != sum(row['frame_bytes'] for row in detail['rows']):
        raise ValueError('Scientific ledger length differs from measured frame bytes')
    _compare_anchors(store, selection, references)
    predictions = [frame['payload']['expected']['predictions']['K1'] for frame in store.iter_records()]
    workload = sample_workload(selection['probes'], measured, predictions, spec)
    if model is None:
        if (observations['detail'] != detail or read(run/'proof.json') != proof
                or read(run/'workload.json') != workload):
            raise ValueError('Post-exit raw timing, ledger or workload evidence differs')
    else:
        observations['detail'] = detail
        write(run/'observations.json', observations)
        write(run/'proof.json', proof)
        write(run/'workload.json', workload)
    return {'measured': measured, 'observations': observations, 'proof': proof,
            'workload_by_cell': workload, 'telemetry': telemetry}


def _completed(folder):
    completion = read(folder/'supervisor_completion.json')
    _normal_exit(completion)
    tracked = read(folder/'tracked_process_identities.json')
    if tracked['live_after_cleanup'] != 0:
        raise ValueError('Tracked worker cleanup is incomplete')
    for identity in tracked['identities']:
        try:
            process = psutil.Process(identity['pid'])
            if process.is_running() and process.create_time() == identity['create_time']:
                raise ValueError('A tracked benchmark process is still alive')
        except psutil.NoSuchProcess:
            pass
    phases = {path.name.removesuffix('_receipt.json'): read(path) for path in folder.glob('*_receipt.json')}
    required = {'initial_frozen_source_hash', 'freeze_tail_selection', 'seven_source_extract',
                'tail_repeat_0', 'tail_repeat_1', 'tail_repeat_2', 'final_frozen_source_hash'}
    if (set(phases) != required or any(not value['completed'] for value in phases.values())
            or read(folder/'done.json') != DONE):
        raise ValueError('All three seven-query tail rounds and their original scope must complete')
    return completion, phases


def worker(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v19-tail-'):
        raise ValueError('V19 worker requires its own private namespace')
    request = read(folder/'request.json'); meta = request['metadata']
    watch = ThrottledWatch(folder, request['deadline_utc'])
    try:
        with _phase(folder, 'initial_frozen_source_hash', watch):
            _check_window(request)
            expected_meta, sources = _expected_request()
            if meta != expected_meta or request['sources'] != sources:
                raise ValueError('Worker request differs from the accepted V19 sources and environment')
            verify_bindings(sources, watch)
        args = _selection_args(meta); spec = args[-1]
        with _phase(folder, 'freeze_tail_selection', watch):
            selected = _selection(args, watch)
            write(folder/'frozen_probes.json', selected)
            write(folder/'selection_seal.json', dict(_seal(folder, selected, spec), utc=datetime.now(timezone.utc).isoformat()))
        references = _anchor_references(request, selected)
        model_root = ROOT/meta['independent_model_folder']; database = model_root/'independent.sqlite'
        _check_db(database)
        with _phase(folder, 'seven_source_extract', watch):
            transport = _extract(folder, request, selected, database, watch)
            binding = dict(transport, scope='v19_tail_six_new_one_anchor_engineering_only',
                           transport=describe(folder/'subset_binding.json'))
            write(folder/'v19_subset_binding.json', binding)
        model = read(model_root/'reconstruction.json')['receipt']
        repeats = []
        for index in range(3):
            with _phase(folder, f'tail_repeat_{index}', watch):
                repeats.append(_repeat(folder, request, binding, selected, spec, index,
                    references=references, model=model, database=database, watch=watch))
                _check_db(database)
        compare_repeats(folder, repeats, spec)
        _check_repeat_spans(folder, request)
        summary = summarize_repeats(selected, repeats, spec)
        write(folder/'cost_summary.json', summary)
        with _phase(folder, 'final_frozen_source_hash', watch):
            verify_bindings(request['sources'], watch)
            verify_bindings(binding['sources']+[binding['transport']], watch)
            _check_db(database)
            check_gates()
        write(folder/'done.json', DONE)
    except BaseException as error:
        write(folder/'failure.json', {'error_type': type(error).__name__, 'reserved_test': 'locked',
                                     'full_readback_started': False})
        raise


def _anchor_cost_comparison(selection, repeats, inventory):
    result = {}
    for index, probe in enumerate(selection['probes']):
        if probe['sample_role'] != 'anchor':
            continue
        old = inventory['previous_cell_cost_context']['historical_anchor_cost_comparison']
        values = {name: [] for name in ('verification', 'rank', 'vote_sql_and_accumulation', 'append_without_commit_or_budget', 'core')}
        for repeat in repeats:
            row = repeat['measured']['queries'][index]
            append = repeat['observations']['detail']['budget']['rows'][index]['append_without_commit_or_budget_seconds']
            for name, value in {'verification': row['verification_seconds'], 'rank': row['rank_seconds'],
                                'vote_sql_and_accumulation': row['rank_stages_seconds']['sql_selected_votes_and_accumulation'],
                                'append_without_commit_or_budget': append, 'core': row['verification_seconds']+append}.items():
                values[name].append(value)
        result[probe['cell']] = {}
        for name, samples in values.items():
            historic = old[name]
            current = {'count': 3, 'minimum': min(samples), 'median': statistics.median(samples),
                       'maximum': max(samples), 'range': max(samples)-min(samples)}
            result[probe['cell']][name] = {'old_v6': historic['old_v6'], 'prior_v18': historic['current_v18'],
                'current_v19': current, 'median_difference_from_v18_seconds': current['median']-historic['current_v18']['median']}
    if set(result) != {CELL}:
        raise ValueError('The one old n5 anchor must have a separate temporal cost comparison')
    return result


def _publish(folder):
    folder = folder.resolve()
    if folder.parent != PRIVATE or not folder.name.startswith('knn-v19-tail-'):
        raise ValueError('V19 publication requires its own private namespace')
    namespace = folder.relative_to(ROOT).as_posix()
    existing = read(ROOT/REPORT) if (ROOT/REPORT).exists() else None
    if existing:
        if existing['namespace'] != namespace:
            raise FileExistsError('A different V19 execution already owns the public report')
        verify_bindings(existing['evidence'])
    completion, phases = _completed(folder)
    request = read(folder/'request.json')
    _check_window(request, completion)
    meta, sources = _expected_request()
    if request['metadata'] != meta or request['sources'] != sources:
        raise ValueError('Post-exit request differs from the sealed V19 source contract')
    verify_bindings(sources)
    args = _selection_args(meta); selected, spec = _selection(args), args[-1]
    inventory = read(ROOT/INVENTORY)
    seal = read(folder/'selection_seal.json')
    if (selected != read(folder/'frozen_probes.json') or not seal.get('utc')
            or any(seal.get(k) != v for k, v in _seal(folder, selected, spec).items())):
        raise ValueError('Frozen tail selection or its seal changed')
    references = _anchor_references(request, selected)
    binding = read(folder/'v19_subset_binding.json'); transport = read(folder/'subset_binding.json')
    if binding != dict(transport, scope='v19_tail_six_new_one_anchor_engineering_only',
                       transport=describe(folder/'subset_binding.json')):
        raise ValueError('Reinforcement subset binding differs from the sealed extraction')
    verify_bindings(binding['sources']+[binding['transport']])
    check_index(read(folder/'source_index/manifest.json'), selected['probes'],
                args[1]['V6']['population']['total_queries'], {r['path']: r for r in sources}, ROOT)
    repeats = [_repeat(folder, request, binding, selected, spec, index, references=references) for index in range(3)]
    compare_repeats(folder, repeats, spec)
    _check_repeat_spans(folder, request)
    summary = summarize_repeats(selected, repeats, spec)
    if summary != read(folder/'cost_summary.json'):
        raise ValueError('Post-exit three-repeat timing decomposition differs from saved raw evidence')
    coverage = {'covered_cells': 55, 'uncovered_cells': 0, 'unrepresented_population': 0,
                'distinct_historically_verified_queries': 232, 'distinct_comparable_queries': 170,
                'target_cell_distinct_queries': {CELL: 11}, 'target_tail_distinct_queries': 6,
                'new_distinct_queries': 6, 'reused_anchor_queries': 1, 'new_engineering_checks': 21}
    if coverage != spec['conditional_after_all_verified']:
        raise ValueError('Verified tail counts differ from the frozen conditional scope')
    verify_bindings(sources)
    verify_bindings(binding['sources']+[binding['transport']])
    gates = check_gates()
    if gates != spec['this_step']['gates']:
        raise ValueError('Original scientific gates changed')
    audit = {'independent_selection_matches': True, 'three_ledgers_byte_identical': True,
             'original_n5_anchor_payload_matches_every_repeat': True, 'post_exit_costs_recomputed': True,
             'post_exit_telemetry_recomputed': True, 'post_exit_sources_and_limits_verified': True,
             'tracked_processes_stopped': True, 'new_historical_overlap': 0}
    if (folder/'post_exit_audit.json').exists():
        if read(folder/'post_exit_audit.json') != audit:
            raise ValueError('Existing immutable audit differs')
    else:
        write(folder/'post_exit_audit.json', audit)
    public_repeats = []
    for index, result in enumerate(repeats):
        measured = result['measured']
        public_repeats.append({'repeat_index': index, 'proof': result['proof'],
            'workload_by_cell': result['workload_by_cell'], 'telemetry': result['telemetry'],
            'setup_seconds': measured['setup_seconds'], 'tail_flush_and_eof_seal_seconds': measured['tail_flush_and_eof_seal_seconds'],
            'all_chunk_commit_seconds': sum(event['seconds'] for event in measured['chunk_commits'])})
    report = {'status': 'v19_tail_6_new_1_anchor_measured_three_times',
              'created_utc': existing['created_utc'] if existing else datetime.now(timezone.utc).isoformat(),
              'namespace': namespace, 'environment': environment(), 'supervisor': completion, 'phases': phases,
              'sources_bound': len(sources), 'sources_reverified_before_after_and_post_exit': True,
              'selection_sha256': seal['selection']['sha256'], 'specification': seal['specification'],
              'inventory': seal['inventory'], 'repeats': public_repeats, 'summary': summary,
              'anchor_historical_cost_comparison': _anchor_cost_comparison(selected, repeats, inventory),
              'historical_anchor_interpretation': 'The same V6/V18/V19 scientific identity in different machine windows; descriptive temporal differences only, not an optimization speedup estimate.',
              'sampling_interpretation': 'Six deliberate tail identities: one maximum-neighbor and one fixed-hash remainder in each registered band. Roles and bands remain separate. No population-weighted tail, whole-cell, or all-grid runtime projection is authorized.',
              'telemetry_interpretation': 'Read-only 200ms target background observations span each verifier including setup, queries, append and tail. Sampler scheduling/CPU overhead is part of the environment, not an additional timer to sum. Only repeat-level associations are available; no per-query attribution or Ollama causality is established.',
              'coverage': coverage, 'scope': {'new_keys': 6, 'reused_anchor_keys': 1, 'queries_per_repeat': 7,
                'fresh_repeats': 3, 'new_engineering_verifications': 21, 'new_primary_fits': 0,
                'new_primary_validation_runs': 0, 'new_primary_bootstrap': 0, 'SQL_candidate_runs': 0,
                'full_readback_started': False, 'full_validation_complete': False, 'reserved_test': 'locked'},
              'gates': gates, 'T_plan': None,
              'evidence': [describe(path) for path in sorted(folder.rglob('*')) if path.is_file()]}
    if existing is None:
        public_json(ROOT/REPORT, report, exclusive=True)
    elif existing != report:
        raise ValueError('Re-audit differs from the immutable published V19 report')
    print({'report': REPORT, 'namespace': namespace, 'seconds': completion['seconds'], 'coverage': coverage})
    return report


def publish(folder):
    with _exclusive():
        return _publish(Path(folder))


def supervise():
    with _exclusive():
        if (ROOT/REPORT).exists():
            raise FileExistsError('Use --publish to re-audit the existing V19 result')
        meta, sources = _expected_request()
        for request in PRIVATE.glob('knn-v19-tail-*/request.json'):
            raise FileExistsError('Review the existing V19 window before any new execution: '+str(request.parent))
        folder = PRIVATE/('knn-v19-tail-'+uuid4().hex)
        print('V19 supervised window: '+folder.relative_to(ROOT).as_posix(), flush=True)
        receipt = run_window(folder, [sys.executable, '-B', '-m', MODULE, '--worker', str(folder)],
                             sources, 'joint_tail', metadata=meta, budget_seconds=1800, limits=LIMITS)
        _normal_exit(receipt)
        return _publish(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance', action='store_true')
    modes.add_argument('--measure', action='store_true')
    modes.add_argument('--publish', type=Path)
    modes.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.acceptance:
        acceptance()
    elif args.measure:
        supervise()
    elif args.publish:
        publish(args.publish)
    else:
        worker(args.worker)
