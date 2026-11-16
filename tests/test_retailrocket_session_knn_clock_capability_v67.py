"""V67 provenance fixtures only; no clock reads, sleep or actual calibration."""
from copy import deepcopy
import threading
import time
import unittest
from unittest.mock import Mock, patch

from scripts import retailrocket_session_knn_clock_capability_v67 as capability
from scripts import retailrocket_session_knn_wall_cpu_decision_v65 as original
from tests import test_retailrocket_session_knn_wall_cpu_decision_v65 as fixtures


EVIDENCE = []
SOURCE = fixtures.SOURCE
PRESENTATION_FIELDS = {
    'records', 'evaluation', 'live_measurement_executed',
    'measurement_executed_by_this_function', 'live_B_passed',
    'collector_attestation_required', 'source_binding_accepted',
    'authorized_next_measurement', 'v46_adoption_evidence',
}


def record_fixture(origin=capability.FAKE_ORIGIN, **options):
    record = fixtures.capability_fixture(**options)
    record['origin'] = origin
    return record


def evaluate(record, **options):
    binding = dict(expected_origin=record['origin'], expected_source_sha256=SOURCE,
                   expected_environment=deepcopy(record['environment']),
                   expected_clocks=deepcopy(record['clocks']))
    binding.update(options)
    return capability.evaluate_capability(record, **binding)


def arithmetic(result):
    return {key: value for key, value in result.items() if key not in PRESENTATION_FIELDS}


