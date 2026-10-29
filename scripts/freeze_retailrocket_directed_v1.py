"""Freeze D1 specification metadata and bytes only; no research execution flags."""
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
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.retailrocket_directed_protocol import validate

POLICY = 'docs/contracts/retailrocket_directed_paired_v1.json'
INVENTORY = 'reports/stage11/retailrocket_stage11_candidate_inventory_v1.json'
DOC = 'docs/STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md'
PRIVATE = 'shop-mysql-runtime/retailrocket_directed_spec_v1'
VERIFY = 'shop-mysql-runtime/verification/retailrocket-directed-spec-v1'
EXECUTION = 'shop-mysql-runtime/retailrocket_directed_paired_v1'
SPEC = 'reports/stage11/retailrocket_directed_v1_specification.json'
ACCEPT = 'reports/stage11/retailrocket_directed_v1_spec_acceptance.json'
RELEASE = 'reports/stage10/retailrocket_c1_p0_v1_research_release.json'
RELEASE_GUARD = 'shop-mysql-runtime/retailrocket_c1_p0_release_v1/output_guard.json'
REFERENCE_GUARDS = ['shop-mysql-runtime/retailrocket_popularity_v1/development/output_guard.json',
                    'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/output_guard.json']
GATES = ['shop-mysql-runtime/retailrocket_popularity_spec_v1/initial_test_gate.json',
         'shop-mysql-runtime/retailrocket_popularity_implementation_v1/test_gate_snapshot.json',
         'shop-mysql-runtime/retailrocket_cooccurrence_spec_v1/initial_locked_scope.json',
         'shop-mysql-runtime/retailrocket_cooccurrence_implementation_v1/test_gate_snapshot.json']
ABSENT_TEST = ['shop-mysql-runtime/retailrocket_popularity_v1/' + n for n in ('final_refit', 'reserved_test', 'test_usage.jsonl')]
ABSENT_TEST += ['shop-mysql-runtime/retailrocket_cooccurrence_final_v1',
               'shop-mysql-runtime/retailrocket_directed_final_v1',
               EXECUTION + '/reserved_test', EXECUTION + '/final_refit', EXECUTION + '/test_usage.jsonl']
NEW_SOURCES = [POLICY, INVENTORY, DOC, 'scripts/retailrocket_directed_protocol.py',
               'scripts/freeze_retailrocket_directed_v1.py', 'tests/test_retailrocket_directed_protocol.py']
INPUTS = [POLICY, 'docs/contracts/retailrocket_recommendation_v1.json',
          'reports/stage9/retailrocket_popularity_v1_development.json',
          'reports/stage9/retailrocket_popularity_v1_development_acceptance.json',
          'reports/stage10/retailrocket_cooccurrence_v1_validation.json',
          'reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json',
          INVENTORY, 'docs/contracts/retailrocket_cooccurrence_paired_v1.json']


def within(relative):
    if not isinstance(relative, str) or '\\' in relative or ':' in relative or any(x in ('', '.', '..') for x in relative.split('/')):
        raise ValueError('Unsafe relative path')
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()): raise ValueError('Path leaves shop')
    return path


def descriptor(relative):
    path = within(relative)
    with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': relative, 'bytes': path.stat().st_size, 'sha256': digest}


def read(relative):
    if not relative.endswith('.json'): raise ValueError('Metadata JSON only; no CSV/JSONL decoder')
    return json.loads(within(relative).read_text(encoding='utf-8'))


def check(records):
    for record in records:
        expected = {k: record[k] for k in ('path', 'bytes', 'sha256')}
        if descriptor(record['path']) != expected: raise ValueError('Frozen bytes differ: ' + record['path'])


def write_new(relative, value):
    path = within(relative); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')


