"""Pure comparisons of already saved whole-entry load summaries.

No telemetry APIs, SQL, model loading, interpolation or causal adjustment.
Warm entries and publisher observations never enter the six-pair summaries.
"""
from copy import deepcopy
from math import isfinite
from statistics import median


WINDOWS = ('V47', 'V48')
ARMS = ('R', 'C')
ORDERS = ('CR', 'RC') * 3
SCHEDULE = [dict(label='warm_' + arm, mode=arm) for arm in ARMS] + [
    dict(label=f'pair_{pair}_{arm}', mode=arm)
    for pair, order in enumerate(ORDERS, 1) for arm in order]
METRIC_UNITS = {
    'entry_seconds': 'seconds', 'telemetry_duration_seconds': 'seconds', 'samples': 'count',
    'system_cpu_mean_percent': 'percent_all_logical_cpus',
    'system_cpu_max_percent': 'percent_all_logical_cpus',
    'worker_cpu_mean_core_percent': 'percent_one_logical_cpu', 'worker_rss_max_bytes': 'bytes',
    'ollama_cpu_mean_core_percent': 'percent_one_logical_cpu', 'ollama_rss_max_bytes': 'bytes',
    'available_memory_min_bytes': 'bytes',
    'disk_read_bytes': 'bytes', 'disk_write_bytes': 'bytes',
    'disk_read_count': 'count', 'disk_write_count': 'count',
    'disk_read_time': 'milliseconds_host_disk_counter', 'disk_write_time': 'milliseconds_host_disk_counter',
    'disk_valid_intervals': 'count', 'disk_unavailable_or_reset_intervals': 'count',
    'coverage_intervals': 'count', 'coverage_max_gap_seconds': 'seconds',
    'estimated_missing_periodic_intervals': 'estimated_count',
    'collector_mean_seconds': 'seconds', 'collector_max_seconds': 'seconds',
    'collector_total_seconds': 'seconds',
}
METRICS = tuple(METRIC_UNITS)
DELTA_UNITS = {name: ('percentage_points_' + unit.removeprefix('percent_')
    if unit.startswith('percent_') else unit) for name, unit in METRIC_UNITS.items()}
PROCESS_COUNTS = ('observed_processes', 'valid_cpu_intervals', 'unavailable_observations',
                  'discontinuous_cpu_intervals', 'partial_cpu_intervals')


def _number(value, name, *, positive=False, integer=False):
    try:
        valid = (type(value) in (int, float) and isfinite(value)
                 and (value > 0 if positive else value >= 0)
                 and (not integer or type(value) is int))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Invalid nonnegative numeric load field: ' + name)
    return value


def _triple(value, name, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, dict) or set(value) != {'min', 'mean', 'max'}:
        raise ValueError('Expected a saved min/mean/max summary: ' + name)
    for key, number in value.items():
        _number(number, name + '.' + key)
    if not value['min'] <= value['mean'] <= value['max']:
        raise ValueError('Inconsistent summary ordering: ' + name)
    return value


def _process(value, name, intervals, duration):
    if not isinstance(value['status'], str) or not value['status']:
        raise ValueError('Process availability status is required')
    for key in PROCESS_COUNTS:
        _number(value[key], name + '.' + key, integer=True)
    seconds = _number(value['valid_cpu_duration_seconds'], name + '.valid_cpu_duration_seconds')
    valid = value['valid_cpu_intervals']
    if valid > intervals or value['partial_cpu_intervals'] > valid or seconds > duration + 1e-9:
        raise ValueError('Process valid coverage exceeds observation coverage')
    cpu = _triple(value['cpu_core_percent'], name + '.cpu_core_percent', optional=True)
    rss = _triple(value['rss_bytes'], name + '.rss_bytes', optional=True)
    if (valid == 0) != (cpu is None) or (valid == 0) != (seconds == 0):
        raise ValueError('Unavailable CPU must retain zero valid interval coverage')
    quality = {key: value[key] for key in (*PROCESS_COUNTS, 'status', 'valid_cpu_duration_seconds')}
    return (None if cpu is None else cpu['mean'], None if rss is None else rss['max'], quality)


