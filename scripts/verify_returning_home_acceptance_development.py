"""Replay the returning-home acceptance scorer on July, August and synthetic development rosters."""
import argparse
import json

from scripts.evaluate_august_returning_home_paired_slots import OUTPUT as AUGUST, study as august_study
from scripts.evaluate_cart_recommendations import ROOT
from scripts.evaluate_july_returning_home_paired_slots import OUTPUT as JULY, study as july_study
from scripts.returning_home_acceptance_boundary_cases import synthetic_results
from scripts.score_returning_home_acceptance import POLICY_COMMIT, score_returning


OUTPUT = ROOT / "reports/mainline/recommendation_returning_home_acceptance_development_20261127.json"


def replay(archive_path, study):
    archived = json.loads(archive_path.read_bytes())
    calculated = study(score=score_returning)
    for field, expected in archived.items():
        if calculated[field] != expected:
            raise ValueError(f"{archive_path.name}: recomputation differs in {field}")
    if calculated["all_gates_pass"] is not True:
        raise ValueError(f"{archive_path.name}: the published results satisfied all three development thresholds")
    overall = calculated["overall"]
    return {
        "archive": archive_path.relative_to(ROOT).as_posix(),
        "utc_windows_start_inclusive_end_exclusive": calculated["utc_windows_start_inclusive_end_exclusive"],
        "scored_visitor_first_view_targets_sha256": calculated["scored_visitor_first_view_targets_sha256"],
        "paired_best_ranks_sha256": calculated["paired_best_ranks_sha256"],
        "scored_visitors": overall["scored_visitors"],
        "both_hit": overall["both_hit"], "candidate_only_gained": overall["candidate_only_gained"],
        "baseline_only_lost": overall["baseline_only_lost"], "both_missed": overall["both_missed"],
        "net_hits": overall["net_hits"],
        "baseline": overall["baseline"], "candidate": overall["candidate"],
        "hit_rate_change_percentage_points": overall["hit_rate_change_percentage_points"],
        "visitor_bootstrap": calculated["visitor_bootstrap"],
        "mrr_at_10_delta": overall["mrr_at_10_delta"],
        "gates": calculated["gates"], "all_gates_pass": calculated["all_gates_pass"],
    }


def study():
    return {
        "role": "July and August 2015 development replays and synthetic gate checks",
        "policy": "docs/HOME_RETURNING_VISITOR_ACCEPTANCE.md",
        "policy_commit": POLICY_COMMIT,
        "months": {"2015-07": replay(JULY, july_study), "2015-08": replay(AUGUST, august_study)},
        "synthetic_boundaries": synthetic_results(),
        "homepage_default": "original browse popularity",
        "formal_acceptance": "pending independent roster",
        "formal_scored_visitors": 0, "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the full archived replay")
    args = parser.parse_args()
    report = study()
    if args.check:
        if report != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Returning-home acceptance replay differs from the published report")
    else:
        OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    for month, row in report["months"].items():
        print(f"{month}: {row['scored_visitors']:,} visitors, net {row['net_hits']:+,}, "
              f"MRR delta {row['mrr_at_10_delta']:+.5f}, all development thresholds met")


if __name__ == "__main__":
    main()
