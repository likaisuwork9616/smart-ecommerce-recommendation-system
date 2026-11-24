"""Separate the contributions of cart and purchase weights on the frozen August cohort."""
import argparse
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
import sys

from scripts.audit_august_personalization_signals import read_only
from scripts.evaluate_august_personalization import PairedResults, load_august_sources
from scripts.evaluate_cart_popular_fill import first_hit
from scripts.evaluate_cart_recommendations import DB, TOP_K, digest_row
from scripts.personalization_history import august_history_rows
from scripts.score_recommendation_acceptance import ROOT, require
from scripts.verify_recommendation_acceptance_august import read_json


PREVIOUS = "reports/mainline/recommendation_august_personalization_pair_20261124.json"
VARIANTS = ("add_cart", "add_purchase", "add_both")


def record_combined_change(counts, ranks):
    before, cart, purchase, combined = ranks
    if (before is None) == (combined is None):
        return
    direction = "gain" if before is None else "loss"
    cart_repeats = (cart is None) == (combined is None)
    purchase_repeats = (purchase is None) == (combined is None)
    if cart_repeats and purchase_repeats:
        outcome = "either_alone"
    elif cart_repeats:
        outcome = "cart_only"
    elif purchase_repeats:
        outcome = "purchase_only"
    else:
        outcome = "combined_only"
    counts[direction][outcome] += 1


def segment_report(results, previous, bootstrap):
    arms = {"browse_only": previous["browse_only"]}
    comparisons = {}
    for name, result in results.items():
        summary = result.report(bootstrap)
        require(summary["queries"] == previous["queries"] and summary["visitors"] == previous["visitors"]
                and summary["browse_only"] == previous["browse_only"], "Different browse reference")
        if name == "add_both":
            require(summary == previous, "Combined weights differ from the previous August comparison")
        arms[name] = summary["weighted_actions"]
        comparisons[name] = {k: summary[k] for k in (
            "changed_top_tens", "first_hit_changes", "net_extra_hits", "mrr_at_10_difference", "visitor_bootstrap",
        )}
    return {
        "queries": previous["queries"], "visitors": previous["visitors"],
        "arms": arms, "versus_browse_only": comparisons,
    }


def study(*, progress=None):
    previous = read_json(PREVIOUS)
    policy, coverage, model, catalog = load_august_sources()
    frozen = policy["scenarios"]["browse"]
    require(previous["ordered_query_keys_sha256"] == frozen["development_roster"]["ordered_query_keys_sha256"]
            and previous["reserved_test"] == "locked", "Unexpected reference cohort")
    results = {group: {name: PairedResults() for name in VARIANTS}
               for group in ("all_queries", "with_usable_signal")}
    original_digest, new_digest, sampled_digest = sha256(), sha256(), sha256()
    counts = {direction: Counter(dict.fromkeys(("cart_only", "purchase_only", "either_alone", "combined_only"), 0))
              for direction in ("gain", "loss")}
    signal_groups = Counter()
    visitor = None
    sample_count = 0
    with closing(read_only(ROOT / DB)) as db:
        for position, (record, additions) in enumerate(august_history_rows(db, frozen), 1):
            key = record["key"]
            if key[0] != visitor:
                visitor = key[0]
                profile = model.new_ablation_profile()
            for event, items in additions.items():
                for item in items:
                    profile.observe(item, event)
            rankings = profile.rank(key[2])
            base, cart, purchase, combined = rankings
            require(profile.has_paired_cart or (cart == base and combined == purchase),
                    "Cart weight changed a ranking without a paired cart item")
            require(profile.has_paired_purchase or (purchase == base and combined == cart),
                    "Purchase weight changed a ranking without a paired purchase item")
            for ranking in rankings:
                require(len(ranking) == len(set(ranking)) == TOP_K
                        and all(catalog.contains(item, key[2]) for item in ranking), "Invalid top ten")
            truth = set(record["targets"])
            ranks = [first_hit(ranking, truth) for ranking in rankings]
            for name, ranking, rank in zip(VARIANTS, rankings[1:], ranks[1:], strict=True):
                observation = (visitor, ranks[0], rank, ranking != base)
                results["all_queries"][name].add(*observation)
                if profile.has_paired_action:
                    results["with_usable_signal"][name].add(*observation)
            signal_groups[profile.has_paired_cart, profile.has_paired_purchase] += 1
            record_combined_change(counts, ranks)
            digest_row(original_digest, [key, base, combined])
            digest_row(new_digest, [key, cart, purchase])
            if position % 5000 == 1 or position == previous["all_queries"]["queries"]:
                digest_row(sampled_digest, [position, cart, purchase])
                sample_count += 1
            if progress and position % 10000 == 0:
                progress(position)

    require(original_digest.hexdigest() == previous["ordered_query_and_paired_top_tens_sha256"],
            "Previously published top tens differ on the August roster")
    groups = {k: segment_report(v, previous[k], policy["adoption"]["hit_rate_ci"]) for k, v in results.items()}
    for direction, categories in counts.items():
        require(sum(categories.values()) == previous["all_queries"]["first_hit_changes"][direction],
                "Single-action outcomes do not reconcile with combined changes")
    require(groups["with_usable_signal"]["queries"] == coverage["all_browse_queries"]["queries_with_c1_pair"],
            "Usable action coverage differs from the audited source")
    return {
        "study": "August cart and purchase weight ablation on the frozen co-view model",
        "role": previous["role"], "reference_pair": PREVIOUS,
        "history_windows_utc_start_inclusive_end_exclusive": previous["history_windows_utc_start_inclusive_end_exclusive"],
        "ordered_query_keys_sha256": previous["ordered_query_keys_sha256"],
        "weights_view_cart_purchase": {"browse_only": [1, 0, 0], "add_cart": [1, 3, 0],
                                       "add_purchase": [1, 0, 5], "add_both": [1, 3, 5]},
        **groups,
        "queries_by_usable_action": {
            "neither": signal_groups[False, False], "cart_only": signal_groups[True, False],
            "purchase_only": signal_groups[False, True], "both": signal_groups[True, True],
        },
        "which_single_action_reproduced_combined_hit_change": counts,
        "previous_top_tens_verified_sha256": original_digest.hexdigest(),
        "single_action_top_tens_sha256": new_digest.hexdigest(),
        "single_action_sample": {"queries": sample_count, "positions": previous["sampled_paired_top_tens"]["rule"],
                                 "sha256": sampled_digest.hexdigest()},
        "new_model_fits": 0, "formal_scored_queries": 0,
        "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    notify = (lambda n: print(f"Scored {n:,} August queries", file=sys.stderr, flush=True)) if args.progress else None
    print(json.dumps(study(progress=notify), indent=2, allow_nan=False))
