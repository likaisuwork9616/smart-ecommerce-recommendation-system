"""Score frozen homepage lists on one first-view target set per new visitor."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import date, timedelta
from hashlib import sha256
import json
from operator import itemgetter
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from scripts.evaluate_august_home_first_view_pair import summarize_rank_pairs, train_first_view_ranking
from scripts.evaluate_cart_recommendations import DB, ROOT, WINDOWS, digest_row
from scripts.evaluate_home_first_view_single_slot import ranks
from scripts.evaluate_july_home_first_view_pair import ranking_digest, train_browse_ranking
from scripts.score_recommendation_acceptance import FREEZE, natural, packet_rows, require, visitor_interval, window_ms


SCHEMA = "home_first_view_acceptance_v1"
FROZEN_COMMIT = "6ec81d7485abf4cf4bc6480620e6bebaf6932073"
FROZEN_WINDOWS = {"warmup": (1430611200000, 1430697600000), **WINDOWS}
RANKING_FINGERPRINTS = {
    "baseline_rank_item_counts_sha256": "da27de3427b463da80581390d9f285ca1d45e69de30ca91097d452598dd3f019",
    "full_rank_item_votes_sha256": "fb6f3b0849c159264b241d24f0a3c7e2621fcb7d807597d132d924c4eba10d28",
}
BOOTSTRAP = {
    "replicates": 2000, "seed": 20261120, "bit_generator": "NumPy PCG64",
    "percentiles": [2.5, 97.5], "quantile_method": "linear",
}
EPOCH = date(1970, 1, 1)
DAY_MS = 86_400_000
UTC_END_MS = ((date.max - EPOCH).days + 1) * DAY_MS


def frozen_rankings(db, windows):
    """Read warm-up and training events only. Bind the exact contents of both lists."""
    require(windows == FROZEN_WINDOWS, "The training, warm-up or August development window differs")
    baseline = train_browse_ranking(db, windows)
    candidate, _ = train_first_view_ranking(db, windows)
    require(ranking_digest(baseline) == RANKING_FINGERPRINTS["baseline_rank_item_counts_sha256"],
            "Baseline ranking differs from the frozen homepage")
    require(ranking_digest(candidate) == RANKING_FINGERPRINTS["full_rank_item_votes_sha256"],
            "Candidate ranking differs from the frozen first-view top ten")
    return baseline, candidate


def adoption_gates(scored_visitors, net_hits, lower_rate):
    """Compare the exact gain count and the unrounded lower bound (in rate units)."""
    require(natural(scored_visitors) and type(net_hits) is int and abs(net_hits) <= scored_visitors,
            "Invalid scored visitor or net hit count")
    if not scored_visitors:
        return None
    return {"practical_gain": 5000 * net_hits >= scored_visitors, "positive_lower_bound": lower_rate > 0}


def item_key(value):
    return (isinstance(value, str) and value.isascii() and value.isdecimal()
            and (value == "0" or not value.startswith("0")))


def score_home(rows, baseline, candidate, *, rank_audit=None, expected_visitors=None):
    """Score (visitor key, first-view UTC ms, distinct target items) in visitor key order."""
    rankings = [ranks([item for item, _ in ranking]) for ranking in (baseline, candidate)]
    roster_digest, pair_digest = sha256(), sha256()
    pairs, weekly, clusters = Counter(), defaultdict(Counter), {}
    for visitor, first_view, targets in sorted(rows, key=itemgetter(0)):
        require(isinstance(visitor, str) and visitor.strip() and visitor not in clusters,
                "Missing or duplicate visitor key")
        require(natural(first_view) and first_view < UTC_END_MS, "Invalid first-view UTC milliseconds")
        require(isinstance(targets, (list, tuple, set, frozenset)) and targets and
                all(map(item_key, targets)) and len(set(targets)) == len(targets), "Invalid first-view targets")
        best = tuple(min((rank[item] for item in targets if item in rank), default=None) for rank in rankings)
        record = [visitor, first_view, sorted(targets, key=int)]
        digest_row(roster_digest, record)
        digest_row(pair_digest, [*record, *best])
        pairs[best] += 1
        day = EPOCH + timedelta(days=first_view // DAY_MS)
        week = day - timedelta(days=day.weekday())
        weekly[week][best] += 1
        clusters[visitor] = (1, int(best[1] is not None) - int(best[0] is not None))
        if rank_audit is not None:
            rank_audit(visitor, first_view, *best)
    scored = len(clusters)
    require(expected_visitors is None or scored == expected_visitors, "Visitor count differs from declared roster")
    paired = summarize_rank_pairs(pairs)
    paired["scored_visitor_first_view_targets_sha256"] = roster_digest.hexdigest()
    paired["paired_best_ranks_sha256"] = pair_digest.hexdigest()
    uncertainty = gates = None
    if scored:
        uncertainty = {**BOOTSTRAP, **visitor_interval(clusters, BOOTSTRAP)}
        bounds = uncertainty["hit_rate_delta_95_percentile"]
        uncertainty["hit_rate_delta_95_percentage_points"] = [100 * bound for bound in bounds]
        gates = adoption_gates(scored, paired["net_hits"], bounds[0])
    weeks = []
    for monday, counts in sorted(weekly.items()):
        summary = summarize_rank_pairs(counts)
        weeks.append({"week_monday_utc": monday.isoformat(), **{
            field: summary[field] for field in ("scored_visitors", "candidate_only_gained", "baseline_only_lost", "net_hits")
        }})
    gains = paired["candidate_only_gained"]
    return {
        "paired": paired, "visitor_bootstrap": uncertainty, "gates": gates,
        "decision_rule": {
            "policy": "docs/HOME_FIRST_VIEW_ACCEPTANCE.md",
            "policy_commit": "52333bafcdd60f6454647eea25aa224b10edfe46",
            "minimum_gain_percentage_points_inclusive": 0.020, "lower_bound_must_exceed": 0,
        },
        "all_gates_pass": all(gates.values()) if gates is not None else None,
        "weekly": weeks, "gained_share_by_candidate_rank_1_to_10": [
            count / gains if gains else None for count in paired["gained_by_candidate_rank_1_to_10"]
        ],
    }


def packet_scope(manifest, approval_ref=None):
    require(isinstance(manifest, dict) and manifest.get("schema") == SCHEMA
            and manifest.get("role") == "independent", "Expected an independent homepage roster manifest")
    for field in ("source_version", "history_evidence", "approval_ref"):
        value = manifest.get(field)
        require(isinstance(value, str) and value.strip(), f"Missing {field}")
    require(approval_ref == manifest["approval_ref"], "Independent roster requires its recorded approval reference")
    window = manifest.get("window_utc_ms")
    require(isinstance(window, list) and len(window) == 2 and all(map(natural, window)), "Invalid UTC window")
    policy = json.loads(FREEZE.read_bytes())
    locked = window_ms(policy["reserved_test"]["window_utc_start_inclusive_end_exclusive"])
    require(locked[1] <= window[0] < window[1] <= UTC_END_MS,
            "Independent roster must use valid UTC dates after the locked September period")
    require(all(natural(manifest.get(key)) for key in
                ("active_visitors", "previously_seen", "new_without_view", "scored_visitors")),
            "Missing or invalid cohort counts")
    require(manifest["active_visitors"] == manifest["previously_seen"] + manifest["new_without_view"]
            + manifest["scored_visitors"], "Cohort counts do not reconcile")
    return tuple(window)


def packet_visitors(records, start, end):
    for row in records:
        require(isinstance(row, dict) and row.get("seen_before_window") is False,
                "Each scored visitor needs a verified new-visitor flag")
        when = row.get("first_view_ms")
        require(natural(when) and start <= when < end, "First view is outside the approved window")
        yield row["visitor"], when, row["targets"]


def evaluate_packet(manifest_path, *, approval_ref=None, rank_audit=None):
    path = Path(manifest_path).resolve()
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    window = packet_scope(manifest, approval_ref)
    uri = (ROOT / DB).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        baseline, candidate = frozen_rankings(db, FROZEN_WINDOWS)
    with packet_rows(path, manifest["roster"]) as records:
        result = score_home(packet_visitors(records, *window), baseline, candidate,
                            rank_audit=rank_audit, expected_visitors=manifest["scored_visitors"])
    return {
        "schema": SCHEMA, "role": manifest["role"], "source_version": manifest["source_version"],
        "manifest_sha256": sha256(manifest_bytes).hexdigest(), "roster_file_sha256": manifest["roster"]["sha256"],
        "window_utc_ms": list(window), "frozen_ranking_commit": FROZEN_COMMIT, **RANKING_FINGERPRINTS,
        "cohort": {key: manifest[key] for key in ("active_visitors", "previously_seen", "new_without_view", "scored_visitors")},
        **result, "adoption_gates_met": result["all_gates_pass"], "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
    }


@contextmanager
def private_rank_audit(path):
    if path is None:
        yield None
        return
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            def write_row(visitor, first_view, baseline_rank, candidate_rank):
                output.write(json.dumps([visitor, first_view, baseline_rank, candidate_rank]) + "\n")

            yield write_row
            output.close()
            os.link(temporary, path)  # Publish only a verified, complete audit to a new file.
        finally:
            output.close()
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="Independent roster manifest")
    parser.add_argument("--approval-ref", required=True, help="Recorded approval for this roster")
    parser.add_argument("--rank-audit", type=Path, help="New private JSONL file for visitor-level best ranks")
    args = parser.parse_args()
    try:
        with private_rank_audit(args.rank_audit) as audit:
            result = evaluate_packet(args.manifest, approval_ref=args.approval_ref, rank_audit=audit)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"Scoring refused: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
