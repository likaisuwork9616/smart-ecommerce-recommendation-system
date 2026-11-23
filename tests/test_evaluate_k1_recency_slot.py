import unittest

from scripts.evaluate_k1_recency_slot import evaluate


def query(targets, recent):
    original = [(f"i{rank}", "knn") for rank in range(1, 11)]
    return (1, 2, 3), set(targets), original, [], [], recent, len(targets)


class K1RecencyEvaluationTest(unittest.TestCase):
    def test_rank_ten_changes_are_paired_and_misses_count_as_zero(self):
        result = evaluate([
            query({"recent"}, "recent"),
            query({"i10"}, "recent"),
            query({"i4"}, "i4"),
            query({"other"}, None),
            query({"i1"}, "recent"),
            query({"i10", "recent"}, "recent"),
            query({"other", "recent"}, "recent"),
        ])
        self.assertEqual(result["list_changes"], {
            "no_eligible_recent_item": 1,
            "recent_item_already_in_top10": 1,
            "replaced_rank_10": 5,
        })
        self.assertEqual(result["paired_first_hit_changes"], {
            "gain": 2, "loss": 1, "earlier": 0, "same": 3, "later": 0, "both_miss": 1,
        })
        original, revised = result["original_k1"], result["k1_with_recency"]
        self.assertEqual((original["hit_queries"], revised["hit_queries"], result["net_extra_hit_queries"]), (4, 5, 1))
        self.assertEqual(original["first_hit_counts_rank_1_to_10"][:-1],
                         revised["first_hit_counts_rank_1_to_10"][:-1])
        self.assertAlmostEqual(original["mrr_at_10"], 1.45 / 7)
        self.assertAlmostEqual(revised["mrr_at_10"], 1.55 / 7)
        self.assertAlmostEqual(result["mrr_at_10_delta"], 0.1 / 7)


if __name__ == "__main__":
    unittest.main()
