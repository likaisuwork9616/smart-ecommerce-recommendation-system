"""Compare frozen co-add and popular-cart top tens on August next-add queries."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import hashlib
from itertools import combinations, groupby
import json
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from scripts.audit_retailrocket_cart_support import CONTRACT, DB, GAP_MS, RECEIPT, ROOT, cart_sessions
from scripts.verify_cart_validation import verify


INVENTORY = "reports/stage13/retailrocket_cart_support_train.json"
TOP_K = 10
MIN_VISITORS = 2
WINDOWS = {"train": (1430697600000, 1438387200000), "validation": (1438387200000, 1441065600000)}
ARMS = ("coadd", "popular")


def activity_rows(db, role, lo, hi):
    allowed = WINDOWS.get(role)
    if allowed is None or not allowed[0] <= lo < hi <= allowed[1]:
        raise ValueError("This study only reads its training or August development window")
    return db.execute(
        """SELECT v, t, e, i FROM qualified
           WHERE role = ? AND t >= ? AND t < ? AND e IN ('view', 'addtocart')
           ORDER BY v, t""",
        (role, lo, hi),
    )


def digest_row(digest, values):
    digest.update((json.dumps(values, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii"))


@dataclass
class CartModel:
    neighbors: dict
    popular_prefix: list
    cart_items: set
    training: dict

    def rank(self, seed):
        # One extra popular item is enough to replace the excluded seed.
        return self.neighbors.get(seed, []), [i for i in self.popular_prefix if i != seed][:TOP_K]


def build_model(rows):
    event_items = {"view": Counter(), "addtocart": Counter()}
    pair_visitors = Counter()
    sessions = cart_sessions_count = visitors = 0
    for _, events in groupby(rows, key=lambda r: r[0]):
        visitors += 1
        seen_pairs = set()
        for _, _, basket in cart_sessions(events, event_items):
            sessions += 1
            cart_sessions_count += bool(basket)
            seen_pairs.update(combinations(sorted(basket, key=int), 2))
        pair_visitors.update(seen_pairs)

    pairs = sorted(((a, b, n) for (a, b), n in pair_visitors.items() if n >= MIN_VISITORS),
                   key=lambda edge: (int(edge[0]), int(edge[1])))
    neighbors = defaultdict(list)
    pair_digest = hashlib.sha256()
    for a, b, support in pairs:
        neighbors[a].append((b, support))
        neighbors[b].append((a, support))
        digest_row(pair_digest, [a, b, support])
    ranked = {}
    for seed, edges in neighbors.items():
        edges.sort(key=lambda e: (-e[1], int(e[0])))
        ranked[seed] = [item for item, _ in edges[:TOP_K]]
    popularity = sorted(event_items["addtocart"].items(), key=lambda e: (-e[1], int(e[0])))
    popular_digest = hashlib.sha256()
    for item, count in popularity:
        digest_row(popular_digest, [item, count])
    training = {
        "visitors": visitors, "sessions": sessions, "cart_sessions": cart_sessions_count,
        "events": {event: counts.total() for event, counts in event_items.items()},
        "distinct_items": {event: len(counts) for event, counts in event_items.items()},
        "distinct_pairs_before_threshold": len(pair_visitors), "qualifying_pairs": len(pairs),
        "seeds_with_neighbors": len(ranked),
        "seeds_with_ten_neighbors": sum(len(items) == TOP_K for items in ranked.values()),
        "qualifying_pairs_sha256": pair_digest.hexdigest(),
        "popular_counts_sha256": popular_digest.hexdigest(),
    }
    return CartModel(ranked, [item for item, _ in popularity[:TOP_K + 1]], set(event_items["addtocart"]), training)


def session_baskets(events, activity):
    """One visitor's view/add clock defines gaps. Only distinct cart items become baskets."""
    previous = None
    baskets = []
    for t, moment in groupby(events, key=lambda row: row[1]):
        if previous is not None and t < previous:
            raise ValueError("Visitor activity is not in time order")
        if previous is not None and t - previous > GAP_MS:
            yield baskets
            baskets = []
        added = set()
        for _, _, event, item in moment:
            if event == "addtocart":
                added.add(item)
            activity[event + "_events"] += 1
        if added:
            baskets.append((t, added))
            activity["cart_timestamps"] += 1
            activity["multi_item_cart_timestamps"] += len(added) > 1
        previous = t
    if previous is not None:
        yield baskets


