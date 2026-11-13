"""Artificial workload-count tests only; no files, SQL or runner are used."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_workload_distribution_v51 import (
    COUNT_FIELDS, FLAG_FIELD, summarize_workloads,
)


def workload_fixture():
    """Return 48 fresh artificial records with ordinal-valued counters."""
    return [dict({name: ordinal for name in COUNT_FIELDS}, fraction_fallback=False)
            for ordinal in range(1, 49)]


class WorkloadDistributionTests(unittest.TestCase):
    def test_known_ranks_percentiles_and_excluded_target_denominator(self):
        result = summarize_workloads(workload_fixture())
        self.assertEqual((result['count'], result['target_ordinals'], result['other_count']), (48, [32, 38], 46))
        self.assertEqual(len(result['metrics']), 15)
        metric = result['metrics']['history_rows_inserted']
        self.assertEqual(metric['all48'], dict(count=48, min=1, median=24.5, p90=44, max=48, sum=1176, unique_count=48))
        self.assertEqual(metric['excluding_targets46'],
                         dict(count=46, min=1, median=23.5, p90=44, max=48, sum=1106, unique_count=46))
        row32, row38 = metric['targets']['32'], metric['targets']['38']
        self.assertEqual((row32['value'], row32['rank_first'], row32['rank_last']), (32, 17, 17))
        self.assertEqual((row38['value'], row38['rank_first'], row38['rank_last']), (38, 11, 11))
        self.assertEqual(row32['vs_other46'], dict(denominator=46, lower=31, equal=0, higher=15))
        self.assertEqual(row38['vs_other46'], dict(denominator=46, lower=36, equal=0, higher=10))
        self.assertAlmostEqual(row32['ratio_to_all_median'], 32 / 24.5)
        self.assertAlmostEqual(row32['ratio_to_other_median'], 32 / 23.5)
        self.assertIn('nearest_rank', result['percentile_method'])
        self.assertEqual(metric['quantity_kind'], 'logical_count')
        self.assertEqual(result['metrics']['vote_scale_bits']['quantity_kind'], 'bit_width')
        self.assertFalse(result['metrics']['vote_scale_bits']['includes_fallback_sentinel'])

    def test_ties_use_first_and_last_descending_ranks_including_all48(self):
        rows = workload_fixture()
        name = COUNT_FIELDS[0]
        for row in rows:
            row[name] = 0
        for ordinal, value in ((1, 10), (2, 10), (3, 5), (32, 5), (38, 5)):
            rows[ordinal - 1][name] = value
        metric = summarize_workloads(rows)['metrics'][name]
        for ordinal in ('32', '38'):
            row = metric['targets'][ordinal]
            self.assertEqual((row['rank_first'], row['rank_last']), (3, 5))
            self.assertEqual(row['vs_other46'], dict(denominator=46, lower=43, equal=1, higher=2))
            self.assertIsNone(row['ratio_to_all_median'])
            self.assertIsNone(row['ratio_to_other_median'])

    def test_constant_and_zero_counters_have_full_ties_and_defined_zero_denominators(self):
        for constant in (0, 7):
            rows = workload_fixture()
            for row in rows:
                for name in COUNT_FIELDS:
                    row[name] = constant
            result = summarize_workloads(rows)
            for name, metric in result['metrics'].items():
                with self.subTest(constant=constant, name=name):
                    self.assertEqual(metric['all48'], dict(count=48, min=constant, median=constant,
                        p90=constant, max=constant, sum=48 * constant, unique_count=1))
                    self.assertEqual(metric['excluding_targets46']['sum'], 46 * constant)
                    for target in metric['targets'].values():
                        self.assertEqual((target['rank_first'], target['rank_last']), (1, 48))
                        self.assertEqual(target['vs_other46'], dict(denominator=46, lower=0, equal=46, higher=0))
                        self.assertEqual(target['ratio_to_all_median'], 1 if constant else None)
                        self.assertEqual(target['ratio_to_other_median'], 1 if constant else None)

    def test_all_and_other_median_denominators_are_distinct(self):
        rows = workload_fixture()
        name = COUNT_FIELDS[0]
        for index, row in enumerate(rows):
            row[name] = int(index >= 24)
        metric = summarize_workloads(rows)['metrics'][name]
        self.assertEqual(metric['all48']['median'], .5)
        self.assertEqual(metric['excluding_targets46']['median'], 0)
        self.assertEqual(metric['targets']['32']['ratio_to_all_median'], 2)
        self.assertIsNone(metric['targets']['32']['ratio_to_other_median'])

    def test_boolean_field_has_separate_counts_and_no_numeric_ranking(self):
        rows = workload_fixture()
        rows[31][FLAG_FIELD] = True
        rows[6][FLAG_FIELD] = True
        rows[31]['vote_scale_bits'] = rows[6]['vote_scale_bits'] = 0
        result = summarize_workloads(rows)
        self.assertNotIn(FLAG_FIELD, result['metrics'])
        self.assertEqual(result[FLAG_FIELD], dict(all48=dict(count=48, true_count=2, false_count=46),
            excluding_targets46=dict(count=46, true_count=1, false_count=45), targets={'32': True, '38': False}))

    def test_custom_valid_pair_is_one_based_and_excludes_both_targets(self):
        result = summarize_workloads(workload_fixture(), targets=[48, 1])
        metric = result['metrics'][COUNT_FIELDS[0]]
        self.assertEqual(result['target_ordinals'], [48, 1])
        self.assertEqual(metric['targets']['48']['rank_first'], 1)
        self.assertEqual(metric['targets']['1']['rank_last'], 48)
        self.assertEqual(metric['excluding_targets46']['sum'], 1127)
        self.assertEqual(metric['targets']['48']['vs_other46'], dict(denominator=46, lower=46, equal=0, higher=0))

    def test_input_is_unchanged_and_output_contains_only_target_records(self):
        rows = workload_fixture()
        before = deepcopy(rows)
        result = summarize_workloads(iter(rows))
        self.assertEqual(rows, before)
        self.assertNotIn('workloads', result)
        for name, metric in result['metrics'].items():
            expected = {'quantity_kind', 'all48', 'excluding_targets46', 'targets'}
            if name == 'vote_scale_bits':
                expected.add('includes_fallback_sentinel')
            self.assertEqual(set(metric), expected)
            self.assertEqual(set(metric['targets']), {'32', '38'})
            for target in metric['targets'].values():
                self.assertIn(target['ordinal'], (32, 38))
                comparison = target['vs_other46']
                self.assertEqual(comparison['lower'] + comparison['equal'] + comparison['higher'], 46)

    def test_fallback_bit_width_sentinel_keeps_raw_summary_but_disables_target_comparison(self):
        rows = workload_fixture()
        rows[0][FLAG_FIELD] = True
        rows[0]['vote_scale_bits'] = 0
        result = summarize_workloads(rows)
        metric = result['metrics']['vote_scale_bits']
        self.assertEqual(metric['quantity_kind'], 'bit_width')
        self.assertTrue(metric['includes_fallback_sentinel'])
        self.assertEqual(metric['all48']['min'], 0)
        self.assertEqual(metric['all48']['sum'], 1175)
        for ordinal in ('32', '38'):
            target = metric['targets'][ordinal]
            self.assertEqual((target['ordinal'], target['value']), (int(ordinal), int(ordinal)))
            for field in ('rank_first', 'rank_last', 'vs_other46', 'ratio_to_all_median', 'ratio_to_other_median'):
                self.assertIsNone(target[field])
            self.assertIn('sentinel', target['comparison_unavailable_reason'])
        self.assertEqual(result['metrics'][COUNT_FIELDS[0]]['targets']['32']['rank_first'], 17)

    def test_wrong_length_or_row_type_is_rejected(self):
        for count in (0, 47, 49):
            rows = workload_fixture()
            if count == 49:
                rows.append(deepcopy(rows[-1]))
            else:
                rows = rows[:count]
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'Exactly 48'):
                summarize_workloads(rows)
        with self.assertRaisesRegex(ValueError, 'Exactly 48'):
            summarize_workloads(None)
        rows = workload_fixture()
        rows[0] = []
        with self.assertRaisesRegex(ValueError, 'workload schema'):
            summarize_workloads(rows)

    def test_missing_and_extra_fields_are_rejected(self):
        for change in ('missing_count', 'missing_flag', 'extra'):
            rows = workload_fixture()
            if change == 'missing_count':
                rows[0].pop(COUNT_FIELDS[0])
            elif change == 'missing_flag':
                rows[0].pop(FLAG_FIELD)
            else:
                rows[0]['invented_count'] = 1
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'workload schema'):
                summarize_workloads(rows)

    def test_counter_and_boolean_types_are_strict(self):
        for value in (True, False, 0.0, 1.5, -1, float('nan'), float('inf'), '1', None):
            rows = workload_fixture()
            rows[0][COUNT_FIELDS[0]] = value
            with self.subTest(counter=value), self.assertRaisesRegex(ValueError, 'nonnegative integers'):
                summarize_workloads(rows)
        for value in (0, 1, 0.0, 'False', None):
            rows = workload_fixture()
            rows[0][FLAG_FIELD] = value
            with self.subTest(flag=value), self.assertRaisesRegex(ValueError, 'Boolean value'):
                summarize_workloads(rows)

    def test_invalid_target_count_type_range_and_duplicates_are_rejected(self):
        for targets in ((), (32,), (1, 2, 3), (32, 32), (0, 38), (32, 49), (-1, 38),
                        (True, 38), (32.0, 38), ('32', 38), '32,38', None):
            with self.subTest(targets=targets), self.assertRaisesRegex(ValueError, 'Exactly two distinct integer'):
                summarize_workloads(workload_fixture(), targets)


if __name__ == '__main__':
    unittest.main()
