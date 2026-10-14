"""L2 tuning uses the unchanged historical criterion, not route retest results."""
from copy import deepcopy
import unittest

from scripts.compare_rank_regularization import (
    BASELINE_RANKERS, MATCHED, NEW, PREVIOUS, PRIMARY, REPLAYED, merge_experiments,
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


class RankRegularizationSelectionTests(unittest.TestCase):
    def test_route_and_development_diagnostics_cannot_override_history(self):
        previous, matched = records()
        expected = merge_experiments(previous, matched)['selected_models']
        for record in list(previous['models'].values()) + list(matched['models'].values()):
            record['development_evaluation'] = {'recall': 0, 'true_positives': 0}
            record['route_retest_diagnostics'] = {'SP->SP': {'false_positives': 10000}}
        for c in NEW:
            matched['models'][c]['development_evaluation'] = {'recall': 1, 'true_positives': 100000}
            matched['models'][c]['route_retest_diagnostics'] = {'SP->SP': {'false_positives': 0}}
        self.assertEqual(merge_experiments(previous, matched)['selected_models'], expected)
        self.assertEqual(expected[PRIMARY], NEW[0])

    def test_previous_records_preserved_and_thirty_percent_is_not_selection_filter(self):
        previous, matched = records()
        snapshot = deepcopy(previous)
        result = merge_experiments(previous, matched)
        self.assertEqual(previous, snapshot)
        for c in PREVIOUS:
            self.assertEqual(result['models'][c], previous['models'][c])
        selected = result['selected_models'][PRIMARY]
        self.assertFalse(result['models'][selected]['all_validation_months_meet_30_percent'])
        result['models'][PREVIOUS[0]]['development_evaluation']['recall'] = -1
        self.assertEqual(previous, snapshot)

    def test_exact_historical_ties_retain_original_l2_baseline(self):
        previous, matched = records()
        for c in NEW:
            matched['models'][c] = deepcopy(previous['models'][PREVIOUS[0]])
        selected = merge_experiments(previous, matched)['selected_models']
        self.assertEqual(selected['geo_rank_l2'], BASELINE_RANKERS[0])
        self.assertEqual(selected['backlog_rank_l2'], BASELINE_RANKERS[1])
        self.assertEqual(selected[PRIMARY], PREVIOUS[0])

    def test_changed_replayed_metrics_or_incomplete_candidates_rejected(self):
        for c in REPLAYED:
            previous, matched = records()
            matched['models'][c]['validation_true_positives'] += 1
            with self.assertRaises(ValueError):
                merge_experiments(previous, matched)
        previous, matched = records()
        del matched['models'][MATCHED[-1]]
        with self.assertRaises(ValueError):
            merge_experiments(previous, matched)
        previous, matched = records()
        del previous['models'][PREVIOUS[0]]
        with self.assertRaises(ValueError):
            merge_experiments(previous, matched)


if __name__ == '__main__':
    unittest.main()
