"""Synthetic numeric tests only; no saved data or measured workload is loaded."""
from copy import deepcopy
from math import fsum
import unittest

from scripts.retailrocket_session_knn_query_distribution_v50 import (
    RANK_STAGES, query_parts, signed_distribution,
)


def query_fixture():
    """Return a fresh artificial row reusable by the offline analysis tests."""
    return dict(verification_seconds=10.0, rank_seconds=8.0, checkpoint_append_seconds=3.0,
        append_without_commit_seconds=2.0, chunk_commit_seconds=1.0, seconds=13.5,
        rank_stages_seconds=dict(zip(RANK_STAGES, (1.0,) * 7, strict=True)))


class DistributionTests(unittest.TestCase):
    def test_positive_and_negative_cancellation_uses_gross_positive_denominator(self):
        result = signed_distribution([10, -9, 1, -1, 0])
        self.assertEqual((result['count'], result['positive_count'], result['negative_count'], result['zero_count']),
                         (5, 2, 2, 1))
        self.assertEqual((result['net_seconds'], result['positive_seconds'], result['negative_seconds']), (1, 11, -10))
        self.assertEqual(result['positive_top1_seconds'], 10)
        self.assertAlmostEqual(result['positive_top1_share'], 10 / 11)
        self.assertEqual(result['positive_top5_share'], 1)
        self.assertEqual(result['n_for_50pct_positive'], 1)
        self.assertEqual(result['n_for_80pct_positive'], 1)

    def test_all_negative_and_all_zero_have_no_positive_concentration(self):
        for values in ([-3, -2, -1], [0, 0, 0]):
            result = signed_distribution(values)
            with self.subTest(values=values):
                self.assertEqual(result['positive_seconds'], 0)
                for size in (1, 5, 10):
                    self.assertEqual(result['positive_top' + str(size) + '_seconds'], 0)
                    self.assertIsNone(result['positive_top' + str(size) + '_share'])
                self.assertIsNone(result['n_for_50pct_positive'])
                self.assertIsNone(result['n_for_80pct_positive'])

    def test_concentrated_and_uniform_positive_distributions_are_distinguished(self):
        concentrated = signed_distribution([20] + [0] * 19)
        uniform = signed_distribution([1] * 20)
        self.assertEqual(concentrated['net_seconds'], uniform['net_seconds'])
        self.assertEqual(concentrated['positive_top1_share'], 1)
        self.assertEqual(concentrated['n_for_80pct_positive'], 1)
        self.assertEqual(uniform['positive_top1_share'], .05)
        self.assertEqual(uniform['positive_top5_share'], .25)
        self.assertEqual(uniform['positive_top10_share'], .5)
        self.assertEqual(uniform['n_for_50pct_positive'], 10)
        self.assertEqual(uniform['n_for_80pct_positive'], 16)

    def test_one_millisecond_boundaries_belong_to_within_count(self):
        result = signed_distribution([-.002, -.001, -.0001, 0, .0001, .001, .002])
        self.assertEqual((result['above_1ms'], result['below_minus_1ms'], result['within_1ms']), (1, 1, 5))
        self.assertEqual(result['positive_count'], 3)
        self.assertEqual(result['negative_count'], 3)

    def test_percentiles_use_nearest_rank_without_interpolation(self):
        result = signed_distribution(value for value in range(1, 11))
        self.assertEqual((result['p10'], result['p90'], result['median'], result['min'], result['max']),
                         (1, 9, 5.5, 1, 10))
        self.assertIn('nearest_rank', result['percentile_method'])
        short = signed_distribution([2, 0, 1])
        self.assertEqual((short['p10'], short['p90']), (0, 2))
        singleton = signed_distribution([.1])
        self.assertEqual((singleton['p10'], singleton['p90']), (.1, .1))
        large = signed_distribution([1e308])
        self.assertEqual((large['n_for_50pct_positive'], large['n_for_80pct_positive']), (1, 1))

    def test_empty_nonfinite_nonnumeric_and_overflowing_observations_are_rejected(self):
        for values in ([], [float('nan')], [float('inf')], [-float('inf')], [True], ['1'], [None],
                       [1e308, 1e308], [10**1000]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                signed_distribution(values)


class QueryPartsTests(unittest.TestCase):
    def test_nested_query_parts_and_bridge_conserve_without_double_counting(self):
        row = query_fixture()
        before = deepcopy(row)
        result = query_parts(row)
        self.assertEqual(row, before)
        self.assertEqual(result['query_charged_seconds'], 13)
        self.assertEqual(result['query_envelope_seconds'], 13.5)
        self.assertEqual(result['signed_timer_bridge'], .5)
        self.assertEqual(set(result['parts_seconds']), {*RANK_STAGES, 'rank_other', 'verification_other', 'append', 'query_commit'})
        self.assertEqual(result['parts_seconds']['rank_other'], 1)
        self.assertEqual(result['parts_seconds']['verification_other'], 2)
        self.assertEqual(fsum(result['parts_seconds'].values()), 13)
        self.assertEqual(result['max_reconciliation_residual_seconds'], 0)

    def test_tail_commit_is_not_assigned_to_a_query(self):
        row = query_fixture()
        expected = query_parts(row)
        row['tail_commit_seconds'] = 1000
        self.assertEqual(query_parts(row), expected)

    def test_invalid_nesting_and_append_identity_are_rejected(self):
        for field, value, message in (('rank_seconds', 6, 'Rank stages exceed'),
                                       ('verification_seconds', 7, 'Rank stages exceed'),
                                       ('checkpoint_append_seconds', 4, 'Checkpoint append'),
                                       ('seconds', 12, 'query envelope')):
            row = query_fixture()
            row[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                query_parts(row)

    def test_rank_stage_schema_and_original_timer_values_are_strict(self):
        for change in ('missing', 'extra', 'rename'):
            row = query_fixture()
            if change in ('missing', 'rename'):
                row['rank_stages_seconds'].pop(RANK_STAGES[0])
            if change in ('extra', 'rename'):
                row['rank_stages_seconds']['new_stage'] = 0
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'original seven rank stages'):
                query_parts(row)
        for value in (float('nan'), float('inf'), -1, True, '1'):
            for location in ('timer', 'stage'):
                row = query_fixture()
                if location == 'timer':
                    row['verification_seconds'] = value
                else:
                    row['rank_stages_seconds'][RANK_STAGES[0]] = value
                with self.subTest(value=value, location=location), self.assertRaisesRegex(ValueError, 'Finite nonnegative'):
                    query_parts(row)

    def test_small_roundoff_is_retained_and_material_boundary_errors_are_rejected(self):
        row = query_fixture()
        row['rank_seconds'] = 7 - 1e-9
        row['checkpoint_append_seconds'] = 3 + 1e-9
        row['seconds'] = 13 - 1e-9
        result = query_parts(row)
        self.assertLess(result['parts_seconds']['rank_other'], 0)
        self.assertLess(result['signed_timer_bridge'], 0)
        self.assertAlmostEqual(fsum(result['parts_seconds'].values()), result['query_charged_seconds'])
        row['seconds'] = 13 - 1e-7
        with self.assertRaisesRegex(ValueError, 'query envelope'):
            query_parts(row)


if __name__ == '__main__':
    unittest.main()
