"""Exercise the returning-home adoption thresholds and the independent-roster input."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import score_returning_home_acceptance as scorer
from scripts.returning_home_acceptance_boundary_cases import SyntheticNeighbors, synthetic_results


START = 1443744000000  # 2015-10-02 UTC, synthetic data only
RESERVED_START = 1441065600000  # 2015-09-01 UTC
RESERVED_END = 1442534400000  # 2015-09-18 UTC, exclusive


def roster_row(visitor="a"):
    return {"visitor": visitor, "prior_event": {"type": "view", "time_ms": START - 1, "item": "80"},
            "last_view": {"time_ms": START - 1, "items": ["80"]}, "first_view_ms": START, "targets": ["14", "11"]}


def manifest_for(rows, digest):
    return {"schema": "returning_home_acceptance_v1", "role": "independent", "source_version": "synthetic-v1",
            "history_evidence": "generated returning events", "item_key_version": "retailrocket_original_itemid_v1",
            "approval_ref": "synthetic-ref", "window_utc_ms": [START, START + 1000], "active_returning": rows + 1,
            "returning_without_view": 1, "scored_visitors": rows, "roster": {"file": "visitors.jsonl", "sha256": digest}}


class ReturningHomeAcceptanceTests(unittest.TestCase):
    def test_boundaries_on_complete_paired_rosters(self):
        scored = synthetic_results()
        # Independent expected rank arithmetic: common hits are at rank 10, candidate-only
        # hits at the indicated rank. The fixed PCG64 draws give the interval in net people.
        examples = [
            ("hit_exact", 500, 100, 10, 1, (4, 16), (True, True, True)),
            ("hit_just_below", 501, 100, 10, 1, (4, 16), (False, True, True)),
            ("mrr_exact", 500, 100, 20, 4, (12, 29), (True, True, True)),
            ("mrr_just_below", 501, 100, 20, 4, (12, 29), (True, True, False)),
            ("lower_bound_zero", 40, 10, 1, 1, (0, 3), (True, False, True)),
        ]
        for name, total, common, gains, rank, interval_counts, expected in examples:
            with self.subTest(name=name):
                result = scored[name]
                self.assertEqual(result["scored_visitors"], total)
                self.assertEqual((result["baseline_hits"], result["candidate_hits"], result["net_hits"]),
                                 (common, common + gains, gains))
                self.assertAlmostEqual(result["hit_rate_change_percentage_points"], 100 * gains / total)
                self.assertAlmostEqual(result["baseline_mrr_at_10"], common / (10 * total))
                self.assertAlmostEqual(result["candidate_mrr_at_10"], (common / 10 + gains / rank) / total)
                self.assertAlmostEqual(result["mrr_at_10_delta"], gains / (rank * total))
                for bound, count in zip(result["hit_rate_delta_95_percentage_points"], interval_counts, strict=True):
                    self.assertAlmostEqual(bound, 100 * count / total)
                self.assertEqual(result["gates"], dict(zip(
                    ("hit_at_10_delta", "positive_lower_bound", "mrr_at_10_delta"), expected, strict=True)))
                self.assertEqual(result["all_gates_pass"], all(expected))

    def test_scope_needs_the_correct_catalog_window_authorization_and_counts(self):
        manifest = manifest_for(3, "1" * 64)
        self.assertEqual(tuple(scorer.packet_scope(manifest, "synthetic-ref")), (START, START + 1000))
        after_holdout = {**manifest, "window_utc_ms": [RESERVED_END, RESERVED_END + 1]}
        self.assertEqual(scorer.packet_scope(after_holdout, "synthetic-ref"), (RESERVED_END, RESERVED_END + 1))
        with self.assertRaises(ValueError):
            scorer.packet_scope(manifest, "other-ref")
        for invalid in ({"role": "development"}, {"item_key_version": "unrelated-product-ids"},
                        {"window_utc_ms": [RESERVED_END - 1, START]}, {"active_returning": 3}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                scorer.packet_scope({**manifest, **invalid}, "synthetic-ref")

    def test_history_evidence_tied_seed_and_missing_data(self):
        base = roster_row()
        prior = base["prior_event"]
        cart = {**prior, "type": "addtocart"}

        def visitors(row):
            return list(scorer.packet_visitors([row], START, START + 1000))

        self.assertEqual(visitors({**base, "last_view": {"time_ms": START - 1, "items": ["80", "9"]}})[0][2], "9")
        self.assertIsNone(visitors({**base, "prior_event": cart, "last_view": None})[0][2])
        self.assertIsNone(visitors({**base, "prior_event": {**cart, "time_ms": RESERVED_END}, "last_view": None})[0][2])
        invalid_rows = [
            {key: value for key, value in base.items() if key != "last_view"},
            {**base, "prior_event": cart, "last_view": {"time_ms": START, "items": ["80"]}},
            {**base, "last_view": None},
            {**base, "last_view": {"time_ms": START - 2, "items": ["80"]}},
            {**base, "last_view": {"time_ms": START - 1, "items": ["11"]}},
            {**base, "prior_event": {**cart, "time_ms": RESERVED_START}},
            {**base, "prior_event": cart, "last_view": {"time_ms": RESERVED_END - 1, "items": ["80"]}},
            {**base, "first_view_ms": START + 1000},
            {**base, "candidate_rank": 1},
        ]
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                visitors(row)

    def test_cli_scores_every_fallback_and_rejects_a_different_or_duplicate_roster(self):
        popular = [str(item) for item in range(1, 11)]
        rows = [
            roster_row(),
            {**roster_row("b"), "targets": ["80", "999"]},
            {**roster_row("c"), "prior_event": {"type": "transaction", "time_ms": START - 1, "item": "7"},
             "last_view": None, "targets": ["10"]},
            {**roster_row("d"), "last_view": {"time_ms": START - 1, "items": ["81"]},
             "prior_event": {"type": "view", "time_ms": START - 1, "item": "81"}, "targets": ["81"]},
        ]
        with TemporaryDirectory() as directory, patch.object(scorer, "frozen_inputs", return_value=(popular, SyntheticNeighbors())):
            roster = Path(directory) / "visitors.jsonl"
            manifest = Path(directory) / "manifest.json"

            def publish(records):
                roster.write_bytes("".join(json.dumps(r) + "\n" for r in records).encode())
                manifest.write_bytes(json.dumps(manifest_for(len(records), sha256(roster.read_bytes()).hexdigest())).encode())

            def run_cli(audit):
                args = ["score_returning_home_acceptance", "--manifest", str(manifest), "--approval-ref", "synthetic-ref",
                        "--rank-audit", str(audit)]
                output = StringIO()
                with patch.object(sys, "argv", args), redirect_stdout(output), redirect_stderr(StringIO()):
                    scorer.main()
                return json.loads(output.getvalue())

            publish(list(reversed(rows)))
            audit_path = Path(directory) / "output.jsonl"
            result = run_cli(audit_path)
            self.assertEqual(result["overall"]["scored_visitors"], 4)
            self.assertEqual(result["overall"]["candidate_only_gained"], 1)
            self.assertEqual(result["overall"]["both_hit"], 3)
            self.assertEqual(result["overall"]["candidate"]["first_hit_counts_rank_1_to_10"], [1] + [0] * 8 + [3])
            self.assertEqual(result["reserved_test_ranked_queries"], 0)
            self.assertEqual(result["manifest_sha256"], sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(result["roster_file_sha256"], sha256(roster.read_bytes()).hexdigest())
            self.assertEqual([json.loads(line) for line in audit_path.read_text().splitlines()], [
                ["a", START, None, 1], ["b", START, 10, 10], ["c", START, 10, 10], ["d", START, 10, 10],
            ])
            # The edited roster remains valid JSONL and still has distinct visitor keys, but its hash changed.
            roster.write_bytes(roster.read_bytes().replace(b'"d"', b'"x"', 1))
            bad_output = Path(directory) / "failed.jsonl"
            with self.assertRaises(SystemExit) as refused:
                run_cli(bad_output)
            self.assertEqual(refused.exception.code, 2)
            self.assertFalse(bad_output.exists())
            publish(rows + [rows[0]])
            with self.assertRaises(SystemExit) as duplicate:
                run_cli(bad_output)
            self.assertEqual(duplicate.exception.code, 2)
            self.assertFalse(bad_output.exists())

            # The public receipt should agree with the exact MRR decision even when
            # subtracting the two floating-point means would display less than 0.010.
            items = ["14"] * 4 + ["80"] * 20 + ["999"] * 76
            publish([{**roster_row(f"v{i:03d}"), "targets": [item]} for i, item in enumerate(items)])
            boundary = run_cli(Path(directory) / "mrr-boundary.jsonl")
            self.assertEqual(boundary["overall"]["mrr_at_10_delta"], 0.010)
            self.assertEqual(boundary["decision"], "adopt_candidate")

    def test_receipt_drift_is_rejected_before_any_model_is_loaded(self):
        with patch.dict(scorer.MODEL_SHA256, {scorer.EDGES: "0" * 64}):
            with patch.object(scorer.C1DemoModel, "load") as load_model, self.assertRaises(ValueError):
                scorer.frozen_inputs()
            load_model.assert_not_called()

    def test_no_scorable_visitors_leaves_the_decision_pending(self):
        result = scorer.score_returning([], [str(item) for item in range(1, 11)], SyntheticNeighbors(),
                                        expected_visitors=0)
        self.assertIsNone(result["visitor_bootstrap"])
        self.assertIsNone(result["gates"])
        self.assertIsNone(result["all_gates_pass"])


if __name__ == "__main__":
    unittest.main()
