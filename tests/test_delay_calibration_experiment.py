"""Historical calibration decisions must remain isolated from replay outcomes."""

import io
from contextlib import redirect_stderr
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts.compare_calibration_budget import (
    BUDGETS, CANDIDATES, METHODS, decide_calibration_fold, select_candidate,
)
from scripts.delay_calibration_policy import fit_calibrator, transform_scores
from scripts.predict_delay import main as prediction_main, predict_features


def phase_frame(months, rows=40):
    frames = []
    for month in months:
        position = np.arange(rows)
        frame = pd.DataFrame({
            'order_id': [f'{month}-{index:03d}' for index in position],
            'prediction_time': pd.Timestamp(month + '-01') + pd.to_timedelta(position, unit='m'),
            'label_available_time': pd.Timestamp(month + '-15'),
            'delayed': (position >= rows * .75).astype(int),
        })
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def decision_projection(experiment):
    """Remove only the outputs explicitly allowed to consult replay data."""
    models = {}
    for candidate in CANDIDATES:
        models[candidate] = {'raw_policy_average_precision': experiment['models'][candidate]['raw_policy_average_precision']}
        for method in METHODS:
            entry = experiment['models'][candidate][method]
            models[candidate][method] = {
                'calibration': entry['calibration'],
                'probability_metrics': {key: value for key, value in entry['probability_metrics'].items()
                                        if key != 'development_evaluation'},
                'strategies': {budget: {key: value for key, value in row.items()
                                       if key not in ('evaluation', 'evaluation_batch')}
                               for budget, row in entry['strategies'].items()},
            }
    return {'selected_models': experiment['selected_models'], 'models': models}


class CalibrationDecisionTests(unittest.TestCase):
    def setUp(self):
        self.calibration = phase_frame(('2017-09', '2017-10'))
        self.policy = phase_frame(('2017-11',))
        self.evaluation = phase_frame(('2018-02',))
        self.cutoff = pd.Timestamp('2018-02-01')
        self.policy['delayed'] = (np.arange(len(self.policy)) < 10).astype(int)
        # The first highest-score order is still unknown and must retain its slot.
        self.policy.loc[0, 'label_available_time'] = self.cutoff
        self.policy.loc[0, 'delayed'] = np.nan
        self.calibration_scores = {candidate: np.tile(np.linspace(.02, .98, 40), 2)
                                   for candidate in CANDIDATES}
        self.policy_scores = {candidate: np.linspace(.98, .02, 40) for candidate in CANDIDATES}
        self.evaluation_scores = {candidate: np.linspace(.02, .98, 40) for candidate in CANDIDATES}

    def decide(self, policy=None, evaluation=None, evaluation_scores=None):
        return decide_calibration_fold(
            self.calibration, self.calibration_scores,
            self.policy if policy is None else policy, self.policy_scores,
            self.evaluation if evaluation is None else evaluation,
            self.evaluation_scores if evaluation_scores is None else evaluation_scores,
            self.cutoff,
        )

    def test_fit_receives_only_disjoint_calibration_labels_and_oot_scores(self):
        calls = []

        def capture(labels, scores, method):
            calls.append((np.asarray(labels).copy(), np.asarray(scores).copy(), method))
            return fit_calibrator(labels, scores, method)

        with patch('scripts.compare_calibration_budget.fit_calibrator', side_effect=capture):
            experiment, calibrators = self.decide()
        self.assertEqual(len(calls), len(CANDIDATES) * len(METHODS))
        for index, candidate in enumerate(CANDIDATES):
            for method_index, method in enumerate(METHODS):
                labels, scores, used_method = calls[index * len(METHODS) + method_index]
                np.testing.assert_array_equal(labels, self.calibration.delayed)
                np.testing.assert_array_equal(scores, self.calibration_scores[candidate])
                self.assertEqual(used_method, method)
                self.assertEqual(calibrators[candidate][method].fit_rows, len(self.calibration))
                entry = experiment['models'][candidate][method]
                self.assertEqual(entry['probability_metrics']['calibration_fit_descriptive']['rows'], 80)
                self.assertEqual(entry['probability_metrics']['policy_validation']['rows'], 39)

    def test_evaluation_outcomes_and_scores_cannot_change_any_frozen_decision(self):
        original, calibrators = self.decide()
        changed = self.evaluation.copy()
        changed['delayed'] = 1 - changed.delayed
        changed['label_available_time'] = pd.Timestamp('2099-01-01')
        reversed_scores = {candidate: 1 - scores for candidate, scores in self.evaluation_scores.items()}
        replay, changed_calibrators = self.decide(evaluation=changed, evaluation_scores=reversed_scores)
        self.assertEqual(decision_projection(original), decision_projection(replay))
        query = np.linspace(0., 1., 11)
        for candidate in CANDIDATES:
            for method in METHODS:
                self.assertEqual(calibrators[candidate][method].to_report(),
                                 changed_calibrators[candidate][method].to_report())
                np.testing.assert_array_equal(transform_scores(calibrators[candidate][method], query),
                                              transform_scores(changed_calibrators[candidate][method], query))

    def test_policy_labels_at_cutoff_are_ignored_but_full_cohort_consumes_slots(self):
        original, _ = self.decide()
        changed = self.policy.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[0, 'delayed'] = 'outcome not known at cutoff'
        replay, _ = self.decide(policy=changed)
        self.assertEqual(original, replay)
        for candidate in CANDIDATES:
            for method in METHODS:
                row = original['models'][candidate][method]['strategies']['cap_10']
                rule = row['threshold_policy']
                self.assertEqual(rule['full_batch_rows'], 40)
                self.assertEqual(rule['known_rows'], 39)
                self.assertEqual(rule['unknown_rows'], 1)
                self.assertEqual(rule['daily_capacity_rows'], 4)
                self.assertEqual(rule['unknown_predicted_positive_rows'], 1)
                self.assertEqual(row['validation_batch']['unknown_outcome_alerts'], 1)
                self.assertLessEqual(row['validation_batch']['maximum_daily_alert_rate'], .10)

    def test_each_method_and_budget_uses_its_actual_capped_predictions(self):
        experiment, _ = self.decide()
        for candidate in CANDIDATES:
            for method in METHODS:
                for budget, cap in BUDGETS.items():
                    row = experiment['models'][candidate][method]['strategies'][budget]
                    cm = row['evaluation']['confusion_matrix']
                    self.assertEqual(sum(map(sum, cm)), len(self.evaluation))
                    self.assertEqual(cm[0][1] + cm[1][1], row['evaluation_batch']['alerts'])
                    if cap is not None:
                        self.assertLessEqual(row['evaluation_batch']['maximum_daily_alert_rate'], cap)
                        self.assertLessEqual(row['evaluation_batch']['alerts'], int(cap * len(self.evaluation)))

    def test_phase_overlap_maturity_and_calendar_order_are_rejected(self):
        for first, second in (('calibration', 'policy'), ('policy', 'evaluation'), ('calibration', 'evaluation')):
            phases = {name: getattr(self, name).copy() for name in ('calibration', 'policy', 'evaluation')}
            phases[second].loc[1, 'order_id'] = phases[first].iloc[0].order_id
            with self.subTest(overlap=(first, second)), self.assertRaises(ValueError):
                decide_calibration_fold(phases['calibration'], self.calibration_scores,
                                        phases['policy'], self.policy_scores, phases['evaluation'],
                                        self.evaluation_scores, self.cutoff)
        self.calibration.loc[0, 'label_available_time'] = self.cutoff
        with self.assertRaisesRegex(ValueError, 'strictly before'):
            self.decide()
        self.calibration['label_available_time'] = self.calibration.label_available_time.astype('datetime64[ns]')
        self.calibration.loc[0, 'label_available_time'] = self.cutoff - pd.Timedelta(nanoseconds=1)
        self.decide()
        self.calibration['prediction_time'] = pd.Timestamp('2017-10-01')
        with self.assertRaises(ValueError):
            self.decide()


