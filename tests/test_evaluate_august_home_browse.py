from contextlib import closing
import sqlite3
import unittest

from scripts.evaluate_august_home_browse import score, visitor_rows


class AugustHomepageBrowseTest(unittest.TestCase):
    windows = {"warmup": (0, 10), "train": (10, 20), "validation": (20, 30)}
    ranked = [(str(100 + n), str(n)) for n in range(1, 11)]

    def run_study(self, rows):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE qualified (v TEXT,t INTEGER,e TEXT,i TEXT,role TEXT)")
            db.executemany("INSERT INTO qualified VALUES (?,?,?,?,?)", rows)
            return score(visitor_rows(db, self.windows), self.ranked)

    def test_any_prior_event_excludes_visitor_and_only_august_views_count(self):
        result = self.run_study([
            ("A", 0, "addtocart", "3", "warmup"), ("A", 21, "view", "101", "validation"),
            ("B", 19, "transaction", "1", "train"), ("B", 20, "view", "101", "validation"),
            ("C", 19, "addtocart", "2", "train"), ("C", 9, "view", "101", "warmup"),
            ("C", 20, "addtocart", "101", "validation"),
            ("D", 20, "transaction", "101", "validation"),
            ("E", 21, "view", "101", "train"),     # misplaced training role
            ("E", 29, "view", "110", "validation"), ("E", 30, "view", "101", "validation"),
            ("F", 19, "view", "101", "validation"), ("G", 24, "view", "101", "reserved_test"),
            ("H", 30, "view", "101", "reserved_test"),
        ])
        history = result["by_observed_history"]
        self.assertEqual(result["august_active_visitors"], 5)
        self.assertEqual(history["seen_in_train"], {"active": 2, "with_view": 1, "without_view": 1})
        self.assertEqual(history["seen_in_warmup_only"]["with_view"], 1)
        self.assertEqual(history["first_observed_in_august"], {"active": 2, "with_view": 1, "without_view": 1})
        self.assertEqual(result["scored_visitors"], 1)
        self.assertEqual(result["first_hit_by_rank"][-1]["visitors"], 1)
        self.assertEqual(result["hit_at_k"]["5"]["hits"], 0)

    def test_first_view_basket_counts_best_hit_once_and_ignores_later_views(self):
        rows = [
            ("A", 22, "view", "103", "validation"), ("A", 22, "view", "103", "validation"),
            ("A", 22, "view", "106", "validation"), ("A", 22, "addtocart", "101", "validation"),
            ("A", 23, "view", "101", "validation"), ("B", 20, "transaction", "101", "validation"),
            ("B", 24, "view", "101", "validation"), ("C", 21, "view", "2", "validation"),
            ("C", 22, "view", "101", "validation"), ("D", 21, "transaction", "101", "validation"),
            ("D", 22, "view", "2", "validation"),
        ]
        result = self.run_study(rows)
        self.assertEqual(result, self.run_study(reversed(rows)))
        self.assertEqual(result["scored_visitors"], 4)
        self.assertEqual(result["hit_at_k"], {"1": {"hits": 1, "rate": .25},
                                               "5": {"hits": 2, "rate": .5},
                                               "10": {"hits": 2, "rate": .5}})
        self.assertEqual([row["visitors"] for row in result["first_hit_by_rank"]], [1, 0, 1] + [0] * 7)
        self.assertEqual(result["misses_at_10"], 2)
        self.assertEqual(result["first_view_timestamp"], {"total_distinct_items_across_visitors": 5,
                                                         "max_distinct_items": 2, "multiple_distinct_items": 1,
                                                         "multiple_distinct_items_with_hit": 1,
                                                         "multiple_top_ten_items": 1})
        self.assertEqual(result["by_first_august_activity"],
                         {name: {"visitors": 2, "hits_at_10": 1} for name in (
                             "first_activity_includes_view", "activity_precedes_first_view")})

    def test_empty_cohort_has_no_rate(self):
        result = self.run_study([("A", 21, "addtocart", "101", "validation")])
        self.assertEqual(result["hit_at_k"]["10"], {"hits": 0, "rate": None})


if __name__ == "__main__":
    unittest.main()
