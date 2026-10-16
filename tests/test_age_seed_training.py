"""Both feature packages refit at all five fixed paired seeds."""
from copy import deepcopy
import io
import unittest
from unittest.mock import patch

import joblib
import numpy as np

from scripts import delay_age_seed_training as training
from scripts import delay_objective_training as objective
from scripts import delay_unobserved_handover_age_training as original_age
from scripts import delay_rank_focus as original_baseline
from tests.test_delay_unobserved_handover_age_training import frame
from tests.test_delay_objective_training import RecordingRanker


class AgeSeedTrainingTests(unittest.TestCase):
    def test_all_ten_designs_change_only_random_state(self):
        self.assertEqual(training.SEEDS, (11, 29, 42, 73, 101))
        reference = training.make_candidate(training.BASELINE, 42)
        parameters = reference.named_steps['classifier'].get_params(deep=False)
        for seed in training.SEEDS:
            for candidate, count in zip(training.MATCHED, (101, 102), strict=True):
                with self.subTest(seed=seed, candidate=candidate):
                    pipeline = training.make_candidate(candidate, seed)
                    actual = pipeline.named_steps['classifier'].get_params(deep=False)
                    expected = {**parameters, 'random_state': seed}
                    self.assertEqual(actual, expected)
                    self.assertEqual(sum(map(len, training.feature_names(candidate))), count)
                    for left, right in zip(reference.named_steps['preprocessor'].transformers,
                                           pipeline.named_steps['preprocessor'].transformers, strict=True):
                        for (ln, ls), (rn, rs) in zip(left[1].steps, right[1].steps, strict=True):
                            self.assertEqual((ln, type(ls), ls.get_params(deep=False)),
                                             (rn, type(rs), rs.get_params(deep=False)))
        old_num, old_cat = training.feature_names(training.BASELINE)
        new_num, new_cat = training.feature_names(training.AGE)
        self.assertEqual(new_num, old_num + ['seller_unobserved_handover_pending_age_p90_hours_90d'])
        self.assertEqual(new_cat, old_cat)

    def test_unlisted_seed_bool_and_unknown_candidate_are_rejected(self):
        for seed in (True, np.bool_(True), 12, 42., '42', None):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                training.make_candidate(training.BASELINE, seed)
        with self.assertRaises(ValueError):
            training.make_candidate('unlisted', 42)
        with self.assertRaises(ValueError):
            training.make_candidate(training.BASELINE, 42, n_jobs=0)

    def test_all_seeds_fit_identical_mature_queries_and_training_only_statistics(self):
        train = frame('2017-09').sample(frac=1., random_state=8).reset_index(drop=True)
        train.loc[0, training.ADDED_FEATURES[0]] = np.nan
        scoring = frame('2018-02', 20)
        numeric, categorical = training.feature_names(training.AGE)
        scoring[numeric], scoring[categorical] = 999999., 'future_only'
        _, layout = training.training_layout(train)
        fingerprints = set()
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            for seed in training.SEEDS:
                for candidate in training.MATCHED:
                    pipeline, _, fit = training.fit_version(train, scoring, candidate, seed)
                    fingerprints.add((fit['training_order_sha256'], fit['training_labels_sha256']))
                    self.assertEqual(fit['daily_training_groups'], layout['daily_training_groups'])
                    classifier = pipeline.named_steps['classifier']
                    self.assertEqual(classifier.ranker_.fit_parameters, {'group': layout['daily_training_groups']})
                    self.assertEqual(classifier.ranker_.parameters['random_state'], seed)
                    prep = pipeline.named_steps['preprocessor']
                    selected_numeric = training.feature_names(candidate)[0]
                    np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                               np.nanmedian(train[selected_numeric].to_numpy(dtype=float), axis=0))
                    for values in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                        self.assertNotIn('future_only', values)
                    self.assertEqual(fit['manually_added_missingness_indicators'], [])
                    self.assertEqual(fit['age_missing_indicator_from_original_imputer'], candidate == training.AGE)
        self.assertEqual(len(fingerprints), 1)

    def test_invalid_training_rows_and_changed_labels_change_the_layout(self):
        train = frame('2017-09')
        for invalid in (train.iloc[:0], train.assign(order_id=None), train.assign(order_id='duplicate'),
                        train.assign(prediction_time=None), train.assign(delayed='unknown')):
            with self.assertRaises(ValueError):
                training.training_layout(invalid)
        _, first = training.training_layout(train)
        _, second = training.training_layout(train.assign(delayed=1-train.delayed))
        self.assertEqual(first['training_order_sha256'], second['training_order_sha256'])
        self.assertNotEqual(first['training_labels_sha256'], second['training_labels_sha256'])

    def test_seed42_real_refits_reproduce_each_original_fit_and_serialize(self):
        train, scoring = frame('2017-09'), frame('2018-02', 20)
        train.loc[0, training.ADDED_FEATURES[0]] = np.nan
        factory = training.make_candidate
        original_age_factory = original_age.make_candidate
        original_base_factory = original_baseline.make_candidate
        def small(candidate, seed, n_jobs=2):
            return factory(candidate, seed, n_jobs).set_params(classifier__n_estimators=3)
        def old_age_small(candidate, seed=42, n_jobs=2):
            return original_age_factory(candidate, seed, n_jobs).set_params(classifier__n_estimators=3)
        def old_base_small(candidate, seed=42, n_jobs=2):
            return original_base_factory(candidate, seed, n_jobs).set_params(classifier__n_estimators=3)
        for candidate in training.MATCHED:
            with patch.object(training, 'make_candidate', side_effect=small):
                pipeline, scores, fit = training.fit_version(train, scoring, candidate, 42, n_jobs=1)
            if candidate == training.AGE:
                with patch.object(original_age, 'make_candidate', side_effect=old_age_small):
                    _, original_scores, _ = original_age.fit_version(train, scoring, candidate, n_jobs=1)
            else:
                with patch.object(original_baseline, 'make_candidate', side_effect=old_base_small):
                    _, original_scores, _ = original_baseline.fit_version(train, scoring, candidate, n_jobs=1)
            np.testing.assert_array_equal(scores, original_scores)
            self.assertEqual(fit['changed_classifier_parameters_vs_original'], [])
            stream = io.BytesIO()
            joblib.dump(pipeline, stream)
            stream.seek(0)
            restored = joblib.load(stream)
            np.testing.assert_array_equal(scores, training.positive_probability(restored, training.prepare_input(scoring, candidate)))

    def test_new_count_labels_and_future_events_never_enter_either_whitelist(self):
        data = frame('2017-09')
        changed = data.assign(seller_unobserved_handover_pending_count_90d='forbidden',
                              seller_handover_count_90d='forbidden', delayed='forbidden',
                              order_status='canceled', order_delivered_carrier_date='2099-01-01')
        for candidate in training.MATCHED:
            import pandas as pd
            pd.testing.assert_frame_equal(training.prepare_input(data, candidate), training.prepare_input(changed, candidate))


if __name__ == '__main__':
    unittest.main()
