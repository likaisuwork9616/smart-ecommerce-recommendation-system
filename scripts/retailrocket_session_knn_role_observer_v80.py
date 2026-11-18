"""Hold and observe the exact Windows role admitted by the V80 supervisor.

The caller owns the handshake and deadline. This module only supplies identity,
live ancestry and exit facts for that handshake. Nothing opens a handle on
import. The backend can be replaced by a fake within the sealed case suite.
"""

from dataclasses import dataclass
import math
import subprocess
import sys


ACCESS_MASK = 0x00101000  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
BACKEND = 'win32-held-role-v1'
FILETIME_UNIX_EPOCH = 116444736000000000
UINT64_MAX = (1 << 64) - 1
DWORD_MAX = (1 << 32) - 1
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = DWORD_MAX
STILL_ACTIVE = 259


class RoleObservationError(RuntimeError):
    def __init__(self, message, *, api=None, winerror=None, raw_exit_code=None):
        super().__init__(message)
        self.api = api
        self.winerror = winerror
        self.raw_exit_code = raw_exit_code


def _require_pid(pid):
    if type(pid) is not int or not 0 < pid <= DWORD_MAX:
        raise RoleObservationError('Exact positive Windows PID required')
    return pid


def _require_boot(boot):
    if type(boot) is not int or not 0 < boot < 1 << 63:
        raise RoleObservationError('Exact frozen NT boot identity required')
    return boot


def normalize_creation(ticks):
    if type(ticks) is not int or not FILETIME_UNIX_EPOCH <= ticks <= UINT64_MAX:
        raise RoleObservationError('Creation FILETIME outside the supported range')
    # Match psutil 7.2.2: subtract the integer offset before casting to double.
    return float(ticks - FILETIME_UNIX_EPOCH) / 10000000.0


def parse_raw_creation(value):
    if (type(value) is not str or not 1 <= len(value) <= 20
            or not value.isascii() or not value.isdecimal()
            or (len(value) > 1 and value.startswith('0'))):
        raise RoleObservationError('Canonical decimal creation FILETIME required')
    ticks = int(value)
    normalize_creation(ticks)
    return ticks


def require_identity(identity):
    if type(identity) is not dict or set(identity) != {'pid', 'create_time', 'boot_time'}:
        raise RoleObservationError('Frozen three-field Windows identity required')
    _require_pid(identity['pid'])
    _require_boot(identity['boot_time'])
    created = identity['create_time']
    if type(created) is not float or not math.isfinite(created) or created <= 0:
        raise RoleObservationError('Exact finite positive psutil create_time required')
    return dict(identity)


