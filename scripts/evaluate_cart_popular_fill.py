"""Evaluate popular-cart fill on the accepted August next-add cohort."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from scripts.evaluate_cart_recommendations import ROOT, TOP_K, audit, digest_row

BASELINE = "reports/stage13/retailrocket_cart_next_add_201508.json"
ARMS = ("coadd", "popular", "empty_fallback", "popular_fill")
COVERAGE = ("empty", "short", "full")


def popular_fill(coadd, popular):
    """Preserve the co-add prefix and provenance for every emitted slot."""
    shared = set(coadd)
    remaining = TOP_K - len(coadd)
    prefix = [(item, "coadd") for item in coadd]
    filler = [(item, "popular") for item in popular if item not in shared]
    return prefix + filler[:remaining]


def first_hit(items, truth):
    return next((rank for rank, item in enumerate(items, 1) if item in truth), None)


def summarize(ranks):
    positions = Counter(rank for rank in ranks if rank is not None)
    hits = positions.total()
    count = len(ranks)
    return {
        "hit_queries": hits,
        "hit_rate_at_10": hits / count,
        "mrr_at_10": sum(positions[r] / r for r in range(1, TOP_K + 1)) / count,
        "first_hit_counts_rank_1_to_10": [positions[r] for r in range(1, TOP_K + 1)],
    }


def compare(old_ranks, new_ranks):
    changes = dict.fromkeys(("gain", "loss", "earlier", "same", "later", "both_miss"), 0)
    for old, new in zip(old_ranks, new_ranks, strict=True):
        if old is None:
            changes["both_miss" if new is None else "gain"] += 1
        elif new is None:
            changes["loss"] += 1
        elif new < old:
            changes["earlier"] += 1
        elif new > old:
            changes["later"] += 1
        else:
            changes["same"] += 1
    return changes


def verify_fill(rows, expected_digest):
    """Reconstruct all mixed ranks and source labels using SQL anti-join and rank."""
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript("""
            CREATE TABLE ranks (
                query INTEGER, arm INTEGER, position INTEGER, item TEXT,
                PRIMARY KEY (query, arm, item)
            );
        """)
        db.executemany(
            "INSERT INTO ranks VALUES (?, ?, ?, ?)",
            ((query, arm, pos, item)
             for query, (_, _, coadd, popular) in enumerate(rows, 1)
             for arm, items in enumerate((coadd, popular))
             for pos, item in enumerate(items, 1)),
        )
        recomputed = db.execute("""
            WITH retained AS (
                SELECT r.query, r.arm, r.position, r.item
                FROM ranks AS r
                WHERE r.arm = 0 OR NOT EXISTS (
                    SELECT 1 FROM ranks AS c
                    WHERE c.query = r.query AND c.arm = 0 AND c.item = r.item
                )
            ), numbered AS (
                SELECT query, item, arm,
                       ROW_NUMBER() OVER (PARTITION BY query ORDER BY arm, position) AS slot
                FROM retained
            )
            SELECT query, slot, item, CASE WHEN arm = 0 THEN 'coadd' ELSE 'popular' END
            FROM numbered WHERE slot <= ? ORDER BY query, slot
        """, (TOP_K,))
        digest = hashlib.sha256()
        for row in recomputed:
            digest_row(digest, row)
    if digest.hexdigest() != expected_digest:
        raise ValueError("SQL reconstruction disagrees with the mixed ranks or their source labels")


def evaluate(rows):
    ranks = {arm: [] for arm in ARMS}
    bands = {band: {"queries": 0, "hit_queries": dict.fromkeys(ARMS, 0)} for band in COVERAGE}
    slots = dict.fromkeys(("coadd", "popular"), 0)
    first_hit_sources = dict.fromkeys(slots, 0)
    mixed_digest = hashlib.sha256()

    for query, (seed, truth, coadd, popular) in enumerate(rows, 1):
        mixed = popular_fill(coadd, popular)
        items = [item for item, _ in mixed]
        if len(items) != TOP_K or len(set(items)) != TOP_K or seed in items:
            raise ValueError("A mixed list is not ten distinct items excluding the seed")
        for slot, (item, source) in enumerate(mixed, 1):
            slots[source] += 1
            digest_row(mixed_digest, (query, slot, item, source))

        lists = (coadd, popular, coadd or popular, items)
        band = "full" if len(coadd) == TOP_K else "short" if coadd else "empty"
        bands[band]["queries"] += 1
        for arm, ranking in zip(ARMS, lists, strict=True):
            rank = first_hit(ranking, truth)
            ranks[arm].append(rank)
            bands[band]["hit_queries"][arm] += rank is not None

        hit = ranks["popular_fill"][-1]
        if hit is not None:
            first_hit_sources[mixed[hit - 1][1]] += 1

    digest = mixed_digest.hexdigest()
    verify_fill(rows, digest)
    return {
        "queries": len(rows),
        "arms": {arm: summarize(ranks[arm]) for arm in ARMS},
        "by_original_coadd_list_size": bands,
        "popular_fill_vs": {arm: compare(ranks[arm], ranks["popular_fill"]) for arm in ARMS[:-1]},
        "popular_fill_slots_by_source": slots,
        "popular_fill_first_hits_by_source": first_hit_sources,
        "mixed_query_slot_item_and_source_sha256": digest,
        "independent_sql_verified_ranked_slots": sum(slots.values()),
    }


def study(root=ROOT):
    root = Path(root)
    baseline_bytes = (root / BASELINE).read_bytes()
    rows = []

    def capture(_timestamp, seed, targets, coadd, popular):
        rows.append((seed, frozenset(targets), coadd, popular))

    source = audit(root, observe_scorable=capture)
    if source != json.loads(baseline_bytes):
        raise ValueError("The recomputed baseline differs from the published August validation report")
    result = evaluate(rows)
    scored = source["scorable"]
    all_queries = source["all_cart_opportunities"]
    if (result["queries"] != scored["queries"]
            or scored["popular"]["full_ten"] != scored["queries"]
            or all_queries["popular"]["full_ten"] != all_queries["queries"]
            or any(result["arms"][arm]["hit_queries"] != scored[arm]["hit_queries"] for arm in ARMS[:2])):
        raise ValueError("The August query counts, baseline hits or full popular coverage disagree")
    return {
        "study": "Keep co-add order and fill remaining top-ten slots with frozen popular-cart candidates",
        "role": source["role"],
        "reserved_test": source["reserved_test"],
        "reserved_test_ranked_queries": source["reserved_test_ranked_queries"],
        "baseline_report": BASELINE,
        "baseline_report_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "windows_utc_start_inclusive_end_exclusive": source["windows_utc_start_inclusive_end_exclusive"],
        "rules": {
            "empty_fallback": "Use co-add unchanged when it is nonempty. Use the original popular top ten for an empty co-add list.",
            "popular_fill": "Keep every co-add item and its original rank. Append the first distinct items from the original popular top ten until there are ten items. The original lists already exclude the seed.",
            "mrr_at_10": "Average reciprocal rank of the first target in the top ten, with zero for a miss.",
            "paired_rank_changes": "Earlier, same and later count only queries with a hit in both compared lists.",
        },
        "all_cart_opportunities": {
            "queries": all_queries["queries"],
            "original_coadd_empty": all_queries["queries"] - all_queries["coadd"]["with_recommendations"],
            "original_coadd_short_nonempty": all_queries["coadd"]["with_recommendations"] - all_queries["coadd"]["full_ten"],
            "original_coadd_full_ten": all_queries["coadd"]["full_ten"],
            # A full popular list leaves at least 10 minus the co-add length even after excluding overlap.
            "popular_fill_full_ten": all_queries["queries"],
        },
        "scorable": result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the verified JSON to this path. Defaults to stdout.")
    args = parser.parse_args()
    encoded = json.dumps(study(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.report is None:
        print(encoded, end="")
        return
    output = NamedTemporaryFile(dir=args.report.parent, delete=False)
    temporary_path = Path(output.name)
    try:
        with output:
            output.write(encoded.encode("utf-8"))
        temporary_path.replace(args.report)
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
