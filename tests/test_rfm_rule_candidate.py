"""Synthetic G2 acceptance: exact cuts, intact ties, support and same-ID replay.

Fixtures build a complete synthetic order ledger through the frozen builder.
No real CSV, model, sensitivity run or individual artifact is used here.
"""
import builtins
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from scripts import rfm_rule_candidate as candidate
from tests.test_rfm_dataset_builder import add_order, build, empty_tables
from tests.test_rfm_description import all_states_dataset, cents_text, evaluation_spec


AXES = ('recency_seconds', 'frequency_orders', 'monetary_product_cents')


def synthetic_dataset(rfm_rows):
    """Return valid full ledgers for explicit (R seconds, F orders, M cents)."""
    tables = empty_tables()
    cutoff = datetime(2018, 9, 1)
    for index, (seconds, frequency, cents) in enumerate(rfm_rows):
        stamp = (cutoff - timedelta(seconds=seconds)).strftime('%Y-%m-%d %H:%M:%S')
        for order in range(frequency):
            add_order(tables, f'o{index:06d}_{order:03d}', f'c{index:06d}', f'u{index:06d}',
                      purchase=stamp, approval=stamp, delivery=stamp,
                      price=cents_text(cents if order == 0 else 0),
                      freight='0.00', payment='0.00')
    return build(tables)


def balanced_dataset(n_per_level=100):
    return synthetic_dataset([(level, level, level * 100)
                              for level in range(1, 6) for _ in range(n_per_level)])


def evaluate(dataset, **kwargs):
    options = {'expected_customer_ids': [r['customer_unique_id'] for r in dataset['customers']],
               'g1_accepted': True}
    options.update(kwargs)
    return candidate.evaluate_rule_candidate(dataset, evaluation_spec(), **options)


class RFMRuleCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.balanced = balanced_dataset()

    def test_balanced_five_levels_passes_support_at_exact_floor(self):
        result = evaluate(self.balanced)
        agg = result['aggregate']
        self.assertEqual(agg['reference_n'], 500)
        self.assertEqual(agg['support_floor'], 100)
        self.assertEqual(agg['failed_checks'], [])
        self.assertEqual(agg['gate_status']['G2'], 'passed')
        for axis in AXES:
            bins = agg['axes'][axis]['bin_counts']
            self.assertEqual(agg['axes'][axis]['effective_levels'], 5)
            self.assertEqual([row['n'] for row in bins], [100] * 5)
            self.assertTrue(all(row['meets_support_floor'] for row in bins))
            self.assertTrue(all(not row['empty'] for row in bins))

    def test_quantile_ranks_use_integer_ceiling_without_interpolation(self):
        result = evaluate(synthetic_dataset([(i, 1, i) for i in range(1, 7)]))
        for axis in ('recency_seconds', 'monetary_product_cents'):
            info = result['aggregate']['axes'][axis]
            self.assertEqual(info['percentages'], [20, 40, 60, 80])
            self.assertEqual(info['quantile_ranks_1based'], [2, 3, 4, 5])
            self.assertEqual(info['raw_cut_values'], [2, 3, 4, 5])
            self.assertEqual(info['cut_values'], [2, 3, 4, 5])

    def test_ties_are_never_split_by_id_or_original_row_position(self):
        dataset = synthetic_dataset([(10, 1, value) for value in [0, 0, 0, 100, 100, 100, 200]])
        result = evaluate(dataset)
        mapping = result['assignments_by_id']
        seen = {}
        for row in dataset['customers']:
            for axis in AXES:
                key = (axis, row[axis])
                assignment = (mapping[row['customer_unique_id']]['numeric_bins'][axis],
                              mapping[row['customer_unique_id']]['ordinals'][axis])
                self.assertEqual(seen.setdefault(key, assignment), assignment)
        info = result['aggregate']['axes']['monetary_product_cents']
        self.assertEqual(info['raw_cut_values'], [0, 0, 100, 100])
        self.assertEqual(info['cut_values'], [0, 100])
        self.assertEqual([b['n'] for b in info['bin_counts']], [3, 3, 1])

    def test_duplicate_cutpoints_removed_min_retained_and_max_removed(self):
        result = evaluate(synthetic_dataset([(i + 1, 1, v) for i, v in enumerate([0, 0, 0, 9, 9])]))
        info = result['aggregate']['axes']['monetary_product_cents']
        self.assertEqual(info['raw_cut_values'], [0, 0, 0, 9])
        self.assertEqual(info['cut_values'], [0])
        self.assertEqual(info['effective_levels'], 2)
        self.assertEqual([b['n'] for b in info['bin_counts']], [3, 2])
        self.assertTrue(all(b['n'] > 0 for b in info['bin_counts']))

    def test_constant_axis_has_one_level_and_makes_candidate_ineligible(self):
        result = evaluate(synthetic_dataset([(i, 1, i) for i in range(1, 6)]))
        info = result['aggregate']['axes']['frequency_orders']
        self.assertEqual(info['raw_cut_values'], [1] * 4)
        self.assertEqual(info['cut_values'], [])
        self.assertEqual(info['effective_levels'], 1)
        self.assertEqual([b['n'] for b in info['bin_counts']], [5])
        self.assertTrue(info['failed_checks'])
        self.assertEqual(result['aggregate']['gate_status']['G2'], 'ineligible')

    def test_collapsed_effective_levels_and_recency_direction_are_actual(self):
        result = evaluate(synthetic_dataset([(r, f, m) for r, f, m in
                                             [(1, 1, 0), (1, 1, 0), (1, 1, 0), (2, 2, 100), (2, 2, 100)]]))
        self.assertTrue(all(info['effective_levels'] == 2 for info in result['aggregate']['axes'].values()))
        mapping = result['assignments_by_id']
        self.assertEqual(mapping['u000000']['ordinal_tuple'], [2, 1, 1])
        self.assertEqual(mapping['u000004']['ordinal_tuple'], [1, 2, 2])
        self.assertEqual(mapping['u000000']['numeric_bins']['recency_seconds'], 1)
        self.assertEqual(mapping['u000004']['numeric_bins']['recency_seconds'], 2)

    def test_values_equal_to_cut_are_in_lower_numeric_bin(self):
        result = evaluate(synthetic_dataset([(i, i, i * 100) for i in range(1, 6)]))
        for index in range(5):
            item = result['assignments_by_id'][f'u{index:06d}']
            self.assertEqual(item['numeric_bins'], dict.fromkeys(AXES, index + 1))
            self.assertEqual(item['ordinal_tuple'], [5 - index, index + 1, index + 1])

    def test_three_and_four_level_axes_use_collapsed_recency_direction(self):
        for levels in (3, 4):
            result = evaluate(synthetic_dataset([(i, i, i * 100) for i in range(1, levels + 1)]))
            with self.subTest(levels=levels):
                for info in result['aggregate']['axes'].values():
                    self.assertEqual(info['effective_levels'], levels)
                    self.assertEqual([b['n'] for b in info['bin_counts']], [1] * levels)
                for index in range(levels):
                    assignment = result['assignments_by_id'][f'u{index:06d}']
                    self.assertEqual(assignment['ordinal_tuple'], [levels - index, index + 1, index + 1])

    def test_large_integer_money_does_not_round_to_binary64(self):
        base = 2**53
        values = [base + i for i in range(1, 7)]
        result = evaluate(synthetic_dataset([(i + 1, 1, value) for i, value in enumerate(values)]))
        info = result['aggregate']['axes']['monetary_product_cents']
        self.assertEqual(info['cut_values'], [base + 2, base + 3, base + 4, base + 5])
        self.assertTrue(all(type(value) is int for value in info['cut_values']))
        self.assertEqual([result['assignments_by_id'][f'u{i:06d}']['numeric_bins']['monetary_product_cents']
                          for i in range(6)], [1, 1, 2, 3, 4, 5])

    def test_each_axis_low_support_fails_without_recutting_or_merging(self):
        dataset = balanced_dataset(n_per_level=99)
        result = evaluate(dataset)
        self.assertEqual(result['aggregate']['gate_status']['G2'], 'ineligible')
        for info in result['aggregate']['axes'].values():
            self.assertEqual(info['effective_levels'], 5)
            self.assertEqual([b['n'] for b in info['bin_counts']], [99] * 5)
            self.assertTrue(all(not b['meets_support_floor'] for b in info['bin_counts']))
            self.assertTrue(info['failed_checks'])
        self.assertEqual(len(result['assignments_by_id']), 495)

    def test_only_one_axis_bin_below_floor_is_not_hidden_by_average_support(self):
        rows = [(1, 1, 0)] * 101 + [(2, 2, 100)] * 99 + [(3, 3, 200)] * 100
        rows += [(4, 4, 300)] * 100 + [(5, 5, 400)] * 100
        result = evaluate(synthetic_dataset(rows))
        self.assertEqual(result['aggregate']['gate_status']['G2'], 'ineligible')
        for info in result['aggregate']['axes'].values():
            self.assertEqual([b['n'] for b in info['bin_counts']], [101, 99, 100, 100, 100])
            self.assertEqual([b['meets_support_floor'] for b in info['bin_counts']],
                             [True, False, True, True, True])

    def test_support_floor_exact_integer_ceiling_at_point_five_percent(self):
        for n, expected in [(0, 100), (499, 100), (20000, 100), (20001, 101),
                            (20200, 101), (20201, 102), (2**53 + 1, ((2**53 + 1) + 199) // 200)]:
            with self.subTest(n=n):
                self.assertEqual(candidate._support_floor(n), expected)

    def test_small_joint_cells_are_flagged_without_failing_axis_g2(self):
        rows = [(r, f, m * 100) for r in range(1, 6) for f in range(1, 6)
                for m in range(5) for _ in range(4)]
        result = evaluate(synthetic_dataset(rows))
        agg = result['aggregate']
        self.assertEqual(agg['gate_status']['G2'], 'passed')
        cells = agg['neutral_joint_cell_counts']
        self.assertEqual(len(cells), 125)
        self.assertEqual(sum(cell['n'] for cell in cells), 500)
        self.assertTrue(all(cell['n'] == 4 for cell in cells))
        self.assertTrue(all(cell['support_flag'] == 'insufficient_group_support' for cell in cells))
        self.assertEqual(agg['gate_status']['G3'], 'not_executed')

    def test_original_reverse_and_pcg64_seed42_have_identical_same_id_assignments(self):
        original = evaluate(self.balanced)
        variants = []
        reverse = copy.deepcopy(self.balanced)
        reverse['customers'].reverse()
        reverse['orders'].reverse()
        variants.append(reverse)
        permuted = copy.deepcopy(self.balanced)
        positions = np.random.Generator(np.random.PCG64(42)).permutation(len(permuted['customers']))
        permuted['customers'] = [permuted['customers'][int(index)] for index in positions]
        variants.append(permuted)
        for data in variants:
            with self.subTest(first_id=data['customers'][0]['customer_unique_id']):
                result = evaluate(data)
                self.assertEqual(result['assignments_by_id'], original['assignments_by_id'])
                self.assertEqual(result['aggregate'], original['aggregate'])
        check = original['aggregate']['reproducibility']
        self.assertEqual(check['status'], 'passed')
        self.assertIs(check['same_ID_assignments_100pct'], True)
        self.assertEqual([v['name'] for v in check['variants']], ['original', 'reversed', 'pcg64_seed42'])

    def test_reproducibility_rejects_changed_cut_even_with_unchanged_bin_counts(self):
        data = synthetic_dataset([(i, i, i * 100) for i in range(1, 6)])
        partition = candidate._partition
        calls = []

        def changed_partition(rows):
            observed = partition(rows)
            calls.append(1)
            if len(calls) == 2:
                observed['axes']['monetary_product_cents']['cut_values'][0] += 1
            return observed

        with patch.object(candidate, '_partition', side_effect=changed_partition), self.assertRaisesRegex(
                ValueError, 'row order'):
            evaluate(data)

    def test_reproducibility_rejects_swapped_ids_despite_identical_group_sizes(self):
        data = synthetic_dataset([(i, i, i * 100) for i in range(1, 6)])
        partition = candidate._partition
        calls = []

        def changed_partition(rows):
            observed = partition(rows)
            calls.append(1)
            if len(calls) == 2:
                mapping = observed['assignments_by_id']
                mapping['u000000'], mapping['u000001'] = mapping['u000001'], mapping['u000000']
            return observed

        with patch.object(candidate, '_partition', side_effect=changed_partition), self.assertRaisesRegex(
                ValueError, 'same-ID'):
            evaluate(data)

    def test_tie_split_is_rejected_even_if_partition_is_consistent_across_orders(self):
        data = synthetic_dataset([(1, 1, 0), (1, 1, 0), (2, 2, 100)])
        partition = candidate._partition

        def split_tie(rows):
            observed = partition(rows)
            item = observed['assignments_by_id']['u000001']
            item['numeric_bins']['monetary_product_cents'] = 2
            item['ordinals']['monetary_product_cents'] = 2
            item['ordinal_tuple'][2] = 2
            return observed

        with patch.object(candidate, '_partition', side_effect=split_tie), self.assertRaisesRegex(
                ValueError, 'ties split'):
            evaluate(data)

    def test_reproducibility_rejects_a_missing_assignment_id(self):
        data = synthetic_dataset([(1, 1, 0), (2, 2, 100)])
        partition = candidate._partition

        def missing_id(rows):
            observed = partition(rows)
            observed['assignments_by_id'].pop('u000000')
            return observed

        with patch.object(candidate, '_partition', side_effect=missing_id), self.assertRaisesRegex(
                ValueError, 'same IDs'):
            evaluate(data)

    def test_only_active_complete_enters_reference_and_masked_rows_are_retained_outside(self):
        data = all_states_dataset()
        result = evaluate(data)
        self.assertEqual(result['aggregate']['reference_n'], 1)
        self.assertEqual(set(result['assignments_by_id']), {'u_complete'})
        self.assertEqual(data['summary']['history']['customer_universe'], 5)
        self.assertEqual(data['summary']['customer_states']['active_money_unknown'], 1)

    def test_legitimate_zero_money_customer_is_never_filtered(self):
        data = synthetic_dataset([(1, 1, 0), (2, 2, 100), (3, 3, 200)])
        result = evaluate(data)
        self.assertEqual(result['aggregate']['reference_n'], 3)
        self.assertIn('u000000', result['assignments_by_id'])
        self.assertEqual(result['assignments_by_id']['u000000']['numeric_bins']['monetary_product_cents'], 1)

    def test_empty_active_reference_skips_partition_and_remains_not_evaluable(self):
        data = build(add_order(empty_tables(), purchase='2017-08-01 00:00:00',
                               approval='2017-08-02 00:00:00', delivery='2017-08-03 00:00:00'))
        with patch.object(candidate, '_partition', side_effect=AssertionError('empty cutpoints forbidden')):
            result = evaluate(data)
        self.assertEqual(result['aggregate']['reference_n'], 0)
        self.assertEqual(result['aggregate']['gate_status']['G2'], 'not_evaluable_empty_reference')
        self.assertEqual(result['assignments_by_id'], {})
        self.assertTrue(all(info is None for info in result['aggregate']['axes'].values()))

    def test_empty_population_is_not_evaluable_instead_of_a_pass(self):
        result = evaluate(build(empty_tables()))
        self.assertEqual(result['aggregate']['reference_n'], 0)
        self.assertEqual(result['aggregate']['gate_status']['G2'], 'not_evaluable_empty_reference')

    def test_g1_acceptance_requires_exact_true_boolean(self):
        data = synthetic_dataset([(1, 1, 0)])
        for value in (False, 1, 'true', None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate(data, g1_accepted=value)

    def test_independent_complete_roster_is_required_and_strict(self):
        data = synthetic_dataset([(1, 1, 0), (2, 2, 100)])
        for ids in (None, [], ['u000000'], ['u000000', 'u000000'],
                    ['u000000', 'u000001', 'extra'], ['u000000', 1], 'u000000'):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                evaluate(data, expected_customer_ids=ids)

    def test_complete_roster_detects_customer_removed_consistently_with_ledger(self):
        reduced = synthetic_dataset([(1, 1, 0)])
        with self.assertRaises(ValueError):
            evaluate(reduced, expected_customer_ids=['u000000', 'u000001'])

    def test_missing_or_duplicate_customer_order_ids_fail_g0(self):
        original = synthetic_dataset([(1, 1, 0), (2, 2, 100)])
        for table in ('customers', 'orders'):
            for operation in ('drop', 'duplicate'):
                data = copy.deepcopy(original)
                if operation == 'drop':
                    data[table].pop()
                else:
                    data[table].append(copy.deepcopy(data[table][0]))
                with self.subTest(table=table, operation=operation), self.assertRaises(ValueError):
                    evaluate(data, expected_customer_ids=['u000000', 'u000001'])

    def test_bad_schema_types_and_rfm_domain_cannot_reach_cut_estimator(self):
        for field, value in [('recency_seconds', 0), ('recency_seconds', 365 * 86400 + 1),
                             ('recency_seconds', True), ('frequency_orders', 1.0),
                             ('monetary_product_cents', None), ('monetary_product_cents', -1),
                             ('monetary_product_cents', float('nan')), ('rfm_usable', 1)]:
            data = synthetic_dataset([(1, 1, 0)])
            data['customers'][0][field] = value
            with self.subTest(field=field, value=value), patch.object(
                    candidate, '_partition', side_effect=AssertionError('cutpoint estimator reached')), self.assertRaises(ValueError):
                evaluate(data)

    def test_mask_and_state_flags_cannot_promote_incomplete_customer(self):
        for field, value in [('activity_state', 'active_complete'), ('rfm_usable', True),
                             ('monetary_complete', True), ('monetary_product_cents', 0)]:
            data = all_states_dataset()
            row = next(r for r in data['customers'] if r['activity_state'] == 'active_money_unknown')
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate(data)

    def test_population_frequency_and_money_conservation_fail_closed(self):
        for group, field in [('history', 'customer_universe'), ('window', 'event_eligible_orders'),
                             ('customer_states', 'active_complete'),
                             ('customer_money_conservation', 'published_customer_product_cents'),
                             ('customer_money_conservation', 'known_product_cents_masked_customer_subsets')]:
            data = all_states_dataset()
            data['summary'][group][field] += 1
            with self.subTest(group=group, field=field), self.assertRaises(ValueError):
                evaluate(data)

    def test_altered_frozen_policy_or_schema_is_rejected(self):
        data = synthetic_dataset([(1, 1, 0)])
        for mutate in (lambda spec: spec.update(format_version=True),
                       lambda spec: spec['policy']['cutpoints'].update(percentages=[25, 50, 75]),
                       lambda spec: spec['policy']['stability'].update(minimum_joint_adjusted_Rand_every_seed=0.5)):
            spec = evaluation_spec()
            mutate(spec)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                candidate.evaluate_rule_candidate(data, spec, expected_customer_ids=['u000000'], g1_accepted=True)

    def test_pure_core_never_opens_files_mutates_sources_or_runs_sensitivity(self):
        data, spec = copy.deepcopy(self.balanced), evaluation_spec()
        before_data, before_spec = copy.deepcopy(data), copy.deepcopy(spec)
        with patch.object(builtins, 'open', side_effect=AssertionError('file I/O forbidden')), patch.object(
                Path, 'open', side_effect=AssertionError('path I/O forbidden')):
            result = candidate.evaluate_rule_candidate(data, spec,
                        expected_customer_ids=[r['customer_unique_id'] for r in data['customers']], g1_accepted=True)
        self.assertEqual(data, before_data)
        self.assertEqual(spec, before_spec)
        self.assertEqual(result['aggregate']['gate_status']['G3'], 'not_executed')
        execution = result['aggregate']['execution']
        self.assertEqual(execution['model_fits'], 0)
        for field in ('source_RFM_modified', 'private_individual_files_written',
                      'clustering_models_executed', 'sensitivity_resampling_executed', 'dashboard'):
            self.assertIs(execution[field], False)
        encoded = json.dumps(result['aggregate'], allow_nan=False)
        for row in data['customers']:
            self.assertNotIn('"' + row['customer_unique_id'] + '"', encoded)
        for row in data['orders']:
            self.assertNotIn('"' + row['order_id'] + '"', encoded)
        self.assertNotIn('VIP', encoded)
        self.assertNotIn('LTV', encoded)
        self.assertNotIn('total_value_score', encoded)


if __name__ == '__main__':
    unittest.main()
