"""Conservation and complete-batch semantics of route alert exchanges."""
import json
import unittest

import numpy as np
import pandas as pd

from scripts.delay_route_exchanges import (
    COUNT_FIELDS, analyze_route_exchanges,
)


def cohort(rows=40):
    return pd.DataFrame({
        'order_id': [f'private-order-{i:03d}' for i in range(rows)],
        'prediction_time': pd.Timestamp('2017-07-01') + pd.to_timedelta(np.arange(rows), unit='m'),
        'state_route': np.resize(['SP->SP', 'SP->RJ'], rows),
        'delayed': (np.arange(rows) % 3 == 0).astype(int),
    })


def selected_scores(rows, selected):
    values = np.full(rows, .1)
    values[selected] = .9
    return values


def by_cohort(report, name):
    return next(row for row in report['rank_movements']['cohorts'] if row['cohort'] == name)


class RouteExchangeTests(unittest.TestCase):
    def test_known_outcome_changes_reconcile_complete_capacity(self):
        frame = cohort()
        frame['delayed'] = 0
        frame.loc[[0, 4, 8], 'delayed'] = 1
        old, new = selected_scores(40, [0, 1, 2, 3]), selected_scores(40, [2, 3, 4, 5])
        report = analyze_route_exchanges(frame, old, new, np.ones(40, bool))
        summary = report['summary']
        self.assertEqual([summary[key] for key in ('old_alerts', 'new_alerts', 'stable_alerts',
                         'dropped_alerts', 'added_alerts')], [4, 4, 2, 2, 2])
        self.assertEqual([summary[key] for key in ('recovered_delays', 'lost_delays',
                         'added_on_time_alerts', 'removed_on_time_alerts', 'net_TP', 'net_FP')],
                         [1, 1, 1, 1, 0, 0])
        self.assertEqual(summary['old_recall'], 1 / 3)
        self.assertEqual(summary['new_recall'], 1 / 3)
        self.assertEqual(report['allocation_summary']['within_route_exchanges'], 2)
        self.assertEqual(report['allocation_summary']['cross_route_slots'], 0)

    def test_unknown_orders_compete_before_mask_and_never_become_fp(self):
        frame = cohort(20)
        frame['delayed'] = 0
        frame.loc[10, 'delayed'] = 1
        known = np.arange(20) >= 10
        old = selected_scores(20, [0, 1])
        new = selected_scores(20, [1, 10])
        report = analyze_route_exchanges(frame, old, new, known)
        summary = report['summary']
        self.assertEqual(summary['full_batch_rows'], 20)
        self.assertEqual(summary['old_known_alerts'], 0)
        self.assertEqual(summary['new_known_alerts'], 1)
        self.assertEqual(summary['old_unknown_alerts'], 2)
        self.assertEqual(summary['new_unknown_alerts'], 1)
        self.assertEqual(summary['recovered_delays'], 1)
        self.assertEqual(summary['unknown_removed_alerts'], 1)
        self.assertEqual(summary['removed_on_time_alerts'], 0)
        self.assertEqual(summary['net_TP'] + summary['net_FP'] + summary['net_unknown_alerts'], 0)
        corrupted = frame.copy()
        corrupted['delayed'] = corrupted.delayed.astype(object)
        corrupted.loc[~known, 'delayed'] = 'future outcome must not be read'
        self.assertEqual(analyze_route_exchanges(corrupted, old, new, known), report)

    def test_cross_route_counts_are_daily_marginals_without_order_pairs(self):
        frame = cohort()
        frame['state_route'] = 'SP->SP'
        frame.loc[[5, 6, 7], 'state_route'] = 'SP->RJ'
        old = selected_scores(40, [0, 1, 2, 3])
        new = selected_scores(40, [3, 4, 5, 6])
        report = analyze_route_exchanges(frame, old, new, np.ones(40, bool))
        allocation = report['allocation_summary']
        self.assertEqual(allocation['within_route_exchanges'], 1)
        self.assertEqual(allocation['cross_route_slots'], 2)
        self.assertEqual(allocation['monthly_net_recipient_slots'], 2)
        route_rows = {row['state_route']: row for row in report['routes']}
        self.assertEqual(route_rows['SP->SP']['net_alerts'], -2)
        self.assertEqual(route_rows['SP->SP']['cross_route_outgoing_slots'], 2)
        self.assertEqual(route_rows['SP->RJ']['cross_route_incoming_slots'], 2)
        serialized = json.dumps(report, allow_nan=False)
        self.assertNotIn('private-order-', serialized)
        self.assertNotIn('order_pairs', serialized)
        self.assertTrue(all(report['conservation'].values()))

    def test_daily_gross_route_flows_can_cancel_in_monthly_net(self):
        frame = cohort(40)
        frame.loc[20:, 'prediction_time'] += pd.Timedelta(days=1)
        frame['state_route'] = np.resize(['SP->SP', 'SP->RJ'], 40)
        old = selected_scores(40, [0, 2, 21, 23])
        new = selected_scores(40, [1, 3, 20, 22])
        report = analyze_route_exchanges(frame, old, new, np.ones(40, bool))
        self.assertEqual(report['allocation_summary']['cross_route_slots'], 4)
        self.assertEqual(report['allocation_summary']['monthly_net_recipient_slots'], 0)
        self.assertEqual(report['allocation_summary']['monthly_net_donor_slots'], 0)
        for route in report['routes']:
            self.assertEqual(route['cross_route_outgoing_slots'], 2)
            self.assertEqual(route['cross_route_incoming_slots'], 2)
            self.assertEqual(route['net_alerts'], 0)
        self.assertEqual([day['cross_route_slots'] for day in report['days']], [2, 2])

    def test_routes_days_and_route_days_partition_every_count(self):
        frame = cohort(73)
        frame.loc[20:49, 'prediction_time'] += pd.Timedelta(days=1)
        frame.loc[50:, 'prediction_time'] += pd.Timedelta(days=2)
        frame.loc[0, 'state_route'] = None
        old, new = np.linspace(.99, .01, 73), np.linspace(.01, .99, 73)
        known = np.arange(73) % 5 != 0
        report = analyze_route_exchanges(frame, old, new, known)
        for groups in ('routes', 'days', 'route_day_allocations'):
            for field in COUNT_FIELDS:
                self.assertEqual(sum(row[field] for row in report[groups]), report['summary'][field])
        self.assertEqual(report['allocation_summary']['capacity'], 2 + 3 + 2)
        self.assertIn('unknown', [row['state_route'] for row in report['routes']])
        self.assertEqual(sum(row['rows'] for row in report['rank_movements']['cohorts']), 73)
        json.dumps(report, allow_nan=False)

    def test_rank_movement_uses_complete_batch_with_unknown_competitors(self):
        frame = cohort(20)
        frame['delayed'] = 0
        frame.loc[10, 'delayed'] = 1
        known = np.arange(20) >= 10
        old = np.linspace(.4, .01, 20)
        old[[0, 1, 10]] = [.99, .98, .97]
        new = old.copy()
        new[10] = 1
        report = analyze_route_exchanges(frame, old, new, known)
        recovered = by_cohort(report, 'recovered_delays')
        self.assertEqual(recovered['rows'], 1)
        self.assertEqual(recovered['old_rank_bins']['10-20%'], 1)
        self.assertEqual(recovered['new_rank_bins']['<=10%'], 1)
        transitions = [row for row in recovered['rank_bin_transitions'] if row['rows']]
        self.assertEqual(transitions, [{'old_rank_bin': '10-20%', 'new_rank_bin': '<=10%', 'rows': 1}])

    def test_score_ties_use_id_and_output_is_permutation_invariant(self):
        frame = cohort(20)
        frame.index = np.arange(20) % 3
        known = np.arange(20) % 3 != 0
        values = np.full(20, .5)
        expected = analyze_route_exchanges(frame, values, values, known)
        self.assertEqual(expected['summary']['old_alerts'], 2)
        self.assertEqual(expected['summary']['dropped_alerts'], 0)
        self.assertEqual(expected['summary']['old_unknown_alerts'], 1)
        order = np.random.default_rng(33).permutation(20)
        actual = analyze_route_exchanges(frame.iloc[order], values[order], values[order], known[order])
        self.assertEqual(actual, expected)

    def test_zero_daily_capacity_keeps_every_route_and_known_delay(self):
        frame = cohort(9)
        values = np.linspace(.9, .1, 9)
        report = analyze_route_exchanges(frame, values, values[::-1], np.ones(9, bool))
        self.assertEqual(report['allocation_summary']['capacity'], 0)
        self.assertEqual(report['summary']['old_alerts'], 0)
        self.assertEqual(report['summary']['old_false_negatives'], 3)
        self.assertEqual(report['summary']['old_recall'], 0)
        self.assertEqual(len(report['routes']), 2)
        self.assertEqual(report['allocation_summary']['cross_route_slots'], 0)

    def test_zero_known_or_positive_rows_have_null_recall(self):
        frame = cohort()
        values = np.linspace(.9, .1, 40)
        frame['delayed'] = 'unavailable'
        report = analyze_route_exchanges(frame, values, values[::-1], np.zeros(40, bool))
        self.assertIsNone(report['summary']['old_recall'])
        self.assertIsNone(report['summary']['new_recall'])
        self.assertIsNone(report['summary']['old_precision'])
        self.assertEqual(report['summary']['old_unknown_alerts'], 4)
        frame['delayed'] = 0
        report = analyze_route_exchanges(frame, values, values[::-1], np.ones(40, bool))
        self.assertIsNone(report['summary']['old_recall'])
        self.assertEqual(report['summary']['old_precision'], 0)
        json.dumps(report, allow_nan=False)

    def test_minimum_sample_requires_both_known_rows_and_delayed_rows(self):
        frame = cohort(89)
        frame['state_route'] = np.repeat(['a', 'b', 'c'], [30, 29, 30])
        frame['delayed'] = 0
        frame.loc[[*range(5), *range(30, 35), *range(59, 63)], 'delayed'] = 1
        values = np.full(89, .5)
        report = analyze_route_exchanges(frame, values, values, np.ones(89, bool))
        self.assertEqual({row['state_route']: row['minimum_sample_met'] for row in report['routes']},
                         {'a': True, 'b': False, 'c': False})

    def test_general_cap_is_accounted_using_shared_policy(self):
        frame = cohort(30)
        values = np.linspace(.99, .01, 30)
        report = analyze_route_exchanges(frame, values, values[::-1], np.ones(30, bool), cap=.3)
        self.assertEqual(report['allocation_summary']['capacity'], 9)
        self.assertEqual(report['summary']['old_alerts'], 9)
        self.assertEqual(report['summary']['new_alerts'], 9)

    def test_invalid_inputs_are_rejected(self):
        frame = cohort(20)
        values = np.full(20, .5)
        for mask in (np.ones(19, bool), np.ones(20, int), [[True] * 20]):
            with self.assertRaises(ValueError):
                analyze_route_exchanges(frame, values, values, mask)
        for field, value in (('order_id', ''), ('order_id', 1), ('prediction_time', pd.NaT),
                             ('prediction_time', pd.Timestamp('2017-07-01', tz='UTC')),
                             ('delayed', 2), ('state_route', ''), ('state_route', 42)):
            bad = frame.copy()
            bad[field] = bad[field].astype(object)
            bad.loc[0, field] = value
            with self.assertRaises(ValueError):
                analyze_route_exchanges(bad, values, values, np.ones(20, bool))
        duplicate = frame.copy()
        duplicate.loc[1, 'order_id'] = duplicate.loc[0, 'order_id']
        with self.assertRaises(ValueError):
            analyze_route_exchanges(duplicate, values, values, np.ones(20, bool))
        for cap in (-.1, 1.1, np.nan, None, True):
            with self.assertRaises(ValueError):
                analyze_route_exchanges(frame, values, values, np.ones(20, bool), cap=cap)
        for bad in (values[:-1], np.full(20, np.nan), np.full(20, 1.1)):
            with self.assertRaises(ValueError):
                analyze_route_exchanges(frame, bad, values, np.ones(20, bool))


if __name__ == '__main__':
    unittest.main()
