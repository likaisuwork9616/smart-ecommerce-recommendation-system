"""Hand-check coverage, paired scores, visitor weighting and packet refusals."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from scripts.score_recommendation_acceptance import FREEZE, SCHEMA, evaluate_packet, visitor_interval


START = 1443657600000  # October 1, 2015 UTC, using synthetic records only.
TRAIN = 1430697600000


class ScoreAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "manifest.json"
        self.policy = json.loads(FREEZE.read_bytes())
        self.target_rows = [
            {"key": [1, START, 0], "query_ms": START, "through_ms": START + 1, "targets": [2, 9]},
            {"key": [1, START + 2, 0], "query_ms": START + 2, "through_ms": START + 3, "targets": [3]},
            {"key": [2, START, 0], "query_ms": START, "through_ms": START, "targets": None},
            {"key": [3, START, 0], "query_ms": START, "through_ms": START + 1, "targets": [99]},
        ]
        candidate = [[i, "popular"] for i in range(1, 11)]
        self.ranks = [
            {"key": row["key"][:], "candidate": [entry[:] for entry in candidate], "baseline": []}
            for row in self.target_rows
        ]
        self.ranks[1]["baseline"] = [[3, "coadd"]]
        self.ranks[2]["baseline"] = [[1, "coadd"]]
        self.catalog = [[i, TRAIN] for i in range(1, 11)]
        self.metadata = {
            "schema": SCHEMA, "role": "synthetic", "scenario": "cart",
            "window_utc_ms": [START, START + 7_200_000],
            "frozen_training_commit": self.policy["frozen_git_commit"],
            "coverage_queries": 4, "scorable_queries": 3,
        }

    def packet(self):
        for key, rows in (("roster", self.target_rows), ("rankings", self.ranks), ("catalog", self.catalog)):
            filename = f"{key}.jsonl"
            data = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
            (self.path.parent / filename).write_bytes(data)
            self.metadata[key] = {"file": filename, "sha256": sha256(data).hexdigest()}
        self.path.write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_coverage_misses_and_unknown_targets(self):
        self.packet()
        report = evaluate_packet(self.path, self.policy)
        a, b = report["arms"]["candidate"], report["arms"]["baseline"]
        self.assertEqual((a["with_ten"], b["with_any"], report["scorable_queries"]), (4, 2, 3))
        self.assertEqual((a["hit_queries"], b["hit_queries"], b["rank_one_hits"]), (2, 1, 1))
        self.assertAlmostEqual(a["mrr_at_10"], (1 / 2 + 1 / 3) / 3)
        self.assertEqual(report["paired_first_hit_changes"],
                         {"gain": 1, "loss": 0, "earlier": 0, "same": 0, "later": 1, "both_miss": 1})
        self.assertEqual(a["slots_by_source"], {"popular": 40})
        self.assertEqual(a["queries_by_source"], {"popular": 4})
        self.assertEqual(report["visitor_bootstrap"]["visitors"], 2)
        self.assertFalse(report["gates"]["hit_at_1"])
        self.assertIsNone(report["adoption_gates_met"])

    def test_gate_pass_stays_synthetic(self):
        self.ranks[1]["baseline"] = []
        self.target_rows[-1]["targets"] = [1]
        self.packet()
        report = evaluate_packet(self.path, self.policy)
        self.assertEqual(report["visitor_bootstrap"]["hit_rate_delta_95_percentile"], [1.0, 1.0])
        self.assertTrue(report["all_gates_pass"])
        self.assertIsNone(report["adoption_gates_met"])

    def test_empty_scorable_roster_leaves_gates_pending(self):
        self.metadata["scorable_queries"] = 0
        for row in self.target_rows:
            row["targets"] = None
        self.packet()
        report = evaluate_packet(self.path, self.policy)
        self.assertEqual(report["arms"]["candidate"]["with_ten"], 4)
        for metric in ("visitor_bootstrap", "gates", "all_gates_pass"):
            self.assertIsNone(report[metric])

    def test_bootstrap_uses_all_queries_for_each_sampled_visitor(self):
        settings = self.policy["adoption"]["hit_rate_ci"]
        clusters = {30: (1, -1), 10: (9, 3), 20: (2, 2)}
        draw = np.random.Generator(np.random.PCG64(settings["seed"])).integers(3, size=(2000, 3))
        totals = [clusters[key] for key in sorted(clusters)]
        scores = []
        for sampled in draw:
            weights = [list(sampled).count(i) for i in range(3)]
            n = sum(w * count for w, (count, _) in zip(weights, totals, strict=True))
            delta = sum(w * value for w, (_, value) in zip(weights, totals, strict=True))
            scores.append(delta / n)
        expected = np.percentile(scores, [2.5, 97.5], method="linear").tolist()
        self.assertEqual(visitor_interval(clusters, settings)["hit_rate_delta_95_percentile"], expected)

    def test_reserved_window_refused_before_payload_access(self):
        self.metadata["window_utc_ms"] = [1441065600000, START + 1]
        self.path.write_text(json.dumps(self.metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "locked September"):
            evaluate_packet(self.path, self.policy)

    def test_retained_scope_requires_matching_reference_before_payload_access(self):
        self.metadata.update(role="retained", approval_ref="synthetic-ref-for-refusal-test", source_version="example")
        self.path.write_text(json.dumps(self.metadata), encoding="utf-8")
        for ref in (None, "another-ref"):
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, "recorded approval reference"):
                evaluate_packet(self.path, self.policy, approval_ref=ref)

    def test_reordered_or_truncated_rankings_are_refused(self):
        self.ranks[0], self.ranks[1] = self.ranks[1], self.ranks[0]
        self.packet()
        with self.assertRaisesRegex(ValueError, "query keys differ"):
            evaluate_packet(self.path, self.policy)
        self.ranks[0], self.ranks[1] = self.ranks[1], self.ranks[0]
        self.ranks.pop()
        self.packet()
        with self.assertRaisesRegex(ValueError, "lengths differ"):
            evaluate_packet(self.path, self.policy)

    def test_duplicate_query_key_is_refused(self):
        self.target_rows[1] = dict(self.target_rows[0])
        self.ranks[1] = dict(self.ranks[0])
        self.packet()
        with self.assertRaisesRegex(ValueError, "Duplicate query key"):
            evaluate_packet(self.path, self.policy)

    def test_catalog_and_seed_eligibility_are_enforced(self):
        for invalid, message in ((98, "ineligible"), (0, "seed"), (2, "duplicate")):
            with self.subTest(item=invalid):
                self.catalog.append([0, TRAIN])
                self.ranks[0]["candidate"][0][0] = invalid
                self.packet()
                with self.assertRaisesRegex(ValueError, message):
                    evaluate_packet(self.path, self.policy)
                self.catalog.pop()

    def test_browse_as_of_catalog_and_mature_target(self):
        self.metadata.update(scenario="browse", coverage_queries=1, scorable_queries=1)
        self.target_rows = [{"key": [1, START, START], "query_ms": START, "through_ms": START + 1, "targets": [1]}]
        self.ranks = [{"key": [1, START, START], "candidate": [[1, "knn"]], "baseline": [[2, "recency"]]}]
        self.packet()
        report = evaluate_packet(self.path, self.policy)
        self.assertEqual(report["arms"]["candidate"]["hit_queries"], 1)
        self.assertFalse(report["gates"]["full_ten"])
        self.catalog[0][1] = START
        self.packet()
        with self.assertRaisesRegex(ValueError, "ineligible at query time"):
            evaluate_packet(self.path, self.policy)
        self.catalog[0][1] = START - 1
        self.metadata["window_utc_ms"][1] = START + 1_800_000 - 1
        self.packet()
        with self.assertRaisesRegex(ValueError, "no mature next-view target"):
            evaluate_packet(self.path, self.policy)

    def test_purchase_targets_can_share_the_transaction_timestamp(self):
        self.metadata.update(scenario="purchase", coverage_queries=1, scorable_queries=1)
        self.target_rows = [{"key": [1, 42, 0], "query_ms": START, "through_ms": START, "targets": [1]}]
        self.ranks = [{"key": [1, 42, 0], "candidate": [[1, "cobuy"]], "baseline": [[1, "cobuy"]]}]
        self.packet()
        report = evaluate_packet(self.path, self.policy)
        self.assertEqual(report["paired_first_hit_changes"]["same"], 1)
        self.assertFalse(report["gates"]["hit_at_10_ci"])

    def test_cross_window_targets_and_rank_specific_targets_are_refused(self):
        self.target_rows[0]["through_ms"] = self.metadata["window_utc_ms"][1]
        self.packet()
        with self.assertRaisesRegex(ValueError, "outside its window"):
            evaluate_packet(self.path, self.policy)
        self.target_rows[0]["through_ms"] = START + 1
        self.ranks[0]["targets"] = [3]
        self.packet()
        with self.assertRaisesRegex(ValueError, "shared roster"):
            evaluate_packet(self.path, self.policy)

    def test_modified_payload_is_refused(self):
        self.packet()
        with (self.path.parent / "rankings.jsonl").open("r+b") as stream:
            sample = stream.read()
            altered = sample.replace(b'"popular"', b'"coadd"', 1)
            stream.seek(0)
            stream.write(altered)
            stream.truncate()
        with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
            evaluate_packet(self.path, self.policy)


if __name__ == "__main__":
    unittest.main()
