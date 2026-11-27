"""Score an independent returning-visitor roster with the two frozen last-view-slot homepages."""
import argparse
from hashlib import sha256
import json
import math
from operator import itemgetter
from pathlib import Path
import sqlite3

from scripts.c1_demo_model import C1DemoModel, EDGES, POPULARITY, RELEASE, SUPPORT
from scripts.evaluate_august_returning_home_paired_slots import score_visitors
from scripts.evaluate_cart_recommendations import ROOT, TOP_K
from scripts.evaluate_july_home_first_view_pair import ranking_digest
from scripts.score_home_first_view_acceptance import (
    RANKING_FINGERPRINTS, UTC_END_MS, item_key, private_rank_audit,
)
from scripts.score_recommendation_acceptance import (
    FREEZE, RECIPROCAL_SCALE, natural, packet_rows, require, window_ms,
)


SCHEMA = "returning_home_acceptance_v1"
ITEM_KEY_VERSION = "retailrocket_original_itemid_v1"
POLICY_COMMIT = "189e130699752d5ef9bea6c5a443695b0926cf08"
MODEL_SHA256 = {
    EDGES: "e6f283a7cbe0c3c242a3123e9d11d6490f3302b58baf96890330c163a31fbd32",
    SUPPORT: "92774b2cec168ab26abadb30ea7e21aeecc7d54c6e5994555fc592bae5e6f875",
    POPULARITY: "def7a6d1ea99e86fa75b5cad2669c88f0280c588fb08a04c7dbc18ac1f999f89",
}
BASELINE_SHA256 = RANKING_FINGERPRINTS["baseline_rank_item_counts_sha256"]


