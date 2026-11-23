"""Evaluate a single recency slot on the frozen August K1 rankings."""
import json
import math

from scripts.analyze_august_browse_misses import PAIRED_REPORT
from scripts.evaluate_cart_popular_fill import compare, first_hit, summarize
from scripts.evaluate_recency_slot import AUGUST_START, SEPTEMBER_START, reserve_slot
from scripts.score_recommendation_acceptance import FREEZE, TOP_K, require
from scripts.verify_recommendation_acceptance_august import browse_query_details, read_json


MISS_REPORT = "reports/mainline/recommendation_browse_miss_analysis_20261123.json"


def evaluate(rows):
    original_ranks, revised_ranks = [], []
    changes = dict.fromkeys(("no_eligible_recent_item", "recent_item_already_in_top10", "replaced_rank_10"), 0)
    for _, targets, candidate, _, _, recent, _ in rows:
        original = [item for item, _ in candidate]
        revised = reserve_slot(original, recent)
        require(len(revised) == len(set(revised)) == TOP_K and revised[:-1] == original[:-1],
                "The recency slot must preserve nine ranks and ten distinct items")
        if recent is None:
            changes["no_eligible_recent_item"] += 1
        elif recent in original:
            changes["recent_item_already_in_top10"] += 1
        else:
            changes["replaced_rank_10"] += 1
        original_ranks.append(first_hit(original, targets))
        revised_ranks.append(first_hit(revised, targets))

    original = summarize(original_ranks)
    revised = summarize(revised_ranks)
    paired = compare(original_ranks, revised_ranks)
    net = paired["gain"] - paired["loss"]
    mrr_delta = revised["mrr_at_10"] - original["mrr_at_10"]
    require(net == revised["hit_queries"] - original["hit_queries"]
            and paired["earlier"] == paired["later"] == 0
            and math.isclose(mrr_delta, net / (TOP_K * len(original_ranks)), rel_tol=0, abs_tol=1e-14),
            "A change outside rank 10 or a mismatched hit count was found")
    return {
        "queries": len(original_ranks),
        "list_changes": changes,
        "original_k1": original,
        "k1_with_recency": revised,
        "paired_first_hit_changes": paired,
        "net_extra_hit_queries": net,
        "mrr_at_10_delta": mrr_delta,
    }


def study():
    policy = json.loads(FREEZE.read_bytes())
    frozen = policy["scenarios"]["browse"]
    window = [AUGUST_START, SEPTEMBER_START]
    published = read_json(PAIRED_REPORT)
    diagnostic = read_json(MISS_REPORT)
    roster = frozen["development_roster"]
    require(published["window_utc_ms"] == diagnostic["window_utc_start_inclusive_end_exclusive_ms"] == window
            and published["reserved_test_ranked_queries"] == diagnostic["reserved_test_ranked_queries"] == 0
            and diagnostic["ordered_query_keys_sha256"] == roster["ordered_query_keys_sha256"],
            "Existing evidence differs from the frozen August cohort")
    result = evaluate(browse_query_details(frozen, *window))
    expected = published["scenarios"]["browse"]
    original = result["original_k1"]
    previous_k1 = expected["arms"]["candidate"]
    require(result["queries"] == expected["scorable_queries"] == diagnostic["queries"] == roster["scorable_queries"]
            and original["first_hit_counts_rank_1_to_10"] == previous_k1["first_hit_counts_rank_1_to_10"]
            and original["hit_queries"] == previous_k1["hit_queries"]
            and math.isclose(original["mrr_at_10"], previous_k1["mrr_at_10"], rel_tol=0, abs_tol=1e-14),
            "Original K1 metrics differ from the published August comparison")
    opportunity = diagnostic["recency_opportunity"]
    paired = result["paired_first_hit_changes"]
    require(paired["gain"] == opportunity["k1_misses_with_selected_recent_item_as_target"]
            and paired["loss"] <= opportunity["k1_first_hits_at_rank_10"],
            "Observed recency transitions disagree with the previous miss diagnosis")
    return {
        "study": "Reserve K1 rank 10 for the most recent eligible viewed item",
        "role": published["role"],
        "window_utc_start_inclusive_end_exclusive_ms": window,
        "frozen_training_commit": policy["frozen_git_commit"],
        "ordered_query_keys_sha256": roster["ordered_query_keys_sha256"],
        "references": [PAIRED_REPORT, MISS_REPORT],
        "rule": "Preserve K1 ranks 1 to 9. Replace rank 10 only if the most recent eligible item in the session is absent from the top ten. Eligibility requires a first view strictly before the query. Equal-time items are ordered by numeric ID.",
        **result,
        "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
    }


if __name__ == "__main__":
    print(json.dumps(study(), indent=2, allow_nan=False))
