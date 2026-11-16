"""V62 A16 decisions over supplied synthetic records; never collect or run work.

These functions validate arithmetic and refusal states. A passing fixture is
not a B/C/D measurement, an authorization to measure, or V46 adoption evidence.
All thresholds use integer durations and exact Fraction arithmetic.
"""
from copy import deepcopy
from fractions import Fraction

from scripts.retailrocket_session_knn_wall_cpu_summary_v63 import (
    SCHEDULE as C_SCHEDULE, distribution, nearest_rank, summarize_overhead)


GLOBAL_METRICS = ('instrumentation_entry_ns', 'original_entry_ns', 'query_sum_ns')
LOCAL_PHASES = ('sql_positive_overlaps', 'sql_selected_votes_and_accumulation')
DECODERS = ('V39', 'V46')
WARM_ORDER = (('V39', 'O'), ('V46', 'D'), ('V46', 'O'), ('V39', 'D'))
D_SCHEDULE = tuple((f'warm_{decoder}_{mode}', decoder, mode, 0)
                   for decoder, mode in WARM_ORDER) + tuple(
    (f'block_{block}_{decoder}_{mode}', decoder, mode, block)
    for block in range(1, 7)
    for decoder in (DECODERS if block % 2 else DECODERS[::-1])
    for mode in ('OD' if block % 2 else 'DO'))
SOURCE_METRIC = 'accounting.costs.entry_seconds from entry.json.seconds'
C_CONFIGURATION = dict(queries=48, query_points=7, ranking_points=8, setup_tail_points=5,
    lcg_seed=1, lcg_multiplier=1664525, lcg_increment=1013904223,
    lcg_modulus=4294967296, lcg_iterations=4096, sleep_requested_ns=1_000_000)


