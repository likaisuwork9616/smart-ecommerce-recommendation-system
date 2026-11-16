"""Artificial metric dictionaries only; no historical telemetry is read."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_contained_pairs_v61 import summarize_window
from scripts.retailrocket_session_knn_contained_load_v61 import METRICS
from scripts.retailrocket_session_knn_entry_load_v59 import SCHEDULE
from scripts.retailrocket_session_knn_coarse_phases_v60 import PHASES


def fixture():
    entries = {}
    for row in SCHEDULE:
        label, arm = row['label'], row['mode']
        pair = int(label.split('_')[1]) if label.startswith('pair_') else 1000
        offset = 2 if arm == 'C' else 0
        entries[label] = dict(entry_seconds=10 + pair - offset,
            phases={phase: dict(summary=dict(synthetic=True, selection=dict(pairs=[0, 1])),
                metrics={metric: pair + offset for metric in METRICS}) for phase in PHASES})
    return entries


class ContainedPairsTests(unittest.TestCase):
    def test_all_six_pairs_and_seven_phases_in_original_execution_order(self):
        result = summarize_window(fixture())
        self.assertEqual(list(result['formal_entries']), [row['label'] for row in SCHEDULE[2:]])
        self.assertEqual([row['pair'] for row in result['pairs']], list(range(1, 7)))
        self.assertEqual([row['order'] for row in result['pairs']], ['CR', 'RC'] * 3)
        for pair in result['pairs']:
            self.assertEqual(tuple(pair['phases']), PHASES)
            for phase in pair['phases'].values():
                self.assertEqual(set(phase['R']), set(METRICS))
                for metric in METRICS:
                    self.assertEqual(phase['C'][metric] - phase['R'][metric], 2)
                    self.assertEqual(phase['delta_C_minus_R'][metric], 2)

    def test_warm_outliers_never_enter_formal_summary(self):
        result = summarize_window(fixture())
        first = METRICS[0]
        self.assertEqual(list(result['warm_entries']), ['warm_R', 'warm_C'])
        self.assertEqual(result['warm_entries']['warm_R']['phases'][PHASES[0]]['metrics'][first], 1000)
        for summary in result['formal_by_phase'].values():
            self.assertEqual(summary['R'][first], dict(count=6, valid=6, missing=0, min=1, median=3.5, max=6))
            self.assertEqual(summary['C'][first], dict(count=6, valid=6, missing=0, min=3, median=5.5, max=8))
            self.assertEqual(summary['paired_delta_summary'][first],
                             dict(count=6, valid=6, missing=0, min=2, median=2, max=2))

    def test_full_entry_difference_is_separate_from_phase_metrics(self):
        result = summarize_window(fixture())
        for pair in result['pairs']:
            self.assertEqual(pair['full_entry_delta_C_minus_R'], -2)
            self.assertTrue(all(row['delta_C_minus_R'][METRICS[0]] == 2 for row in pair['phases'].values()))

    def test_missing_one_arm_stays_null_and_summary_has_valid_denominator(self):
        entries = fixture()
        metric, phase = METRICS[0], PHASES[0]
        entries['pair_2_C']['phases'][phase]['metrics'][metric] = None
        result = summarize_window(entries)
        self.assertIsNone(result['pairs'][1]['phases'][phase]['delta_C_minus_R'][metric])
        self.assertEqual(result['formal_by_phase'][phase]['C'][metric],
                         dict(count=6, valid=5, missing=1, min=3, median=6, max=8))
        self.assertEqual(result['formal_by_phase'][phase]['paired_delta_summary'][metric],
                         dict(count=6, valid=5, missing=1, min=2, median=2, max=2))

    def test_all_missing_remain_present_not_zero_or_dropped(self):
        entries = fixture()
        phase, metric = PHASES[0], METRICS[0]
        for label in entries:
            if label.endswith('_C'):
                entries[label]['phases'][phase]['metrics'][metric] = None
        result = summarize_window(entries)
        self.assertEqual(result['formal_by_phase'][phase]['paired_delta_summary'][metric],
                         dict(count=6, valid=0, missing=6, min=None, median=None, max=None))
        self.assertEqual(len(result['pairs']), 6)
        self.assertTrue(all(phase in pair['phases'] for pair in result['pairs']))

    def test_input_and_output_views_are_detached(self):
        entries = fixture()
        before = deepcopy(entries)
        result = summarize_window(entries)
        self.assertEqual(entries, before)
        result['formal_entries']['pair_1_C']['phases'][PHASES[0]]['summary']['selection']['pairs'].append(99)
        result['warm_entries']['warm_R']['phases'][PHASES[0]]['metrics'][METRICS[0]] = 0
        result['pairs'][0]['phases'][PHASES[0]]['C'][METRICS[0]] = 123
        self.assertEqual(entries, before)
        self.assertEqual(result['formal_entries']['pair_1_C']['phases'][PHASES[0]]['metrics'][METRICS[0]], 3)

    def test_missing_extra_entry_phase_and_metric_are_rejected(self):
        for mutation in ('entry_missing', 'entry_extra', 'phase_missing', 'phase_extra', 'metric_missing', 'metric_extra'):
            entries = fixture()
            if mutation == 'entry_missing': entries.pop('pair_6_C')
            elif mutation == 'entry_extra': entries['publisher'] = deepcopy(entries['warm_R'])
            elif mutation == 'phase_missing': entries['pair_6_C']['phases'].pop(PHASES[0])
            elif mutation == 'phase_extra': entries['pair_6_C']['phases']['unknown'] = deepcopy(entries['pair_6_C']['phases'][PHASES[0]])
            elif mutation == 'metric_missing': entries['pair_6_C']['phases'][PHASES[0]]['metrics'].pop(METRICS[0])
            else: entries['pair_6_C']['phases'][PHASES[0]]['metrics']['unknown'] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                summarize_window(entries)

    def test_invalid_entry_and_absolute_metric_values_are_rejected(self):
        for field in ('entry', 'metric'):
            for value in (False, True, float('nan'), float('inf'), -1, '1'):
                entries = fixture()
                if field == 'entry': entries['pair_1_R']['entry_seconds'] = value
                else: entries['pair_1_R']['phases'][PHASES[0]]['metrics'][METRICS[0]] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    summarize_window(entries)
        entries = fixture()
        entries['pair_1_R']['entry_seconds'] = 0
        with self.assertRaises(ValueError): summarize_window(entries)


if __name__ == '__main__':
    unittest.main()
