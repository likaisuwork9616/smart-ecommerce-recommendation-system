"""Hand-calculated four-timer cases only; no records or experiments are read."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_absolute_arms_v54 import compare_absolute_arms


def absolute_fixture(r32=1, r33=4, c32=2, c33=1):
    """Return a fresh artificial pair of anonymous-position timers."""
    return {'R': {32: r32, 33: r33}, 'C': {32: c32, 33: c33}}


class AbsoluteArmTests(unittest.TestCase):
    def test_r_contrast_leads_joint_positive_support(self):
        row = compare_absolute_arms(absolute_fixture())
        self.assertEqual(row['absolute_seconds'], {'R': {'32': 1, '33': 4}, 'C': {'32': 2, '33': 1}})
        self.assertEqual(row['query_delta_seconds'], {'32': 1, '33': -3})
        self.assertEqual(row['within_arm_gap_seconds'], {'R': -3, 'C': 1})
        self.assertEqual(row['raw_arm_terms_seconds'], {'C': 1, 'R': 3})
        self.assertEqual(row['gap_seconds'], 4)
        alignment = row['alignment']
        self.assertEqual(alignment['leading_support_arms'], ['R'])
        self.assertEqual((alignment['positive_seconds'], alignment['negative_seconds'], alignment['net_seconds']), (4, 0, 4))
        self.assertEqual(alignment['components']['R']['positive_share'], .75)
        self.assertEqual(alignment['components']['C']['positive_share'], .25)

    def test_c_contrast_can_lead_joint_positive_support(self):
        row = compare_absolute_arms(absolute_fixture(1, 2, 4, 1))
        self.assertEqual(row['gap_seconds'], 4)
        alignment = row['alignment']
        self.assertEqual(alignment['leading_support_arms'], ['C'])
        self.assertEqual(alignment['components']['C']['positive_share'], .75)
        self.assertEqual(alignment['components']['R']['positive_share'], .25)

    def test_each_arm_can_offset_the_other_and_shares_use_gross_positive_support(self):
        for timers, leader, offset in ((absolute_fixture(4, 1, 6, 1), 'C', 'R'),
                                      (absolute_fixture(1, 6, 1, 4), 'R', 'C')):
            with self.subTest(leader=leader):
                row = compare_absolute_arms(timers)
                self.assertEqual(row['gap_seconds'], 2)
                alignment = row['alignment']
                self.assertEqual((alignment['positive_seconds'], alignment['negative_seconds'], alignment['net_seconds']), (5, -3, 2))
                self.assertEqual(alignment['components'][leader]['positive_share'], 1)
                self.assertEqual(alignment['components'][offset]['positive_share'], 0)
                self.assertEqual(alignment['components'][offset]['negative_offset'], -3)
                self.assertEqual(alignment['leading_support_arms'], [leader])

    def test_negative_gap_flips_both_arm_terms_before_contribution_accounting(self):
        row = compare_absolute_arms(absolute_fixture(4, 1, 1, 2))
        self.assertEqual(row['gap_seconds'], -4)
        self.assertEqual(row['within_arm_gap_seconds'], {'R': 3, 'C': -1})
        self.assertEqual(row['raw_arm_terms_seconds'], {'C': -1, 'R': -3})
        alignment = row['alignment']
        self.assertTrue(alignment['defined'])
        self.assertEqual(alignment['direction'], -1)
        self.assertEqual(alignment['components']['C']['aligned_net'], 1)
        self.assertEqual(alignment['components']['R']['aligned_net'], 3)
        self.assertEqual(alignment['net_seconds'], 4)

    def test_zero_gap_keeps_nonzero_raw_contrasts_but_has_no_support_shares(self):
        row = compare_absolute_arms(absolute_fixture(5, 2, 9, 6))
        self.assertEqual(row['query_delta_seconds'], {'32': 4, '33': 4})
        self.assertEqual(row['within_arm_gap_seconds'], {'R': 3, 'C': 3})
        self.assertEqual(row['raw_arm_terms_seconds'], {'C': 3, 'R': -3})
        self.assertEqual(row['gap_seconds'], 0)
        alignment = row['alignment']
        self.assertFalse(alignment['defined'])
        self.assertEqual(alignment['direction'], 0)
        self.assertEqual(alignment['leading_support_arms'], [])
        for component in alignment['components'].values():
            self.assertEqual((component['aligned_net'], component['positive_support'], component['negative_offset']), (0, 0, 0))
            self.assertIsNone(component['positive_share'])

    def test_all_largest_positive_ties_are_retained(self):
        alignment = compare_absolute_arms(absolute_fixture(1, 3, 3, 1))['alignment']
        self.assertEqual(alignment['leading_support_arms'], ['C', 'R'])
        self.assertEqual(alignment['components']['C']['positive_share'], .5)
        self.assertEqual(alignment['components']['R']['positive_share'], .5)

    def test_zero_timers_are_valid_and_input_is_not_mutated(self):
        timers = absolute_fixture(0, 0, 0, 0)
        before = deepcopy(timers)
        row = compare_absolute_arms(timers)
        self.assertEqual(timers, before)
        self.assertEqual(row['gap_seconds'], 0)
        self.assertEqual(row['alignment']['positive_seconds'], 0)
        self.assertEqual(row['alignment']['leading_support_arms'], [])
        self.assertEqual(row['max_reconciliation_residual_seconds'], 0)

    def test_arm_total_duration_proportion_is_not_used_as_gap_contribution(self):
        row = compare_absolute_arms(absolute_fixture(1, 4, 1001, 1000))
        self.assertEqual(row['gap_seconds'], 4)
        self.assertEqual(row['alignment']['leading_support_arms'], ['R'])
        self.assertEqual(row['alignment']['components']['C']['positive_share'], .25)
        self.assertNotEqual(row['alignment']['components']['C']['positive_share'], 2001 / 2006)

    def test_missing_extra_and_wrong_arm_or_position_shapes_are_rejected(self):
        for timers in (None, [], {'R': {32: 1, 33: 2}},
                       {**absolute_fixture(), 'D': {32: 0, 33: 0}},
                       {'R': {32: 1}, 'C': {32: 1, 33: 2}},
                       {'R': {32: 1, 33: 2, 38: 3}, 'C': {32: 1, 33: 2}},
                       {'R': {'32': 1, '33': 2}, 'C': {32: 1, 33: 2}},
                       {'R': {32.0: 1, 33: 2}, 'C': {32: 1, 33: 2}},
                       {'R': {True: 1, 33: 2}, 'C': {32: 1, 33: 2}}):
            with self.subTest(timers=timers), self.assertRaises(ValueError):
                compare_absolute_arms(timers)

    def test_nonfinite_negative_nonnumeric_and_boolean_timers_are_rejected(self):
        for value in (True, False, -1, float('nan'), float('inf'), -float('inf'), '1', None, 10**1000):
            timers = absolute_fixture()
            timers['C'][33] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Finite nonnegative'):
                compare_absolute_arms(timers)

    def test_derived_overflow_and_nonconserving_float_routes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Finite numeric'):
            compare_absolute_arms(absolute_fixture(0, 1e308, 1e308, 0))
        with self.assertRaisesRegex(ValueError, 'do not conserve'):
            compare_absolute_arms(absolute_fixture(1e16, 1e16 - 2, 1, 0))


if __name__ == '__main__':
    unittest.main()
