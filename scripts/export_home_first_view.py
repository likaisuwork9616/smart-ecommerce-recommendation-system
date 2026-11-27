"""Export the two frozen homepage top tens with August visitor-level gain/loss attribution."""
import argparse
import json

from scripts.evaluate_august_home_first_view_pair import OUTPUT as PAIR_REPORT
from scripts.evaluate_cart_recommendations import ROOT
from scripts.export_popular_product_recommendations import (
    OUTPUT as PRODUCT_CARDS, SOURCE_RECEIPT, load_home_rankings, load_product_inputs,
    product_cards_with_aliases, register_first_view_items,
)
from scripts.score_home_first_view_acceptance import RANKING_FINGERPRINTS
from scripts.verify_home_first_view_acceptance_august import OUTPUT as AUGUST_ACCEPTANCE


OUTPUT = ROOT / "docs/recommendation-demo/home-first-view.json"


def public_rows(ranking, other, exclusive, aliases):
    other_ranks = {item: rank for rank, (item, _) in enumerate(other, 1)}
    rows = []
    for rank, ((item, _), count) in enumerate(zip(ranking, exclusive, strict=True), 1):
        other_rank = other_ranks.get(item)
        if type(count) is not int or count < 0 or (other_rank is not None and count):
            raise ValueError("Exclusive hits must belong to an item present in only one list")
        rows.append({"rank": rank, "item": aliases[item], "other_rank": other_rank, "exclusive_hits": count})
    return rows


def snapshot(baseline, candidate, aliases, public_baseline, report):
    if public_baseline != [{"item": aliases[item], "count": count} for item, count in baseline]:
        raise ValueError("Baseline ranks, counts or product aliases differ from the public homepage")
    aliases = dict(aliases)
    register_first_view_items(aliases, candidate)
    paired = report["paired"]
    gained = paired["candidate_only_gained"]
    lost = paired["baseline_only_lost"]
    gains_by_rank = paired["gained_by_candidate_rank_1_to_10"]
    losses_by_rank = paired["lost_by_baseline_rank_1_to_10"]
    both = paired["both_hit"]
    base_hits = paired["baseline"]["hits_at_10"]
    candidate_hits = paired["candidate"]["hits_at_10"]
    if ((gained, lost) != (sum(gains_by_rank), sum(losses_by_rank))
            or (base_hits, candidate_hits) != (both + lost, both + gained)
            or paired["net_hits"] != gained - lost
            or paired["scored_visitors"] != both + gained + lost + paired["both_missed"]):
        raise ValueError("August per-rank hits do not reconcile with the paired visitor totals")
    return {
        "scored_visitors": paired["scored_visitors"], "both_hit": both, "both_missed": paired["both_missed"],
        "baseline_hits": base_hits, "candidate_hits": candidate_hits, "gained": gained, "lost": lost,
        "net_hits": paired["net_hits"], "hit_rate_change_percentage_points": paired["hit_rate_change_percentage_points"],
        "ci95_percentage_points": report["visitor_bootstrap"]["hit_rate_delta_95_percentage_points"],
        "baseline": public_rows(baseline, candidate, losses_by_rank, aliases),
        "candidate": public_rows(candidate, baseline, gains_by_rank, aliases),
    }


def export():
    report = json.loads(AUGUST_ACCEPTANCE.read_bytes())
    if (report["paired"] != json.loads(PAIR_REPORT.read_bytes())["paired"]
            or report["frozen_rankings"] != RANKING_FINGERPRINTS):
        raise ValueError("August acceptance receipt differs from the frozen rankings or paired score")
    home, legacy_aliases, browsing, baskets = load_product_inputs(SOURCE_RECEIPT)
    baseline, candidate = load_home_rankings()
    cards, aliases = product_cards_with_aliases(home, legacy_aliases, browsing, baskets, candidate=candidate)
    if cards != json.loads(PRODUCT_CARDS.read_bytes()):
        raise ValueError("Product detail aliases differ from the published recommendation cards")
    return snapshot(baseline, candidate, aliases, home["rankings"]["browse"], report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="rebuild and verify the public snapshot")
    args = parser.parse_args()
    data = export()
    if args.check:
        if data != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Published homepage comparison differs from the August receipt or product aliases")
    else:
        OUTPUT.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(f"August homepage comparison: {data['gained']} gained, {data['lost']} lost, {data['net_hits']:+} net.")


if __name__ == "__main__":
    main()
