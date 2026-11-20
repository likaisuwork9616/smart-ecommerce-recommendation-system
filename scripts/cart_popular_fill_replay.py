"""Restore the first August hit gained in each kind of popular-cart fill."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.cart_replay_examples import encode, load_verified_examples, restore_verified_examples
from scripts.evaluate_cart_popular_fill import ROOT, popular_fill, study


REPORT = "reports/stage13/retailrocket_cart_popular_fill_201508.json"
RECEIPT = "reports/stage13/retailrocket_cart_popular_fill_replay_201508.json"
EXAMPLES = "shop-mysql-runtime/retailrocket_cart_popular_fill_replay_201508/cases.json"
KINDS = ("empty", "short")


class FirstFillGains:
    def __init__(self):
        self.queries = 0
        self.counts = Counter()
        self.cases = {}

    def observe(self, timestamp, seed, targets, coadd, popular):
        self.queries += 1
        truth = set(targets)
        if not truth.isdisjoint(coadd):
            return
        mixed = popular_fill(coadd, popular)
        hit_ranks = [rank for rank, (item, _) in enumerate(mixed, 1) if item in truth]
        if not hit_ranks:
            return
        kind = "short" if coadd else "empty"
        self.counts[kind] += 1
        if kind in self.cases:
            return
        when = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        self.cases[kind] = {
            "id": kind,
            "cohort_position": self.queries,
            "query_time": when.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "seed": seed,
            "targets": targets,
            "coadd": {"items": coadd, "sources": ["coadd"] * len(coadd), "hit_ranks": []},
            "popular_fill": {
                "items": [item for item, _ in mixed],
                "sources": [source for _, source in mixed],
                "hit_ranks": hit_ranks,
            },
        }

    def payload(self, scored):
        bands = scored["by_original_coadd_list_size"]
        expected = {kind: bands[kind]["hit_queries"]["popular_fill"] - bands[kind]["hit_queries"]["coadd"]
                    for kind in KINDS}
        gained = self.counts.total()
        if (self.queries != scored["queries"] or dict(self.counts) != expected
                or set(self.cases) != set(KINDS) or gained != scored["popular_fill_vs"]["coadd"]["gain"]):
            raise ValueError("補位新增命中的查詢數或案例與八月報告不符。")
        return {
            "scorable_queries": self.queries,
            "total_queries": gained,
            "net_additional_hits": gained,
            "cases": [{**self.cases[kind], "count": self.counts[kind]} for kind in KINDS],
        }


def build_replay(root=ROOT):
    root = Path(root)
    report_bytes = (root / REPORT).read_bytes()
    examples = FirstFillGains()
    results = study(root, observe_scorable=examples.observe)
    if results != json.loads(report_bytes):
        raise ValueError("重建的八月補位查詢、排序或來源與封存報告不符。")
    payload = examples.payload(results["scorable"])
    data = encode(payload)
    receipt = {
        "scope": "August 2015 development next-cart queries",
        "selection": "First gained hit with an empty co-add list and first gained hit with a short nonempty co-add list in verified query order",
        "validation_report": REPORT,
        "validation_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "local_examples": EXAMPLES,
        "local_examples_sha256": hashlib.sha256(data).hexdigest(),
        "scorable_queries": payload["scorable_queries"],
        "gain_queries": payload["total_queries"],
        "cases": [{
            "id": case["id"],
            "count": case["count"],
            "cohort_position": case["cohort_position"],
            "coadd_slots": len(case["coadd"]["items"]),
            "popular_fill_slots": case["popular_fill"]["sources"].count("popular"),
            "hit_ranks_after_fill": case["popular_fill"]["hit_ranks"],
        } for case in payload["cases"]],
    }
    return data, receipt


def load_cart_fill_replay(root=ROOT):
    return load_verified_examples(Path(root), REPORT, RECEIPT, EXAMPLES)


def restore(root=ROOT):
    root = Path(root)
    data, receipt = build_replay(root)
    return restore_verified_examples(root, RECEIPT, EXAMPLES, data, receipt)


if __name__ == "__main__":
    print(restore())
