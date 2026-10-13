"""Pending-context fits and daily ranking must remain historical and causal."""

import io
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_budget_training as budget
from scripts import delay_pending_training as pending
from scripts.delay_pending_features import CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES, PENDING_NUMERIC_FEATURES
from tests.test_delay_budget_training import decision_projection, feature_frame, month_frame


def pending_frame(month, rows=120):
    frame = feature_frame(month, rows)
    for offset, name in enumerate(PENDING_NUMERIC_FEATURES):
        frame[name] = np.arange(rows, dtype=float) + offset
    return frame


class RecordingRanker:
    """Observe the actual transformed training rows and forwarded day groups."""

    instances = []

    def __init__(self, **kwargs):
        self.parameters = kwargs
        self.instances.append(self)

    def fit(self, X, y, group):
        self.training_values = X.copy()
        self.training_labels = np.asarray(y).copy()
        self.group = group
        return self

    def predict(self, X, **kwargs):
        first = X[:, 0]
        return (first.toarray().ravel() if hasattr(first, 'toarray') else np.asarray(first).ravel()) * .001


class MarginRanker:
    def __init__(self, margins):
        self.margins = np.asarray(margins, dtype=float)

    def predict(self, X, **kwargs):
        return self.margins.copy()


class DailyRankerTests(unittest.TestCase):
    def test_binary_ranking_objective_receives_only_supplied_mature_training_groups(self):
        X = np.arange(12).reshape(6, 2)
        labels = np.array([0, 1, 0, 0, 1, 0])
        groups = np.array([2, 4], dtype=int)
        with patch('scripts.delay_pending_training.LGBMRanker', RecordingRanker):
            model = pending.DailyRankClassifier(n_estimators=3, n_jobs=1).fit(X, labels, group=groups)
        received = model.ranker_
        np.testing.assert_array_equal(received.training_values, X)
        np.testing.assert_array_equal(received.training_labels, labels)
        self.assertEqual(received.group, [2, 4])
        self.assertEqual(received.parameters['objective'], 'lambdarank')
        self.assertEqual(received.parameters['label_gain'], [0, 1])
        self.assertEqual(received.parameters['lambdarank_truncation_level'], 20)
        self.assertNotIn('eval_set', received.parameters)
        self.assertNotIn('early_stopping_rounds', received.parameters)
        np.testing.assert_array_equal(model.classes_, [0, 1])

    def test_invalid_labels_and_nonpositive_incomplete_day_groups_fail(self):
        invalid = (
            ([0, 0], [2]), ([1, 1], [2]), ([0, 2], [2]),
            ([0, 1], None), ([0, 1], [0, 2]), ([0, 1], [-1, 3]),
            ([0, 1], [1]), ([0, 1], [1., 1.]), ([0, 1], [[1, 1]]),
            ([[0], [1]], [2]),
        )
        for labels, groups in invalid:
            with self.subTest(labels=labels, groups=groups), self.assertRaises(ValueError):
                pending.DailyRankClassifier(n_jobs=1).fit(np.zeros((2, 1)), labels, group=groups)

    def test_margin_sigmoid_is_monotone_bounded_and_serializes_without_probability_claim(self):
        margins = np.array([-10., -1., 0., 1., 10.])
        model = pending.DailyRankClassifier(n_jobs=1)
        model.ranker_ = MarginRanker(margins)
        model.classes_ = np.array([0, 1])
        actual = model.predict_proba(np.zeros((5, 2)))
        np.testing.assert_allclose(actual[:, 1], 1 / (1 + np.exp(-margins)))
        np.testing.assert_allclose(actual.sum(axis=1), 1.)
        self.assertTrue((np.diff(actual[:, 1]) > 0).all())
        self.assertTrue(((actual > 0) & (actual < 1)).all())
        stream = io.BytesIO()
        joblib.dump(model, stream)
        stream.seek(0)
        np.testing.assert_array_equal(joblib.load(stream).predict_proba(np.zeros((5, 2))), actual)

    def test_nonfinite_margins_and_saturation_cannot_silently_change_daily_ordering(self):
        for margins in ([40., 50.], [-1000., -900.], [0., np.nan], [0., np.inf]):
            model = pending.DailyRankClassifier(n_jobs=1)
            model.ranker_ = MarginRanker(margins)
            with self.subTest(margins=margins), self.assertRaises(ValueError):
                model.predict_proba(np.zeros((2, 1)))
        # Genuine identical margins may remain tied; those did not lose rank.
        model = pending.DailyRankClassifier(n_jobs=1)
        model.ranker_ = MarginRanker([1., 1., 2.])
        actual = model.predict_proba(np.zeros((3, 1)))[:, 1]
        self.assertEqual(actual[0], actual[1])
        self.assertGreater(actual[2], actual[1])


