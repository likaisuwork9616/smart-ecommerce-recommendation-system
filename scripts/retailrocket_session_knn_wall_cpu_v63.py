"""Injected boundary clocks only; no default clock, runner, SQL or filesystem IO.

These records describe logical boundaries, not atomic clock readings or wait time.
All diagnostic arithmetic uses the original integers. A real entry adapter and
V62 B/C/D are deliberately outside this module.
"""
from dataclasses import dataclass


class BoundaryError(ValueError):
    """The recording cannot be accepted as a complete boundary observation."""


def _integer(value, name, *, nonnegative=False):
    if type(value) is not int or (nonnegative and value < 0):
        raise BoundaryError(f'{name} must be an integer')


def _name(value, name):
    if type(value) is not str or not value or value != value.strip():
        raise BoundaryError(f'{name} must be a nonempty identifier')


@dataclass(frozen=True)
class Boundary:
    recording_id: str
    boundary_id: str
    sequence: int
    thread_id: int
    wall_before_ns: int
    thread_cpu_ns: int
    wall_after_ns: int


@dataclass(frozen=True)
class Span:
    id: str
    phase: str
    parent: str | None
    start: str
    end: str


@dataclass(frozen=True)
class CaptureFailure:
    boundary_id: str
    error_type: str
    # A clock that raised has no value. Never invent its missing endpoint.
    raw_values: tuple


@dataclass(frozen=True)
class CallRecord:
    id: str
    phase: str
    parent: str | None
    start: str | None
    end: str | None
    completed: bool
    body_error_type: str | None = None
    timer_error_type: str | None = None

    def as_span(self):
        if (type(self.completed) is not bool or not self.completed
                or self.start is None or self.end is None
                or self.body_error_type is not None or self.timer_error_type is not None):
            raise BoundaryError('An incomplete call is not a completed span')
        return Span(self.id, self.phase, self.parent, self.start, self.end)


def validate_boundary(value):
    if type(value) is not Boundary:
        raise BoundaryError('An immutable Boundary is required')
    _name(value.recording_id, 'recording_id')
    _name(value.boundary_id, 'boundary_id')
    _integer(value.sequence, 'sequence', nonnegative=True)
    _integer(value.thread_id, 'thread_id', nonnegative=True)
    for field in ('wall_before_ns', 'thread_cpu_ns', 'wall_after_ns'):
        _integer(getattr(value, field), field)
    if value.wall_after_ns < value.wall_before_ns:
        raise BoundaryError('The wall bracket moved backwards')


def _ordered(a, b):
    validate_boundary(a)
    validate_boundary(b)
    if a.recording_id != b.recording_id or a.thread_id != b.thread_id:
        raise BoundaryError('Boundary endpoints must share a recording and thread')
    if a.sequence >= b.sequence or a.boundary_id == b.boundary_id:
        raise BoundaryError('Distinct endpoints must follow recorded sequence')
    if b.wall_before_ns < a.wall_after_ns or b.thread_cpu_ns < a.thread_cpu_ns:
        raise BoundaryError('Wall brackets overlap or the CPU clock moved backwards')


def span_values(start, end):
    """V62's signed integer formulas; brackets are not CPU error bounds."""
    _ordered(start, end)
    wall = end.wall_before_ns - start.wall_before_ns
    cpu = end.thread_cpu_ns - start.thread_cpu_ns
    inner = end.wall_before_ns - start.wall_after_ns
    outer = end.wall_after_ns - start.wall_before_ns
    return dict(wall_ns=wall, thread_cpu_ns=cpu, wall_minus_thread_cpu_ns=wall-cpu,
        start_bracket_ns=start.wall_after_ns-start.wall_before_ns,
        end_bracket_ns=end.wall_after_ns-end.wall_before_ns,
        wall_inner_ns=inner, wall_outer_ns=outer,
        residual_inner_ns=inner-cpu, residual_outer_ns=outer-cpu)


