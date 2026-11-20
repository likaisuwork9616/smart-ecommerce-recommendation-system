"""Read first-rank counts from the accepted August browsing rankings."""
import hashlib
import json
from pathlib import Path

from scripts.c1_demo_replay import K1_QUERIES, K1_REPORT, RECENCY_REPORT


ROOT = Path(__file__).resolve().parents[1]
AUGUST = (1438387200000, 1441065600000)
METHODS = ("P0", "C1", "D1", "K1")


def readback(root=ROOT):
    reference = json.loads((root / K1_REPORT).read_bytes())
    recency = json.loads((root / RECENCY_REPORT).read_bytes())
    scope = reference["scope"]
    if tuple(scope["evaluation_utc_ms"]) != AUGUST or scope["reserved_test_ranked_queries"] != 0:
        raise ValueError("The reference is not the accepted August-only readback")

    hits = dict.fromkeys(METHODS, 0)
    rank_one = dict.fromkeys(METHODS, 0)
    roster = hashlib.sha256()
    queries = 0
    with (root / K1_QUERIES).open("rb") as rows:
        source_hash = hashlib.file_digest(rows, "sha256").hexdigest()
        if source_hash != reference["cohort"]["queries_sha256"]:
            raise ValueError("August rankings do not match the accepted readback")
        rows.seek(0)
        for line in rows:
            row = json.loads(line)
            key = row["key"]
            if not AUGUST[0] <= key[2] < AUGUST[1]:
                raise ValueError("A query is outside August")
            roster.update((json.dumps(key, separators=(",", ":")) + "\n").encode("utf-8"))
            targets = set(row["targets"])
            for method in METHODS:
                items = row["predictions"][method]["ids"]
                if len(items) != 10 or len(set(items)) != 10:
                    raise ValueError("A frozen ranking does not contain ten distinct items")
                first = next((rank for rank, item in enumerate(items, 1) if item in targets), None)
                if first != row["terms"][method]["first_hit_rank"]:
                    raise ValueError("First-hit rank disagrees with the archived terms")
                hits[method] += first is not None
                rank_one[method] += first == 1
            queries += 1

    if (queries != reference["cohort"]["queries"] or queries != recency["counts"]["queries"]
            or roster.hexdigest() != recency["roster_sha256"]
            or any(hits[method] != reference["results"]["main"]["arms"][method]["hit_queries"]
                   for method in METHODS)):
        raise ValueError("The August query roster or total hits disagree with the published aggregates")

    # The accepted recency rule only replaces rank 10.
    rank_one["C1+recency"] = rank_one["C1"]
    return {
        "role": "2015-08 exposed development validation",
        "reference_reports": [K1_REPORT, RECENCY_REPORT],
        "accepted_august_rankings_sha256": source_hash,
        "accepted_august_roster_sha256": roster.hexdigest(),
        "queries": queries,
        "first_rank_matches": rank_one,
        "queries_with_ten_distinct_items_per_method": queries,
        "recency_rank_one": "Equal to C1 because the published rule changes only rank 10",
        "reserved_test_ranked_queries": 0,
    }


if __name__ == "__main__":
    print(json.dumps(readback(), indent=2, allow_nan=False))
