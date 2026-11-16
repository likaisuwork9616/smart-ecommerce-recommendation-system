"""Pure load summaries over explicitly selected, adjacent capture pairs.

The caller verifies V60 geometry and source hashes. This module never bridges
excluded pairs, prorates resource values, or estimates complete-phase load.
"""
from collections import Counter
from math import fsum, isfinite
from statistics import mean


DISK_KEYS = ('read_bytes', 'write_bytes', 'read_count', 'write_count', 'read_time', 'write_time')
METRIC_UNITS = dict(
    selected_intervals='count', selected_duration_seconds='seconds_nominal_selected_intervals',
    phase_seconds='seconds', confirmed_interior_share='fraction',
    system_cpu_mean_percent='percent_all_logical_cpus',
    worker_cpu_mean_core_percent='percent_one_logical_cpu',
    ollama_cpu_mean_core_percent='percent_one_logical_cpu',
    available_memory_min_bytes='bytes', worker_rss_max_bytes='bytes', ollama_rss_max_bytes='bytes',
    disk_read_bytes='bytes', disk_write_bytes='bytes', disk_read_count='count', disk_write_count='count',
    disk_read_time='milliseconds_host_disk_counter', disk_write_time='milliseconds_host_disk_counter',
    collector_mean_seconds='seconds', collector_max_seconds='seconds')
METRICS = tuple(METRIC_UNITS)
DELTA_UNITS = {name: ('percentage_points_' + unit.removeprefix('percent_')
    if unit.startswith('percent_') else unit) for name, unit in METRIC_UNITS.items()}
POLICY = dict(selection='V60 capture_hull_contained only',
    interval_weight='raw right monotonic_seconds minus raw left monotonic_seconds',
    point_samples='unique selected interval endpoints',
    process_intervals='complete observed identity sets, successful scan, nonreset counters',
    partial_process_intervals='invalid as a whole; no common-subset estimate',
    disk_intervals='all six adjacent counters valid; no counter reset',
    no_selected_or_valid_observations='null resource summary, never zero',
    resource_proration=False, full_phase_estimate=False)


def _finite(value):
    try:
        return type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError('Nonnegative integer required: ' + name)
    return value


def _selection(records, coverage):
    if not isinstance(records, (list, tuple)) or len(records) < 2:
        raise ValueError('At least two original capture records required')
    for index, record in enumerate(records):
        if type(record['sequence']) is not int or record['sequence'] != index:
            raise ValueError('Original zero-based capture sequence required')
        if not _finite(record['monotonic_seconds']):
            raise ValueError('Finite nonnegative capture start required')
        if index and record['monotonic_seconds'] <= records[index - 1]['monotonic_seconds']:
            raise ValueError('Capture starts must strictly increase')
    phase_ns = _integer(coverage['phase_duration_ns'], 'phase_duration_ns')
    interior_ns = _integer(coverage['capture_contained_interior_duration_ns'], 'interior_duration_ns')
    share = coverage['capture_contained_interior_share']
    if (interior_ns > phase_ns or (phase_ns == 0 and (share is not None or interior_ns != 0))
            or (phase_ns > 0 and (not _finite(share) or share != interior_ns / phase_ns))):
        raise ValueError('Unchanged V60 interior share required')
    selected, previous = [], -1
    for row in coverage['intervals']:
        left, right = row['left_sequence'], row['right_sequence']
        if (type(left) is not int or type(right) is not int or not 0 <= left < right < len(records)
                or right != left + 1 or left <= previous
                or type(row['capture_hull_contained']) is not bool):
            raise ValueError('Unique ordered original adjacent interval identities required')
        previous = left
        if row['capture_hull_contained']:
            selected.append((left, right))
    count = _integer(coverage['capture_hull_contained_count'], 'capture_hull_contained_count')
    if count != len(selected) or (phase_ns == 0 and selected):
        raise ValueError('Selected count must match V60 containment')
    endpoints = sorted({index for pair in selected for index in pair})
    durations = [records[right]['monotonic_seconds'] - records[left]['monotonic_seconds']
                 for left, right in selected]
    return selected, durations, dict(
        selected_pairs=[list(pair) for pair in selected], endpoint_sequences=endpoints,
        selected_intervals=len(selected), selected_duration_seconds=fsum(durations),
        phase_seconds=phase_ns / 1e9, confirmed_interior_share=share,
        confirmed_interior_duration_seconds=interior_ns / 1e9,
        excluded_nominal_intervals=len(coverage['intervals']) - len(selected),
        excluded_hull_only_intervals=len(coverage['capture_hull_only_intervals']))


