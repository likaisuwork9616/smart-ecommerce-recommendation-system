import sqlite3
import unittest
from collections import defaultdict
from contextlib import closing
from fractions import Fraction

from scripts.evaluate_august_personalization import PairedResults
from scripts.evaluate_cart_recommendations import WINDOWS
from scripts.personalization_history import WARMUP_START, visitor_events, visitor_history_rows
from scripts.personalization_ranker import PersonalizationRanker
from scripts.retailrocket_popularity import Catalog
from scripts.score_recommendation_acceptance import SESSION_GAP_MS


def exact_ranking(events, weights, support, popularity, edges, catalog, when):
    scores = defaultdict(Fraction)
    for item, kind in set(events):
        for left, right, count in edges:
            if item == left or item == right:
                other = right if item == left else left
                scores[other] += Fraction(weights[kind] * count, support[item])
    eligible = [item for item, first_view in catalog.first.items() if first_view < when]
    return tuple(sorted(eligible, key=lambda i: (-scores[i], -popularity.get(i, 0), int(i)))[:10])


def graph(edges):
    result = defaultdict(list)
    for left, right, count in edges:
        result[left].append((right, count))
        result[right].append((left, count))
    return result


class PersonalizationPairTest(unittest.TestCase):
    def test_incremental_top_ten_matches_full_resort_and_independent_weighted_sums(self):
        items = [str(i) for i in range(1, 24)]
        support = {item: 20 + int(item) % 5 for item in items}
        popularity = {item: 50 + int(item) % 4 for item in items}
        edges = [(left, right, 1 + (i + j) % 8) for i, left in enumerate(items)
                 for j, right in enumerate(items[:i]) if i < 20 and (i + j) % 3 != 0]
        catalog = Catalog([(i, 3 if int(i) % 4 == 0 else 1) for i in items] + [("40", 4)])
        model = PersonalizationRanker(support, popularity, graph(edges), catalog)
        profile = model.new_profile()
        observed = []
        queries = [(1, []), (2, [("2", "view")]), (3, [("23", "transaction")]),
                   (4, [("2", "addtocart"), ("2", "transaction"), ("2", "addtocart")]),
                   (5, [("3", "view"), ("4", "addtocart"), ("3", "view")]),
                   (6, [("3", "transaction"), ("8", "view")]), (7, [])]
        for when, additions in queries:
            with self.subTest(when=when):
                for item, kind in additions:
                    profile.observe(item, kind)
                observed.extend(additions)
                expected = tuple(exact_ranking(observed, weights, support, popularity, edges, catalog, when)
                                 for weights in ({"view": 1, "addtocart": 0, "transaction": 0},
                                                 {"view": 1, "addtocart": 3, "transaction": 5}))
                self.assertEqual(profile.rank(when), expected)
                self.assertEqual(profile.has_paired_action, when >= 4)
        self.assertFalse(model.new_profile().has_paired_action)

    def test_rank_ten_resolves_sub_float_score_gap_before_popularity(self):
        denominator = 2 ** 28
        edges = [("100", str(i), 1) for i in range(1, 10)]
        edges.extend([("101", "10", denominator - 1), ("102", "11", denominator)])
        support = {str(i): denominator + 2 for i in range(1, 12)}
        support.update({"100": 1, "101": denominator, "102": denominator + 1})
        popularity = {i: denominator + 3 for i in support}
        popularity["10"] += 1
        catalog = Catalog((i, 1) for i in support)
        profile = PersonalizationRanker(support, popularity, graph(edges), catalog).new_profile()
        for item in ("100", "101", "102"):
            profile.observe(item, "view")
        self.assertEqual(float(Fraction(denominator - 1, denominator)), float(Fraction(denominator, denominator + 1)))
        expected = tuple(str(i) for i in range(1, 10)) + ("11",)
        self.assertEqual(profile.rank(2), (expected, expected))

    def test_across_sessions_withhold_tied_actions_and_count_each_item_once_per_type(self):
        later = 20 + SESSION_GAP_MS + 1
        records = [
            {"key": ["1", 10, 10], "history": ["2"]},
            {"key": ["1", 10, 20], "history": ["2", "3"]},
            {"key": ["1", later, later], "history": ["3"]},
        ]
        events = [(5, "transaction", "2"), (10, "addtocart", "2"), (10, "view", "2"),
                  (11, "addtocart", "2"), (20, "transaction", "3"), (20, "view", "3"),
                  (20, "view", "2"), (later, "view", "3"), (later, "addtocart", "4")]
        additions = [values for _, values in visitor_history_rows(records, events)]
        self.assertEqual(additions, [
            {"view": ("2",), "addtocart": (), "transaction": ("2",)},
            {"view": ("3",), "addtocart": ("2",), "transaction": ()},
            {"view": (), "addtocart": (), "transaction": ("3",)},
        ])

    def test_query_history_reads_only_one_visitor_and_allowed_role_clocks(self):
        train, august = WINDOWS["train"]
        stop = WINDOWS["validation"][1]
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE qualified (v TEXT, t INTEGER, e TEXT, i TEXT, role TEXT)")
            rows = [("1", WARMUP_START, "view", "1", "warmup"), ("1", train, "view", "2", "train"),
                    ("1", august, "addtocart", "3", "validation"), ("1", august, "view", "4", "train"),
                    ("1", train, "view", "5", "warmup"), ("2", august, "view", "6", "validation"),
                    ("1", august, "transaction", "7", "reserved_test"),
                    ("1", august + 1, "view", "8", "validation")]
            db.executemany("INSERT INTO qualified VALUES (?, ?, ?, ?, ?)", rows)
            self.assertEqual(list(visitor_events(db, "1", august)), [
                (WARMUP_START, "view", "1"), (train, "view", "2"), (august, "addtocart", "3")])
            with self.assertRaises(ValueError):
                visitor_events(db, "1", stop)

    def test_rank_transitions_and_mrr_keep_both_misses_in_the_denominator(self):
        results = PairedResults()
        for visitor, old, new in [(1, None, 2), (1, 10, None), (2, 7, 1), (2, 1, 6),
                                  (2, 2, 2), (3, None, None)]:
            results.add(visitor, old, new, changed=old != new)
        report = results.report({"seed": 1, "replicates": 10, "percentiles": [2.5, 97.5],
                                 "quantile_method": "linear"})
        self.assertEqual(report["first_hit_changes"], {
            "gain": 1, "loss": 1, "earlier": 1, "same": 1, "later": 1, "both_miss": 1,
        })
        self.assertEqual((report["queries"], report["visitors"], report["net_extra_hits"]), (6, 3, 0))
        self.assertEqual(report["browse_only"]["hit_queries"], 4)
        self.assertEqual(report["weighted_actions"]["hit_queries"], 4)
        self.assertAlmostEqual(report["mrr_at_10_difference"], (1/2 - 1/10 + 1 - 1/7 + 1/6 - 1) / 6)


if __name__ == "__main__":
    unittest.main()