def adoption_result(overall, visitor_bootstrap):
    """Apply the three gates to the rank counts and the unrounded paired hit-rate interval."""
    n = overall["scored_visitors"]
    require(natural(n), "Invalid visitor count")
    units = {}
    hits = {}
    for arm in ("baseline", "candidate"):
        counts = overall[arm]["first_hit_counts_rank_1_to_10"]
        require(len(counts) == TOP_K and all(map(natural, counts)), "Invalid first-hit ranks")
        hits[arm] = sum(counts)
        require(hits[arm] == overall[arm]["hits_at_10"] and hits[arm] <= n, "Hit counts disagree")
        units[arm] = sum(count * (RECIPROCAL_SCALE // rank) for rank, count in enumerate(counts, 1))
    net = overall["net_hits"]
    require(net == hits["candidate"] - hits["baseline"], "Net hits differ from the rank counts")
    mrr_numerator = units["candidate"] - units["baseline"]
    mrr_denominator = RECIPROCAL_SCALE * n
    gates = None
    if n:
        require(visitor_bootstrap and visitor_bootstrap["visitors"] == n, "Paired interval denominator differs")
        lower, upper = visitor_bootstrap["hit_rate_delta_95_percentile"]
        require(math.isfinite(lower) and math.isfinite(upper) and -1 <= lower <= upper <= 1,
                "Invalid paired hit-rate interval")
        gates = {
            "hit_at_10_delta": 50 * net >= n,
            "positive_lower_bound": lower > 0,
            "mrr_at_10_delta": 100 * mrr_numerator >= mrr_denominator,
        }
    else:
        require(visitor_bootstrap is None, "An empty roster cannot supply an interval")
    return {
        "gates": gates, "all_gates_pass": all(gates.values()) if gates is not None else None,
        "reciprocal_rank_units": {**units, "scale": RECIPROCAL_SCALE},
        "mrr_gate_evidence": {"numerator": mrr_numerator, "denominator": mrr_denominator,
                              "delta": mrr_numerator / mrr_denominator if n else None},
        "policy_commit": POLICY_COMMIT,
    }


def score_returning(visitors, popular, model, *, expected_visitors=None, rank_audit=None):
    """Use one ranked pair per returning visitor, with misses and fallbacks in the denominator."""
    result = score_visitors(visitors, popular, model, rank_audit=rank_audit)
    n = result["overall"]["scored_visitors"]
    require(expected_visitors is None or n == expected_visitors, "Scored count differs from the declared roster")
    return {**result, **adoption_result(result["overall"], result["visitor_bootstrap"])}


def frozen_inputs():
    """Load the August training snapshot without opening any evaluation or holdout events."""
    receipt = json.loads((ROOT / RELEASE).read_bytes())
    recorded = {row["path"]: row["sha256"] for row in receipt["sources"] if row["path"] in MODEL_SHA256}
    require(recorded == MODEL_SHA256, "Model source receipt differs from the frozen August snapshot")
    model = C1DemoModel.load(ROOT)  # Also checks each local file against its source receipt.
    ranking = [(row["item_id"], row["views"]) for row in model.search(limit=TOP_K)]
    require(ranking_digest(ranking) == BASELINE_SHA256, "Popularity top ten differs from the frozen baseline")
    return [item for item, _ in ranking], model


def locked_window():
    return window_ms(json.loads(FREEZE.read_bytes())["reserved_test"]["window_utc_start_inclusive_end_exclusive"])


def packet_scope(manifest, approval_ref=None):
    require(isinstance(manifest, dict) and manifest.get("schema") == SCHEMA
            and manifest.get("role") == "independent", "Expected an independent returning-visitor manifest")
    for field in ("source_version", "history_evidence", "approval_ref"):
        value = manifest.get(field)
        require(isinstance(value, str) and value.strip(), f"Missing {field}")
    require(manifest["approval_ref"] == approval_ref, "Expected the recorded approval for this independent roster")
    require(manifest.get("item_key_version") == ITEM_KEY_VERSION, "Expected original Retailrocket item IDs")
    window = manifest.get("window_utc_ms")
    require(isinstance(window, list) and len(window) == 2 and all(map(natural, window))
            and locked_window()[1] <= window[0] < window[1] <= UTC_END_MS,
            "Independent evaluation must follow the locked September window")
    require(all(natural(manifest.get(key)) for key in ("active_returning", "returning_without_view", "scored_visitors"))
            and manifest["active_returning"] == manifest["returning_without_view"] + manifest["scored_visitors"],
            "Invalid or inconsistent returning cohort counts")
    return tuple(window)


def distinct_items(items):
    return isinstance(items, list) and bool(items) and all(map(item_key, items)) and len(items) == len(set(items))


def packet_visitors(records, start, end):
    """Validate source-attested history and targets. Choose a tied seed before looking at rankings."""
    reserved_start, reserved_end = locked_window()

    def valid_history_time(ms):
        return natural(ms) and ms < start and not reserved_start <= ms < reserved_end

    for row in records:
        require(isinstance(row, dict) and set(row) == {"visitor", "prior_event", "last_view", "first_view_ms", "targets"},
                "Expected one returning visitor, history evidence and first-view targets")
        visitor, prior, last = row["visitor"], row["prior_event"], row["last_view"]
        require(isinstance(visitor, str) and visitor.strip(), "Missing anonymous visitor key")
        require(isinstance(prior, dict) and set(prior) == {"type", "time_ms", "item"}
                and prior["type"] in ("view", "addtocart", "transaction")
                and valid_history_time(prior["time_ms"]) and item_key(prior["item"]),
                "Missing or invalid prior qualifying event")
        if last is None:
            require(prior["type"] != "view", "A known prior view conflicts with no recorded last view")
            seed = None
        else:
            require(isinstance(last, dict) and set(last) == {"time_ms", "items"}
                    and valid_history_time(last["time_ms"]) and distinct_items(last["items"]),
                    "Expected the complete, dated last pre-window view basket")
            if prior["type"] == "view":
                require(prior["time_ms"] < last["time_ms"] or
                        (prior["time_ms"] == last["time_ms"] and prior["item"] in last["items"]),
                        "Prior view conflicts with the last pre-window view basket")
            seed = min(last["items"], key=int)
        when = row["first_view_ms"]
        require(natural(when) and start <= when < end, "First view outside the declared window")
        require(distinct_items(row["targets"]), "Expected distinct original item IDs at the first view")
        yield visitor, "returning", seed, when, set(row["targets"])


def evaluate_packet(manifest_path, *, approval_ref=None, rank_audit=None):
    path = Path(manifest_path).resolve()
    contents = path.read_bytes()
    manifest = json.loads(contents)
    window = packet_scope(manifest, approval_ref)
    with packet_rows(path, manifest["roster"]) as records:
        visitors = sorted(packet_visitors(records, *window), key=itemgetter(0))
    require(len(visitors) == manifest["scored_visitors"], "Roster count differs from the manifest")
    popular, model = frozen_inputs()
    result = score_returning(visitors, popular, model, expected_visitors=manifest["scored_visitors"], rank_audit=rank_audit)
    # Report the same difference used by the gate, including an exact tie at +0.010.
    result["overall"]["mrr_at_10_delta"] = result["mrr_gate_evidence"]["delta"]
    passed = result["all_gates_pass"]
    return {
        "schema": SCHEMA, "role": "independent", "source_version": manifest["source_version"],
        "item_key_version": ITEM_KEY_VERSION, "window_utc_ms": list(window),
        "manifest_sha256": sha256(contents).hexdigest(), "roster_file_sha256": manifest["roster"]["sha256"],
        "model_source_receipt": RELEASE, "model_sources_sha256": MODEL_SHA256,
        "baseline_rank_item_counts_sha256": BASELINE_SHA256,
        "cohort": {key: manifest[key] for key in ("active_returning", "returning_without_view", "scored_visitors")},
        **result, "decision": "pending" if passed is None else "adopt_candidate" if passed else "keep_original",
        "reserved_test": "locked", "reserved_test_ranked_queries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Independent returning-visitor roster manifest")
    parser.add_argument("--approval-ref", required=True, help="Recorded approval reference for this roster")
    parser.add_argument("--rank-audit", type=Path, help="New private JSONL file of per-visitor best ranks")
    args = parser.parse_args()
    try:
        with private_rank_audit(args.rank_audit) as audit:
            result = evaluate_packet(args.manifest, approval_ref=args.approval_ref, rank_audit=audit)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"Scoring refused: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
