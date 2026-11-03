"""Independent V4 exact ranking against the sealed V2 SQL membership schema.

Only the frozen independent V2 catalog, index builder and identifier/JSON
formatting are shared. No primary ranker or V2.predict is called. Logical work
and optional per-stage wall time are separate from the scientific prediction.
"""
from collections import Counter
from fractions import Fraction
from functools import cmp_to_key
import hashlib
from heapq import nsmallest
from math import gcd, lcm
from time import perf_counter

from scripts.retailrocket_session_knn_sql_v2 import (
    FrozenCatalog, prepare_catalog, build_index, _dump, _item)


MAX_VOTE_SCALE_BITS = 4096


def _greater_ratio_first(left, right):
    # Python integers do not overflow. Equal reduced ratios share a group.
    difference = right[0] * left[1] - left[0] * right[1]
    return (difference > 0) - (difference < 0)


def _common_scale(denominators):
    """Return an exact scale, or choose ordinary Fraction addition at the cap."""
    scale = 1
    for denominator in denominators:
        scale = lcm(scale, denominator)
        if scale.bit_length() > MAX_VOTE_SCALE_BITS:
            return None
    return scale


def predict(db, support, fit_id, counts, catalog, time, history, current,
            watch=lambda: None, *, workload=None, timings=None):
    """Return the complete frozen V1 prediction dict using exact SQL overlaps.

    The signature follows V1, with a SQLite connection replacing ``sessions``.
    The optional output dict ``workload`` is updated as work is performed, and
    is deliberately kept outside the scientific prediction schema.
    """
    work = {} if workload is None else workload
    work.update(history_rows_inserted=0, sql_overlap_groups_returned=0,
                sql_overlap_membership_matches=0, neighbor_pool_rows_hashed=0,
                sql_selected_rows_inserted=0, sql_vote_membership_rows_returned=0,
                fraction_vote_additions=0, fallback_catalog_rows_examined=0,
                catalog_snapshot_rows_prepared=0, causal_catalog_candidates=0,
                positive_causal_candidates=0)
    work.update(exact_vote_additions=0, integer_vote_additions=0, vote_scale_bits=0,
                fraction_fallback=False, distinct_neighbor_similarities=0)
    phase_start = perf_counter() if timings is not None else 0
    def mark(name):
        nonlocal phase_start
        if timings is not None:
            now = perf_counter()
            timings[name] = now - phase_start
            phase_start = now
    watch()
    if isinstance(catalog, FrozenCatalog):
        if counts is not catalog.counts:
            raise ValueError('FrozenCatalog requires its own immutable counts snapshot')
        prepared = catalog
    else:
        prepared = prepare_catalog(catalog, counts, watch)
        work['catalog_snapshot_rows_prepared'] = len(prepared.first)
    h = set(history)
    # TEMP state belongs to this connection.  The sealed model database may
    # have been reopened mode=ro; prediction never writes its main schema.
    db.execute('CREATE TEMP TABLE IF NOT EXISTS k1_v4_history '
               '(i TEXT PRIMARY KEY) WITHOUT ROWID')
    db.execute('CREATE TEMP TABLE IF NOT EXISTS k1_v4_selected '
               '(v TEXT NOT NULL,s INTEGER NOT NULL,r INTEGER NOT NULL UNIQUE,'
               'PRIMARY KEY(v,s)) WITHOUT ROWID')
    db.execute('DELETE FROM temp.k1_v4_history')
    db.execute('DELETE FROM temp.k1_v4_selected')
    for item in sorted(h, key=int):
        watch()
        _item(item)
        db.execute('INSERT INTO temp.k1_v4_history VALUES(?)', (item,))
        work['history_rows_inserted'] += 1

    # CROSS JOIN fixes the history/posting loop order.  No zero-overlap session
    # is a result row, and COUNT(*) is the complete set intersection size.
    mark('history_and_temp_setup')
    overlaps = db.execute(
        'SELECT membership.v,membership.s,COUNT(*),sizes.n '
        'FROM temp.k1_v4_history AS query '
        'CROSS JOIN main.m AS membership INDEXED BY k1_v2_posting '
        'ON membership.i=query.i '
        'LEFT JOIN main.k1_v2_sizes AS sizes '
        'ON sizes.v=membership.v AND sizes.s=membership.s '
        'GROUP BY membership.v,membership.s')
    pool = []
    visits = excluded = 0
    for visitor, session, intersection, size in overlaps:
        watch()
        work['sql_overlap_groups_returned'] += 1
        visits += intersection
        work['sql_overlap_membership_matches'] += intersection
        key = (visitor, session)
        if type(size) is not int or size <= 0:
            raise ValueError('Missing or invalid independent session-size row')
        if key == current:
            excluded += 1
            continue
        union = len(h) + size - intersection
        if not 0 < intersection <= min(len(h), size) or union <= 0:
            raise ValueError('Invalid or stale independent session-size index')
        pool.append((key, intersection, union, size))
    watch()

    mark('sql_positive_overlaps')
    # Sorting once by numeric source identity gives both the frozen digest order
    # and the tie order within each exact Jaccard group, even for unbounded IDs.
    pool.sort(key=lambda row: (int(row[0][0]), row[0][1]))
    digest = hashlib.sha256()
    for key, intersection, union, _ in pool:
        watch()
        digest.update((_dump([list(key), intersection, union]) + '\n').encode())
        work['neighbor_pool_rows_hashed'] += 1
    mark('neighbor_pool_sha')

    groups = {}
    for row in pool:
        watch()
        intersection, union = row[1:3]
        divisor = gcd(intersection, union)
        ratio = (intersection // divisor, union // divisor)
        if ratio not in groups:
            groups[ratio] = []
        groups[ratio].append(row)
    work['distinct_neighbor_similarities'] = len(groups)
    # Order distinct exact rational values. A group retains every row in
    # numeric identity order, including every excluded member at the cutoff.
    selected = []
    boundary = None
    total_ties = removed = 0
    for ratio in sorted(groups, key=cmp_to_key(_greater_ratio_first)):
        watch()
        members = groups[ratio]
        take = min(500 - len(selected), len(members))
        similarity = Fraction(*ratio)
        for key, intersection, union, size in members[:take]:
            selected.append((key, intersection, union, similarity, size))
        if len(selected) == 500:
            boundary = similarity
            total_ties = len(members)
            removed = total_ties - take
            break
    mark('exact_neighbor_selection')
    # Every selected Fraction has a positive denominator. Multiplication by
    # a common positive integer preserves exact sums, zeros and ordering.
    scale = _common_scale(row[3].denominator for row in selected)
    work['fraction_fallback'] = scale is None
    work['vote_scale_bits'] = 0 if scale is None else scale.bit_length()
    weights = [row[3] for row in selected] if scale is None else [
        row[3].numerator * (scale // row[3].denominator) for row in selected]
    addition_counter = 'fraction_vote_additions' if scale is None else 'integer_vote_additions'
    for rank, (key, _, _, _, _) in enumerate(selected):
        watch()
        db.execute('INSERT INTO temp.k1_v4_selected VALUES(?,?,?)', (*key, rank))
        work['sql_selected_rows_inserted'] += 1
    scores = {}
    membership_counts = Counter()
    votes = db.execute(
        'SELECT chosen.r,membership.i FROM temp.k1_v4_selected AS chosen '
        'CROSS JOIN main.m AS membership '
        'ON membership.v=chosen.v AND membership.s=chosen.s')
    for rank, item in votes:
        watch()
        work['sql_vote_membership_rows_returned'] += 1
        membership_counts[rank] += 1
        first = prepared.first.get(item)
        if first is not None and first < time:
            scores[item] = scores.get(item, 0) + weights[rank]
            work['exact_vote_additions'] += 1
            work[addition_counter] += 1
    for rank, row in enumerate(selected):
        watch()
        if membership_counts[rank] != row[4]:
            raise ValueError('Selected membership rows differ from independent sizes')
    mark('sql_selected_votes_and_accumulation')
    candidate_count = prepared.size(time)
    positive = len(scores)
    work['causal_catalog_candidates'] = candidate_count
    work['positive_causal_candidates'] = positive
    order = nsmallest(10, scores, key=lambda item: (-scores[item], -prepared.counts.get(item, 0), int(item)))
    wanted = min(10, candidate_count)
    if len(order) < wanted:
        for item in prepared.fallback:
            watch()
            work['fallback_catalog_rows_examined'] += 1
            if prepared.first[item] < time and item not in scores:
                order.append(item)
                if len(order) == wanted:
                    break
    watch()
    if len(order) != wanted:
        raise ValueError('Incomplete causal catalog zero complement')
    mark('top_ten_and_zero_fill')
    supported = sum(item in support for item in h)
    reason = None
    if not positive:
        reason = ('no_supported_seed' if not supported else
                  'only_self_session_overlap' if not pool and excluded else
                  'no_eligible_positive_neighbor' if not pool else
                  'no_positive_causal_vote')
    if scale is None:
        top_scores = [scores.get(item, Fraction(0)) for item in order]
    else:
        top_scores = [Fraction(scores.get(item, 0), scale) for item in order]
    result = {'fit_id': fit_id, 'ids': order,
            'scores': [[score.numerator, score.denominator] for score in top_scores],
            'p0_counts': [prepared.counts.get(item, 0) for item in order],
            'candidate_count': candidate_count, 'history_size': len(h),
            'supported_seeds': supported, 'unknown_seeds': len(h) - supported,
            'raw_posting_visits': visits, 'current_session_excluded': excluded,
            'eligible_neighbors': len(pool), 'neighbor_pool_sha256': digest.hexdigest(),
            'selected_neighbors': [
                {'key': list(key), 'intersection': intersection, 'union': union,
                 'similarity': [similarity.numerator, similarity.denominator]}
                for key, intersection, union, similarity, _ in selected],
            'selected_neighbor_count': len(selected),
            'boundary_similarity': None if boundary is None else
                [boundary.numerator, boundary.denominator],
            'boundary_ties_total': total_ties, 'boundary_ties_excluded': removed,
            'vote_memberships': work['sql_vote_membership_rows_returned'],
            'positive_candidates': positive,
            'zero_fill_slots': sum(score == 0 for score in top_scores),
            'fallback_reason': reason}
    mark('prediction_output')
    return result