def _describe(values, weights=None):
    if not values:
        return None
    average = mean(values) if weights is None else fsum(v * w for v, w in zip(values, weights, strict=True)) / fsum(weights)
    return dict(min=min(values), mean=average, max=max(values))


def _quality(all_durations, durations, reasons):
    return dict(intervals=len(all_durations), valid_intervals=len(durations),
        invalid_intervals=len(all_durations)-len(durations), valid_duration_seconds=fsum(durations),
        invalid_duration_seconds=max(0., fsum(all_durations)-fsum(durations)),
        unavailable_reasons=dict(sorted(reasons.items())))


def _snapshot(record, field):
    if field == 'ollama' and record.get('ollama_scan_status') != 'ok':
        return None, 'scan_unavailable'
    values = [record.get('worker')] if field == 'worker' else record.get('ollama')
    if not isinstance(values, list) or not values:
        return None, 'not_observed'
    found = {}
    for process in values:
        if not isinstance(process, dict) or process.get('status') != 'observed':
            return None, 'process_unavailable'
        pid, created = process.get('pid'), process.get('create_time')
        if type(pid) is not int or pid <= 0 or not _finite(created):
            return None, 'invalid_identity'
        identity = (pid, created)
        if identity in found:
            return None, 'duplicate_identity'
        found[identity] = process
    return found, None


def _process_delta(left, right, field):
    before, reason = _snapshot(left, field)
    if reason:
        return None, reason
    after, reason = _snapshot(right, field)
    if reason:
        return None, reason
    if before.keys() != after.keys():
        return None, 'identity_set_changed'
    deltas = []
    for identity in before:
        for counter in ('cpu_user_seconds', 'cpu_system_seconds'):
            first, last = before[identity].get(counter), after[identity].get(counter)
            if not _finite(first) or not _finite(last):
                return None, 'counter_unavailable'
            if last < first:
                return None, 'counter_reset'
            deltas.append(last-first)
    return fsum(deltas), None


def _process_cpu(records, selected, durations, field):
    rates, valid_durations, deltas, reasons = [], [], [], Counter()
    for (left, right), duration in zip(selected, durations, strict=True):
        delta, reason = _process_delta(records[left], records[right], field)
        if reason:
            reasons[reason] += 1
        else:
            rates.append(100 * delta / duration)
            valid_durations.append(duration)
            deltas.append(delta)
    return dict(**_quality(durations, valid_durations, reasons),
        core_percent=_describe(rates, valid_durations),
        cpu_delta_seconds_sum=fsum(deltas) if deltas else None)


def _disk(records, selected, durations):
    deltas, valid_durations, reasons = [], [], Counter()
    for (left, right), duration in zip(selected, durations, strict=True):
        rows = [records[left], records[right]]
        first, last = (row.get('disk_io') for row in rows)
        if any(row.get('disk_io_status') != 'ok' for row in rows) or first is None or last is None:
            reason = 'counter_unavailable'
        elif (not isinstance(first, dict) or not isinstance(last, dict)
                or set(first) != set(DISK_KEYS) or set(last) != set(DISK_KEYS)):
            reason = 'counter_schema_changed'
        elif any(type(row[key]) is not int or row[key] < 0 for row in (first, last) for key in DISK_KEYS):
            reason = 'counter_unavailable'
        elif any(last[key] < first[key] for key in DISK_KEYS):
            reason = 'counter_reset'
        else:
            reason = None
        if reason:
            reasons[reason] += 1
        else:
            deltas.append({key: last[key]-first[key] for key in DISK_KEYS})
            valid_durations.append(duration)
    return dict(**_quality(durations, valid_durations, reasons),
        counter_delta={key: sum(row[key] for row in deltas) for key in DISK_KEYS} if deltas else None)


