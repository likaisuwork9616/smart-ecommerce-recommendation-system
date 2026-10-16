"""Frozen 79-candidate context and historical-only single-feature selection."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts import train_unobserved_handover_age as comparison


def example():
    old = {'models': {candidate: {
        'minimum_validation_month_recall': .20, 'validation_true_positives': 20,
        'validation_pooled_average_precision': .1,
        'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .9, 'confusion_matrix': [[10, 0], [1, 9]]},
    } for candidate in comparison.PREVIOUS}, 'selected_models': {comparison.PRIMARY: comparison.PREVIOUS[0]}}
    matched = {'models': {comparison.BASELINE: deepcopy(old['models'][comparison.BASELINE]),
        comparison.NEW[0]: {'minimum_validation_month_recall': .25, 'validation_true_positives': 25,
        'validation_pooled_average_precision': .12, 'all_validation_months_meet_30_percent': False,
        'development_evaluation': {'recall': .01, 'confusion_matrix': [[10, 0], [9, 1]]}}}}
    return old, matched


def validation(july, september):
    return {month: {'known_outcome_metrics': {'confusion_matrix': [[100, 0], [100-tp, tp]]}}
            for month, tp in [('2017-07', july), ('2017-09', september)]}


class UnobservedHandoverAgeSelectionTests(unittest.TestCase):
    def test_development_and_subgroup_descriptions_never_select_models(self):
        old, matched = example()
        expected = comparison.merge_experiments(old, matched)['selected_models']
        self.assertEqual(expected[comparison.PRIMARY], comparison.NEW[0])
        for item in [*old['models'].values(), *matched['models'].values()]:
            item['development_evaluation'] = {'recall': 0, 'confusion_matrix': [[0, 0], [0, 0]]}
            item['common_misses_recovered'] = 999999
        matched['models'][comparison.NEW[0]]['development_evaluation']['recall'] = 999999
        self.assertEqual(comparison.merge_experiments(old, matched)['selected_models'], expected)

    def test_all79_previous_metrics_remain_frozen_and_30_percent_only_describes_suitability(self):
        old, matched = example()
        snapshot = deepcopy(old)
        result = comparison.merge_experiments(old, matched)
        self.assertEqual((len(comparison.PREVIOUS), len(comparison.ORDER)), (79, 80))
        self.assertEqual(comparison.REPLAYED, (comparison.BASELINE,))
        for candidate in comparison.PREVIOUS:
            self.assertEqual(result['models'][candidate], snapshot['models'][candidate])
        self.assertFalse(result['models'][result['selected_models'][comparison.PRIMARY]]['all_validation_months_meet_30_percent'])
        result['models'][comparison.BASELINE]['validation_true_positives'] = -1
        self.assertEqual(old, snapshot)

    def test_historical_ties_keep_old_fixed_order(self):
        old, matched = example()
        matched['models'][comparison.NEW[0]] = deepcopy(old['models'][comparison.BASELINE])
        selected = comparison.merge_experiments(old, matched)['selected_models']
        self.assertEqual(selected['unobserved_handover_age_ablation'], comparison.BASELINE)
        self.assertEqual(selected[comparison.PRIMARY], comparison.PREVIOUS[0])

    def test_changed_replay_or_missing_candidates_are_rejected(self):
        old, matched = example()
        matched['models'][comparison.BASELINE]['validation_true_positives'] += 1
        with self.assertRaises(ValueError):
            comparison.merge_experiments(old, matched)
        old, matched = example()
        del matched['models'][comparison.BASELINE]
        with self.assertRaises(ValueError):
            comparison.merge_experiments(old, matched)
        old, matched = example()
        del old['models'][comparison.PREVIOUS[-1]]
        with self.assertRaises(ValueError):
            comparison.merge_experiments(old, matched)

    def test_paired_descriptions_keep_only101_and_new102_without_selection_target(self):
        old, matched = example()
        old['models'][comparison.BASELINE]['validation_by_month'] = validation(21, 52)
        old['models'][comparison.BASELINE]['development_evaluation']['confusion_matrix'] = [[100, 10], [35, 65]]
        matched['models'][comparison.BASELINE] = deepcopy(old['models'][comparison.BASELINE])
        matched['models'][comparison.NEW[0]]['validation_by_month'] = validation(23, 51)
        matched['models'][comparison.NEW[0]]['development_evaluation']['confusion_matrix'] = [[100, 10], [30, 70]]
        targets = comparison.compatibility_targets({'folds': [{'name': '2017-12', 'experiment': old}]})
        summary = [{'model_or_selection': candidate, 'true_positives': tp, 'recall': tp/1642}
                   for candidate, tp in ((comparison.BASELINE, 339), (comparison.NEW[0], 350))]
        paired, checks = comparison.paired_comparisons([{'name': '2017-12', 'experiment': matched}], summary, targets)
        self.assertEqual(set(paired['candidates_by_feature_set'].values()), set(comparison.MATCHED))
        self.assertEqual(paired['net_TP_vs_baseline']['unobserved_handover_age102'], 11)
        new = next(row for row in checks if row['candidate'] == comparison.NEW[0])
        self.assertEqual((new['july_difference'], new['september_difference'], new['december_difference']), (2, -1, 5))
        self.assertTrue(all(row['used_for_selection'] is False for row in checks))

    def test_fixed_report_preserves_bytes_and_rejects_changes(self):
        temporary_root = comparison.ROOT / '.runtime/tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            path = Path(directory) / 'specification.json'
            comparison.fixed_json(path, {'fixed': 10})
            original = path.read_bytes()
            comparison.fixed_json(path, {'fixed': 10})
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
                comparison.fixed_json(path, {'fixed': 20})
            self.assertEqual(json.loads(path.read_text()), {'fixed': 10})

    def test_mature_training_identity_order_query_and_parameter_mismatch_rejected(self):
        train = pd.DataFrame({'order_id': ['b', 'a', 'c'], 'prediction_time': pd.to_datetime([
            '2017-09-01 02:00', '2017-09-01 01:00', '2017-09-02 01:00'])})
        info = {'training_order_sha256': hashlib.sha256(b'a\nb\nc').hexdigest(),
            'daily_training_groups': [2, 1], 'classifier_parameters': {'n_estimators': 400},
            'ranker_parameters': {'objective': 'rank:ndcg'}, 'training_jobs': 2, 'prediction_jobs': 1,
            'training_design': 'deadline_wait0', 'daily_training_query_counts': {'queries': 2},
            'reg_lambda': 100., 'pair_method': 'topk', 'pair_focus_k': 10}
        comparison.verify_training_contract(train, info, deepcopy(info))
        legacy = deepcopy(info)
        legacy.pop('pair_method')
        legacy['classifier_parameters']['lambdarank_pair_method'] = 'topk'
        current = deepcopy(info)
        current['classifier_parameters']['lambdarank_pair_method'] = 'topk'
        comparison.verify_training_contract(train, current, legacy)
        for field, value in [('training_order_sha256', 'bad'), ('daily_training_groups', [1, 2]),
                             ('training_jobs', 4), ('classifier_parameters', {'n_estimators': 3})]:
            changed = deepcopy(info)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                comparison.verify_training_contract(train, changed, info)

    def test_feature_quality_keeps_fractional_ages_and_missing_but_rejects_negative_infinite(self):
        name = comparison.ADDED_FEATURES[0]
        data = pd.DataFrame({'prediction_time': pd.to_datetime(['2017-09-01']*3), name: [0.5, 2.75, float('nan')]})
        quality = comparison.feature_quality(data)['overall']
        self.assertEqual((quality['age_observed'], quality['age_missing']), (2, 1))
        self.assertEqual(quality['age_feature_median_hours'], 1.625)
        missing = comparison.feature_quality(data.assign(**{name: float('nan')}))['overall']
        self.assertEqual((missing['age_observed'], missing['age_missing']), (0, 3))
        self.assertIsNone(missing['age_feature_median_hours'])
        for value in (-1., float('inf')):
            with self.assertRaises(ValueError):
                comparison.feature_quality(data.assign(**{name: value}))


if __name__ == '__main__':
    unittest.main()
