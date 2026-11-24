"""Fit two homepage top tens before July and compare first views in July 2015."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import sqlite3

from scripts.c1_demo_model import RELEASE
from scripts.evaluate_august_home_browse import grouped_visitors, visitor_rows
from scripts.evaluate_august_home_first_view_pair import (
    OUTPUT as AUGUST_REPORT, paired_visitor_scores, train_first_view_ranking,
)
from scripts.evaluate_cart_recommendations import CONTRACT, DB, ROOT, digest_row, sha
from scripts.export_home_popularity import ranked_counts
from scripts.score_recommendation_acceptance import window_ms


OUTPUT = ROOT / "reports/mainline/recommendation_july_home_first_view_pair_20261124.json"
JULY_START = "2015-07-01T00:00:00Z"
NEW = "first_observed_in_july"


def train_browse_ranking(db, windows):
    counts = db.execute("""
        SELECT i, COUNT(*) FROM qualified
        WHERE role='train' AND t>=? AND t<? AND e='view' GROUP BY i
    """, windows["train"])
    return ranked_counts(dict(counts))


def ranking_digest(ranking):
    digest = hashlib.sha256()
    for rank, (item, count) in enumerate(ranking, 1):
        digest_row(digest, [rank, item, count])
    return digest.hexdigest()


def july_scores(db, windows, baseline, candidate):
    cohort = Counter()
    rows = visitor_rows(db, windows, scoring_role="train", new_history=NEW)

    def visitors():
        for row in grouped_visitors(rows, new_history=NEW):
            _, history, _, first_view, _ = row
            cohort[history] += 1
            if history == NEW and first_view is None:
                cohort["new_without_view"] += 1
            yield row

    paired = paired_visitor_scores(visitors(), baseline, candidate)
    if cohort[NEW] != paired["scored_visitors"] + cohort["new_without_view"]:
        raise ValueError("New visitors do not reconcile with the July scoring denominator")
    return paired, {
        "active": cohort["seen_in_train"] + cohort["seen_in_warmup_only"] + cohort[NEW],
        "seen_in_warmup_only": cohort["seen_in_warmup_only"], "seen_in_training": cohort["seen_in_train"],
        "first_observed_in_july": cohort[NEW], "new_without_view": cohort["new_without_view"],
        "new_with_view": paired["scored_visitors"],
    }


def concentration(paired):
    gains = paired["gained_by_candidate_rank_1_to_10"]
    peak = max(gains)
    total = paired["candidate_only_gained"]
    return {
        "top_candidate_ranks": [i for i, n in enumerate(gains, 1) if peak and n == peak],
        "gains_at_one_top_item": peak, "share_of_gains": peak / total if total else None,
        "other_gains": total - peak, "other_gains_minus_all_losses": paired["net_hits"] - peak,
    }


def study():
    roles = json.loads((ROOT / CONTRACT).read_bytes())["time_roles"]
    train_start, august_start = roles["train"]
    scope = {"warmup": roles["warmup"], "train": [train_start, JULY_START],
             "validation": [JULY_START, august_start]}
    windows = {name: window_ms(bounds) for name, bounds in scope.items()}
    if (windows["warmup"] != (1430611200000, 1430697600000)
            or windows["train"] != (1430697600000, 1435708800000)
            or windows["validation"] != (1435708800000, 1438387200000)):
        raise ValueError("Unexpected July study windows")

    august = json.loads(AUGUST_REPORT.read_bytes())
    release = json.loads((ROOT / RELEASE).read_bytes())
    receipt = next(dep for dep in release["external_dependencies"] if dep["path"] == DB)
    path = ROOT / DB
    if path.stat().st_size != receipt["bytes"] or sha(path) != receipt["sha256"]:
        raise ValueError("Qualified event ledger differs from its frozen release")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        baseline = train_browse_ranking(db, windows)
        candidate, training = train_first_view_ranking(db, windows)
        paired, cohort = july_scores(db, windows, baseline, candidate)
        # Identify shared items after the July comparison. The original August
        # candidate was fitted through July 31 and needs no August events to rebuild.
        august_training = {"warmup": windows["warmup"], "train": window_ms(roles["train"])}
        august_candidate, _ = train_first_view_ranking(db, august_training)
    august_digest = ranking_digest(august_candidate)
    if august_digest != august["candidate_rank_item_votes_sha256"]:
        raise ValueError("August item identities differ from the archived candidate")
    base_ranks = {item: i for i, (item, _) in enumerate(baseline, 1)}
    august_ranks = {item: i for i, (item, _) in enumerate(august_candidate, 1)}
    july_focus = concentration(paired)
    august_focus = concentration(august["paired"])
    july_leading_items = {candidate[i - 1][0] for i in july_focus["top_candidate_ranks"]}
    august_leading_items = {august_candidate[i - 1][0] for i in august_focus["top_candidate_ranks"]}
    return {
        "study": "Compare first-view and browse-event popularity on July new visitors",
        "role": "July 2015 retrospective development backtest",
        "utc_windows_start_inclusive_end_exclusive": scope,
        "event_ledger_roles": {"warmup": "warmup", "train": "train", "validation": "train"},
        "source_receipt": RELEASE, "contract": CONTRACT, "event_ledger_sha256": receipt["sha256"],
        "baseline_rule": "Rank all qualified fit-window view counts, ties by numeric item ID ascending.",
        "candidate_rule": "Exclude anyone with any warmup event. Each distinct item at a fit visitor's first view timestamp gets one vote. Break count ties by numeric item ID ascending.",
        "scoring_rule": "Exclude visitors seen in warmup or fit by any event and visitors without a July view. Score the first July view time once per visitor, retaining all distinct targets. A gain or loss is credited to the best matching rank of the only list that hit.",
        "training_first_views": training,
        "baseline_rank_item_counts_sha256": ranking_digest(baseline),
        "candidate_rank_item_votes_sha256": ranking_digest(candidate),
        "candidate_ranking": [
            {"rank": r, "training_first_view_visitors": votes, "baseline_rank": base_ranks.get(item),
             "august_candidate_rank": august_ranks.get(item)} for r, (item, votes) in enumerate(candidate, 1)
        ],
        "baseline_view_counts_in_rank_order": [count for _, count in baseline],
        "shared_items_in_top_ten": sum(item in base_ranks for item, _ in candidate),
        "july_cohort": cohort, "paired": paired, "gain_concentration": july_focus,
        "august_comparison": {
            "archived_report": AUGUST_REPORT.relative_to(ROOT).as_posix(),
            "verified_candidate_rank_item_votes_sha256": august_digest,
            "scored_visitors": august["paired"]["scored_visitors"],
            "baseline_hits": august["paired"]["baseline"]["hits_at_10"],
            "candidate_hits": august["paired"]["candidate"]["hits_at_10"],
            "gained": august["paired"]["candidate_only_gained"], "lost": august["paired"]["baseline_only_lost"],
            "net_hits": august["paired"]["net_hits"],
            "hit_rate_change_percentage_points": august["paired"]["hit_rate_change_percentage_points"],
            "gain_concentration": august_focus,
            "shares_a_leading_gain_item_with_july": bool(august_leading_items & july_leading_items),
        },
        "limits": august["limits"], "formal_scored_queries": 0,
        "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the published report")
    args = parser.parse_args()
    report = study()
    if args.check:
        if report != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed July results differ from the report")
    else:
        OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    score = report["paired"]
    print(f"{score['scored_visitors']:,} July visitors, baseline {score['baseline']['hits_at_10']:,}, "
          f"candidate {score['candidate']['hits_at_10']:,}, net {score['net_hits']:+,}")


if __name__ == "__main__":
    main()
