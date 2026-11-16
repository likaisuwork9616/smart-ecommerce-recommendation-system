"""Synthetic orchestration checks for all seven retained coarse phases."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_contained_load_v61 as analysis


def fixture():
    return dict(phases={name: dict(source_kind='synthetic', source_event_ids=[index],
        coverage=dict(tag=name, screen=dict(eligible=index != 0)))
        for index, name in enumerate(analysis.PHASES)})


class ContainedLoadAnalysisTests(unittest.TestCase):
    def test_seven_phases_keep_failed_screen_without_filtering(self):
        source = fixture()
        records = [dict(sentinel='synthetic')]
        with patch.object(analysis, 'summarize_selected', side_effect=lambda raw, coverage: dict(tag=coverage['tag'])) as call, \
                patch.object(analysis, 'flatten_metrics', return_value=dict(phase_seconds=1.)):
            result = analysis.analyze_entry(records, source, 10.)
        self.assertEqual(call.call_count, 7)
        self.assertEqual(tuple(result['phases']), analysis.PHASES)
        self.assertFalse(result['phases'][analysis.PHASES[0]]['coverage_screen']['eligible'])
        self.assertEqual(result['entry_seconds'], 10.)
        for name, row in result['phases'].items():
            self.assertEqual(row['summary']['tag'], name)

    def test_missing_extra_and_reordered_phases_are_rejected(self):
        for change in ('missing', 'extra', 'order'):
            source = fixture()
            if change == 'missing': source['phases'].pop(analysis.PHASES[0])
            elif change == 'extra': source['phases']['unknown'] = deepcopy(source['phases'][analysis.PHASES[0]])
            else: source['phases'] = dict(reversed(list(source['phases'].items())))
            with self.subTest(change=change), self.assertRaises(ValueError):
                analysis.analyze_entry([], source, 10.)

    def test_original_coverage_and_provenance_remain_unchanged(self):
        source = fixture()
        before = deepcopy(source)
        with patch.object(analysis, 'summarize_selected', return_value={}), \
                patch.object(analysis, 'flatten_metrics', return_value={}):
            result = analysis.analyze_entry([], source, 10.)
        row = result['phases'][analysis.PHASES[0]]
        row['source_event_ids'].append(999)
        row['coverage_screen']['eligible'] = True
        self.assertEqual(source, before)


if __name__ == '__main__':
    unittest.main()
