"""Read causal visitor-item histories for the frozen August browsing roster."""

from hashlib import sha256
from itertools import groupby

from scripts.c1_demo_model import QUERIES
from scripts.evaluate_cart_recommendations import WINDOWS, digest_row
from scripts.score_recommendation_acceptance import SESSION_GAP_MS, require
from scripts.verify_recommendation_acceptance_august import archive_rows


EVENTS = ("view", "addtocart", "transaction")
WARMUP_START = 1430611200000  # 2015-05-03 00:00 UTC, context only.


def visitor_events(db, visitor, last_query_ms):
    """Read only this visitor's eligible history, through their final query."""
    train_start, august_start = WINDOWS["train"]
    require(august_start <= last_query_ms < WINDOWS["validation"][1], "Expected an August query")
    return db.execute("""
        SELECT t, e, i FROM qualified
        WHERE v = ? AND t >= ? AND t <= ? AND e IN ('view', 'addtocart', 'transaction')
          AND ((role = 'warmup' AND t < ?)
                OR (role = 'train' AND t >= ? AND t < ?)
                OR (role = 'validation' AND t >= ?))
        ORDER BY t
    """, (visitor, WARMUP_START, last_query_ms, train_start, train_start, august_start, august_start))


def visitor_history_rows(records, events):
    """Yield each query plus newly observed item IDs for each event type."""
    events = iter(events)
    event = next(events, None)
    seen = {kind: set() for kind in EVENTS}
    pending = {kind: set() for kind in EVENTS}
    session_views = set()
    last_query = last_view = session_start = None
    for record in records:
        _, session, when = record["key"]
        require(last_query is None or last_query < when, "Visitor query times must strictly increase")
        last_query = when

        # Actions tied with the preceding query are now in the past.
        additions = pending
        pending = {kind: set() for kind in EVENTS}
        while event is not None and event[0] <= when:
            stamp, kind, item = event
            if kind == "view":
                if last_view is None or stamp - last_view > SESSION_GAP_MS:
                    session_start = stamp
                    session_views.clear()
                session_views.add(item)
                last_view = stamp
            if stamp == when and kind != "view":
                pending[kind].add(item)
            else:
                additions[kind].add(item)
            event = next(events, None)

        require(last_view == when and session_start == session and session_views == set(record["history"]),
                "Qualified view events do not reconstruct the frozen query's session prefix")
        for kind in EVENTS:
            additions[kind].difference_update(seen[kind])
            seen[kind].update(additions[kind])
        yield record, {kind: tuple(sorted(items)) for kind, items in additions.items()}


def august_history_rows(db, frozen):
    """Join the bound C1 August query archive to each visitor's event prefix."""
    inputs = {entry["path"]: entry for entry in frozen["private_inputs"]}
    roster = frozen["development_roster"]
    rows = archive_rows(QUERIES, inputs)
    digest = sha256()
    count = 0
    visited = set()
    start, end = WINDOWS["validation"]
    for visitor, group in groupby(rows, key=lambda row: row["key"][0]):
        require(visitor not in visited, "August archive repeats a visitor outside its group")
        visited.add(visitor)
        records = list(group)
        require(all(start <= record["key"][2] < end for record in records), "Query outside August development")
        events = visitor_events(db, visitor, records[-1]["key"][2])
        for record, additions in visitor_history_rows(records, events):
            digest_row(digest, record["key"])
            count += 1
            yield record, additions
    require(count == roster["scorable_queries"] and digest.hexdigest() == roster["ordered_query_keys_sha256"],
            "August query count or ordered membership differs from the frozen roster")
