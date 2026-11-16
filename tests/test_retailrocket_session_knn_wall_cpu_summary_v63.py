"""Hand-built duration fixtures only; no clocks, calibration or workload runs."""
from copy import deepcopy
from fractions import Fraction
import unittest

from scripts.retailrocket_session_knn_wall_cpu_summary_v63 import (
    SCHEDULE, nearest_rank, distribution, summarize_overhead)


def fixture(deltas=(1, -1, 2, -2, 1, -1, 2, -2), original=100):
    rows = []
    for label, mode in SCHEDULE:
        wall = 1_000_000 if label.startswith('warm_') else original
        if label.startswith('pair_') and mode == 'D':
            wall += deltas[int(label.split('_')[1])-1]
        rows.append(dict(label=label, mode=mode, wall_ns=wall, completed=True))
    return rows


class WallCpuSummaryTests(unittest.TestCase):
    def test_nearest_rank_is_one_based_and_keeps_original_integers(self):
        values = list(reversed(range(1, 101)))
        self.assertEqual(nearest_rank(values, .07), 7)
        self.assertEqual(nearest_rank(values, .95), 95)
        self.assertEqual(nearest_rank(values, 1), 100)
        self.assertEqual(nearest_rank([2**100 + 1], .01), 2**100 + 1)
        self.assertEqual(nearest_rank([1, 2, 3, 4], .5), 2)

    def test_invalid_percentiles_and_values_are_rejected(self):
        for p in (0, -1, 1.1, True, None, float('nan'), float('inf'), '0.95'):
            with self.subTest(p=p), self.assertRaises(ValueError):
                nearest_rank([1, 2], p)
        for values in ([], [None], [True], [float('nan')], [float('inf')], '12'):
            with self.subTest(values=values), self.assertRaises(ValueError):
                nearest_rank(values, .5)

    def test_distribution_even_median_and_missing_denominators(self):
        value = distribution([None, 4, -2, 1, 3])
        self.assertEqual(value, dict(count=5, valid=4, missing=1, min=-2, median=2,
            median_exact=dict(numerator=2, denominator=1), max=4, p95=4))
        self.assertEqual(distribution([None, None]), dict(count=2, valid=0, missing=2,
            min=None, median=None, median_exact=None, max=None, p95=None))
        self.assertEqual(distribution([])['count'], 0)

    def test_large_odd_integer_median_retains_exact_rational(self):
        base = 2**100
        result = distribution([base, base+1])
        self.assertEqual(result['median_exact'], dict(numerator=2*base+1, denominator=2))
        self.assertEqual(result['min'], base)
        self.assertEqual(result['max'], base+1)

    def test_all_eight_pairs_order_layers_and_warmups_are_preserved(self):
        result = summarize_overhead(fixture())
        self.assertEqual(result['status'], 'perturbation_budget_passed')
        self.assertEqual([row['order'] for row in result['pairs']], ['OD', 'DO']*4)
        self.assertEqual([row['pair'] for row in result['pairs']], list(range(1, 9)))
        self.assertEqual([row['label'] for row in result['warmups']], ['warm_O', 'warm_D'])
        self.assertEqual(result['signed_delta_ns']['min'], -2)
        self.assertEqual(result['signed_delta_ns']['max'], 2)
        self.assertEqual(result['absolute_relative_delta']['median_exact'],
                         dict(numerator=3, denominator=200))
        self.assertEqual(result['by_order']['OD']['signed_delta_ns']['median'], 1.5)
        self.assertEqual(result['by_order']['DO']['signed_delta_ns']['median'], -1.5)
        self.assertEqual(result['gate']['valid_pairs'], 8)
        self.assertFalse(result['gate']['measurement_executed_by_this_function'])
        self.assertEqual(result['gate']['evaluation'], 'provided_records_only')

    def test_warm_values_do_not_change_formal_arithmetic(self):
        rows = fixture()
        rows[0]['wall_ns'] = 1
        rows[1]['wall_ns'] = 10**30
        result = summarize_overhead(rows)
        self.assertEqual(result['status'], 'perturbation_budget_passed')
        self.assertEqual(result['absolute_relative_delta']['max'], .02)

    def test_signed_differences_cannot_cancel_the_absolute_budget(self):
        result = summarize_overhead(fixture((4, -4)*4))
        self.assertEqual(result['signed_delta_ns']['median'], 0)
        self.assertEqual(result['status'], 'perturbation_not_accepted')
        self.assertEqual(result['failure_reasons'], ['median_absolute_relative_budget'])
        self.assertFalse(result['gate']['median_passed'])
        self.assertTrue(result['gate']['maximum_passed'])

    def test_exact_budget_edges_and_above_edge_without_float_rounding(self):
        result = summarize_overhead(fixture((2,)*7+(5,)))
        self.assertEqual(result['status'], 'perturbation_budget_passed')
        base = 100 * 2**100
        over_median = summarize_overhead(fixture((2*2**100+1,)*8, original=base))
        self.assertEqual(over_median['status'], 'perturbation_not_accepted')
        self.assertFalse(over_median['gate']['median_passed'])
        over_max = summarize_overhead(fixture((0,)*7+(5*2**100+1,), original=base))
        self.assertFalse(over_max['gate']['maximum_passed'])
        self.assertEqual(over_max['pairs'][7]['absolute_relative_exact'],
            dict(numerator=5*2**100+1, denominator=base))

    def test_missing_duration_stays_in_original_pair_without_substitution(self):
        rows = fixture()
        missing = next(row for row in rows if row['label'] == 'pair_2_D')
        missing['wall_ns'] = None
        result = summarize_overhead(rows)
        self.assertEqual(result['status'], 'perturbation_not_accepted')
        self.assertEqual(len(result['pairs']), 8)
        self.assertIsNone(result['pairs'][1]['delta_D_minus_O_ns'])
        self.assertIsNone(result['pairs'][1]['absolute_relative_delta'])
        self.assertEqual(result['pairs'][1]['unavailable_reasons']['D'], 'missing_wall')
        self.assertEqual(result['pairs'][2]['delta_D_minus_O_ns'], 2)
        self.assertEqual(result['absolute_relative_delta']['missing'], 1)
        self.assertEqual(result['gate']['valid_pairs'], 7)

    def test_incomplete_and_zero_original_are_not_successful_observations(self):
        for mutation in ('incomplete', 'zero_original', 'warm_missing', 'warm_incomplete'):
            rows = fixture()
            if mutation == 'incomplete': rows[2]['completed'] = False
            elif mutation == 'zero_original': rows[2]['wall_ns'] = 0
            elif mutation == 'warm_missing': rows[1]['wall_ns'] = None
            else: rows[0]['completed'] = False
            with self.subTest(mutation=mutation):
                result = summarize_overhead(rows)
                self.assertEqual(result['status'], 'perturbation_not_accepted')
                if mutation.startswith('warm_'):
                    self.assertEqual(result['gate']['valid_pairs'], 8)
                    self.assertIn('warmup_unavailable', result['failure_reasons'])
                else:
                    self.assertIsNone(result['pairs'][0]['delta_D_minus_O_ns'])

    def test_all_missing_remain_null_and_cannot_pass(self):
        rows = fixture()
        for row in rows[2:]: row['wall_ns'] = None
        result = summarize_overhead(rows)
        self.assertEqual(result['gate']['missing_pairs'], 8)
        self.assertIsNone(result['absolute_relative_delta']['median'])
        self.assertIsNone(result['absolute_relative_delta']['max'])
        self.assertFalse(result['gate']['median_passed'])
        self.assertFalse(result['gate']['maximum_passed'])

    def test_missing_extra_duplicate_and_wrong_schedule_are_structural_errors(self):
        for mutation in ('missing', 'extra', 'duplicate', 'reordered', 'mode', 'fields'):
            rows = fixture()
            if mutation == 'missing': rows.pop()
            elif mutation == 'extra': rows.append(deepcopy(rows[-1]))
            elif mutation == 'duplicate': rows[3] = deepcopy(rows[2])
            elif mutation == 'reordered': rows[2], rows[3] = rows[3], rows[2]
            elif mutation == 'mode': rows[2]['mode'] = 'D'
            else: rows[2]['extra'] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                summarize_overhead(rows)

    def test_invalid_wall_and_completion_types_are_rejected(self):
        for value in (-1, False, True, 1., '1', float('nan'), float('inf')):
            rows = fixture(); rows[2]['wall_ns'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize_overhead(rows)
        rows = fixture(); rows[2]['completed'] = 1
        with self.assertRaises(ValueError): summarize_overhead(rows)

    def test_results_are_detached_and_input_is_unchanged(self):
        rows = fixture(); original = deepcopy(rows)
        result = summarize_overhead(rows)
        self.assertEqual(rows, original)
        result['pairs'][0]['O']['wall_ns'] = 1
        result['warmups'][0]['wall_ns'] = 1
        self.assertEqual(rows, original)


if __name__ == '__main__':
    unittest.main()
