"""Replay the homepage acceptance scorer on the archived August development cohort."""
import argparse
from collections import Counter
from contextlib import closing
import json
import sqlite3

from scripts.evaluate_august_home_browse import (
    HISTORY, OUTPUT as COHORT_REPORT, grouped_visitors, load_study_inputs, visitor_rows,
)
from scripts.evaluate_august_home_first_view_pair import OUTPUT as PAIR_REPORT
from scripts.evaluate_cart_recommendations import DB, ROOT
from scripts.score_home_first_view_acceptance import FROZEN_COMMIT, RANKING_FINGERPRINTS, frozen_rankings, score_home


OUTPUT = ROOT / "reports/mainline/recommendation_home_first_view_acceptance_august_20261124.json"


def study():
    cohort = json.loads(COHORT_REPORT.read_bytes())
    archive = json.loads(PAIR_REPORT.read_bytes())
    _, scope, windows = load_study_inputs()
    if any(scope != report["utc_windows_start_inclusive_end_exclusive"] for report in (cohort, archive)):
        raise ValueError("August replay windows differ from the archived studies")
    by_history = Counter()

    def eligible_visitors(db):
        for visitor, history, _, view_at, targets in grouped_visitors(visitor_rows(db, windows)):
            by_history[history, view_at is not None] += 1
            if history == HISTORY[-1] and view_at is not None:
                yield visitor, view_at, targets

    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        baseline, candidate = frozen_rankings(db, windows)
        results = score_home(eligible_visitors(db), baseline, candidate, expected_visitors=cohort["scored_visitors"])

    for history in HISTORY:
        expected = cohort["by_observed_history"][history]
        if (by_history[history, True], by_history[history, False]) != (
                expected["with_view"], expected["without_view"]):
            raise ValueError("Eligibility counts differ from the archived August cohort")
    if results["paired"] != archive["paired"]:
        raise ValueError("August visitor targets, paired best ranks or hit counts differ from the archive")
    return {
        "role": "August 2015 development replay of the homepage acceptance scorer",
        "utc_windows_start_inclusive_end_exclusive": scope,
        "cohort_reference": COHORT_REPORT.relative_to(ROOT).as_posix(),
        "archived_pair": PAIR_REPORT.relative_to(ROOT).as_posix(),
        "frozen_ranking_commit": FROZEN_COMMIT, "frozen_rankings": RANKING_FINGERPRINTS,
        "previously_observed_visitors": sum(
            count for (history, _), count in by_history.items() if history != HISTORY[-1]
        ),
        "new_visitors_without_view": by_history[HISTORY[-1], False],
        **results,
        "homepage_default": "original browse popularity",
        "gate_interpretation": "Development replay verifies the scoring rules. Only an independent roster informs adoption.",
        "formal_acceptance": "pending independent roster",
        "formal_scored_visitors": 0, "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and check the full published report")
    args = parser.parse_args()
    report = study()
    if args.check:
        if report != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("August acceptance replay differs from the published report")
    else:
        OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    paired = report["paired"]
    lo, hi = report["visitor_bootstrap"]["hit_rate_delta_95_percentage_points"]
    print(f"August development: {paired['scored_visitors']:,} visitors, "
          f"gained {paired['candidate_only_gained']}, lost {paired['baseline_only_lost']}, "
          f"net {paired['net_hits']:+}, paired 95% interval [{lo:+.6f}, {hi:+.6f}] percentage points")


if __name__ == "__main__":
    main()
