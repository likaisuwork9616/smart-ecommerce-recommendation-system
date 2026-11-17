"""V75 control-level CP boundaries and locked query-guard acceptance cases.

These artificial CP ledgers test completion semantics, not K1 numerical output.
Full scientific fixtures/goldens are owned by the separate V75 integration suite.
Nothing is generated at import time; no acceptance is run before source sealing.
"""
import uuid
from pathlib import Path
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_full_worker_v75 as worker


SEMANTIC_MUTATIONS = ('wrong_count', 'bool_count', 'float_count', 'false_eof',
                      'integer_eof', 'string_eof', 'wrong_ledger')
PARENT_MUTATIONS = ('missing_stage', 'wrong_run')
PHASES = ('candidate', 'finalize', 'supersede')
ATOMIC_FAULTS = ('payload_half_written', 'after_payload_fsync',
                 'before_manifest_commit', 'after_manifest_commit')
CASE_IDS = (
    [f'A15.{phase}.{mutation}' for phase in PHASES
     for mutation in (*SEMANTIC_MUTATIONS, *PARENT_MUTATIONS)]
    + [f'A15.{phase}.valid' for phase in PHASES]
    + [f'A15.{phase}.candidate_mismatch' for phase in ('finalize', 'supersede')]
    + ['A15.writer_required', 'A15.artificial_count_contract',
       'A10.row_boundary_63_64_65', 'A10.time_boundary_120', 'A10.eof_short_tail']
    + [f'A11.{point}' for point in ATOMIC_FAULTS]
)


class FakeClock:
    def __init__(self):
        self.value = 1000.0
    def utc(self):
        return self.value
    def monotonic(self):
        return self.value
    def advance(self, seconds):
        self.value += seconds


class FakeProcesses:
    def __init__(self):
        self.pid = 1
        self.live = {1}
    def boot_identity(self):
        return 75
    def identity(self):
        return {'pid': self.pid, 'create_time': float(self.pid), 'boot_time': 75}
    def is_alive(self, identity):
        return identity == {'pid': identity['pid'], 'create_time': float(identity['pid']), 'boot_time': 75} and identity['pid'] in self.live
    def switch(self, pid):
        self.live.discard(self.pid)
        self.pid = pid
        self.live.add(pid)


def binding(queries=1):
    return {'profile': 'synthetic_only', 'fixture_id': 'F-control-guard',
            'expected_queries': queries, 'expected_visitors': 1,
            'bootstrap_replicates': 2000, 'sources': [],
            'configuration': {'synthetic_acceptance_only': True,
                              'fixed_validation': {'queries': queries, 'visitors': 1}},
            'method_seal_sha256': '0' * 64, 'fixture_seal_sha256': '0' * 64}


def key(ordinal):
    return ['1', 1, ordinal + 1]


