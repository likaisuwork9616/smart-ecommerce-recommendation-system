from contextlib import closing
import sqlite3
import unittest

from scripts.evaluate_august_returning_home import returning_visitors
from scripts.fit_july_returning_home import fit_model


class JulyReturningHomeTests(unittest.TestCase):
    def setUp(self):
        self.connection = self.enterContext(closing(sqlite3.connect(":memory:")))
        self.connection.execute("CREATE TABLE qualified (v TEXT,t INTEGER,e TEXT,i TEXT,role TEXT)")

    def insert(self, rows):
        self.connection.executemany("INSERT INTO qualified VALUES (?,?,?,?,?)", rows)

    def test_scoring_and_history_share_a_ledger_role_but_never_a_time_window(self):
        windows = {"warmup": (0, 10), "train": (10, 20), "validation": (20, 30)}
        self.insert([
            ("A", 19, "view", "30", "train"), ("A", 19, "view", "8", "train"),
            ("A", 20, "addtocart", "3", "train"), ("A", 21, "view", "70", "train"),
            ("A", 21, "view", "80", "train"), ("A", 21, "view", "90", "validation"),
            ("A", 25, "view", "5", "train"),
            ("B", 3, "view", "14", "warmup"), ("B", 20, "view", "14", "train"),
            ("C", 15, "transaction", "12", "train"), ("C", 29, "view", "77", "train"),
            ("D", 20, "addtocart", "15", "train"), ("D", 21, "view", "15", "train"),
            ("E", 12, "view", "4", "train"), ("E", 30, "view", "33", "train"),
        ])
        self.assertEqual(list(returning_visitors(self.connection, windows, scoring_role="train")), [
            ("A", "seen_in_train", "8", 21, {"70", "80"}),
            ("B", "seen_in_warmup_only", "14", 20, {"14"}),
            ("C", "seen_in_train", None, 29, {"77"}),
        ])

    def test_fit_stops_at_cutoff_and_counts_each_pair_once_per_view_session(self):
        start, end = 100, 10_000_000
        self.insert([
            ("1", start, "view", "8", "train"), ("1", start + 4, "view", "8", "train"),
            ("1", start + 1_800_004, "view", "70", "train"),
            ("1", start + 1_800_004, "view", "2", "train"),
            ("1", start + 1_800_004, "view", "11", "train"),
            ("1", start + 3_600_005, "view", "50", "train"),
            ("2", 200, "view", "8", "train"), ("2", 201, "view", "5", "train"),
            ("3", 200, "view", "5", "train"),
            ("4", 200, "view", "8", "train"), ("4", 202, "view", "70", "train"),
            ("4", 203, "addtocart", "77", "train"),
            ("4", 204, "view", "99", "validation"),
            ("5", start - 1, "view", "80", "warmup"),
            ("6", end, "view", "8", "train"), ("6", end, "view", "88", "train"),
        ])
        self.insert([(str(i), 300, "view", str(i), "train") for i in range(13, 19)])
        popular, model, _ = fit_model(self.connection, (start, end))
        self.assertEqual(popular[:3], ["8", "5", "70"])
        neighbors = model.recommend("8")["recommendations"]
        shared = [(row["item_id"], row["co_sessions"]) for row in neighbors if row["source"] == "cooccurrence"]
        self.assertEqual(shared, [("70", 2), ("5", 1), ("2", 1), ("11", 1)])
        with self.assertRaises(KeyError):
            model.recommend("88")


if __name__ == "__main__":
    unittest.main()
