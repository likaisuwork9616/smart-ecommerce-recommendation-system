"""Explain misses in the frozen August browsing comparison."""
import json
from collections import Counter

from scripts.evaluate_cart_popular_fill import compare, first_hit
from scripts.evaluate_recency_slot import AUGUST_START, SEPTEMBER_START
from scripts.score_recommendation_acceptance import FREEZE, TOP_K, require
from scripts.verify_recommendation_acceptance_august import RECENCY_REPORT, browse_query_details, read_json


PAIRED_REPORT = "reports/mainline/recommendation_default_paired_august_20261123.json"


def summarize(rows):
    k1_ranks, baseline_ranks = [], []
    c1_changes = Counter()
    baseline_only = {"original_c1_also_hit": 0, "only_hit_after_recency_slot": 0}
    both_miss = {"all_targets_eligible": 0, "some_targets_eligible": 0, "no_targets_eligible": 0}
    recent_target_misses = 0
    for _, targets, candidate, baseline, original, recent, reachable in rows:
        k1_rank = first_hit((item for item, _ in candidate), targets)
        baseline_rank = first_hit((item for item, _ in baseline), targets)
        original_hit = not targets.isdisjoint(original)
        recent_target = recent in targets
        require(not recent_target or baseline_rank is not None, "Recency baseline lost its selected target")

        k1_ranks.append(k1_rank)
        baseline_ranks.append(baseline_rank)
        c1_changes["c1_hits"] += original_hit
        c1_changes["recency_hits"] += baseline_rank is not None
        c1_changes["gained"] += not original_hit and baseline_rank is not None
        c1_changes["lost"] += original_hit and baseline_rank is None
        recent_target_misses += k1_rank is None and recent_target

        if k1_rank is None and baseline_rank is not None:
            category = "original_c1_also_hit" if original_hit else "only_hit_after_recency_slot"
            baseline_only[category] += 1
        elif k1_rank is None:
            if not reachable:
                both_miss["no_targets_eligible"] += 1
            elif reachable == len(targets):
                both_miss["all_targets_eligible"] += 1
            else:
                both_miss["some_targets_eligible"] += 1

    paired = compare(baseline_ranks, k1_ranks)
    require(sum(baseline_only.values()) == paired["loss"] and sum(both_miss.values()) == paired["both_miss"],
            "Miss categories do not reconcile")
    rank_counts = {name: Counter(ranks) for name, ranks in (("candidate", k1_ranks), ("baseline", baseline_ranks))}
    return {
        "queries": len(k1_ranks),
        "paired_first_hit_changes": paired,
        "first_hit_counts_rank_1_to_10": {
            name: [counts[rank] for rank in range(1, TOP_K + 1)] for name, counts in rank_counts.items()
        },
        "original_c1_and_recency_counts": dict(c1_changes),
        "baseline_only": {"queries": paired["loss"], **baseline_only},
        "both_miss": {
            "queries": paired["both_miss"],
            "at_least_one_target_eligible": both_miss["all_targets_eligible"] + both_miss["some_targets_eligible"],
            **both_miss,
        },
        "recency_opportunity": {
            "k1_misses_with_selected_recent_item_as_target": recent_target_misses,
            "k1_first_hits_at_rank_10": rank_counts["candidate"][TOP_K],
        },
    }


def study():
    policy = json.loads(FREEZE.read_bytes())
    frozen = policy["scenarios"]["browse"]
    window = [AUGUST_START, SEPTEMBER_START]
    published = read_json(PAIRED_REPORT)
    require(published["window_utc_ms"] == window and published["reserved_test_ranked_queries"] == 0,
            "Paired reference is outside the August development scope")
    expected = published["scenarios"]["browse"]
    result = summarize(browse_query_details(frozen, *window))
    require(result["queries"] == expected["scorable_queries"] == frozen["development_roster"]["scorable_queries"]
            and result["paired_first_hit_changes"] == expected["paired_first_hit_changes"],
            "Reconstructed August pair differs from the published comparison")
    for arm, ranks in result["first_hit_counts_rank_1_to_10"].items():
        require(ranks == expected["arms"][arm]["first_hit_counts_rank_1_to_10"],
                "Reconstructed first hit ranks differ from the published comparison")
    recency = read_json(RECENCY_REPORT)["counts"]
    require(all(recency[key] == value for key, value in result["original_c1_and_recency_counts"].items()),
            "Reconstructed original C1 and recency counts differ from the published comparison")
    return {
        "study": "Browse missed-query diagnosis from frozen rankings",
        "role": published["role"],
        "window_utc_start_inclusive_end_exclusive_ms": window,
        "frozen_training_commit": policy["frozen_git_commit"],
        "ordered_query_keys_sha256": frozen["development_roster"]["ordered_query_keys_sha256"],
        "references": [PAIRED_REPORT, RECENCY_REPORT],
        "eligible_target_rule": "An item's first recorded view is strictly before the query time.",
        "query_target_rule": "Every distinct item at the next observed viewing time in the same session.",
        "recency_opportunity_rule": "Count K1 misses where the existing recency rule selects a target, and count all K1 first hits at rank 10 as the maximum hit-loss exposure.",
        **result,
        "k1_with_recency_rankings_generated": 0,
        "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
    }


if __name__ == "__main__":
    print(json.dumps(study(), indent=2, allow_nan=False))
