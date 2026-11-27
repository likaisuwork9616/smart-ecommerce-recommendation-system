import unittest

from scripts.evaluate_august_returning_home_slot import score_visitors


class TrainingModel:
    def recommend(self, seed):
        if seed == "81":
            raise KeyError(seed)  # Viewed in warm-up only, absent from C1 training.
        neighbors = ["100", "101"] if seed == "30" else []
        return {"recommendations": [
            {"item_id": item, "source": "cooccurrence"} for item in neighbors
        ]}


class ReturningHomeSlotTests(unittest.TestCase):
    def score(self, rows):
        popular = [str(item) for item in range(1, 11)]
        return score_visitors(rows, popular, TrainingModel())

    def test_already_ranked_seeds_keep_their_exact_seats_and_no_prior_view_keeps_ten(self):
        result = self.score([
            ("a", "seen_in_train", "2", 20, {"2"}),
            ("b", "seen_in_train", "10", 20, {"10"}),
            ("c", "seen_in_train", None, 20, {"10"}),
        ])
        overall = result["overall"]
        self.assertEqual(overall["both_hit"], 3)
        self.assertEqual(overall["scored_visitors"], 3)
        for arm in ("baseline", "candidate"):
            self.assertEqual(overall[arm]["first_hit_counts_rank_1_to_10"], [0, 1] + [0] * 7 + [2])
            self.assertAlmostEqual(overall[arm]["mrr_at_10"], (1 / 2 + 1 / 10 + 1 / 10) / 3)
        actions = result["by_slot_action"]
        self.assertEqual(actions["already_in_top_ten"]["scored_visitors"], 2)
        self.assertEqual(actions["no_prior_view"]["scored_visitors"], 1)
        self.assertEqual(actions["replaced_rank_10"]["scored_visitors"], 0)
        self.assertEqual(result["visitor_bootstrap"]["hit_rate_delta_95_percentage_points"], [0, 0])

    def test_first_nine_are_retained_even_when_personalized_ranks_differ_from_popularity(self):
        first_nine = ["100", "101", "1", "2", "3", "4", "5", "6", "7"]
        rows = [(str(rank), "seen_in_train", "30", 20, {item}) for rank, item in enumerate(first_nine, 1)]
        overall = self.score(rows)["overall"]
        self.assertEqual(overall["both_hit"], 9)
        self.assertEqual(overall["net_hits"], 0)
        for arm in ("baseline", "candidate"):
            self.assertEqual(overall[arm]["first_hit_counts_rank_1_to_10"], [1] * 9 + [0])
            self.assertAlmostEqual(overall[arm]["mrr_at_10"], sum(1 / rank for rank in range(1, 10)) / 9)

    def test_gain_loss_warmup_and_tied_targets_are_counted_once_per_visitor(self):
        # The two neighbors push popular item 8 to the baseline's tenth seat.
        result = self.score([
            ("a", "seen_in_train", "30", 20, {"30"}),
            ("b", "seen_in_train", "30", 20, {"8"}),
            ("c", "seen_in_train", "30", 20, {"8", "30"}),
            ("d", "seen_in_train", "30", 20, {"100", "30"}),
            ("e", "seen_in_train", "30", 20, {"9"}),
            ("f", "seen_in_warmup_only", "81", 20, {"81"}),
        ])
        overall = result["overall"]
        self.assertEqual(overall["scored_visitors"], 6)
        self.assertEqual(overall["candidate_only_gained"], 2)
        self.assertEqual(overall["baseline_only_lost"], 1)
        self.assertEqual(overall["both_hit"], 2)
        self.assertEqual(overall["both_missed"], 1)
        self.assertEqual(overall["net_hits"], 1)
        self.assertEqual(overall["baseline"]["hits_at_10"], 3)
        self.assertEqual(overall["candidate"]["hits_at_10"], 4)
        self.assertEqual(overall["gained_by_candidate_rank_1_to_10"], [0] * 9 + [2])
        self.assertEqual(overall["lost_by_baseline_rank_1_to_10"], [0] * 9 + [1])
        self.assertAlmostEqual(overall["baseline"]["mrr_at_10"], (1 + 2 / 10) / 6)
        self.assertAlmostEqual(overall["candidate"]["mrr_at_10"], (1 + 3 / 10) / 6)
        self.assertAlmostEqual(overall["mrr_at_10_delta"], 1 / 60)
        self.assertEqual(result["by_slot_action"]["replaced_rank_10"]["scored_visitors"], 6)
        groups = result["by_baseline_strategy"]
        self.assertEqual(groups["personalized"]["scored_visitors"], 5)
        self.assertEqual(groups["personalized"]["gained"], 1)
        self.assertEqual(groups["personalized"]["lost"], 1)
        self.assertEqual(groups["no_pair"]["scored_visitors"], 1)
        self.assertEqual(groups["no_pair"]["gained"], 1)
        repeats = result["repeat_views"]
        self.assertEqual(repeats["visitors"], 4)
        self.assertEqual(repeats["already_hit_by_baseline"], 2)
        self.assertEqual(repeats["newly_hit"], 2)


if __name__ == "__main__":
    unittest.main()
