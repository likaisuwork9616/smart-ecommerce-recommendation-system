"""Count paired Stage 10 development outcomes and keep one example of each."""
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
CASES = {
    (False, True): "c1_only",
    (True, False): "p0_only",
    (False, False): "neither",
    (True, True): "both",
}


def utc_time(milliseconds):
    when = datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def replay_case(row):
    # The other two key fields identify the visitor and session; omit them.
    query_time = utc_time(row["key"][2])
    if not query_time.startswith("2015-08-"):
        raise ValueError("回放查詢超出開發驗證月份。")
    targets = set(row["targets"])
    case = {
        "query_time": query_time,
        "history": row["history"],
        "targets": row["targets"],
    }
    for arm in ("P0", "C1"):
        prediction = row["predictions"][arm]
        items = prediction["ids"]
        hit_ranks = [rank for rank, item in enumerate(items, 1) if item in targets]
        terms = row["terms"][arm]
        first_hit = hit_ranks[0] if hit_ranks else None
        if (len(hit_ranks), first_hit, len(targets)) != (
            terms["hits"], terms["first_hit_rank"], terms["target_count"]
        ):
            raise ValueError("回放命中名次與既有驗收值不符。")
        case[arm.lower()] = {"items": items, "hit_ranks": hit_ranks}
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
            return library

    def payload(self):
        return self._payload