def _status_counts(value, name, samples):
    if not isinstance(value, dict) or not value or any(not isinstance(k, str) or not k for k in value):
        raise ValueError('Availability status counts required: ' + name)
    for number in value.values():
        _number(number, name, integer=True)
    if sum(value.values()) != samples:
        raise ValueError('Status counts must cover every sample: ' + name)
    return deepcopy(value)


def flatten_load(load, entry_seconds=None):
    """Expose fixed metrics and quality; publisher entry_seconds stays unavailable."""
    if entry_seconds is not None:
        _number(entry_seconds, 'entry_seconds', positive=True)
    duration = _number(load['duration_seconds'], 'duration_seconds', positive=True)
    samples = _number(load['samples'], 'samples', positive=True, integer=True)
    coverage = load['coverage']
    intervals = _number(coverage['intervals'], 'coverage.intervals', integer=True)
    if samples < 3 or intervals != samples - 1 or load['nominal_interval_seconds'] != .2:
        raise ValueError('Expected original 200 ms telemetry and samples minus one intervals')
    max_gap = _number(coverage['max_gap_seconds'], 'max_gap_seconds', positive=True)
    if max_gap > duration + 1e-9:
        raise ValueError('A sample gap cannot exceed its telemetry duration')
    missing = _number(coverage['missing_periodic_intervals'], 'missing_periodic_intervals', integer=True)
    system = _triple(load['system_cpu_percent'], 'system_cpu_percent')
    if system['max'] > 100:
        raise ValueError('System CPU percentage cannot exceed 100')
    available = _triple(load['available_memory_bytes'], 'available_memory_bytes')
    collector = _triple(load['collector_seconds'], 'collector_seconds')
    total = _number(load['total_collector_seconds'], 'total_collector_seconds')
    if abs(total - collector['mean'] * samples) > max(1e-9, total * 1e-10):
        raise ValueError('Collector sample mean must reconcile to its total')
    worker_cpu, worker_rss, worker_quality = _process(load['worker'], 'worker', intervals, duration)
    ollama_cpu, ollama_rss, ollama_quality = _process(load['ollama'], 'ollama', intervals, duration)
    disk_valid = _number(load['disk_valid_intervals'], 'disk_valid_intervals', integer=True)
    disk_missing = _number(load['disk_unavailable_or_reset_intervals'], 'disk_missing_intervals', integer=True)
    if disk_valid + disk_missing != intervals:
        raise ValueError('Disk valid and unavailable intervals must conserve coverage')
    disk = load['disk_io_delta']
    disk_keys = ('read_bytes', 'write_bytes', 'read_count', 'write_count', 'read_time', 'write_time')
    if (disk_valid == 0) != (disk is None):
        raise ValueError('Unavailable disk counters require zero valid intervals')
    if disk is not None:
        if set(disk) != set(disk_keys):
            raise ValueError('Expected the six saved host disk counters')
        for key in disk_keys:
            _number(disk[key], 'disk.' + key, integer=True)
    metrics = dict(entry_seconds=entry_seconds, telemetry_duration_seconds=duration, samples=samples,
        system_cpu_mean_percent=system['mean'], system_cpu_max_percent=system['max'],
        worker_cpu_mean_core_percent=worker_cpu, worker_rss_max_bytes=worker_rss,
        ollama_cpu_mean_core_percent=ollama_cpu, ollama_rss_max_bytes=ollama_rss,
        available_memory_min_bytes=available['min'],
        **{'disk_' + key: None if disk is None else disk[key] for key in disk_keys},
        disk_valid_intervals=disk_valid, disk_unavailable_or_reset_intervals=disk_missing,
        coverage_intervals=intervals, coverage_max_gap_seconds=max_gap,
        estimated_missing_periodic_intervals=missing,
        collector_mean_seconds=collector['mean'], collector_max_seconds=collector['max'],
        collector_total_seconds=total)
    quality = dict(nominal_interval_seconds=.2, worker=worker_quality, ollama=ollama_quality,
        disk_status_counts=_status_counts(load['disk_status_counts'], 'disk_status_counts', samples),
        ollama_scan_status_counts=_status_counts(load['ollama_scan_status_counts'], 'ollama_scan_status_counts', samples))
    return dict(metrics=metrics, load_quality=quality)


