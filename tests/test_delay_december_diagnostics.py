"""Full-batch, availability-mask and paired-count checks for December diagnosis."""
import json
import unittest

import numpy as np
import pandas as pd

from scripts.delay_december_diagnostics import analyze_month


COUNT_KEYS = ('rows', 'positive_rows', 'alerts', 'true_positives', 'false_positives',
              'false_negatives', 'true_negatives')
PAIR_KEYS = ('rows', 'positive_rows', 'recovered_delays', 'lost_delays',
             'added_on_time_alerts', 'removed_on_time_alerts', 'net_TP', 'net_FP')


def cohort(rows=20):
    return pd.DataFrame({
        'order_id': [f'private-order-{i:03d}' for i in range(rows)],
        'prediction_time': pd.Timestamp('2017-11-01') + pd.to_timedelta(np.arange(rows), unit='m'),
        'label_available_time': pd.Timestamp('2017-11-15'),
        'delayed': (np.arange(rows) % 3 == 0).astype(int),
        'state_route': np.where(np.arange(rows) % 2 == 0, 'SP->SP', 'SP->RJ'),
        'customer_state': np.where(np.arange(rows) % 2 == 0, 'SP', 'RJ'),
        'estimated_delivery_days': np.resize([0, 7, 8, 14, 15, 21, 22, 30, 31], rows),
        'route_completed_90d': np.resize([0, 1, 19, 20, 99, 100, np.nan], rows),
        'seller_completed_90d': np.resize([100, 99, 20, 19, 1, 0, np.nan], rows),
        'route_promise_margin_p90_days': np.resize([-1, 0, .1, 7, 7.1, 14, 14.1, np.nan], rows),
    })


def scores(rows=20):
    return {'a': np.linspace(.99, .01, rows),
            'b': np.linspace(.01, .99, rows),
            'c': np.full(rows, .5)}


def overall(report, name):
    return report['models'][name]['known_outcome_diagnostics']['aggregate']['overall']


