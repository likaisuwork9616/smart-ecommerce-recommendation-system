"""Outcome-clock comparisons must keep model parameters and feature fits fixed."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import delay_budget_training as budget
from scripts import delay_outcome_training as outcome
from scripts import delay_pending_training as pending
from scripts.delay_outcome_clock import TRAINING_OUTCOME_COLUMN
from tests.test_delay_budget_training import decision_projection, month_frame
from tests.test_delay_pending_training import pending_frame


class OutcomeTrainingTests(unittest.TestCase):
    def test_nine_contrasts_keep_base_parameters_identical_across_clock_and_wait(self):
        self.assertEqual(len(outcome.NEW_CANDIDATES), 9)
        expected = {'delivery_wait0': ('delivery', 0), 'deadline_wait0': ('deadline', 0),
                    'deadline_wait30': ('deadline', 30)}
        for base in outcome.BASE_MODELS:
            parameter_sets = []
            for design, (clock, wait) in expected.items():
                candidate = f'{base}__{design}'
                with self.subTest(candidate=candidate):
                    self.assertEqual(outcome.candidate_design(candidate), (base, clock, wait))
                    pipeline = outcome.make_candidate(candidate, seed=31, n_jobs=2)
                    parameters = pipeline.named_steps['classifier'].get_params(deep=False)
                    self.assertEqual(parameters['random_state'], 31)
                    self.assertIsNone(parameters.get('early_stopping_rounds'))
                    self.assertEqual(outcome.feature_names(candidate), pending.feature_names(base))
                    parameter_sets.append(parameters)
            self.assertEqual(parameter_sets[0], parameter_sets[1])
            self.assertEqual(parameter_sets[1], parameter_sets[2])
        with self.assertRaises(ValueError):
            outcome.candidate_design('random_forest_route')
        with self.assertRaises(ValueError):
            outcome.make_candidate(outcome.NEW_CANDIDATES[0], n_jobs=0)

    def test_all_nine_fits_ignore_outcome_clock_and_later_scoring_labels(self):
        train = pending_frame('2017-09')
        scoring = pending_frame('2018-02', rows=20)
        train[TRAINING_OUTCOME_COLUMN] = pd.Timestamp('2017-09-15')
        scoring[TRAINING_OUTCOME_COLUMN] = pd.Timestamp('2099-01-01')
        train.loc[0, 'item_count'] = np.nan
        for name in pending.NUMERIC_FEATURES:
            scoring[name] = 1000000.
        for name in pending.CATEGORICAL_FEATURES:
            scoring[name] = 'future_only'
        original_outcome_factory = outcome.make_candidate
        original_pending_factory = pending.make_candidate

        def shrink(pipeline):
            parameters = pipeline.named_steps['classifier'].get_params(deep=False)
            if 'n_estimators' in parameters:
                pipeline.set_params(classifier__n_estimators=3)
            if 'min_child_samples' in parameters:
                pipeline.set_params(classifier__min_child_samples=5)
            return pipeline

        def small_outcome(candidate, seed, n_jobs):
            return shrink(original_outcome_factory(candidate, seed, n_jobs))

        def small_pending(candidate, seed, n_jobs):
            return shrink(original_pending_factory(candidate, seed, n_jobs))

        for candidate in outcome.NEW_CANDIDATES:
            with self.subTest(candidate=candidate), patch.object(outcome, 'make_candidate', side_effect=small_outcome), \
                    patch.object(pending, 'make_candidate', side_effect=small_pending):
                pipeline, values, report = outcome.fit_version(train, scoring, candidate, n_jobs=1)
            numeric, categorical = outcome.feature_names(candidate)
            prep = pipeline.named_steps['preprocessor']
            self.assertEqual(list(prep.feature_names_in_), numeric + categorical)
            self.assertFalse(set(prep.feature_names_in_) & {'order_id', 'delayed', 'label_available_time',
                                                            TRAINING_OUTCOME_COLUMN, 'future_actual_delivery_days'})
            medians = prep.named_transformers_['numeric'].named_steps['imputer'].statistics_
            np.testing.assert_allclose(medians, np.nanmedian(train[numeric].to_numpy(), axis=0))
            for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only', categories)
            changed = scoring.copy()
            changed['delayed'] = 'outcome unavailable'
            changed['label_available_time'] = pd.Timestamp('2099-02-01')
            changed[TRAINING_OUTCOME_COLUMN] = pd.Timestamp('1900-01-01')
            np.testing.assert_array_equal(values, outcome.positive_probability(pipeline, outcome.prepare_input(changed, candidate)))
            self.assertEqual(report['training_jobs'], 1)
            self.assertTrue(np.isfinite(values).all())


class OutcomeHistoricalSelectorTests(unittest.TestCase):
    def test_twenty_four_candidates_five_groups_and_twenty_nine_summaries_use_only_history(self):
        validation = [month_frame(month) for month in ('2017-09', '2017-10', '2017-11')]
        evaluation = month_frame('2018-02')
        weak = np.tile(np.linspace(.01, .99, 50), 2)
        strong = 1 - weak
        winner = 'random_forest_route__deadline_wait0'
        historical_scores = [{candidate: strong if candidate == winner else weak
                              for candidate in outcome.ALL_CANDIDATES} for _ in validation]
        evaluation_scores = {candidate: strong if candidate == winner else weak for candidate in outcome.ALL_CANDIDATES}

        def decide(frame, scores):
            return budget.decide_ranking_fold(validation, historical_scores, frame, scores, '2018-02-01',
                                               candidate_order=outcome.ALL_CANDIDATES,
                                               selection_groups=outcome.SELECTION_GROUPS)

        experiment = decide(evaluation, evaluation_scores)
        self.assertEqual(len(experiment['models']), 24)
        self.assertEqual(set(experiment['selected_models']), set(outcome.SELECTION_GROUPS))
        self.assertEqual(len(experiment['selected_models']), 5)
        self.assertEqual(experiment['selected_models']['all_candidates'], winner)
        self.assertEqual(experiment['selected_models']['deadline_wait0'], winner)
        changed = evaluation.copy()
        changed['delayed'] = 1 - changed.delayed
        changed['label_available_time'] = pd.Timestamp('2099-01-01')
        changed_scores = {candidate: 1 - values for candidate, values in evaluation_scores.items()}
        self.assertEqual(decision_projection(experiment), decision_projection(decide(changed, changed_scores)))
        summary = budget.summarize([{'name': '2018-02', 'experiment': experiment}],
                                  candidate_order=outcome.ALL_CANDIDATES,
                                  selection_groups=outcome.SELECTION_GROUPS)
        self.assertEqual(len(summary), 29)
        primary = next(row for row in summary if row['model_or_selection'] == 'all_candidates')
        self.assertEqual(primary['selected_candidates'], [winner])
        self.assertEqual(primary['true_positives'], 10)
        self.assertEqual(primary['false_positives'], 0)
        self.assertAlmostEqual(primary['recall'], .5)


if __name__ == '__main__':
    unittest.main()
