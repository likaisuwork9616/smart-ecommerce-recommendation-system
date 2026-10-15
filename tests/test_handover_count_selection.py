"""Three-way count ablation must retain frozen metrics and historical selection."""
from copy import deepcopy
import unittest

from scripts.train_handover_count import (
    BASELINE, FULL, NEW, PREVIOUS, PRIMARY, REPLAYED,
    compatibility_targets, merge_experiments, paired_comparisons,
)


def example():
    old = {'models': {candidate: {
        'minimum_validation_month_recall': .20, 'validation_true_positives': 20,
        'validation_pooled_average_precision': .1,
        'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .9, 'confusion_matrix': [[10, 0], [1, 9]]},
    } for candidate in PREVIOUS}, 'selected_models': {PRIMARY: PREVIOUS[0]}}
    matched = {'models': {candidate: deepcopy(old['models'][candidate]) for candidate in REPLAYED}}
    matched['models'][NEW[0]] = {
        'minimum_validation_month_recall': .25, 'validation_true_positives': 25,
        'validation_pooled_average_precision': .12,
        'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .01, 'confusion_matrix': [[10, 0], [9, 1]]},
    }
    return old, matched


def validation(july, september):
    return {month: {'known_outcome_metrics': {'confusion_matrix': [[100, 0], [100-tp, tp]]}}
            for month, tp in [('2017-07', july), ('2017-09', september)]}


class CountSelectionTests(unittest.TestCase):
    def test_development_and_april_group_flags_cannot_select_models(self):
        old, matched = example()
        expected = merge_experiments(old, matched)['selected_models']
        self.assertEqual(expected[PRIMARY], NEW[0])
        for item in [*old['models'].values(), *matched['models'].values()]:
            item['development_evaluation'] = {'recall': 0, 'confusion_matrix': [[0, 0], [0, 0]]}
            item['april_sparse_recovered'] = 999999
            item['all_three_descriptive_periods_not_worse'] = False
        matched['models'][NEW[0]]['development_evaluation']['recall'] = 999999
        self.assertEqual(merge_experiments(old, matched)['selected_models'], expected)

    def test_all77_records_remain_frozen_and_30_percent_is_suitability_only(self):
        old, matched = example()
        snapshot = deepcopy(old)
        result = merge_experiments(old, matched)
        self.assertEqual(len(PREVIOUS), 77)
        for candidate in PREVIOUS:
            self.assertEqual(result['models'][candidate], snapshot['models'][candidate])
        self.assertFalse(result['models'][result['selected_models'][PRIMARY]]['all_validation_months_meet_30_percent'])
        result['models'][BASELINE]['validation_true_positives'] = -1
        self.assertEqual(old, snapshot)

    def test_exact_history_ties_preserve_old_candidate_order(self):
        old, matched = example()
        matched['models'][NEW[0]] = deepcopy(old['models'][BASELINE])
        selected = merge_experiments(old, matched)['selected_models']
        self.assertEqual(selected['count_ablation'], BASELINE)
        self.assertEqual(selected[PRIMARY], PREVIOUS[0])

    def test_either_replayed_metric_mutation_or_missing_candidate_rejected(self):
        for candidate in REPLAYED:
            old, matched = example()
            matched['models'][candidate]['validation_true_positives'] += 1
            with self.assertRaises(ValueError):
                merge_experiments(old, matched)
        old, matched = example()
        del matched['models'][FULL]
        with self.assertRaises(ValueError):
            merge_experiments(old, matched)
        old, matched = example()
        del old['models'][PREVIOUS[-1]]
        with self.assertRaises(ValueError):
            merge_experiments(old, matched)

    def test_three_fixed_comparisons_are_descriptive_and_keep_both_references(self):
        old, matched = example()
        for candidate, july, september, december in ((BASELINE, 21, 52, 65), (FULL, 22, 55, 66)):
            old['models'][candidate]['validation_by_month'] = validation(july, september)
            old['models'][candidate]['development_evaluation']['confusion_matrix'] = [[100, 10], [100-december, december]]
            matched['models'][candidate] = deepcopy(old['models'][candidate])
        matched['models'][NEW[0]]['validation_by_month'] = validation(23, 51)
        matched['models'][NEW[0]]['development_evaluation']['confusion_matrix'] = [[100, 10], [30, 70]]
        targets = compatibility_targets({'folds': [{'name': '2017-12', 'experiment': old}]})
        summary = [{'model_or_selection': c, 'true_positives': tp, 'recall': tp/1642}
                   for c, tp in ((BASELINE, 339), (FULL, 337), (NEW[0], 350))]
        pairs, checks = paired_comparisons([{'name': '2017-12', 'experiment': matched}], summary, targets)
        self.assertEqual(pairs['net_TP_vs_baseline']['count102'], 11)
        self.assertEqual(pairs['net_TP_vs_full104']['count102'], 13)
        count = next(row for row in checks if row['feature_package'] == 'count102')
        self.assertEqual((count['july_difference'], count['september_difference'], count['december_difference']), (2, -1, 5))
        self.assertFalse(count['both_historical_months_not_worse'])
        self.assertTrue(all(row['used_for_selection'] is False for row in checks))


if __name__ == '__main__':
    unittest.main()