class DecemberDiagnosticsTests(unittest.TestCase):
    def test_unknown_outcomes_compete_for_capacity_and_ranks_keep_full_denominator(self):
        frame = cohort()
        known = np.arange(20) >= 10
        frame['delayed'] = 0
        frame.loc[10, 'delayed'] = 1
        values = np.linspace(.4, .01, 20)
        values[0], values[1], values[10] = .99, .98, .97
        report = analyze_month(frame, {'a': values, 'b': values.copy()}, known)
        self.assertEqual(report['complete_batch'], {'rows': 20, 'known_rows': 10,
                         'unknown_rows': 10, 'capacity': 2, 'total_days': 1})
        self.assertEqual(overall(report, 'a')['alerts'], 0)
        self.assertEqual(overall(report, 'a')['false_negatives'], 1)
        self.assertEqual(report['models']['a']['unknown_outcome_alerts'], {'rows': 10, 'alerts': 2})
        ranks = {row['daily_rank_bin']: row for row in report['models']['a']
                 ['known_outcome_diagnostics']['aggregate']['daily_rank_bins']}
        self.assertEqual(ranks['<=10%']['rows'], 0)
        self.assertEqual(ranks['10-20%']['false_negatives'], 1)
        # Filtering first would both alert the known delayed order and give
        # it a <=10% rank; the real complete-batch diagnosis does neither.
        subset = analyze_month(frame.loc[known], {'a': values[known], 'b': values[known]}, np.ones(10, bool))
        self.assertEqual(overall(subset, 'a')['true_positives'], 1)

    def test_unknown_labels_and_future_outcome_timestamps_are_never_inspected(self):
        frame = cohort()
        known = np.arange(20) % 2 == 0
        expected = analyze_month(frame, scores(), known)
        corrupt = frame.copy()
        corrupt['delayed'] = corrupt.delayed.astype(object)
        corrupt['label_available_time'] = corrupt.label_available_time.astype(object)
        corrupt.loc[~known, 'delayed'] = 'future label deliberately corrupted'
        corrupt.loc[~known, 'label_available_time'] = 'not available yet'
        self.assertEqual(analyze_month(corrupt, scores(), known), expected)

    def test_all_groupings_partition_counts_and_full_batch_rank_counts(self):
        frame = cohort(70)
        frame.loc[40:, 'prediction_time'] += pd.Timedelta(days=1)
        frame.loc[1, 'state_route'] = None
        frame.loc[2, 'customer_state'] = None
        known = np.arange(70) % 5 != 0
        report = analyze_month(frame, scores(70), known)
        self.assertEqual(report['complete_batch']['capacity'], 7)
        self.assertEqual(report['complete_batch']['total_days'], 2)
        for model in report['models'].values():
            diagnostics = model['known_outcome_diagnostics']
            aggregate = diagnostics['aggregate']
            for rows in [*aggregate['groups'].values(), aggregate['daily_rank_bins']]:
                for key in COUNT_KEYS:
                    self.assertEqual(sum(row[key] for row in rows), aggregate['overall'][key])
                self.assertAlmostEqual(sum(row['share_of_scope_false_negatives'] for row in rows), 1.)
            self.assertEqual(diagnostics['by_month']['2017-11'], aggregate)
        self.assertEqual(len(report['pairwise_comparisons']), 3)
        for pair in report['pairwise_comparisons']:
            for rows in pair['known_outcome']['groups'].values():
                for key in PAIR_KEYS:
                    self.assertEqual(sum(row[key] for row in rows), pair['known_outcome']['overall'][key])
        json.dumps(report, allow_nan=False)

    def test_paired_recovered_lost_and_on_time_changes_reconcile_model_counts(self):
        frame = cohort()
        frame['delayed'] = 0
        frame.loc[[0, 2, 3], 'delayed'] = 1
        values = {}
        for name, selected in (('a', [0, 1]), ('b', [1, 2]), ('c', [2, 3])):
            values[name] = np.full(20, .1)
            values[name][selected] = .9
        report = analyze_month(frame, values, np.ones(20, bool))
        pairs = {(row['model_a'], row['model_b']): row for row in report['pairwise_comparisons']}
        ab = pairs['a', 'b']['known_outcome']['overall']
        self.assertEqual([ab[key] for key in PAIR_KEYS[2:]], [1, 1, 0, 0, 0, 0])
        ac = pairs['a', 'c']['known_outcome']['overall']
        self.assertEqual([ac[key] for key in PAIR_KEYS[2:]], [2, 1, 0, 1, 1, -1])
        for pair in pairs.values():
            a, b = overall(report, pair['model_a']), overall(report, pair['model_b'])
            changes = pair['known_outcome']['overall']
            self.assertEqual(changes['net_TP'], b['true_positives'] - a['true_positives'])
            self.assertEqual(changes['net_FP'], b['false_positives'] - a['false_positives'])
        overlap = report['delayed_overlap']
        self.assertEqual(overlap['delayed_rows'], 3)
        self.assertEqual(overlap['all_models_miss'], 0)
        self.assertEqual(overlap['any_model_caught'], 3)
        self.assertEqual(sum(row['delayed_rows'] for row in overlap['alert_pattern_counts']), 3)
        self.assertEqual(overlap['pairwise'][0], {'model_a': 'a', 'model_b': 'b',
                         'both_missed': 1, 'both_caught': 0, 'only_a_caught': 1, 'only_b_caught': 1})

    def test_unknown_alert_changes_stay_separate_and_reconcile_full_capacity(self):
        frame = cohort()
        known = np.arange(20) >= 10
        a, b = np.full(20, .1), np.full(20, .1)
        a[[0, 1]], b[[1, 10]] = .9, .9
        report = analyze_month(frame, {'a': a, 'b': b}, known)
        pair = report['pairwise_comparisons'][0]
        unknown = pair['unknown_outcome_alerts']
        self.assertEqual(unknown, {'rows': 10, 'added_alerts': 0, 'removed_alerts': 1, 'net_alerts': -1})
        changes = pair['known_outcome']['overall']
        self.assertEqual(changes['net_TP'] + changes['net_FP'] + unknown['net_alerts'], 0)

    def test_fixed_support_boundaries_missing_values_and_promise_boundaries(self):
        frame = cohort(10)
        frame['route_completed_90d'] = [0, 1, 19, 20, 99, 100, 101, np.nan, 0, 20]
        frame['seller_completed_90d'] = frame.route_completed_90d
        frame['route_promise_margin_p90_days'] = [-1, 0, .001, 7, 7.001, 14, 14.001, np.nan, 0, 7]
        groups = analyze_month(frame, scores(10), np.ones(10, bool))['models']['a']
        groups = groups['known_outcome_diagnostics']['aggregate']['groups']
        for name, column in (('route_history_support', 'route_completed_90d_bin'),
                             ('seller_history_support', 'seller_completed_90d_bin')):
            self.assertEqual({row[column]: row['rows'] for row in groups[name]},
                             {'0': 2, '1-19': 2, '20-99': 3, '100+': 2, 'unknown': 1})
        self.assertEqual({row['route_promise_margin_p90_days_bin']: row['rows'] for row in groups['promise_margin']},
                         {'<=0': 3, '(0,7]': 3, '(7,14]': 2, '14+': 1, 'unknown': 1})
        self.assertEqual({row['promise_bin']: row['rows'] for row in groups['promise_days']},
                         {'0-7': 3, '8-14': 2, '15-21': 2, '22-30': 2, '31+': 1})

    def test_support_minimum_sample_requires_both_rows_and_positives(self):
        frame = cohort(89)
        frame['route_completed_90d'] = np.repeat([0, 1, 20], [30, 29, 30])
        frame['delayed'] = 0
        frame.loc[[*range(5), *range(30, 35), *range(59, 63)], 'delayed'] = 1
        groups = analyze_month(frame, scores(89), np.ones(89, bool))['models']['a']
        groups = groups['known_outcome_diagnostics']['aggregate']['groups']['route_history_support']
        self.assertEqual({row['route_completed_90d_bin']: row['minimum_sample_met'] for row in groups},
                         {'0': True, '1-19': False, '20-99': False})

    def test_zero_known_or_positive_rows_produce_safe_null_rates_and_no_private_ids(self):
        frame = cohort()
        frame['delayed'] = 'unknown'
        report = analyze_month(frame, scores(), np.zeros(20, bool))
        self.assertEqual(report['complete_batch']['known_rows'], 0)
        for model in report['models'].values():
            aggregate = model['known_outcome_diagnostics']['aggregate']
            self.assertIsNone(aggregate['overall']['recall'])
            self.assertIsNone(aggregate['overall']['precision'])
            self.assertEqual(aggregate['overall']['rows'], 0)
        self.assertEqual(report['delayed_overlap']['all_models_miss'], 0)
        serialized = json.dumps(report, allow_nan=False)
        self.assertNotIn('private-order-', serialized)
        frame['delayed'] = 0
        report = analyze_month(frame, scores(), np.ones(20, bool))
        self.assertIsNone(overall(report, 'a')['recall'])
        self.assertEqual(overall(report, 'a')['precision'], 0.)

    def test_permutation_duplicate_external_index_and_label_independent_ranks(self):
        frame = cohort()
        frame.index = np.arange(20) % 3
        known = np.arange(20) % 3 != 0
        values = scores()
        expected = analyze_month(frame, values, known)
        order = np.random.default_rng(11).permutation(20)
        actual = analyze_month(frame.iloc[order], {name: value[order] for name, value in values.items()}, known[order])
        self.assertEqual(actual, expected)
        changed = frame.assign(delayed=1 - frame.delayed)
        report = analyze_month(changed, values, known)
        for name in values:
            self.assertEqual(report['models'][name]['unknown_outcome_alerts'], expected['models'][name]['unknown_outcome_alerts'])

    def test_invalid_id_mask_score_model_month_and_known_labels_are_rejected(self):
        frame = cohort()
        for mask in (np.ones(19, bool), [1] * 20, [[True] * 20], [True] * 19 + [None]):
            with self.assertRaises(ValueError):
                analyze_month(frame, scores(), mask)
        for name, invalid in (('order_id', ''), ('order_id', 1), ('order_id', None),
                              ('prediction_time', pd.NaT), ('delayed', 2)):
            bad = frame.copy()
            bad[name] = bad[name].astype(object)
            bad.loc[0, name] = invalid
            with self.assertRaises(ValueError):
                analyze_month(bad, scores(), np.ones(20, bool))
        duplicate = frame.copy()
        duplicate.loc[1, 'order_id'] = duplicate.loc[0, 'order_id']
        with self.assertRaises(ValueError):
            analyze_month(duplicate, scores(), np.ones(20, bool))
        for values in ({'a': [.5] * 20}, {'a': [.5] * 20, '': [.5] * 20},
                       {'a': [.5] * 19, 'b': [.5] * 20},
                       {'a': [.5] * 19 + [np.nan], 'b': [.5] * 20}):
            with self.assertRaises(ValueError):
                analyze_month(frame, values, np.ones(20, bool))
        with self.assertRaises(ValueError):
            analyze_month(frame.drop(columns='label_available_time'), scores(), np.ones(20, bool))
        frame.loc[0, 'prediction_time'] = pd.Timestamp('2017-12-01')
        with self.assertRaises(ValueError):
            analyze_month(frame, scores(), np.ones(20, bool))

    def test_invalid_support_counts_margin_and_promises_cannot_mislabel_groups(self):
        for column, invalid in (('route_completed_90d', -.1), ('seller_completed_90d', .5),
                                ('route_completed_90d', np.inf),
                                ('route_promise_margin_p90_days', np.inf),
                                ('estimated_delivery_days', -1), ('estimated_delivery_days', np.nan)):
            frame = cohort()
            frame[column] = frame[column].astype(float)
            frame.loc[0, column] = invalid
            with self.assertRaises(ValueError):
                analyze_month(frame, scores(), np.ones(20, bool))


if __name__ == '__main__':
    unittest.main()
