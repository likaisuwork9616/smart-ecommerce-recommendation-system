"""Artificial saved-entry validation only; no original source is analyzed."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_common_direction_v56 as analysis
from tests.test_retailrocket_session_knn_time_reference_analysis_v55 import fixture as previous_fixture, change_stage


def fixture():
    records, v54 = previous_fixture()
    return records, analysis.prior.analyze_entries(records, v54)


class CommonDirectionEntryTests(unittest.TestCase):
    def test_scope_all_cells_other46_and_complete_v55_reconciliation(self):
        records, reference = fixture()
        before = deepcopy(records)
        result = analysis.analyze_entries(records, reference)
        self.assertEqual(records, before)
        self.assertEqual([result[key] for key in ('saved_entries_checked', 'matched_saved_rows',
            'reference_groups', 'unique_reference_timers', 'run_stage_panels', 'located_cells',
            'other_cells', 'target_cells')], [28, 1344, 192, 1152, 8, 384, 368, 16])
        self.assertTrue(result['v55_groups_and_locations_equal'])
        self.assertEqual([(row['pair'], row['stage']) for row in result['cases']], list(analysis.CASES))
        for case, original in zip(result['cases'], reference['cases']):
            for arm, panel in case['arms'].items():
                self.assertEqual(panel['arm_run_position'], case['order'].index(arm) + 1)
                self.assertEqual(list(panel['positions']), [str(position) for position in range(1, 49)])
                self.assertEqual(panel['other_positions'], [p for p in range(1, 49) if p not in (32, 33)])
                self.assertEqual(panel['other46_summary']['direction_counts'], dict(above=0, equal=46, below=0))
                for position in (32, 33):
                    cell = next(row for row in original['cells'] if row['arm'] == arm and row['position'] == position)
                    expected = {k: v for k, v in cell.items() if k not in ('arm', 'position', 'group_key')}
                    self.assertEqual(panel['positions'][str(position)], expected)
        for field in ('key_sha256', 'original_ordinal', 'sql_workload', 'query_envelope_seconds'):
            self.assertNotIn('"' + field + '"', json.dumps(result))

    def test_other_query_change_enters_only_its_stage_arm_and_own_baseline(self):
        records, reference = fixture()
        before = analysis.analyze_entries(records, reference)
        selected = next(row for row in records if row['window'] == 'V48' and row['label'] == 'pair_2_R')
        change_stage(selected, 1, analysis.STAGES[0], .01)
        after = analysis.analyze_entries(records, reference)
        for old_case, new_case in zip(before['cases'], after['cases']):
            for arm in ('R', 'C'):
                changed = old_case['arms'][arm] != new_case['arms'][arm]
                self.assertEqual(changed, old_case['stage'] == analysis.STAGES[0] and arm == 'R')
                for position in range(1, 49):
                    self.assertEqual(old_case['arms'][arm]['positions'][str(position)] !=
                        new_case['arms'][arm]['positions'][str(position)], changed and position == 1)
        summary = after['cases'][0]['arms']['R']['other46_summary']
        self.assertEqual(summary['direction_counts'], dict(above=1, equal=45, below=0))

    def test_other_five_pair_values_form_each_positions_own_reference(self):
        records, reference = fixture()
        for pair, amount in ((1, .4), (3, .3), (4, .2)):
            record = next(row for row in records if row['window'] == 'V48' and row['label'] == f'pair_{pair}_R')
            change_stage(record, 1, analysis.STAGES[0], amount)
        panel = analysis.analyze_entries(records, reference)['cases'][0]['arms']['R']
        self.assertEqual(panel['positions']['1']['seconds'], 1.)
        self.assertAlmostEqual(panel['positions']['1']['full_six']['median_seconds'], 1.1)
        self.assertEqual(panel['other46_summary']['direction_counts'], dict(above=0, equal=45, below=1))
        self.assertEqual(panel['positions']['2']['delta_from_median_seconds'], 0)

    def test_v47_warmup_and_tail_changes_never_enter_the_eight_panels(self):
        records, reference = fixture()
        expected = analysis.analyze_entries(records, reference)
        for record in records:
            if record['window'] == 'V47' or record['label'].startswith('warm_'):
                change_stage(record, 1, analysis.STAGES[0], 20)
            record['measured']['chunk_commits'][0]['seconds'] += 10
            for key in ('all_commit_seconds', 'primary_seconds'):
                record['accounting']['costs'][key] += 10
            record['accounting']['tail_commit_seconds'] += 10
        self.assertEqual(analysis.analyze_entries(records, reference), expected)

    def test_v55_group_observation_summary_target_or_case_corruption_is_rejected(self):
        for mutation in ('timer', 'summary', 'extra_group', 'target', 'order', 'missing_case'):
            records, reference = fixture()
            group = next(iter(reference['groups'].values()))
            if mutation == 'timer':
                group['observations'][0]['seconds'] += .1
            elif mutation == 'summary':
                group['summary']['median_seconds'] += .1
            elif mutation == 'extra_group':
                reference['groups']['extra'] = deepcopy(group)
            elif mutation == 'target':
                reference['cases'][0]['cells'][0]['rank_desc']['first'] += 1
            elif mutation == 'order':
                reference['cases'][0]['order'] = 'CR'
            else:
                reference['cases'].pop()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_entries(records, reference)

    def test_source_and_non_target_timing_corruption_is_rejected(self):
        for mutation in ('identity', 'workload', 'order', 'missing', 'negative', 'boolean', 'nesting'):
            records, reference = fixture()
            row = records[-1]['measured']['queries'][0]
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

    def test_cli_rejects_measurement_before_taking_lock(self):
        with patch('sys.argv', ['common-direction', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.saved.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