class WindowsNative:
    """Production backend restricted to the Windows runtime sealed by V79."""

    def __init__(self):
        if (sys.platform != 'win32' or sys.implementation.name != 'cpython'
                or sys.version_info[:3] != (3, 12, 10) or sys.byteorder != 'little'):
            raise RoleObservationError('V80 requires sealed Windows CPython 3.12.10')

        import ctypes
        from ctypes import wintypes

        import psutil

        if psutil.__version__ != '7.2.2' or not callable(getattr(psutil, '_ppid_map', None)):
            raise RoleObservationError('V80 requires sealed psutil 7.2.2 with Windows parent snapshot')

        self._ctypes = ctypes
        self._psutil = psutil
        self._filetime = wintypes.FILETIME
        self._dword = wintypes.DWORD
        try:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            handle = wintypes.HANDLE
            dword = wintypes.DWORD
            boolean = wintypes.BOOL
            filetime_ptr = ctypes.POINTER(wintypes.FILETIME)

            def bind(name, arguments, result):
                procedure = getattr(kernel, name)
                procedure.argtypes = arguments
                procedure.restype = result
                return procedure

            self._open = bind('OpenProcess', (dword, boolean, dword), handle)
            self._current = bind('GetCurrentProcess', (), handle)
            self._id = bind('GetProcessId', (handle,), dword)
            self._times = bind('GetProcessTimes', (handle,) + (filetime_ptr,) * 4, boolean)
            self._wait = bind('WaitForSingleObject', (handle, dword), dword)
            self._exit = bind('GetExitCodeProcess', (handle, ctypes.POINTER(dword)), boolean)
            self._close = bind('CloseHandle', (handle,), boolean)
        except (OSError, AttributeError) as error:
            raise RoleObservationError('Cannot bind Windows process observation API',
                                       api='Kernel32 binding',
                                       winerror=getattr(error, 'winerror', None)) from error

    def _error(self, api):
        # This is the ctypes thread-local copy set by use_last_error=True.
        code = self._ctypes.get_last_error()
        return RoleObservationError(f'{api} failed with Win32 error {code}',
                                    api=api, winerror=code)

    def borrow_launcher(self, popen):
        wrapped = getattr(popen, '_handle', None)
        if (type(popen) is not subprocess.Popen or type(wrapped) is not subprocess.Handle
                or getattr(wrapped, 'closed', None) is not False or int(wrapped) <= 0):
            raise RoleObservationError('Original live Popen Handle required', api='Popen._handle')
        return int(wrapped)

    def current_handle(self):
        value = self._current()
        if not value:
            raise self._error('GetCurrentProcess')
        return value

    def open_process(self, pid, *, access, inherit):
        if type(access) is not int or access != ACCESS_MASK or inherit is not False:
            raise RoleObservationError('Unexpected role observer access request', api='OpenProcess')
        self._ctypes.set_last_error(0)
        value = self._open(access, inherit, _require_pid(pid))
        if not value:
            raise self._error('OpenProcess')
        return value

    def process_id(self, handle):
        self._ctypes.set_last_error(0)
        value = self._id(handle)
        if not value:
            raise self._error('GetProcessId')
        return value

    def creation_ticks(self, handle):
        creation, exited, kernel, user = (self._filetime() for _ in range(4))
        byref = self._ctypes.byref
        self._ctypes.set_last_error(0)
        if not self._times(handle, byref(creation), byref(exited), byref(kernel), byref(user)):
            raise self._error('GetProcessTimes')
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime

    def signal_state(self, handle):
        self._ctypes.set_last_error(0)
        code = self._wait(handle, 0)
        if code == WAIT_FAILED:
            raise self._error('WaitForSingleObject')
        if code == WAIT_OBJECT_0:
            return True
        if code == WAIT_TIMEOUT:
            return False
        raise RoleObservationError(f'Unexpected process wait status {code}', api='WaitForSingleObject')

    def exit_code(self, handle):
        code = self._dword()
        self._ctypes.set_last_error(0)
        if not self._exit(handle, self._ctypes.byref(code)):
            raise self._error('GetExitCodeProcess')
        return code.value

    def close_handle(self, handle):
        self._ctypes.set_last_error(0)
        if not self._close(handle):
            raise self._error('CloseHandle')

    def parent_snapshot(self):
        # On the pinned Windows psutil this invokes the Toolhelp snapshot for
        # each call. In particular it cannot reuse Process.ppid()'s cached value.
        try:
            return self._psutil._ppid_map()
        except (self._psutil.Error, OSError) as error:
            raise RoleObservationError('Cannot establish a fresh parent snapshot',
                                       api='psutil._ppid_map',
                                       winerror=getattr(error, 'winerror', None)) from error

    def create_time(self, pid):
        try:
            return self._psutil.Process(pid).create_time()
        except (self._psutil.Error, OSError) as error:
            raise RoleObservationError('Cannot confirm legacy process creation time',
                                       api='psutil.Process.create_time',
                                       winerror=getattr(error, 'winerror', None)) from error


@dataclass(frozen=True)
class _ProcessFacts:
    pid: int
    ticks: int
    boot: int

    @property
    def identity(self):
        return {'pid': self.pid, 'create_time': normalize_creation(self.ticks), 'boot_time': self.boot}

    def evidence(self):
        return {'identity': self.identity, 'raw_creation': str(self.ticks)}


def _facts(backend, handle, expected_pid, boot):
    pid = _require_pid(backend.process_id(handle))
    if pid != expected_pid:
        raise RoleObservationError('Process handle PID differs from expected identity', api='GetProcessId')
    ticks = backend.creation_ticks(handle)
    if normalize_creation(ticks) <= 0:
        raise RoleObservationError('Process creation must be after the Unix epoch', api='GetProcessTimes')
    return _ProcessFacts(pid, ticks, boot)


