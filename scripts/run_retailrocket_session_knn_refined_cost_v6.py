"""Three bounded repeats of the ORIGINAL V5 48 queries; never full readback.

Run --acceptance before --measure. Each measurement uses a new supervised
namespace, hashes the inherited source inventory before/after, and publishes
only aggregate cost/coverage after a separately observed normal worker exit.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import unittest
import uuid

import psutil

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, read, write, describe, verify_bindings, environment, check_gates)
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_refined_cost_v6 import refine_roster, summarize_refined


MODULE = 'scripts.run_retailrocket_session_knn_refined_cost_v6'
PARENT = 'reports/stage12/retailrocket_session_knn_v5_ledger_replay_cost_20261103.json'
JOINT = 'reports/stage12/retailrocket_session_knn_v5_joint_cost_20261103.json'
ACCEPT = 'reports/stage12/retailrocket_session_knn_v6_refined_acceptance_20261103.json'
REPORT = 'reports/stage12/retailrocket_session_knn_v6_refined_cost_20261103.json'
METHODS = ('scripts/retailrocket_session_knn_detailed_cost_v6.py',
           'scripts/retailrocket_session_knn_refined_cost_v6.py',
           'scripts/run_retailrocket_session_knn_refined_cost_v6.py',
           'tests/test_retailrocket_session_knn_detailed_cost_v6.py',
           'tests/test_retailrocket_session_knn_refined_cost_v6.py')
SUITES = ('tests.test_retailrocket_session_knn_detailed_cost_v6',
          'tests.test_retailrocket_session_knn_refined_cost_v6',
          'tests.test_retailrocket_session_knn_checkpoint_cost_v5',
          'tests.test_retailrocket_session_knn_pair_v4')
REPEATS = 3


def acceptance():
    folder = ROOT/'shop-mysql-runtime/verification'/('v6-refined-acceptance-'+uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES)
    with (folder/'unittest.log').open('x', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:
        raise ValueError('Synthetic acceptance failed; inspect private unittest.log')
    report = {'status': 'v6_refined_cost_tools_synthetic_accepted',
              'created_utc': datetime.now(timezone.utc).isoformat(), 'environment': environment(),
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'seconds': time.perf_counter()-start,
              'suites': list(SUITES), 'method_files': [describe(ROOT/name) for name in METHODS],
              'log': describe(folder/'unittest.log'), 'real_query_measurement_started': False,
              'full_readback_started': False, 'reserved_test': 'locked', 'T_plan': None}
    write(ROOT/ACCEPT, report)
    print(json.dumps({k: report[k] for k in ('status', 'tests_run', 'seconds')}))


def _normal_exit(receipt):
    if (receipt['exit_code'] != 0 or receipt['stop_reason'] is not None
            or receipt['supervisor_error'] is not None or receipt['actual_exit_observed_utc'] is None
            or receipt['tracked_processes_alive_after_cleanup'] != 0):
        raise ValueError('A supervised normal worker exit is required')


def _proof(store, frozen):
    recovered = store.recover()
    if (recovered['records'] != 48 or len(frozen['probes']) != 48
            or store.get_stage('queries') != {'queries': 48, 'paired_streams_eof_checked': True}
            or read(store.folder/'stages/queries.json')['ledger'] != recovered
            or any((store.folder/name).exists() for name in ('candidate.json', 'acceptance.json'))):
        raise ValueError('A sealed bounded subset is required, without full acceptance')
    digest = hashlib.sha256(); count = size = 0
    for manifest in sorted((store.folder/'chunks').glob('*.json')):
        record = read(manifest)
        with (store.folder/record['payload']['path']).open('rb') as stream:
            for line in stream:
                row = json.loads(line)
                if (row['ordinal'] != count or row['key'] != frozen['probes'][count]['key']
                        or row['payload']['expected']['key'] != row['key']):
                    raise ValueError('Committed ledger differs from the frozen sample')
                digest.update(line); count += 1; size += len(line)
    return {'records': count, 'actual_committed_bytes': size,
            'actual_committed_payload_sha256': digest.hexdigest(), 'checkpoint_chain_checked': True}


def _same_payload(actual, original):
    if any(actual[k] != original[k] for k in ('records', 'actual_committed_bytes', 'actual_committed_payload_sha256')):
        raise ValueError('The original frozen sample scientific ledger bytes changed')


def worker(folder):
    from scripts.retailrocket_session_knn_pair_v4 import verify_selected
    request = read(folder/'request.json'); metadata = request['metadata']
    watch = ThrottledWatch(folder, request['deadline_utc']); phases = {}

    def timed(name, action):
        write(folder/(name+'_started.json'), {'phase': name, 'utc': datetime.now(timezone.utc).isoformat()})
        start = time.perf_counter(); completed = False
        try:
            watch.force(); value = action(); watch.force(); completed = True
            return value
        finally:
            phases[name] = {'completed': completed, 'seconds': time.perf_counter()-start}
            write(folder/(name+'_receipt.json'), phases[name])

    try:
        timed('initial_frozen_source_hash', lambda: verify_bindings(request['sources'], watch))
        check_gates()
        if metadata['environment'] != environment():
            raise ValueError('Frozen environment changed')
        frozen = read(ROOT/metadata['joint_frozen_probes'])
        if len(frozen['probes']) != 48:
            raise ValueError('Only the original 48 frozen V5 queries may be repeated')
        refined = timed('refine_existing_structural_roster', lambda: refine_roster(
            ROOT/metadata['joint_roster'], frozen, watch))
        # Seal the structural policies and coverage BEFORE any new query timing.
        write(folder/'frozen_refinements.json', refined)
        selected = ROOT/metadata['joint_raw_selected_inputs']; config = read(selected/'configuration.json')
        ordinals = read(selected/'ordinals.json'); old_run = read(ROOT/metadata['joint_verified_run'])
        model_root = ROOT/metadata['independent_model_folder']
        model = read(model_root/'reconstruction.json')['receipt']; database = model_root/'independent.sqlite'
        if any(Path(str(database)+suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('Sealed independent model has a journal')
        original = read(ROOT/metadata['joint_original_ledger_proof'])
        results = []
        for repeat in range(REPEATS):
            def measure():
                store = DetailedTimedStore.create(folder/f'repeat_{repeat}'/'verified_subset',
                    {'sources': old_run['binding']['sources'], 'configuration': config,
                     'scope': 'same_original_48_detailed_cost_only'},
                    request['deadline_utc'], request['budget_seconds'], source_root=ROOT,
                    expected_queries=48, required_stages=('reconstruction', 'queries'))
                with store.writer():
                    store.seal_stage('reconstruction', {'kind': 'reused_v5_reconstructed_model',
                                                        'fit_audit': model['fit_audit']})
                    measured = verify_selected(selected/'primary',
                        {key: selected/key for key in ('dataset', 'P0', 'C1', 'D1')},
                        config, store, model, database, ordinals, watch)
                detail = store.detailed_cost_summary(measured)
                proof = _proof(store, frozen); _same_payload(proof, original)
                if proof['actual_committed_bytes'] != sum(e['frame_bytes'] for e in store.append_events):
                    raise ValueError('Observed encoded frame lengths differ from physical ledger bytes')
                summary = summarize_refined(refined, frozen, measured, detail['budget'])
                write(folder/f'repeat_{repeat}'/'measurements.json', measured)
                write(folder/f'repeat_{repeat}'/'observations.json', {'detail': detail,
                    'append_events': store.append_events, 'budget_events': store.budget_events})
                write(folder/f'repeat_{repeat}'/'proof.json', proof)
                write(folder/f'repeat_{repeat}'/'summary.json', summary)
                return {'proof': proof, 'summary': summary}
            results.append(timed(f'same_48_repeat_{repeat}', measure))
        timed('final_frozen_source_hash', lambda: verify_bindings(request['sources'], watch))
        check_gates()
        write(folder/'measurement_result.json', {'phases': phases, 'completed_repeats': len(results),
              'new_independent_repeat_query_checks': 48*len(results), 'new_distinct_query_keys': 0,
              'full_readback_started': False, 'reserved_test': 'locked', 'T_plan': None})
    except BaseException as error:
        write(folder/'failure.json', {'error_type': type(error).__name__, 'full_readback_started': False,
                                     'reserved_test': 'locked', 'T_plan': None})
        raise
    finally:
        write(folder/'watch_statistics.json', {'calls': watch.calls, 'full_checks': watch.full_checks})


def _aggregate_repeat(folder, refined, frozen, request):
    measured = read(folder/'measurements.json'); observations = read(folder/'observations.json')
    run = read(folder/'verified_subset/run.json')
    if run['deadline_utc'] != request['deadline_utc'] or run['budget_seconds'] != request['budget_seconds']:
        raise ValueError('Original absolute deadline/budget must not reset between repeats')
    store = DetailedTimedStore.open(folder/'verified_subset', run['binding'], source_root=ROOT)
    store.append_events = observations['append_events']; store.budget_events = observations['budget_events']
    store.commit_events = measured['chunk_commits']
    detail = store.detailed_cost_summary(measured)
    if detail != observations['detail']:
        raise ValueError('Saved observation summary differs from raw events')
    proof = _proof(store, frozen)
    if proof != read(folder/'proof.json'):
        raise ValueError('Post-exit ledger proof differs')
    _same_payload(proof, read(ROOT/request['metadata']['joint_original_ledger_proof']))
    summary = summarize_refined(refined, frozen, measured, detail['budget'])
    if summary != read(folder/'summary.json'):
        raise ValueError('Saved stratification costs differ from measured rows')
    components = {}
    stages = {}
    for part in detail['rows']:
        for name, value in part['append_exclusive_seconds'].items():
            components[name] = components.get(name, 0.)+value
    for row in measured['queries']:
        for name, value in row['rank_stages_seconds'].items():
            stages[name] = stages.get(name, 0.)+value
    return {'proof': proof, 'refinement_sensitivity': summary,
            'sample_totals_seconds': {
                'verification': sum(row['verification_seconds'] for row in measured['queries']),
                'rank_nested_in_verification': sum(row['rank_seconds'] for row in measured['queries']),
                'verification_other': sum(row['verification_other_seconds'] for row in detail['rows']),
                'append_including_nested_commit': sum(row['checkpoint_append_seconds'] for row in measured['queries']),
                'append_exclusive_components': components,
                'rank_nested_stage_totals': stages,
                'all_chunk_commits_including_final_flush': sum(c['seconds'] for c in measured['chunk_commits']),
                'setup': measured['setup_seconds'], 'tail_flush_eof_and_seal': measured['tail_flush_and_eof_seal_seconds']},
            'budget': {key: detail['budget'][key] for key in ('writes', 'budget_seconds', 'by_context')}}


def publish(folder):
    request = read(folder/'request.json'); completion = read(folder/'supervisor_completion.json')
    _normal_exit(completion)
    identities = read(folder/'tracked_process_identities.json')['identities']
    for identity in identities:
        try:
            process = psutil.Process(identity['pid'])
            if process.is_running() and process.create_time() == identity['create_time']:
                raise ValueError('A tracked process is still alive')
        except psutil.NoSuchProcess:
            pass
    frozen = read(ROOT/request['metadata']['joint_frozen_probes'])
    refined = refine_roster(ROOT/request['metadata']['joint_roster'], frozen)
    if refined != read(folder/'frozen_refinements.json'):
        raise ValueError('Frozen structural refinement changed')
    result = read(folder/'measurement_result.json')
    phases = {p.name.removesuffix('_receipt.json'): read(p) for p in folder.glob('*_receipt.json')}
    if (result['completed_repeats'] != REPEATS or result['phases'] != phases
            or len(phases) != REPEATS+3 or any(not p['completed'] for p in phases.values())):
        raise ValueError('Complete repeats and initial/final preservation receipts are required')
    repeats = [_aggregate_repeat(folder/f'repeat_{i}', refined, frozen, request) for i in range(REPEATS)]
    ranges = {}
    for policy in refined['cells']:
        costs = [r['refinement_sensitivity']['policies'][policy]['scenarios']
                 ['verify_append_without_direct_budget']['total_with_explicit_parent_fallback_seconds'] for r in repeats]
        coverage = repeats[0]['refinement_sensitivity']['policies'][policy]
        ranges[policy] = {'minimum_seconds': min(costs), 'median_seconds': statistics.median(costs),
                          'maximum_seconds': max(costs), 'nonempty_cells': coverage['nonempty_cells'],
                          'sample_covered_population': coverage['sample_covered_population'],
                          'uncovered_population': coverage['uncovered_population']}
    write(folder/'post_exit_audit.json', {'all_tracked_identities_stopped': True,
          'records_per_repeat': 48, 'all_three_payloads_equal_original': True,
          'raw_events_and_cost_summaries_recomputed': True})
    report = {'status': 'v6_same_fixed_48_refined_cost_measured', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'namespace': folder.relative_to(ROOT).as_posix(), 'supervisor': completion,
              'sources_bound': len(request['sources']), 'sources_reverified_before_after': True,
              'environment': request['metadata']['environment'], 'phases': phases,
              'refinement_policy': {key: refined[key] for key in ('neighbor_inclusive_upper_bounds',
                  'vote_inclusive_upper_bounds', 'tail_bin', 'targets_or_predictions_used', 'roster_sha256')},
              'scenario_ranges_seconds': ranges, 'repeats': repeats,
              'scope': {'structural_population': refined['total_queries'], 'original_sample_keys': 48,
                        'repeats': REPEATS, 'new_independent_repeat_query_checks': REPEATS*48,
                        'new_distinct_query_keys': 0, 'new_primary_fits': 0, 'new_primary_validation_runs': 0,
                        'new_primary_bootstrap': 0, 'full_readback_started': False, 'reserved_test': 'locked'},
              'decision': 'do_not_start_full_readback', 'T_plan': None, 'gates': check_gates(),
              'interpretation': 'Three new namespaces retain the same original fixed sample and scientific bytes. '
                  'Ranks/stages are nested in verification; append parts conserve raw cost, including observer overhead. '
                  'Refinements are frozen before timing, use structural rows only, and explicitly expose unsampled cells. '
                  'Parent fallback fills only a conditional sensitivity scenario, never evidence for unsampled cells. '
                  'Repeats/cache/system states are uncontrolled. No causal speedup, runtime bound or full T_plan.',
              'privacy': 'Keys, ordinal rosters, per-query timings/effects and model contents remain ignored. '
                         'Only aggregate workload/cost/coverage and artifact descriptors are published.',
              'evidence': [describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]}
    write(ROOT/REPORT, report)
    print(json.dumps({'report': REPORT, 'supervisor': completion, 'scenario_ranges_seconds': ranges}))


def supervise():
    preflight_started = time.perf_counter()
    check_gates()
    accepted = read(ROOT/ACCEPT)
    if (accepted['status'] != 'v6_refined_cost_tools_synthetic_accepted'
            or {r['path'] for r in accepted['method_files']} != set(METHODS)
            or accepted['environment'] != environment()):
        raise ValueError('Current methods/environment must pass synthetic acceptance first')
    verify_bindings(accepted['method_files'])
    parent = read(ROOT/PARENT)
    prior_request = next(r for r in parent['evidence'] if r['path'].endswith('/request.json'))
    prior_exit = next(r for r in parent['evidence'] if r['path'].endswith('/supervisor_completion.json'))
    verify_bindings([prior_request, prior_exit]); _normal_exit(read(ROOT/prior_exit['path']))
    prior = read(ROOT/prior_request['path'])
    metadata = {key: prior['metadata'][key] for key in ('environment', 'joint_frozen_probes',
        'joint_raw_selected_inputs', 'joint_verified_run', 'joint_original_ledger_proof', 'independent_model_folder')}
    if metadata['environment'] != environment() or not parent['sources_reverified_before_after']:
        raise ValueError('Preserved source and environment evidence required')
    records = {r['path']: r for r in prior['sources']}
    joint = read(ROOT/JOINT); evidence = {r['path']: r for r in joint['evidence']}
    roster = metadata['joint_frozen_probes'].rsplit('/', 1)[0]+'/joint_roster.jsonl'
    records[roster] = evidence[roster]
    for record in [prior_request, prior_exit, *accepted['method_files'], describe(ROOT/ACCEPT),
                   describe(ROOT/PARENT), describe(ROOT/JOINT)]:
        records[record['path']] = record
    metadata.update(joint_roster=roster, repeats=REPEATS,
                    preflight_seconds_before_window=time.perf_counter()-preflight_started,
                    authorization='細化既有結構分層與查詢/append拆帳；原48筆三次重測，0新keys/主要執行/全量/預留測試')
    folder = ROOT/'shop-mysql-runtime/verification'/('knn-v6-refined-'+uuid.uuid4().hex)
    receipt = run_window(folder, [sys.executable, '-B', '-m', MODULE, '--worker', str(folder)],
                         [records[k] for k in sorted(records)], 'joint_tail', metadata=metadata)
    _normal_exit(receipt)
    publish(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance', action='store_true')
    modes.add_argument('--measure', action='store_true')
    modes.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    modes.add_argument('--publish', type=Path)
    args = parser.parse_args()
    if args.acceptance:
        acceptance()
    elif args.measure:
        supervise()
    elif args.worker:
        worker(args.worker)
    else:
        publish(args.publish)
