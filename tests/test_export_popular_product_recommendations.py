import unittest

from scripts.export_popular_product_recommendations import product_cards


class FakeRankings:
    def __init__(self, items):
        self.items = items

    def recommend(self, *args):
        mode = args[0] if len(args) == 2 else "browse"
        source = {"browse": "popularity", "cart": "coadd", "purchase": "cobuy"}[mode]
        return {"recommendations": [{"item_id": item, "source": source} for item in self.items]}


class ProductCardExportTests(unittest.TestCase):
    def setUp(self):
        self.home = {"rankings": {"browse": [{"item": "12"}, {"item": "11"}],
                                  "cart": [{"item": "11"}], "purchase": [{"item": "12"}]}}
        self.aliases = {"first": "11", "second": "12", "previous": "32", "case": "A"}
        self.originals = ["previous", "case"] + [f"private-{i}" for i in range(8)]

    def test_reuses_global_aliases_and_keeps_each_mode_source(self):
        model = FakeRankings(self.originals)
        cards = product_cards(self.home, self.aliases, model, model)
        self.assertEqual(list(cards), ["11", "12"])
        expected = ["32", "A", *map(str, range(33, 41))]
        for seed, card in cards.items():
            self.assertEqual(card["item"], seed)
            for mode, source in (("browse", "popular"), ("cart", "coadd"), ("purchase", "cobuy")):
                self.assertEqual(card["rankings"][mode], [[alias, source] for alias in expected])
        self.assertNotIn("private-0", self.aliases)

    def test_rejects_self_repeat_or_short_rankings(self):
        for items in (self.originals[:9], self.originals[:9] + ["first"],
                      self.originals[:9] + ["case"]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                model = FakeRankings(items)
                product_cards(self.home, self.aliases, model, model)


if __name__ == "__main__":
    unittest.main()
