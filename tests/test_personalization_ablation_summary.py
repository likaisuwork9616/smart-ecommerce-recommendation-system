import unittest
from collections import Counter
from itertools import product

from scripts.evaluate_august_action_ablation import record_combined_change, segment_report
from scripts.evaluate_august_personalization import PairedResults


class CombinedHitChangeTests(unittest.TestCase):
    def test_single_action_matches_a_gain_by_hitting_at_any_rank(self):
        cases = [
            ((None, 9, None, 3), "cart_only"),
            ((None, None, 10, 3), "purchase_only"),
            ((None, 7, 1, 3), "either_alone"),
            ((None, None, None, 3), "combined_only"),
        ]
        for ranks, category in cases:
            with self.subTest(ranks=ranks):
                counts = {"gain": Counter(), "loss": Counter()}
                record_combined_change(counts, ranks)
                self.assertEqual(counts, {"gain": {category: 1}, "loss": {}})

    def test_single_action_matches_a_loss_only_if_it_also_misses(self):
        cases = [
            ((5, None, 9, None), "cart_only"),
            ((5, 10, None, None), "purchase_only"),
            ((5, None, None, None), "either_alone"),
            ((5, 7, 1, None), "combined_only"),
        ]
        for ranks, category in cases:
            with self.subTest(ranks=ranks):
                counts = {"gain": Counter(), "loss": Counter()}
                record_combined_change(counts, ranks)
                self.assertEqual(counts, {"gain": {}, "loss": {category: 1}})

    def test_joint_misses_and_rank_movements_do_not_change_either_count(self):
        counts = {"gain": Counter(cart_only=2), "loss": Counter(either_alone=3)}
        for cart, purchase in product((None, 10), repeat=2):
            for before, after in ((None, None), (1, 10), (10, 1), (2, 2)):
                record_combined_change(counts, (before, cart, purchase, after))
        self.assertEqual(counts, {"gain": {"cart_only": 2}, "loss": {"either_alone": 3}})

    def test_segment_report_uses_same_baseline_for_each_arm(self):
        arms = {key: PairedResults() for key in ("add_cart", "add_purchase", "add_both")}
        for visitor, base, cart, purchase, both in [
            ("10", None, 1, None, 4), ("10", 3, 5, None, None), ("20", None, 2, None, None),
        ]:
            for key, rank in (("add_cart", cart), ("add_purchase", purchase), ("add_both", both)):
                arms[key].add(visitor, base, rank, rank != base)
        settings = {"seed": 2, "replicates": 10, "percentiles": [2.5, 97.5], "quantile_method": "linear"}
        reference = arms["add_both"].report(settings)
        result = segment_report(arms, reference, settings)
        self.assertEqual((result["queries"], result["visitors"]), (3, 2))
        hits = {key: arm["hit_queries"] for key, arm in result["arms"].items()}
        self.assertEqual(hits, {"browse_only": 1, "add_cart": 3, "add_purchase": 0, "add_both": 1})
        deltas = {key: arm["net_extra_hits"] for key, arm in result["versus_browse_only"].items()}
        self.assertEqual(deltas, {"add_cart": 2, "add_purchase": -1, "add_both": 0})
        with self.assertRaises(ValueError):
            segment_report(arms, dict(reference, net_extra_hits=1), settings)


if __name__ == "__main__":
    unittest.main()
