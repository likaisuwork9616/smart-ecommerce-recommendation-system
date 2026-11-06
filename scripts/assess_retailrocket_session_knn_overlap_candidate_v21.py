"""Assess synthetic semantics and real-model plans, never candidate real ranking.

Requires the completed V21 six-round diagnosis and the previously sealed scope.
The candidate remains unadopted; performance needs a separate paired experiment.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import statistics
import sys
from time import perf_counter
import unittest
from uuid import uuid4

from scripts import retailrocket_session_knn_overlap_candidate_v21 as candidate
from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, read, write, describe, verify_bindings, check_gates, environment)
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json, _record
from scripts.run_retailrocket_session_knn_guards_v21 import SPEC, SPEC_SHA256, REPORT as COST

REPORT = 'reports/stage12/retailrocket_session_knn_v21_guards_sql_assessment_20261106.json'
ANALYSIS = 'reports/stage12/retailrocket_session_knn_v21_guards_analysis_20261106.json'
PREVIOUS = 'reports/stage12/retailrocket_session_knn_v17_vote_compare48_20261106.json'
METHODS = ('scripts/retailrocket_session_knn_overlap_candidate_v21.py',
           'scripts/assess_retailrocket_session_knn_overlap_candidate_v21.py',
           'tests/test_retailrocket_session_knn_overlap_candidate_v21.py')
SUITES = ('tests.test_retailrocket_session_knn_overlap_candidate_v21',
          'tests.test_retailrocket_session_knn_sql_v4',
          'tests.test_retailrocket_session_knn_diagnostics_sql_v20')


def assess():
    if (ROOT/REPORT).exists():
        raise FileExistsError('The immutable SQL assessment already exists')
    if describe(ROOT/SPEC)['sha256'] != SPEC_SHA256:
        raise ValueError('Original V21 assessment scope changed')
    cost = read(ROOT/COST)
    if (cost['status'] != 'v21_same_seven_reference_diagnostics_six_rounds_measured'
            or cost['scope']['new_engineering_verifications'] != 42
            or cost['sources_reverified_before_after_and_post_exit'] is not True):
        raise ValueError('Complete the accepted diagnosis before SQL assessment')
    request_record = _record(cost['evidence'], '/request.json')
    verify_bindings([request_record])
    request = read(ROOT/request_record['path'])
    inherited = {r['path']: r for r in request['sources']}
    model_path = Path(request['metadata']['model_root'])/'independent.sqlite'
    model_record = inherited[model_path.as_posix()]
    immutable = [inherited[name] for name in (
        'scripts/retailrocket_session_knn_sql_v4.py',
        'scripts/retailrocket_session_knn_sql_v2.py',
        'scripts/retailrocket_session_knn_readback.py',
        'scripts/retailrocket_session_knn_diagnostics_v20.py',
        'tests/test_retailrocket_session_knn_sql_v4.py',
        'tests/test_retailrocket_session_knn_diagnostics_sql_v20.py')]
    inputs = [describe(ROOT/name) for name in (SPEC, COST, ANALYSIS, PREVIOUS, *METHODS)]
    inputs += [request_record, model_record, *immutable]
    verify_bindings(inputs)
    gates = check_gates()
    if gates != cost['gates']:
        raise ValueError('Scientific gates changed after the diagnosis')
    folder = PRIVATE/('knn-v21-overlap-assessment-'+uuid4().hex)
    folder.mkdir()
    print('SQL assessment: '+folder.relative_to(ROOT).as_posix(), flush=True)
    start = perf_counter()
    with (folder/'tests.log').open('x', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not result.wasSuccessful() or result.skipped or result.testsRun != 24:
        print((folder/'tests.log').read_text(encoding='utf-8'), file=sys.stderr)
        raise ValueError('Candidate semantics must pass all 24 synthetic checks')
    acceptance = {'tests_run': result.testsRun, 'failures': 0, 'errors': 0, 'skipped': 0,
                  'seconds': perf_counter()-start, 'suites': list(SUITES),
                  'log': describe(folder/'tests.log'), 'timing_is_performance_evidence': False}
    path = ROOT/model_path
    siblings_before = sorted(p.name for p in path.parent.iterdir())
    plans = {}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('CREATE TEMP TABLE k1_v4_history (i TEXT PRIMARY KEY) WITHOUT ROWID')
        db.execute('PRAGMA query_only=ON')
        schema = [{'type': t, 'name': n, 'sql': sql} for t, n, sql in db.execute(
            "SELECT type,name,sql FROM main.sqlite_schema WHERE name IN ('m','k1_v2_sizes','k1_v2_posting') ORDER BY name")]
        columns = list(db.execute('PRAGMA main.table_info(k1_v2_sizes)'))
        primary = [row[1] for row in sorted(columns, key=lambda r: r[5]) if row[5]]
        if primary != ['v', 's']:
            raise ValueError('Candidate requires the sealed unique session-size primary key')
        for name, sql in (('original', candidate.OVERLAP_SQL), ('group_before_size_join', candidate.CANDIDATE_SQL)):
            plans[name] = [dict(id=row[0], parent=row[1], auxiliary=row[2], detail=row[3])
                           for row in db.execute('EXPLAIN QUERY PLAN '+sql)]
        if db.execute('PRAGMA query_only').fetchone() != (1,):
            raise ValueError('Plan inspection must remain query-only')
    if sorted(p.name for p in path.parent.iterdir()) != siblings_before:
        raise ValueError('Unexpected model directory side effect')
    original = [r['detail'] for r in plans['original']]
    rewritten = [r['detail'] for r in plans['group_before_size_join']]
    if (not all(any('k1_v2_posting' in line for line in plan) for plan in (original, rewritten))
            or not any('CO-ROUTINE hits' in line for line in rewritten)
            or not all(any('sizes' in line and 'PRIMARY KEY' in line and 'LEFT-JOIN' in line for line in plan)
                       for plan in (original, rewritten))
            or next(i for i, line in enumerate(rewritten) if 'GROUP BY' in line) >=
               next(i for i, line in enumerate(rewritten) if 'LEFT-JOIN' in line)):
        raise ValueError('Observed real-model plan does not support the stated hypothesis')
    diagnostic_counts = [row['diagnostics']['sql_counts'] for row in cost['rounds'] if row['mode'] == 'D']
    if any(c != diagnostic_counts[0] for c in diagnostic_counts):
        raise ValueError('Reused seven-query logical workload changed')
    counts = diagnostic_counts[0]
    matches, groups = counts['intersection_sum'], counts['returned_rows']
    timing = [{'case': label, 'eligible_neighbors': row['eligible_neighbors'],
               'original_overlap_median_seconds': row['by_mode']['R']['seconds']['positive_overlap_inclusive']['median'],
               'original_core_median_seconds': row['by_mode']['R']['seconds']['core']['median']}
              for label, row in cost['summary']['fixed_cases']['cases'].items()]
    verify_bindings(inputs)
    if check_gates() != gates:
        raise ValueError('Scientific gates changed during assessment')
    prior = read(ROOT/PREVIOUS)
    report = {'status': 'v21_overlap_candidate_synthetic_and_plan_assessed_not_adopted',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'environment': environment(),
        'sqlite_version': sqlite3.sqlite_version, 'specification': describe(ROOT/SPEC),
        'diagnostic_cost': describe(ROOT/COST), 'diagnostic_analysis': describe(ROOT/ANALYSIS),
        'method_files': [describe(ROOT/name) for name in METHODS], 'inputs_verified_before_after': inputs,
        'synthetic_acceptance': acceptance, 'actual_model': model_record,
        'model_bytes_verified_before_after': True, 'model_directory_names_unchanged': True,
        'actual_model_plan_only': True, 'history_for_plan': 'empty in-memory TEMP table; no source identities loaded',
        'schema': schema, 'session_size_primary_key': primary, 'plans': plans,
        'original_sql': candidate.OVERLAP_SQL, 'candidate_sql': candidate.CANDIDATE_SQL,
        'logical_join_opportunity': {'fixed_queries': 7, 'posting_matches': matches,
            'positive_groups': groups, 'logical_repeated_size_joins_avoided': matches-groups,
            'logical_join_input_reduction_percent': (matches-groups)/matches*100,
            'interpretation': 'Derived from original sealed workload and plan shape; not measured candidate VM steps, reads, time or speedup.'},
        'original_cost_context': {'fixed_cases': timing,
            'mean_of_per_query_overlap_medians_seconds': statistics.mean(x['original_overlap_median_seconds'] for x in timing),
            'mean_of_per_query_core_medians_seconds': statistics.mean(x['original_core_median_seconds'] for x in timing)},
        'prior_vote_candidate': {'report': describe(ROOT/PREVIOUS), 'name': prior['candidate'],
            'decision': prior['decision'], 'protocol': prior['protocol'], 'rejection_unchanged': True},
        'decision': {'semantic_acceptance': True, 'plan_hypothesis_supported': True,
            'adopted': False, 'measured_speedup_percent': None,
            'next_step': 'At most a separately preregistered paired evaluation on the original 48 fixed cases, with order balance, original full payloads, stage costs and sequential load observation.',
            'reason': 'Grouping moves the unique size lookup after posting aggregation, but only the logical repeated matches are avoided. Posting access, grouping, returned rows and Python work remain. Co-routine overhead may offset savings; no runtime conclusion follows.'},
        'scope': {'candidate_real_rankings': 0, 'candidate_real_performance_runs': 0,
            'actual_model_explain_plans': 2, 'new_keys': 0, 'new_primary_fit_validation_bootstrap': 0,
            'full_validation_complete': False, 'reserved_test': 'locked'},
        'coverage': cost['coverage_before_and_after_reuse'], 'gates': gates, 'T_plan': None}
    write(folder/'assessment.json', report)
    report['private_receipt'] = describe(folder/'assessment.json')
    public_json(ROOT/REPORT, report, exclusive=True)
    print({'report': REPORT, 'tests': result.testsRun, 'logical_join_input_reduction_percent':
           report['logical_join_opportunity']['logical_join_input_reduction_percent'], 'adopted': False})


if __name__ == '__main__':
    assess()
