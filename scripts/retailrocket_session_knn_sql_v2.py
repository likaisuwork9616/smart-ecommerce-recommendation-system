"""Independent exact SQL K1 predictions with the frozen V1 output schema.

Only stdlib code is used here.  ``m(v,s,i)`` is the train-only membership
relation independently reconstructed by the caller; ``h`` keeps its V1 schema
and is not modified.  SQL retrieves every positive-overlap session, rather
than decoding a production model or enumerating every zero-overlap session.

``workload`` contains logical rows inserted/returned at SQL boundaries and
Python arithmetic performed.  These are not SQLite VM steps, physical scans,
V1 full-session visits, or scientific acceptance counts.
"""
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import re
from types import MappingProxyType


_ITEM = re.compile(r'(?:0|[1-9][0-9]*)', re.ASCII)


def _item(value):
    if type(value) is not str or _ITEM.fullmatch(value) is None:
        raise ValueError('Expected a canonical nonnegative decimal identifier')
    return value


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class FrozenCatalog:
    """A causal catalog and P0-count snapshot prepared once by this oracle.

    When passing this object to ``predict``, pass its ``counts`` member as the
    counts argument too.  This makes the fast path explicitly immutable;
    mutable caller dictionaries are never implicitly cached.
    """
    first: object
    counts: object
    first_times: tuple
    fallback: tuple

    def size(self, query_time):
        return bisect_left(self.first_times, query_time)


def prepare_catalog(catalog, counts, watch=lambda: None):
    """Copy and freeze the complete catalog and P0 counts without truncation."""
    first = {}
    for item, timestamp in catalog.items():
        watch()
        _item(item)
        if type(timestamp) is not int:
            raise ValueError('Catalog first-view clocks must be integers')
        first[item] = timestamp
    p0 = {}
    for item, count in counts.items():
        watch()
        _item(item)
        if type(count) is not int or count < 0:
            raise ValueError('P0 counts must be nonnegative integers')
        p0[item] = count
    times = tuple(sorted(first.values()))
    fallback = tuple(sorted(first, key=lambda item: (-p0.get(item, 0), int(item))))
    watch()
    return FrozenCatalog(MappingProxyType(first), MappingProxyType(p0), times, fallback)


def build_index(db, watch=lambda: None):
    """Build independent session sizes and posting access paths from V1 ``m``.

    The derived tables are created once and intentionally reject re-entry.
    This function does not commit or alter the source ``m``/``h`` relations.
    The caller owns transactions and any SQLite VM progress handler.
    """
    watch()
    db.execute('CREATE INDEX k1_v2_posting ON m(i,v,s)')
    db.execute('CREATE TABLE k1_v2_sizes '
               '(v TEXT NOT NULL,s INTEGER NOT NULL,n INTEGER NOT NULL CHECK(n>0),'
               'PRIMARY KEY(v,s)) WITHOUT ROWID')
    db.execute('INSERT INTO k1_v2_sizes SELECT v,s,COUNT(*) FROM m GROUP BY v,s')
    watch()
    sessions, memberships = db.execute(
        'SELECT COUNT(*),COALESCE(SUM(n),0) FROM k1_v2_sizes').fetchone()
    watch()
    return {'train_sessions': sessions, 'session_item_memberships': memberships}


def predict(db, support, fit_id, counts, catalog, time, history, current,
            watch=lambda: None, *, workload=None):
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
    db.execute('CREATE TEMP TABLE IF NOT EXISTS k1_v2_history '
               '(i TEXT PRIMARY KEY) WITHOUT ROWID')
    db.execute('CREATE TEMP TABLE IF NOT EXISTS k1_v2_selected '
               '(v TEXT NOT NULL,s INTEGER NOT NULL,r INTEGER NOT NULL UNIQUE,'
               'PRIMARY KEY(v,s)) WITHOUT ROWID')
    db.execute('DELETE FROM temp.k1_v2_history')
    db.execute('DELETE FROM temp.k1_v2_selected')
    for item in sorted(h, key=int):
        watch()
        _item(item)
        db.execute('INSERT INTO temp.k1_v2_history VALUES(?)', (item,))
        work['history_rows_inserted'] += 1

    # CROSS JOIN fixes the history/posting loop order.  No zero-overlap session
    # is a result row, and COUNT(*) is the complete set intersection size.
    overlaps = db.execute(
        'SELECT membership.v,membership.s,COUNT(*),sizes.n '
        'FROM temp.k1_v2_history AS query '
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
        pool.append((key, intersection, union, Fraction(intersection, union), size))
    watch()

    digest = hashlib.sha256()
    for key, intersection, union, _, _ in sorted(
            pool, key=lambda row: (int(row[0][0]), row[0][1])):
        watch()
        digest.update((_dump([list(key), intersection, union]) + '\n').encode())
        work['neighbor_pool_rows_hashed'] += 1
    pool.sort(key=lambda row: (-row[3], int(row[0][0]), row[0][1]))
    watch()
    selected = pool[:500]
    boundary = selected[-1][3] if len(selected) == 500 else None
    total_ties = removed = 0
    for position, row in enumerate(pool):
        watch()
        if boundary is not None and row[3] == boundary:
            total_ties += 1
            removed += position >= 500

    for rank, (key, _, _, _, _) in enumerate(selected):
        watch()
        db.execute('INSERT INTO temp.k1_v2_selected VALUES(?,?,?)', (*key, rank))
        work['sql_selected_rows_inserted'] += 1
    scores = {}
    membership_counts = Counter()
    votes = db.execute(
        'SELECT chosen.r,membership.i FROM temp.k1_v2_selected AS chosen '
        'CROSS JOIN main.m AS membership '
        'ON membership.v=chosen.v AND membership.s=chosen.s')
    for rank, item in votes:
        watch()
        work['sql_vote_membership_rows_returned'] += 1
        membership_counts[rank] += 1
        first = prepared.first.get(item)
        if first is not None and first < time:
            scores[item] = scores.get(item, Fraction(0)) + selected[rank][3]
            work['fraction_vote_additions'] += 1
    for rank, row in enumerate(selected):
        watch()
        if membership_counts[rank] != row[4]:
            raise ValueError('Selected membership rows differ from independent sizes')
    candidate_count = prepared.size(time)
    positive = len(scores)
    work['causal_catalog_candidates'] = candidate_count
    work['positive_causal_candidates'] = positive
    order = sorted(scores, key=lambda item: (-scores[item], -prepared.counts.get(item, 0),
                                             int(item)))[:10]
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
    supported = sum(item in support for item in h)
    reason = None
    if not positive:
        reason = ('no_supported_seed' if not supported else
                  'only_self_session_overlap' if not pool and excluded else
                  'no_eligible_positive_neighbor' if not pool else
                  'no_positive_causal_vote')
    top_scores = [scores.get(item, Fraction(0)) for item in order]
    return {'fit_id': fit_id, 'ids': order,
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