class CandidateSelectionTests(unittest.TestCase):
    def models(self):
        models = {}
        for candidate in CANDIDATES:
            models[candidate] = {'raw_policy_average_precision': .5, 'sigmoid': {'strategies': {
                'cap_10': {'threshold_policy': {'feasible': False},
                           'validation': {'recall': .1, 'confusion_matrix': [[20, 3], [9, 1]]},
                           'validation_batch': {'alerts': 4},
                           # These future metrics must have no role in candidate selection.
                           'evaluation': {'recall': 1., 'precision': 1.}},
            }}}
        return models

    def test_feasible_candidates_win_then_minimize_full_workload_not_future_score(self):
        models = self.models()
        first, second, third = CANDIDATES[:3]
        for candidate, alerts in ((first, 5), (second, 6)):
            entry = models[candidate]['sigmoid']['strategies']['cap_10']
            entry['threshold_policy']['feasible'] = True
            entry['validation_batch']['alerts'] = alerts
        models[third]['sigmoid']['strategies']['cap_10']['validation']['recall'] = .99
        self.assertEqual(select_candidate(models, 'sigmoid', 'cap_10'), first)
        models[first]['sigmoid']['strategies']['cap_10']['evaluation'] = {'recall': 0., 'precision': 0.}
        self.assertEqual(select_candidate(models, 'sigmoid', 'cap_10'), first)

    def test_when_all_infeasible_maximize_known_recall_before_false_positives(self):
        models = self.models()
        first, second, third = CANDIDATES[:3]
        models[first]['sigmoid']['strategies']['cap_10']['validation']['confusion_matrix'][0][1] = 0
        for candidate, fp in ((second, 5), (third, 4)):
            entry = models[candidate]['sigmoid']['strategies']['cap_10']
            entry['validation']['recall'] = .4
            entry['validation']['confusion_matrix'][0][1] = fp
        self.assertEqual(select_candidate(models, 'sigmoid', 'cap_10'), third)


