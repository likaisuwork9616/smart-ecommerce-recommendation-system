"""Fake launch/file/provenance cases; never launch a real calibration worker."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from scripts import run_retailrocket_session_knn_clock_calibration_v67 as driver
from scripts.retailrocket_session_knn_clock_capability_v67 import evaluate_capability
from tests.test_retailrocket_session_knn_wall_cpu_decision_v65 import capability_fixture


class DriverGuardTests(unittest.TestCase):
    def setUp(self):
        folder = driver.local(driver.PRIVATE)
        folder.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(prefix='v67-driver-fake-', dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        override = patch.object(driver, 'ROOT', self.root)
        override.start()
        self.addCleanup(override.stop)
        driver.local(driver.PRIVATE).mkdir(parents=True)
        driver.local('reports/stage12').mkdir(parents=True)
        seal, acceptance = driver.names(1)
        driver.write_new(seal, {'fake': 'seal'})
        driver.write_new(acceptance, {'fake': 'acceptance'})
        self.folder = driver.PRIVATE + 'fake-attempt'
        driver.local(self.folder).mkdir()

    def test_immutable_write_is_exclusive_and_hashes_flushed_bytes(self):
        row = driver.write_new('raw.json', {'integer': 10**28, 'text': '假資料'})
        self.assertEqual(row, driver.describe('raw.json'))
        self.assertEqual(driver.read('raw.json')['integer'], 10**28)
        with self.assertRaises(FileExistsError):
            driver.write_new('raw.json', {'overwrite': True})

    def test_fsync_failure_is_not_a_successful_persistence_receipt(self):
        with patch.object(driver.os, 'fsync', side_effect=OSError('fake storage failure')):
            with self.assertRaises(OSError):
                driver.write_new('failed.json', {'partial': True})
        self.assertTrue(driver.local('failed.json').exists())

    def test_real_attempt_reservation_cannot_repeat_across_revisions(self):
        driver.reserve_live(1, self.folder, 'a' * 40)
        for revision in (1, 2):
            for path in driver.names(revision):
                if not driver.local(path).exists():
                    driver.write_new(path, {'fake': revision})
            with self.assertRaises(FileExistsError):
                driver.reserve_live(revision, self.folder, 'a' * 40)

    def test_worker_claim_is_exclusive_even_after_a_failed_attempt(self):
        driver.reserve_live(1, self.folder, 'a' * 40)
        row = driver.claim_worker(self.folder, 1)
        self.assertEqual(driver.read(row['path']), {'reservation': driver.describe(driver.RESERVATION)})
        with self.assertRaises(FileExistsError):
            driver.claim_worker(self.folder, 1)

    def test_worker_claim_rejects_changed_receipt_or_folder(self):
        driver.reserve_live(1, self.folder, 'a' * 40)
        with self.assertRaises(ValueError):
            driver.claim_worker(driver.PRIVATE + 'different', 1)
        driver.local(driver.names(1)[1]).write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            driver.claim_worker(self.folder, 1)
        self.assertFalse(driver.local(self.folder + '/worker_claim.json').exists())

    def test_worker_claim_requires_a_preexisting_reservation(self):
        with self.assertRaises(FileNotFoundError):
            driver.claim_worker(self.folder, 1)

    def test_raw_and_attempt_paths_must_stay_in_the_private_workspace(self):
        for name in ('../outside.json',):
            with self.assertRaises(ValueError):
                driver.local(name)
        for name in ('reports/stage12', driver.PRIVATE):
            with self.assertRaises(ValueError):
                driver.private_folder(name)

    def test_successful_supervisor_launches_exactly_once_with_fixed_timeout(self):
        child = Mock(returncode=0)
        launch = Mock(return_value=child)
        value = driver.run_child(['fake-python', 'fake-worker'], driver.local('worker.log'), popen=launch)
        launch.assert_called_once()
        child.communicate.assert_called_once_with(timeout=30)
        child.kill.assert_not_called()
        self.assertEqual(value, dict(timeout=False, returncode=0, launch_error=None))

    def test_supervisor_timeout_kills_only_owned_child_and_never_relaunches(self):
        child = Mock(returncode=-1)
        child.communicate.side_effect = [subprocess.TimeoutExpired('fake-worker', 30), None]
        launch = Mock(return_value=child)
        value = driver.run_child(['fake-worker'], driver.local('worker.log'), popen=launch)
        launch.assert_called_once()
        child.kill.assert_called_once_with()
        self.assertEqual(child.communicate.call_count, 2)
        self.assertTrue(value['timeout'])

    def test_launch_error_is_retained_without_retry(self):
        launch = Mock(side_effect=OSError('fake launch failure'))
        value = driver.run_child(['fake-worker'], driver.local('worker.log'), popen=launch)
        launch.assert_called_once()
        self.assertEqual(value['launch_error']['type'], 'OSError')
        self.assertIsNone(value['returncode'])

    def test_missing_raw_and_outcome_never_become_a_pass(self):
        driver.reserve_live(1, self.folder, 'a' * 40)
        summary = driver.summarize(self.folder, dict(timeout=True, returncode=-1, launch_error=None))
        self.assertEqual(summary['status'], 'clock_capability_unconfirmed')
        self.assertFalse(summary['live_B_passed'])
        self.assertTrue(summary['raw_missing'])
        self.assertTrue(summary['outcome_missing'])

    def test_unpublished_main_is_rejected_before_measurement(self):
        with patch.object(driver, 'git', side_effect=[b'a\n', b'main\n', b'b\n']):
            with self.assertRaises(ValueError):
                driver.published([])

    def test_committed_source_bytes_must_match(self):
        row = driver.describe(driver.names(1)[0])
        with patch.object(driver, 'git', return_value=b'changed bytes'):
            with self.assertRaises(ValueError):
                driver.committed([row], 'fake-commit')

    def test_existing_attempt_blocks_measure_before_any_launch(self):
        driver.reserve_live(1, self.folder, 'a' * 40)
        with patch.object(driver, 'sealed', return_value={'methods': [], 'inputs': []}), \
                patch.object(driver, 'audit_acceptance'), \
                patch.object(driver, 'published', return_value='a' * 40), \
                patch.object(driver, 'run_child') as launch:
            with self.assertRaises(FileExistsError):
                driver.measure(1)
            launch.assert_not_called()

    def saved_fixture(self):
        driver.reserve_live(1, self.folder, 'a' * 40)
        driver.claim_worker(self.folder, 1)
        source = driver.describe(driver.names(1)[0])['sha256']
        record = capability_fixture()
        record['origin'] = 'real_clock_capability_v67'
        record['environment']['source_sha256'] = source
        decision = evaluate_capability(record, expected_origin=record['origin'],
            expected_source_sha256=source, expected_environment=record['environment'],
            expected_clocks=record['clocks'])
        collection = dict(metadata_raw=dict(environment=record['environment'], clocks=record['clocks']),
            control_reads=[], stop_reasons=[], errors=[], captured_stamps=53,
            requested_sleeps=10, primary_error=None)
        raw = dict(record=record, decision=decision, collection=collection.copy(), final=None,
            snapshot_status='provisional_before_raw_persistence')
        descriptor = driver.write_new(self.folder + '/raw.json', raw)
        collection['control_reads'] = [dict(phase='after_raw_persistence',
            wall_ns=record['ended_wall_ns'], error_type=None)]
        final = dict(status='clock_capability_passed', completed=True,
            ended_wall_ns=record['ended_wall_ns'], elapsed_wall_ns=record['elapsed_wall_ns'],
            raw_persisted_within_deadline=True, deadline_ns=30_000_000_000,
            live_B_passed=True, authorized_next_gate=False)
        saved = dict(source_sha256=source, readers=dict(wall='time.perf_counter_ns',
            cpu='time.thread_time_ns', thread='threading.get_ident', identity_checked=True),
            envelope=dict(record=record, decision=decision, collection=collection,
                          persistence=descriptor, final=final))
        return saved

    def test_readonly_summary_recomputes_decision_and_hides_raw_stamps(self):
        driver.write_new(self.folder + '/outcome.json', self.saved_fixture())
        result = driver.summarize(self.folder, dict(timeout=False, returncode=0, launch_error=None))
        self.assertTrue(result['live_B_passed'])
        self.assertNotIn('records', result['decision_summary'])
        self.assertNotIn('ended_wall_ns', result['final'])
        self.assertNotIn('thread_id', json.dumps(result))

    def test_readonly_audit_rejects_changed_final_classification(self):
        saved = self.saved_fixture()
        saved['envelope']['final']['status'] = 'cpu_resolution_insufficient'
        driver.write_new(self.folder + '/outcome.json', saved)
        with self.assertRaises(ValueError):
            driver.summarize(self.folder, dict(timeout=False, returncode=0, launch_error=None))

    def test_readonly_audit_preserves_invalid_last_control_as_failure(self):
        saved = self.saved_fixture()
        envelope = saved['envelope']
        envelope['collection']['control_reads'][-1].update(wall_ns=True, error_type='_Problem')
        envelope['collection']['stop_reasons'] = [dict(reason='invalid_wall_value',
            status='rejected_structure', phase='after_raw_persistence')]
        envelope['final'].update(status='rejected_structure', completed=False, ended_wall_ns=None,
            elapsed_wall_ns=None, raw_persisted_within_deadline=False, live_B_passed=False)
        driver.write_new(self.folder + '/outcome.json', saved)
        result = driver.summarize(self.folder, dict(timeout=False, returncode=0, launch_error=None))
        self.assertEqual(result['status'], 'rejected_structure')
        self.assertIsNone(result['elapsed_wall_ns'])

    def test_provisional_raw_without_final_receipt_cannot_publish_success(self):
        self.saved_fixture()
        result = driver.summarize(self.folder, dict(timeout=True, returncode=-1, launch_error=None))
        self.assertFalse(result['raw_missing'])
        self.assertTrue(result['outcome_missing'])
        self.assertFalse(result['live_B_passed'])

    def test_saved_complete_outcome_with_supervisor_timeout_stays_auditable_failure(self):
        driver.write_new(self.folder + '/outcome.json', self.saved_fixture())
        result = driver.summarize(self.folder, dict(timeout=True, returncode=-1, launch_error=None))
        self.assertEqual(result['status'], 'clock_capability_unconfirmed')
        self.assertFalse(result['live_B_passed'])
        self.assertTrue(result['final']['live_B_passed'])  # Collector evidence is not silently rewritten.

    def test_saved_success_requires_worker_claim(self):
        driver.write_new(self.folder + '/outcome.json', self.saved_fixture())
        # A separate fake path cannot borrow a completed envelope without its claim.
        with patch.object(driver, 'read', wraps=driver.read) as reader:
            def missing_claim(name):
                if name.endswith('/worker_claim.json'):
                    raise FileNotFoundError('fake missing claim')
                return reader._mock_wraps(name)
            reader.side_effect = missing_claim
            with self.assertRaises(FileNotFoundError):
                driver.summarize(self.folder, dict(timeout=False, returncode=0, launch_error=None))

    def test_saved_valid_control_rejects_bool_and_backwards_values(self):
        saved = self.saved_fixture()
        driver.write_new(self.folder + '/outcome.json', saved)
        last = saved['envelope']['collection']['control_reads'][-1]
        for point in (True, -1, saved['envelope']['record']['ended_wall_ns'] - 1):
            with self.subTest(point=point):
                last['wall_ns'] = point
                saved['envelope']['final']['ended_wall_ns'] = point
                with patch.object(driver, 'read', wraps=driver.read) as reader:
                    reader.side_effect = lambda name: saved if name.endswith('/outcome.json') else reader._mock_wraps(name)
                    with self.assertRaises(ValueError):
                        driver.summarize(self.folder, dict(timeout=False, returncode=0, launch_error=None))

    def test_public_failure_details_omit_machine_specific_error_text(self):
        saved = self.saved_fixture()
        error = dict(phase='after_raw_persistence', type='OSError', message='PRIVATE_MACHINE_PATH')
        saved['envelope']['collection']['errors'] = [error]
        saved['envelope']['collection']['primary_error'] = error
        saved['envelope']['collection']['stop_reasons'] = [dict(reason='dependency_error',
            status='clock_capability_unconfirmed', phase='after_raw_persistence')]
        saved['envelope']['final'].update(status='clock_capability_unconfirmed', completed=False, live_B_passed=False)
        driver.write_new(self.folder + '/outcome.json', saved)
        result = driver.summarize(self.folder, dict(timeout=False, returncode=0, launch_error=None))
        self.assertNotIn('PRIVATE_MACHINE_PATH', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
