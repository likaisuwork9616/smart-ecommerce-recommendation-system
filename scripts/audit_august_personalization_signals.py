"""Measure which August browsing queries have earlier cart or purchase signals."""

from collections import Counter
from contextlib import closing
import json
import sqlite3

from scripts.c1_demo_model import EDGES
from scripts.evaluate_cart_recommendations import CONTRACT, DB, sha
from scripts.evaluate_recency_slot import AUGUST_START, SEPTEMBER_START, reserve_slot
from scripts.k1_recency_replay import REPORT as K1_RECENCY_REPORT
from scripts.score_recommendation_acceptance import FREEZE, ROOT, require, window_ms
from scripts.verify_recommendation_acceptance_august import K1_REPORT, browse_query_details, read_json


GROUPS = ("browse_only", "cart_without_purchase", "purchase")
ROLES = ("warmup", "train", "validation")
HISTORY_SCOPE = """
    WITH scope(role, first_ms, end_ms) AS (VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?))
"""
HISTORY_JOIN = """
    JOIN scope ON history.role = scope.role AND history.t >= scope.first_ms AND history.t < scope.end_ms
"""
COUNTS = (
    "queries", "original_k1_misses", "k1_recency_misses", "queries_with_c1_pair",
    "k1_recency_misses_with_c1_pair", "k1_recency_misses_with_c1_pair_and_eligible_target",
)


def history_times(db, windows, paired_items):
    """Record the earliest event of each kind, with and without a training pair."""
    parameters = tuple(value for role in ROLES for value in (role, *windows[role]))
    sql = HISTORY_SCOPE + """
        SELECT history.v, history.e, history.t, history.i FROM qualified AS history
    """ + HISTORY_JOIN + "WHERE history.e IN ('addtocart', 'transaction')"
    observed, paired = {}, {}
    for visitor, event, when, item in db.execute(sql, parameters):
        key = int(visitor), event
        observed[key] = min(when, observed.get(key, when))
        if item in paired_items:
            paired[key] = min(when, paired.get(key, when))

    # SQL MIN on valid raw events checks every clock independently of the
    # qualified-table reader. Exact duplicates cannot affect a minimum.
    db.execute("PRAGMA temp_store = MEMORY")
    db.execute("CREATE TEMP TABLE paired_items (item TEXT PRIMARY KEY) WITHOUT ROWID")
    db.executemany("INSERT INTO paired_items VALUES (?)", ((item,) for item in paired_items))
    oracle = HISTORY_SCOPE + """
        SELECT history.v, history.e, MIN(history.t),
               MIN(CASE WHEN paired_items.item IS NOT NULL THEN history.t END)
        FROM raw AS history
    """ + HISTORY_JOIN + """
        LEFT JOIN paired_items ON history.i = paired_items.item
        WHERE history.bad = '' AND history.e IN ('addtocart', 'transaction')
        GROUP BY history.v, history.e
    """
    raw_observed, raw_paired = {}, {}
    for visitor, event, first, first_paired in db.execute(oracle, parameters):
        key = int(visitor), event
        raw_observed[key] = first
        if first_paired is not None:
            raw_paired[key] = first_paired
    require(observed == raw_observed and paired == raw_paired,
            "Qualified signal clocks differ from independently aggregated raw events")
    return observed, paired


def summarize(rows, observed, paired):
    counts = {group: Counter() for group in GROUPS}
    visitors = {group: set() for group in GROUPS}
    paired_visitors = {group: set() for group in GROUPS}
    for (visitor, _, when), targets, candidate, _, _, recent, reachable in rows:
        has_cart = observed.get((visitor, "addtocart"), when) < when
        has_purchase = observed.get((visitor, "transaction"), when) < when
        group = "purchase" if has_purchase else "cart_without_purchase" if has_cart else "browse_only"
        can_use_pair = (paired.get((visitor, "addtocart"), when) < when
                        or paired.get((visitor, "transaction"), when) < when)

        original = [item for item, _ in candidate]
        original_miss = targets.isdisjoint(original)
        recency_miss = targets.isdisjoint(reserve_slot(original, recent))
        visitors[group].add(visitor)
        row = counts[group]
        row["queries"] += 1
        row["original_k1_misses"] += original_miss
        row["k1_recency_misses"] += recency_miss
        if can_use_pair:
            paired_visitors[group].add(visitor)
            row["queries_with_c1_pair"] += 1
            row["k1_recency_misses_with_c1_pair"] += recency_miss
            row["k1_recency_misses_with_c1_pair_and_eligible_target"] += recency_miss and reachable > 0

    def totals(groups):
        return {
            **{key: sum(counts[group][key] for group in groups) for key in COUNTS},
            "visitors": len(set().union(*(visitors[group] for group in groups))),
            "visitors_with_c1_pair": len(set().union(*(paired_visitors[group] for group in groups))),
        }

    return {
        "all_browse_queries": totals(GROUPS),
        "any_prior_cart_or_purchase": totals(GROUPS[1:]),
        "by_prior_history": {group: totals((group,)) for group in GROUPS},
    }


