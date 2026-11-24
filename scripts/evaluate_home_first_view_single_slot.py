"""Replay the July and August homepage lists with only browse rank ten replaced."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
from itertools import product
import json
import sqlite3

from scripts.evaluate_august_home_browse import (
    HISTORY, HOMEPAGE, grouped_visitors, load_study_inputs, visitor_rows,
)
from scripts.evaluate_august_home_first_view_pair import (
    OUTPUT as AUGUST_REPORT, summarize_rank_pairs, train_first_view_ranking,
)
from scripts.c1_demo_model import RELEASE
from scripts.evaluate_cart_recommendations import CONTRACT, DB, ROOT, TOP_K, digest_row
from scripts.evaluate_july_home_first_view_pair import (
    JULY_START, NEW as JULY_NEW, OUTPUT as JULY_REPORT, ranking_digest, train_browse_ranking,
)
from scripts.score_recommendation_acceptance import window_ms


OUTPUT = ROOT / "reports/mainline/recommendation_home_first_view_single_slot_20261124.json"


def ranks(items):
    by_item = {item: rank for rank, item in enumerate(items, 1)}
    if len(items) != TOP_K or len(by_item) != TOP_K:
        raise ValueError("Each list must contain ten distinct products")
    return by_item


def swap_tenth(baseline, full):
    """Pick by training rank alone. Keep the original list if there is no outsider."""
    base_ranks = ranks(baseline)
    for item, position in ranks(full).items():
        if item not in base_ranks:
            return [*baseline[:-1], item], position
    return list(baseline), None


def score_visitors(visitors, baseline, single, full):
    rank_maps = [ranks(items) for items in (baseline, single, full)]
    roster, pair, triple = (hashlib.sha256() for _ in range(3))
    single_pairs, full_pairs, outcomes = Counter(), Counter(), Counter()
    for visitor, _, _, view_at, targets in visitors:
        if not targets:
            continue
        base_best, single_best, full_best = (
            min((by_item[i] for i in targets if i in by_item), default=None) for by_item in rank_maps
        )
        row = [visitor, view_at, sorted(targets, key=int)]
        digest_row(roster, row)
        digest_row(pair, [*row, base_best, full_best])
        digest_row(triple, [*row, base_best, single_best, full_best])
        single_pairs[base_best, single_best] += 1
        full_pairs[base_best, full_best] += 1
        outcomes[base_best is not None, single_best is not None, full_best is not None] += 1

    solo = summarize_rank_pairs(single_pairs)
    whole = summarize_rank_pairs(full_pairs)
    retained = outcomes[False, True, True]
    full_gains = whole["candidate_only_gained"]
    return {
        "baseline_vs_full": {
            **whole, "scored_visitor_first_view_targets_sha256": roster.hexdigest(),
            "paired_best_ranks_sha256": pair.hexdigest(),
        },
        "baseline_vs_single": solo,
        "three_arm_best_ranks_sha256": triple.hexdigest(),
        "hit_patterns_baseline_single_full": {
            "".join(map(str, bits)): outcomes[bits] for bits in product((0, 1), repeat=3)
        },
        "single_vs_full_tradeoff": {
            "full_gains_retained": retained,
            "share_of_full_gains_retained": retained / full_gains if full_gains else None,
            "full_gains_forgone": outcomes[False, False, True],
            "full_losses_recovered": outcomes[True, True, False],
            "hits_in_both_original_lists_lost_by_single": outcomes[True, False, True],
            "fewer_baseline_losses": whole["baseline_only_lost"] - solo["baseline_only_lost"],
            "single_hits_minus_full_hits": solo["candidate"]["hits_at_10"] - whole["candidate"]["hits_at_10"],
        },
    }


def evaluate_month(db, scope, scoring_role, new_history, archived_path, public_baseline=None):
    archived = json.loads(archived_path.read_bytes())
    if scope != archived["utc_windows_start_inclusive_end_exclusive"]:
        raise ValueError("Scoring or training dates differ from the archived study")
    windows = {name: window_ms(bounds) for name, bounds in scope.items()}
    baseline = train_browse_ranking(db, windows)
    full, _ = train_first_view_ranking(db, windows)
    base_digest, full_digest = ranking_digest(baseline), ranking_digest(full)
    if full_digest != archived["candidate_rank_item_votes_sha256"]:
        raise ValueError("First-view list differs from the archived training ranking")
    if public_baseline is None:
        if base_digest != archived["baseline_rank_item_counts_sha256"]:
            raise ValueError("Browse list differs from the archived training ranking")
    elif baseline != public_baseline:
        raise ValueError("Browse list differs from the frozen homepage top ten")
    base_items = [item for item, _ in baseline]
    full_items = [item for item, _ in full]
    single, source_rank = swap_tenth(base_items, full_items)
    rows = visitor_rows(db, windows, scoring_role=scoring_role, new_history=new_history)
    scores = score_visitors(grouped_visitors(rows, new_history=new_history), base_items, single, full_items)
    if scores["baseline_vs_full"] != archived["paired"]:
        raise ValueError("Roster, targets, or original two lists' results differ from the archived replay")

    single_digest = hashlib.sha256()
    for rank, item in enumerate(single, 1):
        digest_row(single_digest, [rank, item])
    return {
        "utc_windows_start_inclusive_end_exclusive": scope,
        "scoring_ledger_role": scoring_role,
        "archived_pair": archived_path.relative_to(ROOT).as_posix(),
        "baseline_rank_item_counts_sha256": base_digest, "full_rank_item_votes_sha256": full_digest,
        "single_rank_item_sha256": single_digest.hexdigest(),
        "incoming_first_view_rank": source_rank,
        "incoming_training_first_view_visitors": full[source_rank - 1][1] if source_rank else None,
        "displaced_browse_rank": TOP_K if source_rank else None,
        "displaced_item_rank_in_first_view_top_ten": ranks(full_items).get(base_items[-1]) if source_rank else None,
        "displaced_training_views": baseline[-1][1] if source_rank else None,
        **scores,
    }, single[-1] if source_rank else None


def study():
    frozen_public, august, _ = load_study_inputs()
    published_browse = json.loads(HOMEPAGE.read_bytes())["rankings"]["browse"]
    public_baseline = [(item, row["count"]) for (item, _), row in zip(frozen_public, published_browse, strict=True)]
    july = {"warmup": august["warmup"], "train": [august["train"][0], JULY_START],
            "validation": [JULY_START, august["validation"][0]]}
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        july_result, july_item = evaluate_month(db, july, "train", JULY_NEW, JULY_REPORT)
        august_result, august_item = evaluate_month(db, august, "validation", HISTORY[-1], AUGUST_REPORT, public_baseline)
    return {
        "study": "Replace only browse rank ten with the first training first-view item outside the original ten",
        "role": "July and August 2015 retrospective development backtests",
        "source_receipt": RELEASE, "contract": CONTRACT,
        "ranking_rule": "Keep browse ranks 1-9. Scan the frozen first-view top ten in order, skipping all original browse top-ten items. Put the first remaining item at rank ten. If none remains, keep the original list.",
        "scoring_rule": "Within each month use one observation per new visitor with a view. Score all distinct targets at the first view timestamp at the best matching rank. Visitors and targets are identical across all three lists.",
        "fingerprint_rule": "In visitor text order, hash the visitor, first view timestamp, numerically sorted targets, and best ranks in baseline/single/full order (null for a miss). Hit pattern bits use that same arm order; 1 means a hit.",
        "months": {"2015-07": july_result, "2015-08": august_result},
        "same_incoming_item_in_both_months": july_item is not None and july_item == august_item,
        "limits": "First observed in this dataset. First-view overlap measures offline coverage of observed choices. Homepage impressions, clicks and causal effects are unavailable.",
        "formal_scored_queries": 0, "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the published report")
    args = parser.parse_args()
    report = study()
    if args.check:
        if report != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed single-slot results differ from the report")
    else:
        OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    for month, result in report["months"].items():
        single = result["baseline_vs_single"]
        full = result["baseline_vs_full"]
        print(f"{month}: {single['scored_visitors']:,} visitors, original {single['baseline']['hits_at_10']:,}, "
              f"single {single['candidate']['hits_at_10']:,}, full {full['candidate']['hits_at_10']:,}; "
              f"single gained {single['candidate_only_gained']:,}, lost {single['baseline_only_lost']:,}, "
              f"net {single['net_hits']:+,}")


if __name__ == "__main__":
    main()
