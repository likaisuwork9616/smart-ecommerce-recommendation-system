"""Fixed-budget ranking must use train-only fits and historical decisions."""

import io
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_budget_training as training
from scripts.delay_budget_features import (
    CATEGORICAL_FEATURES, FEATURES, FEATURE_SET, NUMERIC_FEATURES,
)
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.predict_delay import build_inference_features, main as prediction_main, predict_features


def month_frame(month, rows=100):
    position = np.arange(rows)
    return pd.DataFrame({
        'order_id': [f'{month}-{index:03d}' for index in position],
        'prediction_time': pd.Timestamp(month + '-01') + pd.to_timedelta(position // 50, unit='D')
                           + pd.to_timedelta(position % 50, unit='m'),
        'label_available_time': pd.Timestamp(month + '-15'),
        'delayed': ((position % 50) < 10).astype(int),
    })


def decision_projection(experiment):
    return {
        'selected_models': experiment['selected_models'],
        'models': {candidate: {key: value for key, value in row.items()
                              if key not in ('development_evaluation', 'evaluation_batch')}
                   for candidate, row in experiment['models'].items()},
    }


def feature_frame(month, rows=120):
    frame = month_frame(month, rows)
    position = np.arange(rows)
    for index, name in enumerate(NUMERIC_FEATURES):
        frame[name] = position.astype(float) + index
    for name in CATEGORICAL_FEATURES:
        frame[name] = np.where(position % 2, 'train_a', 'train_b')
    frame['future_actual_delivery_days'] = frame.delayed * 9999.
    return frame


class RankingTrainingTests(unittest.TestCase):
    def test_all_new_candidates_fit_only_training_features_and_labels(self):
        train = feature_frame('2017-09')
        scoring = feature_frame('2018-02', rows=20)
        first_numeric = NUMERIC_FEATURES[0]
        train.loc[0, first_numeric] = np.nan
        scoring.loc[:, first_numeric] = 1000000.
        for name in CATEGORICAL_FEATURES:
            scoring[name] = 'future_only'
        factory = training.make_candidate

        def small_candidate(candidate, seed, n_jobs):
            pipeline = factory(candidate, seed, n_jobs)
            pipeline.set_params(classifier__n_estimators=3)
            if candidate.startswith('lightgbm'):
                pipeline.set_params(classifier__min_child_samples=5)
            return pipeline

        for candidate in training.NEW_CANDIDATES:
            with self.subTest(candidate=candidate), patch.object(training, 'make_candidate', side_effect=small_candidate):
                pipeline, values, report = training.fit_version(train, scoring, candidate, n_jobs=1)
            numeric, categorical = training.feature_names(candidate)
            preprocessor = pipeline.named_steps['preprocessor']
            self.assertEqual(list(preprocessor.feature_names_in_), numeric + categorical)
            self.assertNotIn('delayed', preprocessor.feature_names_in_)
            self.assertNotIn('label_available_time', preprocessor.feature_names_in_)
            self.assertNotIn('future_actual_delivery_days', preprocessor.feature_names_in_)
            statistics = preprocessor.named_transformers_['numeric'].named_steps['imputer'].statistics_
            np.testing.assert_allclose(statistics, np.nanmedian(train[numeric].to_numpy(), axis=0))
            onehot = preprocessor.named_transformers_['categorical'].named_steps['onehot']
            self.assertEqual(onehot.handle_unknown, 'ignore')
            for categories in onehot.categories_:
                self.assertNotIn('future_only', categories)
            self.assertEqual(values.shape, (len(scoring),))
            self.assertTrue(np.isfinite(values).all())
            self.assertEqual(report['prediction_jobs'], 1)
            changed = scoring.copy()
            changed['delayed'] = 'unknown outcome'
            changed['label_available_time'] = pd.Timestamp('2099-01-01')
            changed['future_actual_delivery_days'] = -9999.
            np.testing.assert_array_equal(
                values, training.positive_probability(pipeline, training.prepare_input(changed, candidate)),
            )

    def test_fixed_boosting_parameters_have_no_evaluation_early_stopping(self):
        for candidate in training.NEW_CANDIDATES:
            with self.subTest(candidate=candidate):
                pipeline = training.make_candidate(candidate, seed=17, n_jobs=2)
                parameters = pipeline.named_steps['classifier'].get_params(deep=False)
                self.assertEqual(parameters['random_state'], 17)
                self.assertEqual(parameters['n_jobs'], 2)
                self.assertIsNone(parameters.get('early_stopping_rounds'))
                if candidate.startswith(('lightgbm', 'xgboost')):
                    self.assertEqual(parameters['n_estimators'], 400)
                    self.assertEqual(parameters['learning_rate'], .05)
                if candidate.startswith('lightgbm'):
                    self.assertEqual(parameters['class_weight'], 'balanced' if candidate.endswith('_weighted') else None)
                    self.assertTrue(parameters['deterministic'])
                elif candidate.startswith('xgboost'):
                    self.assertEqual(parameters['objective'], 'binary:logistic')
                    self.assertEqual(parameters['tree_method'], 'hist')
        for candidate in ('unknown', 'random_forest_route'):
            with self.assertRaises(ValueError):
                training.make_candidate(candidate)
        with self.assertRaises(ValueError):
            training.make_candidate('lightgbm_budget', n_jobs=0)

    def test_feature_contract_excludes_all_metadata_and_outcomes(self):
        frame = feature_frame('2017-09')
        for candidate in training.ALL_CANDIDATES:
            with self.subTest(candidate=candidate):
                numeric, categorical = training.feature_names(candidate)
                features = training.prepare_input(frame, candidate)
                self.assertEqual(list(features), numeric + categorical)
                self.assertFalse(set(features) & {'order_id', 'delayed', 'label_available_time', 'prediction_time', 'future_actual_delivery_days'})
        self.assertEqual(len(FEATURES), 45)
        self.assertEqual(len(FEATURES), len(set(FEATURES)))


class HistoricalRankingDecisionTests(unittest.TestCase):
    def setUp(self):
        self.validation = [month_frame(month) for month in ('2017-09', '2017-10', '2017-11')]
        self.evaluation = month_frame('2018-02')
        self.cutoff = pd.Timestamp('2018-02-01')
        self.scores = [{candidate: np.tile(np.linspace(.99, .01, 50), 2)
                        for candidate in training.ALL_CANDIDATES} for _ in self.validation]
        self.evaluation_scores = {candidate: np.tile(np.linspace(.01, .99, 50), 2)
                                  for candidate in training.ALL_CANDIDATES}

    def decide(self, validation=None, evaluation=None, evaluation_scores=None):
        return training.decide_ranking_fold(
            self.validation if validation is None else validation, self.scores,
            self.evaluation if evaluation is None else evaluation,
            self.evaluation_scores if evaluation_scores is None else evaluation_scores, self.cutoff,
        )

    def test_evaluation_outcomes_and_scores_cannot_change_frozen_decisions(self):
        before = self.decide()
        evaluation = self.evaluation.copy()
        evaluation['delayed'] = 1 - evaluation.delayed
        evaluation['label_available_time'] = pd.Timestamp('2099-01-01')
        scores = {candidate: 1 - values for candidate, values in self.evaluation_scores.items()}
        after = self.decide(evaluation=evaluation, evaluation_scores=scores)
        self.assertEqual(decision_projection(before), decision_projection(after))
        for row in before['models'].values():
            self.assertEqual(row['evaluation_batch']['alerts'], 10)
            self.assertLessEqual(row['evaluation_batch']['maximum_daily_alert_rate'], .10)
        self.assertNotEqual(before['models'][training.ALL_CANDIDATES[0]]['development_evaluation'],
                            after['models'][training.ALL_CANDIDATES[0]]['development_evaluation'])

    def test_labels_at_cutoff_are_unknown_and_high_scores_still_consume_capacity(self):
        frame = self.validation[0].copy()
        frame.loc[0, 'label_available_time'] = self.cutoff
        frame.loc[1, 'label_available_time'] = self.cutoff + pd.Timedelta(days=1)
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[[0, 1], 'delayed'] = 'not available at selection'
        scores = self.scores[0][training.ALL_CANDIDATES[0]]
        result = training.score_validation(frame, scores, self.cutoff)
        self.assertEqual(result['full_batch']['scored_rows'], 100)
        self.assertEqual(result['full_batch']['capacity'], 10)
        self.assertEqual(result['full_batch']['alerts'], 10)
        self.assertEqual(result['full_batch']['unknown_outcome_alerts'], 2)
        metrics = result['known_outcome_metrics']
        self.assertEqual(metrics['rows'], 98)
        self.assertEqual(metrics['confusion_matrix'][1][1], 8)
        self.assertAlmostEqual(metrics['recall'], 8 / 18)
        changed = frame.copy()
        changed.loc[[0, 1], 'delayed'] = [1, 0]
        self.assertEqual(result, training.score_validation(changed, scores, self.cutoff))
        validation = [frame, *self.validation[1:]]
        original = self.decide(validation=validation)
        validation[0] = changed
        self.assertEqual(original, self.decide(validation=validation))

    def test_selector_prioritizes_worst_month_before_pooled_true_positives(self):
        first, second, third = training.ALL_CANDIDATES[:3]
        results = {
            first: {'minimum_validation_month_recall': .29, 'validation_true_positives': 999,
                    'validation_pooled_average_precision': .99},
            second: {'minimum_validation_month_recall': .30, 'validation_true_positives': 20,
                     'validation_pooled_average_precision': .10},
            third: {'minimum_validation_month_recall': .30, 'validation_true_positives': 21,
                    'validation_pooled_average_precision': .01},
        }
        self.assertEqual(training.select_candidate(results, (first, second)), second)
        self.assertEqual(training.select_candidate(results, (first, second, third)), third)
        results[second]['validation_true_positives'] = 21
        self.assertEqual(training.select_candidate(results, (first, second, third)), second)
        results[second]['validation_pooled_average_precision'] = .01
        self.assertEqual(training.select_candidate(results, (third, second)), second)
        with self.assertRaises(ValueError):
            training.select_candidate(results, ())

    def test_overlapping_ids_duplicate_months_and_invalid_calendar_order_fail(self):
        for overlap in ('historical', 'evaluation', 'duplicate'):
            validation = [frame.copy() for frame in self.validation]
            evaluation = self.evaluation.copy()
            if overlap == 'historical':
                validation[1].loc[0, 'order_id'] = validation[0].loc[0, 'order_id']
            elif overlap == 'evaluation':
                evaluation.loc[0, 'order_id'] = validation[0].loc[0, 'order_id']
            else:
                validation[0].loc[1, 'order_id'] = validation[0].loc[0, 'order_id']
            with self.subTest(overlap=overlap), self.assertRaises(ValueError):
                self.decide(validation=validation, evaluation=evaluation)
        for validation in (self.validation[:2], self.validation[::-1],
                           [self.validation[0], self.validation[0], self.validation[2]],
                           [self.validation[0], self.validation[1], month_frame('2018-02')]):
            with self.subTest(months=[str(frame.prediction_time.iloc[0]) for frame in validation]), self.assertRaises(ValueError):
                self.decide(validation=validation)
        with self.assertRaises(ValueError):
            self.decide(evaluation=month_frame('2018-03'))
        missing = self.validation[0].copy()
        missing['label_available_time'] = self.cutoff
        with self.assertRaises(ValueError):
            training.score_validation(missing, self.scores[0][training.ALL_CANDIDATES[0]], self.cutoff)


class ContractProbabilityPipeline:
    classes_ = np.array([1, 0])

    def predict_proba(self, frame):
        self.received_columns = list(frame)
        self.received_customer_zip = frame['customer_zip_prefix3'].tolist()
        self.received_seller_zip = frame['primary_seller_zip_prefix3'].tolist()
        values = frame[NUMERIC_FEATURES[0]].to_numpy(dtype=float)
        return np.column_stack([values, 1 - values])


class BudgetRankingInferenceTests(unittest.TestCase):
    def test_45_feature_artifact_roundtrip_preserves_full_day_cap_and_whitelist(self):
        frame = feature_frame('2018-02', rows=100)
        frame[NUMERIC_FEATURES[0]] = np.tile(np.linspace(.01, .99, 50), 2)
        frame.index = [7] * len(frame)
        artifact = {'format_version': 1, 'pipeline': ContractProbabilityPipeline(),
                    'feature_set': FEATURE_SET, 'selected_model': 'synthetic_budget_only',
                    'feature_names': FEATURES, 'numeric_features': NUMERIC_FEATURES,
                    'categorical_features': CATEGORICAL_FEATURES, 'threshold': 0.,
                    'daily_alert_cap': .10}
        with self.assertRaises(ValueError):
            predict_features(artifact, frame)
        stream = io.BytesIO()
        joblib.dump(artifact, stream)
        stream.seek(0)
        restored = joblib.load(stream)
        result = predict_features(restored, frame, complete_daily_batches=True)
        self.assertEqual(restored['pipeline'].received_columns, FEATURES)
        self.assertEqual(result.index.tolist(), frame.index.tolist())
        self.assertEqual(int(result.predicted_delayed.sum()), 10)
        expected = apply_alert_policy(frame, frame[NUMERIC_FEATURES[0]], 0., .10)
        np.testing.assert_array_equal(result.predicted_delayed, expected.astype(int))
        changed = frame.copy()
        changed['delayed'] = 'outcome unavailable'
        changed['label_available_time'] = pd.Timestamp('2099-01-01')
        changed['future_actual_delivery_days'] = -999999.
        pd.testing.assert_frame_equal(result, predict_features(restored, changed, complete_daily_batches=True))

    def test_raw_inference_dispatch_uses_saved_budget_feature_contract(self):
        expected = feature_frame('2018-02')
        tables = {'known': 'source tables'}
        with patch('scripts.delay_budget_features.build_budget_order_features', return_value=expected) as builder:
            actual = build_inference_features({'feature_set': FEATURE_SET}, tables)
        self.assertIs(actual, expected)
        builder.assert_called_once_with(tables)

    def test_csv_cli_preserves_leading_zero_postal_categories(self):
        frame = feature_frame('2018-02', rows=100)
        frame[NUMERIC_FEATURES[0]] = np.tile(np.linspace(.01, .99, 50), 2)
        frame['customer_zip_prefix3'] = np.tile(['001', '010', '100', '999'], 25)
        frame['primary_seller_zip_prefix3'] = np.tile(['009', '020', '200', '998'], 25)
        csv_text = frame.to_csv(index=False)
        artifact = {'format_version': 1, 'pipeline': ContractProbabilityPipeline(),
                    'feature_set': FEATURE_SET, 'selected_model': 'synthetic_budget_only',
                    'feature_names': FEATURES, 'numeric_features': NUMERIC_FEATURES,
                    'categorical_features': CATEGORICAL_FEATURES, 'threshold': 0.,
                    'daily_alert_cap': .10}
        actual_read_csv = pd.read_csv

        def read_in_memory_csv(path, **kwargs):
            return actual_read_csv(io.StringIO(csv_text), **kwargs)

        with patch('sys.argv', ['predict_delay.py', '--model', 'synthetic.joblib',
                               '--features-csv', 'complete_days.csv', '--complete-daily-batches']), \
                patch('scripts.predict_delay.joblib.load', return_value=artifact), \
                patch('scripts.predict_delay.pd.read_csv', side_effect=read_in_memory_csv), \
                redirect_stdout(io.StringIO()):
            prediction_main()
        self.assertEqual(artifact['pipeline'].received_customer_zip, frame.customer_zip_prefix3.tolist())
        self.assertEqual(artifact['pipeline'].received_seller_zip, frame.primary_seller_zip_prefix3.tolist())


if __name__ == '__main__':
    unittest.main()
