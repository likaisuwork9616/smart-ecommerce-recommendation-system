from contextlib import closing
import sqlite3
import unittest

from scripts.evaluate_july_home_first_view_pair import (
    concentration, july_scores, train_browse_ranking, train_first_view_ranking,
)


class JulyHomeFirstViewPairTest(unittest.TestCase):
    windows = {"warmup": (0, 10), "train": (10, 20), "validation": (20, 30)}

    def database(self, rows):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE qualified (v TEXT,t INTEGER,e TEXT,i TEXT,role TEXT)")
        db.executemany("INSERT INTO qualified VALUES (?,?,?,?,?)", rows)
        return db

    def test_fit_bounds_apply_to_both_rankings_even_when_july_shares_train_role(self):
        rows = [(f"v{i}", 10, "view", str(i), "train") for i in range(1, 12)] + [
            ("known", 9, "addtocart", "7", "warmup"), ("known", 19, "view", "2", "train"),
            ("new", 10, "transaction", "4", "train"), ("new", 11, "view", "10", "train"),
            ("new", 11, "view", "2", "train"), ("new", 12, "view", "10", "train"),
            ("new", 19, "view", "11", "train"), ("after", 20, "view", "11", "train"),
            ("bad", 19, "view", "11", "validation"), ("later", 30, "view", "11", "train"),
        ]
        with closing(self.database(rows)) as db:
            baseline = train_browse_ranking(db, self.windows)
            candidate, training = train_first_view_ranking(db, self.windows)
        self.assertEqual(baseline[:3], [("2", 3), ("10", 3), ("11", 2)])
        self.assertEqual(candidate[:3], [("2", 2), ("10", 2), ("1", 1)])
        self.assertNotIn(("11", 1), candidate)
        self.assertEqual(training["visitors_with_first_view"], 12)
        self.assertEqual(training["visitor_item_votes"], 13)

    def test_score_only_july_new_visitors_and_only_their_first_view_set(self):
        rows = [
            ("warm", 9, "transaction", "5", "warmup"), ("warm", 20, "view", "1", "train"),
            ("prior", 19, "addtocart", "5", "train"), ("prior", 20, "view", "11", "train"),
            ("none", 20, "transaction", "7", "train"),
            ("both", 20, "view", "1", "train"), ("both", 20, "view", "11", "train"),
            ("gain", 20, "addtocart", "4", "train"), ("gain", 29, "view", "11", "train"),
            ("gain", 29, "view", "12", "train"), ("loss", 20, "view", "2", "train"),
            ("loss", 21, "view", "11", "train"), ("miss", 22, "view", "20", "train"),
            ("miss", 30, "view", "1", "train"), ("out", 30, "view", "1", "validation"),
            ("wrong-role", 20, "view", "3", "validation"),
        ]
        baseline = [(str(i), 1) for i in range(1, 11)]
        candidate = [(str(i), 1) for i in range(6, 16)]
        with closing(self.database(reversed(rows))) as db:
            scores, cohort = july_scores(db, self.windows, baseline, candidate)
        self.assertEqual(cohort, {"active": 7, "seen_in_training": 1, "seen_in_warmup_only": 1,
                                  "first_observed_in_july": 5, "new_without_view": 1, "new_with_view": 4})
        self.assertEqual([scores[k] for k in ("both_hit", "candidate_only_gained",
                                              "baseline_only_lost", "both_missed")], [1, 1, 1, 1])
        self.assertEqual(scores["gained_by_candidate_rank_1_to_10"], [0] * 5 + [1] + [0] * 4)

    def test_concentration_uses_exclusive_gains_and_handles_no_gain_and_ties(self):
        def example(gains, losses):
            return concentration({"gained_by_candidate_rank_1_to_10": gains,
                                  "candidate_only_gained": sum(gains), "net_hits": sum(gains) - losses})

        result = example([7, 0, 7, 1] + [0] * 6, 9)
        self.assertEqual(result["top_candidate_ranks"], [1, 3])
        self.assertEqual(result["share_of_gains"], 7 / 15)
        self.assertEqual(result["other_gains_minus_all_losses"], -1)
        empty = example([0] * 10, 2)
        self.assertEqual(empty["top_candidate_ranks"], [])
        self.assertIsNone(empty["share_of_gains"])


if __name__ == "__main__":
    unittest.main()
