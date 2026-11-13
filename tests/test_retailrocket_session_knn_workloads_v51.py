"""Check offline matching and publication using artificial counters only."""
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_workloads_v51 as analysis
from tests.test_retailrocket_session_knn_queries_v50 import fixture as query_fixture


def fixture():
    measured, accounting = query_fixture()
    fields = ('history_rows_inserted', 'sql_overlap_groups_returned',
        'sql_overlap_membership_matches', 'neighbor_pool_rows_hashed',
        'sql_selected_rows_inserted', 'sql_vote_membership_rows_returned',
        'fraction_vote_additions', 'fallback_catalog_rows_examined',
        'catalog_snapshot_rows_prepared', 'causal_catalog_candidates',
        'positive_causal_candidates', 'exact_vote_additions', 'integer_vote_additions',
        'vote_scale_bits', 'distinct_neighbor_similarities')
    for index, row in enumerate(measured['queries'], 1):
        row['sql_workload'] = dict.fromkeys(fields, index)
        row['sql_workload']['fraction_fallback'] = False
    return [dict(window=window, label=item['label'], measured=deepcopy(measured), accounting=deepcopy(accounting))
            for window in ('V47', 'V48') for item in analysis.saved.v47.cold.SCHEDULE]


class SavedWorkloadTests(unittest.TestCase):
    def test_repetitions_collapse_to_48_and_publish_no_identity_or_raw_matrix(self):
        value = analysis.collect_entries(fixture())
        self.assertEqual(value['saved_entries_checked'], 28)
        self.assertEqual(value['matched_saved_rows'], 1344)
        self.assertEqual(value['unique_queries_counted'], 48)
        self.assertTrue(value['warmups_used_for_identity_check_only'])
        metric = value['comparison']['metrics']['neighbor_pool_rows_hashed']
        self.assertEqual(metric['all48']['sum'], 1176)
        self.assertEqual(metric['excluding_targets46']['sum'], 1106)
        self.assertEqual(metric['targets']['32']['rank_first'], 17)
        self.assertEqual(metric['targets']['38']['rank_first'], 11)
        text = json.dumps(value)
        for field in ('key_sha256', 'original_ordinal', 'subset_ordinal', 'sql_workload', 'queries'):
            self.assertNotIn('"' + field + '"', text)

    def test_missing_duplicate_reordered_or_extra_entries_are_rejected(self):
        rows = fixture()
        variants = (rows[:-1], rows + [rows[-1]], [rows[1], rows[0], *rows[2:]],
                    [rows[0], rows[0], *rows[2:]])
        for records in variants:
            with self.subTest(labels=[r['label'] for r in records]), self.assertRaisesRegex(ValueError, 'schedules'):
                analysis.collect_entries(records)

    def test_changed_identity_workload_and_order_including_warmups_are_rejected(self):
        for index in (1, 14, 27):
            for field, replacement in (('original_ordinal', 999), ('key_sha256', 'f' * 64),
                                       ('subset_ordinal', 1), ('sql_workload', {'bad': 3})):
                records = fixture()
                records[index]['measured']['queries'][0][field] = replacement
                with self.subTest(entry=index, field=field), self.assertRaises(ValueError):
                    analysis.collect_entries(records)

    def test_equal_bool_int_counter_corruption_is_not_hidden_by_identity_equality(self):
        records = fixture()
        records[-1]['measured']['queries'][0]['sql_workload']['history_rows_inserted'] = True
        with self.assertRaises(ValueError):
            analysis.collect_entries(records)
        records = fixture()
        records[-1]['measured']['queries'][0]['sql_workload']['fraction_fallback'] = 0
        with self.assertRaises(ValueError):
            analysis.collect_entries(records)

    def test_bad_saved_timing_accounting_is_not_accepted_as_prior_evidence(self):
        records = fixture()
        records[-1]['accounting']['tail_commit_seconds'] += .5
        with self.assertRaisesRegex(ValueError, 'tail commit'):
            analysis.collect_entries(records)

    def test_cli_rejects_experiment_mode_before_taking_lock(self):
        with patch('sys.argv', ['workloads', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.saved.v48.entry, 'exclusive') as exclusive:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            exclusive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
