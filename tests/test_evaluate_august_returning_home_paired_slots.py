import unittest

from scripts.evaluate_august_returning_home_paired_slots import score_visitors


class TrainingModel:
    def recommend(self, seed):
        if seed == "81":
            raise KeyError(seed)  # A warm-up view outside the training catalog.
        if seed in {"1", "9", "10", "30"}:
            return {"recommendations": [
                {"source": "cooccurrence", "item_id": item} for item in ("100", "101", "7")
            ]}
        return {"recommendations": [{"source": "popularity", "item_id": "90"}]}


class PairedHomeSlotTests(unittest.TestCase):
    def score(self, rows):
        popular = [str(rank) for rank in range(1, 11)]
        visitors = [(str(i), "seen_in_warmup_only" if seed == "81" else "seen_in_train",
                     seed, 20, targets) for i, (seed, targets) in enumerate(rows)]
        return score_visitors(visitors, popular, TrainingModel())

    def test_each_arm_reserves_only_when_its_own_list_is_missing_the_seed(self):
        result = self.score([("9", {"9"}), ("1", {"1"}), ("10", {"10"}), ("9", {"10"})])
        # Popularity keeps all original seats. The unmodified C1 list has item 1
        # in fourth place and contains neither item 9 nor item 10.
        overall = result["overall"]
        self.assertEqual(overall["baseline"]["first_hit_counts_rank_1_to_10"], [1] + [0] * 7 + [1, 2])
        self.assertEqual(overall["candidate"]["first_hit_counts_rank_1_to_10"], [0] * 3 + [1] + [0] * 5 + [2])
        self.assertEqual(overall["both_hit_rank_change"], {"earlier": 0, "same": 1, "later": 2})
        self.assertEqual(overall["baseline_only_lost"], 1)
        actions = result["by_slot_action"]
        self.assertEqual(actions["baseline"]["already_in_top_ten"], 4)
        self.assertEqual(actions["candidate"]["already_in_top_ten"], 1)
        self.assertEqual(actions["candidate"]["replaced_rank_10"], 3)

    def test_joint_targets_and_rank_changes_score_each_visitor_once(self):
        # With seed 30, popularity shows 1..9 then 30. C1 shows
        # 100, 101, 7, 1, 2, 3, 4, 5, 6, 30.
        targets = [{"100"}, {"101"}, {"9"}, {"10"}, {"7", "30"}, {"1", "30"}, {"30"}, {"30", "101"}]
        result = self.score([("30", items) for items in targets])
        overall = result["overall"]
        self.assertEqual(overall["scored_visitors"], 8)
        self.assertEqual(overall["baseline"]["hits_at_10"], 5)
        self.assertEqual(overall["candidate"]["hits_at_10"], 6)
        self.assertEqual(overall["candidate_only_gained"], 2)
        self.assertEqual(overall["baseline_only_lost"], 1)
        self.assertEqual(overall["net_hits"], 1)
        self.assertEqual(overall["both_missed"], 1)
        self.assertEqual(overall["both_hit_rank_change"], {"earlier": 2, "same": 1, "later": 1})
        baseline_mrr = (1 + 1 / 7 + 1 / 9 + 2 / 10) / 8
        candidate_mrr = (1 + 2 / 2 + 1 / 3 + 1 / 4 + 1 / 10) / 8
        self.assertAlmostEqual(overall["baseline"]["mrr_at_10"], baseline_mrr)
        self.assertAlmostEqual(overall["candidate"]["mrr_at_10"], candidate_mrr)
        self.assertAlmostEqual(overall["mrr_at_10_delta"], candidate_mrr - baseline_mrr)
        self.assertEqual(result["by_strategy"]["personalized"]["net_hits"], 1)

    def test_fallback_arms_match_for_warmup_unpaired_and_no_view_visitors(self):
        result = self.score([("81", {"81"}), ("20", {"10"}), ("3", {"3"}), (None, {"10"})])
        overall = result["overall"]
        for arm in ("baseline", "candidate"):
            self.assertEqual(overall[arm]["first_hit_counts_rank_1_to_10"], [0, 0, 1] + [0] * 6 + [2])
        self.assertEqual(overall["both_hit_rank_change"], {"earlier": 0, "same": 3, "later": 0})
        self.assertEqual(overall["both_missed"], 1)
        for group, expected_n, expected_hits in (("no_pair", 3, 2), ("no_history", 1, 1)):
            counts = result["by_strategy"][group]
            self.assertEqual(counts["scored_visitors"], expected_n)
            self.assertEqual(counts["baseline_hits"], expected_hits)
            self.assertEqual(counts["candidate_hits"], expected_hits)
            self.assertEqual(counts["gained"], 0)
            self.assertEqual(counts["lost"], 0)
        self.assertEqual(result["visitor_bootstrap"]["hit_rate_delta_95_percentage_points"], [0, 0])


if __name__ == "__main__":
    unittest.main()
