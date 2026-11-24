import sqlite3
import unittest
from contextlib import closing

from scripts.evaluate_august_home_browse import visitor_rows
from scripts.evaluate_august_home_first_view_pair import paired_scores, train_first_view_ranking


class AugustFirstViewPairTest(unittest.TestCase):
    windows = {"warmup": (0, 10), "train": (10, 20), "validation": (20, 30)}

    def database(self, rows):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE qualified (v TEXT,t INTEGER,e TEXT,i TEXT,role TEXT)")
        db.executemany("INSERT INTO qualified VALUES (?,?,?,?,?)", rows)
        return db

    def test_training_votes_keep_ties_and_ignore_known_visitors_and_later_events(self):
        rows = [
            ("known", 9, "transaction", "91", "warmup"), ("known", 10, "view", "91", "train"),
            ("a", 10, "addtocart", "91", "train"), ("a", 11, "view", "10", "train"),
            ("a", 11, "view", "2", "train"), ("a", 11, "view", "2", "train"),
            ("a", 12, "view", "91", "train"), ("b", 19, "view", "2", "train"),
            ("c", 18, "transaction", "2", "train"), ("late", 20, "view", "91", "train"),
            ("invalid_role", 14, "view", "91", "reserved_test"),
            ("before", 9, "view", "91", "train"), ("aug", 20, "view", "91", "validation"),
        ]
        rows += [(f"visitor-{i}", 10, "view", str(i), "train") for i in (1, 3, 4, 5, 6, 7, 8, 9, 11)]
        with closing(self.database(reversed(rows))) as db:
            top, summary = train_first_view_ranking(db, self.windows)
        self.assertEqual(top, [("2", 2), ("1", 1)] + [(str(i), 1) for i in range(3, 11)])
        self.assertEqual(summary, {"visitors_with_first_view": 11, "visitors_with_multiple_first_items": 1,
                                   "distinct_first_view_items": 11, "visitor_item_votes": 12})

    def test_compares_the_two_lists_for_each_visitor_and_counts_a_multi_item_hit_once(self):
        visits = [
            ("both", 20, "view", "1", "validation"), ("both", 20, "view", "15", "validation"),
            ("gained", 21, "view", "11", "validation"), ("gained", 21, "view", "12", "validation"),
            ("gain_again", 22, "view", "15", "validation"),
            ("lost", 22, "view", "1", "validation"), ("lost", 23, "view", "11", "validation"),
            ("miss", 22, "view", "100", "validation"), ("no_view", 20, "transaction", "11", "validation"),
            ("older", 11, "addtocart", "100", "train"), ("older", 24, "view", "11", "validation"),
        ]
        baseline = [(str(i), str(i)) for i in range(1, 11)]
        candidate = [(str(i), 1) for i in range(6, 16)]
        with closing(self.database(visits)) as db:
            result = paired_scores(visitor_rows(db, self.windows), baseline, candidate)
        self.assertEqual(result["scored_visitors"], 5)
        self.assertEqual(result["candidate_only_gained"], 2)
        for field in ("both_hit", "baseline_only_lost", "both_missed"):
            self.assertEqual(result[field], 1)
        self.assertEqual(result["baseline"], {"hits_at_10": 2, "hit_rate_at_10": .4})
        self.assertEqual(result["candidate"], {"hits_at_10": 3, "hit_rate_at_10": .6})
        self.assertEqual(result["net_hits"], 1)
        self.assertEqual(result["hit_rate_change_percentage_points"], 20)
        self.assertEqual(result["gained_by_candidate_rank_1_to_10"], [0] * 5 + [1, 0, 0, 0, 1])
        self.assertEqual(result["lost_by_baseline_rank_1_to_10"], [1] + [0] * 9)


if __name__ == "__main__":
    unittest.main()
