import json
import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.cart_replay_examples import EXAMPLES, RECEIPT, REPORT, FirstCoveredExamples, load_cart_replay, restore
from scripts.evaluate_cart_recommendations import build_model, evaluate


class CartReplayExamplesTests(unittest.TestCase):
    def test_evaluator_exposes_the_rankings_and_targets_it_actually_scored(self):
        train = [(visitor, 0, "addtocart", item) for visitor in ("a", "b") for item in ("1", "2")]
        start = 1438387200000
        rows = [("x", start, "addtocart", "1"), ("x", start + 1, "addtocart", "2"),
                ("y", start, "addtocart", "1"), ("y", start + 1, "addtocart", "8")]
        selector = FirstCoveredExamples()
        result = evaluate(rows, build_model(train), selector.observe)
        payload = selector.payload(result["scorable"])
        self.assertEqual(payload["total_queries"], 2)
        self.assertEqual([(c["seed"], c["targets"], c["coadd"]["items"], c["coadd"]["hit_ranks"])
                          for c in payload["cases"]], [("1", ["2"], ["2"], [1]), ("1", ["8"], ["2"], [])])

    def test_selects_first_in_each_covered_outcome_regardless_of_popularity(self):
        examples = FirstCoveredExamples()
        when = 1438387200000
        examples.observe(when, "99", [], ["2"], ["2"])
        examples.observe(when, "99", ["2"], [], ["2"])
        examples.observe(when, "99", ["2"], ["2"], [])
        examples.observe(when, "1", ["3"], ["2"], ["3"])
        examples.observe(when + 1, "4", ["2", "5"], ["8", "5", "2"], ["8", "5"])
        examples.observe(when + 2, "7", ["3"], ["2"], ["1"])
        examples.observe(when + 3, "8", ["6"], ["6"], ["1"])
        subset = {"queries": 4, "coadd_hit_queries": 2, "popular_hit_queries": 2}
        data = examples.payload({"on_coadd_covered_queries": subset})
        hit, miss = data["cases"]
        self.assertEqual(data["total_queries"], 4)
        self.assertEqual((hit["id"], hit["seed"], hit["count"], hit["cohort_position"]), ("hit", "4", 2, 2))
        self.assertEqual(hit["query_time"], "2015-08-01T00:00:00.001Z")
        self.assertEqual(hit["targets"], ["2", "5"])
        self.assertEqual(hit["coadd"], {"items": ["8", "5", "2"], "hit_ranks": [2, 3]})
        self.assertEqual((miss["id"], miss["seed"], miss["count"], miss["cohort_position"]), ("miss", "1", 2, 1))
        self.assertEqual(miss["coadd"], {"items": ["2"], "hit_ranks": []})
        self.assertEqual(miss["popular"], {"items": ["3"], "hit_ranks": [1]})
        with self.assertRaises(ValueError):
            examples.payload({"on_coadd_covered_queries": {**subset, "queries": 5}})


class CartReplaySourceTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cases = self.root / EXAMPLES
        self.report = self.root / REPORT
        self.data = b'{"cases": []}'
        certified = b'{"scorable": {}}'
        self.receipt = {"local_examples_sha256": sha256(self.data).hexdigest(),
                        "validation_report_sha256": sha256(certified).hexdigest()}
        self.cases.parent.mkdir(parents=True)
        self.report.parent.mkdir(parents=True)
        self.report.write_bytes(certified)
        (self.root / RECEIPT).write_text(json.dumps(self.receipt), encoding="utf-8")

    def test_load_rejects_missing_cases_modified_cases_and_different_report(self):
        with self.assertRaises(FileNotFoundError):
            load_cart_replay(self.root)
        self.cases.write_bytes(self.data)
        self.assertEqual(load_cart_replay(self.root), {"cases": []})
        self.cases.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            load_cart_replay(self.root)
        self.cases.write_bytes(self.data)
        self.report.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            load_cart_replay(self.root)

    def test_restore_writes_checked_bytes_and_preserves_existing_file_on_mismatch(self):
        with patch("scripts.cart_replay_examples.build_cart_replay", return_value=(self.data, self.receipt)):
            self.assertEqual(restore(self.root), self.cases)
        with patch("scripts.cart_replay_examples.build_cart_replay", return_value=(b"other data", {})):
            with self.assertRaises(ValueError):
                restore(self.root)
        self.assertEqual(self.cases.read_bytes(), self.data)
