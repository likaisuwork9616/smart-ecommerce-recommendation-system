import unittest

from scripts.cart_popular_fill_replay import FirstFillGains


class CartFillReplayTests(unittest.TestCase):
    def test_picks_first_gains_and_marks_only_filled_slots_as_popular(self):
        examples = FirstFillGains()
        popular = [str(item) for item in range(1, 11)]
        when = 1438387200000
        for targets, coadd in [(["999"], []), (["3"], ["3"]), (["5"], []),
                               (["3"], ["11", "2"]), (["1"], [])]:
            examples.observe(when, "99", targets, coadd, popular)
        scored = {
            "queries": 5,
            "by_original_coadd_list_size": {
                "empty": {"hit_queries": {"popular_fill": 2, "coadd": 0}},
                "short": {"hit_queries": {"popular_fill": 2, "coadd": 1}},
            },
            "popular_fill_vs": {"coadd": {"gain": 3}},
        }
        report = examples.payload(scored)
        empty, short = report["cases"]
        self.assertEqual((report["scorable_queries"], report["total_queries"]), (5, 3))
        self.assertEqual((empty["id"], empty["cohort_position"], empty["count"]), ("empty", 3, 2))
        self.assertEqual(empty["coadd"]["items"], [])
        self.assertEqual(empty["popular_fill"]["sources"], ["popular"] * 10)
        self.assertEqual(empty["popular_fill"]["hit_ranks"], [5])
        self.assertEqual((short["id"], short["cohort_position"], short["count"]), ("short", 4, 1))
        self.assertEqual(short["targets"], ["3"])
        self.assertEqual(short["coadd"]["sources"], ["coadd", "coadd"])
        self.assertEqual(short["popular_fill"]["items"][:4], ["11", "2", "1", "3"])
        self.assertEqual(short["popular_fill"]["sources"], ["coadd"] * 2 + ["popular"] * 8)
        self.assertEqual(short["popular_fill"]["hit_ranks"], [4])
        with self.assertRaises(ValueError):
            examples.payload({**scored, "queries": 6})


if __name__ == "__main__":
    unittest.main()
