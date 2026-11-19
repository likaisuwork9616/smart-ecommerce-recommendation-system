"""Describe training-window support for an 'also added to cart' item-to-item list."""
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from itertools import combinations, groupby
from math import comb
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB = "shop-mysql-runtime/retailrocket_dataset_v1/builder.sqlite"
RECEIPT = "reports/stage10/retailrocket_c1_p0_v1_research_release.json"
CONTRACT = "docs/contracts/retailrocket_recommendation_v1.json"
GAP_MS = 30 * 60 * 1000


def cart_sessions(events, event_items):
    """Consume a single visitor's time-ordered activity. Each set counts an item once."""
    start = last = None
    cart = set()
    for _, timestamp, event, item in events:
        if last is None or timestamp - last > GAP_MS:
            if last is not None:
                yield start, last, cart
            start = timestamp
            cart = set()
        event_items[event][item] += 1
        if event == "addtocart":
            cart.add(item)
        last = timestamp
    if last is not None:
        yield start, last, cart


def coverage(pair_counts, threshold, event_items):
    """Count items with enough distinct neighbors and the events involving those items."""
    degree = Counter()
    edges = 0
    for (a, b), count in pair_counts.items():
        if count >= threshold:
            edges += 1
            degree[a] += 1
            degree[b] += 1
    result = {"minimum_support": threshold, "unordered_pairs": edges}
    for required in (1, 10):
        seeds = {item for item, n in degree.items() if n >= required}
        result[f"at_least_{required}_neighbors"] = {
            "cart_items": len(seeds),
            "cart_events": sum(event_items["addtocart"][i] for i in seeds),
            "view_items": sum(i in event_items["view"] for i in seeds),
            "view_events": sum(event_items["view"][i] for i in seeds),
        }
    return result


def describe(rows, lo, hi):
    event_items = {"view": Counter(), "addtocart": Counter()}
    pair_sessions, pair_visitors = Counter(), Counter()
    session_sizes = Counter()
    visitors = cart_visitors = multi_cart_visitors = 0
    left_edge = right_edge = 0
    for _, events in groupby(rows, key=lambda row: row[0]):
        visitors += 1
        seen_cart = False
        seen_pairs = set()
        for start, end, cart in cart_sessions(events, event_items):
            session_sizes[len(cart)] += 1
            if cart:
                seen_cart = True
                left_edge += start - lo < GAP_MS
                right_edge += hi - end <= GAP_MS
            if len(cart) >= 2:
                for pair in combinations(sorted(cart), 2):
                    pair_sessions[pair] += 1
                    seen_pairs.add(pair)
        cart_visitors += seen_cart
        multi_cart_visitors += bool(seen_pairs)
        pair_visitors.update(seen_pairs)

    return {
        "events": {event: counts.total() for event, counts in event_items.items()},
        "distinct_items": {event: len(counts) for event, counts in event_items.items()},
        "anonymous_visitors": visitors,
        "cart_visitors": cart_visitors,
        "multi_item_cart_visitors": multi_cart_visitors,
        "sessions": session_sizes.total(),
        "cart_sessions": session_sizes.total() - session_sizes[0],
        "multi_item_cart_sessions": sum(n for size, n in session_sizes.items() if size >= 2),
        "maximum_distinct_cart_items_in_one_session": max(session_sizes, default=0),
        "maximum_pair_occurrences_in_one_session": comb(max(session_sizes, default=0), 2),
        "all_pair_occurrences": pair_sessions.total(),
        "cart_sessions_potentially_clipped_at_window_start": left_edge,
        "cart_sessions_potentially_clipped_at_window_end": right_edge,
        "pair_support_by_session": [coverage(pair_sessions, n, event_items) for n in (1, 2, 3, 5)],
        "pair_support_by_distinct_visitor": [coverage(pair_visitors, n, event_items) for n in (1, 2, 3, 5)],
    }


def audit(root=ROOT):
    receipt = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
    ref = next(row for row in receipt["external_dependencies"] if row["path"] == DB)
    path = root / DB
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if path.stat().st_size != ref["bytes"] or digest != ref["sha256"]:
        raise ValueError("Stage 8 database differs from the accepted source receipt")
    contract = json.loads((root / CONTRACT).read_text(encoding="utf-8"))
    window = contract["time_roles"]["train"]
    lo, hi = [int(datetime.fromisoformat(date).timestamp() * 1000) for date in window]
    sql = """
        SELECT v, t, e, i FROM qualified
        WHERE role = 'train' AND t >= ? AND t < ? AND e IN ('view', 'addtocart')
        ORDER BY v, t
    """
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        result = describe(db.execute(sql, (lo, hi)), lo, hi)
    return {
        "scope": "training-only support inventory; no validation, reserved-test or ranking scores",
        "source_database": {k: ref[k] for k in ("path", "bytes", "sha256")},
        "source_receipt": RECEIPT,
        "train_utc_start_inclusive_end_exclusive": window,
        "session_rule": "group each anonymous visitor's canonical views and add-to-cart events; split only at gaps over 30 minutes; clip to the training window",
        "pair_rule": "unordered distinct added items in the same inferred session; one vote per session or per anonymous visitor as labelled",
        "coverage_rule": "training distinct seed items and event occurrences with at least the indicated number of different co-add neighbors; no ranking or historical availability replay",
        "counts": result,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
