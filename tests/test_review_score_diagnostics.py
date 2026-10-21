"""Synthetic, model-free checks for bounded frozen-score descriptive arithmetic."""
import json
import unittest

import numpy as np
import pandas as pd

from scripts import review_score_diagnostics as diagnostic


def block(labels=(1, 0, None), prefix='query'):
    return pd.DataFrame({
        'order_id': [f'{prefix}-{index}' for index in range(len(labels))],
        'role_label_usable': [value is not None for value in labels],
        'label_state': ['no_visible_answer_at_cutoff' if value is None else
                        'known_low_1_2' if value == 1 else 'known_other_3_5' for value in labels],
        'y': pd.Series(labels, dtype='Int64'),
    })


def scores(truth, values):
    return pd.Series(values, index=truth.order_id.tolist(), dtype='float64')


def features(ids, months=None, waits=None):
    ids = list(ids)
    return pd.DataFrame({'purchase_month': [1] * len(ids) if months is None else months,
                         'purchase_dayofweek': [0] * len(ids),
                         'purchase_hour': [0] * len(ids),
                         'approval_wait_hours': [0] * len(ids) if waits is None else waits},
                        index=pd.Index(ids, name='order_id')).astype('float64')


class ProtocolAndLabelTests(unittest.TestCase):
    def test_protocol_is_fresh_json_safe_and_has_no_training(self):
        protocol = diagnostic.diagnostic_protocol()
        json.dumps(protocol, allow_nan=False)
        self.assertEqual(protocol['fit_calls'], 0)
        self.assertEqual(protocol['prediction_calls'], 0)
        self.assertEqual(protocol['quantile_method'], 'linear')
        self.assertEqual(protocol['standard_deviation_ddof'], 0)
        self.assertEqual(protocol['categorical_vocabulary']['purchase_month'], list(range(1, 13)))
        protocol['categorical_vocabulary']['purchase_month'].clear()
        self.assertEqual(len(diagnostic.diagnostic_protocol()['categorical_vocabulary']['purchase_month']), 12)

    def test_unknown_does_not_enter_low_rate(self):
        result = diagnostic.role_summary(block((1, 0, None, None)))
        self.assertEqual(result['full_orders'], 4)
        self.assertEqual(result['known_labels'], 2)
        self.assertEqual(result['known_low_rate'], .5)
        self.assertEqual(result['unknown_or_ineligible_rate'], .5)
        self.assertEqual(sum(result['exclusive_label_states'].values()), 4)

    def test_role_metadata_keeps_own_cutoff_and_clock_range(self):
        truth = block()
        truth['outer_fold'] = '2018-04'
        truth['role'] = 'outer_train_pool'
        truth['fit_at'] = pd.Timestamp('2018-04-01')
        truth['observation_cutoff'] = pd.Timestamp('2018-04-01')
        truth['prediction_time'] = pd.to_datetime(['2018-01-01', '2018-02-01', '2018-03-01'])
        truth['window_deadline'] = truth.prediction_time + pd.Timedelta(days=60)
        truth['horizon_complete'] = [True, False, False]
        result = diagnostic.role_summary(truth)
        self.assertEqual(result['metadata']['fit_at'], '2018-04-01 00:00:00')
        self.assertEqual(result['metadata']['prediction_time_minimum'], '2018-01-01 00:00:00')
        self.assertEqual(result['metadata']['prediction_time_maximum'], '2018-03-01 00:00:00')
        self.assertEqual(result['metadata']['horizon_incomplete_orders'], 2)

    def test_mixed_role_metadata_is_rejected(self):
        truth = block()
        truth['role'] = ['inner_validation', 'outer_evaluation', 'outer_evaluation']
        with self.assertRaises(ValueError):
            diagnostic.role_summary(truth)

    def test_empty_role_uses_null_rates(self):
        result = diagnostic.role_summary(block(()))
        self.assertEqual(result['full_orders'], 0)
        self.assertIsNone(result['known_low_rate'])
        self.assertIsNone(result['unknown_or_ineligible_rate'])
        json.dumps(result, allow_nan=False)

    def test_label_inconsistencies_fail_closed(self):
        mutations = [
            ('role_label_usable', 0, 'True'), ('role_label_usable', 0, False),
            ('label_state', 0, 'unexpected'), ('label_state', 0, 'known_other_3_5'),
            ('y', 0, None), ('y', 0, 2), ('y', 0, True), ('y', 0, '1'), ('y', 2, 0),
        ]
        for column, row, value in mutations:
            with self.subTest(column=column, row=row, value=value):
                truth = block().astype({'role_label_usable': object, 'y': object})
                truth.loc[row, column] = value
                with self.assertRaises(ValueError):
                    diagnostic.role_summary(truth)

    def test_invalid_roster_identifiers_fail(self):
        for value in ('', None, 'query-0', 1):
            with self.subTest(value=value):
                truth = block().astype({'order_id': object})
                truth.loc[1, 'order_id'] = value
                with self.assertRaises(ValueError):
                    diagnostic.role_summary(truth)

    def test_unknown_reasons_stay_exclusive(self):
        truth = block((None, None, None))
        truth['label_state'] = ['immature_observation_window', 'late_answer_unknown', 'no_visible_answer_at_cutoff']
        result = diagnostic.role_summary(truth)
        self.assertEqual(result['exclusive_label_states']['immature_observation_window'], 1)
        self.assertEqual(result['unknown_or_ineligible_labels'], 3)
        self.assertIsNone(result['known_low_rate'])