def check_locked_scope(freeze_only=False):
    for n, name in enumerate(GATES):
        gate = read(name)
        if n < 2:
            expected = ('locked_at_specification_freeze', 'locked_at_development_entry_freeze')[n]
            valid = gate.get('status') == expected and gate.get('test_ranking_started') is False and type(gate.get('logical_tests_consumed')) is int and gate['logical_tests_consumed'] == 0
        else:
            valid = gate.get('state') == 'locked' and gate.get('C1_test_authorized') is False and type(gate.get('logical_test_runs_consumed_this_round')) is int and gate['logical_test_runs_consumed_this_round'] == 0
        if not valid: raise ValueError('Reference test gate changed: ' + name)
    for name in ABSENT_TEST + ([EXECUTION] if freeze_only else []):
        if within(name).exists(): raise ValueError('Forbidden namespace for this operation: ' + name)


def consistency(): return validate(*(read(p) for p in INPUTS))


def collect_sources():
    release_guard = read(RELEASE_GUARD)
    check(list(release_guard.values()))
    release = read(RELEASE)
    if release['status'] != 'C1_P0_research_handoff_evidence_archived_and_verified':
        raise ValueError('Accepted reference release required')
    manifest = read(release['archive_manifest']['path'])
    if manifest['files'] != release['sources'] or manifest['external_dependencies'] != release['external_dependencies']:
        raise ValueError('Reference release inventory mismatch')
    bound = {}
    def add(record):
        record = {k: record[k] for k in ('path', 'bytes', 'sha256')}; name = record['path']
        if name in bound and bound[name] != record: raise ValueError('Conflicting source identity: ' + name)
        bound[name] = record
    # Mutable indexes were explicitly archived as snapshots; their live bytes may evolve.
    for record in release['sources']:
        if record.get('live_role') != 'mutable_context_snapshot': add(record)
    for record in release['external_dependencies']: add(record)
    for record in release_guard.values(): add(record)
    add(descriptor(RELEASE_GUARD))
    for guard_path in REFERENCE_GUARDS:
        add(descriptor(guard_path)); guard = read(guard_path)
        for record in guard['sources'] + guard['outputs']: add(record)
    for name in GATES + NEW_SOURCES: add(descriptor(name))
    values = [bound[p] for p in sorted(bound)]
    check(values)
    return values


def ensure_new():
    for relative in (PRIVATE, SPEC, ACCEPT, VERIFY + '/tests.log'):
        if within(relative).exists(): raise FileExistsError('Existing/partial freeze preserved: ' + relative)


