"""Evaluate the fixed homepage browse top ten on August visitors' first observed views."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
from itertools import groupby
import json
from operator import itemgetter
import sqlite3

from scripts.c1_demo_model import POPULARITY, RELEASE, read_counts
from scripts.evaluate_cart_recommendations import CONTRACT, DB, ROOT, TOP_K, WINDOWS, digest_row
from scripts.export_home_popularity import OUTPUT as HOMEPAGE, export as rebuild_homepage, ranked_counts
from scripts.score_recommendation_acceptance import window_ms


OUTPUT = ROOT / "reports/mainline/recommendation_august_home_browse_20261124.json"
HISTORY = ("seen_in_train", "seen_in_warmup_only", "first_observed_in_august")
FIRST_ACTIVITY = ("first_activity_includes_view", "activity_precedes_first_view")


def visitor_rows(db, windows):
    # Resolve ties by collecting every view at the earliest view time; event row
    # order cannot tell us which item the visitor saw first in a tied timestamp.
    return db.execute("""
        WITH august AS (
            SELECT v, MIN(t) AS first_activity, MIN(CASE WHEN e='view' THEN t END) AS first_view
            FROM qualified
            WHERE role='validation' AND t>=? AND t<?
            GROUP BY v
        ), cohort AS MATERIALIZED (
            SELECT august.*,
                CASE WHEN EXISTS (
                    SELECT 1 FROM qualified p WHERE p.v=august.v AND p.role='train' AND p.t>=? AND p.t<?
                ) THEN 'seen_in_train'
                WHEN EXISTS (
                    SELECT 1 FROM qualified p WHERE p.v=august.v AND p.role='warmup' AND p.t>=? AND p.t<?
                ) THEN 'seen_in_warmup_only'
                ELSE 'first_observed_in_august' END AS history
            FROM august
        )
        SELECT c.v, c.history, c.first_activity, c.first_view, q.i FROM cohort c
        LEFT JOIN qualified q ON c.history='first_observed_in_august' AND q.v=c.v
            AND q.t=c.first_view AND q.e='view' AND q.role='validation'
        ORDER BY c.v
    """, (*windows["validation"], *windows["train"], *windows["warmup"]))


def grouped_visitors(rows):
    """Yield one row per August visitor, collecting first-view items for new visitors."""
    for visitor, events in groupby(rows, key=itemgetter(0)):
        _, history, activity_at, view_at, first_item = next(events)
        targets = set()
        if history == "first_observed_in_august" and view_at is not None:
            if first_item is None:
                raise ValueError("First view has no matching qualified item")
            targets.add(first_item)
            targets.update(row[4] for row in events)
        yield visitor, history, activity_at, view_at, targets


def score(rows, ranking):
    rank_of = {item: rank for rank, (item, _) in enumerate(ranking, 1)}
    if len(ranking) != TOP_K or len(rank_of) != TOP_K:
        raise ValueError("The homepage must have ten distinct browse items")
    by_history = {group: {"active": 0, "with_view": 0, "without_view": 0} for group in HISTORY}
    by_entry = {group: {"visitors": 0, "hits_at_10": 0} for group in FIRST_ACTIVITY}
    ranks = Counter()
    multi_item = multi_item_hits = multiple_hits = 0
    total_target_items = max_target_items = 0
    roster = hashlib.sha256()
    for visitor, history, activity_at, view_at, targets in grouped_visitors(rows):
        counts = by_history[history]
        counts["active"] += 1
        counts["without_view" if view_at is None else "with_view"] += 1
        if not targets:
            continue
        total_target_items += len(targets)
        max_target_items = max(max_target_items, len(targets))
        digest_row(roster, [visitor, view_at, sorted(targets, key=int)])
        hits = [rank_of[item] for item in targets if item in rank_of]
        entry_group = "first_activity_includes_view" if activity_at == view_at else "activity_precedes_first_view"
        entry = by_entry[entry_group]
        entry["visitors"] += 1
        entry["hits_at_10"] += bool(hits)
        multi_item += len(targets) > 1
        multi_item_hits += len(targets) > 1 and bool(hits)
        multiple_hits += len(hits) > 1
        if hits:
            ranks[min(hits)] += 1

    scored = by_history["first_observed_in_august"]["with_view"]
    hits_at = {}
    for k in (1, 5, TOP_K):
        hits = sum(ranks[rank] for rank in range(1, k + 1))
        hits_at[str(k)] = {"hits": hits, "rate": hits / scored if scored else None}
    return {
        "august_active_visitors": sum(counts["active"] for counts in by_history.values()),
        "by_observed_history": by_history,
        "scored_visitors": scored,
        "scored_visitor_first_view_targets_sha256": roster.hexdigest(),
        "by_first_august_activity": by_entry,
        "first_view_timestamp": {"total_distinct_items_across_visitors": total_target_items,
                                 "max_distinct_items": max_target_items, "multiple_distinct_items": multi_item,
                                 "multiple_distinct_items_with_hit": multi_item_hits,
                                 "multiple_top_ten_items": multiple_hits},
        "hit_at_k": hits_at,
        "misses_at_10": scored - sum(ranks.values()),
        "first_hit_by_rank": [{"rank": r, "public_item": alias, "visitors": ranks[r]}
                              for r, (_, alias) in enumerate(ranking, 1)],
    }


def load_study_inputs():
    public = json.loads(HOMEPAGE.read_bytes())
    if rebuild_homepage() != public:
        raise ValueError("Homepage lists differ from the verified training release")
    # The exporter binds original identifiers to public aliases in this exact order.
    browse = ranked_counts(read_counts(ROOT / POPULARITY, "count"))
    ranking = [(item, public_row["item"]) for (item, _), public_row in
               zip(browse, public["rankings"]["browse"], strict=True)]
    time_roles = json.loads((ROOT / CONTRACT).read_bytes())["time_roles"]
    scope = {role: time_roles[role] for role in ("warmup", "train", "validation")}
    windows = {role: window_ms(bounds) for role, bounds in scope.items()}
    if (windows["train"] != WINDOWS["train"] or windows["validation"] != WINDOWS["validation"]
            or windows["warmup"] != (1430611200000, windows["train"][0])):
        raise ValueError("The frozen training, warm-up or August window has changed")
    return ranking, scope, windows


def study():
    ranking, scope, windows = load_study_inputs()
    release = json.loads((ROOT / RELEASE).read_bytes())
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        results = score(visitor_rows(db, windows), ranking)
    return {
        "study": "Fixed homepage browse ranking against August new visitors' first viewed items",
        "role": "2015-08 development backtest", "utc_windows_start_inclusive_end_exclusive": scope,
        "source_receipt": RELEASE, "contract": CONTRACT,
        "frozen_sources_sha256": {
            path: next(row["sha256"] for row in release[section] if row["path"] == path)
            for path, section in ((POPULARITY, "sources"), (DB, "external_dependencies"))
        },
        "homepage_snapshot": HOMEPAGE.relative_to(ROOT).as_posix(),
        "rules": {
            "roster": "One observation per August-active visitor with an August view and no qualified event of any kind in warmup or train. The train group includes visitors seen in both earlier roles.",
            "ranking": "Same frozen top ten for each visitor, by training view count descending, numeric item ID ascending for ties.",
            "target": "All distinct items viewed at the visitor's earliest August view timestamp. A hit is any overlap, counted once at the best matching rank.",
            "first_activity": "A view tied with a cart or purchase at the earliest activity time belongs to first_activity_includes_view.",
        },
        **results,
        "limits": "First observed within the dataset. No homepage exposures or referral paths are recorded; this measures offline first-view overlap.",
        "new_model_fits": 0, "formal_scored_queries": 0, "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare against the published report")
    args = parser.parse_args()
    result = study()
    if args.check:
        if result != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed August results differ from the report")
    else:
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8", newline="\n")
    print(f"{result['hit_at_k']['10']['hits']:,} top-ten hits / {result['scored_visitors']:,} visitors")


if __name__ == "__main__":
    main()
