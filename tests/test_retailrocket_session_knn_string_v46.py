"""Compare the V46 candidate to V39 on exact output and first rejection."""
from random import Random
import unittest

from scripts import compare_retailrocket_session_knn_string_v46 as bench
from scripts import retailrocket_session_knn_typed_string_v46 as candidate


def outcome(function, *args):
    try:
        return 'accepted', function(*args)
    except ValueError as error:
        return 'rejected', type(error), str(error)


class StringCandidateTests(unittest.TestCase):
    def assert_string(self, text, start=0):
        self.assertEqual(outcome(candidate.scan_string, text, start), outcome(candidate.original._string, text, start))

    def test_unicode_boundaries_and_nonzero_start(self):
        for code in (0x1f, 0x20, 0x7f, 0x85, 0x2028, 0x2029, 0xd7ff, 0xd800, 0xdbff,
                     0xdc00, 0xdfff, 0xe000, 0xffff, 0x10000, 0x10ffff):
            with self.subTest(code=code):
                self.assert_string('前綴"a' + chr(code) + '商品🍀"後綴', 2)

    def test_all_raw_controls_and_long_control_escapes(self):
        for code in range(32):
            with self.subTest(code=code):
                self.assert_string('"x' + chr(code) + 'y"')
                self.assert_string(f'"x\\u{code:04x}y"')
                self.assert_string(f'"x\\u{code:04X}y"')

    def test_short_escapes_and_first_rejection(self):
        for escape in ('"', '\\', 'b', 'f', 'n', 'r', 't', '/', 'x', 'U', 'u000', 'u000g', 'u0061',
                       'uD800', 'ud800', 'ud83d\\udc00', 'u0020'):
            self.assert_string('"x\\' + escape + 'y"')
        for text in ('"open', '"truncated\\', '"\\q' + chr(0), '"' + chr(0xd800) + '\\q"', '"\\u001b'):
            self.assert_string(text)

    def test_seeded_mixed_tokens(self):
        rng = Random(46)
        pieces = ('abc', '商品', '🍀', '\"', '\\', '\\n', '\n', chr(0xd800), '\\u0001', '\\u001A', '\\/', '\\u1234')
        for _ in range(4096):
            text = '前綴"' + ''.join(rng.choices(pieces, k=rng.randrange(14)))
            text += '"' if rng.randrange(2) else ''
            self.assert_string(text, 2)

    def test_full_decoder_keeps_exact_input_rules_and_tuple_tree(self):
        original = candidate.original
        data = {'商品': [True, None, -0.0, 2, ('x🍀', 'a"\\\n\t\x01')], 'other': []}
        sources = (original.ORIGINAL_CANONICAL(data), b'[["x"],[false]]', b'["\xff"]', b'["\\u0061"]',
                   b'["x",]', b'["x" false]', b'["x"]extra', bytearray(b'["x"]'))
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(outcome(candidate.decode, source), outcome(original._decode, source))
        self.assertIsNot(original._decode.__globals__['_string'], candidate.scan_string)

    def test_iterative_decoder_keeps_deep_array_depth(self):
        depth = 1600
        source = b'[' * depth + b'"x"' + b']' * depth
        root, actual_depth = candidate.decode(source)
        self.assertEqual(actual_depth, candidate.original._decode(source)[1])
        self.assertEqual(actual_depth, depth)
        for _ in range(depth):
            self.assertIs(type(root), tuple)
            self.assertEqual(len(root), 1)
            root = root[0]
        self.assertEqual(root, 'x')

    def test_pair_summary_checks_order_and_uses_paired_delta(self):
        tick = 0

        def sample(mode):
            nonlocal tick
            start = tick
            tick += 9 if mode == 'original' else 6
            return dict(mode=mode, interval=[start, tick])

        warmups = [sample(mode) for mode in bench.DECODERS]
        pairs = [[sample(mode) for mode in order] for order in bench.ORDERS]
        result = bench.summarize(warmups, pairs)
        self.assertEqual(result['metrics']['saving_ns']['median'], 3)
        self.assertEqual(result['faster_pairs'], 8)
        with self.assertRaisesRegex(ValueError, 'alternating pairs'):
            bench.summarize(warmups, pairs[::-1])
