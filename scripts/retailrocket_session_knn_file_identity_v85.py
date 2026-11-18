"""FileIdInfo evidence from a supplied borrow-and-query backend.

This interface neither opens files nor loads native APIs. The caller owns a
stable, already open stream and supplies admission and generation evidence.
The same-open checks reject observable changes, and cannot prove continuity
across a hidden replacement or make a caller's attestation trustworthy.
"""

from dataclasses import dataclass


FILE_ID_INFO_CLASS = 0x12
FILE_ID_INFO_SIZE = 24
_MAX_U64 = (1 << 64) - 1
_MAX_WINERROR = (1 << 32) - 1
_RESERVED_IDS = (b'\x00' * 16, b'\xff' * 16)


@dataclass(frozen=True)
class OpenBinding:
    host_id: str
    boot_id: str
    run_id: str
    request_sha256: str
    capture_id: str
    provider_id: str
    filesystem: str
    generation_id: str
    generation_proof_id: str | None
    relative_path: str
    role: str
    pid: int
    creation_id: str
    open_id: str
    local_regular_default_stream_verified: bool = False
    canonical_path_verified: bool = False
    generation_continuity_verified: bool = False
    offset: int = 0
    length: int = 1


@dataclass(frozen=True)
class FileIdReply:
    """A backend-normalized BOOL, Windows buffer bytes and same-call error."""

    success: bool
    payload: bytes | None = None
    winerror: int | None = None


@dataclass(frozen=True)
class FileIdentityKey:
    volume_serial: int
    file_id: bytes

    def to_record(self):
        if not _valid_key(self):
            raise ValueError('Invalid FileIdInfo identity key')
        return dict(volume_serial_hex=f'{self.volume_serial:016x}', file_id_hex=self.file_id.hex())


@dataclass(frozen=True)
class FileIdentityEvidence:
    status: str
    reason: str
    binding: OpenBinding | None
    key: FileIdentityKey | None = None
    winerror: int | None = None


def _text(value):
    return type(value) is str and bool(value.strip())


def _relative_path(value):
    return (_text(value) and not any(char in value for char in ('\\', ':', '\x00'))
            and all(segment not in ('', '.', '..') for segment in value.split('/')))


def _valid_binding(binding):
    if type(binding) is not OpenBinding:
        return False
    return (all(_text(value) for value in (
                binding.host_id, binding.boot_id, binding.run_id, binding.capture_id, binding.provider_id,
                binding.filesystem, binding.generation_id, binding.creation_id, binding.open_id))
            and _text(binding.request_sha256) and len(binding.request_sha256) == 64
            and all(char in '0123456789abcdef' for char in binding.request_sha256)
            and _relative_path(binding.relative_path)
            and type(binding.role) is str and binding.role in ('outer', 'pipeline', 'publisher', 'worker')
            and type(binding.pid) is int and binding.pid > 0
            and type(binding.offset) is int and binding.offset == 0
            and type(binding.length) is int and binding.length == 1
            and all(type(value) is bool for value in (
                binding.local_regular_default_stream_verified, binding.canonical_path_verified,
                binding.generation_continuity_verified))
            and (binding.generation_proof_id is None or _text(binding.generation_proof_id))
            and (not binding.generation_continuity_verified or _text(binding.generation_proof_id)))


def _admitted(binding):
    return binding.local_regular_default_stream_verified and binding.canonical_path_verified


def _valid_key(key):
    return (type(key) is FileIdentityKey and type(key.volume_serial) is int
            and 0 <= key.volume_serial <= _MAX_U64 and type(key.file_id) is bytes
            and len(key.file_id) == 16 and key.file_id not in _RESERVED_IDS)


def _winerror(value):
    return value if type(value) is int and 0 < value <= _MAX_WINERROR else None


def _unknown(binding, reason, winerror=None):
    return FileIdentityEvidence('unknown', reason, binding, winerror=_winerror(winerror))


def _handle_number(value, bits):
    mask = (1 << bits) - 1
    if type(value) is not int or not -(1 << (bits - 1)) <= value <= mask:
        return None
    # _get_osfhandle returns intptr_t. Preserve the full bit pattern when
    # the high bit makes a valid pointer-sized value appear negative.
    number = value & mask
    return None if number in (0, mask, mask - 1) else number


