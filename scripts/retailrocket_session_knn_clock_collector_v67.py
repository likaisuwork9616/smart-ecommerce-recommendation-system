"""One injected V62 B collection; no live clock, sleep or filesystem defaults.

The canonical record ends before pure evaluation. Only ``final`` covers the
whole deadline, including evaluation and the required immutable raw write.
The persisted snapshot is provisional; it cannot itself attest a B pass.
"""
from copy import deepcopy
from fractions import Fraction
import re

from scripts.retailrocket_session_knn_wall_cpu_v63 import BoundaryError, BoundaryRecorder


REAL_ORIGIN = 'real_clock_capability_v67'
FAKE_ORIGIN = 'fake_clock_capability_v67'
DEADLINE_NS = 30_000_000_000
ROUND_NS = 500_000_000
SAMPLE_CAP = 1_000_000
SLEEP_NS = 50_000_000


class _Problem(ValueError):
    def __init__(self, reason, status='rejected_structure'):
        super().__init__(reason)
        self.status = status


class _Halt(Exception):
    pass


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _metadata(value, source_sha256):
    if type(value) is not dict or set(value) != {'environment', 'clocks'}:
        raise _Problem('metadata_missing', 'clock_capability_unconfirmed')
    environment, clocks = value['environment'], value['clocks']
    if type(environment) is not dict or set(environment) != {
            'python', 'os', 'process_id', 'thread_id', 'source_sha256'}:
        raise _Problem('environment_structure')
    for key in ('python', 'os'):
        if type(environment[key]) is not str or not environment[key]:
            raise _Problem('environment_' + key)
    for key in ('process_id', 'thread_id'):
        if type(environment[key]) is not int or environment[key] < 0:
            raise _Problem('environment_' + key)
    if environment['source_sha256'] != source_sha256:
        raise _Problem('source_sha256_mismatch')
    if type(clocks) is not dict or set(clocks) != {'wall', 'cpu'}:
        raise _Problem('clock_metadata_missing', 'clock_capability_unconfirmed')
    resolutions = {}
    for name, api in (('wall', 'time.perf_counter_ns'), ('cpu', 'time.thread_time_ns')):
        row = clocks[name]
        if type(row) is not dict or set(row) != {
                'api', 'available', 'implementation', 'monotonic', 'adjustable', 'resolution_seconds'}:
            raise _Problem('clock_metadata_missing_' + name, 'clock_capability_unconfirmed')
        if row['api'] != api:
            raise _Problem('clock_api_' + name)
        for key in ('available', 'monotonic', 'adjustable'):
            if type(row[key]) is not bool:
                raise _Problem('clock_boolean_' + name + '_' + key)
        if not row['available'] or not row['monotonic'] or row['adjustable']:
            raise _Problem('clock_unusable_' + name, 'clock_capability_unconfirmed')
        if type(row['implementation']) is not str or not row['implementation']:
            raise _Problem('clock_implementation_' + name, 'clock_capability_unconfirmed')
        if type(row['resolution_seconds']) is not str or not row['resolution_seconds']:
            raise _Problem('clock_resolution_missing_' + name, 'clock_capability_unconfirmed')
        try:
            resolution = Fraction(row['resolution_seconds']) * 1_000_000_000
        except (ValueError, ZeroDivisionError):
            raise _Problem('clock_resolution_invalid_' + name) from None
        if resolution <= 0:
            raise _Problem('clock_resolution_nonpositive_' + name)
        resolutions[name] = -(-resolution.numerator // resolution.denominator)
    return resolutions


def collect_capability(*, origin, source_sha256, metadata, wall_clock, cpu_clock,
                       thread_identity, sleep, cancelled, persist, evaluate,
                       sample_cap=SAMPLE_CAP):
    """Collect once using only injected dependencies.

    ``sample_cap`` is a reduced-cap seam for fake cases only. Real collection
    always has the fixed one-million cap, including the initial stamp.
    ``persist`` receives a detached provisional snapshot and returns
    ``{path, bytes, sha256}`` after the required raw bytes have been flushed.
    Exceptions become retained evidence; the first error remains primary.
    """
    if origin not in (REAL_ORIGIN, FAKE_ORIGIN) or not _sha(source_sha256):
        raise ValueError('Explicit V67 provenance and a lowercase SHA256 are required')
    if type(sample_cap) is not int or not 1 <= sample_cap <= SAMPLE_CAP:
        raise ValueError('sample_cap must be a positive integer at most the fixed cap')
    if origin == REAL_ORIGIN and sample_cap != SAMPLE_CAP:
        raise ValueError('Reduced sample_cap is fake-only')
    if not all(callable(x) for x in (metadata, wall_clock, cpu_clock, thread_identity,
                                      sleep, cancelled, persist, evaluate)):
        raise ValueError('Every dependency must be explicitly injected')

    record = dict(origin=origin, completed=False, started_wall_ns=None,
        ended_wall_ns=None, elapsed_wall_ns=None, environment=None, clocks=None,
        rounds=[None] * 3, sleeps=[None] * 10)
    collection = dict(metadata_raw=None, control_reads=[], stop_reasons=[], errors=[],
        partial_captures=[], sample_cap=sample_cap, fake_only_reduced_cap=sample_cap != SAMPLE_CAP,
        captured_stamps=0, requested_sleeps=0, canonical_end_scope='before_pure_evaluation',
        raw_snapshot_provisional=True, primary_error=None)
    state = dict(stopped=False, status=None, last_wall=None, last_control=None,
                 collection_finished=False)
    recorder = BoundaryRecorder(recording_id='v67-b', wall_clock=wall_clock,
        cpu_clock=cpu_clock, thread_identity=thread_identity)

    def stop(reason, status='clock_capability_unconfirmed', *, phase=None, error=None):
        state['stopped'] = True
        if state['status'] is None:
            state['status'] = status
        entry = dict(reason=reason, status=status, phase=phase)
        if entry not in collection['stop_reasons']:
            collection['stop_reasons'].append(entry)
        if error is not None:
            item = dict(phase=phase, type=type(error).__name__, message=str(error))
            collection['errors'].append(item)
            if collection['primary_error'] is None:
                collection['primary_error'] = item.copy()

    def error_stop(error, phase):
        status = error.status if isinstance(error, _Problem) else (
            'rejected_structure' if isinstance(error, BoundaryError) else 'clock_capability_unconfirmed')
        stop(str(error) if isinstance(error, _Problem) else 'dependency_error',
             status, phase=phase, error=error)

    def observe(value, phase):
        if type(value) is not int or value < 0:
            raise _Problem('invalid_wall_value')
        if state['last_wall'] is not None and value < state['last_wall']:
            raise _Problem('wall_moved_backwards')
        state['last_wall'] = value
        if record['started_wall_ns'] is not None and value - record['started_wall_ns'] > DEADLINE_NS:
            stop('deadline_exceeded', phase=phase)

    def control(phase):
        row = dict(phase=phase, wall_ns=None, error_type=None)
        state['last_control'] = None
        try:
            row['wall_ns'] = wall_clock()
            observe(row['wall_ns'], phase)
            state['last_control'] = row['wall_ns']
        except BaseException as error:
            row['error_type'] = type(error).__name__
            error_stop(error, phase)
        collection['control_reads'].append(row)
        return state['last_control']

    def checkpoint(phase):
        # After stopping, do not invoke cancellation hooks or calibration readers.
        if not state['stopped']:
            try:
                cancel = cancelled()
                if type(cancel) is not bool:
                    raise _Problem('cancel_callback_must_return_bool')
                if cancel:
                    stop('cancelled', phase=phase)
            except BaseException as error:
                error_stop(error, phase + ':cancel')
        control(phase)
        if state['stopped']:
            raise _Halt()

    def final_checkpoint(phase):
        try:
            checkpoint(phase)
        except _Halt:
            pass
        return state['last_control']

    def capture(name):
        checkpoint(name + ':before')
        try:
            boundary = recorder.capture(name)
        except BaseException:
            for failure in recorder.failures:
                collection['partial_captures'].append(dict(boundary_id=failure.boundary_id,
                    error_type=failure.error_type, raw_values=list(failure.raw_values)))
            raise
        stamp = dict(wall_before_ns=boundary.wall_before_ns, thread_cpu_ns=boundary.thread_cpu_ns,
                     wall_after_ns=boundary.wall_after_ns, thread_id=boundary.thread_id)
        collection['captured_stamps'] += 1
        # Return even invalid evidence to the current slot before stopping.
        try:
            if boundary.thread_id != record['environment']['thread_id']:
                raise _Problem('metadata_thread_mismatch')
            if boundary.thread_cpu_ns < 0:
                raise _Problem('negative_thread_cpu')
            observe(boundary.wall_before_ns, name)
            observe(boundary.wall_after_ns, name)
            if boundary.wall_after_ns - boundary.wall_before_ns > 100_000:
                stop('bracket_max_exceeded', phase=name)
        except BaseException as error:
            error_stop(error, name)
        return stamp

    phase = 'start'
    try:
        start = control('before_metadata')
        if state['stopped']:
            raise _Halt()
        record['started_wall_ns'] = start
        phase = 'metadata'
        try:
            raw_metadata = metadata()
            collection['metadata_raw'] = raw_metadata
            if type(raw_metadata) is dict:
                record['environment'] = raw_metadata.get('environment')
                record['clocks'] = raw_metadata.get('clocks')
        except BaseException as error:
            error_stop(error, phase)
        checkpoint('after_metadata')
        resolutions = _metadata(raw_metadata, source_sha256)
        checkpoint('after_metadata_validation')
        if resolutions['cpu'] > 100_000:
            stop('declared_cpu_resolution_exceeded', 'cpu_resolution_insufficient', phase=phase)
            raise _Halt()
        for index in range(3):
            phase = f'round:{index + 1}'
            row = dict(round=index + 1, completed=False, stop_reason='error', stamps=[])
            record['rounds'][index] = row
            positives = []
            while True:
                stamp = capture(f'{phase}:stamp:{len(row["stamps"])}')
                row['stamps'].append(stamp)
                if state['stopped']:
                    row['stop_reason'] = 'deadline' if any(
                        x['reason'] == 'deadline_exceeded' for x in collection['stop_reasons']) else 'error'
                    raise _Halt()
                if len(row['stamps']) > 1:
                    delta = stamp['thread_cpu_ns'] - row['stamps'][-2]['thread_cpu_ns']
                    if delta > 0:
                        positives.append(delta)
                elapsed = stamp['wall_before_ns'] - row['stamps'][0]['wall_before_ns']
                if elapsed >= ROUND_NS:
                    row.update(completed=True, stop_reason='wall_target')
                    if len(positives) < 10:
                        stop('too_few_positive_cpu_increments', phase=phase)
                    elif sorted(positives)[(len(positives) * 95 + 99) // 100 - 1] > 100_000:
                        stop('round_cpu_resolution_exceeded', 'cpu_resolution_insufficient', phase=phase)
                    checkpoint(phase + ':after_statistics')
                    break
                if len(row['stamps']) >= sample_cap:
                    row['stop_reason'] = 'sample_cap'
                    stop('sample_cap_before_wall_target', phase=phase)
                    raise _Halt()
        for index in range(10):
            phase = f'sleep:{index + 1}'
            row = dict(trial=index + 1, completed=False, requested_ns=SLEEP_NS, start=None, end=None)
            record['sleeps'][index] = row
            row['start'] = capture(phase + ':start')
            if state['stopped']:
                raise _Halt()
            checkpoint(phase + ':before_sleep')
            collection['requested_sleeps'] += 1
            try:
                sleep(0.05)
            except BaseException as error:
                error_stop(error, phase + ':body')
            checkpoint(phase + ':after_sleep')
            row['end'] = capture(phase + ':end')
            if state['stopped']:
                raise _Halt()
            row['completed'] = True
            if row['end']['wall_before_ns'] - row['start']['wall_before_ns'] < 40_000_000:
                stop('sleep_wall_too_short', phase=phase)
                raise _Halt()
        state['collection_finished'] = True
    except _Halt:
        pass
    except BaseException as error:
        error_stop(error, phase)

    final_checkpoint('before_evaluation')
    record['completed'] = state['collection_finished'] and not state['stopped']
    record['ended_wall_ns'] = state['last_control']
    if record['started_wall_ns'] is not None and record['ended_wall_ns'] is not None:
        record['elapsed_wall_ns'] = record['ended_wall_ns'] - record['started_wall_ns']
    decision = None
    try:
        decision = evaluate(record)
        allowed = {'clock_capability_passed', 'cpu_resolution_insufficient',
                   'clock_capability_unconfirmed', 'rejected_structure'}
        if type(decision) is not dict or decision.get('status') not in allowed:
            raise _Problem('invalid_evaluator_result')
    except BaseException as error:
        error_stop(error, 'evaluate')
    final_checkpoint('after_evaluation')

    persistence = None
    try:
        snapshot = deepcopy(dict(record=record, decision=decision, collection=collection,
                                 final=None, snapshot_status='provisional_before_raw_persistence'))
        final_checkpoint('before_raw_persistence')
        # Capture that last pre-write check, too; later final checks live in the receipt.
        snapshot['collection'] = deepcopy(collection)
        persistence = persist(snapshot)
        if type(persistence) is not dict or set(persistence) != {'path', 'bytes', 'sha256'} or (
                type(persistence['path']) is not str or not persistence['path'] or
                type(persistence['bytes']) is not int or persistence['bytes'] <= 0 or
                not _sha(persistence['sha256'])):
            raise _Problem('raw_persistence_incomplete', 'clock_capability_unconfirmed')
    except BaseException as error:
        error_stop(error, 'persist')
        persistence = None
    # The last read belongs to the 30-second gate. No calibration action follows.
    end = final_checkpoint('after_raw_persistence')
    elapsed = None if end is None or record['started_wall_ns'] is None else end - record['started_wall_ns']
    within = persistence is not None and elapsed is not None and 0 <= elapsed <= DEADLINE_NS
    status = state['status'] or (decision['status'] if decision is not None else 'clock_capability_unconfirmed')
    if any(item['status'] == 'rejected_structure' for item in collection['stop_reasons']):
        status = 'rejected_structure'
    if not within:
        status = status if status == 'rejected_structure' else 'clock_capability_unconfirmed'
    passed = status == 'clock_capability_passed' and within and not state['stopped']
    return dict(record=record, decision=decision, collection=collection, persistence=persistence,
        final=dict(status=status, completed=passed, ended_wall_ns=end, elapsed_wall_ns=elapsed,
                   raw_persisted_within_deadline=within, deadline_ns=DEADLINE_NS,
                   live_B_passed=passed and origin == REAL_ORIGIN,
                   authorized_next_gate=False))
