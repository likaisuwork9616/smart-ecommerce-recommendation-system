"""Independently audit the August co-add comparison from canonicalized raw events.

Temporary SQL tables reconstruct sessions, distinct-visitor pairs, ranking, and
the next cart timestamp. Only aggregate counts and ordered SHA-256 commitments
leave the read-only database connection.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime
from hashlib import file_digest, sha256
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = "reports/stage13/retailrocket_cart_support_train.json"
CONTRACT = "docs/contracts/retailrocket_recommendation_v1.json"


def encode(row):
    return (json.dumps(row, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def model_digest(rows):
    digest = sha256()
    for row in rows:
        digest.update(encode(row))
    return digest.hexdigest()


def prepare(db, train, august):
    db.execute("""
        CREATE TEMP TABLE ev AS
        SELECT role, v, t, e, CAST(i AS INTEGER) AS i
        FROM main.raw
        WHERE bad = '' AND e IN ('view', 'addtocart')
          AND ((role = 'train' AND t >= ? AND t < ?)
            OR (role = 'validation' AND t >= ? AND t < ?))
        GROUP BY rt, v, e, i, x
    """, (*train, *august))
    db.executescript("""
        CREATE INDEX temp.ev_clock ON ev(role, v, t);
        CREATE TEMP TABLE ticks AS
        WITH timepoints AS (
            SELECT DISTINCT role, v, t FROM ev
        ), gaps AS (
            SELECT *, t - LAG(t) OVER (PARTITION BY role, v ORDER BY t) AS gap
            FROM timepoints
        )
        SELECT role, v, t,
               MAX(CASE WHEN gap IS NULL OR gap > 1800000 THEN t END)
               OVER (PARTITION BY role, v ORDER BY t ROWS UNBOUNDED PRECEDING) AS s
        FROM gaps;
        CREATE UNIQUE INDEX temp.tick_key ON ticks(role, v, t);
        CREATE TEMP TABLE cart AS
        SELECT DISTINCT e.role, e.v, k.s, e.t, e.i
        FROM ev e JOIN ticks k USING (role, v, t) WHERE e.e = 'addtocart';
        CREATE UNIQUE INDEX temp.cart_key ON cart(role, v, s, t, i);
        CREATE TEMP TABLE train_members AS
        SELECT DISTINCT v, s, i FROM cart WHERE role = 'train';
        CREATE UNIQUE INDEX temp.train_member_key ON train_members(v, s, i);
        CREATE TEMP TABLE support AS
        SELECT a.i AS a, b.i AS b, COUNT(DISTINCT a.v) AS votes
        FROM train_members a JOIN train_members b ON a.v = b.v AND a.s = b.s AND a.i < b.i
        GROUP BY a.i, b.i;
        CREATE TEMP VIEW pairs AS SELECT a, b, votes FROM support WHERE votes >= 2;
        CREATE TEMP TABLE neighbors AS
        WITH edges AS (SELECT a, b, votes FROM pairs UNION ALL SELECT b, a, votes FROM pairs)
        SELECT a, b, ROW_NUMBER() OVER (PARTITION BY a ORDER BY votes DESC, b) AS ranking
        FROM edges;
        CREATE TEMP TABLE popularity AS
        SELECT i, COUNT(*) AS n FROM ev WHERE role = 'train' AND e = 'addtocart' GROUP BY i;
        CREATE TEMP TABLE popular_choices AS
        WITH seeds AS (
            SELECT DISTINCT i FROM cart WHERE role = 'validation'
        ), global_top AS (
            SELECT i, n FROM popularity ORDER BY n DESC, i LIMIT 11
        )
        SELECT s.i AS seed, p.i AS item,
               ROW_NUMBER() OVER (PARTITION BY s.i ORDER BY p.n DESC, p.i) AS ranking
        FROM seeds s CROSS JOIN global_top p WHERE p.i <> s.i;
        CREATE TEMP TABLE queries AS
        WITH points AS (
            SELECT DISTINCT v, s, t FROM cart WHERE role = 'validation'
        ), successors AS (
            SELECT *, LEAD(t) OVER (PARTITION BY v, s ORDER BY t) AS next_t FROM points
        )
        SELECT ROW_NUMBER() OVER (ORDER BY c.v, c.t, c.i) AS id,
               c.v, c.s, c.t, c.i, p.next_t
        FROM cart c JOIN successors p USING(v, s, t) WHERE c.role = 'validation';
        CREATE TEMP TABLE targets AS
        SELECT q.id, future.i FROM queries q JOIN cart future
          ON future.role = 'validation' AND q.v = future.v AND q.s = future.s
          AND q.next_t = future.t AND q.i <> future.i;
        CREATE UNIQUE INDEX temp.target_key ON targets(id, i);
    """)


def as_lists(records):
    grouped = {}
    for key, item in records:
        grouped.setdefault(key, []).append(str(item))
    return grouped


def role_activity(db):
    counts = {}
    for role, visitors, sessions in db.execute("""
        SELECT role, COUNT(DISTINCT v), SUM(t = s) FROM ticks GROUP BY role
    """):
        counts[role] = {"visitors": visitors, "sessions": sessions}
    for role, sessions in db.execute("""
        SELECT role, COUNT(*) FROM (SELECT DISTINCT role, v, s FROM cart) GROUP BY role
    """):
        counts[role]["cart_sessions"] = sessions
    event_totals, item_totals = {}, {}
    for role, kind, total, items in db.execute("""
        SELECT role, e, COUNT(*), COUNT(DISTINCT i) FROM ev GROUP BY role, e
    """):
        event_totals.setdefault(role, {})[kind] = total
        item_totals.setdefault(role, {})[kind] = items
    counts["train"].update(events=event_totals["train"], distinct_items=item_totals["train"])
    counts["validation"].update({kind + "_events": n for kind, n in event_totals["validation"].items()})
    moments, multi = db.execute("""
        SELECT COUNT(*), COALESCE(SUM(n > 1), 0) FROM (
            SELECT COUNT(*) AS n FROM cart WHERE role = 'validation' GROUP BY v, s, t)
    """).fetchone()
    counts["validation"].update(cart_timestamps=moments, multi_item_cart_timestamps=multi)
    return counts


def arm_counts(counts, prefix, hits=None):
    queries, served = counts["queries"], counts[prefix + "_served"]
    result = {"with_recommendations": served, "full_ten": counts[prefix + "_full10"],
              "coverage": served / queries if queries else None}
    if hits is not None:
        result.update(hit_queries=hits, hit_rate_all=hits / queries if queries else None,
                      hit_rate_when_recommended=hits / served if served else None)
    return result


def audit(db):
    pair = as_lists(db.execute("SELECT a,b FROM neighbors WHERE ranking<=10 ORDER BY a,ranking"))
    popular = as_lists(db.execute("SELECT seed,item FROM popular_choices WHERE ranking<=10 ORDER BY seed,ranking"))
    target = as_lists(db.execute("SELECT id,i FROM targets ORDER BY id,i"))
    source_train_items = {str(i) for i, in db.execute("SELECT i FROM popularity")}
    all_rows, labeled = sha256(), sha256()
    totals, eligible, excluded, hits, overlap = Counter(), Counter(), Counter(), Counter(), Counter()
    scorable_visitors, scorable_sessions = set(), set()
    labels = {(True, True): "both", (True, False): "coadd_only",
              (False, True): "popular_only", (False, False): "neither"}
    for idx, visitor, session, clock, seed, next_t in db.execute("SELECT id,v,s,t,i,next_t FROM queries ORDER BY id"):
        truth, related, baseline = target.get(idx, []), pair.get(seed, []), popular.get(seed, [])
        fields = encode([visitor, clock, str(seed), truth, related, baseline])
        all_rows.update(fields)
        sizes = {"queries": 1, "pair_served": bool(related), "pair_full10": len(related) == 10,
                 "pop_served": bool(baseline), "pop_full10": len(baseline) == 10,
                 "unseen_seed": str(seed) not in source_train_items, "pair_slots": len(related)}
        totals.update(sizes)
        if not truth:
            excluded["terminal" if next_t is None else "only_same_seed"] += 1
            continue
        labeled.update(fields)
        eligible.update(sizes)
        scorable_visitors.add(visitor)
        scorable_sessions.add((visitor, session))
        actual_items = set(truth)
        pair_hit = not actual_items.isdisjoint(related)
        popular_hit = not actual_items.isdisjoint(baseline)
        hits.update({"pair": pair_hit, "popular": popular_hit,
                     "popular_on_pair_served": popular_hit and bool(related),
                     "unseen_targets": actual_items.isdisjoint(source_train_items),
                     "multiple_targets": len(truth) > 1})
        overlap[labels[pair_hit, popular_hit]] += 1
    activity = role_activity(db)
    training = activity["train"]
    training.update(
        distinct_pairs_before_threshold=db.execute("SELECT COUNT(*) FROM support").fetchone()[0],
        qualifying_pairs=db.execute("SELECT COUNT(*) FROM pairs").fetchone()[0],
        seeds_with_neighbors=len(pair), seeds_with_ten_neighbors=sum(len(items) == 10 for items in pair.values()),
        qualifying_pairs_sha256=model_digest(
            [str(a), str(b), n] for a, b, n in db.execute("SELECT a,b,votes FROM pairs ORDER BY a,b")),
        popular_counts_sha256=model_digest(
            [str(i), n] for i, n in db.execute("SELECT i,n FROM popularity ORDER BY n DESC,i")),
    )
    return {
        "training": training, "activity": activity["validation"],
        "all_cart_opportunities": {
            "queries": totals["queries"], "no_later_cart": excluded["terminal"],
            "next_cart_only_seed": excluded["only_same_seed"],
            "coadd": arm_counts(totals, "pair"), "popular": arm_counts(totals, "pop"),
            "query_targets_and_rankings_sha256": all_rows.hexdigest(),
        },
        "scorable": {
            "queries": eligible["queries"], "visitors": len(scorable_visitors), "sessions": len(scorable_sessions),
            "seed_absent_from_training_carts": eligible["unseen_seed"],
            "all_targets_absent_from_training_carts": hits["unseen_targets"],
            "multiple_target_queries": hits["multiple_targets"],
            "coadd": arm_counts(eligible, "pair", hits["pair"]), "popular": arm_counts(eligible, "pop", hits["popular"]),
            "paired_hits": {value: overlap[value] for value in labels.values()},
            "on_coadd_covered_queries": {"queries": eligible["pair_served"], "coadd_hit_queries": hits["pair"],
                                         "popular_hit_queries": hits["popular_on_pair_served"]},
            "query_targets_and_rankings_sha256": labeled.hexdigest(),
        },
        "extra_diagnostics": {"all_seeds_absent_from_training_carts": totals["unseen_seed"],
                              "all_coadd_slots_returned": totals["pair_slots"],
                              "scorable_coadd_slots_returned": eligible["pair_slots"]},
    }


def verify(root=ROOT, primary_report=None):
    root = Path(root)
    inventory = json.loads((root / INVENTORY).read_text(encoding="utf-8"))
    source = inventory["source_database"]
    path = root / source["path"]
    with path.open("rb") as handle:
        if source["bytes"] != path.stat().st_size or source["sha256"] != file_digest(handle, "sha256").hexdigest():
            raise ValueError("Source bytes differ from the existing cart inventory")
    roles = json.loads((root / CONTRACT).read_text(encoding="utf-8"))["time_roles"]
    windows = [tuple(int(datetime.fromisoformat(s).timestamp() * 1000) for s in roles[r])
               for r in ("train", "validation")]
    if windows != [(1430697600000, 1438387200000), (1438387200000, 1441065600000)]:
        raise ValueError("The contract no longer matches the frozen training and August validation windows")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA temp_store=MEMORY")
        prepare(db, *windows)
        result = audit(db)
    prior = inventory["counts"]
    old = next(x for x in prior["pair_support_by_distinct_visitor"] if x["minimum_support"] == 2)
    training = result["training"]
    if (training["qualifying_pairs"] != old["unordered_pairs"] or
            training["seeds_with_neighbors"] != old["at_least_1_neighbors"]["cart_items"] or
            training["seeds_with_ten_neighbors"] != old["at_least_10_neighbors"]["cart_items"] or
            training["events"] != prior["events"] or training["distinct_items"] != prior["distinct_items"]):
        raise ValueError("SQL pair reconstruction differs from the training inventory")
    if primary_report is None:
        return result
    groups = ["training", "activity", "all_cart_opportunities", "scorable"]
    for group in groups:
        if primary_report.get(group) != result[group]:
            raise ValueError(f"SQL reconstruction disagrees with the primary report in {group}")
    return {
        "status": "passed",
        "method": "Independent SQL reconstruction from canonicalized source raw rows in the training and August windows",
        "matched_sections": groups,
        "matched_sha256": {
            "qualifying_pairs": training["qualifying_pairs_sha256"],
            "popular_counts": training["popular_counts_sha256"],
            "all_cart_opportunities": result["all_cart_opportunities"]["query_targets_and_rankings_sha256"],
            "scorable": result["scorable"]["query_targets_and_rankings_sha256"],
        },
    }


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
