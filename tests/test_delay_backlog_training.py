"""Paired backlog contracts, train-only fitting and historical selection."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import delay_backlog_training as training
from scripts import delay_route_load_training as previous
from scripts.delay_backlog_features import ADDED_FEATURES
from scripts.delay_budget_training import decide_ranking_fold, summarize
from scripts.predict_delay import build_inference_features, predict_features
from scripts.train_backlog_changes import paired_comparisons
from tests.test_delay_budget_training import decision_projection, month_frame
from tests.test_delay_engineering_training import engineering_frame


def frame(month, rows=120):
    value = engineering_frame(month, rows).copy()
    for i, name in enumerate(ADDED_FEATURES):
        value[name] = np.arange(rows, dtype=float) + i
    return value


class BacklogTrainingTests(unittest.TestCase):
    def test_nine_cells_hold_backbone_settings_and_only_add_numeric_lags(self):
        self.assertEqual((len(training.PREVIOUS_CANDIDATES),len(training.NEW_CANDIDATES),len(training.ALL_CANDIDATES)),(56,9,65))
        for c in training.NEW_CANDIDATES:
            design = training.candidate_design(c)
            actual = training.make_candidate(c,n_jobs=2)
            baseline = previous.make_candidate(design['backbone_candidate'],n_jobs=2)
            self.assertEqual(actual.named_steps['classifier'].get_params(),baseline.named_steps['classifier'].get_params())
            numeric, categorical = training.feature_names(c)
            old_num, old_cat = previous.feature_names(design['backbone_candidate'])
            self.assertEqual(categorical, old_cat)
            self.assertEqual(numeric[:len(old_num)],old_num)
            self.assertEqual(len(numeric)-len(old_num),18 if design['variant']=='7_14d' else 9)
            self.assertIn(training.feature_set(c),training.FEATURE_SET_DESIGNS)
            for i in (0,1):
                actual_steps=actual.named_steps['preprocessor'].transformers[i][1].steps
                baseline_steps=baseline.named_steps['preprocessor'].transformers[i][1].steps
                self.assertEqual([n for n,_ in actual_steps],[n for n,_ in baseline_steps])
                for (_,a),(_,b) in zip(actual_steps,baseline_steps,strict=True):
                    self.assertEqual(a.get_params(deep=False),b.get_params(deep=False))
        for c in training.PREVIOUS_CANDIDATES:
            self.assertEqual(training.feature_names(c),previous.feature_names(c))
        with self.assertRaises(ValueError):
            training.fit_version(None,None,training.PREVIOUS_CANDIDATES[0])

    def test_all_new_cells_fit_sorted_training_only_and_ignore_future_labels(self):
        train, future = frame('2017-08').iloc[::-1].copy(),frame('2017-09',20)
        train.iloc[0,train.columns.get_loc(ADDED_FEATURES[0])] = np.nan
        factory = training.make_candidate
        for c in training.NEW_CANDIDATES:
            numeric, categorical = training.feature_names(c)
            pipeline = factory(c,n_jobs=1)
            if c.startswith('xgboost'):
                pipeline.set_params(classifier__n_estimators=3)
            scoring = future.copy()
            scoring[numeric] = 999999.
            scoring[categorical] = 'future_only'
            with self.subTest(candidate=c),patch.object(training,'make_candidate',return_value=pipeline),patch.object(pipeline,'fit',wraps=pipeline.fit) as fit:
                actual, scores, info = training.fit_version(train,scoring,c,n_jobs=1)
            expected_train = train.sort_values(['prediction_time','order_id'],kind='stable').reset_index(drop=True)
            pd.testing.assert_frame_equal(fit.call_args.args[0],training.prepare_input(expected_train,c))
            prep = actual.named_steps['preprocessor']
            np.testing.assert_allclose(prep.named_transformers_['numeric'].named_steps['imputer'].statistics_,
                np.nanmedian(train[numeric].to_numpy(dtype=float),axis=0))
            for cats in prep.named_transformers_['categorical'].named_steps['onehot'].categories_:
                self.assertNotIn('future_only',cats)
            changed = scoring.assign(delayed='unknown',label_available_time='unknown',training_outcome_known_time='unknown')
            np.testing.assert_array_equal(scores,training.positive_probability(actual,training.prepare_input(changed,c)))
            if c.startswith('logistic'):
                self.assertTrue(info['converged'])
            artifact={'format_version':1,'pipeline':actual,'feature_names':numeric+categorical,
                'numeric_features':numeric,'categorical_features':categorical,'threshold':0.,'daily_alert_cap':.1}
            with self.assertRaises(ValueError):
                predict_features(artifact,changed)
            self.assertEqual(int(predict_features(artifact,changed,complete_daily_batches=True).predicted_delayed.sum()),2)

    def test_inference_routes_all_six_feature_sets_and_rejects_unknown(self):
        value = object()
        for name,(backbone,variant) in training.FEATURE_SET_DESIGNS.items():
            with patch('scripts.delay_backlog_features.build_backlog_order_features',return_value=value) as build:
                self.assertIs(build_inference_features({'feature_set':name},{},None),value)
                build.assert_called_once_with({},backbone,variant,None)
        with self.assertRaises(ValueError):
            build_inference_features({'feature_set':'backlog_unknown'},{})

    def test_historical_selector_ignores_development_and_reports_every_declared_lag(self):
        historical=[month_frame(m) for m in ('2017-07','2017-08','2017-09')]
        evaluation=month_frame('2017-12')
        weak=np.tile(np.linspace(.01,.99,50),2);strong=weak.copy();strong[np.arange(100)%50<4]=1
        winner=training.NEW_CANDIDATES[-1]
        scores=[{c:strong if c==winner else weak for c in training.ALL_CANDIDATES} for _ in historical]
        def decide(f,p):
            return decide_ranking_fold(historical,scores,f,p,'2017-12-01',candidate_order=training.ALL_CANDIDATES,selection_groups=training.SELECTION_GROUPS)
        result=decide(evaluation,{c:weak for c in training.ALL_CANDIDATES})
        changed=decide(evaluation.assign(delayed=1-evaluation.delayed),{c:1-weak for c in training.ALL_CANDIDATES})
        self.assertEqual(decision_projection(result),decision_projection(changed))
        self.assertEqual(result['selected_models']['new_backlog'],winner)
        folds=[{'name':'2017-12','experiment':result}]
        summary=summarize(folds,candidate_order=training.ALL_CANDIDATES,selection_groups=training.SELECTION_GROUPS)
        comparisons=paired_comparisons(folds,summary)
        self.assertEqual((len(summary),len(comparisons)),(68,3))
        self.assertTrue(all(set(c['candidates'])=={'baseline','7d','14d','7_14d'} for c in comparisons))


if __name__=='__main__':
    unittest.main()