class PendingTrainingTests(unittest.TestCase):
    def test_ranker_training_rows_are_sorted_into_contiguous_approval_days(self):
        original = pending_frame('2017-09')
        train = original.sample(frac=1., random_state=19).reset_index(drop=True)
        scoring = pending_frame('2018-02', rows=20)
        with patch('scripts.delay_pending_training.LGBMRanker', RecordingRanker):
            pipeline, values, report = pending.fit_version(train, scoring, 'lambdarank_pending', n_jobs=1)
        received = pipeline.named_steps['classifier'].ranker_
        sorted_train = train.sort_values(['prediction_time', 'order_id'], kind='stable')
        expected_groups = sorted_train.groupby(sorted_train.prediction_time.dt.normalize(), sort=True).size().tolist()
        self.assertEqual(received.group, expected_groups)
        self.assertEqual(report['daily_training_groups'], expected_groups)
        np.testing.assert_array_equal(received.training_labels, sorted_train.delayed.to_numpy())
        transformed = received.training_values
        first = transformed[:, 0]
        np.testing.assert_array_equal(first.toarray().ravel() if hasattr(first, 'toarray') else np.asarray(first).ravel(),
                                      sorted_train[NUMERIC_FEATURES[0]].to_numpy())
        self.assertEqual(values.shape, (20,))
        self.assertEqual(len(received.training_labels), len(train))
        self.assertNotEqual(len(received.training_labels), len(train) + len(scoring))

    def test_all_five_candidates_use_train_only_imputers_categories_and_metadata_whitelist(self):
        train = pending_frame('2017-09')
        scoring = pending_frame('2018-02', rows=20)
        train.loc[0, NUMERIC_FEATURES[0]] = np.nan
        for name in NUMERIC_FEATURES:
            scoring[name] = 99999.
        for name in CATEGORICAL_FEATURES:
            scoring[name] = 'future_only'
        factory = pending.make_candidate

        def small_candidate(candidate, seed, n_jobs):
            pipeline = factory(candidate, seed, n_jobs)
            if not candidate.startswith('logistic'):
                pipeline.set_params(classifier__n_estimators=3)
                if candidate.startswith(('lightgbm', 'lambdarank')):
                    pipeline.set_params(classifier__min_child_samples=5)
            return pipeline

        for candidate in pending.NEW_CANDIDATES:
            with self.subTest(candidate=candidate), patch.object(pending, 'make_candidate', side_effect=small_candidate):
                pipeline, values, report = pending.fit_version(train, scoring, candidate, n_jobs=1)
            numeric, categorical = pending.feature_names(candidate)
            prep = pipeline.named_steps['preprocessor']
            self.assertEqual(list(prep.feature_names_in_), numeric + categorical)
            self.assertFalse(set(prep.feature_names_in_) & {'delayed', 'order_id', 'label_available_time', 'future_actual_delivery_days'})
            actual_medians = prep.named_transformers_['numeric'].named_steps['imputer'].statistics_
            np.testing.assert_allclose(actual_medians, np.nanmedian(train[numeric].to_numpy(), axis=0))
            encoder = prep.named_transformers_['categorical'].named_steps['onehot']
            for categories in encoder.categories_:
                self.assertNotIn('future_only', categories)
            self.assertEqual(encoder.handle_unknown, 'ignore')
            self.assertTrue(np.isfinite(values).all())
            self.assertEqual(values.shape, (len(scoring),))
            changed = scoring.copy()
            changed['delayed'] = 'unseen outcome'
            changed['label_available_time'] = pd.Timestamp('2099-01-01')
            np.testing.assert_array_equal(values, pending.positive_probability(pipeline, pending.prepare_input(changed, candidate)))
            if candidate.startswith('lambdarank'):
                self.assertEqual(sum(report['daily_training_groups']), len(train))
            else:
                self.assertIsNone(report['daily_training_groups'])
        self.assertEqual(len(FEATURES), 60)


class GeneralizedHistoricalSelectorTests(unittest.TestCase):
    def test_fifteen_candidates_custom_groups_and_summary_preserve_evaluation_isolation(self):
        validation = [month_frame(month) for month in ('2017-09', '2017-10', '2017-11')]
        evaluation = month_frame('2018-02')
        weak = np.tile(np.linspace(.01, .99, 50), 2)
        strong = 1 - weak
        winner = 'lambdarank_pending'
        historical_scores = [{candidate: strong if candidate == winner else weak
                              for candidate in pending.ALL_CANDIDATES} for _ in validation]
        evaluation_scores = {candidate: strong if candidate == winner else weak for candidate in pending.ALL_CANDIDATES}

        def decide(frame, scores):
            return budget.decide_ranking_fold(validation, historical_scores, frame, scores, '2018-02-01',
                                               candidate_order=pending.ALL_CANDIDATES,
                                               selection_groups=pending.SELECTION_GROUPS)

        experiment = decide(evaluation, evaluation_scores)
        self.assertEqual(len(experiment['models']), 15)
        self.assertEqual(set(experiment['selected_models']), set(pending.SELECTION_GROUPS))
        self.assertEqual(experiment['selected_models']['all_candidates'], winner)
        self.assertEqual(experiment['selected_models']['daily_rankers'], winner)
        changed = evaluation.copy()
        changed['delayed'] = 1 - changed.delayed
        changed_scores = {candidate: 1 - values for candidate, values in evaluation_scores.items()}
        self.assertEqual(decision_projection(experiment), decision_projection(decide(changed, changed_scores)))
        summary = budget.summarize([{'name': '2018-02', 'experiment': experiment}],
                                  candidate_order=pending.ALL_CANDIDATES,
                                  selection_groups=pending.SELECTION_GROUPS)
        self.assertEqual(len(summary), 19)
        primary = next(row for row in summary if row['model_or_selection'] == 'all_candidates')
        self.assertEqual(primary['selected_candidates'], [winner])
        self.assertEqual(primary['true_positives'], 10)
        self.assertEqual(primary['false_positives'], 0)
        self.assertAlmostEqual(primary['recall'], .5)


if __name__ == '__main__':
    unittest.main()
