"""V75 bounded artificial acceptance. All inputs are presealed before loading.

Copied inputs used for semantic negatives are trusted component tests, never
registered as admissible bundles. They preserve their failed artifacts and do
not modify frozen methods, presealed source bundles, or published results.
"""
from collections import Counter
from copy import deepcopy
import csv
from decimal import localcontext
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch
import uuid

from scripts import retailrocket_session_knn_bundle_v75 as bundle
from scripts import retailrocket_session_knn_full_worker_v75 as worker
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback as v1
from scripts import retailrocket_session_knn_checks_v4 as checks
from scripts import retailrocket_session_knn_sql_v4 as sql4
from scripts import retailrocket_session_knn_sql_v2 as sql2
from tests.test_retailrocket_session_knn_checkpoint_v2 import FakeClock, FakeProcesses

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / '.runtime' / 'v75' / 'cases'
STREAMS = ('dataset/queries.csv', 'P0/ranked_queries.csv', 'P0/query_metrics.csv',
           'P0/query_slices.csv', 'C1/queries.jsonl', 'D1/queries.jsonl', 'primary/queries.jsonl')


CASE_IDS = ['A01.profile.F-small',
 'A01.profile.F-long',
 'A01.profile.F-edge',
 'A01.invalid_profile.real',
 'A01.invalid_profile.166897',
 'A01.invalid_profile.../F-small',
 'A01.invalid_profile.None',
 'A01.invalid_profile.129',
 'A01.anchor.fixture_seal_sha256',
 'A01.anchor.method_seal_sha256',
 'A01.manifest.missing_profile',
 'A01.manifest.real_profile',
 'A01.manifest.forged_real_count',
 'A01.manifest.caller_count_mismatch',
 'A01.manifest.bool_count',
 'A01.manifest.float_count',
 'A01.manifest.bool_visitors',
 'A01.manifest.wrong_draw_count',
 'A01.manifest.bool_synthetic_marker',
 'A01.manifest.outside_data_path',
 'A01.manifest.absolute_path',
 'A01.manifest.outside_source_path',
 'A01.manifest.wrong_role',
 'A01.path.../outside',
 'A01.path./outside',
 'A01.path.C:/outside',
 'A01.path.dir/../input.txt',
 'A01.path.dir\\input.txt',
 'A01.alias.is_symlink',
 'A01.alias.is_junction',
 'A02.runtime',
 'A02.missing_direct_source',
 'A02.same_size_wrong_sha',
 'A02.undeclared_dynamic',
 'A03.full.F-small',
 'A03.full.F-long',
 'A03.full.F-edge',
 'A04.fallback.no_supported_seed',
 'A04.fallback.only_self_session_overlap',
 'A04.fallback.no_positive_causal_vote',
 'A04.neighbors.499',
 'A04.neighbors.500',
 'A04.neighbors.501',
 'A04.ratio.0',
 'A04.ratio.1',
 'A04.ratio.2',
 'A06.dataset/queries.csv.missing',
 'A06.dataset/queries.csv.extra',
 'A06.dataset/queries.csv.duplicate',
 'A06.dataset/queries.csv.order',
 'A06.P0/ranked_queries.csv.missing',
 'A06.P0/ranked_queries.csv.extra',
 'A06.P0/ranked_queries.csv.duplicate',
 'A06.P0/ranked_queries.csv.order',
 'A06.P0/query_metrics.csv.missing',
 'A06.P0/query_metrics.csv.extra',
 'A06.P0/query_metrics.csv.duplicate',
 'A06.P0/query_metrics.csv.order',
 'A06.P0/query_slices.csv.missing',
 'A06.P0/query_slices.csv.extra',
 'A06.P0/query_slices.csv.duplicate',
 'A06.P0/query_slices.csv.order',
 'A06.C1/queries.jsonl.missing',
 'A06.C1/queries.jsonl.extra',
 'A06.C1/queries.jsonl.duplicate',
 'A06.C1/queries.jsonl.order',
 'A06.D1/queries.jsonl.missing',
 'A06.D1/queries.jsonl.extra',
 'A06.D1/queries.jsonl.duplicate',
 'A06.D1/queries.jsonl.order',
 'A06.primary/queries.jsonl.missing',
 'A06.primary/queries.jsonl.extra',
 'A06.primary/queries.jsonl.duplicate',
 'A06.primary/queries.jsonl.order',
 'A09.same_size_database',
 'A09.missing_database',
 'A09.extra_journal',
 'A09.source_changed',
 'A09.foreign_reconstruction',
 'A11.scientific.before_append',
 'A11.scientific.query_verified',
 'A11.scientific.payload_half_written',
 'A11.scientific.after_payload_fsync',
 'A11.scientific.before_manifest_commit',
 'A11.scientific.after_manifest_commit',
 'A12.invalid.wrong_prefix_key',
 'A12.invalid.chunk_gap',
 'A12.invalid.chain_sha',
 'A13.global_replay',
 'A13.bootstrap_draw',
 'A13.after_stage_global',
 'A14.primary.order',
 'A14.primary.draw_sha256',
 'A14.primary.query_denominator',
 'A14.primary.rng_before',
 'A14.primary.rng_after',
 'A14.primary.delta',
 'A14.primary.missing',
 'A14.primary.extra',
 'A14.C1.order',
 'A14.C1.draw_sha256',
 'A14.C1.query_denominator',
 'A14.C1.rng_before',
 'A14.C1.rng_after',
 'A14.C1.missing',
 'A14.C1.extra']


