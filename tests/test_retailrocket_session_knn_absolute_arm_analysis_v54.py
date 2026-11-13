"""Artificial entry fixtures only; no saved source or benchmark is executed."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_absolute_arms_v54 as analysis
from tests.test_retailrocket_session_knn_peer_stage_analysis_v53 import fixture as previous_fixture


def fixture():
    records, v52 = previous_fixture()
    return records, analysis.prior.analyze_entries(records, v52)


class AbsoluteArmEntryTests(unittest.TestCase):
    def test_all_four_fixed_cases_preserve_absolute_timers_and_reconcile_deltas(self):
        records, reference = fixture()
        result = analysis.analyze_entries(records, reference)
        self.assertEqual((result['saved_entries_checked'], result['matched_saved_rows'],
                          result['selected_absolute_timers']), (28, 1344, 16))
        self.assertEqual([(row['pair'], row['stage']) for row in result['cases']], list(analysis.CASES))
        first = result['cases'][0]
        self.assertEqual(first['absolute_seconds']['R'], {'32': 1., '33': 1.})
        self.assertEqual(first['absolute_seconds']['C']['32'], 1.)
        self.assertAlmostEqual(first['absolute_seconds']['C']['33'], 1.03)
        self.assertAlmostEqual(first['query_delta_seconds']['33'], .03)
        self.assertAlmostEqual(first['gap_seconds'], -.03)
        self.assertEqual(first['alignment']['leading_support_arms'], ['C'])
        for forbidden in ('key_sha256', 'original_ordinal', 'sql_workload', 'query_envelope_seconds'):
            self.assertNotIn('"' + forbidden + '"', json.dumps(result))

    def test_both_position_deltas_are_checked_even_when_prior_gap_is_unchanged(self):
        records, reference = fixture()
        pair = reference['windows']['V48']['pairs'][1]
        stage = analysis.CASES[0][1]
        for position in ('32', '33'):
            pair['positions'][position]['atomic_delta_seconds'][stage] += .1
        with self.assertRaisesRegex(ValueError, 'position'):
            analysis.analyze_entries(records, reference)

    def test_changed_stage_gap_pair_order_or_reference_count_is_rejected(self):
        for mutation in ('gap', 'order', 'count'):
            records, reference = fixture()
            if mutation == 'gap':
                reference['windows']['V48']['pairs'][1]['gap_atomic_seconds'][analysis.CASES[0][1]] += .1
            elif mutation == 'order':
                reference['windows']['V48']['pairs'][1]['order'] = 'CR'
            else:
                reference['windows']['V48']['pairs'].pop()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_entries(records, reference)

    def test_bad_sources_or_timer_nesting_are_rejected_before_publication(self):
        for mutation in ('identity', 'workload', 'missing', 'negative', 'boolean', 'nesting'):
            records, reference = fixture()
            selected = next(row for row in records if row['window'] == 'V48' and row['label'] == 'pair_2_C')
            row = selected['measured']['queries'][31]
            stage = analysis.CASES[0][1]
            if mutation == 'identity':
                row['original_ordinal'] += 1000
            elif mutation == 'workload':
                row['sql_workload']['history_rows_inserted'] += 1
            elif mutation == 'missing':
                records.pop()
            else:
                row['rank_stages_seconds'][stage] = {'negative': -1, 'boolean': True, 'nesting': 100}[mutation]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_entries(records, reference)

    def test_warmup_and_tail_commit_changes_do_not_enter_stage_absolute_values(self):
        records, reference = fixture()
        expected = analysis.analyze_entries(records, reference)
        for record in records:
            amount = 100 if record['label'].startswith('warm_') else 10
            record['measured']['chunk_commits'][0]['seconds'] += amount
            record['accounting']['costs']['all_commit_seconds'] += amount
            record['accounting']['costs']['primary_seconds'] += amount
            record['accounting']['tail_commit_seconds'] += amount
        self.assertEqual(analysis.analyze_entries(records, reference), expected)

    def test_cli_rejects_measurement(self):
        with patch('sys.argv', ['absolute-arms', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.saved.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
