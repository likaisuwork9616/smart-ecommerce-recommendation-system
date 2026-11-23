"""Check the paired scorer against all three frozen August development cohorts."""
import json
import math
import sqlite3
from contextlib import closing
from hashlib import file_digest, sha256
from itertools import groupby, zip_longest

from scripts import evaluate_cart_recommendations as cart
from scripts import evaluate_purchase_baskets as purchase
from scripts.c1_demo_model import EDGES, QUERIES
from scripts.c1_demo_replay import K1_QUERIES, K1_REPORT, RECENCY_REPORT
from scripts.evaluate_cart_popular_fill import popular_fill
from scripts.evaluate_recency_slot import history_catalog, most_recent, reserve_slot
from scripts.score_recommendation_acceptance import FREEZE, ROOT, require, score


def read_json(path):
    return json.loads((ROOT / path).read_bytes())


def archive_rows(relative, frozen_inputs):
    descriptor = frozen_inputs[relative]
    digest = sha256()
    with (ROOT / relative).open("rb") as stream:
        for line in stream:
            digest.update(line)
            yield json.loads(line)
    require(digest.hexdigest() == descriptor["sha256"], "Unexpected frozen browse archive digest")


def browse_slots(prediction, evidence):
    return [(item, evidence if numerator > 0 else "popular")
            for item, (numerator, _) in zip(prediction["ids"], prediction["scores"], strict=True)]


