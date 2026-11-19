import json
import sqlite3
import unittest

from scripts.evaluate_recency_slot import history_catalog, most_recent, reserve_slot


class RecencySlotTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE history (v TEXT, s INTEGER, t INTEGER, items TEXT)")
        # Items 2 and 10 have already appeared elsewhere; item 1 is new at time 12.
        rows = [("other", 0, 1, ["2", "10"]), ("v", 0, 4, ["4"]),
                ("v", 10, 10, ["3"]), ("v", 10, 12, ["1", "10", "2"]),
                ("v", 10, 15, ["5"]), ("v", 10, 16, ["6"])]
        self.db.executemany("INSERT INTO history VALUES (?, ?, ?, ?)",
                            [(v, s, t, json.dumps(items)) for v, s, t, items in rows])
        self.catalog = history_catalog(self.db)

    def test_uses_prefix_strict_eligibility_and_numeric_tie(self):
        self.assertEqual(most_recent(self.db, self.catalog, "v", 10, 12), ("2", 12))
        self.assertEqual(most_recent(self.db, self.catalog, "v", 10, 10), (None, None))

    def test_rechecks_older_basket_eligibility_at_query_time(self):
        self.assertEqual(most_recent(self.db, self.catalog, "v", 10, 15), ("1", 12))

    def test_existing_item_keeps_its_original_rank(self):
        ranked = [str(i) for i in range(10)]
        self.assertEqual(reserve_slot(ranked, "5"), ranked)
        self.assertEqual(reserve_slot(ranked, None), ranked)
        self.assertEqual(reserve_slot(ranked, "10"), ranked[:9] + ["10"])
        self.assertEqual(ranked[-1], "9")
