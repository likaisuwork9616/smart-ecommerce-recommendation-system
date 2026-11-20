import sqlite3
import unittest

from scripts.evaluate_purchase_baskets import WINDOWS, build_baskets, build_lists, evaluate, purchase_rows


class PurchaseBasketTests(unittest.TestCase):
    def test_multiple_transactions_by_one_visitor_count_as_one_vote(self):
        rows = [("a", "x", "10", 1), ("a", "x", "2", 2), ("a", "x", "2", 3),
                ("a", "y", "10", 4), ("a", "y", "2", 4), ("a", "y", "3", 4),
                ("a", "z", "3", 5), ("a", "z", "2", 5),
                ("b", "w", "10", 6), ("b", "w", "2", 6)]
        train, counts = build_baskets(rows)
        ranked, popular, support = build_lists(train)
        self.assertEqual(counts["canonical_transaction_rows"], 10)
        self.assertEqual(counts["item_occurrences_in_transaction_groups"], 9)
        self.assertEqual(counts["groups_spanning_multiple_timestamps"], 1)
        self.assertEqual(ranked, {"2": ("10",), "10": ("2",)})
        self.assertEqual(popular, ["2", "10", "3"])
        self.assertEqual(support["qualified_pairs"], 1)

    def test_scores_other_items_in_same_basket_and_keeps_unknown_targets(self):
        august = [("a", "x", ("1", "2", "10")), ("b", "y", ("50",)),
                  ("b", "z", ("51", "52"))]
        observed = []

        def capture(seed, targets, cobuy, popular):
            observed.append((seed, targets, cobuy, popular))

        result = evaluate(august, {"1": ("2", "10"), "2": ("10",)}, ["1", "2", "10", "3"], capture)
        self.assertEqual(result["all_item_occurrences"]["queries"], 6)
        scored = result["scorable"]
        self.assertEqual(scored["queries"], 5)
        self.assertEqual(scored["all_targets_absent_from_training"], 2)
        self.assertEqual(scored["cobuy"]["with_recommendations"], 2)
        self.assertEqual(scored["cobuy"]["hit_queries"], 2)
        self.assertEqual(scored["popular"]["hit_queries"], 3)
        self.assertEqual(scored["paired_hits"], {"both": 2, "cobuy_only": 0, "popular_only": 1, "neither": 2})
        self.assertEqual([row[0] for row in observed], ["1", "2", "10", "51", "52"])
        self.assertEqual(observed[0], ("1", {"2", "10"}, ("2", "10"), ["2", "10", "3"]))

    def test_reader_matches_dedup_and_excludes_other_roles_and_windows(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE raw(v TEXT,x TEXT,i TEXT,t INTEGER,rt TEXT,e TEXT,role TEXT,bad TEXT)")
        db.execute("CREATE TABLE qualified AS SELECT * FROM raw")
        lo, hi = WINDOWS["validation"]
        accepted = ("v", "x", "1", lo, str(lo), "transaction", "validation", "")
        rejected = [("v", "x", "2", lo, str(lo), "addtocart", "validation", ""),
                    ("v", "x", "3", hi, str(hi), "transaction", "validation", ""),
                    ("v", "y", "4", lo, str(lo), "transaction", "test", "")]
        db.executemany("INSERT INTO raw VALUES (?,?,?,?,?,?,?,?)", [accepted, accepted, *rejected])
        db.executemany("INSERT INTO qualified VALUES (?,?,?,?,?,?,?,?)", [accepted, *rejected])
        self.assertEqual(purchase_rows(db, "validation"), [accepted[:4]])
        with self.assertRaises(KeyError):
            purchase_rows(db, "test")


if __name__ == "__main__":
    unittest.main()
