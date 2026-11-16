"""Pure geometry of saved coarse phases and telemetry capture intervals.

Inputs are one entry's sanitized integer-nanosecond coordinates only.  No CPU
or disk value is allocated by the overlaps computed here.  Nominal intervals
join adjacent capture starts, so nominal coverage alone is not time resolution.
"""


MIN_CONTAINED_INTERVALS = 2
MIN_CONTAINED_SHARE = .5
RULES = dict(clock_unit='integer_nanoseconds', nominal_interval='[start_i,start_i+1)',
    capture_hull='[start_i,start_i+1+capture_i+1)', touch_is_overlap=False,
    containment_allows_equal_boundaries=True, minimum_capture_contained_intervals=2,
    minimum_capture_contained_interior_share=.5,
    resource_proration=False, screen_is_causal_or_accuracy_test=False)


def _ns(value, name):
    if type(value) is not int or value < 0:
        raise ValueError('Nonnegative integer nanoseconds required: ' + name)
    return value


def _bounds(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError('Exactly one phase start/end pair required')
    start, end = (_ns(x, 'phase boundary') for x in value)
    if end < start:
        raise ValueError('Phase end precedes its start')
    return start, end


def _records(records):
    if not isinstance(records, (tuple, list)) or len(records) < 2:
        raise ValueError('At least two captures from one entry required')
    result = []
    for index, record in enumerate(records):
        if (not isinstance(record, dict) or set(record) != {'sequence', 'start_ns', 'capture_ns'}
                or type(record['sequence']) is not int or record['sequence'] != index):
            raise ValueError('Consecutive zero-based capture sequence and sanitized keys required')
        start = _ns(record['start_ns'], 'capture start')
        duration = _ns(record['capture_ns'], 'capture duration')
        if result and (start <= result[-1][0] or result[-1][0] + result[-1][1] > start):
            raise ValueError('Capture starts must increase and capture windows must not overlap')
        result.append((start, duration))
    return result


def _overlap(left_start, left_end, right_start, right_end):
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def analyze_interval(phase_ns, records, *, origin_ns=0):
    """Describe one phase against one entry's samples, without interpolation.

    A nominal interval is fully contained when both adjacent capture starts lie
    within the phase. A capture hull also includes the right capture's elapsed
    acquisition window. Only hull-contained intervals enter the coarse screen;
    the intervals from each left capture's end to the right capture's start
    form its numerator. These are confirmed gaps between acquisition windows,
    not CPU time or exact counter-read intervals. Nominal durations remain as a
    separate descriptor. Hull-only intersections add no coverage. Every output
    coordinate is relative to ``origin_ns``.
    """
    start, end = _bounds(phase_ns)
    origin = _ns(origin_ns, 'origin')
    samples = _records(records)
    duration = end - start
    intervals, hull_only = [], []
    for index, ((left, left_capture), (right, right_capture)) in enumerate(zip(samples, samples[1:])):
        hull_end = right + right_capture
        overlap = _overlap(start, end, left, right)
        hull_overlap = _overlap(start, end, left, hull_end)
        if not overlap and not hull_overlap:
            continue
        nominal_contained = start <= left and right <= end
        capture_contained = start <= left and hull_end <= end
        row = dict(left_sequence=index, right_sequence=index + 1,
            nominal_start_offset_ns=left - origin, nominal_end_offset_ns=right - origin,
            capture_hull_end_offset_ns=hull_end - origin,
            nominal_duration_ns=right - left, nominal_overlap_ns=overlap,
            guaranteed_interior_ns=max(0, right - (left + left_capture)),
            capture_hull_overlap_ns=hull_overlap,
            nominal_contained=nominal_contained, capture_hull_contained=capture_contained,
            classification=('capture_contained' if capture_contained else
                            'nominal_contained_capture_crossing' if nominal_contained else
                            'nominal_crossing' if overlap else 'capture_hull_only'))
        (intervals if overlap else hull_only).append(row)

    nominal_full = [row for row in intervals if row['nominal_contained']]
    capture_full = [row for row in intervals if row['capture_hull_contained']]
    overlap_union = sum(row['nominal_overlap_ns'] for row in intervals)
    full_duration = sum(row['nominal_duration_ns'] for row in nominal_full)
    conservative_duration = sum(row['nominal_duration_ns'] for row in capture_full)
    interior_duration = sum(row['guaranteed_interior_ns'] for row in capture_full)
    if not 0 <= interior_duration <= conservative_duration <= full_duration <= overlap_union <= duration:
        raise ValueError('Nonoverlapping nominal intervals must conserve phase coverage')
    positive = duration > 0
    count_gate = len(capture_full) >= MIN_CONTAINED_INTERVALS
    share_gate = positive and 2 * interior_duration >= duration
    eligible = positive and count_gate and share_gate
    reason = ('zero_duration' if not positive else 'no_contained' if not capture_full else
              'too_few' if not count_gate else 'low_share' if not share_gate else 'eligible')

    def ratio(value):
        return value / duration if positive else None

    return dict(phase_start_offset_ns=start - origin, phase_end_offset_ns=end - origin,
        phase_duration_ns=duration, samples=len(samples), adjacent_intervals=len(samples) - 1,
        nominal_overlap_count=len(intervals), nominal_contained_count=len(nominal_full),
        nominal_crossing_count=len(intervals) - len(nominal_full),
        capture_hull_contained_count=len(capture_full),
        nominal_contained_capture_crossing_count=len(nominal_full) - len(capture_full),
        capture_hull_only_count=len(hull_only),
        nominal_overlap_union_ns=overlap_union, nominal_overlap_share=ratio(overlap_union),
        nominal_contained_duration_ns=full_duration, nominal_contained_share=ratio(full_duration),
        capture_contained_nominal_duration_ns=conservative_duration,
        capture_contained_nominal_share=ratio(conservative_duration),
        capture_contained_interior_duration_ns=interior_duration,
        capture_contained_interior_share=ratio(interior_duration),
        max_nominal_overlap_interval_ns=max((row['nominal_duration_ns'] for row in intervals), default=None),
        nominal_boundary_only=bool(intervals) and not nominal_full,
        intervals=intervals, capture_hull_only_intervals=hull_only,
        screen=dict(positive_duration=positive, minimum_contained_intervals=MIN_CONTAINED_INTERVALS,
            minimum_contained_interior_share=MIN_CONTAINED_SHARE, count_gate_passed=count_gate,
            share_gate_passed=share_gate, eligible=eligible, reason=reason))
