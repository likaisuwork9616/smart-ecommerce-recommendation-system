"""Frozen sparse-history intersections retain full-day competition and accounting."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.delay_route_exchanges import COUNT_FIELDS
from scripts.diagnose_handover_sparse import (
    ADDED_FEATURES, ANALYSIS, BASELINE, CELL_DEFINITIONS, FOCUS_MASKS, MATCHED, NEW,
    build_report, diagnose_phase, group_definitions, validate_output,
)
from tests.test_delay_route_exchanges import cohort, selected_scores


def example(rows=40):
    frame = cohort(rows)
    frame['estimated_delivery_days'] = np.resize([7., 30., 30.25, 32.], rows)
    counts = np.resize([0, 1, 4, 5, 20], rows)
    frame[ADDED_FEATURES[0]] = counts
    frame[ADDED_FEATURES[1]] = np.where(counts >= 5, 24., np.nan)
    frame[ADDED_FEATURES[2]] = np.where(counts >= 5, 48., np.nan)
    frame['delayed'] = 0
    frame.loc[[2, 4, 8], 'delayed'] = 1
    scores = {BASELINE: selected_scores(rows, [0, 1, 2, 3]), NEW: selected_scores(rows, [0, 1, 4, 6])}
    return frame, scores, np.ones(rows, bool)


def focus(report, name):
    return next(row for row in report['focus_masks'] if row['mask'] == name)


class SparseHandoverDiagnosisTests(unittest.TestCase):
    def test_history_and_fractional_promise_boundaries(self):
        frame, _, _ = example()
        groups = group_definitions(frame)
        self.assertEqual(list(groups['support'][:5]), ['history0', 'history1_4', 'history1_4', 'history_ge5', 'history_ge5'])
        self.assertEqual(list(groups['promise_group'][:4]), ['promise0_30', 'promise0_30', 'promise31plus', 'promise31plus'])
        self.assertEqual(list(groups['masks']['promise31plus'][:4]), [False, False, True, True])

    def test_unknown_routes_remain_in_other_route_and_observed_groups(self):
        frame, scores, known = example()
        frame.loc[0, 'state_route'] = None
        report = diagnose_phase(frame, scores, known)
        self.assertTrue(any(row['state_route'] == 'unknown' for row in report['observed_route_promise_support']))
        self.assertEqual(group_definitions(frame)['route_group'][0], 'other_route')

    def test_all_twelve_intersections_and_observed_groups_partition_every_count(self):
        frame, scores, known = example()
        report = diagnose_phase(frame, scores, known)
        self.assertEqual(len(report['intersection_cells']), 12)
        self.assertEqual(len(CELL_DEFINITIONS), 12)
        for rows in (report['intersection_cells'], report['observed_route_promise_support']):
            for field in COUNT_FIELDS:
                self.assertEqual(sum(row[field] for row in rows), report['summary'][field], field)
        self.assertEqual(tuple(row['mask'] for row in report['focus_masks']), FOCUS_MASKS)

    def test_empty_cells_are_retained_without_invented_recall_or_capacity(self):
        frame, scores, known = example()
        frame[ADDED_FEATURES[0]] = 0
        frame[ADDED_FEATURES[1]] = np.nan
        frame[ADDED_FEATURES[2]] = np.nan
        report = diagnose_phase(frame, scores, known)
        empty = [row for row in report['intersection_cells'] if row['support_bin'] != 'history0']
        self.assertEqual(len(empty), 8)
        for row in empty:
            self.assertEqual(row['full_batch_rows'], 0)
            self.assertIsNone(row['old_recall'])
            self.assertTrue(row['small_sample'])
            self.assertFalse(row['minimum_sample_met'])
            self.assertNotIn('capacity', row)
        allocation = report['cell_allocation']
        self.assertEqual(len(allocation['cells']), 12)
        self.assertEqual(len(allocation['daycells']), 12)

    def test_unknown_outcomes_compete_without_being_read_or_becoming_false_positives(self):
        frame, scores, known = example()
        known[[0, 2, 6]] = False
        report = diagnose_phase(frame, scores, known)
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[~known, 'delayed'] = 'not yet available'
        self.assertEqual(diagnose_phase(frame, scores, known), report)
        self.assertEqual(report['summary']['unknown_rows'], 3)
        self.assertEqual(report['summary']['unknown_removed_alerts'], 1)
        self.assertEqual(report['summary']['unknown_added_alerts'], 1)
        self.assertEqual(report['summary']['old_alerts'], 4)

    def test_sparse_groups_keep_existing_alerts_without_their_own_cap(self):
        frame, scores, known = example()
        frame[ADDED_FEATURES[0]] = 5
        frame[ADDED_FEATURES[1]] = 24.
        frame[ADDED_FEATURES[2]] = 48.
        frame.loc[[0, 1, 4, 6], ADDED_FEATURES] = [1, np.nan, np.nan]
        row = focus(diagnose_phase(frame, scores, known), 'history_lt5')
        self.assertEqual(row['full_batch_rows'], 4)
        self.assertEqual(row['new_alerts'], 4)
        self.assertEqual(row['old_alerts'], 2)
        self.assertNotIn('capacity', row)

    def test_overlapping_marginals_cannot_be_added_as_triple_losses(self):
        frame, scores, known = example()
        frame['delayed'] = 0
        frame.loc[2, 'delayed'] = 1
        frame.loc[2, 'estimated_delivery_days'] = 32.
        frame.loc[2, 'state_route'] = 'SP->SP'
        report = diagnose_phase(frame, scores, known)
        self.assertEqual(focus(report, 'history_lt5')['lost_delays'], 1)
        self.assertEqual(focus(report, 'promise31plus')['lost_delays'], 1)
        self.assertEqual(focus(report, 'history_lt5_and_promise31plus')['lost_delays'], 1)
        self.assertEqual(focus(report, 'triple')['lost_delays'], 0)

    def test_rank_cohorts_partition_each_focus_and_preserve_full_day_positions(self):
        frame, scores, known = example()
        report = diagnose_phase(frame, scores, known)
        for row in report['focus_masks']:
            cohorts = row['rank_analysis']['cohorts']['cohorts']
            self.assertEqual(sum(cohort['rows'] for cohort in cohorts), row['full_batch_rows'])
            for cohort in cohorts:
                self.assertEqual(sum(x['rows'] for x in cohort['rank_bin_transitions']), cohort['rows'])
        details = focus(report, 'all')['rank_analysis']['changed_and_missed_rank_details']
        lost = details['lost_delays']
        self.assertEqual(lost['rows'], 1)
        self.assertEqual(lost['old_positions']['median'], 3.)
        self.assertEqual(lost['new_positions']['median'], 5.)
        self.assertEqual(lost['off_top10_gap_slots']['old']['median'], -1.)
        self.assertEqual(lost['off_top10_gap_slots']['new']['median'], 1.)

    def test_tiny_complete_day_retains_zero_capacity_and_all_missed_rank_gap(self):
        frame, _, known = example(9)
        scores = {candidate: np.linspace(.9, .1, 9) for candidate in MATCHED}
        report = diagnose_phase(frame, scores, known)
        self.assertEqual(report['summary']['old_alerts'], 0)
        lost = focus(report, 'all')['rank_analysis']['changed_and_missed_rank_details']['both_missed_delays']
        self.assertEqual(lost['rows'], 3)
        self.assertEqual(lost['off_top10_gap_slots']['new']['minimum'], 3)
        self.assertEqual(report['cell_allocation']['summary']['capacity'], 0)

    def test_daily_gross_cell_flows_do_not_cancel_with_monthly_net(self):
        frame, _, known = example()
        frame.loc[20:, 'prediction_time'] += pd.Timedelta(days=1)
        frame[ADDED_FEATURES[0]] = 5
        frame[ADDED_FEATURES[1]] = 24.
        frame[ADDED_FEATURES[2]] = 48.
        frame['estimated_delivery_days'] = 10.
        frame['state_route'] = 'SP->SP'
        frame.loc[[0, 1, 20, 21], ADDED_FEATURES] = [0, np.nan, np.nan]
        scores = {BASELINE: selected_scores(40, [0, 1, 22, 23]),
                  NEW: selected_scores(40, [2, 3, 20, 21])}
        report = diagnose_phase(frame, scores, known)
        allocation = report['cell_allocation']
        self.assertEqual(allocation['summary']['cross_cell_outgoing_slots'], 4)
        self.assertEqual(allocation['summary']['cross_cell_incoming_slots'], 4)
        self.assertEqual(allocation['summary']['monthly_net_recipient_slots'], 0)
        self.assertTrue(all(row['net_alerts'] == 0 for row in allocation['cells']))
        self.assertEqual(len(allocation['daycells']), 24)

    def test_loss_day_context_counts_whole_day_outside_focus_and_unknown_additions(self):
        frame, scores, known = example()
        known[6] = False
        report = diagnose_phase(frame, scores, known)
        sparse = report['lost_delay_day_context']['history_lt5']
        self.assertEqual(sparse['lost_delay_rows'], 1)
        self.assertEqual(sparse['lost_delay_days'], 1)
        day = sparse['days'][0]
        rows = day['whole_day_changed_alerts_by_cell_outcome']
        self.assertEqual(len(rows), 12 * 2 * 3)
        self.assertEqual(sum(row['rows'] for row in rows if row['direction'] == 'added'), 2)
        self.assertEqual(sum(row['rows'] for row in rows if row['direction'] == 'added' and row['outcome'] == 'unknown'), 1)
        self.assertEqual(sum(row['rows'] for row in rows if row['direction'] == 'added' and row['outcome'] == 'delayed'), 1)
        self.assertIn('promise31plus_and_SP_RJ', report['lost_delay_day_context'])

    def test_no_loss_focus_retains_empty_context_and_all_recovered_days(self):
        frame, scores, known = example()
        frame['delayed'] = 0
        frame.loc[4, 'delayed'] = 1
        frame.loc[4, 'state_route'] = 'SP->RJ'
        frame.loc[4, 'estimated_delivery_days'] = 31.
        frame.loc[4, ADDED_FEATURES] = [1, np.nan, np.nan]
        triple = diagnose_phase(frame, scores, known)['lost_delay_day_context']['triple']
        self.assertEqual(triple['lost_delay_rows'], 0)
        self.assertEqual(triple['days'], [])
        self.assertEqual(sum(row['recovered_delays'] for row in triple['all_focus_days']), 1)

    def test_small_sample_requires_both_known_rows_and_positive_support(self):
        frame, scores, known = example()
        row = focus(diagnose_phase(frame, scores, known), 'all')
        self.assertTrue(row['small_sample'])
        frame.loc[[10, 11], 'delayed'] = 1
        row = focus(diagnose_phase(frame, scores, known), 'all')
        self.assertFalse(row['small_sample'])
        self.assertTrue(row['minimum_sample_met'])

    def test_corrupt_counts_promises_known_labels_and_score_cohorts_fail(self):
        frame, scores, known = example()
        changes = [(ADDED_FEATURES[0], .5), ('estimated_delivery_days', np.nan), ('delayed', 'bad')]
        for column, value in changes:
            changed = frame.copy()
            changed[column] = changed[column].astype(object)
            changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                diagnose_phase(changed, scores, known)
        with self.assertRaises(ValueError):
            diagnose_phase(frame, {BASELINE: scores[BASELINE]}, known)
        with self.assertRaises(ValueError):
            diagnose_phase(frame, scores, known.astype(int))

    def test_no_private_identifiers_or_nonfinite_json_escape(self):
        frame, scores, known = example()
        report = diagnose_phase(frame, scores, known)
        encoded = json.dumps(report, allow_nan=False)
        self.assertNotIn('private-order-', encoded)
        self.assertNotIn('delay_score', encoded)
        self.assertNotIn('donor_order', encoded)

    def test_frozen_source_sha_guard_precedes_any_feature_or_model_work(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            previous = Path(directory) / 'previous.json'
            source.write_text('{}', encoding='utf-8')
            previous.write_text('{}', encoding='utf-8')
            with patch('scripts.diagnose_handover_sparse.read_features') as reader:
                with self.assertRaisesRegex(ValueError, 'exact published diagnostic'):
                    build_report(source, Path(directory), previous)
                reader.assert_not_called()

    def test_output_guards_protect_both_sources_and_unrelated_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            source, previous, output = [Path(directory) / name for name in ('source.json', 'prior.json', 'output.json')]
            for path in (source, previous):
                with self.assertRaises(ValueError):
                    validate_output(path, source, previous)
            output.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_output(output, source, previous)
            output.write_text(json.dumps({'analysis': ANALYSIS, 'format_version': 1}), encoding='utf-8')
            self.assertEqual(validate_output(output, source, previous), output.resolve())
            with self.assertRaises(ValueError):
                validate_output(Path(directory) / 'output.csv', source, previous)


if __name__ == '__main__':
    unittest.main()
