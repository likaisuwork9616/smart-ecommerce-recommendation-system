"""Feature contrasts must be paired and selected without development outcomes."""

import io
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from scripts import delay_budget_training as budget
from scripts import delay_engineering_training as engineering
from scripts.delay_engineering_features import (
    CATEGORICAL_FEATURES, DISPATCH_ENGINEERING_NUMERIC_FEATURES, FEATURE_SETS,
)
from scripts.delay_outcome_clock import TRAINING_OUTCOME_COLUMN
from scripts.predict_delay import predict_features
from tests.test_delay_budget_training import decision_projection, month_frame
from tests.test_delay_pending_training import pending_frame


def engineering_frame(month, rows=120):
    frame = pending_frame(month, rows)
    for offset, name in enumerate(DISPATCH_ENGINEERING_NUMERIC_FEATURES):
        if name not in frame:
            frame[name] = np.arange(rows, dtype=float) + offset
    frame[TRAINING_OUTCOME_COLUMN] = pd.Timestamp(month + '-15')
    return frame


class EngineeringTrainingTests(unittest.TestCase):
    def test_twelve_paired_cells_have_identical_family_parameters_and_exact_contracts(self):
        self.assertEqual(len(engineering.PREVIOUS_CANDIDATES), 24)
        self.assertEqual(len(engineering.NEW_CANDIDATES), 11)
        self.assertEqual(len(engineering.ALL_CANDIDATES), 35)
        self.assertEqual(len(set(engineering.ALL_CANDIDATES)), 35)
        self.assertNotIn(engineering.REUSED_BASE_LIGHTGBM, engineering.NEW_CANDIDATES)
        for family, base, geo, dispatch in zip(engineering.FAMILIES, engineering.BASE_CANDIDATES,
                engineering.GEO_CANDIDATES, engineering.DISPATCH_CANDIDATES, strict=True):
            parameters = []
            for candidate, variant, count in zip((base, geo, dispatch), ('base','geo','dispatch'), (60,83,91), strict=True):
                with self.subTest(candidate=candidate):
                    self.assertEqual(engineering.candidate_family_variant(candidate), (family, variant))
                    numeric, categorical = engineering.feature_names(candidate)
                    self.assertEqual(len(numeric)+len(categorical), count)
                    self.assertEqual(len(set(numeric+categorical)), count)
                    self.assertEqual(categorical, list(CATEGORICAL_FEATURES))
                    self.assertEqual(engineering.feature_set(candidate), FEATURE_SETS[variant])
                    parameter = engineering.make_candidate(candidate, seed=37, n_jobs=2).named_steps['classifier'].get_params(deep=False)
                    self.assertEqual(parameter['random_state'], 37)
                    self.assertIsNone(parameter.get('early_stopping_rounds'))
                    parameters.append(parameter)
            self.assertEqual(parameters[0], parameters[1])
            self.assertEqual(parameters[1], parameters[2])
        with self.assertRaises(ValueError):
            engineering.make_candidate(engineering.NEW_CANDIDATES[0], n_jobs=0)
        with self.assertRaises(ValueError):
            engineering.candidate_family_variant('random_forest_route')
        with self.assertRaises(ValueError):
            engineering.feature_set('unrecognized')

    def test_eleven_fits_learn_imputation_and_categories_only_from_training(self):
        train = engineering_frame('2017-09')
        scoring = engineering_frame('2018-02', rows=20)
        train.loc[0, 'item_count'] = np.nan
        for name in DISPATCH_ENGINEERING_NUMERIC_FEATURES:
            scoring[name] = 1000000.
        for name in CATEGORICAL_FEATURES:
            scoring[name] = 'future_only'
        factory = engineering.make_candidate

        def small(candidate, seed, n_jobs):
            pipeline = factory(candidate, seed, n_jobs)
            params = pipeline.named_steps['classifier'].get_params(deep=False)
            if 'n_estimators' in params:
                pipeline.set_params(classifier__n_estimators=3)
            if 'min_child_samples' in params:
                pipeline.set_params(classifier__min_child_samples=5)
            return pipeline

        for candidate in engineering.NEW_CANDIDATES:
            with self.subTest(candidate=candidate), patch.object(engineering, 'make_candidate', side_effect=small), \
                    patch.object(engineering, 'threadpool_limits', wraps=engineering.threadpool_limits) as limits:
                pipeline, values, report = engineering.fit_version(train, scoring, candidate, n_jobs=2)
            self.assertEqual([call.kwargs for call in limits.call_args_list],[{'limits':2},{'limits':1}])
            numeric, categorical = engineering.feature_names(candidate)
            prep = pipeline.named_steps['preprocessor']
            self.assertEqual(list(prep.feature_names_in_), numeric+categorical)
            self.assertFalse(set(prep.feature_names_in_) & {'order_id','delayed','prediction_time',
                'label_available_time',TRAINING_OUTCOME_COLUMN,'future_actual_delivery_days'})
            np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                                       np.nanmedian(train[numeric].to_numpy(dtype=float),axis=0))
            for categories in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only',categories)
            changed = scoring.copy()
            changed['delayed'] = 'not available'
            changed['label_available_time'] = pd.Timestamp('2099-01-01')
            changed[TRAINING_OUTCOME_COLUMN] = pd.Timestamp('1900-01-01')
            np.testing.assert_array_equal(values, engineering.positive_probability(pipeline, engineering.prepare_input(changed,candidate)))
            self.assertEqual(report['training_design'],'deadline_wait0')
            self.assertEqual(report['training_jobs'],2)
            self.assertEqual(report['prediction_jobs'],1)
            self.assertEqual((report['paired_model_family'],report['paired_feature_variant']),
                             engineering.candidate_family_variant(candidate))
            self.assertTrue(np.isfinite(values).all())
            self.assertTrue(((values>=0)&(values<=1)).all())

    def test_reused_lightgbm_base_and_other_prior_versions_cannot_be_refit(self):
        train = engineering_frame('2017-09')
        for candidate in engineering.PREVIOUS_CANDIDATES:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                engineering.fit_version(train,train,candidate,n_jobs=1)

    def test_preparing_every_old_and_new_candidate_enforces_saved_whitelist(self):
        frame = engineering_frame('2017-09')
        for candidate in engineering.ALL_CANDIDATES:
            with self.subTest(candidate=candidate):
                numeric,categorical = engineering.feature_names(candidate)
                self.assertEqual(list(engineering.prepare_input(frame,candidate)),numeric+categorical)
                self.assertFalse(set(numeric+categorical) & {'delayed','label_available_time','prediction_time',TRAINING_OUTCOME_COLUMN})


