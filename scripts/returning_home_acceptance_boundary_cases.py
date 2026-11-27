"""Deterministic synthetic returning visitors for checking the three adoption boundaries."""
from scripts.score_returning_home_acceptance import packet_visitors, score_returning


class SyntheticNeighbors:
    def recommend(self, seed):
        if seed != "80":
            raise KeyError(seed)
        return {"recommendations": [
            {"item_id": str(item), "source": "cooccurrence"} for item in (11, 12, 13, 14)
        ]}


def synthetic_results():
    popular = [str(item) for item in range(1, 11)]
    model = SyntheticNeighbors()
    start = 1443744000000  # 2015-10-02 UTC, synthetic data only
    # Both lists keep seed 80 in tenth place. Only C1 has 11 (first) and 14 (fourth).
    # Adding one visitor who misses both leaves the numerator intact.
    cases = [
        ("hit_exact", 500, 10, "11", 100),
        ("hit_just_below", 501, 10, "11", 100),
        ("mrr_exact", 500, 20, "14", 100),
        ("mrr_just_below", 501, 20, "14", 100),
        ("lower_bound_zero", 40, 1, "11", 10),
    ]
    results = {}
    for name, total, gains, gain_item, common_hits in cases:
        targets = [gain_item] * gains + ["80"] * common_hits + ["999"] * (total - gains - common_hits)
        rows = (
            {"visitor": f"v{i:03d}", "prior_event": {"type": "view", "time_ms": start - 1, "item": "80"},
             "last_view": {"time_ms": start - 1, "items": ["80"]}, "first_view_ms": start, "targets": [item]}
            for i, item in enumerate(targets)
        )
        scored = score_returning(packet_visitors(rows, start, start + 1), popular, model, expected_visitors=total)
        overall = scored["overall"]
        results[name] = {
            "scored_visitors": overall["scored_visitors"],
            "baseline_hits": overall["baseline"]["hits_at_10"], "candidate_hits": overall["candidate"]["hits_at_10"],
            "net_hits": overall["net_hits"], "hit_rate_change_percentage_points": overall["hit_rate_change_percentage_points"],
            "hit_rate_delta_95_percentage_points": scored["visitor_bootstrap"]["hit_rate_delta_95_percentage_points"],
            "baseline_mrr_at_10": overall["baseline"]["mrr_at_10"], "candidate_mrr_at_10": overall["candidate"]["mrr_at_10"],
            "mrr_at_10_delta": scored["mrr_gate_evidence"]["delta"],
            "gates": scored["gates"], "all_gates_pass": scored["all_gates_pass"],
        }
    return results
