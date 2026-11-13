"""Test paired identity, commit reconciliation and safe numeric publication."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
from math import fsum
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_queries_v50 as analysis
from tests.test_retailrocket_session_knn_query_distribution_v50 import query_fixture


def fixture():
    rows = [dict(query_fixture(), subset_ordinal=index, original_ordinal=100 + index,
                 key_sha256=f'{index:064x}', sql_workload=dict(matches=index)) for index in range(48)]
    all_commit = 48.5
    measured = dict(queries=rows, committed_prefix_rows=0, verified_subset_queries=48,
                    chunk_commits=[dict(completed=True, seconds=all_commit)])
    accounting = dict(costs=dict(verification_seconds=480, rank_seconds=384,
        append_excluding_commit_seconds=96, all_commit_seconds=all_commit, primary_seconds=624.5),
        query_nested_commit_seconds=48, tail_commit_seconds=.5)
    return measured, accounting


class QueryEntryTests(unittest.TestCase):
    def test_query_parts_and_tail_reconcile_without_allocating_tail_to_queries(self):
        measured, accounting = fixture()
        value, identity = analysis.extract_entry(measured, accounting)
        self.assertEqual(value['query_charged_seconds'], 624)
        self.assertEqual(value['tail_commit_seconds'], .5)
        self.assertEqual(value['primary_seconds'], 624.5)
        self.assertEqual(len(identity), 48)
        self.assertEqual(value['queries'][0]['query_charged_seconds'], 13)
        for forbidden in ('key_sha256', 'original_ordinal', 'sql_workload'):
            self.assertNotIn(forbidden, json.dumps(value))

    def test_identity_workload_and_order_changes_are_rejected(self):
        measured, accounting = fixture()
        _, identity = analysis.extract_entry(measured, accounting)
        for field, value in (('original_ordinal', 999), ('key_sha256', 'f' * 64),
                             ('sql_workload', {'matches': 999}), ('subset_ordinal', 1)):
            changed = deepcopy(measured)
            changed['queries'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analysis.extract_entry(changed, accounting, identity)

    def test_missing_duplicate_or_inconsistent_costs_are_rejected(self):
        measured, accounting = fixture()
        changed = deepcopy(measured)
        changed['queries'].pop()
        with self.assertRaisesRegex(ValueError, '48-query'):
            analysis.extract_entry(changed, accounting)
        changed = deepcopy(measured)
        for field in ('original_ordinal', 'key_sha256'):
            changed['queries'][1][field] = changed['queries'][0][field]
        with self.assertRaisesRegex(ValueError, 'Unique'):
            analysis.extract_entry(changed, accounting)
        changed = deepcopy(accounting)
        changed['tail_commit_seconds'] += 1
        with self.assertRaisesRegex(ValueError, 'tail commit'):
            analysis.extract_entry(measured, changed)
        changed = deepcopy(measured)
        changed['chunk_commits'][0]['completed'] = False
        with self.assertRaisesRegex(ValueError, 'Completed'):
            analysis.extract_entry(changed, accounting)


class PairedDistributionTests(unittest.TestCase):
    def test_repeated_positions_have_a_different_positive_denominator_and_warmups_are_separate(self):
        measured, accounting = fixture()
        base, _ = analysis.extract_entry(measured, accounting)
        schedule = analysis.prior.v47.cold.SCHEDULE
        entries = {item['label']: deepcopy(base) for item in schedule}
        nets = (1, -1, 0, 2, -.5, .5)
        for index, net in enumerate(nets, 1):
            entry = entries[f'pair_{index}_C']
            for position, delta in ((0, 1), (1, net - 1)):
                entry['queries'][position]['query_charged_seconds'] += delta
                entry['queries'][position]['parts_seconds']['append'] += delta
            entry['query_charged_seconds'] += net
            entry['tail_commit_seconds'] -= .1
            entry['primary_seconds'] += net - .1
        entries['warm_C']['tail_commit_seconds'] += 1000
        entries['warm_C']['primary_seconds'] += 1000
        value = analysis.summarize_window(entries, schedule, [net - .1 for net in nets])
        pooled = value['pooled_query_differences']
        self.assertEqual(pooled['count'], 288)
        self.assertEqual(pooled['net_seconds'], 2)
        self.assertEqual(pooled['positive_seconds'], 7)
        self.assertEqual(value['position_net_distribution']['positive_seconds'], 6)
        self.assertEqual(value['position_net_distribution']['count'], 48)
        self.assertEqual(value['positive_repeat_histogram']['6'], 1)
        self.assertEqual(value['top_net_positive_positions'][0]['position'], 1)
        self.assertAlmostEqual(value['formal_primary_extra_seconds'], 1.4)
        self.assertAlmostEqual(value['formal_tail_commit_extra_seconds'], -.6)
        self.assertEqual(value['warmup_costs']['C']['tail_commit_seconds'], 1000.5)

    def test_schedule_missing_positions_and_changed_prior_summary_are_rejected(self):
        measured, accounting = fixture()
        base, _ = analysis.extract_entry(measured, accounting)
        schedule = analysis.prior.v47.cold.SCHEDULE
        entries = {item['label']: deepcopy(base) for item in schedule}
        with self.assertRaisesRegex(ValueError, 'schedule'):
            analysis.summarize_window(entries, list(reversed(schedule)), [0] * 6)
        with self.assertRaisesRegex(ValueError, 'V49 paired primary'):
            analysis.summarize_window(entries, schedule, [1] * 6)
        entries['pair_1_C']['queries'].pop()
        with self.assertRaisesRegex(ValueError, '48 fixed positions'):
            analysis.summarize_window(entries, schedule, [0] * 6)

    def test_cli_does_not_expose_measurement(self):
        with patch('sys.argv', ['analysis', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.prior.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
