"""Standalone fake cases for the V85 Windows evidence-source interfaces."""

from collections import deque
from dataclasses import replace
import unittest

from scripts import retailrocket_session_knn_file_identity_v85 as file_ids
from scripts import retailrocket_session_knn_lock_owner_v83 as owners
from scripts import retailrocket_session_knn_qpc_v85 as qpc


_CLOCK_DOMAIN = qpc.ClockDomain('host-a', 'boot-a', 'capture-a', 'win-amd64', 'cpython-3.12.10', 'backend-a')
_FREQUENCY = 3_000_000
_ORIGIN = 2**55
_PROCESSES = frozenset({'outer-a', 'pipeline-b'})
_QUALIFICATION = qpc.ClockQualification(
    _CLOCK_DOMAIN, _FREQUENCY, _ORIGIN, _PROCESSES, verified=True,
)


class _FakeQpc:
    def __init__(self, ticks, *, frequency=_FREQUENCY):
        self.ticks = ticks
        self.frequency = frequency
        self.calls = []

    def query_performance_frequency(self):
        self.calls.append('frequency')
        if isinstance(self.frequency, qpc.QpcApiResult):
            return self.frequency
        return qpc.QpcApiResult(True, self.frequency)

    def query_performance_counter(self):
        self.calls.append('counter')
        if isinstance(self.ticks, qpc.QpcApiResult):
            return self.ticks
        return qpc.QpcApiResult(True, self.ticks)


def _read_sample(backend, *, process='outer-a', **options):
    return qpc.read_qpc_sample(backend, domain=_CLOCK_DOMAIN, process_key=process, **options)


def _sample_bounds(delta, process, *, before=0, after=0):
    sample = _read_sample(_FakeQpc(_ORIGIN + delta), process=process)
    return owners.Bounds(*qpc.sample_bounds_ns(
        sample, _QUALIFICATION, before_ticks=before, after_ticks=after,
    ))


def _classify_synthetic_hold(*, acquired, begin, end, release_begin, common_clock_verified=True):
    scope = owners.Scope('a' * 64, 'run-a', 'fake-file', 'generation-a', 'fake-clock', 'boot-a')
    attempt = owners.Attempt(
        owners.Actor('pipeline', 2, 'pipeline-b', 'boot-a'), scope, 'fake-attempt', 0, begin, end,
        conflict='confirmed_conflict',
    )
    hold = owners.Hold(
        owners.Actor('outer', 1, 'outer-a', 'boot-a'), scope, 'fake-hold', acquired,
        release_begin=release_begin, continuous=True,
    )
    return owners.classify_owner(
        attempt, [hold], coverage_complete=True, common_clock_verified=common_clock_verified,
    )


