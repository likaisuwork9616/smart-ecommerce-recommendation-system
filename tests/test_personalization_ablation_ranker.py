import unittest

from scripts.personalization_ranker import PersonalizationRanker
from scripts.retailrocket_popularity import Catalog
from tests.test_august_personalization_pair import exact_ranking, graph


WEIGHTS_BY_ARM = (
    {"view": 1, "addtocart": 0, "transaction": 0},
    {"view": 1, "addtocart": 3, "transaction": 0},
    {"view": 1, "addtocart": 0, "transaction": 5},
    {"view": 1, "addtocart": 3, "transaction": 5},
)


class AblationRankerTest(unittest.TestCase):
    def test_incremental_arms_match_full_fraction_sort_for_either_action_order(self):
        items = [str(i) for i in range(1, 25)]
        support = {item: 20 + int(item) % 7 for item in items}
        popularity = {item: 40 + int(item) % 4 for item in items}
        edges = [(left, right, 1 + (i * 3 + j) % 17)
                 for i, left in enumerate(items[:20]) for j, right in enumerate(items[:i])
                 if (i + j) % 3]
        catalog = Catalog((item, 1 if int(item) % 4 else 3) for item in [*items, "30"])
        model = PersonalizationRanker(support, popularity, graph(edges), catalog)
        for first, second in (("addtocart", "transaction"), ("transaction", "addtocart")):
            profile = model.new_ablation_profile()
            paired = model.new_profile()
            observations = []
            queries = (
                (1, [("21", first)]),                     # supported item without neighbors
                (2, [("1", "view"), ("22", second)]),
                (3, [("2", first), ("2", first)]),        # duplicate action
                (4, [("3", "view"), ("2", "view")]),
                (5, [("7", second), ("2", second)]),      # overlap with first action
                (6, [("4", first), ("1", second), ("8", "view")]),
                (7, []),
            )
            for when, new_events in queries:
                with self.subTest(first=first, when=when):
                    for item, kind in new_events:
                        profile.observe(item, kind)
                        paired.observe(item, kind)
                    observations.extend(new_events)
                    expected = tuple(exact_ranking(observations, weights, support, popularity,
                                                   edges, catalog, when) for weights in WEIGHTS_BY_ARM)
                    actual = profile.rank(when)
                    self.assertEqual(actual, expected)
                    self.assertEqual((actual[0], actual[3]), paired.rank(when))
                    self.assertEqual(profile.has_paired_action, when >= 3)
                    self.assertEqual(profile.has_paired_cart, when >= (3 if first == "addtocart" else 5))
                    self.assertEqual(profile.has_paired_purchase, when >= (3 if first == "transaction" else 5))
                    if when >= 5:
                        self.assertEqual(len(set(actual)), 4)


if __name__ == "__main__":
    unittest.main()
