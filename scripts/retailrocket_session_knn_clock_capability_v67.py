"""Admit V67 provenance to the unchanged V65 B arithmetic over supplied records.

This module never reads clocks or runs a calibration.  A real-origin record is
still only supplied evidence here: the collector/driver must separately attest
actual execution, completion, the 30-second deadline and persistence.  In
particular, V65's q over an incomplete round is not a completed-round early-stop
decision; the collector must preserve it and apply the V66 completion rules.
"""
from copy import deepcopy
import threading
import time
from types import FunctionType

from scripts import retailrocket_session_knn_wall_cpu_decision_v65 as decision


REAL_ORIGIN = 'real_clock_capability_v67'
FAKE_ORIGIN = 'fake_clock_capability_v67'
ORIGINS = (REAL_ORIGIN, FAKE_ORIGIN)
_REAL_READERS = (getattr(time, 'perf_counter_ns', None),
                 getattr(time, 'thread_time_ns', None),
                 getattr(threading, 'get_ident', None))


def validate_real_readers(wall_clock, cpu_clock, thread_identity):
    """Check actual reader objects without invoking clocks or thread identity."""
    readers = (wall_clock, cpu_clock, thread_identity)
    if any(not callable(expected) or reader is not expected
           for reader, expected in zip(readers, _REAL_READERS)):
        raise ValueError('Real B requires the exact perf_counter_ns/thread_time_ns/get_ident readers')
    return dict(reader_identity_validated=True, measurement_executed=False,
                wall='time.perf_counter_ns', cpu='time.thread_time_ns',
                thread='threading.get_ident')


def _exact_equal(left, right):
    """Metadata equality must not treat bool/float aliases as exact integers."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (set(left) == set(right)
                and all(_exact_equal(left[key], right[key]) for key in left))
    if type(left) in (list, tuple):
        return len(left) == len(right) and all(
            _exact_equal(a, b) for a, b in zip(left, right))
    return left == right


def _clone_capability(admit, result):
    """Only these two call-local globals differ; V65's code remains untouched."""
    original = decision._capability
    namespace = dict(original.__globals__)
    namespace['_synthetic'] = admit
    namespace['_result'] = result
    cloned = FunctionType(original.__code__, namespace, original.__name__,
                          original.__defaults__, original.__closure__)
    cloned.__kwdefaults__ = original.__kwdefaults__
    return cloned


def evaluate_capability(record, *, expected_origin, expected_source_sha256,
                        expected_environment=None, expected_clocks=None):
    """Evaluate canonical V65 B records without converting their V67 origin.

    Source binding is mandatory for either origin.  Real-origin replay also
    requires exact expected environment and clock metadata, captured/bound by
    the driver.  These expectations are not proof that this pure function or
    its caller actually ran a clock: live execution remains separately attested.
    Unknown fields, including caller-provided live-pass claims, stay rejected.
    """
    expected_environment = deepcopy(expected_environment)
    expected_clocks = deepcopy(expected_clocks)
    admission = dict(accepted=False)

    def admit(raw):
        if type(expected_origin) is not str or expected_origin not in ORIGINS:
            raise ValueError('An explicit V67 real or fake expected origin is required')
        if type(raw['origin']) is not str or raw['origin'] != expected_origin:
            raise ValueError('V67 record origin differs from the expected origin')
        decision._sha(expected_source_sha256)
        if raw['environment']['source_sha256'] != expected_source_sha256:
            raise ValueError('V67 record source SHA256 differs from the expected binding')
        if expected_origin == REAL_ORIGIN and (
                expected_environment is None or expected_clocks is None):
            raise ValueError('Real-origin replay requires expected environment and clocks')
        if expected_environment is not None and not _exact_equal(
                raw['environment'], expected_environment):
            raise ValueError('V67 record environment differs from its expected binding')
        if expected_clocks is not None and not _exact_equal(raw['clocks'], expected_clocks):
            raise ValueError('V67 record clocks differ from their expected binding')
        admission['accepted'] = True

    def result(status, reasons, raw, **values):
        scope = ('provided_real_records_not_measurement_by_this_function'
                 if expected_origin == REAL_ORIGIN else
                 'provided_fake_records_only' if expected_origin == FAKE_ORIGIN else
                 'provided_records_not_measurement_by_this_function')
        return dict(status=status, failure_reasons=reasons, records=deepcopy(raw),
            evaluation=scope, source_binding_accepted=admission['accepted'],
            live_measurement_executed=False, measurement_executed_by_this_function=False,
            live_B_passed=False, collector_attestation_required=True,
            authorized_next_measurement=False, v46_adoption_evidence=False, **values)

    try:
        return _clone_capability(admit, result)(record)
    except (ValueError, KeyError, TypeError, ArithmeticError) as error:
        return result('rejected_structure', [str(error)], record)
