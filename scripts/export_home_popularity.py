"""Export three anonymous, seed-free popularity lists from the frozen training data."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
import sqlite3

from scripts.c1_demo_model import POPULARITY, RELEASE, read_counts
from scripts.evaluate_cart_recommendations import DB, ROOT, TOP_K, WINDOWS, digest_row, sha
from scripts.evaluate_purchase_baskets import build_baskets, purchase_rows


CASES = ROOT / "docs/recommendation-demo/cases.json"
OUTPUT = ROOT / "docs/recommendation-demo/popularity.json"
# From the verified product B snapshot: hash (mode, original item, published alias)
# in rank order. A changed list must never silently inherit another item's alias.
POPULAR_CASE_BINDING = "afd29c6fcb20314711f3f8848f0fea9cabf74304445c828725014eb2bd7e3b04"


def ranked_counts(counts):
    return sorted(counts.items(), key=lambda row: (-row[1], int(row[0])))[:TOP_K]


def basket_rankings(db):
    carts = dict(db.execute(
        """SELECT i, COUNT(*) FROM qualified
           WHERE role = 'train' AND t >= ? AND t < ? AND e = 'addtocart'
           GROUP BY i""", WINDOWS["train"],
    ))
    baskets, _ = build_baskets(purchase_rows(db, "train"))
    purchases = Counter(item for _, _, items in baskets for item in items)
    return {"cart": ranked_counts(carts), "purchase": ranked_counts(purchases)}


def export():
    release = json.loads((ROOT / RELEASE).read_bytes())
    for path, entries in ((POPULARITY, release["sources"]), (DB, release["external_dependencies"])):
        receipt = next(row for row in entries if row["path"] == path)
        local = ROOT / path
        if local.stat().st_size != receipt["bytes"] or sha(local) != receipt["sha256"]:
            raise ValueError(f"Source differs from the frozen training release: {path}")

    rankings = {"browse": ranked_counts(read_counts(ROOT / POPULARITY, "count"))}
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rankings.update(basket_rankings(db))

    aliases = json.loads(CASES.read_bytes())["popular"]["rankings"]
    public = {}
    binding = hashlib.sha256()
    for mode, rows in rankings.items():
        public[mode] = []
        for (item, count), (alias, source) in zip(rows, aliases[mode], strict=True):
            if source != "popular":
                raise ValueError("The reference case must contain only popular items")
            digest_row(binding, [mode, item, alias])
            public[mode].append({"item": alias, "count": count})
    if binding.hexdigest() != POPULAR_CASE_BINDING:
        raise ValueError("The rankings or public aliases differ from the verified product B snapshot")

    start, end = (datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                  for ms in WINDOWS["train"])
    return {"training_window_utc": {"start": start, "end_exclusive": end}, "rankings": public}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare against the published JSON")
    args = parser.parse_args()
    snapshot = export()
    if args.check:
        if json.loads(OUTPUT.read_bytes()) != snapshot:
            raise SystemExit("Published popularity data differs from the frozen sources")
        print("All 30 ranks, counts and public item aliases match.")
    else:
        OUTPUT.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
