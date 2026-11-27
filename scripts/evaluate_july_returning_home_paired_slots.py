"""Refit both last-view-slot homepages before July and score July returning visitors."""
import argparse
from contextlib import closing
import json
import sqlite3

from scripts.c1_demo_model import RELEASE
from scripts.evaluate_august_returning_home import returning_visitors
from scripts.evaluate_august_returning_home_paired_slots import OUTPUT as AUGUST_REPORT, score_visitors
from scripts.evaluate_cart_recommendations import CONTRACT, DB, ROOT, sha
from scripts.evaluate_july_home_first_view_pair import JULY_START, OUTPUT as JULY_HOME_REPORT
from scripts.fit_july_returning_home import fit_model
from scripts.score_recommendation_acceptance import window_ms


OUTPUT = ROOT / "reports/mainline/recommendation_july_returning_home_paired_slots_20261127.json"


def study(*, score=score_visitors):
    july = json.loads(JULY_HOME_REPORT.read_bytes())
    roles = json.loads((ROOT / CONTRACT).read_bytes())["time_roles"]
    scope = {"warmup": roles["warmup"], "train": [roles["train"][0], JULY_START],
             "validation": [JULY_START, roles["train"][1]]}
    if scope != july["utc_windows_start_inclusive_end_exclusive"]:
        raise ValueError("Cutoffs differ from the archived July development study")
    windows = {name: window_ms(bounds) for name, bounds in scope.items()}

    source = json.loads((ROOT / RELEASE).read_bytes())
    receipt = next(row for row in source["external_dependencies"] if row["path"] == DB)
    path = ROOT / DB
    if path.stat().st_size != receipt["bytes"] or sha(path) != receipt["sha256"]:
        raise ValueError("Qualified event ledger differs from the frozen source")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        popular, model, training = fit_model(db, windows["train"])
        if training["baseline_rank_item_counts_sha256"] != july["baseline_rank_item_counts_sha256"]:
            raise ValueError("Refitted popularity differs from the archived pre-July top ten")
        results = score(returning_visitors(db, windows, scoring_role="train"), popular, model)
        visitors_with_view = db.execute("""
            SELECT COUNT(DISTINCT v) FROM qualified
            WHERE role='train' AND t>=? AND t<? AND e='view'
        """, windows["validation"]).fetchone()[0]

    july_cohort = july["july_cohort"]
    returning_active = july_cohort["seen_in_warmup_only"] + july_cohort["seen_in_training"]
    scored = results["overall"]["scored_visitors"]
    if scored != visitors_with_view - july_cohort["new_with_view"] or scored > returning_active:
        raise ValueError("Returning visitors do not reconcile with July first-view and active visitor counts")

    august = json.loads(AUGUST_REPORT.read_bytes())
    comparison = august["overall"]
    return {
        "study": "July returning visitors: popularity versus co-browse with the same last-view slot",
        "role": "July 2015 retrospective development backtest",
        "utc_windows_start_inclusive_end_exclusive": scope,
        "event_ledger_roles": {"warmup": "warmup", "train": "train", "validation": "train"},
        "source_receipt": RELEASE, "contract": CONTRACT, "event_ledger_sha256": receipt["sha256"],
        "july_home_report": JULY_HOME_REPORT.relative_to(ROOT).as_posix(),
        "training": training,
        "rules": {
            "cohort": "Any qualified event before July and a July view. Score each visitor once against all distinct items at their earliest July view timestamp.",
            "seed": "Last qualified view strictly before July, including warmup. At a tied timestamp choose the smallest numeric item ID.",
            "baseline_before_slot": "Training browse popularity top ten ranked by qualified view count then ascending numeric item ID.",
            "candidate_before_slot": "Positive co-browse neighbors of the seed ranked by shared training sessions, then training popularity and numeric item ID. Fill remaining seats from popularity without duplicates. No positive pair or no seed gives the popularity list.",
            "shared_slot": august["rules"]["shared_slot"], "metrics": august["rules"]["metrics"],
        },
        "july_cohort": {
            "active_returning": returning_active, "returning_with_view": scored,
            "returning_without_view": returning_active - scored, "all_visitors_with_view": visitors_with_view,
            "new_with_view": july_cohort["new_with_view"],
        },
        **results,
        "august_comparison": {
            "archived_report": AUGUST_REPORT.relative_to(ROOT).as_posix(),
            "scored_visitors": comparison["scored_visitors"],
            "baseline_hits": comparison["baseline"]["hits_at_10"], "candidate_hits": comparison["candidate"]["hits_at_10"],
            "gained": comparison["candidate_only_gained"], "lost": comparison["baseline_only_lost"],
            "net_hits": comparison["net_hits"], "hit_rate_change_percentage_points": comparison["hit_rate_change_percentage_points"],
            "hit_rate_delta_95_percentage_points": august["visitor_bootstrap"]["hit_rate_delta_95_percentage_points"],
            "baseline_mrr_at_10": comparison["baseline"]["mrr_at_10"], "candidate_mrr_at_10": comparison["candidate"]["mrr_at_10"],
            "mrr_at_10_delta": comparison["mrr_at_10_delta"],
        },
        "limits": august["limits"], "formal_scored_queries": 0, "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the archived July report")
    args = parser.parse_args()
    report = study()
    if args.check:
        if report != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed July paired slot results differ from the published report")
    else:
        OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    score = report["overall"]
    print(f"{score['scored_visitors']:,} July visitors, {score['baseline']['hits_at_10']:,} to "
          f"{score['candidate']['hits_at_10']:,} hits, net {score['net_hits']:+,}")


if __name__ == "__main__":
    main()
