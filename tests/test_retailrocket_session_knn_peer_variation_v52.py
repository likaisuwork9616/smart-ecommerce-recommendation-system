"""Hand-calculated numeric fixtures only; no live or saved source is loaded."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_peer_variation_v52 import summarize_peer_variation


class PeerVariationTests(unittest.TestCase):
    def test_six_values_and_unscaled_mad_with_order_subgroups(self):
        values = [-5, -1, 0, 2, 4, 6]
        result = summarize_peer_variation({1: values}, 1, [])
        self.assertEqual(result['pair_orders'], ['CR', 'RC', 'CR', 'RC', 'CR', 'RC'])
        summary = result['target_summary']
        self.assertEqual(summary['values'], values)
        self.assertEqual((summary['count'], summary['sum'], summary['median']), (6, 6, 1))
        self.assertEqual((summary['min'], summary['max'], summary['range'], summary['mad']), (-5, 6, 11, 2.5))
        self.assertEqual((summary['positive_count'], summary['negative_count'], summary['zero_count']), (3, 2, 1))
        cr, rc = summary['by_order']['CR'], summary['by_order']['RC']
        self.assertEqual(cr['values'], [-5, 0, 4])
        self.assertEqual((cr['count'], cr['sum'], cr['median'], cr['range'], cr['mad']), (3, -1, 0, 9, 4))
        self.assertEqual(rc['values'], [-1, 2, 6])
        self.assertEqual((rc['count'], rc['sum'], rc['median'], rc['range'], rc['mad']), (3, 7, 2, 7, 3))
        self.assertNotIn('by_order', cr)

    def test_exact_millisecond_boundaries_are_within(self):
        result = summarize_peer_variation({48: [-.002, -.001, 0, .001, .002, -.0005]}, 48, [])
        summary = result['target_summary']
        self.assertEqual((summary['above_1ms'], summary['below_minus_1ms'], summary['within_1ms']), (1, 1, 4))
        self.assertEqual((summary['positive_count'], summary['negative_count'], summary['zero_count']), (2, 3, 1))
        self.assertEqual(summary['by_order']['CR']['within_1ms'], 1)
        self.assertEqual(summary['by_order']['RC']['within_1ms'], 3)

    def test_direction_denominator_requires_both_deltas_strictly_above_threshold(self):
        result = summarize_peer_variation({1: [.002, -.002, .001, -.001, 0, .003],
            2: [.003, .004, -.005, .006, .007, -.004],
            3: [.001, -.001, .004, -.004, .005, 0]}, 1, [2, 3])
        first, second = result['peer_summaries']
        self.assertEqual(first['position'], 2)
        self.assertEqual(first['direction_vs_target'], dict(eligible_count=3, same_sign_count=1,
                                                          opposite_sign_count=2, ineligible_count=3))
        self.assertEqual(second['direction_vs_target'], dict(eligible_count=0, same_sign_count=0,
                                                           opposite_sign_count=0, ineligible_count=6))

    def test_peer_medians_and_residuals_are_paired_before_summary(self):
        result = summarize_peer_variation({1: [0, 0, 10, 10, 10, 10],
            2: [0, 9, 0, 9, 9, 0], 3: [0, 9, 0, 9, 9, 0],
            4: [30, 30, 30, 30, 30, 30]}, 1, [2, 3, 4])
        peers, relative = result['peer_median_summary'], result['target_minus_peer_median_summary']
        self.assertEqual(peers['values'], [0, 9, 0, 9, 9, 0])
        self.assertEqual(relative['values'], [0, -9, 10, 1, 1, 10])
        self.assertEqual((relative['sum'], relative['median'], relative['mad']), (13, 1, 5))
        self.assertEqual(result['target_summary']['median'] - peers['median'], 5.5)
        self.assertNotEqual(relative['median'], result['target_summary']['median'] - peers['median'])
        self.assertEqual(relative['by_order']['CR']['values'], [0, 10, 1])
        self.assertEqual(relative['by_order']['RC']['values'], [-9, 1, 10])

    def test_even_peer_count_uses_each_pair_midpoint_and_preserves_peer_order(self):
        result = summarize_peer_variation({1: [10] * 6, 2: [0, 2, 4, 6, 8, 10],
                                          3: [2, 4, 6, 8, 10, 12]}, 1, [3, 2])
        self.assertEqual([peer['position'] for peer in result['peer_summaries']], [3, 2])
        self.assertEqual(result['peer_median_summary']['values'], [1, 3, 5, 7, 9, 11])
        self.assertEqual(result['target_minus_peer_median_summary']['values'], [9, 7, 5, 3, 1, -1])

    def test_empty_peers_returns_no_invented_peer_statistics(self):
        result = summarize_peer_variation({1: [0] * 6}, 1, [])
        self.assertEqual(result['peer_summaries'], [])
        self.assertIsNone(result['peer_median_summary'])
        self.assertIsNone(result['target_minus_peer_median_summary'])
        self.assertEqual(result['target_summary']['mad'], 0)
        self.assertEqual(result['target_summary']['zero_count'], 6)

    def test_inputs_and_returned_lists_have_no_shared_mutable_state(self):
        data = {1: [1, 2, 3, 4, 5, 6], 2: [-1, -2, -3, -4, -5, -6]}
        peers = [2]
        before = deepcopy((data, peers))
        result = summarize_peer_variation(data, 1, peers)
        self.assertEqual((data, peers), before)
        result['target_summary']['values'][0] = 100
        result['peer_summaries'][0]['summary']['values'][0] = 100
        self.assertEqual((data, peers), before)
        data[1][1] = 200
        self.assertEqual(result['target_summary']['values'][1], 2)
        self.assertEqual(result['target_summary']['by_order']['CR']['values'][0], 1)

    def test_invalid_keys_target_peer_membership_and_duplicates_are_rejected(self):
        valid = {1: [0] * 6, 2: [0] * 6}
        for target in (True, False, 0, 49, 1.0, '1', None):
            with self.subTest(target=target), self.assertRaises(ValueError):
                summarize_peer_variation(valid, target, [])
        for peer in (True, False, 0, 49, 2.0, '2', None):
            with self.subTest(peer=peer), self.assertRaises(ValueError):
                summarize_peer_variation(valid, 1, [peer])
        for peers in ([1], [2, 2], [3], '2', {2}, None):
            with self.subTest(peers=peers), self.assertRaises(ValueError):
                summarize_peer_variation(valid, 1, peers)
        for key in (True, False, 0, 49, 1.0, '1', None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                summarize_peer_variation({key: [0] * 6, 2: [0] * 6}, 2, [])
        for data in ({}, {2: [0] * 6}, [], None):
            with self.subTest(data=data), self.assertRaises(ValueError):
                summarize_peer_variation(data, 1, [])

    def test_invalid_series_and_unselected_nonfinite_values_are_rejected(self):
        for values in ([], [0] * 5, [0] * 7, '000000', None, {0, 1, 2, 3, 4, 5}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                summarize_peer_variation({1: values}, 1, [])
        for value in (True, False, float('nan'), float('inf'), -float('inf'), '0', None, 10**1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize_peer_variation({1: [0] * 6, 2: [0, 0, value, 0, 0, 0]}, 1, [])

    def test_nonfinite_derived_aggregates_are_rejected(self):
        for values in ([1e308] * 6, [-1e308, 1e308, 0, 0, 0, 0]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                summarize_peer_variation({1: values}, 1, [])


if __name__ == '__main__':
    unittest.main()
