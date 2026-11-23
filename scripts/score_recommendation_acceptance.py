"""Score frozen recommendation pairs from an explicitly scoped, normalized packet."""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from fractions import Fraction
from hashlib import sha256
from itertools import zip_longest
import json
from pathlib import Path

import numpy as np

from scripts.evaluate_cart_popular_fill import compare, first_hit
from scripts.evaluate_cart_recommendations import TOP_K


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "reports/mainline/recommendation_default_freeze_20261120.json"
SCHEMA = "recommendation_default_pairs_v1"
ARMS = ("candidate", "baseline")
SOURCES = {
    "browse": (("knn", "popular"), ("cooccurrence", "popular", "recency")),
    "cart": (("coadd", "popular"),) * 2,
    "purchase": (("cobuy", "popular"),) * 2,
}
RECIPROCAL_SCALE = 2520  # LCM of ranks 1 through 10.
SESSION_GAP_MS = 1_800_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def natural(value):
    return type(value) is int and value >= 0


def window_ms(window):
    return tuple(int(datetime.fromisoformat(time).timestamp() * 1000) for time in window)


def visitor_interval(clusters, settings):
    # One draw per visitor. Summing selected rows implements visitor multiplicities.
    totals = np.asarray([clusters[v] for v in sorted(clusters)], dtype=np.int64)
    rng = np.random.Generator(np.random.PCG64(settings["seed"]))
    draws = np.empty(settings["replicates"])
    for index in range(len(draws)):
        selected = rng.integers(len(totals), size=len(totals))
        n, delta = totals[selected].sum(axis=0)
        draws[index] = delta / n
    return {
        "visitors": len(totals),
        "replicates": len(draws),
        "seed": settings["seed"],
        "hit_rate_delta_95_percentile": np.percentile(
            draws, settings["percentiles"], method=settings["quantile_method"]
        ).tolist(),
    }


