"""Frozen three-way captures retain full-day competition and denominators."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from scripts.delay_route_exchanges import COUNT_FIELDS
from scripts.diagnose_budget_misses import PROMISE_BINS, RANK_BINS
from scripts.diagnose_handover_common_misses import (
    ANALYSIS, BASELINE, COMMON_COUNT_FIELDS, COMPARISONS, COUNT102, GAP_BINS,
    HANDOVER104, MATCHED, PATTERNS, PATTERN_COUNT_FIELDS,
    build_report, common_miss_diagnostics, diagnose_phase, pair_diagnostics,
    pool_development, reconcile_previous, validate_output,
)
from scripts import diagnose_handover_count as count
from tests.test_diagnose_handover_count import example


class CommonMissDiagnosisTests(unittest.TestCase):
    def test_explicit_pattern_order_and_known_outcome_partition(self):
        frame, scores, known = example()
        result = common_miss_diagnostics(frame, scores, known)
        patterns = {row['pattern']: row for row in result['capture_patterns']}
        self.assertEqual(tuple(patterns), PATTERNS)
        self.assertEqual(MATCHED, (BASELINE, COUNT102, HANDOVER104))
        # Delays 2,4,8 are respectively caught by 101+102,102+104,102.
        self.assertEqual(patterns['110']['known_delayed_rows'], 1)
        self.assertEqual(patterns['011']['known_delayed_rows'], 1)
        self.assertEqual(patterns['010']['known_delayed_rows'], 1)
        summary = result['common_misses']['summary']
        self.assertEqual(summary['known_delayed_rows'], 3)
        self.assertEqual(summary['common_missed_delays'], 0)
        for key in PATTERN_COUNT_FIELDS:
            self.assertEqual(sum(row[key] for row in patterns.values()), summary[key])

    def test_common_misses_are_only_known_delayed_000(self):
        frame, scores, known = example()
        frame.loc[[10, 11], 'delayed'] = 1
        known[11] = False
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[11, 'delayed'] = 'not known'
        result = common_miss_diagnostics(frame, scores, known)
        zero = result['capture_patterns'][0]
        self.assertEqual(zero['known_delayed_rows'], 1)
        self.assertEqual(zero['unknown_rows'], 1)
        self.assertEqual(result['common_misses']['summary']['common_missed_delays'], 1)
        self.assertGreater(zero['known_on_time_rows'], 0)

    def test_unknown_high_score_competes_before_masks(self):
        frame, scores, known = example(rows=10)
        scores = {c: np.linspace(.9, .1, 10) for c in MATCHED}
        frame['delayed'] = 0
        frame.loc[1, 'delayed'] = 1
        known[0] = False
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[0, 'delayed'] = object()
        result = common_miss_diagnostics(frame, scores, known)
        self.assertEqual(result['capture_patterns'][-1]['unknown_rows'], 1)
        self.assertEqual(result['common_misses']['summary']['common_missed_delays'], 1)
        for model in result['common_misses']['rank_details'].values():
            self.assertEqual(model['full_day_positions']['minimum'], 2)
            self.assertEqual(model['capacity_gap_slots']['minimum'], 1)
            self.assertEqual(model['rank_bins']['10-20%'], 1)

    def test_subgroups_use_full_day_ranking_without_fresh_cap(self):
        frame, scores, known = example()
        frame[count.ADDED_FEATURES[0]] = 5
        frame[count.ADDED_FEATURES[1]] = 24.
        frame[count.ADDED_FEATURES[2]] = 48.
        frame.loc[[0, 2, 4, 8], count.ADDED_FEATURES] = [1, np.nan, np.nan]
        result = common_miss_diagnostics(frame, scores, known)
        sparse = result['common_misses']['support_bins'][1]
        self.assertEqual(sparse['full_batch_rows'], 4)
        self.assertEqual(sparse['models'][COUNT102]['alerts'], 4)
        self.assertNotIn('capacity', sparse)

    def test_common_marginals_partition_all_counts_and_model_denominators(self):
        frame, scores, known = example()
        frame.loc[10, 'delayed'] = 1
        result = common_miss_diagnostics(frame, scores, known, focus=True)['common_misses']
        for dimension in ('routes', 'promise_days', 'support_bins', 'volume_bins'):
            for field in COMMON_COUNT_FIELDS:
                self.assertEqual(sum(row[field] for row in result[dimension]), result['summary'][field])
            for c in MATCHED:
                for field in ('true_positives', 'false_negatives', 'alerts'):
                    self.assertEqual(sum(row['models'][c][field] for row in result[dimension]), result['summary']['models'][c][field])

    def test_declared_empty_patterns_bins_and_rank_intervals_remain(self):
        frame, scores, known = example()
        frame[count.ADDED_FEATURES[0]] = 0
        frame[count.ADDED_FEATURES[1:]] = np.nan
        result = common_miss_diagnostics(frame, scores, known)
        self.assertEqual(len(result['capture_patterns']), 8)
        common = result['common_misses']
        self.assertEqual([row['promise_bin'] for row in common['promise_days']], list(PROMISE_BINS))
        self.assertEqual(len(common['support_bins']), 3)
        self.assertEqual(len(common['volume_bins']), 4)
        self.assertEqual(common['support_bins'][1]['full_batch_rows'], 0)
        self.assertIsNone(common['support_bins'][1]['common_missed_share_of_known_delays'])
        self.assertEqual(list(common['rank_details'][BASELINE]['rank_bins']), list(RANK_BINS))
        self.assertIsNone(common['rank_details'][BASELINE]['full_day_positions']['minimum'])

    def test_ties_follow_id_and_external_index_has_no_effect(self):
        frame, scores, known = example(rows=10)
        scores = {c: np.full(10, .5) for c in MATCHED}
        frame['delayed'] = 0
        ordered = np.argsort(frame.order_id.to_numpy())
        frame.iloc[ordered[1], frame.columns.get_loc('delayed')] = 1
        frame.index = np.arange(100, 110)
        result = common_miss_diagnostics(frame, scores, known)
        self.assertEqual(result['common_misses']['rank_details'][COUNT102]['full_day_positions']['minimum'], 2)

    def test_zero_daily_capacity_misses_even_highest_scored_delay(self):
        frame, scores, known = example(rows=10)
        frame = frame.iloc[:9].copy()
        scores = {c: scores[c][:9] for c in MATCHED}
        known = known[:9]
        result = common_miss_diagnostics(frame, scores, known)
        self.assertEqual(result['common_misses']['summary']['common_missed_delays'], 3)
        self.assertEqual(sum(result['capture_patterns'][0][key] for key in ('known_delayed_rows','known_on_time_rows','unknown_rows')), 9)
        self.assertEqual(result['common_misses']['summary']['models'][BASELINE]['alerts'], 0)

    def test_closest_rank_is_independent_hindsight_minimum_and_partitions(self):
        frame, scores, known = example(rows=40)
        frame.loc[[10, 20, 30], 'delayed'] = 1
        result = common_miss_diagnostics(frame, scores, known, focus=True)['common_misses']
        self.assertEqual(result['summary']['common_missed_delays'], 3)
        views = result['closest_rank_views']
        for dimension in ('relative_rank_bins', 'capacity_gap_bins'):
            self.assertEqual(sum(row['common_missed_delays'] for row in views[dimension]), 3)
            for row in views[dimension]:
                for marginal in ('routes', 'promise_days', 'support_bins', 'volume_bins'):
                    self.assertEqual(sum(part['common_missed_delays'] for part in row[marginal]), row['common_missed_delays'])
        self.assertEqual([row['gap_bin'] for row in views['capacity_gap_bins']], list(GAP_BINS))
        self.assertNotIn('recall', views)

    def test_rankings_and_captures_are_not_modified_by_label_change(self):
        frame, scores, known = example()
        original = common_miss_diagnostics(frame, scores, known)
        changed = frame.copy()
        changed.delayed = 1 - changed.delayed
        after = common_miss_diagnostics(changed, scores, known)
        self.assertEqual([row['full_batch_rows'] for row in original['capture_patterns']],
                         [row['full_batch_rows'] for row in after['capture_patterns']])

    def test_all_three_pairwise_exchanges_conserve_full_day_budget(self):
        frame, scores, known = example()
        result = diagnose_phase(frame, scores, known)
        self.assertEqual(set(result['comparisons']), set(COMPARISONS))
        for pair in result['comparisons'].values():
            self.assertEqual(pair['summary']['old_alerts'], 4)
            self.assertEqual(pair['summary']['new_alerts'], 4)
            for dimension in ('routes', 'days', 'promise_days', 'support_bins', 'volume_bins'):
                for field in COUNT_FIELDS:
                    self.assertEqual(sum(row[field] for row in pair[dimension]), pair['summary'][field])
            self.assertEqual({row['cohort'] for row in pair['rank_movements']['cohorts']}, {'lost_delays','recovered_delays'})
            for row in pair['rank_movements']['cohorts']:
                self.assertEqual(row['rows'], pair['summary'][row['cohort']])

    def test_previous_summary_routes_and_days_reconcile_and_reject_changes(self):
        frame, scores, known = example()
        result = diagnose_phase(frame, scores, known)
        previous = count.diagnose_phase(frame, scores, known)
        reconcile_previous(result, previous)
        tampered = deepcopy(previous)
        tampered['comparisons']['baseline101_to_count102']['routes'][0]['net_TP'] += 1
        with self.assertRaises(ValueError):
            reconcile_previous(result, tampered)

    def test_swapping_old_new_pair_reverses_losses_and_gains(self):
        frame, scores, known = example()
        first = pair_diagnostics(frame, scores, known, BASELINE, COUNT102)['summary']
        second = pair_diagnostics(frame, scores, known, COUNT102, BASELINE)['summary']
        self.assertEqual(first['recovered_delays'], second['lost_delays'])
        self.assertEqual(first['lost_delays'], second['recovered_delays'])
        self.assertEqual(first['net_TP'], -second['net_TP'])

    def test_missing_candidate_unknown_mask_and_invalid_scores_rejected(self):
        frame, scores, known = example()
        for invalid in ({BASELINE: scores[BASELINE]}, {**scores, COUNT102: np.full(len(frame), np.nan)}):
            with self.assertRaises(ValueError):
                common_miss_diagnostics(frame, invalid, known)
        with self.assertRaises(ValueError):
            common_miss_diagnostics(frame, scores, known.astype(int))
        with self.assertRaises(ValueError):
            pair_diagnostics(frame, scores, known, BASELINE, BASELINE)

    def test_development_pool_excludes_repeated_history(self):
        frame, scores, known = example()
        row = diagnose_phase(frame, scores, known)
        phases = {month: {**deepcopy(row), 'ledger_role':'evaluation', 'month':month} for month in ('2017-12','2018-02','2018-04')}
        phases['historical_repeat'] = {**deepcopy(row), 'ledger_role':'validation', 'month':'2017-07'}
        pooled = pool_development(phases)
        self.assertEqual(len(pooled['phase_keys']), 3)
        self.assertNotIn('historical_repeat', pooled['phase_keys'])
        self.assertEqual(pooled['summary']['full_batch_rows'], len(frame)*3)
        self.assertEqual(pooled['summary']['known_delayed_rows'], 9)
        self.assertTrue(pooled['historical_phases_excluded'])
        phases['2018-04']['month'] = '2018-02'
        with self.assertRaises(ValueError):
            pool_development(phases)

    def test_source_hash_guard_fails_before_reading_private_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source, diag = Path(directory)/'source.json', Path(directory)/'diag.json'
            source.write_text('{}', encoding='utf-8')
            diag.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'exact published'):
                build_report(source, Path(directory)/'absent', diag)

    def test_output_refuses_other_reports_and_non_json(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'source.json', Path(directory)/'output.json'
            source.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_output(source, source)
            with self.assertRaises(ValueError):
                validate_output(output.with_suffix('.csv'), source)
            output.write_text('{"analysis":"another"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_output(output, source)
            output.write_text(json.dumps({'analysis':ANALYSIS,'format_version':1}), encoding='utf-8')
            self.assertEqual(validate_output(output, source), output.resolve())


if __name__ == '__main__':
    unittest.main()
