"""Synthetic exact-rank, same-ID routing, precision and leakage acceptance."""
import builtins
import copy
import json
import math
import unittest
from unittest.mock import patch

from scripts import rfm_description as description
from scripts import rfm_evaluation_contract as method
from tests.test_rfm_dataset_builder import add_order, build, empty_tables, fixture


def evaluation_spec():
    return {'format_version': 1, 'policy': method.policy(), 'planned_outputs': method.planned_outputs()}


def cents_text(value):
    return f'{value // 100}.{value % 100:02d}'


def dataset_for_prices(cents_values):
    tables = empty_tables()
    for index, cents in enumerate(cents_values):
        add_order(tables, f'o{index:04d}', f'c{index:04d}', f'u{index:04d}',
                  price=cents_text(cents), freight='0.00', payment='0.00')
    return build(tables)


def all_states_dataset():
    tables = empty_tables()
    add_order(tables, 'complete', 'c_complete', 'u_complete')
    add_order(tables, 'old', 'c_inactive', 'u_inactive', purchase='2017-08-01 00:00:00',
              approval='2017-08-02 00:00:00', delivery='2017-08-03 00:00:00')
    add_order(tables, 'unknown', 'c_unknown', 'u_unknown', price=None)
    add_order(tables, 'quarantine-good', 'c_quarantine', 'u_quarantine')
    add_order(tables, 'quarantine-bad', 'c_quarantine', 'u_quarantine', delivery='', price=None)
    add_order(tables, 'inactive-old', 'c_inactive_q', 'u_inactive_q', purchase='2017-08-01 00:00:00',
              approval='2017-08-02 00:00:00', delivery='2017-08-03 00:00:00')
    add_order(tables, 'inactive-bad', 'c_inactive_q', 'u_inactive_q', delivery='', price=None)
    return build(tables)


def describe(dataset, **kwargs):
    return description.describe_dataset(dataset, evaluation_spec(), **kwargs)


