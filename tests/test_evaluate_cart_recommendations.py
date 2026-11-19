import sqlite3
import unittest

from scripts.audit_retailrocket_cart_support import GAP_MS
from scripts.evaluate_cart_recommendations import activity_rows, build_model, evaluate


def cart(visitor, time, *items):
    return [(visitor, time, "addtocart", str(item)) for item in items]


def model_with_one_pair():
    # Two visitors co-add 100 and 200. Ten unrelated items are individually
    # more popular, so either ranking can win on the same next basket.
    rows = cart("p", 0, 100, 200) + cart("q", 0, 100, 200)
    for item in range(1, 11):
        for t in range(3):
            rows.extend(cart(f"single-{item}", t, item))
    return build_model(sorted(rows))


class CartRecommendationTests(unittest.TestCase):
    def test_distinct_visitors_not_repeated_sessions_or_additions(self):
        rows = (
            cart("a", 0, 100, 10, 2, 7)
            + cart("a", 1, 7)
            + cart("a", GAP_MS + 2, 100, 7)
            + cart("b", 0, 2, 100, 10)
        )
        model = build_model(rows)
        self.assertEqual(list(model.rank("100")[0]), ["2", "10"])
        self.assertEqual(list(model.rank("7")[0]), [])
        self.assertIn("100", model.rank("2")[0])

    def test_top_ten_numeric_ties_and_exclusion_before_cutoff(self):
        # Item 1 sits inside both unfiltered top tens. Item 10 fills its
        # position. Ranking decimal strings lexicographically would admit 11.
        items = list(range(12))
        rows = cart("a", 0, *reversed(items)) + cart("b", 0, *items)
        neighbors, popular = build_model(rows).rank("1")
        expected = ["0"] + [str(i) for i in range(2, 11)]
        self.assertEqual(list(neighbors), expected)
        self.assertEqual(list(popular), expected)

    def test_visitors_rank_pairs_and_event_occurrences_rank_popularity(self):
        rows = (
            cart("a", 0, 100, 2, 10)
            + cart("a", 1, 2) + cart("a", 2, 2)
            + cart("b", 0, 100, 2, 10)
            + cart("c", 0, 100, 10)
        )
        neighbors, popular = build_model(rows).rank("100")
        self.assertEqual(list(neighbors), ["10", "2"])
        self.assertEqual(list(popular), ["2", "10"])

    def test_session_gap_uses_views_and_splits_strictly_over_thirty_minutes(self):
        rows = (
            cart("a", 0, 900) + cart("a", GAP_MS, 1)
            + [("a", 2 * GAP_MS, "view", "40")]
            + cart("a", 3 * GAP_MS, 2)
            + cart("a", 4 * GAP_MS + 1, 3)
            + cart("b", 4 * GAP_MS + 2, 4)
        )
        result = evaluate(rows, model_with_one_pair())
        self.assertEqual(result["all_cart_opportunities"]["queries"], 5)
        self.assertEqual(result["all_cart_opportunities"]["no_later_cart"], 3)
        self.assertEqual(result["scorable"]["queries"], 2)
        self.assertEqual(result["scorable"]["popular"]["hit_queries"], 2)

    def test_same_time_multi_seed_targets_and_self_only_no_lookahead(self):
        # At time zero each distinct seed is its own opportunity. The target
        # set at time one is {100, 200}. Later, 200 -> {200} has no other item
        # and must not skip forward to 1. Equal-time event order is immaterial.
        rows = (
            cart("a", 0, 100, 900) + cart("a", 1, 100, 200)
            + cart("a", 2, 200) + cart("a", 3, 1)
        )
        model = model_with_one_pair()
        result = evaluate(rows, model)
        reversed_ties = cart("a", 0, 900, 100) + cart("a", 1, 200, 100) + rows[4:]
        self.assertEqual(result, evaluate(reversed_ties, model))
        self.assertEqual(result["all_cart_opportunities"]["queries"], 6)
        self.assertEqual(result["all_cart_opportunities"]["no_later_cart"], 1)
        self.assertEqual(result["all_cart_opportunities"]["next_cart_only_seed"], 1)
        self.assertEqual(result["scorable"]["queries"], 4)
        self.assertEqual(result["scorable"]["coadd"]["hit_queries"], 2)

    def test_all_query_vs_covered_denominators_and_paired_outcomes(self):
        rows = (
            cart("a", 0, 100) + cart("a", 1, 200, 1)
            + cart("b", 0, 100) + cart("b", 1, 200)
            + cart("c", 0, 900) + cart("c", 1, 1)
            + cart("d", 0, 900) + cart("d", 1, 999)
        )
        result = evaluate(rows, model_with_one_pair())
        all_seeds = result["all_cart_opportunities"]
        self.assertEqual(all_seeds["queries"], 9)
        self.assertEqual(all_seeds["no_later_cart"], 5)
        self.assertEqual(all_seeds["coadd"]["with_recommendations"], 4)
        scorable = result["scorable"]
        self.assertEqual(scorable["queries"], 4)
        self.assertEqual(scorable["paired_hits"],
                         {"both": 1, "coadd_only": 1, "popular_only": 1, "neither": 1})
        pairs, popular = scorable["coadd"], scorable["popular"]
        self.assertEqual((pairs["with_recommendations"], pairs["full_ten"], pairs["hit_queries"]),
                         (2, 0, 2))
        self.assertEqual((popular["with_recommendations"], popular["full_ten"], popular["hit_queries"]),
                         (4, 4, 2))
        self.assertEqual((pairs["hit_rate_all"], pairs["hit_rate_when_recommended"]), (0.5, 1.0))
        self.assertEqual((popular["hit_rate_all"], popular["hit_rate_when_recommended"]), (0.5, 0.5))
        self.assertEqual(scorable["on_coadd_covered_queries"],
                         {"queries": 2, "coadd_hit_queries": 2, "popular_hit_queries": 1})
        self.assertEqual(scorable["seed_absent_from_training_carts"], 2)
        self.assertEqual(scorable["all_targets_absent_from_training_carts"], 1)

    def test_no_scorable_target_leaves_rates_undefined(self):
        result = evaluate(cart("a", 0, 900), model_with_one_pair())
        self.assertEqual(result["all_cart_opportunities"]["queries"], 1)
        self.assertEqual(result["scorable"]["queries"], 0)
        for arm in ("coadd", "popular"):
            self.assertIsNone(result["scorable"][arm]["hit_rate_all"])
            self.assertIsNone(result["scorable"][arm]["hit_rate_when_recommended"])

    def test_several_next_items_in_top_ten_are_a_single_query_hit(self):
        model = build_model(cart("a", 0, 1, 2, 3) + cart("b", 0, 3, 2, 1))
        result = evaluate(cart("v", 0, 1) + cart("v", 1, 3, 2), model)
        self.assertEqual(result["scorable"]["queries"], 1)
        self.assertEqual(result["scorable"]["coadd"]["hit_queries"], 1)
        self.assertEqual(result["scorable"]["popular"]["hit_queries"], 1)
        self.assertEqual(result["scorable"]["paired_hits"]["both"], 1)

    def test_sql_reader_keeps_role_window_half_open_and_excludes_transactions(self):
        lo, hi = 1438387200000, 1441065600000
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE qualified(v TEXT, t INTEGER, e TEXT, i TEXT, role TEXT)")
        rows = [
            ("a", lo - 1, "addtocart", "1", "validation"),
            ("a", lo, "addtocart", "2", "train"),
            ("a", lo, "addtocart", "3", "validation"),
            ("a", lo + GAP_MS, "transaction", "4", "validation"),
            ("a", lo + 2 * GAP_MS, "addtocart", "5", "validation"),
            ("a", hi - 1, "view", "6", "validation"),
            ("a", hi, "addtocart", "7", "validation"),
            ("a", hi, "addtocart", "8", "test"),
        ]
        db.executemany("INSERT INTO qualified VALUES(?,?,?,?,?)", reversed(rows))
        accepted = list(activity_rows(db, "validation", lo, hi))
        self.assertEqual(accepted, [rows[n][:4] for n in (2, 4, 5)])
        self.assertEqual(evaluate(accepted, model_with_one_pair())["scorable"]["queries"], 0)
        with self.assertRaises(ValueError):
            list(activity_rows(db, "test", lo, hi))
        with self.assertRaises(ValueError):
            list(activity_rows(db, "validation", lo, hi + 1))


if __name__ == "__main__":
    unittest.main()
