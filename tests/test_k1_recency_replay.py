import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import k1_recency_replay as replay
from scripts.evaluate_k1_recency_slot import evaluate
from scripts.evaluate_recency_slot import AUGUST_START


class K1RecencyReplayTest(unittest.TestCase):
    def test_selects_first_change_for_each_outcome_and_binds_the_receipt(self):
        original = [(str(rank), "knn") for rank in range(1, 11)]

        def query(position, target, recent):
            return ("visitor", 0, AUGUST_START + position), {target}, original, [], [], recent, 1

        rows = [
            query(1, "4", "99"),
            query(2, "21", "21"),
            query(3, "22", "22"),
            query(4, "10", "42"),
            query(5, "10", "43"),
        ]

        def study(*, observe_change=None):
            return {**evaluate(rows, observe_change=observe_change), "ordered_query_keys_sha256": "fixture"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / replay.REPORT
            report.parent.mkdir(parents=True)
            report.write_bytes(replay.encode(study()))
            with (patch.object(replay, "ROOT", root),
                  patch("scripts.evaluate_k1_recency_slot.study", side_effect=study)):
                data, receipt = replay.build_replay()
            (root / replay.RECEIPT).write_bytes(replay.encode(receipt))
            path = replay.restore_verified_examples(root, replay.RECEIPT, replay.EXAMPLES, data, receipt)
            payload = replay.load_k1_recency_replay(root)
            self.assertEqual(payload, json.loads(data))
            self.assertEqual(payload["total_queries"], 5)
            self.assertEqual(payload["net_additional_hits"], 0)
            gained, lost = payload["cases"]
            for case, kind, position, removed, inserted, before, after in (
                (gained, "gained", 2, "10", "21", [], [10]),
                (lost, "lost", 4, "10", "42", [10], []),
            ):
                with self.subTest(kind=kind):
                    self.assertEqual((case["id"], case["count"], case["cohort_position"]), (kind, 2, position))
                    self.assertEqual(case["k1"]["items"][:9], case["k1_recency"]["items"][:9])
                    self.assertEqual(case["k1"]["items"][9], removed)
                    self.assertEqual(case["k1_recency"]["items"][9], inserted)
                    self.assertEqual(case["k1"]["hit_ranks"], before)
                    self.assertEqual(case["k1_recency"]["hit_ranks"], after)
                    self.assertNotIn("history", case)
            path.write_bytes(data + b" ")
            with self.assertRaisesRegex(ValueError, "回放收據不符"):
                replay.load_k1_recency_replay(root)
