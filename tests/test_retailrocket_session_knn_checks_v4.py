"""Frozen-oracle equivalence for metric caching and typed JSON exact checks."""
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_DOWN
from fractions import Fraction
import math
import random
import sys
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_checks_v4 as checks
from scripts.retailrocket_popularity_oracle import terms as frozen_terms
from scripts.retailrocket_session_knn_oracle import exact as frozen_exact


def outcome(function, actual, expected):
    try:
        function(actual, expected)
        return 'accepted'
    except BaseException as error:
        return type(error).__name__


class MetricCacheTests(unittest.TestCase):
    def setUp(self):
        checks.clear_caches()

    def compare_terms(self, ids, targets):
        binary, precise = checks.terms(ids, targets)
        old_binary, old_precise = frozen_terms(ids, targets)
        self.assertEqual(binary, old_binary)
        self.assertEqual({key: value.hex() for key, value in binary.items() if type(value) is float},
                         {key: value.hex() for key, value in old_binary.items() if type(value) is float})
        self.assertEqual({key: str(value) for key, value in precise.items()},
                         {key: str(value) for key, value in old_precise.items()})
        return binary, precise

    def test_hit_patterns_and_full_target_denominator_match_decimal_strings_and_float_bits(self):
        for target_count in (1, 2, 10, 11, 30):
            targets = ['t' + str(i) for i in range(target_count)]
            for ranks in ((), (1,), (2,), (10,), (1, 3), (2, 4, 10)):
                if len(ranks) > target_count:
                    continue
                hit = iter(targets)
                predicted = [next(hit) if rank in ranks else 'miss' + str(rank) for rank in range(1, 11)]
                with self.subTest(target_count=target_count, ranks=ranks):
                    self.compare_terms(predicted, targets)

    def test_empty_predictions_and_all_ten_hits(self):
        self.compare_terms([], ['t'])
        self.compare_terms(['t' + str(i) for i in range(10)], ['t' + str(i) for i in range(10)])

    def test_cache_key_depends_on_hit_ranks_and_full_count_not_ids_or_list_length(self):
        self.compare_terms(['a'], ['a', 'b'])
        self.compare_terms(['x', 'miss'], ['x', 'y'])
        info = checks.cache_info()['terms']
        self.assertEqual(info['misses'], 1)
        self.assertEqual(info['hits'], 1)
        self.compare_terms(['x'], ['x', 'y', 'z'])
        self.assertEqual(checks.cache_info()['terms']['misses'], 2)

    def test_invalid_inputs_do_not_bypass_validation_on_cache_hits(self):
        self.compare_terms(['a'], ['a'])
        before = checks.cache_info()['terms'].copy()
        for predicted, targets in [(['a'], []), (['a'], ['a', 'a']),
                                    (['a', 'a'], ['a']), (list(range(11)), [1])]:
            with self.subTest(predicted=predicted, targets=targets), self.assertRaises(ValueError):
                checks.terms(predicted, targets)
        self.assertEqual(checks.cache_info()['terms'], before)

    def test_returned_dictionaries_are_independent_and_cached_values_stay_frozen(self):
        first, precise = self.compare_terms(['a'], ['a'])
        first['ndcg'] = -99.0; first['extra'] = 'bad'
        precise['ndcg'] = Decimal(-99)
        again, exact = self.compare_terms(['x'], ['x'])
        self.assertEqual(again['ndcg'], 1.0)
        self.assertEqual(exact['ndcg'], Decimal(1))
        self.assertNotIn('extra', again)

    def test_custom_labels_and_subclasses_use_frozen_equality_without_pattern_cache(self):
        class MyString(str): pass
        with patch.object(checks, '_frozen_terms', wraps=frozen_terms) as original:
            self.compare_terms([MyString('x')], ['x'])
            self.assertEqual(original.call_count, 1)
        class Label:
            def __init__(self, name): self.name = name
            def __hash__(self): return 0
            def __eq__(self, other):
                return self.name == other.name or 'truth' in (self.name, other.name)
        self.compare_terms([Label('one'), Label('two')], [Label('truth')])
        self.assertEqual(checks.cache_info()['terms']['currsize'], 0)
        self.assertEqual(checks.cache_info()['label_fallbacks'], 2)

    def test_changed_numeric_context_falls_back_instead_of_reusing_old_decimal_result(self):
        predicted = ['miss', 'a']; targets = ['a', 'b', 'c']
        self.compare_terms(predicted, targets)
        with localcontext() as context:
            context.rounding = ROUND_DOWN
            context.prec = 31
            self.compare_terms(predicted, targets)
        self.assertEqual(checks.cache_info()['context_fallbacks'], 1)
        self.compare_terms(predicted, targets)
        self.assertEqual(checks.cache_info()['terms']['hits'], 1)

    def test_clear_cache_resets_counts_and_allows_a_fresh_run_context(self):
        self.compare_terms(['a'], ['a'])
        checks.clear_caches()
        self.assertEqual(checks.cache_info()['terms']['currsize'], 0)
        self.assertEqual(checks.cache_info()['terms']['hits'], 0)
        self.assertEqual(checks.cache_info()['terms']['misses'], 0)
        self.assertEqual(checks.cache_info()['context_fallbacks'], 0)


