"""Only historical metrics may select between frozen topk and new mean."""
from copy import deepcopy
import unittest

from scripts.compare_rank_pair_method import (
    BASELINE, MATCHED, NEW, PREVIOUS, PRIMARY, merge_experiments,
    compatibility_targets, paired_comparisons,
)


def example():
    old = {'models': {c: {
        'minimum_validation_month_recall': .20, 'validation_true_positives': 20,
        'validation_pooled_average_precision': .1,
        'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .9, 'confusion_matrix': [[10, 0], [1, 9]]},
    } for c in PREVIOUS}, 'selected_models': {PRIMARY: PREVIOUS[0]}}
    matched = {'models': {BASELINE: deepcopy(old['models'][BASELINE]), NEW[0]: {
        'minimum_validation_month_recall': .25, 'validation_true_positives': 25,
        'validation_pooled_average_precision': .12,
        'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .01, 'confusion_matrix': [[10, 0], [9, 1]]},
    }}}
    return old,matched


def validation(july,september):
    return {month:{'known_outcome_metrics':{'confusion_matrix':[[100,0],[100-tp,tp]]}}
            for month,tp in [('2017-07',july),('2017-09',september)]}


class PairMethodSelectionTests(unittest.TestCase):
    def test_development_and_descriptive_flags_do_not_select_models(self):
        old,matched=example()
        expected=merge_experiments(old,matched)['selected_models']
        self.assertEqual(expected[PRIMARY],NEW[0])
        for record in [*old['models'].values(),*matched['models'].values()]:
            record['development_evaluation']={'recall':0,'confusion_matrix':[[0,0],[0,0]]}
            record['all_three_descriptive_periods_not_worse']=False
        matched['models'][NEW[0]]['development_evaluation']['recall']=100000
        matched['models'][NEW[0]]['all_three_descriptive_periods_not_worse']=True
        self.assertEqual(merge_experiments(old,matched)['selected_models'],expected)

    def test_old75_metrics_preserved_and_floor_is_suitability_only(self):
        old,matched=example(); snapshot=deepcopy(old)
        result=merge_experiments(old,matched)
        for candidate in PREVIOUS:
            self.assertEqual(result['models'][candidate],old['models'][candidate])
        self.assertFalse(result['models'][result['selected_models'][PRIMARY]]['all_validation_months_meet_30_percent'])
        result['models'][PREVIOUS[0]]['development_evaluation']['recall']=-1
        self.assertEqual(old,snapshot)

    def test_exact_historical_ties_keep_topk_in_pair_and_previous_global_order(self):
        old,matched=example()
        matched['models'][NEW[0]]=deepcopy(old['models'][BASELINE])
        selected=merge_experiments(old,matched)['selected_models']
        self.assertEqual(selected['backlog_pair_method'],BASELINE)
        self.assertEqual(selected[PRIMARY],PREVIOUS[0])

    def test_changed_baseline_metric_or_missing_candidate_rejected(self):
        old,matched=example(); matched['models'][BASELINE]['validation_true_positives']+=1
        with self.assertRaises(ValueError): merge_experiments(old,matched)
        old,matched=example(); del matched['models'][MATCHED[-1]]
        with self.assertRaises(ValueError): merge_experiments(old,matched)
        old,matched=example(); del old['models'][PREVIOUS[-1]]
        with self.assertRaises(ValueError): merge_experiments(old,matched)

    def test_historical_and_development_compatibility_are_labelled_and_nonselecting(self):
        old,matched=example()
        old['models'][BASELINE]['validation_by_month']=validation(21,52)
        old['models'][BASELINE]['development_evaluation']['confusion_matrix']=[[100,10],[35,65]]
        source={'folds':[{'name':'2017-12','experiment':old}]}
        targets=compatibility_targets(source)
        self.assertFalse(targets['used_for_selection'])
        self.assertEqual(targets['december_development_TP'],65)
        matched['models'][BASELINE]=deepcopy(old['models'][BASELINE])
        matched['models'][NEW[0]]['validation_by_month']=validation(22,51)
        matched['models'][NEW[0]]['development_evaluation']['confusion_matrix']=[[100,10],[30,70]]
        summary=[{'model_or_selection':c,'true_positives':n,'recall':n/1000}
                 for c,n in ((BASELINE,339),(NEW[0],350))]
        _,checks=paired_comparisons([{'name':'2017-12','experiment':matched}],summary,targets)
        mean=next(row for row in checks if row['pair_method']=='mean')
        self.assertEqual((mean['july_difference'],mean['september_difference'],mean['december_difference']),(1,-1,5))
        self.assertFalse(mean['both_historical_months_not_worse'])
        self.assertFalse(mean['all_three_descriptive_periods_not_worse'])
        self.assertTrue(all(row['used_for_selection'] is False for row in checks))


if __name__=='__main__': unittest.main()
