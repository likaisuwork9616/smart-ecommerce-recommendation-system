"""Select examples from the accepted Stage 10 paired development rankings."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts.c1_demo_model import C1, RELEASE


QUERIES = f"{C1}/queries.jsonl"
CASES = {
    (False, True): "c1_only",
    (True, False): "p0_only",
    (False, False): "neither",
    (True, True): "both",
}


def replay_case(row, case_id):
    # The other two key fields identify the visitor and session; omit them.
    when = datetime.fromtimestamp(row["key"][2] / 1000, tz=timezone.utc)
    if (when.year, when.month) != (2015, 8):
        raise ValueError("回放查詢超出開發驗證月份。")
    targets = set(row["targets"])
    case = {
        "id": case_id,
        "query_time": when.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
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
    case["c1"]["zero_fill_slots"] = row["predictions"]["C1"]["zero_fill_slots"]
    return case


class ReplayLibrary:
    def __init__(self, cases):
        self._cases = cases

    @classmethod
    def load(cls, root: Path):
        root = Path(root)
        release = json.loads((root / RELEASE).read_text(encoding="utf-8"))
        source = next((entry for entry in release["sources"] if entry["path"] == QUERIES), None)
        if source is None:
            raise ValueError("Stage 10 公開收據缺少配對查詢的來源。")
        found = {}
        with (root / QUERIES).open("rb") as stream:
            if (os.fstat(stream.fileno()).st_size != source["bytes"]
                    or hashlib.file_digest(stream, "sha256").hexdigest() != source["sha256"]):
                raise ValueError("本機回放來源與 Stage 10 封存收據不符。")
            stream.seek(0)
            for line in stream:
                row = json.loads(line)
                outcome = tuple(row["terms"][arm]["hits"] > 0 for arm in ("P0", "C1"))
                name = CASES[outcome]
                if name not in found:
                    found[name] = replay_case(row, name)
                    if len(found) == len(CASES):
                        break
        if not found:
            raise ValueError("配對查詢檔沒有回放案例。")
        return cls([found[name] for name in CASES.values() if name in found])

    def payload(self):
        return {"cases": self._cases}
