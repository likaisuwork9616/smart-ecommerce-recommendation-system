"""Artificial labelled markers only: no real clocks, models, SQL or runner."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_wall_cpu_layout_v63 import build_layout


def fixture():
    cohort = [dict(original_ordinal=100 + index * 2, key_sha256=f'{index + 1:064x}')
              for index in range(48)]
    markers = []

    def add(point, ordinal=None):
        identity = (dict(original_ordinal=None, key_sha256=None) if ordinal is None
                    else cohort[ordinal])
        markers.append(dict(boundary_id=f'b{len(markers)}', point=point,
                            subset_ordinal=ordinal, **identity))

    for point in ('setup_start', 'prefix_start', 'setup_end'):
        add(point)
    for index in range(48):
        for point in ('query_start', 'rank_start', 'ranking_start',
                      'history_and_temp_setup', 'sql_positive_overlaps',
                      'neighbor_pool_sha', 'exact_neighbor_selection',
                      'sql_selected_votes_and_accumulation', 'top_ten_and_zero_fill',
                      'prediction_output', 'rank_end', 'verification_end',
                      'append_start', 'append_end', 'query_end'):
            add(point, index)
    for point in ('tail_start', 'tail_end'):
        add(point)
    return markers, cohort


class LayoutTests(unittest.TestCase):
    def test_complete_counts_original_identity_and_setup_tail_scope(self):
        markers, cohort = fixture()
        result = build_layout(markers, cohort, completed=True)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['expected_marker_count'], 725)
        self.assertEqual(result['observed_marker_count'], 725)
        self.assertEqual(result['pair_marker_count'], 341)
        self.assertEqual(result['rank_marker_count'], 384)
        self.assertEqual(result['completed_query_count'], 48)
        self.assertIsNone(result['expected_next'])
        self.assertEqual(result['cohort'][31],
                         dict(original_ordinal=162, key_sha256=f'{32:064x}'))
        self.assertEqual(result['cohort'][32],
                         dict(original_ordinal=164, key_sha256=f'{33:064x}'))
        spans = {row['id']: row for row in result['spans']}
        self.assertEqual(len(spans), 578)
        self.assertEqual(spans['setup'], dict(id='setup', phase='setup',
                         parent=None, start='b0', end='b2'))
        self.assertEqual(spans['tail'], dict(id='tail', phase='tail',
                         parent=None, start='b723', end='b724'))
        self.assertEqual(spans['query:0:query']['start'], 'b3')
        self.assertEqual(spans['query:0:query']['end'], 'b17')
        self.assertEqual(spans['query:47:query']['start'], 'b708')
        self.assertEqual(spans['query:47:query']['end'], 'b722')

    def test_shared_rank_mark_ids_and_parent_layers_preserve_wrapper_gaps(self):
        markers, cohort = fixture()
        result = build_layout(markers, cohort, completed=True)
        spans = {row['id']: row for row in result['spans']}
        rank = spans['query:0:rank']
        marks = spans['query:0:rank_marks']
        self.assertEqual((rank['parent'], rank['start'], rank['end']),
                         ('query:0:verification', 'b4', 'b13'))
        self.assertEqual((marks['parent'], marks['start'], marks['end']),
                         ('query:0:rank', 'b5', 'b12'))
        children = [row for row in result['spans'] if row['parent'] == marks['id']]
        self.assertEqual(len(children), 7)
        self.assertEqual([(row['start'], row['end']) for row in children],
                         [(f'b{i}', f'b{i + 1}') for i in range(5, 12)])
        self.assertEqual(spans['query:0:append']['parent'], 'query:0:query')
        self.assertEqual(spans['query:0:verification']['parent'], 'query:0:query')
        self.assertTrue(all(set(row) == {'id', 'phase', 'parent', 'start', 'end'}
                            for row in result['spans']))

    def test_incomplete_valid_prefix_never_invents_spans_or_boundary_ids(self):
        markers, cohort = fixture()
        for count, completed_queries, next_point in (
                (0, 0, 'setup_start'), (3, 0, 'query_start'),
                (10, 0, 'sql_selected_votes_and_accumulation'),
                (18, 1, 'query_start'), (724, 48, 'tail_end')):
            with self.subTest(count=count):
                result = build_layout(markers[:count], cohort, completed=False)
                self.assertEqual(result['status'], 'incomplete')
                self.assertEqual(result['spans'], [])
                self.assertEqual(result['completed_query_count'], completed_queries)
                self.assertEqual(result['expected_next']['point'], next_point)
                self.assertEqual(result['observed_boundary_ids'],
                                 [f'b{i}' for i in range(count)])

    def test_all_markers_do_not_override_explicit_incomplete_status(self):
        markers, cohort = fixture()
        result = build_layout(markers, cohort, completed=False)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['spans'], [])
        self.assertIsNone(result['expected_next'])
        self.assertFalse(result['completed'])

    def test_completed_trace_requires_all_markers(self):
        markers, cohort = fixture()
        for count in (0, 3, 18, 724):
            with self.subTest(count=count), self.assertRaises(ValueError):
                build_layout(markers[:count], cohort, completed=True)

    def test_missing_reordered_extra_and_duplicate_boundaries_rejected(self):
        markers, cohort = fixture()
        cases = []
        missing = deepcopy(markers)
        del missing[7]
        cases.append(missing)
        reordered = deepcopy(markers)
        reordered[7], reordered[8] = reordered[8], reordered[7]
        cases.append(reordered)
        cases.append(markers + [dict(markers[-1], boundary_id='extra')])
        duplicate_id = deepcopy(markers)
        duplicate_id[8]['boundary_id'] = duplicate_id[7]['boundary_id']
        cases.append(duplicate_id)
        for index, changed in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                build_layout(changed, cohort, completed=True)

    def test_partial_trace_must_be_prefix_not_skipped_or_resumed(self):
        markers, cohort = fixture()
        cases = (markers[3:18], markers[:4] + markers[5:10], markers[:3] + markers[18:33])
        for changed in cases:
            with self.subTest(points=[x['point'] for x in changed]), self.assertRaises(ValueError):
                build_layout(changed, cohort, completed=False)
        with self.assertRaises(ValueError):
            build_layout(markers, cohort, completed=True, fresh=False)

    def test_query_ordinal_original_identity_and_hash_must_match_cohort(self):
        markers, cohort = fixture()
        for field, value in (('subset_ordinal', 1), ('subset_ordinal', False),
                             ('original_ordinal', 102), ('original_ordinal', True),
                             ('key_sha256', f'{2:064x}'), ('point', 'wrong')):
            changed = deepcopy(markers)
            changed[3][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build_layout(changed, cohort, completed=True)

    def test_nonquery_points_cannot_claim_query_identity(self):
        markers, cohort = fixture()
        for index in (0, 1, 2, 723, 724):
            changed = deepcopy(markers)
            changed[index].update(subset_ordinal=0, **cohort[0])
            with self.subTest(index=index), self.assertRaises(ValueError):
                build_layout(changed, cohort, completed=True)

    def test_cohort_requires_unique_fortyeight_identities_in_supplied_order(self):
        markers, cohort = fixture()
        cases = [cohort[:-1], cohort + [cohort[-1]], tuple(reversed(cohort))]
        for field, value in (('original_ordinal', 100), ('original_ordinal', True),
                             ('original_ordinal', -1), ('key_sha256', f'{1:064x}'),
                             ('key_sha256', 'a' * 63), ('key_sha256', 'A' * 64),
                             ('key_sha256', None)):
            changed = deepcopy(cohort)
            changed[1][field] = value
            cases.append(changed)
        extra = deepcopy(cohort)
        extra[0]['extra'] = 'unvalidated'
        cases.append(extra)
        for index, changed in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                build_layout(markers, changed, completed=True)

    def test_nonnumeric_cohort_order_is_preserved_when_trace_matches(self):
        markers, cohort = fixture()
        cohort[0], cohort[1] = cohort[1], cohort[0]
        for marker in markers:
            ordinal = marker['subset_ordinal']
            if ordinal is not None:
                marker.update(cohort[ordinal])
        result = build_layout(markers, cohort, completed=True)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([row['original_ordinal'] for row in result['cohort'][:2]],
                         [102, 100])

    def test_flags_and_marker_schema_use_strict_types(self):
        markers, cohort = fixture()
        for flag in (0, 1, None, 'true'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                build_layout(markers, cohort, completed=flag)
            with self.subTest(fresh=flag), self.assertRaises(ValueError):
                build_layout(markers, cohort, completed=True, fresh=flag)
        for field, value in (('boundary_id', ''), ('boundary_id', 1), ('boundary_id', ' b0'),
                             ('point', None), ('subset_ordinal', float('nan'))):
            changed = deepcopy(markers)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_layout(changed, cohort, completed=True)
        for delete in (False, True):
            changed = deepcopy(markers)
            if delete:
                del changed[0]['point']
            else:
                changed[0]['extra'] = 'not allowed'
            with self.subTest(delete=delete), self.assertRaises(ValueError):
                build_layout(changed, cohort, completed=True)
        with self.assertRaises(ValueError):
            build_layout(iter(markers), cohort, completed=True)

    def test_plans_are_detached_from_input_and_accept_explicit_tuples(self):
        markers, cohort = fixture()
        result = build_layout(tuple(markers), tuple(cohort), completed=True)
        markers[3]['boundary_id'] = 'mutated'
        cohort[0]['original_ordinal'] = 999
        query = next(row for row in result['spans'] if row['id'] == 'query:0:query')
        self.assertEqual(query['start'], 'b3')
        self.assertEqual(result['cohort'][0]['original_ordinal'], 100)


if __name__ == '__main__':
    unittest.main()