def _summary(values):
    available = [value for value in values if value is not None]
    return dict(count=len(values), valid=len(available), missing=len(values) - len(available),
        min=min(available) if available else None, median=median(available) if available else None,
        max=max(available) if available else None)


def _difference(later, earlier):
    return {key: None if later[key] is None or earlier[key] is None else later[key] - earlier[key]
            for key in METRICS}


def analyze_load_reports(reports):
    """Compare all formal pairs, preserving the saved execution order and nulls."""
    if set(reports) != set(WINDOWS):
        raise ValueError('Exactly V47 and V48 are required')
    windows = {}
    for window in WINDOWS:
        report = reports[window]
        if report['schedule'] != SCHEDULE or set(report['runs']) != {x['label'] for x in SCHEDULE}:
            raise ValueError('All 14 entries in the original CR/RC schedule are required')
        rows = []
        for position, item in enumerate(SCHEDULE, 1):
            source = report['runs'][item['label']]
            if source['mode'] != item['mode']:
                raise ValueError('Saved run arm differs from original schedule')
            entry = source['accounting']['costs']['entry_seconds']
            _number(entry, 'entry_seconds', positive=True)
            rows.append(dict(label=item['label'], arm=item['mode'], run_position=position,
                             **flatten_load(source['load'], entry)))
        by_label = {row['label']: row for row in rows}
        formal = rows[2:]
        pairs = []
        for pair, order in enumerate(ORDERS, 1):
            r, c = (by_label[f'pair_{pair}_{arm}']['metrics'] for arm in ARMS)
            pairs.append(dict(pair=pair, order=order, R=deepcopy(r), C=deepcopy(c),
                              delta_C_minus_R=_difference(c, r)))
        directions = [row['delta_C_minus_R']['entry_seconds'] for row in pairs]
        windows[window] = dict(formal_entries=formal, pairs=pairs,
            formal_by_arm={arm: {key: _summary([row['metrics'][key] for row in formal if row['arm'] == arm])
                                 for key in METRICS} for arm in ARMS},
            pair_delta_summary={key: _summary([row['delta_C_minus_R'][key] for row in pairs]) for key in METRICS},
            entry_direction_counts=dict(candidate_slower=sum(x > 0 for x in directions),
                candidate_faster=sum(x < 0 for x in directions), equal=sum(x == 0 for x in directions)),
            warm_entries=rows[:2], publisher=flatten_load(report['publisher_load']))
    between = {arm: {key: dict(V47=windows['V47']['formal_by_arm'][arm][key]['median'],
                               V48=windows['V48']['formal_by_arm'][arm][key]['median'])
                     for key in METRICS} for arm in ARMS}
    for arm in ARMS:
        for row in between[arm].values():
            row['median_difference_V48_minus_V47'] = (
                None if row['V47'] is None or row['V48'] is None else row['V48'] - row['V47'])
    return dict(metric_units=deepcopy(METRIC_UNITS), delta_units=deepcopy(DELTA_UNITS),
        windows=windows, between_window_arm_medians=between,
        interpretation=[
            'C minus R is signed descriptive difference, not a load-adjusted treatment effect.',
            'Between-window median differences are unpaired differences of six-entry medians.',
            'Telemetry brackets the entry and has a different boundary from entry_seconds.',
            'Disk deltas are host totals, not process IO or query waiting time.',
            'Collector elapsed is not removable observer overhead; gaps are not wait durations.',
            'No interpolation, correlation, regression, significance test or causal attribution.'])
