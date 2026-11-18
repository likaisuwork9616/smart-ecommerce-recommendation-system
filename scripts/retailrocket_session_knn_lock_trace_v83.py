"""Model V82 evidence on injected fake clocks, locks and write steps only.

No default clock, file IO, or native backend is provided. This model starts
after the fake guard is open and initialized, at the V80 retry-loop boundary.
"""

from copy import deepcopy


RETRY_LIMIT_SECONDS = 1.0
RETRY_SLEEP_SECONDS = 0.005


class LockBusy(RuntimeError):
    """Fake backend equivalent of the frozen guard's WriterBusy wrapper."""


class LockStopped(RuntimeError):
    """Preserve the original decision operands without flattening the reason."""

    def __init__(self, decision):
        self.decision = dict(decision)
        super().__init__(decision['reason'])


class EventBuffer:
    """Bounded fake evidence buffer with an explicit dropped-event count."""

    def __init__(self, capacity=256):
        if type(capacity) is not int or capacity < 1:
            raise ValueError('Event capacity must be a positive integer')
        self._capacity = capacity
        self._events = []
        self._seen = 0

    def _record(self, clock, event, check_id, **fields):
        self._seen += 1
        if len(self._events) >= self._capacity:
            return
        try:
            tick_ns = clock.observe_ns()
        except Exception:
            return
        if type(tick_ns) is not int or tick_ns < 0:
            return
        self._events.append(dict(event=event, seq=self._seen, tick_ns=tick_ns,
                                 check_id=check_id, **fields))

    def snapshot(self):
        dropped = self._seen - len(self._events)
        return dict(events=deepcopy(self._events), complete=dropped == 0,
                    seen_events=self._seen, dropped_events=dropped)


def _error_fields(error):
    cause = error.__cause__ if error.__cause__ is not None else error
    return dict(wrapper_type=type(error).__name__, cause_type=type(cause).__name__,
                errno=getattr(cause, 'errno', None), winerror=getattr(cause, 'winerror', None))


def _retry_decision(clock, loop_start_mono, request_deadline_utc):
    decision_mono = clock.monotonic()
    elapsed_seconds = decision_mono - loop_start_mono
    utc_sample = utc_predicate = requested_sleep_seconds = None
    utc_evaluated = False
    if elapsed_seconds >= RETRY_LIMIT_SECONDS:
        reason = 'lock_retry_monotonic_limit'
    else:
        utc_evaluated = True
        utc_sample = clock.utc()
        utc_predicate = utc_sample >= request_deadline_utc
        if utc_predicate:
            reason = 'lock_retry_request_utc_deadline'
        else:
            reason = 'retry'
            requested_sleep_seconds = RETRY_SLEEP_SECONDS
    return dict(reason=reason, loop_start_mono=loop_start_mono, decision_mono=decision_mono,
                elapsed_seconds=elapsed_seconds, request_deadline_utc=request_deadline_utc,
                utc_evaluated=utc_evaluated, utc_sample=utc_sample, utc_predicate=utc_predicate,
                requested_sleep_seconds=requested_sleep_seconds)


def _fake_operation(emit, event, action, **fields):
    emit(event + '_begin', **fields)
    try:
        action()
    except BaseException as error:
        emit(event + '_end', result='failed', error=_error_fields(error), **fields)
        raise
    emit(event + '_end', result='succeeded', **fields)


def run_fake_check(*, clock, backend, trace, check_id, request_deadline_utc, steps=()):
    """Run one fake retry loop, optional fake critical section, and release.

    The separate fake observation clock does not supply the guard's predicate
    operands. ``steps`` supplies named fake operations while the lock is held.
    """
    def emit(event, **fields):
        trace._record(clock, event, check_id, **fields)

    loop_start_mono = clock.monotonic()
    emit('lock_loop_begin', loop_start_mono=loop_start_mono,
         request_deadline_utc=request_deadline_utc, retry_limit_seconds=RETRY_LIMIT_SECONDS)
    attempt_index = 0
    while True:
        attempt_index += 1
        emit('lock_attempt_begin', attempt_index=attempt_index)
        try:
            backend.acquire()
        except LockBusy as error:
            emit('lock_attempt_end', attempt_index=attempt_index, result='rejected',
                 error=_error_fields(error))
            decision = _retry_decision(clock, loop_start_mono, request_deadline_utc)
            emit('retry_decision', attempt_index=attempt_index, decision=decision)
            if decision['reason'] != 'retry':
                raise LockStopped(decision) from error
            _fake_operation(emit, 'retry_sleep', lambda: clock.sleep(RETRY_SLEEP_SECONDS),
                            attempt_index=attempt_index, requested_seconds=RETRY_SLEEP_SECONDS)
        except BaseException as error:
            emit('lock_attempt_end', attempt_index=attempt_index, result='failed',
                 error=_error_fields(error))
            raise
        else:
            break

    hold_id = f'{check_id}:{attempt_index}'
    try:
        emit('lock_attempt_end', attempt_index=attempt_index, result='acquired', hold_id=hold_id)
        for operation, action in steps:
            _fake_operation(emit, 'state_write', action, hold_id=hold_id, operation=operation)
    finally:
        _fake_operation(emit, 'unlock', backend.release, hold_id=hold_id)
