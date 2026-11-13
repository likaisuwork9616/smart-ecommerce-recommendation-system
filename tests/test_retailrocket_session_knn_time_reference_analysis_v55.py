"""Synthetic saved-entry tests only; no original records or experiments."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_time_reference_v55 as analysis
from tests.test_retailrocket_session_knn_absolute_arm_analysis_v54 import fixture as previous_fixture


def fixture():
    records, reference = previous_fixture()
    return records, analysis.prior.analyze_entries(records, reference)


def change_stage(record, position, stage, amount):
    row = record['measured']['queries'][position - 1]
    row['rank_stages_seconds'][stage] += amount
    for key in ('rank_seconds', 'verification_seconds', 'seconds'):
        row[key] += amount
    for key in ('rank_seconds', 'verification_seconds', 'primary_seconds'):
        record['accounting']['costs'][key] += amount


class TimeReferenceEntryTests(unittest.TestCase):
    def test_eight_groups_six_observations_and_all_sixteen_targets_are_retained(self):
        records, reference = fixture()
        before = deepcopy(records)
        result = analysis.analyze_entries(records, reference)
        self.assertEqual(records, before)
        self.assertEqual((result['saved_entries_checked'], result['matched_saved_rows'],
                          result['unique_reference_timers'], result['target_absolute_timers']), (28, 1344, 48, 16))
        self.assertEqual(len(result['groups']), 8)
        self.assertEqual([(row['pair'], row['stage']) for row in result['cases']], list(analysis.CASES))
        for group in result['groups'].values():
            self.assertEqual([row['pair'] for row in group['observations']], list(range(1, 7)))
            self.assertEqual([row['order'] for row in group['observations']], list(analysis.ORDERS))
            for row in group['observations']:
                self.assertEqual(row['arm_run_position'], row['order'].index(group['arm']) + 1)
        first = result['cases'][0]
        self.assertEqual([(cell['arm'], cell['position']) for cell in first['cells']],
                         [('R', 32), ('R', 33), ('C', 32), ('C', 33)])
        for case, source in zip(result['cases'], reference['cases']):
            for cell in case['cells']:
                self.assertEqual(cell['seconds'], source['absolute_seconds'][cell['arm']][str(cell['position'])])
                self.assertEqual(cell['other_five']['count'], 5)
        tied = first['cells'][0]
        self.assertEqual(tied['rank_desc'], dict(first=1, last=6))
        self.assertEqual(tied['counts'], dict(below=0, equal=6, above=0))
        # Candidate vote values: .995, 1.03, .985, 1.06, .975, 1.09.
        located = first['cells'][3]
        self.assertAlmostEqual(located['full_six']['median_seconds'], 1.0125)
        self.assertAlmostEqual(located['other_five']['median_seconds'], .995)
        self.assertEqual(located['rank_desc'], dict(first=3, last=3))
        for key in ('key_sha256', 'original_ordinal', 'sql_workload', 'query_envelope_seconds'):
            self.assertNotIn('"' + key + '"', json.dumps(result))

    def test_reference_groups_never_mix_stage_arm_or_position(self):
        records, reference = fixture()
        before = analysis.analyze_entries(records, reference)
        selected = next(row for row in records if row['window'] == 'V48' and row['label'] == 'pair_6_C')
        stage = 'sql_positive_overlaps'
        change_stage(selected, 32, stage, .2)
        after = analysis.analyze_entries(records, reference)
        key = analysis.group_key(stage, 'C', 32)
        changed = [name for name in before['groups'] if before['groups'][name] != after['groups'][name]]
        self.assertEqual(changed, [key])
        for old_case, new_case in zip(before['cases'], after['cases']):
            for old_cell, new_cell in zip(old_case['cells'], new_case['cells']):
                self.assertEqual(old_cell != new_cell, old_cell['group_key'] == key)

    def test_other_five_excludes_only_current_pair_and_keeps_other_target(self):
        records, reference = fixture()
        result = analysis.analyze_entries(records, reference)
        second = result['cases'][1]['cells'][3]
        # Pair 3 is removed; pair 2 remains. Other five median is 1.03.
        self.assertAlmostEqual(second['other_five']['median_seconds'], 1.03)
        self.assertAlmostEqual(second['other_five']['min_seconds'], .975)

    def test_v47_warmups_and_tail_commits_do_not_enter_reference_times(self):
        records, reference = fixture()
        expected = analysis.analyze_entries(records, reference)
        for record in records:
            if record['window'] == 'V47' or record['label'].startswith('warm_'):
                change_stage(record, 32, analysis.STAGES[0], 20)
            record['measured']['chunk_commits'][0]['seconds'] += 10
            for key in ('all_commit_seconds', 'primary_seconds'):
                record['accounting']['costs'][key] += 10
            record['accounting']['tail_commit_seconds'] += 10
        self.assertEqual(analysis.analyze_entries(records, reference), expected)

    def test_changed_v54_absolute_timer_order_or_case_set_is_rejected(self):
        for mutation in ('timer', 'order', 'stage', 'missing', 'duplicate'):
            records, reference = fixture()
            if mutation == 'timer':
                reference['cases'][0]['absolute_seconds']['R']['32'] += .1
            elif mutation == 'order':
                reference['cases'][0]['order'] = 'CR'
            elif mutation == 'stage':
                reference['cases'][0]['stage'] = 'sql_positive_overlaps'
            elif mutation == 'missing':
                reference['cases'].pop()
            else:
                reference['cases'][1] = deepcopy(reference['cases'][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_entries(records, reference)

    def test_source_identity_workload_schedule_and_bad_timers_are_rejected(self):
        for mutation in ('identity', 'workload', 'order', 'missing', 'negative', 'boolean', 'nesting'):
            records, reference = fixture()
            row = records[-1]['measured']['queries'][31]
            if mutation == 'identity':
                row['original_ordinal'] += 1000
            elif mutation == 'workload':
                row['sql_workload']['history_rows_inserted'] += 1
            elif mutation == 'order':
                records[0], records[1] = records[1], records[0]
            elif mutation == 'missing':
                records.pop()
            else:
                row['rank_stages_seconds'][analysis.STAGES[0]] = {'negative': -1, 'boolean': True, 'nesting': 100}[mutation]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_entries(records, reference)

    def test_cli_rejects_measurement_before_lock(self):
        with patch('sys.argv', ['time-reference', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.saved.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
