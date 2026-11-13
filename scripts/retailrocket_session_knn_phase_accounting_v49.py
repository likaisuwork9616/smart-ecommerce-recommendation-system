"""Partition saved V47/V48 observations without executing a measured workload."""
from collections import defaultdict
from math import fsum, isclose, isfinite

from scripts.retailrocket_session_knn_sources_v24 import summarize_events


TOLERANCE_SECONDS = 1e-8
PARENTS = {
    'run.total': {None},
    'checkpoint.create': {'run.total'},
    'checkpoint.writer_lifetime': {'run.total'},
    'checkpoint.writer_acquire': {'checkpoint.writer_lifetime'},
    'checkpoint.check_sources': {'checkpoint.create', 'checkpoint.writer_acquire'},
    'binding.verify_sources': {'checkpoint.check_sources'},
    'binding.descriptor': {'binding.verify_sources'},
    'verifier.total': {'checkpoint.writer_lifetime'},
    'verifier.setup_envelope': {'verifier.total'},
    'context.load_context': {'verifier.setup_envelope'},
    'context.prepare_catalog': {'verifier.setup_envelope'},
    'cache.identity': {'context.load_context'},
    'cache.cold_build': {'context.load_context'},
    'cache.original_load_context': {'cache.cold_build'},
    'cache.original_prepare_catalog': {'cache.cold_build'},
    'cache.pre_use_digest': {'context.load_context'},
    'cache.use': {'context.load_context'},
    'cache.final_guard': {'verifier.total'},
    'snapshot.fingerprint': {'cache.cold_build', 'cache.pre_use_digest', 'cache.final_guard'},
    'snapshot.validation': {'snapshot.fingerprint'},
    'snapshot.json': {'snapshot.fingerprint'},
    'snapshot.utf8': {'snapshot.fingerprint'},
    'snapshot.sha256': {'snapshot.fingerprint'},
    'snapshot.release': {'snapshot.fingerprint'},
    'verifier.seal_consistent': {'verifier.total'},
    'run.ledger_proof': {'run.total'},
    'run.output_write': {'run.total'},
}
MULTIPLE = {'checkpoint.check_sources', 'binding.verify_sources', 'binding.descriptor',
            'run.output_write', *(name for name in PARENTS if name.startswith('snapshot.'))}
SNAPSHOT_LOCATIONS = {'cache.cold_build': 'cold', 'cache.pre_use_digest': 'pre_use', 'cache.final_guard': 'final'}
PRIMARY_FIELDS = {'verification_seconds', 'append_excluding_commit_seconds', 'all_commit_seconds'}


def _seconds(value, name):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError('Finite nonnegative saved seconds required: ' + name)
    return value


def _remainder(total, values, name):
    value = total - fsum(values)
    if value < -TOLERANCE_SECONDS:
        raise ValueError('Parts exceed enclosing interval: ' + name)
    return max(0.0, value)