def _fields(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('Exact fields required: ' + ','.join(sorted(fields)))


def _int(value, name, *, nullable=False, minimum=0):
    if nullable and value is None:
        return
    if type(value) is not int or value < minimum:
        raise ValueError(name + ' requires an exact integer')


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError(name + ' requires an exact bool')


def _text(value, name):
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(name + ' requires a nonempty string')


def _sha(value):
    if (type(value) is not str or len(value) != 64
            or any(char not in '0123456789abcdef' for char in value)):
        raise ValueError('Lowercase SHA256 required')


def _list(value, count, name):
    if type(value) is not list or len(value) != count:
        raise ValueError(f'{name} requires exactly {count} ordered slots')


def _synthetic(record):
    if record['origin'] != 'synthetic_fixture' or type(record['origin']) is not str:
        raise ValueError('Only explicit synthetic fixture records are accepted')


def _exact(value):
    return dict(numerator=value.numerator, denominator=value.denominator)


def _result(status, reasons, raw, **values):
    return dict(status=status, failure_reasons=reasons, records=deepcopy(raw),
        evaluation='provided_synthetic_records_only', live_measurement_executed=False,
        authorized_next_measurement=False, v46_adoption_evidence=False, **values)


def _public(function, record):
    try:
        return function(record)
    except (ValueError, KeyError, TypeError, ArithmeticError) as error:
        return _result('rejected_structure', [str(error)], record)


def _stats(values):
    result = distribution(values)
    present = [value for value in values if value is not None]
    result.update(p50=None if not present else nearest_rank(present, Fraction(1, 2)),
                  p99=None if not present else nearest_rank(present, Fraction(99, 100)))
    return result


def _stamp(value, thread_id):
    _fields(value, ('wall_before_ns', 'thread_cpu_ns', 'wall_after_ns', 'thread_id'))
    for name in value:
        _int(value[name], name)
    if value['thread_id'] != thread_id or value['wall_after_ns'] < value['wall_before_ns']:
        raise ValueError('Wrong thread or backward wall bracket')
    return value


def _pair(start, end, thread_id):
    _stamp(start, thread_id); _stamp(end, thread_id)
    if (end['wall_before_ns'] < start['wall_after_ns']
            or end['thread_cpu_ns'] < start['thread_cpu_ns']):
        raise ValueError('Backward wall or thread CPU stamps')
    return (end['wall_before_ns']-start['wall_before_ns'],
            end['thread_cpu_ns']-start['thread_cpu_ns'])


def _capability(record):
    _fields(record, ('origin', 'completed', 'started_wall_ns', 'ended_wall_ns', 'elapsed_wall_ns',
                     'environment', 'clocks', 'rounds', 'sleeps'))
    _synthetic(record); _bool(record['completed'], 'completed')
    for field in ('started_wall_ns', 'ended_wall_ns', 'elapsed_wall_ns'):
        _int(record[field], field, nullable=True)
    if None not in (record['started_wall_ns'], record['ended_wall_ns'], record['elapsed_wall_ns']):
        if record['ended_wall_ns']-record['started_wall_ns'] != record['elapsed_wall_ns']:
            raise ValueError('Capability elapsed wall must use its outer endpoints')
    environment = record['environment']
    _fields(environment, ('python', 'os', 'process_id', 'thread_id', 'source_sha256'))
    for name in ('python', 'os'):
        _text(environment[name], name)
    for name in ('process_id', 'thread_id'):
        _int(environment[name], name)
    _sha(environment['source_sha256'])
    _fields(record['clocks'], ('wall', 'cpu'))
    reasons, declared = [], {}
    for name, clock in record['clocks'].items():
        _fields(clock, ('api', 'available', 'implementation', 'monotonic', 'adjustable', 'resolution_seconds'))
        if clock['api'] != ('time.perf_counter_ns' if name == 'wall' else 'time.thread_time_ns'):
            raise ValueError('The specified wall/thread CPU APIs cannot be substituted')
        for flag in ('available', 'monotonic', 'adjustable'):
            _bool(clock[flag], flag)
        _text(clock['implementation'], 'implementation')
        resolution = clock['resolution_seconds']
        if resolution is None:
            declared[name] = None
        else:
            _text(resolution, 'resolution_seconds')
            rational = Fraction(resolution)
            if rational <= 0:
                raise ValueError('Declared resolution must be positive')
            ns = rational*1_000_000_000
            declared[name] = (ns.numerator+ns.denominator-1)//ns.denominator
        if (not clock['available'] or not clock['monotonic'] or clock['adjustable']
                or declared[name] is None):
            reasons.append(name+'_clock_metadata_unconfirmed')
    if (not record['completed'] or any(record[name] is None for name in ('started_wall_ns', 'ended_wall_ns', 'elapsed_wall_ns'))
            or record['elapsed_wall_ns'] > 30_000_000_000):
        reasons.append('capability_incomplete_or_deadline')
    _list(record['rounds'], 3, 'rounds'); _list(record['sleeps'], 10, 'sleeps')
    rounds, brackets, cpu_p95, chronology = [], [], [], []
    for number, row in enumerate(record['rounds'], 1):
        if row is None:
            reasons.append(f'round_{number}_missing')
            rounds.append(None)
            continue
        _fields(row, ('round', 'completed', 'stop_reason', 'stamps'))
        _int(row['round'], 'round', minimum=1); _bool(row['completed'], 'completed')
        if row['round'] != number or row['stop_reason'] not in ('wall_target', 'sample_cap', 'deadline', 'error'):
            raise ValueError('Dense round order or stop reason differs')
        if type(row['stamps']) is not list:
            raise ValueError('Dense stamps must retain their ordered list')
        stamps = row['stamps']
        for stamp in stamps:
            _stamp(stamp, environment['thread_id'])
            brackets.append(stamp['wall_after_ns']-stamp['wall_before_ns'])
            chronology.append(stamp)
        deltas = [_pair(a, b, environment['thread_id']) for a, b in zip(stamps, stamps[1:])]
        wall = [pair[0] for pair in deltas]
        cpu = [pair[1] for pair in deltas]
        positive = [value for value in cpu if value > 0]
        elapsed = None if len(stamps) < 2 else stamps[-1]['wall_before_ns']-stamps[0]['wall_before_ns']
        if (not row['completed'] or row['stop_reason'] != 'wall_target'
                or elapsed is None or elapsed < 500_000_000 or len(stamps) > 1_000_000):
            reasons.append(f'round_{number}_incomplete_or_cap')
        if len(positive) < 10:
            reasons.append(f'round_{number}_insufficient_positive_cpu')
        p95 = None if not positive else nearest_rank(positive, Fraction(95, 100))
        if p95 is not None:
            cpu_p95.append(p95)
        rounds.append(dict(round=number, samples=len(stamps), elapsed_wall_ns=elapsed,
            wall_increments=_stats(wall), positive_cpu_increments=_stats(positive),
            brackets=_stats([stamp['wall_after_ns']-stamp['wall_before_ns'] for stamp in stamps]),
            cpu_increment_count=len(cpu), zero_cpu_increments=cpu.count(0),
            zero_cpu_ratio_exact=None if not cpu else _exact(Fraction(cpu.count(0), len(cpu)))))
    sleeps, ratios = [], []
    for trial, row in enumerate(record['sleeps'], 1):
        if row is None:
            reasons.append(f'sleep_{trial}_missing'); sleeps.append(None); continue
        _fields(row, ('trial', 'completed', 'requested_ns', 'start', 'end'))
        _int(row['trial'], 'trial', minimum=1); _bool(row['completed'], 'completed')
        _int(row['requested_ns'], 'requested_ns')
        if row['trial'] != trial or row['requested_ns'] != 50_000_000:
            raise ValueError('Fixed sleep identity/request required')
        if row['start'] is None or row['end'] is None:
            for endpoint in ('start', 'end'):
                if row[endpoint] is not None:
                    _stamp(row[endpoint], environment['thread_id'])
                    chronology.append(row[endpoint])
                    brackets.append(row[endpoint]['wall_after_ns']-row[endpoint]['wall_before_ns'])
            reasons.append(f'sleep_{trial}_missing_endpoint')
            sleeps.append(dict(trial=trial, wall_ns=None, cpu_ns=None, cpu_wall_ratio_exact=None))
            continue
        wall, cpu = _pair(row['start'], row['end'], environment['thread_id'])
        chronology.extend((row['start'], row['end']))
        brackets.extend(stamp['wall_after_ns']-stamp['wall_before_ns'] for stamp in (row['start'], row['end']))
        ratio = None if wall == 0 else Fraction(cpu, wall)
        if not row['completed'] or wall < 40_000_000 or ratio is None:
            reasons.append(f'sleep_{trial}_incomplete_or_short_wall')
        if ratio is not None:
            ratios.append(ratio)
        sleeps.append(dict(trial=trial, wall_ns=wall, cpu_ns=cpu,
                           cpu_wall_ratio_exact=None if ratio is None else _exact(ratio)))
    for start, end in zip(chronology, chronology[1:]):
        _pair(start, end, environment['thread_id'])
    if (chronology and record['elapsed_wall_ns'] is not None
            and chronology[-1]['wall_after_ns']-chronology[0]['wall_before_ns'] > record['elapsed_wall_ns']):
        raise ValueError('Capability outer elapsed wall cannot omit its supplied stamps')
    if chronology and ((record['started_wall_ns'] is not None and chronology[0]['wall_before_ns'] < record['started_wall_ns'])
            or (record['ended_wall_ns'] is not None and chronology[-1]['wall_after_ns'] > record['ended_wall_ns'])):
        raise ValueError('Capability raw stamps lie outside its outer endpoints')
    q_values = cpu_p95 + ([] if declared['cpu'] is None else [declared['cpu']])
    q = max(q_values) if q_values else None
    bracket_stats = _stats(brackets)
    ratio_p90 = None if not ratios else nearest_rank(ratios, Fraction(9, 10))
    if not brackets or bracket_stats['p99'] > 50_000 or bracket_stats['max'] > 100_000:
        reasons.append('bracket_window_unconfirmed')
    if len(ratios) != 10 or ratio_p90 is None or ratio_p90 > Fraction(1, 10):
        reasons.append('sleep_cpu_wall_ratio_unconfirmed')
    insufficient = q is not None and q > 100_000
    if insufficient:
        reasons.append('cpu_progress_screen_above_100000_ns')
    status = ('cpu_resolution_insufficient' if insufficient else
              'clock_capability_unconfirmed' if reasons else 'clock_capability_passed')
    return _result(status, reasons, record, declared_resolution_ceil_ns=declared, rounds=rounds,
        q_ns=q, brackets=bracket_stats, sleeps=sleeps,
        sleep_ratio_p90_exact=None if ratio_p90 is None else _exact(ratio_p90),
        q_is_observed_progress_screen_not_error_bound=True)


def evaluate_capability(record):
    return _public(_capability, record)


def _overhead(record):
    _fields(record, ('origin', 'capability', 'probes', 'workloads'))
    _synthetic(record)
    prerequisite = evaluate_capability(record['capability'])
    _fields(record['probes'], ('empty_stamp', 'full_recording'))
    reasons, probe_results = [], {}
    for name, rows in record['probes'].items():
        _list(rows, 4097, name)
        for row in rows:
            _fields(row, ('outer_wall_ns', 'completed', 'clock_reads', 'allocation_ns', 'append_ns', 'dispatch_ns'))
            _bool(row['completed'], 'completed')
            _fields(row['clock_reads'], ('wall', 'cpu'))
            for clock, value in row['clock_reads'].items():
                _int(value, 'clock_reads.'+clock)
            if row['clock_reads'] != dict(wall=2, cpu=1):
                reasons.append(name+'_clock_reads')
            for field in ('outer_wall_ns', 'allocation_ns', 'append_ns', 'dispatch_ns'):
                _int(row[field], field, nullable=True)
            if row['outer_wall_ns'] is not None and any(
                    row[field] is not None and row[field] > row['outer_wall_ns']
                    for field in ('allocation_ns', 'append_ns', 'dispatch_ns')):
                raise ValueError('Probe component cost cannot lie outside its outer wall')
            if not row['completed'] or any(row[field] is None for field in ('outer_wall_ns', 'allocation_ns', 'append_ns', 'dispatch_ns')):
                reasons.append(name+'_unavailable')
        probe_results[name] = {field: _stats([row[field] for row in rows])
            for field in ('outer_wall_ns', 'allocation_ns', 'append_ns', 'dispatch_ns')}
        probe_results[name]['actual_added_clock_reads'] = {
            clock: sum(row['clock_reads'][clock] for row in rows) for clock in ('wall', 'cpu')}
    _list(record['workloads'], 2, 'workloads')
    workloads, namespaces = {}, []
    for expected, workload in zip(('lcg', 'sleep'), record['workloads']):
        _fields(workload, ('name', 'elapsed_wall_ns', 'configuration', 'rows'))
        if workload['name'] != expected or type(workload['name']) is not str:
            raise ValueError('Both fixed workloads must keep their order')
        _int(workload['elapsed_wall_ns'], 'elapsed_wall_ns', nullable=True)
        _fields(workload['configuration'], C_CONFIGURATION)
        for name, value in workload['configuration'].items():
            _int(value, name)
        if workload['configuration'] != C_CONFIGURATION:
            raise ValueError('Frozen artificial workload configuration changed')
        _list(workload['rows'], 18, 'workload rows')
        projected, signatures = [], []
        for row in workload['rows']:
            _fields(row, ('label', 'mode', 'wall_ns', 'completed', 'namespace',
                          'outer_includes_output', 'trace_sha256', 'checksum_sha256'))
            _text(row['namespace'], 'namespace'); namespaces.append(row['namespace'])
            _bool(row['outer_includes_output'], 'outer_includes_output')
            for field in ('trace_sha256', 'checksum_sha256'):
                if row[field] is not None:
                    _sha(row[field])
            signatures.append((row['trace_sha256'], row['checksum_sha256']))
            if not row['outer_includes_output']:
                reasons.append(expected+'_outer_does_not_include_output')
            projected.append({field: row[field] for field in ('label', 'mode', 'wall_ns', 'completed')})
        summary = summarize_overhead(projected)
        available_wall = sum(row['wall_ns'] for row in projected if row['wall_ns'] is not None)
        if workload['elapsed_wall_ns'] is not None and workload['elapsed_wall_ns'] < available_wall:
            raise ValueError('Sequential workload elapsed wall cannot omit entry costs')
        if (workload['elapsed_wall_ns'] is None or workload['elapsed_wall_ns'] > 120_000_000_000
                or summary['status'] != 'perturbation_budget_passed'):
            reasons.append(expected+'_perturbation_or_deadline')
        if any(None in pair for pair in signatures) or len(set(signatures)) != 1:
            reasons.append(expected+'_trace_or_checksum_differs')
        workloads[expected] = summary
    if len(namespaces) != len(set(namespaces)):
        raise ValueError('Every synthetic workload entry needs a fresh namespace')
    if prerequisite['status'] != 'clock_capability_passed':
        reasons.append('prerequisite_B_not_passed')
    status = ('rejected_structure' if prerequisite['status'] == 'rejected_structure' else
              prerequisite['status'] if prerequisite['status'] != 'clock_capability_passed' else
              'perturbation_not_accepted' if reasons else 'artificial_perturbation_passed')
    return _result(status, sorted(set(reasons)), record, prerequisite=prerequisite,
        probes=probe_results, workloads=workloads, subtract_probe_cost=False)


def evaluate_artificial_overhead(record):
    return _public(_overhead, record)


def _cohort(value):
    _list(value, 48, 'cohort')
    ordinals, keys = [], []
    for ordinal, row in enumerate(value):
        _fields(row, ('subset_ordinal', 'original_ordinal', 'key_sha256'))
        _int(row['subset_ordinal'], 'subset_ordinal'); _int(row['original_ordinal'], 'original_ordinal')
        _sha(row['key_sha256'])
        if row['subset_ordinal'] != ordinal:
            raise ValueError('Fixed cohort subset order differs')
        ordinals.append(row['original_ordinal']); keys.append(row['key_sha256'])
    if len(set(ordinals)) != 48 or len(set(keys)) != 48:
        raise ValueError('Cohort identities must be unique')


def _metric_values(row):
    metrics = row['metrics']
    _fields(metrics, ('instrumentation_entry_ns', 'original_entry_ns', 'run_total_ns',
                     'entry_span_ns', 'query_wall_ns', *LOCAL_PHASES))
    for field in ('instrumentation_entry_ns', 'original_entry_ns', 'run_total_ns', 'entry_span_ns'):
        _int(metrics[field], field, nullable=True)
    for field in ('query_wall_ns', *LOCAL_PHASES):
        _list(metrics[field], 48, field)
        for value in metrics[field]:
            _int(value, field, nullable=True)
    query_sum = None if None in metrics['query_wall_ns'] else sum(metrics['query_wall_ns'])
    chain = (query_sum, metrics['original_entry_ns'], metrics['run_total_ns'], metrics['instrumentation_entry_ns'])
    if None not in chain and list(chain) != sorted(chain):
        raise ValueError('Query sum/original entry/run.total/instrumentation hierarchy differs')
    for ordinal in range(48):
        values = (metrics['query_wall_ns'][ordinal], *(metrics[phase][ordinal] for phase in LOCAL_PHASES))
        if None not in values and sum(values[1:]) > values[0]:
            raise ValueError('Nonoverlapping ranking phases cannot exceed query wall')
    result = dict(instrumentation_entry_ns=metrics['instrumentation_entry_ns'],
                  original_entry_ns=metrics['original_entry_ns'], query_sum_ns=query_sum)
    # Display positions 32/33 mean subset positions 31/32, not original IDs.
    for ordinal in (32, 33):
        for phase in LOCAL_PHASES:
            result[f'{ordinal}:{phase}'] = metrics[phase][ordinal-1]
    if not row['completed']:
        return {name: None for name in result}
    return result


def _paired(rows, metric, *, relative):
    pairs, absolute, signed = [], [], []
    for block in range(1, 7):
        group = {row['mode']: row for row in rows if row['block'] == block}
        original, diagnostic = (_metric_values(group[mode])[metric] for mode in ('O', 'D'))
        unavailable = (original is None or diagnostic is None or relative and original == 0)
        delta = None if unavailable else diagnostic-original
        value = None if unavailable else (Fraction(abs(delta), original) if relative else abs(delta))
        pairs.append(dict(block=block, order='OD' if block % 2 else 'DO',
            O=original, D=diagnostic, delta_D_minus_O_ns=delta,
            absolute_exact=None if value is None else _exact(Fraction(value))))
        absolute.append(value); signed.append(delta)
    values = [value for value in absolute if value is not None]
    stats = distribution(absolute)
    median = (None if not values else Fraction(stats['median_exact']['numerator'], stats['median_exact']['denominator']))
    median_limit, maximum_limit = ((Fraction(2, 100), Fraction(5, 100)) if relative else (100_000, 500_000))
    passed = len(values) == 6 and median <= median_limit and max(values) <= maximum_limit
    return dict(passed=passed, pairs=pairs, signed_delta_ns=distribution(signed),
        absolute=stats, valid_pairs=len(values), missing_pairs=6-len(values),
        median_limit_exact=_exact(Fraction(median_limit)), maximum_limit_exact=_exact(Fraction(maximum_limit)),
        by_order={order: dict(signed_delta_ns=distribution([signed[i] for i in range(6) if pairs[i]['order'] == order]),
            absolute=distribution([absolute[i] for i in range(6) if pairs[i]['order'] == order])) for order in ('OD', 'DO')})


def _window(record):
    _fields(record, ('origin', 'started_wall_ns', 'ended_wall_ns', 'elapsed_wall_ns',
                     'prerequisite_C', 'cohort', 'source_sha256', 'entries', 'calibrations'))
    _synthetic(record)
    for field in ('started_wall_ns', 'ended_wall_ns', 'elapsed_wall_ns'):
        _int(record[field], field, nullable=True)
    if None not in (record['started_wall_ns'], record['ended_wall_ns'], record['elapsed_wall_ns']):
        if record['ended_wall_ns']-record['started_wall_ns'] != record['elapsed_wall_ns']:
            raise ValueError('Window elapsed wall must use its own outer endpoints')
    _cohort(record['cohort']); _sha(record['source_sha256'])
    prerequisite = evaluate_artificial_overhead(record['prerequisite_C'])
    _list(record['entries'], 28, 'entries'); _list(record['calibrations'], 56, 'calibrations')
    reasons, capability_results, namespaces, entry_envelopes = [], [], [], []
    if (any(record[name] is None for name in ('started_wall_ns', 'ended_wall_ns', 'elapsed_wall_ns'))
            or record['elapsed_wall_ns'] > 1_800_000_000_000):
        reasons.append('window_incomplete_or_deadline')
    for index, (row, expected) in enumerate(zip(record['entries'], D_SCHEDULE)):
        _fields(row, ('label', 'decoder', 'mode', 'block', 'namespace', 'completed', 'thread_id',
            'cohort', 'source_sha256', 'original_entry_metric', 'metrics', 'timeline',
            'event_brackets_ns', 'agreement', 'calibration_before', 'calibration_after'))
        _int(row['block'], 'block'); _bool(row['completed'], 'completed'); _int(row['thread_id'], 'thread_id')
        if (row['label'], row['decoder'], row['mode'], row['block']) != expected:
            raise ValueError('All warmups and six alternating decoder blocks must keep their fixed order')
        _text(row['namespace'], 'namespace'); namespaces.append(row['namespace'])
        _cohort(row['cohort']); _sha(row['source_sha256'])
        if row['cohort'] != record['cohort'] or row['source_sha256'] != record['source_sha256']:
            raise ValueError('Source/cohort differs within the fixed window')
        if row['original_entry_metric'] != SOURCE_METRIC:
            raise ValueError('Original entry metric cannot be replaced by run.total or entry_span')
        _metric_values(row)
        _fields(row['agreement'], ('payload_equal', 'workload_equal', 'ledger_equal', 'source_verified',
                                  'outer_scope_verified'))
        for field, value in row['agreement'].items():
            if value is None:
                reasons.append(row['label']+'_agreement_unavailable_'+field)
                continue
            _bool(value, field)
            if not value:
                raise ValueError('Independent semantic agreement failed: '+field)
        if (not row['completed'] or any(value is None for value in _metric_values(row).values())
                or row['metrics']['run_total_ns'] is None or row['metrics']['entry_span_ns'] is None
                or any(None in row['metrics'][phase] for phase in LOCAL_PHASES)):
            reasons.append(row['label']+'_unavailable')
        timeline = row['timeline']
        _fields(timeline, ('before_calibration_end_ns', 'sampler_first_ns', 'instrumentation_start_ns',
            'instrumentation_end_ns', 'sampler_last_ns', 'after_calibration_start_ns'))
        for value in timeline.values():
            _int(value, 'timeline', nullable=True)
        if any(value is None for value in timeline.values()):
            reasons.append(row['label']+'_timeline_missing')
        else:
            points = [timeline[name] for name in ('before_calibration_end_ns', 'sampler_first_ns',
                'instrumentation_start_ns', 'instrumentation_end_ns', 'sampler_last_ns', 'after_calibration_start_ns')]
            if points != sorted(points):
                raise ValueError('Sampler coverage or calibration placement differs')
            if (row['metrics']['instrumentation_entry_ns'] is not None
                    and points[3]-points[2] != row['metrics']['instrumentation_entry_ns']):
                raise ValueError('Instrumentation metric must use its own same outer endpoints')
        brackets = row['event_brackets_ns']
        if type(brackets) is not list:
            raise ValueError('Event brackets must keep their list')
        if row['mode'] == 'O' and brackets:
            raise ValueError('Original O cannot contain new boundary probes')
        if row['mode'] == 'D' and row['completed'] and len(brackets) != 725:
            raise ValueError('Completed D requires all 725 boundary brackets')
        for bracket in brackets:
            _int(bracket, 'event bracket', nullable=True)
        if row['mode'] == 'D' and (None in brackets or any(value > 100_000 for value in brackets if value is not None)):
            reasons.append(row['label']+'_event_bracket_unconfirmed')
        for offset, position in enumerate(('before', 'after')):
            calibration = record['calibrations'][2*index+offset]
            _fields(calibration, ('id', 'entry_label', 'position', 'capability'))
            identity = row['label']+':'+position
            if (calibration['id'] != identity or row['calibration_'+position] != identity
                    or calibration['entry_label'] != row['label'] or calibration['position'] != position):
                raise ValueError('All 56 pre/post calibrations must remain attached to their own entry')
            result = evaluate_capability(calibration['capability'])
            if result['status'] == 'rejected_structure':
                raise ValueError('Malformed pre/post calibration: '+identity)
            if (calibration['capability']['environment']['thread_id'] != row['thread_id']
                    or calibration['capability']['environment']['source_sha256'] != record['source_sha256']):
                raise ValueError('Calibration thread/source differs from its entry')
            capability_results.append(dict(id=identity, result=result))
            endpoint = 'ended_wall_ns' if position == 'before' else 'started_wall_ns'
            outer_endpoint = 'before_calibration_end_ns' if position == 'before' else 'after_calibration_start_ns'
            if (calibration['capability'][endpoint] is not None and timeline[outer_endpoint] is not None
                    and calibration['capability'][endpoint] != timeline[outer_endpoint]):
                raise ValueError('Calibration must share its actual outer endpoint with the entry timeline')
            if result['status'] != 'clock_capability_passed':
                reasons.append(identity+'_capability_not_passed')
        entry_envelopes.append((record['calibrations'][2*index]['capability']['started_wall_ns'],
                                record['calibrations'][2*index+1]['capability']['ended_wall_ns']))
        before, after = (record['calibrations'][2*index+offset]['capability'] for offset in (0, 1))
        if before['environment'] != after['environment'] or before['clocks'] != after['clocks']:
            raise ValueError('Pre/post calibration must retain worker identity and clock metadata')
        if all(item['result']['status'] == 'clock_capability_passed' for item in capability_results[-2:]):
            _pair(before['sleeps'][-1]['end'], after['rounds'][0]['stamps'][0], row['thread_id'])
    if len(namespaces) != len(set(namespaces)):
        raise ValueError('All 28 entries require a fresh namespace')
    for first, second in zip(entry_envelopes, entry_envelopes[1:]):
        if first[1] is not None and second[0] is not None and first[1] > second[0]:
            raise ValueError('Entries and all their calibrations must execute sequentially')
    for index in range(27):
        after = record['calibrations'][2*index+1]['capability']
        before = record['calibrations'][2*(index+1)]['capability']
        first_identity = tuple(after['environment'][name] for name in ('process_id', 'thread_id'))
        second_identity = tuple(before['environment'][name] for name in ('process_id', 'thread_id'))
        if (first_identity == second_identity
                and capability_results[2*index+1]['result']['status'] == 'clock_capability_passed'
                and capability_results[2*(index+1)]['result']['status'] == 'clock_capability_passed'):
            _pair(after['sleeps'][-1]['end'], before['rounds'][0]['stamps'][0], before['environment']['thread_id'])
    for start, end in entry_envelopes:
        if ((start is not None and record['started_wall_ns'] is not None and start < record['started_wall_ns'])
                or (end is not None and record['ended_wall_ns'] is not None and end > record['ended_wall_ns'])):
            raise ValueError('Window envelope cannot omit entry or calibration costs')
    summaries = {}
    for decoder in DECODERS:
        rows = [row for row in record['entries'][4:] if row['decoder'] == decoder]
        metrics = {metric: _paired(rows, metric, relative=True) for metric in GLOBAL_METRICS}
        metrics.update({f'{ordinal}:{phase}': _paired(rows, f'{ordinal}:{phase}', relative=False)
                        for ordinal in (32, 33) for phase in LOCAL_PHASES})
        summaries[decoder] = metrics
        if any(not result['passed'] for result in metrics.values()):
            reasons.append(decoder+'_perturbation_budget')
    if prerequisite['status'] != 'artificial_perturbation_passed':
        reasons.append('prerequisite_C_not_passed')
    capability_bad = any(row['result']['status'] != 'clock_capability_passed' for row in capability_results)
    resolution_bad = any(row['result']['status'] == 'cpu_resolution_insufficient' for row in capability_results)
    status = ('rejected_structure' if prerequisite['status'] == 'rejected_structure' else
              'cpu_resolution_insufficient' if resolution_bad else
              'clock_capability_unconfirmed' if capability_bad or any('bracket_unconfirmed' in reason for reason in reasons) else
              prerequisite['status'] if prerequisite['status'] != 'artificial_perturbation_passed' else
              'perturbation_not_accepted' if reasons else 'window_perturbation_passed')
    return _result(status, reasons, record, prerequisite=prerequisite,
        warmups=deepcopy(record['entries'][:4]), decoders=summaries, calibrations=capability_results,
        formal_pairs=12, formal_entries=24, warm_entries=4, calibration_count=56,
        original_entry_metric=SOURCE_METRIC, local_display_ordinals=[32, 33],
        local_subset_ordinals=[31, 32], live_B_C_D_passed=False)


def evaluate_window(record):
    return _public(_window, record)
