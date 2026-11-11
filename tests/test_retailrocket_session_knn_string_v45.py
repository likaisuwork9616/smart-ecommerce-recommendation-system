"""Verify split string timings and exact V44 sample membership."""
import unittest
from unittest.mock import patch

from scripts import diagnose_retailrocket_session_knn_string_v45 as run


class StringTimingTests(unittest.TestCase):
    def test_preserves_values_and_end_offsets_for_original_string_forms(self):
        split = run.split_string()
        for text in ('""', 'x"商品🍀"y', 'x"a\\t\\n\\u0001\\\\\\\""y'):
            with self.subTest(text=text):
                start = text.index('"')
                value, end, checked, scanned = split(text, start)
                self.assertEqual((value, end), run.typed._string(text, start))
                self.assertLessEqual(checked, scanned)

    def test_preserves_original_rejection_for_bad_escape_and_missing_quote(self):
        split = run.split_string()
        for text in ('"\\u0061"', '"x\\', '"x\x01"', '"open'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as original:
                    run.typed._string(text, 0)
                with self.assertRaisesRegex(ValueError, str(original.exception)):
                    split(text, 0)

    def test_separates_character_scan_and_return_using_four_timestamps(self):
        with patch.object(run, 'perf_counter_ns', side_effect=[10, 31, 39, 44]):
            sampler = run.StringSampler([(0, 3, 1)], 3)
            self.assertEqual(sampler.string('"x"', 0), ('x', 3))
        self.assertEqual(sampler.records, [[1, 21, 8, 5]])

    def test_preserves_whole_tree_and_v44_counts_with_crossed_windows(self):
        source = b'["' + b'x' * 300 + b'","z",[]]'
        windows = [(1, 2, 1), (10, 20, 1), (304, 307, 1), (309, 311, 1)]
        original = run.prior.Sampler(windows, len(source))
        split = run.StringSampler(windows, len(source))
        self.assertEqual(run.prior.sampled_decoder(split)(source), run.prior.sampled_decoder(original)(source))
        self.assertEqual([row[0] for row in split.records], [row[0] for row in original.records])
        self.assertEqual([row[0] for row in split.records], [1, 0, 1, 0])

    def test_applies_tail_weight_and_rejects_invalid_counts_and_intervals(self):
        length = run.prior.BLOCK * (run.prior.STRATUM + 2)
        sample = dict(seed=run.prior.WARMUP_SEED, interval=[10, 90], windows=[[1, 20, 4, 3], [2, 30, 5, 4]])
        count, phases, sampled = run.phases(sample, length, [1, 2])
        self.assertEqual((count, sampled), (68, 3))
        self.assertEqual(phases, {'character_check': 1340, 'scanstring': 266, 'return_tail': 200})
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            run.phases(sample, length, [2, 1])
        sample['interval'][1] = 20
        with self.assertRaisesRegex(ValueError, 'exceed the decoder interval'):
            run.phases(sample, length, [1, 2])