class FakeQpcTests(unittest.TestCase):
    def test_raw_counter_and_rate_are_exact_above_float_precision(self):
        backend = _FakeQpc(2**63 - 1, frequency=2**53 + 1)
        sample = _read_sample(backend)
        self.assertEqual(backend.calls, ['frequency', 'counter'])
        self.assertEqual(sample, qpc.QpcSample(_CLOCK_DOMAIN, 'outer-a', 2**63 - 1, 2**53 + 1))
        self.assertIs(type(sample.ticks), int)
        self.assertIs(type(sample.frequency_hz), int)

    def test_native_failure_preserves_error_and_stops_frequency_first(self):
        failed_frequency = _FakeQpc(_ORIGIN, frequency=qpc.QpcApiResult(False, None, 50))
        failed_counter = _FakeQpc(qpc.QpcApiResult(False, None, 5))
        for backend, expected_calls, expected_operation, expected_error in (
            (failed_frequency, ['frequency'], 'QueryPerformanceFrequency', 50),
            (failed_counter, ['frequency', 'counter'], 'QueryPerformanceCounter', 5),
            (_FakeQpc(qpc.QpcApiResult(False, _ORIGIN, 0)), ['frequency', 'counter'],
             'QueryPerformanceCounter', None),
        ):
            with self.subTest(expected_calls=expected_calls):
                with self.assertRaises(qpc.QpcEvidenceError) as error:
                    _read_sample(backend)
                self.assertEqual(error.exception.winerror, expected_error)
                self.assertEqual(error.exception.operation, expected_operation)
                self.assertEqual(backend.calls, expected_calls)

    def test_rejects_unusable_ticks_or_frequency(self):
        for backend in (
            _FakeQpc(-1), _FakeQpc(True), _FakeQpc(2**63), _FakeQpc(float(_ORIGIN)),
            _FakeQpc(_ORIGIN, frequency=0), _FakeQpc(_ORIGIN, frequency=-1),
            _FakeQpc(_ORIGIN, frequency=True), _FakeQpc(_ORIGIN, frequency=2**63),
            _FakeQpc(_ORIGIN, frequency=3_000_000.0),
        ):
            with self.subTest(ticks=backend.ticks, frequency=backend.frequency):
                with self.assertRaises(qpc.QpcEvidenceError):
                    _read_sample(backend)

    def test_rejects_inversion_or_frequency_change_in_same_process(self):
        previous = _read_sample(_FakeQpc(_ORIGIN))
        self.assertEqual(_read_sample(_FakeQpc(_ORIGIN), previous=previous), previous)
        for backend in (_FakeQpc(_ORIGIN - 1), _FakeQpc(_ORIGIN + 1, frequency=_FREQUENCY + 1)):
            with self.subTest(ticks=backend.ticks, frequency=backend.frequency):
                with self.assertRaises(qpc.QpcEvidenceError):
                    _read_sample(backend, previous=previous)
        with self.assertRaises(qpc.QpcEvidenceError):
            _read_sample(_FakeQpc(_ORIGIN + 1), process='pipeline-b', previous=previous)

    def test_shared_origin_preserves_fractional_ticks_with_outward_rounding(self):
        self.assertEqual(_sample_bounds(-1, 'outer-a'), owners.Bounds(-667, 0))
        self.assertEqual(_sample_bounds(2, 'pipeline-b', before=2, after=4), owners.Bounds(-334, 2334))

    def test_unqualified_sample_or_invalid_margins_have_no_bounds(self):
        sample = _read_sample(_FakeQpc(_ORIGIN))
        for qualification, changed_sample in (
            (replace(_QUALIFICATION, verified=False), sample),
            (_QUALIFICATION, replace(sample, domain=replace(_CLOCK_DOMAIN, host_id='host-b'))),
            (_QUALIFICATION, replace(sample, domain=replace(_CLOCK_DOMAIN, boot_id='boot-b'))),
            (_QUALIFICATION, replace(sample, domain=replace(_CLOCK_DOMAIN, capture_id='capture-b'))),
            (_QUALIFICATION, replace(sample, domain=replace(_CLOCK_DOMAIN, platform_id='win-arm64'))),
            (_QUALIFICATION, replace(sample, domain=replace(_CLOCK_DOMAIN, runtime_id='cpython-3.13.0'))),
            (_QUALIFICATION, replace(sample, domain=replace(_CLOCK_DOMAIN, adapter_id='backend-b'))),
            (_QUALIFICATION, replace(sample, domain=replace(_CLOCK_DOMAIN, source='other-source'))),
            (_QUALIFICATION, replace(sample, frequency_hz=_FREQUENCY + 1)),
            (_QUALIFICATION, replace(sample, process_key='unknown-role')),
        ):
            with self.subTest(qualification=qualification, sample=changed_sample):
                with self.assertRaises(qpc.QpcEvidenceError):
                    qpc.sample_bounds_ns(changed_sample, qualification, before_ticks=0, after_ticks=0)
        for before, after in ((-1, 0), (0, True), (0.0, 0), (0, 2**63)):
            with self.subTest(before=before, after=after):
                with self.assertRaises(qpc.QpcEvidenceError):
                    qpc.sample_bounds_ns(sample, _QUALIFICATION, before_ticks=before, after_ticks=after)

    def test_synthetic_cross_role_interval_strictly_contains_attempt(self):
        result = _classify_synthetic_hold(
            acquired=_sample_bounds(0, 'outer-a', after=2),
            begin=_sample_bounds(8, 'pipeline-b', before=1),
            end=_sample_bounds(12, 'pipeline-b', after=1),
            release_begin=_sample_bounds(20, 'outer-a', before=2),
        )
        self.assertEqual(result['status'], 'confirmed_holder_during_attempt')
        self.assertEqual(result['owner']['creation_id'], 'outer-a')

    def test_touching_or_one_tick_apart_cannot_establish_containment(self):
        for begin_delta, end_delta in ((1, 12), (4, 12), (8, 15)):
            with self.subTest(begin_delta=begin_delta, end_delta=end_delta):
                result = _classify_synthetic_hold(
                    acquired=_sample_bounds(0, 'outer-a', after=2),
                    begin=_sample_bounds(begin_delta, 'pipeline-b'),
                    end=_sample_bounds(end_delta, 'pipeline-b', after=2),
                    release_begin=_sample_bounds(20, 'outer-a', before=1),
                )
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['owner'])

    def test_missing_clock_proof_leaves_causal_order_unknown(self):
        result = _classify_synthetic_hold(
            acquired=_sample_bounds(0, 'outer-a'),
            begin=_sample_bounds(8, 'pipeline-b'),
            end=_sample_bounds(12, 'pipeline-b'),
            release_begin=_sample_bounds(20, 'outer-a'),
            common_clock_verified=False,
        )
        self.assertEqual(result['reason'], 'coverage_or_common_clock_not_verified')
        self.assertIsNone(result['owner'])

    def test_reversed_attempt_bounds_are_inconsistent(self):
        result = _classify_synthetic_hold(
            acquired=_sample_bounds(0, 'outer-a'),
            begin=_sample_bounds(12, 'pipeline-b'),
            end=_sample_bounds(8, 'pipeline-b'),
            release_begin=_sample_bounds(20, 'outer-a'),
        )
        self.assertEqual(result['reason'], 'rejection_sample_order_impossible')
        self.assertIsNone(result['owner'])


