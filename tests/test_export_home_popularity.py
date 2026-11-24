import sqlite3
import unittest
from contextlib import closing

from scripts.export_home_popularity import WINDOWS, basket_rankings


class HomePopularityTests(unittest.TestCase):
    def test_training_bounds_event_counts_and_unique_items_per_visitor_transaction(self):
        start, end = WINDOWS["train"]
        rows = [
            ("train", start, "v1", "addtocart", "10", ""),
            ("train", start + 1, "v1", "addtocart", "10", ""),
            ("train", start, "v2", "addtocart", "2", ""),
            ("train", end - 1, "v2", "addtocart", "2", ""),
            ("train", start, "v1", "transaction", "9", "x"),
            ("train", start + 1, "v1", "transaction", "9", "x"),
            ("train", start + 2, "v2", "transaction", "9", "x"),
            ("train", start + 3, "v1", "transaction", "8", "x"),
            ("validation", start + 1, "v1", "transaction", "8", "y"),
            ("validation", start + 1, "v1", "addtocart", "10", ""),
            ("train", end, "v1", "transaction", "8", "z"),
            ("train", start - 1, "v1", "addtocart", "10", ""),
        ]
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE qualified (role, t, v, e, i, x)")
            db.executemany("INSERT INTO qualified VALUES (?, ?, ?, ?, ?, ?)", rows)
            db.execute("CREATE TABLE raw AS SELECT *, t AS rt, '' AS bad FROM qualified")
            self.assertEqual(basket_rankings(db), {
                "cart": [("2", 2), ("10", 2)],
                "purchase": [("9", 2), ("8", 1)],
            })


if __name__ == "__main__":
    unittest.main()
