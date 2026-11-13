"""Synthetic saved-entry and fixed-pair integration; no real records used."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_peers_v52 as analysis
from tests.test_retailrocket_session_knn_workloads_v51 import fixture as saved_fixture


def records_fixture():
    records = saved_fixture()
    for record in records:
        for row in record['measured']['queries']:
            row['sql_workload']['sql_selected_rows_inserted'] = 500
    return records


def timing_fixture():
    pairs = [dict(pair=index, order=order,
                  position_extras_seconds=[(position - 25) * index / 10000 for position in range(1, 49)])
             for index, order in enumerate(analysis.saved.v47.cold.ORDERS, 1)]
    return dict(pairs=pairs, positions=[dict(position=position, distribution=analysis.timing.signed_distribution(
        row['position_extras_seconds'][position - 1] for row in pairs)) for position in range(1, 49)])


class SavedPeerTests(unittest.TestCase):
    def test_matching_uses_workload_and_excludes_both_targets(self):
        records = records_fixture()
        expected = analysis.match_entries(records)
        changed = deepcopy(records)
        for row in changed[0]['measured']['queries']:
            row['seconds'] += 1000
        self.assertEqual(analysis.match_entries(changed), expected)
        self.assertEqual(expected['matched_saved_rows'], 1344)
        self.assertEqual(expected['unique_queries_counted'], 48)
        for target in expected['matching']['targets'].values():
            self.assertFalse({32, 38} & set(target['expanded_positions']))
            self.assertTrue(set(target['primary_positions']) <= set(target['expanded_positions']))
        for forbidden in ('key_sha256', 'original_ordinal', 'sql_workload'):
            self.assertNotIn('"' + forbidden + '"', json.dumps(expected))

    def test_changed_or_missing_saved_entries_are_rejected(self):
        records = records_fixture()
        with self.assertRaisesRegex(ValueError, 'schedules'):
            analysis.match_entries(records[:-1])
        records[-1]['measured']['queries'][0]['sql_workload']['history_rows_inserted'] += 1
        with self.assertRaisesRegex(ValueError, 'workload changed'):
            analysis.match_entries(records)

    def test_window_keeps_frozen_primary_and_expanded_sets(self):
        matching = analysis.match_entries(records_fixture())['matching']
        result = analysis.compare_window(timing_fixture(), matching)
        for target in (32, 38):
            for mode, key in (('primary', 'primary_positions'), ('expanded', 'expanded_positions')):
                selected = matching['targets'][str(target)][key]
                direct = analysis.summarize_peer_variation(
                    {position: [(position - 25) * index / 10000 for index in range(1, 7)]
                     for position in range(1, 49)}, target, selected)
                self.assertEqual(result[str(target)][mode], direct)

    def test_changed_pair_order_count_or_summary_is_rejected(self):
        matching = analysis.match_entries(records_fixture())['matching']
        for mutation in ('order', 'pairs', 'cells', 'summary', 'positions'):
            comparison = timing_fixture()
            if mutation == 'order':
                comparison['pairs'][0]['order'] = 'RC'
            elif mutation == 'pairs':
                comparison['pairs'].pop()
            elif mutation == 'cells':
                comparison['pairs'][0]['position_extras_seconds'].pop()
            elif mutation == 'summary':
                comparison['positions'][0]['distribution']['median'] += 1
            else:
                comparison['positions'].reverse()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.compare_window(comparison, matching)

    def test_cli_rejects_measurement(self):
        with patch('sys.argv', ['peers', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.saved.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