def _require_legacy_time(backend, facts):
    create_time = backend.create_time(facts.pid)
    if type(create_time) is not float or create_time != normalize_creation(facts.ticks):
        raise RoleObservationError('Raw FILETIME and legacy psutil create_time differ',
                                   api='psutil.Process.create_time')


def self_ready(identity, *, backend=None):
    """Resolve the role's own creation tick value using its process pseudo handle."""
    identity = require_identity(identity)
    backend = WindowsNative() if backend is None else backend
    handle = backend.current_handle()
    if type(handle) is not int or handle == 0:
        raise RoleObservationError('Missing current-process pseudo handle', api='GetCurrentProcess')
    facts = _facts(backend, handle, identity['pid'], identity['boot_time'])
    if facts.identity != identity:
        raise RoleObservationError('Self native and legacy process identity differ')
    return str(facts.ticks)


def _parent_chain(snapshot, role_pid, launcher_pid):
    if type(snapshot) is not dict:
        raise RoleObservationError('Missing Windows parent snapshot', api='psutil._ppid_map')
    chain = []
    seen = {role_pid}
    child = role_pid
    while child != launcher_pid:
        parent = snapshot.get(child)
        if type(parent) is not int or not 0 < parent <= DWORD_MAX or parent in seen:
            raise RoleObservationError('Parent chain does not reach the original launcher',
                                       api='psutil._ppid_map')
        chain.append([child, parent])
        seen.add(parent)
        child = parent
    return chain


