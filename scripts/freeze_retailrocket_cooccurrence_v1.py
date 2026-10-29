"""Freeze/verify C1 vs accepted P0; hash source bytes, never parse real CSVs."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.retailrocket_cooccurrence_protocol import validate

POLICY = 'docs/contracts/retailrocket_cooccurrence_paired_v1.json'
DOC = 'docs/STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md'
PRIVATE = 'shop-mysql-runtime/retailrocket_cooccurrence_spec_v1'
VERIFY = 'shop-mysql-runtime/verification/retailrocket-cooccurrence-spec-v1'
SPEC = 'reports/stage10/retailrocket_cooccurrence_v1_specification.json'
ACCEPT = 'reports/stage10/retailrocket_cooccurrence_v1_spec_acceptance.json'
P0_GUARD = 'shop-mysql-runtime/retailrocket_popularity_v1/development/output_guard.json'
NEW_SOURCES = [POLICY, DOC, 'scripts/retailrocket_cooccurrence_protocol.py',
    'scripts/freeze_retailrocket_cooccurrence_v1.py', 'tests/test_retailrocket_cooccurrence_protocol.py',
    'docs/STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md',
    '.venv/Lib/site-packages/numpy-2.5.4.dist-info/METADATA']
ABSENT_PATHS = ['shop-mysql-runtime/retailrocket_cooccurrence_paired_v1',
    'shop-mysql-runtime/retailrocket_popularity_v1/final_refit',
    'shop-mysql-runtime/retailrocket_popularity_v1/reserved_test',
    'shop-mysql-runtime/retailrocket_popularity_v1/test_usage.jsonl']


def within(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Path must resolve inside shop')
    return path


def descriptor(relative):
    path = within(relative)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def read(relative):
    return json.loads(within(relative).read_text(encoding='utf-8'))


def check(records):
    for record in records:
        if descriptor(record['path']) != record:
            raise ValueError('Frozen bytes differ: ' + record['path'])


def check_locked_scope():
    for relative in ABSENT_PATHS:
        if within(relative).exists():
            raise ValueError('Spec-only lock requires absent namespace: ' + relative)


def consistency():
    return validate(read(POLICY), read('docs/contracts/retailrocket_recommendation_v1.json'),
                    read('reports/stage9/retailrocket_popularity_v1_development.json'),
                    read('reports/stage9/retailrocket_popularity_v1_development_acceptance.json'))


def collect_sources():
    guard = read(P0_GUARD)
    bound = {}
    for record in guard['sources'] + guard['outputs']:
        path = record['path']
        if path in bound and bound[path] != record:
            raise ValueError('Inconsistent upstream descriptors: ' + path)
        bound[path] = record
    check(list(bound.values()))
    for relative in [P0_GUARD, *NEW_SOURCES]:
        record = descriptor(relative)
        if record['path'] in bound and record != bound[record['path']]:
            raise ValueError('Source changed while collecting: ' + relative)
        bound[record['path']] = record
    return [bound[p] for p in sorted(bound)]


def write_new(relative, value):
    path = within(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def freeze():
    if within(PRIVATE).exists():
        if not within(PRIVATE + '/output_guard.json').exists():
            raise FileExistsError('Partial freeze preserved; no replay or overwrite')
        return verify()
    if any(within(p).exists() for p in (SPEC, ACCEPT, VERIFY + '/tests.log')):
        raise FileExistsError('Existing freeze evidence preserved; no overwrite')
    started = time.perf_counter()
    check_locked_scope()
    checks = consistency()
    bound = collect_sources()
    suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_retailrocket_cooccurrence_protocol')
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        outcome = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not outcome.wasSuccessful() or outcome.skipped:
        print(log.getvalue())
        raise ValueError('Specification mutation tests failed')
    check(bound)
    check_locked_scope()
    within(PRIVATE).mkdir()
    within(VERIFY).mkdir(parents=True, exist_ok=True)
    with within(VERIFY + '/tests.log').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(log.getvalue())
    policy = read(POLICY)
    scope = policy['scope_this_round']
    tests = {'tests_run': outcome.testsRun, 'failures': len(outcome.failures),
             'errors': len(outcome.errors), 'skips': len(outcome.skipped),
             'meaning': 'specification guard mutation tests only; C1 algorithm/oracle/bootstrap not implemented'}
    initial = {'state': 'locked', 'C1_test_authorized': False, 'logical_test_runs_consumed_this_round': 0,
               'absent_paths': ABSENT_PATHS, 'protocol': descriptor(POLICY),
               'note': 'Immutable initial snapshot; future separately authorized execution must not edit this receipt'}
    write_new(PRIVATE + '/initial_locked_scope.json', initial)
    specification = {'status': 'C1_P0_paired_v1_frozen_before_C1_implementation_and_scores',
        'date_asia_taipei': '2026-10-28', 'protocol': descriptor(POLICY), 'sources': bound,
        'source_verification': 'P0 guard sources and outputs plus new protocol inputs checked by SHA-256/size before and after; CSV bytes hashed, zero CSV rows parsed',
        'consistency_checks': checks, 'tests': tests, 'scope': scope,
        'fixed_validation': policy['fixed_validation'], 'P0_identity': policy['P0_identity'],
        'initial_locked_scope': descriptor(PRIVATE + '/initial_locked_scope.json')}
    write_new(SPEC, specification)
    acceptance = {'status': 'paired_specification_consistency_sources_and_freeze_readback_passed',
        'specification': descriptor(SPEC), 'sources_verified': len(bound), 'checks_passed': len(checks),
        'tests': tests, 'scope': scope, 'fixed_validation': policy['fixed_validation'],
        'P0_reference_only': policy['P0_identity'], 'absent_execution_paths_verified': ABSENT_PATHS,
        'elapsed_seconds': round(time.perf_counter() - started, 6),
        'next_step': 'implement exact C1 and paired evaluator with hand/independent synthetic oracle; train-only cost preflight and resource limits; freeze separate real validation entry; no test activation'}
    write_new(ACCEPT, acceptance)
    outputs = [descriptor(p) for p in (SPEC, ACCEPT, PRIVATE + '/initial_locked_scope.json', VERIFY + '/tests.log')]
    write_new(PRIVATE + '/output_guard.json', {'sources': bound, 'outputs': outputs})
    if read(SPEC) != specification or read(ACCEPT) != acceptance or read(PRIVATE + '/initial_locked_scope.json') != initial:
        raise ValueError('Freeze JSON semantic roundtrip failed')
    check(bound + outputs)
    check_locked_scope()
    return {'status': acceptance['status'], 'sources_verified': len(bound), 'checks_passed': len(checks),
            'tests': tests, 'scope': scope}


def verify():
    guard = read(PRIVATE + '/output_guard.json')
    check(guard['sources'] + guard['outputs'])
    checks = consistency()
    # These are initial-scope absence checks, not a future test-unlock mechanism.
    check_locked_scope()
    return {'status': 'frozen_paired_specification_sources_and_outputs_verified',
            'sources_verified': len(guard['sources']), 'checks_passed': len(checks),
            'tests_rerun': False, 'scope': read(ACCEPT)['scope']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true')
    group.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    print(json.dumps(freeze() if args.freeze else verify(), ensure_ascii=False, indent=2))
