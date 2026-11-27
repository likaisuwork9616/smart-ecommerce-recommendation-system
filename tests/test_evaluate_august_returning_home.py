from contextlib import closing
import sqlite3
import unittest

from scripts.evaluate_august_returning_home import candidate_ranking, returning_visitors, score_visitors


class SyntheticC1:
    def recommend(self, seed):
        listings = {
            "2": [("42", "cooccurrence"), ("3", "cooccurrence"), ("99", "popularity")],
            "4": [("42", "cooccurrence"), ("17", "cooccurrence")],
            "8": [("99", "popularity")],
        }
        return {"recommendations": [{"item_id": item, "source": source} for item, source in listings[seed]]}


class AugustReturningHomeTest(unittest.TestCase):
    windows = {"warmup": (0, 10), "train": (10, 20), "validation": (20, 30)}
    baseline = [str(i) for i in range(1, 11)]

    def visitors(self, rows):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE qualified (v TEXT,t INTEGER,e TEXT,i TEXT,role TEXT)")
            db.executemany("INSERT INTO qualified VALUES (?,?,?,?,?)", rows)
            return list(returning_visitors(db, self.windows))

    def test_only_prior_qualified_events_establish_history_and_only_august_views_are_targets(self):
        rows = [
            ("A", 0, "view", "80", "warmup"), ("A", 10, "view", "55", "train"),
            ("A", 18, "view", "11", "train"), ("A", 18, "view", "2", "train"),
            ("A", 19, "transaction", "90", "train"), ("A", 20, "view", "99", "train"),
            ("A", 20, "addtocart", "5", "validation"), ("A", 21, "view", "42", "validation"),
            ("A", 21, "view", "42", "validation"), ("A", 21, "view", "8", "validation"),
            ("A", 21, "transaction", "22", "validation"), ("A", 22, "view", "23", "validation"),
            ("B", 0, "view", "7", "warmup"), ("B", 20, "view", "9", "validation"),
            ("C", 19, "addtocart", "31", "train"), ("C", 20, "addtocart", "4", "validation"),
            ("C", 29, "view", "10", "validation"), ("C", 30, "view", "11", "validation"),
            ("D", 9, "view", "17", "warmup"), ("D", 21, "transaction", "71", "validation"),
            ("E", 20, "addtocart", "4", "validation"), ("E", 22, "view", "5", "validation"),
            ("F", 9, "view", "7", "train"), ("F", 10, "view", "8", "warmup"),
            ("F", 15, "view", "9", "validation"), ("F", 23, "view", "6", "validation"),
            ("G", 12, "view", "15", "train"), ("G", 30, "view", "16", "validation"),
            ("H", 9, "view", "13", "warmup"), ("H", 19, "addtocart", "7", "train"),
            ("H", 20, "view", "14", "validation"),
        ]
        expected = [
            ("A", "seen_in_train", "2", 21, {"42", "8"}),
            ("B", "seen_in_warmup_only", "7", 20, {"9"}),
            ("C", "seen_in_train", None, 29, {"10"}),
            ("H", "seen_in_train", "13", 20, {"14"}),
        ]
        self.assertEqual(self.visitors(rows), expected)
        self.assertEqual(self.visitors(reversed(rows)), expected)

    def test_homepage_uses_only_cooccurrence_seats_then_fills_from_the_fixed_top_ten(self):
        strategy, ranking, shared = candidate_ranking("2", self.baseline, SyntheticC1())
        self.assertEqual(strategy, "personalized")
        self.assertEqual(ranking, ["42", "3", "1", "2", "4", "5", "6", "7", "8", "9"])
        self.assertEqual(shared, 2)

    def test_no_history_or_no_usable_pair_preserves_the_entire_baseline(self):
        for seed, expected in ((None, "no_history"), ("8", "no_pair"), ("500", "no_pair")):
            with self.subTest(seed=seed):
                strategy, ranking, shared = candidate_ranking(seed, self.baseline, SyntheticC1())
                self.assertEqual((strategy, list(ranking), shared), (expected, self.baseline, 0))

    def test_full_denominator_includes_fallback_and_each_target_set_scores_once_at_best_rank(self):
        visitors = [
            ("gain", "seen_in_train", "4", 20, {"42", "17"}),
            ("loss", "seen_in_train", "4", 20, {"9", "10"}),
            ("both", "seen_in_warmup_only", "2", 20, {"1", "2", "3", "42"}),
            ("miss", "seen_in_train", "2", 20, {"99"}),
            ("only_cart_history", "seen_in_train", None, 21, {"3", "10"}),
            ("no_c1_pair", "seen_in_train", "8", 22, {"1"}),
        ]
        result = score_visitors(visitors, self.baseline, SyntheticC1())
        overall = result["overall"]
        self.assertEqual(overall["scored_visitors"], 6)
        self.assertEqual(overall["both_hit"], 3)
        self.assertEqual(overall["both_missed"], 1)
        self.assertEqual(overall["candidate_only_gained"], 1)
        self.assertEqual(overall["baseline_only_lost"], 1)
        self.assertEqual(overall["net_hits"], 0)
        self.assertEqual(overall["baseline"]["hits_at_10"], 4)
        self.assertEqual(overall["candidate"]["hits_at_10"], 4)
        self.assertEqual(overall["gained_by_candidate_rank_1_to_10"], [1] + [0] * 9)
        self.assertEqual(overall["lost_by_baseline_rank_1_to_10"], [0] * 8 + [1, 0])
        self.assertEqual(result["coverage"]["visitors_with_prior_view"], 5)
        self.assertEqual(result["coverage"]["visitors_with_cooccurrence"], 4)
        self.assertEqual(result["coverage"]["visitors_with_changed_ranking"], 4)
        self.assertEqual(result["coverage"]["visitors_with_full_candidate_top_ten"], 6)
        self.assertEqual(result["coverage"]["visitors_revisiting_prior_item"], 1)
        self.assertEqual(result["by_strategy"]["personalized"]["scored_visitors"], 4)
        for group in ("no_history", "no_pair"):
            self.assertEqual(result["by_strategy"][group]["both_hit"], 1)
            self.assertEqual(result["by_strategy"][group]["net_hits"], 0)


if __name__ == "__main__":
    unittest.main()