class HeldRole:
    """Single-owner observation of one ready/ack role through its exit.

    The caller must close the object even when admission raises. It supplies the
    deadline check so the role and all ancestors share the work child's budget.
    """

    def __init__(self, popen, *, boot_identity, backend=None, track=None):
        self._backend = WindowsNative() if backend is None else backend
        self._popen = popen  # Keep the original Popen owner alive.
        self._read_boot = boot_identity
        self._boot = _require_boot(boot_identity())
        self._track = track
        self._owned = []
        self._nodes = []
        self._role_handle = None
        self._admit_started = False
        self._ready = False
        self._acknowledged = False
        self._closed = False
        self._exit_rejected = False
        self._observed_exit = None
        self._launcher_handle = self._backend.borrow_launcher(popen)
        if type(self._launcher_handle) is not int or self._launcher_handle <= 0:
            raise RoleObservationError('Missing borrowed launcher handle', api='Popen._handle')
        self._launcher = _facts(self._backend, self._launcher_handle, _require_pid(popen.pid), self._boot)
        if track is not None:
            track(self._launcher.identity)
        self._require_live(self._launcher_handle)
        _require_legacy_time(self._backend, self._launcher)

    @property
    def launcher_identity(self):
        return self._launcher.identity

    def _is_signaled(self, handle):
        result = self._backend.signal_state(handle)
        if type(result) is not bool:
            raise RoleObservationError('Process signal state must be boolean', api='WaitForSingleObject')
        return result

    def _require_live(self, handle):
        if self._is_signaled(handle):
            raise RoleObservationError('Process signaled before role acknowledgment', api='WaitForSingleObject')

    def _open_owned(self, pid):
        handle = self._backend.open_process(pid, access=ACCESS_MASK, inherit=False)
        if (type(handle) is not int or handle <= 0 or handle == self._launcher_handle
                or handle in self._owned):
            raise RoleObservationError('Invalid or aliased owned process handle', api='OpenProcess')
        self._owned.append(handle)
        return handle

    def _check_boot(self):
        if _require_boot(self._read_boot()) != self._boot:
            raise RoleObservationError('Boot identity changed during role observation')

    def admit(self, role_identity, raw_creation, *, check=None):
        if self._closed or self._admit_started:
            raise RoleObservationError('Role admission is single use')
        self._admit_started = True
        if check is not None:
            check()
        identity = require_identity(role_identity)
        announced = _ProcessFacts(identity['pid'], parse_raw_creation(raw_creation), self._boot)
        if announced.identity != identity:
            raise RoleObservationError('Ready raw, legacy or boot identity differs')

        role_pid = identity['pid']
        launcher_pid = self._launcher.pid
        needs_chain = role_pid != launcher_pid
        before = _parent_chain(self._backend.parent_snapshot(), role_pid, launcher_pid) if needs_chain else []
        pids = [role_pid, *(parent for _, parent in before)]
        nodes = []
        for position, pid in enumerate(pids):
            if check is not None:
                check()
            if position and pid == launcher_pid:
                handle = self._launcher_handle
            else:
                handle = self._open_owned(pid)
            facts = _facts(self._backend, handle, pid, self._boot)
            self._require_live(handle)
            _require_legacy_time(self._backend, facts)
            if position == 0 and facts != announced:
                raise RoleObservationError('Held role creation FILETIME differs from ready')
            if nodes and facts.ticks > nodes[-1][1].ticks:
                raise RoleObservationError('Parent process creation follows child creation')
            nodes.append((handle, facts))

        if nodes[-1][1] != self._launcher:
            raise RoleObservationError('Role chain does not bind the original launcher object')
        if check is not None:
            check()
        after = _parent_chain(self._backend.parent_snapshot(), role_pid, launcher_pid) if needs_chain else []
        if before != after:
            raise RoleObservationError('Fresh parent chain changed during role admission')

        self._nodes = nodes
        self._role_handle = nodes[0][0]
        self._recheck_handles(check)
        if self._track is not None:
            # Do not add unanchored parent IDs to the caller's cleanup set.
            for _, facts in nodes:
                if facts.pid != launcher_pid:
                    self._track(facts.identity)
        return {
            'launcher_identity': self.launcher_identity,
            'role_identity': announced.identity,
            'launcher_raw_creation': str(self._launcher.ticks),
            'raw_creation': raw_creation,
            'ancestry': {
                'nodes': [facts.evidence() for _, facts in nodes],
                'fresh_chain_before': before,
                'fresh_chain_after': after,
            },
            'backend': BACKEND,
            'access_mask': ACCESS_MASK,
            'pre_ack_nonsignaled': True,
        }

    def _recheck_handles(self, check):
        self._check_boot()
        if self._backend.borrow_launcher(self._popen) != self._launcher_handle:
            raise RoleObservationError('Original Popen handle changed', api='Popen._handle')
        if (_facts(self._backend, self._launcher_handle, self._launcher.pid, self._boot)
                != self._launcher):
            raise RoleObservationError('Original launcher identity changed')
        for handle, facts in self._nodes:
            if check is not None:
                check()
            if _facts(self._backend, handle, facts.pid, self._boot) != facts:
                raise RoleObservationError('Held role ancestry identity changed')
            self._require_live(handle)
        self._require_live(self._launcher_handle)

    def recheck_pre_ack(self, *, check=None):
        if self._closed or self._role_handle is None or self._acknowledged:
            raise RoleObservationError('A bound unacknowledged role is required for pre-ack check')
        self._ready = False
        self._recheck_handles(check)
        self._ready = True

    def mark_acknowledged(self):
        if self._closed or not self._ready or self._acknowledged:
            raise RoleObservationError('A successful live pre-ack check is required')
        self._acknowledged = True

    def poll_exit(self):
        if self._closed or not self._acknowledged or self._exit_rejected:
            raise RoleObservationError('A live acknowledged observation is required for role exit')
        if self._observed_exit is not None:
            return self._observed_exit
        try:
            if not self._is_signaled(self._role_handle):
                return None
            code = self._backend.exit_code(self._role_handle)
            if type(code) is not int or not 0 <= code <= DWORD_MAX:
                raise RoleObservationError('Expected an exact DWORD exit code', api='GetExitCodeProcess')
            if code == STILL_ACTIVE:
                raise RoleObservationError('Signaled role supplied the reserved exit code 259',
                                           api='GetExitCodeProcess', raw_exit_code=code)
        except BaseException:
            self._exit_rejected = True
            raise
        self._observed_exit = code
        return code

    def close(self):
        """Close all handles opened by this observer once, even on refusal."""
        if self._closed:
            return
        self._closed = True
        first_error = None
        while self._owned:
            handle = self._owned.pop()
            try:
                self._backend.close_handle(handle)
            except BaseException as error:
                if first_error is None:
                    first_error = error
                else:
                    first_error.add_note(f'Additional CloseHandle failure: {error}')
        if first_error is not None:
            raise first_error