def read_only(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def study():
    policy = read_json(FREEZE)
    frozen = policy["scenarios"]["browse"]
    roster = frozen["development_roster"]
    reference = read_json(K1_RECENCY_REPORT)
    original = read_json(K1_REPORT)["results"]["main"]
    dates = read_json(CONTRACT)["time_roles"]
    history_windows = {role: dates[role] for role in ROLES}
    windows = {role: window_ms(history_windows[role]) for role in ROLES}
    august = (AUGUST_START, SEPTEMBER_START)
    require(windows["validation"] == august
            and windows["train"] == window_ms(policy["frozen_training"]["window_utc_start_inclusive_end_exclusive"])
            and history_windows["warmup"] == ["2015-05-03T00:00:00Z", history_windows["train"][0]]
            and policy["reserved_test"]["status"] == reference["reserved_test"] == "locked"
            and reference["window_utc_start_inclusive_end_exclusive_ms"] == list(august)
            and reference["reserved_test_ranked_queries"] == 0
            and reference["ordered_query_keys_sha256"] == roster["ordered_query_keys_sha256"],
            "Signal history must respect the frozen training and August development windows")

    binding = policy["shared_private_database"]
    database = ROOT / DB
    before = database.stat()
    require(binding["path"] == DB and before.st_size == binding["bytes"] and sha(database) == binding["sha256"],
            "Unexpected frozen source database")
    # browse_query_details verifies this same C1 archive against the frozen
    # receipt and checks the query order, targets and candidate catalog.
    with closing(read_only(ROOT / EDGES)) as db:
        paired_items = {item for item, in db.execute("SELECT a FROM edges UNION SELECT b FROM edges")}
    with closing(read_only(database)) as db:
        observed, paired = history_times(db, windows, paired_items)

    result = summarize(browse_query_details(frozen, *august), observed, paired)
    total = result["all_browse_queries"]
    queries = total["queries"]
    require(queries == roster["scorable_queries"] == reference["queries"] == original["queries"]
            and total["visitors"] == original["visitors"]
            and queries - total["original_k1_misses"] == reference["original_k1"]["hit_queries"]
            == original["arms"]["K1"]["hit_queries"]
            and queries - total["k1_recency_misses"] == reference["k1_with_recency"]["hit_queries"],
            "Segmented counts do not reconcile with the verified August roster and hits")
    after = database.stat()
    require((after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns),
            "The frozen history source changed during the audit")
    return {
        "study": "Prior cart and purchase signal coverage on the frozen August browsing queries",
        "role": reference["role"],
        "window_utc_start_inclusive_end_exclusive_ms": list(august),
        "history_windows_utc_start_inclusive_end_exclusive": history_windows,
        "ordered_query_keys_sha256": roster["ordered_query_keys_sha256"],
        "source_database": binding,
        "references": [FREEZE.relative_to(ROOT).as_posix(), CONTRACT, K1_REPORT, K1_RECENCY_REPORT],
        "rules": {
            "history": "Same anonymous visitor key across the scoped windows. Add and transaction timestamps must be strictly earlier than the query.",
            "groups": "Any prior purchase takes precedence. Otherwise categorize as prior cart or browsing only. A visitor can appear in multiple groups.",
            "c1_pair": "At least one prior cart or purchase item has a distinct co-view neighbor in the frozen training graph. This measures usable input coverage for that graph.",
            "miss": "No item in the next view basket is present in the existing top ten.",
            "eligible_target": "At least one next view item belongs to the existing query-time catalog.",
        },
        **result,
        "independent_signal_clock_check": "All qualified minima matched SQL minima from valid raw events in the same windows.",
        "new_model_fits": 0,
        "formal_scored_queries": 0,
        "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
    }


if __name__ == "__main__":
    print(json.dumps(study(), indent=2, allow_nan=False))