def browse_rows(frozen, start, end):
    inputs = {item["path"]: item for item in frozen["private_inputs"]}
    history = (ROOT / EDGES).resolve()
    with history.open("rb") as stream:
        require(file_digest(stream, "sha256").hexdigest() == inputs[EDGES]["sha256"],
                "Unexpected frozen browse history")
    key_digest = sha256()
    with closing(sqlite3.connect(history.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        catalog = history_catalog(db)
        for k1, c1 in zip_longest(archive_rows(K1_QUERIES, inputs), archive_rows(QUERIES, inputs)):
            require(k1 is not None and c1 is not None and k1["key"] == c1["key"]
                    and k1["targets"] == c1["targets"] and k1["history"] == c1["history"],
                    "August browse archives disagree on a query or target")
            key = k1["key"]
            visitor, session, when = key
            require(start <= when < end, "Query outside August development")
            cart.digest_row(key_digest, key)
            neighbor = k1["predictions"]["K1"]
            cooc = c1["predictions"]["C1"]
            require(neighbor["fit_id"] == frozen["training_fingerprint"]["k1_fit_id"]
                    and cooc == k1["predictions"]["C1"], "August browse ranking or fit differs")
            candidate = browse_slots(neighbor, "knn")
            baseline = browse_slots(cooc, "cooccurrence")
            recent, _ = most_recent(db, catalog, visitor, session, when)
            revised = reserve_slot(cooc["ids"], recent)
            if revised != cooc["ids"]:
                baseline[-1] = (revised[-1], "recency")
            for arm in (candidate, baseline):
                items = {item for item, _ in arm}
                require(len(arm) == len(items) == cart.TOP_K and
                        all(catalog.contains(i, when) for i in items), "August browse list is ineligible")
            yield (int(visitor), session, when), set(c1["targets"]), candidate, baseline
    require(key_digest.hexdigest() == frozen["development_roster"]["ordered_query_keys_sha256"],
            "August browse roster differs")


def basket_pair(related, popular, source):
    candidate = popular_fill(related, popular, original=source)
    baseline = [(i, source) for i in related] if related else [(i, "popular") for i in popular]
    return candidate, baseline


def cart_rows(db, frozen, start, end):
    model = cart.build_model(cart.activity_rows(db, "train", *cart.WINDOWS["train"]))
    report = read_json("reports/stage13/retailrocket_cart_next_add_201508.json")
    require(model.training == report["training"], "Frozen cart training differs")
    all_rows, scorable_rows = sha256(), sha256()
    activity = dict.fromkeys(("view_events", "addtocart_events", "cart_timestamps", "multi_item_cart_timestamps"), 0)
    groups = groupby(cart.activity_rows(db, "validation", start, end), key=lambda row: row[0])
    for visitor, events in groups:
        for baskets in cart.session_baskets(events, activity):
            for (when, current), following in zip_longest(baskets, baskets[1:]):
                next_items = following[1] if following else set()
                for seed in sorted(current, key=int):
                    targets = sorted(next_items - {seed}, key=int)
                    related, popular = model.rank(seed)
                    record = [visitor, when, seed, targets, related, popular]
                    cart.digest_row(all_rows, record)
                    if targets:
                        cart.digest_row(scorable_rows, record)
                    yield (int(visitor), when, int(seed)), set(targets) or None, *basket_pair(related, popular, "coadd")
    require(all_rows.hexdigest() == frozen["all_queries_targets_and_rankings_sha256"]
            and scorable_rows.hexdigest() == frozen["scorable_queries_targets_and_rankings_sha256"],
            "August cart roster, targets or original ranks differ")


def purchase_rows(db, frozen, start, end):
    require((start, end) == purchase.WINDOWS["validation"], "Purchase reader is August-only")
    train, train_counts = purchase.build_baskets(purchase.purchase_rows(db, "train"))
    august, _ = purchase.build_baskets(purchase.purchase_rows(db, "validation"))
    ranked, popular_items, training_support = purchase.build_lists(train)
    report = read_json("reports/stage13/retailrocket_purchase_basket_201508.json")
    require({**train_counts, **training_support} == report["training"], "Frozen purchase training differs")
    prefix = popular_items[:cart.TOP_K + 1]
    all_rows = sha256()
    for visitor, transaction, items in august:
        for seed in items:
            targets = tuple(item for item in items if item != seed)
            related = ranked.get(seed, ())
            popular = [item for item in prefix if item != seed][:cart.TOP_K]
            cart.digest_row(all_rows, [visitor, transaction, seed, targets, related, popular])
            key = (int(visitor), int(transaction), int(seed))
            yield key, set(targets) or None, *basket_pair(related, popular, "cobuy")
    require(all_rows.hexdigest() == frozen["all_queries_targets_and_rankings_sha256"],
            "August purchase roster, targets or original ranks differ")


def verify_browse(result):
    k1 = read_json(K1_REPORT)["results"]["main"]["arms"]["K1"]
    recency = read_json(RECENCY_REPORT)
    first = read_json("reports/stage12/retailrocket_browse_rank_one_201508.json")["first_rank_matches"]
    for name, hits, rank_one, mrr in (
        ("candidate", k1["hit_queries"], first["K1"], k1["metrics"]["mrr"]),
        ("baseline", recency["counts"]["recency_hits"], first["C1+recency"], recency["metrics"]["recency"]["mrr"]),
    ):
        arm = result["arms"][name]
        require(arm["with_ten"] == result["coverage_queries"] and arm["hit_queries"] == hits
                and arm["rank_one_hits"] == rank_one and math.isclose(arm["mrr_at_10"], mrr, abs_tol=1e-14, rel_tol=0),
                "August browse score differs from the published metrics")


def verify_basket(result, report, scope):
    original = report[scope]
    counts = (
        original["popular_fill_full_ten"],
        original["queries"] - original["original_" + ("coadd" if scope == "all_cart_opportunities" else "cobuy")
                                       + "_short_nonempty"],
    )
    for name, source, full_ten in zip(("candidate", "baseline"), ("popular_fill", "empty_fallback"), counts, strict=True):
        expected = report["scorable"]["arms"][source]
        arm = result["arms"][name]
        require(arm["with_ten"] == full_ten and arm["with_any"] == original["queries"]
                and arm["hit_queries"] == expected["hit_queries"]
                and arm["first_hit_counts_rank_1_to_10"] == expected["first_hit_counts_rank_1_to_10"]
                and math.isclose(arm["mrr_at_10"], expected["mrr_at_10"], abs_tol=1e-14, rel_tol=0),
                "August basket score differs from the published metrics")
    require(result["paired_first_hit_changes"] == report["scorable"]["popular_fill_vs"]["empty_fallback"],
            "August paired first-hit changes differ from the published comparison")


def verify():
    policy = json.loads(FREEZE.read_bytes())
    start, end = cart.WINDOWS["validation"]
    db_url = (ROOT / cart.DB).resolve().as_uri() + "?mode=ro&immutable=1"
    results = {}
    with closing(sqlite3.connect(db_url, uri=True)) as db:
        for scenario, frozen in policy["scenarios"].items():
            roster = frozen["development_roster"]
            counts = (roster["coverage_queries"], roster["scorable_queries"])
            if scenario == "browse":
                result = score(browse_rows(frozen, start, end), scenario, policy, counts)
                verify_browse(result)
            else:
                read_rows, scope = (
                    (cart_rows, "all_cart_opportunities") if scenario == "cart"
                    else (purchase_rows, "all_item_occurrences")
                )
                result = score(read_rows(db, roster, start, end), scenario, policy, counts)
                verify_basket(result, read_json(f"reports/stage13/retailrocket_{scenario}_popular_fill_201508.json"), scope)
            results[scenario] = result
    return {
        "role": "2015-08 exposed development validation",
        "window_utc_ms": [start, end],
        "frozen_training_commit": policy["frozen_git_commit"],
        "published_point_metrics_match": True,
        "reserved_test": "locked",
        "reserved_test_ranked_queries": 0,
        "formal_scored_queries": 0,
        "scenarios": results,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, allow_nan=False))
