"""V85 QPC/QPF evidence interface for injected backends.

No Windows API, clock, or process is accessed by this module itself. A
qualification is supplied by the caller. Matching labels and frequency do
not establish the qualification or an uncertainty bound.
"""

from dataclasses import dataclass
from typing import Protocol


QPC_SOURCE = 'win32-qpc-qpf-v85'
_MAX_SIGNED64 = (1 << 63) - 1
_MAX_DWORD = (1 << 32) - 1
_NS_PER_SECOND = 1_000_000_000


class QpcEvidenceError(ValueError):
    def __init__(self, message, *, operation=None, winerror=None):
        self.operation = operation
        self.winerror = winerror
        super().__init__(message)


@dataclass(frozen=True)
class ClockDomain:
    """Caller-provided receipt labels matched by a separate qualification."""

    host_id: str
    boot_id: str
    capture_id: str
    platform_id: str
    runtime_id: str
    adapter_id: str
    source: str = QPC_SOURCE


@dataclass(frozen=True)
class QpcApiResult:
    succeeded: bool
    value: int | None
    winerror: int | None = None


class QpcBackend(Protocol):
    def query_performance_frequency(self) -> QpcApiResult: ...

    def query_performance_counter(self) -> QpcApiResult: ...


@dataclass(frozen=True)
class QpcSample:
    domain: ClockDomain
    process_key: str
    ticks: int
    frequency_hz: int


@dataclass(frozen=True)
class ClockQualification:
    domain: ClockDomain
    frequency_hz: int
    origin_ticks: int
    process_keys: frozenset[str]
    verified: bool


def _named(value):
    return type(value) is str and bool(value.strip())


def _raw_integer(value, minimum, maximum=_MAX_SIGNED64):
    return type(value) is int and minimum <= value <= maximum


def _valid_domain(domain):
    return (type(domain) is ClockDomain and type(domain.source) is str
            and domain.source == QPC_SOURCE and _named(domain.host_id)
            and _named(domain.boot_id) and _named(domain.capture_id)
            and _named(domain.platform_id) and _named(domain.runtime_id)
            and _named(domain.adapter_id))


def _valid_sample(sample):
    return (type(sample) is QpcSample and _valid_domain(sample.domain)
            and _named(sample.process_key) and _raw_integer(sample.ticks, 0)
            and _raw_integer(sample.frequency_hz, 1))


def _read_integer(result, operation, minimum):
    if type(result) is not QpcApiResult or type(result.succeeded) is not bool:
        raise QpcEvidenceError('Malformed QPC/QPF result', operation=operation)
    if not result.succeeded:
        if result.winerror is not None and not _raw_integer(result.winerror, 0, _MAX_DWORD):
            raise QpcEvidenceError('Malformed Win32 error code', operation=operation)
        # A failed read cannot contribute the output buffer to evidence.
        raise QpcEvidenceError(operation + ' failed', operation=operation, winerror=result.winerror or None)
    if result.winerror is not None or not _raw_integer(result.value, minimum):
        raise QpcEvidenceError('Invalid QPC/QPF success value', operation=operation)
    return result.value


def read_qpc_sample(backend: QpcBackend, *, domain, process_key, previous=None):
    """Read one raw QPF/QPC pair using an explicitly supplied backend.

    A supplied previous sample must describe the same process and domain.
    Its frequency must be unchanged and its tick may not exceed the new one.
    """
    if not _valid_domain(domain) or not _named(process_key):
        raise QpcEvidenceError('Valid source, domain and process labels required')
    if previous is not None and (not _valid_sample(previous) or previous.domain != domain
                                 or previous.process_key != process_key):
        raise QpcEvidenceError('Previous sample belongs to another process or domain')

    frequency = _read_integer(backend.query_performance_frequency(), 'QueryPerformanceFrequency', 1)
    if previous is not None and frequency != previous.frequency_hz:
        raise QpcEvidenceError('QPF changed within a process and domain', operation='QueryPerformanceFrequency')
    ticks = _read_integer(backend.query_performance_counter(), 'QueryPerformanceCounter', 0)
    if previous is not None and ticks < previous.ticks:
        raise QpcEvidenceError('QPC moved backwards within a process and domain', operation='QueryPerformanceCounter')
    return QpcSample(domain=domain, process_key=process_key, ticks=ticks, frequency_hz=frequency)


def sample_bounds_ns(sample, qualification, *, before_ticks, after_ticks):
    """Return integer nanosecond bounds against the same qualified origin.

    ``before_ticks`` and ``after_ticks`` are explicit extra error bounds
    rounded up to ticks by the caller. Each side also allows one native tick
    for cross-thread ordering uncertainty. A caller can pass the resulting
    pair to V83 Bounds. This conversion does not qualify a real clock.
    """
    if not _valid_sample(sample):
        raise QpcEvidenceError('Valid raw QPC sample required')
    if (type(qualification) is not ClockQualification or qualification.verified is not True
            or not _valid_domain(qualification.domain) or qualification.domain != sample.domain
            or not _raw_integer(qualification.frequency_hz, 1)
            or qualification.frequency_hz != sample.frequency_hz
            or not _raw_integer(qualification.origin_ticks, 0)
            or type(qualification.process_keys) is not frozenset
            or not all(_named(key) for key in qualification.process_keys)
            or sample.process_key not in qualification.process_keys):
        raise QpcEvidenceError('No matching common clock qualification')
    if not _raw_integer(before_ticks, 0) or not _raw_integer(after_ticks, 0):
        raise QpcEvidenceError('Explicit nonnegative integer error bounds required')

    relative = sample.ticks - qualification.origin_ticks
    low_numerator = (relative - before_ticks - 1) * _NS_PER_SECOND
    high_numerator = (relative + after_ticks + 1) * _NS_PER_SECOND
    return low_numerator // sample.frequency_hz, -(-high_numerator // sample.frequency_hz)