def _point_value(record, field):
    if field in ('worker_rss_bytes', 'ollama_rss_bytes'):
        group = field.split('_')[0]
        snapshot, reason = _snapshot(record, group)
        if reason:
            return None, reason
        values = [process.get('rss_bytes') for process in snapshot.values()]
        if any(not _finite(value) for value in values):
            return None, 'rss_unavailable'
        return sum(values), None
    if field == 'available_memory_bytes':
        value = record.get('memory', {}).get('available_bytes')
    else:
        value = record.get('collector_seconds')
    return (value, None) if _finite(value) else (None, 'value_unavailable')


def _points(records, endpoints, field):
    values, reasons = [], Counter()
    for index in endpoints:
        value, reason = _point_value(records[index], field)
        if reason:
            reasons[reason] += 1
        else:
            values.append(value)
    return dict(total_count=len(endpoints), valid_count=len(values), missing_count=len(endpoints)-len(values),
                unavailable_reasons=dict(sorted(reasons.items())), stats=_describe(values))


def summarize_selected(records, coverage):
    """Summarize only original adjacent pairs whose V60 capture hull is inside.

    Interval CPU uses raw nominal start-to-start durations, not confirmed
    interiors or phase duration. Point summaries use deduplicated endpoints.
    A process interval with any partial/unknown identity set is unavailable.
    """
    selected, durations, selection = _selection(records, coverage)
    values, valid_durations, reasons = [], [], Counter()
    for (_, right), duration in zip(selected, durations, strict=True):
        value = records[right].get('system_cpu_percent')
        if not _finite(value) or value > 100:
            reasons['value_unavailable'] += 1
        else:
            values.append(value)
            valid_durations.append(duration)
    return dict(selection=selection,
        system_cpu=dict(**_quality(durations, valid_durations, reasons),
                        percent=_describe(values, valid_durations)),
        worker_cpu=_process_cpu(records, selected, durations, 'worker'),
        ollama_cpu=_process_cpu(records, selected, durations, 'ollama'),
        disk=_disk(records, selected, durations),
        points={field: _points(records, selection['endpoint_sequences'], field) for field in
            ('available_memory_bytes', 'worker_rss_bytes', 'ollama_rss_bytes', 'collector_seconds')})


def flatten_metrics(summary):
    """Fixed comparison fields; quality and reasons remain in the full summary."""
    def stat(value, key):
        return None if value is None else value[key]
    selected, points = summary['selection'], summary['points']
    disk = summary['disk']['counter_delta']
    result = dict(selected_intervals=selected['selected_intervals'],
        selected_duration_seconds=selected['selected_duration_seconds'], phase_seconds=selected['phase_seconds'],
        confirmed_interior_share=selected['confirmed_interior_share'],
        system_cpu_mean_percent=stat(summary['system_cpu']['percent'], 'mean'),
        worker_cpu_mean_core_percent=stat(summary['worker_cpu']['core_percent'], 'mean'),
        ollama_cpu_mean_core_percent=stat(summary['ollama_cpu']['core_percent'], 'mean'),
        available_memory_min_bytes=stat(points['available_memory_bytes']['stats'], 'min'),
        worker_rss_max_bytes=stat(points['worker_rss_bytes']['stats'], 'max'),
        ollama_rss_max_bytes=stat(points['ollama_rss_bytes']['stats'], 'max'),
        **{'disk_' + key: None if disk is None else disk[key] for key in DISK_KEYS},
        collector_mean_seconds=stat(points['collector_seconds']['stats'], 'mean'),
        collector_max_seconds=stat(points['collector_seconds']['stats'], 'max'))
    if tuple(result) != METRICS:
        raise ValueError('Fixed metric order changed')
    return result