_FILE_FD = 9
_VOLUME = 0xFEDCBA9876543210
_FILE_ID = bytes.fromhex('ff800123456789ab00cdef1032547698')
_PAYLOAD = _VOLUME.to_bytes(8, 'little') + _FILE_ID
_BINDING = file_ids.OpenBinding(
    host_id='host-a', boot_id='boot-a', run_id='run-a', request_sha256='a' * 64,
    capture_id='capture-a',
    provider_id='provider-a', filesystem='NTFS', generation_id='generation-a',
    generation_proof_id='overlap-a', relative_path='control/budgets/budget.guard',
    role='outer', pid=1, creation_id='outer-a', open_id='open-a',
    local_regular_default_stream_verified=True, canonical_path_verified=True,
    generation_continuity_verified=True,
)


class _FakeStream:
    def __init__(self, fd=_FILE_FD, *, closed=False):
        self.descriptors = deque((fd, fd))
        self.closed = closed

    def fileno(self):
        return self.descriptors.popleft()


class _FakeFileIdBackend:
    def __init__(self, *, open_ids=('open-a', 'open-a'), handles=(123, 123),
                 reply=None, pointer_bits=64):
        self._open_ids = deque(open_ids)
        self._handles = deque(handles)
        self._reply = file_ids.FileIdReply(True, _PAYLOAD) if reply is None else reply
        self.pointer_bits = pointer_bits
        self.calls = []

    def current_open_id(self, stream):
        self.calls.append(('open_id', stream))
        return self._open_ids.popleft()

    def get_osfhandle(self, fd):
        self.calls.append(('handle', fd))
        return self._handles.popleft()

    def get_file_information_by_handle_ex(self, handle, info_class, size):
        self.calls.append(('query', handle, info_class, size))
        return self._reply


def _capture_file(backend=None, *, stream=None, fd=_FILE_FD, binding=_BINDING):
    if backend is None:
        backend = _FakeFileIdBackend(open_ids=(binding.open_id, binding.open_id))
    if stream is None:
        stream = _FakeStream()
    return file_ids.capture_file_identity(stream, fd=fd, binding=binding, backend=backend)


