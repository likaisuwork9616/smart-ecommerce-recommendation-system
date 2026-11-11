"""Test sparse sample membership, original parser parity and paired estimates."""
import unittest

from scripts import diagnose_retailrocket_session_knn_decode_v44 as run


class SparseDecodeTests(unittest.TestCase):
    def test_one_seeded_block_per_stratum_and_partial_last_weight(self):
        span = run.BLOCK * run.STRATUM
        length = span + 2 * run.BLOCK + 1
        windows = run.plan(length, run.WARMUP_SEED)
        self.assertEqual(windows, run.plan(length, run.WARMUP_SEED))
        self.assertEqual([window[2] for window in windows], [64, 3])
        for index, (start, end, _) in enumerate(windows):
            self.assertEqual(start // span, index)
            self.assertEqual(start % run.BLOCK, 0)
            self.assertEqual(end, min(start + run.BLOCK, length))

    def test_exact_windows_sample_token_starts_and_skip_jumped_window(self):
        source = b'["' + b'x' * 300 + b'","z",[]]'
        sampler = run.Sampler([(1, 2, 1), (10, 20, 1), (304, 307, 1), (309, 311, 1)], len(source))
        self.assertEqual(run.sampled_decoder(sampler)(source), run.prior.typed._decode(source))
        self.assertEqual([(row[0], row[2]) for row in sampler.records], [(1, 0), (0, 0), (1, 0), (0, 2)])

    def test_unicode_escapes_and_original_rejections_match(self):
        data = {'商品': ['🍀\t', True, -0.0, '\x01'], 'empty': []}
        source = run.prior.typed.ORIGINAL_CANONICAL(data)
        expected = run.prior.typed._decode(source)
        _, actual = run.replay(source, len(source.decode('utf-8')), run.WARMUP_SEED)
        self.assertEqual(actual, expected)
        for invalid in (b'[true,]', br'"\u0061"', b'"\xff"'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError) as expected_error:
                    run.prior.typed._decode(invalid)
                with self.assertRaises(type(expected_error.exception)) as actual_error:
                    run.replay(invalid, len(invalid), run.WARMUP_SEED)
                self.assertEqual(str(actual_error.exception), str(expected_error.exception))

    def test_inverse_probability_and_paired_original_time(self):
        length = run.BLOCK * run.STRATUM + 2 * run.BLOCK + 1
        sampled = dict(seed=run.WARMUP_SEED, interval=[30000, 50000], utf8_ns=100,
                       windows=[[2, 80, 1, 40], [1, 30, 2, 20]])
        plain = dict(seed=None, interval=[0, 18000])
        result = run.pair_summary(plain, sampled, length, clock_floor=10)
        self.assertEqual(result['string_calls'], 131)
        self.assertEqual(result['string_ns'], 5210)
        self.assertEqual(result['tuple_ns'], 2620)
        self.assertEqual(result['array_ns'], 10070)
        self.assertEqual(result['array_minus_string_ns'], 4860)
        self.assertEqual(result['array_minus_string_clock_floor_ns'], 8180)
        self.assertEqual(result['overhead_ns'], 2000)
        sampled['windows'][0][1] = 50000
        with self.assertRaisesRegex(ValueError, 'exceed full decoder time'):
            run.pair_summary(plain, sampled, length, clock_floor=10)
