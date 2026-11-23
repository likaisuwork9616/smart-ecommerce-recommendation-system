"""Restore two local replay cases for the frozen August K1 recency comparison."""
import hashlib
import json
from pathlib import Path

from scripts.c1_demo_replay import utc_time
from scripts.cart_replay_examples import encode, load_verified_examples, restore_verified_examples
from scripts.evaluate_cart_recommendations import ROOT, TOP_K


REPORT = "reports/mainline/recommendation_k1_recency_slot_20261123.json"
RECEIPT = "reports/mainline/recommendation_k1_recency_replay_20261123.json"
EXAMPLES = "shop-mysql-runtime/retailrocket_k1_recency_replay_201508/cases.json"


def build_replay():
    from scripts.evaluate_k1_recency_slot import study
    from scripts.score_recommendation_acceptance import require

    report_bytes = (ROOT / REPORT).read_bytes()
    first = {}

    def observe(position, query_time, targets, original, revised, original_rank, revised_rank):
        kind = "gained" if original_rank is None else "lost"
        if kind in first:
            return
        require((original_rank, revised_rank) in ((None, TOP_K), (TOP_K, None)),
                "The replay must gain or lose its only hit at rank ten")
        first[kind] = {
            "id": kind,
            "cohort_position": position,
            "query_time": utc_time(query_time),
            "targets": sorted(targets, key=int),
            "k1": {"items": original, "hit_ranks": [original_rank] if original_rank else []},
            "k1_recency": {"items": revised, "hit_ranks": [revised_rank] if revised_rank else []},
        }

    result = study(observe_change=observe)
    require(result == json.loads(report_bytes) and set(first) == {"gained", "lost"},
            "Rebuilt recency study or selected replay cases differ from the August report")
    counts = result["paired_first_hit_changes"]
    cases = [{**first[kind], "count": counts[change]} for kind, change in (("gained", "gain"), ("lost", "loss"))]
    data = encode({
        "total_queries": result["queries"],
        "net_additional_hits": result["net_extra_hit_queries"],
        "cases": cases,
    })
    receipt = {
        "scope": "August 2015 development browsing queries",
        "selection": "First gained hit and first lost hit in frozen query order",
        "validation_report": REPORT,
        "validation_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "ordered_query_keys_sha256": result["ordered_query_keys_sha256"],
        "local_examples": EXAMPLES,
        "local_examples_sha256": hashlib.sha256(data).hexdigest(),
        "total_queries": result["queries"],
        "cases": [{
            "id": case["id"],
            "count": case["count"],
            "cohort_position": case["cohort_position"],
            "target_count": len(case["targets"]),
            "hit_ranks_before": case["k1"]["hit_ranks"],
            "hit_ranks_after": case["k1_recency"]["hit_ranks"],
        } for case in cases],
        "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
    }
    return data, receipt


def load_k1_recency_replay(root=ROOT):
    try:
        return load_verified_examples(Path(root), REPORT, RECEIPT, EXAMPLES)
    except ValueError as exc:
        raise ValueError("本機 K1 留一席案例與八月回放收據不符，請重新建立。") from exc


def restore():
    data, receipt = build_replay()
    try:
        return restore_verified_examples(ROOT, RECEIPT, EXAMPLES, data, receipt)
    except ValueError as exc:
        raise ValueError("重新擷取的 K1 留一席案例與已發布的收據不符。") from exc


if __name__ == "__main__":
    print(restore())