class ExactCheckTests(unittest.TestCase):
    def check_same(self, actual, expected):
        self.assertEqual(outcome(checks.recursive_exact, actual, expected),
                         outcome(frozen_exact, actual, expected))

    def test_plain_nested_values_order_types_and_signed_zero(self):
        values = [None, True, False, 0, 1, -1, 0.0, -0.0, 1.0, 1e-300,
                  5e-324, '1', [], [0], {'a': 1, 'b': [True, -0.0]}]
        for actual in values:
            for expected in values:
                with self.subTest(actual=repr(actual), expected=repr(expected)):
                    self.check_same(actual, expected)
        with self.assertRaises(ValueError):
            checks.recursive_exact({'nested': [0.0]}, {'nested': [-0.0]})
        checks.recursive_exact({'b': [2], 'a': 1}, {'a': 1, 'b': [2]})

    def test_tuple_and_list_are_json_array_equivalent(self):
        checks.recursive_exact({'x': (1, [2, 3])}, {'x': [1, (2, 3)]})
        self.check_same([1, (2,)], (1, [2]))

    def test_unicode_surrogate_pairs_astral_strings_and_nonascii_key_sorting_use_frozen(self):
        cases = [('\ud83d\ude00', '\U0001f600'),
                 ({'\ud83d\ude00': 1}, {'\U0001f600': 1}),
                 ({'\U0001f600': 1, '中': [2]}, {'中': [2], '\U0001f600': 1}),
                 ({'\ud800': 'x'}, {'\ud800': 'x'})]
        for actual, expected in cases:
            with self.subTest(actual=repr(actual)), patch.object(checks, '_frozen_exact', wraps=frozen_exact) as original:
                self.check_same(actual, expected)
                self.assertTrue(original.called)

    def test_scalar_container_subclasses_fallback_to_frozen(self):
        class MyInt(int): pass
        class MyFloat(float): pass
        class MyString(str): pass
        class MyDict(dict): pass
        class MyList(list): pass
        for actual, expected in [(MyInt(1), 1), (MyFloat(-0.0), -0.0),
                                 (MyString('x'), 'x'), (MyDict(a=1), {'a': 1}),
                                 ({'a': MyList([1])}, {'a': [1]})]:
            with patch.object(checks, '_frozen_exact', wraps=frozen_exact) as original:
                self.check_same(actual, expected)
                self.assertTrue(original.called)

    def test_nonstring_keys_preserve_json_key_coercion_and_sort_rejections(self):
        for actual, expected in [({1: 'x'}, {'1': 'x'}), ({False: 'x'}, {'false': 'x'}),
                                 ({1: 'x', 'a': 2}, {'1': 'x', 'a': 2})]:
            self.check_same(actual, expected)

    def test_nonfinite_and_unsupported_values_never_gain_acceptance(self):
        for value in (float('nan'), float('inf'), -float('inf'), Decimal(1), Fraction(1, 2), {1, 2}, object()):
            self.check_same({'a': value}, {'a': value})
            self.check_same({'a': 1, 'z': value}, {'a': 2, 'z': value})

    def test_huge_integer_json_digit_limit_is_not_bypassed(self):
        previous = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(640)
            big = 1 << 3000
            self.check_same(big, big)
            with self.assertRaises(ValueError):
                checks.recursive_exact(big, big)
            sys.set_int_max_str_digits(0)
            self.check_same(big, big)
        finally:
            sys.set_int_max_str_digits(previous)

    def test_circular_and_deep_structures_preserve_frozen_rejection_semantics(self):
        cycle = []; cycle.append(cycle)
        self.check_same(cycle, cycle)
        left = right = 1
        for _ in range(500):
            left, right = [left], [right]
        self.check_same(left, right)

    def test_fixed_random_plain_json_and_nested_mutations_match_frozen(self):
        rng = random.Random(20261103)
        def value(depth):
            if not depth or rng.randrange(3) == 0:
                return rng.choice((None, True, False, -0.0, 0.0, 1, 1.0, 'a', '99'))
            if rng.randrange(2):
                return [value(depth - 1) for _ in range(rng.randrange(5))]
            return {str(index): value(depth - 1) for index in range(rng.randrange(5))}
        for _ in range(150):
            actual = value(4)
            self.check_same(actual, deepcopy(actual))
            self.check_same(actual, value(4))

    def test_complete_large_neighbor_schema_and_deep_faults(self):
        actual = checks._benchmark_payload(500)
        checks.recursive_exact(actual, deepcopy(actual))
        for field, replacement in [('union', 999), ('intersection', True), ('similarity', [1.0, 4])]:
            corrupted = deepcopy(actual)
            corrupted['predictions']['K1']['selected_neighbors'][499][field] = replacement
            self.check_same(actual, corrupted)
            with self.assertRaises(ValueError):
                checks.recursive_exact(actual, corrupted)

    def test_dispatch_matches_frozen_under_both_explicit_strategies(self):
        for strategy in ('frozen', 'typed_recursive'):
            with patch.object(checks, 'EXACT_STRATEGY', strategy):
                checks.exact({'a': [1, -0.0]}, {'a': (1, -0.0)})
                with self.assertRaises(ValueError):
                    checks.exact({'a': True}, {'a': 1})

    def test_bounded_benchmark_reports_synthetic_scope_without_asserting_speed(self):
        result = checks.benchmark_exact(repeats=2, number=2, neighbors=500)
        self.assertFalse(result['real_data_accessed'])
        self.assertEqual(result['neighbors'], 500)
        self.assertEqual(set(result['median_per_call_seconds']), {'frozen', 'typed_recursive'})
        self.assertIn(result['recommended_strategy'], ('frozen', 'typed_recursive'))
        for kwargs in ({'neighbors': 501}, {'number': 0}, {'repeats': True}):
            with self.assertRaises(ValueError):
                checks.benchmark_exact(**kwargs)


if __name__ == '__main__':
    unittest.main()