class WorkerGuardCases(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / '.runtime' / 'v75' / 'cases' / ('guard-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True, exist_ok=False)
        self.serial = 0
        # Preserve every artificial run, tampered stage and failure receipt.

    def new_store(self, n=1, fault=None):
        self.serial += 1
        folder = self.root / str(self.serial)
        clock, processes = FakeClock(), FakeProcesses()
        store = worker.create_store(folder, binding(n), 5000.0, 3000,
                                    clock=clock, process_api=processes, fault=fault)
        return store, clock, processes

    def completed(self, candidate=True):
        store, clock, processes = self.new_store()
        with store.writer():
            store.seal_stage('reconstruction', {'artificial_control_only': True})
            store.append_verified(0, key(0), {'artificial_control_only': True})
            store.flush_chunk()
            store.seal_stage('queries', {'queries': 1, 'paired_streams_eof_checked': True})
            store.seal_stage('global', {'artificial_control_only': True})
            store.seal_stage('bootstrap', {'artificial_control_only': True})
            if candidate:
                store.write_candidate({'artificial_control_only': True})
        return store, clock, processes

    @staticmethod
    def refresh_candidate(store):
        path = store.folder / 'candidate.json'
        if not path.exists():
            return
        candidate = cp.read(path)
        candidate['stages'] = [cp.descriptor(store.folder, 'stages/' + stage + '.json')
                               for stage in worker.REQUIRED_STAGES
                               if (store.folder / 'stages' / (stage + '.json')).exists()]
        path.write_bytes(cp.encoded(candidate))

    @staticmethod
    def mutate(store, mutation):
        path = store.folder / 'stages' / 'queries.json'
        stage = cp.read(path)
        if mutation == 'missing_stage':
            # Preserve the original evidence; only the active stage is absent.
            path.rename(store.folder / 'recovery' / 'queries-missing-evidence.json')
            return
        if mutation == 'wrong_run':
            stage['run_sha256'] = 'f' * 64
        elif mutation == 'wrong_ledger':
            stage['ledger']['records'] = 0
        else:
            field, value = {
                'wrong_count': ('queries', 2), 'bool_count': ('queries', True),
                'float_count': ('queries', 1.0), 'false_eof': ('paired_streams_eof_checked', False),
                'integer_eof': ('paired_streams_eof_checked', 1),
                'string_eof': ('paired_streams_eof_checked', 'true')}[mutation]
            stage['receipt'][field] = value
        path.write_bytes(cp.encoded(stage))

    def invoke(self, opened, phase):
        if phase == 'finalize':
            candidate = cp.read(opened.folder / 'candidate.json')
            return opened.finalize(cp.descriptor(opened.folder, 'candidate.json')['sha256'],
                                   candidate['worker_identity'], 0)
        with opened.writer():
            if phase == 'supersede':
                return opened.supersede_candidate()
            return opened.write_candidate({'artificial_control_only': True})

    def test_A15_all_paths_reject_semantic_and_parent_faults_after_open(self):
        for phase in PHASES:
            for mutation in (*SEMANTIC_MUTATIONS, *PARENT_MUTATIONS):
                with self.subTest(case_id=f'A15.{phase}.{mutation}'):
                    prior, clock, processes = self.completed(candidate=phase != 'candidate')
                    processes.switch(2)
                    events = []
                    opened = worker.open_store(prior.folder, prior.binding, clock=clock,
                                               process_api=processes, fault=events.append)
                    # All mutations occur AFTER open, before the actual writer lock.
                    self.mutate(opened, mutation)
                    self.refresh_candidate(opened)
                    stage_files = {p.name: p.read_bytes() for p in (opened.folder / 'stages').iterdir()}
                    candidate_path = opened.folder / 'candidate.json'
                    candidate_bytes = candidate_path.read_bytes() if candidate_path.exists() else None
                    with self.assertRaises(cp.IntegrityError):
                        self.invoke(opened, phase)
                    if mutation in SEMANTIC_MUTATIONS:
                        self.assertIn('before_queries_completion_guard', events)
                    else:
                        self.assertNotIn('before_queries_completion_guard', events)
                    self.assertFalse((opened.folder / 'acceptance.json').exists())
                    self.assertEqual(candidate_path.read_bytes() if candidate_path.exists() else None,
                                     candidate_bytes)
                    self.assertEqual({p.name: p.read_bytes() for p in (opened.folder / 'stages').iterdir()},
                                     stage_files)
                    self.assertFalse(list((opened.folder / 'recovery').glob('*.superseded.json')))

    def test_A15_all_paths_accept_valid_current_locked_stage(self):
        for phase in PHASES:
            with self.subTest(case_id=f'A15.{phase}.valid'):
                prior, clock, processes = self.completed(candidate=phase != 'candidate')
                processes.switch(2)
                events = []
                opened = worker.open_store(prior.folder, prior.binding, clock=clock,
                                           process_api=processes, fault=events.append)
                result = self.invoke(opened, phase)
                self.assertIn('before_queries_completion_guard', events)
                if phase == 'candidate':
                    self.assertTrue((opened.folder / 'candidate.json').is_file())
                elif phase == 'finalize':
                    self.assertEqual(result['ledger']['records'], 1)
                    self.assertTrue((opened.folder / 'normal_worker_exit.json').is_file())
                else:
                    self.assertIsNotNone(result)
                    self.assertFalse((opened.folder / 'candidate.json').exists())
                    self.assertTrue(list((opened.folder / 'recovery').glob('*.candidate.json')))

    def test_A15_candidate_mismatch_is_not_accepted_or_superseded(self):
        for phase in ('finalize', 'supersede'):
            with self.subTest(case_id=f'A15.{phase}.candidate_mismatch'):
                prior, clock, processes = self.completed()
                processes.switch(2)
                events = []
                opened = worker.open_store(prior.folder, prior.binding, clock=clock,
                                           process_api=processes, fault=events.append)
                path = opened.folder / 'candidate.json'
                candidate = cp.read(path)
                candidate['ledger']['records'] = 0
                path.write_bytes(cp.encoded(candidate))
                old = path.read_bytes()
                with self.assertRaises(cp.IntegrityError):
                    self.invoke(opened, phase)
                self.assertIn('before_queries_completion_guard', events)
                self.assertEqual(path.read_bytes(), old)
                self.assertFalse((opened.folder / 'acceptance.json').exists())

    def test_A15_writer_required_and_artificial_exact_counts(self):
        store, _, _ = self.completed(candidate=False)
        with self.subTest(case_id='A15.writer_required'):
            with self.assertRaises(cp.WriterBusy):
                store._complete_checks()
        with self.subTest(case_id='A15.artificial_count_contract'):
            for n in (True, 1.0, 0, 130, 166897):
                bad = binding()
                bad['expected_queries'] = n
                with self.assertRaises(cp.IntegrityError):
                    worker.FullCheckpointStore(self.root / 'never-created', bad)
            for bad in ({'synthetic_acceptance_only': False}, {'fixed_validation': {'queries': True, 'visitors': 1}}):
                value = binding()
                value['configuration'].update(bad)
                with self.assertRaises(cp.IntegrityError):
                    worker.FullCheckpointStore(self.root / 'never-created', value)
            self.assertFalse((self.root / 'never-created').exists())

    def test_A10_count_boundary_and_eof_tail(self):
        store, _, _ = self.new_store(65)
        with store.writer():
            store.seal_stage('reconstruction', {'artificial_control_only': True})
            with self.subTest(case_id='A10.row_boundary_63_64_65'):
                for ordinal in range(63):
                    store.append_verified(ordinal, key(ordinal), {'n': ordinal})
                self.assertEqual(store._summary['records'], 0)
                self.assertEqual(store._pending_count, 63)
                store.append_verified(63, key(63), {'n': 63})
                self.assertEqual(store._summary['records'], 64)
                store.append_verified(64, key(64), {'n': 64})
                self.assertEqual(store._summary['records'], 64)
                self.assertEqual(store._pending_count, 1)
            with self.subTest(case_id='A10.eof_short_tail'):
                store.flush_chunk()
                self.assertEqual(store._summary['records'], 65)
                counts = [cp.read(p)['count'] for p in sorted((store.folder / 'chunks').iterdir())]
                self.assertEqual(counts, [64, 1])

    def test_A10_time_boundary_only_at_completed_append(self):
        with self.subTest(case_id='A10.time_boundary_120'):
            store, clock, _ = self.new_store(2)
            with store.writer():
                store.seal_stage('reconstruction', {'artificial_control_only': True})
                store.append_verified(0, key(0), {'n': 0})
                clock.advance(121)
                self.assertEqual(store._summary['records'], 0)
                self.assertEqual(store._pending_count, 1)
                # Simulated query is now complete; no polling committed it halfway.
                store.append_verified(1, key(1), {'n': 1})
                self.assertEqual(store._summary['records'], 2)
                self.assertEqual(store._pending_count, 0)

    def test_A11_atomic_faults_preserve_and_recover_contiguous_content(self):
        for point in ATOMIC_FAULTS:
            with self.subTest(case_id='A11.' + point):
                fired = []
                def fault(event):
                    if event == point and not fired:
                        fired.append(event)
                        raise RuntimeError('expected artificial interruption')
                store, clock, processes = self.new_store(1, fault)
                with self.assertRaisesRegex(RuntimeError, 'expected artificial interruption'):
                    with store.writer():
                        store.seal_stage('reconstruction', {'artificial_control_only': True})
                        store.append_verified(0, key(0), {'n': 0})
                        store.flush_chunk()
                self.assertEqual(fired, [point])
                evidence = {p.relative_to(store.folder).as_posix(): p.read_bytes()
                            for p in (store.folder / 'payloads').iterdir()}
                self.assertTrue(evidence)
                processes.switch(2)
                resumed = worker.open_store(store.folder, store.binding, clock=clock, process_api=processes)
                with resumed.writer():
                    n = resumed.recover()['records']
                    self.assertEqual(n, 1 if point == 'after_manifest_commit' else 0)
                    if n == 0:
                        resumed.append_verified(0, key(0), {'n': 0})
                        resumed.flush_chunk()
                records = list(resumed.iter_records())
                self.assertEqual(records, [{'ordinal': 0, 'key': key(0), 'payload': {'n': 0}}])
                for name, content in evidence.items():
                    self.assertEqual((store.folder / name).read_bytes(), content)
                self.assertFalse((store.folder / 'candidate.json').exists())
                self.assertFalse((store.folder / 'acceptance.json').exists())


if __name__ == '__main__':
    unittest.main()
