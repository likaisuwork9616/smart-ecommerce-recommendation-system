"""Preserve accepted C1/P0 evidence bytes; never import or rerun research code."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPORT = 'reports/stage10/retailrocket_c1_p0_v1_research_release.json'
PRIVATE = 'shop-mysql-runtime/retailrocket_c1_p0_release_v1'
VERIFY = 'shop-mysql-runtime/verification/retailrocket-c1-p0-release-v1'
ARCHIVE = 'shop-mysql-runtime/backups/retailrocket_c1_p0_research_release_v1.zip'
C1 = 'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1'
P0 = 'shop-mysql-runtime/retailrocket_popularity_v1/development'
TOP_GUARDS = [C1 + '/output_guard.json', P0 + '/output_guard.json']
GATES = ['shop-mysql-runtime/retailrocket_popularity_spec_v1/initial_test_gate.json',
         'shop-mysql-runtime/retailrocket_popularity_implementation_v1/test_gate_snapshot.json',
         'shop-mysql-runtime/retailrocket_cooccurrence_spec_v1/initial_locked_scope.json',
         'shop-mysql-runtime/retailrocket_cooccurrence_implementation_v1/test_gate_snapshot.json']
ABSENT = ['shop-mysql-runtime/retailrocket_popularity_v1/' + n for n in
          ('final_refit', 'reserved_test', 'test_usage.jsonl')]
ABSENT += ['shop-mysql-runtime/retailrocket_cooccurrence_final_v1',
           C1 + '/failure.json', P0 + '/failure.json']
MANIFEST_MEMBER = 'retailrocket_c1_p0_v1_archive_manifest.json'
HANDOFF = 'docs/STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md'
CODE = 'scripts/archive_retailrocket_c1_p0_v1.py'
TEST = 'tests/test_archive_retailrocket_c1_p0_v1.py'
SNAPSHOTS = ['.gitattributes', '.gitignore', 'README.md', 'data/README.md', 'docs/README.md',
             'docs/PROJECT_PROGRESS.md', 'reports/README.md', 'scripts/README.md',
             'tests/README.md', 'requirements.txt', 'requirements-lock.txt', 'scripts/__init__.py']
EXTRAS = [HANDOFF, CODE, TEST, 'docs/STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md',
          'docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md',
          'docs/STAGE8_RETAILROCKET_BUILD_V1.md', VERIFY + '/tests.log']


def safe_name(name):
    if not isinstance(name, str):
        raise ValueError('Archive path must be a string')
    path = PurePosixPath(name)
    if (not name or name.startswith('/') or '\\' in name or ':' in name or '\0' in name
            or any(p in ('', '.', '..') for p in name.split('/')) or path.as_posix() != name):
        raise ValueError('Unsafe archive member')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)),
                *('LPT' + str(i) for i in range(1, 10))}
    for part in path.parts:
        if part.endswith((' ', '.')) or any(c in part for c in '<>"|?*') or part.split('.')[0].upper() in reserved:
            raise ValueError('Unsafe Windows archive member')
    return name


def inside(root, name):
    root = Path(root).resolve()
    path = root / safe_name(name)
    if not path.resolve().is_relative_to(root):
        raise ValueError('Path leaves shop')
    return path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def descriptor(root, name):
    path = inside(root, name)
    return {'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encoded(value))


def assert_descriptor(root, item):
    if descriptor(root, item['path']) != {k: item[k] for k in ('path', 'bytes', 'sha256')}:
        raise ValueError('Source bytes differ: ' + item['path'])


def normalize(items):
    unique = {}
    for item in items:
        name = safe_name(item['path'])
        value = {k: item[k] for k in ('path', 'bytes', 'sha256')}
        if name in unique and unique[name] != value:
            raise ValueError('Conflicting source descriptors: ' + name)
        unique[name] = value
    return [unique[name] for name in sorted(unique)]


def descriptors(value):
    """Read JSON metadata only; never decode a CSV or JSONL research record."""
    if isinstance(value, dict):
        if {'path', 'bytes', 'sha256'} <= value.keys():
            yield {k: value[k] for k in ('path', 'bytes', 'sha256')}
        else:
            for child in value.values():
                yield from descriptors(child)
    elif isinstance(value, list):
        for child in value:
            yield from descriptors(child)


def check_locked(root):
    for number, name in enumerate(GATES):
        gate = read(inside(root, name))
        if number < 2:
            expected = ('locked_at_specification_freeze', 'locked_at_development_entry_freeze')[number]
            valid = (gate.get('status') == expected and gate.get('test_ranking_started') is False
                     and gate.get('logical_tests_consumed') == 0)
        else:
            valid = (gate.get('state') == 'locked' and gate.get('C1_test_authorized') is False
                     and gate.get('logical_test_runs_consumed_this_round') == 0)
        if not valid:
            raise ValueError('Reserved-test gate is not locked: ' + name)
    for name in ABSENT:
        if inside(root, name).exists():
            raise ValueError('Unexpected test/final/failure evidence: ' + name)


def namespace_files(root, prefix):
    folder = inside(root, prefix)
    if not folder.is_dir():
        raise FileNotFoundError(prefix)
    return sorted(p.relative_to(Path(root).resolve()).as_posix() for p in folder.rglob('*') if p.is_file())


def archived_role(name):
    return (name.startswith(('docs/', 'scripts/', 'tests/', 'reports/'))
            or name.startswith((C1 + '/', P0 + '/'))
            or PurePosixPath(name).name.endswith('guard.json') or name in GATES)


def collect(root):
    check_locked(root)
    bound = {}
    pending = list(TOP_GUARDS)
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        if name in bound:
            assert_descriptor(root, bound[name])
        current = descriptor(root, name)
        if name in bound and bound[name] != current:
            raise ValueError('Guard changed: ' + name)
        bound[name] = current
        visited.add(name)
        for item in descriptors(read(inside(root, name))):
            path = item['path']
            if path in bound and bound[path] != item:
                raise ValueError('Conflicting lineage descriptor: ' + path)
            if path not in bound:
                assert_descriptor(root, item)
            bound[path] = item
            if PurePosixPath(path).name.endswith('guard.json'):
                pending.append(path)
    for name in GATES:
        current = descriptor(root, name)
        if name in bound and bound[name] != current:
            raise ValueError('Gate changed: ' + name)
        bound[name] = current
    # No unaccounted file can be smuggled into a result namespace.
    for prefix in (C1, P0):
        names = namespace_files(root, prefix)
        if set(names) != {name for name in bound if name.startswith(prefix + '/')}:
            raise ValueError('Result namespace inventory differs from guards: ' + prefix)
    files = [dict(item, live_role='frozen_research_source') for name, item in sorted(bound.items()) if archived_role(name)]
    dependencies = [dict(item, live_role='external_dependency_not_archived') for name, item in sorted(bound.items()) if not archived_role(name)]
    payload = {d['path']: d for d in files}
    for name in [*EXTRAS, *SNAPSHOTS]:
        value = descriptor(root, name)
        if name in bound and bound[name] != value:
            raise ValueError('Frozen dependency changed: ' + name)
        # A pre-existing frozen binding always overrides the mutable-index rule.
        role = 'mutable_context_snapshot' if name in SNAPSHOTS and name not in bound else 'frozen_research_source'
        payload[name] = dict(value, live_role=role)
    dependencies = [d for d in dependencies if d['path'] not in payload]
    return [payload[name] for name in sorted(payload)], dependencies


def facts(root):
    p = read(inside(root, 'reports/stage9/retailrocket_popularity_v1_development.json'))
    pa = read(inside(root, 'reports/stage9/retailrocket_popularity_v1_development_acceptance.json'))
    c = read(inside(root, 'reports/stage10/retailrocket_cooccurrence_v1_validation.json'))
    ca = read(inside(root, 'reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json'))
    if (p['status'] != 'development_fit_and_full_validation_independently_accepted'
            or pa['status'] != 'all_validation_output_cells_and_aggregates_independently_accepted'
            or c['status'] != 'C1_paired_validation_and_bootstrap_independently_accepted'
            or ca['status'] != 'complete_C1_model_lineage_queries_nested_values_and_bootstrap_accepted'):
        raise ValueError('Accepted historical evidence unavailable')
    for report in (p, c):
        scope = report['scope']
        if scope['reserved_test_state'] != 'locked' or scope['reserved_test_ranked_queries'] != 0 or scope['final_refits'] != 0:
            raise ValueError('Historical role differs from validation-only handoff')
    v = c['validation']
    if (p['scope']['real_primary_fits'] != 1 or c['scope']['real_C1_primary_fits'] != 1
            or c['scope']['P0_refits_or_rerankings'] != 0 or c['scope']['validation_queries'] != 166897
            or p['scope']['validation_ranked_queries'] != 166897 or v['uncertainty']['replicates'] != 2000
            or v['arms']['P0'] != p['validation']):
        raise ValueError('Unexpected paired scope or P0 aggregate drift')
    for acceptance in (pa, ca):
        assert_descriptor(root, acceptance['result'])
    return {'provenance': 'copied_from_accepted_reports_no_new_metrics', 'evaluation_role': 'retrospective_exposed_development_validation',
            'P0_scope': p['scope'], 'C1_scope': c['scope'], 'queries': v['paired']['queries'],
            'visitors': v['paired']['visitors'], 'metrics': {arm: data['metrics'] for arm, data in v['arms'].items()},
            'paired_delta': v['paired']['delta_metrics'], 'uncertainty': v['uncertainty'],
            'cold_target_slice': {arm: data['slices']['target_model']['all_zero'] for arm, data in v['arms'].items()},
            'fallback_reasons': v['diagnostics']['fallback_reason'],
            'small_groups': {family: v['paired']['slices'][family][group] for family, group in
                             [('current_basket', 'multiple'), ('target_basket', 'multiple'), ('target_model', 'mixed')]},
            'support_floor_queries': v['arms']['C1']['support_floor_queries'],
            'historical_C1_readback': ca['readback'], 'historical_C1_resources': c['resources'],
            'fit_ids': {'P0': p['fit_audit']['fit_id'], 'C1': c['fit_audit']['fit_id']}}


def pack(root, path, manifest):
    if not Path(path).resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Archive destination leaves shop')
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        archive.writestr(MANIFEST_MEMBER, encoded(manifest))
        for item in manifest['files']:
            name = safe_name(item['path'])
            sha = hashlib.sha256()
            size = 0
            with inside(root, name).open('rb') as source, archive.open(name, 'w', force_zip64=True) as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
            if size != item['bytes'] or sha.hexdigest() != item['sha256']:
                raise ValueError('Source changed while archiving: ' + name)


def inspect_archive(path, expected_manifest_sha=None):
    checked = total = 0
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len({n.casefold() for n in names}):
            raise ValueError('Duplicate ZIP members')
        for name in names:
            safe_name(name)
        raw = archive.read(MANIFEST_MEMBER)
        manifest_sha = hashlib.sha256(raw).hexdigest()
        if expected_manifest_sha and manifest_sha != expected_manifest_sha:
            raise ValueError('Archive manifest changed')
        manifest = json.loads(raw)
        expected = [safe_name(d['path']) for d in manifest['files']]
        dependencies = [safe_name(d['path']) for d in manifest['external_dependencies']]
        if (len(expected) != len({n.casefold() for n in expected})
                or len(dependencies) != len({n.casefold() for n in dependencies})
                or {n.casefold() for n in expected} & {n.casefold() for n in dependencies} or MANIFEST_MEMBER in expected
                or set(names) != {MANIFEST_MEMBER, *expected}):
            raise ValueError('ZIP or dependency inventory differs')
        for item in manifest['files']:
            sha = hashlib.sha256()
            size = 0
            with archive.open(item['path']) as source:
                while chunk := source.read(1024 * 1024):
                    sha.update(chunk)
                    size += len(chunk)
            # ZipExtFile checks CRC on reaching EOF; the separate hash detects valid-CRC replacement.
            if size != item['bytes'] or sha.hexdigest() != item['sha256']:
                raise ValueError('Archived payload differs: ' + item['path'])
            checked += 1
            total += size
    return manifest, {'payload_files': checked, 'zip_members': checked + 1, 'payload_bytes': total,
                      'all_payload_CRC_and_SHA256_passed': True, 'manifest_sha256': manifest_sha,
                      'external_dependencies_not_archived': len(dependencies)}


def ensure_new(root):
    target = inside(root, ARCHIVE)
    for path in (inside(root, PRIVATE), target, target.with_suffix('.zip.partial'), inside(root, REPORT), inside(root, VERIFY + '/tests.log')):
        if path.exists():
            raise FileExistsError('Existing/partial release preserved; no replay: ' + str(path))


def archive_release(root=ROOT):
    root = Path(root).resolve()
    if inside(root, PRIVATE + '/output_guard.json').is_file():
        return verify(root)
    ensure_new(root)
    check_locked(root)
    import sys
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_archive_retailrocket_c1_p0_v1')
    log = io.StringIO()
    started = time.perf_counter()
    tests = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    seconds = round(time.perf_counter() - started, 6)
    inside(root, VERIFY).mkdir(parents=True, exist_ok=True)
    with inside(root, VERIFY + '/tests.log').open('x', encoding='utf-8', newline='\n') as output:
        output.write(log.getvalue())
    if not tests.wasSuccessful() or tests.skipped:
        raise ValueError('Archive synthetic tests failed; evidence preserved')
    files, dependencies = collect(root)
    summary = facts(root)
    return publish(root, files, dependencies, summary, {'tests_run': tests.testsRun, 'failures': len(tests.failures),
                   'errors': len(tests.errors), 'skips': len(tests.skipped), 'elapsed_seconds': seconds})


def publish(root, files, dependencies, summary, tests):
    private = inside(root, PRIVATE)
    target = inside(root, ARCHIVE)
    partial = target.with_suffix('.zip.partial')
    manifest = {'release_id': 'retailrocket_c1_p0_research_release_v1',
                'scope': 'C1/P0 accepted result evidence package, frozen public research sources and selected context snapshots',
                'files': files, 'external_dependencies': dependencies, 'research_facts': summary,
                'operational_status': 'offline_research_only_cold_items_small_groups_retrospective_limits_retained',
                'snapshot_policy': 'Mutable context snapshots may evolve; all other live evidence and listed dependencies remain byte-identical.',
                'restore': 'Verify ZIP and detached receipt before restoring into a clean shop directory; no extraction command is implemented.',
                'excluded': 'Raw dataset, full recommendation dataset, Python environment and non-result private lineage dependencies are hashes only; no credentials, MySQL, Git history or unrelated research.',
                'restore_limit': 'Result evidence package, not a standalone raw-data/environment reconstruction or disaster-recovery backup.',
                'attribution': 'Retailrocket ecommerce dataset v2; existing frozen CC BY-NC-SA 4.0 source/license evidence remains an external dependency; no new licensing determination.'}
    # Exclusive creation preserves an interrupted attempt and forbids overwrite.
    private.mkdir()
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        write_new(private / 'archive_manifest.json', manifest)
        pack(root, partial, manifest)
        restored, verification = inspect_archive(partial, digest(private / 'archive_manifest.json'))
        if restored != manifest:
            raise ValueError('Archive manifest readback differs')
        for item in files + dependencies:
            assert_descriptor(root, item)
        check_locked(root)
        for prefix in (C1, P0):
            if set(namespace_files(root, prefix)) != {d['path'] for d in files if d['path'].startswith(prefix + '/')}:
                raise ValueError('Result namespace changed during archiving')
        partial.rename(target)
        receipt = {'status': 'C1_P0_research_handoff_evidence_archived_and_verified', 'release_id': manifest['release_id'],
                   'archive': descriptor(root, ARCHIVE), 'archive_manifest': descriptor(root, PRIVATE + '/archive_manifest.json'),
                   'verification': verification, 'sources': files, 'external_dependencies': dependencies, 'research_facts': summary,
                   'frozen_payload_files': sum(d['live_role'] == 'frozen_research_source' for d in files),
                   'context_snapshots': sum(d['live_role'] == 'mutable_context_snapshot' for d in files),
                   'P0_result_files_unchanged': sum(d['path'].startswith(P0 + '/') for d in files),
                   'C1_result_files_unchanged': sum(d['path'].startswith(C1 + '/') for d in files),
                   'gates_unchanged_and_locked': GATES, 'absent_test_final_failure_paths': ABSENT,
                   'archive_tests': tests, 'elapsed_seconds': round(time.perf_counter() - started, 6),
                   'scope_this_turn': {'train_fits': 0, 'ranked_queries': 0, 'metric_recalculations': 0,
                                       'bootstrap_replicates': 0, 'reserved_test_ranked_queries': 0,
                                       'reserved_test_state': 'locked', 'research_tests_rerun': False},
                   'backup_limit': 'Same shop drive only; external dependency bytes are not in ZIP; no remote backup or GitHub publication.'}
        write_new(inside(root, REPORT), receipt)
        write_new(private / 'output_guard.json', {'receipt': descriptor(root, REPORT), 'archive': receipt['archive'],
                                                'manifest': receipt['archive_manifest']})
        return {'status': receipt['status'], 'archive_bytes': receipt['archive']['bytes'], **verification,
                'archive_tests': tests, 'elapsed_seconds': receipt['elapsed_seconds']}
    except Exception as error:
        write_new(private / 'failure.json', {'status': 'partial_archive_preserved_no_replay', 'error_type': type(error).__name__})
        raise


def verify(root=ROOT, archive_only=False):
    root = Path(root).resolve()
    if not archive_only and inside(root, PRIVATE + '/failure.json').exists():
        raise ValueError('Partial release preserved')
    receipt = read(inside(root, REPORT))
    assert_descriptor(root, receipt['archive'])
    manifest, checked = inspect_archive(inside(root, receipt['archive']['path']), receipt['verification']['manifest_sha256'])
    if (manifest['files'] != receipt['sources'] or manifest['external_dependencies'] != receipt['external_dependencies']
            or manifest['research_facts'] != receipt['research_facts'] or checked != receipt['verification']):
        raise ValueError('Release inventory/facts mismatch')
    verified = 0
    if not archive_only:
        check_locked(root)
        assert_descriptor(root, receipt['archive_manifest'])
        for item in manifest['files'] + manifest['external_dependencies']:
            if item['live_role'] != 'mutable_context_snapshot':
                assert_descriptor(root, item)
                verified += 1
        for item in read(inside(root, PRIVATE + '/output_guard.json')).values():
            assert_descriptor(root, item)
        for prefix in (C1, P0):
            if set(namespace_files(root, prefix)) != {d['path'] for d in manifest['files'] if d['path'].startswith(prefix + '/')}:
                raise ValueError('Result namespace inventory changed')
    return {'status': 'archive_only_verified' if archive_only else 'archive_and_live_frozen_evidence_dependencies_verified',
            **checked, 'live_frozen_files_verified': verified, 'research_recomputed': False,
            'live_gate_checked': not archive_only}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--archive', action='store_true')
    actions.add_argument('--verify', action='store_true')
    actions.add_argument('--verify-archive-only', action='store_true')
    args = parser.parse_args()
    value = archive_release() if args.archive else verify(archive_only=args.verify_archive_only)
    print(json.dumps(value, ensure_ascii=False, indent=2))
