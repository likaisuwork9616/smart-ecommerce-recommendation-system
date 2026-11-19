"""Load examples from the accepted August development rankings."""
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from scripts.c1_demo_model import EDGES, QUERIES, RELEASE
from scripts.evaluate_recency_slot import history_catalog, most_recent, reserve_slot
from scripts.retailrocket_popularity import K


RECENCY_REPORT = "reports/stage10/recency_slot_validation_201508.json"
K1_REPORT = "reports/stage12/k1_august_readback_20261119.json"
K1_QUERIES = "shop-mysql-runtime/retailrocket_session_knn_paired_v1/queries.jsonl"
CASES = {
    (False, True): "c1_only",
    (True, False): "p0_only",
    (False, False): "neither",
    (True, True): "both",
}


def utc_time(milliseconds):
    when = datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def replay_context(row):
    # The other two key fields identify the visitor and session; omit them.
    query_time = utc_time(row["key"][2])
    if not query_time.startswith("2015-08-"):
        raise ValueError("回放查詢超出開發驗證月份。")
    return {
        "query_time": query_time,
        "history": row["history"],
        "targets": row["targets"],
    }


def replay_ranking(row, arm):
    targets = set(row["targets"])
    items = row["predictions"][arm]["ids"]
    hit_ranks = [rank for rank, item in enumerate(items, 1) if item in targets]
    terms = row["terms"][arm]
    first_hit = hit_ranks[0] if hit_ranks else None
    if (len(hit_ranks), first_hit, len(targets)) != (
        terms["hits"], terms["first_hit_rank"], terms["target_count"]
    ):
        raise ValueError("回放命中名次與既有驗收值不符。")
    return {"items": items, "hit_ranks": hit_ranks}


def replay_case(row):
    case = replay_context(row)
    for arm in ("P0", "C1"):
        case[arm.lower()] = replay_ranking(row, arm)
    outcome = (bool(case["p0"]["hit_ranks"]), bool(case["c1"]["hit_ranks"]))
    case["id"] = CASES[outcome]
    case["c1"]["zero_fill_slots"] = row["predictions"]["C1"]["zero_fill_slots"]
    return case


def recency_replay(root, sources, stream, total, c1_hits):
    """Use the published full counts and reconstruct the first actual example of each change."""
    report = json.loads((root / RECENCY_REPORT).read_text(encoding="utf-8"))
    counts = report["counts"]
    gained, lost = counts["gained"], counts["lost"]
    if (type(gained) is not int or type(lost) is not int
            or counts["queries"] != total or not 0 <= gained <= total - c1_hits
            or not 0 <= lost <= c1_hits or report["net_extra_hit_queries"] != gained - lost
            or counts.get("c1_hits", c1_hits) != c1_hits
            or counts.get("recency_hits", c1_hits + gained - lost) != c1_hits + gained - lost):
        raise ValueError("最近商品留一席的統計與開發驗證名冊不符。")
    for name in (EDGES, QUERIES):
        if report["source_sha256"][name] != sources[name]["sha256"]:
            raise ValueError("最近商品留一席的統計與 Stage 10 來源不符。")
    path = root / EDGES
    with path.open("rb") as handle:
        if (os.fstat(handle.fileno()).st_size != sources[EDGES]["bytes"]
                or hashlib.file_digest(handle, "sha256").hexdigest() != sources[EDGES]["sha256"]):
            raise ValueError("最近商品留一席的瀏覽紀錄與 Stage 10 來源不符。")

    wanted = {name for name in ("gained", "lost") if counts[name]}
    examples = {}
    stream.seek(0)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        catalog = history_catalog(db)
        for line in stream:
            if not wanted:
                break
            row = json.loads(line)
            ranked = row["predictions"]["C1"]["ids"]
            targets = set(row["targets"])
            old_hit = not targets.isdisjoint(ranked)
            outcome = "lost" if old_hit else "gained"
            if outcome not in wanted:
                continue
            recent, timestamp = most_recent(db, catalog, *row["key"])
            if len(ranked) != K or (recent is not None and recent not in row["history"]):
                raise ValueError("單席回放與原共現榜或已看商品不符。")
            revised = reserve_slot(ranked, recent)
            hit_ranks = [rank for rank, item in enumerate(revised, 1) if item in targets]
            if bool(hit_ranks) == old_hit:
                continue
            case = replay_case(row)
            examples[outcome] = {
                "id": outcome, "count": counts[outcome], "query_time": case["query_time"],
                "recent_time": utc_time(timestamp), "history": case["history"], "targets": case["targets"],
                "c1": {"items": ranked, "hit_ranks": case["c1"]["hit_ranks"]},
                "recency": {"items": revised, "hit_ranks": hit_ranks},
            }
            wanted.remove(outcome)
    if wanted:
        raise ValueError("找不到最近商品留一席統計中記載的案例。")
    return {"total_queries": total, "net_additional_hits": gained - lost,
            "cases": [examples[name] for name in ("gained", "lost") if name in examples]}