class RFMDescriptionTests(unittest.TestCase):
    def test_five_states_exhaustive_same_id_routing_not_pooled(self):
        dataset = all_states_dataset()
        roster = [row['customer_unique_id'] for row in dataset['customers']]
        result = describe(dataset, expected_customer_ids=roster)
        route = result['routing_counts']
        self.assertEqual(route['population_n'], 5)
        self.assertEqual(set(route['by_state'].values()), {1})
        self.assertEqual(result['eligible_n'], 1)
        self.assertEqual(route['complete_active_n'], 1)
        self.assertEqual(route['clean_inactive_n'], 1)
        self.assertEqual(route['withheld_n'], 3)
        self.assertTrue(route['same_ID_exhaustive_disjoint'])
        self.assertTrue(route['independent_roster_checked'])
        raw = result['statistics_and_null_reasons']['raw']
        self.assertEqual(raw['frequency_orders']['sum'], 1)
        self.assertEqual(raw['monetary_product_cents']['sum'], 1000)
        self.assertEqual(route['null_counts_by_state']['active_money_unknown']['monetary_product_cents'], 1)
        self.assertEqual(route['null_counts_by_state']['inactive_with_quarantine']['recency_seconds'], 1)

    def test_readonly_no_input_or_spec_mutation_and_no_file_io(self):
        dataset, spec = all_states_dataset(), evaluation_spec()
        before_dataset, before_spec = copy.deepcopy(dataset), copy.deepcopy(spec)
        with patch.object(builtins, 'open', side_effect=AssertionError('file I/O forbidden')):
            result = description.describe_dataset(dataset, spec)
        self.assertEqual(dataset, before_dataset)
        self.assertEqual(spec, before_spec)
        self.assertFalse(result['execution']['source_RFM_modified'])

    def test_row_permutations_produce_identical_aggregate_values(self):
        dataset = all_states_dataset()
        reordered = copy.deepcopy(dataset)
        reordered['customers'].reverse()
        reordered['orders'].reverse()
        self.assertTrue(description.artifacts._same(describe(dataset), describe(reordered)))

    def test_no_ids_rows_scores_cutpoints_or_partitions_in_output(self):
        dataset = all_states_dataset()
        result = describe(dataset)
        encoded = json.dumps(result, allow_nan=False)
        for row in dataset['customers']:
            self.assertNotIn('"' + row['customer_unique_id'] + '"', encoded)
        for row in dataset['orders']:
            self.assertNotIn('"' + row['order_id'] + '"', encoded)
        self.assertNotIn('20', result['statistics_and_null_reasons']['raw']['recency_seconds']['empirical_quantiles'])
        self.assertEqual(result['gate_status']['G2'], 'not_executed')
        self.assertEqual(result['gate_status']['G3'], 'not_executed')
        self.assertEqual(result['execution']['model_fits'], 0)
        self.assertTrue(all(result['execution'][key] is False for key in result['execution'] if key != 'model_fits'))

    def test_policy_or_planned_output_change_rejected_before_description(self):
        for mutate in (lambda s: s.update(format_version=True),
                       lambda s: s['policy']['description'].update(quantile_rule='linear'),
                       lambda s: s['planned_outputs'].update(public_outputs='IDs allowed')):
            spec = evaluation_spec()
            mutate(spec)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                description.describe_dataset(build(fixture()), spec)

    def test_missing_or_duplicate_expected_ids_fail(self):
        dataset = dataset_for_prices([100, 200])
        for roster in (['u0000'], ['u0000', 'u0000'], ['u0000', 'u0001', 'extra'],
                       ['u0000', 1], 'u0000'):
            with self.subTest(roster=roster), self.assertRaises(ValueError):
                describe(dataset, expected_customer_ids=roster)

    def test_independent_roster_detects_consistently_removed_customer(self):
        original = dataset_for_prices([100, 200])
        reduced = dataset_for_prices([100])
        roster = [row['customer_unique_id'] for row in original['customers']]
        with self.assertRaisesRegex(ValueError, 'expected roster'):
            describe(reduced, expected_customer_ids=roster)

    def test_ledger_detects_dropped_customer_or_order_and_duplicate_ids(self):
        original = dataset_for_prices([100, 200])
        for table, operation in (('customers', 'drop'), ('orders', 'drop'),
                                 ('customers', 'duplicate'), ('orders', 'duplicate')):
            data = copy.deepcopy(original)
            if operation == 'drop':
                data[table].pop()
            else:
                data[table].append(copy.deepcopy(data[table][0]))
            with self.subTest(table=table, operation=operation), self.assertRaises(ValueError):
                describe(data)

    def test_strict_schema_types_nulls_and_nonfinite_rejected(self):
        for field, value in (('frequency_orders', True), ('monetary_product_cents', 1.0),
                             ('monetary_product_cents', None), ('recency_days', float('nan')),
                             ('recency_seconds', -1), ('last_window_purchase_at', 'invalid'),
                             ('rfm_usable', 1), ('S', None)):
            data = build(fixture())
            data['customers'][0][field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                describe(data)

    def test_extra_or_missing_columns_rejected(self):
        for operation in ('extra', 'missing'):
            data = build(fixture())
            if operation == 'extra':
                data['customers'][0]['score'] = 5
            else:
                del data['customers'][0]['monetary_complete']
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                describe(data)

    def test_state_and_unknown_mask_forgery_rejected(self):
        for field, value in (('activity_state', 'active_complete'), ('monetary_product_cents', 0),
                             ('rfm_usable', True), ('monetary_complete', True)):
            data = all_states_dataset()
            row = next(r for r in data['customers'] if r['activity_state'] == 'active_money_unknown')
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                describe(data)

    def test_summary_population_frequency_and_money_forgery_rejected(self):
        for group, key in (('history', 'customer_universe'), ('window', 'event_eligible_orders'),
                           ('customer_states', 'active_complete'),
                           ('customer_money_conservation', 'published_customer_product_cents'),
                           ('customer_money_conservation', 'known_product_cents_masked_customer_subsets')):
            data = all_states_dataset()
            data['summary'][group][key] += 1
            with self.subTest(group=group, key=key), self.assertRaises(ValueError):
                describe(data)

    def test_extra_state_summary_cannot_be_ignored(self):
        data = build(fixture())
        data['summary']['customer_states']['extra_state'] = 0
        with self.assertRaises(ValueError):
            describe(data)

    def test_exact_descriptive_rank_with_ties_not_linear_interpolation(self):
        result = describe(dataset_for_prices([1, 1, 2, 9, 9]))
        stat = result['statistics_and_null_reasons']['raw']['monetary_product_cents']
        self.assertEqual(stat['empirical_quantiles'], {'0': 1, '1': 1, '5': 1, '25': 1,
                         '50': 2, '75': 9, '95': 9, '99': 9, '100': 9})
        self.assertEqual(stat['sum'], 22)
        self.assertEqual((stat['mean_numerator'], stat['mean_denominator']), (22, 5))
        self.assertEqual(stat['arithmetic_mean'], 22 / 5)
        self.assertEqual(stat['IQR'], 8)
        self.assertEqual(stat['Bowley_skewness'], 0.75)

    def test_integer_ranks_at_small_and_exact_percent_boundaries(self):
        q = description._quantiles(list(range(1, 101)))
        self.assertEqual(q, {str(p): max(1, p) for p in description.PERCENTAGES})
        q = description._quantiles([1, 1, 1, 10])
        self.assertEqual(q['75'], 1)
        self.assertEqual(q['95'], 10)

    def test_large_integer_money_above_binary64_precision_preserved(self):
        values = [2**53 + 1, 2**53 + 2, 2**53 + 3]
        result = describe(dataset_for_prices(values))
        stat = result['statistics_and_null_reasons']['raw']['monetary_product_cents']
        self.assertEqual(stat['min'], values[0])
        self.assertEqual(stat['max'], values[-1])
        self.assertEqual(stat['empirical_quantiles']['50'], values[1])
        self.assertEqual(stat['sum'], sum(values))
        for key in ('min', 'max', 'sum', 'mean_numerator', 'mean_denominator'):
            self.assertIs(type(stat[key]), int)
        self.assertTrue(all(type(v) is int for v in stat['empirical_quantiles'].values()))
        self.assertEqual(stat['mean_numerator'], 3 * (2**53 + 2))

    def test_one_second_recency_remains_exact_not_rounded_day(self):
        tables = add_order(empty_tables(), purchase='2018-08-31 23:59:59',
                           approval='2018-08-31 23:59:59', delivery='2018-08-31 23:59:59')
        result = describe(build(tables))
        self.assertEqual(result['statistics_and_null_reasons']['raw']['recency_seconds']['min'], 1)
        self.assertEqual(result['statistics_and_null_reasons']['log1p_views']['recency_seconds']['min'], math.log1p(1 / 86400))

    def test_IQR_zero_has_null_skew_fences_and_counts_not_zero(self):
        result = describe(dataset_for_prices([100, 100, 100]))
        stat = result['statistics_and_null_reasons']['raw']['monetary_product_cents']
        self.assertEqual(stat['IQR'], 0)
        self.assertIsNone(stat['Bowley_skewness'])
        out = result['outlier_flags_not_removed']['monetary_product_cents']
        for key in ('lower_fence_numerator', 'upper_fence_numerator', 'fence_denominator',
                    'lower_flag_count', 'upper_flag_count', 'flag_count'):
            self.assertIsNone(out[key])
        self.assertEqual(out['removed_n'], 0)

    def test_exact_half_fence_does_not_round(self):
        values = [0, 1, 1, 2, 2, 2, 3, 4]
        result = describe(dataset_for_prices(values))
        out = result['outlier_flags_not_removed']['monetary_product_cents']
        self.assertEqual(out['upper_fence_numerator'], 7)
        self.assertEqual(out['fence_denominator'], 2)
        self.assertEqual(out['upper_flag_count'], 1)
        self.assertEqual(out['removed_n'], 0)
        self.assertEqual(result['eligible_n'], 8)

    def test_values_equal_to_fence_are_not_flagged(self):
        result = describe(dataset_for_prices([1, 1, 1, 2, 3, 3, 6, 7]))
        out = result['outlier_flags_not_removed']['monetary_product_cents']
        self.assertEqual(out['upper_fence_numerator'], 12)
        self.assertEqual(out['upper_flag_count'], 1)

    def test_q99_tail_includes_all_ties_and_reports_actual_fraction(self):
        result = describe(dataset_for_prices([1, 1, 2, 9, 9]))
        tail = result['shape_and_tail_diagnostics']['M_ge_Q99']
        self.assertEqual(tail['threshold_cents'], 9)
        self.assertEqual(tail['count'], 2)
        self.assertEqual(tail['fraction']['value'], 2 / 5)
        self.assertEqual(tail['share_of_total_M']['value'], 18 / 22)
        self.assertTrue(tail['includes_all_threshold_ties'])

    def test_legitimate_zero_money_active_customers_not_dropped(self):
        result = describe(dataset_for_prices([0, 0, 0]))
        self.assertEqual(result['eligible_n'], 3)
        raw = result['statistics_and_null_reasons']['raw']['monetary_product_cents']
        self.assertEqual(raw['sum'], 0)
        self.assertEqual(raw['arithmetic_mean'], 0.0)
        self.assertEqual(result['shape_and_tail_diagnostics']['M_equals_0']['value'], 1.0)
        tail = result['shape_and_tail_diagnostics']['M_ge_Q99']
        self.assertEqual(tail['count'], 3)
        self.assertIsNone(tail['share_of_total_M']['value'])
        self.assertEqual(tail['share_of_total_M']['null_reason'], 'zero_total_M')
        self.assertEqual(result['statistics_and_null_reasons']['log1p_views']['monetary_product_cents']['min'], 0.0)

    def test_empty_reference_all_other_statistics_null_and_no_cuts(self):
        tables = add_order(empty_tables(), purchase='2017-08-01 00:00:00',
                           approval='2017-08-02 00:00:00', delivery='2017-08-03 00:00:00')
        result = describe(build(tables))
        self.assertEqual(result['routing_counts']['population_n'], 1)
        self.assertEqual(result['eligible_n'], 0)
        for family in ('raw', 'log1p_views'):
            for stat in result['statistics_and_null_reasons'][family].values():
                self.assertEqual(stat['n'], 0)
                self.assertEqual(stat['null_reason'], 'empty_reference')
                self.assertTrue(all(v is None for k, v in stat.items() if k not in ('n', 'null_reason')))
        self.assertEqual(result['gate_status']['G1'], 'not_evaluable_empty_reference')

    def test_empty_dataset_remains_explicit_empty_population(self):
        result = describe(build(empty_tables()))
        self.assertEqual(result['routing_counts']['population_n'], 0)
        self.assertEqual(result['population_and_money_conservation']['state_sum'], 0)
        self.assertEqual(result['eligible_n'], 0)

    def test_log_views_have_only_frozen_summary_fields_and_units(self):
        result = describe(dataset_for_prices([0, 100, 900]))
        logs = result['statistics_and_null_reasons']['log1p_views']
        expected = [math.log1p(v) for v in (0, 1, 9)]
        stat = logs['monetary_product_cents']
        self.assertEqual(stat['arithmetic_mean'], math.fsum(expected) / 3)
        self.assertEqual(stat['max'], math.log1p(9))
        self.assertEqual(set(stat), {'n', 'null_count', 'min', 'max', 'arithmetic_mean',
                                     'empirical_quantiles', 'null_reason'})
        self.assertTrue(all(math.isfinite(v) for v in stat['empirical_quantiles'].values()))

    def test_partial_masked_money_stays_out_of_numeric_sum_but_conserves(self):
        result = describe(all_states_dataset())
        aggregate = result['population_and_money_conservation']
        money = aggregate['money']
        self.assertEqual(aggregate['complete_active_product_cents'], 1000)
        self.assertEqual(money['known_product_cents_masked_customer_subsets'], 1000)
        self.assertEqual(money['eligible_window_product_cents_on_known_orders'], 2000)
        self.assertTrue(money['known_product_cents_equal_published_plus_masked_known'])
        self.assertEqual(aggregate['frequency_sum_all_customers'], 3)
        self.assertEqual(aggregate['window_event_eligible_orders'], 3)


if __name__ == '__main__':
    unittest.main()
