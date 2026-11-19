"""Compare the accepted C1 list with one reserved recency slot on August validation."""
import hashlib
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from scripts.c1_demo_model import EDGES, QUERIES, RELEASE
from scripts.retailrocket_popularity import Catalog, K, Sum, metric_terms


ROOT = Path(__file__).resolve().parents[1]
AUGUST_START = 1438387200000
SEPTEMBER_START = 1441065600000
VALIDATION = "reports/stage10/retailrocket_cooccurrence_v1_validation.json"


def history_catalog(db):
    # The accepted history table contains warm-up, train and validation views.
    first = {}
    for timestamp, items in db.execute(
        "SELECT t, items FROM history WHERE t < ?", (SEPTEMBER_START,)
    ):
        for item in json.loads(items):
            if item not in first or timestamp < first[item]:
                first[item] = timestamp
    return Catalog(first.items())


def most_recent(db, catalog, visitor, session, when):
    baskets = db.execute(
        "SELECT t, items FROM history WHERE v = ? AND s = ? AND t <= ? ORDER BY t DESC",
        (visitor, session, when),
    )
    current = baskets.fetchone()
    if current is None or current[0] != when:
        raise ValueError("Missing query basket in the accepted session history")
    basket = current
    while basket is not None:
        timestamp, items = basket
        eligible = [item for item in json.loads(items) if catalog.contains(item, when)]
        if eligible:
            return min(eligible, key=int), timestamp
        basket = baskets.fetchone()
    return None, None


def reserve_slot(ranked, recent):
    if recent is None or recent in ranked:
        return ranked
    return ranked[:K - 1] + [recent]


def evaluate(root):
    release = json.loads((root / RELEASE).read_text(encoding="utf-8"))
    sources = {entry["path"]: entry for entry in release["sources"]}
    digests = {}
    for name in (EDGES, QUERIES):
        path = root / name
        with path.open("rb") as stream:
            digests[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        if digests[name] != sources[name]["sha256"] or path.stat().st_size != sources[name]["bytes"]:
            raise ValueError(f"Source differs from its Stage 10 release receipt: {name}")

    original = json.loads((root / VALIDATION).read_text(encoding="utf-8"))["validation"]
    totals = Counter()
    changes = Counter()
    measures = ("ndcg", "mrr", "hit_rate")
    sums = {arm: {m: Sum() for m in measures} for arm in ("c1", "recency")}
    roster = hashlib.sha256()
    uri = (root / EDGES).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db, (root / QUERIES).open("rb") as stream:
        catalog = history_catalog(db)
        for line in stream:
            row = json.loads(line)
            visitor, session, when = row["key"]
            if not AUGUST_START <= when < SEPTEMBER_START or catalog.size(when) != row["candidate_count"]:
                raise ValueError("Unexpected validation clock or causal catalog size")
            roster.update((json.dumps(row["key"], separators=(",", ":")) + "\n").encode("utf-8"))
            recent, timestamp = most_recent(db, catalog, visitor, session, when)
            ranked = row["predictions"]["C1"]["ids"]
            if len(ranked) != K or (recent is not None and recent not in row["history"]):
                raise ValueError("Unexpected C1 list length or session prefix")
            revised = reserve_slot(ranked, recent)
            if recent is None:
                changes["no_eligible_item"] += 1
            elif recent in ranked:
                changes["already_in_top10"] += 1
            else:
                changes["replaced_rank10"] += 1
            if timestamp is not None and timestamp < when:
                totals["selected_from_earlier_basket"] += 1

            old = metric_terms(ranked, row["targets"])
            new = metric_terms(revised, row["targets"])
            if old != row["terms"]["C1"]:
                raise ValueError("Original query metrics differ from the accepted C1 results")
            for arm, terms in (("c1", old), ("recency", new)):
                for measure in measures:
                    sums[arm][measure].add(terms[measure])
            totals["queries"] += 1
            totals["c1_hits"] += bool(old["hits"])
            totals["recency_hits"] += bool(new["hits"])
            totals["gained"] += not old["hits"] and bool(new["hits"])
            totals["lost"] += bool(old["hits"]) and not new["hits"]

    count = totals["queries"]
    metrics = {arm: {m: sums[arm][m].value() / count for m in measures} for arm in sums}
    accepted = original["arms"]["C1"]
    if (count != accepted["queries"] or roster.hexdigest() != original["roster_sha256"]
            or not all(math.isclose(v, accepted["metrics"][m], abs_tol=1e-12, rel_tol=0)
                       for m, v in metrics["c1"].items())):
        raise ValueError("Roster or original aggregate differs from the Stage 10 report")
    if sum(changes.values()) != count or totals["recency_hits"] - totals["c1_hits"] != totals["gained"] - totals["lost"]:
        raise ValueError("Paired outcome counts do not reconcile")
    return {
        "role": "2015-08 exposed development validation",
        "baseline": "C1",
        "rule": "latest eligible same-session view through query time; numeric ascending item ID on ties; replace rank 10 only if absent",
        "receipt": RELEASE,
        "source_sha256": digests,
        "roster_sha256": roster.hexdigest(),
        "counts": dict(totals),
        "list_changes": dict(changes),
        "metrics": metrics,
        "net_extra_hit_queries": totals["gained"] - totals["lost"],
        "mean_ndcg_at_10_difference": metrics["recency"]["ndcg"] - metrics["c1"]["ndcg"],
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(ROOT), indent=2, allow_nan=False))
