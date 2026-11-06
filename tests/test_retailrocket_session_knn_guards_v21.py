"""Synthetic differential and fault checks for direct append observations."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_guards_v21 as diagnostic
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import run_retailrocket_session_knn_guards_v21 as entry
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from tests import test_retailrocket_session_knn_diagnostics_v20 as inherited


class GuardTests(unittest.TestCase):
    make_store = inherited.InstrumentationTests.make_store

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_full_verifier_payload_and_workload(self):
        original = diagnostic.diagnostic_rows
        def checked(*args):
            rows = original(*args)
            for row in rows:
                self.assertEqual(set(row['guard_counts'].values()), {1})
                for group, parent in (
                    ('guard_check_parts', row['append_phases']['guards_and_key']),
                    ('writer_check_parts', row['append_budget_check_parts']['writer_context_and_observer_other'])):
                    for clock in parent:
                        self.assertAlmostEqual(sum(p[clock] for p in row[group].values()), parent[clock])
            return rows
        with patch.object(inherited, 'diagnostic', diagnostic), patch.object(diagnostic, 'diagnostic_rows', checked):
            inherited.InstrumentationTests.test_complete_verifier_keeps_all_four_arm_payloads_and_nested_commit_diagnostics(self)

    def test_protocol_bytes_and_nested_budget_contexts(self):
        with patch.object(inherited, 'diagnostic', diagnostic):
            inherited.InstrumentationTests.test_append_protocol_bytes_match_v6_and_budget_reads_keep_exclusive_contexts(self)

    def test_budget_deadline_and_write_faults(self):
        with patch.object(inherited, 'diagnostic', diagnostic):
            inherited.InstrumentationTests.test_failed_append_budget_parse_deadline_and_fault_restore_contexts(self)

    def test_guard_short_circuit_identity_errors_and_original_filesystem_trace(self):
        originals = (cp.CheckpointStore._require_writer, cp.CheckpointStore._key,
                     DetailedTimedStore.append_verified, diagnostic.prior.DiagnosticTimedStore.append_verified)
        for failure in ('success', 'acceptance', 'candidate', 'global', 'key', 'ordinal', 'order', 'exists_error'):
            traces, errors = [], []
            for cls in (DetailedTimedStore, diagnostic.DiagnosticTimedStore):
                store = self.make_store(cls, failure+cls.__name__)
                with store.writer():
                    store.seal_stage('reconstruction', {})
                    if failure == 'order':
                        store.append_verified(0, ['2', 0, 0], {})
                    target = {'acceptance': 'acceptance.json', 'candidate': 'candidate.json',
                              'global': 'stages/global.json'}.get(failure)
                    if target:
                        (store.folder/target).write_text('{}', encoding='utf-8')
                    trace = []
                    original_exists = Path.exists
                    def exists(path):
                        trace.append(path.relative_to(store.folder).as_posix())
                        if failure == 'exists_error' and path.name == 'candidate.json':
                            raise PermissionError('synthetic path failure')
                        return original_exists(path)
                    try:
                        with patch.object(Path, 'exists', exists):
                            try:
                                store.append_verified(1 if failure in ('ordinal', 'order') else 0,
                                    ['01', 0, 0] if failure == 'key' else ['1', 0, 0], {})
                            except (cp.IntegrityError, PermissionError) as error:
                                errors.append((type(error), str(error)))
                            else:
                                errors.append(None)
                        traces.append(trace)
                        if cls is diagnostic.DiagnosticTimedStore:
                            event = store.append_diagnostics[-1]['guard_detail']
                            expected = ['acceptance'] if failure == 'acceptance' else (
                                ['acceptance', 'candidate'] if failure in ('candidate', 'exists_error')
                                else ['acceptance', 'candidate', 'global'])
                            self.assertEqual([e['purpose'] for e in event['exists']], expected)
                            self.assertEqual(len(event['identity']), int(failure not in ('acceptance', 'candidate', 'global', 'exists_error')))
                            self.assertEqual(event['completed'], failure == 'success')
                            self.assertIsNone(store._active_append_diagnostic)
                    finally:
                        if target:
                            (store.folder/target).unlink()
            self.assertEqual(traces[0], traces[1], failure)
            self.assertEqual(errors[0], errors[1], failure)
            self.assertEqual(errors[0] is None, failure == 'success')
        self.assertEqual(originals, (cp.CheckpointStore._require_writer, cp.CheckpointStore._key,
                         DetailedTimedStore.append_verified, diagnostic.prior.DiagnosticTimedStore.append_verified))

    def test_no_writer_rejects_before_any_filesystem_or_identity_check(self):
        store = self.make_store(diagnostic.DiagnosticTimedStore, 'no_writer')
        with self.assertRaises(cp.WriterBusy):
            store.append_verified(0, ['1', 0, 0], {})
        event = store.append_diagnostics[-1]['guard_detail']
        self.assertEqual((event['exists'], event['identity']), ([], []))
        self.assertFalse(event['writer_checks'][0]['completed'])

    def test_nested_signed_accounting_and_tamper_rejection(self):
        measured, observations, raw = inherited.hand_accounting()
        event = {'subset_ordinal': 0, 'completed': True,
                 'exists': [{'purpose': purpose, 'completed': True, 'result': False,
                             'total': inherited.span(.1, .2)} for purpose in ('acceptance', 'candidate', 'global')],
                 'identity': [{'completed': True, 'total': inherited.span(.1, .1)}],
                 'writer_checks': [{'completed': True, 'total': inherited.span(.5, .4)}]}
        raw['append'][0]['guard_detail'] = event
        result = diagnostic.diagnostic_rows(measured, observations, raw)[0]
        self.assertAlmostEqual(result['guard_check_parts']['order_reconstruction_dispatch_other']['wall_seconds'], .7)
        self.assertAlmostEqual(result['writer_check_parts']['context_and_observer_other']['wall_seconds'], 1.5)
        self.assertLess(result['writer_check_parts']['acceptance_exists']['wall_minus_thread_cpu_seconds'], 0)
        summary = diagnostic.summarize_diagnostics(measured, observations, raw)
        self.assertEqual(summary['guard_counts']['identity_format'], 1)
        for change in ('order', 'result', 'missing', 'identity', 'wall_exceeds', 'cpu_exceeds', 'unfinished'):
            changed = deepcopy(raw)
            e = changed['append'][0]['guard_detail']
            if change == 'order': e['exists'].reverse()
            elif change == 'result': e['exists'][0]['result'] = True
            elif change == 'missing': e['exists'].pop()
            elif change == 'identity': e['identity'].append(deepcopy(e['identity'][0]))
            elif change == 'wall_exceeds': e['identity'][0]['total'] = inherited.span(2, .1)
            elif change == 'cpu_exceeds': e['identity'][0]['total'] = inherited.span(.1, 4)
            else: e['completed'] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                diagnostic.diagnostic_rows(measured, observations, changed)


class FixedEvidenceTests(inherited.FixedEvidenceTests):
    def setUp(self):
        super().setUp()
        context = patch.object(inherited, 'entry', entry)
        context.start()
        self.addCleanup(context.stop)


if __name__ == '__main__':
    unittest.main()
