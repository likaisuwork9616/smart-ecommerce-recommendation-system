"""Paired August development backtest of browse-only and multi-action C1 scores."""
import argparse
from collections import defaultdict
from contextlib import closing
from hashlib import sha256
import json
import sys

from scripts.audit_august_personalization_signals import read_only
from scripts.c1_demo_model import EDGES, QUERIES, SUPPORT, POPULARITY
from scripts.evaluate_cart_popular_fill import compare, first_hit, summarize
from scripts.evaluate_cart_recommendations import DB, TOP_K, digest_row, sha
from scripts.evaluate_recency_slot import AUGUST_START, SEPTEMBER_START, history_catalog
from scripts.personalization_history import august_history_rows
from scripts.personalization_ranker import PersonalizationRanker
from scripts.score_recommendation_acceptance import FREEZE, ROOT, require, visitor_interval
from scripts.verify_recommendation_acceptance_august import read_json


SIGNAL_AUDIT = "reports/mainline/recommendation_august_personalization_signals_20261123.json"


class PairedResults:
    def __init__(self):
        self.before = []
        self.after = []
        self.visitors = defaultdict(lambda: [0, 0])
        self.changed_lists = 0

    def add(self, visitor, old_rank, new_rank, changed):
        self.before.append(old_rank)
        self.after.append(new_rank)
        cluster = self.visitors[visitor]
        cluster[0] += 1
        cluster[1] += int(new_rank is not None) - int(old_rank is not None)
        self.changed_lists += changed

    def report(self, bootstrap):
        baseline = summarize(self.before)
        weighted = summarize(self.after)
        transitions = compare(self.before, self.after)
        net = weighted["hit_queries"] - baseline["hit_queries"]
        require(net == transitions["gain"] - transitions["loss"]
                and sum(transitions.values()) == len(self.before), "Paired hit changes differ")
        return {
            "queries": len(self.before), "visitors": len(self.visitors),
            "changed_top_tens": self.changed_lists,
            "browse_only": baseline, "weighted_actions": weighted,
            "first_hit_changes": transitions, "net_extra_hits": net,
            "mrr_at_10_difference": weighted["mrr_at_10"] - baseline["mrr_at_10"],
            "visitor_bootstrap": visitor_interval(self.visitors, bootstrap),
        }


def evaluate(records, model, catalog, bootstrap, *, progress=None):
    overall, signal = PairedResults(), PairedResults()
    visitor = None
    archive_matches = 0
    signal_queries = 0
    signal_visitors = set()
    ranking_digest, sample_digest = sha256(), sha256()
    sample_count = 0
    for position, (record, additions) in enumerate(records, 1):
        key = record["key"]
        current, _, when = key
        require(AUGUST_START <= when < SEPTEMBER_START, "Browse query outside August")
        if current != visitor:
            visitor = current
            profile = model.new_profile()
            viewed = set()
            has_action = False
        viewed.update(additions["view"])
        for event, items in additions.items():
            for item in items:
                profile.observe(item, event)
        has_action = has_action or bool(additions["addtocart"] or additions["transaction"])
        if has_action:
            signal_queries += 1
            signal_visitors.add(visitor)

        before, after = profile.rank(when)
        expected_length = min(catalog.size(when), TOP_K)
        require(record["candidate_count"] == catalog.size(when) and expected_length == TOP_K,
                "Unexpected August candidate catalog")
        for ranking in (before, after):
            require(len(ranking) == len(set(ranking)) == expected_length
                    and all(catalog.contains(item, when) for item in ranking), "Invalid top ten")
        if len(viewed) == len(record["history"]) and viewed == set(record["history"]):
            require(list(before) == record["predictions"]["C1"]["ids"],
                    "Browse-only ranking differs from archived C1 for the same history")
            archive_matches += 1
        changed = before != after
        require(not changed or profile.has_paired_action, "A ranking changed without a usable action")
        truth = set(record["targets"])
        require(bool(truth), "Missing next-view target basket")
        baseline_rank, weighted_rank = first_hit(before, truth), first_hit(after, truth)
        overall.add(visitor, baseline_rank, weighted_rank, changed)
        if profile.has_paired_action:
            signal.add(visitor, baseline_rank, weighted_rank, changed)
        digest_row(ranking_digest, [key, before, after])
        if position % 5000 == 1 or position == 166897:
            digest_row(sample_digest, [position, before, after])
            sample_count += 1
        if progress and position % 10000 == 0:
            progress(position)
    return {
        "all_queries": overall.report(bootstrap),
        "with_usable_signal": signal.report(bootstrap),
        "any_prior_action": {"queries": signal_queries, "visitors": len(signal_visitors)},
        "same_view_history_checked_against_archived_c1": archive_matches,
        "ordered_query_and_paired_top_tens_sha256": ranking_digest.hexdigest(),
        "sampled_paired_top_tens": {
            "rule": "Every 5000th roster position starting at 1, plus 166897 (one-based).",
            "queries": sample_count, "sha256": sample_digest.hexdigest(),
        },
    }


