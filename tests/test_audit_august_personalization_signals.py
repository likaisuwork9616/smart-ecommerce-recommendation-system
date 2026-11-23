import sqlite3
import unittest
from contextlib import closing

from scripts.audit_august_personalization_signals import history_times, summarize


def browse(visitor, when, target, *, rank_ten="i10", recent=None, reachable=1):
    items = [f"i{rank}" for rank in range(1, 10)] + [rank_ten]
    return (visitor, when, when), {target}, [(item, "knn") for item in items], [], [], recent, reachable


class AugustPersonalizationSignalTests(unittest.TestCase):
    def test_history_keeps_only_scoped_events_and_earliest_paired_item(self):
        windows = {"warmup": (0, 10), "train": (10, 20), "validation": (20, 30)}
        events = [
            ("1", "addtocart", 15, "paired", "train", ""),
            ("1", "addtocart", 7, "unpaired", "warmup", ""),
            ("1", "transaction", 23, "paired", "validation", ""),
            ("2", "addtocart", 30, "paired", "validation", ""),
            ("2", "transaction", 22, "paired", "reserved_test", ""),
            ("3", "transaction", 35, "paired", "reserved_test", ""),
            ("4", "view", 21, "paired", "validation", ""),
        ]
        raw = [*events, events[0], ("1", "transaction", 8, "paired", "warmup", "invalid")]
        with closing(sqlite3.connect(":memory:")) as database:
            for table, rows in (("qualified", events), ("raw", raw)):
                database.execute(f"CREATE TABLE {table}(v TEXT,e TEXT,t INT,i TEXT,role TEXT,bad TEXT)")
                database.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?)", rows)
            observed, paired = history_times(database, windows, {"paired"})
        self.assertEqual(observed, {(1, "addtocart"): 7, (1, "transaction"): 23})
        self.assertEqual(paired, {(1, "addtocart"): 15, (1, "transaction"): 23})

    def test_query_requires_strictly_earlier_events_and_deduplicates_visitors(self):
        observed = {(1, "addtocart"): 7, (1, "transaction"): 23, (2, "addtocart"): 25}
        paired = {(1, "addtocart"): 15, (1, "transaction"): 23, (2, "addtocart"): 25}
        result = summarize([
            browse(1, 7, "i10", recent="replaced"),
            browse(1, 15, "other"),
            browse(1, 23, "hit", recent="hit"),
            browse(1, 24, "other", reachable=0),
            browse(2, 25, "i1"),
            browse(2, 26, "other"),
        ], observed, paired)
        browse_only, cart, purchase = result["by_prior_history"].values()
        self.assertEqual((browse_only["queries"], cart["queries"], purchase["queries"]), (2, 3, 1))
        self.assertEqual((cart["queries_with_c1_pair"], cart["k1_recency_misses_with_c1_pair"]), (2, 1))
        self.assertEqual(purchase["k1_recency_misses_with_c1_pair_and_eligible_target"], 0)
        totals = result["all_browse_queries"]
        self.assertEqual((totals["queries"], totals["visitors"], totals["k1_recency_misses"]), (6, 2, 4))
        self.assertEqual((totals["queries_with_c1_pair"], totals["original_k1_misses"]), (3, 4))
        signals = result["any_prior_cart_or_purchase"]
        self.assertEqual((signals["queries"], signals["visitors"], signals["visitors_with_c1_pair"]), (4, 2, 2))


if __name__ == "__main__":
    unittest.main()