def k1_replay(root, c1_stream, total, c1_hits):
    """Pair first examples with the original C1 rows and the accepted K1 counts."""
    report = json.loads((root / K1_REPORT).read_text(encoding="utf-8"))
    main = report["results"]["main"]
    counts = main["paired_hit_queries_K1_vs_C1"]
    net = main["net_extra_hit_queries_K1_minus_C1"]
    if (report["status"] != "august_development_semantic_readback_passed"
            or report["scope"]["evaluation_utc_ms"] != [1438387200000, 1441065600000]
            or report["cohort"]["queries"] != total or main["queries"] != total
            or set(counts) != {"k1_only", "c1_only", "both", "neither"}
            or any(type(n) is not int or n < 0 for n in counts.values()) or sum(counts.values()) != total
            or counts["both"] + counts["c1_only"] != c1_hits or main["arms"]["C1"]["hit_queries"] != c1_hits
            or counts["both"] + counts["k1_only"] != main["arms"]["K1"]["hit_queries"]
            or net != counts["k1_only"] - counts["c1_only"]):
        raise ValueError("K1 回放統計與八月開發驗證不符。")

    wanted = [name for name in ("k1_only", "c1_only") if counts[name]]
    found = {}
    with (root / K1_QUERIES).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != report["cohort"]["queries_sha256"]:
            raise ValueError("本機 K1 回放來源與八月驗收收據不符。")
        stream.seek(0)
        c1_stream.seek(0)
        for line in stream:
            row = json.loads(line)
            reference = json.loads(c1_stream.readline())
            if (any(row[k] != reference[k] for k in ("key", "targets", "history"))
                    or row["predictions"]["C1"] != reference["predictions"]["C1"]
                    or row["terms"]["C1"] != reference["terms"]["C1"]):
                raise ValueError("K1 案例與原 C1 查詢或排名不符。")
            case = replay_context(row)
            for arm in ("K1", "C1"):
                ranked = replay_ranking(row, arm)
                fills = row["predictions"][arm]["zero_fill_slots"]
                if (len(ranked["items"]) != K or len(set(ranked["items"])) != K
                        or type(fills) is not int or not 0 <= fills <= K):
                    raise ValueError("K1 回放的前十名或補位數無效。")
                case[arm.lower()] = {**ranked, "zero_fill_slots": fills}
            k1_hit, c1_hit = bool(case["k1"]["hit_ranks"]), bool(case["c1"]["hit_ranks"])
            if k1_hit != c1_hit:
                name = "k1_only" if k1_hit else "c1_only"
                if name not in wanted:
                    raise ValueError("K1 案例與驗收報告中的命中類別不符。")
                found.setdefault(name, {**case, "id": name, "count": counts[name]})
            if len(found) == len(wanted):
                break
    if len(found) != len(wanted):
        raise ValueError("找不到 K1 驗收報告記載的案例。")
    return {"total_queries": total, "net_additional_hits": net, "cases": [found[name] for name in wanted]}


class ReplayLibrary:
    def __init__(self, examples, counts):
        self._payload = {
            "cases": [{**examples[name], "count": count} for name, count in counts.items() if count],
            "total_queries": sum(counts.values()),
            "net_additional_hits": counts["c1_only"] - counts["p0_only"],
        }

    @classmethod
    def load(cls, root: Path):
        root = Path(root)
        release = json.loads((root / RELEASE).read_text(encoding="utf-8"))
        sources = {entry["path"]: entry for entry in release["sources"]}
        source = sources.get(QUERIES)
        if source is None:
            raise ValueError("Stage 10 公開收據缺少配對查詢的來源。")
        found = {}
        counts = dict.fromkeys(CASES.values(), 0)
        with (root / QUERIES).open("rb") as stream:
            if (os.fstat(stream.fileno()).st_size != source["bytes"]
                    or hashlib.file_digest(stream, "sha256").hexdigest() != source["sha256"]):
                raise ValueError("本機回放來源與 Stage 10 封存收據不符。")
            stream.seek(0)
            for line in stream:
                case = replay_case(json.loads(line))
                name = case["id"]
                counts[name] += 1
                found.setdefault(name, case)
            if not found:
                raise ValueError("配對查詢檔沒有回放案例。")
            library = cls(found, counts)
            try:
                library._payload["recency"] = recency_replay(
                    root, sources, stream, sum(counts.values()), counts["c1_only"] + counts["both"]
                )
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                print(f"最近商品留一席回放無法載入：{exc}", file=sys.stderr)
            try:
                library._payload["k1"] = k1_replay(
                    root, stream, sum(counts.values()), counts["c1_only"] + counts["both"]
                )
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                print(f"K1 回放無法載入：{exc}", file=sys.stderr)
            return library

    def payload(self):
        return self._payload
