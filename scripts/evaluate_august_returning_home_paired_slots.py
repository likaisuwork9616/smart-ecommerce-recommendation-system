"""Compare popularity and co-browse homepages using the same last-view slot on August returners."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import sqlite3

from scripts.c1_demo_model import C1DemoModel, RELEASE
from scripts.evaluate_august_home_browse import load_study_inputs
from scripts.evaluate_august_returning_home import STRATEGIES, candidate_ranking, returning_visitors
from scripts.evaluate_august_returning_home_slot import (
    ACTIONS, OUTPUT as PREVIOUS, group_summary, hit_rate_interval, rank_summary,
)
from scripts.evaluate_cart_popular_fill import first_hit
from scripts.evaluate_cart_recommendations import CONTRACT, DB, ROOT, TOP_K, digest_row
from scripts.evaluate_recency_slot import reserve_slot


OUTPUT = ROOT / "reports/mainline/recommendation_august_returning_home_paired_slots_20261127.json"


def slotted(ranking, seed):
    if len(ranking) != TOP_K or len(set(ranking)) != TOP_K:
        raise ValueError("Expected ten distinct homepage items before reserving a slot")
    revised = reserve_slot(ranking, seed)
    if seed is None:
        return revised, "no_prior_view"
    if seed in ranking:
        return revised, "already_in_top_ten"
    return revised, "replaced_rank_10"


def score_visitors(visitors, popular, model, *, rank_audit=None):
    """Compare both final lists per visitor, recording best ranks against the same target set."""
    roster, unslotted_pairs = hashlib.sha256(), hashlib.sha256()
    previous_slot_pairs, slot_pairs = hashlib.sha256(), hashlib.sha256()
    pairs = Counter()
    strategies = {strategy: Counter() for strategy in STRATEGIES}
    actions = {arm: dict.fromkeys(ACTIONS, 0) for arm in ("baseline", "candidate")}
    cache, clusters = {}, {}
    for visitor, _, seed, first_view, targets in visitors:
        if visitor in clusters or not targets:
            raise ValueError("Expected one nonempty first-view target set per visitor")
        if seed not in cache:
            strategy, original, _ = candidate_ranking(seed, popular, model)
            baseline, base_action = slotted(popular, seed)
            candidate, candidate_action = slotted(original, seed)
            cache[seed] = strategy, original, baseline, candidate, base_action, candidate_action
        strategy, original, baseline, candidate, base_action, candidate_action = cache[seed]
        base_rank, candidate_rank = first_hit(baseline, targets), first_hit(candidate, targets)
        pairs[base_rank, candidate_rank] += 1
        strategies[strategy][base_rank, candidate_rank] += 1
        actions["baseline"][base_action] += 1
        actions["candidate"][candidate_action] += 1
        clusters[visitor] = (1, int(candidate_rank is not None) - int(base_rank is not None))

        record = [visitor, first_view, sorted(targets, key=int)]
        original_rank = first_hit(original, targets)
        digest_row(roster, record)
        digest_row(unslotted_pairs, [*record, first_hit(popular, targets), original_rank])
        digest_row(previous_slot_pairs, [*record, original_rank, candidate_rank])
        digest_row(slot_pairs, [*record, base_rank, candidate_rank])
        if rank_audit is not None:
            rank_audit(visitor, first_view, base_rank, candidate_rank)

    overall = rank_summary(pairs)
    shared_hits = [(base, candidate, count) for (base, candidate), count in pairs.items()
                   if base is not None and candidate is not None]
    overall["both_hit_rank_change"] = {
        "earlier": sum(n for base, candidate, n in shared_hits if candidate < base),
        "same": sum(n for base, candidate, n in shared_hits if candidate == base),
        "later": sum(n for base, candidate, n in shared_hits if candidate > base),
    }
    return {
        "overall": overall,
        "by_strategy": {strategy: group_summary(counts) for strategy, counts in strategies.items()},
        "by_slot_action": actions, "visitor_bootstrap": hit_rate_interval(clusters),
        "scored_visitor_first_view_targets_sha256": roster.hexdigest(),
        "unslotted_paired_best_ranks_sha256": unslotted_pairs.hexdigest(),
        "previous_slot_paired_best_ranks_sha256": previous_slot_pairs.hexdigest(),
        "paired_best_ranks_sha256": slot_pairs.hexdigest(),
    }


def study(*, score=score_visitors):
    popular, scope, windows = load_study_inputs()
    model = C1DemoModel.load(ROOT)
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        result = score(returning_visitors(db, windows), [item for item, _ in popular], model)
    previous = json.loads(PREVIOUS.read_bytes())
    if (result["scored_visitor_first_view_targets_sha256"] != previous["scored_visitor_first_view_targets_sha256"]
            or result["unslotted_paired_best_ranks_sha256"] != previous["previous_paired_best_ranks_sha256"]
            or result["previous_slot_paired_best_ranks_sha256"] != previous["paired_best_ranks_sha256"]
            or result["overall"]["candidate"] != previous["overall"]["candidate"]):
        raise ValueError("Returning visitor roster or prior rankings differ from the frozen slot report")
    return {
        "study": "Paired popularity and co-browse top tens with the same last-view slot for returning visitors",
        "role": "2015-08 development backtest", "utc_windows_start_inclusive_end_exclusive": scope,
        "source_receipt": RELEASE, "contract": CONTRACT, "previous_report": PREVIOUS.relative_to(ROOT).as_posix(),
        "rules": {
            "roster_seed_target": previous["rules"]["roster_seed_target"],
            "baseline_before_slot": "Frozen training browse popularity top ten for everyone.",
            "candidate_before_slot": "Frozen positive co-browse neighbors of the last pre-August view. Fill from the same popularity top ten in order, skipping duplicates. With no pair or no prior view, use the full popularity ranking.",
            "shared_slot": "For each arm separately, keep the seed at its original rank if already present. If absent, replace only rank ten. If there is no seed, retain the whole ranking.",
            "eligibility": previous["rules"]["eligibility"],
            "metrics": previous["rules"]["metrics"],
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
            raise SystemExit("Recomputed paired homepage slot results differ from the report")
    else:
        OUTPUT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    overall = result["overall"]
    print(f"{overall['scored_visitors']:,} visitors, {overall['baseline']['hits_at_10']:,} to "
          f"{overall['candidate']['hits_at_10']:,} hits, net {overall['net_hits']:+,}")


if __name__ == "__main__":
    main()