def _open_is_current(stream, fd, binding, backend):
    if stream.closed is not False:
        return False
    observed_fd = stream.fileno()
    if type(observed_fd) is not int or observed_fd != fd:
        return False
    observed_open = backend.current_open_id(stream)
    return type(observed_open) is str and observed_open == binding.open_id


def _interpret_reply(reply, binding):
    if type(reply) is not FileIdReply or type(reply.success) is not bool:
        return _unknown(binding, 'malformed_file_id_reply')
    if not reply.success:
        code = _winerror(reply.winerror)
        reason = 'file_id_query_failed' if code is not None else 'file_id_query_failed_without_winerror'
        return _unknown(binding, reason, code)
    payload = reply.payload
    if reply.winerror is not None or type(payload) is not bytes or len(payload) != FILE_ID_INFO_SIZE:
        return _unknown(binding, 'malformed_file_id_reply')
    key = FileIdentityKey(int.from_bytes(payload[:8], 'little'), payload[8:])
    if not _valid_key(key):
        return _unknown(binding, 'unusable_file_id')
    return FileIdentityEvidence('captured', 'observed', binding, key)


def capture_file_identity(stream, *, fd, binding, backend):
    """Read from the same CRT descriptor used for locking, through a fake port.

    The backend supplies ``pointer_bits``, ``current_open_id(stream)``,
    ``get_osfhandle(fd)`` and ``get_file_information_by_handle_ex``. The owner
    must keep the stream stable throughout. The handle is borrowed twice for
    bracketing, never closed here, and never stored as the file identity.
    """
    if not _valid_binding(binding):
        return _unknown(None, 'invalid_binding')
    if not _admitted(binding):
        return _unknown(binding, 'unqualified_path_or_provider')
    bits = getattr(backend, 'pointer_bits', None)
    if type(fd) is not int or fd < 0 or type(bits) is not int or bits not in (32, 64):
        return _unknown(binding, 'invalid_fd_or_pointer_width')

    stage = 'open_binding_not_current'
    query_failure = None
    try:
        if not _open_is_current(stream, fd, binding, backend):
            return _unknown(binding, stage)
        stage = 'invalid_borrowed_handle'
        before = _handle_number(backend.get_osfhandle(fd), bits)
        if before is None:
            return _unknown(binding, stage)
        stage = 'file_id_query_raised'
        reply = backend.get_file_information_by_handle_ex(before, FILE_ID_INFO_CLASS, FILE_ID_INFO_SIZE)
        result = _interpret_reply(reply, binding)
        query_failure = result.winerror
        stage = 'open_or_handle_changed'
        if not _open_is_current(stream, fd, binding, backend):
            return _unknown(binding, stage, query_failure)
        after = _handle_number(backend.get_osfhandle(fd), bits)
        if after != before:
            return _unknown(binding, stage, query_failure)
    except (OSError, AttributeError, ValueError, TypeError) as error:
        winerror = getattr(error, 'winerror', None) if stage == 'file_id_query_raised' else query_failure
        return _unknown(binding, stage, winerror)

    return result


def _captured(evidence):
    return (type(evidence) is FileIdentityEvidence and evidence.status == 'captured'
            and _valid_key(evidence.key) and _valid_binding(evidence.binding)
            and _admitted(evidence.binding))


def _scope(binding):
    return (binding.host_id, binding.boot_id, binding.run_id, binding.request_sha256, binding.capture_id,
            binding.provider_id, binding.filesystem, binding.offset, binding.length)


def compare_file_identity(left, right):
    """Compare two admitted observations without inferring generation from ID."""
    if not _captured(left) or not _captured(right):
        return dict(status='unknown', reason='missing_or_invalid_capture')
    a, b = left.binding, right.binding
    if _scope(a) != _scope(b):
        return dict(status='unknown', reason='incomparable_scope')
    if (not a.generation_continuity_verified or not b.generation_continuity_verified
            or a.generation_proof_id != b.generation_proof_id):
        return dict(status='unknown', reason='unproved_generation')
    if left.key != right.key:
        return dict(status='different_file', reason='different_keys')
    if a.generation_id != b.generation_id or a.relative_path != b.relative_path:
        return dict(status='unknown', reason='unproved_generation')
    return dict(status='same_file_generation', reason='matched_generation')
