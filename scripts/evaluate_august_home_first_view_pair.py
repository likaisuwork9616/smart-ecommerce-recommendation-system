"""Compare two frozen homepage top tens on the August new-visitor first-view roster."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
from itertools import groupby
import json
from operator import itemgetter
import sqlite3

from scripts.evaluate_august_home_browse import (
    OUTPUT as BASELINE_REPORT, grouped_visitors, load_study_inputs, visitor_rows,
)
from scripts.evaluate_cart_recommendations import DB, ROOT, TOP_K, digest_row
from scripts.export_home_popularity import ranked_counts


OUTPUT = ROOT / "reports/mainline/recommendation_august_home_first_view_pair_20261124.json"


def train_first_view_ranking(db, windows):
    rows = db.execute("""
        WITH first_view AS (
            SELECT v, MIN(t) AS first_t FROM qualified
            WHERE role='train' AND t>=? AND t<? AND e='view'
              AND v NOT IN (SELECT v FROM qualified WHERE role='warmup' AND t>=? AND t<?)
            GROUP BY v
        )
        SELECT f.v, q.i FROM first_view f JOIN qualified q
          ON q.v=f.v AND q.t=f.first_t AND q.role='train' AND q.e='view'
        ORDER BY f.v
    """, (*windows["train"], *windows["warmup"]))
    votes = Counter()
    visitors = multi_item = 0
    for _, first_views in groupby(rows, key=itemgetter(0)):
        items = {item for _, item in first_views}
        votes.update(items)
        visitors += 1
        multi_item += len(items) > 1

    return ranked_counts(votes), {
        "visitors_with_first_view": visitors, "visitors_with_multiple_first_items": multi_item,
        "distinct_first_view_items": len(votes), "visitor_item_votes": sum(votes.values()),
    }


def paired_scores(rows, baseline, candidate):
    base_rank = {item: rank for rank, (item, _) in enumerate(baseline, 1)}
    candidate_rank = {item: rank for rank, (item, _) in enumerate(candidate, 1)}
    if any(len(items) != TOP_K for items in (baseline, candidate, base_rank, candidate_rank)):
        raise ValueError("Each ranking must contain ten distinct products")
    roster = hashlib.sha256()
    observations = hashlib.sha256()
    outcomes = Counter()
    gained_by_rank = Counter()
    lost_by_rank = Counter()
    for visitor, _, _, view_at, targets in grouped_visitors(rows):
        if not targets:
            continue
        baseline_best = min((base_rank[item] for item in targets if item in base_rank), default=None)
        candidate_best = min((candidate_rank[item] for item in targets if item in candidate_rank), default=None)
        record = [visitor, view_at, sorted(targets, key=int)]
        digest_row(roster, record)
        digest_row(observations, [*record, baseline_best, candidate_best])
        outcomes[baseline_best is not None, candidate_best is not None] += 1
        if baseline_best is None and candidate_best is not None:
            gained_by_rank[candidate_best] += 1
        elif baseline_best is not None and candidate_best is None:
            lost_by_rank[baseline_best] += 1

    scored = sum(outcomes.values())
    both = outcomes[True, True]
    lost, gained = outcomes[True, False], outcomes[False, True]
    base_hits, candidate_hits = both + lost, both + gained
    return {
        "scored_visitors": scored, "scored_visitor_first_view_targets_sha256": roster.hexdigest(),
        "paired_best_ranks_sha256": observations.hexdigest(),
        "both_hit": both, "candidate_only_gained": gained, "baseline_only_lost": lost,
        "both_missed": outcomes[False, False], "net_hits": gained - lost,
        "gained_by_candidate_rank_1_to_10": [gained_by_rank[r] for r in range(1, TOP_K + 1)],
        "lost_by_baseline_rank_1_to_10": [lost_by_rank[r] for r in range(1, TOP_K + 1)],
        "baseline": {"hits_at_10": base_hits, "hit_rate_at_10": base_hits / scored if scored else None},
        "candidate": {"hits_at_10": candidate_hits, "hit_rate_at_10": candidate_hits / scored if scored else None},
        "hit_rate_change_percentage_points": 100 * (gained - lost) / scored if scored else None,
    }


def study():
    baseline, scope, windows = load_study_inputs()
    previous = json.loads(BASELINE_REPORT.read_bytes())
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        candidate, training = train_first_view_ranking(db, windows)
        result = paired_scores(visitor_rows(db, windows), baseline, candidate)
    if (result["scored_visitors"] != previous["scored_visitors"]
            or result["scored_visitor_first_view_targets_sha256"] != previous["scored_visitor_first_view_targets_sha256"]
            or result["baseline"]["hits_at_10"] != previous["hit_at_k"]["10"]["hits"]):
        raise ValueError("August visitors, targets or baseline outcomes differ from the archived study")

    base_ranks = {item: rank for rank, (item, _) in enumerate(baseline, 1)}
    aliases = dict(baseline)
    public_ranking = []
    ranking_digest = hashlib.sha256()
    for rank, (item, votes) in enumerate(candidate, 1):
        digest_row(ranking_digest, [rank, item, votes])
        public_ranking.append({
            "rank": rank, "training_first_view_visitors": votes,
            "baseline_rank": base_ranks.get(item), "baseline_public_alias": aliases.get(item),
        })
    return {
        "study": "Training first-view visitor popularity vs. homepage browse event popularity",
        "role": "August 2015 development backtest", "utc_windows_start_inclusive_end_exclusive": scope,
        "baseline_report": BASELINE_REPORT.relative_to(ROOT).as_posix(), "homepage_snapshot": previous["homepage_snapshot"],
        "training_rule": "Only train visitors with a view and no qualified warmup event. Each distinct item at the first view timestamp receives one vote from that visitor. Sort by votes descending, then numeric item ID ascending. Freeze the top ten before August.",
        "training": training, "candidate_ranking": public_ranking, "candidate_rank_item_votes_sha256": ranking_digest.hexdigest(),
        "shared_items_in_top_ten": sum(item in base_ranks for item, _ in candidate),
        "scoring_rule": "One observation per archived August visitor. Any first-view item in a top ten is a hit. Fingerprint ordered visitor, first view time, numerically sorted targets, then best rank for each arm (null for miss).",
        "paired": result, "limits": previous["limits"], "formal_scored_queries": 0,
        "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the archived report")
    args = parser.parse_args()
    result = study()
    if args.check:
        if result != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed paired results differ from the report")
    else:
        OUTPUT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    scored = result["paired"]
    print(f"{scored['scored_visitors']:,} visitors, baseline {scored['baseline']['hits_at_10']:,}, "
          f"candidate {scored['candidate']['hits_at_10']:,}, net {scored['net_hits']:+,}")


if __name__ == "__main__":
    main()
