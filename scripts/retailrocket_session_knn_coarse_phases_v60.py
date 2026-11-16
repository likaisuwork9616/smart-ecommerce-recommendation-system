"""Extract seven saved coarse intervals without inventing query boundaries.

These disjoint intervals are selected contexts, not a full entry partition.
The post-setup envelope includes tail and other work and is not V49 primary.
"""
from math import isclose

from scripts.retailrocket_session_knn_phase_accounting_v49 import (
    partition, TOLERANCE_SECONDS)


PHASES = (
    'reference_build', 'original_load', 'prepare_catalog', 'snapshot_cold',
    'snapshot_pre_use', 'post_setup_before_final_guard', 'snapshot_final',
)
SNAPSHOT_PARENTS = {
    'cache.cold_build': 'snapshot_cold',
    'cache.pre_use_digest': 'snapshot_pre_use',
    'cache.final_guard': 'snapshot_final',
}


def extract_phases(events, accounting, diagnostic=None):
    """Validate the original event/accounting tree and expose exact saved bounds.

    ``post_setup_before_final_guard`` uses two event boundaries. It includes the
    query loop, append/commit, tail/seal, closing and intervening work, but not
    the final guard. No per-query or V49-primary boundary is reconstructed.
    Zero-duration intervals remain present for explicit coverage handling.
    """
    partitioned = partition(events, accounting, diagnostic)
    by_phase = {}
    for event in events:
        by_phase.setdefault(event['phase'], []).append(event)

    def one(name):
        rows = by_phase[name]
        if len(rows) != 1:
            raise ValueError('One original coarse event required: ' + name)
        return rows[0]

    root = one('run.total')
    use = one('cache.use')
    build = use['metadata']['typed_reference']['build']
    selected = {
        'reference_build': dict(start_ns=build['start_ns'], end_ns=build['end_ns'],
            source_kind='passive_reference_build', source_event_ids=[use['id']]),
    }
    for name, source in (('original_load', 'cache.original_load_context'),
                         ('prepare_catalog', 'cache.original_prepare_catalog')):
        event = one(source)
        selected[name] = dict(start_ns=event['start_ns'], end_ns=event['end_ns'],
            source_kind='observed_event', source_event_ids=[event['id']])
    for event in by_phase['snapshot.fingerprint']:
        name = SNAPSHOT_PARENTS[events[event['parent']]['phase']]
        if name in selected:
            raise ValueError('Duplicate coarse snapshot owner: ' + name)
        selected[name] = dict(start_ns=event['start_ns'], end_ns=event['end_ns'],
            source_kind='observed_event', source_event_ids=[event['id']])
    setup, guard = one('verifier.setup_envelope'), one('cache.final_guard')
    selected['post_setup_before_final_guard'] = dict(
        start_ns=setup['end_ns'], end_ns=guard['start_ns'],
        source_kind='derived_between_events', source_event_ids=[setup['id'], guard['id']])
    if set(selected) != set(PHASES):
        raise ValueError('Exactly seven original coarse intervals required')

    rows, previous_end = [], root['start_ns']
    for name in PHASES:
        row = selected[name]
        start, end = row['start_ns'], row['end_ns']
        if (type(start) is not int or type(end) is not int
                or not root['start_ns'] <= start <= end <= root['end_ns']
                or start < previous_end):
            raise ValueError('Coarse intervals must be ordered, disjoint and inside run.total')
        duration = end - start
        if name != 'post_setup_before_final_guard' and not isclose(
                duration / 1e9, partitioned['parts_seconds'][name],
                rel_tol=0, abs_tol=TOLERANCE_SECONDS):
            raise ValueError('Saved coarse duration differs from V49 accounting: ' + name)
        rows.append(dict(name=name, duration_ns=duration, **row))
        previous_end = end
    return dict(root_start_ns=root['start_ns'], root_end_ns=root['end_ns'],
                root_duration_ns=root['end_ns'] - root['start_ns'], phases=rows)
