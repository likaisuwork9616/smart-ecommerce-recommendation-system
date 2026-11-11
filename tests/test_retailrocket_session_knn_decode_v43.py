"""Exercise the measured decoder's parity and interval accounting."""
from copy import deepcopy
import unittest

from scripts import diagnose_retailrocket_session_knn_decode_v43 as run


class DecodeDiagnosticTests(unittest.TestCase):
    def test_timers_preserve_original_tree_depth_and_operation_counts(self):
        source = run.typed.ORIGINAL_CANONICAL({'商品': ['🍀\t\n', -0.0, True, 13, ('\x01', None)], 'empty': []})
        original = run.typed._decode
        _, expected = run.replay(source, 'plain')
        sample, actual = run.replay(source, 'observed')
        self.assertIs(original, run.typed._decode)
        self.assertEqual(actual, expected)
        total, parts = run.phases(sample, run.tree_counts(expected[0]))
        self.assertEqual(set(parts), set(run.PHASES))
        self.assertEqual(sum(parts.values()), total)
        self.assertTrue(all(value >= 0 for value in parts.values()))

    def test_known_array_and_string_counts_and_escape_cases(self):
        source = br'["tag",["escaped\n",true],[],["\u0001"]]'
        sample, decoded = run.replay(source, 'observed')
        expected = (('tag', ('escaped\n', True), (), ('\x01',)), 2)
        self.assertEqual(decoded, expected)
        self.assertEqual(sample['calls'], {'utf8': 1, 'tuple_build': 4, 'string_scan': 3})

    def test_original_rejection_of_invalid_utf8_escapes_and_array_punctuation(self):
        for source in (b'"\xff"', br'"\u0061"', b'[true,]', b'[true false]', b'[true]]', bytearray(b'[]')):
            with self.subTest(source=source):
                with self.assertRaises(ValueError) as expected:
                    run.replay(source, 'plain')
                with self.assertRaises(type(expected.exception)) as actual:
                    run.replay(source, 'observed')
                self.assertEqual(str(actual.exception), str(expected.exception))

    def test_replay_summary_rejects_changed_counts_negative_residual_or_wrong_order(self):
        source = b'["x",[false]]'
        counts = {'utf8': 1, 'string_scan': 1, 'tuple_build': 2}
        warmups = [run.replay(source, mode)[0] for mode in ('plain', 'observed')]
        pairs = [[run.replay(source, mode)[0] for mode in order] for order in run.prior.ORDERS]
        self.assertEqual(len(run.summarize(warmups, pairs, counts)['observed_minus_plain_ns']), 6)
        with self.assertRaisesRegex(ValueError, 'alternating pairs'):
            run.summarize(warmups, pairs[::-1], counts)
        wrong_count = deepcopy(pairs[0][1])
        wrong_count['calls']['tuple_build'] += 1
        with self.assertRaisesRegex(ValueError, 'operation counts'):
            run.phases(wrong_count, counts)
        overflow = deepcopy(pairs[0][1])
        overflow['elapsed_ns']['utf8'] = run.prior._duration(overflow['interval']) + 1
        with self.assertRaisesRegex(ValueError, 'exceed the full decoder interval'):
            run.phases(overflow, counts)