class EngineeringHistoricalSelectionTests(unittest.TestCase):
    def test_dispatch_winner_is_excluded_from_primary_and_development_cannot_change_selections(self):
        validation = [month_frame(month) for month in ('2017-09','2017-10','2017-11')]
        evaluation = month_frame('2018-02')
        positions = np.arange(100)%50
        weak = np.tile(np.linspace(.01,.99,50),2)
        geo_values = weak.copy()
        geo_values[positions<4] = 1.
        dispatch_values = weak.copy()
        dispatch_values[positions<5] = 1.
        geo_winner, dispatch_winner = engineering.GEO_CANDIDATES[0],engineering.DISPATCH_CANDIDATES[0]
        historical = [{candidate: (geo_values if candidate==geo_winner else dispatch_values if candidate==dispatch_winner else weak)
                       for candidate in engineering.ALL_CANDIDATES} for _ in validation]
        development = {candidate: weak for candidate in engineering.ALL_CANDIDATES}

        def decide(frame, values):
            return budget.decide_ranking_fold(validation,historical,frame,values,'2018-02-01',
                candidate_order=engineering.ALL_CANDIDATES,selection_groups=engineering.SELECTION_GROUPS)

        before = decide(evaluation,development)
        self.assertEqual(len(before['models']),35)
        self.assertEqual(len(before['selected_models']),6)
        self.assertEqual(before['selected_models'][engineering.PRIMARY_SELECTION],geo_winner)
        self.assertEqual(before['selected_models']['all_including_dispatch'],dispatch_winner)
        self.assertTrue(set(engineering.SELECTION_GROUPS[engineering.PRIMARY_SELECTION]).isdisjoint(engineering.DISPATCH_CANDIDATES))
        changed = evaluation.copy()
        changed['delayed'] = 1-changed.delayed
        changed['label_available_time'] = pd.Timestamp('2099-01-01')
        after = decide(changed,{candidate:1-values for candidate,values in development.items()})
        self.assertEqual(decision_projection(before),decision_projection(after))
        summary = budget.summarize([{'name':'2018-02','experiment':before}],candidate_order=engineering.ALL_CANDIDATES,
                                   selection_groups=engineering.SELECTION_GROUPS)
        self.assertEqual(len(summary),41)


class ContractProbabilityPipeline:
    classes_ = np.array([1,0])

    def predict_proba(self,frame):
        self.received_columns = list(frame)
        score = frame.item_count.to_numpy(dtype=float)
        return np.column_stack([score,1-score])


class EngineeringArtifactTests(unittest.TestCase):
    def test_geo_and_dispatch_artifacts_keep_feature_whitelist_and_complete_day_guard(self):
        frame = engineering_frame('2018-02',rows=100)
        frame['item_count'] = np.tile(np.linspace(.01,.99,50),2)
        frame.index = [7]*len(frame)
        for candidate in (engineering.GEO_CANDIDATES[0],engineering.DISPATCH_CANDIDATES[0]):
            numeric,categorical = engineering.feature_names(candidate)
            artifact = {'format_version':1,'pipeline':ContractProbabilityPipeline(),
                'feature_set':engineering.feature_set(candidate),'selected_model':candidate,
                'feature_names':numeric+categorical,'numeric_features':numeric,'categorical_features':categorical,
                'threshold':0.,'daily_alert_cap':.10}
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):
                predict_features(artifact,frame)
            stream = io.BytesIO()
            joblib.dump(artifact,stream)
            stream.seek(0)
            restored = joblib.load(stream)
            result = predict_features(restored,frame,complete_daily_batches=True)
            self.assertEqual(restored['pipeline'].received_columns,numeric+categorical)
            self.assertEqual(result.index.tolist(),frame.index.tolist())
            self.assertEqual(int(result.predicted_delayed.sum()),10)


if __name__ == '__main__':
    unittest.main()