class Arm:
    def __init__(self):
        self.any = self.full = 0
        self.ranks = []
        self.slots = Counter()
        self.source_queries = Counter()
        self.hit_sources = Counter()

    def add(self, slots, targets):
        self.any += bool(slots)
        self.full += len(slots) == TOP_K
        sources = [source for _, source in slots]
        self.slots.update(sources)
        self.source_queries.update(set(sources))
        if targets is None:
            return None
        rank = first_hit((item for item, _ in slots), targets)
        self.ranks.append(rank)
        if rank is not None:
            self.hit_sources[sources[rank - 1]] += 1
        return rank

    def summary(self, coverage):
        counts = Counter(self.ranks)
        positions = [counts[r] for r in range(1, TOP_K + 1)]
        scored = len(self.ranks)
        hits = scored - counts[None]
        mrr_units = sum(c * (RECIPROCAL_SCALE // r) for r, c in enumerate(positions, 1))
        return {
            "with_any": self.any, "with_ten": self.full,
            "any_rate": self.any / coverage if coverage else None,
            "full_ten_rate": self.full / coverage if coverage else None,
            "hit_queries": hits, "hit_rate_at_10": hits / scored if scored else None,
            "rank_one_hits": positions[0], "hit_rate_at_1": positions[0] / scored if scored else None,
            "mrr_at_10": mrr_units / (scored * RECIPROCAL_SCALE) if scored else None,
            "first_hit_counts_rank_1_to_10": positions,
            "slots_by_source": dict(sorted(self.slots.items())),
            "queries_by_source": dict(sorted(self.source_queries.items())),
            "first_hits_by_source": dict(sorted(self.hit_sources.items())),
        }, mrr_units


def score(rows, scenario, policy, expected_counts):
    """Rows carry one authoritative key and target set, and two ordered lists with sources."""
    arms = {name: Arm() for name in ARMS}
    seen = set()
    clusters = {}
    for key, targets, candidate, baseline in rows:
        require(key not in seen, "Duplicate query key")
        seen.add(key)
        new = arms["candidate"].add(candidate, targets)
        old = arms["baseline"].add(baseline, targets)
        if targets is not None:
            cluster = clusters.setdefault(key[0], [0, 0])
            cluster[0] += 1
            cluster[1] += (new is not None) - (old is not None)

    coverage, scored = len(seen), len(arms["candidate"].ranks)
    require((coverage, scored) == expected_counts, "Roster counts differ from the frozen counts")
    summaries, units = {}, {}
    for name in ARMS:
        summaries[name], units[name] = arms[name].summary(coverage)
    differences = compare(arms["baseline"].ranks, arms["candidate"].ranks)
    uncertainty = gates = None
    if scored:
        new, old = (summaries[arm] for arm in ARMS)
        delta_hits = new["hit_queries"] - old["hit_queries"]
        delta_mrr = Fraction(units["candidate"] - units["baseline"], scored * RECIPROCAL_SCALE)
        thresholds = policy["scenarios"][scenario]
        adoption = policy["adoption"]
        ci = adoption["hit_rate_ci"]
        uncertainty = visitor_interval(clusters, ci)
        gates = {
            "full_ten": Fraction(new["with_ten"], coverage) >= Fraction(str(adoption["minimum_query_full_ten_rate"])),
            "hit_at_1": Fraction(new["rank_one_hits"] - old["rank_one_hits"], scored)
            >= Fraction(str(adoption["minimum_first_rank_hit_rate_delta"])),
            "hit_at_10_delta": Fraction(delta_hits, scored) >= Fraction(str(thresholds["minimum_hit_rate_delta"])),
            "mrr_at_10_delta": delta_mrr >= Fraction(str(thresholds["minimum_mrr_at_10_delta"])),
            "hit_at_10_ci": uncertainty["hit_rate_delta_95_percentile"][0] > ci["lower_bound_strictly_greater_than"],
        }
    return {
        "coverage_queries": coverage,
        "scorable_queries": scored,
        "arms": summaries,
        "paired_first_hit_changes": differences,
        "visitor_bootstrap": uncertainty,
        "gates": gates,
        "all_gates_pass": all(gates.values()) if gates is not None else None,
    }


def packet_scope(manifest, policy, approval_ref):
    require(isinstance(manifest, dict), "Invalid packet manifest")
    require(manifest.get("schema") == SCHEMA, "Unknown packet schema")
    require(manifest.get("scenario") in tuple(SOURCES), "Unknown scenario")
    require(manifest.get("role") in ("retained", "synthetic"), "Unknown scoring role")
    times = manifest.get("window_utc_ms")
    locked = window_ms(policy["reserved_test"]["window_utc_start_inclusive_end_exclusive"])
    require(isinstance(times, list) and len(times) == 2 and all(map(natural, times)),
            "Expected UTC millisecond bounds")
    require(locked[1] <= times[0] < times[1], "Packet window must follow the locked September period")
    require(manifest.get("frozen_training_commit") == policy["frozen_git_commit"], "Frozen training version differs")
    require(all(natural(manifest.get(field)) for field in ("coverage_queries", "scorable_queries"))
            and manifest["scorable_queries"] <= manifest["coverage_queries"], "Invalid roster counts")
    if manifest["role"] == "retained":
        for field in ("approval_ref", "source_version"):
            value = manifest.get(field)
            require(isinstance(value, str) and value.strip(), f"Missing {field}")
        require(approval_ref == manifest["approval_ref"], "Retained packet requires its recorded approval reference")
    return times


@contextmanager
def packet_rows(manifest_path, descriptor):
    require(isinstance(descriptor, dict), "Invalid packet file descriptor")
    name = descriptor["file"]
    require(isinstance(name, str) and "/" not in name and "\\" not in name and
            ":" not in name and name.endswith(".jsonl"), "Expected a local JSONL basename")
    path = manifest_path.parent / name
    require(path.resolve().parent == manifest_path.parent, "Packet file must stay in its directory")
    with path.open("rb") as stream:
        digest = sha256()

        def records():
            for line in stream:
                digest.update(line)
                yield json.loads(line)
            require(digest.hexdigest() == descriptor.get("sha256"), "Packet file SHA-256 differs")

        yield records()


def read_catalog(records, scenario, policy, end):
    start_train, end_train = window_ms(policy["frozen_training"]["window_utc_start_inclusive_end_exclusive"])
    start_locked, end_locked = window_ms(policy["reserved_test"]["window_utc_start_inclusive_end_exclusive"])
    catalog = {}
    for item, when in records:
        require(natural(item) and natural(when) and item not in catalog, "Invalid or duplicate catalog entry")
        if scenario == "browse":
            require(when < end and not start_locked <= when < end_locked, "Browse catalog uses an excluded time")
        else:
            require(start_train <= when < end_train, "Eligible item must have training evidence")
        catalog[item] = when
    return catalog


def paired_rows(roster, rankings, catalog, scenario, window, locked):
    start, end = window
    for expected, ranked in zip_longest(roster, rankings):
        require(isinstance(expected, dict) and isinstance(ranked, dict), "Roster and ranking lengths differ")
        require(set(ranked) == {"key", *ARMS}, "Rankings must use the targets from the shared roster")
        key, when, through, targets = (expected[field] for field in ("key", "query_ms", "through_ms", "targets"))
        require(isinstance(key, list) and len(key) == 3 and all(map(natural, key)), "Invalid query key")
        require(key == ranked["key"] and all(map(natural, ranked["key"])), "Ranking query keys differ")
        require(natural(when) and natural(through) and start <= when <= through < end,
                "Query or target time is outside its window")
        if scenario == "browse":
            require(key[1] <= when == key[2] and not locked[0] <= key[1] < locked[1],
                    "Browse clocks disagree with query key")
            require(targets is not None and when < through <= when + SESSION_GAP_MS <= end,
                    "Browse query has no mature next-view target")
        elif scenario == "cart":
            require(when == key[1] and (targets is None or through > when), "Invalid next-add clock")
        if targets is not None:
            require(isinstance(targets, list) and targets and all(map(natural, targets)) and
                    len(set(targets)) == len(targets), "Targets must be null or distinct item IDs")
            require(scenario == "browse" or key[2] not in targets, "The seed cannot be a target")
            targets = set(targets)
        arms = []
        for name, sources in zip(ARMS, SOURCES[scenario], strict=True):
            slots = ranked[name]
            require(isinstance(slots, list) and len(slots) <= TOP_K, "Invalid ranking length")
            seen = set()
            for item, source in slots:
                require(natural(item) and item not in seen and source in sources, "Invalid or duplicate ranked slot")
                require(item in catalog and catalog[item] < when, "Ranked item is ineligible at query time")
                require(scenario == "browse" or item != key[2], "The seed cannot be recommended")
                seen.add(item)
            arms.append(slots)
        yield tuple(key), targets, *arms


def evaluate_packet(manifest_path, policy, *, approval_ref=None):
    manifest_path = manifest_path.resolve()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    window = packet_scope(manifest, policy, approval_ref)
    scenario = manifest["scenario"]
    locked = window_ms(policy["reserved_test"]["window_utc_start_inclusive_end_exclusive"])
    with packet_rows(manifest_path, manifest["catalog"]) as records:
        catalog = read_catalog(records, scenario, policy, window[1])
    with (
        packet_rows(manifest_path, manifest["roster"]) as roster,
        packet_rows(manifest_path, manifest["rankings"]) as rankings,
    ):
        rows = paired_rows(roster, rankings, catalog, scenario, window, locked)
        result = score(rows, scenario, policy, (manifest["coverage_queries"], manifest["scorable_queries"]))
    return {
        "schema": SCHEMA, "role": manifest["role"], "scenario": scenario,
        "window_utc_ms": window, "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "frozen_training_commit": policy["frozen_git_commit"],
        "reserved_test": "locked", **result,
        "adoption_gates_met": result["all_gates_pass"] if manifest["role"] == "retained" else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--approval-ref", help="Recorded scoped approval for a retained packet")
    args = parser.parse_args()
    try:
        result = evaluate_packet(args.manifest, json.loads(FREEZE.read_bytes()), approval_ref=args.approval_ref)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Scoring refused: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
