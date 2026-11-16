"""Synthetic integration of phase extraction, coverage and paired summaries."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_phase_coverage_v60 as analysis
from tests.test_retailrocket_session_knn_phase_accounting_v49 import fixture, event


def entry_fixture():
    events, accounting = fixture()
    raw = dict(records=[dict(sequence=index, monotonic_seconds=float(index), collector_seconds=.01,
                             ignored_resource_value=999) for index in range(102)])
    return events, raw, dict(accounting=accounting)


class CoverageAnalysisTests(unittest.TestCase):
    def test_normalization_uses_ns_and_strips_resource_fields(self):
        records = [dict(sequence=0, monotonic_seconds=1.23456789, collector_seconds=.002, cpu=99)]
        self.assertEqual(analysis.normalize_records(records),
                         [dict(sequence=0, start_ns=1234567890, capture_ns=2000000)])
        self.assertEqual(records[0]['cpu'], 99)

    def test_normalization_rejects_boolean_negative_and_nonfinite(self):
        for value in (False, True, -1, float('nan'), float('inf'), 1e308):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analysis.ns(value)

    def test_seven_phases_integrate_without_resource_or_live_calls(self):
        events, raw, source = entry_fixture()
        before = deepcopy((events, raw, source))
        with patch('psutil.Process', side_effect=AssertionError('No live sampling')):
            result = analysis.analyze_entry(events, raw, source)
        self.assertEqual((events, raw, source), before)
        self.assertEqual(tuple(result['phases']), analysis.PHASES)
        self.assertEqual(result['phases']['post_setup_before_final_guard']['coverage']['phase_duration_ns'], 19_000_000_000)
        self.assertTrue(all(row['coverage']['screen']['eligible'] for row in result['phases'].values()))
        encoded = json.dumps(result)
        for forbidden in ('ignored_resource_value', 'typed_reference', 'cpu_user_seconds', 'key_sha256'):
            self.assertNotIn(forbidden, encoded)

    def test_absolute_clock_shift_does_not_change_public_coverage(self):
        events, raw, source = entry_fixture()
        expected = analysis.analyze_entry(events, raw, source)
        shift = 4000
        for row in events:
            row['start_ns'] += shift * 10**9
            row['end_ns'] += shift * 10**9
        proof = event(events, 'cache.use')['metadata']['typed_reference']
        for row in [proof['build'], *proof['checks']]:
            row['start_ns'] += shift * 10**9
            row['end_ns'] += shift * 10**9
        for row in raw['records']:
            row['monotonic_seconds'] += shift
        self.assertEqual(analysis.analyze_entry(events, raw, source), expected)

    def test_all_pairs_keep_failed_arm_and_exclude_warm_from_counts(self):
        base = analysis.analyze_entry(*entry_fixture())
        entries = {row['label']: deepcopy(base) for row in analysis.SCHEDULE}
        phase = analysis.PHASES[0]
        for label in ('warm_R', 'warm_C', 'pair_3_C'):
            row = entries[label]['phases'][phase]['coverage']
            row['screen']['eligible'] = False
        result = analysis.summarize_window(entries)
        self.assertEqual(len(result['formal_entries']), 12)
        self.assertEqual(len(result['warm_entries']), 2)
        self.assertEqual(result['formal_by_phase'][phase]['R']['eligible_count'], 6)
        self.assertEqual(result['formal_by_phase'][phase]['C']['eligible_count'], 5)
        self.assertEqual(result['formal_by_phase'][phase]['both_eligible_pairs'], [1, 2, 4, 5, 6])
        self.assertFalse(result['pairs'][2]['phases'][phase]['C']['eligible'])
        self.assertEqual([row['order'] for row in result['pairs']], ['CR', 'RC'] * 3)

    def test_missing_entry_or_phase_is_not_silently_omitted(self):
        base = analysis.analyze_entry(*entry_fixture())
        for mutation in ('entry', 'phase'):
            entries = {row['label']: deepcopy(base) for row in analysis.SCHEDULE}
            if mutation == 'entry': entries.pop('pair_6_C')
            else: entries['pair_6_C']['phases'].pop(analysis.PHASES[0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.summarize_window(entries)


if __name__ == '__main__':
    unittest.main()
