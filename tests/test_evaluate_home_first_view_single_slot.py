import hashlib
import unittest

from scripts.evaluate_cart_recommendations import digest_row
from scripts.evaluate_home_first_view_single_slot import score_visitors, swap_tenth


class HomeSingleSlotTest(unittest.TestCase):
    baseline = [str(i) for i in range(1, 11)]

    def test_pick_first_training_outsider_skipping_original_tenth(self):
        full = ["10", "2", "12", "11", *self.baseline[2:8]]
        single, source_rank = swap_tenth(self.baseline, full)
        self.assertEqual((single, source_rank), ([*self.baseline[:9], "12"], 3))
        self.assertEqual(swap_tenth(self.baseline, self.baseline[::-1]), (self.baseline, None))
        with self.assertRaises(ValueError):
            swap_tenth(self.baseline, ["12"] * 10)

    def test_three_way_counts_distinguish_fewer_losses_from_visitors_recovered(self):
        full = ["1", "11", "12", "2", "3", "4", "5", "6", "7", "8"]
        single, _ = swap_tenth(self.baseline, full)
        examples = [
            ({"15"}, [None, None, None]), ({"12"}, [None, None, 3]),
            ({"11", "12"}, [None, 10, 2]), ({"10"}, [10, None, None]),
            ({"10", "12"}, [10, None, 3]), ({"9"}, [9, 9, None]), ({"1", "2"}, [1, 1, 1]),
        ]
        visitors = [(str(i), "new", 8, 10, targets) for i, (targets, _) in enumerate(examples)]
        visitors.append(("known", "seen_in_train", 8, 10, set()))
        score = score_visitors(visitors, self.baseline, single, full)
        self.assertEqual(score["hit_patterns_baseline_single_full"], {
            "000": 1, "001": 1, "010": 0, "011": 1, "100": 1, "101": 1, "110": 1, "111": 1,
        })
        self.assertEqual(score["single_vs_full_tradeoff"], {
            "full_gains_retained": 1, "share_of_full_gains_retained": 0.5, "full_gains_forgone": 1,
            "full_losses_recovered": 1, "hits_in_both_original_lists_lost_by_single": 1,
            "fewer_baseline_losses": 0, "single_hits_minus_full_hits": -1,
        })
        expected = hashlib.sha256()
        for i, (targets, best) in enumerate(examples):
            digest_row(expected, [str(i), 10, sorted(targets, key=int), *best])
        self.assertEqual(score["three_arm_best_ranks_sha256"], expected.hexdigest())
        solo = score["baseline_vs_single"]
        self.assertEqual(solo["scored_visitors"], len(examples))
        self.assertEqual(solo["gained_by_candidate_rank_1_to_10"], [0] * 9 + [1])
        self.assertEqual(solo["lost_by_baseline_rank_1_to_10"], [0] * 9 + [2])


if __name__ == "__main__":
    unittest.main()