class BoundaryRecorder:
    """Fail closed after an invalid capture or failed body; readers are required."""
    def __init__(self, *, recording_id, wall_clock, cpu_clock, thread_identity):
        _name(recording_id, 'recording_id')
        if not all(callable(value) for value in (wall_clock, cpu_clock, thread_identity)):
            raise BoundaryError('All three readers must be explicitly injected')
        self.recording_id = recording_id
        self._wall, self._cpu, self._thread = wall_clock, cpu_clock, thread_identity
        self._boundaries, self._failures, self._calls = [], [], []
        self._ids, self._call_ids = set(), set()
        self._failed = False

    @property
    def boundaries(self):
        return tuple(self._boundaries)

    @property
    def failures(self):
        return tuple(self._failures)

    @property
    def calls(self):
        return tuple(self._calls)

    @property
    def failed(self):
        return self._failed

    def capture(self, boundary_id):
        if self._failed:
            raise BoundaryError('A failed recording cannot continue')
        before = cpu = after = None
        try:
            _name(boundary_id, 'boundary_id')
            if boundary_id in self._ids:
                raise BoundaryError('Duplicate boundary identifier')
            thread_before = self._thread()
            # No validation, allocation or buffer write between these three reads.
            before = self._wall()
            cpu = self._cpu()
            after = self._wall()
            thread_after = self._thread()
            _integer(thread_before, 'thread_before', nonnegative=True)
            _integer(thread_after, 'thread_after', nonnegative=True)
            if thread_before != thread_after:
                raise BoundaryError('Thread changed during the boundary capture')
            boundary = Boundary(self.recording_id, boundary_id, len(self._boundaries),
                                thread_before, before, cpu, after)
            validate_boundary(boundary)
            if self._boundaries:
                _ordered(self._boundaries[-1], boundary)
            self._boundaries.append(boundary)
            self._ids.add(boundary_id)
            return boundary
        except BaseException as error:
            self._failed = True
            self._failures.append(CaptureFailure(boundary_id, type(error).__name__, (before, cpu, after)))
            raise

    def tap(self, boundary_id):
        """Legacy wall return only; diagnostics retain the unrounded Boundary."""
        return self.capture(boundary_id).wall_before_ns / 1_000_000_000

    def call(self, span_id, phase, body, *, parent=None):
        """Run one body; preserve its original exception if the end clock also fails."""
        _name(span_id, 'span_id')
        _name(phase, 'phase')
        if parent is not None:
            _name(parent, 'parent')
        if not callable(body) or span_id in self._call_ids:
            raise BoundaryError('A new call identifier and callable body are required')
        self._call_ids.add(span_id)
        start_id, end_id = span_id + ':start', span_id + ':end'
        try:
            self.capture(start_id)
        except BaseException as error:
            self._calls.append(CallRecord(span_id, phase, parent, None, None, False,
                                          timer_error_type=type(error).__name__))
            raise
        try:
            value = body()
        except BaseException as error:
            timer_error, captured_end = None, None
            try:
                self.capture(end_id)
                captured_end = end_id
            except BaseException as secondary:
                timer_error = type(secondary).__name__
            self._failed = True
            self._calls.append(CallRecord(span_id, phase, parent, start_id, captured_end,
                                          False, type(error).__name__, timer_error))
            raise
        try:
            self.capture(end_id)
        except BaseException as error:
            self._calls.append(CallRecord(span_id, phase, parent, start_id, None, False,
                                          timer_error_type=type(error).__name__))
            raise
        self._calls.append(CallRecord(span_id, phase, parent, start_id, end_id, True))
        return value


def invoke(mode, body, *, recorder=None, span_id=None, phase=None, parent=None):
    """O executes the body without constructing or reading a diagnostic recorder."""
    if mode == 'O':
        if recorder is not None:
            raise BoundaryError('O must not receive a diagnostic recorder')
        return body()
    if mode != 'D' or type(recorder) is not BoundaryRecorder:
        raise BoundaryError('D requires an explicitly configured BoundaryRecorder')
    return recorder.call(span_id, phase, body, parent=parent)


