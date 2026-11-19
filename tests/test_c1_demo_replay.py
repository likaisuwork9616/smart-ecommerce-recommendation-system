import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.c1_demo_model import EDGES
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

    def save_recency_fixture(self):
        # Two retained hits change the number of matching items but not the query outcome.
        scenarios = [
            (["31"], [], ["31"]),           # current item not eligible at this time
            (["12"], [], ["12"]),           # already ranked
            (["11", "20"], [], ["32"]),     # still hits rank one after removing 20
            (["11", "32"], [], ["32"]),     # still hits rank one after adding 32
            (["6", "98"], [], ["35", "6"]), # first gain: numeric tie picks 6
            (["20", "99"], ["35"], ["51"]), # first loss: 51 is new, select earlier 35
            (["33"], [], ["33"]),           # later gain
            (["20"], [], ["34"]),           # later loss
            (["1", "17"], [], ["17"]),      # old P0/C1 both hit
        ]
        rows = []
        warm = POPULAR + RELATED + ["32", "33", "34", "35"]
        warm_time = 1438387190000
        baskets = [("private_warm", warm_time, warm_time, json.dumps(warm), "train")]
        for offset, (targets, previous, current) in enumerate(scenarios):
            when = 1438387200000 + offset * 1000
            visitor = f"private_{offset}"
            start = when - 5 if previous else when
            row = saved_query(targets)
            row["key"] = [visitor, start, when]
            row["history"] = sorted(set(previous + current), key=int)
            rows.append(row)
            if previous:
                baskets.append((visitor, start, start, json.dumps(previous), "validation"))
            baskets.append((visitor, start, when, json.dumps(current), "validation"))
        self.save_source(rows)
        database = self.root / EDGES
        with closing(sqlite3.connect(database)) as db:
            db.execute("CREATE TABLE history (v TEXT, s INTEGER, t INTEGER, items TEXT, role TEXT)")
            db.executemany("INSERT INTO history VALUES (?, ?, ?, ?, ?)", baskets)
            db.commit()
        release_path = self.root / RELEASE
        release = json.loads(release_path.read_text(encoding="utf-8"))
        data = database.read_bytes()
        release["sources"].append({"path": EDGES, "sha256": hashlib.sha256(data).hexdigest(),
                                   "bytes": len(data)})
        release_path.write_text(json.dumps(release), encoding="utf-8")
        report = {
            "source_sha256": {s["path"]: s["sha256"] for s in release["sources"]},
            "counts": {"queries": len(rows), "gained": 2, "lost": 2},
            "net_extra_hit_queries": 0,
        }
        report_path = self.root / "reports/stage10/recency_slot_validation_201508.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path

    def test_recency_replays_first_query_level_gain_and_loss(self):
        self.save_recency_fixture()
        payload = ReplayLibrary.load(self.root).payload()
        self.assertEqual([case["id"] for case in payload["cases"]],
                         ["c1_only", "p0_only", "neither", "both"])
        recency = payload["recency"]
        self.assertEqual(recency["total_queries"], 9)
        self.assertEqual(recency["net_additional_hits"], 0)
        self.assertEqual([(case["id"], case["count"]) for case in recency["cases"]],
                         [("gained", 2), ("lost", 2)])
        gain, loss = recency["cases"]
        for case, recent in ((gain, "6"), (loss, "35")):
            self.assertEqual(case["c1"]["items"], RELATED)
            self.assertEqual(case["recency"]["items"], RELATED[:9] + [recent])
            self.assertIn(recent, case["history"])
        self.assertEqual(gain["targets"], ["6", "98"])
        self.assertEqual((gain["c1"]["hit_ranks"], gain["recency"]["hit_ranks"]), ([], [10]))
        self.assertEqual(gain["query_time"], gain["recent_time"])
        self.assertEqual(loss["targets"], ["20", "99"])
        self.assertEqual((loss["c1"]["hit_ranks"], loss["recency"]["hit_ranks"]), ([10], []))
        self.assertLess(loss["recent_time"], loss["query_time"])
        self.assertNotIn("private", json.dumps(recency))

    def test_missing_recency_report_preserves_original_replay(self):
        report = self.save_recency_fixture()
        report.unlink()
        payload = ReplayLibrary.load(self.root).payload()
        self.assertNotIn("recency", payload)
        self.assertEqual(payload["total_queries"], 9)
        self.assertEqual(len(payload["cases"]), 4)

    def test_recency_report_must_match_accepted_sources(self):
        report = self.save_recency_fixture()
        data = json.loads(report.read_text(encoding="utf-8"))
        data["source_sha256"][EDGES] = "0" * 64
        report.write_text(json.dumps(data), encoding="utf-8")
        payload = ReplayLibrary.load(self.root).payload()
        self.assertNotIn("recency", payload)
        self.assertEqual(payload["total_queries"], 9)

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
