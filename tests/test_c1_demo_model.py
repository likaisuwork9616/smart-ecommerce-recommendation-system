import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import c1_demo_model as demo
from scripts import retailrocket_cooccurrence as c1
from scripts import retailrocket_popularity as p0


class C1DemoTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.counts = {str(i): 10 for i in range(1, 16)}
        self.counts["12"] = 11
        self.support = {item: 8 for item in self.counts}
        # Both edge directions, a P0 tie-break, then a numeric ID tie-break.
        self.pairs = {("1", "5"): 2, ("5", "12"): 2, ("5", "10"): 2, ("2", "5"): 3}
        database = self.root / demo.EDGES
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        with connection:
            connection.execute("CREATE TABLE edges (a TEXT, b TEXT, n INTEGER)")
            connection.executemany("INSERT INTO edges VALUES(?, ?, ?)",
                                   [(a, b, n) for (a, b), n in self.pairs.items()])
        connection.close()
        for name, column, data in ((demo.POPULARITY, "count", self.counts),
                                   (demo.SUPPORT, "support", self.support)):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["itemid", column])
                writer.writerows(data.items())
        sources = [{"path": name, "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest()}
                   for name in (demo.SUPPORT, demo.EDGES, demo.POPULARITY)]
        receipt = self.root / demo.RELEASE
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"sources": sources}), encoding="utf-8")
        self.model = demo.C1DemoModel.load(self.root)

    def test_every_single_seed_matches_original_ranker(self):
        # Add a warmup-only item to the full catalog, outside the fitted selector.
        catalog = p0.Catalog([(item, 1) for item in (*self.support, "999")])
        original = c1.Ranker(c1.Model(self.support, self.pairs, "fixture", {}), self.counts, catalog)
        for seed in self.support:
            with self.subTest(seed=seed):
                actual = self.model.recommend(seed)["recommendations"]
                expected = original.rank(2, [seed])
                self.assertEqual([row["item_id"] for row in actual], expected["ids"])
                self.assertEqual([row["rank"] for row in actual], list(range(1, len(actual) + 1)))
                for row, (num, den) in zip(actual, expected["scores"], strict=True):
                    self.assertEqual(row["co_sessions"] * den, num * self.support[seed])
                    self.assertEqual(row["source"], "cooccurrence" if num else "popularity")
        self.assertEqual(self.model.recommend("3")["positive_candidates"], 0)

    def test_seed_search_and_unknown_item(self):
        self.assertEqual(self.model.search()[0]["item_id"], "12")
        self.assertEqual([row["item_id"] for row in self.model.search("1", 3)], ["1", "10", "11"])
        self.assertEqual(self.model.search("abc"), [])
        self.assertEqual(self.model.search("99"), [])
        with self.assertRaises(KeyError):
            self.model.recommend("999")

    def test_refuses_changed_frozen_input(self):
        with (self.root / demo.SUPPORT).open("a", encoding="utf-8") as stream:
            stream.write("30,1\n")
        with self.assertRaisesRegex(ValueError, "support.csv"):
            demo.C1DemoModel.load(self.root)