def study(*, progress=None):
    policy = read_json(FREEZE)
    frozen = policy["scenarios"]["browse"]
    roster = frozen["development_roster"]
    coverage = read_json(SIGNAL_AUDIT)
    binding = policy["shared_private_database"]
    require(binding == coverage["source_database"] and binding["path"] == DB
            and (ROOT / DB).stat().st_size == binding["bytes"] and sha(ROOT / DB) == binding["sha256"],
            "Unexpected frozen event database")
    require(coverage["ordered_query_keys_sha256"] == roster["ordered_query_keys_sha256"]
            and coverage["window_utc_start_inclusive_end_exclusive_ms"] == [AUGUST_START, SEPTEMBER_START]
            and coverage["reserved_test"] == policy["reserved_test"]["status"] == "locked",
            "Coverage reference differs from the frozen August cohort")
    with closing(read_only(ROOT / EDGES)) as source:
        catalog = history_catalog(source)
    model = PersonalizationRanker.from_frozen(ROOT, catalog)
    with closing(read_only(ROOT / DB)) as database:
        result = evaluate(august_history_rows(database, frozen), model, catalog,
                          policy["adoption"]["hit_rate_ci"], progress=progress)
    all_rows, usable = result["all_queries"], result["with_usable_signal"]
    audited = coverage["all_browse_queries"]
    require(all_rows["queries"] == roster["scorable_queries"] == audited["queries"]
            and all_rows["visitors"] == audited["visitors"]
            and usable["queries"] == audited["queries_with_c1_pair"]
            and usable["visitors"] == audited["visitors_with_c1_pair"]
            and all(result["any_prior_action"][k] == coverage["any_prior_cart_or_purchase"][k]
                    for k in ("queries", "visitors")), "Signal coverage differs from the prior audit")
    require(all_rows["changed_top_tens"] == usable["changed_top_tens"]
            and all_rows["net_extra_hits"] == usable["net_extra_hits"]
            and result["same_view_history_checked_against_archived_c1"] > 0,
            "Paired changes or archived ranking checks differ")
    return {
        "study": "August browse-only vs weighted prior cart and purchase C1 rankings",
        "role": coverage["role"], "reference_audit": SIGNAL_AUDIT,
        "freeze": FREEZE.relative_to(ROOT).as_posix(),
        "frozen_training_commit": policy["frozen_git_commit"],
        "history_windows_utc_start_inclusive_end_exclusive": coverage["history_windows_utc_start_inclusive_end_exclusive"],
        "ordered_query_keys_sha256": roster["ordered_query_keys_sha256"],
        "frozen_inputs": [DB, EDGES, SUPPORT, POPULARITY, QUERIES],
        "rules": {
            "history": "Same visitor across warmup, training and August, including all views through the current basket. Cart and transaction event times must be strictly earlier than the query.",
            "weights_by_distinct_visitor_item_event_type": {
                "browse_only": {"view": 1, "addtocart": 0, "transaction": 0},
                "weighted_actions": {"view": 1, "addtocart": 3, "transaction": 5},
            },
            "rank": "Sum seed weight times training co-view session pair count divided by seed session support. Break ties and fill zero scores by frozen view popularity, then ascending numeric item ID. Eligible items must have a strictly prior first view.",
            "target": "Any item in the next strictly later view basket in the same session. MRR uses the reciprocal of the first hit rank, zero on a miss.",
            "usable_signal": coverage["rules"]["c1_pair"],
        },
        **result,
        "new_model_fits": 0, "formal_scored_queries": 0,
        "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", action="store_true", help="write periodic query counts to stderr")
    args = parser.parse_args()
    notify = (lambda n: print(f"Scored {n:,} August queries", file=sys.stderr, flush=True)) if args.progress else None
    print(json.dumps(study(progress=notify), indent=2, allow_nan=False))
