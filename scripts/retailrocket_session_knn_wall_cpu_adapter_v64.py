"""Invocation-local V27/V39 boundary integration; no clock defaults or runner CLI.

The original pair, SQL, SetupClock and entry code objects remain unchanged.
Injected readers and an explicit fresh48 cohort are required; this module never
starts telemetry, calibrates a clock or selects a dataset.
"""
import hashlib

from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_sql_v4 as sql
from scripts import retailrocket_session_knn_reuse_v27 as reuse
from scripts import retailrocket_session_knn_typed_adapter_v39 as typed
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.retailrocket_session_knn_wall_cpu_v63 import (
    BoundaryError, BoundaryRecorder, analyze_fresh48)
from scripts.retailrocket_session_knn_wall_cpu_layout_v63 import (
    SETUP_POINTS, TAIL_POINTS, QUERY_EXECUTION_POINTS, RANK_PHASES, build_layout)


def bind_predictor(predictor, clock):
    if predictor.__code__ is not sql.predict.__code__ or not callable(clock):
        raise BoundaryError('Original V4 predictor code and an explicit clock required')
    return _clone(predictor, perf_counter=clock)


class BoundarySession:
    def __init__(self, mode, cohort, *, recorder=None, legacy_clock=None):
        checked = build_layout([], cohort, completed=False)['cohort']
        if mode == 'D':
            if (type(recorder) is not BoundaryRecorder or recorder.failed or recorder.boundaries
                    or legacy_clock is not None):
                raise BoundaryError('D requires a fresh explicit recorder only')
        elif mode == 'O':
            if recorder is not None or not callable(legacy_clock):
                raise BoundaryError('O requires a legacy clock and no diagnostic recorder')
        else:
            raise BoundaryError('Only original O or diagnostic D is supported')
        self.mode, self.cohort = mode, checked
        self.recorder, self.legacy_clock = recorder, legacy_clock
        self._markers = [] if mode == 'D' else None
        self._expected = [] if mode == 'D' else None
        if mode == 'D':
            for point in SETUP_POINTS:
                self._expected.append(dict(point=point, subset_ordinal=None, original_ordinal=None, key_sha256=None))
            for ordinal, identity in enumerate(checked):
                for point in QUERY_EXECUTION_POINTS:
                    self._expected.append(dict(point=point, subset_ordinal=ordinal, **identity))
            for point in TAIL_POINTS:
                self._expected.append(dict(point=point, subset_ordinal=None, original_ordinal=None, key_sha256=None))
        self.started = False
        self.report = None
        self.error_type = None
        self.secondary_error_type = None

    def begin(self, config, ordinals):
        if self.started:
            raise BoundaryError('Each session belongs to exactly one fresh entry')
        count = config['fixed_validation']['queries']
        if type(count) is not int or len(ordinals) != 48 or count != 48:
            raise BoundaryError('Only the explicit fresh48 entry shape is supported')
        actual = [dict(original_ordinal=row['original_ordinal'],
            key_sha256=hashlib.sha256(pair.dump(row['key']).encode()).hexdigest()) for row in ordinals]
        build_layout([], actual, completed=False)
        if actual != self.cohort:
            raise BoundaryError('Entry identities differ from the explicit cohort')
        self.started = True

    def _tick(self, origin):
        if not self.started or self.report is not None or self.error_type is not None:
            raise BoundaryError('A boundary requires one active entry')
        if self.mode == 'O':
            return self.legacy_clock()
        index = len(self._markers)
        if index >= len(self._expected):
            raise BoundaryError('Extra clock outside the fixed fresh48 layout')
        target = self._expected[index]
        expected_origin = 'rank' if target['point'] in ('ranking_start', *RANK_PHASES) else 'pair'
        if origin != expected_origin:
            raise BoundaryError('Pair/ranking clock order differs from the frozen code')
        marker = dict(boundary_id=f'b{index}', **target)
        value = self.recorder.tap(marker['boundary_id'])
        self._markers.append(marker)
        return value

    def pair_tick(self):
        return self._tick('pair')

    def rank_tick(self):
        return self._tick('rank')

    def finish(self, *, completed, result=None, error=None):
        if type(completed) is not bool or not self.started or self.report is not None:
            raise BoundaryError('One explicit completion state is required')
        if error is not None:
            self.error_type = type(error).__name__
        if completed:
            if (error is not None or result is None
                    or type(result['committed_prefix_rows']) is not int
                    or result['committed_prefix_rows'] != 0):
                raise BoundaryError('Successful diagnostic entries must be fresh')
            identities = [dict(original_ordinal=row['original_ordinal'], key_sha256=row['key_sha256'])
                          for row in result['queries']]
            build_layout([], identities, completed=False)
            if (identities != self.cohort
                    or type(result['verified_subset_queries']) is not int
                    or result['verified_subset_queries'] != 48
                    or any(type(row['subset_ordinal']) is not int or row['subset_ordinal'] != ordinal
                           for ordinal, row in enumerate(result['queries']))):
                raise BoundaryError('Completed output identities differ from the cohort')
        if self.mode == 'O':
            self.report = dict(mode='O', completed=completed, diagnostics=None, error_type=self.error_type)
        else:
            diagnostic = analyze_fresh48(self.recorder.boundaries, self._markers, self.cohort, completed=completed)
            self.report = dict(mode='D', completed=completed, diagnostics=diagnostic, error_type=self.error_type)
        return self.report