class ClockAndSupportTests(unittest.TestCase):
    def test_clock_derivation_uses_purchase_clock_and_original_wait(self):
        raw = pd.DataFrame({'order_id': ['b', 'a', 'outside'],
                            'order_purchase_timestamp': ['2018-01-01 00:00:00', '2017-12-31 23:30:00', 'bad'],
                            'order_approved_at': ['2018-01-01 00:00:00', '2018-01-02 01:30:00', 'bad'],
                            'post_approval_field': ['ignored'] * 3})
        original = raw.copy(deep=True)
        result = diagnostic.derive_clock_features(raw, ['a', 'b'])
        self.assertEqual(result.index.tolist(), ['a', 'b'])
        self.assertEqual(result.loc['a'].tolist(), [12, 6, 23, 26])
        self.assertEqual(result.loc['b'].tolist(), [1, 0, 0, 0])
        pd.testing.assert_frame_equal(raw, original)

    def test_clock_derivation_rejects_selected_bad_clocks_and_missing_ids(self):
        raw = pd.DataFrame({'order_id': ['a'], 'order_purchase_timestamp': ['2018-01-02 00:00:00'],
                            'order_approved_at': ['2018-01-01 00:00:00']})
        with self.assertRaises(ValueError):
            diagnostic.derive_clock_features(raw, ['a'])
        with self.assertRaises(ValueError):
            diagnostic.derive_clock_features(raw, ['absent'])
        raw.loc[0, 'order_approved_at'] = 'bad'
        with self.assertRaises(ValueError):
            diagnostic.derive_clock_features(raw, ['a'])

    def test_clock_derivation_rejects_timezone_aware_clocks(self):
        raw = pd.DataFrame({'order_id': ['a'],
                            'order_purchase_timestamp': pd.to_datetime(['2018-01-01'], utc=True),
                            'order_approved_at': pd.to_datetime(['2018-01-02'], utc=True)})
        with self.assertRaises(ValueError):
            diagnostic.derive_clock_features(raw, ['a'])

    def test_categorical_counts_tv_and_boundary_support(self):
        train = features([f'train-{i}' for i in range(59)], [1] * 30 + [2] * 29)
        truth = block((1, 0, None))
        query = features(truth.order_id, [1, 2, 3])
        result = diagnostic.compare_feature_support(train, query, truth)
        monthly = result['categorical']['purchase_month']
        self.assertEqual(len(monthly['training_categories']), 12)
        self.assertEqual(monthly['training_categories'][0]['training_orders'], 30)
        full = monthly['query_subsets']['full']
        self.assertEqual(full['counts'], [1, 1, 1] + [0] * 9)
        self.assertAlmostEqual(full['total_variation_from_training'], 1/3)
        self.assertEqual(full['zero_training_support']['orders'], 1)
        self.assertEqual(full['sparse_positive_training_support']['orders'], 1)
        self.assertEqual(full['below_30_training_support_including_zero']['orders'], 2)
        self.assertEqual(monthly['query_subsets']['known']['zero_training_support']['orders'], 0)
        self.assertEqual(monthly['query_subsets']['unknown']['zero_training_support']['fraction'], 1)

    def test_support_uses_only_supplied_eligible_training_reference(self):
        truth = block((1, None))
        query = features(truth.order_id, [1, 12], [1, 1000])
        result = diagnostic.compare_feature_support(features(['eligible'], [1], [1]), query, truth)
        self.assertEqual(result['eligible_training_orders'], 1)
        self.assertEqual(result['categorical']['purchase_month']['query_subsets']['unknown']['zero_training_support']['orders'], 1)
        self.assertEqual(result['approval_wait_hours']['query_subsets']['unknown']['above_training_maximum']['orders'], 1)

    def test_wait_bins_include_zero_and_exact_boundaries_once(self):
        waits = [0, 1, 6, 24, 72, 168, 169]
        truth = block((1, 0, None, 1, 0, None, 1))
        train = features([f'train-{i}' for i in range(7)], waits=waits)
        query = features(truth.order_id, waits=waits)
        result = diagnostic.compare_feature_support(train, query, truth)['approval_wait_hours']
        self.assertEqual([item['orders'] for item in result['training_bins']], [1, 1, 1, 1, 1, 2])
        self.assertEqual(result['query_subsets']['full']['bin_counts'], [1, 1, 1, 1, 1, 2])
        self.assertIsNone(result['training_bins'][-1]['upper'])
        self.assertTrue(result['training_bins'][-1]['upper_unbounded'])
        self.assertFalse(result['training_bins'][-1]['upper_inclusive'])
        json.dumps(result, allow_nan=False)

    def test_wait_quantiles_linear_and_population_standard_deviation(self):
        truth = block((1, 0))
        result = diagnostic.compare_feature_support(features(['a', 'b'], waits=[0, 10]),
                                                     features(truth.order_id, waits=[0, 10]), truth)
        stats = result['approval_wait_hours']['training_distribution']
        self.assertEqual(stats['mean'], 5)
        self.assertEqual(stats['standard_deviation'], 5)
        self.assertEqual(stats['quantiles']['0.25'], 2.5)
        self.assertEqual(stats['quantiles']['0.99'], 9.9)

    def test_wait_range_and_p99_comparisons_are_strict(self):
        truth = block((1, 0, None, 1, 0))
        result = diagnostic.compare_feature_support(features(['a', 'b'], waits=[1, 101]),
                                                     features(truth.order_id, waits=[0, 1, 100, 101, 102]), truth)
        full = result['approval_wait_hours']['query_subsets']['full']
        self.assertEqual(full['below_training_minimum']['orders'], 1)
        self.assertEqual(full['above_training_maximum']['orders'], 1)
        self.assertEqual(full['outside_training_range']['orders'], 2)
        self.assertEqual(full['above_training_p99']['orders'], 2)

    def test_empty_query_subset_retains_vocabulary_and_null_tv(self):
        truth = block((1, 0))
        result = diagnostic.compare_feature_support(features(['train']), features(truth.order_id), truth)
        unknown = result['categorical']['purchase_hour']['query_subsets']['unknown']
        self.assertEqual(unknown['counts'], [0] * 24)
        self.assertEqual(unknown['proportions'], [None] * 24)
        self.assertIsNone(unknown['total_variation_from_training'])
        self.assertIsNone(unknown['zero_training_support']['fraction'])
        wait = result['approval_wait_hours']['query_subsets']['unknown']
        self.assertEqual(wait['distribution']['orders'], 0)
        self.assertIsNone(wait['distribution']['mean'])
        self.assertEqual(wait['above_training_p99']['orders'], 0)
        self.assertIsNone(wait['above_training_p99']['fraction'])

    def test_empty_training_reference_yields_null_tv_and_range(self):
        truth = block()
        result = diagnostic.compare_feature_support(features([]), features(truth.order_id), truth)
        self.assertIsNone(result['categorical']['purchase_month']['query_subsets']['full']['total_variation_from_training'])
        self.assertIsNone(result['approval_wait_hours']['query_subsets']['full']['outside_training_range']['orders'])

    def test_support_rejects_reordered_queries_and_invalid_feature_values(self):
        truth = block()
        train = features(['train'])
        with self.assertRaises(ValueError):
            diagnostic.compare_feature_support(train, features(reversed(truth.order_id)), truth)
        for name, value in [('purchase_month', 0), ('purchase_month', 1.5), ('purchase_dayofweek', 7),
                            ('purchase_hour', 24), ('approval_wait_hours', -1), ('approval_wait_hours', np.nan)]:
            with self.subTest(name=name, value=value):
                query = features(truth.order_id)
                query.loc[truth.order_id.iloc[0], name] = value
                with self.assertRaises(ValueError):
                    diagnostic.compare_feature_support(train, query, truth)

    def test_feature_column_order_or_extra_columns_are_rejected(self):
        truth = block()
        train = features(['train'])
        query = features(truth.order_id)
        with self.assertRaises(ValueError):
            diagnostic.compare_feature_support(train, query.loc[:, list(reversed(diagnostic.FEATURES))], truth)
        query['future_label'] = 1
        with self.assertRaises(ValueError):
            diagnostic.compare_feature_support(train, query, truth)