@dataclass
class ListCounts:
    with_recommendations: int = 0
    full_ten: int = 0
    hit_queries: int = 0

    def add(self, items, hit=False):
        self.with_recommendations += bool(items)
        self.full_ten += len(items) == TOP_K
        self.hit_queries += hit

    def summary(self, total, scored):
        result = {
            "with_recommendations": self.with_recommendations, "full_ten": self.full_ten,
            "coverage": self.with_recommendations / total if total else None,
        }
        if scored:
            result.update(hit_queries=self.hit_queries, hit_rate_all=self.hit_queries / total if total else None,
                          hit_rate_when_recommended=self.hit_queries / self.with_recommendations
                          if self.with_recommendations else None)
        return result


def evaluate(rows, model, observe_scorable=None):
    """Score all August opportunities and optionally expose each labeled row in report order."""
    activity = dict.fromkeys(("visitors", "sessions", "cart_sessions", "view_events", "addtocart_events",
                              "cart_timestamps", "multi_item_cart_timestamps"), 0)
    opportunities = {arm: ListCounts() for arm in ARMS}
    scored = {arm: ListCounts() for arm in ARMS}
    paired = dict.fromkeys(("both", "coadd_only", "popular_only", "neither"), 0)
    outcomes = {(True, True): "both", (True, False): "coadd_only", (False, True): "popular_only",
                (False, False): "neither"}
    total = valid = no_later = repeat_only = popular_hits_on_covered = 0
    valid_visitors = set()
    valid_sessions = unknown_seed = unknown_targets = multi_targets = 0
    all_digest = hashlib.sha256()
    scored_digest = hashlib.sha256()
    for visitor, events in groupby(rows, key=lambda r: r[0]):
        activity["visitors"] += 1
        for baskets in session_baskets(events, activity):
            activity["sessions"] += 1
            activity["cart_sessions"] += bool(baskets)
            before = valid
            for pos, (t, current) in enumerate(baskets):
                successor = baskets[pos + 1][1] if pos + 1 < len(baskets) else set()
                for seed in sorted(current, key=int):
                    total += 1
                    targets = successor - {seed}
                    coadd, popular = model.rank(seed)
                    ordered_targets = sorted(targets, key=int)
                    record = [visitor, t, seed, ordered_targets, coadd, popular]
                    digest_row(all_digest, record)
                    opportunities["coadd"].add(coadd)
                    opportunities["popular"].add(popular)
                    if not targets:
                        no_later += not successor
                        repeat_only += bool(successor)
                        continue
                    valid += 1
                    digest_row(scored_digest, record)
                    valid_visitors.add(visitor)
                    unknown_seed += seed not in model.cart_items
                    unknown_targets += model.cart_items.isdisjoint(targets)
                    multi_targets += len(targets) > 1
                    coadd_hit = not targets.isdisjoint(coadd)
                    popular_hit = not targets.isdisjoint(popular)
                    scored["coadd"].add(coadd, coadd_hit)
                    scored["popular"].add(popular, popular_hit)
                    paired[outcomes[coadd_hit, popular_hit]] += 1
                    popular_hits_on_covered += bool(coadd) and popular_hit
                    if observe_scorable is not None:
                        observe_scorable(t, seed, ordered_targets, coadd, popular)
            valid_sessions += valid > before
    if (sum(paired.values()) != valid or total != no_later + repeat_only + valid
            or paired["both"] + paired["coadd_only"] != scored["coadd"].hit_queries
            or paired["both"] + paired["popular_only"] != scored["popular"].hit_queries):
        raise ValueError("Query partitions or paired hit counts disagree")
    return {
        "activity": activity,
        "all_cart_opportunities": {
            "queries": total, "no_later_cart": no_later, "next_cart_only_seed": repeat_only,
            **{arm: counts.summary(total, False) for arm, counts in opportunities.items()},
            "query_targets_and_rankings_sha256": all_digest.hexdigest(),
        },
        "scorable": {
            "queries": valid, "visitors": len(valid_visitors), "sessions": valid_sessions,
            "multiple_target_queries": multi_targets, "seed_absent_from_training_carts": unknown_seed,
            "all_targets_absent_from_training_carts": unknown_targets,
            **{arm: counts.summary(valid, True) for arm, counts in scored.items()}, "paired_hits": paired,
            "on_coadd_covered_queries": {"queries": scored["coadd"].with_recommendations,
                                         "coadd_hit_queries": scored["coadd"].hit_queries,
                                         "popular_hit_queries": popular_hits_on_covered},
            "query_targets_and_rankings_sha256": scored_digest.hexdigest(),
        },
    }


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(root=ROOT, observe_scorable=None):
    root = Path(root)
    receipt = json.loads((root / RECEIPT).read_bytes())
    source = next(r for r in receipt["external_dependencies"] if r["path"] == DB)
    path = root / DB
    binding = {field: source[field] for field in ("path", "bytes", "sha256")}
    inventory = json.loads((root / INVENTORY).read_bytes())
    if (inventory["source_database"] != binding or path.stat().st_size != binding["bytes"]
            or sha(path) != binding["sha256"]):
        raise ValueError("Training inventory or local database differs from the accepted source")
    roles = json.loads((root / CONTRACT).read_bytes())["time_roles"]
    for role, expected in WINDOWS.items():
        actual = tuple(int(datetime.fromisoformat(date).timestamp() * 1000) for date in roles[role])
        if actual != expected:
            raise ValueError("Frozen time roles differ")
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        model = build_model(activity_rows(db, "train", *WINDOWS["train"]))
        prior = inventory["counts"]
        support = {r["minimum_support"]: r for r in prior["pair_support_by_distinct_visitor"]}
        expected = {
            "visitors": prior["anonymous_visitors"], "sessions": prior["sessions"], "cart_sessions": prior["cart_sessions"],
            "events": prior["events"], "distinct_items": prior["distinct_items"],
            "distinct_pairs_before_threshold": support[1]["unordered_pairs"],
            "qualifying_pairs": support[MIN_VISITORS]["unordered_pairs"],
            "seeds_with_neighbors": support[MIN_VISITORS]["at_least_1_neighbors"]["cart_items"],
            "seeds_with_ten_neighbors": support[MIN_VISITORS]["at_least_10_neighbors"]["cart_items"],
        }
        if any(model.training[k] != v for k, v in expected.items()):
            raise ValueError("Rebuilt training support differs from the original train-only inventory")
        august = evaluate(activity_rows(db, "validation", *WINDOWS["validation"]), model, observe_scorable)
    if sha(path) != binding["sha256"]:
        raise ValueError("Source bytes changed during evaluation")
    result = {
        "study": "next distinct-item add-to-cart at the immediately following cart timestamp",
        "role": "2015-08 exposed development validation", "reserved_test": "locked",
        "reserved_test_ranked_queries": 0, "source_database": binding,
        "source_report_sha256": {name: sha(root / name) for name in (CONTRACT, RECEIPT, INVENTORY)},
        "windows_utc_start_inclusive_end_exclusive": {role: roles[role] for role in WINDOWS},
        "rules": {
            "session": "Clip to each window. Group canonical views/adds by visitor, split only at activity gaps over 30 minutes.",
            "query": "One query per distinct item added at a timestamp. Other simultaneous adds do not define an order.",
            "target": "All distinct items except the seed at the next strictly later add timestamp in the same session. No skipping same-item-only next adds.",
            "candidates": "Only items observed added during training, excluding the seed. Unknown August targets remain in the denominator.",
            "coadd": "At least 2 distinct visitors must support an unordered in-session pair. Rank by support descending, numeric item ID ascending. Return up to 10 without filling.",
            "popular": "Canonical training add event count descending, numeric item ID ascending. Take up to 10 after excluding the seed.",
            "hit": "At least one ranked item is in the next-add target set. An empty list is a miss on scorable queries.",
        },
        "training": model.training, **august,
    }
    result["independent_verification"] = verify(root, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the verified aggregate JSON to this path. Defaults to stdout.")
    args = parser.parse_args()
    result = json.dumps(audit(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.report is None:
        print(result, end="")
    else:
        # Create the file in the report directory so it inherits the workspace's Windows permissions.
        output = NamedTemporaryFile(dir=args.report.parent, delete=False)
        temporary_path = Path(output.name)
        try:
            with output:
                output.write(result.encode("utf-8"))
            temporary_path.replace(args.report)
        finally:
            temporary_path.unlink(missing_ok=True)
