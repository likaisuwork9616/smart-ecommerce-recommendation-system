"""Check the homepage decision on synthetic visitors and fixed confidence boundaries."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import score_home_first_view_acceptance as scorer
from scripts.score_home_first_view_acceptance import adoption_gates, packet_scope, packet_visitors, score_home


OCTOBER_START = 1443657600000
BASELINE = [(str(item), 20 - item) for item in range(1, 11)]
CANDIDATE = [(str(item), 25 - item) for item in range(6, 16)]


def synthetic_manifest(scored_visitors, roster_hash):
    return {
        "schema": "home_first_view_acceptance_v1", "role": "independent", "source_version": "synthetic-v1",
        "history_evidence": "synthetic prior-event flags", "approval_ref": "synthetic-approval",
        "window_utc_ms": [OCTOBER_START, OCTOBER_START + 1000],
        "active_visitors": scored_visitors + 2, "previously_seen": 1,
        "new_without_view": 1, "scored_visitors": scored_visitors,
        "roster": {"file": "synthetic.jsonl", "sha256": roster_hash},
    }


class HomeFirstViewAcceptanceTest(unittest.TestCase):
    def test_effect_threshold_and_zero_confidence_bound_on_complete_rosters(self):
        # Gains are assigned to the first visitor keys. Others miss both lists.
        # The first two cohorts round to the same displayed percentage-point gain.
        examples = [
            (25_000, 5, True, True, (1, 10)),
            (25_001, 5, False, True, (1, 10)),
            (5_000, 1, True, False, (0, 3)),
        ]
        for total, gains, practical, positive, interval_counts in examples:
            with self.subTest(visitors=total):
                rows = (
                    (f"v{i:05d}", OCTOBER_START, ["11"] if i < gains else ["999"])
                    for i in range(total)
                )
                result = score_home(rows, BASELINE, CANDIDATE)
                pair = result["paired"]
                self.assertEqual(pair["scored_visitors"], total)
                self.assertEqual(pair["candidate_only_gained"], gains)
                self.assertEqual(pair["baseline_only_lost"], 0)
                self.assertEqual(pair["net_hits"], gains)
                self.assertEqual(result["gates"], {
                    "practical_gain": practical, "positive_lower_bound": positive,
                })
                self.assertEqual(result["all_gates_pass"], practical and positive)
                ci = result["visitor_bootstrap"]["hit_rate_delta_95_percentage_points"]
                for bound, hits in zip(ci, interval_counts, strict=True):
                    self.assertAlmostEqual(bound, 100 * hits / total)

    def test_four_groups_with_simultaneous_targets_and_multiple_matches(self):
        rows = [
            ("d", OCTOBER_START, ["999"]),
            ("a", OCTOBER_START, ["6", "1", "7"]),
            ("c", OCTOBER_START, ["5"]),
            ("b", OCTOBER_START, ["15", "11"]),
        ]
        audit = []
        result = score_home(rows, BASELINE, CANDIDATE, rank_audit=lambda *row: audit.append(row))
        pair = result["paired"]
        self.assertEqual(pair["scored_visitors"], 4)
        for field in ("both_hit", "candidate_only_gained", "baseline_only_lost", "both_missed"):
            self.assertEqual(pair[field], 1, field)
        self.assertEqual((pair["baseline"]["hits_at_10"], pair["candidate"]["hits_at_10"]), (2, 2))
        self.assertEqual(pair["net_hits"], 0)
        # The two candidate-only targets are ranks 6 and 10. Only rank 6 gets credit.
        self.assertEqual(pair["gained_by_candidate_rank_1_to_10"], [0] * 5 + [1] + [0] * 4)
        self.assertEqual(pair["lost_by_baseline_rank_1_to_10"], [0] * 4 + [1] + [0] * 5)
        self.assertEqual([(key, base, full) for key, _, base, full in audit], [
            ("a", 1, 1), ("b", None, 6), ("c", 5, None), ("d", None, None),
        ])

    def test_nonpositive_lower_bound_and_empty_roster(self):
        self.assertEqual(adoption_gates(5_000, 1, -1e-12), {
            "practical_gain": True, "positive_lower_bound": False,
        })
        self.assertEqual(adoption_gates(5_000, 1, 1e-12), {
            "practical_gain": True, "positive_lower_bound": True,
        })
        result = score_home([], BASELINE, CANDIDATE)
        self.assertEqual(result["paired"]["scored_visitors"], 0)
        for field in ("visitor_bootstrap", "gates", "all_gates_pass"):
            self.assertIsNone(result[field])

    def test_same_visitor_cannot_enter_the_denominator_twice(self):
        rows = [("a", OCTOBER_START, ["1"]), ("a", OCTOBER_START + 1, ["11"])]
        with self.assertRaises(ValueError):
            score_home(rows, BASELINE, CANDIDATE)

    def test_formal_scope_excludes_seen_windows_and_needs_matching_approval(self):
        packet = synthetic_manifest(1, "a" * 64)
        self.assertEqual(tuple(packet_scope(packet, "synthetic-approval")), tuple(packet["window_utc_ms"]))
        for start in (1438387200000, 1441065600000):  # August development and September holdout.
            with self.subTest(window_start=start), self.assertRaises(ValueError):
                packet_scope(dict(packet, window_utc_ms=[start, OCTOBER_START + 1000]), "synthetic-approval")
        with self.assertRaises(ValueError):
            packet_scope(packet, "different-approval")

    def test_packet_visitor_must_be_new_and_first_view_in_half_open_window(self):
        end = OCTOBER_START + 1000
        visitor = {
            "visitor": "v", "first_view_ms": OCTOBER_START, "targets": ["11"],
            "seen_before_window": False,
        }
        self.assertEqual(list(packet_visitors([visitor], OCTOBER_START, end)),
                         [("v", OCTOBER_START, ["11"])])
        for invalid in ({"seen_before_window": True}, {"seen_before_window": None},
                        {"first_view_ms": OCTOBER_START - 1}, {"first_view_ms": end}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                list(packet_visitors([dict(visitor, **invalid)], OCTOBER_START, end))

    def test_cli_packet_checks_hashes_and_only_publishes_a_complete_rank_audit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            roster = root / "synthetic.jsonl"
            manifest = root / "manifest.json"
            # The CLI opens only this temporary database; both lists are synthetic.
            training_db = root / "training.sqlite"
            training_db.touch()

            def run_cli(audit):
                args = ["score_home", "--manifest", str(manifest), "--approval-ref", "synthetic-approval",
                        "--rank-audit", str(audit)]
                output = StringIO()
                with (patch.object(sys, "argv", args), patch.object(scorer, "DB", training_db),
                      patch.object(scorer, "frozen_rankings", return_value=(BASELINE, CANDIDATE)),
                      redirect_stdout(output)):
                    scorer.main()
                return json.loads(output.getvalue())

            visitors = [("anon-b", ["11", "15"]), ("anon-c", ["999"]), ("anon-a", ["1", "6"])]
            rows = [{"visitor": visitor, "first_view_ms": OCTOBER_START, "seen_before_window": False,
                     "targets": targets} for visitor, targets in visitors]
            roster.write_bytes("".join(json.dumps(row) + "\n" for row in rows).encode())
            roster_hash = sha256(roster.read_bytes()).hexdigest()
            manifest.write_bytes(json.dumps(synthetic_manifest(3, roster_hash)).encode())
            good_audit = root / "valid-ranks.jsonl"
            report = run_cli(good_audit)
            self.assertEqual(report["manifest_sha256"], sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(report["roster_file_sha256"], roster_hash)
            pair = report["paired"]
            self.assertEqual((pair["scored_visitors"], pair["candidate_only_gained"], pair["baseline_only_lost"],
                              pair["net_hits"], pair["both_hit"], pair["both_missed"]), (3, 1, 0, 1, 1, 1))
            self.assertEqual(report["reserved_test_ranked_queries"], 0)
            self.assertEqual([json.loads(line) for line in good_audit.read_text().splitlines()], [
                ["anon-a", OCTOBER_START, 1, 1], ["anon-b", OCTOBER_START, None, 6],
                ["anon-c", OCTOBER_START, None, None],
            ])

            with self.subTest("tampered roster"):
                roster.write_bytes(roster.read_bytes().replace(b"999", b"998"))
                before = set(root.iterdir())
                errors = StringIO()
                with redirect_stderr(errors), self.assertRaises(SystemExit) as stopped:
                    run_cli(root / "invalid-ranks.jsonl")
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn("SHA-256", errors.getvalue())
                self.assertEqual(set(root.iterdir()), before)

            with self.subTest("empty eligible population"):
                roster.write_bytes(b"")
                manifest.write_bytes(json.dumps(synthetic_manifest(0, sha256(b"").hexdigest())).encode())
                empty_audit = root / "empty-ranks.jsonl"
                empty = run_cli(empty_audit)
                self.assertEqual(empty["paired"]["scored_visitors"], 0)
                self.assertIsNone(empty["adoption_gates_met"])
                self.assertIsNone(empty["visitor_bootstrap"])
                self.assertEqual(empty_audit.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
