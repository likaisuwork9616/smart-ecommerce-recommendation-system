"""Read-only reconciliation of rejected SQL candidates and engineering costs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings, environment, check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.run_retailrocket_session_knn_vote_v7 import schedule
from scripts.retailrocket_session_knn_priority_v23 import summarize_run, summarize_window

BASE = 'reports/stage12/retailrocket_session_knn_v23_priority_'
INVENTORY = BASE+'inventory_20261109.json'
INVENTORY_SHA = '7cbc1fc4dbb33587674e1386d2ecd2010ecf67317b905976bf377f92a4bcc4de'
REPORT = BASE+'costs_20261109.json'
METHODS = ('scripts/retailrocket_session_knn_priority_v23.py',
           'scripts/summarize_retailrocket_session_knn_priority_v23.py',
           'tests/test_retailrocket_session_knn_priority_v23.py')
SUITES = ('tests.test_retailrocket_session_knn_priority_v23',
          'tests.test_retailrocket_session_knn_detailed_cost_v6',
          'tests.test_retailrocket_session_knn_vote_comparison_v7')


def frames(folder):
    for path in sorted((folder/'chunks').glob('*.json')):
        record = read(path)
        with (folder/record['payload']['path']).open('rb') as stream:
            yield from stream


def sealed_store(folder, binding):
    # This audit verifies saved ledger chains and the inventory's small files.
    # It explicitly does not certify the original large data/model again.
    return DetailedTimedStore.open(folder, binding, source_root=ROOT,
                                  external_source_verifier=lambda: None)


def summarize():
    if (ROOT/REPORT).exists():
        raise FileExistsError('An immutable V23 cost reconciliation already exists')
    if describe(ROOT/INVENTORY)['sha256'] != INVENTORY_SHA:
        raise ValueError('Expected the sealed V23 evidence inventory')
    inventory = read(ROOT/INVENTORY)
    verify_bindings(inventory['verified_inputs'])
    gates = check_gates()
    if gates != inventory['gates'] or environment() != inventory['environment']:
        raise ValueError('Original environment or locked gates changed')
    methods = [describe(ROOT/name) for name in METHODS]
    folder = PRIVATE/('knn-v23-priority-audit-'+uuid4().hex)
    folder.mkdir()
    start = perf_counter()
    with (folder/'tests.log').open('x', encoding='utf-8') as log:
        tests = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not tests.testsRun or not tests.wasSuccessful() or tests.skipped:
        print((folder/'tests.log').read_text(encoding='utf-8'), file=sys.stderr)
        raise ValueError('Cost conservation and paired decision checks failed')
    acceptance = dict(tests_run=tests.testsRun, failures=0, errors=0, skipped=0,
                      seconds=perf_counter()-start, suites=list(SUITES), log=describe(folder/'tests.log'))
    comparisons = {}
    reference_frames = None
    for version, item in inventory['comparisons'].items():
        report = read(ROOT/item['report']['path'])
        request = read(ROOT/item['namespace']/'request.json')
        cohort = item['cohort']
        probes = read(ROOT/cohort['probes'])['probes']
        reference = read(ROOT/cohort['reference'])
        binding = read(ROOT/cohort['old_run'])['binding']
        source_root = (ROOT/cohort['old_run']).parent
        original = sealed_store(source_root, binding)
        proof = ledger_proof(original, probes)
        scientific_fields = ('records', 'actual_committed_bytes', 'actual_committed_payload_sha256')
        if any(proof[k] != reference[k] for k in scientific_fields) or len(probes) != 48:
            raise ValueError('Original fixed48 ledger or roster differs')
        current_reference = list(frames(source_root))
        if reference_frames is not None and current_reference != reference_frames:
            raise ValueError('The two comparisons do not share the same physical reference')
        reference_frames = current_reference
        runs, reference_workload = {}, None
        for label, mode in schedule('compare48', item['candidate']):
            run = ROOT/item['namespace']/label
            contract = read(run/'verified_subset/run.json')
            if (contract['binding'] != binding or contract['expected_queries'] != 48
                    or any(contract[k] != request[k] for k in ('deadline_utc', 'budget_seconds'))):
                raise ValueError('Historical run changed fixed48, binding or original clock')
            store = sealed_store(run/'verified_subset', binding)
            current = ledger_proof(store, probes)
            if (current != read(run/'proof.json')
                    or any(current[k] != reference[k] for k in scientific_fields)):
                raise ValueError('Historical ledger proof differs from the original reference')
            if list(frames(run/'verified_subset')) != reference_frames:
                raise ValueError('Full scientific payload bytes changed')
            m, o, e = (read(run/name) for name in ('measured.json', 'observations.json', 'entry.json'))
            if e['label'] != label or e['mode'] != mode:
                raise ValueError('Historical run mode or order changed')
            if read(run/'profile.json'):
                raise ValueError('Detailed SQL profiling was enabled in a timed comparison')
            workload = [q['sql_workload'] for q in m['queries']]
            if reference_workload is not None and workload != reference_workload:
                raise ValueError('Historical candidate changed logical workload')
            reference_workload = workload
            runs[label] = summarize_run(m, o, e, probes)
        window = summarize_window(report, runs)
        if window['decision']['supports_candidate']:
            raise ValueError('This inventory concerns the two rejected candidates only')
        window.update(candidate=item['candidate'], report=item['report'], runs=runs,
            source_closure_count=item['source_closure_count'], source_closure_bytes=item['source_closure_bytes'],
            binding_source_count=item['binding_source_count'], binding_source_bytes=item['binding_source_bytes'],
            reference_payload_bytes=reference['actual_committed_bytes'],
            baseline_contract='Native original V4; before/after resource snapshots' if version=='V17' else
                'Symmetric A/B SQL adapters; continuous telemetry across each complete entry',
            source_verification_structure={
                'basis':'Inferred from sealed source control flow, not a runtime count of source reads',
                'measured_window_closure_passes':2, 'publisher_closure_passes_without_wall_timer':2,
                'entry_binding_passes_per_fresh_run':2,
                'entry_binding_passes_all_14_runs':28,
                'publisher_binding_passes_from_14_store_opens':14,
                'window_closure_logical_hash_bytes':2*item['source_closure_bytes'],
                'publisher_closure_logical_hash_bytes':2*item['source_closure_bytes'],
                'entry_binding_logical_hash_bytes':28*item['binding_source_bytes'],
                'publisher_binding_logical_hash_bytes':14*item['binding_source_bytes'],
                'caution':'Repeated logical byte coverage is not unique bytes, physical disk I/O or measured per-pass latency. '
                    'Create validates input at setup; writer rechecks after lock. Publisher independently reopens ledgers. '
                    'These boundaries must be preserved or replaced with an explicitly validated equivalent.'})
        comparisons[version] = window
    verify_bindings([*inventory['verified_inputs'], *methods])
    if check_gates() != gates:
        raise ValueError('Scientific gates changed during saved-evidence reconciliation')
    result = {'status':'v23_rejected_candidates_and_costs_reconciled',
        'created_utc':datetime.now(timezone.utc).isoformat(), 'inventory':describe(ROOT/INVENTORY),
        'methods':methods, 'synthetic_acceptance':acceptance, 'comparisons':comparisons,
        'all_28_historical_ledgers_and_1344_payloads_match_reference':True,
        'new_query_verifications':0, 'new_candidate_runs':0,
        'large_model_or_raw_data_rehashed':False,
        'interpretation':'Recomputed original known-validation engineering observations. Every window and mode is separate. '
            'Do not pool candidate effects across V17/V22, project these batch costs to full validation, '
            'interpret source descriptors as physical I/O, or treat inferred pass counts as newly instrumented timings.',
        'scope':inventory['scope'], 'gates':gates, 'T_plan':None}
    public_json(ROOT/REPORT, result, exclusive=True)
    print(json.dumps({'report':REPORT,'tests':tests.testsRun,'historical_ledgers':28,
        'candidate_decisions':{v:r['decision']['median_saving_percent'] for v,r in comparisons.items()},
        'window_parts':{v:r['window_exclusive_seconds'] for v,r in comparisons.items()}}))


if __name__ == '__main__':
    summarize()