class CapabilityProvenanceTests(unittest.TestCase):
    def test_real_reader_identity_accepts_exact_objects_without_measurement(self):
        result = capability.validate_real_readers(
            time.perf_counter_ns, time.thread_time_ns, threading.get_ident)
        self.assertEqual(result, dict(reader_identity_validated=True, measurement_executed=False,
            wall='time.perf_counter_ns', cpu='time.thread_time_ns', thread='threading.get_ident'))

    def test_real_reader_identity_rejects_replacements_without_calling_them(self):
        for index in range(3):
            readers = [time.perf_counter_ns, time.thread_time_ns, threading.get_ident]
            replacement = Mock(side_effect=AssertionError('Readers must never be invoked here'))
            readers[index] = replacement
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    capability.validate_real_readers(*readers)
                replacement.assert_not_called()

    def test_real_reader_identity_rejects_clock_substitution_and_wrapping(self):
        for cpu_reader in (time.process_time_ns, lambda: time.thread_time_ns()):
            with self.subTest(cpu_reader=cpu_reader):
                with self.assertRaises(ValueError):
                    capability.validate_real_readers(time.perf_counter_ns, cpu_reader, threading.get_ident)

    def test_real_reader_identity_cannot_accept_a_missing_api_as_none(self):
        with patch.object(capability, '_REAL_READERS',
                          (time.perf_counter_ns, None, threading.get_ident)):
            with self.assertRaises(ValueError):
                capability.validate_real_readers(time.perf_counter_ns, None, threading.get_ident)

    def test_full_statistics_are_exactly_the_existing_b_arithmetic(self):
        synthetic = fixtures.capability_fixture()
        expected = original.evaluate_capability(synthetic)
        for origin in capability.ORIGINS:
            with self.subTest(origin=origin):
                record = record_fixture(origin)
                result = evaluate(record)
                self.assertEqual(arithmetic(result), arithmetic(expected))
                self.assertEqual(result['status'], 'clock_capability_passed')
                self.assertEqual(result['q_ns'], 10_000)
                self.assertEqual(result['brackets']['count'], 53)
                self.assertEqual(result['records']['origin'], origin)
                self.assertFalse(result['live_B_passed'])
        EVIDENCE.append(dict(case='V67_existing_B_arithmetic_exact', origins=list(capability.ORIGINS),
                             live_measurement_executed=False))

    def test_clone_has_same_code_and_only_two_replaced_globals(self):
        before = dict(original._capability.__globals__)
        admit, result = lambda value: None, lambda *args, **kwargs: None
        cloned = capability._clone_capability(admit, result)
        self.assertIs(cloned.__code__, original._capability.__code__)
        self.assertIs(cloned.__defaults__, original._capability.__defaults__)
        self.assertIs(cloned.__closure__, original._capability.__closure__)
        self.assertIsNot(cloned.__globals__, original._capability.__globals__)
        self.assertEqual(set(cloned.__globals__), set(before))
        for name, value in before.items():
            expected = admit if name == '_synthetic' else result if name == '_result' else value
            self.assertIs(cloned.__globals__[name], expected, name)
        evaluate(record_fixture())
        self.assertEqual(set(original._capability.__globals__), set(before))
        for name, value in before.items():
            self.assertIs(original._capability.__globals__[name], value, name)

    def test_origin_and_input_stay_unchanged_with_independent_raw_snapshot(self):
        record = record_fixture(capability.REAL_ORIGIN)
        before = deepcopy(record)
        result = evaluate(record)
        self.assertEqual(record, before)
        self.assertEqual(result['records'], before)
        self.assertIsNot(result['records'], record)
        record['rounds'][0]['stamps'][0]['thread_cpu_ns'] = 999
        self.assertEqual(result['records'], before)
        self.assertEqual(result['evaluation'],
                         'provided_real_records_not_measurement_by_this_function')

    def test_origin_binding_rejects_synthetic_and_cross_origin_claims(self):
        for origin, expected in (
                ('synthetic_fixture', capability.REAL_ORIGIN),
                (capability.FAKE_ORIGIN, capability.REAL_ORIGIN),
                (capability.REAL_ORIGIN, capability.FAKE_ORIGIN),
                (capability.REAL_ORIGIN, 'synthetic_fixture'),
                (True, capability.REAL_ORIGIN)):
            record = record_fixture(origin)
            with self.subTest(origin=origin, expected=expected):
                result = evaluate(record, expected_origin=expected)
                self.assertEqual(result['status'], 'rejected_structure')
                self.assertFalse(result['source_binding_accepted'])
                self.assertEqual(result['records']['origin'], origin)

    def test_source_hash_requires_explicit_matching_lowercase_sha256(self):
        for record_hash, expected_hash in (
                ('b'*64, SOURCE), (SOURCE, 'b'*64), (SOURCE, 'A'*64),
                (SOURCE, ''), (SOURCE, True), ('invalid', 'invalid')):
            record = record_fixture()
            record['environment']['source_sha256'] = record_hash
            with self.subTest(record_hash=record_hash, expected_hash=expected_hash):
                result = evaluate(record, expected_source_sha256=expected_hash)
                self.assertEqual(result['status'], 'rejected_structure')
                self.assertEqual(result['records'], record)

    def test_real_origin_requires_both_expected_metadata_bindings(self):
        record = record_fixture(capability.REAL_ORIGIN)
        for missing in ('expected_environment', 'expected_clocks'):
            with self.subTest(missing=missing):
                result = evaluate(record, **{missing: None})
                self.assertEqual(result['status'], 'rejected_structure')
                self.assertFalse(result['source_binding_accepted'])
        result = capability.evaluate_capability(record_fixture(),
            expected_origin=capability.FAKE_ORIGIN, expected_source_sha256=SOURCE)
        self.assertEqual(result['status'], 'clock_capability_passed')

    def test_environment_identity_and_exact_type_mismatches_are_rejected(self):
        record = record_fixture(capability.REAL_ORIGIN)
        for field, value in (('python', 'different'), ('os', 'different'),
                             ('process_id', 20), ('thread_id', 74), ('thread_id', 73.0)):
            expected = deepcopy(record['environment']); expected[field] = value
            with self.subTest(field=field, value=value):
                result = evaluate(record, expected_environment=expected)
                self.assertEqual(result['status'], 'rejected_structure')
                self.assertFalse(result['source_binding_accepted'])

    def test_clock_metadata_identity_and_bool_aliases_are_rejected(self):
        record = record_fixture(capability.REAL_ORIGIN)
        for field, value in (('api', 'time.process_time_ns'), ('implementation', 'different'),
                             ('available', 1), ('monotonic', False),
                             ('adjustable', True), ('resolution_seconds', '0.000000002')):
            expected = deepcopy(record['clocks']); expected['cpu'][field] = value
            with self.subTest(field=field, value=value):
                result = evaluate(record, expected_clocks=expected)
                self.assertEqual(result['status'], 'rejected_structure')
                self.assertFalse(result['source_binding_accepted'])

    def test_record_cannot_supply_live_pass_or_execution_attestation(self):
        for field in ('live_B_passed', 'live_measurement_executed',
                      'measurement_executed_by_this_function', 'collector_attestation'):
            record = record_fixture(capability.REAL_ORIGIN); record[field] = True
            with self.subTest(field=field):
                result = evaluate(record)
                self.assertEqual(result['status'], 'rejected_structure')
                self.assertFalse(result['live_B_passed'])
                self.assertFalse(result['live_measurement_executed'])
                self.assertEqual(result['records'][field], True)

    def test_arithmetic_pass_never_authorizes_live_pass_or_next_measurement(self):
        for origin in capability.ORIGINS:
            result = evaluate(record_fixture(origin))
            self.assertTrue(result['source_binding_accepted'])
            self.assertTrue(result['collector_attestation_required'])
            for field in ('live_B_passed', 'live_measurement_executed',
                          'measurement_executed_by_this_function',
                          'authorized_next_measurement', 'v46_adoption_evidence'):
                self.assertIs(result[field], False)

    def test_threshold_edges_and_nearest_rank_results_match_exactly(self):
        variants = []
        for seconds in ('0.0001', '0.0001000000001'):
            raw = fixtures.capability_fixture()
            raw['clocks']['cpu']['resolution_seconds'] = seconds
            variants.append(raw)
        variants.extend((
            fixtures.capability_fixture(cpu_steps=[[10_000]*19+[900_000], [10_000]*10, [10_000]*10]),
            fixtures.capability_fixture(cpu_steps=[[0]+[10_000]*9, [10_000]*10, [10_000]*10]),
            fixtures.capability_fixture(sleep_cpus=[5_000_001]*2+[5_000_000]*8),
            fixtures.capability_fixture(sleep_walls=[39_999_999]+[50_000_000]*9)))
        for index, synthetic in enumerate(variants):
            with self.subTest(index=index):
                expected = original.evaluate_capability(synthetic)
                record = deepcopy(synthetic); record['origin'] = capability.FAKE_ORIGIN
                self.assertEqual(arithmetic(evaluate(record)), arithmetic(expected))

    def test_partial_high_q_keeps_arithmetic_without_claiming_live_insufficiency(self):
        synthetic = fixtures.capability_fixture(cpu_steps=[[200_000]*10, [10_000]*10, [10_000]*10])
        synthetic.update(completed=False)
        synthetic['rounds'][0].update(completed=False, stop_reason='deadline')
        synthetic['rounds'][0]['stamps'] = synthetic['rounds'][0]['stamps'][:2]
        synthetic['rounds'][1:] = [None, None]
        synthetic['sleeps'] = [None]*10
        expected = original.evaluate_capability(synthetic)
        record = deepcopy(synthetic); record['origin'] = capability.REAL_ORIGIN
        result = evaluate(record)
        self.assertEqual(arithmetic(result), arithmetic(expected))
        self.assertEqual(result['q_ns'], 200_000)
        self.assertEqual(result['status'], 'cpu_resolution_insufficient')
        self.assertIn('round_1_incomplete_or_cap', result['failure_reasons'])
        self.assertIn('round_1_insufficient_positive_cpu', result['failure_reasons'])
        self.assertFalse(result['live_B_passed'])
        self.assertTrue(result['collector_attestation_required'])
        self.assertEqual(result['records'], record)

    def test_missing_slots_and_partial_endpoints_are_preserved(self):
        synthetic = fixtures.capability_fixture()
        synthetic['completed'] = False
        synthetic['rounds'][2] = None
        synthetic['sleeps'][0]['end'] = None
        synthetic['sleeps'][0]['completed'] = False
        synthetic['sleeps'][1:] = [None]*9
        expected = original.evaluate_capability(synthetic)
        record = deepcopy(synthetic); record['origin'] = capability.FAKE_ORIGIN
        result = evaluate(record)
        self.assertEqual(arithmetic(result), arithmetic(expected))
        self.assertEqual(result['status'], 'clock_capability_unconfirmed')
        self.assertEqual(result['records'], record)
        self.assertIsNone(result['records']['rounds'][2])
        self.assertIsNone(result['records']['sleeps'][0]['end'])

    def test_original_structural_refusals_keep_raw_values_and_status(self):
        for case in ('wrong_api', 'cross_thread', 'backward_cpu', 'bool_wall', 'outer_envelope'):
            synthetic = fixtures.capability_fixture()
            if case == 'wrong_api': synthetic['clocks']['cpu']['api'] = 'time.process_time_ns'
            elif case == 'cross_thread': synthetic['rounds'][0]['stamps'][0]['thread_id'] = 74
            elif case == 'backward_cpu': synthetic['rounds'][0]['stamps'][2]['thread_cpu_ns'] = 5_000
            elif case == 'bool_wall': synthetic['rounds'][0]['stamps'][0]['wall_before_ns'] = True
            else: synthetic['started_wall_ns'] = 11_000_000
            with self.subTest(case=case):
                expected = original.evaluate_capability(synthetic)
                record = deepcopy(synthetic); record['origin'] = capability.REAL_ORIGIN
                result = evaluate(record)
                self.assertEqual(arithmetic(result), arithmetic(expected))
                self.assertEqual(result['status'], 'rejected_structure')
                self.assertEqual(result['records'], record)


if __name__ == '__main__':
    unittest.main()
