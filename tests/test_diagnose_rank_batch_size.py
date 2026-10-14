"""Daily volume diagnostics preserve complete batches and outcome availability."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.diagnose_rank_batch_size import (
    ANALYSIS, build_report, counts, daily_alignment, diagnose_phase, validate_output, volume_bin,
)
from scripts.diagnose_rank_focus import BASELINES, MATCHED, NEW
from scripts.delay_rank_query_alignment import summarize_queries


def batches(sizes):
    frames = []
    offset = 0
    for day, size in enumerate(sizes):
        frames.append(pd.DataFrame({
            'order_id': [f'order_{value:05d}' for value in range(offset, offset + size)],
            'prediction_time': pd.Timestamp('2017-07-01') + pd.Timedelta(days=day),
            'state_route': np.resize(['SP->SP', 'SP->RJ'], size),
            'estimated_delivery_days': np.resize([7., 14., 21., 30., 31.], size),
            'delayed': np.zeros(size, int),
        }))
        offset += size
    return pd.concat(frames, ignore_index=True)


class DailyVolumeUnitTests(unittest.TestCase):
    def test_fixed_size_boundaries(self):
        expected = {1: '1-99', 99: '1-99', 100: '100-199', 199: '100-199',
                    200: '200-399', 399: '200-399', 400: '400+', 900: '400+'}
        for size, label in expected.items():
            with self.subTest(size=size):
                self.assertEqual(volume_bin(size), label)
        for invalid in (0, -1, True, 1.5, '100', None):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError)):
                volume_bin(invalid)

    def test_native_k_and_capacity_boundary_counts(self):
        sizes = np.array([99, 100, 199, 200, 399, 400])
        for k, expected in ((10, (4, 1, 1)), (20, (2, 1, 3)), (40, (0, 1, 5))):
            result = daily_alignment(sizes, k)
            self.assertEqual(result['days'], 6)
            self.assertEqual(result['full_rows'], int(sizes.sum()))
            self.assertEqual(result['capacity'], 137)
            self.assertEqual(result['effective_focus_positions'], 6 * k)
            self.assertEqual(tuple(result['relation'][name]['days'] for name in
                                   ('k_lt_capacity', 'k_eq_capacity', 'k_gt_capacity')), expected)
            for field in ('days', 'full_rows', 'capacity', 'effective_focus_positions'):
                self.assertEqual(sum(row[field] for row in result['relation'].values()), result[field])
            self.assertEqual(result['relation'], result['effective_relation'])

    def test_small_batches_clip_focus_without_creating_alerts(self):
        result = daily_alignment(np.array([1, 9, 10]), 20)
        self.assertEqual(result['capacity'], 1)
        self.assertEqual(result['effective_focus_positions'], 20)
        self.assertEqual(result['relation']['k_gt_capacity']['days'], 3)
        self.assertEqual(result['broad_inclusion_days'], 3)
        frame = batches([1, 9])
        scores = {candidate: np.full(len(frame), .5) for candidate in MATCHED}
        phase = diagnose_phase(frame, scores, np.ones(len(frame), bool))
        self.assertEqual(phase['context'][MATCHED[0]]['capacity'], 0)
        self.assertTrue(all(row['capacity'] == 0 for row in phase['daily_volume']))

    def test_counts_use_known_outcomes_and_aggregate_weighted_support(self):
        frame = batches([10, 100])
        frame.loc[[0, *range(10, 20)], 'delayed'] = 1
        alert = np.zeros(len(frame), bool)
        alert[[0, *range(10, 20)]] = True
        frame.loc[11:19, 'delayed'] = 0
        frame.loc[20:28, 'delayed'] = 1
        known = np.ones(len(frame), bool)
        result = counts(frame, known, alert)
        self.assertEqual(result['known_delayed_rows'], 11)
        self.assertEqual((result['TP'], result['FP'], result['FN']), (2, 9, 9))
        self.assertEqual((result['days'], result['capacity'], result['alerts']), (2, 11, 11))
        first = counts(frame, known, alert, frame.prediction_time.eq(pd.Timestamp('2017-07-01')).to_numpy())
        second = counts(frame, known, alert, frame.prediction_time.eq(pd.Timestamp('2017-07-02')).to_numpy())
        self.assertAlmostEqual(result['TP'] / result['known_delayed_rows'], 2 / 11)
        self.assertAlmostEqual(result['recall'], 2 / 11)
        self.assertNotAlmostEqual(result['TP'] / result['known_delayed_rows'],
                                 (first['TP'] / first['known_delayed_rows'] + second['TP'] / second['known_delayed_rows']) / 2)
        for field in ('full_rows', 'known_rows', 'unknown_rows', 'known_delayed_rows', 'days',
                      'capacity', 'alerts', 'known_alerts', 'unknown_alerts', 'TP', 'FP', 'FN', 'TN'):
            self.assertEqual(result[field], first[field] + second[field])

    def test_counts_reject_partial_day_support_and_malformed_masks(self):
        frame = batches([10, 20])
        known = np.ones(len(frame), bool)
        alert = np.zeros(len(frame), bool)
        alert[[0, 10, 11]] = True
        partial = np.ones(len(frame), bool)
        partial[1] = False
        with self.assertRaises(ValueError):
            counts(frame, known, alert, partial)
        for wrong in (np.ones(len(frame), int), np.ones(len(frame) - 1, bool), np.ones((len(frame), 1), bool)):
            with self.subTest(shape=wrong.shape), self.assertRaises(ValueError):
                counts(frame, wrong, alert)

    def test_unknown_label_corruption_does_not_change_analysis(self):
        frame = batches([20, 40])
        frame.loc[[0, 1, 20, 21, 22], 'delayed'] = 1
        scores = {candidate: np.linspace(.99, .01, len(frame)) for candidate in MATCHED}
        scores[NEW[2]] = np.linspace(.01, .99, len(frame))
        known = np.ones(len(frame), bool)
        known[[0, 20]] = False
        expected = diagnose_phase(frame, scores, known)
        changed = frame.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[~known, 'delayed'] = 'future outcome must never be read'
        self.assertEqual(diagnose_phase(changed, scores, known), expected)

    def test_unknown_rows_compete_and_ties_use_order_ids_before_outcome_mask(self):
        frame = batches([20])
        frame.loc[[1, 2], 'delayed'] = 1
        known = np.ones(20, bool)
        known[0] = False
        scores = {candidate: np.full(20, .5) for candidate in MATCHED}
        scores[NEW[2]] = np.full(20, .5)
        scores[NEW[2]][2] = .9
        # Reversing rows prevents input order from accidentally agreeing with
        # the contractual secondary order_id key for tied scores.
        order = np.arange(19, -1, -1)
        phase = diagnose_phase(frame.iloc[order].reset_index(drop=True),
                               {candidate: values[order] for candidate, values in scores.items()}, known[order])
        baseline, changed = phase['context'][BASELINES[1]], phase['context'][NEW[2]]
        self.assertEqual((baseline['alerts'], baseline['unknown_alerts'], baseline['TP'], baseline['FN']), (2, 1, 1, 1))
        self.assertEqual((changed['alerts'], changed['unknown_alerts'], changed['TP'], changed['FN']), (2, 1, 1, 1))
        movement = phase['contrasts'][NEW[2]]
        self.assertEqual((movement['overall']['recovered_delays'], movement['overall']['lost_delays']), (1, 1))
        ranks = movement['by_volume_bin'][0]['changed_delay_ranks']
        self.assertEqual(ranks['recovered_delays']['old_positions']['minimum'], 3)
        self.assertEqual(ranks['recovered_delays']['new_positions']['minimum'], 1)
        self.assertEqual(ranks['lost_delays']['old_positions']['minimum'], 2)
        self.assertEqual(ranks['lost_delays']['new_positions']['minimum'], 3)

    def test_all_day_and_volume_contrasts_conserve_caught_missed_and_slots(self):
        frame = batches([9, 100, 200, 400])
        frame.loc[np.arange(0, len(frame), 7), 'delayed'] = 1
        scores = {candidate: np.linspace(.01, .99, len(frame)) for candidate in MATCHED}
        for candidate in NEW:
            scores[candidate] = scores[candidate][::-1]
        phase = diagnose_phase(frame, scores, np.ones(len(frame), bool), include_primary_change=True)
        self.assertEqual(set(phase['contrasts']), {*NEW, 'primary_change'})
        self.assertEqual(phase['contrasts']['primary_change']['comparison']['comparison_kind'], 'mixed_objective_and_feature_package')
        for value in phase['contrasts'].values():
            overall = value['overall']
            self.assertEqual(overall['new_true_positives'] + overall['new_false_negatives'], overall['positive_rows'])
            self.assertEqual(overall['old_true_positives'] + overall['old_false_negatives'], overall['positive_rows'])
            self.assertEqual(overall['net_TP'], overall['recovered_delays'] - overall['lost_delays'])
            self.assertEqual(overall['dropped_alerts'], overall['added_alerts'])
            self.assertEqual(overall['old_alerts'], overall['new_alerts'])
            for rows in (value['daily'], value['by_volume_bin']):
                for field in ('full_batch_rows', 'known_rows', 'unknown_rows', 'positive_rows', 'net_TP',
                              'old_true_positives', 'new_true_positives', 'recovered_delays', 'lost_delays',
                              'added_alerts', 'dropped_alerts'):
                    self.assertEqual(sum(row[field] for row in rows), overall[field])
            for row in value['by_volume_bin']:
                for dimension in ('routes', 'promise_days'):
                    self.assertEqual(sum(group['net_TP'] for group in row[dimension]), row['net_TP'])
                for cohort in ('recovered_delays', 'lost_delays'):
                    self.assertEqual(row['changed_delay_ranks'][cohort]['rows'], row[cohort])

    def test_missing_score_cohort_and_known_label_corruption_are_rejected(self):
        frame = batches([20])
        scores = {candidate: np.full(20, .5) for candidate in MATCHED}
        with self.assertRaises(ValueError):
            diagnose_phase(frame, {candidate: score for candidate, score in scores.items() if candidate != NEW[0]}, np.ones(20, bool))
        frame.loc[1, 'delayed'] = 2
        with self.assertRaises(ValueError):
            diagnose_phase(frame, scores, np.ones(20, bool))

    def test_source_hash_tampering_stops_before_loading_or_analysis(self):
        source = {
            'feature_dataset': {'path': 'features.csv', 'sha256': 'frozen-feature-hash'},
            'score_export': {'path': 'scores.csv', 'sha256': 'frozen-score-hash'},
            'source_report': {'path': 'prior.json', 'sha256': 'frozen-prior-hash'},
            'source_candidate_versions': {'path': 'archive.json', 'sha256': 'frozen-archive-hash'},
            'specification_sha256': 'frozen-spec-hash',
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.json'
            path.write_text(json.dumps(source), encoding='utf-8')
            with patch('scripts.diagnose_rank_batch_size.sha256', return_value='tampered-hash'), \
                    patch('scripts.diagnose_rank_batch_size.read_features') as loader:
                with self.assertRaisesRegex(ValueError, 'Frozen diagnostic source changed'):
                    build_report(path, Path(temporary))
                loader.assert_not_called()

    def test_report_output_guards_source_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.json'
            output = Path(temporary) / 'result.json'
            source.write_text('{}', encoding='utf-8')
            self.assertEqual(validate_output(output, source), output.resolve())
            with self.assertRaises(ValueError):
                validate_output(source, source)
            with self.assertRaises(ValueError):
                validate_output(output.with_suffix('.csv'), source)
            output.write_text(json.dumps({'analysis': 'different', 'format_version': 1}), encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_output(output, source)
            output.write_text(json.dumps({'analysis': ANALYSIS, 'format_version': 1}), encoding='utf-8')
            self.assertEqual(validate_output(output, source), output.resolve())


class MatureQueryAlignmentTests(unittest.TestCase):
    def test_complete_cohort_and_mature_query_capacity_are_distinct(self):
        result = summarize_queries([{'full_eligible_rows': 400, 'training_rows': 10,
                                     'training_positive_rows': 1}])
        alignment = result['focus']['20']['alignment']
        mature = alignment['mature_query']['all_queries']
        complete = alignment['retrospective_complete_cohort']['all_queries']
        self.assertEqual(mature['configured_k_relation']['above']['queries'], 1)
        self.assertEqual(complete['configured_k_relation']['below']['queries'], 1)
        self.assertEqual(mature['effective_focus_relation_queries']['above'], 1)
        self.assertEqual(complete['effective_focus_relation_queries']['below'], 1)
        self.assertEqual(result['excluded_not_mature_rows'], 390)

    def test_zero_queries_and_uniform_labels_are_not_mixed_pairs(self):
        result = summarize_queries([
            {'full_eligible_rows': 10, 'training_rows': 0, 'training_positive_rows': 0},
            {'full_eligible_rows': 10, 'training_rows': 9, 'training_positive_rows': 0},
            {'full_eligible_rows': 30, 'training_rows': 20, 'training_positive_rows': 20},
            {'full_eligible_rows': 40, 'training_rows': 30, 'training_positive_rows': 2},
        ])
        self.assertEqual((result['past_eligible_days'], result['queries'],
                          result['days_without_mature_training_rows']), (4, 3, 1))
        self.assertEqual((result['mixed_label_queries'], result['all_on_time_queries'],
                          result['all_delayed_queries']), (1, 1, 1))
        focus = result['focus']['20']
        self.assertEqual(focus['effective_focus_positions'], 49)
        self.assertEqual(focus['mixed_query_effective_focus_positions'], 20)
        self.assertAlmostEqual(focus['mixed_query_focus_position_fraction'], 20 / 30)
        for reference in focus['alignment'].values():
            self.assertEqual(sum(row['queries'] for row in reference['mixed_label_queries']['configured_k_relation'].values()), 1)
            self.assertEqual(sum(row['queries'] for row in reference['all_queries']['configured_k_relation'].values()), 3)

    def test_clipped_position_coverage_uses_total_rows_not_mean_daily_fraction(self):
        result = summarize_queries([
            {'full_eligible_rows': 10, 'training_rows': 10, 'training_positive_rows': 1},
            {'full_eligible_rows': 100, 'training_rows': 100, 'training_positive_rows': 10},
        ])
        focus = result['focus']['20']
        self.assertEqual(focus['effective_focus_positions'], 30)
        self.assertAlmostEqual(focus['focus_position_fraction'], 30 / 110)
        self.assertNotAlmostEqual(focus['focus_position_fraction'], (1 + .2) / 2)
        self.assertEqual(focus['queries_fully_covered_by_k'], 1)
        self.assertEqual(result['focus']['40']['effective_focus_positions'], 50)

    def test_query_counts_must_be_nonnegative_and_nested(self):
        for n, q, p in ((0, 0, 0), (10, 11, 0), (10, 5, 6), (10, -1, 0),
                        (10, 5, -1), (10, True, 0), (10, 5.5, 0)):
            with self.subTest(counts=(n, q, p)), self.assertRaises(ValueError):
                summarize_queries([{'full_eligible_rows': n, 'training_rows': q,
                                    'training_positive_rows': p}])
        empty = summarize_queries([])
        self.assertEqual(empty['queries'], 0)
        self.assertIsNone(empty['focus']['20']['focus_position_fraction'])


if __name__ == '__main__':
    unittest.main()
