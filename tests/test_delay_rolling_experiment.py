"""Monthly model versions must preserve train-only and validation-only decisions."""
import io
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from scripts.compare_monthly_retraining import (
    CANDIDATES, PRIMARY_STRATEGY, STRATEGIES, decide_fold, fit_month,
    feature_names, make_candidate, prepare_input,
)
from scripts.predict_delay import predict_features
from scripts.train_delay_model import binary_metrics


def feature_frame(rows=144):
    """Outcome columns are deliberately tempting and never valid model inputs."""
    numeric, categorical = feature_names('logistic_route')
    position = np.arange(rows)
    frame = pd.DataFrame({name: position.astype(float) % (11 + index)
                          for index, name in enumerate(numeric)})
    for name in categorical:
        frame[name] = np.where(position % 3, 'SP', 'RJ')
    frame['state_route'] = np.where(position % 3, 'SP->RJ', 'RJ->SP')
    frame['order_id'] = [f'order-{index}' for index in position]
    frame['delayed'] = position % 2
    frame['prediction_time'] = pd.Timestamp('2017-04-01')
    frame['label_available_time'] = pd.Timestamp('2017-05-01')
    frame['future_delivery_delay'] = np.where(frame.delayed, 99999.0, -99999.0)
    return frame


class RollingFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frame = feature_frame()
        cls.splits = {'train': frame.iloc[:72].copy(), 'scoring': frame.iloc[72:].copy()}
        cls.splits['scoring']['prediction_time'] = pd.Timestamp('2017-12-01')
        cls.splits['scoring']['label_available_time'] = pd.Timestamp('2099-01-01')
        cls.splits['scoring']['future_delivery_delay'] = 1e12
        # Scoring values must not alter a learned median or trigger another fit.
        cls.imputed_column = feature_names('logistic_route')[0][0]
        cls.splits['train'][cls.imputed_column] = np.arange(72, dtype=float)
        cls.splits['train'].loc[0, cls.imputed_column] = np.nan
        cls.splits['scoring'][cls.imputed_column] = 100000.0
        cls.fit_calls, cls.created, cls.results = [], [], {}
        original_fit = Pipeline.fit

        def small_candidate(candidate, seed, n_jobs):
            pipeline = make_candidate(candidate, seed, n_jobs)
            if candidate.startswith('random_forest'):
                pipeline.set_params(classifier__n_estimators=12,
                                    classifier__min_samples_leaf=2)
            cls.created.append((candidate, pipeline))
            return pipeline

        def record_fit(pipeline, features, labels, **params):
            cls.fit_calls.append((pipeline, features.copy(), labels.copy()))
            return original_fit(pipeline, features, labels, **params)

        with patch('scripts.compare_monthly_retraining.make_candidate',
                   side_effect=small_candidate), patch.object(Pipeline, 'fit', new=record_fit), \
                redirect_stdout(io.StringIO()):
            for candidate in CANDIDATES:
                cls.results[candidate] = fit_month(cls.splits, candidate, seed=42, n_jobs=1)

    def test_fit_uses_only_train_rows_and_excludes_target_and_maturity_metadata(self):
        self.assertEqual(len(self.fit_calls), len(CANDIDATES))
        self.assertEqual(len(self.created), len(CANDIDATES))
        for candidate, pipeline in self.created:
            calls = [call for call in self.fit_calls if call[0] is pipeline]
            self.assertEqual(len(calls), 1)
            _, features, labels = calls[0]
            pd.testing.assert_frame_equal(features, prepare_input(self.splits['train'], candidate))
            pd.testing.assert_series_equal(labels, self.splits['train'].delayed)
            self.assertFalse({'delayed', 'label_available_time', 'prediction_time',
                              'order_id', 'future_delivery_delay'}.intersection(features.columns))
            self.assertFalse(set(features.index) & set(self.splits['scoring'].index))
            imputer = pipeline.named_steps['preprocessor'].named_transformers_[
                'numeric'].named_steps['imputer']
            numeric, _ = feature_names(candidate)
            self.assertEqual(imputer.statistics_[numeric.index(self.imputed_column)], 36.0)

    def test_scoring_ignores_future_outcomes_and_random_forest_predicts_with_one_job(self):
        changed = self.splits['scoring'].copy()
        changed['delayed'] = 1 - changed.delayed
        changed['label_available_time'] = pd.Timestamp('2200-01-01')
        changed['prediction_time'] = pd.Timestamp('2199-01-01')
        changed['future_delivery_delay'] = -1e12
        for candidate, (report, pipeline, scores) in self.results.items():
            numeric, categorical = feature_names(candidate)
            artifact = {'format_version': 1, 'pipeline': pipeline, 'threshold': .5,
                        'feature_names': numeric + categorical,
                        'numeric_features': numeric, 'categorical_features': categorical}
            result = predict_features(artifact, changed)
            np.testing.assert_array_equal(scores, result.delay_score)
            self.assertEqual(len(scores), len(changed))
            self.assertTrue(np.isfinite(scores).all())
            if candidate.startswith('random_forest'):
                self.assertEqual(pipeline.named_steps['classifier'].n_jobs, 1)

    def test_reloaded_final_month_artifact_preserves_existing_inference_contract(self):
        for candidate, (report, pipeline, scores) in self.results.items():
            numeric, categorical = feature_names(candidate)
            artifact = {'format_version': 1, 'selected_model': candidate,
                        'feature_set': 'route_promise_90d' if candidate.endswith('_route') else 'approval_static',
                        'pipeline': pipeline, 'threshold': float(np.median(scores)),
                        'feature_names': numeric + categorical,
                        'numeric_features': numeric, 'categorical_features': categorical,
                        'metadata': {'research_only': True, 'model_fit_month': '2017-12',
                                     'strategy': PRIMARY_STRATEGY}}
            stream = io.BytesIO()
            joblib.dump(artifact, stream, compress=3)
            stream.seek(0)
            restored = joblib.load(stream)
            inference = predict_features(restored, self.splits['scoring'])
            np.testing.assert_array_equal(inference.delay_score, scores)
            np.testing.assert_array_equal(inference.predicted_delayed,
                                          (scores >= restored['threshold']).astype(int))
            np.testing.assert_array_equal(inference.order_id, self.splits['scoring'].order_id)
            self.assertTrue(inference.threshold.eq(restored['threshold']).all())
            self.assertEqual(len(restored['feature_names']), 30 if candidate.endswith('_route') else 21)


