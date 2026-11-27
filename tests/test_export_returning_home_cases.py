import unittest
from unittest.mock import Mock

from scripts.export_returning_home_cases import public_case


class ReturningHomeReplayTests(unittest.TestCase):
    def setUp(self):
        self.popular = [str(100 + rank) for rank in range(1, 11)]
        self.aliases = {item: f"{rank:02d}" for rank, item in enumerate(self.popular, 1)}
        self.aliases["700"] = "14"  # An existing product-card alias outside the popular ten.
        self.model = Mock()
        self.model.recommend.return_value = {"recommendations": [
            {"source": "cooccurrence", "item_id": item} for item in ("700", "600", "101")
        ]}

    def export(self, targets, ranks):
        return public_case("109", targets, self.popular, self.model, self.aliases, ranks, 1)

    def test_both_examples_share_aliases_and_keep_all_first_view_targets(self):
        gained = self.export({"600", "700"}, (None, 1))
        self.assertEqual(gained["actual"], ["15", "14"])
        self.assertEqual(gained["previous"], "09")
        self.assertEqual(gained["baseline"], [f"{rank:02d}" for rank in range(1, 11)])
        self.assertEqual(gained["candidate"], ["14", "15", "01", "02", "03", "04", "05", "06", "07", "09"])
        lost = self.export({"108"}, (8, None))
        self.assertEqual(lost["actual"], ["08"])
        self.assertEqual(lost["candidate"], gained["candidate"])

    def test_rejects_a_displayed_hit_rank_that_differs_from_the_visitor_audit(self):
        with self.assertRaisesRegex(ValueError, "first-hit ranks"):
            self.export({"600", "700"}, (None, 2))


if __name__ == "__main__":
    unittest.main()
