"""The matched objective experiment must keep historical-only selection."""
from copy import deepcopy
import unittest

from scripts.compare_backlog_objectives import (
    CLASSIFIERS, MATCHED, PREVIOUS, PRIMARY, RANKERS, merge_experiments,
)


def records():
    previous = {'models': {c: {
        'minimum_validation_month_recall': .2, 'validation_true_positives': 20,
        'validation_pooled_average_precision': .1,
        'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .9, 'true_positives': 999},
    } for c in PREVIOUS}, 'selected_models': {PRIMARY: PREVIOUS[0]}}
    matched = {'models': {c: deepcopy(previous['models'][c]) for c in CLASSIFIERS}}
    for candidate in RANKERS:
        matched['models'][candidate] = {
            'minimum_validation_month_recall': .25, 'validation_true_positives': 25,
            'validation_pooled_average_precision': .12,
            'all_validation_months_meet_30_percent': False,
            'development_evaluation': {'recall': .01, 'true_positives': 1},
        }
    return previous, matched


class ObjectiveSelectionTests(unittest.TestCase):
    def test_development_results_cannot_change_any_selection(self):
        previous, matched = records()
        expected = merge_experiments(previous, matched)['selected_models']
        altered_previous, altered_matched = deepcopy(previous), deepcopy(matched)
        for record in list(altered_previous['models'].values()) + list(altered_matched['models'].values()):
            record['development_evaluation'] = {'recall': 0, 'true_positives': 0}
        for candidate in RANKERS:
            altered_matched['models'][candidate]['development_evaluation'] = {'recall': 1, 'true_positives': 100000}
        self.assertEqual(merge_experiments(altered_previous, altered_matched)['selected_models'], expected)
        self.assertEqual(expected[PRIMARY], RANKERS[0])

    def test_original_records_are_unchanged_and_floor_is_suitability_only(self):
        previous, matched = records()
        snapshot = deepcopy(previous)
        result = merge_experiments(previous, matched)
        self.assertEqual(previous, snapshot)
        for candidate in PREVIOUS:
            self.assertEqual(result['models'][candidate], snapshot['models'][candidate])
        selected = result['selected_models'][PRIMARY]
        self.assertFalse(result['models'][selected]['all_validation_months_meet_30_percent'])
        result['models'][PREVIOUS[0]]['development_evaluation']['recall'] = -1
        self.assertEqual(previous, snapshot)

    def test_fixed_candidate_order_breaks_complete_historical_ties(self):
        previous, matched = records()
        for candidate in RANKERS:
            matched['models'][candidate] = deepcopy(previous['models'][PREVIOUS[0]])
        selected = merge_experiments(previous, matched)['selected_models']
        self.assertEqual(selected[PRIMARY], PREVIOUS[0])
        self.assertEqual(selected['geo_objectives'], CLASSIFIERS[0])
        self.assertEqual(selected['backlog_objectives'], CLASSIFIERS[1])

    def test_changed_baseline_and_missing_candidates_are_rejected(self):
        previous, matched = records()
        matched['models'][CLASSIFIERS[0]]['validation_true_positives'] += 1
        with self.assertRaisesRegex(ValueError, 'Frozen classifier metrics changed'):
            merge_experiments(previous, matched)
        previous, matched = records()
        del previous['models'][PREVIOUS[0]]
        with self.assertRaises(ValueError):
            merge_experiments(previous, matched)
        previous, matched = records()
        del matched['models'][MATCHED[-1]]
        with self.assertRaises(ValueError):
            merge_experiments(previous, matched)


if __name__ == '__main__':
    unittest.main()
