"""Pair-focus changes retain historical selection and separate compatibility goals."""
from copy import deepcopy
import unittest

from scripts.compare_rank_pair_focus import (
    BASELINE_RANKERS, MATCHED, NEW, PREVIOUS, PRIMARY, REPLAYED,
    compatibility_targets, merge_experiments, paired_comparisons,
)


def records():
    previous = {'models': {c: {
        'minimum_validation_month_recall': .2, 'validation_true_positives': 20,
        'validation_pooled_average_precision': .1,
        'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .9, 'true_positives': 999},
    } for c in PREVIOUS}, 'selected_models': {PRIMARY: PREVIOUS[0]}}
    matched = {'models': {c: deepcopy(previous['models'][c]) for c in REPLAYED}}
    for c in NEW:
        matched['models'][c] = {
            'minimum_validation_month_recall': .25, 'validation_true_positives': 25,
            'validation_pooled_average_precision': .12,
            'all_validation_months_meet_30_percent': False,
            'development_evaluation': {'recall': .01, 'true_positives': 1},
        }
    return previous, matched


def validation(july, september):
    return {month: {'known_outcome_metrics': {'confusion_matrix': [[1000, 0], [100-tp, tp]]}}
            for month, tp in [('2017-07', july), ('2017-09', september)]}


class PairFocusSelectionTests(unittest.TestCase):
    def test_development_and_compatibility_flags_cannot_override_history(self):
        previous, matched = records()
        expected = merge_experiments(previous, matched)['selected_models']
        for record in list(previous['models'].values()) + list(matched['models'].values()):
            record['development_evaluation'] = {'recall': 0, 'true_positives': 0}
            record['descriptive_compatibility'] = False
        for c in NEW:
            matched['models'][c]['development_evaluation'] = {'recall': 1, 'true_positives': 100000}
            matched['models'][c]['descriptive_compatibility'] = True
        self.assertEqual(merge_experiments(previous, matched)['selected_models'], expected)
        self.assertEqual(expected[PRIMARY], NEW[0])

    def test_previous_metrics_preserved_and_floor_remains_suitability_only(self):
        previous, matched = records()
        snapshot = deepcopy(previous)
        result = merge_experiments(previous, matched)
        self.assertEqual(previous, snapshot)
        for c in PREVIOUS: self.assertEqual(result['models'][c], previous['models'][c])
        self.assertFalse(result['models'][result['selected_models'][PRIMARY]]['all_validation_months_meet_30_percent'])
        result['models'][PREVIOUS[0]]['development_evaluation']['recall'] = -1
        self.assertEqual(previous, snapshot)

    def test_exact_historical_ties_keep_original_focus20(self):
        previous, matched = records()
        for c in NEW: matched['models'][c] = deepcopy(previous['models'][PREVIOUS[0]])
        result = merge_experiments(previous, matched)['selected_models']
        self.assertEqual(result['geo_rank_focus'], BASELINE_RANKERS[0])
        self.assertEqual(result['backlog_rank_focus'], BASELINE_RANKERS[1])
        self.assertEqual(result[PRIMARY], PREVIOUS[0])

    def test_changed_original_metrics_or_missing_candidate_rejected(self):
        for c in REPLAYED:
            previous, matched = records()
            matched['models'][c]['validation_true_positives'] += 1
            with self.assertRaises(ValueError): merge_experiments(previous, matched)
        previous, matched = records()
        del matched['models'][MATCHED[-1]]
        with self.assertRaises(ValueError): merge_experiments(previous, matched)

    def test_compatibility_targets_use_declared_historical_counts(self):
        previous, _ = records()
        counts = {'xgboost_rank_geo': (25,43), 'xgboost_rank_backlog_7_14d': (28,35),
                  BASELINE_RANKERS[0]: (20,50), BASELINE_RANKERS[1]: (18,49)}
        for c, values in counts.items(): previous['models'][c]['validation_by_month'] = validation(*values)
        source = {'folds': [{'name': '2017-12', 'experiment': previous}]}
        targets = compatibility_targets(source)
        self.assertFalse(targets['used_for_selection'])
        self.assertEqual(targets['packages']['geo83']['july_current_TP'], 20)
        self.assertEqual(targets['packages']['geo83']['july_restore_TP'], 25)
        self.assertEqual(targets['packages']['backlog101']['september_current_TP'], 49)
        self.assertEqual(targets['packages']['backlog101']['july_restore_TP'], 28)
        for model in previous['models'].values(): model['development_evaluation'] = {'recall': 999}
        self.assertEqual(compatibility_targets(source), targets)

    def test_joint_month_goals_cannot_be_satisfied_by_pooled_compensation(self):
        previous, matched = records()
        anchors = {'xgboost_rank_geo': (25,43), 'xgboost_rank_backlog_7_14d': (28,35),
                   BASELINE_RANKERS[0]: (20,50), BASELINE_RANKERS[1]: (18,49)}
        for c,v in anchors.items(): previous['models'][c]['validation_by_month'] = validation(*v)
        targets = compatibility_targets({'folds': [{'name':'2017-12','experiment':previous}]})
        counts = {BASELINE_RANKERS[0]:(20,50),BASELINE_RANKERS[1]:(18,49),
                  NEW[0]:(24,51),NEW[1]:(30,49),NEW[2]:(28,49),NEW[3]:(100,48)}
        for c,v in counts.items(): matched['models'][c]['validation_by_month'] = validation(*v)
        summary=[{'model_or_selection':c,'true_positives':sum(v),'recall':0} for c,v in counts.items()]
        _,checks=paired_comparisons([{'name':'2017-12','experiment':matched}],summary,targets)
        indexed={row['candidate']:row for row in checks}
        a='both_months_not_worse_than_l2_100_top20'
        b='restore_july_l2_10_and_preserve_september_l2_100'
        self.assertTrue(indexed[NEW[0]][a])
        self.assertFalse(indexed[NEW[0]][b])
        self.assertFalse(indexed[NEW[1]][a])
        self.assertTrue(indexed[NEW[2]][a] and indexed[NEW[2]][b])
        self.assertFalse(indexed[NEW[3]][a] or indexed[NEW[3]][b])
        self.assertTrue(all(row['used_for_selection'] is False for row in checks))


if __name__=='__main__': unittest.main()