class EchoProbabilityPipeline:
    """A deterministic estimator with reversed class order and a visible input contract."""

    classes_ = np.array([1, 0])

    def predict_proba(self, features):
        self.received_columns = list(features.columns)
        probabilities = features['score'].to_numpy(dtype=float)
        return np.column_stack([probabilities, 1 - probabilities])


class CalibratedInferenceTests(unittest.TestCase):
    def setUp(self):
        self.features = phase_frame(('2018-02',), rows=20)
        self.features['prediction_time'] = (pd.Timestamp('2018-02-01') +
                                             pd.to_timedelta(np.arange(20) // 10, unit='D'))
        self.features['score'] = np.tile(np.linspace(.01, .99, 10), 2)
        self.features['route'] = 'SP->RJ'
        self.features['future_delivery_delay'] = np.where(self.features.delayed, 9999., -9999.)
        self.features.index = [7] * 20
        self.artifact = {
            'format_version': 1, 'pipeline': EchoProbabilityPipeline(),
            'threshold': .5, 'feature_names': ['score', 'route'],
            'numeric_features': ['score'], 'categorical_features': ['route'],
            'selected_model': 'synthetic_only',
        }

    def test_old_artifact_keeps_exact_columns_and_excludes_outcomes_from_estimator(self):
        output = predict_features(self.artifact, self.features)
        self.assertEqual(list(output.columns), ['order_id', 'delay_score', 'threshold', 'predicted_delayed'])
        self.assertEqual(output.index.tolist(), self.features.index.tolist())
        self.assertEqual(self.artifact['pipeline'].received_columns, ['score', 'route'])
        np.testing.assert_array_equal(output.delay_score, self.features.score)
        np.testing.assert_array_equal(output.predicted_delayed, (self.features.score >= .5).astype(int))
        changed = self.features.copy()
        changed['delayed'] = 1 - changed.delayed
        changed['future_delivery_delay'] = -changed.future_delivery_delay
        pd.testing.assert_frame_equal(output, predict_features(self.artifact, changed))

    def test_calibrated_artifact_roundtrip_applies_transform_before_threshold_and_daily_cap(self):
        self.artifact['calibrator'] = fit_calibrator([0, 0, 1, 1], [.1, .2, .8, .9], 'isotonic')
        self.artifact['daily_alert_cap'] = .20
        stream = io.BytesIO()
        joblib.dump(self.artifact, stream)
        stream.seek(0)
        restored = joblib.load(stream)
        result = predict_features(restored, self.features, complete_daily_batches=True)
        np.testing.assert_array_equal(result.raw_delay_score, self.features.score)
        expected_scores = transform_scores(restored['calibrator'], self.features.score)
        np.testing.assert_array_equal(result.delay_score, expected_scores)
        np.testing.assert_array_equal(result.threshold_eligible, (expected_scores >= .5).astype(int))
        expected = np.zeros(20, dtype=int)
        expected[[8, 9, 18, 19]] = 1
        np.testing.assert_array_equal(result.predicted_delayed, expected)
        np.testing.assert_array_equal(result.budget_suppressed,
                                      ((expected_scores >= .5) & ~expected.astype(bool)).astype(int))
        self.assertEqual(result.predicted_delayed.sum(), 4)
        self.assertEqual(restored['pipeline'].received_columns, ['score', 'route'])

    def test_uncapped_calibrated_artifact_does_not_require_daily_metadata(self):
        self.artifact['calibrator'] = fit_calibrator([0, 0, 1, 1], [.1, .2, .8, .9], 'isotonic')
        features = self.features.drop(columns='prediction_time')
        result = predict_features(self.artifact, features)
        expected = transform_scores(self.artifact['calibrator'], features.score)
        np.testing.assert_array_equal(result.delay_score, expected)
        np.testing.assert_array_equal(result.predicted_delayed, (expected >= .5).astype(int))
        self.assertNotIn('threshold_eligible', result)

    def test_capped_artifact_requires_explicit_complete_batch_acknowledgment_and_metadata(self):
        self.artifact['daily_alert_cap'] = .10
        with self.assertRaisesRegex(ValueError, 'complete_daily_batches'):
            predict_features(self.artifact, self.features)
        for missing in ('order_id', 'prediction_time'):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                predict_features(self.artifact, self.features.drop(columns=missing),
                                 complete_daily_batches=True)

    def test_cli_rejects_single_order_for_capped_model_even_with_batch_acknowledgment(self):
        self.artifact['daily_alert_cap'] = .10
        with patch('scripts.predict_delay.joblib.load', return_value=self.artifact), \
                patch('sys.argv', ['predict_delay.py', '--model', 'synthetic.joblib',
                                   '--order-id', 'one_order', '--complete-daily-batches']), \
                patch('scripts.predict_delay.load_olist_tables') as load_tables, \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            prediction_main()
        self.assertEqual(error.exception.code, 2)
        load_tables.assert_not_called()


if __name__ == '__main__':
    unittest.main()
