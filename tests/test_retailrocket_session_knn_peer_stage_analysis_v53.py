"""Synthetic entry/reconciliation checks; no original measured records read."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
from math import fsum
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_peer_stages_v53 as analysis
from tests.test_retailrocket_session_knn_workloads_v51 import fixture as saved_fixture


def fixture():
    records = saved_fixture()
    for record in records:
        label = record['label']
        if label.startswith('pair_') and label.endswith('_C'):
            number = int(label.split('_')[1])
            for position, delta, stage in ((32, .010 * number, 'sql_positive_overlaps'),
                    (33, (-.005 if number % 2 else .015) * number, 'sql_selected_votes_and_accumulation')):
                row = record['measured']['queries'][position - 1]
                row['rank_stages_seconds'][stage] += delta
                for field in ('rank_seconds', 'verification_seconds', 'seconds'):
                    row[field] += delta
            rows = record['measured']['queries']
            costs = record['accounting']['costs']
            costs['rank_seconds'] = fsum(row['rank_seconds'] for row in rows)
            costs['verification_seconds'] = fsum(row['verification_seconds'] for row in rows)
            costs['primary_seconds'] = costs['verification_seconds'] + 96 + 48.5
    reference = dict(matching=dict(targets={'32': dict(primary_positions=[33], expanded_positions=[33])}), windows={})
    for window in ('V47', 'V48'):
        entries = {row['label']: row for row in records if row['window'] == window}
        values = {position: [] for position in (32, 33)}
        for number in range(1, 7):
            for position in (32, 33):
                def charged(arm):
                    row = entries[f'pair_{number}_{arm}']['measured']['queries'][position - 1]
                    return row['verification_seconds'] + row['append_without_commit_seconds'] + row['chunk_commit_seconds']
                values[position].append(charged('C') - charged('R'))
        summary = analysis.prior.summarize_peer_variation(values, 32, [33])
        reference['windows'][window] = {'32': dict(primary=summary, expanded=deepcopy(summary))}
    return records, reference


class PeerStageEntryTests(unittest.TestCase):
    def test_full_entries_reconcile_to_prior_and_publish_only_derived_differences(self):
        records, reference = fixture()
        value = analysis.analyze_entries(records, reference)
        self.assertEqual((value['saved_entries_checked'], value['matched_saved_rows']), (28, 1344))
        for window in value['windows'].values():
            self.assertEqual(window['opposite_pair_numbers'], [1, 3, 5])
            self.assertAlmostEqual(window['pairs'][0]['positions']['32']['atomic_delta_seconds']['sql_positive_overlaps'], .01)
            self.assertAlmostEqual(window['pairs'][0]['gap_seconds'], .015)
            self.assertAlmostEqual(window['stage_variation']['atomic']['sql_positive_overlaps']['32']['median'], .035)
            self.assertEqual(window['stage_variation']['groups']['append']['33']['mad'], 0)
        for name in ('key_sha256', 'original_ordinal', 'sql_workload', 'query_envelope_seconds'):
            self.assertNotIn('"' + name + '"', json.dumps(value))

    def test_changed_fixed_peer_or_prior_values_are_rejected(self):
        for mutation in ('peer', 'order', 'total', 'gap', 'reverse_count'):
            records, reference = fixture()
            if mutation == 'peer':
                reference['matching']['targets']['32']['primary_positions'] = [34]
            else:
                for mode in ('primary', 'expanded'):
                    row = reference['windows']['V48']['32'][mode]
                    if mutation == 'order':
                        row['pair_orders'][0] = 'RC'
                    elif mutation == 'total':
                        row['target_summary']['values'][0] += .1
                    elif mutation == 'gap':
                        row['target_minus_peer_median_summary']['values'][0] += .1
                    else:
                        row['peer_summaries'][0]['direction_vs_target']['opposite_sign_count'] += 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_entries(records, reference)

    def test_changed_identity_workload_schedule_and_timer_nesting_are_rejected(self):
        for mutation in ('identity', 'workload', 'schedule', 'nesting'):
            records, reference = fixture()
            row = records[-1]['measured']['queries'][31]
            if mutation == 'identity':
                row['original_ordinal'] += 1000
            elif mutation == 'workload':
                row['sql_workload']['history_rows_inserted'] += 1
            elif mutation == 'schedule':
                records.pop()
            else:
                row['rank_stages_seconds']['sql_positive_overlaps'] += 10
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                analysis.analyze_entries(records, reference)

    def test_warmups_and_tail_commits_do_not_enter_selected_query_differences(self):
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
        with patch('sys.argv', ['stages', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.saved.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
