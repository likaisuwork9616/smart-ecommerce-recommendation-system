from collections import Counter, defaultdict
from datetime import date, datetime
import unittest

from scripts.evaluate_august_home_first_view_pair import paired_scores, summarize_rank_pairs
from scripts.evaluate_august_home_weekly import summarize_weeks, utc_day


def timestamp(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


class AugustWeeklyTest(unittest.TestCase):
    def test_first_view_week_handles_sunday_monday_ties_and_partial_weeks(self):
        first_day = timestamp("2015-08-01T00:00:00Z")
        sunday = timestamp("2015-08-02T23:59:59.999Z")
        monday = timestamp("2015-08-03T00:00:00Z")
        last_day = timestamp("2015-08-31T23:59:59.999Z")
        baseline = [(str(i), "") for i in range(1, 11)]
        candidate = [(str(i), 0) for i in range(6, 16)]
        # A's tied first targets hit ranks 6 and 7. B's first activity was Sunday,
        # but its first view was Monday and hits both lists (including rank 6).
        visitors = [
            ("A", "first_observed_in_august", sunday, sunday, "11"),
            ("A", "first_observed_in_august", sunday, sunday, "12"),
            ("B", "first_observed_in_august", sunday, monday, "1"),
            ("B", "first_observed_in_august", sunday, monday, "11"),
            ("C", "first_observed_in_august", first_day, first_day, "1"),
            ("D", "first_observed_in_august", last_day, last_day, "100"),
        ]
        days = defaultdict(Counter)

        def observe(view_at, before, after):
            days[utc_day(view_at)][before, after] += 1

        month = paired_scores(visitors, baseline, candidate, observe)
        weeks = summarize_weeks(days, date(2015, 8, 1), date(2015, 9, 1), month)
        self.assertEqual([w["days"] for w in weeks], [2, 7, 7, 7, 7, 1])
        self.assertEqual([w["scored_visitors"] for w in weeks], [2, 1, 0, 0, 0, 1])
        self.assertEqual(weeks[0]["candidate_only_gained"], 1)
        self.assertEqual(weeks[0]["baseline_only_lost"], 1)
        self.assertEqual(weeks[0]["rank_6_candidate_only"], 1)
        self.assertEqual(weeks[0]["share_of_month_rank_6_gains"], 1)
        self.assertEqual(weeks[0]["rank_6_gains_per_1000_visitors"], 500)
        self.assertEqual(weeks[0]["net_minus_rank_6_gains"], -1)
        self.assertEqual(weeks[1]["both_hit"], 1)
        self.assertEqual(weeks[1]["rank_6_candidate_only"], 0)
        self.assertIsNone(weeks[2]["rank_6_gains_per_1000_visitors"])
        self.assertEqual(weeks[-1]["both_missed"], 1)

    def test_reconciles_rank_attribution_and_rejects_out_of_window_dates(self):
        start, end = date(2015, 8, 1), date(2015, 9, 1)
        expected = summarize_rank_pairs(Counter({(None, 6): 1}))
        with self.assertRaisesRegex(ValueError, "rank attributions"):
            summarize_weeks({start: Counter({(None, 7): 1})}, start, end, expected)
        with self.assertRaisesRegex(ValueError, "outside"):
            summarize_weeks({end: Counter({(None, 6): 1})}, start, end, expected)
        empty = summarize_weeks({}, start, end, summarize_rank_pairs(Counter()))
        self.assertTrue(all(w["share_of_month_rank_6_gains"] is None for w in empty))


if __name__ == "__main__":
    unittest.main()
