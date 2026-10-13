"""Frozen monthly replay guards without running model fits or a full report."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.diagnose_december_misses import (
    CANDIDATES, CUTOFF, EVALUATION_MONTH, main, verify_month_scores,
)


def frozen_month(month='2017-07'):
    frame = pd.DataFrame({
        'order_id': ['order-a', 'order-b', 'order-c'],
        'prediction_time': pd.to_datetime([month + '-01 09:00', month + '-01 10:00', month + '-02 09:00']),
        'label_available_time': [CUTOFF - pd.Timedelta(nanoseconds=1),
                                 CUTOFF, CUTOFF + pd.Timedelta(nanoseconds=1)],
        'delayed': [1, 0, 1],
    })
    evaluation = month == EVALUATION_MONTH
    known = np.ones(3, bool) if evaluation else np.array([True, False, False])
    values, predictions = np.array([.9, .8, .7]), np.zeros(3, bool)
    scores = pd.DataFrame({
        'fold': EVALUATION_MONTH, 'candidate': CANDIDATES[0], 'model_version': month,
        'role': 'evaluation' if evaluation else 'validation',
        'order_id': frame.order_id,
        'prediction_time': frame.prediction_time,
        'known_at_selection': np.zeros(3, bool) if evaluation else known,
        'outcome_for_metrics': np.where(known, frame.delayed, np.nan),
        'delay_score': values, 'predicted_delayed': predictions,
    })
    return frame, scores, known, values, predictions


class FrozenDecemberReplayTests(unittest.TestCase):
    def verify(self, frame, scores, known, values, predictions, month='2017-07'):
        return verify_month_scores(frame, scores, CANDIDATES[0], month, known, values, predictions)

    def test_strict_historical_cutoff_includes_only_delivery_before_december_first(self):
        frame, scores, known, values, predictions = frozen_month()
        self.verify(frame, scores, known, values, predictions)
        # Equality and one nanosecond after cutoff are both unknown; their
        # eventually observed labels must remain absent from frozen metrics.
        self.assertEqual(scores.outcome_for_metrics.notna().tolist(), [True, False, False])
        changed = frame.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[~known, 'delayed'] = 'not available at the cutoff'
        self.verify(changed, scores, known, values, predictions)

    def test_caller_cannot_reclassify_boundary_or_future_outcomes_as_known(self):
        frame, scores, _, values, predictions = frozen_month()
        for incorrect in (np.array([True, True, False]), np.array([True, False, True]),
                          np.array([False, False, False])):
            forged = scores.copy()
            forged['known_at_selection'] = incorrect
            forged['outcome_for_metrics'] = np.where(incorrect, frame.delayed, np.nan)
            with self.assertRaises(ValueError):
                self.verify(frame, forged, incorrect, values, predictions)

    def test_historical_role_flags_and_unknown_metric_labels_must_match(self):
        frame, scores, known, values, predictions = frozen_month()
        for column, position, invalid in (('role', 0, 'evaluation'),
                                          ('known_at_selection', 1, True),
                                          ('outcome_for_metrics', 1, 0.),
                                          ('outcome_for_metrics', 0, np.nan)):
            bad = scores.copy()
            bad.loc[position, column] = invalid
            with self.assertRaises((ValueError, AssertionError)):
                self.verify(frame, bad, known, values, predictions)

    def test_december_development_labels_are_available_only_for_retrospective_metrics(self):
        frame, scores, known, values, predictions = frozen_month(EVALUATION_MONTH)
        self.verify(frame, scores, known, values, predictions, EVALUATION_MONTH)
        self.assertTrue(known.all())
        self.assertFalse(scores.known_at_selection.any())
        for column, invalid in (('role', 'validation'), ('known_at_selection', True),
                                ('outcome_for_metrics', np.nan)):
            bad = scores.copy()
            bad.loc[0, column] = invalid
            with self.assertRaises((ValueError, AssertionError)):
                self.verify(frame, bad, known, values, predictions, EVALUATION_MONTH)
        with self.assertRaises(ValueError):
            self.verify(frame, scores, np.array([True, False, True]), values, predictions, EVALUATION_MONTH)

    def test_complete_month_identity_and_timestamps_cannot_be_dropped_replaced_or_duplicated(self):
        frame, scores, known, values, predictions = frozen_month()
        self.verify(frame, scores.iloc[::-1], known, values, predictions)
        changes = [scores.iloc[:-1].copy(), scores.copy(), scores.copy(), scores.copy()]
        changes[1].loc[1, 'order_id'] = 'other-order'
        changes[2].loc[1, 'order_id'] = changes[2].loc[0, 'order_id']
        changes[3].loc[1, 'prediction_time'] += pd.Timedelta(minutes=1)
        for bad in changes:
            with self.assertRaises((ValueError, AssertionError)):
                self.verify(frame, bad, known, values, predictions)
        # A duplicated frame paired with similarly duplicated scores is not
        # evidence that the complete batch was preserved.
        duplicate_frame, duplicate_scores = frame.copy(), scores.copy()
        duplicate_frame.loc[1, 'order_id'] = duplicate_frame.loc[0, 'order_id']
        duplicate_scores.loc[1, 'order_id'] = duplicate_scores.loc[0, 'order_id']
        with self.assertRaises(ValueError):
            self.verify(duplicate_frame, duplicate_scores, known, values, predictions)

    def test_masks_unknown_months_and_invalid_id_types_are_rejected_before_alignment(self):
        frame, scores, known, values, predictions = frozen_month()
        for mask in ([1, 0, 0], [True, False], [[True, False, False]], [True, None, False]):
            with self.assertRaises(ValueError):
                self.verify(frame, scores, mask, values, predictions)
        with self.assertRaises(ValueError):
            self.verify(frame, scores, known, values, predictions, '2017-10')
        for invalid in ('', None, 123):
            bad_frame, bad_scores = frame.copy(), scores.copy()
            bad_frame['order_id'] = bad_frame.order_id.astype(object)
            bad_scores['order_id'] = bad_scores.order_id.astype(object)
            bad_frame.loc[0, 'order_id'] = invalid
            bad_scores.loc[0, 'order_id'] = invalid
            with self.assertRaises(ValueError):
                self.verify(bad_frame, bad_scores, known, values, predictions)

    def test_replayed_score_and_alert_changes_cannot_silently_pass(self):
        frame, scores, known, values, predictions = frozen_month()
        with self.assertRaises((ValueError, AssertionError)):
            self.verify(frame, scores, known, values + .001, predictions)
        with self.assertRaises((ValueError, AssertionError)):
            self.verify(frame, scores, known, values, np.array([True, False, False]))

    def test_cli_rejects_input_alias_and_non_json_without_building_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'frozen.json'
            source.write_text('{"frozen": true}', encoding='utf-8')
            for output in (source, Path(directory) / 'output.csv'):
                with self.subTest(output=str(output)), patch('scripts.diagnose_december_misses.build_report') as build:
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        main(['--source-report', str(source), '--output', str(output)])
                    build.assert_not_called()
            self.assertEqual(source.read_text(encoding='utf-8'), '{"frozen": true}')

    def test_cli_cannot_overwrite_an_unrelated_existing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'older_experiment.json'
            output.write_text('{"historical_result": 123}', encoding='utf-8')
            with patch('scripts.diagnose_december_misses.build_report', return_value={}) as build:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    main(['--output', str(output)])
                build.assert_not_called()
            self.assertEqual(output.read_text(encoding='utf-8'), '{"historical_result": 123}')

    def test_cli_can_repeat_this_diagnosis_but_cannot_claim_another_format(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'december_miss_diagnostics.json'
            own_report = '{"analysis":"december_and_its_historical_validation_misses","format_version":1}'
            output.write_text(own_report, encoding='utf-8')
            with patch('scripts.diagnose_december_misses.build_report', return_value={'status': 'ok'}) as build:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--output', str(output)]), {'status': 'ok'})
                build.assert_called_once()
            for existing in ('{"analysis":"another_experiment","format_version":1}',
                             '{"analysis":"december_and_its_historical_validation_misses","format_version":2}',
                             'unfinished invalid JSON'):
                output.write_text(existing, encoding='utf-8')
                with patch('scripts.diagnose_december_misses.build_report') as build:
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        main(['--output', str(output)])
                    build.assert_not_called()
                self.assertEqual(output.read_text(encoding='utf-8'), existing)


if __name__ == '__main__':
    unittest.main()
