import unittest

from scripts.purchase_popular_fill_replay import PurchaseFillExamples


class PurchaseFillReplayTests(unittest.TestCase):
    def test_overlap_uses_two_distinct_queries_and_keeps_multiple_targets(self):
        examples = PurchaseFillExamples()
        popular = [str(i) for i in range(1, 11)]
        examples.observe("99", {"2", "6"}, ("11",), popular)
        examples.observe("98", {"2"}, ("2",), popular)
        examples.observe("97", {"1"}, ("12", "14"), popular)
        stats = {"queries": 3, "popular_fill_vs": {
            "empty_fallback": {"gain": 2},
            "popular": {"later": 2},
        }}

        replay = examples.payload(stats)
        self.assertEqual(replay["overlap_queries"], 2)
        first, second = replay["cases"]
        self.assertEqual((first["id"], first["cohort_position"], first["targets"]), ("short_gain", 1, ["2", "6"]))
        self.assertEqual(first["cobuy"]["hit_ranks"], [])
        self.assertEqual(first["popular"]["hit_ranks"], [2, 6])
        self.assertEqual(first["popular_fill"]["hit_ranks"], [3, 7])
        self.assertEqual(first["popular_fill"]["sources"], ["cobuy"] + ["popular"] * 9)
        self.assertEqual((second["id"], second["cohort_position"]), ("popular_later", 3))
        self.assertEqual(second["popular_fill"]["items"][:3], ["12", "14", "1"])


if __name__ == "__main__":
    unittest.main()