def freeze():
    if within(PRIVATE + '/output_guard.json').is_file(): return verify()
    ensure_new(); check_locked_scope(freeze_only=True)
    within(PRIVATE).mkdir(parents=True)
    write_new(PRIVATE + '/started.json', {'operation': 'D1_specification_freeze_only', 'model_or_metric_execution': False})
    started = time.perf_counter()
    try:
        checks = consistency(); sources = collect_sources()
        suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_retailrocket_directed_protocol')
        log = io.StringIO()
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        within(VERIFY).mkdir(parents=True, exist_ok=True)
        with within(VERIFY + '/tests.log').open('x', encoding='utf-8', newline='\n') as stream: stream.write(log.getvalue())
        if not result.wasSuccessful() or result.skipped: raise ValueError('D1 specification/entry tests failed')
        check(sources); check_locked_scope(freeze_only=True)
        policy = read(POLICY)
        tests = {'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
                 'skips': len(result.skipped), 'meaning': 'metadata protocol/entry safety only; no D1 model, ranking or bootstrap correctness claim'}
        initial = {'state': 'locked', 'D1_test_authorized': False, 'logical_test_runs_consumed_this_round': 0,
                   'protocol': descriptor(POLICY), 'absent_execution_at_freeze': EXECUTION,
                   'absent_test_paths': ABSENT_TEST, 'reference_gates': [descriptor(p) for p in GATES],
                   'note': 'Immutable initial snapshot; later separately guarded validation does not edit this receipt or authorize test.'}
        write_new(PRIVATE + '/initial_locked_scope.json', initial)
        spec = {'status': 'D1_C1_P0_paired_v1_frozen_before_D1_implementation_and_scores',
                'date_asia_taipei': policy['date_asia_taipei'], 'protocol': descriptor(POLICY),
                'candidate_inventory': descriptor(INVENTORY), 'sources': sources, 'consistency_checks': checks,
                'source_verification': 'Accepted C1/P0/release frozen payload and package-external dependencies SHA/size; mutable context snapshots excluded; zero real CSV/JSONL rows parsed.',
                'tests': tests, 'scope_at_freeze': policy['scope_this_round'], 'fixed_validation': policy['fixed_validation'],
                'reference_identity': policy['reference_identity'], 'initial_locked_scope': descriptor(PRIVATE + '/initial_locked_scope.json')}
        write_new(SPEC, spec)
        acceptance = {'status': 'D1_specification_metadata_sources_and_JSON_readback_passed',
                      'specification': descriptor(SPEC), 'sources_verified': len(sources), 'checks_passed': len(checks),
                      'tests': tests, 'scope_at_freeze': policy['scope_this_round'], 'fixed_validation': policy['fixed_validation'],
                      'reference_identity': policy['reference_identity'], 'elapsed_seconds': round(time.perf_counter()-started, 6),
                      'next_step': 'Implement D1/three-arm evaluator/bootstrap plus hand and independent synthetic oracle; audit train-only cost, then separately freeze real validation entry. Keep test locked.'}
        write_new(ACCEPT, acceptance)
        outputs = [descriptor(p) for p in (SPEC, ACCEPT, PRIVATE + '/started.json', PRIVATE + '/initial_locked_scope.json', VERIFY + '/tests.log')]
        guard = {'sources': sources, 'outputs': outputs}
        write_new(PRIVATE + '/output_guard.json', guard)
        if (read(SPEC) != spec or read(ACCEPT) != acceptance or read(PRIVATE + '/initial_locked_scope.json') != initial
                or read(PRIVATE + '/output_guard.json') != guard
                or read(PRIVATE + '/started.json') != {'operation': 'D1_specification_freeze_only', 'model_or_metric_execution': False}):
            raise ValueError('Frozen metadata JSON semantic roundtrip differs')
        check(sources + outputs); check_locked_scope(freeze_only=True)
        return {'status': acceptance['status'], 'sources_verified': len(sources), 'checks_passed': len(checks),
                'tests': tests, 'scope_at_freeze': policy['scope_this_round']}
    except Exception as error:
        write_new(PRIVATE + '/failure.json', {'status': 'partial_specification_preserved_no_replay', 'error_type': type(error).__name__})
        raise


def verify():
    if within(PRIVATE + '/failure.json').exists(): raise ValueError('Partial freeze preserved')
    guard = read(PRIVATE + '/output_guard.json'); check(guard['sources'] + guard['outputs'])
    checks = consistency(); check_locked_scope(freeze_only=False)
    gate = read(PRIVATE + '/initial_locked_scope.json')
    if (gate['state'] != 'locked' or gate['D1_test_authorized'] is not False
            or type(gate['logical_test_runs_consumed_this_round']) is not int or gate['logical_test_runs_consumed_this_round'] != 0):
        raise ValueError('D1 initial gate changed')
    return {'status': 'frozen_D1_specification_sources_and_outputs_verified', 'sources_verified': len(guard['sources']),
            'checks_passed': len(checks), 'tests_rerun': False, 'research_recomputed': False,
            'scope_at_freeze': read(ACCEPT)['scope_at_freeze'],
            'current_D1_validation_namespace_exists': within(EXECUTION).exists(),
            'interpretation': 'Historical freeze verified; namespace existence is not evidence of model execution/acceptance and never opens test.'}


def parser():
    result = argparse.ArgumentParser(description=__doc__); group = result.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true'); group.add_argument('--verify', action='store_true')
    return result


if __name__ == '__main__':
    args = parser().parse_args()
    print(json.dumps(freeze() if args.freeze else verify(), ensure_ascii=False, indent=2))
