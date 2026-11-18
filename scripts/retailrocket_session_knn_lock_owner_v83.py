"""Classify one rejected lock attempt using supplied synthetic evidence.

Bounds are already-expanded integer nanosecond sample bounds in the supplied
clock domain. The caller supplies the coverage and common-clock attestations.
This module does not acquire a lock, read a clock, or establish OS capability.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Bounds:
    lower_ns: int
    upper_ns: int


@dataclass(frozen=True)
class Actor:
    role: str
    pid: int
    creation_id: str
    boot_id: str
    kind: str = 'role'


@dataclass(frozen=True)
class Scope:
    request_sha256: str
    run_id: str
    file_id: str
    generation: str
    clock_domain: str
    boot_id: str
    offset: int = 0
    length: int = 1


@dataclass(frozen=True)
class Attempt:
    actor: Actor
    scope: Scope
    check_id: str
    attempt_index: int
    begin: Bounds | None
    end: Bounds | None
    rejected: bool = True
    # This is an independent classification supplied by the fake backend.
    conflict: str = 'unknown'


@dataclass(frozen=True)
class Hold:
    actor: Actor
    scope: Scope
    hold_id: str
    acquired: Bounds | None
    release_begin: Bounds | None = None
    last_proven_held: Bounds | None = None
    continuous: bool = False


def _text(value):
    return type(value) is str and bool(value.strip())


def _valid_actor(actor, scope):
    return (type(actor) is Actor
            and type(actor.kind) is str and actor.kind == 'role'
            and type(actor.role) is str
            and actor.role in ('outer', 'pipeline', 'publisher', 'worker')
            and type(actor.pid) is int and actor.pid > 0
            and _text(actor.creation_id)
            and _text(actor.boot_id) and actor.boot_id == scope.boot_id)


def _valid_scope(scope):
    return (type(scope) is Scope
            and _text(scope.request_sha256) and len(scope.request_sha256) == 64
            and all(char in '0123456789abcdef' for char in scope.request_sha256)
            and all(_text(value) for value in (scope.run_id, scope.file_id,
                                              scope.generation, scope.clock_domain, scope.boot_id))
            and type(scope.offset) is int and scope.offset == 0
            and type(scope.length) is int and scope.length == 1)


def _valid_bounds(bounds):
    return (type(bounds) is Bounds and type(bounds.lower_ns) is int
            and type(bounds.upper_ns) is int and bounds.lower_ns <= bounds.upper_ns)


def _result(status, reason, conflict='unknown', *, candidates=(), owner=None):
    return dict(status=status, reason=reason, conflict=conflict,
                candidate_hold_ids=sorted(candidates),
                owner=asdict(owner.actor) if owner is not None else None,
                hold_id=owner.hold_id if owner is not None else None)


def classify_owner(attempt, holds, *, coverage_complete, common_clock_verified):
    """Require strict containment of the entire amplified rejection interval.

    The hold starts at the latest possible successful acquisition sample. It
    ends at the earliest possible release begin, or a certified held witness
    when release is unobserved. Only intervals proved continuous are eligible.
    Candidates are from the supplied records and are not an exhaustive roster.
    """
    if (type(attempt) is not Attempt or attempt.rejected is not True
            or not _valid_scope(attempt.scope) or not _valid_actor(attempt.actor, attempt.scope)
            or not _text(attempt.check_id) or type(attempt.attempt_index) is not int
            or attempt.attempt_index < 0):
        return _result('unknown', 'invalid_or_unobserved_rejected_attempt')
    conflict = 'unknown'
    if type(attempt.conflict) is str and attempt.conflict in ('confirmed_conflict', 'confirmed_nonconflict'):
        conflict = attempt.conflict
    if coverage_complete is not True or common_clock_verified is not True:
        return _result('unknown', 'coverage_or_common_clock_not_verified', conflict)
    if not _valid_bounds(attempt.begin) or not _valid_bounds(attempt.end):
        return _result('unknown', 'missing_or_invalid_rejection_bounds', conflict)
    begin, end = attempt.begin.lower_ns, attempt.end.upper_ns
    if begin > end:
        return _result('inconsistent', 'rejection_sample_order_impossible', conflict)
    if type(holds) not in (list, tuple):
        return _result('unknown', 'missing_or_invalid_hold_records', conflict)

    seen = set()
    known = []
    unresolved = []
    for hold in holds:
        if (type(hold) is not Hold or not _valid_scope(hold.scope) or hold.scope != attempt.scope
                or not _valid_actor(hold.actor, hold.scope) or not _text(hold.hold_id)
                or hold.hold_id in seen):
            return _result('unknown', 'incompatible_or_duplicate_hold_record', conflict)
        seen.add(hold.hold_id)
        right_bound = hold.release_begin if hold.release_begin is not None else hold.last_proven_held
        if hold.continuous is not True or not _valid_bounds(hold.acquired) or not _valid_bounds(right_bound):
            unresolved.append(hold.hold_id)
            continue
        if right_bound.upper_ns < hold.acquired.lower_ns:
            return _result('inconsistent', 'hold_sample_order_impossible', conflict)
        left, right = hold.acquired.upper_ns, right_bound.lower_ns
        if left >= right:
            unresolved.append(hold.hold_id)
        else:
            known.append((left, right, hold))

    known.sort(key=lambda item: (item[0], item[1], item[2].hold_id))
    for (_, right, earlier), (left, _, later) in zip(known, known[1:]):
        if left < right:
            return _result('inconsistent', 'overlapping_guaranteed_exclusive_holds', conflict,
                           candidates=(earlier.hold_id, later.hold_id))
    overlapping = [hold.hold_id for left, right, hold in known if left <= end and begin <= right]
    if unresolved:
        return _result('unknown', 'incomplete_or_collapsed_hold_bounds', conflict,
                       candidates=overlapping + unresolved)
    for left, right, hold in known:
        if left < begin and end < right:
            return _result('confirmed_holder_during_attempt', 'strict_containment', conflict,
                           candidates=(hold.hold_id,), owner=hold)
    return _result('unknown', 'no_strictly_containing_hold', conflict, candidates=overlapping)
