"""Artificial position deviations only; no saved positions or runs are read."""
from copy import deepcopy
from math import nextafter
import sys
import unittest

from scripts.retailrocket_session_knn_segments_v57 import analyze_segments


def segment_fixture(overrides=None, default=0):
    """Return a fresh artificial 48-position deviation dictionary."""
    return {position: (overrides or {}).get(position, default) for position in range(1, 49)}


class SegmentTests(unittest.TestCase):
    def test_block_counts_densities_and_direction_shares_conserve_each_view(self):
        block_values = (1, -2, 0, .001, -.001, .002)
        row = analyze_segments({position: block_values[(position - 1) // 8] for position in range(1, 49)})
        all48, other46 = row['views']['all48'], row['views']['other46']
        self.assertEqual(all48['modes']['raw']['counts'], dict(above=24, neutral=8, below=16))
        self.assertEqual(other46['modes']['raw']['counts'], dict(above=23, neutral=8, below=15))
        self.assertEqual(all48['modes']['over_1ms']['counts'], dict(above=16, neutral=24, below=8))
        self.assertEqual(other46['modes']['over_1ms']['counts'], dict(above=16, neutral=22, below=8))
        self.assertEqual(all48['blocks'][0]['modes']['raw']['shares']['above'], 1 / 3)
        self.assertEqual(other46['blocks'][3]['count'], 7)
        self.assertEqual(other46['blocks'][4]['count'], 7)
        self.assertEqual(other46['blocks'][3]['modes']['raw']['shares']['above'], 7 / 23)
        self.assertEqual(other46['blocks'][4]['modes']['raw']['shares']['below'], 7 / 15)
        for mode in ('raw', 'over_1ms'):
            for direction in ('above', 'neutral', 'below'):
                target_count = sum(item['is_target'] and item[mode + '_direction'] == direction for item in row['positions'])
                self.assertEqual(all48['modes'][mode]['counts'][direction], other46['modes'][mode]['counts'][direction] + target_count)
        for view in row['views'].values():
            self.assertEqual(sum(block['count'] for block in view['blocks']), view['count'])
            for mode in ('raw', 'over_1ms'):
                totals = view['modes'][mode]['counts']
                self.assertEqual(sum(totals.values()), view['count'])
                for direction in ('above', 'neutral', 'below'):
                    self.assertEqual(sum(block['modes'][mode]['counts'][direction] for block in view['blocks']), totals[direction])
                    self.assertAlmostEqual(sum(block['modes'][mode]['shares'][direction] for block in view['blocks']), 1)
                    if direction != 'neutral':
                        self.assertEqual(sum(run['length'] for run in view['modes'][mode]['runs'] if run['direction'] == direction), totals[direction])
                for block in view['blocks']:
                    self.assertAlmostEqual(sum(block['modes'][mode]['densities'].values()), 1)

    def test_seven_and_eight_position_density_denominators(self):
        row = analyze_segments(segment_fixture({25: 1, 26: 1, 32: 1, 33: -1, 34: -1}))
        for view_name, positive, negative, size in (('all48', 3, 2, 8), ('other46', 2, 1, 7)):
            view = row['views'][view_name]
            self.assertEqual(view['blocks'][3]['modes']['raw']['densities']['above'], positive / size)
            self.assertEqual(view['blocks'][4]['modes']['raw']['densities']['below'], negative / size)

    def test_all_zero_has_no_runs_and_absent_direction_shares_are_none(self):
        row = analyze_segments(segment_fixture())
        for name, view in row['views'].items():
            for mode in view['modes'].values():
                self.assertEqual(mode['runs'], [])
                self.assertEqual(mode['longest'], dict(above=dict(length=0, segments=[]), below=dict(length=0, segments=[])))
                self.assertEqual(mode['counts'], dict(above=0, neutral=view['count'], below=0))
                self.assertEqual(mode['sequence'], '0' * 48 if name == 'all48' else '0' * 31 + 'xx' + '0' * 15)
            for block in view['blocks']:
                for mode in block['modes'].values():
                    self.assertIsNone(mode['shares']['above'])
                    self.assertIsNone(mode['shares']['below'])
                    self.assertEqual(mode['shares']['neutral'], block['count'] / view['count'])

    def test_all_positive_and_all_negative_keep_cross_block_runs(self):
        for value, direction, symbol in ((1, 'above', '+'), (-1, 'below', '-')):
            with self.subTest(direction=direction):
                row = analyze_segments(segment_fixture(default=value))
                for mode in ('raw', 'over_1ms'):
                    all_mode = row['views']['all48']['modes'][mode]
                    self.assertEqual(all_mode['sequence'], symbol * 48)
                    self.assertEqual(all_mode['runs'], [dict(direction=direction, start=1, end=48, length=48)])
                    self.assertEqual(all_mode['longest'][direction], dict(length=48, segments=[dict(start=1, end=48, length=48)]))
                    other_mode = row['views']['other46']['modes'][mode]
                    self.assertEqual(other_mode['sequence'], symbol * 31 + 'xx' + symbol * 15)
                    self.assertEqual(other_mode['runs'], [dict(direction=direction, start=1, end=31, length=31),
                        dict(direction=direction, start=34, end=48, length=15)])

    def test_exact_thresholds_are_neutral_and_adjacent_float_outside_is_directional(self):
        row = analyze_segments(segment_fixture({1: .001, 2: -.001,
            3: nextafter(.001, float('inf')), 4: nextafter(-.001, -float('inf'))}))
        self.assertEqual(row['views']['all48']['modes']['raw']['sequence'][:4], '+-+-')
        self.assertEqual(row['views']['all48']['modes']['over_1ms']['sequence'][:4], '00+-')
        self.assertEqual(row['positions'][0]['raw_direction'], 'above')
        self.assertEqual(row['positions'][0]['over_1ms_direction'], 'neutral')

    def test_neutral_and_excluded_targets_break_runs_without_compressing_positions(self):
        row = analyze_segments(segment_fixture({position: 1 for position in range(30, 36)}))
        self.assertEqual(row['views']['all48']['modes']['raw']['runs'], [dict(direction='above', start=30, end=35, length=6)])
        expected = [dict(direction='above', start=30, end=31, length=2), dict(direction='above', start=34, end=35, length=2)]
        self.assertEqual(row['views']['other46']['modes']['raw']['runs'], expected)
        self.assertEqual(row['views']['other46']['modes']['raw']['longest']['above'], dict(length=2,
            segments=[dict(start=30, end=31, length=2), dict(start=34, end=35, length=2)]))
        neutral = analyze_segments(segment_fixture({30: 1, 31: 1, 33: 1, 34: 1}))
        self.assertEqual(neutral['views']['all48']['modes']['raw']['runs'], [dict(direction='above', start=30, end=31, length=2),
            dict(direction='above', start=33, end=34, length=2)])

    def test_block_boundary_does_not_cut_an_adjacent_run(self):
        row = analyze_segments(segment_fixture({7: -1, 8: -1, 9: -1, 10: -1}))
        for view in row['views'].values():
            self.assertEqual(view['modes']['raw']['runs'], [dict(direction='below', start=7, end=10, length=4)])
            self.assertEqual(view['blocks'][0]['modes']['raw']['counts']['below'], 2)
            self.assertEqual(view['blocks'][1]['modes']['raw']['counts']['below'], 2)

    def test_first_last_and_singleton_runs_are_retained_with_all_longest_ties(self):
        row = analyze_segments(segment_fixture({1: 1, 3: -1, 5: -1, 48: 1}))
        mode = row['views']['all48']['modes']['raw']
        self.assertEqual(mode['runs'], [dict(direction='above', start=1, end=1, length=1),
            dict(direction='below', start=3, end=3, length=1), dict(direction='below', start=5, end=5, length=1),
            dict(direction='above', start=48, end=48, length=1)])
        self.assertEqual(mode['longest']['above']['segments'], [dict(start=1, end=1, length=1), dict(start=48, end=48, length=1)])
        self.assertEqual(mode['longest']['below']['segments'], [dict(start=3, end=3, length=1), dict(start=5, end=5, length=1)])

    def test_runs_are_maximal_and_modes_are_independent(self):
        row = analyze_segments(segment_fixture({1: 1, 2: .0005, 3: 1, 4: -1, 5: -1, 7: 1}))
        modes = row['views']['all48']['modes']
        self.assertEqual(modes['raw']['runs'], [dict(direction='above', start=1, end=3, length=3),
            dict(direction='below', start=4, end=5, length=2), dict(direction='above', start=7, end=7, length=1)])
        self.assertEqual(modes['raw']['longest']['above']['length'], 3)
        self.assertEqual(modes['over_1ms']['longest']['above'], dict(length=1, segments=[
            dict(start=1, end=1, length=1), dict(start=3, end=3, length=1), dict(start=7, end=7, length=1)]))

    def test_excluded_targets_leave_block_summaries_and_positions_explicit(self):
        row = analyze_segments(segment_fixture({32: 100, 33: -100}))
        self.assertEqual(row['views']['all48']['excluded_positions'], [])
        self.assertEqual(row['views']['other46']['excluded_positions'], [32, 33])
        self.assertEqual(row['views']['all48']['blocks'][3]['delta_seconds'], dict(min=0, median=0, max=100))
        self.assertEqual(row['views']['all48']['blocks'][4]['delta_seconds'], dict(min=-100, median=0, max=0))
        for block in row['views']['other46']['blocks']:
            self.assertEqual(block['delta_seconds'], dict(min=0, median=0, max=0))
            self.assertNotIn('sum', block['delta_seconds'])
        self.assertEqual(len(row['positions']), 48)
        self.assertEqual([item['position'] for item in row['positions'] if item['is_target']], [32, 33])
        self.assertEqual(row['positions'][31], dict(position=32, delta_seconds=100, raw_direction='above',
            over_1ms_direction='above', is_target=True))

    def test_signed_medians_are_stable_for_large_values_and_odd_block_sizes(self):
        largest = sys.float_info.max
        for value in (largest, -largest):
            row = analyze_segments(segment_fixture(default=value))
            for view in row['views'].values():
                for block in view['blocks']:
                    self.assertEqual(block['delta_seconds'], dict(min=value, median=value, max=value))
        mixed = analyze_segments(segment_fixture({position: -largest if position <= 4 else largest for position in range(1, 9)}))
        self.assertEqual(mixed['views']['all48']['blocks'][0]['delta_seconds']['median'], 0)
        odd = analyze_segments(segment_fixture({position: position - 24 for position in range(25, 33)}))
        self.assertEqual(odd['views']['all48']['blocks'][3]['delta_seconds']['median'], 4.5)
        self.assertEqual(odd['views']['other46']['blocks'][3]['delta_seconds']['median'], 4)

    def test_invalid_schema_and_position_key_types_are_rejected(self):
        valid = segment_fixture()
        invalid = (None, [], {position: 0 for position in range(1, 48)}, valid | {49: 0},
                   {str(position): 0 for position in range(1, 49)},
                   {1.0 if position == 1 else position: 0 for position in range(1, 49)},
                   {True if position == 1 else position: 0 for position in range(1, 49)})
        for values in invalid:
            with self.subTest(kind=type(values)), self.assertRaises(ValueError):
                analyze_segments(values)

    def test_nonfinite_boolean_and_nonnumeric_values_are_rejected(self):
        for value in (True, False, float('nan'), float('inf'), -float('inf'), '1', None, 10**1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analyze_segments(segment_fixture({48: value}))

    def test_input_order_values_and_output_isolation_are_preserved(self):
        values = dict(reversed(list(segment_fixture({1: 1, 32: -1, 33: .001}).items())))
        before, order = deepcopy(values), list(values)
        row = analyze_segments(values)
        self.assertEqual(values, before)
        self.assertEqual(list(values), order)
        self.assertEqual([item['position'] for item in row['positions']], list(range(1, 49)))
        row['positions'][0]['delta_seconds'] = 99
        self.assertEqual(values, before)


if __name__ == '__main__':
    unittest.main()
