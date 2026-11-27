"""Evaluate a last-view slot on the frozen August returning-visitor homepage cohort."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import sqlite3

from scripts.c1_demo_model import C1DemoModel, RELEASE
from scripts.evaluate_august_home_browse import load_study_inputs
from scripts.evaluate_august_home_first_view_pair import summarize_rank_pairs
from scripts.evaluate_august_returning_home import (
    OUTPUT as BASELINE_REPORT, STRATEGIES, candidate_ranking, returning_visitors,
)
from scripts.evaluate_cart_popular_fill import first_hit
from scripts.evaluate_cart_recommendations import CONTRACT, DB, ROOT, TOP_K, digest_row
from scripts.evaluate_recency_slot import reserve_slot
from scripts.score_home_first_view_acceptance import BOOTSTRAP
from scripts.score_recommendation_acceptance import visitor_interval


OUTPUT = ROOT / "reports/mainline/recommendation_august_returning_home_slot_20261127.json"
ACTIONS = ("replaced_rank_10", "already_in_top_ten", "no_prior_view")


def group_summary(pairs):
    result = summarize_rank_pairs(pairs)
    return {
        "scored_visitors": result["scored_visitors"], "baseline_hits": result["baseline"]["hits_at_10"],
        "candidate_hits": result["candidate"]["hits_at_10"], "gained": result["candidate_only_gained"],
        "lost": result["baseline_only_lost"], "net_hits": result["net_hits"],
    }


def rank_summary(pairs):
    overall = summarize_rank_pairs(pairs)
    n = overall["scored_visitors"]
    for column, arm in enumerate(("baseline", "candidate")):
        positions = Counter()
        for ranks, count in pairs.items():
            positions[ranks[column]] += count
        counts = [positions[r] for r in range(1, TOP_K + 1)]
        overall[arm]["first_hit_counts_rank_1_to_10"] = counts
        overall[arm]["mrr_at_10"] = sum(count / rank for rank, count in enumerate(counts, 1)) / n if n else None
    overall["mrr_at_10_delta"] = overall["candidate"]["mrr_at_10"] - overall["baseline"]["mrr_at_10"] if n else None
    return overall


def hit_rate_interval(clusters):
    if not clusters:
        return None
    uncertainty = {**BOOTSTRAP, **visitor_interval(clusters, BOOTSTRAP)}
    uncertainty["hit_rate_delta_95_percentage_points"] = [
        100 * bound for bound in uncertainty["hit_rate_delta_95_percentile"]
    ]
    return uncertainty


def score_visitors(visitors, popular, model):
    """Score one first-view target set per visitor against two ten-item homepages."""
    if len(popular) != TOP_K or len(set(popular)) != TOP_K:
        raise ValueError("Expected ten distinct homepage popularity items")
    roster, previous_pairs, slot_pairs = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    pairs = Counter()
    actions = {action: Counter() for action in ACTIONS}
    strategies = {strategy: Counter() for strategy in STRATEGIES}
    cache, clusters = {}, {}
    repeat = dict.fromkeys(("visitors", "already_hit_by_baseline", "newly_hit"), 0)
    for visitor, _, seed, first_view, targets in visitors:
        if visitor in clusters or not targets:
            raise ValueError("Expected one nonempty first-view target set per visitor")
        if seed not in cache:
            strategy, baseline, _ = candidate_ranking(seed, popular, model)
            revised = reserve_slot(baseline, seed)
            if (len(baseline) != TOP_K or len(set(baseline)) != TOP_K or len(revised) != TOP_K
                    or len(set(revised)) != TOP_K or baseline[:-1] != revised[:-1]):
                raise ValueError("Slot rule must preserve nine positions and ten distinct items")
            if seed is None:
                action = "no_prior_view"
            elif seed in baseline:
                action = "already_in_top_ten"
            else:
                action = "replaced_rank_10"
            cache[seed] = strategy, baseline, revised, action
        strategy, baseline, revised, action = cache[seed]
        old, new = first_hit(baseline, targets), first_hit(revised, targets)
        pairs[old, new] += 1
        actions[action][old, new] += 1
        strategies[strategy][old, new] += 1
        clusters[visitor] = (1, int(new is not None) - int(old is not None))
        if seed in targets:
            repeat["visitors"] += 1
            repeat["already_hit_by_baseline"] += old is not None
            repeat["newly_hit"] += old is None and new is not None
        record = [visitor, first_view, sorted(targets, key=int)]
        digest_row(roster, record)
        digest_row(previous_pairs, [*record, first_hit(popular, targets), old])
        digest_row(slot_pairs, [*record, old, new])

    return {
        "overall": rank_summary(pairs),
        "by_slot_action": {action: group_summary(counts) for action, counts in actions.items()},
        "by_baseline_strategy": {strategy: group_summary(counts) for strategy, counts in strategies.items()},
        "repeat_views": repeat, "visitor_bootstrap": hit_rate_interval(clusters),
        "scored_visitor_first_view_targets_sha256": roster.hexdigest(),
        "previous_paired_best_ranks_sha256": previous_pairs.hexdigest(),
        "paired_best_ranks_sha256": slot_pairs.hexdigest(),
    }


def study():
    popular, scope, windows = load_study_inputs()
    model = C1DemoModel.load(ROOT)
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        result = score_visitors(returning_visitors(db, windows), [item for item, _ in popular], model)
    previous = json.loads(BASELINE_REPORT.read_bytes())
    if (result["scored_visitor_first_view_targets_sha256"] != previous["scored_visitor_first_view_targets_sha256"]
            or result["previous_paired_best_ranks_sha256"] != previous["paired_best_ranks_sha256"]
            or result["repeat_views"]["visitors"] != previous["coverage"]["visitors_revisiting_prior_item"]):
        raise ValueError("Returning visitor roster, base ranks or repeat views differ from the previous report")
    return {
        "study": "Keep rank ten for the last pre-August viewed item on returning-visitor homepages",
        "role": "2015-08 development backtest", "utc_windows_start_inclusive_end_exclusive": scope,
        "source_receipt": RELEASE, "contract": CONTRACT, "baseline_report": BASELINE_REPORT.relative_to(ROOT).as_posix(),
        "rules": {
            "roster_seed_target": "Use the same returning visitors, last pre-August view and all distinct items at their first August view timestamp as in the baseline report.",
            "baseline": "Frozen C1 positive cooccurrence items filled to ten from the fixed popularity list; use the whole popularity list when the prior baseline had no C1 pair or no prior view.",
            "candidate": "Only replace the tenth item when the seed exists and is absent from the baseline ten. Otherwise use the baseline unchanged.",
            "eligibility": "Every seed has a qualified view strictly before August and is therefore in the historical candidate catalog, including warmup items with no fitted C1 statistics.",
            "metrics": "Each visitor contributes one observation. Use the best matching rank across their distinct targets. Reciprocal rank is zero for a miss. The percentile interval resamples paired visitors with replacement.",
        },
        **result, "limits": previous["limits"], "new_model_fits": 0, "formal_scored_queries": 0,
        "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="recompute and compare the published report")
    args = parser.parse_args()
    result = study()
    if args.check:
        if result != json.loads(OUTPUT.read_bytes()):
            raise SystemExit("Recomputed August slot results differ from the published report")
    else:
        OUTPUT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    overall = result["overall"]
    print(f"{overall['scored_visitors']:,} visitors, "
          f"{overall['baseline']['hits_at_10']:,} to {overall['candidate']['hits_at_10']:,} hits, "
          f"+{overall['candidate_only_gained']:,} / -{overall['baseline_only_lost']:,}")


if __name__ == "__main__":
    main()
