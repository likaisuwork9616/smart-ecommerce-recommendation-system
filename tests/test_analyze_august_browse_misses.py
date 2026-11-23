import unittest

from scripts.analyze_august_browse_misses import summarize
from scripts.evaluate_recency_slot import reserve_slot


def rank(item=None, position=1):
    items = [f"filler-{index}" for index in range(10)]
    if item is not None:
        items[position - 1] = item
    return items


def query(targets, candidate, original, recent, reachable):
    baseline = reserve_slot(original, recent)
    return (
        (1, 2, 3), set(targets),
        [(item, "knn") for item in candidate], [(item, "cooccurrence") for item in baseline],
        original, recent, reachable,
    )


class BrowseMissAnalysisTest(unittest.TestCase):
    def test_misses_use_paired_ranks_and_per_query_catalog_eligibility(self):
        summary = summarize([
            query({"a"}, rank(), rank("a"), "r", 1),
            query({"a"}, rank(), rank(), "a", 1),
            query({"a", "b"}, rank(), rank("a"), "b", 2),
            query({"a", "b"}, rank(), rank(), None, 2),
            query({"a", "b", "c"}, rank(), rank(), "r", 2),
            query({"a"}, rank(), rank(), "r", 0),
            query({"a"}, rank("a", 10), rank(), "r", 1),
            query({"a"}, rank(), rank("a", 10), "r", 1),
        ])
        self.assertEqual(summary["baseline_only"], {
            "queries": 3, "original_c1_also_hit": 2, "only_hit_after_recency_slot": 1,
        })
        self.assertEqual(summary["both_miss"], {
            "queries": 4, "at_least_one_target_eligible": 3, "all_targets_eligible": 2,
            "some_targets_eligible": 1, "no_targets_eligible": 1,
        })
        self.assertEqual(summary["original_c1_and_recency_counts"], {
            "c1_hits": 3, "recency_hits": 3, "gained": 1, "lost": 1,
        })
        self.assertEqual(summary["recency_opportunity"], {
            "k1_misses_with_selected_recent_item_as_target": 2, "k1_first_hits_at_rank_10": 1,
        })

    def test_recent_target_must_appear_in_reconstructed_baseline(self):
        key, targets, candidate, _, original, recent, reachable = query({"a"}, rank(), rank(), "a", 1)
        with self.assertRaisesRegex(ValueError, "lost its selected target"):
            summarize([(key, targets, candidate, candidate, original, recent, reachable)])


if __name__ == "__main__":
    unittest.main()