class FakeFileIdTests(unittest.TestCase):
    def test_borrows_same_fd_and_preserves_all_identity_bits(self):
        stream = _FakeStream()
        backend = _FakeFileIdBackend(handles=(-(2**63) + 123, -(2**63) + 123))
        captured = _capture_file(backend, stream=stream)
        self.assertEqual(captured.status, 'captured')
        self.assertEqual(captured.binding, _BINDING)
        self.assertEqual(captured.key.volume_serial, _VOLUME)
        self.assertEqual(captured.key.file_id, _FILE_ID)
        self.assertEqual(captured.key.to_record(), {
            'volume_serial_hex': 'fedcba9876543210',
            'file_id_hex': 'ff800123456789ab00cdef1032547698',
        })
        self.assertEqual(backend.calls, [
            ('open_id', stream), ('handle', _FILE_FD), ('query', 2**63 + 123, 0x12, 24),
            ('open_id', stream), ('handle', _FILE_FD),
        ])
        self.assertFalse(stream.descriptors)
        self.assertFalse(stream.closed)

    def test_32bit_high_bit_handle_retains_unsigned_value(self):
        backend = _FakeFileIdBackend(handles=(-2**31 + 123, 2**31 + 123), pointer_bits=32)
        self.assertEqual(_capture_file(backend).status, 'captured')
        self.assertIn(('query', 2**31 + 123, 0x12, 24), backend.calls)

    def test_rejects_fd_mismatch_closed_stream_and_unusable_handles(self):
        for stream, fd in ((_FakeStream(10), _FILE_FD), (_FakeStream(closed=True), _FILE_FD),
                           (_FakeStream(), True), (_FakeStream(-1), -1)):
            with self.subTest(closed=stream.closed, fd=fd):
                backend = _FakeFileIdBackend()
                self.assertEqual(_capture_file(backend, stream=stream, fd=fd).status, 'unknown')
                self.assertFalse(any(call[0] in ('handle', 'query') for call in backend.calls))
        for bits, handle in ((32, 0), (32, -1), (32, 2**32 - 1), (32, 2**32),
                             (64, True), (64, -1), (64, 2**64 - 1), (64, -2), (64, 2**64 - 2)):
            with self.subTest(bits=bits, handle=handle):
                backend = _FakeFileIdBackend(handles=(handle,), pointer_bits=bits)
                self.assertEqual(_capture_file(backend).status, 'unknown')
                self.assertFalse(any(call[0] == 'query' for call in backend.calls))

    def test_file_id_api_failure_preserves_winerror_without_fallback(self):
        backend = _FakeFileIdBackend(reply=file_ids.FileIdReply(False, _PAYLOAD, 50))
        captured = _capture_file(backend)
        self.assertEqual(captured.status, 'unknown')
        self.assertEqual(captured.reason, 'file_id_query_failed')
        self.assertEqual(captured.winerror, 50)
        self.assertIsNone(captured.key)
        self.assertEqual([call for call in backend.calls if call[0] == 'query'], [('query', 123, 0x12, 24)])

    def test_missing_winerror_does_not_reuse_a_failure_code(self):
        for winerror in (None, 0):
            with self.subTest(winerror=winerror):
                backend = _FakeFileIdBackend(reply=file_ids.FileIdReply(False, None, winerror))
                captured = _capture_file(backend)
                self.assertEqual(captured.status, 'unknown')
                self.assertEqual(captured.reason, 'file_id_query_failed_without_winerror')
                self.assertIsNone(captured.winerror)
                self.assertIsNone(captured.key)

    def test_file_id_error_stays_available_if_open_changes_afterward(self):
        backend = _FakeFileIdBackend(open_ids=('open-a', 'other-open'),
                                     reply=file_ids.FileIdReply(False, None, 50))
        captured = _capture_file(backend)
        self.assertEqual(captured.status, 'unknown')
        self.assertEqual(captured.reason, 'open_or_handle_changed')
        self.assertEqual(captured.winerror, 50)
        self.assertIsNone(captured.key)

    def test_reply_must_contain_exact_full_file_id_info_and_a_usably_distinct_id(self):
        initial_volume = _PAYLOAD[:8]
        for payload in (_PAYLOAD[:-1], _PAYLOAD + b'\x00', bytearray(_PAYLOAD),
                        initial_volume + bytes(16), initial_volume + b'\xff' * 16):
            with self.subTest(payload=payload):
                backend = _FakeFileIdBackend(reply=file_ids.FileIdReply(True, payload))
                captured = _capture_file(backend)
                self.assertEqual(captured.status, 'unknown')
                self.assertIsNone(captured.key)

    def test_open_generation_or_handle_change_during_capture_fails_closed(self):
        stale = _FakeFileIdBackend(open_ids=('other-open',))
        self.assertEqual(_capture_file(stale).status, 'unknown')
        self.assertFalse(any(call[0] == 'query' for call in stale.calls))
        for backend in (_FakeFileIdBackend(open_ids=('open-a', 'other-open')),
                        _FakeFileIdBackend(handles=(123, 456))):
            with self.subTest(backend=backend):
                self.assertEqual(_capture_file(backend).status, 'unknown')
                self.assertEqual([call for call in backend.calls if call[0] == 'query'],
                                 [('query', 123, 0x12, 24)])

    def test_fd_rebound_after_query_cannot_be_borrowed_again(self):
        stream = _FakeStream()
        stream.descriptors[-1] = _FILE_FD + 1
        backend = _FakeFileIdBackend()
        self.assertEqual(_capture_file(backend, stream=stream).status, 'unknown')
        self.assertEqual(backend.calls, [
            ('open_id', stream), ('handle', _FILE_FD), ('query', 123, 0x12, 24),
        ])

    def test_foreign_or_ambiguous_file_paths_are_not_admitted(self):
        for changed in (
            replace(_BINDING, local_regular_default_stream_verified=False),
            replace(_BINDING, canonical_path_verified=False),
            replace(_BINDING, relative_path='control/../budget.guard'),
            replace(_BINDING, relative_path='control/budget.guard:alternate'),
            replace(_BINDING, relative_path='//server/share/budget.guard'),
        ):
            with self.subTest(binding=changed):
                captured = _capture_file(binding=changed)
                self.assertEqual(captured.status, 'unknown')
                self.assertIsNone(captured.key)

    def test_independent_role_opens_can_share_one_file_generation(self):
        other = replace(_BINDING, role='pipeline', pid=2, creation_id='pipeline-b', open_id='open-b')
        other_backend = _FakeFileIdBackend(open_ids=('open-b', 'open-b'), handles=(789, 789))
        self.assertEqual(file_ids.compare_file_identity(
            _capture_file(), _capture_file(other_backend, binding=other),
        )['status'], 'same_file_generation')

    def test_same_identity_requires_common_scope_path_and_generation_proof(self):
        left = _capture_file()
        for field, other in (
            ('host_id', 'host-b'), ('boot_id', 'boot-b'), ('run_id', 'run-b'), ('capture_id', 'capture-b'),
            ('request_sha256', 'b' * 64), ('provider_id', 'provider-b'),
            ('generation_id', 'generation-b'), ('generation_proof_id', 'overlap-b'),
            ('relative_path', 'control/alias.guard'),
        ):
            with self.subTest(field=field):
                binding = replace(_BINDING, **{field: other})
                self.assertEqual(file_ids.compare_file_identity(left, _capture_file(binding=binding))['status'],
                                 'unknown')
        unproved = replace(_BINDING, generation_continuity_verified=False, generation_proof_id=None)
        captured = _capture_file(binding=unproved)
        self.assertEqual(captured.status, 'captured')
        self.assertEqual(file_ids.compare_file_identity(left, captured)['status'], 'unknown')

    def test_comparison_checks_high_file_id_bits_and_full_volume_serial(self):
        left = _capture_file()
        for payload in (
            (_VOLUME ^ 2**63).to_bytes(8, 'little') + _FILE_ID,
            _PAYLOAD[:-1] + bytes([_PAYLOAD[-1] ^ 0x80]),
        ):
            with self.subTest(payload=payload):
                backend = _FakeFileIdBackend(reply=file_ids.FileIdReply(True, payload))
                self.assertEqual(file_ids.compare_file_identity(left, _capture_file(backend))['status'],
                                 'different_file')
