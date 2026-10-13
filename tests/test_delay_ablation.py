"""Disjoint feature contracts, train isolation and historical-only selection."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts import delay_ablation_features as features
from scripts import delay_ablation_training as training
from scripts import delay_budget_training as budget
from scripts.delay_engineering_features import ENGINEERING_NUMERIC_FEATURES, BASE_NUMERIC_FEATURES, CATEGORICAL_FEATURES
from scripts.predict_delay import build_inference_features, predict_features
from tests.test_delay_engineering_features import interaction_fixture
from tests.test_delay_engineering_training import engineering_frame, ContractProbabilityPipeline
from tests.test_delay_budget_training import month_frame, decision_projection


class AblationFeatureTests(unittest.TestCase):
    def test_disjoint_groups_exactly_partition_prior_twenty_three_additions(self):
        groups = [features.GEOGRAPHIC_FEATURES, features.WORKLOAD_FEATURES, features.OTHER_FEATURES]
        self.assertEqual([len(g) for g in groups], [12, 5, 6])
        self.assertEqual(len(set(sum(groups, []))), 23)
        self.assertEqual(set(sum(groups, [])), set(ENGINEERING_NUMERIC_FEATURES) - set(BASE_NUMERIC_FEATURES))
        for variant, count in zip(features.VARIANT_FEATURES, (72, 65, 77), strict=True):
            names = features.VARIANT_FEATURES[variant]
            self.assertEqual(len(names) + len(CATEGORICAL_FEATURES), count)
            self.assertEqual(names, [c for c in ENGINEERING_NUMERIC_FEATURES if c in names])
            self.assertTrue(set(features.OTHER_FEATURES).isdisjoint(names))
        self.assertTrue(set(features.GEOGRAPHIC_FEATURES).isdisjoint(features.VARIANT_FEATURES['load_only']))

    def test_workload_hand_calculation_without_geo_and_preserves_duplicate_index(self):
        frame = pd.concat([interaction_fixture()] * 2, ignore_index=True).drop(columns=['geo_primary_distance_km'])
        frame.index = [3, 3]
        original = frame.copy(deep=True)
        actual = features.add_workload_interactions(frame)
        np.testing.assert_allclose(actual[features.WORKLOAD_FEATURES], [[12 / 21, 30 / 31, .25, .2, .1]] * 2)
        assert_frame_equal(actual[original.columns], original)
        assert_frame_equal(frame, original)
        with self.assertRaises(ValueError):
            features.add_workload_interactions(actual)

    def test_workload_zero_negative_and_nonfinite_counts_stay_defined_or_missing(self):
        frame = pd.concat([interaction_fixture()] * 3, ignore_index=True)
        count_columns = [c for c in frame if 'pending' in c or 'completed' in c]
        frame.loc[0, count_columns] = 0
        frame.loc[1, count_columns] = -1
        frame.loc[2, count_columns] = np.inf
        actual = features.add_workload_interactions(frame)
        np.testing.assert_array_equal(actual.loc[0, features.WORKLOAD_FEATURES[:2]].to_numpy(), [0, 0])
        self.assertTrue(actual.loc[0, features.WORKLOAD_FEATURES[2:]].isna().all())
        self.assertTrue(actual.loc[[1, 2], features.WORKLOAD_FEATURES].isna().all(axis=None))

    def test_all_input_contracts_exclude_other_dispatch_labels_and_keep_zip_zero(self):
        frame = engineering_frame('2018-02')
        frame['customer_zip_prefix3'] = '001'
        for variant, numeric in features.VARIANT_FEATURES.items():
            actual = features.prepare_ablation_input(frame, variant)
            self.assertEqual(list(actual), numeric + list(CATEGORICAL_FEATURES))
            self.assertTrue(actual.customer_zip_prefix3.eq('001').all())
            changed = frame.copy()
            changed['delayed'], changed['label_available_time'] = 'unknown', pd.Timestamp('2099-01-01')
            for column in features.OTHER_FEATURES:
                changed[column] = 999999
            assert_frame_equal(actual, features.prepare_ablation_input(changed, variant))
        with self.assertRaises(ValueError):
            features.prepare_ablation_input(frame, 'undefined')
        with self.assertRaises(ValueError):
            features.prepare_ablation_input(frame.drop(columns=['seller_pending_vs_completed_30d']), 'load_only')

    def test_raw_load_builder_does_not_require_or_consult_geographic_reference(self):
        frame = engineering_frame('2018-02')
        frame['order_purchase_timestamp'] = frame.prediction_time - pd.Timedelta(hours=1)
        columns = ['order_id', 'order_purchase_timestamp', 'prediction_time'] + list(BASE_NUMERIC_FEATURES) + list(CATEGORICAL_FEATURES)
        tables = object()
        with patch.object(features, 'build_pending_order_features', return_value=frame[columns]) as pending, \
                patch.object(features, 'build_engineering_order_features') as geo:
            actual = features.build_ablation_order_features(tables, 'load_only')
        pending.assert_called_once_with(tables)
        geo.assert_not_called()
        self.assertEqual(list(actual), ['order_id', 'order_purchase_timestamp', 'prediction_time']
            + features.VARIANT_FEATURES['load_only'] + list(CATEGORICAL_FEATURES))
        for variant in ('geo_only', 'geo_load'):
            with self.assertRaisesRegex(ValueError, 'geolocation'):
                features.build_ablation_order_features(tables, variant)

    def test_inference_dispatches_each_ablation_contract_and_rejects_unknown(self):
        tables, geo, returned = object(), object(), object()
        for variant, feature_set in features.FEATURE_SETS.items():
            with patch.object(features, 'build_ablation_order_features', return_value=returned) as builder:
                self.assertIs(build_inference_features({'feature_set': feature_set}, tables, geo), returned)
            builder.assert_called_once_with(tables, variant, geo)
        with self.assertRaises(ValueError):
            build_inference_features({'feature_set': 'ablation_unknown'}, tables)


class AblationTrainingTests(unittest.TestCase):
    def test_twenty_cells_keep_family_parameters_and_preprocessing_contracts(self):
        self.assertEqual((len(training.PREVIOUS_CANDIDATES), len(training.NEW_CANDIDATES), len(training.ALL_CANDIDATES)), (31, 12, 43))
        self.assertEqual(len(set(training.ALL_CANDIDATES)), 43)
        self.assertFalse(any('dispatch' in c for c in training.ALL_CANDIDATES))
        for i, family in enumerate(training.FAMILIES):
            cells = [training.BASE_CANDIDATES[i], *(v[i] for v in training.VARIANT_CANDIDATES.values()), training.FULL_CANDIDATES[i]]
            params = [training.make_candidate(c, seed=37, n_jobs=2).named_steps['classifier'].get_params() for c in cells]
            self.assertTrue(all(p == params[0] for p in params))
            self.assertEqual(params[0]['random_state'], 37)
            self.assertIsNone(params[0].get('early_stopping_rounds'))
        with self.assertRaises(ValueError):
            training.make_candidate(training.NEW_CANDIDATES[0], n_jobs=0)
        with self.assertRaises(ValueError):
            training.fit_version(None, None, training.BASE_CANDIDATES[0])

    def test_twelve_fits_use_only_training_values_and_categories(self):
        train, scoring = engineering_frame('2017-09'), engineering_frame('2018-02', rows=20)
        train.loc[0, 'item_count'] = np.nan
        for column in ENGINEERING_NUMERIC_FEATURES:
            scoring[column] = 1000000.
        for column in CATEGORICAL_FEATURES:
            scoring[column] = 'future_only'
        factory = training.make_candidate
        def small(candidate, seed, n_jobs):
            pipeline = factory(candidate, seed, n_jobs)
            if 'n_estimators' in pipeline.named_steps['classifier'].get_params():
                pipeline.set_params(classifier__n_estimators=3)
            if 'min_child_samples' in pipeline.named_steps['classifier'].get_params():
                pipeline.set_params(classifier__min_child_samples=5)
            return pipeline
        for candidate in training.NEW_CANDIDATES:
            with self.subTest(candidate=candidate), patch.object(training, 'make_candidate', side_effect=small):
                pipeline, values, report = training.fit_version(train, scoring, candidate, n_jobs=1)
            numeric, categorical = training.feature_names(candidate)
            prep = pipeline.named_steps['preprocessor']
            self.assertEqual(list(prep.feature_names_in_), numeric + categorical)
            np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                       np.nanmedian(train[numeric].to_numpy(dtype=float), axis=0))
            for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only', categories)
            changed = scoring.copy()
            changed['delayed'], changed['training_outcome_known_time'] = 'unknown', pd.Timestamp('2099-01-01')
            np.testing.assert_array_equal(values, training.positive_probability(pipeline, training.prepare_input(changed, candidate)))
            self.assertEqual(report['prediction_jobs'], 1)
            self.assertTrue(np.isfinite(values).all())

    def test_development_labels_or_scores_cannot_change_historical_selection(self):
        validation = [month_frame(m) for m in ('2017-09', '2017-10', '2017-11')]
        evaluation = month_frame('2018-02')
        weak = np.tile(np.linspace(.01, .99, 50), 2)
        strong = weak.copy()
        strong[np.arange(100) % 50 < 4] = 1
        winner = training.VARIANT_CANDIDATES['load_only'][0]
        historical = [{c: strong if c == winner else weak for c in training.ALL_CANDIDATES} for _ in validation]
        values = {c: weak for c in training.ALL_CANDIDATES}
        def decide(frame, scores):
            return budget.decide_ranking_fold(validation, historical, frame, scores, '2018-02-01',
                candidate_order=training.ALL_CANDIDATES, selection_groups=training.SELECTION_GROUPS)
        before = decide(evaluation, values)
        self.assertEqual(before['selected_models'][training.PRIMARY_SELECTION], winner)
        changed = evaluation.copy()
        changed['delayed'] = 1 - changed.delayed
        changed['label_available_time'] = pd.Timestamp('2099-01-01')
        after = decide(changed, {c: 1 - v for c, v in values.items()})
        self.assertEqual(decision_projection(before), decision_projection(after))
        self.assertEqual(len(budget.summarize([{'name': '2018-02', 'experiment': before}],
            candidate_order=training.ALL_CANDIDATES, selection_groups=training.SELECTION_GROUPS)), 50)

    def test_new_artifacts_require_full_day_and_use_saved_whitelist(self):
        frame = engineering_frame('2018-02', rows=100)
        frame['item_count'] = np.tile(np.linspace(.01, .99, 50), 2)
        for variant, candidates in training.VARIANT_CANDIDATES.items():
            numeric, categorical = training.feature_names(candidates[0])
            artifact = {'format_version': 1, 'pipeline': ContractProbabilityPipeline(), 'feature_names': numeric + categorical,
                'numeric_features': numeric, 'categorical_features': categorical, 'threshold': 0., 'daily_alert_cap': .10}
            with self.assertRaises(ValueError):
                predict_features(artifact, frame)
            actual = predict_features(artifact, frame, complete_daily_batches=True)
            self.assertEqual(int(actual.predicted_delayed.sum()), 10)
            self.assertEqual(artifact['pipeline'].received_columns, numeric + categorical)


if __name__ == '__main__':
    unittest.main()
