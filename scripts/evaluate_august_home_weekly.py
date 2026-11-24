"""Group the frozen homepage first-view comparison by UTC calendar week in August."""
import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
import json

from scripts.evaluate_august_home_first_view_pair import (
    OUTPUT as MONTHLY_REPORT, study as monthly_study, summarize_rank_pairs,
)
from scripts.evaluate_cart_recommendations import ROOT, WINDOWS


OUTPUT = ROOT / "reports/mainline/recommendation_august_home_weekly_20261124.json"


def utc_day(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms // 1000, UTC).date()


def summarize_weeks(daily, start, end, monthly):
    """Clip Monday–Sunday weeks to [start, end) and reconcile every hit rank."""
    if any(day < start or day >= end for day in daily):
        raise ValueError("First-view date outside the declared development window")
    monthly_sixth = monthly["gained_by_candidate_rank_1_to_10"][5]
    weeks = []
    combined = Counter()
    while start < end:
        stop = min(start + timedelta(days=7 - start.weekday()), end)
        days = (stop - start).days
        pairs = Counter()
        for offset in range(days):
            pairs.update(daily.get(start + timedelta(days=offset), {}))
        combined.update(pairs)
        metrics = summarize_rank_pairs(pairs)
        sixth = metrics["gained_by_candidate_rank_1_to_10"][5]
        visitors = metrics["scored_visitors"]
        weeks.append({
            "start_date_utc": start.isoformat(), "end_date_exclusive_utc": stop.isoformat(),
            "days": days, "scored_visitors": visitors,
            "baseline_hits": metrics["baseline"]["hits_at_10"], "candidate_hits": metrics["candidate"]["hits_at_10"],
            "both_hit": metrics["both_hit"], "both_missed": metrics["both_missed"],
            "candidate_only_gained": metrics["candidate_only_gained"], "baseline_only_lost": metrics["baseline_only_lost"],
            "net_hits": metrics["net_hits"], "rank_6_candidate_only": sixth,
            "share_of_month_rank_6_gains": sixth / monthly_sixth if monthly_sixth else None,
            "rank_6_gains_per_1000_visitors": 1000 * sixth / visitors if visitors else None,
            "net_minus_rank_6_gains": metrics["net_hits"] - sixth,
        })
        start = stop
    if any(value != monthly[field] for field, value in summarize_rank_pairs(combined).items()):
        raise ValueError("Weekly visitor counts, paired outcomes or rank attributions differ from the month")
    return weeks


def study():
    reference = json.loads(MONTHLY_REPORT.read_bytes())
    daily = defaultdict(Counter)

    def observe(view_at, baseline_best, candidate_best):
        daily[utc_day(view_at)][baseline_best, candidate_best] += 1

    if monthly_study(observe=observe) != reference:
        raise ValueError("Replay of the frozen rankings, visitors or best ranks differs from the monthly report")
    monthly = reference["paired"]
    start, end = map(utc_day, WINDOWS["validation"])
    return {
        "study": "Weekly first-view gains and losses for two fixed homepage top tens",
        "role": reference["role"], "monthly_report": MONTHLY_REPORT.relative_to(ROOT).as_posix(),
        "utc_windows_start_inclusive_end_exclusive": reference["utc_windows_start_inclusive_end_exclusive"],
        "candidate_rank_item_votes_sha256": reference["candidate_rank_item_votes_sha256"],
        "scored_visitor_first_view_targets_sha256": monthly["scored_visitor_first_view_targets_sha256"],
        "paired_best_ranks_sha256": monthly["paired_best_ranks_sha256"],
        "grouping": "One observation per archived visitor, by earliest qualified August view in UTC. Calendar weeks run Monday to Sunday and are clipped to August.",
        "attribution": "Rank 6 counts candidate-only hits whose best match is rank 6. Net minus rank 6 gains subtracts those gains from the observed net with all other outcomes held fixed.",
        "month": {
            "scored_visitors": monthly["scored_visitors"], "baseline_hits": monthly["baseline"]["hits_at_10"],
            "candidate_hits": monthly["candidate"]["hits_at_10"], "both_hit": monthly["both_hit"],
            "both_missed": monthly["both_missed"], "candidate_only_gained": monthly["candidate_only_gained"],
            "baseline_only_lost": monthly["baseline_only_lost"], "net_hits": monthly["net_hits"],
            "rank_6_candidate_only": monthly["gained_by_candidate_rank_1_to_10"][5],
        },
        "weeks": summarize_weeks(daily, start, end, monthly), "limits": reference["limits"],
        "formal_scored_queries": 0, "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the published report")
    args = parser.parse_args()
    report = study()
    if args.check:
        if report != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed weekly results differ from the report")
    else:
        OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{report['month']['scored_visitors']:,} visitors in {len(report['weeks'])} UTC calendar weeks")


if __name__ == "__main__":
    main()
