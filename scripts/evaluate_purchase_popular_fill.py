"""Compare four purchase rankings on the frozen August same-transaction cohort."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from scripts.evaluate_cart_popular_fill import evaluate
from scripts.evaluate_purchase_baskets import ROOT, study as purchase_baseline


BASELINE = "reports/stage13/retailrocket_purchase_basket_201508.json"


def study(root=ROOT, observe_scorable=None):
    root = Path(root)
    baseline_bytes = (root / BASELINE).read_bytes()
    rows = []

    def capture(seed, targets, cobuy, popular):
        rows.append((seed, targets, cobuy, popular))
        if observe_scorable is not None:
            observe_scorable(seed, targets, cobuy, popular)

    baseline = purchase_baseline(root, observe_scorable=capture)
    if baseline != json.loads(baseline_bytes):
        raise ValueError("The reconstructed August purchase baseline differs from its published report")

    result = evaluate(rows, original="cobuy")
    scored = baseline["scorable"]
    all_queries = baseline["all_item_occurrences"]
    expected_empty_fallback_hits = (
        scored["cobuy"]["hit_queries"] + scored["popular"]["hit_queries"]
        - scored["popular_hits_on_cobuy_covered_queries"]
    )
    if (result["queries"] != scored["queries"]
            or all_queries["popular"]["full_ten"] != all_queries["queries"]
            or result["arms"]["empty_fallback"]["hit_queries"] != expected_empty_fallback_hits
            or any(result["arms"][arm][field] != scored[arm][field]
                   for arm in ("cobuy", "popular")
                   for field in ("hit_queries", "first_hit_counts_rank_1_to_10", "mrr_at_10"))):
        raise ValueError("The August cohort, original ranks, or empty fallback disagree")

    return {
        "study": "Keep co-purchase order and fill remaining top-ten slots with frozen popular-purchase candidates",
        "role": baseline["role"],
        "reserved_test": baseline["reserved_test"],
        "reserved_test_ranked_queries": baseline["reserved_test_ranked_queries"],
        "baseline_report": BASELINE,
        "baseline_report_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "baseline_queries_targets_and_rankings_sha256": baseline["queries_targets_and_rankings_sha256"],
        "windows_utc_start_inclusive_end_exclusive": baseline["windows_utc_start_inclusive_end_exclusive"],
        "rules": {
            "empty_fallback": "Use the original co-purchase list unchanged if it is nonempty, otherwise use the original popular-purchase list.",
            "popular_fill": "Keep every co-purchase item at its original rank and append the first items from the original popular top ten that are not already listed. Both lists exclude the seed.",
            "mrr_at_10": "Mean reciprocal rank of the first hit over all scorable queries, with a zero for a miss.",
            "paired_rank_changes": "Earlier, same and later counts are restricted to queries hit by both compared lists.",
        },
        "all_item_occurrences": {
            "queries": all_queries["queries"],
            "original_cobuy_empty": all_queries["queries"] - all_queries["cobuy"]["with_recommendations"],
            "original_cobuy_short_nonempty": all_queries["cobuy"]["with_recommendations"] - all_queries["cobuy"]["full_ten"],
            "original_cobuy_full_ten": all_queries["cobuy"]["full_ten"],
            # The ten distinct popularity candidates suffice even after removing overlap with the prefix.
            "popular_fill_full_ten": all_queries["queries"],
        },
        "scorable": result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write verified aggregate JSON to this path. Defaults to stdout.")
    args = parser.parse_args()
    encoded = json.dumps(study(), indent=2, allow_nan=False) + "\n"
    if args.report is None:
        print(encoded, end="")
        return
    output = NamedTemporaryFile(dir=args.report.parent, delete=False)
    temp = Path(output.name)
    try:
        with output:
            output.write(encoded.encode("utf-8"))
        temp.replace(args.report)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
