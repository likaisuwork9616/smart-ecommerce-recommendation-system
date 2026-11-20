import unittest

from scripts.evaluate_cart_popular_fill import evaluate, popular_fill


class PopularCartFillTests(unittest.TestCase):
    def test_preserves_coadd_order_and_skips_duplicates_in_popular_order(self):
        mixed = popular_fill(["5", "2"], ["2", "1", "5", "7", "8", "9", "10", "11", "12", "13"])
        self.assertEqual(mixed[:2], [("5", "coadd"), ("2", "coadd")])
        self.assertEqual(mixed[2:], [(item, "popular") for item in ["1", "7", "8", "9", "10", "11", "12", "13"]])

    def test_separates_empty_fallback_from_short_list_fill_and_preserves_full_list(self):
        popular = [str(item) for item in range(1, 11)]
        full = [str(item) for item in range(11, 21)]
        result = evaluate([
            ("99", {"3"}, [], popular),
            ("99", {"3"}, ["11", "2"], popular),
            ("99", {"3"}, full, popular),
        ])
        arms = result["arms"]
        self.assertEqual([arms[arm]["hit_queries"] for arm in arms], [0, 3, 1, 2])
        self.assertEqual(arms["popular_fill"]["first_hit_counts_rank_1_to_10"], [0, 0, 1, 1, 0, 0, 0, 0, 0, 0])
        self.assertAlmostEqual(arms["popular_fill"]["mrr_at_10"], (1 / 3 + 1 / 4) / 3)
        self.assertEqual(result["popular_fill_vs"]["popular"],
                         {"gain": 0, "loss": 1, "earlier": 0, "same": 1, "later": 1, "both_miss": 0})
        self.assertEqual(result["popular_fill_slots_by_source"], {"coadd": 12, "popular": 18})
        self.assertEqual(result["popular_fill_first_hits_by_source"], {"coadd": 0, "popular": 2})
        self.assertEqual(result["independent_sql_verified_ranked_slots"], 30)

    def test_preserves_an_existing_coadd_hit_even_when_popular_lists_it_earlier(self):
        result = evaluate([("99", {"5", "9"}, ["11", "5"], ["5", "9", "1", "2", "3", "4", "6", "7", "8", "10"])])
        self.assertEqual(result["popular_fill_vs"]["coadd"]["same"], 1)
        self.assertEqual(result["popular_fill_vs"]["popular"]["later"], 1)
        self.assertEqual(result["popular_fill_first_hits_by_source"], {"coadd": 1, "popular": 0})


if __name__ == "__main__":
    unittest.main()
