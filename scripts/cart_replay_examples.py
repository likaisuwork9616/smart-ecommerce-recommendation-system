"""Rebuild two local cart examples from the accepted August development replay."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from scripts.evaluate_cart_recommendations import ROOT, audit


REPORT = "reports/stage13/retailrocket_cart_next_add_201508.json"
RECEIPT = "reports/stage13/retailrocket_cart_replay_201508.json"
EXAMPLES = "shop-mysql-runtime/retailrocket_cart_replay_201508/cases.json"


def encode(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


class FirstCoveredExamples:
    def __init__(self):
        self.counts = Counter()
        self.cases = {}
        self.popular_hits = 0

    def observe(self, timestamp, seed, targets, coadd, popular):
        if not targets or not coadd or not popular:
            return
        target_items = set(targets)
        name = "miss" if target_items.isdisjoint(coadd) else "hit"
        self.counts[name] += 1
        self.popular_hits += not target_items.isdisjoint(popular)
        if name in self.cases:
            return
        when = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        case = {
            "id": name, "cohort_position": self.counts.total(),
            "query_time": when.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "seed": seed, "targets": targets,
        }
        for arm, items in (("coadd", coadd), ("popular", popular)):
            case[arm] = {"items": items, "hit_ranks": [
                position for position, item in enumerate(items, 1) if item in targets
            ]}
        self.cases[name] = case

    def payload(self, scored):
        total, hits = self.counts.total(), self.counts["hit"]
        if ({"queries": total, "coadd_hit_queries": hits, "popular_hit_queries": self.popular_hits}
                != scored["on_coadd_covered_queries"] or set(self.cases) != {"hit", "miss"}):
            raise ValueError("兩榜皆有推薦的查詢或案例次數與八月驗證結果不符。")
        return {
            "total_queries": total, "coadd_hit_queries": hits, "popular_hit_queries": self.popular_hits,
            "net_additional_hits": hits - self.popular_hits,
            "cases": [{**self.cases[name], "count": self.counts[name]} for name in ("hit", "miss")],
        }


def build_cart_replay(root=ROOT):
    root = Path(root)
    certified = (root / REPORT).read_bytes()
    examples = FirstCoveredExamples()
    result = audit(root, observe_scorable=examples.observe)
    if result != json.loads(certified):
        raise ValueError("重建的訓練榜、八月查詢／目標／排名或統計與封存報告不符。")
    payload = examples.payload(result["scorable"])
    data = encode(payload)
    receipt = {
        "scope": "August 2015 development queries with a next add of another item and two nonempty lists",
        "selection": "First coadd hit and first coadd miss in the accepted query order, regardless of the popular result",
        "validation_report": REPORT, "validation_report_sha256": hashlib.sha256(certified).hexdigest(),
        "local_examples": EXAMPLES, "local_examples_sha256": hashlib.sha256(data).hexdigest(),
        "total_queries": payload["total_queries"],
        "cases": [{
            "id": case["id"], "count": case["count"], "cohort_position": case["cohort_position"],
            **{arm: {"list_size": len(case[arm]["items"]), "hit_ranks": case[arm]["hit_ranks"]}
               for arm in ("coadd", "popular")},
        } for case in payload["cases"]],
    }
    return data, receipt


def load_cart_replay(root=ROOT):
    """Read only the two checked examples. The web server never needs to score a query."""
    root = Path(root)
    receipt = json.loads((root / RECEIPT).read_bytes())
    certified = (root / REPORT).read_bytes()
    if receipt["validation_report_sha256"] != hashlib.sha256(certified).hexdigest():
        raise ValueError("加購回放收據與八月開發驗證報告不符。")
    data = (root / EXAMPLES).read_bytes()
    if receipt["local_examples_sha256"] != hashlib.sha256(data).hexdigest():
        raise ValueError("本機加購案例與核對過的範例不符，請重新建立。")
    return json.loads(data)


def restore(root=ROOT):
    root = Path(root)
    data, receipt = build_cart_replay(root)
    if json.loads((root / RECEIPT).read_bytes()) != receipt:
        raise ValueError("重新擷取的加購案例與已發布的收據不符。")
    path = root / EXAMPLES
    path.parent.mkdir(exist_ok=True, parents=True)
    output = NamedTemporaryFile(dir=path.parent, delete=False)
    temp = Path(output.name)
    try:
        with output:
            output.write(data)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return path


if __name__ == "__main__":
    print(restore())
