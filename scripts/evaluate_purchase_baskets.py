"""Evaluate a transaction-key basket recommender on August development purchases."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
import hashlib
from itertools import combinations, groupby
import json
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from scripts.evaluate_cart_recommendations import (
    CONTRACT, DB, MIN_VISITORS, RECEIPT, ROOT, TOP_K, WINDOWS, ListCounts, digest_row, sha,
)


def purchase_rows(db, role):
    start, end = WINDOWS[role]
    qualified = db.execute("""
        SELECT v, x, i, t FROM qualified
        WHERE role=? AND t>=? AND t<? AND e='transaction'
        ORDER BY v,x,i,t
    """, (role, start, end)).fetchall()
    canonical_raw = db.execute("""
        SELECT v, x, i, t FROM raw
        WHERE role=? AND t>=? AND t<? AND e='transaction' AND bad=''
        GROUP BY rt,v,e,i,x ORDER BY v,x,i,t
    """, (role, start, end)).fetchall()
    if qualified != canonical_raw:
        raise ValueError("Purchase rows differ from the separately deduplicated raw source")
    return qualified


def build_baskets(rows):
    baskets = []
    clocks = []
    for (visitor, transaction), group in groupby(rows, key=lambda row: row[:2]):
        events = list(group)
        if not transaction:
            raise ValueError("Purchase row has no transaction key")
        items = tuple(sorted({row[2] for row in events}, key=int))
        baskets.append((visitor, transaction, items))
        timestamps = [row[3] for row in events]
        clocks.append(max(timestamps) - min(timestamps))

    context = {
        "canonical_transaction_rows": len(rows),
        "transaction_groups": len(baskets),
        "anonymous_visitors": len({visitor for visitor, _, _ in baskets}),
        "distinct_transaction_keys": len({transaction for _, transaction, _ in baskets}),
        "distinct_items": len({item for _, _, items in baskets for item in items}),
        "item_occurrences_in_transaction_groups": sum(len(items) for _, _, items in baskets),
        "groups_with_at_least_two_distinct_items": sum(len(items) > 1 for _, _, items in baskets),
        "max_items_in_group": max((len(items) for _, _, items in baskets), default=0),
        "groups_spanning_multiple_timestamps": sum(span > 0 for span in clocks),
        "max_timestamp_span_ms": max(clocks, default=0),
    }
    return baskets, context


def build_lists(baskets):
    popularity = Counter(item for _, _, items in baskets for item in items)
    votes = Counter()
    for _, visitor_baskets in groupby(baskets, key=lambda basket: basket[0]):
        pairs = {pair for _, _, items in visitor_baskets for pair in combinations(items, 2)}
        votes.update(pairs)
    neighbors = defaultdict(list)
    digest = hashlib.sha256()
    qualified_pairs = 0
    for (left, right), support in sorted(votes.items(), key=lambda e: (int(e[0][0]), int(e[0][1]))):
        if support < MIN_VISITORS:
            continue
        neighbors[left].append((right, support))
        neighbors[right].append((left, support))
        digest_row(digest, [left, right, support])
        qualified_pairs += 1

    ranked = {seed: tuple(item for item, _ in sorted(edges, key=lambda e: (-e[1], int(e[0])))[:TOP_K])
              for seed, edges in neighbors.items()}
    popular = sorted(popularity, key=lambda item: (-popularity[item], int(item)))
    return ranked, popular, {
        "observed_pairs": len(votes),
        "qualified_pairs": qualified_pairs,
        "qualified_pairs_sha256": digest.hexdigest(),
        "seeds_with_at_least_one_neighbor": len(ranked),
        "seeds_with_ten_neighbors": sum(len(items) == TOP_K for items in ranked.values()),
    }


def evaluate(baskets, ranked, popular, observe_scorable=None):
    popularity = set(popular)
    prefix = popular[:TOP_K + 1]
    all_lists = {name: ListCounts() for name in ("cobuy", "popular")}
    scored_lists = {name: ListCounts() for name in all_lists}
    pair_outcomes = dict.fromkeys(("both", "cobuy_only", "popular_only", "neither"), 0)
    outcome_keys = {(True, True): "both", (True, False): "cobuy_only",
                    (False, True): "popular_only", (False, False): "neither"}
    ranks = {name: Counter() for name in all_lists}
    digest = hashlib.sha256()
    total = eligible = unknown_targets = popular_on_covered = 0
    for visitor, transaction, items in baskets:
        for seed in items:
            total += 1
            targets = tuple(item for item in items if item != seed)
            truth = set(targets)
            cobuy = ranked.get(seed, ())
            baseline = [item for item in prefix if item != seed][:TOP_K]
            digest_row(digest, [visitor, transaction, seed, targets, cobuy, baseline])
            all_lists["cobuy"].add(cobuy)
            all_lists["popular"].add(baseline)
            if not targets:
                continue
            eligible += 1
            if observe_scorable is not None:
                observe_scorable(seed, truth, cobuy, baseline)
            unknown_targets += popularity.isdisjoint(truth)
            hits = []
            for name, ranking in (("cobuy", cobuy), ("popular", baseline)):
                first = next((pos for pos, item in enumerate(ranking, start=1) if item in truth), None)
                hit = first is not None
                scored_lists[name].add(ranking, hit)
                if hit:
                    ranks[name][first] += 1
                hits.append(hit)
            popular_on_covered += bool(cobuy) and hits[1]
            pair_outcomes[outcome_keys[tuple(hits)]] += 1

    return {
        "all_item_occurrences": {
            "queries": total,
            **{name: counts.summary(total, False) for name, counts in all_lists.items()},
        },
        "scorable": {
            "queries": eligible,
            "all_targets_absent_from_training": unknown_targets,
            **{name: {**counts.summary(eligible, True),
                       "first_hit_counts_rank_1_to_10": [ranks[name][i] for i in range(1, TOP_K+1)],
                       "mrr_at_10": sum(ranks[name][i] / i for i in range(1, TOP_K+1)) / eligible
                       if eligible else None}
               for name, counts in scored_lists.items()},
            "paired_hits": pair_outcomes,
            "popular_hits_on_cobuy_covered_queries": popular_on_covered,
        },
        "queries_targets_and_rankings_sha256": digest.hexdigest(),
    }


def study(root=ROOT, observe_scorable=None):
    root = Path(root)
    release = json.loads((root / RECEIPT).read_bytes())
    source = next(entry for entry in release["external_dependencies"] if entry["path"] == DB)
    binding = {name: source[name] for name in ("path", "bytes", "sha256")}
    database = root / DB
    if database.stat().st_size != binding["bytes"] or sha(database) != binding["sha256"]:
        raise ValueError("Purchase source does not match the accepted database")
    roles = json.loads((root / CONTRACT).read_bytes())["time_roles"]
    for role, bound in WINDOWS.items():
        window = tuple(int(datetime.fromisoformat(stamp).timestamp() * 1000) for stamp in roles[role])
        if window != bound:
            raise ValueError("Training or August window differs from the accepted contract")

    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        train, train_counts = build_baskets(purchase_rows(db, "train"))
        august, august_counts = build_baskets(purchase_rows(db, "validation"))
    if sha(database) != binding["sha256"]:
        raise ValueError("Purchase source changed during the experiment")
    overlap = {basket[:2] for basket in train}.intersection(basket[:2] for basket in august)
    if overlap:
        raise ValueError("Transaction groups cross the training and validation boundary")
    ranked, popular, training_support = build_lists(train)
    result = evaluate(august, ranked, popular, observe_scorable)
    if (result["all_item_occurrences"]["queries"] != august_counts["item_occurrences_in_transaction_groups"]
            or result["scorable"]["queries"] != result["all_item_occurrences"]["queries"]
            - (august_counts["transaction_groups"] - august_counts["groups_with_at_least_two_distinct_items"])):
        raise ValueError("Transaction and query cohort counts disagree")
    return {
        "study": "Other items recorded under the same transaction key as one known item",
        "role": "2015-08 development validation",
        "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
        "source_database": binding,
        "windows_utc_start_inclusive_end_exclusive": {role: roles[role] for role in WINDOWS},
        "canonical_raw_check": "Matched deduplicated raw transaction rows within each allowed window",
        "transaction_groups_crossing_train_and_validation": len(overlap),
        "rules": {
            "basket": "One group per anonymous visitor key and transaction key; distinct item IDs, without timestamp order.",
            "cobuy": "Unordered pairs within a group; at least two distinct supporting visitors, counted once each. Sort by votes descending, numeric item ID ascending.",
            "popular": "Number of training transaction groups containing the item. Sort by count descending, numeric item ID ascending.",
            "query": "One query per distinct seed item per group; remove it from both top tens. Only groups with other distinct items are scored. Unknown targets stay in the denominator.",
            "hit": "At least one other item in the same group is ranked. MRR@10 is the mean reciprocal rank of the first hit, with misses scored zero.",
        },
        "training": {**train_counts, **training_support},
        "august": august_counts,
        **result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the aggregate JSON; defaults to stdout.")
    args = parser.parse_args()
    result = json.dumps(study(), indent=2, allow_nan=False) + "\n"
    if args.report is None:
        print(result, end="")
        return
    output = NamedTemporaryFile(dir=args.report.parent, delete=False)
    temp = Path(output.name)
    try:
        with output:
            output.write(result.encode("utf-8"))
        temp.replace(args.report)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
