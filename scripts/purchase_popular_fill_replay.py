"""Restore two distinct purchase-fill trade-offs from the verified August cohort."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from scripts.cart_replay_examples import encode, load_verified_examples, restore_verified_examples
from scripts.evaluate_cart_popular_fill import TOP_K, first_hit, popular_fill
from scripts.evaluate_purchase_popular_fill import ROOT, study


REPORT = "reports/stage13/retailrocket_purchase_popular_fill_201508.json"
RECEIPT = "reports/stage13/retailrocket_purchase_popular_fill_replay_201508.json"
EXAMPLES = "shop-mysql-runtime/retailrocket_purchase_popular_fill_replay_201508/cases.json"
ARMS = ("cobuy", "popular", "popular_fill")


def rank_with_sources(ranking, targets):
    return {
        "items": [item for item, _ in ranking],
        "sources": [source for _, source in ranking],
        "hit_ranks": [rank for rank, (item, _) in enumerate(ranking, 1) if item in targets],
    }


class PurchaseFillExamples:
    def __init__(self):
        self.queries = 0
        self.matches = defaultdict(list)

    def observe(self, seed, targets, cobuy, popular):
        self.queries += 1
        mixed = popular_fill(cobuy, popular, original="cobuy")
        mixed_first = first_hit((item for item, _ in mixed), targets)
        if mixed_first is None:
            return
        popular_first = first_hit(popular, targets)
        short_gain = 0 < len(cobuy) < TOP_K and first_hit(cobuy, targets) is None
        popular_later = popular_first is not None and popular_first < mixed_first
        if not (short_gain or popular_later):
            return
        case = {
            "cohort_position": self.queries,
            "seed": seed,
            "targets": sorted(targets, key=int),
            "cobuy": rank_with_sources([(item, "cobuy") for item in cobuy], targets),
            "popular": rank_with_sources([(item, "popular") for item in popular], targets),
            "popular_fill": rank_with_sources(mixed, targets),
        }
        if short_gain:
            self.matches["short_gain"].append(case)
        if popular_later:
            self.matches["popular_later"].append(case)

    def payload(self, scored):
        counts = {kind: len(matches) for kind, matches in self.matches.items()}
        expected = {
            "short_gain": scored["popular_fill_vs"]["empty_fallback"]["gain"],
            "popular_later": scored["popular_fill_vs"]["popular"]["later"],
        }
        if self.queries != scored["queries"] or counts != expected:
            raise ValueError("兩類購買案例的查詢數與八月補位報告不符。")
        gained, delayed = self.matches["short_gain"], self.matches["popular_later"]
        first_gain = gained[0]
        first_distinct_delay = next((case for case in delayed
                                     if case["cohort_position"] != first_gain["cohort_position"]), None)
        if first_distinct_delay is None:
            raise ValueError("找不到另一筆熱門榜命中後移的案例。")
        overlap = {case["cohort_position"] for case in gained} & {case["cohort_position"] for case in delayed}
        return {
            "scorable_queries": self.queries,
            "overlap_queries": len(overlap),
            "cases": [
                {"id": "short_gain", "count": counts["short_gain"], **first_gain},
                {"id": "popular_later", "count": counts["popular_later"], **first_distinct_delay},
            ],
        }


def build_replay(root=ROOT):
    root = Path(root)
    report_bytes = (root / REPORT).read_bytes()
    examples = PurchaseFillExamples()
    results = study(root, observe_scorable=examples.observe)
    if results != json.loads(report_bytes):
        raise ValueError("重建的購買補位查詢、名次或來源與八月報告不符。")
    payload = examples.payload(results["scorable"])
    data = encode(payload)
    receipt = {
        "scope": "August 2015 development same-transaction purchase queries",
        "selection": "First short-list fill gain, then first distinct query with a later first hit than the original popularity list",
        "validation_report": REPORT,
        "validation_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "local_examples": EXAMPLES,
        "local_examples_sha256": hashlib.sha256(data).hexdigest(),
        "scorable_queries": payload["scorable_queries"],
        "overlap_queries": payload["overlap_queries"],
        "cases": [{
            "id": case["id"],
            "count": case["count"],
            "cohort_position": case["cohort_position"],
            "target_count": len(case["targets"]),
            "list_sizes": {arm: len(case[arm]["items"]) for arm in ARMS},
            "first_hit_ranks": {arm: next(iter(case[arm]["hit_ranks"]), None) for arm in ARMS},
        } for case in payload["cases"]],
    }
    return data, receipt


def load_purchase_fill_replay(root=ROOT):
    return load_verified_examples(Path(root), REPORT, RECEIPT, EXAMPLES)


def restore(root=ROOT):
    root = Path(root)
    data, receipt = build_replay(root)
    return restore_verified_examples(root, RECEIPT, EXAMPLES, data, receipt)


if __name__ == "__main__":
    print(restore())