class RollingDecisionTests(unittest.TestCase):
    def setUp(self):
        self.validation = pd.DataFrame({
            'prediction_time': pd.to_datetime(np.repeat(['2017-09-01', '2017-10-01', '2017-11-01'], 4)),
            'delayed': [1, 1, 1, 0] * 3,
        })
        self.evaluation = pd.DataFrame({
            'prediction_time': pd.Timestamp('2018-02-01'),
            'delayed': [1, 0, 1, 0, 1, 0],
        })
        # Model versions can emit different score scales from one month to another.
        # The first month's high scores alone satisfy the pooled recall target.
        base = np.array([.95, .90, .85, .80, .20, .15, .10, .05, .40, .35, .30, .25])
        self.validation_scores = {candidate: base.copy() for candidate in CANDIDATES}
        self.evaluation_scores = {candidate: np.array([.9, .8, .7, .6, .3, .2])
                                  for candidate in CANDIDATES}
        self.result = decide_fold(self.validation, self.validation_scores,
                                  self.evaluation, self.evaluation_scores, min_recall=.30)

    def test_pooled_score_scale_can_hide_weak_month_but_monthly_floor_does_not(self):
        self.assertEqual(PRIMARY_STRATEGY, 'every_month_floor')
        for candidate in CANDIDATES:
            strategies = self.result['models'][candidate]['strategies']
            pooled = strategies['pooled_3months']
            monthly = strategies['every_month_floor']
            self.assertEqual(pooled['threshold'], .85)
            self.assertGreaterEqual(pooled['validation']['recall'], .30)
            self.assertEqual(pooled['validation_by_month']['2017-10']['recall'], 0.0)
            self.assertEqual(pooled['validation_by_month']['2017-11']['recall'], 0.0)
            self.assertEqual(monthly['threshold'], .20)
            self.assertLessEqual(monthly['threshold'], pooled['threshold'])
            self.assertTrue(all(row['recall'] >= .30
                                for row in monthly['validation_by_month'].values()))
            self.assertEqual(strategies['recent_month']['threshold'], .40)

    def test_threshold_equality_includes_all_ties_and_monthly_selection_scope_is_correct(self):
        tied = {candidate: np.array([.8, .5, .5, .5, .6, .4, .4, .4, .7, .4, .4, .4])
                for candidate in CANDIDATES}
        result = decide_fold(self.validation, tied, self.evaluation,
                             self.evaluation_scores, min_recall=.50)
        labels = self.validation.delayed.to_numpy()
        recent = self.validation.prediction_time.dt.strftime('%Y-%m').eq('2017-11').to_numpy()
        for candidate in CANDIDATES:
            strategies = result['models'][candidate]['strategies']
            monthly = strategies['every_month_floor']
            self.assertEqual(monthly['threshold'], .4)
            self.assertTrue(np.all(tied[candidate][tied[candidate] == .4] >= monthly['threshold']))
            self.assertEqual(monthly['validation'], binary_metrics(labels, tied[candidate], .4))
            self.assertEqual(monthly['validation']['confusion_matrix'], [[0, 3], [0, 9]])
            latest = strategies['recent_month']
            self.assertEqual(latest['selection_validation'],
                             binary_metrics(labels[recent], tied[candidate][recent], latest['threshold']))
            self.assertEqual(latest['selection_validation']['rows'], 4)
            for strategy in ('pooled_3months', 'every_month_floor'):
                self.assertEqual(strategies[strategy]['selection_validation'],
                                 strategies[strategy]['validation'])
                self.assertEqual(strategies[strategy]['selection_validation']['rows'], 12)

    def test_evaluation_labels_and_scores_cannot_change_thresholds_or_model_selection(self):
        changed_evaluation = self.evaluation.copy()
        changed_evaluation['delayed'] = 1 - changed_evaluation.delayed
        changed_evaluation['prediction_time'] = pd.Timestamp('2099-01-01')
        changed_scores = {candidate: 1 - values for candidate, values in self.evaluation_scores.items()}
        changed = decide_fold(self.validation, self.validation_scores,
                              changed_evaluation, changed_scores, min_recall=.30)
        self.assertEqual(self.result['selected_models'], changed['selected_models'])
        evaluation_changed = False
        for candidate in CANDIDATES:
            for strategy in STRATEGIES:
                before = self.result['models'][candidate]['strategies'][strategy]
                after = changed['models'][candidate]['strategies'][strategy]
                evaluation_changed |= before['evaluation'] != after['evaluation']
                for key in ('threshold', 'threshold_policy', 'selection_scope',
                            'selection_validation', 'validation', 'validation_by_month',
                            'minimum_validation_month_recall'):
                    self.assertEqual(before[key], after[key])
        self.assertTrue(evaluation_changed)

    def test_decisions_are_deterministic_under_candidate_score_dict_order(self):
        changed = decide_fold(self.validation,
                              dict(reversed(list(self.validation_scores.items()))),
                              self.evaluation,
                              dict(reversed(list(self.evaluation_scores.items()))), min_recall=.30)
        self.assertEqual(self.result, changed)
        for strategy in STRATEGIES:
            self.assertEqual(self.result['selected_models'][strategy], CANDIDATES[0])

    def test_shuffling_joined_validation_rows_preserves_thresholds_and_selection(self):
        order = np.array([11, 4, 0, 8, 7, 2, 9, 3, 5, 10, 1, 6])
        shuffled = self.validation.iloc[order].copy()
        shuffled.index = [0] * len(shuffled)
        reordered_scores = {candidate: values[order] for candidate, values in self.validation_scores.items()}
        actual = decide_fold(shuffled, reordered_scores, self.evaluation,
                             self.evaluation_scores, min_recall=.30)
        self.assertEqual(actual, self.result)


if __name__ == '__main__':
    unittest.main()