class ScoreDistributionTests(unittest.TestCase):
    def test_full_known_unknown_distributions_and_bias_have_correct_denominators(self):
        truth = block((1, 0, None))
        result = diagnostic.score_profile(scores(truth, [.1, .3, .9]), truth)
        self.assertAlmostEqual(result['distributions']['full']['mean'], 1.3/3)
        self.assertAlmostEqual(result['distributions']['known']['mean'], .2)
        self.assertEqual(result['distributions']['unknown']['mean'], .9)
        self.assertAlmostEqual(result['known_probability_bias'], -.3)
        self.assertEqual(result['distributions']['low']['orders'], 1)
        self.assertEqual(result['distributions']['low']['standard_deviation'], 0)

    def test_score_bins_cover_each_endpoint_exactly_once(self):
        truth = block((1, 0, None, 1, 0, None, 1, 0))
        result = diagnostic.score_profile(scores(truth, diagnostic.SCORE_EDGES), truth)
        bins = result['score_bins']
        self.assertEqual([item['full_orders'] for item in bins], [1, 1, 1, 1, 1, 1, 2])
        self.assertEqual(sum(item['known_labels'] for item in bins), 6)
        self.assertEqual(sum(item['unknown_or_ineligible_labels'] for item in bins), 2)
        self.assertTrue(bins[-1]['upper_inclusive'])
        self.assertEqual(bins[-1]['upper'], 1)
        self.assertIsNone(bins[2]['known_low_rate'])
        self.assertEqual(bins[2]['full_probability_mean'], .1)

    def test_all_unknown_and_empty_groups_remain_null(self):
        truth = block((None, None))
        result = diagnostic.score_profile(scores(truth, [.1, .2]), truth)
        self.assertIsNone(result['known_probability_bias'])
        self.assertIsNone(result['distributions']['known']['mean'])
        self.assertEqual(result['distributions']['low']['quantiles'], {f'{q:g}': None for q in diagnostic.QUANTILES})
        self.assertIsNone(result['score_bins'][0]['full_probability_mean'])
        json.dumps(result, allow_nan=False)

    def test_score_distribution_quantiles_use_linear_interpolation(self):
        truth = block((1, 0))
        result = diagnostic.score_profile(scores(truth, [0, 1]), truth)['distributions']['full']
        self.assertEqual(result['quantiles']['0.25'], .25)
        self.assertEqual(result['quantiles']['0.99'], .99)
        self.assertEqual(result['standard_deviation'], .5)

    def test_invalid_probability_vectors_fail_closed(self):
        truth = block()
        for values in ([.1, .2, np.nan], [.1, np.inf, .3], [-.1, .2, .3], [.1, .2, 1.1]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    diagnostic.score_profile(scores(truth, values), truth)
        with self.assertRaises(ValueError):
            diagnostic.score_profile(pd.Series(['0.1', '0.2', '0.3'], index=truth.order_id), truth)
        with self.assertRaises(ValueError):
            diagnostic.score_profile(scores(truth, [.1, .2, .3]).iloc[::-1], truth)

    def test_diagnostics_leave_all_input_frames_unchanged(self):
        truth = block()
        probability = scores(truth, [.1, .2, .3])
        query = features(truth.order_id)
        train = features(['train'])
        originals = [item.copy(deep=True) for item in (truth, probability, query, train)]
        diagnostic.role_summary(truth)
        diagnostic.score_profile(probability, truth)
        diagnostic.compare_feature_support(train, query, truth)
        diagnostic.paired_loss_profile(probability, probability, truth)
        for actual, expected in zip((truth, probability, query, train), originals):
            if isinstance(actual, pd.DataFrame):
                pd.testing.assert_frame_equal(actual, expected)
            else:
                pd.testing.assert_series_equal(actual, expected)


class PairedLossTests(unittest.TestCase):
    def test_same_selected_bins_and_global_known_denominator(self):
        truth = block((1, 0, 1, None))
        selected = scores(truth, [.01, .2, .7, 1])
        reference = scores(truth, [.2, .2, .2, .2])
        result = diagnostic.paired_loss_profile(selected, reference, truth)
        self.assertEqual(result['contribution_denominator_known_labels'], 3)
        self.assertEqual([item['known_labels'] for item in result['score_bins']], [1, 0, 0, 0, 1, 0, 1])
        first = result['score_bins'][0]['losses']['brier']
        self.assertAlmostEqual(first['selected_contribution'], .9801/3)
        self.assertAlmostEqual(first['reference_contribution'], .64/3)
        self.assertAlmostEqual(result['totals_reconciled_to_existing_losses']['brier']['selected'], (0.9801+.04+.09)/3)

    def test_bin_contributions_sum_to_existing_known_only_losses(self):
        truth = block((1, 0, 1, 0, None))
        selected = scores(truth, [0, 1, .3, .05, .99])
        reference = scores(truth, [.2] * 5)
        result = diagnostic.paired_loss_profile(selected, reference, truth)
        for metric, total in result['totals_reconciled_to_existing_losses'].items():
            self.assertAlmostEqual(sum(item['losses'][metric]['selected_contribution'] for item in result['score_bins']), total['selected'])
            self.assertAlmostEqual(sum(item['losses'][metric]['reference_contribution'] for item in result['score_bins']), total['reference'])
            self.assertAlmostEqual(sum(item['losses'][metric]['selected_minus_reference_contribution'] for item in result['score_bins']), total['selected_minus_reference'])
        json.dumps(result, allow_nan=False)

    def test_reference_endpoint_clipping_is_log_only(self):
        truth = block((1, 0))
        result = diagnostic.paired_loss_profile(scores(truth, [0, 1]), scores(truth, [1, 0]), truth)
        totals = result['totals_reconciled_to_existing_losses']
        self.assertEqual(totals['brier']['selected'], 1)
        self.assertEqual(totals['brier']['reference'], 0)
        self.assertTrue(np.isfinite(totals['binary_log_loss']['selected']))
        expected = (-np.log(1e-15)-np.log(1-(1-1e-15)))/2
        self.assertEqual(totals['binary_log_loss']['selected'], expected)

    def test_unknown_probabilities_do_not_change_loss(self):
        truth = block((1, 0, None))
        first = diagnostic.paired_loss_profile(scores(truth, [.1, .2, 0]), scores(truth, [.3, .3, 1]), truth)
        second = diagnostic.paired_loss_profile(scores(truth, [.1, .2, 1]), scores(truth, [.3, .3, 0]), truth)
        self.assertEqual(first, second)

    def test_empty_bins_contribute_zero_but_unknown_role_is_null(self):
        truth = block((1, 0))
        result = diagnostic.paired_loss_profile(scores(truth, [.1, .1]), scores(truth, [.2, .2]), truth)
        self.assertEqual(result['score_bins'][0]['losses']['brier']['selected_contribution'], 0)
        truth = block((None, None))
        result = diagnostic.paired_loss_profile(scores(truth, [.1, .1]), scores(truth, [.2, .2]), truth)
        self.assertIsNone(result['score_bins'][0]['losses']['brier']['selected_contribution'])
        self.assertIsNone(result['totals_reconciled_to_existing_losses']['brier']['selected'])

    def test_paired_loss_cannot_relabel_inner_candidates_as_outer(self):
        truth = block()
        truth['role'] = 'inner_validation'
        with self.assertRaises(ValueError):
            diagnostic.paired_loss_profile(scores(truth, [.1, .2, .3]), scores(truth, [.2, .2, .2]), truth)


if __name__ == '__main__':
    unittest.main()
