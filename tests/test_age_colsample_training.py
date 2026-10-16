"""Column subsampling is the sole classifier change at every paired seed."""
import io
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_age_colsample_training as training
from scripts import delay_age_seed_training as previous
from scripts import delay_objective_training as objective
from tests.test_delay_objective_training import RecordingRanker
from tests.test_delay_unobserved_handover_age_training import frame


class AgeColsampleTrainingTests(unittest.TestCase):
    def test_all_ten_factories_change_only_colsample_and_keep_preprocessing(self):
        for seed in training.SEEDS:
            for candidate, count in zip(training.MATCHED, (101, 102), strict=True):
                with self.subTest(seed=seed, candidate=candidate):
                    before = previous.make_candidate(candidate, seed)
                    after = training.make_candidate(candidate, seed)
                    original = before.named_steps['classifier'].get_params(deep=False)
                    actual = after.named_steps['classifier'].get_params(deep=False)
                    self.assertEqual(actual, {**original, 'colsample_bytree': 1.})
                    self.assertEqual((actual['subsample'], actual['reg_lambda'], actual['random_state']), (.8, 100., seed))
                    self.assertEqual((actual['lambdarank_pair_method'], actual['lambdarank_num_pair_per_sample']), ('topk', 10))
                    self.assertEqual(sum(map(len, training.feature_names(candidate))), count)
                    self.assertEqual(training.preprocessing_specification(before), training.preprocessing_specification(after))

    def test_fixed_seed_and_candidate_guards_remain_in_force(self):
        for seed in (True, 12, 42., '42', None):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                training.make_candidate(training.BASELINE, seed)
        with self.assertRaises(ValueError):
            training.make_candidate('not_registered', 42)
        factory = previous.make_candidate
        with patch.object(previous, 'make_candidate', side_effect=lambda c, s, n: factory(c, s, n).set_params(classifier__colsample_bytree=.5)):
            with self.assertRaisesRegex(ValueError, 'frozen .8'):
                training.make_candidate(training.BASELINE, 42)

    def test_fresh_fits_keep_queries_and_train_only_statistics_at_all_seeds(self):
        train, scoring = frame('2017-09').sample(frac=1., random_state=17), frame('2018-02', 20)
        train.loc[train.index[0], training.ADDED_FEATURES[0]] = np.nan
        numeric, categorical = training.feature_names(training.AGE)
        scoring[numeric], scoring[categorical] = 999999., 'future_only'
        _, layout = training.training_layout(train)
        state_hashes = {candidate: set() for candidate in training.MATCHED}
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            for seed in training.SEEDS:
                for candidate in training.MATCHED:
                    pipeline, scores, fit = training.fit_version(train, scoring, candidate, seed)
                    classifier = pipeline.named_steps['classifier']
                    self.assertEqual(classifier.ranker_.fit_parameters, {'group': layout['daily_training_groups']})
                    self.assertEqual(classifier.ranker_.parameters['colsample_bytree'], 1.)
                    self.assertEqual(classifier.ranker_.parameters['subsample'], .8)
                    self.assertEqual((fit['training_order_sha256'], fit['training_labels_sha256']),
                                     (layout['training_order_sha256'], layout['training_labels_sha256']))
                    self.assertEqual(fit['changed_classifier_parameters_vs_source'], ['colsample_bytree'])
                    self.assertTrue(fit['train_only_preprocessing_verified'])
                    self.assertEqual(fit['manually_added_missingness_indicators'], [])
                    state_hashes[candidate].add(fit['preprocessing_state_sha256'])
                    for values in pipeline.named_steps['preprocessor'].named_transformers_['categorical'].named_steps['onehot'].categories_:
                        self.assertNotIn('future_only', values)
                    self.assertTrue(np.isfinite(scores).all())
        self.assertTrue(all(len(values) == 1 for values in state_hashes.values()))

    def test_tampered_medians_or_categories_are_rejected(self):
        train = frame('2017-09')
        with patch.object(objective, 'XGBRanker', RecordingRanker):
            pipeline, _, _ = training.fit_version(train, frame('2018-02', 20), training.AGE, 42)
        prep = pipeline.named_steps['preprocessor']
        imputer = prep.named_transformers_['numeric'].named_steps['imputer']
        imputer.statistics_[0] += 1
        with self.assertRaises(AssertionError):
            training.verify_preprocessing(pipeline, train, training.AGE)
        imputer.statistics_[0] -= 1
        ohe = prep.named_transformers_['categorical'].named_steps['onehot']
        ohe.categories_[0][0] = 'future_only'
        with self.assertRaises(AssertionError):
            training.verify_preprocessing(pipeline, train, training.AGE)

    def test_one_new_age_raw_feature_excludes_counts_targets_and_future_events(self):
        data = frame('2017-09')
        corrupted = data.assign(seller_unobserved_handover_pending_count_90d='forbidden', seller_handover_count_90d='forbidden',
                                delayed='forbidden', order_status='canceled', order_delivered_carrier_date='2099-01-01')
        old_num, old_cat = training.feature_names(training.BASELINE)
        new_num, new_cat = training.feature_names(training.AGE)
        self.assertEqual(new_num, old_num + list(training.ADDED_FEATURES))
        self.assertEqual(new_cat, old_cat)
        for candidate in training.MATCHED:
            pd.testing.assert_frame_equal(training.prepare_input(data, candidate), training.prepare_input(corrupted, candidate))

    def test_real_small_native_fit_serializes_and_keeps_both_parameter_layers(self):
        train = frame('2017-09')
        train.loc[0, training.ADDED_FEATURES[0]] = np.nan
        factory = training.make_candidate
        with patch.object(training, 'make_candidate', side_effect=lambda c, s, n: factory(c, s, n).set_params(classifier__n_estimators=3)):
            pipeline, scores, fit = training.fit_version(train, frame('2018-02', 20), training.AGE, 29, n_jobs=1)
        self.assertEqual(fit['classifier_parameters']['colsample_bytree'], 1.)
        self.assertEqual(fit['ranker_parameters']['colsample_bytree'], 1.)
        self.assertEqual(fit['ranker_parameters']['random_state'], 29)
        stream = io.BytesIO()
        joblib.dump(pipeline, stream)
        stream.seek(0)
        restored = joblib.load(stream)
        np.testing.assert_array_equal(scores, training.positive_probability(restored, training.prepare_input(frame('2018-02', 20), training.AGE)))


if __name__ == '__main__':
    unittest.main()
