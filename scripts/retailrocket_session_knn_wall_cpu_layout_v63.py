"""Pure V62 fresh48 marker layout validation; no clocks or query execution.

This maps labelled boundary references to a span plan. It does not establish
that the real V4 entry emitted those labels or that scientific output matches.
"""
import re


QUERY_POINTS = ('query_start', 'rank_start', 'rank_end', 'verification_end',
                'append_start', 'append_end', 'query_end')
RANK_PHASES = ('history_and_temp_setup', 'sql_positive_overlaps',
               'neighbor_pool_sha', 'exact_neighbor_selection',
               'sql_selected_votes_and_accumulation', 'top_ten_and_zero_fill',
               'prediction_output')
SETUP_POINTS = ('setup_start', 'prefix_start', 'setup_end')
TAIL_POINTS = ('tail_start', 'tail_end')
QUERY_EXECUTION_POINTS = (QUERY_POINTS[:2] + ('ranking_start',) + RANK_PHASES
                          + QUERY_POINTS[2:])
COHORT_FIELDS = frozenset(('original_ordinal', 'key_sha256'))
MARKER_FIELDS = frozenset(('boundary_id', 'point', 'subset_ordinal',
                           'original_ordinal', 'key_sha256'))


def _cohort(cohort):
    if type(cohort) not in (list, tuple) or len(cohort) != 48:
        raise ValueError('Exactly 48 explicit cohort identities required')
    checked, ordinals, hashes = [], set(), set()
    for item in cohort:
        if type(item) is not dict or set(item) != COHORT_FIELDS:
            raise ValueError('Exact original ordinal and key hash fields required')
        ordinal, digest = item['original_ordinal'], item['key_sha256']
        if type(ordinal) is not int or ordinal < 0 or ordinal in ordinals:
            raise ValueError('Unique nonnegative integer original ordinals required')
        if (type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}', digest) is None
                or digest in hashes):
            raise ValueError('Unique lowercase SHA256 key identities required')
        ordinals.add(ordinal)
        hashes.add(digest)
        checked.append(dict(original_ordinal=ordinal, key_sha256=digest))
    return checked


def _expected(cohort):
    expected = []
    for point in SETUP_POINTS:
        expected.append(dict(point=point, subset_ordinal=None,
                             original_ordinal=None, key_sha256=None))
    for ordinal, identity in enumerate(cohort):
        for point in QUERY_EXECUTION_POINTS:
            expected.append(dict(point=point, subset_ordinal=ordinal, **identity))
    for point in TAIL_POINTS:
        expected.append(dict(point=point, subset_ordinal=None,
                             original_ordinal=None, key_sha256=None))
    return expected


def _span(identity, phase, parent, start, end):
    return dict(id=identity, phase=phase, parent=parent, start=start, end=end)


def _plan(markers):
    """Use supplied boundary ids, never synthesize missing clock readings."""
    spans = [
        _span('setup', 'setup', None, markers[0]['boundary_id'],
              markers[2]['boundary_id']),
        _span('tail', 'tail', None, markers[-2]['boundary_id'],
              markers[-1]['boundary_id'])]
    for ordinal in range(48):
        group = markers[3 + 15 * ordinal:3 + 15 * (ordinal + 1)]
        ids = {row['point']: row['boundary_id'] for row in group}
        prefix = f'query:{ordinal}'
        query, verification, rank, rank_marks, append = (
            prefix + ':' + phase for phase in
            ('query', 'verification', 'rank', 'rank_marks', 'append'))
        spans.extend((
            _span(query, 'query', None, ids['query_start'], ids['query_end']),
            _span(verification, 'verification', query,
                  ids['query_start'], ids['verification_end']),
            _span(rank, 'rank', verification, ids['rank_start'], ids['rank_end']),
            _span(rank_marks, 'rank_marks', rank,
                  ids['ranking_start'], ids['prediction_output']),
            _span(append, 'append', query, ids['append_start'], ids['append_end'])))
        start = ids['ranking_start']
        for phase in RANK_PHASES:
            end = ids[phase]
            spans.append(_span(prefix + ':' + phase, phase, rank_marks, start, end))
            start = end
    return spans


def build_layout(markers, cohort, *, completed, fresh=True):
    """Validate a complete fresh48 trace or its explicitly incomplete prefix.

    The supplied cohort order is authoritative; original ordinals need not be
    numerically sorted. Markers carry ids and labels only. Clock monotonicity,
    thread identity and numeric containment belong to the separate boundary core.
    Incomplete traces get no span plan, even when some queries finished.
    """
    if type(completed) is not bool or type(fresh) is not bool:
        raise ValueError('Completion and fresh flags must be explicit booleans')
    if not fresh:
        raise ValueError('Resume or non-fresh entries are outside this layout')
    identities = _cohort(cohort)
    if type(markers) not in (list, tuple):
        raise ValueError('An explicit ordered marker list or tuple is required')
    expected = _expected(identities)
    if len(markers) > len(expected):
        raise ValueError('Extra marker outside the fixed fresh48 layout')
    seen, observed, pair_count, rank_count = set(), [], 0, 0
    for marker, target in zip(markers, expected):
        if type(marker) is not dict or set(marker) != MARKER_FIELDS:
            raise ValueError('Exact boundary marker fields required')
        boundary_id = marker['boundary_id']
        if (type(boundary_id) is not str or not boundary_id
                or boundary_id != boundary_id.strip() or boundary_id in seen):
            raise ValueError('Nonempty unique boundary ids required')
        for field, value in target.items():
            actual = marker[field]
            if type(actual) is not type(value) or actual != value:
                raise ValueError(f'Marker {field} differs from fixed prefix')
        seen.add(boundary_id)
        observed.append(boundary_id)
        if target['point'] in ('ranking_start', *RANK_PHASES):
            rank_count += 1
        else:
            pair_count += 1
    if completed and len(markers) != len(expected):
        raise ValueError('Completed entry requires all 725 original call points')
    return dict(
        status='complete' if completed else 'incomplete', completed=completed,
        expected_marker_count=len(expected), observed_marker_count=len(markers),
        pair_marker_count=pair_count, rank_marker_count=rank_count,
        completed_query_count=sum(row['point'] == 'query_end' for row in markers),
        observed_boundary_ids=observed,
        expected_next=None if len(markers) == len(expected) else dict(expected[len(markers)]),
        cohort=identities, spans=_plan(markers) if completed else [])