def partition(events, accounting, expected_diagnostic=None):
    """Return an additive entry partition and explicitly nested detail tables.

    The signed bridge preserves the difference between the entry timer and the
    observer root. Snapshot details and primary details are nested alternatives,
    not extra terms to add to ``parts_seconds``. ``rank_parts_seconds`` partitions
    verification time into ranking stages, ranking remainder and work outside
    ranking; it is a child of ``primary_parts_seconds['verification_seconds']``.
    """
    diagnostic = summarize_events(events)
    if expected_diagnostic is not None and diagnostic != expected_diagnostic:
        raise ValueError('Saved diagnostic differs from the original event tree')
    if any(not event['completed'] for event in events):
        raise ValueError('Only completed saved entries may be partitioned')
    by_phase = defaultdict(list)
    children = defaultdict(list)
    for event in events:
        by_phase[event['phase']].append(event)
        children[event['parent']].append(event)
        parent_phase = None if event['parent'] is None else events[event['parent']]['phase']
        if event['phase'] not in PARENTS or parent_phase not in PARENTS[event['phase']]:
            raise ValueError('Unexpected cold-entry phase or parent: ' + event['phase'])
    if set(by_phase) != set(PARENTS) or len(children[None]) != 1:
        raise ValueError('Complete original cold-entry tree required')
    for phase in set(PARENTS) - MULTIPLE:
        if len(by_phase[phase]) != 1:
            raise ValueError('Expected exactly one phase: ' + phase)

    def one(phase):
        return by_phase[phase][0]

    def duration(event):
        return event['end_ns'] - event['start_ns']

    exclusive = {event['id']: duration(event) - sum(duration(child) for child in children[event['id']])
                 for event in events}
    by_exclusive = {phase: sum(exclusive[event['id']] for event in grouped) / 1e9
                    for phase, grouped in by_phase.items()}
    cold = one('cache.cold_build')
    proof = one('cache.use')['metadata']['typed_reference']
    build, checks = proof['build'], proof['checks']
    if (build.get('completed') is not True or type(build.get('roots')) is not int or build['roots'] != 2
            or type(checks) is not list or len(checks) != 2
            or [row.get('root') for row in checks] != ['config', 'model']
            or any(row.get('completed') is not True or row.get('equal') is not True for row in checks)):
        raise ValueError('Complete original passive reference and late checks required')
    passive = [('reference_build', build), ('late_config', checks[0]), ('late_model', checks[1])]
    intervals = []
    for name, row in passive:
        start, end = row.get('start_ns'), row.get('end_ns')
        if (type(start) is not int or type(end) is not int
                or not cold['start_ns'] <= start <= end <= cold['end_ns']):
            raise ValueError('Passive interval outside cold build: ' + name)
        for child in children[cold['id']]:
            if max(start, child['start_ns']) < min(end, child['end_ns']):
                raise ValueError('Passive interval overlaps an observed cold child: ' + name)
        intervals.append((start, end))
    for left, right in zip(intervals, intervals[1:]):
        if left[1] > right[0]:
            raise ValueError('Passive reference or late intervals overlap or change order')
    cold_snapshots = [event for event in by_phase['snapshot.fingerprint'] if event['parent'] == cold['id']]
    if (len(cold_snapshots) != 1 or build['end_ns'] > one('cache.original_load_context')['start_ns']
            or one('cache.original_prepare_catalog')['end_ns'] > checks[0]['start_ns']
            or checks[-1]['end_ns'] > cold_snapshots[0]['start_ns']):
        raise ValueError('Passive timings left the original build and late boundaries')

    snapshot_parts = {}
    for event in by_phase['snapshot.fingerprint']:
        location = SNAPSHOT_LOCATIONS[events[event['parent']]['phase']]
        if location in snapshot_parts:
            raise ValueError('Duplicate snapshot location')
        values = dict.fromkeys(('validation', 'json', 'utf8', 'sha256', 'release', 'other'), 0.0)
        values['other'] = exclusive[event['id']] / 1e9
        for child in children[event['id']]:
            values[child['phase'].removeprefix('snapshot.')] += exclusive[child['id']] / 1e9
        snapshot_parts[location] = values
    if set(snapshot_parts) != {'cold', 'pre_use', 'final'}:
        raise ValueError('Exactly three original snapshot locations required')

    costs = accounting['costs']
    entry = _seconds(costs['entry_seconds'], 'entry')
    primary = _seconds(costs['primary_seconds'], 'primary')
    tail = _seconds(accounting['entry_exclusive_seconds']['tail_without_commit_seconds'], 'tail_without_commit')
    primary_parts = dict(accounting['primary_parts_seconds'])
    if set(primary_parts) != PRIMARY_FIELDS:
        raise ValueError('Complete primary subparts required')
    for name, value in primary_parts.items():
        _seconds(value, name)
        if value != costs[name]:
            raise ValueError('Primary subpart differs from saved costs: ' + name)
    residuals = [abs(fsum(primary_parts.values()) - primary)]
    if not isclose(fsum(primary_parts.values()), primary, rel_tol=0, abs_tol=TOLERANCE_SECONDS):
        raise ValueError('Primary subparts do not conserve primary time')
    rank_parts = dict(accounting['rank_stages_seconds'])
    if not rank_parts or {'rank_unpartitioned_seconds', 'verification_outside_rank_seconds'} & set(rank_parts):
        raise ValueError('Distinct original rank stages required')
    for name, value in rank_parts.items():
        _seconds(value, name)
    rank_parts['rank_unpartitioned_seconds'] = _seconds(accounting['rank_unpartitioned_seconds'], 'rank remainder')
    rank = _seconds(costs['rank_seconds'], 'rank')
    if not isclose(fsum(rank_parts.values()), rank, rel_tol=0, abs_tol=TOLERANCE_SECONDS):
        raise ValueError('Rank stages do not conserve rank time')
    rank_parts['verification_outside_rank_seconds'] = _seconds(
        accounting['verification_outside_rank_seconds'], 'verification outside rank')
    residuals.append(abs(fsum(rank_parts.values()) - primary_parts['verification_seconds']))
    if not isclose(fsum(rank_parts.values()), primary_parts['verification_seconds'],
                   rel_tol=0, abs_tol=TOLERANCE_SECONDS):
        raise ValueError('Rank and outside-rank parts do not conserve verification time')
    seal = duration(one('verifier.seal_consistent')) / 1e9
    if tail < seal - TOLERANCE_SECONDS:
        raise ValueError('Tail without commit must contain the original seal interval')

    parts = {name: (row['end_ns'] - row['start_ns']) / 1e9 for name, row in passive}
    parts.update(
        cold_other=_remainder(by_exclusive['cache.cold_build'], parts.values(), 'cold exclusive'),
        original_load=by_exclusive['cache.original_load_context'],
        prepare_catalog=by_exclusive['cache.original_prepare_catalog'],
        **{'snapshot_' + location: fsum(values.values()) for location, values in snapshot_parts.items()},
        identity=by_exclusive['cache.identity'],
        final_guard_other=by_exclusive['cache.final_guard'],
        source_verification=fsum(by_exclusive[name] for name in
            ('checkpoint.check_sources', 'binding.verify_sources', 'binding.descriptor')),
        checkpoint_other=fsum(by_exclusive[name] for name in
            ('checkpoint.create', 'checkpoint.writer_acquire', 'checkpoint.writer_lifetime')),
        primary=primary,
        tail_without_commit=tail,
        verifier_other=_remainder(by_exclusive['verifier.total'] + seal, (primary, tail), 'verifier and seal'),
        setup_other=fsum(by_exclusive[name] for name in ('verifier.setup_envelope', 'context.load_context',
            'context.prepare_catalog', 'cache.pre_use_digest', 'cache.use')),
        ledger_proof=by_exclusive['run.ledger_proof'],
        output_write=by_exclusive['run.output_write'],
        run_other=by_exclusive['run.total'],
        signed_entry_bridge=entry - diagnostic['root_wall_ns'] / 1e9)
    residuals.append(abs(fsum(parts.values()) - entry))
    for event in by_phase['snapshot.fingerprint']:
        location = SNAPSHOT_LOCATIONS[events[event['parent']]['phase']]
        residuals.append(abs(fsum(snapshot_parts[location].values()) - duration(event) / 1e9))
    nonreference = entry - parts['reference_build']
    residuals.append(abs(fsum(value for name, value in parts.items() if name != 'reference_build') - nonreference))
    if max(residuals) > TOLERANCE_SECONDS:
        raise ValueError('Partition does not conserve the saved entry timer')
    return dict(parts_seconds=parts, snapshot_parts_seconds=snapshot_parts, primary_parts_seconds=primary_parts,
        rank_parts_seconds=rank_parts,
        entry_seconds=entry, root_seconds=diagnostic['root_wall_ns'] / 1e9,
        nonreference_seconds=nonreference, events=len(events),
        max_reconciliation_residual_seconds=max(residuals))
