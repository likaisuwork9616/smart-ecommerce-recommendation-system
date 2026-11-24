import unittest

from scripts.export_home_first_view import snapshot


class HomeFirstViewExportTests(unittest.TestCase):
    def setUp(self):
        self.baseline = [(str(100 + i), 50 - i) for i in range(10)]
        # One reordering, one existing product-card alias outside the homepage
        # top ten, and one product never shown anywhere in the public demo.
        self.candidate = [self.baseline[1], self.baseline[0], *self.baseline[2:8],
                          ("900", 2), ("901", 1)]
        self.aliases = {item: f"{rank:02d}" for rank, (item, _) in enumerate(self.baseline, 1)}
        self.aliases.update({"900": "41", "902": "76"})
        self.public = [{"item": self.aliases[item], "count": count} for item, count in self.baseline]
        self.report = {
            "paired": {
                "scored_visitors": 20, "both_hit": 7, "both_missed": 6, "candidate_only_gained": 4,
                "baseline_only_lost": 3, "net_hits": 1, "baseline": {"hits_at_10": 10},
                "candidate": {"hits_at_10": 11}, "hit_rate_change_percentage_points": 5.0,
                "lost_by_baseline_rank_1_to_10": [0] * 8 + [2, 1],
                "gained_by_candidate_rank_1_to_10": [0] * 8 + [1, 3],
            },
            "visitor_bootstrap": {"hit_rate_delta_95_percentage_points": [-10, 20]},
        }

    def test_aliases_and_attribution_stay_with_the_product(self):
        result = snapshot(self.baseline, self.candidate, self.aliases, self.public, self.report)
        self.assertEqual(result["baseline"][0], {"rank": 1, "item": "01", "other_rank": 2, "exclusive_hits": 0})
        self.assertEqual(result["candidate"][0], {"rank": 1, "item": "02", "other_rank": 2, "exclusive_hits": 0})
        self.assertEqual(result["baseline"][8], {"rank": 9, "item": "09", "other_rank": None, "exclusive_hits": 2})
        self.assertEqual(result["candidate"][8:], [
            {"rank": 9, "item": "41", "other_rank": None, "exclusive_hits": 1},
            {"rank": 10, "item": "77", "other_rank": None, "exclusive_hits": 3},
        ])
        self.assertNotIn("901", self.aliases)

    def test_shared_product_cannot_be_credited_with_a_gain(self):
        self.report["paired"]["gained_by_candidate_rank_1_to_10"] = [1] + [0] * 8 + [3]
        with self.assertRaisesRegex(ValueError, "only one list"):
            snapshot(self.baseline, self.candidate, self.aliases, self.public, self.report)

    def test_wrong_published_alias_or_unbalanced_total_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "public homepage"):
            snapshot(self.baseline, self.candidate, self.aliases, self.public[::-1], self.report)
        self.report["paired"]["baseline_only_lost"] += 1
        with self.assertRaisesRegex(ValueError, "visitor totals"):
            snapshot(self.baseline, self.candidate, self.aliases, self.public, self.report)


if __name__ == "__main__":
    unittest.main()
