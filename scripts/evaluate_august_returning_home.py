"""Compare fixed homepage popularity with a pre-August last-view C1 list for returning visitors."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
from itertools import groupby
import json
from operator import itemgetter
import sqlite3

from scripts.c1_demo_model import C1DemoModel, RELEASE
from scripts.evaluate_august_home_browse import HISTORY, OUTPUT as HOME_REPORT, load_study_inputs
from scripts.evaluate_august_home_first_view_pair import summarize_rank_pairs
from scripts.evaluate_cart_recommendations import CONTRACT, DB, ROOT, TOP_K, digest_row
from scripts.score_home_first_view_acceptance import BOOTSTRAP
from scripts.score_recommendation_acceptance import visitor_interval


OUTPUT = ROOT / "reports/mainline/recommendation_august_returning_home_20261127.json"
STRATEGIES = ("personalized", "no_pair", "no_history")


def returning_visitors(db, windows, *, scoring_role="validation"):
    """One row per returning visitor with a view in the scoring window, in visitor-key order."""
    if scoring_role not in ("train", "validation"):
        raise ValueError("Only development ledger roles can supply first-view queries")
    rows = db.execute("""
        WITH scoring_month AS MATERIALIZED (
            SELECT v, MIN(t) AS first_view FROM qualified
            WHERE role=? AND t>=? AND t<? AND e='view'
            GROUP BY v
        ), prior_activity AS MATERIALIZED (
            SELECT a.*, CASE WHEN EXISTS (
                SELECT 1 FROM qualified p WHERE p.v=a.v AND p.role='train' AND p.t>=? AND p.t<?
            ) THEN 'seen_in_train' WHEN EXISTS (
                SELECT 1 FROM qualified p WHERE p.v=a.v AND p.role='warmup' AND p.t>=? AND p.t<?
            ) THEN 'seen_in_warmup_only' END AS history
            FROM scoring_month a
        ), returning_cohort AS MATERIALIZED (
            SELECT a.*, (
                SELECT p.i FROM qualified p WHERE p.v=a.v AND p.e='view' AND (
                    (p.role='warmup' AND p.t>=? AND p.t<?) OR (p.role='train' AND p.t>=? AND p.t<?)
                )
                ORDER BY p.t DESC, CAST(p.i AS INTEGER) ASC LIMIT 1
            ) AS seed
            FROM prior_activity a WHERE a.history IS NOT NULL
        )
        SELECT r.v, r.history, r.seed, r.first_view, q.i FROM returning_cohort r
        JOIN qualified q ON q.v=r.v AND q.t=r.first_view AND q.e='view' AND q.role=?
        ORDER BY r.v
    """, (scoring_role, *windows["validation"], *windows["train"], *windows["warmup"],
          *windows["warmup"], *windows["train"], scoring_role))
    for visitor, events in groupby(rows, key=itemgetter(0)):
        _, history, seed, first_view, item = next(events)
        yield visitor, history, seed, first_view, {item, *(row[4] for row in events)}


def candidate_ranking(seed, baseline, model):
    """Preserve positive C1 ranks, then fill unoccupied slots from the exact published baseline."""
    if seed is None:
        return "no_history", baseline, 0
    try:
        recommendations = model.recommend(seed)["recommendations"]
    except KeyError as error:
        # A warm-up item may have no entry in the training catalog.
        if error.args != (seed,):
            raise
        return "no_pair", baseline, 0
    shared = [row["item_id"] for row in recommendations if row["source"] == "cooccurrence"]
    if not shared:
        return "no_pair", baseline, 0
    ranked = (shared + [item for item in baseline if item not in shared])[:TOP_K]
    return "personalized", ranked, len(shared)


def score_visitors(visitors, baseline, model):
    if len(baseline) != TOP_K or len(set(baseline)) != TOP_K:
        raise ValueError("Baseline must contain ten distinct homepage items")
    roster_digest, pair_digest = hashlib.sha256(), hashlib.sha256()
    pairs = Counter()
    strategy_pairs = {group: Counter() for group in STRATEGIES}
    history_counts = dict.fromkeys(HISTORY[:2], 0)
    cache, clusters = {}, {}
    changed = multi_target = revisited_seed = 0
    for visitor, history, seed, first_view, targets in visitors:
        if visitor in clusters or not targets:
            raise ValueError("Expected one nonempty first-view target set per visitor")
        if seed not in cache:
            cache[seed] = candidate_ranking(seed, baseline, model)
        group, candidate, _ = cache[seed]
        if len(candidate) != TOP_K or len(set(candidate)) != TOP_K:
            raise ValueError("Candidate must contain ten distinct homepage items")
        best = tuple(next((rank for rank, item in enumerate(ranking, 1) if item in targets), None)
                     for ranking in (baseline, candidate))
        record = [visitor, first_view, sorted(targets, key=int)]
        digest_row(roster_digest, record)
        digest_row(pair_digest, [*record, *best])
        pairs[best] += 1
        strategy_pairs[group][best] += 1
        history_counts[history] += 1
        changed += candidate != baseline
        multi_target += len(targets) > 1
        revisited_seed += seed is not None and seed in targets
        clusters[visitor] = (1, int(best[1] is not None) - int(best[0] is not None))
    overall = summarize_rank_pairs(pairs)
    strata = {group: summarize_rank_pairs(group_pairs) for group, group_pairs in strategy_pairs.items()}
    scored = overall["scored_visitors"]
    personalized = strata["personalized"]["scored_visitors"]
    uncertainty = None
    if scored:
        uncertainty = {**BOOTSTRAP, **visitor_interval(clusters, BOOTSTRAP)}
        uncertainty["hit_rate_delta_95_percentage_points"] = [
            bound * 100 for bound in uncertainty["hit_rate_delta_95_percentile"]]
    return {
        "overall": overall, "by_strategy": strata, "by_observed_history": history_counts,
        "coverage": {
            "visitors_with_prior_view": scored - strata["no_history"]["scored_visitors"],
            "visitors_with_cooccurrence": personalized, "cooccurrence_rate": personalized / scored if scored else None,
            "visitors_with_changed_ranking": changed, "visitors_with_full_candidate_top_ten": scored,
            "multiple_first_view_items": multi_target, "visitors_revisiting_prior_item": revisited_seed,
        },
        "scored_visitor_first_view_targets_sha256": roster_digest.hexdigest(),
        "paired_best_ranks_sha256": pair_digest.hexdigest(), "visitor_bootstrap": uncertainty,
    }


def study():
    ranking, scope, windows = load_study_inputs()
    model = C1DemoModel.load(ROOT)
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        result = score_visitors(returning_visitors(db, windows), [item for item, _ in ranking], model)
    previous = json.loads(HOME_REPORT.read_bytes())
    expected = {group: previous["by_observed_history"][group]["with_view"] for group in HISTORY[:2]}
    if result["by_observed_history"] != expected:
        raise ValueError("Returning visitor counts differ from the archived August homepage roster")
    return {
        "study": "Last observed view for returning homepage visitors versus fixed browse popularity",
        "role": "2015-08 development backtest", "utc_windows_start_inclusive_end_exclusive": scope,
        "source_receipt": RELEASE, "contract": CONTRACT,
        "baseline_report": HOME_REPORT.relative_to(ROOT).as_posix(), "homepage_snapshot": previous["homepage_snapshot"],
        "rules": {
            "roster": "Any qualified warmup or training event; at least one August view. One observation per visitor.",
            "seed": "Last qualified view strictly before August in warmup or train. Select the smallest numeric item ID among distinct tied items before consulting the model.",
            "baseline": "Fixed published training browse popularity top ten.",
            "candidate": "Frozen C1 positive cooccurrence items for the seed, ordered by shared sessions, training views, then numeric ID. Fill to ten from the fixed baseline, skipping duplicates; the seed is allowed as a popular item.",
            "fallback": "No prior view (no_history), or a seed with no positive training pair (no_pair), uses the full baseline.",
            "target": "Any distinct item viewed at the visitor's earliest August view timestamp. Record the best matching rank; count one hit per visitor per arm.",
            "uncertainty": "Resample paired visitors with replacement. Report the percentile interval of candidate minus baseline hit rate.",
        },
        **result,
        "limits": "Offline first-view overlap for observed returning visitors. The ledger has no homepage exposure, referral or conversion attribution.",
        "new_model_fits": 0, "formal_scored_queries": 0, "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the archived report")
    args = parser.parse_args()
    result = study()
    if args.check:
        if result != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed returning-visitor results differ from the report")
    else:
        OUTPUT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    overall = result["overall"]
    print(f"{overall['scored_visitors']:,} visitors, baseline {overall['baseline']['hits_at_10']:,}, "
          f"candidate {overall['candidate']['hits_at_10']:,}, net {overall['net_hits']:+,}")


if __name__ == "__main__":
    main()