def make_verifier(observer, pool, namespace, request, *, session,
                  pair_function=pair.verify_selected, predictor=sql.predict):
    """Bind actual V27 make_verifier code; no extra store.recover or SQL proxy."""
    if pair_function.__code__ is not pair.verify_selected.__code__:
        raise BoundaryError('The original V4 verifier code object is required')
    bound_predictor = bind_predictor(predictor, session.rank_tick)
    sql_view = observed._ModuleView(pair.sql, predict=bound_predictor)
    pair_view = observed._ModuleView(pair, sql=sql_view)

    class SetupClock(observed._SetupClock):
        __call__ = _clone(observed._SetupClock.__call__, perf_counter=session.pair_tick)

    observation_view = observed._ModuleView(observed, _SetupClock=SetupClock)
    factory = _clone(reuse.make_verifier, observed=observation_view, pair=pair_view,
                     ORIGINALS=(pair_function, *reuse.ORIGINALS[1:]))
    original = factory(observer, pool, namespace, request)

    def verify(primary, paths, config, store, model, database, ordinals,
               watch=lambda: None, fault=lambda point: None):
        session.begin(config, ordinals)
        try:
            result = original(primary, paths, config, store, model, database, ordinals, watch, fault)
        except BaseException as error:
            try:
                session.finish(completed=False, error=error)
            except BaseException as secondary:
                session.secondary_error_type = type(secondary).__name__
            raise
        try:
            session.finish(completed=True, result=result)
        except BaseException as error:
            pool.invalidate()
            try:
                session.finish(completed=False, error=error)
            except BaseException as secondary:
                session.secondary_error_type = type(secondary).__name__
            raise
        return result
    return verify


def bind_entry(*, session, pair_function=pair.verify_selected, predictor=sql.predict,
               entry_function=None, store_factory=None):
    """Pierce V39's c1.run_fixed48 binding with invocation-local module views.

    Optional test seams must retain original entry bytecode. Neither this
    function nor its caller creates or replaces the caller-supplied worker pool.
    """
    entry_function = reuse.entry._run if entry_function is None else entry_function
    if entry_function.__code__ is not reuse.entry._run.__code__:
        raise BoundaryError('The original V22 entry code object is required')
    def factory(observer, pool, namespace, request):
        return make_verifier(observer, pool, namespace, request, session=session,
                             pair_function=pair_function, predictor=predictor)
    entry_view = observed._ModuleView(reuse.entry, _run=entry_function)
    runner = _clone(reuse.run_fixed48, make_verifier=factory, entry=entry_view,
                    StoreFactory=reuse.StoreFactory if store_factory is None else store_factory)
    typed_runner = _clone(typed.run_fixed48, c1=observed._ModuleView(reuse, run_fixed48=runner))
    def run(folder, request, label, mode, data, **kwargs):
        if mode != 'C':
            raise BoundaryError('V39 and V46 workers both use the original C1 worker route')
        return typed_runner(folder, request, label, mode, data, **kwargs)
    return run
