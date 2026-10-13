"""Verify matched validation strategies and their decision/inference boundaries."""
import copy
import io
from collections import Counter
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from scripts.compare_multimonth_validation import (
    CANDIDATES, STRATEGIES, feature_names, make_candidate, prepare_input,
    run_experiment, select_model,
)
from scripts.delay_alert_policy import choose_recall_threshold
from scripts.predict_delay import predict_features
from scripts.train_delay_model import binary_metrics


def feature_frame(rows=144):
    """Include outcome metadata that must never enter the feature matrix."""
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
    frame['label_available_time'] = pd.Timestamp('2017-11-01')
    frame['future_delivery_delay'] = position * 1000.0
    return frame


class MultimonthExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frame = feature_frame()
        cls.splits = {'train': frame.iloc[:72].copy(),
                      'validation': frame.iloc[72:120].copy(),
                      'evaluation': frame.iloc[120:].copy()}
        for offset, month in enumerate(('2017-07-01', '2017-08-01', '2017-09-01')):
            cls.splits['validation'].loc[72 + offset * 16:87 + offset * 16,
                                         'prediction_time'] = pd.Timestamp(month)
        cls.splits['evaluation']['prediction_time'] = pd.Timestamp('2017-12-01')
        cls.changed = {name: part.copy() for name, part in cls.splits.items()}
        cls.changed['evaluation']['delayed'] = 1 - cls.changed['evaluation']['delayed']
        cls.changed['evaluation']['label_available_time'] = pd.Timestamp('2099-01-01')
        cls.changed['evaluation']['prediction_time'] = pd.Timestamp('2098-01-01')
        cls.changed['evaluation']['order_id'] = 'changed-' + cls.changed['evaluation'].order_id
        cls.changed['evaluation']['future_delivery_delay'] = -1e12
        cls.created, cls.fit_calls = [], []
        original_fit = Pipeline.fit

        def small_candidate(candidate, seed, n_jobs):
            pipeline = make_candidate(candidate, seed, n_jobs)
            if candidate.startswith('random_forest'):
                pipeline.set_params(classifier__n_estimators=16,
                                    classifier__min_samples_leaf=2)
            cls.created.append((candidate, pipeline))
            return pipeline

        def record_fit(pipeline, features, labels, **params):
            cls.fit_calls.append((pipeline, features.copy(), labels.copy()))
            return original_fit(pipeline, features, labels, **params)

        with patch('scripts.compare_multimonth_validation.make_candidate',
                   side_effect=small_candidate), patch.object(Pipeline, 'fit', new=record_fit), \
                redirect_stdout(io.StringIO()):
            cls.result, cls.pipelines, cls.scores = run_experiment(
                cls.splits, min_recall=.30, seed=42, n_jobs=1)
            cls.altered, cls.altered_pipelines, cls.altered_scores = run_experiment(
                cls.changed, min_recall=.30, seed=42, n_jobs=1)

    def test_selection_uses_only_designated_validation_scope_with_stable_ties(self):
        models = {candidate: {'strategies': {strategy: {
            'selection_validation': {
                'predicted_positive_rows': 30,
                'confusion_matrix': [[100, 21], [20, 9]],
                'average_precision': .5,
            },
            'validation': {'predicted_positive_rows': 0},
            'evaluation': {'predicted_positive_rows': 0},
        } for strategy in STRATEGIES}} for candidate in CANDIDATES}
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                self.assertEqual(select_model(models, strategy), CANDIDATES[0])
                changed = copy.deepcopy(models)
                changed['logistic_route']['strategies'][strategy]['selection_validation'][
                    'predicted_positive_rows'] = 29
                self.assertEqual(select_model(changed, strategy), 'logistic_route')
                changed = copy.deepcopy(models)
                changed['logistic_route']['strategies'][strategy]['selection_validation'][
                    'confusion_matrix'][0][1] = 20
                self.assertEqual(select_model(changed, strategy), 'logistic_route')
                changed = copy.deepcopy(models)
                changed['logistic_route']['strategies'][strategy]['selection_validation'][
                    'average_precision'] = .6
                for candidate in CANDIDATES:
                    decision = changed[candidate]['strategies'][strategy]
                    decision['validation'] = {'malicious_pooled_metric': candidate}
                    decision['evaluation'] = {'entirely_changed_evaluation': candidate}
                    decision['validation_by_month'] = {'unused': {'recall': 0}}
                self.assertEqual(select_model(changed, strategy), 'logistic_route')
        with self.assertRaises(ValueError):
            select_model(models, 'unknown')

    def test_all_three_strategies_share_one_train_only_fit_per_candidate(self):
        self.assertEqual(Counter(name for name, _ in self.created),
                         Counter({name: 2 for name in CANDIDATES}))
        self.assertEqual(len(self.fit_calls), 2 * len(CANDIDATES))
        counts = Counter(id(pipeline) for pipeline, _, _ in self.fit_calls)
        for candidate, pipeline in self.created:
            self.assertEqual(counts[id(pipeline)], 1)
            _, actual_features, actual_labels = next(
                call for call in self.fit_calls if call[0] is pipeline)
            pd.testing.assert_frame_equal(actual_features,
                                          prepare_input(self.splits['train'], candidate))
            pd.testing.assert_series_equal(actual_labels, self.splits['train'].delayed)
            self.assertFalse({'delayed', 'label_available_time', 'prediction_time',
                              'order_id', 'future_delivery_delay'}.intersection(actual_features))
        for candidate in CANDIDATES:
            self.assertEqual(set(self.result['models'][candidate]['strategies']), set(STRATEGIES))

    def test_evaluation_outcomes_and_metadata_cannot_change_fit_or_decisions(self):
        self.assertEqual(self.result['selected_models'], self.altered['selected_models'])
        for candidate in CANDIDATES:
            before, after = self.result['models'][candidate], self.altered['models'][candidate]
            self.assertEqual(before['classifier_parameters'], after['classifier_parameters'])
            for strategy in STRATEGIES:
                for key in ('threshold', 'threshold_policy', 'selection_scope',
                            'selection_validation', 'validation', 'validation_by_month',
                            'minimum_validation_month_recall'):
                    self.assertEqual(before['strategies'][strategy][key],
                                     after['strategies'][strategy][key])
            for partition in ('validation', 'evaluation'):
                np.testing.assert_array_equal(self.scores[candidate][partition],
                                              self.altered_scores[candidate][partition])
            first = self.pipelines[candidate].named_steps['classifier']
            second = self.altered_pipelines[candidate].named_steps['classifier']
            if candidate.startswith('random_forest'):
                self.assertEqual(first.n_jobs, 1)
                for tree, changed_tree in zip(first.estimators_, second.estimators_):
                    np.testing.assert_array_equal(tree.tree_.threshold, changed_tree.tree_.threshold)
                    np.testing.assert_array_equal(tree.tree_.value, changed_tree.tree_.value)
            else:
                np.testing.assert_array_equal(first.coef_, second.coef_)
                np.testing.assert_array_equal(first.intercept_, second.intercept_)

    def test_monthly_floor_and_recent_scope_use_the_expected_validation_rows(self):
        validation = self.splits['validation']
        recent = validation.prediction_time.dt.strftime('%Y-%m').eq('2017-09').to_numpy()
        for candidate in CANDIDATES:
            decisions = self.result['models'][candidate]['strategies']
            floor = decisions['every_month_floor']
            self.assertEqual(set(floor['validation_by_month']),
                             {'2017-07', '2017-08', '2017-09'})
            self.assertLessEqual(floor['threshold'], decisions['pooled_3months']['threshold'])
            for month in floor['validation_by_month'].values():
                self.assertGreaterEqual(month['recall'], .30)
            scores = self.scores[candidate]['validation']
            recent_labels, recent_scores = validation.delayed.to_numpy()[recent], scores[recent]
            expected_threshold, _ = choose_recall_threshold(recent_labels, recent_scores, .30)
            latest = decisions['recent_month']
            self.assertEqual(latest['threshold'], expected_threshold)
            self.assertEqual(latest['selection_scope'], 'latest validation calendar month')
            self.assertEqual(latest['selection_validation'],
                             binary_metrics(recent_labels, recent_scores, expected_threshold))
            self.assertEqual(latest['selection_validation']['rows'], 16)
            for strategy in ('pooled_3months', 'every_month_floor'):
                decision = decisions[strategy]
                self.assertEqual(decision['selection_scope'], 'all three validation months')
                self.assertEqual(decision['selection_validation'], decision['validation'])
                self.assertEqual(decision['selection_validation']['rows'], 48)

    def test_serialized_artifacts_preserve_existing_inference_contract(self):
        evaluation = self.splits['evaluation']
        for candidate in CANDIDATES:
            model = self.result['models'][candidate]
            numeric, categorical = feature_names(candidate)
            for strategy in STRATEGIES:
                with self.subTest(candidate=candidate, strategy=strategy):
                    threshold = model['strategies'][strategy]['threshold']
                    artifact = {'format_version': 1, 'selected_model': candidate,
                                'feature_set': model['feature_set'],
                                'pipeline': self.pipelines[candidate], 'threshold': threshold,
                                'feature_names': numeric + categorical, 'numeric_features': numeric,
                                'categorical_features': categorical,
                                'metadata': {'research_only': True, 'strategy': strategy}}
                    stream = io.BytesIO()
                    joblib.dump(artifact, stream, compress=3)
                    stream.seek(0)
                    restored = joblib.load(stream)
                    inference = predict_features(restored, evaluation)
                    np.testing.assert_array_equal(inference.delay_score,
                                                  self.scores[candidate]['evaluation'])
                    np.testing.assert_array_equal(inference.predicted_delayed,
                        (self.scores[candidate]['evaluation'] >= threshold).astype(int))
                    np.testing.assert_array_equal(inference.order_id, evaluation.order_id)
                    self.assertTrue(inference.threshold.eq(threshold).all())
                    expected = 30 if candidate.endswith('_route') else 21
                    self.assertEqual(len(restored['feature_names']), expected)
                    if candidate.startswith('random_forest'):
                        self.assertEqual(restored['pipeline'].named_steps['classifier'].n_jobs, 1)


if __name__ == '__main__':
    unittest.main()