ADDITIVE = ('wall_ns', 'thread_cpu_ns', 'wall_minus_thread_cpu_ns')


def validate_registry(boundaries, *, allow_empty=False):
    if type(boundaries) not in (list, tuple) or (not allow_empty and not boundaries):
        raise BoundaryError('An explicit ordered boundary list or tuple is required')
    registry = {}
    previous = None
    for index, boundary in enumerate(boundaries):
        validate_boundary(boundary)
        if boundary.sequence != index or boundary.boundary_id in registry:
            raise BoundaryError('Registry sequence or identifier is duplicated/missing')
        if previous is not None:
            _ordered(previous, boundary)
        registry[boundary.boundary_id] = boundary
        previous = boundary
    return registry


def analyze_spans(boundaries, spans):
    """Validate one registry/tree and subtract only nonoverlapping direct children."""
    registry = validate_registry(boundaries)
    if type(spans) not in (list, tuple) or not spans:
        raise BoundaryError('An explicit nonempty span list or tuple is required')
    plan, values, children = {}, {}, {None: []}
    for span in spans:
        if type(span) is not Span:
            raise BoundaryError('An immutable completed Span plan is required')
        for field in ('id', 'phase', 'start', 'end'):
            _name(getattr(span, field), field)
        if span.parent is not None:
            _name(span.parent, 'parent')
        if span.id in plan or span.start not in registry or span.end not in registry:
            raise BoundaryError('Duplicate span or missing endpoint')
        plan[span.id] = span
        values[span.id] = span_values(registry[span.start], registry[span.end])
        children.setdefault(span.parent, []).append(span.id)
        children.setdefault(span.id, [])
    for span in plan.values():
        if span.parent is not None:
            if span.parent not in plan:
                raise BoundaryError('Missing parent span')
            parent = plan[span.parent]
            if not (registry[parent.start].sequence <= registry[span.start].sequence
                    < registry[span.end].sequence <= registry[parent.end].sequence):
                raise BoundaryError('Child endpoints leave their parent')
        ancestors, current = set(), span.id
        while current is not None:
            if current in ancestors:
                raise BoundaryError('Cyclic parent relationship')
            ancestors.add(current)
            current = plan[current].parent
            if current is not None and current not in plan:
                raise BoundaryError('Missing ancestor')
    for ids in children.values():
        ids.sort(key=lambda name: registry[plan[name].start].sequence)
        for left, right in zip(ids, ids[1:]):
            if registry[plan[left].end].sequence > registry[plan[right].start].sequence:
                raise BoundaryError('Sibling spans overlap; do not add nested levels')
    output = {}
    for span_id, span in plan.items():
        summed = {key: sum(values[child][key] for child in children[span_id]) for key in ADDITIVE}
        unassigned = {key: values[span_id][key] - summed[key] for key in ADDITIVE}
        if unassigned['wall_ns'] < 0 or unassigned['thread_cpu_ns'] < 0:
            raise BoundaryError('Direct children exceed parent duration')
        output[span_id] = dict(phase=span.phase, parent=span.parent, start=span.start, end=span.end,
            inclusive=values[span_id], direct_children=list(children[span_id]),
            children_sum=summed, unassigned=unassigned)
    return dict(spans=output, roots=list(children[None]),
                root_totals={key: sum(values[root][key] for root in children[None]) for key in ADDITIVE})


def analyze_fresh48(boundaries, markers, cohort, *, completed, fresh=True):
    """Bind the labelled layout to the exact registry order, including prefixes."""
    from scripts.retailrocket_session_knn_wall_cpu_layout_v63 import build_layout
    layout = build_layout(markers, cohort, completed=completed, fresh=fresh)
    registry = validate_registry(boundaries, allow_empty=not completed)
    if list(registry) != layout['observed_boundary_ids']:
        raise BoundaryError('Marker identifiers must match the exact clock registry order')
    analysis = (analyze_spans(boundaries, [Span(**row) for row in layout['spans']])
                if completed else None)
    return dict(layout=layout, analysis=analysis)
