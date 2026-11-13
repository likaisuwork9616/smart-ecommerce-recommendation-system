"""Synthetic V56 references only; no real source or experiment is loaded."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_segments_v57 as analysis
from tests.test_retailrocket_session_knn_common_direction_analysis_v56 import fixture as previous_fixture


def fixture():
    records, v55 = previous_fixture()
    return analysis.prior.analyze_entries(records, v55)


class SegmentReferenceTests(unittest.TestCase):
    def test_fixed_eight_panels_and_ninety_six_blocks_reconcile_to_v56(self):
        reference = fixture()
        before = deepcopy(reference)
        result = analysis.analyze_reference(reference)
        self.assertEqual(reference, before)
        self.assertEqual([result[k] for k in ('run_stage_panels', 'located_cells', 'other_cells',
            'target_cells', 'block_summaries')], [8, 384, 368, 16, 96])
        for case, source in zip(result['cases'], reference['cases']):
            self.assertEqual((case['pair'], case['order'], case['stage']),
                             (source['pair'], source['order'], source['stage']))
            for arm, panel in case['arms'].items():
                self.assertEqual(panel['arm_run_position'], case['order'].index(arm) + 1)
                self.assertEqual([row['position'] for row in panel['positions']], list(range(1, 49)))
                self.assertEqual([b['count'] for b in panel['views']['other46']['blocks']], [8, 8, 8, 7, 7, 8])
                self.assertEqual([b['count'] for b in panel['views']['all48']['blocks']], [8] * 6)
                self.assertEqual([(b['start'], b['end']) for b in panel['views']['all48']['blocks']], list(analysis.BLOCKS))
                for row in panel['positions']:
                    self.assertEqual(row['delta_seconds'], source['arms'][arm]['positions'][str(row['position'])]
                                     ['delta_from_median_seconds'])
        self.assertTrue(result['all48_equals_other46_plus_targets'])
        for key in ('key_sha256', 'original_ordinal', 'sql_workload', 'query_envelope_seconds'):
            self.assertNotIn('"' + key + '"', json.dumps(result))

    def test_target_is_retained_in_all48_but_breaks_primary_runs(self):
        result = analysis.analyze_reference(fixture())
        panel = result['cases'][2]['arms']['C']
        self.assertGreater(panel['positions'][31]['delta_seconds'], .001)
        full = panel['views']['all48']['modes']['over_1ms']
        other = panel['views']['other46']['modes']['over_1ms']
        self.assertEqual(full['longest']['above']['segments'], [dict(start=32, end=32, length=1)])
        self.assertEqual(other['runs'], [])
        self.assertEqual(other['sequence'][31:33], 'xx')

    def test_changed_scope_case_arm_order_and_position_set_are_rejected(self):
        for mutation in ('scope', 'case', 'arm', 'arm_order', 'missing_position', 'wrong_key_type'):
            reference = fixture()
            panel = reference['cases'][0]['arms']['R']
            if mutation == 'scope':
                reference['unique_reference_timers'] -= 1
            elif mutation == 'case':
                reference['cases'][0], reference['cases'][1] = reference['cases'][1], reference['cases'][0]
            elif mutation == 'arm':
                reference['cases'][0]['arms']['extra'] = deepcopy(panel)
            elif mutation == 'arm_order':
                panel['arm_run_position'] = 2
            elif mutation == 'missing_position':
                panel['positions'].pop('48')
            else:
                panel['positions'][1] = panel['positions'].pop('1')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_reference(reference)

    def test_target_and_own_median_delta_reconciliation_rejects_corruption(self):
        for mutation in ('delta', 'seconds', 'median', 'pair', 'target', 'boolean', 'nonfinite'):
            reference = fixture()
            panel = reference['cases'][0]['arms']['R']
            cell = panel['positions']['1']
            if mutation == 'delta':
                cell['delta_from_median_seconds'] += .01
            elif mutation == 'seconds':
                cell['seconds'] += .01
            elif mutation == 'median':
                cell['full_six']['median_seconds'] += .01
            elif mutation == 'pair':
                cell['pair'] = 3
            elif mutation == 'target':
                panel['target_comparisons']['32']['delta_seconds'] += .01
            elif mutation == 'boolean':
                cell['delta_from_median_seconds'] = False
            else:
                cell['seconds'] = float('nan')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_reference(reference)

    def test_both_v56_direction_modes_and_other46_membership_are_checked(self):
        for mutation in ('raw', 'threshold', 'members', 'count'):
            reference = fixture()
            panel = reference['cases'][0]['arms']['R']
            if mutation == 'raw':
                panel['other46_summary']['direction_counts']['above'] += 1
            elif mutation == 'threshold':
                panel['other46_summary']['over_1ms_counts']['below'] += 1
            elif mutation == 'members':
                panel['other_positions'][-1] = 32
            else:
                panel['other46_summary']['count'] = 48
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_reference(reference)

    def test_cli_rejects_measurement_before_taking_lock(self):
        with patch('sys.argv', ['segments', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.saved.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
