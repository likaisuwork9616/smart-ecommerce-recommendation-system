import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.c1_demo_replay import QUERIES, RELEASE, ReplayLibrary


POPULAR = [str(i) for i in range(1, 11)]
RELATED = [str(i) for i in range(11, 21)]


def saved_query(targets, *, fallback=False):
    c1 = POPULAR if fallback else RELATED
    row = {
        "key": ["private_visitor", 1438387199500, 1438387200123],
        "history": ["31", "32"],
        "targets": targets,
        "slices": {"diagnostics": "private"},
        "predictions": {"P0": {"ids": POPULAR}, "C1": {"ids": c1, "zero_fill_slots": 10 if fallback else 0}},
        "terms": {},
    }
    for arm, items in (("P0", POPULAR), ("C1", c1)):
        ranks = [rank for rank, item in enumerate(items, 1) if item in targets]
        row["terms"][arm] = {
            "target_count": len(targets), "hits": len(ranks), "first_hit_rank": ranks[0] if ranks else None
        }
    return row


class ReplayTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.queries = self.root / QUERIES
        self.queries.parent.mkdir(parents=True)
        (self.root / RELEASE).parent.mkdir(parents=True)

    def save_source(self, rows):
        data = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
        self.queries.write_bytes(data)
        source = {"path": QUERIES, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        (self.root / RELEASE).write_text(json.dumps({"sources": [source]}), encoding="utf-8")

    def test_first_of_each_outcome_and_only_public_fields(self):
        self.save_source([
            saved_query(["99"], fallback=True), saved_query(["18", "12", "99"]),
            saved_query(["4", "11"]), saved_query(["8"]), saved_query(["19"]),
        ])
        library = ReplayLibrary.load(self.root)
        self.queries.unlink()  # Serving the selected cases needs no further file I/O.
        payload = library.payload()
        cases = payload["cases"]
        self.assertEqual([case["id"] for case in cases], ["c1_only", "p0_only", "neither", "both"])
        self.assertEqual([case["count"] for case in cases], [2, 1, 1, 1])
        self.assertEqual(payload["total_queries"], 5)
        self.assertEqual(payload["net_additional_hits"], 1)
        hit, p0_only, miss, both = cases
        self.assertEqual(set(hit), {"id", "count", "query_time", "history", "targets", "p0", "c1"})
        self.assertEqual(hit["query_time"], "2015-08-01T00:00:00.123Z")
        self.assertEqual(hit["history"], ["31", "32"])
        self.assertEqual(hit["targets"], ["18", "12", "99"])
        self.assertEqual(hit["c1"], {"items": RELATED, "hit_ranks": [2, 8], "zero_fill_slots": 0})
        self.assertEqual(hit["p0"], {"items": POPULAR, "hit_ranks": []})
        self.assertEqual(p0_only["p0"]["hit_ranks"], [8])
        self.assertEqual(miss["c1"]["zero_fill_slots"], 10)
        self.assertEqual(miss["c1"]["hit_ranks"], [])
        self.assertEqual((both["p0"]["hit_ranks"], both["c1"]["hit_ranks"]), ([4], [1]))
        self.assertNotIn("private", json.dumps(cases))

    def test_outcomes_with_no_example_are_omitted(self):
        self.save_source([saved_query(["99"]), saved_query(["1", "3"])])
        payload = ReplayLibrary.load(self.root).payload()
        self.assertEqual([(case["id"], case["count"]) for case in payload["cases"]],
                         [("p0_only", 1), ("neither", 1)])
        self.assertEqual(payload["total_queries"], 2)
        self.assertEqual(payload["net_additional_hits"], -1)

    def test_checks_even_the_unselected_tail_against_the_receipt(self):
        self.save_source([saved_query([x]) for x in ("12", "4", "99")] + [saved_query(["5", "13"]), saved_query(["98"])])
        original = self.queries.read_bytes()
        self.queries.write_bytes(original.replace(b'["98"]', b'["97"]'))
        with self.assertRaisesRegex(ValueError, "封存收據"):
            ReplayLibrary.load(self.root)

    def test_rejects_inconsistent_recorded_rank(self):
        row = saved_query(["13"])
        row["terms"]["C1"]["first_hit_rank"] = 1
        self.save_source([saved_query([x]) for x in ("12", "4", "99")] + [saved_query(["5", "13"]), row])
        with self.assertRaisesRegex(ValueError, "命中名次"):
            ReplayLibrary.load(self.root)

    def test_rejects_a_row_outside_development(self):
        row = saved_query(["13"])
        row["key"][2] = 1441065600000  # UTC start of September
        self.save_source([row])
        with self.assertRaisesRegex(ValueError, "開發驗證月份"):
            ReplayLibrary.load(self.root)