class InjectedFailure(RuntimeError):
    pass


def unique(label):
    path = TEST_ROOT / (label + '-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


def json_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def write_json(path, value):
    path.write_bytes(cp.encoded(value))


def write_rows(path, values):
    path.write_bytes(b''.join(cp.encoded(value) for value in values))


def copied_input(admitted, label):
    parent = unique(label)
    root = parent / 'input'
    shutil.copytree(admitted['bundle_root'], root)
    config = deepcopy(admitted['config'])
    binding = deepcopy(admitted['binding'])
    # The copy is an explicit unit-test input, not a production admission route.
    return {'bundle_root': root, 'primary': root / 'primary',
            'paths': {key: root / key for key in ('dataset', 'P0', 'C1', 'D1')},
            'config': config, 'binding': binding, 'parent': parent,
            'manifest': deepcopy(admitted['manifest'])}


def rebind_copied_input(value):
    value['binding']['sources'] = cp.bind_sources(value['bundle_root'],
                                                  [row['path'] for row in value['binding']['sources']])


def store_for(value, label='run', **kwargs):
    clock = kwargs.pop('clock', FakeClock())
    processes = kwargs.pop('process_api', FakeProcesses())
    folder = (value['parent'] if 'parent' in value else unique(label)) / label
    return worker.create_store(folder, value['binding'], 1900, 900,
            source_root=value['bundle_root'], clock=clock, process_api=processes, **kwargs)


def read_golden(value):
    return (value['bundle_root'] / value['manifest']['golden_records']).read_bytes()


def science_bytes(store):
    return b''.join(cp.encoded(record) for record in store.iter_records())


def run_full(value, store, fault=lambda point: None):
    with store.writer():
        return worker.verify_full(value['primary'], value['paths'], value['config'], store, fault=fault)


class AdmissionTests(unittest.TestCase):
    def test_A01_registered_and_invalid_profiles_and_anchor(self):
        for profile, expected in [('F-small', (7, 6)), ('F-long', (129, 3)), ('F-edge', (1, 1))]:
            with self.subTest(case_id='A01.profile.' + profile, profile=profile):
                value = bundle.admit(profile)
                self.assertEqual((value['binding']['expected_queries'], value['binding']['expected_visitors']), expected)
        for profile in ('real', '166897', '../F-small', None, 129):
            with self.subTest(case_id='A01.invalid_profile.' + str(profile), invalid_profile=profile), self.assertRaises(ValueError):
                bundle.admit(profile)
        for field in ('fixture_seal_sha256', 'method_seal_sha256'):
            with self.subTest(case_id='A01.anchor.' + field, anchor=field), self.assertRaises(ValueError):
                bundle.admit('F-small', **{field: '0' * 64})
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            bundle.admit('F-small')

    def test_A01_manifest_semantics_before_science_reads(self):
        admitted = bundle.admit('F-small')
        manifest_path = admitted['bundle_root'] / 'manifest.json'
        original_read = bundle.read_json
        mutations = {
            'missing_profile': lambda m: m.pop('profile'),
            'real_profile': lambda m: m.update(profile='real'),
            'forged_real_count': lambda m: m.update(expected_queries=166897),
            'caller_count_mismatch': lambda m: m.update(expected_queries=8),
            'bool_count': lambda m: m.update(expected_queries=True),
            'float_count': lambda m: m.update(expected_queries=7.0),
            'bool_visitors': lambda m: m.update(expected_visitors=True),
            'wrong_draw_count': lambda m: m.update(bootstrap_replicates=1999),
            'bool_synthetic_marker': lambda m: m['configuration'].update(synthetic_acceptance_only=1),
            'outside_data_path': lambda m: m['paths'].update(dataset='../outside-sentinel'),
            'absolute_path': lambda m: m['paths'].update(dataset=str(TEST_ROOT.resolve())),
            'outside_source_path': lambda m: m['sources'][0].update(path='../outside-sentinel'),
            'wrong_role': lambda m: m['sources'][0].update(role='reserved_test'),
        }
        for name, mutate in mutations.items():
            changed = deepcopy(admitted['manifest']); mutate(changed)
            def injected_read(path):
                if Path(path) == manifest_path:
                    return deepcopy(changed)
                return original_read(path)
            # Metadata is injected only AFTER the real sealed manifest SHA check.
            # Any attempt to hash scientific source bytes is a test failure.
            original_describe = bundle.describe
            def guarded_describe(root, path):
                if Path(root) == admitted['bundle_root']:
                    self.fail('invalid metadata reached scientific source reading')
                return original_describe(root, path)
            with self.subTest(case_id='A01.manifest.' + name, mutation=name), patch.object(bundle, 'read_json', side_effect=injected_read), \
                 patch.object(bundle, 'describe', side_effect=guarded_describe), self.assertRaises(ValueError):
                bundle.admit('F-small')

    def test_A01_path_alias_escape_and_same_size_source_change(self):
        root = unique('A01-paths')
        source = root / 'input.txt'; source.write_bytes(b'fixed artificial')
        descriptor = bundle.describe(root, 'input.txt')
        source.write_bytes(b'other artificial')
        self.assertEqual(source.stat().st_size, descriptor['bytes'])
        self.assertNotEqual(bundle.describe(root, 'input.txt'), descriptor)
        for name in ('../outside', '/outside', 'C:/outside', 'dir/../input.txt', 'dir\\input.txt'):
            with self.subTest(case_id='A01.path.' + name, path=name), self.assertRaises(ValueError):
                bundle.safe_path(root, name)
        # Native link privileges are not required: both filesystem alias predicates
        # are explicitly injected before any open, with a controlled artificial path.
        for predicate in ('is_symlink', 'is_junction'):
            with self.subTest(case_id='A01.alias.' + predicate, alias=predicate), patch.object(Path, predicate, return_value=True), \
                 self.assertRaises(ValueError):
                bundle.safe_path(root, 'input.txt')

    def test_A02_runtime_closure_and_direct_source_identity(self):
        seal = bundle._sealed_document(bundle.METHOD_SEAL, os.environ['V75_METHOD_SEAL_SHA256'])
        runtime = deepcopy(seal); runtime['runtime']['python'] = '0.0.0'
        with self.subTest(case_id='A02.runtime', mutation='runtime'), self.assertRaises(ValueError):
            bundle._verify_methods(runtime)
        missing = deepcopy(seal)
        seed = seal['source_seeds'][0]
        missing['methods'] = [row for row in missing['methods'] if row['path'] != seed]
        with self.subTest(case_id='A02.missing_direct_source', mutation='missing_direct_source'), self.assertRaises(ValueError):
            bundle._verify_methods(missing)
        changed = deepcopy(seal); changed['methods'][0]['sha256'] = '0' * 64
        with self.subTest(case_id='A02.same_size_wrong_sha', mutation='same_size_wrong_sha'), self.assertRaises(ValueError):
            bundle._verify_methods(changed)
        root = unique('A02-dynamic')
        (root / 'scripts').mkdir()
        (root / 'scripts' / 'entry.py').write_text('import importlib\nname="helper"\nimportlib.import_module(name)\n', encoding='utf-8')
        with self.subTest(case_id='A02.undeclared_dynamic', mutation='undeclared_dynamic'), self.assertRaisesRegex(ValueError, 'Nonliteral dynamic'):
            bundle.source_inventory(['scripts/entry.py'], root=root)


class FullContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.small = bundle.admit('F-small')
        cls.long = bundle.admit('F-long')
        cls.edge = bundle.admit('F-edge')

    def test_A03_A05_complete_payloads_and_original_draws(self):
        for profile, admitted in [('F-small', self.small), ('F-long', self.long), ('F-edge', self.edge)]:
            with self.subTest(case_id='A03.full.' + profile, profile=profile):
                value = copied_input(admitted, 'A03-full-' + profile)
                store = store_for(value)
                result = run_full(value, store)
                self.assertEqual(science_bytes(store), read_golden(value))
                reference = bundle.read_json(value['bundle_root'] / 'reference.json')
                self.assertEqual(result['aggregate'], reference['aggregate'])
                self.assertEqual(result['fit_audit'], reference['fit_audit'])
                self.assertEqual(result['bootstrap_replicates'], 2000)
                self.assertEqual(result['queries_checked'], value['binding']['expected_queries'])
                self.assertIs(result['real_full_acceptance'], False)
                self.assertEqual(set(store.run['required_stages']), set(worker.REQUIRED_STAGES))
                self.assertIs(store.get_stage('queries')['paired_streams_eof_checked'], True)
                self.assertTrue((store.folder / 'candidate.json').exists())
                self.assertFalse((store.folder / 'acceptance.json').exists())
                if profile == 'F-long':
                    chunks = [cp.read(path)['count'] for path in sorted((store.folder / 'chunks').glob('*.json'))]
                    self.assertEqual(chunks, [64, 64, 1])
                    counts = Counter(row['key'][0] for row in store.iter_records())
                    self.assertEqual(counts, {'90': 70, '91': 40, '92': 19})
                if profile == 'F-edge':
                    first = next(store.iter_records())['payload']['expected']['predictions']['K1']
                    self.assertEqual((first['eligible_neighbors'], first['selected_neighbor_count']), (501, 500))

    def test_A06_seven_stream_missing_extra_duplicate_and_order(self):
        for relative in STREAMS:
            for change in ('missing', 'extra', 'duplicate', 'order'):
                with self.subTest(case_id='A06.' + relative + '.' + change, stream=relative, mutation=change):
                    value = copied_input(self.small, 'A06-' + change)
                    path = value['bundle_root'] / relative
                    if path.suffix == '.csv':
                        with path.open(encoding='utf-8', newline='') as stream:
                            reader = csv.DictReader(stream); header = reader.fieldnames; values = list(reader)
                        active = [i for i, row in enumerate(values) if row.get('role') == 'validation']
                    else:
                        values = json_rows(path); active = list(range(len(values)))
                    if change == 'missing': values.pop(active[-1])
                    elif change == 'extra': values.append(deepcopy(values[active[-1]]))
                    elif change == 'duplicate': values.insert(active[1], deepcopy(values[active[0]]))
                    else: values[active[0]], values[active[1]] = values[active[1]], values[active[0]]
                    if path.suffix == '.csv':
                        with path.open('w', encoding='utf-8', newline='') as stream:
                            writer = csv.DictWriter(stream, header, lineterminator='\n'); writer.writeheader(); writer.writerows(values)
                    else: write_rows(path, values)
                    rebind_copied_input(value)
                    store = store_for(value)
                    with self.assertRaises((ValueError, cp.IntegrityError)):
                        run_full(value, store)
                    self.assertIsNotNone(store.get_stage('reconstruction'))
                    self.assertIsNone(store.get_stage('queries'))
                    self.assertFalse((store.folder / 'candidate.json').exists())
                    self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_A07_cached_terms_context_copy_and_attempt_lifetime(self):
        checks.clear_caches()
        try:
            for ids, targets in [(['1', '2', '9'], ['2']), (['1', '2', '9'], ['2', '8']), (['1', '2', '9'], ['2'])]:
                self.assertEqual(checks.terms(ids, targets), v1.terms(ids, targets))
            info = checks.cache_info()['terms']; self.assertGreater(info['hits'], 0); self.assertGreater(info['misses'], 0)
            actual = checks.terms(['1'], ['1']); actual[0]['hits'] = 99
            self.assertEqual(checks.terms(['1'], ['1']), v1.terms(['1'], ['1']))
            with localcontext() as context:
                context.prec = 42
                self.assertEqual(checks.terms(['1', '2'], ['2']), v1.terms(['1', '2'], ['2']))
                self.assertGreater(checks.cache_info()['context_fallbacks'], 0)
            value = copied_input(self.small, 'A07-attempt')
            store = store_for(value)
            def fail(point):
                if point == 'query_work':
                    self.assertEqual(checks.cache_info()['terms']['currsize'], 0)
                    raise InjectedFailure(point)
            with self.assertRaises(InjectedFailure): run_full(value, store, fail)
            self.assertEqual(checks.cache_info()['terms']['currsize'], 0)
            reopened = worker.open_store(store.folder, value['binding'], source_root=value['bundle_root'],
                                         clock=store.clock, process_api=store.processes)
            run_full(value, reopened)
            self.assertEqual(science_bytes(reopened), read_golden(value))
            self.assertEqual(checks.cache_info()['terms']['currsize'], 0)
        finally:
            checks.clear_caches()

    def test_A08_fresh_model_and_unsealed_database_rebuild(self):
        value = copied_input(self.small, 'A08-unsealed')
        store = store_for(value)
        def fault(point):
            if point == 'database_row': raise InjectedFailure(point)
        with self.assertRaises(InjectedFailure): run_full(value, store, fault)
        self.assertTrue((store.folder / 'independent.sqlite').exists())
        self.assertIsNone(store.get_stage('reconstruction'))
        self.assertFalse((store.folder / 'candidate.json').exists())
        reopened = worker.open_store(store.folder, value['binding'], source_root=value['bundle_root'],
                                     clock=store.clock, process_api=store.processes)
        run_full(value, reopened)
        self.assertEqual(science_bytes(reopened), read_golden(value))
        archives = list(store.folder.glob('uncommitted-db-*'))
        self.assertEqual(len(archives), 1)
        self.assertTrue((archives[0] / 'independent.sqlite').exists())
        self.assertIsNotNone(reopened.get_stage('reconstruction'))
        foreign = deepcopy(value['binding']); foreign['fixture_id'] = 'other-artificial-run'
        with self.assertRaises(cp.IntegrityError):
            worker.open_store(store.folder, foreign, source_root=value['bundle_root'], clock=store.clock, process_api=store.processes)

    def test_A09_sealed_database_and_source_integrity(self):
        for mutation in ('same_size_database', 'missing_database', 'extra_journal', 'source_changed', 'foreign_reconstruction'):
            with self.subTest(case_id='A09.' + mutation, mutation=mutation):
                value = copied_input(self.small, 'A09-' + mutation)
                store = store_for(value)
                def fault(point):
                    if point == 'query_work': raise InjectedFailure(point)
                with self.assertRaises(InjectedFailure): run_full(value, store, fault)
                database = store.folder / 'independent.sqlite'
                original = database.read_bytes()
                if mutation == 'same_size_database': database.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
                elif mutation == 'missing_database': database.rename(store.folder / 'missing-db-preserved.sqlite')
                elif mutation == 'extra_journal': Path(str(database) + '-journal').write_bytes(b'artificial journal')
                elif mutation == 'foreign_reconstruction':
                    stage = cp.read(store.folder / 'stages' / 'reconstruction.json')
                    stage['run_sha256'] = 'f' * 64
                    write_json(store.folder / 'stages' / 'reconstruction.json', stage)
                else:
                    path = value['primary'] / 'fit_audit.json'; path.write_bytes(path.read_bytes().replace(b'fit_id', b'fit_iD', 1))
                with self.assertRaises((ValueError, cp.IntegrityError)):
                    reopened = worker.open_store(store.folder, value['binding'], source_root=value['bundle_root'],
                                                  clock=store.clock, process_api=store.processes)
                    run_full(value, reopened)
                self.assertFalse((store.folder / 'candidate.json').exists())
                self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_A11_scientific_payload_recovery_after_atomic_faults(self):
        for point in ('before_append', 'query_verified', 'payload_half_written', 'after_payload_fsync', 'before_manifest_commit', 'after_manifest_commit'):
            with self.subTest(case_id='A11.scientific.' + point, point=point):
                value = copied_input(self.small, 'A11-' + point)
                def fault(event):
                    if event == point: raise InjectedFailure(point)
                store = store_for(value, fault=fault)
                with self.assertRaises(InjectedFailure): run_full(value, store, fault)
                reopened = worker.open_store(store.folder, value['binding'], source_root=value['bundle_root'],
                                              clock=store.clock, process_api=store.processes)
                run_full(value, reopened)
                self.assertEqual(science_bytes(reopened), read_golden(value))
                self.assertFalse((reopened.folder / 'acceptance.json').exists())

    def test_A12_invalid_committed_prefix_is_not_reused(self):
        for mutation in ('wrong_prefix_key', 'chunk_gap', 'chain_sha'):
            with self.subTest(case_id='A12.invalid.' + mutation, mutation=mutation):
                value = copied_input(self.long, 'A12-' + mutation)
                store = store_for(value)
                seen = 0
                def fault(point):
                    nonlocal seen
                    if point == 'query_verified':
                        seen += 1
                        if seen == 65: raise InjectedFailure(point)
                with self.assertRaises(InjectedFailure): run_full(value, store, fault)
                self.assertEqual(store.recover()['records'], 64)
                chunk = store.folder / 'chunks' / '00000000.json'
                record = cp.read(chunk)
                if mutation == 'chunk_gap':
                    chunk.rename(store.folder / 'chunks' / '00000001.json')
                elif mutation == 'chain_sha':
                    record['previous_sha256'] = 'f' * 64
                    write_json(chunk, record)
                else:
                    # The chain itself is valid but no longer matches source prefix.
                    payload_path = store.folder / record['payload']['path']
                    records = json_rows(payload_path)
                    records[0]['key'][2] -= 1
                    write_rows(payload_path, records)
                    record['first_key'] = records[0]['key']
                    record['payload'] = cp.descriptor(store.folder, record['payload']['path'])
                    write_json(chunk, record)
                    latest = cp.read(store.folder / 'latest.json')
                    latest['last_manifest_sha256'] = cp.descriptor(store.folder, 'chunks/00000000.json')['sha256']
                    write_json(store.folder / 'latest.json', latest)
                with self.assertRaises((ValueError, cp.IntegrityError)):
                    reopened = worker.open_store(store.folder, value['binding'], source_root=value['bundle_root'],
                                                  clock=store.clock, process_api=store.processes)
                    run_full(value, reopened)
                self.assertFalse((store.folder / 'candidate.json').exists())
                self.assertFalse((store.folder / 'acceptance.json').exists())

    def test_A13_combined_global_and_original_draw_replay(self):
        for point in ('global_replay', 'bootstrap_draw', 'after_stage_global'):
            with self.subTest(case_id='A13.' + point, point=point):
                value = copied_input(self.small, 'A13-' + point)
                seen = Counter()
                def fault(event):
                    seen[event] += 1
                    if event == point: raise InjectedFailure(point)
                store = store_for(value, fault=fault)
                with self.assertRaises(InjectedFailure): run_full(value, store, fault)
                self.assertFalse((store.folder / 'candidate.json').exists())
                if point == 'after_stage_global':
                    self.assertIsNotNone(store.get_stage('global'))
                    self.assertIsNone(store.get_stage('bootstrap'))
                replay = Counter()
                reopened = worker.open_store(store.folder, value['binding'], source_root=value['bundle_root'],
                                              clock=store.clock, process_api=store.processes)
                run_full(value, reopened, lambda event: replay.update([event]))
                self.assertEqual(replay['global_replay'], value['binding']['expected_queries'])
                self.assertEqual(replay['bootstrap_draw'], 2000)
                self.assertEqual(science_bytes(reopened), read_golden(value))

    def test_A14_original_draw_identity_and_complete_count(self):
        mutations = ('order', 'draw_sha256', 'query_denominator', 'rng_before', 'rng_after', 'delta', 'missing', 'extra')
        for role in ('primary', 'C1'):
            for mutation in mutations:
                if role == 'C1' and mutation == 'delta':
                    continue  # Frozen reference-draw identity excludes its old C1-P0 delta.
                with self.subTest(case_id='A14.' + role + '.' + mutation, role=role, mutation=mutation):
                    value = copied_input(self.small, 'A14-' + role + '-' + mutation)
                    path = value['bundle_root'] / role / 'bootstrap.jsonl'
                    values = json_rows(path)
                    if mutation == 'order': values[0], values[1] = values[1], values[0]
                    elif mutation == 'draw_sha256': values[0][mutation] = '0' * 64
                    elif mutation == 'query_denominator': values[0][mutation] += 1
                    elif mutation in ('rng_before', 'rng_after'): values[0][mutation]['state']['state'] += 1
                    elif mutation == 'delta': values[0]['delta'] += 0.1
                    elif mutation == 'missing': values.pop()
                    else: values.append(deepcopy(values[-1]))
                    write_rows(path, values)
                    rebind_copied_input(value)
                    store = store_for(value)
                    with self.assertRaises((ValueError, cp.IntegrityError)): run_full(value, store)
                    self.assertIsNotNone(store.get_stage('queries'))
                    self.assertIsNone(store.get_stage('bootstrap'))
                    self.assertEqual(store.recover()['records'], value['binding']['expected_queries'])
                    self.assertFalse((store.folder / 'candidate.json').exists())
                    self.assertFalse((store.folder / 'acceptance.json').exists())


class ExactCoreTests(unittest.TestCase):
    def check_prediction(self, sessions, history, current=('999999', 999), catalog=None, counts=None, at=100, support_override=None):
        support = dict(Counter(item for members in sessions.values() for item in members)) if support_override is None else support_override
        counts = support if counts is None else counts
        catalog = dict.fromkeys(support, 0) if catalog is None else catalog
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
            db.executemany('INSERT INTO m VALUES(?,?,?)', ((v, session, item) for (v, session), members in sessions.items() for item in sorted(members, key=int)))
            sql4.build_index(db)
            prepared = sql4.prepare_catalog(catalog, counts)
            args = db, support, 'artificial', prepared.counts, prepared, at, history, current
            actual = worker.sql.predict(*args)
            self.assertEqual(actual, sql2.predict(*args))
            self.assertEqual(actual, v1.predict(sessions, support, 'artificial', counts, catalog, at, history, current))
            return actual

    def test_A04_hand_unknown_self_future_and_fallback(self):
        sessions = {('7', 1): {'1', '88'}, ('7', 2): {'1'}, ('10', 1): {'1', '2'}, ('2', 1): {'1', '3', '4'}}
        row = self.check_prediction(sessions, ['1', '999', '1'], ('7', 1),
                {'1': 1, '2': 1, '3': 1, '4': 100, '9': 1, '8': 1}, {'9': 3, '8': 3})
        self.assertEqual(row['ids'], ['1', '2', '3', '8', '9'])
        self.assertEqual(row['scores'], [[13, 12], [1, 3], [1, 4], [0, 1], [0, 1]])
        self.assertEqual((row['unknown_seeds'], row['current_session_excluded']), (1, 1))
        for history, current, reason in [([], ('7', 1), 'no_supported_seed'),
            (['1'], ('7', 1), 'only_self_session_overlap'), (['1'], ('7', 2), 'no_positive_causal_vote')]:
            with self.subTest(case_id='A04.fallback.' + reason, reason=reason):
                row = self.check_prediction({('7', 1): {'1'}}, history, current, {'1': 100, '2': 110})
                self.assertEqual(row['fallback_reason'], reason)

    def test_A04_no_eligible_positive_neighbor(self):
        row = self.check_prediction({('7', 1): {'1'}}, ['9'], ('7', 1),
                    {'1': 100, '2': 110}, support_override={'9': 1})
        self.assertEqual(row['fallback_reason'], 'no_eligible_positive_neighbor')

    def test_A04_exact_cutoff_499_500_501_and_large_ids(self):
        start = 10 ** 24 - 250
        for count in (499, 500, 501):
            with self.subTest(case_id='A04.neighbors.' + str(count), neighbors=count):
                sessions = {(str(start + i), 0): {'1'} if i % 2 else {'1', '2', '4', '5', '6'} for i in reversed(range(count))}
                row = self.check_prediction(sessions, ['1', '2', '3'])
                self.assertEqual([item['key'][0] for item in row['selected_neighbors']], [str(start + i) for i in range(min(count, 500))])
                self.assertEqual(row['boundary_ties_excluded'], max(0, count - 500))

    def test_A04_near_equal_ratios_and_fraction_scale_fallback(self):
        n = 10 ** 70
        for index, (a, b) in enumerate([((n + 1, n), (n + 2, n + 1)), ((n + 2, n + 1), (n + 1, n)), ((2, 6), (1, 3))]):
            with self.subTest(case_id='A04.ratio.' + str(index)):
                self.assertEqual(sql4._greater_ratio_first(a, b), (Fraction(*a) < Fraction(*b)) - (Fraction(*a) > Fraction(*b)))
        self.assertIsNone(sql4._common_scale(iter([2 ** 4096 + 1, 3])))
        sessions = {('1', 0): {'1'}, ('2', 0): {'1', '2'}, ('3', 0): {'1', '3', '4', '5'}}
        integers = self.check_prediction(sessions, ['1', '9'])
        with patch.object(sql4, 'MAX_VOTE_SCALE_BITS', 2):
            fractions = self.check_prediction(sessions, ['1', '9'])
        self.assertEqual(integers, fractions)


if __name__ == '__main__':
    unittest.main()
